import json
import threading
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.db import connection

from organizations.models import Organization, OrganizationMembership
from projects.models import Project
from runs.models import Attachment, Attempt, Run, TestCase as TestCaseModel
from tokens.models import ApiToken, generate_raw_token, hash_token


def _make_project_and_token():
    org = Organization.objects.create(name='Acme')
    project = Project.objects.create(organization=org, name='Widgets', slug='widgets')
    raw_token = generate_raw_token()
    ApiToken.objects.create(
        project=project, name='CI', token_hash=hash_token(raw_token),
        display_prefix=raw_token[:12], display_suffix=raw_token[-4:],
    )
    return project, raw_token

VALID_REPORT = {
    'tests': [
        {
            'id': 'login works',
            'title': 'login works',
            'outcome': 'passed',
            'retries': [{'status': 'passed', 'duration': 120, 'attachments': []}],
            'attachments': [],
        },
        {
            'id': 'flaky test',
            'title': 'flaky test',
            'outcome': 'flaky',
            'retries': [
                {'status': 'failed', 'duration': 50, 'attachments': [{'name': 'trace.zip', 'contentType': 'application/zip'}]},
                {'status': 'passed', 'duration': 60, 'attachments': [{'name': 'screenshot.png', 'contentType': 'image/png'}]},
            ],
            'attachments': [{'name': 'screenshot.png', 'contentType': 'image/png'}],
        },
    ],
}

VALID_MANIFEST = [
    {'testId': 'flaky test', 'attachmentName': 'trace.zip', 'partName': 'attachment-0', 'retryIndex': 0},
    {'testId': 'flaky test', 'attachmentName': 'screenshot.png', 'partName': 'attachment-1', 'retryIndex': 1},
]


