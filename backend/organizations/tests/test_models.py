from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from organizations.models import Organization, OrganizationMembership


class OrganizationMembershipTests(TestCase):
    def test_unique_membership_per_user_per_org(self):
        user = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=user, role='owner')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OrganizationMembership.objects.create(organization=org, user=user, role='member')

    def test_two_organizations_can_share_a_name(self):
        Organization.objects.create(name='Acme')
        Organization.objects.create(name='Acme')
        self.assertEqual(Organization.objects.filter(name='Acme').count(), 2)

    def test_organizations_ordered_by_created_at(self):
        first = Organization.objects.create(name='First')
        second = Organization.objects.create(name='Second')
        self.assertEqual(list(Organization.objects.all()), [first, second])
