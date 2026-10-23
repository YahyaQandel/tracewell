from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from organizations.models import Organization, OrganizationMembership


def _membership_url(organization_id, membership_id):
    return reverse(
        'membership-detail', kwargs={'organization_id': organization_id, 'membership_id': membership_id},
    )


class ChangeMemberRoleTests(TestCase):
    def test_owner_can_change_another_members_role(self):
        owner = User.objects.create_user(username='owner', password='pw')
        member = User.objects.create_user(username='member', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        membership = OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(owner)

        response = self.client.patch(
            _membership_url(org.id, membership.id), {'role': 'admin'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        membership.refresh_from_db()
        self.assertEqual(membership.role, 'admin')

    def test_admin_cannot_change_roles(self):
        admin = User.objects.create_user(username='admin', password='pw')
        member = User.objects.create_user(username='member', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=admin, role='admin')
        membership = OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(admin)

        response = self.client.patch(
            _membership_url(org.id, membership.id), {'role': 'admin'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        membership.refresh_from_db()
        self.assertEqual(membership.role, 'member')

    def test_member_cannot_change_roles(self):
        member = User.objects.create_user(username='member', password='pw')
        other = User.objects.create_user(username='other', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=member, role='member')
        other_membership = OrganizationMembership.objects.create(organization=org, user=other, role='member')
        self.client.force_login(member)

        response = self.client.patch(
            _membership_url(org.id, other_membership.id), {'role': 'admin'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)

    def test_demoting_the_sole_owner_is_rejected(self):
        owner = User.objects.create_user(username='owner', password='pw')
        org = Organization.objects.create(name='Acme')
        membership = OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        self.client.force_login(owner)

        response = self.client.patch(
            _membership_url(org.id, membership.id), {'role': 'member'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        membership.refresh_from_db()
        self.assertEqual(membership.role, 'owner')

    def test_demoting_one_of_two_owners_succeeds(self):
        owner_a = User.objects.create_user(username='owner_a', password='pw')
        owner_b = User.objects.create_user(username='owner_b', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner_a, role='owner')
        membership_b = OrganizationMembership.objects.create(organization=org, user=owner_b, role='owner')
        self.client.force_login(owner_a)

        response = self.client.patch(
            _membership_url(org.id, membership_b.id), {'role': 'member'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        membership_b.refresh_from_db()
        self.assertEqual(membership_b.role, 'member')

    def test_invalid_role_value_is_rejected(self):
        owner = User.objects.create_user(username='owner', password='pw')
        member = User.objects.create_user(username='member', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        membership = OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(owner)

        response = self.client.patch(
            _membership_url(org.id, membership.id), {'role': 'superadmin'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)


class RemoveMemberTests(TestCase):
    def test_owner_can_remove_a_member(self):
        owner = User.objects.create_user(username='owner', password='pw')
        member = User.objects.create_user(username='member', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        membership = OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(owner)

        response = self.client.delete(_membership_url(org.id, membership.id))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(OrganizationMembership.objects.filter(id=membership.id).exists())

    def test_admin_cannot_remove_members(self):
        admin = User.objects.create_user(username='admin', password='pw')
        member = User.objects.create_user(username='member', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=admin, role='admin')
        membership = OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(admin)

        response = self.client.delete(_membership_url(org.id, membership.id))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(OrganizationMembership.objects.filter(id=membership.id).exists())

    def test_removing_the_sole_owner_is_rejected(self):
        owner = User.objects.create_user(username='owner', password='pw')
        org = Organization.objects.create(name='Acme')
        membership = OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        self.client.force_login(owner)

        response = self.client.delete(_membership_url(org.id, membership.id))

        self.assertEqual(response.status_code, 400)
        self.assertTrue(OrganizationMembership.objects.filter(id=membership.id).exists())

    def test_removing_one_of_two_owners_succeeds(self):
        owner_a = User.objects.create_user(username='owner_a', password='pw')
        owner_b = User.objects.create_user(username='owner_b', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=owner_a, role='owner')
        membership_b = OrganizationMembership.objects.create(organization=org, user=owner_b, role='owner')
        self.client.force_login(owner_a)

        response = self.client.delete(_membership_url(org.id, membership_b.id))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(OrganizationMembership.objects.filter(id=membership_b.id).exists())

    def test_cross_org_membership_id_gets_404(self):
        owner = User.objects.create_user(username='owner', password='pw')
        other_member = User.objects.create_user(username='other', password='pw')
        org = Organization.objects.create(name='Acme')
        other_org = Organization.objects.create(name='Other Co')
        OrganizationMembership.objects.create(organization=org, user=owner, role='owner')
        other_membership = OrganizationMembership.objects.create(
            organization=other_org, user=other_member, role='member',
        )
        self.client.force_login(owner)

        response = self.client.delete(_membership_url(org.id, other_membership.id))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(OrganizationMembership.objects.filter(id=other_membership.id).exists())
