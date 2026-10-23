from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import OrganizationMembership
from organizations.views import OrganizationScopedView
from projects.models import Project
from projects.serializers import ProjectListSerializer, ProjectSerializer
from projects.slugs import slugify_project_name
from runs.models import Run


class ProjectScopedView(APIView):
    """Shared membership gate for every endpoint nested under
    /api/projects/<project_id>/ (project-level, not org-level - see
    OrganizationScopedView in organizations/views.py for the org-level
    equivalent this mirrors).

    A project has no membership model of its own - organization
    membership IS project access (per #23's design), so this checks the
    requesting user's OrganizationMembership against the project's
    organization. Collapses "project doesn't exist" and "project exists
    but you're not a member of its organization" to the same 404, for
    the same enumeration-safety reason OrganizationScopedView does -
    placed here (projects/views.py), not in tokens/ or any other leaf
    app, since project-scoping is a projects-level concern the same way
    org-scoping is organizations-level (same dependency-direction lesson
    TW-25's design review established for OrganizationScopedView: other
    future project-scoped endpoints should depend on this, not the
    reverse).
    """

    def _require_project_membership(self, request, project_id):
        is_member = OrganizationMembership.objects.filter(
            organization__projects__id=project_id, user=request.user,
        ).exists()
        if not is_member:
            raise Http404
        return get_object_or_404(Project, id=project_id)


class ProjectListCreateView(OrganizationScopedView):
    def get(self, request, organization_id):
        self._require_membership(request, organization_id)

        projects = Project.objects.filter(organization_id=organization_id)
        member_count = OrganizationMembership.objects.filter(
            organization_id=organization_id,
        ).count()

        # One query for every project in this org, ordered so the first
        # row per project_id encountered is the latest - avoids N+1 the
        # same way member_count does (single query, not one per project).
        # -id as a tiebreaker: uploaded_at has SQLite's coarser datetime
        # resolution, so two fast concurrent uploads could tie on
        # timestamp - without a secondary key, "latest" would pick
        # nondeterministically between them (flagged by code review).
        latest_run_by_project_id = {}
        for run in Run.objects.filter(
            project__organization_id=organization_id,
        ).order_by('project_id', '-uploaded_at', '-id'):
            latest_run_by_project_id.setdefault(run.project_id, run)

        serializer = ProjectListSerializer(
            projects, many=True,
            context={'member_count': member_count, 'latest_run_by_project_id': latest_run_by_project_id},
        )
        return Response(serializer.data, status=200)

    def post(self, request, organization_id):
        self._require_membership(request, organization_id)

        name = request.data.get('name') or ''
        slug = slugify_project_name(name)
        if not slug:
            return Response({'name': ['This field may not be blank.']}, status=400)

        try:
            with transaction.atomic():
                project = Project.objects.create(
                    organization_id=organization_id, name=name, slug=slug,
                )
        except IntegrityError:
            return Response(
                {'slug': ['A project with this identifier already exists in this organization.']},
                status=409,
            )

        return Response(ProjectSerializer(project).data, status=201)


class ProjectSlugPreviewView(OrganizationScopedView):
    def get(self, request, organization_id):
        self._require_membership(request, organization_id)

        name = request.query_params.get('name') or ''
        slug = slugify_project_name(name)
        if not slug:
            return Response({'name': ['This field may not be blank.']}, status=400)

        return Response({'slug': slug}, status=200)
