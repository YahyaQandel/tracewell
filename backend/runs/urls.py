from django.urls import path

from runs.views import RunDetailView, UploadRunView

app_name = 'runs'

urlpatterns = [
    path('runs/', UploadRunView.as_view(), name='upload'),
    path('runs/<uuid:run_id>/', RunDetailView.as_view(), name='detail'),
]
