from django.urls import path

from projects.views import ProjectListCreateView, ProjectSlugPreviewView

urlpatterns = [
    path('', ProjectListCreateView.as_view(), name='project-list'),
    path('slug-preview/', ProjectSlugPreviewView.as_view(), name='project-slug-preview'),
]
