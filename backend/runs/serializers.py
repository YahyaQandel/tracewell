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
