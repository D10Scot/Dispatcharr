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
| D3 | The callback **never calls `django.contrib.auth.login()`** and sets no Django session. Transient state lives in Redis behind a single-use key, bound to the browser by an HttpOnly cookie. |
| D4 | Tokens reach the SPA through a **one-time exchange code** in the URL **fragment**, redeemed by `POST`. Tokens never appear in a URL. |
| D5 | **Per-provider redirect URI** `<public_base_url>/api/accounts/oidc/<slug>/callback/`. The transaction is bound to a provider. RFC 9207 `iss` is checked when the provider advertises it. |
| D6 | `public_base_url` is **explicit configuration**. The `Host` header is never used to build a redirect URI. |
| D7 | Providers live in a **dedicated model** (`OIDCProvider`), not in `CoreSettings`. `CoreSettings` is readable by every Standard user. The password toggle and `public_base_url` live in a new `CoreSettings` group, `auth_settings`, which the generic settings endpoint refuses to write. |
| D8 | Identity is keyed on **(provider, issuer, subject)**. Email is never used for matching. An existing local user links through an explicit, authenticated "link" flow. |
| D9 | `user_level` is **recomputed from the mapping on every SSO login**. No match means refusal, and the stored level is left unchanged. |
| D10 | Entra preset: **single tenant only**. A tenant GUID is required; `common`, `organizations` and `consumers` are refused. `roles` is the default claim. A groups overage refuses the login rather than calling Graph. |
| D11 | Client secret **encrypted at rest** (Fernet, key derived from `SECRET_KEY` by HKDF), write-only in the API. |
| D12 | Password-off **lockout guard**: refuse unless an enabled provider exists and the acting admin's own token came from an SSO login on an enabled provider. |
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

- `core/models.py:227-234` defines eight group keys. `CoreSettings` is at `:290`. `_get_group` (`:398`) reads through a Redis group cache (`:236-242`), invalidated on `post_save` (`core/signals.py:11, :23`), so a write reaches every process at its next read. This is the R1 mechanism.
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
| `GET <slug>/start/?next=<path>[&intent=link&link_ticket=<t>]` | AllowAny, UI ACL, `oidc` throttle | Begins a transaction and answers with a 302 to the provider. |
| `GET <slug>/callback/` | AllowAny, UI ACL, `oidc` throttle | The redirect URI. Completes the flow, then 302s to the SPA with a handoff code in the fragment. |
| `POST exchange/` `{code}` | AllowAny, UI ACL, `oidc` throttle | Redeems a handoff code for `{access, refresh}`. |
| `POST link-ticket/` | `Authenticated` (JWT) | Issues a one-time link ticket for the caller (§ 4.2). |
| `GET/POST/PATCH/DELETE providers-admin/[<id>/]` | `IsAdmin` | Provider CRUD (§ 5). |
| `POST providers-admin/<id>/test/` | `IsAdmin` | Fetches and validates discovery and JWKS, then reports the redirect URI and any problem. Writes nothing. |
| `GET/PATCH settings/` | `IsAdmin` (GET also `IsStandardUser`, fields public) | `auth_settings`: `public_base_url`, `password_login_enabled`. PATCH runs the D12 guard. |
| `GET/DELETE identities/?user=<id>`, `identities/<id>/` | `IsAdmin` | List and unlink a user's SSO identities. |

The `oidc` throttle is a new DRF scope at `20/minute` per IP, using `LoginRateThrottle`'s trusted-proxy `get_ident` (`apps/accounts/throttling.py:8-22`). It is not the shared `login` scope, because one SSO login costs three requests against `login`'s 3/minute.

nginx needs no change: everything sits under `^~ /api/` (`docker/nginx.conf:177-179`). The SPA route `/login/sso` falls through to `location /`.

### 3.2 Start

