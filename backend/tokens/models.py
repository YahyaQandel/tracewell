import hashlib
import secrets
import uuid

from django.conf import settings
from django.db import models

from projects.models import Project

RAW_TOKEN_PREFIX = 'tw_live_'


def generate_raw_token():
    return RAW_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


class ApiToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, related_name='api_tokens', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name='created_tokens',
        on_delete=models.SET_NULL, null=True,
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    display_prefix = models.CharField(max_length=16)
    display_suffix = models.CharField(max_length=4)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def masked_display(self):
        return f'{self.display_prefix}{"•" * 8}{self.display_suffix}'
