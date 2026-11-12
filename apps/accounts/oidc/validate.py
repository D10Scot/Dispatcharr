"""ID token validation (SSO spec 3.4; OIDC Core 1.0 section 3.1.3.7).

The verification algorithm comes from the provider's configuration, never from the token
header or the JWK. PyJWT would guess a JWK's algorithm from its ``kty`` when it carries no
``alg`` (Entra's do not), and would read an ``oct`` key as HS256, so ``oct`` keys and keys of
the wrong family are refused and ``PyJWK`` is always built with the configured algorithm.

Every failure is ``IdTokenInvalid``; no message names a claim value, and nothing is logged
but an exception class.
"""

import hmac
import logging

import jwt

from . import discovery, mapping

logger = logging.getLogger(__name__)

ALLOWED_ALGS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "EdDSA"}
)
LEEWAY = 60
REQUIRED = ["iss", "sub", "aud", "exp", "iat", "nonce"]
ENTRA_ISSUER = "https://login.microsoftonline.com/{tenant}/v2.0"
MAX_SUBJECT = 255


# What decoding an ID token can raise on hostile input: PyJWT's own errors; ValueError and
# TypeError from ill-shaped JSON or claims; ArithmeticError when a time claim is 1e999 (JSON
# float infinity, which int() refuses with OverflowError); RecursionError when the header or
# the payload nests deeper than the parser can follow.
_DECODE_ERRORS = (jwt.PyJWTError, ValueError, TypeError, ArithmeticError, RecursionError)


class IdTokenInvalid(Exception):
    """The ID token failed a check. Carries no detail by design."""


def _family(alg):
    if alg.startswith(("RS", "PS")):
        return "RSA"
    if alg.startswith("ES"):
        return "EC"
    if alg == "EdDSA":
        return "OKP"
    return None


def _select_key(jwks, kid, alg):
    """The ``PyJWK`` for ``kid`` built with the configured ``alg``, or None if no key matches.

    A matching key that is ``oct``, of the wrong family or names a different ``alg`` is a
    refusal, not a miss: refetching would not make it acceptable.
    """
    keys = jwks.get("keys") if isinstance(jwks, dict) else None
    if not isinstance(keys, list):
        return None
    matches = [k for k in keys if isinstance(k, dict) and k.get("kid") == kid]
    if not matches:
        return None
    if len(matches) > 1:
        raise IdTokenInvalid()
    jwk = matches[0]
    if discovery.has_private_members(jwk):
        logger.warning("OIDC JWK refused: it carries a private key member")
        raise IdTokenInvalid()
    kty = jwk.get("kty")
    if kty == "oct" or kty != _family(alg):
        raise IdTokenInvalid()
    if "alg" in jwk and jwk.get("alg") != alg:
        raise IdTokenInvalid()
    try:
        return jwt.PyJWK(jwk, algorithm=alg)
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        logger.warning("OIDC JWK could not be loaded: %s", type(exc).__name__)
        raise IdTokenInvalid() from None


def _resolve_key(provider, disco, kid, alg):
    jwks = discovery.get_jwks(provider, disco)
    key = _select_key(jwks, kid, alg)
    if key is None and discovery.claim_jwks_refetch(provider):
        jwks = discovery.get_jwks(provider, disco, refetch=True)
        key = _select_key(jwks, kid, alg)
    if key is None:
        raise IdTokenInvalid()
    return key


def validate_id_token(provider, id_token, nonce, disco):
    """Return the validated claims, or raise ``IdTokenInvalid``.

    ``discovery.DiscoveryError`` from the JWKS fetch propagates for the caller to map.
    """
    alg = provider.id_token_alg
    if alg not in ALLOWED_ALGS or not isinstance(id_token, str):
        raise IdTokenInvalid()
    try:
        header = jwt.get_unverified_header(id_token)
    except _DECODE_ERRORS as exc:
        logger.info("OIDC ID token header refused: %s", type(exc).__name__)
        raise IdTokenInvalid() from None
    # The header's alg is not consulted here: ``algorithms=[alg]`` below refuses any other
    # value, ``none`` and every ``HS*`` included.
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise IdTokenInvalid()

    key = _resolve_key(provider, disco, kid, alg)
    try:
        claims = jwt.decode(
            id_token,
            key.key,
            algorithms=[alg],
            audience=provider.client_id,
            issuer=provider.issuer,
            leeway=LEEWAY,
            options={"require": REQUIRED},
        )
    except _DECODE_ERRORS as exc:
        logger.info("OIDC ID token refused: %s", type(exc).__name__)
        raise IdTokenInvalid() from None

    _check_claims(provider, claims, nonce)
    return claims


def _check_claims(provider, claims, nonce):
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub or len(sub) > MAX_SUBJECT:
        raise IdTokenInvalid()
    # The subject is half the identity key: refused, never stripped (two subjects that differ
    # only by a control character must not resolve to one identity).
    if mapping.has_control_char(sub):
        raise IdTokenInvalid()
    if claims.get("iss") != provider.issuer:
        raise IdTokenInvalid()

    # azp: whenever present it must be a string equal to client_id, whatever aud's shape;
    # with several audiences it must be present (OIDC Core 3.1.3.7 items 4-5).
    aud = claims.get("aud")
    if isinstance(aud, list) and len(aud) > 1 and "azp" not in claims:
        raise IdTokenInvalid()
    if "azp" in claims:
        azp = claims["azp"]
        if not isinstance(azp, str) or azp != provider.client_id:
            raise IdTokenInvalid()

    token_nonce = claims.get("nonce")
    if (
        not isinstance(token_nonce, str)
        or not isinstance(nonce, str)
        or not token_nonce.isascii()
        or not hmac.compare_digest(token_nonce, nonce)
    ):
        raise IdTokenInvalid()

    if provider.kind == "entra":
        tenant = (provider.entra_tenant_id or "").lower()
        tid = claims.get("tid")
        if not tenant or not isinstance(tid, str) or tid.lower() != tenant:
            raise IdTokenInvalid()
        if claims.get("iss") != ENTRA_ISSUER.format(tenant=provider.entra_tenant_id):
            raise IdTokenInvalid()
