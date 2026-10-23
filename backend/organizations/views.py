from django.db import transaction
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import Organization, OrganizationMembership
from organizations.serializers import CreateOrganizationSerializer, OrganizationSerializer


class OrganizationListCreateView(APIView):
    """GET/POST /api/organizations/.

    AC2/AC4: creating an organization atomically creates the creator's
    owner membership in the same transaction - no organization can exist
    with zero owners because membership-row creation failed after the
    organization row committed (same pattern as TW-2's run-creation).
    """

    def get(self, request):
        memberships = (
            OrganizationMembership.objects
            .filter(user=request.user)
            .select_related('organization')
        )
        organizations = []
        for membership in memberships:
            organization = membership.organization
            organization.requesting_user_role = membership.role
            organizations.append(organization)

        serializer = OrganizationSerializer(organizations, many=True)
        return Response(serializer.data, status=200)

    def post(self, request):
        write_serializer = CreateOrganizationSerializer(data=request.data)
        write_serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            organization = write_serializer.save()
            OrganizationMembership.objects.create(
                organization=organization,
                user=request.user,
                role='owner',
            )

        organization.requesting_user_role = 'owner'
        serializer = OrganizationSerializer(organization)
        return Response(serializer.data, status=201)
