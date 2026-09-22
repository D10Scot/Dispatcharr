"""The live-stream URL patterns Django keeps so the authorize hop can resolve.

Phase 2 stage 2d-4 deleted apps/proxy/live_proxy/, and with it stream_ts and
stream_xc -- the two views nginx has routed to the Go relay since 2d-3. The URL
PATTERNS cannot go with them, and the reason is not routing:

    apps/proxy/authorize_views.py's _surface_for() hands the URI in
    X-Original-URI to DJANGO'S OWN RESOLVER and keys on the matched view's
    __name__ ("stream_ts", "stream_xc"). Its comment says why it is written
    that way -- "rather than re-deriving each surface's URL shape here, a
    second copy of the urlconf, guaranteed to drift".

So with these patterns removed, every `auth_request` subrequest for a live tune
resolves to the SPA catch-all and authorize_view answers 403 -- in production,
on the one surface this whole phase exists to keep working. Measured: removing
them turns 22 tests in apps/proxy/tests red, all of them on the authorize hop.

These two callables therefore exist to BE RESOLVED, never to be called. nginx
sends /proxy/ts/stream/ and both XC live roots to the Go relay, so nothing
reaches them in any shape that runs nginx. The one shape that does not is
DISPATCHARR_ENV=dev, where docker/supervisord/all-dev.conf starts relay-go and
the Go relay serves the same paths on its own port (DISPATCHARR_RELAY_GO_PORT,
5658 by default) -- so a request arriving here is a developer pointing at the
wrong port, and saying so plainly is more useful than a 404 that looks like a
missing channel.
"""

import logging

from django.http import JsonResponse
from django.urls import path, re_path
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from dispatcharr.utils import XC_STREAM_ID_PATTERN

# "live_proxy", not "live_proxy.views": apps/proxy/next_source.py:34-38's
# precedent, and this is not a views module. Renaming it once the directory
# behind the name is gone is 2d-6's, which now has TWO sites -- this one and
# apps/proxy/ts_admin_views.py's (spec Amendment A12.4).
logger = logging.getLogger("live_proxy")

_MOVED = {
    "error": "This endpoint is served by the Go relay.",
    "detail": (
        "Phase 2 stage 2d-3 pointed nginx at the Go relay for /proxy/ts/stream/ "
        "and both Xtream live roots. Reaching Django here means no nginx is in "
        "front: in DISPATCHARR_ENV=dev, tune against the relay's own port "
        "(DISPATCHARR_RELAY_GO_PORT, 5658 by default)."
    ),
}


def _moved():
    # 501, not 404: a 404 is indistinguishable from an unknown channel, which
    # is the one thing a developer debugging a tune must not be told wrongly.
    return JsonResponse(_MOVED, status=501)


@csrf_exempt
@api_view(["GET", "HEAD"])
@permission_classes([AllowAny])
def stream_ts(request, channel_id):
    """Resolved by _surface_for as SURFACE_LIVE. Never called behind nginx."""
    logger.warning("stream_ts reached Django; the Go relay serves this route")
    return _moved()


@csrf_exempt
@api_view(["GET", "HEAD"])
@permission_classes([AllowAny])
def stream_xc(request, username, password, channel_id):
    """Resolved by _surface_for as SURFACE_LIVE_XC. Never called behind nginx."""
    logger.warning("stream_xc reached Django; the Go relay serves this route")
    return _moved()


# The namespace is UNCHANGED from apps/proxy/live_proxy/urls.py:4, deliberately:
# Global Constraint 6 is no behaviour change on a surviving surface, and
# `proxy:live_proxy:stream` is a reversible name even though nothing in the tree
# reverses it (`grep -rn "live_proxy:stream"` is empty, and
# apps/proxy/ts_admin_urls.py:11-13 records the same fact for its own six).
# Keeping it costs nothing; changing it would be an unstated contract change.
app_name = "live_proxy"

urlpatterns = [
    path("stream/<str:channel_id>", stream_ts, name="stream"),
]

# The two root-level Xtream live patterns, verbatim from dispatcharr/urls.py,
# spliced back into the root urlconf so the pattern text has one home.
# XC_STREAM_ID_PATTERN and \Z are load-bearing exactly as they were: Phase 1
# D7's three-segment regex trap is unchanged, and
# tests/test_urls_xc_three_segment.py still pins it.
xc_urlpatterns = [
    re_path(
        rf"^live/(?P<username>[^/]+)/(?P<password>[^/]+)/(?P<channel_id>{XC_STREAM_ID_PATTERN})\Z",
        stream_xc,
        name="xc_live_stream_endpoint",
    ),
    re_path(
        rf"^(?P<username>[^/]+)/(?P<password>[^/]+)/(?P<channel_id>{XC_STREAM_ID_PATTERN})\Z",
        stream_xc,
        name="xc_stream_endpoint",
    ),
]
