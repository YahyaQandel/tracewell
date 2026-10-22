import json

from django.db import OperationalError, transaction
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from runs.models import Attachment, Attempt, Run, TestCase
from runs.parsers import ParseError, parse_upload
from runs.serializers import RunSerializer


class UploadRunView(APIView):
    """POST /api/runs/ — TW-1's CLI multipart bundle.

    AC4: the whole parse-and-validate step happens before any DB row or
    attachment file is written, and all writes happen inside one
    transaction.atomic() block, so a failure never leaves a partial Run.
    """
    parser_classes = [MultiPartParser]

    def post(self, request):
        report_raw = request.data.get('report')
        manifest_raw = request.data.get('manifest', '[]')

        try:
            report = json.loads(report_raw) if isinstance(report_raw, str) else report_raw
        except (TypeError, json.JSONDecodeError):
            return Response({'detail': 'report is not valid JSON'}, status=400)

        try:
            manifest = json.loads(manifest_raw) if isinstance(manifest_raw, str) else manifest_raw
        except (TypeError, json.JSONDecodeError):
            return Response({'detail': 'manifest is not valid JSON'}, status=400)

        try:
            parsed = parse_upload(report, manifest)
        except ParseError as exc:
            return Response({'detail': str(exc)}, status=400)

        branch = request.data.get('branch') or None
        commit_sha = request.data.get('commit') or None
        # `project` (request.data.get('project')) is accepted implicitly by
        # being present in multipart form data and otherwise ignored - no
        # Project model exists yet (design.md: out of scope for this ticket).

        attachment_files_by_part_name = {
            key: value for key, value in request.data.items()
            if key.startswith('attachment-') and hasattr(value, 'read')
        }

        try:
            with transaction.atomic():
                run = Run.objects.create(branch=branch, commit_sha=commit_sha)

                for parsed_test in parsed.tests:
                    test_case = TestCase.objects.create(
                        run=run,
                        title=parsed_test.title,
                        outcome=parsed_test.outcome,
                    )
                    for parsed_attempt in parsed_test.attempts:
                        attempt = Attempt.objects.create(
                            test_case=test_case,
                            attempt_number=parsed_attempt.retry_index + 1,
                            status=parsed_attempt.status,
                            duration_ms=parsed_attempt.duration_ms,
                        )
                        for parsed_attachment in parsed_attempt.attachments:
                            uploaded_file = attachment_files_by_part_name.get(parsed_attachment.part_name)
                            if uploaded_file is None:
                                continue
                            Attachment.objects.create(
                                attempt=attempt,
                                name=parsed_attachment.name,
                                # Non-blocking design note: content-type
                                # can also be sourced from the multipart
                                # part itself. Prefer the actual uploaded
                                # file's declared content_type (more
                                # likely to be accurate than the
                                # manifest's JSON metadata) when
                                # available, falling back to the parser's
                                # value otherwise.
                                content_type=getattr(uploaded_file, 'content_type', None) or parsed_attachment.content_type,
                                file=uploaded_file,
                            )
        except OperationalError:
            # AC3 (data-corruption, not throughput, guarantee): under
            # SQLite write contention a concurrent request can be
            # rejected by the database itself. transaction.atomic() has
            # already rolled back anything from this request - nothing
            # partial is left behind. Surface as a clean 503 rather than
            # a 500 with a leaked stack trace; the client can retry.
            return Response(
                {'detail': 'database is busy, try again'},
                status=503,
            )

        serializer = RunSerializer(run)
        return Response(serializer.data, status=201)
