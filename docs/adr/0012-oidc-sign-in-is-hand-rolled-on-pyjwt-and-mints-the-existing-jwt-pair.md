# 12. OIDC sign-in is hand-rolled on PyJWT and mints the existing JWT pair

Date: 2026-10-31. Revised 2026-11-11: the library comparison is corrected and the size estimate redone.

## Status

Proposed (accepted when the spec `docs/superpowers/specs/2026-10-31-sso-oidc-design.md`'s PR merges)

## Context

The owner wants single sign-on for the web UI and REST API login, with Microsoft Entra ID preferred
and any standards OpenID Connect provider supported. Username and password login stays as the
fallback and can be switched off at runtime. The rulings that bind the design are in the spec (R1 to
R4). Two of them decide the library question:

- **R1.** Providers, their client secrets and the password toggle live in the database. An admin
  edits them in the UI, and a change takes effect with no restart.
- **R4.** OIDC only: a generic provider plus an Entra preset.

The product authenticates the SPA, the WebSocket and every browser-reachable media URL with one
credential: a `djangorestframework-simplejwt` access token, sent as a Bearer header or as `?token=`
(`apps/accounts/authentication.py:91-104`, `dispatcharr/jwt_ws_auth.py:27-44`,
`apps/proxy/authorize.py:90-97`). No browser path depends on a Django session. Any SSO design that
gives the SPA that same token pair leaves the player, recordings, VOD, catch-up and the WebSocket
working with no change. A design that instead logs the user in with a Django session cookie adds a
second principal source that `apps/proxy/authorize.py:345-363` (`_session_user`) would honour on the
streaming surfaces. That cookie would be ambient, so every streaming GET would become a CSRF target.

Six options were compared (spec § Library choice). The first version of this record judged Authlib
only by its Django integration, from that integration's v0.11 documentation, and did not consider
MSAL. Both are corrected here; the decision is unchanged, and its reasoning is now the accurate one.

| Option | DB-stored providers, editable live (R1) | Generic OIDC and Entra (R4) | New dependencies | What it does for the ID token | Hands the SPA a simplejwt pair |
|---|---|---|---|---|---|
| `mozilla-django-oidc` | No. Each endpoint and credential is one Django setting. | One provider | 1 package | Not assessed; it fails R1 first | No. It establishes a Django session. |
| `django-allauth` (OIDC provider) | Its OIDC docs configure providers in `SOCIALACCOUNT_PROVIDERS` settings | Yes | The allauth account framework and its own login, session and headless model | Not assessed | No, not without custom glue |
| `Authlib`, Django integration | Registered in-process per name. Live edits need per-process re-registration. Flow state lives in the Django session. | Yes | `authlib`, which requires `joserfc` and `cryptography` | Validates it (`parse_id_token`) | No. The glue is ours either way. |
| `Authlib`, framework-agnostic client (`requests_client.OAuth2Session` + `authlib.oidc.core.CodeIDToken`) | **Yes.** A session object is built per request from whatever the caller holds. | Yes | Same as above | Validates `iss`, `aud`, `azp`, `nonce`, expiry; signature through its JOSE layer | No. The glue is ours either way. |
| MSAL Python (`ConfidentialClientApplication`) | Yes, built per request | **No.** Microsoft identity platform only. | `msal` | **Does not validate it.** Never the signature; since 1.38.0 nothing at all ("validation is the application's responsibility", `msal/oauth2cli/oidc.py`). | No |
| Thin code + PKCE flow on **PyJWT** (already locked, 2.15.1) and **requests** (already locked) | Yes, by construction | Yes | **None** | Ours to get right, on `jwt.decode` | Yes. `RefreshToken.for_user` is the same path a password login takes. |

**The honest runner-up is Authlib's framework-agnostic client.** It meets R1 and R4, and it would
supply the authorization-URL construction with PKCE, the token request with `client_secret_basic`,
`client_secret_post` or `private_key_jwt`, and the ID-token claims checks: an estimated 250 to 350
of the lines this design otherwise writes. It would not supply discovery and JWKS fetching under
the spec's limits and SSRF check, the shared cache, the Redis transaction and browser binding, the
claim mapping and provisioning, the handoff, or the simplejwt glue, which are most of the work.
Its cost is a second JOSE implementation (`joserfc`) beside PyJWT, which simplejwt requires and so
cannot be dropped: one more security-critical dependency to pin, scan and keep current, to save a
few hundred lines that sit on PyJWT calls already used elsewhere in the product. That trade is a
judgement, not a necessity. It is the one to revisit first if the hand-rolled protocol code proves
costly to maintain.

MSAL is not a candidate: it cannot serve a generic provider, and it leaves ID-token validation to
the application anyway.

## Decision

Implement the OpenID Connect authorization code flow with PKCE (S256) in this repository, in a new
`apps/accounts/oidc/` package. Use PyJWT's `PyJWKSet`/`PyJWK` and `jwt.decode` for every JWS and
claim check and for signing the `private_key_jwt` client assertion, `cryptography` (already locked)
for the client key pair and its self-signed certificate, and `requests` behind the repository's
SSRF check (`core/http_security.py`) for discovery, JWKS and the token request. No new Python
dependency is added. On success, the callback mints the existing simplejwt pair with
`RefreshToken.for_user()`, shortens its refresh token to 12 hours, stamps it with five claims
(`auth_method=oidc`, the provider id, the level the IdP mapping granted at that sign-in, and, for
the cheap refresh re-evaluation, the provider's configuration version and the linked identity's
id), and hands it to the SPA through a one-time, browser-bound exchange code. It never calls
`django.contrib.auth.login()`.

The code we write covers the protocol plumbing: building the redirect, state and nonce, the token
request with its client authentication, and claim mapping. The cryptographic steps, signature
verification and signing, stay in a vetted library.

## Consequences

- R1 holds with no adapter layer. Providers are rows, read per login, and discovery and JWKS caches
  are keyed by the row's version.
- JWT-based browser playback (the floating player, recordings, VOD and catch-up) and the
  WebSocket need no change, and no new cookie-borne principal exists. The one intentional change
  on the streaming side is the spec's D19: while password login is off, the existing Django-session
  principal (`apps/proxy/authorize.py`'s `_session_user`) stops authorizing streams.
- `uv.lock` does not change for SSO, and there is no new supply-chain surface to pin, scan or watch.
- We own an estimated 1,300 to 1,700 lines of non-test Python (estimated after the 2026-11-11
  redesign, before any code exists). About 600 of them are protocol code in the narrow sense: the
  flow, client authentication, ID-token validation, discovery and JWKS. The rest is storage,
  provisioning, the lockout guard and the admin API, which no library would have written. The
  earlier "about 400 lines" counted only the protocol code and predated the certificate
  credential, the SSRF policy and the per-transaction cookie. So the spec's threat list and its
  per-threat tests are mandatory, not optional, and a security-adjacent review cadence applies
  (`fable` from round one).
- Getting the protocol details right is on us. The first documentation-backed review found two we
  had wrong, the Basic-auth credential encoding (RFC 6749 § 2.3.1) and the discovery URL for an
  issuer ending in `/` (OIDC Discovery § 4.1), and one we had not specified, JWKS entries with no
  `alg` member. A library would have carried those. Each now has a test.
- Protocol features we do not build do not exist: RP-initiated logout, Graph lookups on a groups
  overage, front-channel and back-channel logout, dynamic registration, the `form_post` response
  mode and mutual-TLS client authentication. Each is listed as out of
  scope in the spec.
- If the flow ever needs SAML or broad federation features, revisit this record rather than growing
  the hand-rolled code.
