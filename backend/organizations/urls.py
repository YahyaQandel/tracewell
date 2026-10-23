from django.urls import path

from organizations.views import OrganizationListCreateView

urlpatterns = [
    path('', OrganizationListCreateView.as_view(), name='organization-list'),
]
