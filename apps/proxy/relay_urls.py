"""The relay control API's routes (Phase 1 D12).

Mounted at /proxy/relay/ from apps/proxy/urls.py, so they are served by
whichever process nginx sends /proxy/relay/ to -- the relay (D5, D14).
No trailing slashes, matching apps/proxy/live_proxy/urls.py, which is
what makes nginx's `location ^~ /proxy/relay/` prefix sufficient and
keeps APPEND_SLASH out of the internal contract.
"""

from django.urls import path

from apps.proxy import relay_views

app_name = "relay_control"

urlpatterns = [
    path("channels", relay_views.channels_view, name="channels"),
    path(
        "channels/<str:identifier>",
        relay_views.channel_view,
        name="channel",
    ),
    path(
        "channels/<str:identifier>/clients/<str:client_id>",
        relay_views.channel_client_view,
        name="channel-client",
    ),
    path(
        "channels/<str:identifier>/advance",
        relay_views.channel_advance_view,
        name="channel-advance",
    ),
]
