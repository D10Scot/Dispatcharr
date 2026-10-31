# OIDC single sign-on for the web UI and REST API login

Date: 2026-10-31. Seed SHA: `149678aa3accd82997d523e9747305ccd4c52a46`. Implement this spec PR by PR with subagents, following CLAUDE.md § Delegation for phase work.

The product is being renamed from Dispatcharr to Mino (`docs/superpowers/specs/2026-10-28-mino-rename-design.md`). This spec uses the names live at the seed SHA. Every **new** identifier it introduces is named neutrally or for Mino, as `CONTEXT.md` § Mino requires, so the rename never has to touch it:

- env vars `MINO_PASSWORD_LOGIN_FORCE` and `MINO_OIDC_ALLOW_HTTP`
- the cookie `mino_oidc_tx`
- the settings group `auth_settings`
- the routes under `/api/accounts/oidc/`

New Python modules live in the `dispatcharr` and `apps` packages, which the rename keeps (its C-10). User-visible strings use whatever product name the tree carries when each PR lands; its C1 decides that.

ADR: `docs/adr/0011-oidc-sign-in-is-hand-rolled-on-pyjwt-and-mints-the-existing-jwt-pair.md`.

## Goal

Admins and users sign in to the web UI, and so obtain REST API credentials, through an OpenID Connect provider. Microsoft Entra ID is the preferred provider and gets a preset; any standards OIDC provider works through the generic form. Username and password login remains the fallback, and an admin can switch it off at runtime without locking the instance out.

## Owner rulings (override every default below)

- **R1. Config home.** Providers and the password toggle live in the database and are edited in the admin UI. A change takes effect with no restart. Client secrets are stored in the database.
- **R2. Provisioning.** Create the user just in time on their first SSO login. Map Entra app roles or groups (generic: a configurable claim) to `user_level`: Streamer 0, Standard 1, Admin 10. Refuse a login that matches no mapping.
- **R3. Break-glass.** When password login is off, a `manage.py` command and/or an env var turns it back on. Neither is reachable from the web.
- **R4. Protocols.** OIDC only: a generic provider plus an Entra preset (tenant id, issuer, app roles).
- **Standing fact.** SSO covers web UI and REST API login only. Xtream, M3U, HDHomeRun and stream clients keep their protocol-level credentials.

## Decisions at a glance

| # | Decision |
|---|---|
| D1 | Hand-rolled authorization code + PKCE (S256) flow on **PyJWT** and **requests**, both already locked. No new dependency. (ADR 0011) |
| D2 | SSO ends by minting the **existing simplejwt pair** (`RefreshToken.for_user`). The SPA, WebSocket, player, recordings, VOD and catch-up need no change. |
| D3 | The callback **never calls `django.contrib.auth.login()`** and sets no Django session. Transient state lives in Redis behind a single-use key, bound to the browser by an HttpOnly cookie. Linking starts only from an authenticated `POST`, so the binding exists only in the linking user's own browser. |
| D4 | Tokens reach the SPA through a **one-time exchange code** in the URL **fragment**, redeemed by `POST`. Tokens never appear in a URL. |
| D5 | **Per-provider redirect URI** `<public_base_url>/api/accounts/oidc/<slug>/callback/`. The transaction is bound to a provider. RFC 9207 `iss` is checked when the provider advertises it. |
| D6 | `public_base_url` is **explicit configuration**, and must be https except for loopback or the `MINO_OIDC_ALLOW_HTTP` deployment switch. The `Host` header is never used to build a redirect URI. |
| D7 | Providers live in a **dedicated model** (`OIDCProvider`), not in `CoreSettings`. `CoreSettings` is readable by every Standard user. The password toggle and `public_base_url` live in a new `CoreSettings` group, `auth_settings`, which the generic settings endpoint refuses to write, rename or delete. Security decisions read it fresh from Postgres, never through the group cache. |
| D8 | Identity is keyed on **(provider, issuer, subject)**. Email is never used for matching. A provider's issuer, tenant and client id are immutable once identities exist. An existing local user links through an explicit, authenticated "link" flow. |
| D9 | `user_level` is **recomputed from the mapping on every SSO login**, before any write. No match means refusal, and nothing is written. |
| D10 | Entra preset: **single tenant only**. A tenant GUID is required; `common`, `organizations` and `consumers` are refused. `roles` is the default claim. A groups overage refuses the login rather than calling Graph. |
| D11 | Client secret **encrypted at rest** (Fernet, key derived from `SECRET_KEY` by HKDF), write-only in the API. |
| D12 | Password-off **lockout guard**: refuse unless the acting admin's own token came from an SSO login on an enabled provider **at its current configuration version and redirect URI**, evaluated against the complete proposed state. While password login is off, the same proof, from another provider, is needed to change or disable a provider. Guarded writes are serialized by row locks. The toggle, its enforcement and break-glass land together in S4. |
| D13 | Password-off also **refuses refresh of password-issued tokens**. Only a ≤30-minute access-token tail survives the switch. |
| D14 | Break-glass: `MINO_PASSWORD_LOGIN_FORCE=1` (env, wins over the DB) and `manage.py password_login --enable/--disable/--status` (writes the DB). |
| D15 | RP-initiated logout, SAML, SCIM, Graph lookups, multi-tenant Entra and paired-device auth are **out of scope**. |
| D16 | E2E uses a **fake OIDC provider added to `e2e-upstream`** (node stdlib crypto, no new image, no new npm dependency) and a new `sso` Playwright project with its own container. |

## 1. Current auth surface (verified at the seed SHA)

### REST API

- `dispatcharr/settings.py:328-346`: `REST_FRAMEWORK` authenticates with `rest_framework_simplejwt.authentication.JWTAuthentication`, then `apps.accounts.authentication.ApiKeyAuthentication` (`:334-337`). The default permission is `IsAdmin` (`:338-340`). The only throttle rate is `"login": "3/minute"` (`:344`).
- `dispatcharr/settings.py:492-497`: `SIMPLE_JWT` sets access tokens to 30 minutes and refresh tokens to 1 day. `ROTATE_REFRESH_TOKENS` is `False`, and `token_blacklist` is not in `INSTALLED_APPS` (`:110-139`), so no token can be revoked before it expires.
- Routes are in `apps/accounts/api_urls.py:29-37`: `auth/login/` (`AuthViewSet.login`, an alias), `auth/logout/`, `initialize-superuser/`, `permissions/`, `token/` and `token/refresh/`.
- `apps/accounts/api_views.py:57-131`: `TokenObtainPairView` gates on `network_access_allowed(request, "UI")` (`:61`) and throttles with `LoginRateThrottle` (`:58`). It writes `login_success` and `login_failed` `SystemEvent`s through `log_system_event` (`:68-74, :99-104, :110-116, :123-129`) and sets `last_login` (`:94-96`).
- `apps/accounts/api_views.py:134-158`: `TokenRefreshView` applies the same UI ACL. In simplejwt 5.5.1, `TokenRefreshSerializer.validate` looks the user up with a bare `.get()` and applies `USER_AUTHENTICATION_RULE`, so an inactive user cannot refresh. `RefreshToken.access_token` copies every claim except `token_type`, `exp`, `jti` and `iat` into the new access token (simplejwt 5.5.1 `tokens.py:379-410`, `serializers.py:102-150`, read from the PyPI wheel). **A custom claim set at mint time therefore survives every refresh.** D12 and D13 rely on this.
- `apps/accounts/api_views.py:228-245`: `logout` writes a `logout` event and calls `django.contrib.auth.logout(request)` (`:244`). That call is a no-op for a JWT caller, who has no session.
- `apps/accounts/api_views.py:288-312`: `UserViewSet.me` lets a user `PATCH` their own `password` (`ALLOWED_FIELDS` at `:292`). `UserSerializer.update` sets it (`apps/accounts/serializers.py:157-158`). An SSO-only user could therefore give themselves a local password and bypass the IdP's MFA. § 5.4 closes this.
- `apps/accounts/api_views.py:161-194`: `initialize_superuser` is the first-admin bootstrap. It is IP-gated and closes once any `user_level >= 10` exists.
- `apps/accounts/authentication.py:47-88`: API keys are read from `X-API-Key` or `Authorization: ApiKey`, looked up by plaintext value, and refused for inactive users. `:91-104` is `QueryParamJWTAuthentication`, which reads `?token=` for `<video src>` media.
- `apps/accounts/models.py:12-33`: `User(AbstractUser)` carries `user_level` (default `STREAMER`, `:30`), `channel_profiles` M2M (`:25-29`), `custom_properties`, `api_key` and `stream_limit`. `apps/accounts/serializers.py:16` defines `SAFE_CREDENTIAL_RE = ^[A-Za-z0-9._@-]+$` for usernames.
- `apps/accounts/permissions.py:6-28`: `Authenticated`, `IsStandardUser` and `IsAdmin` all apply the UI network ACL. `:42-49` grants `list`/`retrieve` to `IsStandardUser`, and `core/api_views.py:116-120` uses that mapping for `CoreSettingsViewSet`. **Every Standard user can read every `CoreSettings` group.** That is why D7 keeps secrets out of `CoreSettings`.
- `apps/accounts/admin.py:23-38` wraps Django admin's `login` in the shared throttle. `docker/nginx.conf:642-644` 301s every `/admin` path to `/login` in every nginx-fronted shape, so the admin site is reachable only in dev, with no nginx.

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

