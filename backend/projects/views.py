from django.db import IntegrityError, transaction
from django.http import Http404
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import OrganizationMembership
from projects.models import Project
from projects.serializers import ProjectListSerializer, ProjectSerializer
from projects.slugs import slugify_project_name


class OrganizationScopedView(APIView):
    """Shared membership gate for every endpoint nested under
    /api/organizations/<organization_id>/.

    Collapses "organization doesn't exist" and "organization exists but
    you're not a member" to the same 404 - returning 403 for the second
    case would let an authenticated user enumerate which organization
    IDs are real by watching for a 403-vs-404 split, which is exactly
    the kind of leak a multi-tenant app (this epic's whole reason for
    existing) must not have.
    """

    def _require_membership(self, request, organization_id):
        membership = OrganizationMembership.objects.filter(
            organization_id=organization_id, user=request.user,
        ).first()
        if membership is None:
            raise Http404
        return membership


class ProjectListCreateView(OrganizationScopedView):
    def get(self, request, organization_id):
        self._require_membership(request, organization_id)

        projects = Project.objects.filter(organization_id=organization_id)
        member_count = OrganizationMembership.objects.filter(
            organization_id=organization_id,
        ).count()

        serializer = ProjectListSerializer(
            projects, many=True, context={'member_count': member_count},
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
