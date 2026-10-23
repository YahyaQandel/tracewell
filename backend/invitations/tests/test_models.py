from django.contrib.auth.models import User
from django.test import TestCase

from invitations.models import Invitation
from organizations.models import Organization


class InvitationModelTests(TestCase):
    def test_token_is_generated_and_unique_per_invitation(self):
        org = Organization.objects.create(name='Acme')
        inviter = User.objects.create_user(username='alice', password='pw')

        first = Invitation.objects.create(
            organization=org, email='a@example.com', role='member', invited_by=inviter,
        )
        second = Invitation.objects.create(
            organization=org, email='b@example.com', role='member', invited_by=inviter,
        )

        self.assertTrue(first.token)
        self.assertTrue(second.token)
        self.assertNotEqual(first.token, second.token)

    def test_status_defaults_to_pending(self):
        org = Organization.objects.create(name='Acme')
        inviter = User.objects.create_user(username='alice', password='pw')

        invitation = Invitation.objects.create(
            organization=org, email='a@example.com', role='member', invited_by=inviter,
        )

        self.assertEqual(invitation.status, 'pending')
        self.assertIsNone(invitation.accepted_at)
