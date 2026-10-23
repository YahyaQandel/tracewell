from django.conf import settings
from rest_framework import serializers

from runs.models import Attachment, Attempt, Run, TestCase


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ['id', 'name', 'content_type', 'file']


class AttemptSerializer(serializers.ModelSerializer):
    attachments = AttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Attempt
        fields = ['id', 'attempt_number', 'status', 'duration_ms', 'attachments']


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
        # Precedence per spec.md: failed > flaky > passed. A run with
        # both failed and flaky test cases shows "failed" - failed is
        # the more severe signal and must not be masked by flaky also
        # being present. Never "running" - no upload model in this
        # codebase today creates a Run before it's fully complete (TW-2's
        # atomic-creation guarantee), so there is nothing to derive a
        # "running" status from. See spec.md gap 1.
        if run.failed_count > 0:
            return 'failed'
        if run.flaky_count > 0:
            return 'flaky'
        return 'passed'
