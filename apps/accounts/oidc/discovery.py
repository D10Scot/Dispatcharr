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
from urllib.parse import urlparse

import requests
from django.conf import settings

from core.http_security import fetch_outbound_http, validate_outbound_http_url

logger = logging.getLogger(__name__)

MAX_BYTES = 1024 * 1024  # 1 MiB, enforced while streaming
TIMEOUT = (5, 10)  # connect, read
WELL_KNOWN = "/.well-known/openid-configuration"

_REDIRECT_MESSAGES = ("More than ", "Redirect without a Location")


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


def _read_limited(resp, kind):
    chunks = []
    total = 0
    try:
        for chunk in resp.iter_content(chunk_size=8192):
            total += len(chunk)
            if total > MAX_BYTES:
                raise DiscoveryError(f"{kind}_too_large")
            chunks.append(chunk)
    except requests.RequestException as exc:
        logger.warning("OIDC %s body read failed: %s", kind, type(exc).__name__)
        raise DiscoveryError(f"{kind}_unreachable") from None
    return b"".join(chunks)


def _get_json(url, provider, *, kind, not_allowed_code):
    """GET ``url`` under the SSRF policy and return the parsed JSON object."""
    if not _scheme_allowed(url):
        raise DiscoveryError(not_allowed_code)
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
        body = _read_limited(resp, kind)
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