1. Load the provider by `slug`. 404 if it is absent or disabled. 409 `{"code": "sso_not_configured"}` if `auth_settings.public_base_url` is unset.
2. Validate `next`: it must start with a single `/`, must not start with `//` or `/\`, and must contain no `\`, scheme or control character, with a 512-character maximum. Anything else becomes `/`. Never use an absolute URL.
3. Generate `state` (32 random bytes, base64url), `nonce` (32 bytes) and `code_verifier` (64 bytes base64url, RFC 7636 §4.1), plus `binding` (32 bytes).
4. Write the transaction to Redis at `oidc:tx:<state>`, TTL 600 s, value `{provider_id, provider_version, nonce, code_verifier, binding_hash: sha256(binding), next, intent, link_user_id, created}`.
5. Set the cookie `mino_oidc_tx=<binding>`: `HttpOnly`, `SameSite=Lax`, `Path=/api/accounts/oidc/`, `Max-Age=600`, and `Secure` when `public_base_url` is https. `Lax` is required: the callback is a top-level cross-site GET navigation from the IdP, and `Strict` would drop the cookie.
6. 302 to the discovered `authorization_endpoint` with:
   - `response_type=code`, `client_id`, `redirect_uri=<public_base_url>/api/accounts/oidc/<slug>/callback/`, `scope`, `state`, `nonce`
   - `code_challenge=BASE64URL(SHA256(code_verifier))`, `code_challenge_method=S256`
   - `prompt=select_account` if the provider sets `prompt_select_account`

### 3.3 Callback

Each check refuses with a 302 to `<public_base_url>/login?sso_error=<code>`, a fixed vocabulary that names no claim value, and a `login_failed` event (§ 7). Checks run in this order:

1. If an `error` parameter is present, the result is `idp_error`. The provider's `error_description` is logged at DEBUG only, redacted.
2. Fetch and delete `oidc:tx:<state>` in one step: Redis `GETDEL` through the project's Redis client, falling back to a Lua get-and-delete. A missing transaction is `state_invalid`. Single use is what stops replay.
3. `sha256(cookie mino_oidc_tx)` must equal `binding_hash`, compared with `hmac.compare_digest`. A mismatch or missing cookie is `binding_invalid`. **This is the login-CSRF defence.**
4. The transaction's `provider_id` must equal the URL slug's provider, and `provider_version` must equal the row's current version. Otherwise the result is `provider_mismatch`, the mix-up defence (D5).
5. If discovery has `authorization_response_iss_parameter_supported: true`, the `iss` parameter must be present and equal the provider's issuer (RFC 9207). If the parameter is present when not advertised, it must still match. Otherwise `issuer_mismatch`.
6. POST the token endpoint with `grant_type=authorization_code`, `code`, `redirect_uri` (identical string) and `code_verifier`. Authenticate the client with `client_secret_basic` (default) or `client_secret_post` (per provider). Timeouts are 5 s connect and 10 s read, `allow_redirects=False`, with a 1 MiB response cap. A non-200 or a missing `id_token` is `token_exchange_failed`.
7. Validate the ID token (§ 3.4). A failure is `id_token_invalid`.
8. Resolve the identity and the level (§ 4). The results are `no_mapping`, `inactive`, `groups_overage` or `link_conflict`.
9. Mint: `refresh = RefreshToken.for_user(user)`, then `refresh["auth_method"] = "oidc"` and `refresh["oidc_provider"] = provider.id`, so both claims survive refresh (§ 1). Update `last_login`.
10. Store the handoff at `oidc:handoff:<code>`, where `code` is 32 random bytes. TTL 60 s, value `{access, refresh, binding_hash, next}`.
11. Re-set `mino_oidc_tx` with the same binding and `Max-Age=120`. 302 to `<public_base_url>/login/sso#code=<code>`. A fragment is never sent to a server, a proxy log or a `Referer` header.

### 3.4 ID token validation (OIDC Core 1.0 §3.1.3.7)

The call is `jwt.decode(id_token, key, algorithms=[provider.id_token_alg], audience=provider.client_id, issuer=provider.issuer, leeway=60, options={"require": ["iss","sub","aud","exp","iat","nonce"]})`, with:

