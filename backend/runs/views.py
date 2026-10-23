import json

from django.db import OperationalError, transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.views import OrganizationScopedView
from projects.views import ProjectScopedView
from runs.models import Attachment, Attempt, Run, TestCase, status_for
from runs.parsers import ParseError, parse_upload
from runs.serializers import RunDetailSerializer, RunListSerializer, RunSerializer
from tokens.authentication import ApiTokenAuthentication


class UploadRunView(APIView):
    """POST /api/runs/ — TW-1's CLI multipart bundle.

    AC4: the whole parse-and-validate step happens before any DB row or
    attachment file is written, and all writes happen inside one
    transaction.atomic() block, so a failure never leaves a partial Run.

    Auth: TW-26 gives this a real credential (ApiTokenAuthentication,
    Bearer <token>). permission_classes stays AllowAny deliberately - no
    role/membership check is needed here, a valid project-scoped token IS
    the authorization (the client isn't a logged-in org member, it's a CI
    job holding a project secret). But the view itself must still require
    SOME authenticator to have succeeded, since AllowAny alone would let
    a header-less request through with request.auth=None - see the
    explicit check in post() below. This replaces the TW-22-era setup
    that left this endpoint fully unauthenticated; that reasoning no
    longer holds now a real CI credential exists.
    """
    parser_classes = [MultiPartParser]
    authentication_classes = [ApiTokenAuthentication]
    permission_classes = [AllowAny]

    def post(self, request):
        if request.auth is None:
            raise AuthenticationFailed('Authentication credentials were not provided.')
        project = request.auth.project

        report_raw = request.data.get('report')
        manifest_raw = request.data.get('manifest', '[]')

        # cli/src/upload/httpClient.ts's classifyResponse reads `body.message`
        # on a 400 (and falls back to a generic "malformed report" string if
        # that key is absent) - it never reads `detail`, DRF's own
        # convention. Using `message` here means the CLI actually surfaces
        # the real validation reason instead of discarding it.
        try:
            report = json.loads(report_raw) if isinstance(report_raw, str) else report_raw
        except (TypeError, json.JSONDecodeError):
            return Response({'message': 'report is not valid JSON'}, status=400)

        try:
            manifest = json.loads(manifest_raw) if isinstance(manifest_raw, str) else manifest_raw
        except (TypeError, json.JSONDecodeError):
            return Response({'message': 'manifest is not valid JSON'}, status=400)

        try:
            parsed = parse_upload(report, manifest)
        except ParseError as exc:
            return Response({'message': str(exc)}, status=400)

        branch = request.data.get('branch') or None
        commit_sha = request.data.get('commit') or None
        # A client-sent `project` field (request.data.get('project')) is
        # never read for scoping purposes - the authenticated token's own
        # project (resolved above) determines where the run belongs, full
        # stop. A token scoped to project A can never create a run under
        # project B no matter what string the client sends; this is
        # strictly safer than trusting a client-supplied value and one
        # fewer thing to validate.

        # The CLI sends every attachment under the literal, repeated field
        # name "attachment[]" (buildMultipartRequest.ts) - there is no
        # per-part field name on the wire. `partName` (e.g. "attachment-0")
        # only exists inside the JSON manifest, and is assigned in the same
        # order the CLI builds attachmentParts - so position in
        # request.FILES.getlist('attachment[]') corresponds 1:1 to the
        # index embedded in partName. request.data.items() would silently
        # collapse repeated keys to the last one (MultiValueDict), which is
        # what originally made this match nothing.
        uploaded_files = request.FILES.getlist('attachment[]')
        attachment_files_by_part_name = {
            f'attachment-{index}': uploaded_file
            for index, uploaded_file in enumerate(uploaded_files)
        }

        try:
            with transaction.atomic():
                run = Run.objects.create(project=project, branch=branch, commit_sha=commit_sha)

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

            # Serializing re-reads the Run and its nested test_cases/
            # attempts/attachments - under the same SQLite write
            # contention this is meant to survive, that read can itself
            # raise OperationalError even though the write above already
            # committed cleanly. Must stay inside this try so a request
            # that genuinely succeeded doesn't crash with an unhandled
            # 500 while building its own success response (this was a
            # real bug: a write-succeeded request could still report as
            # a total failure).
            serializer = RunSerializer(run)
            response_data = serializer.data
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

        return Response(response_data, status=201)


VALID_STATUSES = {'passed', 'failed', 'flaky'}


