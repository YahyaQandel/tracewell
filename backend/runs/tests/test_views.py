import json
import threading

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from runs.models import Attachment, Attempt, Run, TestCase as TestCaseModel

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

    def _post(self, report=VALID_REPORT, manifest=VALID_MANIFEST, attachments=None, extra=None):
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
        return self.client.post(self.url, data=data, format='multipart')

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

    def test_project_part_is_accepted_and_ignored(self):
        response = self._post(extra={'project': 'some-project-id'})
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
