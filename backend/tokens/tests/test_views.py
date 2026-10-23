from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from organizations.models import Organization, OrganizationMembership
from projects.models import Project
from tokens.models import ApiToken, generate_raw_token, hash_token


def _token_list_url(project_id):
    return reverse('token-list', kwargs={'project_id': project_id})


def _token_revoke_url(project_id, token_id):
    return reverse('token-revoke', kwargs={'project_id': project_id, 'token_id': token_id})


def _make_org_project_and_member():
    member = User.objects.create_user(username='member', password='pw')
    org = Organization.objects.create(name='Acme')
    OrganizationMembership.objects.create(organization=org, user=member, role='member')
    project = Project.objects.create(organization=org, name='Widgets', slug='widgets')
    return member, org, project


class TokenListTests(TestCase):
    def test_unauthenticated_request_gets_403_not_404(self):
        _, _, project = _make_org_project_and_member()
        response = self.client.get(_token_list_url(project.id))
        self.assertEqual(response.status_code, 403)

    def test_non_member_gets_404_not_403(self):
        outsider = User.objects.create_user(username='outsider', password='pw')
        _, _, project = _make_org_project_and_member()
        self.client.force_login(outsider)

        response = self.client.get(_token_list_url(project.id))

        self.assertEqual(response.status_code, 404)

    def test_nonexistent_project_also_gets_404(self):
        member, _, _ = _make_org_project_and_member()
        self.client.force_login(member)
        import uuid

        response = self.client.get(_token_list_url(uuid.uuid4()))

        self.assertEqual(response.status_code, 404)

    def test_member_sees_only_active_tokens(self):
        member, _, project = _make_org_project_and_member()
        self.client.force_login(member)
        active = ApiToken.objects.create(
            project=project, name='active', token_hash='a' * 64,
            display_prefix='tw_live_aaaa', display_suffix='aaaa',
        )
        from django.utils import timezone

        ApiToken.objects.create(
            project=project, name='revoked', token_hash='b' * 64,
            display_prefix='tw_live_bbbb', display_suffix='bbbb',
            revoked_at=timezone.now(),
        )

        response = self.client.get(_token_list_url(project.id))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['id'], str(active.id))

    def test_list_never_exposes_the_raw_token_or_hash(self):
        member, _, project = _make_org_project_and_member()
        self.client.force_login(member)
        ApiToken.objects.create(
            project=project, name='CI', token_hash='c' * 64,
            display_prefix='tw_live_cccc', display_suffix='cccc',
        )

        response = self.client.get(_token_list_url(project.id))

        body_text = response.content.decode()
        self.assertNotIn('c' * 64, body_text)
        self.assertIn('masked_display', body_text)

    def test_cross_project_isolation(self):
        member, org, project_a = _make_org_project_and_member()
        project_b = Project.objects.create(organization=org, name='Other', slug='other')
        ApiToken.objects.create(
            project=project_b, name='b-token', token_hash='d' * 64,
            display_prefix='tw_live_dddd', display_suffix='dddd',
        )
        self.client.force_login(member)

        response = self.client.get(_token_list_url(project_a.id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])


class CreateTokenTests(TestCase):
    def test_member_can_create_a_token(self):
        member, _, project = _make_org_project_and_member()
        self.client.force_login(member)

        response = self.client.post(
            _token_list_url(project.id), {'name': 'CI token'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(ApiToken.objects.count(), 1)
        token = ApiToken.objects.get()
        self.assertEqual(token.name, 'CI token')
        self.assertEqual(token.created_by, member)

    def test_response_includes_the_full_raw_token_exactly_once(self):
        member, _, project = _make_org_project_and_member()
        self.client.force_login(member)

        response = self.client.post(
            _token_list_url(project.id), {'name': 'CI token'}, content_type='application/json',
        )

        body = response.json()
        self.assertIn('token', body)
        raw_token = body['token']
        self.assertTrue(raw_token.startswith('tw_live_'))

        token = ApiToken.objects.get()
        self.assertEqual(token.token_hash, hash_token(raw_token))

        # A subsequent list call never exposes the raw value again.
        list_response = self.client.get(_token_list_url(project.id))
        self.assertNotIn(raw_token, list_response.content.decode())

    def test_empty_name_is_rejected_and_creates_nothing(self):
        member, _, project = _make_org_project_and_member()
        self.client.force_login(member)

        response = self.client.post(
            _token_list_url(project.id), {'name': ''}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(ApiToken.objects.count(), 0)

    def test_create_requires_project_membership(self):
        outsider = User.objects.create_user(username='outsider', password='pw')
        _, _, project = _make_org_project_and_member()
        self.client.force_login(outsider)

        response = self.client.post(
            _token_list_url(project.id), {'name': 'CI'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(ApiToken.objects.count(), 0)


class RevokeTokenTests(TestCase):
    def test_member_can_revoke_a_token(self):
        member, _, project = _make_org_project_and_member()
        token = ApiToken.objects.create(
            project=project, name='CI', token_hash='e' * 64,
            display_prefix='tw_live_eeee', display_suffix='eeee',
        )
        self.client.force_login(member)

        response = self.client.post(_token_revoke_url(project.id, token.id))

        self.assertEqual(response.status_code, 204)
        token.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)

    def test_revoked_token_no_longer_appears_in_the_active_list(self):
        member, _, project = _make_org_project_and_member()
        token = ApiToken.objects.create(
            project=project, name='CI', token_hash='f' * 64,
            display_prefix='tw_live_ffff', display_suffix='ffff',
        )
        self.client.force_login(member)
        self.client.post(_token_revoke_url(project.id, token.id))

        response = self.client.get(_token_list_url(project.id))

        self.assertEqual(response.json(), [])

    def test_revoking_an_already_revoked_token_404s(self):
        member, _, project = _make_org_project_and_member()
        from django.utils import timezone

        token = ApiToken.objects.create(
            project=project, name='CI', token_hash='g' * 64,
            display_prefix='tw_live_gggg', display_suffix='gggg',
            revoked_at=timezone.now(),
        )
        self.client.force_login(member)

        response = self.client.post(_token_revoke_url(project.id, token.id))

        self.assertEqual(response.status_code, 404)

    def test_revoked_token_immediately_stops_authenticating_uploads(self):
        member, _, project = _make_org_project_and_member()
        self.client.force_login(member)
        raw_token = generate_raw_token()
        token = ApiToken.objects.create(
            project=project, name='CI', token_hash=hash_token(raw_token),
            display_prefix=raw_token[:12], display_suffix=raw_token[-4:],
        )

        revoke_response = self.client.post(_token_revoke_url(project.id, token.id))
        self.assertEqual(revoke_response.status_code, 204)

        upload_response = self.client.post(
            reverse('runs:upload'),
            data={'report': '{"tests": []}', 'manifest': '[]'},
            format='multipart',
            headers={'Authorization': f'Bearer {raw_token}'},
        )
        self.assertEqual(upload_response.status_code, 401)

    def test_revoke_requires_project_membership(self):
        outsider = User.objects.create_user(username='outsider', password='pw')
        _, _, project = _make_org_project_and_member()
        token = ApiToken.objects.create(
            project=project, name='CI', token_hash='h' * 64,
            display_prefix='tw_live_hhhh', display_suffix='hhhh',
        )
        self.client.force_login(outsider)

        response = self.client.post(_token_revoke_url(project.id, token.id))

        self.assertEqual(response.status_code, 404)
        token.refresh_from_db()
        self.assertIsNone(token.revoked_at)