class RunListView(ProjectScopedView):
    """GET /api/projects/<project_id>/runs/ - run history for a project.
    Supports ?status=/?branch=/?search= filters (TW-13), all combining
    with AND semantics when present together.

    distinct=True on every Count() is required, not optional: joining
    through test_cases__attempts for the Sum (duration lives two
    relations from Run) fans out each TestCase row once per Attempt it
    has, so an un-distinct'd Count('test_cases', filter=...) overcounts
    by that fan-out factor. Verified directly: a test case with 2
    attempts read as 2 flaky test cases, not 1, before distinct=True was
    added. Sum is unaffected by the same fan-out, since summing each
    attempt's own duration once is correct regardless of how many rows
    the join produces. See design.md for the full repro.

    branch/search are real .filter() calls against real columns - no
    null-guard needed: `branch = 'main'` against a NULL column evaluates
    to NULL (not true) in standard SQL, correctly excluding it without
    erroring, same for `commit_sha__icontains`. This is why every
    Run.branch is null today (the CLI never sends one - see #46):
    filtering still works correctly, it just has nothing real to match
    against yet.
    """

    def get(self, request, project_id):
        project = self._require_project_membership(request, project_id)

        status_param = request.query_params.get('status')
        if status_param is not None and status_param not in VALID_STATUSES:
            return Response(
                {'status': [f'must be one of: {", ".join(sorted(VALID_STATUSES))}']},
                status=400,
            )

        runs = Run.objects.filter(project=project).annotate(
            passed_count=Count('test_cases', filter=Q(test_cases__outcome='passed'), distinct=True),
            failed_count=Count('test_cases', filter=Q(test_cases__outcome='failed'), distinct=True),
            flaky_count=Count('test_cases', filter=Q(test_cases__outcome='flaky'), distinct=True),
            skipped_count=Count('test_cases', filter=Q(test_cases__outcome='skipped'), distinct=True),
            duration_ms=Coalesce(Sum('test_cases__attempts__duration_ms'), 0),
        )

        branch_param = request.query_params.get('branch')
        if branch_param is not None:
            runs = runs.filter(branch=branch_param)

        search_param = request.query_params.get('search')
        if search_param is not None:
            runs = runs.filter(commit_sha__icontains=search_param)

        runs = runs.order_by('-uploaded_at')

        if status_param is not None:
            # Derived value, not a column - can't push into .filter().
            # Applied last, in Python, on the already-DB-narrowed result
            # set so this only ever evaluates the rows that already
            # passed branch/search, not the full unfiltered table.
            runs = [run for run in runs if status_for(run) == status_param]

        return Response(RunListSerializer(runs, many=True).data)


class RunDetailView(APIView):
    """GET /api/runs/<run_id>/ - full detail for one run: header fields,
    computed status/counts (same status_for() precedence RunListView's
    ?status= filter and badge use), and every test_case/attempt/
    attachment nested three levels deep.

    Not an OrganizationScopedView subclass - this URL has a run_id, not
    an organization_id, so there's nothing to bind the usual class-level
    gate to. Resolves the run first, then reuses the SAME enumeration-
    safe membership check via a bare OrganizationScopedView() instance
    (_require_membership has no self-dependent state - see design.md)
    rather than writing a second copy of that 404-collapsing logic.
    """

    def get(self, request, run_id):
        run = get_object_or_404(
            Run.objects.select_related('project'), id=run_id,
        )
        if run.project is None:
            # Pre-TW-26 edge case: no project means no organization means
            # no membership path any non-staff user can ever satisfy.
            raise Http404

        OrganizationScopedView()._require_membership(request, run.project.organization_id)

        try:
            run = Run.objects.filter(id=run_id).annotate(
                passed_count=Count('test_cases', filter=Q(test_cases__outcome='passed'), distinct=True),
                failed_count=Count('test_cases', filter=Q(test_cases__outcome='failed'), distinct=True),
                flaky_count=Count('test_cases', filter=Q(test_cases__outcome='flaky'), distinct=True),
                skipped_count=Count('test_cases', filter=Q(test_cases__outcome='skipped'), distinct=True),
                duration_ms=Coalesce(Sum('test_cases__attempts__duration_ms'), 0),
            ).get()
        except Run.DoesNotExist:
            # Hardening noted during design review: no delete endpoint
            # for Run exists anywhere today, so this window isn't
            # exploitable yet, but .get() raising DoesNotExist here would
            # otherwise surface as an unhandled 500 rather than a 404 if
            # that ever changes.
            raise Http404

        return Response(RunDetailSerializer(run).data)
