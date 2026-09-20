from django.urls import path
from . import views

app_name = 'live_proxy'

urlpatterns = [
    path('stream/<str:channel_id>', views.stream_ts, name='stream'),
]
