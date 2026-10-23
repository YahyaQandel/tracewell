import logging

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from tokens.models import ApiToken, hash_token

logger = logging.getLogger(__name__)


class ApiTokenAuthentication(BaseAuthentication):
    """Authenticates `Authorization: Bearer <token>` against ApiToken.

    Returns None (does not raise) when no Bearer header is present at
    all - this authenticator "didn't attempt," consistent with DRF
    convention. It is the VIEW's responsibility (not this class, and not
    permission_classes) to require that `request.auth` ends up non-None
    when authentication is actually mandatory - see UploadRunView.
    Verified directly against DRF source (rest_framework.views.APIView
    .permission_denied): AllowAny never calls that denial path, so a
    missing-credential request would otherwise pass straight through
    with request.auth=None if the view didn't check for it itself.
    """

    def authenticate(self, request):
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer '):
            return None

        raw_token = header[len('Bearer '):]
        token_hash = hash_token(raw_token)
        try:
            token = ApiToken.objects.select_related('project').get(
                token_hash=token_hash, revoked_at__isnull=True,
            )
        except ApiToken.DoesNotExist:
            raise AuthenticationFailed('Invalid or revoked API token.')

        # Single UPDATE statement - no read-modify-write gap, so no race
        # to guard against (this is NOT an invariant-protecting check
        # like TW-25's last-owner guard; it's a bare informational
        # timestamp where a lost update under concurrency is harmless -
        # do not add select_for_update()/atomic() here). A failure here
        # must never block or roll back the upload itself - on this
        # project's SQLite backend (no busy-timeout configured), a
        # transient OperationalError on this statement is a real failure
        # class, and this write runs on every single authenticated
        # request, so it's wrapped and logged, never propagated.
        try:
            ApiToken.objects.filter(id=token.id).update(last_used_at=timezone.now())
        except Exception:
            logger.warning('Failed to update last_used_at for API token %s', token.id, exc_info=True)

        return (None, token)  # (user, auth): no Django User for a CI token

    def authenticate_header(self, request):
        # DRF's APIView.handle_exception silently coerces 401 -> 403 for
        # AuthenticationFailed/NotAuthenticated whenever
        # get_authenticate_header() returns falsy (BaseAuthentication's
        # default). Confirmed directly against DRF source
        # (rest_framework.views.APIView.handle_exception) and against
        # DRF's own built-in TokenAuthentication, which implements this
        # exact method for the same reason. Without this override, every
        # auth-failure case here would silently 403 instead of the 401
        # the CLI's httpClient.ts actually distinguishes on.
        return 'Bearer'
