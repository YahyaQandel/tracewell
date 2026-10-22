from django.test import SimpleTestCase

from runs.parsers import ParseError, parse_upload


VALID_REPORT = {
    'tests': [
        {
            'id': 'login works',
            'title': 'login works',
            'outcome': 'passed',
            'retries': [
                {'status': 'passed', 'duration': 120, 'attachments': []},
            ],
            'attachments': [],
        },
        {
            'id': 'flaky test',
            'title': 'flaky test',
            'outcome': 'flaky',
            'retries': [
                {
                    'status': 'failed',
                    'duration': 50,
                    'attachments': [
                        {'name': 'trace.zip', 'contentType': 'application/zip'},
                    ],
                },
                {
                    'status': 'passed',
                    'duration': 60,
                    'attachments': [
                        {'name': 'screenshot.png', 'contentType': 'image/png'},
                    ],
                },
            ],
            'attachments': [
                {'name': 'screenshot.png', 'contentType': 'image/png'},
            ],
        },
    ],
}


class ParseUploadTests(SimpleTestCase):
    def test_parses_tests_and_attempts(self):
        manifest = [
            {'testId': 'flaky test', 'attachmentName': 'trace.zip', 'partName': 'attachment-0', 'retryIndex': 0},
            {'testId': 'flaky test', 'attachmentName': 'screenshot.png', 'partName': 'attachment-1', 'retryIndex': 1},
        ]

        parsed = parse_upload(VALID_REPORT, manifest)

        self.assertEqual(len(parsed.tests), 2)
        login_test = parsed.tests[0]
        self.assertEqual(login_test.title, 'login works')
        self.assertEqual(login_test.outcome, 'passed')
        self.assertEqual(len(login_test.attempts), 1)
        self.assertEqual(login_test.attempts[0].status, 'passed')
        self.assertEqual(login_test.attempts[0].duration_ms, 120)
        self.assertEqual(login_test.attempts[0].attachments, [])

    def test_uses_retries_attachments_not_top_level(self):
        # The top-level ParsedTest.attachments field only mirrors the LAST
        # attempt. The parser must use retries[].attachments (via manifest)
        # for every attempt, not the top-level field, or attachment-0
        # (belonging to attempt 0) would be silently dropped.
        manifest = [
            {'testId': 'flaky test', 'attachmentName': 'trace.zip', 'partName': 'attachment-0', 'retryIndex': 0},
            {'testId': 'flaky test', 'attachmentName': 'screenshot.png', 'partName': 'attachment-1', 'retryIndex': 1},
        ]

        parsed = parse_upload(VALID_REPORT, manifest)

        flaky_test = parsed.tests[1]
        self.assertEqual(len(flaky_test.attempts), 2)
        attempt_0, attempt_1 = flaky_test.attempts
        self.assertEqual(attempt_0.status, 'failed')
        self.assertEqual([a.part_name for a in attempt_0.attachments], ['attachment-0'])
        self.assertEqual(attempt_1.status, 'passed')
        self.assertEqual([a.part_name for a in attempt_1.attachments], ['attachment-1'])

    def test_missing_tests_array_is_rejected(self):
        with self.assertRaises(ParseError):
            parse_upload({'not_tests': []}, [])

    def test_report_not_an_object_is_rejected(self):
        with self.assertRaises(ParseError):
            parse_upload(['not', 'an', 'object'], [])

    def test_manifest_entry_with_unknown_test_id_is_rejected(self):
        manifest = [
            {'testId': 'does not exist', 'attachmentName': 'x.png', 'partName': 'attachment-0', 'retryIndex': 0},
        ]
        with self.assertRaises(ParseError):
            parse_upload(VALID_REPORT, manifest)

    def test_manifest_entry_with_out_of_range_retry_index_is_rejected(self):
        manifest = [
            {'testId': 'login works', 'attachmentName': 'x.png', 'partName': 'attachment-0', 'retryIndex': 5},
        ]
        with self.assertRaises(ParseError):
            parse_upload(VALID_REPORT, manifest)

    def test_malformed_json_string_is_rejected(self):
        with self.assertRaises(ParseError):
            parse_upload('not even json-decodable as a dict', [])

    def test_attachment_content_type_resolved_from_report_by_name(self):
        # content_type is a fallback value (the view layer prefers the
        # actual uploaded multipart part's own content_type when one is
        # present) - but when it's used, it must be looked up from the
        # report's own declared AttachmentRef.contentType by name, not a
        # hardcoded placeholder.
        manifest = [
            {'testId': 'flaky test', 'attachmentName': 'trace.zip', 'partName': 'attachment-0', 'retryIndex': 0},
        ]
        parsed = parse_upload(VALID_REPORT, manifest)
        flaky_test = parsed.tests[1]
        self.assertEqual(flaky_test.attempts[0].attachments[0].content_type, 'application/zip')

    def test_attachment_content_type_defaults_when_report_never_declared_it(self):
        manifest = [
            {'testId': 'flaky test', 'attachmentName': 'not-in-report.log', 'partName': 'attachment-0', 'retryIndex': 0},
        ]
        parsed = parse_upload(VALID_REPORT, manifest)
        flaky_test = parsed.tests[1]
        self.assertEqual(flaky_test.attempts[0].attachments[0].content_type, 'application/octet-stream')

    def test_duplicate_attachment_name_within_a_retry_keeps_both(self):
        # Two distinct files can legitimately share a display name (e.g.
        # two screenshots both named "screenshot.png"). partName is the
        # real uniqueness key; name is just display metadata and is
        # allowed to collide - no dedup, both attachments are kept.
        manifest = [
            {'testId': 'login works', 'attachmentName': 'screenshot.png', 'partName': 'attachment-0', 'retryIndex': 0},
            {'testId': 'login works', 'attachmentName': 'screenshot.png', 'partName': 'attachment-1', 'retryIndex': 0},
        ]

        parsed = parse_upload(VALID_REPORT, manifest)

        login_test = parsed.tests[0]
        self.assertEqual(len(login_test.attempts[0].attachments), 2)
        part_names = {a.part_name for a in login_test.attempts[0].attachments}
        self.assertEqual(part_names, {'attachment-0', 'attachment-1'})
