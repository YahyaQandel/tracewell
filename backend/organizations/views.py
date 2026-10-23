from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.exceptions import LastOwnerError
from organizations.models import Organization, OrganizationMembership
from organizations.permissions import require_role
from organizations.serializers import (
    CreateOrganizationSerializer,
    OrganizationMembershipSerializer,
    OrganizationSerializer,
)


class OrganizationScopedView(APIView):
    """Shared membership gate for every endpoint nested under
    /api/organizations/<organization_id>/.

    Collapses "organization doesn't exist" and "organization exists but
    you're not a member" to the same 404 - returning 403 for the second
    case would let an authenticated user enumerate which organization
    IDs are real by watching for a 403-vs-404 split, which is exactly
    the kind of leak a multi-tenant app (this epic's whole reason for
    existing) must not have.

    Relocated here from projects/views.py (TW-23) in TW-25: organizations
    is this codebase's dependency root (projects/models.py imports from
    organizations.models, never the reverse), so a shared org-membership
    gate belongs here, not in a leaf app - see design.md's "OrganizationScopedView
    relocation" section for the full rationale.
    """

    def _require_membership(self, request, organization_id):
        membership = OrganizationMembership.objects.filter(
            organization_id=organization_id, user=request.user,
        ).first()
        if membership is None:
            raise Http404
        return membership


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


class MembershipDetailView(OrganizationScopedView):
    def patch(self, request, organization_id, membership_id):
        membership = self._require_membership(request, organization_id)
        require_role(membership, 'owner')

        target = get_object_or_404(OrganizationMembership, id=membership_id, organization_id=organization_id)
        new_role = request.data.get('role')
        if new_role not in ('owner', 'admin', 'member'):
            return Response({'role': ['Must be one of owner, admin, member.']}, status=400)

        if target.role == 'owner' and new_role != 'owner':
            try:
                with transaction.atomic():
                    _assert_not_last_owner(organization_id, exclude_membership_id=target.id)
                    target.role = new_role
                    target.save(update_fields=['role'])
            except LastOwnerError:
                return Response(
                    {'role': ['Cannot change the role of the organization\'s last remaining owner.']},
                    status=400,
                )
        else:
            target.role = new_role
            target.save(update_fields=['role'])
        return Response(OrganizationMembershipSerializer(target).data)

    def delete(self, request, organization_id, membership_id):
        membership = self._require_membership(request, organization_id)
        require_role(membership, 'owner')

        target = get_object_or_404(OrganizationMembership, id=membership_id, organization_id=organization_id)
        if target.role == 'owner':
            try:
                with transaction.atomic():
                    _assert_not_last_owner(organization_id, exclude_membership_id=target.id)
                    target.delete()
            except LastOwnerError:
                return Response(
                    {'role': ['Cannot remove the organization\'s last remaining owner.']},
                    status=400,
                )
        else:
            target.delete()
        return Response(status=204)


def _assert_not_last_owner(organization_id, exclude_membership_id):
    """Must be called inside a transaction.atomic() block, with the
    mutation of the target row happening before that block ends (so the
    lock taken here is held through the mutation, not released before it).

    PREVIOUS BUG (caught by a second-round fresh review, reproduced on
    real Postgres, confirmed to be a no-op on SQLite): this used to
    .exclude(id=exclude_membership_id) BEFORE locking, which locks only
    the *other* owner rows, not the full owner set. Two concurrent
    requests demoting/removing two DIFFERENT owners of the same org each
    exclude a different row, so their lock sets are disjoint and never
    contend - the lock provided zero serialization between them, and both
    could pass the "am I the last owner" check and both commit, leaving
    zero owners.

    Fix: lock every owner row for the organization FIRST (no exclude), so
    two concurrent mutations of any two owner rows in the same org always
    contend for an overlapping lock set and are forced to serialize - the
    second request's count only runs after the first's transaction (which
    already changed its target's role away from 'owner', or deleted it)
    has committed. The exclude happens only in the count itself, after
    the lock on the full set is already held.
    """
    owner_ids = list(
        OrganizationMembership.objects.select_for_update().filter(
            organization_id=organization_id, role='owner',
        ).values_list('id', flat=True)
    )
    remaining_owners = len(owner_ids) - (1 if exclude_membership_id in owner_ids else 0)
    if remaining_owners <= 0:
        raise LastOwnerError()
