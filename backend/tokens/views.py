from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response

from projects.views import ProjectScopedView
from tokens.models import RAW_TOKEN_PREFIX, ApiToken, generate_raw_token, hash_token
from tokens.serializers import ApiTokenSerializer, CreateApiTokenSerializer


class TokenListCreateView(ProjectScopedView):
    def get(self, request, project_id):
        self._require_project_membership(request, project_id)
        tokens = ApiToken.objects.filter(project_id=project_id, revoked_at__isnull=True)
        return Response(ApiTokenSerializer(tokens, many=True).data)

    def post(self, request, project_id):
        project = self._require_project_membership(request, project_id)
        serializer = CreateApiTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        raw_token = generate_raw_token()
        token = ApiToken.objects.create(
            project=project,
            name=serializer.validated_data['name'],
            created_by=request.user,
            token_hash=hash_token(raw_token),
            display_prefix=raw_token[:len(RAW_TOKEN_PREFIX) + 4],
            display_suffix=raw_token[-4:],
        )
        return Response(
            {**ApiTokenSerializer(token).data, 'token': raw_token},
            status=201,
        )


class TokenRevokeView(ProjectScopedView):
    def post(self, request, project_id, token_id):
        self._require_project_membership(request, project_id)
        token = get_object_or_404(
            ApiToken, id=token_id, project_id=project_id, revoked_at__isnull=True,
        )
        token.revoked_at = timezone.now()
        token.save(update_fields=['revoked_at'])
        return Response(status=204)
