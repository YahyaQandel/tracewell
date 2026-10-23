import uuid

from django.db import models

from projects.models import Project


def attachment_upload_path(instance, filename):
    run_id = instance.attempt.test_case.run_id
    return f'runs/{run_id}/{instance.id}-{filename}'


class Run(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project, related_name='runs', on_delete=models.CASCADE,
        null=True, blank=True,
    )
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
    # Nullable until #51 (CLI parser never reads Playwright's errors[]
    # field today, see parseResult() in cli/src/report/parseReport.ts) -
    # every row is null until that fix ships real data. TextField (not
    # CharField) for message/stack since stack traces are unbounded.
    error_message = models.TextField(null=True, blank=True)
    error_stack = models.TextField(null=True, blank=True)
    error_file = models.CharField(max_length=1024, null=True, blank=True)
    error_line = models.PositiveIntegerField(null=True, blank=True)


class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt = models.ForeignKey(Attempt, related_name='attachments', on_delete=models.CASCADE)
    name = models.CharField(max_length=512)
    content_type = models.CharField(max_length=255)
    file = models.FileField(upload_to=attachment_upload_path)


def status_for(run):
    """Single source of truth for the failed > flaky > passed precedence
    on a Run annotated with failed_count/flaky_count (see RunListView's
    .annotate() in views.py) - called by both RunListView's ?status=
    filter and RunListSerializer.get_status(), so the filter can never
    disagree with the badge a run actually displays. Lives here (not in
    views.py or serializers.py) because both of those modules already
    import from this one - putting it in either would make the other
    import backwards. Never returns 'running' - no upload model in this
    codebase creates a Run before it's fully complete (TW-2's atomic-
    creation guarantee), so there's nothing to derive that from."""
    if run.failed_count > 0:
        return 'failed'
    if run.flaky_count > 0:
        return 'flaky'
    return 'passed'