- The key is selected from the cached `PyJWKSet` by the header `kid`. An unknown `kid` triggers one JWKS refetch, with a 60 s per-provider cooldown key, and then refuses.
- `id_token_alg` defaults to `RS256` and is restricted to `{RS256, RS384, RS512, PS256, PS384, PS512, ES256, ES384, EdDSA}`. `none` and every `HS*` are refused at save time and at validation. An HMAC ID token would be keyed by the client secret, which is a key-confusion hazard.
- If `aud` is a list with more than one entry, `azp` must be present and equal `client_id`.
- `nonce` must equal the transaction nonce (`hmac.compare_digest`).
- Entra preset: `tid` must equal the configured tenant GUID, and `iss` must equal `https://login.microsoftonline.com/<tid>/v2.0` exactly. With a tenant-specific discovery document, the exact `iss` match "is all that is needed" (https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens, § Validate the issuer). The `tid` check is defence in depth.
- `c_hash` and `at_hash` are not checked. Entra documents that `c_hash` "isn't returned on ID tokens from the /token endpoint" (id-token-claims-reference), and the code-flow token-endpoint response is TLS-protected.

### 3.5 Discovery and JWKS fetching and caching

- Discovery is fetched from `<issuer>/.well-known/openid-configuration`. Its `issuer` must equal the configured issuer exactly (OIDC Discovery §4.3), and `authorization_endpoint`, `token_endpoint` and `jwks_uri` must be present.
- The configured issuer, and every discovered endpoint, must be `https`, unless the env var `MINO_OIDC_ALLOW_HTTP=1` is set. That is a deployment-level switch the e2e stack uses, and it is not a DB setting, so it cannot be enabled from the web.
- Both documents are cached in the Django cache (Redis, shared by every process): `oidc:disco:<provider_id>:<version>` and `oidc:jwks:<provider_id>:<version>`, TTL 3600 s. Every provider save bumps `version` (D7), so an edit is never served a stale document. Entra recommends checking for key updates about every 24 h; an hour is stricter.
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

A unique constraint covers `(provider, issuer, subject)`. A provider with identities cannot be deleted (`PROTECT`); the admin disables it, or unlinks the identities first. Its `issuer` (or Entra tenant) cannot be changed while identities exist: the save is refused with a message saying to create a new provider. Changing the issuer would silently JIT a duplicate user for every person.

### 4.2 Resolution on callback

1. **Known identity**: `(provider, iss, sub)` exists. Use its user. If `user.is_active` is false, refuse with `inactive`. SSO never reactivates a user.
2. **Link intent.** The transaction carries `intent=link` and a `link_user_id` taken from a one-time link ticket. `POST link-ticket/` mints the ticket for the JWT caller and stores it in Redis for 120 s; `start` consumes it. Attach the identity to that user. If the identity already belongs to another user, refuse with `link_conflict`. The mapping still applies (step 4), so an admin linking an IdP account that maps to Standard is demoted. The UI warns about this before linking.
3. **Unknown identity, no link intent.** JIT-create the user:
   - Start from `preferred_username`, falling back to `email`, then `sub`.
   - Reduce it to the `SAFE_CREDENTIAL_RE` alphabet, truncate it to 150 characters, and add `-2`, `-3`, … until it is unique. The username is a label only, never an identity key.
   - Call `set_unusable_password()`. Set `email` and `first_name`/`last_name` from `email`, `given_name` and `family_name` when present.
   - Set `is_staff` and `is_superuser` to false. Leave `channel_profiles` empty, which `apps/proxy/authorize.py:202-223` reads as unrestricted, exactly like a user created in the Users page with none. Set `stream_limit` to 0 and add no `xc_password`, so an SSO user has no XC access until an admin grants it.
   - Two concurrent first logins: catch `IntegrityError` on the unique constraint, then re-read and use the winner.
   - **No email-based matching of an existing local user, ever.**
4. **Level.** Evaluate the mapping, an ordered list of `{value, user_level}`, against the claim. The **highest** matched level wins. No match means refuse with `no_mapping`, and the stored level is left untouched. Otherwise set `user.user_level` if it changed (D9).

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
  - `version` (int, bumped on every save), `created`, `updated`

  `mappings` is validated as a list of `{value: non-empty str ≤ 256, user_level ∈ {0, 1, 10}}`, at most 50 entries, with no duplicate values.
