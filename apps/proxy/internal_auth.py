"""Two context-separated HMACs of SECRET_KEY, and the headers that carry them.

Phase 1 D11. Every internal hop in the split authenticates with an HMAC of
the deployment's own SECRET_KEY, compared with hmac.compare_digest:

  X-Dispatcharr-Authorized = HMAC(SECRET_KEY, "relay-trust")
      nginx sets it on every relay-bound location so the relay will trust
      the X-Relay-* params. It is a secret, not the literal "1", because
      nginx is not always in front of the relay's port: uwsgi's
      http = 0.0.0.0:5656 is published in dev and debug, and the relay's
      own :5657 is reachable from anywhere on a compose network.

  X-Dispatcharr-Internal = HMAC(SECRET_KEY, "internal-principal")
      "this caller is part of this deployment" — the DVR's stream fetch
      here, and /api/relay/... and /proxy/relay/... in PR 6 and PR 7.

Distinct context strings so a marker leaked through a config file nginx
reads cannot be replayed as an internal principal.

Both roles derive the same values because docker/entrypoint.sh generates
/data/jwt once and every role reads it from the same volume — a deployment
fact, which is why docker/docker-compose.yml's relay service mounts
./data:/data.

Wire contract: the HMAC key is the UTF-8 bytes of DJANGO_SECRET_KEY exactly
as docker/entrypoint.sh:138 exports it (`tr -d '\r\n' < /data/jwt`); the
nginx-side RELAY_TRUST_TOKEN computed in docker/init/03-init-dispatcharr.sh
must read the same environment variable and encode it the same way, or the
two sides derive different tokens and every nginx-authorized tune falls
through to the inline path.
"""

import hashlib
import hmac
import time

from django.conf import settings

RELAY_TRUST_CONTEXT = b"relay-trust"
INTERNAL_PRINCIPAL_CONTEXT = b"internal-principal"
# A third context, for the *bound* form of the internal principal. The
# static token above is long-lived and shared by every internal caller
# (issue #181); this one binds a single request — method, path, body — and
# expires. /api/relay/... (PR 6) and /proxy/relay/... (PR 7) require both:
# the static header says "part of this deployment", the bound one says
# "and this exact call, just now". The DVR's stream fetch deliberately
# sends only the static header, because ffmpeg re-sends its -headers line
# on every reconnect for the life of a recording and a windowed token
# would 403 the reconnect.
INTERNAL_REQUEST_CONTEXT = b"internal-request"
INTERNAL_REQUEST_WINDOW_SECONDS = 120

# Wire names, for the two producers that spell headers rather than META
# keys: docker/init/03-init-dispatcharr.sh (nginx) and the DVR's ffmpeg
# -headers argument.
HEADER_AUTHORIZED = "X-Dispatcharr-Authorized"
HEADER_INTERNAL = "X-Dispatcharr-Internal"
HEADER_INTERNAL_REQUEST = "X-Dispatcharr-Internal-Request"
HEADER_RELAY_CHANNEL = "X-Relay-Channel"
HEADER_RELAY_OUTPUT = "X-Relay-Output"
HEADER_RELAY_CLIENT = "X-Relay-Client"
HEADER_RELAY_USER = "X-Relay-User"
HEADER_RELAY_NAME = "X-Relay-Name"
# 2b-2. The hop resolves both once so the relay never re-queries: the
# output format used to cost a User row inside the relay process
# (authorize_views.result_from_headers), and the client address cannot
# be derived from REMOTE_ADDR by a relay nginx proxy_passes to rather
# than uwsgi_passes to (spec § Stage 2d, NB1).
HEADER_RELAY_OUTPUT_FORMAT = "X-Relay-Output-Format"
HEADER_RELAY_CLIENT_IP = "X-Relay-Client-IP"
# The real status of a denial nginx can only carry as 403. Read back by
# `auth_request_set $authorize_status $upstream_http_x_authorize_status`
# and turned into the client's status by `error_page 403 =
# @authorize_denied`.
HEADER_AUTHORIZE_STATUS = "X-Authorize-Status"

# request.META keys, which is how Django sees all of the above.
META_AUTHORIZED = "HTTP_X_DISPATCHARR_AUTHORIZED"
META_INTERNAL = "HTTP_X_DISPATCHARR_INTERNAL"
META_INTERNAL_REQUEST = "HTTP_X_DISPATCHARR_INTERNAL_REQUEST"
META_RELAY_CHANNEL = "HTTP_X_RELAY_CHANNEL"
META_RELAY_OUTPUT = "HTTP_X_RELAY_OUTPUT"
META_RELAY_CLIENT = "HTTP_X_RELAY_CLIENT"
META_RELAY_USER = "HTTP_X_RELAY_USER"
META_RELAY_OUTPUT_FORMAT = "HTTP_X_RELAY_OUTPUT_FORMAT"
META_RELAY_CLIENT_IP = "HTTP_X_RELAY_CLIENT_IP"
META_ORIGINAL_URI = "HTTP_X_ORIGINAL_URI"


