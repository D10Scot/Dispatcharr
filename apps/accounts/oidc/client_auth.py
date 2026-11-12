"""Client authentication at the token endpoint, and the token request (SSO spec 3.4a, 3.3 step 6).

Three methods:

- ``client_secret_basic``: id and secret are EACH form-urlencoded (RFC 6749 2.3.1, Appendix B)
  before they are joined with ``:`` and base64-encoded. ``requests``' ``auth=(id, secret)`` is
  deliberately not used: it encodes the raw values.
- ``client_secret_post``: ``client_id`` and ``client_secret`` in the form body.
- ``private_key_jwt``: a client assertion built per request from the ACTIVE key pair, in the
  shape Microsoft's certificate-credentials page documents: header ``alg`` PS256 (RS256 for a
  generic provider that chose it), ``typ`` JWT and ``x5t#S256``; claims ``iss`` and ``sub`` the
  client id, ``aud`` the discovered token endpoint, a fresh ``jti``, ``iat`` and ``nbf`` now,
  ``exp`` now + 300 s.

Nothing here logs a secret, key, assertion, code, verifier or response body. Exceptions are
logged by class name and HTTP status only.
"""

import base64
import hashlib
import json
import logging
import time
import uuid
from urllib.parse import quote_plus

import jwt
import requests
from cryptography.hazmat.primitives import serialization

from apps.accounts.models import OIDCProvider

from . import certificates, discovery
from . import secrets as oidc_secrets

logger = logging.getLogger(__name__)

ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
ASSERTION_LIFETIME = 300
TIMEOUT = (5, 10)


class CredentialUnavailable(Exception):
    """The provider has no usable credential for its method (missing or undecryptable)."""


class TokenExchangeFailed(Exception):
    """The token request failed. ``code`` is ``client_auth_failed`` or ``token_exchange_failed``."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def basic_header(client_id, secret):
    """``Basic`` credentials with each half form-urlencoded first (RFC 6749 2.3.1)."""
    pair = f"{quote_plus(client_id, safe='')}:{quote_plus(secret, safe='')}"
    return "Basic " + base64.b64encode(pair.encode("utf-8")).decode("ascii")


def assertion_alg(provider):
    if provider.kind == OIDCProvider.KIND_ENTRA:
        return "PS256"
    return provider.client_assertion_alg or "PS256"


def build_client_assertion(provider, token_endpoint):
    """The signed assertion, from the ACTIVE pair only (never the pending one)."""
    if not provider.client_key_encrypted or not provider.client_cert_pem:
        raise CredentialUnavailable()
    try:
        key_pem = oidc_secrets.decrypt(provider.client_key_encrypted, oidc_secrets.CLIENT_KEY)
        key = serialization.load_pem_private_key(key_pem.encode("ascii"), password=None)
        cert = certificates.load_certificate(provider.client_cert_pem)
    except (oidc_secrets.CredentialUnreadable, ValueError, TypeError):
        raise CredentialUnavailable() from None
    der = cert.public_bytes(serialization.Encoding.DER)
    now = int(time.time())
    claims = {
        "iss": provider.client_id,
        "sub": provider.client_id,
        "aud": token_endpoint,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "nbf": now,
        "exp": now + ASSERTION_LIFETIME,
    }
    return jwt.encode(
        claims,
        key,
        algorithm=assertion_alg(provider),
        headers={"x5t#S256": _b64url(hashlib.sha256(der).digest())},
    )


def client_authentication(provider, token_endpoint):
    """``(form_fields, headers)`` that authenticate the client by its configured method."""
    method = provider.client_auth_method
    if method == OIDCProvider.AUTH_PRIVATE_KEY_JWT:
        return (
            {
                "client_id": provider.client_id,
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": build_client_assertion(provider, token_endpoint),
            },
            {},
        )
    if not provider.client_secret_encrypted:
        raise CredentialUnavailable()
    try:
        secret = oidc_secrets.decrypt(provider.client_secret_encrypted)
    except oidc_secrets.CredentialUnreadable:
        raise CredentialUnavailable() from None
    if method == OIDCProvider.AUTH_SECRET_POST:
        return {"client_id": provider.client_id, "client_secret": secret}, {}
    if method == OIDCProvider.AUTH_SECRET_BASIC:
        return {}, {"Authorization": basic_header(provider.client_id, secret)}
    raise CredentialUnavailable()


def exchange_code(provider, disco, *, code, redirect_uri, code_verifier):
    """POST the token endpoint and return the ``id_token``. Raises ``TokenExchangeFailed``.

    The endpoint passes the SSRF check at every use (it comes from the IdP's document), the
    request follows no redirect, and the response is read under the 1 MiB cap and the
    discovery module's total deadline.
    """
    try:
        discovery.check_token_endpoint(provider, disco)
    except discovery.DiscoveryError:
        raise TokenExchangeFailed("token_exchange_failed") from None
    token_endpoint = disco["token_endpoint"]
    try:
        auth_fields, headers = client_authentication(provider, token_endpoint)
    except CredentialUnavailable:
        logger.warning("OIDC provider has no usable client credential")
        raise TokenExchangeFailed("token_exchange_failed") from None

    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        **auth_fields,
    }
    headers = {"Accept": "application/json", **headers}
    discovery.release_db_connection()
    deadline = discovery.deadline_from_now()
    try:
        resp = requests.post(
            token_endpoint,
            data=form,
            headers=headers,
            timeout=TIMEOUT,
            allow_redirects=False,
            stream=True,
        )
    except requests.RequestException as exc:
        logger.warning("OIDC token request failed: %s", type(exc).__name__)
        raise TokenExchangeFailed("token_exchange_failed") from None

    try:
        status = resp.status_code
        try:
            body = discovery.read_limited(
                resp, deadline, too_large="token_too_large", failed="token_unreachable"
            )
        except discovery.DiscoveryError:
            raise TokenExchangeFailed("token_exchange_failed") from None
    finally:
        resp.close()

    try:
        doc = json.loads(body)
    except (ValueError, RecursionError):
        doc = None
    if status != 200:
        logger.warning("OIDC token endpoint answered HTTP %s", status)
        # Only RFC 6749 5.2's fixed code is read; error_description is never read or kept.
        if isinstance(doc, dict) and doc.get("error") == "invalid_client":
            raise TokenExchangeFailed("client_auth_failed")
        raise TokenExchangeFailed("token_exchange_failed")
    id_token = doc.get("id_token") if isinstance(doc, dict) else None
    if not isinstance(id_token, str) or not id_token:
        raise TokenExchangeFailed("token_exchange_failed")
    return id_token
