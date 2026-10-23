import secrets
import uuid

from django.conf import settings
from django.db import models

from organizations.models import Organization


class Invitation(models.Model):
    STATUS_CHOICES = [
        ('pending', 'pending'),
        ('accepted', 'accepted'),
        ('revoked', 'revoked'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, related_name='invitations', on_delete=models.CASCADE)
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=[('admin', 'admin'), ('member', 'member')])
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='sent_invitations', on_delete=models.CASCADE)
    token = models.CharField(max_length=64, unique=True, default=secrets.token_urlsafe)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']
