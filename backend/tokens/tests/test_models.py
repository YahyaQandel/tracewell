from django.db import IntegrityError
from django.test import TestCase

from organizations.models import Organization
from projects.models import Project
from tokens.models import ApiToken, RAW_TOKEN_PREFIX, generate_raw_token, hash_token


def _make_project():
    org = Organization.objects.create(name='Acme')
    return Project.objects.create(organization=org, name='Widgets', slug='widgets')


class GenerateRawTokenTests(TestCase):
    def test_starts_with_the_display_prefix(self):
        raw = generate_raw_token()
        self.assertTrue(raw.startswith(RAW_TOKEN_PREFIX))

    def test_two_calls_produce_different_values(self):
        self.assertNotEqual(generate_raw_token(), generate_raw_token())


class HashTokenTests(TestCase):
    def test_is_deterministic(self):
        raw = generate_raw_token()
        self.assertEqual(hash_token(raw), hash_token(raw))

    def test_different_tokens_hash_differently(self):
        self.assertNotEqual(hash_token(generate_raw_token()), hash_token(generate_raw_token()))


class ApiTokenModelTests(TestCase):
    def test_token_hash_must_be_unique(self):
        project = _make_project()
        ApiToken.objects.create(
            project=project, name='CI', token_hash='a' * 64,
            display_prefix='tw_live_abcd', display_suffix='wxyz',
        )
        with self.assertRaises(IntegrityError):
            ApiToken.objects.create(
                project=project, name='CI 2', token_hash='a' * 64,
                display_prefix='tw_live_abcd', display_suffix='wxyz',
            )

    def test_masked_display_format(self):
        token = ApiToken(display_prefix='tw_live_abcd', display_suffix='wxyz')
        self.assertEqual(token.masked_display(), 'tw_live_abcd••••••••wxyz')

    def test_revoked_tokens_are_excluded_from_active_lookup(self):
        from django.utils import timezone

        project = _make_project()
        active = ApiToken.objects.create(
            project=project, name='active', token_hash='b' * 64,
            display_prefix='tw_live_bbbb', display_suffix='bbbb',
        )
        revoked = ApiToken.objects.create(
            project=project, name='revoked', token_hash='c' * 64,
            display_prefix='tw_live_cccc', display_suffix='cccc',
            revoked_at=timezone.now(),
        )

        active_tokens = ApiToken.objects.filter(project=project, revoked_at__isnull=True)

        self.assertIn(active, active_tokens)
        self.assertNotIn(revoked, active_tokens)