def _token(context: bytes) -> str:
    # settings.SECRET_KEY access itself raises ImproperlyConfigured on an
    # empty or missing key (Django 6), so there is no empty-secret case to
    # guard against here.
    secret = settings.SECRET_KEY.encode()
    return hmac.new(secret, context, hashlib.sha256).hexdigest()


def relay_trust_token() -> str:
    """The value nginx puts in X-Dispatcharr-Authorized."""
    return _token(RELAY_TRUST_CONTEXT)


def internal_principal_token() -> str:
    """The value an in-deployment caller puts in X-Dispatcharr-Internal."""
    return _token(INTERNAL_PRINCIPAL_CONTEXT)


def _matches(value, expected: str) -> bool:
    # WSGI/uWSGI hand header values to Django as latin-1 decoded str, so a
    # byte >= 0x80 from a client reaching uwsgi's :5656 (published in
    # dev/debug) or the relay's own :5657 directly (any compose peer) can
    # land here. hmac.compare_digest raises on non-ASCII str, so exclude it
    # before comparing rather than let a malformed header turn into a 500.
    if not isinstance(value, str) or not value or not expected or not value.isascii():
        return False
    return hmac.compare_digest(value, expected)


def request_is_relay_trusted(request) -> bool:
    """True when nginx authorized this request and set the marker itself.

    nginx overrides a client's own header of the same name in every
    relay-bound location and blanks it everywhere else (the 0.8.40
    HTTP_-prefixed *_param rule), so a "" here is a request that was never
    authorized and must fall through to an inline authorize_stream call.
    """
    return _matches(request.META.get(META_AUTHORIZED), relay_trust_token())


def request_is_internal(request) -> bool:
    """True when the caller proved it holds this deployment's SECRET_KEY."""
    return _matches(request.META.get(META_INTERNAL), internal_principal_token())


def internal_request_token(method: str, path: str, body: bytes, timestamp: int) -> str:
    """The hex digest half of X-Dispatcharr-Internal-Request.

    Signed over the method, the path, the timestamp and a digest of the
    body, so a captured call cannot be replayed against another route or
    with different arguments, and cannot be replayed at all once the
    window closes.

    Replay INSIDE the window is possible and accepted: there is no nonce.
    The effect is bounded — a replayed next-source is idempotent, since
    Channel.get_stream() reuses a live assignment and reports
    slot_reserved=False, and the worst case is a replayed release after a
    new tune re-reserved, which under-counts one provider slot until that
    channel's next release. A nonce store would put Redis on the verify
    path, and an attacker positioned to capture on the internal network
    already holds the static X-Dispatcharr-Internal token.
    """
    message = b"\n".join(
        [
            INTERNAL_REQUEST_CONTEXT,
            method.upper().encode(),
            path.encode(),
            str(int(timestamp)).encode(),
            hashlib.sha256(body or b"").hexdigest().encode(),
        ]
    )
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def build_internal_request_header(method: str, path: str, body: bytes) -> str:
    """The full header value a caller sends. Used by control_plane and PR 7.

    `path` is the full path the caller will request, query string
    included — `request.get_full_path()` on the other side.
    """
    timestamp = int(time.time())
    return f"v1.{timestamp}.{internal_request_token(method, path, body, timestamp)}"


def request_is_internal_request(request) -> bool:
    """True when this exact request was signed, recently, with SECRET_KEY."""
    raw = request.META.get(META_INTERNAL_REQUEST)
    if not isinstance(raw, str) or not raw.isascii():
        return False
    parts = raw.split(".")
    if len(parts) != 3 or parts[0] != "v1":
        return False
    try:
        timestamp = int(parts[1])
    except ValueError:
        return False
    if abs(int(time.time()) - timestamp) > INTERNAL_REQUEST_WINDOW_SECONDS:
        return False
    expected = internal_request_token(
        # get_full_path(), not path: the query string is part of what a
        # caller is asking for, so it has to be part of what the token
        # binds (PR 7). They are the same string when there is no query,
        # which is why every call PR 6 shipped verifies unchanged.
        request.method, request.get_full_path(), request.body, timestamp
    )
    return _matches(parts[2], expected)
