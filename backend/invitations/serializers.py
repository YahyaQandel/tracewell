from rest_framework import serializers

from invitations.models import Invitation


class InvitationSerializer(serializers.ModelSerializer):
    """Read shape - deliberately excludes `token`, which must only ever
    be delivered via the invitation email, never returned from a normal
    read (same "secret delivered once" principle as design.md's cited
    API-token precedent)."""

    class Meta:
        model = Invitation
        fields = ['id', 'organization', 'email', 'role', 'status', 'created_at']


class CreateInvitationSerializer(serializers.Serializer):
    """Write shape for POST. `role` explicitly restricts to admin/member -
    this is the real enforcement point: Django model field `choices` are
    NOT self-enforcing at `.objects.create()` time (only validated via
    `full_clean()`/forms, which `.objects.create()` never calls), so the
    model's matching `choices` is a second, non-load-bearing layer only -
    this serializer field is what actually rejects role='owner'."""

    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=[('admin', 'admin'), ('member', 'member')])
