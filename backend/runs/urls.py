from django.urls import path

from runs.views import UploadRunView

app_name = 'runs'

urlpatterns = [
    path('runs/', UploadRunView.as_view(), name='upload'),
]
