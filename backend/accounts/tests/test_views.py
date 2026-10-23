from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class LoginTests(TestCase):
    def test_correct_credentials_log_in_and_start_a_session(self):
        User.objects.create_user(username='alice', password='correct-pw')

        response = self.client.post(
            reverse('login'),
            {'username': 'alice', 'password': 'correct-pw'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['username'], 'alice')
        self.assertIn('_auth_user_id', self.client.session)

    def test_wrong_password_is_rejected(self):
        User.objects.create_user(username='alice', password='correct-pw')

        response = self.client.post(
            reverse('login'),
            {'username': 'alice', 'password': 'wrong-pw'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_unknown_username_is_rejected(self):
        response = self.client.post(
            reverse('login'),
            {'username': 'nobody', 'password': 'anything'},
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 401)


class LogoutTests(TestCase):
    def test_logout_ends_the_session(self):
        user = User.objects.create_user(username='alice', password='pw')
        self.client.force_login(user)

        response = self.client.post(reverse('logout'))

        self.assertEqual(response.status_code, 204)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_a_protected_endpoint_rejects_requests_after_logout(self):
        user = User.objects.create_user(username='alice', password='pw')
        self.client.force_login(user)
        self.client.post(reverse('logout'))

        response = self.client.get(reverse('organization-list'))

        # DRF's SessionAuthentication has no WWW-Authenticate challenge
        # scheme (authenticate_header() returns None), so DRF downgrades
        # an unauthenticated request to 403 rather than 401 - verified
        # directly against rest_framework.views.APIView.permission_denied.
        self.assertEqual(response.status_code, 403)
