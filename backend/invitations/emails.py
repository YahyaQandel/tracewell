from django.core.mail import send_mail


def send_invitation_email(invitation):
    """Thin wrapper around send_mail so the view doesn't know which
    backend is configured - swapping console -> real SMTP later is a
    settings.py EMAIL_BACKEND change only, zero view/test changes needed.

    Must be called after Invitation.objects.create() succeeds, never
    wrapped in the same transaction.atomic() block as the row creation -
    sending an email is not a DB operation and must never be rolled back
    by one.
    """
    send_mail(
        subject=f"You've been invited to join {invitation.organization.name} on Tracewell",
        message=(
            f"You've been invited to join {invitation.organization.name} "
            f"as a {invitation.role}. Accept using this token: {invitation.token}"
        ),
        from_email=None,
        recipient_list=[invitation.email],
    )
