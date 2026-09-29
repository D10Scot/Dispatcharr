from django.urls import path

from .api_views import MinoCapabilitiesView

app_name = "mino"

urlpatterns = [
    path("capabilities/", MinoCapabilitiesView.as_view(), name="capabilities"),
]