class UploadRunViewTests(TestCase):
    url = reverse('runs:upload')

    def setUp(self):
        self.project, self.raw_token = _make_project_and_token()

    def _post(self, report=VALID_REPORT, manifest=VALID_MANIFEST, attachments=None, extra=None, token=None):
        # Mirrors the real CLI exactly (buildMultipartRequest.ts /
        # httpClient.ts): every attachment is sent under the SAME literal
        # field name "attachment[]", in manifest order - never per-part
        # keys like "attachment-0". Django's test client supports repeated
        # field names via a list value under one key, same as a real
        # multipart request with repeated parts.
        data = {
            'report': json.dumps(report),
            'manifest': json.dumps(manifest),
        }
        if extra:
            data.update(extra)
        if attachments:
            data['attachment[]'] = attachments
        auth_token = self.raw_token if token is None else token
        headers = {'Authorization': f'Bearer {auth_token}'} if auth_token else {}
        return self.client.post(self.url, data=data, format='multipart', headers=headers)

    def test_valid_upload_creates_run_with_full_outcome_set(self):
        attachments = [
            SimpleUploadedFile('trace.zip', b'trace-bytes', content_type='application/zip'),
            SimpleUploadedFile('screenshot.png', b'png-bytes', content_type='image/png'),
        ]
        response = self._post(attachments=attachments)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Run.objects.count(), 1)
        run = Run.objects.get()
        self.assertEqual(run.test_cases.count(), 2)

        flaky = run.test_cases.get(title='flaky test')
        self.assertEqual(flaky.outcome, 'flaky')
        self.assertEqual(flaky.attempts.count(), 2)

        attempt_0 = flaky.attempts.get(attempt_number=1)
        self.assertEqual(attempt_0.status, 'failed')
        self.assertEqual(attempt_0.attachments.count(), 1)
        self.assertEqual(attempt_0.attachments.get().name, 'trace.zip')

        attempt_1 = flaky.attempts.get(attempt_number=2)
        self.assertEqual(attempt_1.status, 'passed')
        self.assertEqual(attempt_1.attachments.count(), 1)
        self.assertEqual(attempt_1.attachments.get().name, 'screenshot.png')

    def test_branch_and_commit_are_optional_and_nullable(self):
        response = self._post()
        self.assertEqual(response.status_code, 201, response.content)
        run = Run.objects.get()
        self.assertIsNone(run.branch)
        self.assertIsNone(run.commit_sha)

    def test_branch_and_commit_are_stored_when_sent(self):
        response = self._post(extra={'branch': 'main', 'commit': 'abc123'})
        self.assertEqual(response.status_code, 201, response.content)
        run = Run.objects.get()
        self.assertEqual(run.branch, 'main')
        self.assertEqual(run.commit_sha, 'abc123')

    def test_project_body_field_is_ignored_in_favor_of_the_authenticated_tokens_project(self):
        # TW-26: the authenticated token's own project determines the
        # run's project - a client-sent `project` string in the body is
        # never read for this purpose, no matter what it says. This is
        # strictly safer than trusting a client-supplied value.
        response = self._post(extra={'project': 'some-other-project-id-that-does-not-exist'})
        self.assertEqual(response.status_code, 201, response.content)
        run = Run.objects.get()
        self.assertEqual(run.project, self.project)

    def test_run_is_attached_to_the_authenticated_tokens_project(self):
        response = self._post()
        self.assertEqual(response.status_code, 201, response.content)
        run = Run.objects.get()
        self.assertEqual(run.project, self.project)

    def test_missing_authorization_header_is_rejected(self):
        response = self._post(token='')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(Run.objects.count(), 0)

    def test_malformed_authorization_header_is_rejected(self):
        response = self.client.post(
            self.url,
            data={'report': json.dumps(VALID_REPORT), 'manifest': json.dumps(VALID_MANIFEST)},
            format='multipart',
            headers={'Authorization': 'NotBearer something'},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(Run.objects.count(), 0)

    def test_unknown_token_is_rejected(self):
        response = self._post(token='tw_live_this-token-does-not-exist')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(Run.objects.count(), 0)

    def test_revoked_token_is_rejected(self):
        from django.utils import timezone

        token = ApiToken.objects.get(token_hash=hash_token(self.raw_token))
        token.revoked_at = timezone.now()
        token.save(update_fields=['revoked_at'])

        response = self._post()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(Run.objects.count(), 0)

    def test_successful_auth_updates_last_used_at(self):
        token = ApiToken.objects.get(token_hash=hash_token(self.raw_token))
        self.assertIsNone(token.last_used_at)

        response = self._post()

        self.assertEqual(response.status_code, 201, response.content)
        token.refresh_from_db()
        self.assertIsNotNone(token.last_used_at)

    def test_a_failed_upload_with_a_valid_token_still_updates_last_used_at(self):
        # "Used" means "authenticated," not "succeeded at creating a run"
        # - a malformed report still proves the token is live.
        token = ApiToken.objects.get(token_hash=hash_token(self.raw_token))
        self.assertIsNone(token.last_used_at)

        response = self.client.post(
            self.url,
            data={'report': 'not valid json{{{', 'manifest': '[]'},
            format='multipart',
            headers={'Authorization': f'Bearer {self.raw_token}'},
        )

        self.assertEqual(response.status_code, 400)
        token.refresh_from_db()
        self.assertIsNotNone(token.last_used_at)

    def test_last_used_at_update_failure_does_not_abort_the_upload(self):
        # Regression guard for a design-review-caught gap: a transient
        # failure updating last_used_at (e.g. SQLite contention) must
        # never block or roll back the run upload itself.
        from django.db.models.query import QuerySet

        with patch.object(QuerySet, 'update', side_effect=Exception('simulated database is busy')):
            response = self._post()

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Run.objects.count(), 1)

    def test_successful_response_includes_a_url_field(self):
        # cli/src/upload/httpClient.ts's classifyResponse reads `body.url`
        # on 201 and prints it to the user - a response missing this key
        # means every real upload prints a blank URL.
        response = self._post()
        self.assertEqual(response.status_code, 201, response.content)
        run = Run.objects.get()
        self.assertEqual(response.json()['url'], f'http://localhost:5173/runs/{run.id}')

    def test_malformed_json_report_returns_400_and_creates_nothing(self):
        response = self.client.post(
            self.url,
            data={'report': 'not valid json{{{', 'manifest': '[]'},
            format='multipart',
            headers={'Authorization': f'Bearer {self.raw_token}'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Run.objects.count(), 0)
        # cli/src/upload/httpClient.ts's classifyResponse reads
        # `body.message` on a 400, not DRF's conventional `detail` - using
        # the wrong key means the CLI always falls back to a generic
        # "malformed report" string and discards the real reason.
        self.assertIn('message', response.json())

    def test_missing_tests_array_returns_400_and_creates_nothing(self):
        response = self._post(report={'not_tests': []})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Run.objects.count(), 0)

    def test_manifest_referencing_unknown_test_returns_400_and_creates_nothing(self):
        bad_manifest = [{'testId': 'does not exist', 'attachmentName': 'x', 'partName': 'attachment-0', 'retryIndex': 0}]
        response = self._post(manifest=bad_manifest)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Run.objects.count(), 0)
        self.assertEqual(TestCaseModel.objects.count(), 0)
        self.assertEqual(Attempt.objects.count(), 0)

    def test_malformed_json_manifest_returns_400_and_creates_nothing(self):
        response = self.client.post(
            self.url,
            data={'report': json.dumps(VALID_REPORT), 'manifest': 'not valid json{{{'},
            format='multipart',
            headers={'Authorization': f'Bearer {self.raw_token}'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Run.objects.count(), 0)

    def test_empty_tests_array_is_valid(self):
        # Edge case: a Playwright run where every test was filtered out
        # (e.g. --grep matched nothing) still produces a valid, empty Run
        # - this is not the same as AC4's "malformed input", it's a
        # legitimate zero-test run.
        response = self._post(report={'tests': []}, manifest=[])
        self.assertEqual(response.status_code, 201, response.content)
        run = Run.objects.get()
        self.assertEqual(run.test_cases.count(), 0)

    def test_full_attempt_status_vocabulary_round_trips(self):
        # AC1 names the full attempt-level outcome set explicitly:
        # passed/failed/timedOut/skipped/interrupted. Only passed/failed
        # are exercised elsewhere in this suite - this proves the other
        # three survive parse -> persist -> serialize unchanged, not just
        # that the model/parser *accept* them as valid choices.
        report = {
            'tests': [
                {
                    'id': 'times out then is abandoned',
                    'title': 'times out then is abandoned',
                    'outcome': 'failed',
                    'retries': [
                        {'status': 'timedOut', 'duration': 30000, 'attachments': []},
                        {'status': 'interrupted', 'duration': 0, 'attachments': []},
                    ],
                    'attachments': [],
                },
                {
                    'id': 'skipped test',
                    'title': 'skipped test',
                    'outcome': 'skipped',
                    'retries': [
                        {'status': 'skipped', 'duration': 0, 'attachments': []},
                    ],
                    'attachments': [],
                },
            ],
        }
        response = self._post(report=report, manifest=[])
        self.assertEqual(response.status_code, 201, response.content)

        timeout_test = TestCaseModel.objects.get(title='times out then is abandoned')
        self.assertEqual(timeout_test.outcome, 'failed')
        statuses = list(timeout_test.attempts.order_by('attempt_number').values_list('status', flat=True))
        self.assertEqual(statuses, ['timedOut', 'interrupted'])

        skipped_test = TestCaseModel.objects.get(title='skipped test')
        self.assertEqual(skipped_test.outcome, 'skipped')
        self.assertEqual(skipped_test.attempts.get().status, 'skipped')

        # Round-trips through the serializer too, not just the DB.
        response_body = response.json()
        serialized_titles = {tc['title']: tc for tc in response_body['test_cases']}
        self.assertEqual(
            [a['status'] for a in serialized_titles['times out then is abandoned']['attempts']],
            ['timedOut', 'interrupted'],
        )
        self.assertEqual(serialized_titles['skipped test']['attempts'][0]['status'], 'skipped')

    def test_attachment_file_content_is_actually_stored(self):
        # Regression test for a real bug: the view used to match attachment
        # multipart parts by a field-name convention ("attachment-0",
        # "attachment-1") that the real CLI never sends - it always sends
        # every attachment under the literal repeated field name
        # "attachment[]" (see buildMultipartRequest.ts), with the numbered
        # partName living only inside the JSON manifest. The old code
        # silently matched nothing and dropped every attachment while still
        # returning 201. This asserts the actual bytes round-trip, not just
        # that an Attachment row with the right name exists.
        attachments = [
            SimpleUploadedFile('trace.zip', b'trace-bytes', content_type='application/zip'),
            SimpleUploadedFile('screenshot.png', b'png-bytes', content_type='image/png'),
        ]
        response = self._post(attachments=attachments)
        self.assertEqual(response.status_code, 201, response.content)

        self.assertEqual(Attachment.objects.count(), 2)
        trace = Attachment.objects.get(name='trace.zip')
        screenshot = Attachment.objects.get(name='screenshot.png')
        self.assertEqual(trace.file.read(), b'trace-bytes')
        self.assertEqual(screenshot.file.read(), b'png-bytes')

    def test_no_attachments_is_valid(self):
        single_test_report = {
            'tests': [
                {
                    'id': 'no attachments here',
                    'title': 'no attachments here',
                    'outcome': 'passed',
                    'retries': [{'status': 'passed', 'duration': 10, 'attachments': []}],
                    'attachments': [],
                },
            ],
        }
        response = self._post(report=single_test_report, manifest=[])
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Attachment.objects.count(), 0)