- **`auth_settings`**, a new `CoreSettings` group (the ninth): `{"public_base_url": "", "password_login_enabled": true}`, read through `CoreSettings._get_group` like the others. A data migration seeds it, so PATCH works on a fresh instance. Contrast `epg_settings`, which has no seeding migration (CLAUDE.md § State).
- **`CoreSettingsViewSet.update` and `.create` refuse `key == "auth_settings"`** with 400 `{"code": "use_auth_settings_endpoint"}`. Otherwise the generic endpoint would bypass the D12 guard. Reads through the generic endpoint stay allowed, since neither field is secret.
- **`public_base_url`.** It must be an absolute `http(s)` URL with no path beyond `/`, no query, no fragment and no userinfo. It is stored without a trailing slash. `http` is accepted with a warning in the UI, because Entra requires https redirect URIs except for localhost. **It is never derived from the request.** `ALLOWED_HOSTS=["*"]` (`settings.py:107`) makes `request.get_host()` attacker-controlled.

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
| `POST /api/accounts/token/refresh/` | refused (401 `token_not_valid`) unless the refresh token carries `auth_method == "oidc"` and its `oidc_provider` is an enabled provider (D13) |
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

`PATCH settings/` with `password_login_enabled: false` succeeds only when all of these hold:

1. At least one provider is `enabled`, and its secret decrypts.
2. `public_base_url` is set.
3. The request's validated access token carries `auth_method == "oidc"`, with an `oidc_provider` that is one of those enabled providers. The acting admin proved, in this session, that SSO works for them **and maps them to Admin**, since `IsAdmin` gates the endpoint.

Otherwise the answer is 409 `{"code": "lockout_guard", "reasons": [...]}`. The same guard runs when a provider save would leave **zero** enabled providers while password login is off: disabling or deleting the last enabled provider is refused. An API-key caller has no token claims, so it fails (3) by design.

### 5.6 Break-glass (R3, D14)

- **`MINO_PASSWORD_LOGIN_FORCE=1`** (exactly `1`; any other value is ignored with one WARNING at boot) makes password login enabled regardless of the DB. It is read once at settings import into `settings.PASSWORD_LOGIN_FORCE`. Precedence: **env on ⇒ enabled; else the DB value.** While it is on:
  - `providers/` reports `password_login_forced: true`, and the login page and the SSO settings panel show a banner.
  - Every password login writes `login_success` with `break_glass: true`.
  - D13's refresh refusal is off.

  Setting it means editing the deployment's environment and restarting, which is not reachable from the web.
- **`manage.py password_login --enable | --disable | --status`** writes `auth_settings.password_login_enabled` through `CoreSettings._update_group`, so the group cache is invalidated and the change is live with no restart. `--disable` runs guard checks (1) and (2) but not (3), because the CLI has no SSO session, and needs `--force` to override them. `--status` prints the DB value, the env override and the enabled providers. A management command has no URL, and nothing in the web tier invokes it.
- Neither can be set by the UI, the REST API or a `CoreSettings` write. A test asserts that the generic settings endpoint and `PATCH settings/` cannot change `settings.PASSWORD_LOGIN_FORCE`.

`docs/` gains an operator page with the two paste-ready commands, `docker exec <container> python manage.py password_login --enable` and the env line, and the `LoginForm` "Forgot password" text points to it.

### 5.7 Frontend

- **`frontend/src/api.js`**: `getAuthConfig()` (`GET providers/`), `exchangeSsoCode(code)`, `createLinkTicket()`, and admin CRUD for providers, auth settings and identities. All HTTP stays in `api.js`.
- **`frontend/src/store/auth.jsx`**: `loginWithTokens({access, refresh})`, factored out of `login()` (`:177-197`) so the password and SSO paths store tokens identically. `authConfig` state.
- **`pages/Login.jsx`**: after the superuser check, fetch `authConfig`. Render one button per provider, plus `LoginForm` only when `password_login_enabled`. The SSO button sets `window.location.href = /api/accounts/oidc/<slug>/start/?next=<current intended path>`, a top-level navigation, never fetch or XHR. Show the `?sso_error=` code as fixed copy.
- **New route `/login/sso`** in the unauthenticated branch at `App.jsx:168-170`:
  - read `location.hash`, then immediately `history.replaceState` to drop it
  - `POST exchange/`, then `loginWithTokens`, `initData`, and navigate to the handoff's `next`
  - on failure, go to `/login?sso_error=exchange_failed`
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

