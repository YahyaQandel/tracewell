from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from invitations.models import Invitation
from organizations.models import Organization, OrganizationMembership


def _invitations_url(organization_id):
    return reverse('invitation-list', kwargs={'organization_id': organization_id})


def _revoke_url(organization_id, invitation_id):
    return reverse(
        'invitation-revoke', kwargs={'organization_id': organization_id, 'invitation_id': invitation_id},
    )


def _accept_url():
    return reverse('invitation-accept')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class CreateInvitationTests(TestCase):
    def test_owner_can_invite_a_member(self):
        owner = User.objects.create_user(username='owner', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        self.client.force_login(owner)

        response = self.client.post(
            _invitations_url(org.id),
            {'email': 'new@example.com', 'role': 'member'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        invitation = Invitation.objects.get()
        self.assertEqual(invitation.email, 'new@example.com')
        self.assertEqual(invitation.role, 'member')
        self.assertEqual(invitation.status, 'pending')
        self.assertEqual(invitation.invited_by, owner)

    def test_admin_can_invite_a_member(self):
        admin = User.objects.create_user(username='admin', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=admin, role='admin')
        self.client.force_login(admin)

        response = self.client.post(
            _invitations_url(org.id),
            {'email': 'new@example.com', 'role': 'member'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)

    def test_plain_member_cannot_invite(self):
        member = User.objects.create_user(username='member', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(member)

        response = self.client.post(
            _invitations_url(org.id),
            {'email': 'new@example.com', 'role': 'member'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Invitation.objects.count(), 0)

    def test_non_member_gets_404(self):
        outsider = User.objects.create_user(username='outsider', password='pw')
        org = Organization.objects.create(name='Acme')
        self.client.force_login(outsider)

        response = self.client.post(
            _invitations_url(org.id),
            {'email': 'new@example.com', 'role': 'member'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)

    def test_inviting_an_existing_member_is_rejected(self):
        owner = User.objects.create_user(username='owner', password='pw')
        existing = User.objects.create_user(username='existing', password='pw', email='existing@example.com')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        OrganizationMembership.objects.create(organization=org, user=existing, role='member')
        self.client.force_login(owner)

        response = self.client.post(
            _invitations_url(org.id),
            {'email': 'existing@example.com', 'role': 'member'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Invitation.objects.count(), 0)

    def test_duplicate_pending_invitation_is_rejected(self):
        owner = User.objects.create_user(username='owner', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        self.client.force_login(owner)
        self.client.post(
            _invitations_url(org.id),
            {'email': 'new@example.com', 'role': 'member'},
            content_type='application/json',
        )

        response = self.client.post(
            _invitations_url(org.id),
            {'email': 'new@example.com', 'role': 'member'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Invitation.objects.count(), 1)

    def test_role_owner_is_rejected(self):
        owner = User.objects.create_user(username='owner', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        self.client.force_login(owner)

        response = self.client.post(
            _invitations_url(org.id),
            {'email': 'new@example.com', 'role': 'owner'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Invitation.objects.count(), 0)

    def test_sends_an_email(self):
        owner = User.objects.create_user(username='owner', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        self.client.force_login(owner)

        self.client.post(
            _invitations_url(org.id),
            {'email': 'new@example.com', 'role': 'member'},
            content_type='application/json',
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('new@example.com', mail.outbox[0].to)


class ListInvitationsTests(TestCase):
    def test_lists_only_pending_invitations(self):
        owner = User.objects.create_user(username='owner', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        inviter = owner
        pending = Invitation.objects.create(
            organization=org, email='pending@example.com', role='member', invited_by=inviter,
        )
        Invitation.objects.create(
            organization=org, email='revoked@example.com', role='member',
            invited_by=inviter, status='revoked',
        )
        self.client.force_login(owner)

        response = self.client.get(_invitations_url(org.id))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['id'], str(pending.id))

    def test_non_member_gets_404(self):
        outsider = User.objects.create_user(username='outsider', password='pw')
        org = Organization.objects.create(name='Acme')
        self.client.force_login(outsider)

        response = self.client.get(_invitations_url(org.id))

        self.assertEqual(response.status_code, 404)


class RevokeInvitationTests(TestCase):
    def test_owner_can_revoke(self):
        owner = User.objects.create_user(username='owner', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        invitation = Invitation.objects.create(
            organization=org, email='a@example.com', role='member', invited_by=owner,
        )
        self.client.force_login(owner)

        response = self.client.post(_revoke_url(org.id, invitation.id))

        self.assertEqual(response.status_code, 204)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, 'revoked')

    def test_admin_can_revoke(self):
        admin = User.objects.create_user(username='admin', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=admin, role='admin')
        invitation = Invitation.objects.create(
            organization=org, email='a@example.com', role='member', invited_by=admin,
        )
        self.client.force_login(admin)

        response = self.client.post(_revoke_url(org.id, invitation.id))

        self.assertEqual(response.status_code, 204)

    def test_plain_member_cannot_revoke(self):
        member = User.objects.create_user(username='member', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=member, role='member')
        invitation = Invitation.objects.create(
            organization=org, email='a@example.com', role='member', invited_by=member,
        )
        self.client.force_login(member)

        response = self.client.post(_revoke_url(org.id, invitation.id))

        self.assertEqual(response.status_code, 403)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, 'pending')

    def test_revoking_an_already_accepted_invitation_404s(self):
        owner = User.objects.create_user(username='owner', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        invitation = Invitation.objects.create(
            organization=org, email='a@example.com', role='member',
            invited_by=owner, status='accepted',
        )
        self.client.force_login(owner)

        response = self.client.post(_revoke_url(org.id, invitation.id))

        self.assertEqual(response.status_code, 404)


class AcceptInvitationTests(TestCase):
    def test_accepting_creates_membership_and_clears_pending(self):
        owner = User.objects.create_user(username='owner', password='pw')
        invitee = User.objects.create_user(username='invitee', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        invitation = Invitation.objects.create(
            organization=org, email='invitee@example.com', role='admin', invited_by=owner,
        )
        self.client.force_login(invitee)

        response = self.client.post(
            _accept_url(), {'token': invitation.token}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 204)
        membership = OrganizationMembership.objects.get(organization=org, user=invitee)
        self.assertEqual(membership.role, 'admin')
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, 'accepted')
        self.assertIsNotNone(invitation.accepted_at)

    def test_invalid_token_404s(self):
        invitee = User.objects.create_user(username='invitee', password='pw')
        self.client.force_login(invitee)

        response = self.client.post(
            _accept_url(), {'token': 'not-a-real-token'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)

    def test_reusing_an_already_accepted_token_404s(self):
        owner = User.objects.create_user(username='owner', password='pw')
        first_invitee = User.objects.create_user(username='first', password='pw')
        second_invitee = User.objects.create_user(username='second', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        invitation = Invitation.objects.create(
            organization=org, email='a@example.com', role='member', invited_by=owner,
        )
        self.client.force_login(first_invitee)
        self.client.post(_accept_url(), {'token': invitation.token}, content_type='application/json')

        self.client.force_login(second_invitee)
        response = self.client.post(
            _accept_url(), {'token': invitation.token}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)

    def test_accepting_when_already_a_member_returns_409(self):
        owner = User.objects.create_user(username='owner', password='pw')
        invitee = User.objects.create_user(username='invitee', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        OrganizationMembership.objects.create(organization=org, user=invitee, role='member')
        invitation = Invitation.objects.create(
            organization=org, email='invitee@example.com', role='admin', invited_by=owner,
        )
        self.client.force_login(invitee)

        response = self.client.post(
            _accept_url(), {'token': invitation.token}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 409)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, 'pending')
