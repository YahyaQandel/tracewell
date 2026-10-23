from rest_framework import serializers

from organizations.models import Organization, OrganizationMembership


class OrganizationSerializer(serializers.ModelSerializer):
    """Read shape for GET/POST responses — role is read-only here."""
    role = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ['id', 'name', 'role']

    def get_role(self, organization):
        # Annotated onto each Organization instance by the view
        # (per-request-user role lives on the membership row, not on
        # Organization itself - see design.md).
        return getattr(organization, 'requesting_user_role', None)


class OrganizationMembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationMembership
        fields = ['id', 'organization', 'user', 'role']


class CreateOrganizationSerializer(serializers.ModelSerializer):
    """Write shape for POST — AC5's empty/missing-name validation lives
    here (CharField's default allow_blank=False), not hand-rolled in the
    view, so it's the single place name validation can be found or
    extended."""

    class Meta:
        model = Organization
        fields = ['name']
