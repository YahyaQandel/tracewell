from django.urls import path

from organizations.views import MembershipDetailView, OrganizationListCreateView

urlpatterns = [
    path('', OrganizationListCreateView.as_view(), name='organization-list'),
    path(
        '<uuid:organization_id>/members/<uuid:membership_id>/',
        MembershipDetailView.as_view(),
        name='membership-detail',
    ),
]
