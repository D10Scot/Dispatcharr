# OIDC single sign-on for the web UI and REST API login

Date: 2026-10-31, redesigned 2026-11-11 after a documentation-backed review and the owner's rulings B1 to B6 (recorded at the end). Seed SHA: `149678aa3accd82997d523e9747305ccd4c52a46`. Implement this spec PR by PR with subagents, following CLAUDE.md § Delegation for phase work.

The product is being renamed from Dispatcharr to Mino (`docs/superpowers/specs/2026-10-28-mino-rename-design.md`). This spec uses the names live at the seed SHA. Every **new** identifier it introduces is named neutrally or for Mino, as `CONTEXT.md` § Mino requires, so the rename never has to touch it:

- env vars `MINO_PASSWORD_LOGIN_FORCE` and `MINO_OIDC_ALLOW_HTTP`
- the cookies `__Host-mino_oidc_tx_<id>` and, over plain HTTP only, `mino_oidc_tx_<id>` (§ 3.2)
- the settings group `auth_settings`
- the routes under `/api/accounts/oidc/`

New Python modules live in the `dispatcharr` and `apps` packages, which the rename keeps (its C-10). User-visible strings use whatever product name the tree carries when each PR lands; its C1 decides that.

ADR: `docs/adr/0012-oidc-sign-in-is-hand-rolled-on-pyjwt-and-mints-the-existing-jwt-pair.md`.

## Goal

Admins and users sign in to the web UI, and so obtain REST API credentials, through an OpenID Connect provider. Microsoft Entra ID is the preferred provider and gets a preset; any standards OIDC provider works through the generic form. Username and password login remains the fallback, and an admin can switch it off at runtime without locking the instance out.

## Owner rulings (override every default below)

- **R1. Config home.** Providers and the password toggle live in the database and are edited in the admin UI. A change takes effect with no restart. Client secrets are stored in the database.
- **R2. Provisioning.** Create the user just in time on their first SSO login. Map Entra app roles or groups (generic: a configurable claim) to `user_level`: Streamer 0, Standard 1, Admin 10. Refuse a login that matches no mapping.
- **R3. Break-glass.** When password login is off, a `manage.py` command and/or an env var turns it back on. Neither is reachable from the web.
- **R4. Protocols.** OIDC only: a generic provider plus an Entra preset (tenant id, issuer, app roles).
- **B1 to B6 (2026-11-11).** The lockout guard is simplified, the response mode stays `query`, an SSO session lasts about 12 hours, a certificate credential (`private_key_jwt`) is offered beside the client secret, an Entra setup page is written for operators, and the binding cookie is `__Host-` prefixed and named per transaction. The full text is in § Recorded owner rulings (2026-11-11).
- **Standing fact.** SSO covers web UI and REST API login only. Xtream, M3U, HDHomeRun and stream clients keep their protocol-level credentials.

## Decisions at a glance

| # | Decision |
|---|---|
| D1 | Hand-rolled authorization code + PKCE (S256) flow on **PyJWT** and **requests**, both already locked. No new dependency. (ADR 0012) |
| D2 | SSO ends by minting the **existing simplejwt pair** (`RefreshToken.for_user`). The SPA, WebSocket, player, recordings, VOD and catch-up need no change. |
| D3 | The callback **never calls `django.contrib.auth.login()`** and sets no Django session. Transient state lives in Redis behind a single-use key, bound to the browser by an HttpOnly, `__Host-` prefixed cookie named per transaction (ruling B6). Linking starts only from an authenticated `POST`, so the binding exists only in the linking user's own browser. |
| D4 | Tokens reach the SPA through a **one-time exchange code** in the URL **fragment**, redeemed by `POST`. Tokens never appear in a URL. |
| D5 | **Per-provider redirect URI** `<public_base_url>/api/accounts/oidc/<slug>/callback/`. The transaction is bound to a provider. RFC 9207 `iss` is checked when the provider advertises it. |
| D6 | `public_base_url` is **explicit configuration**, and must be https except for loopback or the `MINO_OIDC_ALLOW_HTTP` deployment switch. The `Host` header is never used to build a redirect URI. |
| D7 | Providers live in a **dedicated model** (`OIDCProvider`), not in `CoreSettings`. `CoreSettings` is readable by every Standard user. The password toggle and `public_base_url` live in a new `CoreSettings` group, `auth_settings`, which neither the generic settings endpoint nor Django admin's `CoreSettingsAdmin` may write, rename or delete. Security decisions read it fresh from Postgres, never through the group cache. |
| D8 | Identity is keyed on **(provider, issuer, subject)**. Email is never used for matching. A provider's issuer, tenant and client id are immutable once identities exist. An existing local user links through an explicit, authenticated "link" flow. |
| D9 | `user_level` is **recomputed from the mapping on every SSO login**, before any write. No match means refusal, and nothing is written. |
| D10 | Entra preset: **single tenant only**. A tenant GUID is required; `common`, `organizations` and `consumers` are refused. `roles` is the default claim. A groups overage refuses the login rather than calling Graph. |
| D11 | The client credential, a secret or a private key, is **encrypted at rest** (Fernet, key derived from `SECRET_KEY` by HKDF). The secret is write-only in the API, and the private key never leaves the server. |
| D12 | (Ruling B1) Password-off **lockout guard**: password login can be switched off only by an admin whose own token came from an SSO sign-in, on a provider that is enabled now, that mapped them to Admin at that sign-in. One floor: while password login is off, the last enabled provider cannot be disabled or deleted. Every other provider edit is allowed while password login is off, so a single-provider instance can rotate its credential. Break-glass covers the rest. The writes that the rule depends on are serialized by one row lock. The toggle, its enforcement and break-glass land together in S4. |
| D13 | Password-off also **refuses refresh of password-issued tokens**. Only a ≤30-minute access-token tail survives the switch. |
| D14 | Break-glass: `MINO_PASSWORD_LOGIN_FORCE=1` (env, wins over the DB) and `manage.py password_login --enable/--disable/--status` (writes the DB). The operator page gives the full recovery for an instance whose admins have no password (§ 5.6). |
| D15 | RP-initiated logout, SAML, SCIM, Graph lookups, multi-tenant Entra and paired-device auth are **out of scope**. |
| D16 | E2E uses a **fake OIDC provider added to `e2e-upstream`** (node stdlib crypto, no new image, no new npm dependency) and a new `sso` Playwright project with its own container. |
| D17 | (Ruling Q1) Refreshing an OIDC token **re-evaluates the level cheaply, with no IdP call**. When the provider's version has changed since the token was minted, the level is recomputed from the mapping-claim values stored on the identity at its last login, under the current mappings. If the claim path itself changed, the refresh is refused and the user must sign in again. A lower level demotes the user through one atomic conditional update, and no match refuses the refresh. Refresh never promotes, and never demotes the last active admin (D21). |
| D18 | (Ruling Q4) Provider and `auth_settings` changes write an audit `SystemEvent`, `auth_config_changed`, after commit. It names the changed fields, never their values. |
| D19 | (Ruling Q7) While password login is off, a Django session no longer authorizes streams (`_session_user`). |
| D20 | (Ruling Q8) An admin-only active/inactive control on the Users page (PR S0). Admins cannot deactivate themselves or the last active admin. The CLI one-liner stays as the break-glass path. |
| D21 | **An active admin always remains.** No SSO login, link or token refresh may lower the level of the last active admin: it is refused with `last_admin` and writes nothing. `initialize_superuser` additionally stays closed once any `OIDCProvider` row exists (§ 4.4). |
| D22 | **Outbound fetches** (discovery, JWKS, the token request) go through the repository's SSRF check, `core/http_security.py`. Private addresses are allowed only by a per-provider flag that the Entra preset cannot set, and loopback only by the `MINO_OIDC_ALLOW_HTTP` deployment switch (§ 3.5). |
| D23 | **Client authentication** is `client_secret_post`, `client_secret_basic` (credentials form-urlencoded first, RFC 6749 § 2.3.1) or `private_key_jwt` (ruling B4). The Entra preset offers `private_key_jwt` and `client_secret_post`. The key pair is generated in the app, and only its certificate can be downloaded (§ 5.2). |
| D24 | (Ruling B2) The authorization response uses the default **`query` response mode**. `form_post` was considered and rejected (§ 3.2). |
| D25 | (Ruling B3) An SSO-issued refresh token lives **12 hours**, not the password pair's 1 day (§ 3.3 step 9). |
| D26 | A provider carries an optional **credential expiry date**, and admins are warned 30 days ahead (§ 5.2). |

## 1. Current auth surface (verified at the seed SHA)

### REST API

- `dispatcharr/settings.py:328-346`: `REST_FRAMEWORK` authenticates with `rest_framework_simplejwt.authentication.JWTAuthentication`, then `apps.accounts.authentication.ApiKeyAuthentication` (`:334-337`). The default permission is `IsAdmin` (`:338-340`). The only throttle rate is `"login": "3/minute"` (`:344`).
- `dispatcharr/settings.py:492-497`: `SIMPLE_JWT` sets access tokens to 30 minutes and refresh tokens to 1 day. `ROTATE_REFRESH_TOKENS` is `False`, and `token_blacklist` is not in `INSTALLED_APPS` (`:110-139`), so no token can be revoked before it expires.
- Routes are in `apps/accounts/api_urls.py:29-37`: `auth/login/` (`AuthViewSet.login`, an alias), `auth/logout/`, `initialize-superuser/`, `permissions/`, `token/` and `token/refresh/`.
- `apps/accounts/api_views.py:57-131`: `TokenObtainPairView` gates on `network_access_allowed(request, "UI")` (`:61`) and throttles with `LoginRateThrottle` (`:58`). It writes `login_success` and `login_failed` `SystemEvent`s through `log_system_event` (`:68-74, :99-104, :110-116, :123-129`) and sets `last_login` (`:94-96`).
- `apps/accounts/api_views.py:134-158`: `TokenRefreshView` applies the same UI ACL. In simplejwt 5.5.1, `TokenRefreshSerializer.validate` looks the user up with a bare `.get()` and applies `USER_AUTHENTICATION_RULE`, so an inactive user cannot refresh. `RefreshToken.access_token` copies every claim except `token_type`, `exp`, `jti` and `iat` into the new access token (simplejwt 5.5.1 `tokens.py:379-410`, `serializers.py:102-150`, read from the PyPI wheel). **A custom claim set at mint time therefore survives every refresh.** D12, D13 and D17 rely on this. The refresh token's own `exp` is what refresh enforces, not the class lifetime: `TokenRefreshSerializer.validate` builds `RefreshToken(attrs["refresh"])` (`serializers.py:112`), whose constructor decodes with PyJWT's expiry check (`tokens.py:65`, `backends.py:160-171`) and then calls `check_exp()` on the token's `exp` claim (`tokens.py:72, :118, :187-206`). With `ROTATE_REFRESH_TOKENS` false, `serializers.py:128-143` never re-stamps it. D25 relies on this.
- `apps/accounts/api_views.py:228-245`: `logout` writes a `logout` event and calls `django.contrib.auth.logout(request)` (`:244`). That call is a no-op for a JWT caller, who has no session.
- `apps/accounts/api_views.py:288-312`: `UserViewSet.me` lets a user `PATCH` their own `password` (`ALLOWED_FIELDS` at `:292`). `UserSerializer.update` sets it (`apps/accounts/serializers.py:157-158`). An SSO-only user could therefore give themselves a local password and bypass the IdP's MFA. § 5.4 closes this.
- `apps/accounts/api_views.py:161-194`: `initialize_superuser` is the first-admin bootstrap. It is unauthenticated and `csrf_exempt`. It closes only while a user with `user_level >= 10` exists (`:164`, a filter that ignores `is_active`), and otherwise creates a superuser for any caller the setup IP policy admits: by default every private or loopback address (`dispatcharr/utils.py:380-410`, `LOCAL_NETWORK_CIDRS` at `:17-25`). **Lowering the last admin's level therefore reopens an unauthenticated account-creation endpoint to the LAN.** `apps/accounts/tests/test_accounts.py:35-44` pins that it is open when only a non-admin user exists. `UserViewSet` has no guard of its own against demoting or deleting the last admin (`:249-282`). D21 and § 4.4 keep SSO from ever reaching that state.
- `manage.py createsuperuser` produces an Admin: `CustomUserManager.create_superuser` defaults `user_level` to 10 (`apps/accounts/models.py:6-9`). § 5.6's recovery procedure depends on this.
- `apps/accounts/authentication.py:47-88`: API keys are read from `X-API-Key` or `Authorization: ApiKey`, looked up by plaintext value, and refused for inactive users. `:91-104` is `QueryParamJWTAuthentication`, which reads `?token=` for `<video src>` media.
- `apps/accounts/models.py:12-33`: `User(AbstractUser)` carries `user_level` (default `STREAMER`, `:30`), `channel_profiles` M2M (`:25-29`), `custom_properties`, `api_key` and `stream_limit`. `apps/accounts/serializers.py:16` defines `SAFE_CREDENTIAL_RE = ^[A-Za-z0-9._@-]+$` for usernames.
- `apps/accounts/permissions.py:6-28`: `Authenticated`, `IsStandardUser` and `IsAdmin` all apply the UI network ACL. `:42-49` grants `list`/`retrieve` to `IsStandardUser`, and `core/api_views.py:116-120` uses that mapping for `CoreSettingsViewSet`. **Every Standard user can read every `CoreSettings` group.** That is why D7 keeps secrets out of `CoreSettings`.
- `apps/accounts/admin.py:23-38` wraps Django admin's `login` in the shared throttle. `docker/nginx.conf:642-644` 301s `/admin`, `/admin/` and every `/admin` path that is **not** exactly three segments deep, sending them to `/login`. Its negative lookahead `(?!/[^/]+/[^/]+/?$)` exempts three-segment paths for the XC username `admin`. So `/admin/login/` is redirected, but `/admin/core/coresettings/` and every other app/model admin page fall through to `location /` (`:716-719`) and reach Django's admin (`dispatcharr/urls.py:104`) in **production** too. A browser with an existing admin-site session can use them there. A browser without one is sent to `/admin/login/`, which nginx redirects to `/login`. The API uWSGI's `http = 0.0.0.0:5656` (`docker/uwsgi.ini:36`), which `docker/docker-compose.dev.yml:10` and `docker/docker-compose.debug.yml:9` publish, exposes the whole admin site, login included, in dev and debug.

### Outbound HTTP

`core/http_security.py` is the repository's SSRF check. `validate_outbound_http_url(url, allow_private=False, allow_loopback=False)` (`:14-157`) allows only `http` and `https`, cross-checks the host `urlparse` reads against the host urllib3 would dial, resolves it, and refuses link-local (cloud metadata included), unspecified and multicast addresses always, and loopback and private addresses unless the matching flag is set. In strict mode it also refuses reserved addresses and anything not globally reachable. **With `allow_private=True` it is looser than "RFC 1918 only"**: the `is_private` branch accepts and continues before the `is_reserved` test (`:137-145`), and Python's `is_private` covers more than LAN ranges. Under Python 3.13, `240.0.0.0/4` is both private and reserved, and `198.18.0.0/15` is private, so the flag admits both. `fetch_outbound_http` (`:211-263`) is a `requests.get` that validates every redirect hop; with `max_redirects=0` it raises on the first redirect instead of following it (`:235-263`). It is **GET only** (`:248`). Its docstring accepts one residual: DNS can change between a hop's check and its connect (`:219-220`). § 3.5 uses both functions.

### WebSocket

`dispatcharr/asgi.py:14` wraps the router in `JWTAuthMiddleware` (`dispatcharr/jwt_ws_auth.py:27-44`), which validates `?token=<access>` with `JWTAuthentication`. `dispatcharr/consumers.py:63-70` closes an unauthenticated socket. The frontend opens it with the store's `accessToken` (`frontend/src/WebSocket.jsx:88-94`).

### Streaming and media

- `apps/proxy/authorize.py:90-97`: the authorize hop's authenticator union is `JWTAuthentication`, `ApiKeyAuthentication` and `QueryParamJWTAuthentication`. `_drf_user` (`:304-342`) runs that union. `_session_user` (`:345-363`) then falls back to **a Django session's user**, and `_resolve_principal` (`:383-404`) uses both.
- Recordings (`apps/channels/api_views.py:3277-3281`, `RECORDING_PLAYBACK_AUTHENTICATORS`), VOD (`apps/proxy/vod_proxy/views.py:649, :916`) and catch-up (`apps/timeshift/views.py:285`) accept the same JWT trio.
- `frontend/src/components/FloatingVideo.jsx:26-32, :385, :483, :653, :791` reads `useAuthStore.getState().accessToken` for `?token=` and for hls.js's `xhrSetup` Authorization header.

**What SSO users need for the player, recordings, VOD and catch-up: nothing beyond a simplejwt access token in the auth store.** Every browser-reachable media path authenticates with it. No browser path depends on a Django session. This is why D2 mints the existing pair. It is also why D3 forbids a session login: the moment the callback called `login()`, `_session_user` would honour an ambient `sessionid` cookie on every streaming surface. Under `CORS_ALLOW_ALL_ORIGINS=True` and `CSRF_TRUSTED_ORIGINS=["http://*","https://*"]` (`settings.py:488-489`, a known defect), that is a CSRF exposure the product does not have today.

### Frontend login

- `frontend/src/store/auth.jsx`:
  - `:152-154` keeps `accessToken`, `refreshToken` and `tokenExpiration` in the store and `localStorage`.
  - `:177-197` `login()` calls `API.login`, then stores the pair.
  - `:200-222` refresh, and logout on failure.
  - `:225-246` logout clears both.
  - `:107-110` `initData` refuses a Streamer, so a Streamer cannot use the UI.
- `frontend/src/api.js:190-201` (`POST /api/accounts/token/`), `:204-220` (`/token/refresh/`, which sends a 401 to `/login`) and `:222-227` (logout).
- `frontend/src/pages/Login.jsx:33-51` shows `SuperuserForm` until an admin exists, then `LoginForm` (`frontend/src/components/forms/LoginForm.jsx`, whose "Forgot password" text is at `:289-313`).
- `frontend/src/App.jsx:168-170` routes only `/login` while unauthenticated. Every other path navigates to `/login` (`:171-182`).

### Settings storage

- `core/models.py:227-234` defines eight group keys. `CoreSettings` is at `:290`. `_get_group` (`:398`) reads through a Redis group cache (`:236-242`), invalidated in `post_save` (`core/signals.py:11-15`), not `on_commit`. Its version check and fill are not atomic (`core/models.py:420-434`), so a racing reader can re-cache a stale value for up to 300 s (`:242`). R1's no-restart effect for the password toggle therefore comes from reading `auth_settings` fresh from Postgres on every security decision (§ 5.1), not from this cache.
- `docker/entrypoint.sh:138` exports `DJANGO_SECRET_KEY` from the persisted `/data/jwt`. `BACKUP_DATA_DIRS` (`settings.py:480-484`) does not include it, so a backup restored to a fresh instance gets a different `SECRET_KEY`. § 5.2 depends on this.

### Events and logging

- `apps/connect/models.py:3-22` (`SUPPORTED_EVENTS`) lists `login_failed` only. `login_success` and `logout` are logged as `SystemEvent`s but cannot be subscribed to. That is unchanged here (§ 7).
- `scripts/check_credential_logging.py:111-113` (`CREDENTIAL_RE`) matches `\btoken\b`, `password`, `api_key`, `_url` and headers. It does **not** match `client_secret`, `id_token`, `access_token`, `refresh_token` or `code_verifier`, because `_` is a word character. § 8 extends it.

## 2. Library choice

Recorded in ADR 0012. The comparison:

