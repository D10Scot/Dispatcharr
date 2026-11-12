"""Discovery and JWKS fetching (SSO spec section 3.5, D22).

Every server-side fetch passes ``core/http_security.py``: ``fetch_outbound_http`` with
``max_redirects=0`` for discovery and JWKS, ``validate_outbound_http_url`` for the token
endpoint (``fetch_outbound_http`` is GET only). Endpoints named by the IdP's own document are
checked at every use, not only when the provider is saved. Failures are fixed codes: neither
the helper's message (it names the resolved address) nor an exception's text is returned or
logged, only the exception class and an HTTP status.
"""

import json
import logging
import time
from urllib.parse import urlparse

import redis
import requests
import urllib3
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django_redis.exceptions import ConnectionInterrupted

from core.http_security import fetch_outbound_http, validate_outbound_http_url

logger = logging.getLogger(__name__)

MAX_BYTES = 1024 * 1024  # 1 MiB, enforced while streaming
TIMEOUT = (5, 10)  # connect, read
# TOTAL_DEADLINE bounds one whole outbound exchange (discovery, JWKS, the token POST): DNS,
# connect, the request, the response headers and the body, measured from just before the
# request starts. How it is enforced depends on the process:
# - under gevent's socket monkey-patching (the uWSGI API workers, which serve every caller:
#   the admin "test" action, start, link/start and the callback) ``run_bounded`` arms one
#   ``gevent.Timeout`` around the whole call. Every socket wait there is a cooperative wait,
#   so the timer interrupts the call wherever it waits, and the exchange answers its fixed
#   "unreachable"/"token_exchange_failed" code at the deadline. The tests drive a dripped
#   header read and a dripped body read; name resolution and the connect sit under the same
#   timer but no test stalls them. Measured (apps/accounts/tests/test_oidc_outbound_deadline.py, a 1.5 s deadline, one
#   byte per 0.1 s): dripped headers and a dripped gzip body each ended at 1.50-1.51 s,
#   where without gevent the same calls ran 8.1 s (as long as the server dripped) and
#   5.2 s;
# - without it (``manage.py runserver``, a management command, Celery, Daphne, the test
#   runner itself) nothing can interrupt a blocking read, and no thread or signal is added
#   to try. There the old bounds still apply and only they: TIMEOUT per connect and per
#   receive, and the deadline checked between body reads. Headers dripped just inside the
#   read timeout still hold such a request for as long as the server keeps dripping (a
#   review measured 55.6 s at one byte per 0.7 s), and the body can overrun the deadline by
#   one read, longer for a compressed body because urllib3's read1 keeps receiving until
#   the decoder yields output (24.2 s measured for gzip dripped at one byte per second).
#   No production caller runs there today.
TOTAL_DEADLINE = 15
READ_SIZE = 65536
CACHE_TTL = 3600
JWKS_REFETCH_COOLDOWN = 60
WELL_KNOWN = "/.well-known/openid-configuration"

_REDIRECT_MESSAGES = ("More than ", "Redirect without a Location")
# A cache outage: django-redis raises redis' own errors, or ConnectionInterrupted in older
# versions. A cache failure is a miss, never a 500; the flow's own Redis store decides
# whether a login can proceed.
CACHE_ERRORS = (redis.RedisError, ConnectionInterrupted)


def release_db_connection():
    """Hand this request's database connection back before an outbound call.

    Under ``django-db-geventpool`` a greenlet keeps the connection it first queried with until
    the request ends, and a worker has eight. A callback waiting on a slow IdP would hold one
    for the whole fetch; eight of them stall every database-backed request on that worker.
    ``close()`` returns it to the pool and the next query takes one again. Inside an atomic
    block the connection is the transaction's and is kept: no outbound call is made in one.
    """
    if not connection.in_atomic_block:
        connection.close()