No event payload and no log line ever carries `code`, `state`, `nonce`, `code_verifier`, the binding, an ID token, an access token, a refresh token, the client secret, a raw claim set or `sub`. Failure reasons name the check, never the value.

## 8. Security review

| # | Threat | Defence | Test (PR) |
|---|---|---|---|
| T1 | Open redirect via `next` | § 3.2 step 2 allowlist (relative path only) | `//evil`, `/\evil`, `https://evil`, `%2F%2Fevil` and a control character all become `/` (S2) |
| T2 | Open redirect or host poisoning via the `Host` header | `public_base_url` only (D6) | a request with `Host: evil.example` produces `redirect_uri` and a final Location on the configured base (S2) |
| T3 | Login CSRF (the victim is logged in as the attacker) | tx binding cookie (§ 3.3 step 3) and handoff bound to the same binding | callback with valid state but no or a wrong cookie → `binding_invalid`; exchange with another browser's code → 400 (S2) |
| T4 | State replay | `GETDEL`, single use | a second callback with the same state → `state_invalid` (S2) |
| T5 | Authorization code injection or interception | PKCE S256, verifier server-side only | the token request body carries `code_verifier` matching the stored challenge, and the fake IdP refuses a wrong verifier (S2 unit, S5 e2e) |
| T6 | ID-token substitution or replay | `nonce` bound to the transaction, `aud`/`azp`, `exp`/`iat` with 60 s leeway | per-claim negative tests: wrong nonce, wrong aud, multi-aud without azp, expired, iat in the future (S2) |
| T7 | Signature bypass | `algorithms=[configured]`, `none`/`HS*` refused, `kid` must resolve | `alg=none` token, HS256 token signed with the client secret, unknown kid after one refetch, token signed by a key not in JWKS (S2) |
| T8 | Mix-up across providers | per-provider redirect URI, tx bound to provider and version, RFC 9207 `iss` | callback for provider B with a transaction from A → `provider_mismatch`; advertised `iss` param absent or wrong → `issuer_mismatch` (S2) |
| T9 | Entra multi-tenant issuer pitfall | single tenant only (D10), exact `iss`, `tid` check | the preset refuses `common`/`organizations`; a token with a correct signature but another `tid`/`iss` is refused (S1, S2) |
| T10 | Account takeover by email | identity keyed on (provider, iss, sub), no email matching | a JIT login whose email equals an existing admin's email creates a **new** Standard user and does not touch the admin (S2) |
| T11 | Privilege retained after an IdP change | level recomputed on each login, refusal on no match | login 1 maps Admin, login 2 maps Standard → level 1; login 3 no match → refused and level unchanged (S2) |
| T12 | Self-service password bypassing the IdP | § 5.4 | SSO-only user `PATCH me {password}` → 400 (S4) |
| T13 | Lockout | D12 guard, last-provider guard, break-glass | each guard reason individually yields 409; env force re-enables; command `--enable` re-enables live (S4) |
| T14 | Guard bypass through the generic settings endpoint | refusal of `auth_settings` in `CoreSettingsViewSet` | `PATCH /api/core/settings/<auth id>/` and `POST` with that key → 400 (S1) |
| T15 | Client secret disclosure | write-only field, encrypted at rest, not in `CoreSettings` | GET list/detail never contains the secret or ciphertext; a Standard user's `GET /api/core/settings/` lacks it; DB column ≠ plaintext (S1) |
| T16 | Credential logging | `CREDENTIAL_RE` extended with `client_secret`, `id_token`, `access_token`, `refresh_token`, `code_verifier` and `\bnonce\b`; logs name checks, not values | `tests/test_credential_logging_guard.py` gains a case per name; `assertLogs` over a full callback finds none of the secret values (S2) |
| T17 | Secrets in SystemEvent and Connect payloads | § 7 field whitelist | after a success and each failure, every `SystemEvent.details` JSON is searched for the code, state, ID token, tokens and secret, and none is present (S2) |
| T18 | Ambient session principal on streaming surfaces | D3: no `login()` | after a completed callback, the response sets no `sessionid` cookie and no session row holds `_auth_user_id` (S2) |
| T19 | Token leakage via URL | fragment handoff, 60 s single use | the callback Location has `#code=`, never `?code=`, and a second exchange → 400 (S2) |
| T20 | Discovery or JWKS abuse (slow, huge, redirect) | timeouts, 1 MiB cap, no redirects, https-only unless env | an oversized body and a 302 from jwks_uri → refused with a clear admin `test` result (S2) |
| T21 | Brute force or DoS of the flow | `oidc` throttle 20/min per trusted-proxy IP; caches | the 21st start in a minute → 429 (S2) |
| T22 | Deactivated user regaining access via SSO | `is_active` check, SSO never reactivates | inactive linked user → `inactive` (S2) |

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
- `settings/` GET and PATCH with the D12 guard. In S1, check (3) can never pass, so turning password login off is refused. That is correct, since no SSO login exists yet.
- `identities/` list and delete.
- CLAUDE.md § State: "eight groups" becomes "nine", naming `auth_settings`. The `e2e/tests/guards/global-mutation.spec.ts` header lists the ninth group.