- **`mozilla-django-oidc`.** Each RP endpoint and credential is a single Django setting (`OIDC_RP_CLIENT_ID`, `OIDC_OP_AUTHORIZATION_ENDPOINT`, …). PKCE sits behind `OIDC_USE_PKCE` (default off), and success establishes a Django session (`SessionRefresh` middleware, tokens "in the user session"). Source: https://mozilla-django-oidc.readthedocs.io/en/stable/settings.html. It fails R1 (settings, not DB), multi-provider, and D3 (session).
- **`django-allauth`**, OpenID Connect provider. Providers are declared as `APPS` entries in the `SOCIALACCOUNT_PROVIDERS` setting, one independent instance each (https://docs.allauth.org/en/latest/socialaccount/providers/openid_connect.html). allauth also has a `SocialApp` DB model, but that page does not document it for OIDC, and I did not verify a runtime-editable path. Either way it brings the allauth account framework (its own login views, email handling, session login and headless mode) for one flow, plus custom glue to hand the SPA a simplejwt pair.
- **Authlib.** It has two clients, and the first draft of this spec judged only one of them, from its v0.11 documentation.
  - The *Django integration* (`oauth.register(name, …)`, https://github.com/authlib/authlib/blob/main/docs/oauth2/client/web/django.rst) keeps a named, in-process registry and stores flow state in the Django session (`authlib/integrations/django_client/apps.py`: `set_state_data(request.session, …)`). A live DB edit needs per-process re-registration across four uWSGI workers, and the session dependency conflicts with D3.
  - The *framework-agnostic client* (`authlib.integrations.requests_client.OAuth2Session`, https://github.com/authlib/authlib/blob/main/docs/oauth2/client/http/index.rst) has neither problem. It is constructed per request from whatever configuration the caller holds, so DB-stored providers work. It builds the authorization URL with PKCE (`code_challenge_method='S256'`), performs the token request with `client_secret_basic`, `client_secret_post` or `private_key_jwt` (`requests.rst`, § "Using `private_key_jwt` in Requests"), and its `authlib.oidc.core.CodeIDToken` claims class validates `iss`, `aud`, `azp`, `nonce` and expiry (`authlib/oidc/core/claims.py`). **It would be a sound choice.**
  - What it would not provide: discovery and JWKS fetching under § 3.5's limits and SSRF check, the shared cache, the Redis transaction and browser binding, the mapping and provisioning, the handoff, and the simplejwt glue. Those are most of this spec. What it would replace is the URL construction, the token request and client authentication, and the claims checks: an estimated 250 to 350 of the lines we would otherwise write.
  - Its cost: a new direct dependency, `authlib`, which itself requires `joserfc` and `cryptography` (its `pyproject.toml` `dependencies`). That is a second JOSE implementation beside PyJWT, which simplejwt requires and so cannot be removed.
- **MSAL Python** (`msal.ConfidentialClientApplication`). It speaks to the Microsoft identity platform only, so it cannot serve a generic provider (R4). It supports a certificate credential and builds the auth-code flow with PKCE and a nonce. **It does not validate the ID token.** Before 1.38.0 its `decode_id_token` checked `iss`, `aud`, expiry and nonce but never the signature, relying on the TLS channel to the token endpoint; since 1.38.0 "MSAL's token acquisition no longer validates the ID token… validation is the application's responsibility" (`msal/oauth2cli/oidc.py`, `decode_id_token` docstring, https://github.com/AzureAD/microsoft-authentication-library-for-python/blob/dev/msal/oauth2cli/oidc.py). Its token cache and account model serve calling Microsoft APIs, which this spec never does. It would add a dependency and still leave ID-token validation, the generic provider and everything else to us.
- **Hand-rolled on PyJWT + requests.** PyJWT 2.15.1 and `cryptography` 50.0.0 are already in `uv.lock` (`:1736`, `:542`), `requests` 2.34.2 too (`:1987`). PyJWT provides what the flow needs (https://pyjwt.readthedocs.io/en/stable/api.html, `PyJWKClient` parameters and `jwt.decode`):
  - `jwt.decode(token, key, algorithms=…, audience=…, issuer=…, leeway=…, options={"require": [...]})`
  - `PyJWK`/`PyJWKSet` (https://pyjwt.readthedocs.io/en/stable/usage.html: JWKS keys are selected by `kid`)

  DB-backed, multi-provider and session-free by construction.

**Chosen: hand-rolled on PyJWT.** It needs no new supply-chain surface and satisfies R1 natively. JWS signing and verification stay in a vetted library. The honest comparison is with Authlib's framework-agnostic client, which would also work: the choice trades a few hundred lines of protocol code we must own and review for not adding a second JOSE stack to pin, scan and keep current.

The cost, as an estimate made after the 2026-11-11 redesign and before any code exists: **1,300 to 1,700 lines of non-test Python** across `apps/accounts/oidc/` and the views, serializers and command around it. About 600 of those are protocol code in the narrow sense (flow, client authentication, ID-token validation, discovery and JWKS); the rest is storage, provisioning, the guard and the admin API, which any library choice would leave to us. The earlier figure of "about 400 lines" counted only the first group and predated the certificate credential, the SSRF policy and the per-transaction cookie. That size is why § 8 and the fable-from-round-one review cadence apply.

We fetch JWKS ourselves with `requests` and build `jwt.PyJWKSet` from the document, rather than using `PyJWKClient`. That gives control over timeouts, redirects, response size, and a Redis cache shared by all four workers (§ 3.5). `PyJWKClient` uses `urllib` with a per-process cache.

## 3. The flow

### 3.1 Endpoints (all under `/api/accounts/oidc/`, all in `apps/accounts/api_urls.py`)

| Method and path | Auth | Purpose |
|---|---|---|
| `GET providers/` | AllowAny, UI ACL | Login-page config: `[{slug, display_name}]` of enabled providers, plus `password_login_enabled` and `password_login_forced` (break-glass active). Never returns an issuer, client id or secret. |
| `GET <slug>/start/?next=<path>` | AllowAny, UI ACL, `oidc` throttle | Begins a **login** transaction and answers with a 302 to the provider. It takes no `intent` parameter: a GET start can never link. |
| `POST <slug>/link/start/` `{next}` | `Authenticated` (JWT), UI ACL, `oidc` throttle | Begins a **link** transaction for the caller (§ 4.2). Sets the binding cookie on this same-origin response and answers `200 {authorize_url}`. The SPA then navigates to that URL. |
| `GET <slug>/callback/` | AllowAny, UI ACL, `oidc` throttle | The redirect URI. Completes the flow, then 302s to the SPA with a handoff code in the fragment. |
| `POST exchange/` `{code}` | AllowAny, UI ACL, `oidc` throttle | Redeems a handoff code (§ 3.3a). |
| `GET/POST/PATCH/DELETE providers-admin/[<id>/]` | `IsAdmin` | Provider CRUD (§ 5). |
| `POST providers-admin/<id>/test/` | `IsAdmin` | Fetches and validates discovery and JWKS, then reports the redirect URI and any problem as fixed codes. Writes nothing. |
| `POST providers-admin/<id>/certificate/` | `IsAdmin` | Generates a **pending** key pair and self-signed certificate (§ 5.2). Answers the certificate, never the key. |
| `GET providers-admin/<id>/certificate/?slot=active\|pending` | `IsAdmin` | Downloads that slot's public certificate as PEM, for upload to the IdP. |
| `POST providers-admin/<id>/certificate/activate/` `{thumbprint_sha256}` | `IsAdmin` | Makes the pending pair the active one, if it is still the certificate named, and sets `client_auth_method` to `private_key_jwt`. 409 otherwise (§ 5.2). |
| `GET/PATCH settings/` | `IsAdmin` (GET also `IsStandardUser`, fields public) | `auth_settings`: `public_base_url`, `password_login_enabled`. For an admin, GET also carries `credential_warnings` (§ 5.2). PATCH runs the § 5.5 guard (from S4; before S4, turning passwords off is refused outright). |
| `GET/DELETE identities/?user=<id>`, `identities/<id>/` | `IsAdmin` | List and unlink a user's SSO identities. |

The `oidc` throttle is a new DRF scope at `20/minute` per IP, using `LoginRateThrottle`'s trusted-proxy `get_ident` (`apps/accounts/throttling.py:8-22`). It is not the shared `login` scope, because one SSO login costs three requests against `login`'s 3/minute.

nginx needs no change: everything sits under `^~ /api/` (`docker/nginx.conf:177-179`). The SPA route `/login/sso` falls through to `location /`.

Every response from `start`, `link/start`, `callback` and `exchange` carries `Referrer-Policy: no-referrer` and `Cache-Control: no-store`.

### 3.2 Start

1. Load the provider by `slug`. 404 if it is absent or disabled. 409 `{"code": "sso_not_configured"}` if `auth_settings.public_base_url` is unset.
2. Validate `next`: it must start with a single `/`, must not start with `//` or `/\`, and must contain no `\`, scheme or control character, with a 512-character maximum. Anything else becomes `/`. Never use an absolute URL.
3. Generate `state` (32 random bytes, base64url), `nonce` (32 bytes) and `code_verifier` (64 bytes base64url, RFC 7636 §4.1), plus `binding` (32 bytes).
4. Write the transaction to Redis at `oidc:tx:<state>`, TTL 600 s, value `{provider_id, provider_version, nonce, code_verifier, binding_hash: sha256(binding), next, intent, link_user_id, created}`. The provider's `version` is recorded for the mix-up check in § 3.3 step 4 only. On `GET start`, `intent` is always `login` and `link_user_id` is null. Only `POST link/start` writes `intent=link`, with `link_user_id = request.user.id` taken from the authenticated caller, never from a parameter.
5. Set the **binding cookie** (ruling B6). Its name is per transaction: `<prefix><tx_id>`, where `tx_id` is the first 16 hex characters of `sha256(state)`. Its value is `binding`.
   - When `public_base_url` is https, the prefix is `__Host-mino_oidc_tx_` and the attributes are `Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age=600`, with no `Domain`. A browser accepts a `__Host-` cookie only with `Secure`, `Path=/` and no `Domain` (draft-ietf-httpbis-rfc6265bis-20 § 4.1.3.2, https://www.ietf.org/archive/id/draft-ietf-httpbis-rfc6265bis-20.txt), so a sibling subdomain or a plain-HTTP origin cannot plant or overwrite it.
   - When `public_base_url` is http (loopback, or the `MINO_OIDC_ALLOW_HTTP` switch: dev and e2e), the prefix is `mino_oidc_tx_` and the cookie has the same attributes without `Secure`. A `__Host-` cookie cannot be set without `Secure`, and browsers differ on whether `http://localhost` may set a `Secure` cookie, so the fallback keys on the scheme alone. One function, `binding_cookie_name(tx_id)`, picks the prefix from `public_base_url`'s scheme, and every reader and writer calls it.
   - **Consequences of `Path=/`.** The prefix forces it, so for up to ten minutes the browser sends this cookie on every request to the origin, not only to `/api/accounts/oidc/`. It is `HttpOnly`, about 80 bytes with its name, and no other code reads it.
   - **Two tabs.** Each transaction has its own cookie name, so a second login tab no longer overwrites the first tab's binding.
   - **Stale cookies.** An abandoned transaction's cookie expires by `Max-Age`. Every refusal after `state` is known, and every exchange, deletes that transaction's cookie (`Max-Age=0`, same name, `Path` and `Secure`). To bound the `Cookie` header, `start` and `link/start` count the request's cookies carrying the prefix: at five or more they expire all of them before setting the new one, which abandons those in-flight transactions.
   - `Lax` is required: the callback is a top-level cross-site GET navigation from the IdP, and `Strict` would drop the cookie. For `link/start`, the cookie is set on the authenticated, same-origin `fetch` response. The binding, and therefore the link, exists only in the browser of the user who asked to link.
6. `GET start` answers with a 302, and `POST link/start` with `200 {authorize_url}`. Both point at the discovered `authorization_endpoint` with:
   - `response_type=code`, `client_id`, `redirect_uri=<public_base_url>/api/accounts/oidc/<slug>/callback/`, `scope`, `state`, `nonce`
   - `code_challenge=BASE64URL(SHA256(code_verifier))`, `code_challenge_method=S256`. **PKCE is always sent and never gated on discovery.** Entra's discovery document has no `code_challenge_methods_supported` (verified live, 2026-11-11), and Entra supports PKCE all the same (v2-oauth2-auth-code-flow, `code_challenge`).
   - `prompt=select_account` if the provider sets `prompt_select_account`
   - no `response_mode`, which leaves the code flow's default, `query`

**Response mode: `query`, with `form_post` considered and rejected (ruling B2, D24).** This deviates from two recommendations, and both are recorded here as what they are:

- Microsoft: "For web applications, we recommend using `response_mode=form_post`, to ensure the most secure transfer of tokens to your application" (v2-protocols-oidc, the `response_mode` row of the sign-in request table).
- RFC 9700 § 4.3.1 (authorization code in browser history) lists as a countermeasure "Use the form post response mode instead of redirect for the authorization response".

Why it is rejected here: a `form_post` response is a cross-site `POST` to the callback. A `SameSite=Lax` cookie is not sent on it, so the binding cookie would have to become `SameSite=None; Secure`, which removes the plain-HTTP dev and e2e path and weakens the cookie that is the login-CSRF defence. The callback would also have to be a CSRF-exempt `POST` endpoint. What `form_post` buys is keeping the code out of URLs, logs and history. Here a logged or remembered code is already useless: redeeming it needs the `code_verifier`, which never leaves Redis, and the client credential, and it is single use at the IdP (§ 3.3, request logs). Microsoft's other reason, the URL length limit, concerns responses that carry tokens; this flow returns only a code.

### 3.3 Callback

Each check refuses with a 302 to `<public_base_url>/login?sso_error=<code>`, a fixed vocabulary that names no claim value, and a `login_failed` event (§ 7). Checks run in this order:

1. If an `error` parameter is present, `GETDEL` the transaction named by `state` (if any), and the result is `idp_error`. Only the `error` value is recorded, and only when it is one of RFC 6749 §4.1.2.1's fixed codes; any other value is recorded as `other`. Application code never logs or stores `error_description` or `error_uri`. The request logs still record them as part of the raw query; see the request-log residual below.
2. Fetch and delete `oidc:tx:<state>` in one step: Redis `GETDEL` through the project's Redis client, falling back to a Lua get-and-delete. A missing transaction is `state_invalid`. Single use is what stops replay.
3. Read the binding cookie named for this `state` (§ 3.2 step 5). Its `sha256` must equal `binding_hash`, compared with `hmac.compare_digest`. A mismatch or missing cookie is `binding_invalid`. **This is the login-CSRF defence.**
4. The transaction's `provider_id` must equal the URL slug's provider, and `provider_version` must equal the row's current version. Otherwise the result is `provider_mismatch`, the mix-up defence (D5).
5. If discovery has `authorization_response_iss_parameter_supported: true`, the `iss` parameter must be present and equal the provider's issuer (RFC 9207). If the parameter is present when not advertised, it must still match. Otherwise `issuer_mismatch`. Entra does not advertise it (verified live, 2026-11-11), so for Entra the mix-up defence is the per-provider redirect URI and step 4.
6. POST the token endpoint with `grant_type=authorization_code`, `code`, `redirect_uri` (identical string) and `code_verifier`, authenticating the client by the provider's `client_auth_method` (§ 3.4a). The URL passes § 3.5's outbound check first. Timeouts are 5 s connect and 10 s read, `allow_redirects=False`, with a 1 MiB response cap.
   - A response whose JSON `error` is `invalid_client` (RFC 6749 § 5.2's fixed code) is `client_auth_failed`. Only that fixed code is read; `error_description` is never logged or stored. This is the result an expired secret or certificate produces, and the login page's copy for it points an administrator at the recovery page (§ 5.6).
   - Any other non-200, or a missing `id_token`, is `token_exchange_failed`.
7. Validate the ID token (§ 3.4). A failure is `id_token_invalid`.
8. Resolve the identity and the level (§ 4). The results are `no_mapping`, `inactive`, `groups_overage`, `link_conflict` or `last_admin`.
9. Mint: `refresh = RefreshToken.for_user(user)`, then:
   - **Lifetime (ruling B3, D25).** `refresh.set_exp(lifetime=settings.OIDC_REFRESH_TOKEN_LIFETIME)`, a new settings constant of `timedelta(hours=12)`. `set_exp` overwrites the `exp` that the constructor stamped from the class lifetime, counting from the same `current_time` (simplejwt 5.5.1 `tokens.py:78, :155-173`). Refresh enforces the token's own `exp` (§ 1), so an SSO refresh token stops working 12 hours after sign-in. The access token is unchanged at 30 minutes, so the last one can outlive the refresh token by up to that: the hard bound on an SSO session is 12 h 30 min. If `ROTATE_REFRESH_TOKENS` were ever switched on, `serializers.py:139`'s bare `refresh.set_exp()` would re-stamp a rotated SSO token with the 1-day class lifetime; a test pins that it is off.
   - **Claims**, all of which survive refresh (§ 1):
     - `refresh["auth_method"] = "oidc"`: D13's refresh gate and the § 5.5 guard read it.
     - `refresh["oidc_provider"] = provider.id`: the refresh rule "provider still enabled" (§ 5.4), D17 and the guard read it.
     - `refresh["oidc_provider_version"] = provider.version`: **D17 only.** It is the cheap "has anything changed" comparison on refresh. The guard no longer reads it.
     - `refresh["oidc_identity"] = identity.id`: **D17 only**, to find the stored claim values.
     - `refresh["oidc_level"] = <the level the mapping produced at § 4.2 step 1>`: **the guard only.** This is what the IdP granted at this sign-in, not the user's stored level, which a local admin can change later.

   That makes five claims. The sixth claim of earlier drafts, `oidc_redirect`, is removed with the redirect-hash proof (ruling B1). Update `last_login`.
10. Store the handoff at `oidc:handoff:<code>`, where `code` is 32 random bytes. TTL 60 s, value `{access, refresh, binding_hash, tx_id, next, intent}`.
11. Re-set the binding cookie, same name and value, with `Max-Age=120`. 302 to `<public_base_url>/login/sso#code=<code>`. A fragment is never sent to a server, a proxy log or a `Referer` header.

Every refusal from step 3 onward also deletes this transaction's binding cookie (§ 3.2 step 5).

**Request logs and the callback query.** The callback URL's query carries `code` and `state`. Two server-side logs can record it:

- uWSGI's `%(uri)` request log (`docker/uwsgi.ini:58-69`, `docker/uwsgi.dev.ini:42-53`, `docker/uwsgi.debug.ini:89`). With `DISPATCHARR_DEBUG=true` it logs every request. Otherwise, in any `DISPATCHARR_ENV` including `dev`, `--disable-logging` (`docker/entrypoint.sh:213-218`) reduces it to the lines `log-4xx`/`log-5xx` keep. A successful callback answers 302 and is not logged. A callback refused **before the view runs** is logged: a 403 from the UI network ACL, a 429 from the `oidc` throttle, or a 5xx.
- nginx's inherited default access log (`docker/nginx.conf` sets no `access_log`), which records every request.
- In a bare `manage.py runserver` dev process only, Django's `django.server` logger: `WSGIRequestHandler.log_message` logs every request line, query included.

The logged URL may therefore carry a `state` that was **never consumed** (an ACL or throttle refusal, or a failure before step 2) and a `code` that was **never redeemed**. On the `error` branch it carries no `code`, and step 1 also deletes the transaction (`GETDEL`) before redirecting. What a reader of those logs can do with the values:

- **A `state`** completes nothing without the browser's binding cookie (step 3). The cookie is HttpOnly and never logged, and the transaction expires 600 s after `start` whether or not it was consumed.
- **A `code`** can be redeemed only with the `code_verifier`, which exists only in the Redis transaction and is never sent to the browser or logged, and with the client credential (§ 5.2). It is single use at the IdP and short-lived there.

**The request logs record the whole callback query, not only `code` and `state`.** An IdP may also send these parameters, and each is recorded as received:

- `error`, `error_description` and `error_uri` (RFC 6749 §4.1.2.1): IdP-authored diagnostic text, which can name the user or the tenant but carries no credential
- `session_state` (OIDC Session Management): an opaque value, usable only alongside the user's own session at the IdP
- `iss` (RFC 9207): the public issuer identifier

None of these completes a flow, or can be replayed to obtain a token.

**Chosen: accept and record this wider residual, rather than redact at the sinks.** Redacting means changing the uWSGI `log-format` and nginx's access log, which govern every path including XC's, or adding a per-path log route to both. That is a cross-cutting change to shared logging, which this spec is not chartered to make, for parameters that carry no credential. `code` and `state` keep their own, separate justification above: they are flow values, and what neutralises them is PKCE, the client credential and the binding cookie.

**The residual is the one exception to § 7's guarantee.** It covers the raw callback query in three request logs only: uWSGI, nginx, and `runserver`'s `django.server`. No secret that completes a flow appears in any URL. Two things that would be worse are designed out:

- The link flow puts no secret in any URL (§ 4.2).
- The handoff code travels only in a fragment.

`SENSITIVE_QUERY_KEYS` (`dispatcharr/utils.py:63`) gains `code`, `state`, `session_state`, `id_token`, `access_token`, `refresh_token`, `client_secret`, `client_assertion` and `code_verifier`, so any Django log line that runs a URL through `redact_url` masks them.

Exceptions from the token and discovery requests, and `ValueError`s from the outbound check, are logged by class name and HTTP status only, never `str(exc)` and never a response body. This is the exception-derived gap that `scripts/check_credential_logging.py:95-98` says the checker cannot see.

### 3.3a Exchange

`POST exchange/` with body `{code}`:

1. Fetch and delete `oidc:handoff:<code>` atomically with `GETDEL`, the same primitive as § 3.3 step 2. If nothing is there (wrong code, already used, or past its 60 s TTL), answer 400 `{"code": "handoff_invalid"}`. Because it is `GETDEL`, two concurrent exchanges of one code cannot both succeed.
2. Read the binding cookie named by the handoff's `tx_id`. Its `sha256` must equal the stored `binding_hash` (`hmac.compare_digest`). Otherwise answer 400 `{"code": "handoff_invalid"}`. The handoff is consumed either way, so a stolen code is worth one failed attempt.
3. Re-validate `next` with § 3.2 step 2's function.
4. Answer `200 {"access", "refresh", "next", "intent"}` (`intent` is `login` or `link`). Set `Cache-Control: no-store`, `Pragma: no-cache` and `Referrer-Policy: no-referrer`, and delete the binding cookie with `Max-Age=0` and the same name, `Path` and `Secure`. Step 2's refusal deletes it too.

### 3.4 ID token validation (OIDC Core 1.0 §3.1.3.7)

The call is `jwt.decode(id_token, key, algorithms=[provider.id_token_alg], audience=provider.client_id, issuer=provider.issuer, leeway=60, options={"require": ["iss","sub","aud","exp","iat","nonce"]})`, with:

- The key is selected from the cached JWKS by the header `kid`. An unknown `kid` triggers one JWKS refetch, with a 60 s per-provider cooldown key, and then refuses.
- **The algorithm comes from the provider's configuration, never from the JWK.** Entra's JWKS entries carry no `alg` member (they carry `kty`, `use`, `kid`, `x5t`, `n`, `e`, `x5c` and `issuer`; verified live, 2026-11-11). PyJWT 2.15.1's `PyJWK` would then guess from `kty`: RS256 for RSA, and **HS256 for `oct`** (`jwt/api_jwk.py:37-66`). So the validator refuses any JWK whose `kty` is `oct`, refuses a `kty` that does not match the configured algorithm's family (RSA for `RS*`/`PS*`, EC for `ES*`, OKP for `EdDSA`), and builds `PyJWK(jwk, algorithm=provider.id_token_alg)` explicitly. A JWK's own `alg`, when present, must equal the configured one.
- `id_token_alg` defaults to `RS256` and is restricted to `{RS256, RS384, RS512, PS256, PS384, PS512, ES256, ES384, EdDSA}`. `none` and every `HS*` are refused at save time and at validation. An HMAC ID token would be keyed by the client secret, which is a key-confusion hazard.
- `azp`, whenever it is present, must be a string equal to `client_id`, whatever the shape of `aud`: a scalar, a one-element list or several entries. If `aud` has more than one entry, `azp` must also be present. A present `azp` that is not a string, or that differs from `client_id`, is refused (OIDC Core §3.1.3.7, items 4-5).
- `nonce` must equal the transaction nonce (`hmac.compare_digest`).
- Entra preset: `tid` must equal the configured tenant GUID, and `iss` must equal `https://login.microsoftonline.com/<tid>/v2.0` exactly. With a tenant-specific discovery document, the exact `iss` match "is all that is needed" (https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens, § Validate the issuer). The `tid` check is defence in depth.
- `c_hash` and `at_hash` are not checked. Entra documents that `c_hash` "isn't returned on ID tokens from the /token endpoint" (id-token-claims-reference), and the code-flow token-endpoint response is TLS-protected.

### 3.4a Client authentication at the token endpoint (D23)

`client_auth_method` is one of three values. The Entra preset offers the first two and **defaults to `client_secret_post`**; activating a certificate switches it to `private_key_jwt` (§ 5.2). The generic form offers all three and defaults to `client_secret_basic`, which RFC 6749 § 2.3.1 says an authorization server MUST support.

- **`private_key_jwt`** (ruling B4; RFC 7523, OIDC Core § 9). The request carries `client_id`, `client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer` and `client_assertion`, in place of `client_secret` (v2-oauth2-auth-code-flow, § Request an access token with a certificate credential). The assertion is built per request with `jwt.encode(claims, private_key, algorithm=…, headers={"x5t#S256": …})`; PyJWT 2.15.1 adds `typ: JWT` and `alg` itself (`jwt/api_jws.py:160`). Its shape follows Microsoft's certificate-credentials page (https://learn.microsoft.com/en-us/entra/identity-platform/certificate-credentials, § Assertion format):
  - Header: `alg` `PS256` ("Should be **PS256**… Use PSS padding"), `typ` `JWT`, and `x5t#S256`, the base64url SHA-256 thumbprint of the certificate's DER encoding. That page no longer lists the SHA-1 `x5t` header, so it is not sent.
  - Claims: `iss` and `sub` are both the client id. `aud` is the discovered `token_endpoint`, which for Entra is the documented `https://login.microsoftonline.com/{tenantId}/oauth2/v2.0/token`, and which OIDC Core § 9 says the audience SHOULD be. `jti` is a fresh `uuid4`. `iat` and `nbf` are now, and `exp` is now + 300 s (the page: "keep it short - 5-10 minutes after `nbf` at most").
  - A generic provider may set `client_assertion_alg` to `RS256` instead, for an OP without PSS. The Entra preset fixes `PS256`.
- **`client_secret_post`**, the Entra preset's method when a secret is used. `client_id` and `client_secret` go in the form body, which `requests` form-encodes. Microsoft: "Like all parameters here, the client secret must be URL-encoded before being sent" (v2-oauth2-auth-code-flow, the `client_secret` row).
- **`client_secret_basic`.** The client id and the secret are **each** encoded with the `application/x-www-form-urlencoded` algorithm before they are joined with `:` and base64-encoded: "The client identifier is encoded using the `application/x-www-form-urlencoded` encoding algorithm per Appendix B, and the encoded value is used as the username; the client password is encoded using the same algorithm and used as the password" (RFC 6749 § 2.3.1). In Python that is `urllib.parse.quote_plus(value, safe="")` on the UTF-8 string. `requests`' `auth=(id, secret)` is **not** used: it base64-encodes the raw values. An OP that expects the raw form is not conformant, and `client_secret_post` is the remedy the admin UI names.

### 3.5 Discovery and JWKS fetching and caching

- **Discovery URL.** Strip one terminating `/` from the configured issuer, then append `/.well-known/openid-configuration`: "If the Issuer value contains a path component, any terminating / MUST be removed before appending /.well-known/openid-configuration" (OIDC Discovery § 4.1). The **stored issuer is not normalised**. The document's `issuer` must equal it exactly, trailing slash included, and so must the ID token's `iss` (OIDC Discovery § 4.3: "MUST be identical"). `authorization_endpoint`, `token_endpoint` and `jwks_uri` must be present.
- The configured issuer, and every discovered endpoint, must be `https`, unless the env var `MINO_OIDC_ALLOW_HTTP=1` is set. That is a deployment-level switch the e2e stack uses, read once into `settings.OIDC_ALLOW_HTTP`. It is not a DB setting, so it cannot be enabled from the web.
- **Every server-side fetch passes the repository's SSRF check (D22, § 1 Outbound HTTP).**
  - Discovery and JWKS are fetched with `fetch_outbound_http(url, allow_private=provider.allow_private_network, allow_loopback=settings.OIDC_ALLOW_HTTP, max_redirects=0, timeout=(5, 10), stream=True)`. `max_redirects=0` makes the first redirect an error rather than a hop.
  - The token request is a `POST`, and `fetch_outbound_http` is GET only (`core/http_security.py:248`). So it calls `validate_outbound_http_url(token_endpoint, …)` with the same two flags, then `requests.post(…, allow_redirects=False)`. It does not extend the shared helper: that is a change to a module other code depends on, for one caller.
  - `token_endpoint` and `jwks_uri` come from the IdP's document, so they are checked **at every use**, not only when the provider is saved. A discovery document that names `http://169.254.169.254/…` is refused whatever the flags.
  - **`allow_private_network`** is a per-provider boolean, default false. A LAN IdP (Authentik or Keycloak on an RFC 1918 or Tailscale address) needs it, and its help text says so. The Entra preset refuses it, because Entra is never on a private address. It is a database field rather than an environment variable because R1 puts provider configuration in the UI, and because the people who need it are exactly the self-hosters with a LAN IdP. It widens what an admin can make the server fetch, which the image and logo proxies already allow (`core/http_security.py:30-31`). Link-local (metadata included), unspecified and multicast addresses stay refused under either setting. With the flag on, the helper admits everything Python calls `is_private`, which includes some reserved and benchmarking ranges as well as RFC 1918 (§ 1 Outbound HTTP). That is the inherited behaviour of the shared helper, accepted here as it is for its other `allow_private` callers; this spec neither rewrites the helper nor adds an OIDC-local stricter list.
  - **Loopback** is allowed only under `MINO_OIDC_ALLOW_HTTP`, for the unit tests' in-process OP and for a developer's local one.
  - The residual is the helper's own: DNS can change between the check and the connect (`core/http_security.py:219-220`). It is accepted, as it is for that module's other callers.
  - A refusal reaches the admin `test` action as a fixed code naming the endpoint (`discovery_not_allowed`, `jwks_uri_not_allowed`, `token_endpoint_not_allowed`), never as the helper's message, which names the resolved address.
- Both documents are cached in the Django cache (Redis, shared by every process): `oidc:disco:<provider_id>:<version>` and `oidc:jwks:<provider_id>:<version>`, TTL 3600 s. Every security-relevant provider edit bumps `version` (§ 5.1), so an edit is never served a stale document. Entra recommends checking for key updates about every 24 h; an hour is stricter.
- Fetches use 5 s connect and 10 s read timeouts, a 1 MiB cap enforced while streaming, and default TLS verification. Under the API's gevent monkey-patching these are cooperative. They happen only on `start`, `callback` and the admin `test` action, never on an ordinary API request.
- **What live Entra's documents contain** (verified 2026-11-11), for implementers and for the fake OPs, which mimic the first two points:
  - JWKS entries have no `alg` member, and do carry `x5c` and `issuer`.
  - Discovery has neither `code_challenge_methods_supported` nor `authorization_response_iss_parameter_supported`.
  - `token_endpoint_auth_methods_supported` is `client_secret_post`, `private_key_jwt`, `client_secret_basic`, `self_signed_tls_client_auth`.
  - `id_token_signing_alg_values_supported` is `RS256` only.

### 3.6 Entra preset specifics

- **Fields.** Tenant id (a GUID; `common`, `organizations`, `consumers` and domain names are refused), client id, the credential (a certificate generated here, or a client secret; § 5.2), the credential's expiry date, and display name. The issuer is derived as `https://login.microsoftonline.com/<tenant>/v2.0`, and discovery as `<issuer>/.well-known/openid-configuration`. `client_auth_method` is `private_key_jwt` or `client_secret_post` (§ 3.4a). `allow_private_network` is refused (§ 3.5).
- **The preset is the global cloud only.** It hardcodes `login.microsoftonline.com`. The national clouds have their own endpoints, `https://login.microsoftonline.us` and `https://login.partner.microsoftonline.cn` (https://learn.microsoft.com/en-us/entra/identity-platform/authentication-national-cloud, § Microsoft Entra authentication endpoints), and External ID tenants sign in at `<tenant-name>.ciamlogin.com` (https://learn.microsoft.com/en-us/entra/external-id/customers/concept-custom-url-domain). Those tenants use the **generic** form, with the issuer copied from their own discovery document. What they lose is everything the preset adds: the derived issuer, the `tid` check, the refusal of the multi-tenant aliases, the groups-overage refusal, the `PS256` assertion default and the Entra-specific help text. The standard checks (exact `iss`, `aud`, signature, nonce) still apply. The form says so beside the preset.
- **Redirect URI length.** Entra allows "a maximum of 256 characters for each redirect URI" (reply-url, § Maximum number of redirect URIs and URI length). The redirect URI of an Entra provider is validated to at most 256 characters wherever it can change: creating an Entra provider, changing a provider's `slug` or `kind`, and saving `public_base_url`, each against every Entra provider. A longer one is refused with 400 `{"code": "redirect_uri_too_long"}`. The URI is built from two rows, so each of those writes takes § 5.5's `auth_settings` row lock first, then **reloads** `public_base_url` and the affected slugs under it, and validates what it reloaded. Without that, a slug edit and a base-URL edit could each pass against the other's old value and commit a combined URI that is too long.
- **Why single tenant.** The multi-tenant endpoints return the templated issuer `https://login.microsoftonline.com/{tenantid}/v2.0`. Validating it requires substituting `tid`, checking it is a GUID, and checking the signing key's own `issuer` property (access-tokens page, § Multitenant applications and § Validate the signing key issuer). That is a known pitfall with no use for a homelab instance, so it is refused rather than half-implemented.
- **Default mapping claim: `roles`.** It is an array of app-role values ("the set of roles that were assigned to the user", id-token-claims-reference) and is emitted when app roles are defined on the registration and assigned. The admin UI text tells the owner to create app roles, for example `Mino.Admin` and `Mino.User`, and assign users or groups to them.
- **`groups` is allowed but discouraged.** A JWT carries at most 200 groups. Above that, the token carries `_claim_names: {"groups": "src1"}` with `_claim_sources`, or `hasgroups: true`, instead of `groups` (id-token-claims-reference, § Groups overage claim). When the mapping claim is `groups` and either marker is present, the login is refused with `groups_overage`. No Graph call is made (D15).
- **Identity claims.** `sub` is pairwise per application. That is fine because identities are keyed per provider. `oid` and `tid` are stored as display metadata only.
- **Never authorize on `email` or `preferred_username`.** Entra: email "isn't guaranteed to be correct and is mutable… Never use it for authorization", and preferred_username "can't be used to make authorization decisions" (id-token-claims-reference).

### 3.7 Generic provider

Fields: display name, slug, issuer URL, client id, client auth method (§ 3.4a) with its credential (a client secret, or a certificate generated here; § 5.2), the credential's expiry date, `allow_private_network` (§ 3.5), scopes (default `openid profile email`; must contain `openid`), ID-token alg, mapping claim path, mappings, `prompt_select_account` and enabled.

The mapping claim path is a dotted path into the ID token's claims. Each segment is a key, with no escaping and no wildcards. Keycloak's `realm_access.roles` is the motivating case. The value must be a string or a list of strings; any other type matches nothing. Claims are read from the ID token only. The UserInfo endpoint is not called, so a provider must be configured to put the mapping claim in the ID token. The admin UI says so.

## 4. Identity linking and provisioning

### 4.1 Model

`OIDCIdentity` (new, in `apps/accounts/models.py`):

- `user` FK, `on_delete=CASCADE`
- `provider` FK, `on_delete=PROTECT`
- `issuer`, `subject`
- `email_at_last_login`, `display_name`, `extra` (JSON: `tid`/`oid` for Entra)
- `mapping_claim_path` (string): the provider's `claim_path` at the last successful login, which is the path `mapping_claim_values` was read from
- `mapping_claim_values` (JSON list of strings): the values of the provider's mapping claim from the last successful login, at most 200 entries (Entra's JWT group limit). D17 recomputes from these. It is never logged, and never sent in an event or an API response other than the admin `identities/` detail.
- `created`, `last_login`

A unique constraint covers `(provider, issuer, subject)`. A provider with identities cannot be deleted (`PROTECT`); the admin disables it, or unlinks the identities first. While identities exist, the provider's **`issuer`, Entra tenant and `client_id`** cannot be changed. The save is refused with a message saying to create a new provider, then have each person link it (§ 4.2) or unlink and re-provision. Any of the three edits would silently JIT a duplicate user for every person: `sub` is scoped to the issuer, and Entra's `sub` is pairwise per application, so a new client id means new subjects.

### 4.2 Resolution on callback

Authorization is decided **before any write**. `ATOMIC_REQUESTS` is `False` (`dispatcharr/settings.py:162`), so the order is explicit:

1. **Level, computed with no DB write.** Evaluate the mapping, an ordered list of `{value, user_level}`, against the claim. The **highest** matched level wins. No match means refuse with `no_mapping`; nothing has been written and the stored level is left untouched. A groups overage is refused here too (§ 3.6). A refused login leaves no user, no identity and no changed row.
2. **One `transaction.atomic()` block** does everything below, under one lock protocol for every callback, whatever level it maps to:
   - **When step 1's level is below Admin, its first statement is `admin_floor_lock()`** (§ 4.4), before any row lock.
   - **A callback never waits for an identity row while it holds a user row.** For an identity that exists, the identity row is locked first and its user second (step 3). For an identity this callback creates, the user row is locked or inserted inside an attempt savepoint together with the identity insert (steps 4 and 5); if that insert conflicts, the savepoint is rolled back, which releases the user row, **before** the winner's identity is locked. No callback locks a set of other users' rows. § 4.4's table lists the order for every path.
   - **The user every later step judges is the row as locked here, never an object loaded earlier.** Step 6's `last_admin` test and its write both use it.
3. **Known identity.** `(provider, iss, sub)` exists, read with `select_for_update`.
   - With `intent=link`, compare `identity.user_id` with `link_user_id` first. If they differ, refuse with `link_conflict`, before anything else is decided and without locking the other user's row.
   - Then read its user with `User.objects.select_for_update().get(pk=identity.user_id)` and use that row.
   - If `user.is_active` is false, refuse with `inactive`. SSO never reactivates a user.
4. **Link intent, unknown identity.** One **attempt savepoint** (`with transaction.atomic():`) holds both the lock on the target user and the identity insert:

   ```text
   try:
     with transaction.atomic():              # attempt savepoint
       user = User.objects.select_for_update().get(pk=link_user_id)   # gone or inactive: refuse inactive
       insert OIDCIdentity(provider, iss, sub, user)
   except IntegrityError on the (provider, issuer, subject) constraint:
     # the attempt savepoint is rolled back: the lock on the target user is released
     continue as step 3 with the winner's identity
   ```

   - The lock sits **inside** the savepoint on purpose. The "unknown identity" lookup ran before any lock, so another transaction may have created the identity since. If the user lock were taken outside the savepoint, this callback would hold the user row while waiting for the winner's identity row, the reverse of step 3's order: an Admin-mapped callback that has locked that identity and is waiting for the same user would deadlock with it. PostgreSQL releases a row lock taken inside a savepoint when that savepoint is rolled back, so after the conflict this callback holds no user row and step 3 takes identity, then user.
   - **Who owns the winner is checked, not assumed.** Step 3's comparison runs on the winner's identity. If it belongs to another user the result is `link_conflict`, before step 6, so the losing user's level is not changed. If it belongs to `link_user_id` (the same person linked from a second tab, or a concurrent link for the same user), the link is already made, and the callback continues as a known identity and succeeds.
   - A user-row lock does not stop a second link transaction, for a **different** local user, from inserting the same identity, and `select_for_update` cannot lock a row that does not exist yet; the constraint is what decides.
   - The mapping still applies (step 6), so an admin who links an IdP account that maps to Standard is demoted. The UI warns about this before linking.
   - The link transaction exists only in the browser that called `POST link/start` with its own JWT (§ 3.2 steps 4-5).
5. **Unknown identity, login intent.** JIT-create the user:
   - Start from `preferred_username`, falling back to `email`. **Never from `sub`**: the username is written to `SystemEvent` details as `user` (§ 7), and `sub` must not appear there.
   - Reduce it to the `SAFE_CREDENTIAL_RE` alphabet. If nothing is left, or neither claim is present, use `sso-` plus 8 random lowercase hex characters, which is unrelated to any claim.
   - Every candidate fits the 150-character column (`apps/accounts/migrations/0001_initial.py:26`): the base is truncated to `150 - len(suffix)` for each suffix, so `base[:150]`, `base[:148] + '-2'`, …, `base[:147] + '-20'`. The username is a label only, never an identity key.
   - Call `set_unusable_password()`. Set `email` and `first_name`/`last_name` from `email`, `given_name` and `family_name` when present.
   - Set `is_staff` and `is_superuser` to false. Leave `channel_profiles` empty, which `apps/proxy/authorize.py:202-223` reads as unrestricted, exactly like a user created in the Users page with none. Set `stream_limit` to 0 and add no `xc_password`, so an SSO user has no XC access until an admin grants it.
   - **Conflicts are told apart by constraint, not by catching any `IntegrityError`.** Savepoints nest like this:

     ```text
     transaction.atomic()                    # outer, step 2
       try:
         with transaction.atomic():          # attempt savepoint: BOTH inserts
           for suffix in ('', '-2', … '-20'):
             try:
               with transaction.atomic():    # username savepoint
                 user = insert User(username=base + suffix)
               break
             except IntegrityError on the username constraint: continue
           else: refuse provisioning_failed
           insert OIDCIdentity(provider, iss, sub, user)
       except IntegrityError on the (provider, issuer, subject) constraint:
         # the attempt savepoint is rolled back: this attempt's User is gone
         continue as step 3 with the winner's identity: lock it, then its user
     ```

     The identity conflict is caught **outside** the attempt savepoint, so rolling that savepoint back removes this attempt's user row. The winner lookup then runs inside the still-open outer transaction. Any other `IntegrityError` propagates, and the outer transaction rolls back.
   - **No email-based matching of an existing local user, ever.**
6. **Apply the level.** If the user is an Admin, step 1's level is lower, and a count made under `admin_floor_lock()` finds no **other** active admin, refuse with `last_admin` (§ 4.4, D21). The exception rolls the whole block back, so a link attempt leaves no identity, and nothing about the user or an existing identity changes. Otherwise set `user.user_level` from step 1 if it changed (D9), and store this login's `mapping_claim_path` and `mapping_claim_values` on the identity. Commit.

SSO never writes `channel_profiles`, `stream_limit`, `custom_properties`, `api_key` or `is_active` after creation. Those stay local admin decisions.

### 4.3 Lifecycle consequences, stated for the owner

- **Mapping removed or role unassigned in the IdP.** The next SSO login is refused. An already-issued pair keeps working until its refresh token expires, 12 hours after sign-in (D25), plus an access-token tail of at most 30 minutes. To stop it at once, an operator deactivates the local user. `JWTAuthentication` refuses inactive users (simplejwt 5.5.1 `authentication.py:138`), and so does refresh. At the seed SHA there is no UI or API control for this: `UserSerializer` does not expose `is_active` (`apps/accounts/serializers.py:60-77`), the Django admin fieldsets omit it (`apps/accounts/admin.py:13-17`), and S4 closes the admin site while password login is off. From PR S0 an admin deactivates the user on the Users page (D20, § 5.8). The operator doc page (S4) keeps a paste-ready command as the break-glass path, for when no admin can sign in:

```bash
docker exec <container> su - dispatch -c 'cd /app && python manage.py shell -c "from apps.accounts.models import User; print(User.objects.filter(username=\"<name>\").update(is_active=False))"'
```

It prints `1` when the user existed. It is wrapped in `su - dispatch -c` for the reason § 5.6 gives under "How the commands are run". S0 pins the effect through the API (§ 5.8), and S2 pins it for SSO tokens: `apps.accounts.tests.test_oidc_flow.DeactivationTests.test_inactive_user_access_and_refresh_refused` deactivates an SSO user by queryset `update()`, then asserts 401 on both their access token and their refresh token.
- **Role changed in the IdP.** Applied at the next SSO login, not mid-session. Refresh makes no IdP call, so it cannot see this.
- **Mapping changed in this app** (an admin edits the provider's mappings or claim path). This bumps the provider version, so the next refresh of each user's token recomputes their level from their stored claim values (D17). A lower level demotes at once, and no match refuses the refresh, so the user must sign in again and is then refused with `no_mapping`. A higher level waits for the next login.
- **Local user deleted.** The identity cascades, and the next SSO login JIT-creates a **new** user with a new id and no history. To block a person, deactivate them; do not delete them. The Users page says this on the delete dialog for a user with linked identities.
- **Provider disabled.** Its start and callback 404, and its refresh tokens are refused (§ 5.4). Its users can still use the password, if they have one and password login is on.
- **The IdP would demote the last active admin.** That login, link or refresh is refused with `last_admin`, and the user stays an Admin locally (§ 4.4). The fix is in the IdP or the mapping, or by making someone else an Admin first.
- **The provider's credential expires at the IdP.** Every sign-in through it fails with `client_auth_failed`. Existing sessions run out within 12 hours. § 5.2's expiry date exists to warn before this, and § 5.6 is the recovery when it happens with password login off.

### 4.4 An active admin always remains (D21)

**The defect this closes.** `initialize_superuser` creates an Admin for any caller on a private address whenever no user has `user_level >= 10` (§ 1). SSO lowers levels in three places: the callback on login (D9), the callback on link (§ 4.2 step 6), and token refresh (D17). Without a rule, an IdP mapping change that demotes the only admin would reopen that endpoint, unauthenticated, to the LAN.

**The rule.** No SSO login, link or refresh may lower the level of a user who is the last **active** admin (`is_active` and `user_level >= 10`). The attempt is refused with the named error `last_admin` and writes nothing:

- on the callback, a 302 to `/login?sso_error=last_admin` and a `login_failed` event with that reason (§ 4.2 step 6)
- on refresh, 401 `token_not_valid` and a `login_failed` event with reason `last_admin` (§ 5.4)

"Active" is stricter than the bootstrap's own test, which ignores `is_active`. It is the right bound all the same: an instance whose only admins are deactivated is locked out even though the bootstrap stays closed.

**Locking.** One helper, `apps/accounts/admin_floor.py`'s `admin_floor_lock()`, takes a PostgreSQL transaction-scoped advisory lock on one fixed key (`SELECT pg_advisory_xact_lock(<constant>)`). It must be called inside `transaction.atomic()`, as that transaction's **first** statement, and it is released at commit or rollback. It is a mutex over "writes that can remove an active admin", and it locks no row. Callers are listed below.

**The guarantee is a PostgreSQL guarantee, and a runtime SQLite instance does not get the feature.** Two non-PostgreSQL cases exist and they are treated differently:

- **The test fallback**, `TEST_USE_SQLITE=1` (`dispatcharr/settings_test.py:39-47`). The helper does nothing there, and the concurrency tests that depend on it skip themselves, as the tree's other PostgreSQL-only tests do. Every single-request test still runs.
- **A runtime SQLite database.** `dispatcharr/settings.py:259-265` switches the live database to SQLite when `DB_ENGINE=sqlite`. Nothing else in the tree sets or documents that variable, and the image's entrypoint always provisions PostgreSQL, but the branch exists. A silent no-op there would leave D20 and D21 promising a serialization that is not happening. So `settings.py` sets `RUNTIME_SQLITE = True` in that branch and `False` otherwise. **`settings_test.py` then sets `RUNTIME_SQLITE = False` explicitly, after its `from dispatcharr.settings import *`.** That line is needed: the star import at `settings_test.py:22` executes `settings.py` first, so a test process that inherits `DB_ENGINE=sqlite` takes the runtime branch and would carry `True` into the tests, whichever database `settings_test.py:39-47` goes on to choose. The marker describes the live database only, and under test the suite decides refusals with `override_settings`. On a runtime SQLite instance the writes that depend on the floor are **refused with 400 `{"code": "requires_postgresql"}`**:
  - S0: a `PATCH` setting `is_active` to false
  - S1: creating an `OIDCProvider`. With no provider there is no SSO login, link or refresh, and the password toggle cannot be switched off, because § 5.5 needs an SSO session. `password_login --disable` exits non-zero with the same reason and has no `--force` past it.

  Refusal is chosen over specifying SQLite's behaviour because the alternative is to reason about, and test, SQLite's writer lock under Django's deferred transactions for a configuration the product does not ship. Reactivating a user, and everything else in S0, works on SQLite.

Callers of the helper:

- **S0's deactivation guard** (§ 5.8), for a PATCH that sets `is_active` to false.
- **The callback**, when the mapped level is below Admin (§ 4.2 step 2). It is taken before the identity is looked up, so before the callback can know whether the user is an Admin. The cost is that below-Admin sign-ins queue behind each other for the length of one short transaction, which makes no network call (the token exchange is finished before step 2).
- **D17's refresh re-evaluation**, when the recomputed level is below Admin (§ 5.4).

**The floor protocol, the same in every caller:**

1. `admin_floor_lock()`.
2. In a callback only, the identity row (§ 4.2 step 3).
3. **Reload and lock the target**: `target = User.objects.select_for_update().get(pk=…)`. This row lock is held through the write.
4. Decide on `target`, and on nothing loaded before step 1: refuse when `target` is an active admin, the write would lower its level or deactivate it, and `User.objects.filter(is_active=True, user_level__gte=10).exclude(pk=target.pk).exists()` is false.
5. Write.

**Why step 3 is required.** The mutex serializes the floor's writers, but it does not refresh a Python object a request loaded before it queued. Without the reload this sequence, which uses only permitted paths, ends with no admin. A is Admin and U is Standard. U's token refresh loads U and is delayed before its locking block. An Admin-mapped callback promotes U. A's below-Admin callback takes the mutex, correctly sees U as another active admin, and demotes A. U's refresh then takes the mutex; its stale U says Standard, so it never asks the last-admin question, and its conditional update lowers U's **current** level, which is Admin. The same shape applies to S0: `UserViewSet` loads the target before `perform_update` runs (`apps/accounts/api_views.py:276-278`).

**Admin-mapped callbacks still do not take the mutex, and after step 3 that is sound for a stated reason.** The floor needs two things from a promotion: that a demoter judging the *promoted* user sees the promotion, and that a promotion never makes a demoter's count of *other* admins too high. Step 3 gives the first: the demoter's `select_for_update` on the target waits for a promoting transaction that holds that row, then reads the committed level. The second holds because a count under READ COMMITTED sees only committed admins: a promotion still in flight is not counted, so the demoter refuses conservatively, and a promotion that rolls back was never counted. A promotion cannot reduce the admin set, so it has nothing to serialize against. Making promoters queue on the mutex would buy nothing and would put every Admin sign-in behind every other.

**Why a mutex and not row locks on the admins.** The first redesign locked every active admin row (`select_for_update`) in the below-Admin paths. That set is dynamic, and locking it inverts the identity-then-user order that Admin-mapped callbacks use. A concrete cycle: an Admin-mapped callback locks identity I and has read its user U as Standard; a local promotion commits U as Admin (`UserViewSet.update`, `apps/accounts/api_views.py:276-278`, an existing writer); a second, demoting callback for I then locks U as part of the admin set and waits for I; the first callback's update of U waits for the second. PostgreSQL aborts one. With the advisory lock nothing ever holds a user row while waiting for an identity row:

**Status of this protocol.** Everything in this subsection is specified, not demonstrated. No part of it has been executed at spec time: the orders in the table were derived by reading the base tree and reasoning about PostgreSQL and Django, and four review rounds each found an interleaving the previous version missed. It is to be proven by the named concurrency tests (T15a, T26, T27, T30, T31, T36 and § 5.5's two) running against a real PostgreSQL in the implementation PRs, and an implementer who finds a path this table does not list adds it here before writing code for it.

**The lock-order table.** This is the one place to check an ordering. It lists every path in this spec that takes a lock, and the existing writers they meet. "sfu" is `select_for_update`. A row in brackets is taken only when the mapped or recomputed level is below Admin.

| Path | Locks, in order | Notes |
|---|---|---|
| callback, identity exists (login or link; § 4.2 step 3) | [advisory] → identity (sfu) → its user (sfu) | then updates both rows it holds |
| callback, new identity, login (JIT; step 5) | [advisory] → inside the attempt savepoint: new user row (insert) → identity (insert) | on an identity conflict the savepoint is rolled back, dropping the new user row, and the path becomes the row above |
| callback, new identity, link (step 4) | [advisory] → inside the attempt savepoint: target user (sfu) → identity (insert) | on an identity conflict the savepoint is rolled back, releasing the user row, and the path becomes the first row |
| refresh, version unchanged (§ 5.4) | none | no lock and no write |
| refresh, re-evaluation that may lower (§ 5.4) | advisory → the token's user (sfu) | provider and identity are re-read with plain queries under the user lock; never an identity row lock |
| refresh, re-evaluation that yields Admin before the lock | none | no write |
| S0 deactivation (§ 5.8) | advisory → target user (sfu) | the transaction covers the guards and the scalar save only; a `channel_profiles` change in the same PATCH is written after it commits, with no user lock held |
| `PATCH settings/`, `password_login` command (§ 5.5) | `auth_settings` row (sfu) | provider rows are read, not locked |
| provider create, delete, update setting `enabled` false, update changing `slug` or `kind` (§ 5.5, § 3.6) | `auth_settings` row (sfu) → the provider row (its own write) | |
| any other provider update (§ 5.1) | the provider row (its own write) | |
| certificate generate, activate (§ 5.2) | the provider row (sfu) | never `auth_settings` |
| identity unlink (`DELETE identities/<id>/`) | identity row (its own delete) | |
| Users API update or `me` PATCH (existing) | user row (its own write); then, separately, `channel_profiles` through rows | autocommit: each statement is its own transaction, so the user row is not held while the through rows are written |
| Users API delete (existing; from S2 it answers 409 on an `IntegrityError`, see below) | the user's dependents, then the user row | the dependents are the `channel_profiles` through rows (`apps/accounts/models.py:25-29`), the `groups` and `user_permissions` through rows it inherits from `AbstractUser`, `NotificationDismissal` rows (`core/models.py:977-987`) and, from S1, `OIDCIdentity` rows. Django's deletion collector deletes cascading dependents before the row they point at; this spec relies on that order and does not change it |

Three families of rows are involved, and each has one order: **advisory → identity → user** for accounts, **`auth_settings` → provider** for configuration, and nothing that holds a lock in one family asks for a lock in the other. **The rule that keeps the delete path out of every cycle is about the order locks are acquired, not about writes: no transaction in this spec acquires a lock on an existing dependent of a user row while it already holds that user row.** A user delete holds dependents and then asks for the user, so a path that held the user and then asked for an existing dependent would deadlock with it. Writing a dependent whose lock was taken **before** the user row is fine, and the known-identity callback does exactly that: it locks the identity, then the user, then updates both. The one dependent touched after the user row is an identity the transaction is itself inserting inside the attempt savepoint. The advisory lock is only ever a transaction's first lock. A path that holds a user row and then touches an identity does so only for an identity row it is itself inserting, which no other transaction can hold or wait behind a lock on; if the insert conflicts with a committed row, the user row is released before the existing identity is locked. So no cycle exists among these paths.

**Dependents of a user row, checked path by path (round 4).** A review found one violation of the rule above: S0's guarded update ran `UserSerializer.update` inside its transaction, and that method calls `instance.channel_profiles.set(…)` after the save (`apps/accounts/serializers.py:130-165`), so a PATCH of `{is_active: false, channel_profiles: []}` held the user row and waited for a through row that a concurrent delete of the same user already held. § 5.8 now writes the profiles after the transaction. The other paths were checked for the same shape:

- **JIT user creation** (§ 4.2 step 5) inserts the user row and nothing else. `channel_profiles` is left empty by not touching it; there is no `.set()` and no through-row write, and none to `groups` or `user_permissions`.
- **The callback's level write** (step 6) and **D17's** are single-column updates of `user_level`. The callback's `last_login` update is likewise one column. None goes through `UserSerializer`.
- **Link** inserts an identity while holding the user row. That is the one dependent touched after the user row: the row is new, so a delete of that user cannot already hold it, and no deadlock follows. **The delete can still lose, and its outcome is specified.** Django's `CASCADE` is done by the deletion collector in Python, not by the database. A `DELETE users/<id>/` that is waiting for the user row has already finished collecting and deleting the identities it could see, so when the link commits, the new identity still references the user and the delete fails its foreign-key constraint with an `IntegrityError`. At the seed `UserViewSet.destroy` has no handling for that (`apps/accounts/api_views.py:280-282`). From S2, `destroy` catches `IntegrityError` and answers **409 `{"code": "user_changed_during_delete"}`**. The user row is not deleted, there is no retry loop, and the admin retries; the second attempt sees the identity and removes it with the user. The user row is **not** locked ahead of its identities to avoid this: that is the order this table forbids. It lands in S2 because that is the first PR in which anything inserts an identity under a user lock.
- **No path in this spec writes `NotificationDismissal`, `groups` or `user_permissions`.**

**What this pass found (2026-11-11, round 3).** Walking every path against the table turned up, beyond the link-conflict inversion a review had reported: the known-identity link branch locked another user's row before refusing `link_conflict`, which was harmless but needless and is now refused first (§ 4.2 step 3); and the Users API delete path, which this spec does not change but meets, was not in any ordering argument and is now listed with the assumption it rests on.

**What the rule does not cover, and the bootstrap decision.** Local paths can still remove the last admin: an admin can demote or delete themselves through `UserViewSet` (§ 1), and S0 guards deactivation only. Those are existing behaviour and stay out of scope. As defence in depth for an SSO-configured instance, **`initialize_superuser` also stays closed while any `OIDCProvider` row exists**: both its GET status and its POST treat that as "already set up". Such an instance holds an IdP credential and SSO-provisioned users, and must not be claimable from the LAN whatever local path emptied its admin set. Recovery is then the CLI (`createsuperuser`, § 5.6).

**Considered and not done: closing the bootstrap once any user exists.** It would cover the local paths on every instance. It also changes behaviour that upstream pinned on purpose (`apps/accounts/tests/test_accounts.py:35-44`: the bootstrap is open when only a non-admin user exists), which is the only web recovery for a non-SSO instance that lost its admin. That is a product decision outside this spec, and it is put to the owner as Q9.

**Tests.** T30 pins the helper under S0's deactivation guard. T31 pins the bootstrap (S1) and the three SSO paths (S2).

**Addendum (2026-11-12, added by PR #661; the text above is unchanged).** The wait for the advisory lock is bounded at 5 s (`apps/accounts/admin_floor.py`, `LOCK_WAIT_SECONDS`): `admin_floor_lock()` sets `lock_timeout` for the lock alone and restores the previous value once it is granted, so later row locks wait as before. A caller not granted the lock in time writes nothing (its transaction rolls back) and answers:

- the Users API deactivation (§ 5.8): **503 `{"code": "admin_floor_busy"}`** with `Retry-After: 1`;
- token refresh (§ 5.4): the same 503 with `Retry-After: 1`, never a 401, and the refresh token is not used up;
- the SSO callback login and link (§ 4.2): the existing **`provisioning_failed`** redirect.

## 5. Runtime configuration

### 5.1 Storage (D7)

- **`OIDCProvider`** (new, `apps/accounts/models.py`). Columns:
  - `slug` (unique, `[a-z0-9-]{1,40}`), `display_name`, `kind` (`generic` / `entra`), `enabled`
  - `issuer`, `entra_tenant_id`, `client_id`, `allow_private_network` (bool, default false)
  - `client_auth_method`, `client_assertion_alg`, `client_secret_encrypted` (text), `client_key_encrypted` and `client_cert_pem` (the active pair), `pending_client_key_encrypted` and `pending_client_cert_pem`, `client_secret_expires_at` (date, nullable)
  - `scopes`, `id_token_alg`, `claim_path`, `mappings` (JSON list), `prompt_select_account`
  - `version` (int), `created`, `updated`

  `version` is bumped in the same transaction as any change to a **security-relevant** field: `enabled`, `issuer`, `entra_tenant_id`, `client_id`, `allow_private_network`, the secret, the active key pair, `client_auth_method`, `client_assertion_alg`, `scopes`, `id_token_alg`, `claim_path` or `mappings`. `slug` is security-relevant too, because it is part of the redirect URI: renaming it bumps `version`. Edits to `display_name`, `prompt_select_account`, `client_secret_expires_at` or the pending pair leave `version` alone.

  **Every provider mutation writes only the columns it means to change.** The CRUD serializer's `update`, the certificate actions and any other writer issue one `OIDCProvider.objects.filter(pk=…).update(…)` whose keyword arguments are exactly the validated fields whose values differ from the row, plus `version=F("version") + 1` when one of them is security-relevant. No provider write calls `instance.save()` without `update_fields`. A full-row save would write back every column as the request first loaded it, and § 5.5's floor depends on that not happening: a credential PATCH that loaded P while it was disabled must not re-save `enabled=False` over an enable that committed in between, because that write takes no lock. The `F()` expression keeps the version increment atomic under concurrent edits. It is the same hazard, and the same remedy, as § 5.8's `update_fields` rule for users. The version keys the discovery and JWKS caches (§ 3.5), the transaction check (§ 3.3 step 4) and D17's refresh re-evaluation (§ 5.4). The lockout guard does not read it (§ 5.5).

  `mappings` is validated as a list of `{value: non-empty str ≤ 256, user_level ∈ {0, 1, 10}}`, at most 50 entries, with no duplicate values.
- **`auth_settings`**, a new `CoreSettings` group (the ninth): `{"public_base_url": "", "password_login_enabled": true}`. A data migration seeds it, so PATCH works on a fresh instance. Contrast `epg_settings`, which has no seeding migration (CLAUDE.md § State).
- **Every security decision reads `auth_settings` fresh from Postgres**, through `CoreSettings._load_group_value` (`core/models.py:385-393`), never through the Redis group cache in `_get_group` (`:397-435`). That covers the login gate, the refresh gate, the admin-login gate, the `me` password rule and the guard. The cache's version check and fill are not one atomic step, and its invalidation runs in `post_save` (`core/signals.py:11-15`) rather than `on_commit`, so a racing reader can repopulate a stale value for up to `_GROUP_CACHE_TTL_SECONDS` (300 s, `core/models.py:242`). These reads happen on login, refresh and settings writes only, a handful per user per 30 minutes, so the cache buys nothing here. `CoreSettings.get_auth_settings()` is defined as this fresh read.
- **`CoreSettingsViewSet` refuses `auth_settings` in every direction**, with 400 `{"code": "use_auth_settings_endpoint"}`. The check runs at the top of `update`, `create` and `destroy`, **before** the serializer validates. Otherwise a rename into the unique key (`core/models.py:291-294`) would answer with the serializer's uniqueness error instead, and the refusal could be removed without any test noticing. Refused requests:
  - `update` and `partial_update` when the stored key **or** the proposed `key` is `auth_settings`, which covers renaming into or out of it
  - `create` with that key
  - `destroy` of that row

  The viewset inherits `ModelViewSet.destroy` (`core/api_views.py:107-114`), and `CoreSettingsSerializer` exposes `key` as writable (`core/serializers.py:44-47`, `fields = "__all__"`). A deleted group falls back to its defaults (`core/models.py:390-391`), which would re-enable password login outside the guard. Reads through the generic endpoint stay allowed, since neither field is secret.
- **Django admin is a second writer, and gets the same refusal from S1.** `core/admin.py:31-41` registers `CoreSettingsAdmin` with no restriction, and `/admin/` is routed at `dispatcharr/urls.py:102-104`. nginx does not shield `/admin/core/coresettings/` (§ 1: a three-segment path escapes `docker/nginx.conf:642-644`), so this matters in production as well as dev. These controls are therefore enforced in Django and are **independent of nginx**. `CoreSettingsAdmin` gains:
  - `has_change_permission(request, obj)` and `has_delete_permission(request, obj)` that return `False` when `obj.key == "auth_settings"`, making that row view-only
  - a `ModelForm` whose `clean_key` refuses `auth_settings`, which covers both adding it and renaming another row into it
  - `delete_queryset` that refuses, with a message, any bulk delete whose queryset contains it

  The change view's `readonly_fields` include `key` for that row, so it cannot be renamed out either. Operators are pointed to the Single sign-on settings page.
- **`public_base_url`.** It must be an absolute URL with no path beyond `/`, no query, no fragment and no userinfo. It is stored without a trailing slash. **It must be `https`**, with two exceptions:
  - the host is a loopback literal (`localhost`, `127.0.0.0/8`, `::1`), the dev and e2e case
  - the env var `MINO_OIDC_ALLOW_HTTP=1` is set (§ 3.5)

  Any other `http` value is refused with 400 `{"code": "public_base_url_insecure"}`. Over plain HTTP to a non-local host, the binding cookie would lose `Secure` and `exchange` would return both JWTs in cleartext. PKCE protects the IdP leg, not this one. **The URL is never derived from the request.** `ALLOWED_HOSTS=["*"]` (`settings.py:107`) makes `request.get_host()` attacker-controlled.

### 5.2 The client credential (D11, D23, D26)

A provider authenticates to its IdP with a client secret or with a key pair (§ 3.4a).

**The client secret.**

- Stored as Fernet ciphertext. The key is `HKDF-SHA256(SECRET_KEY, salt=None, info=b"mino-oidc-client-secret")`. `cryptography` is already locked.
- The API serializer field is `write_only`. Responses carry `client_secret_set: bool` instead. A PATCH without the field keeps the stored value. An empty string is refused, not taken to mean "clear".
- Why encrypt when `xc_password` is plaintext: a provider secret can mint sessions for the whole tenant app. A DB dump or a published Postgres port (CLAUDE.md § Known defects: `5436:5432`) should not hand it over. This does not fix `xc_password`, which is out of scope.

**The key pair and certificate (ruling B4).**

- **Generated in the app, never uploaded.** `POST providers-admin/<id>/certificate/` generates an RSA 2048 key and a self-signed X.509 certificate with `cryptography` (`rsa.generate_private_key`, `x509.CertificateBuilder`): subject `CN=mino-oidc-<slug>`, SHA-256, valid from now for 730 days. The private key is serialized as PKCS#8 PEM and stored as Fernet ciphertext under its own HKDF `info`, `b"mino-oidc-client-key"`. The certificate is public and stored as PEM.
- **Why generated rather than uploaded.** An uploaded key has already existed in a browser, on an admin's disk and probably in a download folder. A key generated here exists in one place, and no API returns it: there is no serializer field for it, readable or writable. What the admin carries to the IdP is the certificate, which is public. Microsoft's guidance prefers a CA-issued certificate but says "if using a trusted CA isn't possible, self-signed certificates are still preferred over passwords" (security-best-practices-for-app-registration, § Credentials). A tenant whose application-management policy requires a trusted issuer cannot use this, and uses a secret instead; uploading a CA-issued pair is not built.
- **Two slots, so rotation cannot lock anyone out.** Generation always fills the **pending** slot and never touches the active pair. The admin downloads the pending certificate (`GET …/certificate/?slot=pending`), uploads it to the IdP beside the old one (Entra: **Certificates & secrets** > **Certificates** > **Upload certificate**, certificate-credentials § Register your certificate), then calls `POST …/certificate/activate/` with the body `{"thumbprint_sha256": <the pending certificate they uploaded>}`. Activation moves pending to active, sets `client_auth_method` to `private_key_jwt` and bumps `version`. The stored secret, if any, is kept, so switching back is one PATCH of `client_auth_method`.
- **Activation names the certificate it expects.** Two administrators can interleave: A generates and downloads certificate A; B generates again, which replaces the pending slot with certificate B; A uploads A and activates. A bodyless activation would then promote B, which the IdP has never seen, and break client authentication. So activation runs in a transaction that takes `select_for_update()` on the provider row, compares the body's `thumbprint_sha256` with the pending certificate's (`hmac.compare_digest` on the hex strings), and promotes only on a match. A missing or different thumbprint, or an empty pending slot, answers 409 `{"code": "pending_certificate_changed"}` and changes nothing. Generation takes the same row lock, so the compare and the promote cannot straddle a regeneration. The UI sends the thumbprint of the certificate it displayed and offered for download.
- Responses carry `client_certificate: {thumbprint_sha256, not_after}` for each filled slot, and nothing about the key.

**A provider can be enabled only with a credential for its method**: a stored secret for the two secret methods, an active key pair for `private_key_jwt`. A provider may be created disabled with neither, which is how the certificate path starts: create, generate, upload, activate, enable. Enabling without one is refused with 400 `{"code": "credential_missing"}`.

**Unreadable credentials.** If decryption of the secret or the key fails (`SECRET_KEY` changed, for example a backup restored onto a new instance, § 1), the provider reports `credential_unreadable` in the admin list and `test` action. Its logins fail closed with `token_exchange_failed`, and the admin re-enters the secret or generates a new certificate.

**Expiry (D26).** Both kinds of credential expire at the IdP, and an expired one stops every sign-in through the provider (§ 4.3). Entra shows a secret's expiry when it is created, and names the failure `AADSTS7000222` (§ 5.9).

- **Each credential has its own expiry, and the one reported is the one in use.** A provider can hold a secret and a certificate at once (above), so a single shared date would report the certificate's `notAfter` for a secret after a switch back.
  - The certificate's expiry is not stored separately: it is the `notAfter` of `client_cert_pem`, read from the certificate.
  - The secret's expiry is `client_secret_expires_at`, an optional date the admin enters from what the IdP showed; the form asks for it beside the secret field. **Saving a new `client_secret` without a date in the same request resets it to null**, so a new secret never inherits the old one's date.
- `providers-admin/` list and detail carry `credential_expiry: {expires_at, state, days_left}`, computed for the credential that `client_auth_method` selects: the active certificate for `private_key_jwt`, the secret otherwise. `state` is `unknown` (no date), `ok`, `expiring` (30 days or fewer left) or `expired`.
- `GET settings/`, for an admin, carries `credential_warnings`: one `{slug, state, days_left}` per **enabled** provider whose state is `expiring` or `expired`. The SPA reads it once after an admin's sign-in and shows a notification, and the Single sign-on panel shows a banner (§ 5.7). `password_login --status` prints the same (§ 5.6).
- Nothing here disables a provider or blocks a login on the date alone. The date is the admin's note of what the IdP will do, and it can be wrong.
- It is never part of the public `providers/` response.

### 5.3 What "password login disabled" disables

When `password_login_enabled` is false and the break-glass is not active:

| Surface | Behaviour |
|---|---|
| `POST /api/accounts/token/` and `POST /api/accounts/auth/login/` | 403 `{"code": "password_login_disabled"}`, plus a `login_failed` event with reason `password_login_disabled` |
| `POST /api/accounts/token/refresh/` | refused (401 `token_not_valid`) unless the refresh token carries `auth_method == "oidc"` and its `oidc_provider` is an enabled provider (D13). A stale **password** pair in a browser is why the SPA runs the SSO handoff before refreshing (§ 5.7). |
| Django admin site | `POST /admin/login/` → 403, added inside the existing wrapper at `apps/accounts/admin.py:30-35`. **Existing admin sessions are cut off too**: `admin.site.has_permission` is wrapped to return `False` while password login is disabled, unless break-glass is active. The admin site is reached only by password login and a Django session, and a session made before the switch would otherwise outlive it. Three-segment admin paths escape nginx's `/admin` redirect (§ 1), so this check lives in Django and does not rely on nginx. |
| `PATCH /api/accounts/users/me/` with `password` | refused for every user. When password login is on, refused only for users without a usable password (§ 5.4). |
| `POST /api/accounts/initialize-superuser/` | not affected by the toggle: bootstrap only, closed once any admin exists and, from S1, while any provider exists (§ 4.4) |
| API keys (`X-API-Key`, `Authorization: ApiKey`) | unchanged, keep working |
| XC, M3U, EPG, HDHomeRun and stream credentials | unchanged |
| Existing access tokens | valid until expiry, at most 30 minutes |
| Existing Django **session** cookies used as a stream principal (`apps/proxy/authorize.py:345-363`, `_session_user`) | **refused** (D19): while password login is off and break-glass is not active, `_session_user` returns `None`. Every Django session comes from the admin site's password login (the OIDC flow never creates one, D3), so a session that outlives the switch would otherwise keep authorizing streams for Django's default two weeks (`SESSION_COOKIE_AGE` is unset). See § 5.4a. |
| `manage.py changepassword` / `createsuperuser` | unchanged (CLI). They are the second half of the recovery procedure (§ 5.6). |
| Login page | the password form is hidden, and SSO buttons are shown |

### 5.4 Refresh and password rules that hold regardless of the toggle

- A refresh token with `auth_method == "oidc"` is refused when its provider is disabled or deleted.
- **D17, refresh re-evaluation.** For a refresh token with `auth_method == "oidc"`, `TokenRefreshView` first reads the provider row by `oidc_provider`, a primary-key read it already needs for the rule above.
  - **If `provider.version == oidc_provider_version`**, nothing else is read, and refresh proceeds as today. This is the common case, and it costs one indexed read.
  - **Otherwise** it reads the identity by `oidc_identity`, refusing if the identity is missing or belongs to another user.
  - **Claim path changed** (`identity.mapping_claim_path != provider.claim_path`): refuse with 401 `token_not_valid`, which forces a fresh login. The stored values were read from a different claim, so yesterday's `roles=["Admin"]` must not be reinterpreted as a `groups` assertion.
  - **Same path**: recompute the level by applying the provider's **current** mappings to `identity.mapping_claim_values`.
  - **No match**: refuse with 401 `token_not_valid`. The stored level is not changed.
  - **A match at or above the user's stored level**: nothing is written, and refresh proceeds. Refresh never promotes.
  - **A match below the user's stored level**: everything above was read without a lock, so it is only the reason to enter the locked block, and **nothing read before the lock decides the write**. Inside `transaction.atomic()`, following § 4.4's floor protocol:
    1. `admin_floor_lock()`. A level below the stored one is always below Admin, so this branch always takes it.
    2. Reload the user with `select_for_update`.
    3. **Re-read the provider row and the whole identity row with plain, non-locking queries**, and repeat every check above on them: the provider exists and is enabled; the identity exists and belongs to this user; `identity.mapping_claim_path == provider.claim_path`; the current mappings applied to `identity.mapping_claim_values` match. A failed check refuses with 401 `token_not_valid` and writes nothing. An identity row lock is **never** taken here: the user row is already held, and identity-after-user is the order § 4.4's table forbids. The plain read is sound because the only writer of those identity columns, the callback, writes them while holding this user's row lock: it either committed before step 2, and is visible, or is waiting behind step 2. An admin's unlink deletes the row without that lock; the read then either finds no identity and refuses, or finds the row as it was a moment before its deletion, which is the answer an earlier refresh would have given.
    4. Decide on the recomputed level and the reloaded user:
       - **at or above the reloaded user's level** (a sign-in in between promoted the mapping's answer, or the user was lowered meanwhile): nothing is written, and refresh proceeds. In particular a recompute that now yields Admin is "no demotion", never a `last_admin` refusal.
       - **lower, and the reloaded user is an active admin with no other active admin** (D21): refuse with 401 `token_not_valid`, write a `login_failed` event with reason `last_admin`, and leave the level alone.
       - **lower otherwise**: one conditional update that touches only `user_level`, `User.objects.filter(pk=user.pk, user_level__gt=new_level).update(user_level=new_level)`.
    5. Refresh.

    The update lowers or does nothing, so no interleaving can raise a level through refresh.

  The refresh token's claims are not rewritten. `ROTATE_REFRESH_TOKENS` is false, so every later refresh repeats the check, which stays cheap.

  **A stale `oidc_level`, stated plainly.** The token's `oidc_level` records the sign-in and is never updated. After a mapping edit that demotes a user, their next refresh lowers `user_level`, and `IsAdmin` then refuses them everywhere, the guard included. Until that refresh, for at most the 30-minute access-token tail, they are still an Admin with `oidc_level` 10 and could pass the § 5.5 guard. The mapping edit that causes this is itself made by an admin, the window is the same one in which that user can still do anything else an Admin can, and break-glass recovers the outcome. Ruling B1 accepts this in exchange for dropping the version proof.

  Why this is sound without the IdP: it re-applies a changed local mapping to what the IdP asserted at the last login. It cannot see a role the IdP has since withdrawn; that still waits for the next login, or for deactivation (§ 4.3).

  **Addendum (2026-11-12, added by PR #661; the text above is unchanged).** Step 1's `admin_floor_lock()` waits at most 5 s (§ 4.4's addendum). When it is not granted, refresh answers **503 `{"code": "admin_floor_busy"}`** with `Retry-After: 1`, writes nothing and leaves the refresh token usable. The web client retries such a refresh after `Retry-After` (1 s when absent or unreadable, at most 10 s), three attempts in all, and abandons the retry if the stored session changed while it waited; any other refusal signs out as before.

### 5.4a Sessions on the streaming surfaces (D19)

`_session_user` (`apps/proxy/authorize.py:345-363`) gains one check. Once `get_user(http_request)` has returned an authenticated user, read `auth_settings` fresh (§ 5.1). If password login is disabled and `settings.PASSWORD_LOGIN_FORCE` is false, return `None`.

The check sits **after** `get_user`, so a request with no session cookie, and a session with no logged-in user, run no extra query. The tune-path query ledger's **runtime** half (`apps/proxy/tests/test_tune_path_query_ledger.py`'s `LEDGER` and its five drive tests) runs the authorize hop without a session, and stays green **unchanged**. That is evidence the anonymous path did not grow. Its **static** half, `BoundaryModulesOrmSitesTests`, is updated in S4 with the one authorised change listed there. `apps/proxy/authorize.py` is a Gate 2 module (`scripts/coverage_live_path.coveragerc:41`), and the Python floor allows no rise. So the new statements must be covered by the new tests, and the PR runs `scripts/coverage_live_path_isolated.sh` before pushing.
- `PATCH users/me/` refuses `password` for a user whose `has_usable_password()` is false. This lands in **S2**, the same PR that first creates such users, so there is never a release in which an SSO-only user can give themselves a password. An SSO-only user cannot give themselves a password path that bypasses the IdP. An admin can still set a password for that user through `PATCH users/<id>/`, a deliberate local decision.

### 5.5 The lockout guard (D12, ruling B1)

The guard answers one question: is the admin who is switching password login off someone who demonstrably gets in, as an Admin, without a password? It does not try to prove that the path will keep working. Break-glass (§ 5.6) covers that.

**The rule.** `PATCH settings/` to `password_login_enabled: false` is accepted only when the acting request's validated access token carries all of:

- `auth_method == "oidc"`: the session came from an SSO sign-in
- an `oidc_provider` naming a provider that exists and is `enabled` **now**, in the stored state
- `oidc_level == 10`: that provider's mapping made this user Admin **at that sign-in**. Without it, a user who signed in while mapped to Standard and was then promoted locally would pass `IsAdmin` on their stored level. Their next SSO login would demote them, and with password login off no Admin path would remain.

`IsAdmin` gates the endpoint as well. An API-key caller and a password session have no such claims, so neither can switch password login off. Otherwise the write is refused with 409 `{"code": "lockout_guard", "reasons": [...]}`, where each reason is one of `not_sso_session`, `provider_not_enabled` and `not_admin_at_sign_in`.

**The floor.** While the stored `password_login_enabled` is false, a provider write that would leave **no enabled provider** is refused with 409 `{"code": "lockout_guard", "reasons": ["last_enabled_provider"]}`. That is: disabling the only enabled provider, or deleting it. The floor reads the stored value, not the break-glass override, so an instance cannot be emptied of providers while the environment variable happens to be set.

**Everything else is allowed while password login is off**, with no proof and by any admin credential:

- Editing a provider, including its credential, mappings, slug and client auth method. **A single-provider instance rotates its secret or certificate without touching the password toggle.** This is the case the ruling was made for.
- Disabling or deleting a provider while another stays enabled.
- Changing `public_base_url`. It changes every redirect URI, so the settings form warns that each IdP registration must be updated first.

Any of these can break SSO if done wrongly. The remedy is break-glass, and the settings panel says so beside the toggle.

**What ruling B1 removed.** The provider-version proof and the redirect-URI-hash proof, with the `oidc_redirect` claim; the evaluation of a "proposed state"; the rule that a provider could be edited while password login was off only with a proof from a *different* provider; the outright refusal of `public_base_url` changes while off; and the requirement that the proof provider's secret decrypt. The row locks on every provider row went with them.

**Serialization.** The rule and the floor each read two things, the password toggle and the set of enabled providers, and two concurrent writes can each be valid alone and wrong together:

- two requests each disabling one of the last two enabled providers while password login is off
- one request switching password login off while another disables the provider it relies on

One lock closes both: `select_for_update()` on the `auth_settings` `CoreSettings` row, inside `transaction.atomic()`. It is taken by exactly the writes that can change either input in the dangerous direction:

- **every** `auth_settings` mutation (`PATCH settings/` and the `password_login` command)
- a provider update whose validated data sets `enabled` to false, and every provider delete

- from S1, for § 3.6's redirect-URI length only: a provider create, and a provider update whose validated data changes `slug` or `kind`

After taking the lock, the write **reloads** `auth_settings` and counts enabled providers, then decides, then writes. Nothing read before the lock is used to decide. Any other provider write (a credential, mapping or display edit, or enabling) takes no lock, and § 5.1's column-restricted writes are what stop it from changing `enabled` or `slug` by accident.

**Tests (S4)**, all in `apps.accounts.tests.test_password_login_toggle.LockoutGuardTests`:

- `test_sso_admin_can_switch_password_login_off`: an admin who signed in through P, mapped to Admin, gets 200.
- `test_password_session_admin_refused`: an admin holding a password-issued pair gets 409 with `not_sso_session`.
- `test_api_key_admin_refused`: the same through `X-API-Key`.
- `test_standard_at_sign_in_promoted_later_refused`: P maps the user to Standard, and they sign in. An admin promotes them locally, and they refresh. With that token they get 409 with `not_admin_at_sign_in`.
- `test_oidc_level_survives_refresh`.
- `test_proof_provider_since_disabled_refused`: the admin signed in through P; P is then disabled while password login is on and Q stays enabled. With the still-valid access token they get 409 with `provider_not_enabled`.
- `test_single_provider_credential_rotation_while_off`: password login is off and P is the only provider. `PATCH providers-admin/<P>/ {client_secret}` answers 200, P's version rises, and password login is still off.
- `test_public_base_url_change_while_off_allowed`: 200.
- `test_disable_last_enabled_provider_while_off_refused` and `test_delete_last_enabled_provider_while_off_refused`: 409 with `last_enabled_provider`, and the provider is unchanged.
- `test_disable_one_of_two_providers_while_off_allowed`: 200.
- `test_disable_last_provider_while_on_allowed`: 200.
- `test_concurrent_disables_of_last_two_providers_one_wins`. Password login is off, with two enabled providers. A `TransactionTestCase` runs two threads, each disabling a different provider. The interleaving is forced: the test wraps the floor-evaluation function so each thread waits on a `threading.Barrier(2, timeout=2)` **after** reading and **before** writing, and the wrapper swallows `BrokenBarrierError`.
  - With the lock, the second thread blocks in `select_for_update()` before it reaches the barrier. The first thread's wait times out, it commits, and the second then counts one enabled provider and gets 409.
  - Without the lock, both threads pass the barrier and both commit.
- `test_switch_off_racing_disable_of_only_provider_serialized`. Password login is on, and Q is the only enabled provider. Thread A sends `PATCH settings/ {password_login_enabled: false}` with a valid token from Q. Thread B disables Q, which the floor allows while password login is on. Both use the same barrier wrapper around the decide step. Exactly one may commit:
  - if A commits first, B reloads, sees password login off and Q the last enabled provider, and gets 409
  - if B commits first, A reloads, finds Q disabled, and gets 409

  The test asserts `not (password_login_enabled is False and enabled provider count == 0)`, and its message names that state.

### 5.6 Break-glass (R3, D14)

- **`MINO_PASSWORD_LOGIN_FORCE=1`** (exactly `1`; any other value is ignored with one WARNING at boot) makes password login enabled regardless of the DB. It is read once at settings import into `settings.PASSWORD_LOGIN_FORCE`. Precedence: **env on ⇒ enabled; else the DB value.** While it is on:
  - `providers/` reports `password_login_forced: true`, and the login page and the SSO settings panel show a banner.
  - Every password login writes `login_success` with `break_glass: true`.
  - D13's refresh refusal is off.

  Setting it means editing the deployment's environment and restarting, which is not reachable from the web.
- **`manage.py password_login --enable | --disable | --status`** writes `auth_settings.password_login_enabled` through `CoreSettings._update_group`, inside the same locking transaction as § 5.5. Every gate reads the row fresh (§ 5.1), so the change is live at the next request with no restart.
  - `--disable` requires at least one enabled provider, the floor of § 5.5. It cannot apply the § 5.5 rule, because the CLI has no SSO session, and `--force` overrides the check.
  - `--status` prints the DB value, the env override, each enabled provider with its credential expiry state (§ 5.2), and **the number of active admins who have a usable password**.
  - `--enable` prints that number too. When it is zero it adds, on its own line, that no admin can sign in with a password yet and names the two commands below.
  - A management command has no URL, and nothing in the web tier invokes it.
- Neither can be set by the UI, the REST API or a `CoreSettings` write. A test asserts that the generic settings endpoint and `PATCH settings/` cannot change `settings.PASSWORD_LOGIN_FORCE`.

**Re-enabling password login is not enough on an SSO-only instance.** Every JIT user has `set_unusable_password()` (§ 4.2 step 5). If every admin was provisioned by SSO, turning password login back on gives nobody a password to type. The likeliest trigger is ordinary: the provider's client secret or certificate expired at the IdP (§ 4.3), so SSO fails for everyone with `client_auth_failed` while password login is off.

**How the commands are run.** `docker exec <container> python manage.py …` does not work in this image, and the first redesign's commands were wrong. `settings.py:41` reads `SECRET_KEY` only from the `DJANGO_SECRET_KEY` environment variable. PID 1 exports it from `/data/jwt` (`docker/entrypoint.sh:138`), and a `docker exec` process does not inherit PID 1's exports. The entrypoint writes the variables a later shell needs to `/etc/profile.d/dispatcharr.sh` and `/etc/environment` (`:272-315`), which a **login** shell loads. So every documented command is

```text
docker exec [-it] <container> su - dispatch -c 'cd /app && python manage.py <command>'
```

the same shape the e2e fixture builds (`e2e/fixtures/instance.ts:388-392`), and the shape the entrypoint itself uses for `migrate` (`docker/entrypoint.sh:432`). `su - dispatch` also makes the command run as the application user, not root. `dispatch` is the default of `POSTGRES_USER` (`docker/entrypoint.sh:12`), and the page says to substitute it where a deployment sets that variable.

**The CLI must see the two new switches.** The login shell gets only the variables the entrypoint lists. `MINO_OIDC_ALLOW_HTTP` (S1) and `MINO_PASSWORD_LOGIN_FORCE` (S4) are added to its optional-variable loop (`docker/entrypoint.sh:290-292`), which propagates a variable only when it is set. Without that, `password_login --status` run through `su -` would report the override as off while the web tier had it on. `tests/test_entrypoint_env_propagation.py` parses that loop and asserts both names are in it.

**How the documented commands are validated.**

- A `guards` test, `e2e/tests/guards/sso-recovery-doc.spec.ts` (S4; no container, no browser), reads `docs/sso-recovery.md`. Every line of a fenced `bash` block that starts `docker exec` must match `docker exec [-it ]<container> su - dispatch -c '<inner>'` with `<inner>` starting `cd /app && python manage.py `. For the token-only commands (`password_login --enable`, `password_login --status`, `createsuperuser`), `<inner>` must equal what the fixture builds for that argv. The one-line builder moves out of `manage()` into a pure module, `e2e/fixtures/manage-command.ts`, which `instance.ts` imports, so the guard test imports no container capability. The page and the fixture therefore cannot drift apart, and a `python manage.py` line with no `su -` fails by name.
- S5's break-glass spec then runs `password_login --enable` and `password_login --status` through `instance.manage()`, which is that same line, in its scoped AIO container. `scripts/e2e_up.sh:369-376` starts that container with no `-e DJANGO_SECRET_KEY`, so the key reaches the command only through the login shell: the case an operator is in.
- `changepassword` and `createsuperuser` prompt on a terminal, and the deactivation one-liner contains quotes that `instance.manage()` refuses (`instance.ts:379-386`). CI pins their wrapper through the guard test and does not run them. The S4 PR's test plan runs each of the three once by hand in an AIO container started without `DJANGO_SECRET_KEY` and pastes the output.

**The recovery procedure** is `docs/sso-recovery.md`, a new operator page (S4), with paste-ready commands and the output to expect from each:

1. Turn password login back on. Either way works; the first needs no restart.

   ```bash
   docker exec <container> su - dispatch -c 'cd /app && python manage.py password_login --enable'
   ```

   or set `MINO_PASSWORD_LOGIN_FORCE=1` in the container's environment and restart it.
2. Read the line `--enable` printed. If it reports at least one active admin with a usable password, sign in as that admin and skip to step 4. `password_login --status`, run the same way, prints it again.
3. Otherwise give an admin a password. Either:

   ```bash
   docker exec -it <container> su - dispatch -c 'cd /app && python manage.py changepassword <admin-username>'
   ```

   which sets a password on an existing SSO admin (Django's command works on a user whose password is unusable), or

   ```bash
   docker exec -it <container> su - dispatch -c 'cd /app && python manage.py createsuperuser'
   ```

   which creates a new local Admin (`user_level` 10, § 1). This second form is also the recovery when no admin exists at all and the bootstrap is closed by § 4.4.
4. Sign in with the password. Repair the provider: for an expired credential, create a new secret at the IdP and save it with its expiry date, or generate, upload and activate a new certificate (§ 5.2). Run the provider's **Test**.
5. Sign out, sign in through SSO, and switch password login off again from that SSO session (§ 5.5). Remove `MINO_PASSWORD_LOGIN_FORCE` if it was set.
6. A recovery account created in step 3 keeps its password. Delete it from the Users page, or keep it deliberately as a local fallback.

The page also carries § 4.3's deactivation one-liner. The `LoginForm` "Forgot password" text, and the login page's copy for `client_auth_failed`, point to it.

### 5.7 Frontend

- **`frontend/src/api.js`**: `getAuthConfig()` (`GET providers/`), `exchangeSsoCode(code)`, `startSsoLink(slug, next)` (`POST <slug>/link/start/`, returns `authorize_url`), and admin CRUD for providers, auth settings and identities. All HTTP stays in `api.js`. **The OIDC browser endpoints use origin-relative URLs.** `getAuthConfig`, `exchangeSsoCode`, `startSsoLink` and the login button's navigation all use plain `/api/accounts/oidc/…`, never the `host` prefix. In dev, `host` is `http://<hostname>:5656` (`api.js:20-23`), a different origin from vite's `:9191`. With that prefix, the default `credentials: 'same-origin'` would neither send the binding cookie to `exchange/` nor store the one that `link/start` sets. Vite already proxies `/api/` to `:5656` (`frontend/devProxy.js:39-43`). In dev, `public_base_url` is the vite origin (`http://localhost:9191`), so the callback and the cookie live on one origin. **`getAuthConfig` and `exchangeSsoCode` also pass `auth: false` to `request()`.** By default `request()` first calls `API.getAuthToken()` (`api.js:51-56`, `:92-94`). That refreshes an expired token (`store/auth.jsx:168-174`), and a refused refresh hard-navigates to `/login` (`api.js:211-216`). A stale password pair would therefore abort the very exchange meant to replace it. `fetch`'s default `credentials: 'same-origin'` still sends the binding cookie, which is all the exchange needs. The SPA never reads or names that cookie: it is `HttpOnly`, and its per-transaction name is the server's business.
- **`frontend/src/store/auth.jsx`**: `loginWithTokens({access, refresh})`, factored out of `login()` (`:177-197`) so the password and SSO paths store tokens identically. It **replaces** any stored pair and resets `isInitialized`/`isInitializing` to false, so the next `initData` reloads `user` (`initData` skips an initialized session, `:98-102`). Also `authConfig` state, and `completeSsoHandoff()` (below).
- **`pages/Login.jsx`**: after the superuser check, fetch `authConfig`. Render one button per provider, plus `LoginForm` only when `password_login_enabled`. The SSO button sets `window.location.href = /api/accounts/oidc/<slug>/start/?next=<current intended path>`, a top-level navigation, never fetch or XHR. Show the `?sso_error=` code as fixed copy.
- **The handoff runs before authentication bootstrap, not as a route.** On mount, `App.jsx`'s auth effect (`:83-104`) refreshes the stored token or logs out. The route table (`:150-182`) sends an authenticated user away from any unknown path, and only unauthenticated users have `/login`. A `/login/sso` route alone would therefore be bypassed in the authenticated link case. It would also lose to a stale password refresh token: `api.js:204-216` hard-navigates to `/login` on a refused refresh, which is exactly what D13 produces after password login is switched off. So `checkAuth` in `App.jsx` gains a first step:

  > If `location.pathname === '/login/sso'`, `await completeSsoHandoff()` **before** `initializeAuth()`. That reads the `#code=` value and immediately runs `history.replaceState` to drop the hash, then calls `exchangeSsoCode`, then `loginWithTokens`, and records `next`. On success the stale pair has already been replaced, so the `initializeAuth()`/`initData()` that follow run on the new SSO tokens. `checkAuth` then navigates to `next`, or to `/users` with a "linked" notice when `intent === 'link'`. On failure it clears the stored tokens and navigates to `/login?sso_error=exchange_failed`.

  `/login/sso` is also listed in **both** branches of the route table, rendering a loader, so neither branch redirects away while the handoff runs.
- **Linking** is a `POST` through `startSsoLink`, then `window.location.assign(authorize_url)`. It is never a GET link carrying a secret.
- **Settings**: a new admin-only "Single sign-on" section in `frontend/src/config/settingsNav.js`, covering:
  - `public_base_url`
  - the provider list
  - a provider form with Generic and Entra variants, showing the computed redirect URI read-only with a copy button. The Entra variant links to the setup page (§ 5.9) and says that national-cloud and External ID tenants use the Generic variant (§ 3.6).
  - the credential block: a choice between **Certificate** (recommended) and **Client secret**. Certificate shows the active and pending certificates' thumbprints and expiry, with "Generate certificate", "Download certificate" and "Activate" actions (§ 5.2). "Activate" sends the thumbprint of the pending certificate the form is showing, and a 409 `pending_certificate_changed` reloads the block with fixed copy saying another administrator generated a newer certificate. Client secret shows the write-only field and the expiry date field.
  - on the Generic variant only, the "Identity provider is on a private network" switch (`allow_private_network`, § 3.5)
  - a banner for each enabled provider whose credential is `expiring` or `expired` (§ 5.2)
  - the mapping table, the "Test" button, and the password-login toggle, whose 409 reasons render inline. Beside the toggle, fixed text says that while it is off a wrong provider edit can lock everyone out, and links to the recovery page (§ 5.6).
- **Credential warning at sign-in.** After `initData` loads an Admin, the store calls `getAuthSettings()` once and shows one Mantine notification per entry of `credential_warnings`. A failure of that call is ignored.
- **Users page**: a user's linked identities with Unlink, and a "Link SSO account" action on the current user's own profile.
- `data-testid`s are registered per ADR 0003 for every new surface the e2e project selects.

### 5.8 Activating and deactivating users (D20, PR S0)

- **API.** `UserSerializer` gains `is_active`, writable only through `UserViewSet`'s admin actions (`update`/`partial_update`, `IsAdmin`). `me` keeps dropping it, because it is not in `ALLOWED_FIELDS` (`apps/accounts/api_views.py:292`).
- **Profile writes save only what they change.** Dropping `is_active` from `me`'s input is not enough. `me` serializes the `request.user` it loaded earlier (`apps/accounts/api_views.py:289-309`), and `UserSerializer.update` then calls an unrestricted `instance.save()` (`apps/accounts/serializers.py:154-160`). So a profile PATCH that started before an admin's deactivation would re-save its stale `is_active=True`.
  - `UserSerializer.update` therefore saves with `update_fields` set to exactly the model fields it assigned: the keys of `validated_data` minus `channel_profiles`, plus `password` when one was set. It skips the save when that set is empty.
  - It never writes `is_active`, `user_level` or `last_login` unless they are among those fields.
  - That applies to the admin path too, so a concurrent admin edit of another field cannot undo a deactivation either.
- **`channel_profiles` is written outside the guarded transaction.** At the seed, `UserSerializer.update` saves the user and then calls `instance.channel_profiles.set(…)` (`apps/accounts/serializers.py:130-165`), as two separate autocommit writes. S0's transaction must not swallow the second: it holds the target's row lock, and writing that user's through rows under it is the reverse of the order a user delete takes (§ 4.4's table). So for a PATCH that sets `is_active` to false, `perform_update` pops `channel_profiles` out of `serializer.validated_data` before the transaction, runs the guards and `serializer.save()` (now scalars only) inside it, and after it has committed calls `apply_channel_profiles(instance, profiles)` if the field was sent. That helper is the serializer's existing `instance.channel_profiles.set(…)` line, given a name so both callers and the test share it. The two writes are separate, exactly as at the seed: a failure of the second leaves the deactivation in place. Every other admin update keeps the seed's path unchanged.
- **Guards.** For a PATCH that sets `is_active` to false, these run in `UserViewSet.perform_update` inside `transaction.atomic()`, under § 4.4's floor protocol: `admin_floor_lock()` (the helper S0 introduces: a transaction-scoped advisory lock), then the target **reloaded** with `select_for_update`, then the guards on that row, never on `serializer.instance` as the view loaded it. So two concurrent deactivations cannot each leave the other as "the last admin", and a target promoted after the view loaded it is judged as the Admin it now is. On a runtime SQLite database the PATCH is refused with `requires_postgresql` (§ 4.4). D21's SSO paths take the same lock from S2, so a deactivation and an SSO demotion serialize too. A PATCH setting `is_active: false` answers 400 when:
  - the target is the requesting user (`{"code": "cannot_deactivate_self"}`)
  - the target is the last active admin (`{"code": "last_active_admin"}`)

  Demoting or deleting the last active admin **through the Users API** is not in this ruling's scope and is unchanged. Demotion **by SSO** is refused by D21 (§ 4.4).
- **UI.** `frontend/src/components/forms/User.jsx` gains an admin-only "Active" switch, hidden for the current user. `frontend/src/components/tables/UsersTable.jsx` gains an "Active" badge column. HTTP goes through `api.js` as usual.
- **The form sends `is_active` only when the admin changed it.** At the seed, `User.jsx`'s `onSubmit` (`:75-86`) sends every form value through `formValuesToPayload` (`frontend/src/utils/forms/UserUtils.js:66-109`), which spreads them all into the payload. With `is_active` in the form, an admin editing a user's name in a form opened before another admin deactivated that user would send a stale `is_active: true`. `update_fields` would save it, because it was assigned, and the guards only refuse deactivation.
  - `formValuesToPayload(values, existingUser)` keeps `is_active` in the payload **only when `values.is_active !== existingUser.is_active`**, comparing against the user object loaded from the server when the form opened. Otherwise it deletes the key. On create (`existingUser` absent) it keeps the key.
  - This is a pure comparison inside `UserUtils.js`. It deliberately does not use Mantine's `form.isDirty`. `User.jsx` initialises the form from create defaults (`:56-59`) and loads the user with `form.setValues` (`:95-107`) without resetting the dirty baseline, so dirty state is not measured against the loaded user.
  - A form opened while the user was active, then submitted after another admin deactivated them, still holds `is_active: true` equal to its loaded `true`, so it sends no `is_active`.
  - Both files are in S0's scope.
- **Break-glass.** The CLI one-liner in § 4.3 stays, for when no admin can sign in.

### 5.9 Operator documentation

Two pages under `docs/`, written for an operator and linked from the UI. `docs/sso-recovery.md` is § 5.6's procedure (S4). `docs/sso-entra-setup.md` is the Entra app registration (ruling B5, S3). Its content, each step naming the admin-center blade:

1. **Register the application.** Supported account types: "Accounts in this organizational directory only", that is single tenant (D10). Note the **Directory (tenant) ID** and **Application (client) ID** for the provider form.
2. **Add the redirect URI under the Web platform, not Single-page application.** Paste the redirect URI the provider form shows. This app is "a traditional web application where most of the application logic is performed on the server", whose platform is **Web** (reply-url, § Web application redirect URI configuration); the code is redeemed server-side with a client credential, which an SPA registration does not allow. The URI must be `https` (reply-url: `http` "is supported *only* for *localhost* URIs") and at most 256 characters.
3. **Require assignment.** Enterprise apps > the application > Properties > **Assignment required?** = **Yes** (https://learn.microsoft.com/en-us/entra/identity-platform/howto-restrict-your-app-to-a-set-of-users, § Update the app to require user assignment). Without it, any user in the tenant can complete sign-in at Entra and is refused only by this app's mapping. That page also says an app requiring assignment needs tenant-wide admin consent granted, and that Global Administrators are not subject to the requirement.
4. **Create app roles and assign them.** App registrations > App roles: create, for example, `Mino.Admin` and `Mino.User` with allowed member type Users/Groups. Then Enterprise apps > Users and groups: assign users or groups to a role (howto-add-app-roles-in-apps). Entra then emits those values in the `roles` claim, which is the preset's mapping claim. Map each value to a level in the provider form.
5. **Only if mapping on groups instead:** Token configuration > Add groups claim > **Groups assigned to the application**. That option "includes only groups assigned to the application" and "is recommended for large organizations due to the group number limit in token" (optional-claims, § Configure groups optional claims). The page explains the overage refusal (§ 3.6) and why `roles` is preferred.
6. **Add the credential.**
   - **Certificate (preferred).** In the provider form choose Certificate, generate, and download the `.pem`. Upload it under Certificates & secrets > Certificates > Upload certificate, then press Activate in the provider form. Microsoft: "For best security, we recommend using certificate credentials" (v2-oauth2-auth-code-flow, § Redeem a code for an access token).
   - **Client secret.** Certificates & secrets > New client secret. Copy the **Value** (not the Secret ID) into the provider form, and enter the expiry date Entra shows into the expiry field. A secret stops working on that date, and every sign-in then fails until it is replaced.
7. **Test, then sign in.** Press Test in the provider form, sign in through the button in a private window, and only then consider switching password login off.
8. **Sovereign clouds and External ID** use the generic provider form (§ 3.6).

The blade and field names above are from Microsoft's pages where one is cited; "Accounts in this organizational directory only" and the secret's **Value** / **Secret ID** columns are from the admin center itself and are checked against it when the page is written.

**What each sign-in error means.** Two tables. The first maps this app's `sso_error` codes (§ 3.3) to a cause and a fix, including `client_auth_failed` (the credential is wrong or expired: see the recovery page), `no_mapping` (the user has no assigned role that the provider maps), `groups_overage`, `last_admin` (§ 4.4), `id_token_invalid` and `provider_mismatch`. The second lists the Entra codes an operator sees on Microsoft's own error page or in the sign-in log, with the meaning Microsoft documents (https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes):

| Entra code | Microsoft's description | What to do here |
|---|---|---|
| `AADSTS50011` | "InvalidReplyTo - The reply address is missing, misconfigured, or doesn't match reply addresses configured for the app" | Make the registered redirect URI identical to the one the provider form shows. Check `public_base_url` and the slug. |
| `AADSTS900971` | "No reply address provided" | Add the redirect URI under the Web platform. |
| `AADSTS50105` | "EntitlementGrantsNotFound - The signed in user isn't assigned to a role for the signed in app" | Assign the user, or a group they are in, to an app role (step 4). |
| `AADSTS700016` | "UnauthorizedClient_DoesNotMatchRequest - The application wasn't found in the directory/tenant" | Check the client id and the tenant id. |
| `AADSTS90002` | "InvalidTenantName - The tenant name wasn't found in the data store" | Check the tenant id. A national-cloud tenant needs the generic form. |
| `AADSTS50194` | the application "isn't configured as a multitenant application" and a `/common` endpoint was used | Not reachable from the preset, which always uses the tenant endpoint. It indicates a hand-built generic provider pointed at `/common`. |
| `AADSTS7000215` | "Invalid client secret is provided" | The secret's Value was mistyped, or its Secret ID was pasted instead. |
| `AADSTS7000222` | "InvalidClientSecretExpiredKeysProvided - The provided client secret keys are expired" | Create a new secret and save it with its expiry date. If nobody can sign in, follow the recovery page. |
| `AADSTS700027` | "Client assertion failed signature validation" | The active certificate is not the one uploaded to Entra, or it has expired. Upload the active certificate, or generate, upload and activate a new one. |
| `AADSTS7000218` | "The request body must contain the following parameter: 'client_assertion' or 'client_secret'" | The provider has no usable credential (for example `credential_unreadable` after a restore, § 5.2). |
| `AADSTS7000112` | "UnauthorizedClientApplicationDisabled - The application is disabled" | Re-enable the enterprise application in Entra. |

The token-endpoint codes (`AADSTS7000215`, `AADSTS7000222`, `AADSTS700027`, `AADSTS7000218`) never reach this app's logs or events, because `error_description` is never recorded (§ 3.3). The operator sees `client_auth_failed` here and finds the code in Entra's sign-in log.

## 6. Out of scope (D15)

- Xtream, M3U, EPG, HDHomeRun and stream credentials, and `xc_password` storage.
- Phase 4c paired-device auth (`docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md`, the 4c brief). Nothing here pre-empts its design. The Mino app keeps its own auth path.
- SAML, SCIM and any provisioning push; deprovisioning happens at the next login (§ 4.3).
- **RP-initiated logout and front- and back-channel logout: out.** The SPA's logout clears its tokens and records the event, as now. The IdP session survives, so the next SSO click may sign in silently. `prompt_select_account` is the per-provider mitigation.
- Microsoft Graph calls (groups overage), multi-tenant Entra, guest-account policy beyond "a guest is a new identity in this tenant", and the UserInfo endpoint.
- An Entra preset for the national clouds or External ID; they use the generic form (§ 3.6).
- `response_mode=form_post` (D24, § 3.2), mutual-TLS client authentication, and uploading a CA-issued certificate and key (§ 5.2).
- Guarding the last admin against demotion or deletion through the Users API, and closing the bootstrap whenever any user exists (§ 4.4, Q9).
- Token revocation and blacklisting (simplejwt `token_blacklist` stays uninstalled).
- Fixing `ALLOWED_HOSTS`, CORS or CSRF wildcards. This spec only avoids depending on them.
- Making `login_success` and `logout` subscribable in Connect.

## 7. Events and logging

- **Success**: `log_system_event('login_success', user=<username>, client_ip=…, user_agent=…, method='oidc', provider=<slug>)`.
- **Failure**: `login_failed`, with `user` set to `'sso'` (or the resolved username when one exists) and `reason` taken from the fixed vocabulary of § 3.3 plus `provider=<slug>`. A refresh refused by D21 writes the same event with reason `last_admin`.
- **Link and unlink**: `login_success`, with `method='oidc_link'` or `'oidc_unlink'` and `admin=<username>`.
- **Configuration changes (D18)**: every provider create, update and delete, and every `auth_settings` change (through `PATCH settings/` or the `password_login` command), writes `log_system_event('auth_config_changed', user=<acting username, or 'cli'>, action=<provider_created|provider_updated|provider_deleted|auth_settings_updated>, provider=<slug or None>, fields=<sorted list of changed field names>)`.
  - It is registered in `SystemEvent.EVENT_TYPES` (`core/models.py:816-839`) and in `SUPPORTED_EVENTS` (`apps/connect/models.py:3-22`), so Connect integrations can subscribe. Both are `choices`, so S1 ships a migration for `core` and one for `connect`.
  - `fields` holds **names only**. `client_secret` can appear as a name, but no value of any field is ever in the payload, `public_base_url` included. Generating a certificate records the field name `pending_client_certificate`, and activating one records `client_certificate` and `client_auth_method`.
  - The event is written from `transaction.on_commit`, so a write refused by the guard, or rolled back, leaves no event.

No event payload and no **application** log line (Django's `logging`, any logger) ever carries `code`, `state`, `nonce`, `code_verifier`, the binding, an ID token, an access token, a refresh token, the client secret, the client private key, a client assertion, a raw claim set or `sub`. Failure reasons name the check, never the value. Application code never logs `error_description` or `error_uri` either. The uWSGI, nginx and `runserver` (`django.server`) request logs are outside this guarantee for the callback's **whole raw query**, meaning `code`, `state`, `error*`, `session_state` and `iss`. § 3.3 states that residual, why it is accepted, and why `code`/`state` are reasoned separately.

## 8. Security review

| # | Threat | Defence | Test (PR) |
|---|---|---|---|
| T1 | Open redirect via `next` | § 3.2 step 2 allowlist (relative path only) | `//evil`, `/\evil`, `https://evil`, `%2F%2Fevil` and a control character all become `/` (S2) |
| T2 | Open redirect or host poisoning via the `Host` header | `public_base_url` only (D6) | a request with `Host: evil.example` produces `redirect_uri` and a final Location on the configured base (S2) |
| T3 | Login CSRF (the victim is logged in as the attacker) | tx binding cookie (§ 3.3 step 3) and handoff bound to the same binding | callback with valid state but no or a wrong cookie → `binding_invalid`; exchange with another browser's code → 400 (S2) |
| T3b | Binding cookie planted or overwritten from a sibling subdomain or a plain-HTTP origin; one login tab clobbering another (ruling B6) | `__Host-` prefix with `Secure; Path=/` and no `Domain`; per-transaction name; stale-cookie cap (§ 3.2 step 5) | `apps.accounts.tests.test_oidc_flow.BindingCookieTests`: <br>• `test_https_cookie_is_host_prefixed`: with an https `public_base_url`, the `Set-Cookie` name starts `__Host-mino_oidc_tx_`, and it has `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/` and no `Domain` <br>• `test_http_fallback_cookie_is_unprefixed`: with `http://localhost:9191`, the name starts `mino_oidc_tx_` and there is no `Secure` <br>• `test_two_transactions_do_not_clobber`: one client calls `start` twice, then completes the **first** transaction's callback and exchange, then the second's; both succeed <br>• `test_cookie_for_other_transaction_refused`: the callback for transaction A, sent with only transaction B's cookie → `binding_invalid` <br>• `test_refusal_and_exchange_delete_the_cookie`: a `binding_invalid` callback and a completed exchange each answer `Max-Age=0` for that transaction's cookie name <br>• `test_fifth_stale_cookie_expires_all`: a `start` carrying five prefixed cookies expires all five and sets one (S2) |
| T3a | Account-linking CSRF (the victim's IdP identity is attached to the attacker's account) | link only via authenticated `POST link/start`, binding cookie set in the caller's browser, no link secret in any URL, `GET start` can never link (§ 3.1, § 3.2) | two clients: the attacker calls `link/start` and hands its `authorize_url` to the victim client, whose IdP identity maps to Admin; the victim's callback → `binding_invalid`, no `OIDCIdentity` is created and the attacker's `user_level` is unchanged; `GET start?intent=link` writes `intent=login` (S2) |
| T4 | State replay | `GETDEL`, single use | a second callback with the same state → `state_invalid` (S2) |
| T5 | Authorization code injection or interception | PKCE S256, verifier server-side only | the token request body carries `code_verifier` matching the stored challenge, and the fake IdP refuses a wrong verifier (S2 unit, S5 e2e) |
| T6 | ID-token substitution or replay | `nonce` bound to the transaction, `aud`/`azp`, `exp`/`iat` with 60 s leeway | per-claim negative tests: wrong nonce, wrong aud, multi-aud without azp, a mismatching `azp` with a scalar `aud` and with a one-element list `aud`, a non-string `azp`, expired, iat in the future (S2) |
| T7 | Signature bypass | `algorithms=[configured]`, `none`/`HS*` refused, `kid` must resolve, algorithm from configuration and never from the JWK, `oct` keys refused (§ 3.4) | `alg=none` token, HS256 token signed with the client secret, unknown kid after one refetch, and **a token with a JWKS-listed `kid` but signed by a different RSA key**. The fake OP's JWKS entries carry no `alg`, as Entra's do, so every passing test proves validation works without it; `test_jwks_oct_key_refused`: a JWKS whose matching `kid` is a `kty: oct` key, with an HS256 token signed by it → `id_token_invalid` (S2) |
| T8 | Mix-up across providers | per-provider redirect URI, tx bound to provider and version, RFC 9207 `iss` when advertised | callback for provider B with a transaction from A → `provider_mismatch`; advertised `iss` param absent or wrong → `issuer_mismatch`; a fake OP that, like Entra, does not advertise it and sends none → the login succeeds (S2) |
| T9 | Entra multi-tenant issuer pitfall | single tenant only (D10), exact `iss`, `tid` check | the preset refuses `common`/`organizations` (S1); at runtime, three correctly-signed tokens are refused (S2): correct `iss` with another `tid`; another tenant's `iss` with the configured `tid`; a missing `tid` |
| T10 | Account takeover by email | identity keyed on (provider, iss, sub), no email matching | a JIT login whose email equals an existing admin's email creates a **new** Standard user and does not touch the admin (S2) |
| T11 | Privilege retained after an IdP change | level recomputed on each login, refusal on no match | login 1 maps Admin, login 2 maps Standard → level 1; login 3 no match → refused and level unchanged (S2) |
| T12 | Self-service password bypassing the IdP | § 5.4 | SSO-only user `PATCH me {password}` → 400 and `has_usable_password()` still false (S2); any user while password login is off → 400 (S4) |
| T12a | Django admin as a second writer, and a session that outlives password-off | § 5.1 `CoreSettingsAdmin` restrictions (S1); § 5.3 `has_permission` wrap (S4) | `core.tests.test_auth_settings_guard.AuthSettingsDjangoAdminTests`, with a superuser `force_login`'d **before** each change: the change form POST, delete view, bulk-delete action and add/rename-into for `auth_settings` all leave the row unchanged (S1). The same pre-established session gets 302-to-login or 403 on `/admin/core/coresettings/` once password login is off, and 200 again under `PASSWORD_LOGIN_FORCE` (S4) |
| T13 | Lockout | D12 guard and its floor (§ 5.5), break-glass and the recovery procedure (§ 5.6) | `LockoutGuardTests` (§ 5.5): each of the four reasons individually yields 409; a single provider's credential rotates while password login is off; the two races are serialized. Env force re-enables; command `--enable` re-enables live. `apps.accounts.tests.test_password_login_toggle.RecoveryTests`: <br>• `test_enable_reports_no_admin_has_a_password`: with one SSO-provisioned admin (unusable password), `password_login --enable` prints a count of 0 and names `changepassword` and `createsuperuser` <br>• `test_changepassword_then_password_login_recovers`: after `--enable`, that admin's `POST token/` → 401; after `set_password` (what `changepassword` does), → 200 <br>• `test_status_lists_expiring_credential` (S4) |
| T14 | Guard bypass through the generic settings endpoint | refusal of `auth_settings` in `CoreSettingsViewSet`, every direction, before serializer validation (§ 5.1) | `core.tests.test_auth_settings_guard.AuthSettingsGenericEndpointTests`, each case asserting the exact body `{"code": "use_auth_settings_endpoint"}`, not just the status. On `/api/core/settings/`: `PATCH`, `PUT` and `DELETE` of the `auth_settings` row; `POST` with that key; `PATCH` renaming the `auth_settings` row to another key; `PATCH` renaming another row to `auth_settings`. All → 400, and the row is unchanged (S1) |
| T15 | Client secret or private key disclosure | write-only secret field; no field at all for the key; both encrypted at rest; not in `CoreSettings` | GET list/detail never contains the secret or ciphertext; a Standard user's `GET /api/core/settings/` lacks it; DB column ≠ plaintext. `apps.accounts.tests.test_oidc_providers.ProviderCertificateTests`: <br>• `test_private_key_never_in_any_response`: after generate and activate, the bodies of generate, activate, certificate download, list and detail contain no `PRIVATE KEY` marker, and `client_key_encrypted` does not contain one either <br>• `test_download_is_the_public_certificate`: the PEM parses as an X.509 certificate whose public key matches the stored key's <br>• `test_generate_fills_pending_and_leaves_active`: a second generate leaves the active thumbprint unchanged <br>• `test_activate_promotes_the_named_certificate`: the active thumbprint is the former pending one, `client_auth_method` is `private_key_jwt`, `credential_expiry.expires_at` equals its `notAfter`, and `version` rose <br>• `test_stale_activation_refused`: generate (certificate A), generate again (certificate B), then activate naming A → 409 `pending_certificate_changed`; the active pair, `client_auth_method` and `version` are unchanged and B is still pending. Activating with no body → the same 409 (S1) |
| T15a | A provider write re-saving a stale column (the floor's premise, § 5.1) | column-restricted `update()` for every provider mutation | `apps.accounts.tests.test_oidc_providers.ProviderPartialWriteTests`: <br>• `test_stale_patch_does_not_resave_enabled`: a `TransactionTestCase`. Thread A sends `PATCH {display_name}` for P, which is disabled, and is held on a `threading.Event` in a wrapper around the serializer's `update`, after the view has loaded the instance. The test thread enables P through the API and commits, then sets the event. Afterwards P is enabled and carries the new `display_name` <br>• `test_stale_certificate_action_does_not_resave_enabled`: the same with certificate generation as the held request <br>• `test_concurrent_security_edits_both_bump_version`: two PATCHes of different security-relevant fields, the second held the same way, leave `version` two higher (S1). `LockoutGuardTests.test_unrelated_patch_cannot_empty_the_enabled_set`: password login off, P disabled and Q enabled. A credential PATCH for P is held as above; P is enabled; Q is disabled (allowed: P is enabled); the held PATCH is released. An enabled provider remains (S4) |
| T16 | Credential logging | `CREDENTIAL_RE` extended with `client_secret`, `client_assertion`, `client_key`, `id_token`, `access_token`, `refresh_token`, `code_verifier` and `\bnonce\b`; `SENSITIVE_QUERY_KEYS` extended (§ 3.3); exceptions logged by class only; `error_description` never logged; request-log residual documented (§ 3.3) | `tests/test_credential_logging_guard.py` gains a case per name; `tests/test_redaction.py` gains `redact_url` cases for each new query key; with distinctive sentinel values for code, state, secret, ID token, tokens and `sub` (with `preferred_username` and `email` both absent from the ID token), capture by a **recording handler on each configured logger**, not the root alone. `apps`, `core.utils` and `apps.proxy` set `propagate: False` with handlers of their own (`dispatcharr/settings.py:584-604`), and `settings_test` inherits that (`dispatcharr/settings_test.py:22`). So a test helper context manager does the following for each of `apps`, `core`, `core.utils`, `django` and the root:
  - attaches a `logging.Handler` subclass that appends every formatted record to a list
  - sets that logger's level to DEBUG
  - on exit removes the handler and restores the original level, in `finally`

  It is not `assertLogs`, which fails when a logger emits nothing, as `core.utils` may on a successful flow. An empty capture is a pass. Break-check S2(h) is what proves the OIDC module's own logger is actually observed. The test runs over a happy callback, a token endpoint 500, a token endpoint connection error, and an IdP `error=access_denied&error_description=<sentinel>` finds no sentinel. Test: `apps.accounts.tests.test_oidc_logging.OidcLoggingTests.test_no_sentinel_in_any_logger`. Break-check S2(h) proves the capture sees the OIDC module's own logger (S2) |
| T17 | Secrets in SystemEvent and Connect payloads | § 7 field whitelist | after a success and each failure, every `SystemEvent.details` JSON is searched for the code, state, ID token, tokens, secret and `sub`, and none is present. One case has both `preferred_username` and `email` absent, and asserts that the created username matches `^sso-[0-9a-f]{8}$` (S2) |
| T18 | Ambient session principal on streaming surfaces | D3: no `login()` | after a completed callback, the response sets no `sessionid` cookie and no session row holds `_auth_user_id` (S2) |
| T19 | Token leakage via URL, and handoff replay | fragment handoff; `GETDEL` single use with a 60 s TTL; `no-store` (§ 3.3a) | the callback Location has `#code=`, never `?code=`; the exchange response shape is exactly `{access, refresh, next, intent}` with `Cache-Control: no-store` and the cookie deleted; a sequential second exchange → 400; **two concurrent exchanges** of one code (two threads, real Redis, barrier) → exactly one 200; an exchange after the TTL → 400 (S2) |
| T20 | Discovery or JWKS abuse (slow, huge, redirect) | timeouts, 1 MiB cap, no redirects, https-only unless env | an oversized body and a 302 from jwks_uri → refused with a clear admin `test` result (S1) |
| T20a | Server-side request forgery through the issuer or a discovered endpoint | `core/http_security.py` on discovery, JWKS and the token request, at every use; `allow_private_network` per provider, refused on the Entra preset; loopback only under the env switch (§ 3.5) | `apps.accounts.tests.test_oidc_discovery.OutboundPolicyTests`, with `socket.getaddrinfo` patched so no test resolves a real name: <br>• `test_private_issuer_refused_by_default`: an issuer resolving to `10.0.0.5` → `test` reports `discovery_not_allowed` and no request is sent <br>• `test_private_issuer_allowed_with_flag` <br>• `test_metadata_address_refused_even_with_flag`: `169.254.169.254` with `allow_private_network` true → refused <br>• `test_discovered_jwks_uri_checked`: a public issuer whose document names a `jwks_uri` on `10.0.0.5` → `jwks_uri_not_allowed` <br>• `test_entra_preset_refuses_private_flag`: 400 (S1) <br>• `test_discovered_token_endpoint_checked_at_callback`: a `token_endpoint` on a private address, flag off → the callback answers `token_exchange_failed` and the fake OP's token handler was never called <br>• `test_loopback_needs_env_switch`: without `OIDC_ALLOW_HTTP`, the in-process OP on `127.0.0.1` is refused (S2) |
| T20b | Discovery URL built wrongly for an issuer ending in `/` | strip one terminating `/` before appending the well-known path; stored issuer and `iss` compared exactly (§ 3.5) | `apps.accounts.tests.test_oidc_discovery.DiscoveryUrlTests`: <br>• `test_trailing_slash_issuer_fetches_single_slash_path`: issuer `http://127.0.0.1:<port>/realms/x/` → the fake OP records exactly one request, for `/realms/x/.well-known/openid-configuration`, and none containing `//.well-known` <br>• `test_trailing_slash_issuer_compared_exactly`: that document's `issuer` without the slash → refused; with it → accepted (S1) <br>• `test_id_token_iss_must_match_stored_issuer_exactly`: an ID token whose `iss` lacks the stored trailing slash → `id_token_invalid` (S2) |
| T21 | Brute force or DoS of the flow | `oidc` throttle 20/min per trusted-proxy IP; caches | the 21st start in a minute → 429 (S2) |
| T22 | Deactivated user regaining access via SSO | `is_active` check, SSO never reactivates | inactive linked user → `inactive`; link to a `link_user_id` deactivated between `link/start` and the callback → `inactive` (S2) |
| T23 | Credentials over cleartext | `public_base_url` must be https except loopback or `MINO_OIDC_ALLOW_HTTP` (§ 5.1) | `http://mino.example` → 400 `public_base_url_insecure`; `http://localhost:9191` → accepted; `http://mino.example` with `override_settings` for the env → accepted (S1) |
| T24 | Partial writes on refusal or a lost race | mapping decided before any write; one transaction; savepoints told apart by constraint (§ 4.2) | an unmapped first login leaves the `User` and `OIDCIdentity` counts unchanged; two concurrent first logins for one `sub` (`TransactionTestCase`, two threads, barrier) yield one user and one identity; **forced losing branch**: before the attempt, a second connection commits the winner's `OIDCIdentity` for the same `(provider, iss, sub)`, with the identity insert patched to wait on a barrier until that commit lands. The attempt ends logged in as the winner's user, and the `User` count rises by exactly one (the winner's); a username collision with an unrelated user yields `name-2`, not a refusal (S2) |
| T25 | Username edge cases | per-candidate truncation; `sso-<hex>` fallback (§ 4.2) | a 150-character `preferred_username` colliding with an existing user yields a 150-character `…-2`, not a DB length error; a `preferred_username` of only filtered-out characters yields `sso-<hex>` (S2) |
| T26 | Concurrent linking of two local users to one identity | link-branch savepoint plus constraint-specific recovery (§ 4.2 step 4) | `ProvisioningAtomicityTests.test_concurrent_links_one_wins`: two `TransactionTestCase` threads, local users A and B, both linking the same `(provider, iss, sub)`, with the identity insert patched to wait on a `Barrier(2)`. One gets the handoff and the other `link_conflict`. The loser's `user_level` and identity count are unchanged <br>• `test_link_conflict_with_own_identity_does_not_deadlock`, event-controlled, no sleep. All three callbacks are Admin-mapped, so none takes the advisory lock and none can queue behind another on it. Link callback L, for user U and a not-yet-existing identity I, is held on `Event` E1 after its identity lookup found nothing and before its attempt savepoint. The test thread links I to **the same U** through a second link callback and commits. Admin-mapped login callback C for I is started and held on `Event` E2 after it has locked I and before it locks U. E1 is set; a wrapper sets `Event` E3 when L enters the conflict handler, that is, after its insert failed. The test waits for E3 (5 s bound), then sets E2. Both threads are joined with a 10 s timeout and a `finally` sets every event. Neither raised; C returned a handoff; L returned a handoff with `intent=link` (the winner belongs to U, so it is not `link_conflict`); one identity exists <br>• `test_link_racing_user_delete_answers_409`, event-controlled, PostgreSQL only. Each thread records its `pg_backend_pid()`. Admin-mapped link callback L for user U is held on `Event` E1 after its identity insert and before its transaction commits. Admin B sends `DELETE users/<U>/` on another thread. The test polls (5 s bound, no fixed sleep) until B's backend is waiting with L's pid in `pg_blocking_pids(<B's pid>)`, and fails explicitly if that state is not reached; then it sets E1. Both threads are joined with a 10 s timeout and a `finally` sets E1. L returned a handoff; B answered 409 `user_changed_during_delete`; U and its new identity both exist (S2) |
| T27 | Privilege retained after a local mapping change (D17) | refresh re-evaluation from stored claim values | `apps.accounts.tests.test_oidc_flow.RefreshReevaluationTests`: <br>• `test_mapping_change_demotes_on_refresh`: mapped Admin → mapping edited to Standard → refresh 200 and `user_level == 1` <br>• `test_mapping_removed_refuses_refresh`: no match → 401, level unchanged <br>• `test_refresh_never_promotes` <br>• `test_claim_path_change_refuses_refresh`: the claim path is edited from `roles` to `groups` → refresh 401 and level unchanged, even though the stored values would match a `groups` mapping <br>• `test_concurrent_refreshes_never_raise_level`: two refreshes of the same Admin user, through two linked providers whose mappings now give 0 and 1, with a second active admin present. Two sync points make the order deterministic: <br>• a `Barrier(2)` after the pre-lock compute step, so both have read 10 <br>• an `Event`: the level-0 refresh runs its locked block, commits and sets it, and the level-1 refresh waits on it in a wrapper around `admin_floor_lock`, before its own locked block <br>The final level is 0, because the level-1 refresh reloads the user, finds its recomputed 1 is not below the stored 0, and writes nothing <br>• `test_unchanged_version_reads_only_provider`: `assertNumQueries` on a refresh with an unchanged version is the password-refresh baseline plus exactly one provider read <br>• three changed-between-reads tests, each holding the refresh on an `Event` in a wrapper around `admin_floor_lock`, after the pre-lock recompute said Standard and before the helper runs, with a second active admin present: <br>&nbsp;&nbsp;◦ `test_claim_path_changed_between_reads`, two cases. (a) The test thread edits the provider's claim path from `roles` to `groups` and nothing else: released, the refresh answers 401 and the user's level is unchanged, because the re-read identity still says `roles`. (b) The test thread makes the same edit and then drives a callback that stores `mapping_claim_path="groups"` with values the `groups` mapping maps to Admin: released, the refresh answers 200 and the level is 10, because provider and identity were re-read together and agree <br>&nbsp;&nbsp;◦ `test_recompute_to_admin_between_reads_is_no_demotion`: the user is the **only** active admin here. The test thread drives an Admin-mapped callback for the same identity under the unchanged path, which stores Admin-mapped values. Released, the refresh answers **200**, the level is 10, and no `last_admin` event is written <br>&nbsp;&nbsp;◦ `test_identity_unlinked_between_reads_refuses`: the test thread deletes the identity. Released, the refresh answers 401 and the level is unchanged (S2) |
| T28 | Pre-switch Django session authorizing streams (D19) | `_session_user` refuses while password login is off | `apps.proxy.tests.test_authorize_session_principal.SessionPrincipalPasswordOffTests`, with a client `force_login`'d before the switch, against `authorize_stream` on the catch-up surface, which requires a principal: <br>• password on → principal resolved <br>• off → `AuthorizeDenied(401)` <br>• off with `PASSWORD_LOGIN_FORCE` → resolved <br>The runtime query ledger passes unchanged; the static ORM-site entry for `authorize.py` changes as S4 lists (S4) |
| T29 | Secrets in audit events (D18) | names-only payload, `on_commit` | `apps.accounts.tests.test_oidc_audit.AuthConfigAuditTests`: <br>• creating and updating a provider with a sentinel secret, and changing `public_base_url` to a sentinel URL, writes `auth_config_changed` rows whose `details` JSON contains neither sentinel, with `fields` listing `client_secret` and `public_base_url` <br>• a guard-refused write (409) leaves no `auth_config_changed` row (S1; S4 for the guard case and the CLI's `user='cli'`) |
| T30 | Deactivation control abuse (D20) | admin-only field, self and last-admin guards under `admin_floor_lock()` with the target row reloaded and locked (§ 4.4; no lock on the admin set), refusal on runtime SQLite | `apps.accounts.tests.test_user_activation.UserActivationTests`: <br>• a Standard user's `PATCH users/<id>/ {is_active: false}` → 403 <br>• `PATCH users/me/ {is_active: false}` leaves the user active <br>• an admin deactivating themselves → 400 `cannot_deactivate_self` <br>• deactivating the last active admin → 400 `last_active_admin` <br>• a deactivated user's access token → 401 and refresh → 401 <br>• reactivation restores both <br>• two concurrent deactivations of the only two admins (barrier, as § 5.5) → exactly one succeeds <br>• `test_patch_without_is_active_preserves_deactivation`: an admin's `PATCH users/<id>/ {first_name}` on a deactivated user leaves it inactive, and its access and refresh are still refused <br>• `test_stale_profile_patch_cannot_reactivate`: the target's `PATCH users/me/ {first_name}` loads `request.user`, then waits on a barrier. An admin deactivates the target, and then the PATCH completes. The target stays inactive, and their access and refresh tokens are still refused <br>• `test_stale_target_cannot_deactivate_last_admin`: a `TransactionTestCase`. Admin X sends `PATCH users/<T>/ {is_active: false}` for T, a Standard user, and is held on a `threading.Event` in a wrapper around `admin_floor_lock`, before the helper runs and after the view has loaded T. The test thread commits two ORM updates standing for a promotion and a demotion that happened meanwhile: T becomes Admin, then X becomes Standard. The event is set. The PATCH answers 400 `last_active_admin`, and T is still active <br>• `test_deactivation_refused_on_runtime_sqlite`: with `override_settings(RUNTIME_SQLITE=True)`, `PATCH {is_active: false}` → 400 `requires_postgresql` and the user is unchanged; `PATCH {is_active: true}` on an inactive user → 200 <br>• `test_mixed_deactivation_and_profile_change_does_not_deadlock_with_delete`: a `TransactionTestCase`, PostgreSQL only, event-controlled. U is a Standard user with one channel-profile membership. Admin A sends `PATCH users/<U>/ {is_active: false, channel_profiles: []}` and is held on `Event` E1 in a wrapper around `apply_channel_profiles`, the one helper through which both `UserSerializer.update` and `perform_update` write the profiles, so the hold lands on that write wherever it runs. Admin B sends `DELETE users/<U>/` on another thread. Each thread records its own connection's `pg_backend_pid()` before it sends its request. The test then polls, with a 5 s bound and no fixed sleep, for one of two states: B's thread has finished, or B's backend is waiting and A's pid is in `pg_blocking_pids(<B's pid>)`. If neither holds within the bound the test **fails**, naming the state it saw, without setting E1 as if it had. Otherwise it sets E1. Both threads are joined with a 10 s timeout and a `finally` sets E1. Neither request ended in PostgreSQL's deadlock error, B answered 204, and U is gone <br>• `tests.test_runtime_sqlite_marker.RuntimeSqliteMarkerTests`, which imports settings in a child interpreter (`subprocess.run([sys.executable, "-c", …])`) so the import is isolated from the running suite's: `dispatcharr.settings` with `DB_ENGINE=sqlite` → `RUNTIME_SQLITE` is `True`, and without it → `False`; `dispatcharr.settings_test` with `DB_ENGINE=sqlite` inherited → `False` both with `TEST_USE_SQLITE=1` (engine `sqlite3`) and with it unset (engine `postgresql`) (S0) |

| T31 | Unauthenticated bootstrap reopened by demoting the last admin (D21) | `last_admin` refusal on login, link and refresh under `admin_floor_lock()`; bootstrap closed while a provider exists (§ 4.4) | `apps.accounts.tests.test_oidc_last_admin.LastAdminTests`: <br>• `test_login_demoting_last_admin_refused`: the only active admin signs in with claims that map to Standard → `sso_error=last_admin`, `user_level` still 10, the identity's stored claim values unchanged, and exactly one active admin remains <br>• `test_login_demoting_admin_allowed_when_another_remains`: with a second active admin → level 1 <br>• `test_inactive_second_admin_does_not_count`: the second admin is deactivated → refused <br>• `test_link_demoting_last_admin_refused`: no `OIDCIdentity` is created <br>• `test_refresh_demoting_last_admin_refused`: mapping edited to Standard, then refresh → 401, level still 10, a `login_failed` event with reason `last_admin` <br>• `test_concurrent_demotions_of_two_admins_one_wins`: two admins, two threads, each signing in with a Standard mapping, barrier after the admin-set read and before the write → exactly one is demoted <br>• `test_demotion_racing_deactivation_one_wins`: admin A is deactivated through the Users API while admin B's SSO login demotes B, same barrier → exactly one succeeds, and one active admin remains <br>• `test_promoting_and_demoting_callbacks_do_not_deadlock`, the bounded interleaving of § 4.4's cycle, with a second active admin present throughout and no sleep. Callback 1, Admin-mapped, for identity I whose user U is Standard, is held on `Event` E1 after it has locked I and before it locks U. The test thread promotes U to Admin through the Users API and commits. Callback 2, Standard-mapped, for the same I, runs through a wrapper around `admin_floor_lock` that sets `Event` E2 when the helper **returns**, that is, after callback 2 holds whatever the helper took and before it asks for I. The test thread waits for E2 (5 s bound), then sets E1. Both threads are joined with a 10 s timeout, and a `finally` sets both events so a failure cannot hang the run. Neither raised, both callbacks returned a handoff, and U's final level is 1 (callback 2 committed last) <br>• `test_refresh_with_stale_user_cannot_demote_last_admin`: A is Admin, U is Standard, and a mapping edit has made U's recomputed level Streamer. U's refresh is held on an `Event` in a wrapper around `admin_floor_lock`, before the helper runs and after the view has loaded U. The test thread promotes U to Admin through the Users API, which leaves U's stored claim values alone so the recompute under the lock is still Streamer, then drives A's Standard-mapped callback, which demotes A (allowed: U is an admin). The event is set. The refresh answers 401 with a `login_failed` reason of `last_admin`; U's level is 10 and exactly one active admin remains (S2) <br>`apps.accounts.tests.test_accounts.InitializeSuperuserTests.test_closed_when_a_provider_exists`: no admin, one `OIDCProvider` row → GET reports `superuser_exists: true` and POST creates no user (S1) |
| T32 | Client secret mangled or mis-encoded at the token endpoint | form-urlencoding of id and secret before Basic; `client_secret_post` for Entra (§ 3.4a) | `apps.accounts.tests.test_oidc_flow.ClientAuthTests`, with the secret `p@ss:w+rd/ %&=é~` and the client id `client:id+1`: <br>• `test_basic_credentials_are_form_urlencoded`: the fake OP base64-decodes the header, splits on the first `:`, form-decodes both halves, and they equal the id and secret; the raw decoded header contains no bare space and exactly one `:` <br>• `test_post_secret_round_trips`: the fake OP's parsed form body has the exact secret, and no `Authorization` header was sent <br>• `test_entra_preset_defaults_to_post_and_refuses_basic` <br>• `test_invalid_client_maps_to_client_auth_failed`: a 401 `{"error": "invalid_client", "error_description": <sentinel>}` → `sso_error=client_auth_failed`, and the sentinel is in no log or event (S2) |
| T33 | Forged, replayable or over-long client assertion (ruling B4) | assertion built per request to Microsoft's documented shape, 5-minute life, fresh `jti` (§ 3.4a) | `apps.accounts.tests.test_oidc_flow.ClientAssertionTests`, where the fake OP verifies the assertion with the downloaded certificate's public key: <br>• `test_assertion_shape`: header `alg` is `PS256`, `typ` is `JWT`, `x5t#S256` equals the base64url SHA-256 of the certificate's DER, and there is no `x5t`; claims `iss == sub == client_id`, `aud ==` the discovered `token_endpoint`, `exp - nbf == 300`, `iat == nbf` <br>• `test_assertion_replaces_secret`: the form body has `client_assertion_type` and `client_assertion` and no `client_secret`, and no `Authorization` header was sent <br>• `test_jti_is_fresh_per_request`: two logins → two different `jti` <br>• `test_signature_verifies_with_active_certificate_only`: after generating a pending pair without activating it, the assertion still verifies against the active certificate and fails against the pending one <br>• `test_generic_provider_may_use_rs256` (S2) |
| T34 | SSO session outliving the ruling's bound (ruling B3) | 12-hour `exp` stamped at mint; refresh enforces the token's own `exp` (§ 3.3 step 9) | `apps.accounts.tests.test_oidc_flow.SessionLifetimeTests`: <br>• `test_sso_refresh_token_lives_12_hours`: the exchanged refresh token's `exp - iat` is 43200, and a password login's is still 86400 <br>• `test_refresh_refused_after_12_hours`: with `rest_framework_simplejwt.tokens.aware_utcnow` patched to sign-in + 11 h 59 min, `POST token/refresh/` → 200; patched to + 12 h 1 s → 401 <br>• `test_refresh_rotation_is_off`: `settings.SIMPLE_JWT["ROTATE_REFRESH_TOKENS"]` is false, with a message naming § 3.3 step 9 (S2) |
| T35 | Credential expiring unnoticed, or the wrong credential's date reported (D26) | per-credential expiry, reported for the method in use; admin warnings (§ 5.2) | `apps.accounts.tests.test_oidc_providers.CredentialExpiryTests`: states `unknown`, `ok`, `expiring` at exactly 30 days, `expired` on the day after; `credential_warnings` lists an enabled expiring provider and omits a disabled one; the public `providers/` body has no expiry field <br>• `test_switch_back_to_secret_reports_the_secrets_own_expiry`: a provider with a secret that expired yesterday activates a certificate (state `ok`, the certificate's `notAfter`), then PATCHes `client_auth_method` back to `client_secret_post` → state `expired` with the secret's date <br>• `test_secret_with_no_date_is_unknown_after_switch_back`: the same with no secret date → `unknown`, not the certificate's date <br>• `test_new_secret_without_date_resets_expiry`: `PATCH {client_secret}` alone → `client_secret_expires_at` is null (S1) |
| T36 | Redirect URI longer than Entra accepts | 256-character validation (§ 3.6) | `apps.accounts.tests.test_oidc_providers.EntraPresetTests.test_redirect_uri_over_256_refused`: a slug that takes the URI to 257 characters → 400 `redirect_uri_too_long`, and 256 → accepted; a `public_base_url` change that takes an existing Entra provider past 256 → 400 <br>• `test_slug_edit_racing_base_url_edit_cannot_exceed_256`: a `TransactionTestCase`. An Entra provider's redirect URI is 240 characters. Thread A lengthens the slug by 10 and thread B lengthens `public_base_url` by 10, each held on a `Barrier(2, timeout=2)` between its length validation and its write, `BrokenBarrierError` swallowed. Exactly one answers 200 and the other 400 `redirect_uri_too_long`, and the committed URI is 250 characters (S1) |

Out of the threat model: an admin who is already malicious (they can point a provider at their own IdP and map themselves to Admin, which they already are), and in-process plugins (unsandboxed by design, CLAUDE.md § Events and plugins).

## 9. PR breakdown

Six PRs in order, S0 to S5. Each opens as a draft, gets a pinned review (`fable` from round one: security-adjacent), and lands with `Backend result` / `Frontend result` / `E2E result` green. Test labels: `apps.accounts.tests` (all backend here), `core.tests` (S1's `CoreSettings` refusal and the no-pending-migrations check), and `tests` (S2's credential-logging checker).

### S0: Admin-only user activation control (D20)

**Changes:** § 5.8: the `is_active` serializer field and guards, `settings.RUNTIME_SQLITE` with its refusal (§ 4.4), plus the `User.jsx` switch and `UsersTable.jsx` column. Independent of SSO, so it lands first, and the deactivation lever § 4.3 relies on exists before any SSO user does. The guard's lock is `apps/accounts/admin_floor.py`'s `admin_floor_lock()` (§ 4.4), introduced here with its one caller, so S2's SSO paths take the same mutex.

**Tests:** T30. Vitest:

- `frontend/src/components/forms/__tests__/User.test.jsx`: `active switch hidden for the current user` (rendering only; that file mocks the form and the utils at `:18-49`, so it does not test the payload)
- `frontend/src/utils/forms/__tests__/UserUtils.test.js`, through the real `formValuesToPayload`:
  - `untouched active user omits is_active` (loaded `true`, values `true` → no key)
  - `untouched inactive user omits is_active` (loaded `false`, values `false` → no key)
  - `activating sends is_active true` (loaded `false`, values `true` → `true`)
  - `deactivating sends is_active false` (loaded `true`, values `false` → `false`)
  - `create keeps is_active`
- Backend: T30's `test_patch_without_is_active_preserves_deactivation` and `test_stale_profile_patch_cannot_reactivate`

**Break-checks:**

- (a) Drop the self check. `apps.accounts.tests.test_user_activation.UserActivationTests.test_admin_cannot_deactivate_self` reddens: it expects 400 `cannot_deactivate_self` and gets 200.
- (b) Make `admin_floor_lock()` return without taking the advisory lock. `UserActivationTests.test_concurrent_last_admin_deactivations_one_wins` reddens, deterministically through a barrier wrapper of § 5.5's kind around the guard's count: both 200, and no active admin remains, which the message names.
- (d) Restore the unrestricted `instance.save()` in `UserSerializer.update`. `UserActivationTests.test_stale_profile_patch_cannot_reactivate` reddens: `is_active` is true after the PATCH completes.
- (e) Make `formValuesToPayload` always keep `is_active`, dropping the comparison with the loaded user. `frontend/src/utils/forms/__tests__/UserUtils.test.js` › `untouched active user omits is_active` reddens: it finds `is_active: true` in the payload. That is exactly the stale value that would reactivate a user deactivated in the meantime.
- (f) Run the deactivation guards on `serializer.instance` instead of the target reloaded under the lock. `UserActivationTests.test_stale_target_cannot_deactivate_last_admin` reddens: the PATCH answers 200 and no active admin remains, which the message names.
- (i) Leave `channel_profiles` in `validated_data`, so `serializer.save()` writes the profiles inside the guarded transaction. `UserActivationTests.test_mixed_deactivation_and_profile_change_does_not_deadlock_with_delete` reddens: at E1 request A still holds U's row, B's delete has removed the through row and is waiting for U (the state `pg_stat_activity` shows), A's `.set([])` then waits for that through row, and one of the two ends in PostgreSQL's deadlock error, which the assertion message quotes.
- (h) Delete `RUNTIME_SQLITE = False` from `settings_test.py`. `tests.test_runtime_sqlite_marker.RuntimeSqliteMarkerTests.test_test_settings_reset_the_marker_under_inherited_db_engine` reddens for both test database selections: the child interpreter prints `True`.
- (g) Drop the `RUNTIME_SQLITE` refusal. `UserActivationTests.test_deactivation_refused_on_runtime_sqlite` reddens: it expects 400 `requires_postgresql` and gets 200.
- (c) Add `is_active` to `me`'s `ALLOWED_FIELDS`. `UserActivationTests.test_me_cannot_change_is_active` reddens on `is_active` false.

**PR description draft:**

> Adds an admin-only active/inactive control for users (SSO spec PR S0, ruling Q8): an `is_active`
> field writable only by admins through `/api/accounts/users/<id>/`, guarded so an admin cannot
> deactivate themselves or the last active admin, plus a switch in the user form and a column in
> the Users table. A deactivated user's access and refresh tokens are refused. The CLI one-liner in
> the spec stays as the break-glass path.
> Tests: `apps.accounts.tests`, frontend vitest. Break-checks listed in the spec's S0 section.

### S1: Models, settings group and admin API (no login yet)

**Changes:**

- `OIDCProvider` and `OIDCIdentity` models plus migration.
- A data migration seeding `auth_settings`, plus `AUTH_SETTINGS_KEY` and `CoreSettings.get_auth_settings()` beside the eight group keys at `core/models.py:227-234`.
- The `CoreSettingsViewSet` refusal for that key, and the `CoreSettingsAdmin` restrictions (§ 5.1).
- The `auth_config_changed` audit event (D18, § 7), with the `core` and `connect` choices migrations.
- `apps/accounts/oidc/secrets.py` (HKDF + Fernet, one `info` label per kind of secret).
- `apps/accounts/oidc/certificates.py`: key and certificate generation, the two slots, and the three `certificate/` endpoints (§ 5.2). Building the client assertion is S2's.
- Serializers with the write-only secret, no key field, `credential_expiry`, and mapping validation. Every provider write is a column-restricted `update()` (§ 5.1).
- Entra preset validation: tenant GUID, derived issuer, `client_auth_method` limited to `private_key_jwt` and `client_secret_post`, `allow_private_network` refused, and the 256-character redirect URI (§ 3.6).
- `providers-admin/` CRUD and the `test/` action. Discovery and JWKS fetch live in `apps/accounts/oidc/discovery.py`, with § 3.5's limits, discovery URL rule and outbound check. `settings.OIDC_ALLOW_HTTP` is read from the env here, and `MINO_OIDC_ALLOW_HTTP` joins the entrypoint's optional-variable loop (§ 5.6), with `tests/test_entrypoint_env_propagation.py`.
- `credential_warnings` on `GET settings/` (§ 5.2).
- `initialize_superuser` stays closed while any `OIDCProvider` row exists (§ 4.4). The existing `InitializeSuperuserTests` are unchanged: none of them creates a provider.
- `settings/` GET and PATCH. **In S1, S2 and S3, `password_login_enabled: false` is refused unconditionally** with 409 `{"code": "password_toggle_unavailable"}`. The guard of § 5.5, the enforcement of § 5.3 and the break-glass land together in S4. No mergeable state between them can record "passwords off" while passwords still work. `public_base_url` is writable from S1, with § 5.1's https rule.
- `identities/` list and delete.
- CLAUDE.md § State: "eight groups" becomes "nine", naming `auth_settings`. The `e2e/tests/guards/global-mutation.spec.ts` header lists the ninth group.

**Tests:** model constraints; `issuer`, Entra tenant and `client_id` immutability with identities present, including changing an Entra `client_id` with a linked identity (400); `version` bumped by a mapping edit and not by a `display_name` or `client_secret_expires_at` edit; T29 (S1 half); the unconditional `password_toggle_unavailable` refusal; T23; T12a's S1 half; delete-PROTECT; secret and key round-trip and the unreadable-after-key-change path for each; no secret in any response; T14, T15; Entra refusals (T9 part); mapping validation; T20, T20a (S1 half), T20b (S1 half), T15a (S1 half), T31 (the bootstrap case), T35, T36; `RuntimeSqliteTests` (§ 4.4); the `test` action against an in-process `http.server` thread serving discovery and JWKS (no network). That thread listens on `127.0.0.1`, so the fake-OP test base class sets `override_settings(OIDC_ALLOW_HTTP=True)`, and its JWKS entries carry no `alg` (§ 3.5).

**Break-checks:**

- (a) Add a `SerializerMethodField` named `client_secret` to the provider serializer that returns the decrypted value, `secrets.decrypt(obj.client_secret_encrypted)`. `apps.accounts.tests.test_oidc_providers.ProviderSecretTests.test_secret_never_in_responses` reddens: it asserts the sentinel secret is absent from the list, detail, create and update response bodies, and finds it in each. Merely dropping `write_only` from the input field would not redden it: the model has no `client_secret` attribute (the column is `client_secret_encrypted`), so DRF would have nothing to render.
- (a2) Add `client_secret_encrypted` to the serializer's `fields`. The same test reddens on its second assertion, that no response body contains the stored ciphertext.
- (b) Check only the stored key in the `CoreSettingsViewSet` refusal, not the proposed one. `core.tests.test_auth_settings_guard.AuthSettingsGenericEndpointTests.test_rename_other_row_into_auth_settings_refused` reddens. The status is still 400, from the serializer's uniqueness error on `key`, but the body is that error rather than `{"code": "use_auth_settings_endpoint"}`, and the assertion on the body names the difference.
- (c) Accept `organizations` as a tenant. `apps.accounts.tests.test_oidc_providers.EntraPresetTests.test_multi_tenant_aliases_refused` reddens: it expects 400 with `{"entra_tenant_id": ["must be a tenant GUID"]}` for each of `common`, `organizations` and `consumers`, and gets 201 for `organizations`.
- (d) Drop `client_id` from the immutable-with-identities set. `apps.accounts.tests.test_oidc_providers.ProviderImmutabilityTests.test_client_id_change_refused_with_identities` reddens: it expects 400 and an unchanged `client_id` after a PATCH on an Entra provider with one linked identity, and gets 200.
- (f) Put the new value of each changed field into the audit payload. `apps.accounts.tests.test_oidc_audit.AuthConfigAuditTests.test_audit_payload_names_fields_only` reddens: it finds the secret sentinel in `details`.
- (e) Make `CoreSettingsAdmin.has_change_permission` return `True` for every row. `core.tests.test_auth_settings_guard.AuthSettingsDjangoAdminTests.test_change_form_post_leaves_row_unchanged` reddens: after the change-form POST, the row's `value` differs from its value before.
- (g) Append `/.well-known/openid-configuration` to the issuer without stripping its terminating `/`. `apps.accounts.tests.test_oidc_discovery.DiscoveryUrlTests.test_trailing_slash_issuer_fetches_single_slash_path` reddens: the fake OP recorded a request for `/realms/x//.well-known/openid-configuration`, which the message quotes.
- (g2) Normalise the stored issuer by stripping its trailing `/` before comparing it with the document's `issuer`. `DiscoveryUrlTests.test_trailing_slash_issuer_compared_exactly` reddens: the document whose `issuer` lacks the slash is accepted.
- (h) Fetch the JWKS with a bare `requests.get` instead of `fetch_outbound_http`. `apps.accounts.tests.test_oidc_discovery.OutboundPolicyTests.test_discovered_jwks_uri_checked` reddens: it expects `jwks_uri_not_allowed` and finds that a request to the private address was attempted.
- (h2) Pass `allow_private=True` unconditionally. `OutboundPolicyTests.test_private_issuer_refused_by_default` reddens: it expects `discovery_not_allowed` and gets a fetch attempt.
- (i) Add `client_key_encrypted`'s decrypted PEM to the certificate-generation response. `apps.accounts.tests.test_oidc_providers.ProviderCertificateTests.test_private_key_never_in_any_response` reddens, naming the generate response and the `PRIVATE KEY` marker.
- (i2) Make generation write the active slot. `ProviderCertificateTests.test_generate_fills_pending_and_leaves_active` reddens: the active thumbprint changed.
- (i3) Make activation ignore the body and promote whatever is pending. `ProviderCertificateTests.test_stale_activation_refused` reddens: it expects 409 and an unchanged active thumbprint, and finds certificate B active.
- (l) Save the provider in the serializer's `update` with a bare `instance.save()`. `ProviderPartialWriteTests.test_stale_patch_does_not_resave_enabled` reddens: P is disabled after the held PATCH completes, which the message names as a stale `enabled` written back.
- (m) Report the active certificate's `notAfter` whenever a certificate exists, whatever `client_auth_method` says. `CredentialExpiryTests.test_switch_back_to_secret_reports_the_secrets_own_expiry` reddens: state `ok` where it expects `expired`.
- (n) Take no `auth_settings` lock for a provider update that changes `slug`. `EntraPresetTests.test_slug_edit_racing_base_url_edit_cannot_exceed_256` reddens: each request validated against the other's old value, both pass the barrier, both answer 200, and the committed URI is 260 characters.
- (o) Drop the `RUNTIME_SQLITE` refusal from provider creation. `apps.accounts.tests.test_oidc_providers.RuntimeSqliteTests.test_provider_create_refused_on_runtime_sqlite` reddens: with `override_settings(RUNTIME_SQLITE=True)` it expects 400 `requires_postgresql` and no row, and gets 201.
- (j) Drop the `OIDCProvider` test from `initialize_superuser`. `apps.accounts.tests.test_accounts.InitializeSuperuserTests.test_closed_when_a_provider_exists` reddens: POST created a user.
- (k) Compare the Entra redirect URI's length with `<` 2048 instead of `<=` 256. `EntraPresetTests.test_redirect_uri_over_256_refused` reddens: the 257-character case answers 201.

**Hooks:** `apps/accounts/models.py` and `core/models.py` (`makemigrations --check`); `*.py` (credential logging); `apps/accounts/tests/test_*.py` and `core/tests/test_*.py`.

**PR description draft:**

> Adds the storage and admin API for OIDC single sign-on, the first PR of the SSO spec
> (`docs/superpowers/specs/2026-10-31-sso-oidc-design.md`, PR S1; ADR 0012). New models
> `OIDCProvider` and `OIDCIdentity`, a seeded `auth_settings` settings group that the generic
> `/api/core/settings/` endpoint refuses to write, admin CRUD with a discovery/JWKS `test` action,
> and an Entra preset that accepts only a tenant GUID. A provider authenticates with a client
> secret or with a key pair generated in the app, whose certificate can be downloaded for the
> IdP; both are encrypted at rest and never returned, and a credential expiry date drives an
> admin warning. Discovery and JWKS fetches go through the repository's SSRF check. The
> first-admin bootstrap stays closed once a provider exists. No login flow yet, and password
> login cannot be switched off until PR S4 lands the lockout guard together with its
> enforcement and break-glass.
> Tests: `apps.accounts.tests`, `core.tests`. Break-checks listed in the spec's S1 section.

### S2: The OIDC flow (backend)

**Changes:**

- `apps/accounts/oidc/flow.py` (start, link/start, callback, exchange; § 3.2-3.3a), with the binding cookie of § 3.2 step 5.
- `apps/accounts/oidc/client_auth.py` (§ 3.4a): the three methods, the Basic encoding and the client assertion.
- `apps/accounts/oidc/validate.py` (§ 3.4).
- `apps/accounts/oidc/provisioning.py` (§ 4), with D21's `last_admin` refusal on login and link (§ 4.4).
- `UserViewSet.destroy` answers 409 `user_changed_during_delete` on an `IntegrityError` (§ 4.4, "Dependents of a user row").
- `settings.OIDC_REFRESH_TOKEN_LIFETIME` and the 12-hour `exp` (§ 3.3 step 9).
- The `oidc` throttle scope at `settings.py:343-345`.
- § 5.4's `me` password rule for users without a usable password (T12).
- D17's refresh re-evaluation (§ 5.4) with its `last_admin` refusal, the `oidc_identity` claim, and `mapping_claim_path`/`mapping_claim_values` on the identity.
- The `auth_method`/`oidc_provider`/`oidc_provider_version`/`oidc_level` claims, the `providers/` public endpoint, and § 5.4's first rule (refresh of an OIDC token refused when its provider is disabled or deleted).
- `SENSITIVE_QUERY_KEYS` extension (`dispatcharr/utils.py:63`), `Referrer-Policy`/`no-store` headers, and class-only exception logging (§ 3.3).
- The `CREDENTIAL_RE` extension (`scripts/check_credential_logging.py:111-113`) and its tests.
- § 7 events.

**Tests:** T1-T3b, T4-T8, T9 (runtime part), T10, T11, T12 (S2 half), T16-T19, T20a and T20b (S2 halves), T21, T22, T24-T27, T31 (the SSO paths), T32-T34, all against an in-process fake OP: a `http.server` thread plus RSA and EC keys generated with `cryptography` in `setUpClass`, issuing tokens with PyJWT. Like Entra, that OP publishes JWKS entries with no `alg` and a discovery document with neither `code_challenge_methods_supported` nor `authorization_response_iss_parameter_supported` by default; the RFC 9207 tests switch the latter on. It still **requires** a valid `code_verifier`, so a flow that gated PKCE on discovery would fail every test. The suite also covers:

- the happy path, end to end through the Django test client, including that the exchanged access token authenticates `GET /api/accounts/users/me/` **and** `_drf_user` in `apps/proxy/authorize.py` (the D2 claim that streaming needs nothing new);
- that all five custom claims (`auth_method`, `oidc_provider`, `oidc_provider_version`, `oidc_level`, `oidc_identity`) survive `POST token/refresh/`, and that the token carries no `oidc_redirect`;
- the concurrent JIT path and the username-collision path (T24).

**Break-checks:**

- (a) Delete the binding comparison. `apps.accounts.tests.test_oidc_flow.BindingTests.test_callback_without_binding_cookie_refused` reddens: it expects a 302 to `/login?sso_error=binding_invalid` and receives a 302 to `/login/sso#code=…`.
- (b) Pass `options={"verify_signature": False}` to `jwt.decode`. `apps.accounts.tests.test_oidc_flow.SignatureTests.test_listed_kid_wrong_key_refused` reddens: it expects `sso_error=id_token_invalid` and gets a 302 to `/login/sso`. A wrong-key token is the one that isolates signature verification; `alg` and `kid` are both valid in it.
- (b2) Choose the verification key by the token header's `alg`: for `HS*`, use the decrypted client secret as an HMAC key, and pass `algorithms=[header alg]`. `apps.accounts.tests.test_oidc_flow.SignatureTests.test_hs256_signed_with_client_secret_refused` reddens the same way. This is the key-confusion mechanism that test exists for; appending `HS256` to the list alone would not redden it, because PyJWT will not use an RSA public key as an HMAC secret.
- (b3) Check `azp` only when `aud` has more than one entry. `apps.accounts.tests.test_oidc_flow.AzpTests.test_scalar_aud_mismatched_azp_refused` reddens: it expects `sso_error=id_token_invalid` and gets the handoff redirect.
- (b4) Drop the Entra `tid` comparison. `apps.accounts.tests.test_oidc_flow.EntraRuntimeTests.test_configured_iss_other_tid_refused` reddens the same way.
- (f) Move the JIT user insert **out of the transaction**, before the mapping is evaluated: a bare `User.objects.create(...)` ahead of step 1, outside `transaction.atomic()`. `apps.accounts.tests.test_oidc_provisioning.ProvisioningAtomicityTests.test_unmapped_first_login_writes_nothing` reddens on a `User` count of N+1. Merely reordering statements inside the atomic block would not leave a row after the refusal's rollback, which is why the break moves the insert outside it.
- (f2) Move the user insert (and its username-retry loop) **out of the attempt savepoint**, so it runs directly in the outer transaction, just before the attempt savepoint. Keep the identity-conflict handler where it is, outside the attempt savepoint. Rolling the savepoint back now leaves the loser's user row in place, and the outer transaction commits it. T24's forced-losing-branch test, `ProvisioningAtomicityTests.test_losing_identity_insert_leaves_no_orphan_user`, reddens on its assertion that the `User` count rose by exactly one: it rose by two, and the extra row is the loser's `sso-…` or claim-derived user with no `OIDCIdentity`, which the assertion message names.
- (i4) Under the lock, re-read only `mapping_claim_values` and skip the repeated claim-path comparison. `RefreshReevaluationTests.test_claim_path_changed_between_reads` reddens on case (a): the refresh answers 200 and the user is demoted to Standard, the pre-lock `roles` mapping having been applied without the path being checked again.
- (i5) Under the lock, enter the last-admin test on the pre-lock level instead of the recomputed one. `RefreshReevaluationTests.test_recompute_to_admin_between_reads_is_no_demotion` reddens: it expects 200 and gets 401 with a `last_admin` event.
- (q) Take the link target's `select_for_update` before the attempt savepoint instead of inside it. `ProvisioningAtomicityTests.test_link_conflict_with_own_identity_does_not_deadlock` reddens: L holds U and waits for I while C holds I and waits for U, and one of them ends in PostgreSQL's deadlock error, which the assertion message quotes.
- (r) Remove the `IntegrityError` handler from `UserViewSet.destroy`. `ProvisioningAtomicityTests.test_link_racing_user_delete_answers_409` reddens: the delete raises instead of answering 409 `user_changed_during_delete`.
- (q2) Answer `link_conflict` for every identity conflict in the link branch without comparing owners. The same test reddens: L answers `sso_error=link_conflict` where it expects the handoff.
- (i2) Drop the `mapping_claim_path` comparison and apply the mappings to the stored values. `RefreshReevaluationTests.test_claim_path_change_refuses_refresh` reddens: it expects 401 and gets 200.
- (i3) Skip the reload and write the pre-lock decision unconditionally: `user.user_level = new_level; user.save(update_fields=['user_level'])` on the user object loaded before the lock. `RefreshReevaluationTests.test_concurrent_refreshes_never_raise_level` reddens: the second sync point makes the level-1 refresh run its block after the level-0 write has committed, its stale object still says 10, and the save leaves the level at 1, which the message names as a promotion. Without that ordering the break could pass by scheduling luck, if the 1 were written first and then overwritten by the 0.
- (i) Skip the recompute when the version differs, and just refresh. `apps.accounts.tests.test_oidc_flow.RefreshReevaluationTests.test_mapping_change_demotes_on_refresh` reddens: it expects `user_level == 1` and finds 10.
- (h) Add `logger.debug("token response %s", token_json)` to the token-exchange step in `apps/accounts/oidc/flow.py`, whose logger is `apps.accounts.oidc.flow`. `OidcLoggingTests.test_no_sentinel_in_any_logger` reddens, naming the ID-token sentinel and the logger `apps.accounts.oidc.flow`. A root-only capture would have stayed green, because `apps` does not propagate.
- (g) In the callback, skip the binding comparison (step 3) when the transaction's `intent` is `link`. `apps.accounts.tests.test_oidc_flow.LinkCsrfTests.test_forwarded_link_authorize_url_does_not_link` reddens, asserting `OIDCIdentity.objects.filter(user=attacker).exists()` is false and finding it true. That test uses two Django test clients: the attacker client calls `POST link/start` and receives `authorize_url` and its own binding cookie; the victim client, holding a different binding cookie from its own `GET start`, drives the fake OP and the callback with the attacker's `state`. The path is fully exercised. Break-check (a), which removes the comparison for every intent, is caught by T3 instead.
- (c) Look up an existing user by email before JIT. `apps.accounts.tests.test_oidc_provisioning.EmailTakeoverTests.test_matching_email_creates_new_user` reddens: it asserts that the resolved user id differs from the existing admin's, and names the admin's id when it is equal.
- (d) Call `django.contrib.auth.login(request, user)` in the callback. `apps.accounts.tests.test_oidc_flow.SessionTests.test_callback_sets_no_session` reddens on its assertion that `sessionid` is absent from `response.cookies`.
- (j) Build the binding cookie's name without `tx_id`, one fixed name for every transaction. `BindingCookieTests.test_two_transactions_do_not_clobber` reddens: the first transaction's callback answers `binding_invalid`, because the second `start` overwrote its cookie.
- (j2) Use the unprefixed name whatever the scheme. `BindingCookieTests.test_https_cookie_is_host_prefixed` reddens on the cookie's name.
- (k) Send Basic credentials as `requests`' `auth=(client_id, secret)`. `ClientAuthTests.test_basic_credentials_are_form_urlencoded` reddens: the client id's own `:` splits the pair in the wrong place, and form-decoding turns each `+` into a space, so neither half equals what was configured. The message shows both pairs.
- (l) Set the assertion's `aud` to the provider's issuer. `ClientAssertionTests.test_assertion_shape` reddens on `aud`, naming the discovered `token_endpoint` it expected.
- (l2) Sign the assertion with the pending key when one exists. `ClientAssertionTests.test_signature_verifies_with_active_certificate_only` reddens: verification against the active certificate fails.
- (m) Delete the `refresh.set_exp(lifetime=…)` call. `SessionLifetimeTests.test_sso_refresh_token_lives_12_hours` reddens: `exp - iat` is 86400. `test_refresh_refused_after_12_hours` reddens too, with a 200 at 12 h 1 s.
- (n) Drop the `last_admin` check from § 4.2 step 6. `apps.accounts.tests.test_oidc_last_admin.LastAdminTests.test_login_demoting_last_admin_refused` reddens: it expects `sso_error=last_admin` and a level of 10, and gets the handoff and a level of 1.
- (n2) Drop it from the refresh path only. `LastAdminTests.test_refresh_demoting_last_admin_refused` reddens: 200 and level 1.
- (n3) In the callback, skip `admin_floor_lock()` and keep the count. `LastAdminTests.test_concurrent_demotions_of_two_admins_one_wins` reddens, deterministically through its barrier: both logins succeed and no active admin remains, which the message names.
- (n4) Make `admin_floor_lock()` also evaluate the first redesign's row locks: `list(User.objects.select_for_update().filter(is_active=True, user_level__gte=10).order_by("pk"))`. The `list()` matters: an unevaluated queryset locks nothing. `LastAdminTests.test_promoting_and_demoting_callbacks_do_not_deadlock` reddens: when E2 fires callback 2 already holds U's row and goes on to wait for I, callback 1 holds I and then waits for U, and one of the two ends in PostgreSQL's deadlock error, which the assertion message quotes.
- (n5) In D17's refresh path, decide on the user object the view loaded instead of the row reloaded under the lock. `LastAdminTests.test_refresh_with_stale_user_cannot_demote_last_admin` reddens: the refresh answers 200, U's level is 0, and no active admin remains, which the message names.
- (o) Validate `token_endpoint` only when the provider is saved, not before the POST. `OutboundPolicyTests.test_discovered_token_endpoint_checked_at_callback` reddens: the fake OP's token handler was called.
- (p) Take the algorithm from the key: build `PyJWK(jwk)` with no `algorithm`, drop the `kty` checks, and pass `algorithms=[key.algorithm_name]`. `SignatureTests.test_jwks_oct_key_refused` reddens: it expects `sso_error=id_token_invalid` and gets the handoff redirect, because PyJWT read the `oct` key as HS256. Dropping the `kty` checks alone would not redden it: the configured `algorithms` list still refuses HS256, and the `kty` checks are the second layer.
  - *Note (2026-11-12, observed on `03c83ecf`):* since S2's fix round 3 an `oct` JWK is refused one layer earlier, by the private-member check in `_select_key` (it carries `k`), so under (p) `SignatureTests.test_jwks_oct_key_refused` stays green. (p) as worded reddens `SignatureTests.test_wrong_family_key_refused` instead, the only test in `apps.accounts.tests` to do so on that tree (the `SelectKeyFamilyTests` refusal tests added with this note redden too): `None != 'id_token_invalid' : expected id_token_invalid, got …/login/sso#code=…`, because PyJWT builds an ES256 key from the EC JWK and the token verifies. The `kty` guard on its own is pinned by `SelectKeyFamilyTests`, which patches out `PyJWK(jwk, algorithm=alg)`, the layer that otherwise refuses a wrong-family key a second time.
- (e) Skip the `provider_id` check in callback step 4. `apps.accounts.tests.test_oidc_flow.MixUpTests.test_transaction_from_other_provider_refused` reddens: it starts at provider A, delivers the callback to provider B's path, expects `sso_error=provider_mismatch`, and gets `token_exchange_failed` or the handoff instead.

**PR description draft:**

> Adds the OIDC authorization-code + PKCE flow (spec PR S2; ADR 0012): per-provider start and
> callback routes, ID-token validation on PyJWT against cached discovery and JWKS, identity
> linking on (provider, issuer, subject) with just-in-time users and a claim → user_level mapping
> that refuses unmapped logins, and a one-time fragment handoff that gives the SPA the same
> simplejwt pair a password login does — so the player, recordings, VOD, catch-up and the
> WebSocket need no change. No Django session is created. The client authenticates with a
> secret (form-urlencoded per RFC 6749) or a signed assertion from its certificate; an SSO
> session lasts 12 hours; the browser binding is a `__Host-` cookie named per transaction; and
> no SSO login, link or refresh can demote the last active admin. The credential-logging check
> now recognises OIDC secrets. Backend only; the UI is PR S3.
> Tests: `apps.accounts.tests`, `tests`. Break-checks listed in the spec's S2 section.

### S3: Frontend login and settings UI

**Changes:** § 5.7. New `data-testid`s are registered. `docs/sso-entra-setup.md` (§ 5.9, ruling B5) lands here, with the form that links to it.

**Tests (vitest):**

- The login page renders provider buttons from a mocked `getAuthConfig`, and hides the password form when it is disabled.
- `completeSsoHandoff`: strips the hash before the exchange request, calls `loginWithTokens` with the response, and maps a failure to `sso_error`.
- **Dev origin.** With `import.meta.env.DEV` true (vitest `define`/`vi.stubEnv`) and `window.location` at `http://localhost:9191`, `exchangeSsoCode`, `startSsoLink` and `getAuthConfig` call `fetch` with a URL whose origin is `http://localhost:9191` (a path starting `/api/accounts/oidc/`), not `:5656`, and with no `credentials: 'omit'`. Test: `frontend/src/__tests__/api.oidc.test.js` › `OIDC endpoints are origin-relative in dev`. Browser binding itself is exercised end to end by S5, which runs the built SPA behind nginx, and by the dev procedure in the S3 PR's test plan: one manual sign-in through `npm run dev` against a running fake OP.
- **Through the real wrapper.** With `localStorage` holding an expired access token and a refresh token, mock only `globalThis.fetch`, not `api.js`, so that `POST token/refresh/` would answer 401. Run `completeSsoHandoff`. The first `fetch` call is `POST /api/accounts/oidc/exchange/` with no `Authorization` header. No `token/refresh/` call is made, and `window.location.href` is never set to `/login`. Repeat for `getAuthConfig`.
- **Ordering under a stale pair.** The `App` auth effect, with `/login/sso#code=x` and a stale password refresh token in `localStorage` whose refresh the mock answers 401, calls `exchangeSsoCode` **before** any `refreshToken`, never navigates to `/login`, and finishes with the new pair stored.
- **Authenticated linking.** With an already-initialized session, a handoff with `intent: 'link'` replaces the pair, resets `isInitialized`, and re-runs `initData`, so `user` is reloaded.
- `loginWithTokens` writes the same three `localStorage` keys `login()` writes.
- The settings form never sends `client_secret` when the field is untouched, and renders each of the four 409 `lockout_guard` reasons (§ 5.5) as its own fixed copy.
- The credential block: "Activate" is disabled with no pending certificate; the Entra variant offers no Basic method and no private-network switch; a provider whose `credential_expiry.state` is `expiring` renders the banner.
- An Admin's `initData` followed by `credential_warnings: [{slug, state: 'expired'}]` shows one notification; a Standard user's makes no `getAuthSettings` call.
- The login page renders fixed copy for `sso_error=client_auth_failed` and `last_admin`.
- The Entra form computes and shows the redirect URI from `public_base_url` and the slug.

**Break-checks:**

- (a) Drop `history.replaceState`. `frontend/src/store/__tests__/ssoHandoff.test.jsx` › `completeSsoHandoff strips the fragment before the exchange request` reddens: it records `window.location.hash` at the moment the mocked `fetch` receives `POST /api/accounts/oidc/exchange/`, expects `''`, and gets `'#code=…'`.
- (b) Send `client_secret: ''` on an untouched field. `frontend/src/components/forms/settings/__tests__/SsoSettingsForm.test.jsx` › `untouched secret is not sent` reddens: it asserts that the mocked `API.updateOidcProvider` payload has no `client_secret` key, and finds `''`.
- (c) Run `completeSsoHandoff` after `initializeAuth()` instead of before. `frontend/src/__tests__/App.ssoHandoff.test.jsx` › `handoff runs before refresh with a stale pair` reddens on a `refreshToken` call preceding `exchangeSsoCode`.
- (e) Build the OIDC URLs with the `host` prefix. `api.oidc.test.js` › `OIDC endpoints are origin-relative in dev` reddens on a `fetch` URL whose origin is `:5656`.
- (d) Drop `auth: false` from `exchangeSsoCode`. `frontend/src/__tests__/api.oidc.test.js` › `exchange is sent unauthenticated through the real wrapper` reddens: its first `fetch` is `token/refresh/`, not `exchange/`.

**PR description draft:**

> Adds the UI for OIDC sign-in (spec PR S3): provider buttons on the login page, a `/login/sso`
> handler that redeems the one-time handoff before auth bootstrap runs, without authenticating the
> request, and stores tokens exactly as a password login does (the `/login/sso` route itself only
> shows a loader),
> an admin-only "Single sign-on" settings section (Entra preset with the redirect URI to paste
> into the app registration, generic provider, certificate or secret credential with expiry
> warnings, claim mappings, password-login toggle) and linked-identity management on the Users
> page. Adds the Entra setup page for operators. No backend change.
> Tests: frontend vitest. Break-checks listed in the spec's S3 section.

### S4: Password toggle, refresh refusal and break-glass

**Changes:**

- § 5.3 enforcement in `TokenObtainPairView`, `TokenRefreshView`, the admin login wrapper and `UserViewSet.me`.
- § 5.3's "refused for every user while password login is off" row for `me`. The `has_usable_password()` rule landed in S2.
- The `admin.site.has_permission` wrap (§ 5.3).
- The `_session_user` check (D19, § 5.4a), with the isolated Gate 2 coverage run.
- **One authorised test change: the static ORM-site ledger.** `apps/proxy/tests/test_tune_path_query_ledger.py`'s `BOUNDARY_MODULES["apps/proxy/authorize.py"]` (`:294-303`) pins `authorize.py`'s model imports and model-class calls, whether or not a branch runs. `BoundaryModulesOrmSitesTests.test_the_boundary_modules_gained_no_orm_read_after_gate_1_was_retired` (`:367-371`) therefore reddens on the new read. This is exactly the behaviour being changed, so the entry is updated. Before and after:
  - `model_imports` gains `("_session_user", "core.models", "CoreSettings")`, a function-local import
  - `model_class_calls` goes from `{"CoreSettings.get_default_output_format": 1}` to `{"CoreSettings.get_default_output_format": 1, "CoreSettings.get_auth_settings": 1}`
  - `objects` and `get_object_or_404` are unchanged

  The read is not routed through an indirection to keep the scanner quiet. The **runtime** ledger (`LEDGER`, and the five `…_runs_no_query_outside_its_ledger` tests at `:242-263`) is **not** changed: the anonymous drives run no new query, and that is the evidence.
- The `password_login` command's `auth_config_changed` event, with `user='cli'`.
- § 5.5's rule, floor and serialization. This replaces S1's unconditional `password_toggle_unavailable` refusal, so the toggle, its enforcement and the break-glass become usable in one merge.
- Every gate reads `auth_settings` fresh (§ 5.1).
- `PASSWORD_LOGIN_FORCE` read in settings, and `MINO_PASSWORD_LOGIN_FORCE` added to the entrypoint's optional-variable loop and to `tests/test_entrypoint_env_propagation.py` (§ 5.6). Both S1 and S4 edit `dispatcharr/settings.py`, a shared path prefix, so every backend label runs, `tests` included.
- `e2e/tests/guards/sso-recovery-doc.spec.ts`, and the command-line builder moved to `e2e/fixtures/manage-command.ts` (§ 5.6).
- The `password_login` management command (`apps/accounts/management/commands/password_login.py`), with § 5.6's `--status` and `--enable` output.
- `password_login_forced` in `providers/`.
- `docs/sso-recovery.md` (§ 5.6), and the `LoginForm` and `client_auth_failed` copy that link to it.

**Tests:**

- every row of § 5.3; T12 (S4 half), T12a (S4 half), T13, T28, T29 (S4 half)
- all fourteen § 5.5 tests, and T15a's `test_unrelated_patch_cannot_empty_the_enabled_set`, in `apps.accounts.tests.test_password_login_toggle.LockoutGuardTests`. The tests of the mechanisms ruling B1 removed are not carried over (the list is in § Recorded owner rulings (2026-11-11)).
- T13's `RecoveryTests`
- the env force over a DB false (`override_settings(PASSWORD_LOGIN_FORCE=True)`)
- the command's three verbs and `--force`: `--disable` with no enabled provider exits non-zero and leaves the row unchanged, and with `--force` writes it; under `override_settings(RUNTIME_SQLITE=True)`, `--disable --force` still exits non-zero naming `requires_postgresql` (§ 4.4)
- that no HTTP route can change `PASSWORD_LOGIN_FORCE`
- **Fresh read against a warmed stale cache.** Warm the Redis group cache by calling `CoreSettings._get_group("auth_settings", …)` while the row says enabled. Then flip the row to disabled with `CoreSettings.objects.filter(key="auth_settings").update(...)`, which fires no signal and so leaves the warmed cache stale. `POST token/` must answer 403 `password_login_disabled`.

**Break-checks:**

- (a) Check only the DB in the login gate and ignore the env. `apps.accounts.tests.test_password_login_toggle.BreakGlassTests.test_env_force_overrides_db_off` reddens: with `override_settings(PASSWORD_LOGIN_FORCE=True)` and the row disabled, it expects `POST token/` → 200 and gets 403.
- (b) Accept any refresh token while password login is disabled. `apps.accounts.tests.test_password_login_toggle.RefreshGateTests.test_password_issued_refresh_refused_when_off` reddens: it expects 401 `token_not_valid` for a refresh token with no `auth_method` claim, gets 200, and its message names `auth_method`.
- (c) Read `auth_settings` through `CoreSettings._get_group` in the login gate. `apps.accounts.tests.test_password_login_toggle.PasswordLoginGateTests.test_fresh_read_beats_warmed_stale_cache` reddens with a 200 in place of 403. The pre-warmed cache is what makes the failure name the cache rather than an ordinary miss.
- (d) Drop the `auth_method == "oidc"` comparison from the rule. `apps.accounts.tests.test_password_login_toggle.LockoutGuardTests.test_password_session_admin_refused` reddens: the answer is still 409, because a password token has no `oidc_provider` either, but its `reasons` no longer include `not_sso_session`, which the assertion names. The comparison is what gives the operator the right reason; the refusal itself is over-determined.
- (d2) Drop the "provider is enabled now" check. `LockoutGuardTests.test_proof_provider_since_disabled_refused` reddens: it expects 409 with `provider_not_enabled` and gets 200.
- (d3) Drop the `oidc_level == 10` comparison. `LockoutGuardTests.test_standard_at_sign_in_promoted_later_refused` reddens: it expects 409 with `not_admin_at_sign_in` and gets 200.
- (d4) Drop the floor from the provider update path. `LockoutGuardTests.test_disable_last_enabled_provider_while_off_refused` reddens: it expects 409 with `last_enabled_provider` and gets 200 with the provider disabled.
- (d5) Reinstate the removed rule: while password login is off, refuse any provider write that bumps `version`. `LockoutGuardTests.test_single_provider_credential_rotation_while_off` reddens: it expects 200 and gets 409. This pins ruling B1's purpose, so the stricter guard cannot return unnoticed.
- (e) Remove the `select_for_update()` on the `auth_settings` row. `LockoutGuardTests.test_concurrent_disables_of_last_two_providers_one_wins` reddens with two 200s and no enabled provider, deterministically, because of the barrier described in § 5.5.
- (h) Remove the `_session_user` password-off check. `apps.proxy.tests.test_authorize_session_principal.SessionPrincipalPasswordOffTests.test_session_principal_refused_when_password_login_off` reddens: it expects `AuthorizeDenied` with status 401 and gets a resolved principal.
- (h2) Put the check **before** `get_user`. `apps.proxy.tests.test_tune_path_query_ledger` reddens on an extra `core_coresettings` query keyed `auth_settings` in the authorize-hop ledger.
- (e2) In the provider update path, decide whether the floor applies from a read of `auth_settings` made **before** the lock, and when that read says password login is on, skip the lock and write directly. `LockoutGuardTests.test_switch_off_racing_disable_of_only_provider_serialized` reddens:
  - Thread B (disable Q) reads "on", takes no lock and waits at the barrier.
  - Thread A (switch password login off, token from Q) locks, reloads, finds Q enabled, passes the rule and waits at the barrier.
  - Both pass. A commits, then B commits.
  - Both requests return 200.

  The test's assertion fails on the forbidden state, password login off with no enabled provider, and its message names it.
- (g) Remove `MINO_PASSWORD_LOGIN_FORCE` from the entrypoint's optional-variable loop. `tests.test_entrypoint_env_propagation.EntrypointEnvPropagationTests.test_auth_switches_reach_login_shells` reddens, naming the variable.
- (g2) Write the page's first command as `docker exec <container> python manage.py password_login --enable`. `e2e/tests/guards/sso-recovery-doc.spec.ts` › `every documented command runs through the login shell` reddens, quoting the line.
- (f) Make `password_login --enable` print nothing about passwords. `RecoveryTests.test_enable_reports_no_admin_has_a_password` reddens: the output does not name `changepassword`.

**PR description draft:**

> Makes password login switchable at runtime (spec PR S4): when an admin turns it off — which the
> lockout guard allows only from an SSO session, on an enabled provider, that mapped them to
> Admin — the token, login and admin-login endpoints refuse passwords, password-issued refresh
> tokens stop refreshing, and API keys keep working. While it is off the last enabled provider
> cannot be disabled or deleted; every other provider edit, credential rotation included, is
> allowed. Break-glass is `MINO_PASSWORD_LOGIN_FORCE=1` in the environment or
> `python manage.py password_login --enable`; neither is reachable from the web, and
> `docs/sso-recovery.md` gives the full procedure for an instance whose admins have no password.
> Tests: `apps.accounts.tests`. Break-checks listed in the spec's S4 section.

### S5: E2E with a fake OIDC provider

**Changes:**

- **The fake OP.** `e2e-upstream/src/oidc/` serves a minimal OP on the existing server:
  - discovery, with neither `code_challenge_methods_supported` nor `authorization_response_iss_parameter_supported`, as Entra's has neither (§ 3.5)
  - `authorize`: auto-approves; the next login's claims are set through the control API
  - `token`: **requires** a valid PKCE `code_verifier` although discovery does not advertise PKCE, and verifies the client secret from the form body (`client_secret_post`)
  - `jwks`, whose entries carry no `alg` member, as Entra's do not

  It uses `node:crypto` (`generateKeyPairSync`, `sign`). **No new npm dependency, and no new image:** the existing digest-pinned `node:24-slim` stages (`e2e-upstream/Dockerfile:18, :29`) build it.
- **Faults**, selectable per login: wrong `iss`, wrong `aud`, bad nonce, expired, `alg=none`, unknown `kid`, and omitting the RFC 9207 `iss` while advertising it.
- **Concrete origins.** `issuer` is `http://<upstream container name>:8080/oidc`, the in-network origin. That is `E2E_UPSTREAM_INTERNAL_URL` (`e2e/fixtures/upstream.ts:8`) + `/oidc`, which Django reaches for discovery, `token` and `jwks`. Discovery advertises `authorization_endpoint` as `E2E_UPSTREAM_CONTROL_URL` + `/oidc/authorize`, the host-published origin (`upstream.ts:5`, `http://127.0.0.1:9402` by default) that the Playwright browser on the runner reaches. Both base URLs are passed to the provider as environment by `scripts/e2e_up.sh` when it starts the upstream container, so discovery is built from them and not hard-coded. The issuer is an opaque string; only its fetches need to resolve, and Django makes them in-network. The upstream container's address is a private one, so the specs seed their provider as a **generic** provider with `allow_private_network: true` (§ 3.5) and `client_auth_method: client_secret_post`.
- **What e2e does not reach.** The stack is plain HTTP on loopback, so the browser gets the unprefixed fallback cookie (§ 3.2 step 5); the `__Host-` form is pinned by S2's `BindingCookieTests`. `private_key_jwt` is pinned by S2's `ClientAssertionTests` and not repeated here.
- **Launcher.** `scripts/e2e_up.sh:369-376`'s `docker run` passes `-e MINO_OIDC_ALLOW_HTTP=1` only when `E2E_OIDC_ALLOW_HTTP=1` is set in the invoking environment. The new variable is named neutrally (`CONTEXT.md` § Mino), so the shared stack never gets it. `public_base_url` is the loopback `http://localhost:<DISPATCHARR_E2E_PORT>`, which § 5.1 accepts without the env.
- **Playwright project.** `sso` in `e2e/playwright.config.ts`: `testDir: './tests/sso'`, `workers: 1`, `fullyParallel: false`, with its `baseURL` taken from `E2E_BASE_URL` like every project (`playwright.config.ts:5`). It runs **only against a scoped stack** of its own:
  - `DISPATCHARR_E2E_CONTAINER`, `_VOLUME`, `_NETWORK` and `_PORT` (`scripts/e2e_up.sh:121-128`), plus `E2E_BASE_URL` to match
  - **one shared scope assertion**, `assertScopedStack(env = process.env)` in `e2e/tests/sso/scope.ts`. It is a pure function that throws, naming each failing variable, unless all of these hold:
    - `DISPATCHARR_E2E_CONTAINER`, `_VOLUME`, `_NETWORK` and `_PORT` are all set
    - the container name is not the shared default `dispatcharr-e2e`
    - `_PORT` is not the shared default `9191`
    - `E2E_BASE_URL` is set **explicitly**. The `http://localhost:9191` default in `e2e/playwright.config.ts:5` does not count, because the function reads the environment, not the config.
    - its host is a loopback literal (`localhost`, `127.0.0.1`, `[::1]`), and its port equals `DISPATCHARR_E2E_PORT`

    This ties the HTTP target to the container that `instance.manage()` acts on. `instance.ts:67-68` picks that container from `DISPATCHARR_E2E_CONTAINER` independently, and `e2e_up.sh:119-128` checks only that variables are present, not that they correspond.
  - It is the **first statement** of `sso.setup.ts`, before `ensureSuperuser` sends any request, and the first statement of a `test.beforeAll` in every `sso` spec, before any mutation.
  - Its refusal cases are pinned without a container or browser, in the `guards` project, by `e2e/tests/guards/sso-scope.spec.ts`:
    - `refuses a missing E2E_BASE_URL`
    - `refuses a base URL port that differs from DISPATCHARR_E2E_PORT`
    - `refuses a non-loopback base URL`
    - `refuses the shared container name`
    - `refuses the shared port`
    - `accepts a consistent scoped stack`

    Each passes an env object and asserts the thrown message names the variable. Because the function is pure and is called before any request, a refusal is a refusal before any HTTP mutation.
  - Break-check: when `E2E_BASE_URL` is unset, make `assertScopedStack` substitute `http://127.0.0.1:${DISPATCHARR_E2E_PORT}` and keep every other check. `refuses a missing E2E_BASE_URL`, whose env is otherwise a consistent scoped stack, reddens deterministically: no error is thrown. Substituting the shared `localhost:9191` would not do it, because the port-match and shared-port rules would still throw.

  Turning password login off is instance-wide, and ADR 0001's shared container must never see it.
- **Bootstrap and tokens.** The project has its own setup file, `tests/sso/sso.setup.ts`, run as a `sso-setup` project that `sso` lists in `dependencies:`. It never reads the shared `playwright/.auth/tokens.json` or `principals.json`. The setup:
  1. calls the existing `ensureSuperuser` (`e2e/setup/provision-admin.ts:34`) against the scoped stack's `E2E_BASE_URL`, which creates the private stack's first admin through `initialize-superuser`
  2. reads `GET /api/accounts/oidc/providers/`. If `password_login_enabled` is false, a previous run died mid-test, and setup fails with a message naming `scripts/e2e_up.sh --reset` and the scoped variables to rerun with. It does not repair the state itself, because that would need the `instance` fixture here too.
  3. obtains the admin pair:
     - if `playwright/.auth/sso-tokens.json` holds a refresh token that the unthrottled refresh endpoint accepts, it uses that, for **0** password logins
     - otherwise it makes one login through `loginWithThrottleBackoff` (`e2e/setup/login.ts:207`), which honours `Retry-After`
  4. writes the pair to `playwright/.auth/sso-tokens.json` through `writeAuthFileAtomically` (`e2e/setup/auth-files.ts:81`, mode 0600)

  Each spec builds `new ApiClient(request, pair)` from that file (`e2e/fixtures/api.ts:60-83`; a client handed a pair never touches `tokens.json`). The browser half signs in through the SSO button, and a test that needs the SSO admin's own pair (§ 5.5's rule) reads it from the page's `localStorage` after sign-in.
- **Password-request budget.** `POST /api/accounts/token/` allows 3 requests per minute per IP, and failed requests count too (`apps/accounts/api_views.py:58`; `e2e/README.md` § "The login throttle"). The whole `sso` run spends at most **3**: at most one in setup (cold only), plus the break-glass spec's two probes. No other `sso` spec sends a password. The project runs `workers: 1` and `fullyParallel: false`, so no two password requests overlap. **The specs are order-independent**, and nothing relies on execution order. The break-glass spec leaves password login on when it finishes (it ends with `--enable` and a successful login), and no other `sso` spec sends a password or depends on the toggle's state. A cold run therefore sits exactly on the cap, and a warm run spends 2, in any order.
- **The negative probe is never retried.** The password-off `POST token/` probe is a raw `request.post` with no backoff helper, asserting `status() === 403` and `code === 'password_login_disabled'`, so a retry can never turn a real 200 into a pass. A 429 fails the test with a message naming the budget. The positive probe after break-glass goes through `loginWithThrottleBackoff`, so a budget overlap only waits. The project timeout allows one 60 s throttle window: 180 s, the streaming projects' order of magnitude.
- **CI.** `.github/workflows/e2e-tests.yml:100` adds `"sso"` to the explicit `projects` list. Its job sets the four scoped-stack variables, `E2E_BASE_URL` and `E2E_OIDC_ALLOW_HTTP=1`. It runs on the same change-detector pattern (`e2e-tests.yml`'s `changes` job, which already includes `apps/`, `frontend/`, `e2e/` and `e2e-upstream/`), so `E2E result` requires it.
- **Local development.** Because this PR changes `e2e-upstream/`, the implementer runs it with a **private provider** and a scoped stack, per `e2e/README.md:86-99`: `DISPATCHARR_E2E_UPSTREAM_CONTAINER`, `_PORT` and `_IMAGE`, plus `E2E_UPSTREAM_CONTROL_URL` and `E2E_UPSTREAM_INTERNAL_URL`. The PR description lists the exact exports used.
- **Capabilities.** The break-glass test lives alone in `e2e/tests/sso/break-glass.spec.ts` and calls the **existing** `instance.manage()` in `e2e/fixtures/instance.ts` (`:378`), which already builds the `docker exec … manage.py` line.
  - `instance.ts` is already on the `SUBPROCESS` and `CONTAINER_INTROSPECTION` allowlists (`e2e/tests/guards/allowlist.ts:59-90`), so neither needs a new entry.
  - Destructuring the `instance` fixture **is** detected independently (`e2e/tests/guards/capabilities.spec.ts:92-101`, enforced at `:137-139`). So `CONTAINER_LIFECYCLE` (`allowlist.ts:35-56`) gains exactly one entry, `'tests/sso/break-glass.spec.ts'`. Its comment: it runs one management command inside its own scoped container to recover from password-off state that the shared container must never hold, and it never calls `up`/`restart`/`recreate`/`down`.
  - That capability's `why` text is extended to name break-glass recovery.
  - The other `sso` specs do not take the fixture.
- **Global-mutation guard.** `e2e/tests/guards/global-mutation.spec.ts` treats `/api/accounts/oidc/settings/` and `providers-admin/` as instance-wide writes, allowlisted only for files under `tests/sso/`.
- `e2e/COVERAGE.md` rows.

**Tests:**

- **Happy path** (`@contract`, `tests/sso/sign-in.spec.ts` › `signs in through the fake OP and plays a channel`). Seed a provider through the API, then click the button in the browser, so the fake OP completes the flow. Assert:
  - the user is created at the mapped level
  - the channels page loads
  - a live channel plays in the floating player
  - the WebSocket connects
- **Unmapped claim** (`@contract`). It lands on `/login?sso_error=no_mapping`.
- **Toggle and break-glass** (`@characterization`, `tests/sso/break-glass.spec.ts`). Sign in through SSO as Admin, then switch password login off with the SSO pair read from `localStorage`. The raw, unretried `POST token/` → 403. Then run `password_login --enable` through `instance.manage()`, which is the recovery page's first command verbatim (§ 5.6), and assert its exit code is 0 and its output carries the usable-password count; run `password_login --status` the same way and assert it prints the DB value as enabled. `POST token/` via `loginWithThrottleBackoff` → 200. That leaves the stack with password login on for the next run. Its comment names the implementation fact it pins: the `password_login` management command, run inside the AIO container. Per ADR 0002, an operator CLI inside the image is something a reimplementation may change.

**Break-check:** make the fake OP return the wrong `aud` (the `wrong-aud` fault set as the default for every login). `e2e/tests/sso/sign-in.spec.ts` › `signs in through the fake OP and plays a channel` reddens: its `expect(page).toHaveURL(/\/channels/)` times out on `/login?sso_error=id_token_invalid`, which shows the browser path really validates.

**PR description draft:**

> Adds end-to-end coverage for OIDC sign-in (spec PR S5): a minimal fake OpenID provider in
> `e2e-upstream` (node stdlib crypto, no new image or dependency) with injectable token faults,
> and an `sso` Playwright project on its own container that signs in through it, plays a channel,
> switches password login off and recovers with the break-glass command.
> Tests: `E2E result` (`sso` project). Break-check: a wrong-audience fault reddens the happy path.

### Overlap with sibling work

| Sibling | Overlap | Handling |
|---|---|---|
| Mino rename C1 (#613, open) | `frontend/src/pages/Login.jsx`, `LoginForm.jsx` strings and logo | S3 rebases onto whatever lands first. New strings use the live product name. |
| Mino rename R1 (#612, open) | name ratchet over living files | New code adds no `dispatcharr` string beyond imports of the kept `dispatcharr` package. If R1 has merged, each PR runs `scripts/check_product_name.py`. |
| Mino rename E1 | `DISPATCHARR_*` → `MINO_*` env alias | The two new env vars are born `MINO_*` and need no alias. |
| Mino rename W1 | `X-Dispatcharr-*` headers | None used. |

## Recorded owner rulings on the open questions (2026-10-31)

The owner answered "accept defaults except 8", with these specifics:

| Q | Ruling | Where it is applied |
|---|---|---|
| Q1 | **Yes**: a mapping change also demotes on token refresh, only if that is cheap. No IdP call on refresh; re-evaluate from what the server already holds. | D17, § 5.4, § 4.3, T27, S2 |
| Q2 | **No**: mappings do not assign Channel Profiles (later). | § 4.2 step 5 (JIT users get no profiles) |
| Q3 | **Yes**: single-tenant Entra only. | D10, § 3.6, T9 |
| Q4 | **Yes**: provider and auth-settings changes write an audit `SystemEvent`, with no secret in the payload. | D18, § 7, T29, S1, S4 |
| Q5 | **Out**: RP-initiated and federated logout stay out of scope. | D15, § 6 |
| Q6 | **Yes**: API keys keep working when password login is off. | § 5.3 |
| Q7 | **Yes**: switching password login off also stops pre-existing Django sessions authorizing streams through `_session_user`. | D19, § 5.3, § 5.4a, T28, S4 |
| Q8 | **In scope now**: an admin-only Users-page deactivate/activate control, with tests that a deactivated user's access and refresh are refused. The CLI one-liner stays as break-glass. | D20, § 5.8, § 4.3, T30, S0 |

## Recorded owner rulings (2026-11-11)

A documentation-backed review of the spec at `04e76269` returned NO-GO. The owner then ruled as follows. These override the 2026-10-31 text wherever they differ; R1 to R4 and Q1 to Q8 otherwise stand.

| # | Ruling | Where it is applied |
|---|---|---|
| B1 | **Simplify the lockout guard.** Password login can be switched off only by an admin whose own token came from an SSO sign-in on a currently enabled provider that mapped them to Admin at that sign-in. Drop the provider-version and redirect-hash proofs, the proposed-state evaluation, and the rule needing a proof from a different provider to edit a provider while passwords are off: a single-Entra instance must be able to rotate its credential without toggling password login. Break-glass covers the rest. One floor stays: disabling or deleting the last enabled provider while password login is off is refused. | D12, § 5.5, § 3.3 step 9, § 5.4, T13, S4 |
| B2 | **Response mode stays `query`.** `form_post` is recorded as considered and rejected. | D24, § 3.2 |
| B3 | **Shorter SSO session.** SSO-issued refresh tokens live about 12 hours. | D25, § 3.3 step 9, § 1, T34, S2 |
| B4 | **Certificate credential.** `private_key_jwt` client authentication as an alternative to a client secret, for Entra and generic providers. | D23, § 3.4a, § 5.2, T15, T33, S1, S2 |
| B5 | **Entra setup operator page.** | § 5.9, S3 |
| B6 | **Binding cookie.** `__Host-` prefix and a per-transaction name. | D3, § 3.2 step 5, T3b, S2 |

**What B1 removed from the earlier drafts**, so nobody looks for it:

- The token claim `oidc_redirect`. Five claims remain (§ 3.3 step 9): `auth_method` and `oidc_provider` (the refresh gates and the guard), `oidc_provider_version` and `oidc_identity` (D17 only), `oidc_level` (the guard only).
- The guard's use of `oidc_provider_version`, its "proposed state" evaluation, its requirement that the proof provider's secret decrypt, old rule 2 (a proof from another provider to edit a provider while off) and old rule 3 (no `public_base_url` change while off).
- The row locks on every `OIDCProvider` row. One lock on the `auth_settings` row remains.
- Tests: `test_stale_proof_refused`, `test_slug_rename_while_off_refused`, `test_base_url_change_then_disable_refused`, `test_combined_patch_refused`, `test_unusable_remaining_provider_refused`. `test_concurrent_disables_one_wins` and `test_disable_racing_provider_edit_serialized` are replaced by two tests of the races the simplified rule still has. `test_standard_at_issuance_promoted_later_refused` survives, renamed.
- Break-checks: S4 (d) "drop `oidc_provider_version` from the proof check" and (d2) "drop the `oidc_redirect` comparison". S4's (d) to (e2) are re-derived from the new rule.
- `--disable`'s requirement of a decryptable secret and a set `public_base_url`.

**Defects the same review found, and where each is fixed:**

| # | Defect | Fix |
|---|---|---|
| A1 | An SSO demotion of the last admin reopened the unauthenticated first-admin bootstrap. | D21, § 4.4, T31 |
| A2 | Break-glass did not recover an instance whose admins have no password, and a credential's expiry was never mentioned. | § 5.6's procedure, D26, § 5.2, T13, T35 |
| A3 | `client_secret_basic` was the default with no encoding specified. | D23, § 3.4a, T32 |
| A4 | An issuer ending in `/` produced a `//.well-known` discovery URL. | § 3.5, T20b |
| A5 | Outbound fetches bypassed the repository's SSRF check. | D22, § 3.5, T20a |

**Recorded, not changed:** the library comparison is corrected in § 2 and ADR 0012 (C1); what live Entra's discovery and JWKS contain is in § 3.5 (C2); sovereign clouds and External ID use the generic form (C3, § 3.6); Entra redirect URIs are validated to 256 characters (C4, § 3.6, T36).

**Places where a ruling was applied other than literally:**

- B4 asked for the assertion's `x5t`/`x5t#S256` header to be read from Microsoft's page. The page as fetched on 2026-11-11 lists only `x5t#S256` with `PS256`, so the SHA-1 `x5t` is not sent (§ 3.4a).
- B1 keeps "a currently enabled provider" as the stored state at the time of the request. A provider whose credential has silently expired is still "enabled", so the rule cannot see that; § 5.2's expiry warning and § 5.6's recovery are what cover it.

## Open question for the owner

| Q | Question | Default in this spec |
|---|---|---|
| Q9 | Should `initialize_superuser` also stay closed whenever **any user** exists, not only while a provider exists? That would close the bootstrap after a local admin demotes or deletes themselves on any instance, at the price of making `createsuperuser` the only recovery there, and it changes behaviour that `apps/accounts/tests/test_accounts.py:35-44` pins. | **No.** Closed while a provider exists (§ 4.4); otherwise unchanged. |
