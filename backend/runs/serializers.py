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

    class Meta:
        model = Run
        fields = ['id', 'branch', 'commit_sha', 'uploaded_at', 'test_cases']
