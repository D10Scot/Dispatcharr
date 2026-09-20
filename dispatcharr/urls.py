from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView, RedirectView
from .routing import websocket_urlpatterns
from apps.output.views import xc_player_api, xc_panel_api, xc_get, xc_xmltv
from apps.proxy.authorize_views import authorize_internal_view, authorize_view
from apps.proxy import stream_routes
from apps.proxy.vod_proxy.views import stream_xc_movie, stream_xc_episode
from apps.timeshift.views import timeshift_proxy, timeshift_proxy_query
from dispatcharr.utils import XC_STREAM_ID_PATTERN

urlpatterns = [
    # API Routes
    path("api/", include(("apps.api.urls", "api"), namespace="api")),
    path("api", RedirectView.as_view(url="/api/", permanent=True)),
    # Swagger redirects (Swagger UI is served at /api/swagger/)
    path("swagger/", RedirectView.as_view(url="/api/swagger/", permanent=True)),
    path("swagger", RedirectView.as_view(url="/api/swagger/", permanent=True)),
    path("redoc/", RedirectView.as_view(url="/api/redoc/", permanent=True)),
    path("redoc", RedirectView.as_view(url="/api/redoc/", permanent=True)),
    # Outputs
    path("output", RedirectView.as_view(url="/output/", permanent=True)),
    path("output/", include(("apps.output.urls", "output"), namespace="output")),
    # HDHR
    path("hdhr", RedirectView.as_view(url="/hdhr/", permanent=True)),
    path("hdhr/", include(("apps.hdhr.urls", "hdhr"), namespace="hdhr")),
    # Add proxy apps - Move these before the catch-all
    path("proxy/", include(("apps.proxy.urls", "proxy"), namespace="proxy")),
    path("proxy", RedirectView.as_view(url="/proxy/", permanent=True)),
    # Internal: nginx's auth_request target (Phase 1 PR 5, ADR 0005). The
    # nginx location is `internal;`, so this is unreachable from outside
    # the container in every shape that runs nginx; in dev, where nothing
    # runs nginx, the stream views authorize inline and never call it.
    path("_dispatcharr/authorize", authorize_view, name="authorize"),
    # Internal: the Go relay's dev fallback (Phase 2 spec D5, exception 2).
    # ITS OWN PATH, deliberately not the one above: `= /_dispatcharr/authorize`
    # is an `internal;` exact-match location in docker/nginx.conf, so a POST
    # to it is 404'd by nginx before Django sees it in every nginx-fronted
    # shape -- which would turn a SECRET_KEY mismatch between roles from
    # today's silent-but-working degrade into every live tune failing.
    # Registered unconditionally, because Django cannot know at boot whether
    # the relay it will talk to has nginx in front of it; gated by
    # IsInternalRelay, which is the only protection it has since it sits
    # outside nginx's shield by design.
    path(
        "_dispatcharr/authorize-internal",
        authorize_internal_view,
        name="authorize-internal",
    ),
    # xc
    re_path("player_api.php", xc_player_api, name="xc_player_api"),
    re_path("panel_api.php", xc_panel_api, name="xc_panel_api"),
    re_path("get.php", xc_get, name="xc_get"),
    re_path("xmltv.php", xc_xmltv, name="xc_xmltv"),
    # The two XC live-stream patterns, unchanged in shape and moved to
    # apps/proxy/stream_routes.py with the view they name. Phase 2 stage 2d-4
    # deleted apps/proxy/live_proxy/views.py's stream_xc, and nginx has served
    # both shapes from the Go relay since 2d-3 -- but the PATTERNS cannot go,
    # and the reason is not routing: apps/proxy/authorize_views.py's
    # _surface_for() hands the URI in X-Original-URI to DJANGO'S OWN RESOLVER
    # and keys on the matched view's __name__. Remove them and every
    # auth_request subrequest for an XC live tune resolves to the SPA catch-all
    # and authorize_view answers 403 -- in production. XC_STREAM_ID_PATTERN and
    # \Z are therefore load-bearing exactly as before (Phase 1 D7's
    # three-segment regex trap), and tests/test_urls_xc_three_segment.py still
    # pins them. See apps/proxy/stream_routes.py's header.
    *stream_routes.xc_urlpatterns,
    path(
        "timeshift/<str:username>/<str:password>/<str:duration>/<str:timestamp>/<str:channel_id>",
        timeshift_proxy,
        name="timeshift_proxy",
    ),
    path(
        "streaming/timeshift.php",
        timeshift_proxy_query,
        name="timeshift_proxy_query",
    ),
    # XC VOD endpoints
    path(
        "movie/<str:username>/<str:password>/<str:stream_id>.<str:extension>",
        stream_xc_movie,
        name="stream_xc_movie",
    ),
    path(
        "series/<str:username>/<str:password>/<str:stream_id>.<str:extension>",
        stream_xc_episode,
        name="stream_xc_episode",
    ),
    # Admin
    path("admin", RedirectView.as_view(url="/admin/", permanent=True)),
    path("admin/", admin.site.urls),

    # VOD proxy is now handled by the main proxy URLs above
    # Catch-all routes should always be last
    path("", TemplateView.as_view(template_name="index.html")),  # React entry point
    path("<path:unused_path>", TemplateView.as_view(template_name="index.html")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += websocket_urlpatterns

# Serve static files for development (React's JS, CSS, etc.)
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
