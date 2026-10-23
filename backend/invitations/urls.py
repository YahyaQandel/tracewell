from django.urls import path

from invitations.views import InvitationListCreateView, InvitationRevokeView

urlpatterns = [
    path('', InvitationListCreateView.as_view(), name='invitation-list'),
    path('<uuid:invitation_id>/revoke/', InvitationRevokeView.as_view(), name='invitation-revoke'),
]
