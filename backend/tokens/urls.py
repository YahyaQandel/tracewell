from django.urls import path

from tokens.views import TokenListCreateView, TokenRevokeView

urlpatterns = [
    path('', TokenListCreateView.as_view(), name='token-list'),
    path('<uuid:token_id>/revoke/', TokenRevokeView.as_view(), name='token-revoke'),
]
