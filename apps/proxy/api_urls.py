"""Internal control-plane routes the relay calls (Phase 1 D12).

Mounted at /api/relay/ from apps/api/urls.py. Not part of the client API:
IsInternalRelay, no principal, no IsAdmin. nginx serves them through the
existing `location ^~ /api/` block, which carries the blanking include —
it blanks the four X-Relay-* params and the X-Dispatcharr-Authorized
marker, and leaves the two internal headers alone, which is exactly
right here.
"""

from django.urls import path

from apps.proxy import api_views

app_name = "relay"

urlpatterns = [
    path(
        "channels/<str:identifier>/next-source",
        api_views.next_source_view,
        name="next-source",
    ),
    path(
        "channels/<str:identifier>/release",
        api_views.release_view,
        name="release",
    ),
    path("events", api_views.events_view, name="events"),
]
