from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from organizations.models import Organization, OrganizationMembership
from projects.models import Project


def _projects_url(organization_id):
    return reverse('project-list', kwargs={'organization_id': organization_id})


def _slug_preview_url(organization_id):
    return reverse('project-slug-preview', kwargs={'organization_id': organization_id})


class CreateProjectTests(TestCase):
    def test_unauthenticated_request_gets_403_not_404(self):
        org = Organization.objects.create(name='Acme')
        response = self.client.post(_projects_url(org.id), {'name': 'Frontend'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Project.objects.count(), 0)

    def test_non_member_gets_404_not_403(self):
        outsider = User.objects.create_user(username='outsider', password='pw')
        org = Organization.objects.create(name='Acme')
        self.client.force_login(outsider)

        response = self.client.post(
            _projects_url(org.id), {'name': 'Frontend'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Project.objects.count(), 0)

    def test_nonexistent_organization_also_gets_404(self):
        member = User.objects.create_user(username='alice', password='pw')
        self.client.force_login(member)

        response = self.client.post(
            _projects_url('00000000-0000-0000-0000-000000000000'),
            {'name': 'Frontend'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)

    def test_member_can_create_a_project(self):
        member = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(member)

        response = self.client.post(
            _projects_url(org.id), {'name': 'My Project!'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        project = Project.objects.get()
        self.assertEqual(project.organization, org)
        self.assertEqual(project.name, 'My Project!')
        self.assertEqual(project.slug, 'my-project')

    def test_response_includes_id_organization_name_and_slug(self):
        member = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=member, role='owner')
        self.client.force_login(member)

        response = self.client.post(
            _projects_url(org.id), {'name': 'My Project'}, content_type='application/json',
        )

        body = response.json()
        project = Project.objects.get()
        self.assertEqual(body['id'], str(project.id))
        self.assertEqual(body['organization'], str(org.id))
        self.assertEqual(body['name'], 'My Project')
        self.assertEqual(body['slug'], 'my-project')

    def test_empty_name_is_rejected_and_creates_nothing(self):
        member = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=member, role='owner')
        self.client.force_login(member)

        response = self.client.post(
            _projects_url(org.id), {'name': ''}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Project.objects.count(), 0)

    def test_missing_name_is_rejected_and_creates_nothing(self):
        member = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=member, role='owner')
        self.client.force_login(member)

        response = self.client.post(_projects_url(org.id), {}, content_type='application/json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Project.objects.count(), 0)

    def test_all_punctuation_name_slugifies_to_empty_and_is_rejected(self):
        member = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=member, role='owner')
        self.client.force_login(member)

        response = self.client.post(
            _projects_url(org.id), {'name': '!!!'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Project.objects.count(), 0)

    def test_slug_collision_within_same_organization_returns_409(self):
        member = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=member, role='owner')
        self.client.force_login(member)
        self.client.post(_projects_url(org.id), {'name': 'Frontend'}, content_type='application/json')

        response = self.client.post(
            _projects_url(org.id), {'name': 'Frontend'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(Project.objects.filter(slug='frontend', organization=org).count(), 1)

    def test_same_slug_in_different_organization_does_not_collide(self):
        member = User.objects.create_user(username='alice', password='pw')
        org_a = Organization.objects.create(name='Acme')
        org_b = Organization.objects.create(name='Globex')
        OrganizationMembership.objects.create(organization=org_a, user=member, role='owner')
        OrganizationMembership.objects.create(organization=org_b, user=member, role='owner')
        self.client.force_login(member)

        response_a = self.client.post(
            _projects_url(org_a.id), {'name': 'Frontend'}, content_type='application/json',
        )
        response_b = self.client.post(
            _projects_url(org_b.id), {'name': 'Frontend'}, content_type='application/json',
        )

        self.assertEqual(response_a.status_code, 201)
        self.assertEqual(response_b.status_code, 201)


class SlugPreviewTests(TestCase):
    def test_unauthenticated_get_gets_403_not_404(self):
        org = Organization.objects.create(name='Acme')
        response = self.client.get(_slug_preview_url(org.id), {'name': 'My Project'})
        self.assertEqual(response.status_code, 403)

    def test_requires_membership(self):
        outsider = User.objects.create_user(username='outsider', password='pw')
        org = Organization.objects.create(name='Acme')
        self.client.force_login(outsider)

        response = self.client.get(_slug_preview_url(org.id), {'name': 'My Project'})

        self.assertEqual(response.status_code, 404)

    def test_returns_derived_slug_without_creating_a_project(self):
        member = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(member)

        response = self.client.get(_slug_preview_url(org.id), {'name': 'My Project!'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'slug': 'my-project'})
        self.assertEqual(Project.objects.count(), 0)

    def test_empty_name_returns_400(self):
        member = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=member, role='member')
        self.client.force_login(member)

        response = self.client.get(_slug_preview_url(org.id), {'name': ''})

        self.assertEqual(response.status_code, 400)


class ListProjectsTests(TestCase):
    def test_unauthenticated_get_gets_403_not_404(self):
        org = Organization.objects.create(name='Acme')
        response = self.client.get(_projects_url(org.id))
        self.assertEqual(response.status_code, 403)

    def test_non_member_gets_404_not_403(self):
        outsider = User.objects.create_user(username='outsider', password='pw')
        org = Organization.objects.create(name='Acme')
        self.client.force_login(outsider)

        response = self.client.get(_projects_url(org.id))

        self.assertEqual(response.status_code, 404)

    def test_nonexistent_organization_also_gets_404(self):
        member = User.objects.create_user(username='alice', password='pw')
        self.client.force_login(member)

        response = self.client.get(_projects_url('00000000-0000-0000-0000-000000000000'))

        self.assertEqual(response.status_code, 404)

    def test_empty_organization_returns_200_with_empty_list(self):
        member = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=member, role='owner')
        self.client.force_login(member)

        response = self.client.get(_projects_url(org.id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_lists_all_projects_with_member_count_and_null_latest_run(self):
        alice = User.objects.create_user(username='alice', password='pw')
        bob = User.objects.create_user(username='bob', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=alice, role='owner')
        OrganizationMembership.objects.create(organization=org, user=bob, role='member')
        project_a = Project.objects.create(organization=org, name='Frontend', slug='frontend')
        project_b = Project.objects.create(organization=org, name='Backend', slug='backend')
        self.client.force_login(alice)

        response = self.client.get(_projects_url(org.id))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 2)
        by_slug = {entry['slug']: entry for entry in body}
        self.assertEqual(by_slug['frontend']['id'], str(project_a.id))
        self.assertEqual(by_slug['frontend']['name'], 'Frontend')
        self.assertEqual(by_slug['frontend']['member_count'], 2)
        self.assertIsNone(by_slug['frontend']['latest_run'])
        self.assertEqual(by_slug['backend']['member_count'], 2)
        self.assertIsNone(by_slug['backend']['latest_run'])

    def test_member_count_reflects_organization_not_other_organizations(self):
        alice = User.objects.create_user(username='alice', password='pw')
        bob = User.objects.create_user(username='bob', password='pw')
        org = Organization.objects.create(name='Acme')
        other_org = Organization.objects.create(name='Other Co')
        OrganizationMembership.objects.create(organization=org, user=alice, role='owner')
        OrganizationMembership.objects.create(organization=other_org, user=bob, role='owner')
        Project.objects.create(organization=org, name='Frontend', slug='frontend')
        self.client.force_login(alice)

        response = self.client.get(_projects_url(org.id))

        body = response.json()
        self.assertEqual(body[0]['member_count'], 1)

    def test_only_lists_projects_in_the_requested_organization(self):
        alice = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        other_org = Organization.objects.create(name='Other Co')
        OrganizationMembership.objects.create(organization=org, user=alice, role='owner')
        OrganizationMembership.objects.create(organization=other_org, user=alice, role='owner')
        Project.objects.create(organization=org, name='Frontend', slug='frontend')
        Project.objects.create(organization=other_org, name='Unrelated', slug='unrelated')
        self.client.force_login(alice)

        response = self.client.get(_projects_url(org.id))

        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['slug'], 'frontend')

    def test_latest_run_reflects_a_real_uploaded_run(self):
        # TW-26 closes #36: Run.project is now a real FK, so latest_run
        # should stop being hardcoded None once a run actually exists.
        from runs.models import Run

        alice = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=alice, role='owner')
        project = Project.objects.create(organization=org, name='Frontend', slug='frontend')
        older_run = Run.objects.create(project=project)
        newer_run = Run.objects.create(project=project)
        self.client.force_login(alice)

        response = self.client.get(_projects_url(org.id))

        body = response.json()
        self.assertEqual(body[0]['latest_run'], str(newer_run.id))

    def test_latest_run_handles_a_timestamp_tie_without_erroring(self):
        # Two runs sharing the exact same uploaded_at (SQLite's coarser
        # datetime resolution makes this realistic under fast concurrent
        # uploads) is a KNOWN, documented, not-yet-fixed determinism gap
        # (see the comment in projects/views.py's get()) - this test only
        # pins down that the endpoint still returns 200 with ONE of the
        # two tied runs as "latest" (not a 500, not both, not neither),
        # not which one. A '-id' tiebreaker was tried and reverted here:
        # Run.id is a random uuid4, not time-ordered, so asserting a
        # specific "newer" run would win was itself a ~50/50 coin flip
        # dressed up as a regression test - this was caught running the
        # full suite repeatedly (it failed about 1 run in 3), not from
        # reading the code alone.
        from unittest.mock import patch

        from django.utils import timezone
        from runs.models import Run

        alice = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=alice, role='owner')
        project = Project.objects.create(organization=org, name='Frontend', slug='frontend')
        fixed_time = timezone.now()
        with patch('django.utils.timezone.now', return_value=fixed_time):
            run_a = Run.objects.create(project=project)
            run_b = Run.objects.create(project=project)
        self.assertEqual(run_a.uploaded_at, run_b.uploaded_at)
        self.client.force_login(alice)

        response = self.client.get(_projects_url(org.id))

        self.assertEqual(response.status_code, 200)
        self.assertIn(response.json()[0]['latest_run'], {str(run_a.id), str(run_b.id)})

    def test_latest_run_does_not_leak_a_run_from_another_project(self):
        from runs.models import Run

        alice = User.objects.create_user(username='alice', password='pw')
        org = Organization.objects.create(name='Acme')
        OrganizationMembership.objects.create(organization=org, user=alice, role='owner')
        project_a = Project.objects.create(organization=org, name='Frontend', slug='frontend')
        project_b = Project.objects.create(organization=org, name='Backend', slug='backend')
        Run.objects.create(project=project_b)
        self.client.force_login(alice)

        response = self.client.get(_projects_url(org.id))

        by_slug = {entry['slug']: entry for entry in response.json()}
        self.assertIsNone(by_slug['frontend']['latest_run'])
        self.assertIsNotNone(by_slug['backend']['latest_run'])