**Tests:** model constraints; issuer immutability with identities present; delete-PROTECT; secret round-trip and the unreadable-after-key-change path; no secret in any response; T14, T15; Entra refusals (T9 part); mapping validation; the `test` action against an in-process `http.server` thread serving discovery and JWKS (no network).

**Break-checks:**

- (a) Make `client_secret` a readable field. The T15 response test reddens, naming `client_secret`.
- (b) Remove the `auth_settings` refusal in `CoreSettingsViewSet.update`. T14 reddens with a 200 in place of the expected 400.
- (c) Accept `organizations` as a tenant. The preset test reddens.

**Hooks:** `apps/accounts/models.py` and `core/models.py` (`makemigrations --check`); `*.py` (credential logging); `apps/accounts/tests/test_*.py` and `core/tests/test_*.py`.

**PR description draft:**

> Adds the storage and admin API for OIDC single sign-on, the first PR of the SSO spec
> (`docs/superpowers/specs/2026-10-31-sso-oidc-design.md`, PR S1; ADR 0011). New models
> `OIDCProvider` and `OIDCIdentity`, a seeded `auth_settings` settings group that the generic
> `/api/core/settings/` endpoint refuses to write, admin CRUD with a discovery/JWKS `test` action,
> and an Entra preset that accepts only a tenant GUID. Client secrets are encrypted at rest and
> never returned. No login flow yet: password login cannot be switched off until PR S2 lands an
> SSO login the lockout guard can see.
> Tests: `apps.accounts.tests`, `core.tests`. Break-checks: a readable secret field, a removed
> settings refusal and an accepted `organizations` tenant each redden a named test.

### S2: The OIDC flow (backend)

**Changes:**

- `apps/accounts/oidc/flow.py` (start, callback, exchange, link ticket).
- `apps/accounts/oidc/validate.py` (§ 3.4).
- `apps/accounts/oidc/provisioning.py` (§ 4).
- The `oidc` throttle scope at `settings.py:343-345`.
- The `auth_method`/`oidc_provider` claims, and the `providers/` public endpoint.
- The `CREDENTIAL_RE` extension (`scripts/check_credential_logging.py:111-113`) and its tests.
- § 7 events.

**Tests:** T1-T8, T10, T11, T16-T22, all against an in-process fake OP: a `http.server` thread plus RSA and EC keys generated with `cryptography` in `setUpClass`, issuing tokens with PyJWT. The suite also covers:

- the happy path, end to end through the Django test client, including that the exchanged access token authenticates `GET /api/accounts/users/me/` **and** `_drf_user` in `apps/proxy/authorize.py` (the D2 claim that streaming needs nothing new);
- that both custom claims survive `POST token/refresh/`;
- the concurrent JIT `IntegrityError` path.

**Break-checks:**

- (a) Delete the binding comparison. The T3 test reddens with `binding_invalid` expected and a 302 to `/login/sso` received.
- (b) Pass `algorithms=None`, or append `"HS256"`. The T7 HS256 test reddens.
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
- `/login/sso`: strips the hash before the exchange request, calls `loginWithTokens` with the response, and maps a failure to `sso_error`.
- `loginWithTokens` writes the same three `localStorage` keys `login()` writes.
- The settings form never sends `client_secret` when the field is untouched, and renders 409 `lockout_guard` reasons.
- The Entra form computes and shows the redirect URI from `public_base_url` and the slug.

