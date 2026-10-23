from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from organizations.models import Organization, OrganizationMembership


class ListOrganizationsTests(TestCase):
    def test_requires_authentication(self):
        response = self.client.get(reverse('organization-list'))
        # DRF's SessionAuthentication has no WWW-Authenticate challenge
        # scheme, so an unauthenticated request is downgraded to 403
        # rather than 401 - verified against DRF's own
        # APIView.permission_denied source.
        self.assertEqual(response.status_code, 403)

    def test_empty_for_a_user_with_no_organizations(self):
        user = User.objects.create_user(username='alice', password='pw')
        self.client.force_login(user)

        response = self.client.get(reverse('organization-list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_lists_only_the_requesting_users_organizations_with_role(self):
        alice = User.objects.create_user(username='alice', password='pw')
        bob = User.objects.create_user(username='bob', password='pw')
        alice_org = Organization.objects.create(name='Alice Co')
        bob_org = Organization.objects.create(name='Bob Co')
        OrganizationMembership.objects.create(organization=alice_org, user=alice, role='owner')
        OrganizationMembership.objects.create(organization=bob_org, user=bob, role='owner')

        self.client.force_login(alice)
        response = self.client.get(reverse('organization-list'))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['name'], 'Alice Co')
        self.assertEqual(body[0]['role'], 'owner')

    def test_user_in_two_organizations_sees_both_with_correct_roles(self):
        alice = User.objects.create_user(username='alice', password='pw')
        owned = Organization.objects.create(name='Owned Co')
        joined = Organization.objects.create(name='Joined Co')
        OrganizationMembership.objects.create(organization=owned, user=alice, role='owner')
        OrganizationMembership.objects.create(organization=joined, user=alice, role='member')

        self.client.force_login(alice)
        response = self.client.get(reverse('organization-list'))

        body = response.json()
        self.assertEqual(len(body), 2)
        roles_by_name = {org['name']: org['role'] for org in body}
        self.assertEqual(roles_by_name, {'Owned Co': 'owner', 'Joined Co': 'member'})


class CreateOrganizationTests(TestCase):
    def test_requires_authentication(self):
        response = self.client.post(reverse('organization-list'), {'name': 'Acme'})
        # See ListOrganizationsTests.test_requires_authentication: DRF
        # downgrades unauthenticated SessionAuthentication requests to
        # 403, not 401.
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Organization.objects.count(), 0)

    def test_creates_organization_with_creator_as_owner(self):
        user = User.objects.create_user(username='alice', password='pw')
        self.client.force_login(user)

        response = self.client.post(
            reverse('organization-list'),
            {'name': 'Acme'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Organization.objects.count(), 1)
        org = Organization.objects.get()
        self.assertEqual(org.name, 'Acme')
        membership = OrganizationMembership.objects.get(organization=org, user=user)
        self.assertEqual(membership.role, 'owner')

    def test_response_includes_created_organization_id_and_name(self):
        user = User.objects.create_user(username='alice', password='pw')
        self.client.force_login(user)

        response = self.client.post(
            reverse('organization-list'),
            {'name': 'Acme'},
            content_type='application/json',
        )

        body = response.json()
        org = Organization.objects.get()
        self.assertEqual(body['id'], str(org.id))
        self.assertEqual(body['name'], 'Acme')
        self.assertEqual(body['role'], 'owner')

    def test_empty_name_is_rejected_and_creates_nothing(self):
        user = User.objects.create_user(username='alice', password='pw')
        self.client.force_login(user)

        response = self.client.post(
            reverse('organization-list'),
            {'name': ''},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Organization.objects.count(), 0)

    def test_missing_name_is_rejected_and_creates_nothing(self):
        user = User.objects.create_user(username='alice', password='pw')
        self.client.force_login(user)

        response = self.client.post(
            reverse('organization-list'),
            {},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Organization.objects.count(), 0)

    def test_empty_name_with_other_fields_present_is_still_rejected(self):
        # design.md's test plan asks for this explicitly: confirms the
        # 400 is from real name validation, not a lucky empty-body
        # short-circuit that happens to not notice other fields.
        user = User.objects.create_user(username='alice', password='pw')
        self.client.force_login(user)

        response = self.client.post(
            reverse('organization-list'),
            {'name': '', 'unexpected_field': 123},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Organization.objects.count(), 0)
