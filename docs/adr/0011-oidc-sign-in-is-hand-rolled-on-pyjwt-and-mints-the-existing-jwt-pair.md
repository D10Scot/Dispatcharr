# 11. OIDC sign-in is hand-rolled on PyJWT and mints the existing JWT pair

Date: 2026-10-31

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

Four options were compared (spec § Library choice):

| Option | DB-stored providers, editable live (R1) | Several providers | New dependencies | Hands the SPA a simplejwt pair |
|---|---|---|---|---|
| `mozilla-django-oidc` | No. Each endpoint and credential is one Django setting. | No | 1 package | No. It establishes a Django session. |
| `django-allauth` (OIDC provider) | Its OIDC docs configure providers in `SOCIALACCOUNT_PROVIDERS` settings | Yes | The allauth account framework and its own login, session and headless model | No, not without custom glue |
| `Authlib` Django client | Registered in-process per name. Live edits need per-process re-registration. | Yes | `authlib` (with its JOSE stack) | No. The glue is ours either way. |
| Thin code + PKCE flow on **PyJWT** (already locked, 2.15.1) and **requests** (already locked) | Yes, by construction | Yes | **None** | Yes. `RefreshToken.for_user` is the same path a password login takes. |

## Decision

Implement the OpenID Connect authorization code flow with PKCE (S256) in this repository, in a new
`apps/accounts/oidc/` package. Use PyJWT's `PyJWKSet`/`PyJWK` and `jwt.decode` for every JWS and
claim check, and `requests` for discovery, JWKS and the token request. No new Python dependency is
added. On success, the callback mints the existing simplejwt pair with `RefreshToken.for_user()`,
stamps it with `auth_method=oidc`, the provider id, the provider's configuration version, the level the IdP mapping
granted at that sign-in, the linked identity's id (for the cheap refresh re-evaluation), and a hash of the redirect URI used (the claims the spec's lockout guard checks), and hands it to the SPA through a one-time,
browser-bound exchange code. It never calls `django.contrib.auth.login()`.

The code we write covers the protocol plumbing: building the redirect, state and nonce, the token
request and claim mapping. The cryptographic step, signature verification, stays in a vetted
library.

## Consequences

- R1 holds with no adapter layer. Providers are rows, read per login, and discovery and JWKS caches
  are keyed by the row's version.
- The streaming surfaces, the WebSocket and the floating player need no change, and no new
  cookie-borne principal exists.
- `uv.lock` does not change for SSO, and there is no new supply-chain surface to pin, scan or watch.
- We own about 400 lines of security-relevant code, so the spec's threat list and its per-threat
  tests are mandatory, not optional. A security-adjacent review cadence applies (`fable` from round
  one).
- Protocol features we do not build do not exist: RP-initiated logout, Graph lookups on a groups
  overage, front-channel and back-channel logout, and dynamic registration. Each is listed as out of
  scope in the spec.
- If the flow ever needs SAML or broad federation features, revisit this record rather than growing
  the hand-rolled code.
