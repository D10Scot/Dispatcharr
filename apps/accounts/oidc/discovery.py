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
# A total bound on reading one response body, measured from before the connect. The per-read
# timeout alone lets a server that drips a byte every few seconds hold a request until
# uWSGI's harakiri. The deadline is checked between body reads, so the connect and the wait
# for the status line are bounded only by TIMEOUT: the worst case is the connect timeout,
# plus the read timeout for the headers, plus TOTAL_DEADLINE, plus one read timeout.
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


def _read_limited(resp, kind, deadline):
    return read_limited(
        resp, deadline, too_large=f"{kind}_too_large", failed=f"{kind}_unreachable"
    )


def _get_json(url, provider, *, kind, not_allowed_code):
    """GET ``url`` under the SSRF policy and return the parsed JSON object."""
    if not _scheme_allowed(url):
        raise DiscoveryError(not_allowed_code)
    release_db_connection()
    deadline = deadline_from_now()
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
        body = _read_limited(resp, kind, deadline)
    finally:
        resp.close()
    try:
        doc = json.loads(body)
    except (ValueError, RecursionError):
        # RecursionError: a deeply nested body inside the size cap. It is not a ValueError.
        raise DiscoveryError(f"{kind}_invalid") from None
    if not isinstance(doc, dict):
        raise DiscoveryError(f"{kind}_invalid")
    return doc


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
        fetch_jwks(provider, discovery)
    except DiscoveryError as exc:
        problems.append(exc.code)
    try:
        check_token_endpoint(provider, discovery)
    except DiscoveryError as exc:
        problems.append(exc.code)
    return problems