Recorded in ADR 0011. The comparison:

- **`mozilla-django-oidc`.** Each RP endpoint and credential is a single Django setting (`OIDC_RP_CLIENT_ID`, `OIDC_OP_AUTHORIZATION_ENDPOINT`, …). PKCE sits behind `OIDC_USE_PKCE` (default off), and success establishes a Django session (`SessionRefresh` middleware, tokens "in the user session"). Source: https://mozilla-django-oidc.readthedocs.io/en/stable/settings.html. It fails R1 (settings, not DB), multi-provider, and D3 (session).
- **`django-allauth`**, OpenID Connect provider. Providers are declared as `APPS` entries in the `SOCIALACCOUNT_PROVIDERS` setting, one independent instance each (https://docs.allauth.org/en/latest/socialaccount/providers/openid_connect.html). allauth also has a `SocialApp` DB model, but that page does not document it for OIDC, and I did not verify a runtime-editable path. Either way it brings the allauth account framework (its own login views, email handling, session login and headless mode) for one flow, plus custom glue to hand the SPA a simplejwt pair.
- **Authlib** Django client. `oauth.register(name, …)` or `AUTHLIB_OAUTH_CLIENTS` in settings, with `code_challenge_method='S256'` (https://docs.authlib.org/en/v0.11/client/django.html; I could not reach the current-version Django client page, so the v1.x specifics are unverified). The registry is in-process, so a live DB edit needs per-process re-registration across four uWSGI workers. It adds a new dependency and its JOSE stack, and the simplejwt glue is still ours.
- **Hand-rolled on PyJWT + requests.** PyJWT 2.15.1 and `cryptography` 50.0.0 are already in `uv.lock` (`:1736`, `:542`), `requests` 2.34.2 too (`:1987`). PyJWT provides what the flow needs (https://pyjwt.readthedocs.io/en/stable/api.html, `PyJWKClient` parameters and `jwt.decode`):
  - `jwt.decode(token, key, algorithms=…, audience=…, issuer=…, leeway=…, options={"require": [...]})`
  - `PyJWK`/`PyJWKSet` (https://pyjwt.readthedocs.io/en/stable/usage.html: JWKS keys are selected by `kid`)

  DB-backed, multi-provider and session-free by construction.

**Chosen: hand-rolled on PyJWT.** It needs no new supply-chain surface and satisfies R1 natively. JWS verification stays in a vetted library. The cost is roughly 400 lines of protocol code we own, which is why § 8 and the fable-from-round-one review cadence apply.

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
| `POST providers-admin/<id>/test/` | `IsAdmin` | Fetches and validates discovery and JWKS, then reports the redirect URI and any problem. Writes nothing. |
| `GET/PATCH settings/` | `IsAdmin` (GET also `IsStandardUser`, fields public) | `auth_settings`: `public_base_url`, `password_login_enabled`. PATCH runs the § 5.5 guard (from S4; before S4, turning passwords off is refused outright). |
| `GET/DELETE identities/?user=<id>`, `identities/<id>/` | `IsAdmin` | List and unlink a user's SSO identities. |

The `oidc` throttle is a new DRF scope at `20/minute` per IP, using `LoginRateThrottle`'s trusted-proxy `get_ident` (`apps/accounts/throttling.py:8-22`). It is not the shared `login` scope, because one SSO login costs three requests against `login`'s 3/minute.

nginx needs no change: everything sits under `^~ /api/` (`docker/nginx.conf:177-179`). The SPA route `/login/sso` falls through to `location /`.

Every response from `start`, `link/start`, `callback` and `exchange` carries `Referrer-Policy: no-referrer` and `Cache-Control: no-store`.

### 3.2 Start

1. Load the provider by `slug`. 404 if it is absent or disabled. 409 `{"code": "sso_not_configured"}` if `auth_settings.public_base_url` is unset.
2. Validate `next`: it must start with a single `/`, must not start with `//` or `/\`, and must contain no `\`, scheme or control character, with a 512-character maximum. Anything else becomes `/`. Never use an absolute URL.
3. Generate `state` (32 random bytes, base64url), `nonce` (32 bytes) and `code_verifier` (64 bytes base64url, RFC 7636 §4.1), plus `binding` (32 bytes).
4. Write the transaction to Redis at `oidc:tx:<state>`, TTL 600 s, value `{provider_id, provider_version, nonce, code_verifier, binding_hash: sha256(binding), next, intent, link_user_id, created}`. On `GET start`, `intent` is always `login` and `link_user_id` is null. Only `POST link/start` writes `intent=link`, with `link_user_id = request.user.id` taken from the authenticated caller, never from a parameter.
5. Set the cookie `mino_oidc_tx=<binding>`: `HttpOnly`, `SameSite=Lax`, `Path=/api/accounts/oidc/`, `Max-Age=600`, and `Secure` when `public_base_url` is https. `Lax` is required: the callback is a top-level cross-site GET navigation from the IdP, and `Strict` would drop the cookie. For `link/start`, the cookie is set on the authenticated, same-origin `fetch` response. The binding, and therefore the link, exists only in the browser of the user who asked to link.
6. `GET start` answers with a 302, and `POST link/start` with `200 {authorize_url}`. Both point at the discovered `authorization_endpoint` with:
   - `response_type=code`, `client_id`, `redirect_uri=<public_base_url>/api/accounts/oidc/<slug>/callback/`, `scope`, `state`, `nonce`
   - `code_challenge=BASE64URL(SHA256(code_verifier))`, `code_challenge_method=S256`
   - `prompt=select_account` if the provider sets `prompt_select_account`

### 3.3 Callback

Each check refuses with a 302 to `<public_base_url>/login?sso_error=<code>`, a fixed vocabulary that names no claim value, and a `login_failed` event (§ 7). Checks run in this order:

1. If an `error` parameter is present, `GETDEL` the transaction named by `state` (if any), and the result is `idp_error`. Only the `error` value is recorded, and only when it is one of RFC 6749 §4.1.2.1's fixed codes; any other value is recorded as `other`. `error_description` and `error_uri` are never logged or stored.
2. Fetch and delete `oidc:tx:<state>` in one step: Redis `GETDEL` through the project's Redis client, falling back to a Lua get-and-delete. A missing transaction is `state_invalid`. Single use is what stops replay.
3. `sha256(cookie mino_oidc_tx)` must equal `binding_hash`, compared with `hmac.compare_digest`. A mismatch or missing cookie is `binding_invalid`. **This is the login-CSRF defence.**
4. The transaction's `provider_id` must equal the URL slug's provider, and `provider_version` must equal the row's current version. Otherwise the result is `provider_mismatch`, the mix-up defence (D5).
5. If discovery has `authorization_response_iss_parameter_supported: true`, the `iss` parameter must be present and equal the provider's issuer (RFC 9207). If the parameter is present when not advertised, it must still match. Otherwise `issuer_mismatch`.
6. POST the token endpoint with `grant_type=authorization_code`, `code`, `redirect_uri` (identical string) and `code_verifier`. Authenticate the client with `client_secret_basic` (default) or `client_secret_post` (per provider). Timeouts are 5 s connect and 10 s read, `allow_redirects=False`, with a 1 MiB response cap. A non-200 or a missing `id_token` is `token_exchange_failed`.
7. Validate the ID token (§ 3.4). A failure is `id_token_invalid`.
8. Resolve the identity and the level (§ 4). The results are `no_mapping`, `inactive`, `groups_overage` or `link_conflict`.
9. Mint: `refresh = RefreshToken.for_user(user)`, then set four claims, all of which survive refresh (§ 1):
   - `refresh["auth_method"] = "oidc"`
   - `refresh["oidc_provider"] = provider.id`
   - `refresh["oidc_provider_version"] = provider.version`
   - `refresh["oidc_redirect"] = sha256_hex(redirect_uri)`, the exact `redirect_uri` string sent in step 6, which is built from `public_base_url` and `slug`

   Update `last_login`.
10. Store the handoff at `oidc:handoff:<code>`, where `code` is 32 random bytes. TTL 60 s, value `{access, refresh, binding_hash, next, intent}`.
11. Re-set `mino_oidc_tx` with the same binding and `Max-Age=120`. 302 to `<public_base_url>/login/sso#code=<code>`. A fragment is never sent to a server, a proxy log or a `Referer` header.

**Request logs and the callback query.** The callback URL's query carries `code` and `state`. Two server-side logs can record it:

- uWSGI's `%(uri)` request log (`docker/uwsgi.ini:58-69`, `uwsgi.dev.ini:42-53`, `uwsgi.debug.ini:89`). In dev and debug it logs every request. Outside them, `--disable-logging` (`docker/entrypoint.sh:213-218`) reduces it to the lines `log-4xx`/`log-5xx` keep. A successful callback answers 302 and is not logged. A callback refused **before the view runs** is logged: a 403 from the UI network ACL, a 429 from the `oidc` throttle, or a 5xx.
- nginx's inherited default access log (`docker/nginx.conf` sets no `access_log`), which records every request.

The logged URL may therefore carry a `state` that was **never consumed** (an ACL or throttle refusal, or a failure before step 2) and a `code` that was **never redeemed**. On the `error` branch it carries no `code`, and step 1 also deletes the transaction (`GETDEL`) before redirecting. What a reader of those logs can do with the values:

- **A `state`** completes nothing without the browser's `mino_oidc_tx` binding cookie (step 3). The cookie is HttpOnly and never logged, and the transaction expires 600 s after `start` whether or not it was consumed.
- **A `code`** can be redeemed only with the `code_verifier`, which exists only in the Redis transaction and is never sent to the browser or logged, and with the client secret (§ 5.2). It is single use at the IdP and short-lived there.

This residual is accepted and recorded, rather than reworking the global log format, which also governs every XC path. **It is the one exception to § 7's guarantee, and it is scoped to these two request logs and to `code` and `state` only.** No secret that completes a flow appears in any URL. Two things that would be worse are designed out:

- The link flow puts no secret in any URL (§ 4.2).
- The handoff code travels only in a fragment.

`SENSITIVE_QUERY_KEYS` (`dispatcharr/utils.py:63`) gains `code`, `state`, `session_state`, `id_token`, `access_token`, `refresh_token`, `client_secret` and `code_verifier`, so any Django log line that runs a URL through `redact_url` masks them.

Exceptions from the token and discovery requests are logged by class name and HTTP status only, never `str(exc)` and never a response body. This is the exception-derived gap that `scripts/check_credential_logging.py:95-98` says the checker cannot see.

### 3.3a Exchange

`POST exchange/` with body `{code}`:

1. Fetch and delete `oidc:handoff:<code>` atomically with `GETDEL`, the same primitive as § 3.3 step 2. If nothing is there (wrong code, already used, or past its 60 s TTL), answer 400 `{"code": "handoff_invalid"}`. Because it is `GETDEL`, two concurrent exchanges of one code cannot both succeed.
2. `sha256(cookie mino_oidc_tx)` must equal the stored `binding_hash` (`hmac.compare_digest`). Otherwise answer 400 `{"code": "handoff_invalid"}`. The handoff is consumed either way, so a stolen code is worth one failed attempt.
3. Re-validate `next` with § 3.2 step 2's function.
4. Answer `200 {"access", "refresh", "next", "intent"}` (`intent` is `login` or `link`). Set `Cache-Control: no-store`, `Pragma: no-cache` and `Referrer-Policy: no-referrer`, and delete `mino_oidc_tx` with `Max-Age=0` and the same `Path`.

### 3.4 ID token validation (OIDC Core 1.0 §3.1.3.7)

The call is `jwt.decode(id_token, key, algorithms=[provider.id_token_alg], audience=provider.client_id, issuer=provider.issuer, leeway=60, options={"require": ["iss","sub","aud","exp","iat","nonce"]})`, with:

- The key is selected from the cached `PyJWKSet` by the header `kid`. An unknown `kid` triggers one JWKS refetch, with a 60 s per-provider cooldown key, and then refuses.
- `id_token_alg` defaults to `RS256` and is restricted to `{RS256, RS384, RS512, PS256, PS384, PS512, ES256, ES384, EdDSA}`. `none` and every `HS*` are refused at save time and at validation. An HMAC ID token would be keyed by the client secret, which is a key-confusion hazard.
- `azp`, whenever it is present, must be a string equal to `client_id`, whatever the shape of `aud`: a scalar, a one-element list or several entries. If `aud` has more than one entry, `azp` must also be present. A present `azp` that is not a string, or that differs from `client_id`, is refused (OIDC Core §3.1.3.7, items 4-5).
- `nonce` must equal the transaction nonce (`hmac.compare_digest`).
- Entra preset: `tid` must equal the configured tenant GUID, and `iss` must equal `https://login.microsoftonline.com/<tid>/v2.0` exactly. With a tenant-specific discovery document, the exact `iss` match "is all that is needed" (https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens, § Validate the issuer). The `tid` check is defence in depth.
- `c_hash` and `at_hash` are not checked. Entra documents that `c_hash` "isn't returned on ID tokens from the /token endpoint" (id-token-claims-reference), and the code-flow token-endpoint response is TLS-protected.

### 3.5 Discovery and JWKS fetching and caching

- Discovery is fetched from `<issuer>/.well-known/openid-configuration`. Its `issuer` must equal the configured issuer exactly (OIDC Discovery §4.3), and `authorization_endpoint`, `token_endpoint` and `jwks_uri` must be present.
- The configured issuer, and every discovered endpoint, must be `https`, unless the env var `MINO_OIDC_ALLOW_HTTP=1` is set. That is a deployment-level switch the e2e stack uses, and it is not a DB setting, so it cannot be enabled from the web.
- Both documents are cached in the Django cache (Redis, shared by every process): `oidc:disco:<provider_id>:<version>` and `oidc:jwks:<provider_id>:<version>`, TTL 3600 s. Every security-relevant provider edit bumps `version` (§ 5.1), so an edit is never served a stale document. Entra recommends checking for key updates about every 24 h; an hour is stricter.
- Fetches use `requests` with 5 s connect and 10 s read timeouts, `allow_redirects=False`, a 1 MiB cap and default TLS verification. Under the API's gevent monkey-patching these are cooperative. They happen only on `start`, `callback` and the admin `test` action, never on an ordinary API request.

### 3.6 Entra preset specifics

- **Fields.** Tenant id (a GUID; `common`, `organizations`, `consumers` and domain names are refused), client id, client secret and display name. The issuer is derived as `https://login.microsoftonline.com/<tenant>/v2.0`, and discovery as `<issuer>/.well-known/openid-configuration`.
- **Why single tenant.** The multi-tenant endpoints return the templated issuer `https://login.microsoftonline.com/{tenantid}/v2.0`. Validating it requires substituting `tid`, checking it is a GUID, and checking the signing key's own `issuer` property (access-tokens page, § Multitenant applications and § Validate the signing key issuer). That is a known pitfall with no use for a homelab instance, so it is refused rather than half-implemented.
- **Default mapping claim: `roles`.** It is an array of app-role values ("the set of roles that were assigned to the user", id-token-claims-reference) and is emitted when app roles are defined on the registration and assigned. The admin UI text tells the owner to create app roles, for example `Mino.Admin` and `Mino.User`, and assign users or groups to them.
- **`groups` is allowed but discouraged.** A JWT carries at most 200 groups. Above that, the token carries `_claim_names: {"groups": "src1"}` with `_claim_sources`, or `hasgroups: true`, instead of `groups` (id-token-claims-reference, § Groups overage claim). When the mapping claim is `groups` and either marker is present, the login is refused with `groups_overage`. No Graph call is made (D15).
- **Identity claims.** `sub` is pairwise per application. That is fine because identities are keyed per provider. `oid` and `tid` are stored as display metadata only.
- **Never authorize on `email` or `preferred_username`.** Entra: email "isn't guaranteed to be correct and is mutable… Never use it for authorization", and preferred_username "can't be used to make authorization decisions" (id-token-claims-reference).

### 3.7 Generic provider

Fields: display name, slug, issuer URL, client id, client secret, client auth method, scopes (default `openid profile email`; must contain `openid`), ID-token alg, mapping claim path, mappings, `prompt_select_account` and enabled.

The mapping claim path is a dotted path into the ID token's claims. Each segment is a key, with no escaping and no wildcards. Keycloak's `realm_access.roles` is the motivating case. The value must be a string or a list of strings; any other type matches nothing. Claims are read from the ID token only. The UserInfo endpoint is not called, so a provider must be configured to put the mapping claim in the ID token. The admin UI says so.

## 4. Identity linking and provisioning

### 4.1 Model

`OIDCIdentity` (new, in `apps/accounts/models.py`):

- `user` FK, `on_delete=CASCADE`
- `provider` FK, `on_delete=PROTECT`
- `issuer`, `subject`
- `email_at_last_login`, `display_name`, `extra` (JSON: `tid`/`oid` for Entra)
- `created`, `last_login`

A unique constraint covers `(provider, issuer, subject)`. A provider with identities cannot be deleted (`PROTECT`); the admin disables it, or unlinks the identities first. While identities exist, the provider's **`issuer`, Entra tenant and `client_id`** cannot be changed. The save is refused with a message saying to create a new provider, then have each person link it (§ 4.2) or unlink and re-provision. Any of the three edits would silently JIT a duplicate user for every person: `sub` is scoped to the issuer, and Entra's `sub` is pairwise per application, so a new client id means new subjects.

### 4.2 Resolution on callback

Authorization is decided **before any write**. `ATOMIC_REQUESTS` is `False` (`dispatcharr/settings.py:162`), so the order is explicit:

1. **Level, computed with no DB write.** Evaluate the mapping, an ordered list of `{value, user_level}`, against the claim. The **highest** matched level wins. No match means refuse with `no_mapping`; nothing has been written and the stored level is left untouched. A groups overage is refused here too (§ 3.6). A refused login leaves no user, no identity and no changed row.
2. **One `transaction.atomic()` block** does everything below.
3. **Known identity.** `(provider, iss, sub)` exists, read with `select_for_update`. Use its user.
   - If `user.is_active` is false, refuse with `inactive`. SSO never reactivates a user.
   - With `intent=link`, the identity must belong to `link_user_id`. Otherwise refuse with `link_conflict`, before anything else is decided.
4. **Link intent, unknown identity.** Re-read `link_user_id` with `select_for_update`. Refuse with `inactive` if that user is gone or inactive. Otherwise create the identity for them.
   - The mapping still applies (step 6), so an admin who links an IdP account that maps to Standard is demoted. The UI warns about this before linking.
   - The link transaction exists only in the browser that called `POST link/start` with its own JWT (§ 3.2 steps 4-5).
5. **Unknown identity, login intent.** JIT-create the user:
   - Start from `preferred_username`, falling back to `email`, then `sub`.
   - Reduce it to the `SAFE_CREDENTIAL_RE` alphabet and truncate it to 150 characters. The username is a label only, never an identity key.
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
         identity = select_for_update the winner's identity; continue as step 3
     ```

     The identity conflict is caught **outside** the attempt savepoint, so rolling that savepoint back removes this attempt's user row. The winner lookup then runs inside the still-open outer transaction. Any other `IntegrityError` propagates, and the outer transaction rolls back.
   - **No email-based matching of an existing local user, ever.**
6. **Apply the level.** Set `user.user_level` from step 1 if it changed (D9). Commit.

SSO never writes `channel_profiles`, `stream_limit`, `custom_properties`, `api_key` or `is_active` after creation. Those stay local admin decisions.

### 4.3 Lifecycle consequences, stated for the owner

- **Mapping removed or role unassigned in the IdP.** The next SSO login is refused. An already-issued pair keeps working until its refresh token expires, at most 1 day (`SIMPLE_JWT`). An admin who needs it to stop now deactivates the local user: `JWTAuthentication` refuses inactive users (simplejwt 5.5.1 `authentication.py:138`), and so does refresh.
- **Role changed in the IdP.** Applied at the next SSO login, not mid-session.
- **Local user deleted.** The identity cascades, and the next SSO login JIT-creates a **new** user with a new id and no history. To block a person, deactivate them; do not delete them. The Users page says this on the delete dialog for a user with linked identities.
- **Provider disabled.** Its start and callback 404, and its refresh tokens are refused (§ 5.4). Its users can still use the password, if they have one and password login is on.

## 5. Runtime configuration

### 5.1 Storage (D7)

- **`OIDCProvider`** (new, `apps/accounts/models.py`). Columns:
  - `slug` (unique, `[a-z0-9-]{1,40}`), `display_name`, `kind` (`generic` / `entra`), `enabled`
  - `issuer`, `entra_tenant_id`, `client_id`, `client_secret_encrypted` (text), `client_auth_method`
  - `scopes`, `id_token_alg`, `claim_path`, `mappings` (JSON list), `prompt_select_account`
  - `version` (int), `created`, `updated`

  `version` is bumped in the same transaction as any change to a **security-relevant** field: `enabled`, `issuer`, `entra_tenant_id`, `client_id`, the secret, `client_auth_method`, `scopes`, `id_token_alg`, `claim_path` or `mappings`. `slug` is security-relevant too, because it is part of the redirect URI: renaming it bumps `version`. Edits to `display_name` or `prompt_select_account` leave `version` alone. The version keys the discovery and JWKS caches (§ 3.5), the transaction check (§ 3.3 step 4) and the lockout proof (§ 5.5).

  `mappings` is validated as a list of `{value: non-empty str ≤ 256, user_level ∈ {0, 1, 10}}`, at most 50 entries, with no duplicate values.
- **`auth_settings`**, a new `CoreSettings` group (the ninth): `{"public_base_url": "", "password_login_enabled": true}`. A data migration seeds it, so PATCH works on a fresh instance. Contrast `epg_settings`, which has no seeding migration (CLAUDE.md § State).
- **Every security decision reads `auth_settings` fresh from Postgres**, through `CoreSettings._load_group_value` (`core/models.py:385-393`), never through the Redis group cache in `_get_group` (`:397-435`). That covers the login gate, the refresh gate, the admin-login gate, the `me` password rule and the guard. The cache's version check and fill are not one atomic step, and its invalidation runs in `post_save` (`core/signals.py:11-15`) rather than `on_commit`, so a racing reader can repopulate a stale value for up to `_GROUP_CACHE_TTL_SECONDS` (300 s, `core/models.py:242`). These reads happen on login, refresh and settings writes only, a handful per user per 30 minutes, so the cache buys nothing here. `CoreSettings.get_auth_settings()` is defined as this fresh read.
- **`CoreSettingsViewSet` refuses `auth_settings` in every direction**, with 400 `{"code": "use_auth_settings_endpoint"}`. The check runs at the top of `update`, `create` and `destroy`, **before** the serializer validates. Otherwise a rename into the unique key (`core/models.py:291-294`) would answer with the serializer's uniqueness error instead, and the refusal could be removed without any test noticing. Refused requests:
  - `update` and `partial_update` when the stored key **or** the proposed `key` is `auth_settings`, which covers renaming into or out of it
  - `create` with that key
  - `destroy` of that row

  The viewset inherits `ModelViewSet.destroy` (`core/api_views.py:107-114`), and `CoreSettingsSerializer` exposes `key` as writable (`core/serializers.py:44-47`, `fields = "__all__"`). A deleted group falls back to its defaults (`core/models.py:390-391`), which would re-enable password login outside the guard. Reads through the generic endpoint stay allowed, since neither field is secret.
- **`public_base_url`.** It must be an absolute URL with no path beyond `/`, no query, no fragment and no userinfo. It is stored without a trailing slash. **It must be `https`**, with two exceptions:
  - the host is a loopback literal (`localhost`, `127.0.0.0/8`, `::1`), the dev and e2e case
  - the env var `MINO_OIDC_ALLOW_HTTP=1` is set (§ 3.5)

  Any other `http` value is refused with 400 `{"code": "public_base_url_insecure"}`. Over plain HTTP to a non-local host, the binding cookie would lose `Secure` and `exchange` would return both JWTs in cleartext. PKCE protects the IdP leg, not this one. **The URL is never derived from the request.** `ALLOWED_HOSTS=["*"]` (`settings.py:107`) makes `request.get_host()` attacker-controlled.

### 5.2 The client secret (D11)

- Stored as Fernet ciphertext. The key is `HKDF-SHA256(SECRET_KEY, salt=None, info=b"mino-oidc-client-secret")`. `cryptography` is already locked.
- The API serializer field is `write_only`. Responses carry `client_secret_set: bool` instead. A PATCH without the field keeps the stored value. An empty string is refused, not taken to mean "clear".
- If decryption fails (`SECRET_KEY` changed, for example a backup restored onto a new instance, § 1), the provider reports `secret_unreadable` in the admin list and `test` action. Its logins fail closed with `token_exchange_failed`, and the admin re-enters the secret.
- Why encrypt when `xc_password` is plaintext: a provider secret can mint sessions for the whole tenant app. A DB dump or a published Postgres port (CLAUDE.md § Known defects: `5436:5432`) should not hand it over. This does not fix `xc_password`, which is out of scope.

### 5.3 What "password login disabled" disables

When `password_login_enabled` is false and the break-glass is not active:

| Surface | Behaviour |
|---|---|
| `POST /api/accounts/token/` and `POST /api/accounts/auth/login/` | 403 `{"code": "password_login_disabled"}`, plus a `login_failed` event with reason `password_login_disabled` |
| `POST /api/accounts/token/refresh/` | refused (401 `token_not_valid`) unless the refresh token carries `auth_method == "oidc"` and its `oidc_provider` is an enabled provider (D13). A stale **password** pair in a browser is why the SPA runs the SSO handoff before refreshing (§ 5.7). |
| Django admin `POST /admin/login/` | 403, added inside the existing wrapper at `apps/accounts/admin.py:30-35`. nginx already blocks `/admin` outside dev. |
| `PATCH /api/accounts/users/me/` with `password` | refused for every user. When password login is on, refused only for users without a usable password (§ 5.4). |
| `POST /api/accounts/initialize-superuser/` | unchanged: bootstrap only, and closed once any admin exists |
| API keys (`X-API-Key`, `Authorization: ApiKey`) | unchanged, keep working |
| XC, M3U, EPG, HDHomeRun and stream credentials | unchanged |
| Existing access tokens | valid until expiry, at most 30 minutes |
| `manage.py changepassword` / `createsuperuser` | unchanged (CLI) |
| Login page | the password form is hidden, and SSO buttons are shown |

### 5.4 Refresh and password rules that hold regardless of the toggle

- A refresh token with `auth_method == "oidc"` is refused when its provider is disabled or deleted.
- `PATCH users/me/` refuses `password` for a user whose `has_usable_password()` is false. An SSO-only user cannot give themselves a password path that bypasses the IdP. An admin can still set a password for that user through `PATCH users/<id>/`, a deliberate local decision.

### 5.5 The lockout guard (D12)

The guard proves a **current** working admin sign-in path, not a historical one.

**Proof.** The acting request's validated access token carries:

- `auth_method == "oidc"`
- an `oidc_provider` P, and an `oidc_provider_version` equal to P's version **in the proposed state**
- an `oidc_redirect` equal to `sha256_hex` of P's redirect URI **in the proposed state**, built from the proposed `public_base_url` and P's proposed `slug`

P must also be `enabled` and its secret must decrypt. "Proposed state" means the stored rows with the request's own changes applied: the guard evaluates the complete state the write would commit, under the locks below. `IsAdmin` gates every guarded endpoint, so the proof says that this admin signed in through P, as P and its redirect URI will be configured after the write, and P mapped them to Admin.

- Any security-relevant edit to P since that sign-in bumps its version (§ 5.1), and so voids the proof. That includes a slug rename.
- Any `public_base_url` change since that sign-in changes the redirect URI, and so voids the proof. That includes a change made earlier while password login was on.
- An API-key caller has no token claims, so it never holds a proof.

**Guarded writes.** Each of these is refused with 409 `{"code": "lockout_guard", "reasons": [...]}` unless the condition holds:

1. `PATCH settings/` to `password_login_enabled: false` requires a proof, and `public_base_url` must be set.
2. While password login is off, a provider write that bumps an enabled provider's `version`, disables it or deletes it requires a proof from a provider **other than** the one being written. With a single provider, the admin turns password login on (or uses break-glass), edits, signs in again through SSO, and turns it off again.
3. While password login is off, `PATCH settings/` changing `public_base_url` is refused outright. No current proof can match a redirect URI that no one has signed in through yet. A combined PATCH that changes `public_base_url` **and** turns password login off fails rule 1 for the same reason: the proposed redirect URI does not match the proof.

**Serialization.** Each guarded write runs in `transaction.atomic()`. It first takes `select_for_update()` on the `auth_settings` `CoreSettings` row, then on every `OIDCProvider` row, in id order. Only then does it evaluate the guard and write. Two concurrent disables therefore cannot each see the other's provider still enabled.

**Tests (S4):**

- **Stale proof.** Sign in via P, edit P's mapping, then disable password login: 409.
- **Slug rename while off.** With password login off and P the only provider, rename P's slug: 409.
- **Base URL changed, then disable.** With password login on, sign in via P, change `public_base_url`, then disable password login: 409.
- **Combined PATCH.** `{public_base_url: <new>, password_login_enabled: false}` with an otherwise valid proof: 409, and neither field changes.
- **Unusable remaining provider.** With password off, disable P while the only other enabled provider Q has never been proven: 409.
- **Concurrent disables.** Password is off, with two enabled providers. A `TransactionTestCase` runs two threads, each disabling a different provider and each holding a proof from the other's provider. Exactly one must succeed. The interleaving is forced deterministically: the test wraps the guard-evaluation function so each thread waits on a `threading.Barrier(2, timeout=2)` **after** reading and **before** writing, and the wrapper swallows `BrokenBarrierError`.
  - With the row lock, the second thread blocks in `select_for_update()` before it reaches the barrier. The first thread's wait times out, it commits, and the second then sees one enabled provider and gets 409.
  - Without the lock, both threads pass the barrier and both commit.

### 5.6 Break-glass (R3, D14)

- **`MINO_PASSWORD_LOGIN_FORCE=1`** (exactly `1`; any other value is ignored with one WARNING at boot) makes password login enabled regardless of the DB. It is read once at settings import into `settings.PASSWORD_LOGIN_FORCE`. Precedence: **env on ⇒ enabled; else the DB value.** While it is on:
  - `providers/` reports `password_login_forced: true`, and the login page and the SSO settings panel show a banner.
  - Every password login writes `login_success` with `break_glass: true`.
  - D13's refresh refusal is off.

  Setting it means editing the deployment's environment and restarting, which is not reachable from the web.
- **`manage.py password_login --enable | --disable | --status`** writes `auth_settings.password_login_enabled` through `CoreSettings._update_group`, inside the same locking transaction as § 5.5. Every gate reads the row fresh (§ 5.1), so the change is live at the next request with no restart. `--disable` requires an enabled provider whose secret decrypts, plus a set `public_base_url`. It cannot require the § 5.5 proof, because the CLI has no SSO session, and `--force` overrides both checks. `--status` prints the DB value, the env override and the enabled providers. A management command has no URL, and nothing in the web tier invokes it.
- Neither can be set by the UI, the REST API or a `CoreSettings` write. A test asserts that the generic settings endpoint and `PATCH settings/` cannot change `settings.PASSWORD_LOGIN_FORCE`.

`docs/` gains an operator page with the two paste-ready commands, `docker exec <container> python manage.py password_login --enable` and the env line, and the `LoginForm` "Forgot password" text points to it.

### 5.7 Frontend

- **`frontend/src/api.js`**: `getAuthConfig()` (`GET providers/`), `exchangeSsoCode(code)`, `startSsoLink(slug, next)` (`POST <slug>/link/start/`, returns `authorize_url`), and admin CRUD for providers, auth settings and identities. All HTTP stays in `api.js`. **`getAuthConfig` and `exchangeSsoCode` pass `auth: false` to `request()`.** By default `request()` first calls `API.getAuthToken()` (`api.js:51-56`, `:92-94`). That refreshes an expired token (`store/auth.jsx:168-174`), and a refused refresh hard-navigates to `/login` (`api.js:211-216`). A stale password pair would therefore abort the very exchange meant to replace it. `fetch`'s default `credentials: 'same-origin'` still sends the `mino_oidc_tx` cookie, which is all the exchange needs.
- **`frontend/src/store/auth.jsx`**: `loginWithTokens({access, refresh})`, factored out of `login()` (`:177-197`) so the password and SSO paths store tokens identically. It **replaces** any stored pair and resets `isInitialized`/`isInitializing` to false, so the next `initData` reloads `user` (`initData` skips an initialized session, `:98-102`). Also `authConfig` state, and `completeSsoHandoff()` (below).
- **`pages/Login.jsx`**: after the superuser check, fetch `authConfig`. Render one button per provider, plus `LoginForm` only when `password_login_enabled`. The SSO button sets `window.location.href = /api/accounts/oidc/<slug>/start/?next=<current intended path>`, a top-level navigation, never fetch or XHR. Show the `?sso_error=` code as fixed copy.
- **The handoff runs before authentication bootstrap, not as a route.** On mount, `App.jsx`'s auth effect (`:83-104`) refreshes the stored token or logs out. The route table (`:150-182`) sends an authenticated user away from any unknown path, and only unauthenticated users have `/login`. A `/login/sso` route alone would therefore be bypassed in the authenticated link case. It would also lose to a stale password refresh token: `api.js:204-216` hard-navigates to `/login` on a refused refresh, which is exactly what D13 produces after password login is switched off. So `checkAuth` in `App.jsx` gains a first step:

  > If `location.pathname === '/login/sso'`, `await completeSsoHandoff()` **before** `initializeAuth()`. That reads the `#code=` value and immediately runs `history.replaceState` to drop the hash, then calls `exchangeSsoCode`, then `loginWithTokens`, and records `next`. On success the stale pair has already been replaced, so the `initializeAuth()`/`initData()` that follow run on the new SSO tokens. `checkAuth` then navigates to `next`, or to `/users` with a "linked" notice when `intent === 'link'`. On failure it clears the stored tokens and navigates to `/login?sso_error=exchange_failed`.

  `/login/sso` is also listed in **both** branches of the route table, rendering a loader, so neither branch redirects away while the handoff runs.
- **Linking** is a `POST` through `startSsoLink`, then `window.location.assign(authorize_url)`. It is never a GET link carrying a secret.
- **Settings**: a new admin-only "Single sign-on" section in `frontend/src/config/settingsNav.js`, covering:
  - `public_base_url`
  - the provider list
  - a provider form with Generic and Entra variants, showing the computed redirect URI read-only with a copy button
  - the mapping table, the "Test" button, and the password-login toggle, whose 409 reasons render inline
- **Users page**: a user's linked identities with Unlink, and a "Link SSO account" action on the current user's own profile.
- `data-testid`s are registered per ADR 0003 for every new surface the e2e project selects.

## 6. Out of scope (D15)

- Xtream, M3U, EPG, HDHomeRun and stream credentials, and `xc_password` storage.
- Phase 4c paired-device auth (`docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md`, the 4c brief). Nothing here pre-empts its design. The Mino app keeps its own auth path.
- SAML, SCIM and any provisioning push; deprovisioning happens at the next login (§ 4.3).
- **RP-initiated logout and front- and back-channel logout: out.** The SPA's logout clears its tokens and records the event, as now. The IdP session survives, so the next SSO click may sign in silently. `prompt_select_account` is the per-provider mitigation.
- Microsoft Graph calls (groups overage), multi-tenant Entra, guest-account policy beyond "a guest is a new identity in this tenant", and the UserInfo endpoint.
- Token revocation and blacklisting (simplejwt `token_blacklist` stays uninstalled).
- Fixing `ALLOWED_HOSTS`, CORS or CSRF wildcards. This spec only avoids depending on them.
- Making `login_success` and `logout` subscribable in Connect.

## 7. Events and logging

- **Success**: `log_system_event('login_success', user=<username>, client_ip=…, user_agent=…, method='oidc', provider=<slug>)`.
- **Failure**: `login_failed`, with `user` set to `'sso'` (or the resolved username when one exists) and `reason` taken from the fixed vocabulary of § 3.3 plus `provider=<slug>`.
- **Link and unlink**: `login_success`, with `method='oidc_link'` or `'oidc_unlink'` and `admin=<username>`.
- **Settings changes**: this spec adds no event for provider or settings writes. A new event type is a scope decision for the owner (Q4).

No event payload and no **application** log line (Django's `logging`, any logger) ever carries `code`, `state`, `nonce`, `code_verifier`, the binding, an ID token, an access token, a refresh token, the client secret, a raw claim set or `sub`. Failure reasons name the check, never the value. The uWSGI and nginx request logs are outside this guarantee, for the callback's `code` and `state` only. § 3.3 states that residual and why it is accepted.

## 8. Security review

| # | Threat | Defence | Test (PR) |
|---|---|---|---|
| T1 | Open redirect via `next` | § 3.2 step 2 allowlist (relative path only) | `//evil`, `/\evil`, `https://evil`, `%2F%2Fevil` and a control character all become `/` (S2) |
| T2 | Open redirect or host poisoning via the `Host` header | `public_base_url` only (D6) | a request with `Host: evil.example` produces `redirect_uri` and a final Location on the configured base (S2) |
| T3 | Login CSRF (the victim is logged in as the attacker) | tx binding cookie (§ 3.3 step 3) and handoff bound to the same binding | callback with valid state but no or a wrong cookie → `binding_invalid`; exchange with another browser's code → 400 (S2) |
| T3a | Account-linking CSRF (the victim's IdP identity is attached to the attacker's account) | link only via authenticated `POST link/start`, binding cookie set in the caller's browser, no link secret in any URL, `GET start` can never link (§ 3.1, § 3.2) | two clients: the attacker calls `link/start` and hands its `authorize_url` to the victim client, whose IdP identity maps to Admin; the victim's callback → `binding_invalid`, no `OIDCIdentity` is created and the attacker's `user_level` is unchanged; `GET start?intent=link` writes `intent=login` (S2) |
| T4 | State replay | `GETDEL`, single use | a second callback with the same state → `state_invalid` (S2) |
| T5 | Authorization code injection or interception | PKCE S256, verifier server-side only | the token request body carries `code_verifier` matching the stored challenge, and the fake IdP refuses a wrong verifier (S2 unit, S5 e2e) |
| T6 | ID-token substitution or replay | `nonce` bound to the transaction, `aud`/`azp`, `exp`/`iat` with 60 s leeway | per-claim negative tests: wrong nonce, wrong aud, multi-aud without azp, a mismatching `azp` with a scalar `aud` and with a one-element list `aud`, a non-string `azp`, expired, iat in the future (S2) |
| T7 | Signature bypass | `algorithms=[configured]`, `none`/`HS*` refused, `kid` must resolve | `alg=none` token, HS256 token signed with the client secret, unknown kid after one refetch, and **a token with a JWKS-listed `kid` but signed by a different RSA key** (S2) |
| T8 | Mix-up across providers | per-provider redirect URI, tx bound to provider and version, RFC 9207 `iss` | callback for provider B with a transaction from A → `provider_mismatch`; advertised `iss` param absent or wrong → `issuer_mismatch` (S2) |
| T9 | Entra multi-tenant issuer pitfall | single tenant only (D10), exact `iss`, `tid` check | the preset refuses `common`/`organizations` (S1); at runtime, three correctly-signed tokens are refused (S2): correct `iss` with another `tid`; another tenant's `iss` with the configured `tid`; a missing `tid` |
| T10 | Account takeover by email | identity keyed on (provider, iss, sub), no email matching | a JIT login whose email equals an existing admin's email creates a **new** Standard user and does not touch the admin (S2) |
| T11 | Privilege retained after an IdP change | level recomputed on each login, refusal on no match | login 1 maps Admin, login 2 maps Standard → level 1; login 3 no match → refused and level unchanged (S2) |
| T12 | Self-service password bypassing the IdP | § 5.4 | SSO-only user `PATCH me {password}` → 400 (S4) |
| T13 | Lockout | D12 guard, last-provider guard, break-glass | each guard reason individually yields 409; env force re-enables; command `--enable` re-enables live (S4) |
| T14 | Guard bypass through the generic settings endpoint | refusal of `auth_settings` in `CoreSettingsViewSet`, every direction, before serializer validation (§ 5.1) | `core.tests.test_auth_settings_guard.AuthSettingsGenericEndpointTests`, each case asserting the exact body `{"code": "use_auth_settings_endpoint"}`, not just the status. On `/api/core/settings/`: `PATCH`, `PUT` and `DELETE` of the `auth_settings` row; `POST` with that key; `PATCH` renaming the `auth_settings` row to another key; `PATCH` renaming another row to `auth_settings`. All → 400, and the row is unchanged (S1) |
| T15 | Client secret disclosure | write-only field, encrypted at rest, not in `CoreSettings` | GET list/detail never contains the secret or ciphertext; a Standard user's `GET /api/core/settings/` lacks it; DB column ≠ plaintext (S1) |
| T16 | Credential logging | `CREDENTIAL_RE` extended with `client_secret`, `id_token`, `access_token`, `refresh_token`, `code_verifier` and `\bnonce\b`; `SENSITIVE_QUERY_KEYS` extended (§ 3.3); exceptions logged by class only; `error_description` never logged; request-log residual documented (§ 3.3) | `tests/test_credential_logging_guard.py` gains a case per name; `tests/test_redaction.py` gains `redact_url` cases for each new query key; with distinctive sentinel values for code, state, secret, ID token and tokens, root-logger capture at DEBUG over a happy callback, a token endpoint 500, a token endpoint connection error, and an IdP `error=access_denied&error_description=<sentinel>` finds no sentinel (S2) |
| T17 | Secrets in SystemEvent and Connect payloads | § 7 field whitelist | after a success and each failure, every `SystemEvent.details` JSON is searched for the code, state, ID token, tokens and secret, and none is present (S2) |
| T18 | Ambient session principal on streaming surfaces | D3: no `login()` | after a completed callback, the response sets no `sessionid` cookie and no session row holds `_auth_user_id` (S2) |
| T19 | Token leakage via URL, and handoff replay | fragment handoff; `GETDEL` single use with a 60 s TTL; `no-store` (§ 3.3a) | the callback Location has `#code=`, never `?code=`; the exchange response shape is exactly `{access, refresh, next, intent}` with `Cache-Control: no-store` and the cookie deleted; a sequential second exchange → 400; **two concurrent exchanges** of one code (two threads, real Redis, barrier) → exactly one 200; an exchange after the TTL → 400 (S2) |
| T20 | Discovery or JWKS abuse (slow, huge, redirect) | timeouts, 1 MiB cap, no redirects, https-only unless env | an oversized body and a 302 from jwks_uri → refused with a clear admin `test` result (S2) |
| T21 | Brute force or DoS of the flow | `oidc` throttle 20/min per trusted-proxy IP; caches | the 21st start in a minute → 429 (S2) |
| T22 | Deactivated user regaining access via SSO | `is_active` check, SSO never reactivates | inactive linked user → `inactive`; link to a `link_user_id` deactivated between `link/start` and the callback → `inactive` (S2) |
| T23 | Credentials over cleartext | `public_base_url` must be https except loopback or `MINO_OIDC_ALLOW_HTTP` (§ 5.1) | `http://mino.example` → 400 `public_base_url_insecure`; `http://localhost:9191` → accepted; `http://mino.example` with `override_settings` for the env → accepted (S1) |
| T24 | Partial writes on refusal or a lost race | mapping decided before any write; one transaction; savepoints told apart by constraint (§ 4.2) | an unmapped first login leaves the `User` and `OIDCIdentity` counts unchanged; two concurrent first logins for one `sub` (`TransactionTestCase`, two threads, barrier) yield one user and one identity; **forced losing branch**: before the attempt, a second connection commits the winner's `OIDCIdentity` for the same `(provider, iss, sub)`, with the identity insert patched to wait on a barrier until that commit lands. The attempt ends logged in as the winner's user, and the `User` count rises by exactly one (the winner's); a username collision with an unrelated user yields `name-2`, not a refusal (S2) |

Out of the threat model: an admin who is already malicious (they can point a provider at their own IdP and map themselves to Admin, which they already are), and in-process plugins (unsandboxed by design, CLAUDE.md § Events and plugins).

## 9. PR breakdown

Five PRs in order. Each opens as a draft, gets a pinned review (`fable` from round one: security-adjacent), and lands with `Backend result` / `Frontend result` / `E2E result` green. Test labels: `apps.accounts.tests` (all backend here), `core.tests` (S1's `CoreSettings` refusal and the no-pending-migrations check), and `tests` (S2's credential-logging checker).

### S1: Models, settings group and admin API (no login yet)

**Changes:**

- `OIDCProvider` and `OIDCIdentity` models plus migration.
- A data migration seeding `auth_settings`, plus `AUTH_SETTINGS_KEY` and `CoreSettings.get_auth_settings()` beside the eight group keys at `core/models.py:227-234`.
- The `CoreSettingsViewSet` refusal for that key.
- `apps/accounts/oidc/secrets.py` (HKDF + Fernet).
- Serializers with the write-only secret and mapping validation.
- Entra preset validation (tenant GUID, derived issuer).
- `providers-admin/` CRUD and the `test/` action. Discovery and JWKS fetch live in `apps/accounts/oidc/discovery.py`, with § 3.5's limits.
- `settings/` GET and PATCH. **In S1, S2 and S3, `password_login_enabled: false` is refused unconditionally** with 409 `{"code": "password_toggle_unavailable"}`. The guard of § 5.5, the enforcement of § 5.3 and the break-glass land together in S4. No mergeable state between them can record "passwords off" while passwords still work. `public_base_url` is writable from S1, with § 5.1's https rule.
- `identities/` list and delete.
- CLAUDE.md § State: "eight groups" becomes "nine", naming `auth_settings`. The `e2e/tests/guards/global-mutation.spec.ts` header lists the ninth group.

**Tests:** model constraints; `issuer`, Entra tenant and `client_id` immutability with identities present, including changing an Entra `client_id` with a linked identity (400); `version` bumped by a mapping edit and not by a `display_name` edit; the unconditional `password_toggle_unavailable` refusal; T23; delete-PROTECT; secret round-trip and the unreadable-after-key-change path; no secret in any response; T14, T15; Entra refusals (T9 part); mapping validation; the `test` action against an in-process `http.server` thread serving discovery and JWKS (no network).

**Break-checks:**

- (a) Make `client_secret` a readable field. The T15 response test reddens, naming `client_secret`.
- (b) Check only the stored key in the `CoreSettingsViewSet` refusal, not the proposed one. `AuthSettingsGenericEndpointTests.test_rename_other_row_into_auth_settings_refused` reddens. The status is still 400, from the serializer's uniqueness error on `key`, but the body is that error rather than `{"code": "use_auth_settings_endpoint"}`, and the assertion on the body names the difference.
- (c) Accept `organizations` as a tenant. The preset test reddens.
- (d) Drop `client_id` from the immutable-with-identities set. The Entra `client_id` test reddens with a 200.

**Hooks:** `apps/accounts/models.py` and `core/models.py` (`makemigrations --check`); `*.py` (credential logging); `apps/accounts/tests/test_*.py` and `core/tests/test_*.py`.

**PR description draft:**

> Adds the storage and admin API for OIDC single sign-on, the first PR of the SSO spec
> (`docs/superpowers/specs/2026-10-31-sso-oidc-design.md`, PR S1; ADR 0011). New models
> `OIDCProvider` and `OIDCIdentity`, a seeded `auth_settings` settings group that the generic
> `/api/core/settings/` endpoint refuses to write, admin CRUD with a discovery/JWKS `test` action,
> and an Entra preset that accepts only a tenant GUID. Client secrets are encrypted at rest and
> never returned. No login flow yet, and password login cannot be switched off until PR S4
> lands the lockout guard together with its enforcement and break-glass.
> Tests: `apps.accounts.tests`, `core.tests`. Break-checks: a readable secret field, a removed
> settings refusal and an accepted `organizations` tenant each redden a named test.

### S2: The OIDC flow (backend)

**Changes:**

- `apps/accounts/oidc/flow.py` (start, link/start, callback, exchange; § 3.2-3.3a).
- `apps/accounts/oidc/validate.py` (§ 3.4).
- `apps/accounts/oidc/provisioning.py` (§ 4).
- The `oidc` throttle scope at `settings.py:343-345`.
- The `auth_method`/`oidc_provider`/`oidc_provider_version` claims, the `providers/` public endpoint, and § 5.4's first rule (refresh of an OIDC token refused when its provider is disabled or deleted).
- `SENSITIVE_QUERY_KEYS` extension (`dispatcharr/utils.py:63`), `Referrer-Policy`/`no-store` headers, and class-only exception logging (§ 3.3).
- The `CREDENTIAL_RE` extension (`scripts/check_credential_logging.py:111-113`) and its tests.
- § 7 events.

**Tests:** T1-T3a, T4-T8, T9 (runtime part), T10, T11, T16-T22, T24, all against an in-process fake OP: a `http.server` thread plus RSA and EC keys generated with `cryptography` in `setUpClass`, issuing tokens with PyJWT. The suite also covers:

- the happy path, end to end through the Django test client, including that the exchanged access token authenticates `GET /api/accounts/users/me/` **and** `_drf_user` in `apps/proxy/authorize.py` (the D2 claim that streaming needs nothing new);
- that all four custom claims (`auth_method`, `oidc_provider`, `oidc_provider_version`, `oidc_redirect`) survive `POST token/refresh/`;
- the concurrent JIT path and the username-collision path (T24).

**Break-checks:**

- (a) Delete the binding comparison. The T3 test reddens with `binding_invalid` expected and a 302 to `/login/sso` received.
- (b) Pass `options={"verify_signature": False}` to `jwt.decode`. The T7 "JWKS-listed `kid`, different RSA key" test reddens: it expects `sso_error=id_token_invalid` and gets a 302 to `/login/sso`. A wrong-key token is the one that isolates signature verification; `alg` and `kid` are both valid in it.
- (b2) Choose the verification key by the token header's `alg`: for `HS*`, use the decrypted client secret as an HMAC key, and pass `algorithms=[header alg]`. The T7 HS256 test reddens the same way. This is the key-confusion mechanism that test exists for; appending `HS256` to the list alone would not redden it, because PyJWT will not use an RSA public key as an HMAC secret.
- (b3) Check `azp` only when `aud` has more than one entry. T6's scalar-`aud` mismatching-`azp` test reddens.
- (b4) Drop the Entra `tid` comparison. T9's "correct `iss`, other `tid`" runtime test reddens.
- (f) Move the JIT user insert **out of the transaction**, before the mapping is evaluated: a bare `User.objects.create(...)` ahead of step 1, outside `transaction.atomic()`. `apps.accounts.tests.test_oidc_provisioning.ProvisioningAtomicityTests.test_unmapped_first_login_writes_nothing` reddens on a `User` count of N+1. Merely reordering statements inside the atomic block would not leave a row after the refusal's rollback, which is why the break moves the insert outside it.
- (f2) Move the `except IntegrityError` for the identity constraint **inside** the attempt savepoint, so the savepoint commits the user before the conflict is handled. T24's forced-losing-branch test (`ProvisioningAtomicityTests.test_losing_identity_insert_leaves_no_orphan_user`) reddens on a `User` count rise of two.
- (g) In the callback, skip the binding comparison (step 3) when the transaction's `intent` is `link`. `apps.accounts.tests.test_oidc_flow.LinkCsrfTests.test_forwarded_link_authorize_url_does_not_link` reddens, asserting `OIDCIdentity.objects.filter(user=attacker).exists()` is false and finding it true. That test uses two Django test clients: the attacker client calls `POST link/start` and receives `authorize_url` and its own binding cookie; the victim client, holding a different binding cookie from its own `GET start`, drives the fake OP and the callback with the attacker's `state`. The path is fully exercised. Break-check (a), which removes the comparison for every intent, is caught by T3 instead.
- (c) Look up an existing user by email before JIT. The T10 test reddens, naming the admin's id.
- (d) Call `django.contrib.auth.login(request, user)` in the callback. The T18 test reddens on the `sessionid` cookie.
- (e) Skip the `provider_id` check. The T8 test reddens.

**PR description draft:**

> Adds the OIDC authorization-code + PKCE flow (spec PR S2; ADR 0011): per-provider start and
> callback routes, ID-token validation on PyJWT against cached discovery and JWKS, identity
> linking on (provider, issuer, subject) with just-in-time users and a claim → user_level mapping
> that refuses unmapped logins, and a one-time fragment handoff that gives the SPA the same
> simplejwt pair a password login does — so the player, recordings, VOD, catch-up and the
> WebSocket need no change. No Django session is created. The credential-logging check now
> recognises OIDC secrets. Backend only; the UI is PR S3.
> Tests: `apps.accounts.tests`, `tests`. Break-checks listed in the spec's S2 section.

### S3: Frontend login and settings UI

**Changes:** § 5.7. New `data-testid`s are registered.

**Tests (vitest):**

- The login page renders provider buttons from a mocked `getAuthConfig`, and hides the password form when it is disabled.
- `completeSsoHandoff`: strips the hash before the exchange request, calls `loginWithTokens` with the response, and maps a failure to `sso_error`.
- **Through the real wrapper.** With `localStorage` holding an expired access token and a refresh token, mock only `globalThis.fetch`, not `api.js`, so that `POST token/refresh/` would answer 401. Run `completeSsoHandoff`. The first `fetch` call is `POST /api/accounts/oidc/exchange/` with no `Authorization` header. No `token/refresh/` call is made, and `window.location.href` is never set to `/login`. Repeat for `getAuthConfig`.
- **Ordering under a stale pair.** The `App` auth effect, with `/login/sso#code=x` and a stale password refresh token in `localStorage` whose refresh the mock answers 401, calls `exchangeSsoCode` **before** any `refreshToken`, never navigates to `/login`, and finishes with the new pair stored.
- **Authenticated linking.** With an already-initialized session, a handoff with `intent: 'link'` replaces the pair, resets `isInitialized`, and re-runs `initData`, so `user` is reloaded.
- `loginWithTokens` writes the same three `localStorage` keys `login()` writes.
- The settings form never sends `client_secret` when the field is untouched, and renders 409 `lockout_guard` reasons.
- The Entra form computes and shows the redirect URI from `public_base_url` and the slug.

**Break-checks:**

- (a) Drop `history.replaceState`. The hash-strip test reddens.
- (b) Send `client_secret: ''` on an untouched field. The settings-form test reddens.
- (c) Run `completeSsoHandoff` after `initializeAuth()` instead of before. The stale-pair ordering test reddens on a `refreshToken` call preceding `exchangeSsoCode`.
- (d) Drop `auth: false` from `exchangeSsoCode`. The through-the-real-wrapper test reddens: its first `fetch` is `token/refresh/`, not `exchange/`.

**PR description draft:**

> Adds the UI for OIDC sign-in (spec PR S3): provider buttons on the login page, a `/login/sso`
> handler that redeems the one-time handoff before auth bootstrap runs, without authenticating the
> request, and stores tokens exactly as a password login does (the `/login/sso` route itself only
> shows a loader),
> an admin-only "Single sign-on" settings section (Entra preset with the redirect URI to paste
> into the app registration, generic provider, claim mappings, password-login toggle) and
> linked-identity management on the Users page. No backend change.
> Tests: frontend vitest. Break-checks listed in the spec's S3 section.

### S4: Password toggle, refresh refusal and break-glass

**Changes:**

- § 5.3 enforcement in `TokenObtainPairView`, `TokenRefreshView`, the admin login wrapper and `UserViewSet.me`.
- § 5.4's `me` password rule.
- § 5.5's guard, proof, guarded provider writes and serialization. This replaces S1's unconditional `password_toggle_unavailable` refusal, so the toggle, its enforcement and the break-glass become usable in one merge.
- Every gate reads `auth_settings` fresh (§ 5.1).
- `PASSWORD_LOGIN_FORCE` read in settings.
- The `password_login` management command (`apps/accounts/management/commands/password_login.py`).
- `password_login_forced` in `providers/`.
- The operator doc page, and the `LoginForm` copy.

**Tests:**

- every row of § 5.3; T12, T13
- § 5.5's three named tests (stale proof, unusable remaining provider, concurrent disables)
- the env force over a DB false (`override_settings(PASSWORD_LOGIN_FORCE=True)`)
- the command's three verbs and `--force`
- that no HTTP route can change `PASSWORD_LOGIN_FORCE`
- **Fresh read against a warmed stale cache.** Warm the Redis group cache by calling `CoreSettings._get_group("auth_settings", …)` while the row says enabled. Then flip the row to disabled with `CoreSettings.objects.filter(key="auth_settings").update(...)`, which fires no signal and so leaves the warmed cache stale. `POST token/` must answer 403 `password_login_disabled`.

**Break-checks:**

- (a) Check only the DB in the login gate and ignore the env. The force test reddens.
- (b) Accept any refresh token while password login is disabled. The D13 test reddens, naming `auth_method`.
- (c) Read `auth_settings` through `CoreSettings._get_group` in the login gate. The warmed-stale-cache test reddens with a 200 in place of 403. The pre-warmed cache is what makes the failure name the cache rather than an ordinary miss.
- (d) Drop `oidc_provider_version` from the proof check. The stale-proof test reddens with a 200.
- (e) Remove the `select_for_update()` on the `auth_settings` and provider rows. The concurrent-disables test reddens with two 200s, deterministically, because of the barrier described in § 5.5.

**PR description draft:**

> Makes password login switchable at runtime (spec PR S4): when an admin turns it off — which the
> lockout guard allows only from an SSO session on an enabled provider — the token, login and
> admin-login endpoints refuse passwords, password-issued refresh tokens stop refreshing, and API
> keys keep working. Break-glass is `MINO_PASSWORD_LOGIN_FORCE=1` in the environment or
> `python manage.py password_login --enable`; neither is reachable from the web.
> Tests: `apps.accounts.tests`. Break-checks listed in the spec's S4 section.

### S5: E2E with a fake OIDC provider

**Changes:**

- **The fake OP.** `e2e-upstream/src/oidc/` serves a minimal OP on the existing server:
  - discovery
  - `authorize`: auto-approves; the next login's claims are set through the control API
  - `token`: verifies PKCE and the client secret
  - `jwks`

  It uses `node:crypto` (`generateKeyPairSync`, `sign`). **No new npm dependency, and no new image:** the existing digest-pinned `node:24-slim` stages (`e2e-upstream/Dockerfile:18, :29`) build it.
- **Faults**, selectable per login: wrong `iss`, wrong `aud`, bad nonce, expired, `alg=none`, unknown `kid`, and omitting the RFC 9207 `iss` while advertising it.
- **Concrete origins.** `issuer` is `http://<upstream container name>:8080/oidc`, the in-network origin. That is `E2E_UPSTREAM_INTERNAL_URL` (`e2e/fixtures/upstream.ts:8`) + `/oidc`, which Django reaches for discovery, `token` and `jwks`. Discovery advertises `authorization_endpoint` as `E2E_UPSTREAM_CONTROL_URL` + `/oidc/authorize`, the host-published origin (`upstream.ts:5`, `http://127.0.0.1:9402` by default) that the Playwright browser on the runner reaches. Both base URLs are passed to the provider as environment by `scripts/e2e_up.sh` when it starts the upstream container, so discovery is built from them and not hard-coded. The issuer is an opaque string; only its fetches need to resolve, and Django makes them in-network.
- **Launcher.** `scripts/e2e_up.sh:369-376`'s `docker run` passes `-e MINO_OIDC_ALLOW_HTTP=1` only when `E2E_OIDC_ALLOW_HTTP=1` is set in the invoking environment. The new variable is named neutrally (`CONTEXT.md` § Mino), so the shared stack never gets it. `public_base_url` is the loopback `http://localhost:<DISPATCHARR_E2E_PORT>`, which § 5.1 accepts without the env.
- **Playwright project.** `sso` in `e2e/playwright.config.ts`: `testDir: './tests/sso'`, `workers: 1`, `fullyParallel: false`, with its `baseURL` taken from `E2E_BASE_URL` like every project (`playwright.config.ts:5`). It runs **only against a scoped stack** of its own:
  - `DISPATCHARR_E2E_CONTAINER`, `_VOLUME`, `_NETWORK` and `_PORT` (`scripts/e2e_up.sh:121-128`), plus `E2E_BASE_URL` to match
  - a guard at the top of the spec that fails, naming the variables, when `DISPATCHARR_E2E_CONTAINER` is unset or equals the shared default `dispatcharr-e2e`

  Turning password login off is instance-wide, and ADR 0001's shared container must never see it.
- **Auth state.** The project uses no stored `storageState` from `setup/`. Each test logs in through the API or the SSO button itself, so a principal's saved tokens from the shared stack can never apply.
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

- **Happy path** (`@contract`). Seed a provider through the API, then click the button in the browser, so the fake OP completes the flow. Assert:
  - the user is created at the mapped level
  - the channels page loads
  - a live channel plays in the floating player
  - the WebSocket connects
- **Unmapped claim** (`@contract`). It lands on `/login?sso_error=no_mapping`.
- **Toggle and break-glass** (`@characterization`). Sign in through SSO as Admin, switch password login off, and `POST token/` → 403. Then run `password_login --enable` through `instance.manage()`, and `POST token/` → 200. Its comment names the implementation fact it pins: the `password_login` management command, run inside the AIO container. Per ADR 0002, an operator CLI inside the image is something a reimplementation may change.

**Break-check:** make the fake OP return the wrong `aud`. The happy-path test reddens on `sso_error=id_token_invalid`, which shows the browser path really validates.

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

## Open questions for the owner

- **Q1.** On a mapping change, should SSO also **demote on refresh** rather than only at the next login? This spec re-evaluates at login only. The worst case is a 1-day refresh lifetime, and deactivating the local user is the immediate lever.
- **Q2.** Should a provider's mapping also assign **Channel Profiles** (claim value → profiles)? This spec leaves JIT users unrestricted with no profiles, the same as a user created in the UI with none, and leaves profiles to admins.
- **Q3.** Is **single-tenant-only** Entra acceptable? Guests invited into your tenant work; "any organisation" does not.
- **Q4.** Should provider and settings changes write an audit `SystemEvent` (a new event type)? Not included.
- **Q5.** **RP-initiated logout** is out (D15). Confirm, or ask for it as a follow-up.
- **Q6.** Should **API keys** be disable-able alongside password login? This spec keeps them working, per the brief.
