import uuid

from django.db import models


def attachment_upload_path(instance, filename):
    run_id = instance.attempt.test_case.run_id
    return f'runs/{run_id}/{instance.id}-{filename}'


class Run(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.CharField(max_length=255, null=True, blank=True)
    commit_sha = models.CharField(max_length=40, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)


class TestCase(models.Model):
    OUTCOME_CHOICES = [
        ('passed', 'passed'),
        ('failed', 'failed'),
        ('skipped', 'skipped'),
        ('flaky', 'flaky'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(Run, related_name='test_cases', on_delete=models.CASCADE)
    title = models.CharField(max_length=1024)
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES)


class Attempt(models.Model):
    STATUS_CHOICES = [
        ('passed', 'passed'),
        ('failed', 'failed'),
        ('timedOut', 'timedOut'),
        ('skipped', 'skipped'),
        ('interrupted', 'interrupted'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    test_case = models.ForeignKey(TestCase, related_name='attempts', on_delete=models.CASCADE)
    attempt_number = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    duration_ms = models.PositiveIntegerField()


class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(Attempt, related_name='attachments', on_delete=models.CASCADE)
    name = models.CharField(max_length=512)
    content_type = models.CharField(max_length=255)
    file = models.FileField(upload_to=attachment_upload_path)