class ConcurrentUploadTests(TransactionTestCase):
    """AC3: concurrent uploads never collide on identity (UUIDs) or
    interleave writes (transaction.atomic()) — NOT that every concurrent
    write is guaranteed to succeed. design.md explicitly scopes AC3 as a
    data-corruption guarantee, not a throughput one: SQLite's own write
    serialization under concurrent writers is a separate, already-tracked
    constraint (see infra/README.md's GCS-FUSE SQLite caveat). A request
    that SQLite's locking rejects outright must fail cleanly (not corrupt
    anything, not leave a partial Run) - it is not required to succeed.

    Uses TransactionTestCase because the regular TestCase wraps each test
    in its own transaction, which would hide real concurrent-commit
    behavior."""

    url = reverse('runs:upload')

    def test_concurrent_uploads_never_corrupt_or_interleave(self):
        _, raw_token = _make_project_and_token()
        report = {
            'tests': [
                {
                    'id': 'independent test',
                    'title': 'independent test',
                    'outcome': 'passed',
                    'retries': [{'status': 'passed', 'duration': 5, 'attachments': []}],
                    'attachments': [],
                },
            ],
        }
        results = []
        results_lock = threading.Lock()

        def upload():
            from django.test import Client
            client = Client()
            response = client.post(
                self.url,
                data={'report': json.dumps(report), 'manifest': '[]'},
                format='multipart',
                headers={'Authorization': f'Bearer {raw_token}'},
            )
            with results_lock:
                results.append(response.status_code)

        threads = [threading.Thread(target=upload) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Every response is either a clean success or a clean, explicit
        # "busy, retry" error (SQLite rejecting a write under contention)
        # - never a corrupted or partially-written result, and never an
        # unhandled 500 with a leaked stack trace.
        self.assertTrue(all(code in (201, 503) for code in results), results)
        succeeded = results.count(201)
        self.assertGreaterEqual(succeeded, 1, 'at least one concurrent upload must succeed')

        # Every Run that DOES exist has exactly one TestCase and one
        # Attempt - no interleaving between concurrent writes produced a
        # Run with another upload's rows mixed in, and no two Runs share
        # an id (UUIDs rule out identity collision by construction).
        self.assertEqual(Run.objects.count(), succeeded)
        run_ids = set(Run.objects.values_list('id', flat=True))
        self.assertEqual(len(run_ids), succeeded)
        for run in Run.objects.all():
            self.assertEqual(run.test_cases.count(), 1)
            self.assertEqual(run.test_cases.get().attempts.count(), 1)


def _runs_url(project_id):
    return reverse('run-list', kwargs={'project_id': project_id})


def _make_org_project_member():
    org = Organization.objects.create(name='Acme')
    project = Project.objects.create(organization=org, name='Widgets', slug='widgets')
    member = User.objects.create_user(username='member', password='pw')
    OrganizationMembership.objects.create(organization=org, user=member, role='owner')
    return org, project, member


def _make_run_with_test_cases(project, outcomes_and_attempt_durations, branch=None, commit_sha=None):
    """outcomes_and_attempt_durations: list of (outcome, [attempt_durations])."""
    run = Run.objects.create(project=project, branch=branch, commit_sha=commit_sha)
    for outcome, durations in outcomes_and_attempt_durations:
        test_case = TestCaseModel.objects.create(run=run, title=f'test ({outcome})', outcome=outcome)
        for i, duration in enumerate(durations, start=1):
            Attempt.objects.create(
                test_case=test_case, attempt_number=i, status='passed' if outcome != 'failed' else 'failed',
                duration_ms=duration,
            )
    return run


class RunListViewTests(TestCase):
    def test_empty_project_returns_empty_list(self):
        org, project, member = _make_org_project_member()
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_run_with_only_passed_test_cases_shows_passed_status(self):
        org, project, member = _make_org_project_member()
        _make_run_with_test_cases(project, [('passed', [100])])
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id))

        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['status'], 'passed')
        self.assertEqual(body[0]['passed_count'], 1)
        self.assertEqual(body[0]['failed_count'], 0)
        self.assertEqual(body[0]['flaky_count'], 0)

    def test_skipped_test_cases_are_counted(self):
        # Zero coverage for skipped_count before this test (flagged by
        # fresh-session code review on PR #45) - passed/failed/flaky all
        # had dedicated assertions, skipped had none.
        org, project, member = _make_org_project_member()
        _make_run_with_test_cases(
            project,
            [('passed', [10]), ('skipped', [0])],
        )
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id))

        body = response.json()
        self.assertEqual(body[0]['status'], 'passed')
        self.assertEqual(body[0]['passed_count'], 1)
        self.assertEqual(body[0]['skipped_count'], 1)
        self.assertEqual(body[0]['failed_count'], 0)
        self.assertEqual(body[0]['flaky_count'], 0)

    def test_failed_takes_precedence_over_flaky_on_the_same_run(self):
        # Precedence test: both outcomes present on the SAME run - must
        # not just test each status in isolation.
        org, project, member = _make_org_project_member()
        run = _make_run_with_test_cases(
            project,
            [('failed', [50]), ('flaky', [60, 70])],
        )
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id))

        body = response.json()
        self.assertEqual(body[0]['id'], str(run.id))
        self.assertEqual(body[0]['status'], 'failed')
        self.assertEqual(body[0]['failed_count'], 1)
        self.assertEqual(body[0]['flaky_count'], 1)

    def test_flaky_but_no_failed_shows_flaky_status(self):
        org, project, member = _make_org_project_member()
        _make_run_with_test_cases(project, [('passed', [10]), ('flaky', [20, 30])])
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id))

        body = response.json()
        self.assertEqual(body[0]['status'], 'flaky')

    def test_runs_are_ordered_newest_first(self):
        org, project, member = _make_org_project_member()
        run1 = _make_run_with_test_cases(project, [('passed', [10])])
        run2 = _make_run_with_test_cases(project, [('passed', [10])])
        run3 = _make_run_with_test_cases(project, [('passed', [10])])
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id))

        ids = [row['id'] for row in response.json()]
        self.assertEqual(ids, [str(run3.id), str(run2.id), str(run1.id)])

    def test_null_branch_and_commit_sha_serialize_as_null(self):
        org, project, member = _make_org_project_member()
        _make_run_with_test_cases(project, [('passed', [10])], branch=None, commit_sha=None)
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id))

        body = response.json()
        self.assertIsNone(body[0]['branch'])
        self.assertIsNone(body[0]['commit_sha'])

    def test_duration_sums_every_attempt_across_all_test_cases(self):
        org, project, member = _make_org_project_member()
        _make_run_with_test_cases(
            project,
            [('passed', [100]), ('flaky', [50, 75])],
        )
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id))

        body = response.json()
        self.assertEqual(body[0]['duration_ms'], 100 + 50 + 75)

    def test_fan_out_does_not_inflate_counts_when_a_test_case_has_multiple_attempts(self):
        # The exact case that broke this query during design verification:
        # one failed test case (1 attempt) and one flaky test case with
        # 2+ attempts. Without distinct=True on the view's Count() calls,
        # flaky_count reads 2 instead of 1.
        org, project, member = _make_org_project_member()
        _make_run_with_test_cases(
            project,
            [('failed', [50]), ('flaky', [10, 20, 30])],
        )
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id))

        body = response.json()
        self.assertEqual(body[0]['failed_count'], 1)
        self.assertEqual(body[0]['flaky_count'], 1)
        self.assertEqual(body[0]['duration_ms'], 50 + 10 + 20 + 30)

    def test_non_member_of_project_org_gets_404(self):
        org, project, member = _make_org_project_member()
        outsider = User.objects.create_user(username='outsider', password='pw')
        self.client.force_login(outsider)

        response = self.client.get(_runs_url(project.id))

        self.assertEqual(response.status_code, 404)

    def test_nonexistent_project_gets_404_same_shape_as_non_member(self):
        org, project, member = _make_org_project_member()
        self.client.force_login(member)

        response = self.client.get(_runs_url('00000000-0000-0000-0000-000000000000'))

        self.assertEqual(response.status_code, 404)

    def test_query_count_stays_constant_regardless_of_run_count(self):
        org, project, member = _make_org_project_member()
        self.client.force_login(member)

        for _ in range(5):
            _make_run_with_test_cases(
                project,
                [('passed', [10]), ('failed', [20]), ('flaky', [30, 40])],
            )

        with CaptureQueriesContext(connection) as ctx_few:
            response = self.client.get(_runs_url(project.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 5)
        few_query_count = len(ctx_few.captured_queries)

        for _ in range(5):
            _make_run_with_test_cases(
                project,
                [('passed', [10]), ('failed', [20]), ('flaky', [30, 40])],
            )

        with CaptureQueriesContext(connection) as ctx_many:
            response = self.client.get(_runs_url(project.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 10)
        many_query_count = len(ctx_many.captured_queries)

        self.assertEqual(
            few_query_count, many_query_count,
            f'query count must not grow with run count: 5 runs -> {few_query_count} queries, '
            f'10 runs -> {many_query_count} queries',
        )


class RunListFilterTests(TestCase):
    """TW-13: ?status=/?branch=/?search= on GET /api/projects/<id>/runs/."""

    def test_status_filter_returns_only_matching_runs(self):
        org, project, member = _make_org_project_member()
        _make_run_with_test_cases(project, [('passed', [10])])
        failed_run = _make_run_with_test_cases(project, [('failed', [10])])
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id), {'status': 'failed'})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['id'], str(failed_run.id))

    def test_status_filter_matches_the_same_precedence_the_badge_shows(self):
        # A run with both failed and flaky test cases shows 'failed' per
        # precedence (see test_failed_takes_precedence_over_flaky...) -
        # the filter must agree: ?status=flaky must NOT match it, and
        # ?status=failed must.
        org, project, member = _make_org_project_member()
        mixed_run = _make_run_with_test_cases(
            project, [('failed', [10]), ('flaky', [20, 30])],
        )
        self.client.force_login(member)

        flaky_response = self.client.get(_runs_url(project.id), {'status': 'flaky'})
        failed_response = self.client.get(_runs_url(project.id), {'status': 'failed'})

        self.assertEqual(flaky_response.json(), [])
        self.assertEqual(len(failed_response.json()), 1)
        self.assertEqual(failed_response.json()[0]['id'], str(mixed_run.id))

    def test_unrecognized_status_value_returns_400_not_empty_list(self):
        org, project, member = _make_org_project_member()
        _make_run_with_test_cases(project, [('passed', [10])])
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id), {'status': 'bogus'})

        self.assertEqual(response.status_code, 400)

    def test_branch_filter_excludes_other_branches_and_null_branch(self):
        org, project, member = _make_org_project_member()
        main_run = _make_run_with_test_cases(project, [('passed', [10])], branch='main')
        _make_run_with_test_cases(project, [('passed', [10])], branch='dev')
        _make_run_with_test_cases(project, [('passed', [10])], branch=None)
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id), {'branch': 'main'})

        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['id'], str(main_run.id))

    def test_branch_filter_against_all_null_branches_returns_empty_list_not_error(self):
        # The "acknowledged-empty data" case from spec.md gap 2 - every
        # Run.branch is null in practice today since the CLI never sends
        # one (see #46). Must not crash.
        org, project, member = _make_org_project_member()
        _make_run_with_test_cases(project, [('passed', [10])], branch=None)
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id), {'branch': 'main'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_search_matches_commit_sha_case_insensitively(self):
        org, project, member = _make_org_project_member()
        matching_run = _make_run_with_test_cases(
            project, [('passed', [10])], commit_sha='a1b2c3d4',
        )
        _make_run_with_test_cases(project, [('passed', [10])], commit_sha='ffffffff')
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id), {'search': 'A1B2'})

        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['id'], str(matching_run.id))

    def test_search_against_null_commit_sha_excludes_it_without_error(self):
        org, project, member = _make_org_project_member()
        _make_run_with_test_cases(project, [('passed', [10])], commit_sha=None)
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id), {'search': 'anything'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_all_three_filters_combine_with_and_not_or(self):
        org, project, member = _make_org_project_member()
        # Satisfies status+branch but not search.
        _make_run_with_test_cases(
            project, [('failed', [10])], branch='main', commit_sha='zzzzzzzz',
        )
        # Satisfies status+search but not branch.
        _make_run_with_test_cases(
            project, [('failed', [10])], branch='dev', commit_sha='a1b2c3d4',
        )
        # Satisfies branch+search but not status.
        _make_run_with_test_cases(
            project, [('passed', [10])], branch='main', commit_sha='a1b2c3d4',
        )
        # Satisfies all three.
        target_run = _make_run_with_test_cases(
            project, [('failed', [10])], branch='main', commit_sha='a1b2c3d4',
        )
        self.client.force_login(member)

        response = self.client.get(
            _runs_url(project.id),
            {'status': 'failed', 'branch': 'main', 'search': 'a1b2'},
        )

        body = response.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['id'], str(target_run.id))

    def test_filters_matching_zero_runs_returns_200_empty_list(self):
        org, project, member = _make_org_project_member()
        _make_run_with_test_cases(project, [('passed', [10])], branch='main')
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id), {'branch': 'nonexistent-branch'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_omitting_all_filters_matches_unfiltered_behavior(self):
        org, project, member = _make_org_project_member()
        run1 = _make_run_with_test_cases(project, [('passed', [10])])
        run2 = _make_run_with_test_cases(project, [('failed', [10])])
        self.client.force_login(member)

        response = self.client.get(_runs_url(project.id))

        ids = {row['id'] for row in response.json()}
        self.assertEqual(ids, {str(run1.id), str(run2.id)})

    def test_non_member_gets_404_even_with_filters_present(self):
        org, project, member = _make_org_project_member()
        outsider = User.objects.create_user(username='outsider', password='pw')
        self.client.force_login(outsider)

        response = self.client.get(
            _runs_url(project.id),
            {'status': 'failed', 'branch': 'main', 'search': 'x'},
        )

        self.assertEqual(response.status_code, 404)


def _run_detail_url(run_id):
    return reverse('runs:detail', kwargs={'run_id': run_id})


class RunDetailViewTests(TestCase):
    def test_returns_header_fields_and_nested_test_cases(self):
        org, project, member = _make_org_project_member()
        run = _make_run_with_test_cases(
            project, [('passed', [100])], branch='main', commit_sha='abc123',
        )
        self.client.force_login(member)

        response = self.client.get(_run_detail_url(run.id))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['id'], str(run.id))
        self.assertEqual(body['branch'], 'main')
        self.assertEqual(body['commit_sha'], 'abc123')
        self.assertEqual(body['status'], 'passed')
        self.assertEqual(body['passed_count'], 1)
        self.assertEqual(body['failed_count'], 0)
        self.assertEqual(body['flaky_count'], 0)
        self.assertEqual(body['skipped_count'], 0)
        self.assertEqual(body['duration_ms'], 100)
        self.assertIn('uploaded_at', body)
        self.assertEqual(len(body['test_cases']), 1)
        test_case = body['test_cases'][0]
        self.assertEqual(test_case['outcome'], 'passed')
        self.assertEqual(len(test_case['attempts']), 1)
        self.assertEqual(test_case['attempts'][0]['status'], 'passed')
        self.assertEqual(test_case['attempts'][0]['duration_ms'], 100)

    def test_status_precedence_matches_runs_list(self):
        # Same precedence test shape as RunListViewTests - must agree
        # with the badge the runs list already shows for this run.
        org, project, member = _make_org_project_member()
        run = _make_run_with_test_cases(
            project, [('failed', [50]), ('flaky', [60, 70])],
        )
        self.client.force_login(member)

        response = self.client.get(_run_detail_url(run.id))

        body = response.json()
        self.assertEqual(body['status'], 'failed')
        self.assertEqual(body['failed_count'], 1)
        self.assertEqual(body['flaky_count'], 1)

    def test_test_cases_are_ordered_by_title_not_insertion_order(self):
        org, project, member = _make_org_project_member()
        run = Run.objects.create(project=project)
        # Create out of alphabetical order on purpose.
        TestCaseModel.objects.create(run=run, title='zebra test', outcome='passed')
        TestCaseModel.objects.create(run=run, title='alpha test', outcome='passed')
        TestCaseModel.objects.create(run=run, title='mango test', outcome='passed')
        self.client.force_login(member)

        response = self.client.get(_run_detail_url(run.id))

        titles = [tc['title'] for tc in response.json()['test_cases']]
        self.assertEqual(titles, ['alpha test', 'mango test', 'zebra test'])

    def test_null_branch_and_commit_sha_serialize_as_null(self):
        org, project, member = _make_org_project_member()
        run = _make_run_with_test_cases(project, [('passed', [10])])
        self.client.force_login(member)

        response = self.client.get(_run_detail_url(run.id))

        body = response.json()
        self.assertIsNone(body['branch'])
        self.assertIsNone(body['commit_sha'])

    def test_attachments_are_nested_three_levels_deep(self):
        org, project, member = _make_org_project_member()
        run = Run.objects.create(project=project)
        test_case = TestCaseModel.objects.create(run=run, title='test with attachment', outcome='passed')
        attempt = Attempt.objects.create(test_case=test_case, attempt_number=1, status='passed', duration_ms=10)
        Attachment.objects.create(
            attempt=attempt, name='screenshot.png', content_type='image/png',
            file=SimpleUploadedFile('screenshot.png', b'fake-image-bytes'),
        )
        self.client.force_login(member)

        response = self.client.get(_run_detail_url(run.id))

        body = response.json()
        attachments = body['test_cases'][0]['attempts'][0]['attachments']
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]['name'], 'screenshot.png')
        self.assertEqual(attachments[0]['content_type'], 'image/png')
        self.assertIn('file', attachments[0])

    def test_response_never_contains_shard_count_title_or_author(self):
        # Regression guard for gaps 1/2 (spec.md) - these fields don't
        # exist as real data anywhere and must never be silently invented
        # by a future change.
        org, project, member = _make_org_project_member()
        run = _make_run_with_test_cases(project, [('passed', [10])])
        self.client.force_login(member)

        response = self.client.get(_run_detail_url(run.id))

        body = response.json()
        self.assertNotIn('shard_count', body)
        self.assertNotIn('title', body)
        self.assertNotIn('author', body)

    def test_non_member_of_project_org_gets_404(self):
        org, project, member = _make_org_project_member()
        run = _make_run_with_test_cases(project, [('passed', [10])])
        outsider = User.objects.create_user(username='outsider', password='pw')
        self.client.force_login(outsider)

        response = self.client.get(_run_detail_url(run.id))

        self.assertEqual(response.status_code, 404)

    def test_nonexistent_run_gets_404_same_shape_as_non_member(self):
        org, project, member = _make_org_project_member()
        self.client.force_login(member)

        response = self.client.get(_run_detail_url('00000000-0000-0000-0000-000000000000'))

        self.assertEqual(response.status_code, 404)

    def test_run_with_no_project_gets_404(self):
        # Pre-TW-26 edge case: Run.project is nullable. No membership
        # path exists for a projectless run - must 404, not 500 from
        # None.organization_id.
        org, project, member = _make_org_project_member()
        run = Run.objects.create(project=None)
        self.client.force_login(member)

        response = self.client.get(_run_detail_url(run.id))

        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_request_is_denied(self):
        org, project, member = _make_org_project_member()
        run = _make_run_with_test_cases(project, [('passed', [10])])

        response = self.client.get(_run_detail_url(run.id))

        self.assertIn(response.status_code, (401, 403))

    def test_query_count_stays_constant_regardless_of_test_case_count(self):
        org, project, member = _make_org_project_member()

        def make_run_with_n_test_cases(n):
            run = Run.objects.create(project=project)
            for i in range(n):
                test_case = TestCaseModel.objects.create(run=run, title=f'test {i}', outcome='passed')
                attempt = Attempt.objects.create(test_case=test_case, attempt_number=1, status='passed', duration_ms=10)
                Attachment.objects.create(
                    attempt=attempt, name='a.png', content_type='image/png',
                    file=SimpleUploadedFile('a.png', b'x'),
                )
            return run

        small_run = make_run_with_n_test_cases(1)
        large_run = make_run_with_n_test_cases(10)
        self.client.force_login(member)

        with CaptureQueriesContext(connection) as small_ctx:
            self.client.get(_run_detail_url(small_run.id))
        with CaptureQueriesContext(connection) as large_ctx:
            self.client.get(_run_detail_url(large_run.id))

        self.assertEqual(
            len(small_ctx.captured_queries), len(large_ctx.captured_queries),
            'query count must not scale with test_case/attempt/attachment count (N+1 check)',
        )
