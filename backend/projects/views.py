from django.db import IntegrityError, transaction
from rest_framework.response import Response

from organizations.models import OrganizationMembership
from organizations.views import OrganizationScopedView
from projects.models import Project
from projects.serializers import ProjectListSerializer, ProjectSerializer
from projects.slugs import slugify_project_name


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
