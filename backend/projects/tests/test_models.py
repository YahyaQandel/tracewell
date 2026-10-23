from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from organizations.models import Organization
from projects.models import Project


class ProjectModelTests(TestCase):
    def test_unique_slug_per_organization(self):
        org = Organization.objects.create(name='Acme')
        Project.objects.create(organization=org, name='Frontend', slug='frontend')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Project.objects.create(organization=org, name='Frontend Again', slug='frontend')

    def test_same_slug_allowed_in_different_organizations(self):
        org_a = Organization.objects.create(name='Acme')
        org_b = Organization.objects.create(name='Globex')

        Project.objects.create(organization=org_a, name='Frontend', slug='frontend')
        Project.objects.create(organization=org_b, name='Frontend', slug='frontend')

        self.assertEqual(Project.objects.filter(slug='frontend').count(), 2)

    def test_projects_ordered_by_created_at(self):
        org = Organization.objects.create(name='Acme')
        first = Project.objects.create(organization=org, name='First', slug='first')
        second = Project.objects.create(organization=org, name='Second', slug='second')
        self.assertEqual(list(Project.objects.all()), [first, second])
