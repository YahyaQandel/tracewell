from rest_framework.exceptions import PermissionDenied


def require_role(membership, *allowed_roles):
    """Raise PermissionDenied if membership.role not in allowed_roles."""
    if membership.role not in allowed_roles:
        raise PermissionDenied()