# RFC 7517/7518 private and symmetric key members. A JWKS is public by definition: a key that
# carries one is refused whatever its type. An RSA private key would otherwise load and then
# fail inside PyJWT's verify (AttributeError, a 500); an EC or OKP private key would load and
# verify, accepting a key the IdP should never have published.
PRIVATE_MEMBERS = ("d", "p", "q", "dp", "dq", "qi", "oth", "k")


def has_private_members(jwk):
    return isinstance(jwk, dict) and any(member in jwk for member in PRIVATE_MEMBERS)


class DiscoveryError(Exception):
    """A fetch or validation failure, carrying only a fixed ``code``."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def discovery_url(issuer):
    """Strip one terminating ``/`` from the issuer, then append the well-known path.

    OIDC Discovery 4.1. The STORED issuer is not normalised: the document's ``issuer`` and an
    ID token's ``iss`` must equal it exactly, trailing slash included.
    """
    base = issuer[:-1] if issuer.endswith("/") else issuer
    return base + WELL_KNOWN


def _scheme_allowed(url):
    try:
        scheme = urlparse(url).scheme.lower()
    except ValueError:  # e.g. "https://[oops": urlparse refuses it
        return False
    return scheme == "https" or (scheme == "http" and settings.OIDC_ALLOW_HTTP)


def _now():
    """The monotonic clock; a seam so the deadline test needs no real waiting."""
    return time.monotonic()


def read_limited(resp, deadline, *, too_large, failed):
    """Read a streamed body under the 1 MiB cap and a monotonic ``deadline``.

    ``read1`` returns after one underlying receive, so the deadline is checked between
    receives rather than after a buffered read that waits for a whole chunk. Raises
    ``DiscoveryError(too_large)`` past the cap and ``DiscoveryError(failed)`` on a transport
    error or once the deadline has passed.
    """
    chunks = []
    total = 0
    try:
        while True:
            if _now() > deadline:
                logger.warning("OIDC response body read exceeded its deadline")
                raise DiscoveryError(failed)
            chunk = resp.raw.read1(READ_SIZE, decode_content=True)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BYTES:
                raise DiscoveryError(too_large)
            chunks.append(chunk)
    except requests.RequestException as exc:
        logger.warning("OIDC response body read failed: %s", type(exc).__name__)
        raise DiscoveryError(failed) from None
    except (urllib3.exceptions.HTTPError, OSError) as exc:
        # Reading the raw stream directly surfaces urllib3's own errors (ReadTimeoutError,
        # ProtocolError, DecodeError), which requests would otherwise have wrapped.
        logger.warning("OIDC response body read failed: %s", type(exc).__name__)
        raise DiscoveryError(failed) from None
    return b"".join(chunks)


def deadline_from_now():
    return _now() + TOTAL_DEADLINE


class _DeadlineExpired(BaseException):
    """Thrown into the greenlet by ``run_bounded``'s timer.

    A ``BaseException``, like ``gevent.Timeout`` itself, so no ``except Exception`` between
    the timer and ``run_bounded`` (ours, requests', urllib3's) can swallow it; ``finally``
    blocks still run, which is what closes the response and the socket.
    """


def _gevent_socket_patched():
    """True in a process whose ``socket`` module gevent has monkey-patched (uWSGI's API)."""
    try:
        from gevent import monkey
    except ImportError:  # pragma: no cover - gevent is a main dependency
        return False
    return monkey.is_module_patched("socket")


def run_bounded(call, *, on_expiry, label):
    """Return ``call(deadline)``, bounded as a whole by ``TOTAL_DEADLINE``.

    ``deadline`` is the monotonic deadline for ``read_limited``'s between-reads check. Under
    gevent a timer covers the whole call (DNS, connect, headers, body); when it fires the
    exception ``on_expiry()`` returns is raised in place of whatever the call was waiting
    on. Outside gevent the call runs with the per-read timeouts and the between-reads check
    only (see the comment at ``TOTAL_DEADLINE``). The caller releases its database
    connection before calling. ``label`` names the exchange in the log, never a URL.
    """
    deadline = deadline_from_now()
    if not _gevent_socket_patched():
        return call(deadline)
    import gevent

    expired = _DeadlineExpired()
    try:
        # A context manager: the timer is closed on every exit, so none is left armed.
        with gevent.Timeout(TOTAL_DEADLINE, expired):
            return call(deadline)
    except _DeadlineExpired as exc:
        if exc is not expired:
            raise
        logger.warning("OIDC %s exchange exceeded its total deadline", label)
        raise on_expiry() from None


def _read_limited(resp, kind, deadline):
    return read_limited(
        resp, deadline, too_large=f"{kind}_too_large", failed=f"{kind}_unreachable"
    )


def _fetch_body(url, provider, kind, not_allowed_code, deadline):
    """The request and the limited body read: the part ``run_bounded`` bounds."""
    try:
        resp = fetch_outbound_http(
            url,
            allow_private=provider.allow_private_network,
            allow_loopback=settings.OIDC_ALLOW_HTTP,
            max_redirects=0,
            timeout=TIMEOUT,
            stream=True,
        )
    except ValueError as exc:
        # The helper raises ValueError for a refused address AND for a redirect hop. Its
        # message names the resolved address, so only the class of refusal is kept.
        if str(exc).startswith(_REDIRECT_MESSAGES):
            raise DiscoveryError(f"{kind}_redirect") from None
        raise DiscoveryError(not_allowed_code) from None
    except requests.RequestException as exc:
        logger.warning("OIDC %s fetch failed: %s", kind, type(exc).__name__)
        raise DiscoveryError(f"{kind}_unreachable") from None

    try:
        if resp.status_code != 200:
            logger.warning("OIDC %s fetch answered HTTP %s", kind, resp.status_code)
            raise DiscoveryError(f"{kind}_http_error")
        return _read_limited(resp, kind, deadline)
    finally:
        resp.close()


def _get_json(url, provider, *, kind, not_allowed_code):
    """GET ``url`` under the SSRF policy and return the parsed JSON object."""
    if not _scheme_allowed(url):
        raise DiscoveryError(not_allowed_code)
    release_db_connection()
    body = run_bounded(
        lambda deadline: _fetch_body(url, provider, kind, not_allowed_code, deadline),
        on_expiry=lambda: DiscoveryError(f"{kind}_unreachable"),
        label=kind,
    )
    try:
        doc = json.loads(body)
    except (ValueError, RecursionError):
        # RecursionError: a deeply nested body inside the size cap. It is not a ValueError.
        raise DiscoveryError(f"{kind}_invalid") from None
    if not isinstance(doc, dict):
        raise DiscoveryError(f"{kind}_invalid")
    return doc


def _printable_ascii(value):
    return all("!" <= c <= "~" for c in value)


def fetch_discovery(provider):
    """Fetch and validate the provider's discovery document (uncached)."""
    doc = _get_json(
        discovery_url(provider.issuer),
        provider,
        kind="discovery",
        not_allowed_code="discovery_not_allowed",
    )
    if doc.get("issuer") != provider.issuer:
        raise DiscoveryError("discovery_issuer_mismatch")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        value = doc.get(field)
        if not isinstance(value, str) or not value:
            raise DiscoveryError("discovery_endpoint_missing")
        # Printable ASCII only, no space: a URL the IdP means is already percent-encoded. A
        # lone surrogate would make the authorize redirect and link/start's JSON raise, and
        # a CR, LF, NUL or space has no business in an endpoint either. Checked before the
        # document is cached, so a bad one is never served for the cache's hour.
        if not _printable_ascii(value):
            raise DiscoveryError("discovery_endpoint_invalid")
        try:
            urlparse(value)
        except ValueError:
            raise DiscoveryError("discovery_endpoint_invalid") from None
        if not _scheme_allowed(value):
            raise DiscoveryError("discovery_endpoint_insecure")
    return doc


def fetch_jwks(provider, discovery):
    """Fetch the JWKS the discovery document names (uncached). Checked at every use."""
    doc = _get_json(
        discovery["jwks_uri"],
        provider,
        kind="jwks",
        not_allowed_code="jwks_uri_not_allowed",
    )
    keys = doc.get("keys")
    if not isinstance(keys, list) or not keys or not all(isinstance(k, dict) for k in keys):
        raise DiscoveryError("jwks_invalid")
    return doc


def check_token_endpoint(provider, discovery):
    """The token request is a POST, so it is checked here rather than fetched here."""
    url = discovery["token_endpoint"]
    if not _scheme_allowed(url):
        raise DiscoveryError("token_endpoint_not_allowed")
    try:
        validate_outbound_http_url(
            url,
            allow_private=provider.allow_private_network,
            allow_loopback=settings.OIDC_ALLOW_HTTP,
        )
    except ValueError:
        raise DiscoveryError("token_endpoint_not_allowed") from None


def _cache_key(kind, provider):
    return f"oidc:{kind}:{provider.pk}:{provider.version}"


def discovery_cache_key(provider):
    return _cache_key("disco", provider)


def jwks_cache_key(provider):
    return _cache_key("jwks", provider)


def get_discovery(provider):
    """The validated discovery document, cached per provider and version for an hour.

    Every security-relevant provider edit bumps ``version``, so an edit is never served a
    stale document. Only a document that passed ``fetch_discovery``'s checks is cached.
    """
    key = discovery_cache_key(provider)
    doc = _cache_get(key)
    # A hit counts only for this provider's issuer: a database restored under a Redis that
    # kept its keys could otherwise pair this row with another row's document, and send the
    # client credential to that document's token endpoint.
    if isinstance(doc, dict) and doc.get("issuer") == provider.issuer:
        return doc
    doc = fetch_discovery(provider)
    _cache_set(key, doc)
    return doc


def _cache_get(key):
    try:
        return cache.get(key)
    except CACHE_ERRORS as exc:
        logger.warning("OIDC cache read failed: %s", type(exc).__name__)
        return None


def _cache_set(key, doc):
    try:
        cache.set(key, doc, CACHE_TTL)
    except CACHE_ERRORS as exc:
        logger.warning("OIDC cache write failed: %s", type(exc).__name__)


def get_jwks(provider, discovery, *, refetch=False):
    """The JWKS, cached like discovery. ``refetch`` bypasses the cache (an unknown ``kid``)."""
    key = jwks_cache_key(provider)
    if not refetch:
        doc = _cache_get(key)
        if isinstance(doc, dict):
            return doc
    doc = fetch_jwks(provider, discovery)
    _cache_set(key, doc)
    return doc


def claim_jwks_refetch(provider):
    """True at most once per provider per 60 s: the unknown-``kid`` refetch cooldown."""
    try:
        return cache.add(f"oidc:jwks-refetch:{provider.pk}", 1, JWKS_REFETCH_COOLDOWN)
    except CACHE_ERRORS as exc:
        logger.warning("OIDC cache write failed: %s", type(exc).__name__)
        return False


def run_test(provider):
    """Fetch and validate discovery and JWKS fresh and report fixed problem codes.

    Writes nothing: not the database and not the cache.
    """
    problems = []
    try:
        discovery = fetch_discovery(provider)
    except DiscoveryError as exc:
        return [exc.code]
    try:
        jwks = fetch_jwks(provider, discovery)
    except DiscoveryError as exc:
        problems.append(exc.code)
    else:
        # The login refuses such a key (validate._select_key); the test must not call it fine.
        if any(has_private_members(k) for k in jwks["keys"]):
            problems.append("jwks_private_key")
    try:
        check_token_endpoint(provider, discovery)
    except DiscoveryError as exc:
        problems.append(exc.code)
    return problems
