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
"""

import hashlib
import hmac

from django.conf import settings

RELAY_TRUST_CONTEXT = b"relay-trust"
INTERNAL_PRINCIPAL_CONTEXT = b"internal-principal"

# Wire names, for the two producers that spell headers rather than META
# keys: docker/init/03-init-dispatcharr.sh (nginx) and the DVR's ffmpeg
# -headers argument.
HEADER_AUTHORIZED = "X-Dispatcharr-Authorized"
HEADER_INTERNAL = "X-Dispatcharr-Internal"
HEADER_RELAY_CHANNEL = "X-Relay-Channel"
HEADER_RELAY_OUTPUT = "X-Relay-Output"
HEADER_RELAY_CLIENT = "X-Relay-Client"
HEADER_RELAY_USER = "X-Relay-User"
HEADER_RELAY_NAME = "X-Relay-Name"
# The real status of a denial nginx can only carry as 403. Read back by
# `auth_request_set $authorize_status $upstream_http_x_authorize_status`
# and turned into the client's status by `error_page 403 =
# @authorize_denied`.
HEADER_AUTHORIZE_STATUS = "X-Authorize-Status"

# request.META keys, which is how Django sees all of the above.
META_AUTHORIZED = "HTTP_X_DISPATCHARR_AUTHORIZED"
META_INTERNAL = "HTTP_X_DISPATCHARR_INTERNAL"
META_RELAY_CHANNEL = "HTTP_X_RELAY_CHANNEL"
META_RELAY_OUTPUT = "HTTP_X_RELAY_OUTPUT"
META_RELAY_CLIENT = "HTTP_X_RELAY_CLIENT"
META_RELAY_USER = "HTTP_X_RELAY_USER"
META_ORIGINAL_URI = "HTTP_X_ORIGINAL_URI"


def _token(context: bytes) -> str:
    secret = (settings.SECRET_KEY or "").encode()
    return hmac.new(secret, context, hashlib.sha256).hexdigest()


def relay_trust_token() -> str:
    """The value nginx puts in X-Dispatcharr-Authorized."""
    return _token(RELAY_TRUST_CONTEXT)


def internal_principal_token() -> str:
    """The value an in-deployment caller puts in X-Dispatcharr-Internal."""
    return _token(INTERNAL_PRINCIPAL_CONTEXT)


def _matches(value, expected: str) -> bool:
    if not isinstance(value, str) or not value or not expected:
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