**Break-checks:**

- (a) Drop `history.replaceState`. The hash-strip test reddens.
- (b) Send `client_secret: ''` on an untouched field. The settings-form test reddens.

**PR description draft:**

> Adds the UI for OIDC sign-in (spec PR S3): provider buttons on the login page, a `/login/sso`
> route that redeems the one-time handoff and stores tokens exactly as a password login does,
> an admin-only "Single sign-on" settings section (Entra preset with the redirect URI to paste
> into the app registration, generic provider, claim mappings, password-login toggle) and
> linked-identity management on the Users page. No backend change.
> Tests: frontend vitest. Break-checks listed in the spec's S3 section.

### S4: Password toggle, refresh refusal and break-glass

**Changes:**

- § 5.3 enforcement in `TokenObtainPairView`, `TokenRefreshView`, the admin login wrapper and `UserViewSet.me`.
- § 5.4.
- `PASSWORD_LOGIN_FORCE` read in settings.
- The `password_login` management command (`apps/accounts/management/commands/password_login.py`).
- `password_login_forced` in `providers/`.
- The operator doc page, and the `LoginForm` copy.

**Tests:** every row of § 5.3; T12, T13; the env force over a DB false (`override_settings(PASSWORD_LOGIN_FORCE=True)`); the command's three verbs and `--force`, with the change visible to a subsequent request with no cache flush (R1, no restart); and that no HTTP route can change `PASSWORD_LOGIN_FORCE`.

**Break-checks:**

- (a) Check only the DB in the login gate and ignore the env. The force test reddens.
- (b) Accept any refresh token while password login is disabled. The D13 test reddens, naming `auth_method`.
- (c) Write the setting with `CoreSettings.objects.filter().update()` in the command (it bypasses `post_save`). The live-without-restart test reddens.

**PR description draft:**

> Makes password login switchable at runtime (spec PR S4): when an admin turns it off — which the
> lockout guard allows only from an SSO session on an enabled provider — the token, login and
> admin-login endpoints refuse passwords, password-issued refresh tokens stop refreshing, and API
> keys keep working. Break-glass is `MINO_PASSWORD_LOGIN_FORCE=1` in the environment or
> `python manage.py password_login --enable`; neither is reachable from the web.
> Tests: `apps.accounts.tests`. Break-checks listed in the spec's S4 section.

### S5: E2E with a fake OIDC provider

**Changes:**

- `e2e-upstream/src/oidc/`: a minimal OP served on the existing server. Discovery, `authorize` (auto-approve; the next login's claims are set by the control API), `token` (verifies PKCE and the client secret) and `jwks`, using `node:crypto` (`generateKeyPairSync`, `sign`). **No new npm dependency, and no new image:** the existing digest-pinned `node:24-slim` stages (`e2e-upstream/Dockerfile:18, :29`) build it.
- Faults selectable per login: wrong `iss`, wrong `aud`, bad nonce, expired, `alg=none`, unknown `kid`, and omitting the RFC 9207 `iss` while advertising it.
- **The two-origin problem.** The browser reaches `authorize` on the host-published origin, while Django reaches `token` and `jwks` over the e2e network. The discovery document advertises each endpoint on its own origin, and the issuer is one opaque string used for both (e2e-upstream README § "Two origins, never conflated"). `MINO_OIDC_ALLOW_HTTP=1` is set on the `sso` container only.
- A new Playwright project, **`sso`**, with **its own container**. Turning password login off is instance-wide, and ADR 0001's shared container must never see it.
- `e2e/tests/guards/global-mutation.spec.ts` treats `/api/accounts/oidc/settings/` and `providers-admin/` as instance-wide writes, allowlisted for the `sso` project only.
- `e2e/COVERAGE.md` rows.

**Tests:**

- Seed a provider through the API, then click the button in the browser, so the fake OP completes the flow. Assert the user is created at the mapped level, the channels page loads, a live channel plays in the floating player, and the WebSocket connects.
- An unmapped claim lands on `/login?sso_error=no_mapping`.
- The password toggle off: token obtain → 403. Then break-glass via `manage.py password_login --enable` through the allowlisted subprocess capability (one allowlist line), and token obtain → 200.

Every test carries `@contract`.

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
