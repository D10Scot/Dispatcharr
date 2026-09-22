"""The admin Stats UI's five control routes, at /proxy/ts/.

Split out of apps/proxy/live_proxy/urls.py by Phase 2 stage 2d-2 so the
routing leaves the directory stage 2d-4 deletes along with the views it
points at. The five paths and the five `name=` strings are byte-identical
to the ones they replace; apps/proxy/urls.py mounts this module at the same
`ts/` prefix, ahead of the `stream_routes` include that carries `stream/`
(it was `live_proxy`'s until stage 2d-4).

The app namespace is this module's own, in apps/proxy/relay_urls.py's
idiom. It is the one thing about these five routes that is not identical
across the move -- `proxy:live_proxy:stop_channel` becomes
`proxy:ts_admin:stop_channel` -- and nothing reverses them: `reverse(` does
not appear anywhere in the tree against any of these six names, and
frontend/src/api.js dials the literal paths (:2465, :2548, :2561, :2617,
:3317, :3334).
"""

from django.urls import path

from apps.proxy import ts_admin_views

app_name = 'ts_admin'

urlpatterns = [
    path('change_stream/<str:channel_id>', ts_admin_views.change_stream, name='change_stream'),
    path('status', ts_admin_views.channel_status, name='channel_status'),
    path('status/<str:channel_id>', ts_admin_views.channel_status, name='channel_status_detail'),
    path('stop/<str:channel_id>', ts_admin_views.stop_channel, name='stop_channel'),
    path('stop_client/<str:channel_id>', ts_admin_views.stop_client, name='stop_client'),
    path('next_stream/<str:channel_id>', ts_admin_views.next_stream, name='next_stream'),
]
