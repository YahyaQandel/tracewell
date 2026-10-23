from django.conf import settings
from rest_framework import serializers

from runs.models import Attachment, Attempt, Run, TestCase, status_for


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ['id', 'name', 'content_type', 'file']


class AttemptSerializer(serializers.ModelSerializer):
    attachments = AttachmentSerializer(many=True, read_only=True)
    error = serializers.SerializerMethodField()

    class Meta:
        model = Attempt
        fields = ['id', 'attempt_number', 'status', 'duration_ms', 'error', 'attachments']

    def get_error(self, attempt):
        # null for passed/skipped (nothing to show) - a non-null object
        # with all-null inner fields for failed/timedOut (something to
        # show, just not populated yet - see #51). Branches on status,
        # not on whether error_message happens to be set, since status
        # is the actual semantic signal and nothing enforces the two
        # staying in sync at the DB layer.
        if attempt.status not in ('failed', 'timedOut'):
            return None
        return {
            'message': attempt.error_message,
            'stack': attempt.error_stack,
            'file': attempt.error_file,
            'line': attempt.error_line,
        }


class TestCaseSerializer(serializers.ModelSerializer):
    attempts = AttemptSerializer(many=True, read_only=True)

    class Meta:
        model = TestCase
        fields = ['id', 'title', 'outcome', 'attempts']


class RunSerializer(serializers.ModelSerializer):
    test_cases = TestCaseSerializer(many=True, read_only=True)
    url = serializers.SerializerMethodField()

    class Meta:
        model = Run
        fields = ['id', 'url', 'branch', 'commit_sha', 'uploaded_at', 'test_cases']

    def get_url(self, run):
        # cli/src/upload/httpClient.ts's classifyResponse reads this field
        # and prints it to the user on every successful upload - the
        # frontend dashboard isn't built yet, but the URL it will resolve
        # to is already a fixed shape (/runs/<id>), so emit it now rather
        # than leaving every upload's printed URL blank.
        return f'{settings.FRONTEND_BASE_URL.rstrip("/")}/runs/{run.id}'


class RunListSerializer(serializers.Serializer):
    """Run summary row for GET /api/projects/<project_id>/runs/ - see
    design.md. passed_count/failed_count/flaky_count/skipped_count/
    duration_ms are plain IntegerFields (not SerializerMethodField)
    because the view's annotate() already attaches them to each run
    object; DRF's default attribute lookup finds them directly. Only
    status is derived, from the other annotated counts.
    """

    id = serializers.UUIDField()
    branch = serializers.CharField(allow_null=True)
    commit_sha = serializers.CharField(allow_null=True)
    status = serializers.SerializerMethodField()
    passed_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    flaky_count = serializers.IntegerField()
    skipped_count = serializers.IntegerField()
    duration_ms = serializers.IntegerField()
    uploaded_at = serializers.DateTimeField()

    def get_status(self, run):
        # Shared with RunListView's ?status= filter (TW-13) via
        # status_for() (runs/models.py) - one function, so the filter and
        # this displayed badge can never disagree about the same run's
        # status.
        return status_for(run)


class RunDetailSerializer(serializers.Serializer):
    """GET /api/runs/<run_id>/ response shape - see spec.md. Deliberately
    NOT RunSerializer (used by UploadRunView's POST response) - that one
    has no status/counts (the upload response doesn't need a badge) and
    nests TestCaseSerializer without ordering (insertion order is fine
    for a one-time upload echo, meaningless for a reader browsing a run
    days later - see get_test_cases below).

    No shard_count/title/author fields anywhere - that data doesn't
    exist (see spec.md gaps 1/2). Don't add these as null placeholders
    either; that would imply a future source that doesn't exist.
    """

    id = serializers.UUIDField()
    branch = serializers.CharField(allow_null=True)
    commit_sha = serializers.CharField(allow_null=True)
    status = serializers.SerializerMethodField()
    passed_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    flaky_count = serializers.IntegerField()
    skipped_count = serializers.IntegerField()
    duration_ms = serializers.IntegerField()
    uploaded_at = serializers.DateTimeField()
    test_cases = serializers.SerializerMethodField()

    def get_status(self, run):
        return status_for(run)

    def get_test_cases(self, run):
        # Flat list, ordered by title (gap 1: no file-grouping data
        # exists - title is the only deterministic, meaningful order
        # available; id/insertion order is UUID-random). prefetch_related
        # collapses the three-level nested serialization (test_cases ->
        # attempts -> attachments) to 3 queries total regardless of row
        # count - same N+1 discipline RunListView already applies to its
        # own aggregate counts, extended one level deeper here since this
        # view nests three levels, not zero.
        test_cases = run.test_cases.order_by('title').prefetch_related(
            'attempts__attachments',
        )
        return TestCaseSerializer(test_cases, many=True).data
