from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from invitations.emails import send_invitation_email
from invitations.models import Invitation
from invitations.serializers import CreateInvitationSerializer, InvitationSerializer
from organizations.models import OrganizationMembership
from organizations.permissions import require_role
from organizations.views import OrganizationScopedView


class InvitationListCreateView(OrganizationScopedView):
    def get(self, request, organization_id):
        self._require_membership(request, organization_id)
        invitations = Invitation.objects.filter(
            organization_id=organization_id, status='pending',
        )
        return Response(InvitationSerializer(invitations, many=True).data)

    def post(self, request, organization_id):
        membership = self._require_membership(request, organization_id)
        require_role(membership, 'owner', 'admin')

        serializer = CreateInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data['email']
        role = serializer.validated_data['role']

        if OrganizationMembership.objects.filter(
            organization_id=organization_id, user__email__iexact=email,
        ).exists():
            return Response({'email': ['This person already has access to the organization.']}, status=400)

        existing_pending = Invitation.objects.filter(
            organization_id=organization_id, email=email, status='pending',
        ).first()
        if existing_pending is not None:
            return Response({'email': ['An invitation is already pending for this email.']}, status=400)

        invitation = Invitation.objects.create(
            organization_id=organization_id, email=email, role=role, invited_by=request.user,
        )
        send_invitation_email(invitation)
        return Response(InvitationSerializer(invitation).data, status=201)


class InvitationRevokeView(OrganizationScopedView):
    def post(self, request, organization_id, invitation_id):
        membership = self._require_membership(request, organization_id)
        require_role(membership, 'owner', 'admin')

        invitation = get_object_or_404(
            Invitation, id=invitation_id, organization_id=organization_id, status='pending',
        )
        invitation.status = 'revoked'
        invitation.save(update_fields=['status'])
        return Response(status=204)


class InvitationAcceptView(APIView):
    """Not organization-scoped - the acceptor isn't a member yet."""

    def post(self, request):
        token = request.data.get('token') or ''
        invitation = Invitation.objects.filter(token=token, status='pending').first()
        if invitation is None:
            raise Http404

        try:
            with transaction.atomic():
                OrganizationMembership.objects.create(
                    organization=invitation.organization, user=request.user, role=invitation.role,
                )
                invitation.status = 'accepted'
                invitation.accepted_at = timezone.now()
                invitation.save(update_fields=['status', 'accepted_at'])
        except IntegrityError:
            return Response(
                {'token': ['You already have access to this organization.']},
                status=409,
            )

        return Response(status=204)
