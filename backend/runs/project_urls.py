from django.urls import path

from runs.views import RunListView

urlpatterns = [
    path('runs/', RunListView.as_view(), name='run-list'),
]
