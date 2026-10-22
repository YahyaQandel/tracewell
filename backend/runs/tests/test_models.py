from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from runs.models import Attachment, Attempt, Run, TestCase as TestCaseModel, attachment_upload_path


class RunModelTests(TestCase):
    def test_branch_and_commit_default_to_none(self):
        run = Run.objects.create()
        self.assertIsNone(run.branch)
        self.assertIsNone(run.commit_sha)

    def test_id_is_a_uuid_assigned_without_a_db_round_trip(self):
        run = Run()
        self.assertIsNotNone(run.id)
        run.save()
        self.assertEqual(Run.objects.get().id, run.id)

    def test_two_runs_never_share_an_id(self):
        run_a = Run.objects.create()
        run_b = Run.objects.create()
        self.assertNotEqual(run_a.id, run_b.id)


class CascadeDeleteTests(TestCase):
    def setUp(self):
        self.run = Run.objects.create()
        self.test_case = TestCaseModel.objects.create(run=self.run, title='t', outcome='passed')
        self.attempt = Attempt.objects.create(
            test_case=self.test_case, attempt_number=1, status='passed', duration_ms=1,
        )
        self.attachment = Attachment.objects.create(
            attempt=self.attempt,
            name='trace.zip',
            content_type='application/zip',
            file=SimpleUploadedFile('trace.zip', b'bytes'),
        )

    def test_deleting_a_run_cascades_to_all_descendants(self):
        self.run.delete()
        self.assertEqual(TestCaseModel.objects.count(), 0)
        self.assertEqual(Attempt.objects.count(), 0)
        self.assertEqual(Attachment.objects.count(), 0)

    def test_deleting_a_test_case_cascades_to_its_attempts_and_attachments(self):
        self.test_case.delete()
        self.assertEqual(Attempt.objects.count(), 0)
        self.assertEqual(Attachment.objects.count(), 0)
        # The Run row itself is untouched - cascade only flows downward.
        self.assertEqual(Run.objects.count(), 1)


class AttachmentUploadPathTests(TestCase):
    def test_path_is_namespaced_by_run_id(self):
        run = Run.objects.create()
        test_case = TestCaseModel.objects.create(run=run, title='t', outcome='passed')
        attempt = Attempt.objects.create(test_case=test_case, attempt_number=1, status='passed', duration_ms=1)
        attachment = Attachment(attempt=attempt, name='screenshot.png', content_type='image/png')

        path = attachment_upload_path(attachment, 'screenshot.png')

        self.assertTrue(path.startswith(f'runs/{run.id}/'))
        self.assertIn(str(attachment.id), path)
        self.assertTrue(path.endswith('-screenshot.png'))

    def test_two_runs_attachments_never_collide_on_path(self):
        run_a = Run.objects.create()
        run_b = Run.objects.create()
        tc_a = TestCaseModel.objects.create(run=run_a, title='t', outcome='passed')
        tc_b = TestCaseModel.objects.create(run=run_b, title='t', outcome='passed')
        attempt_a = Attempt.objects.create(test_case=tc_a, attempt_number=1, status='passed', duration_ms=1)
        attempt_b = Attempt.objects.create(test_case=tc_b, attempt_number=1, status='passed', duration_ms=1)

        attachment_a = Attachment(attempt=attempt_a, name='same-name.png', content_type='image/png')
        attachment_b = Attachment(attempt=attempt_b, name='same-name.png', content_type='image/png')

        path_a = attachment_upload_path(attachment_a, 'same-name.png')
        path_b = attachment_upload_path(attachment_b, 'same-name.png')

        self.assertNotEqual(path_a, path_b)
        self.assertIn(f'runs/{run_a.id}/', path_a)
        self.assertIn(f'runs/{run_b.id}/', path_b)
