# Phase 1 PR 5 — Authorize Hop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put every long-lived stream surface behind one Django function, `authorize_stream()`,
reached by an nginx `auth_request` subrequest once per tune and by an inline call when there is no
nginx — closing #87 and #95, and giving the relay a trust marker it cannot be handed by a client.

**Architecture:** `apps/proxy/authorize.py` owns the whole decision: the `STREAMS`/`XC_API`
network ACL, principal resolution (internal HMAC, Xtream credentials, JWT, API key, query-param
JWT, session, anonymous), `user_level`, Channel Profile membership, `hidden_from_output`,
`is_adult` against the user's `hide_adult_content`, Output Profile resolution, client-id minting
and — on the live surfaces — the per-user stream limit. `apps/proxy/authorize_views.py` exposes it
twice: as the `AllowAny` view nginx calls at `= /_dispatcharr/authorize` (`internal;`), and as
`resolve_authorization()`, which the seven stream views call and which trusts nginx's answer only
when `X-Dispatcharr-Authorized` carries `HMAC(SECRET_KEY, "relay-trust")`. nginx copies the 200
response's `X-Relay-*` headers into variables with `auth_request_set` and re-emits them as
`uwsgi_param HTTP_X_RELAY_*`; every non-relay uwsgi location blanks the same five params through
one shared include, because both processes run the same urlconf and either can serve a stream view.

**Tech Stack:** Django 6 + DRF (`apps/proxy/`, `apps/timeshift/`, `apps/channels/`), nginx 1.24.0
`auth_request` / `auth_request_set` / `map` / `uwsgi_param`, bash
(`docker/init/03-init-dispatcharr.sh`), Docker (`docker/Dockerfile`), Playwright + TypeScript
(`e2e/`), the curated metrics ledger (`metrics/curated/defects.yml`).

**Spec:** `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` § The eight pull
requests › PR 5 — `migration/phase1-authorize`.

**Branch:** `migration/phase1-authorize` (worktree `.worktrees/phase1-pr5`), off `main`.

**Plan date:** this file is dated **2026-09-05**, the day it was written, not 2026-09-04 like its
three predecessors.

## Branch base

This branch was cut from PR 4's branch, so PR 4's work (`docker/uwsgi.relay.ini`, the nginx
location table with `upstream relay_py`, the `relay-uwsgi` supervisord program, the modular
`relay` service, `test_role_split`, `instance.supervisorctl()`, the widened greybox buffering pin,
the reshaped `get_dvr_stream_base_url()`) is already present in this worktree as ordinary file
content.

**PR 5 executes only after PR 4 (#175) has merged to `main`.** Task 1 is the gate: reset this
branch onto `origin/main` before anything else. PR 4 arrives on `main` **squashed**, so:

- **This plan cites no PR 4 commit hash anywhere, and neither may the executor.** After a squash
  merge the hashes on this branch do not exist on `main`; `git merge-base --is-ancestor` answers
  "no" for a PR 4 that has demonstrably merged. Every check in Task 1 is a check on **file
  content**.
- **Every file:line below was verified against this worktree before the reset.** Line numbers
  drift; the tree wins. Task 1 re-runs the greps that matter and says what to do with each answer.

## Global Constraints

- Two context-separated HMACs of `settings.SECRET_KEY`, hex digest, compared with
  `hmac.compare_digest`: `X-Dispatcharr-Authorized` = `HMAC(SECRET_KEY, "relay-trust")`,
  `X-Dispatcharr-Internal` = `HMAC(SECRET_KEY, "internal-principal")` (D11).
- The five params nginx sets and blanks: `HTTP_X_DISPATCHARR_AUTHORIZED`, `HTTP_X_RELAY_CHANNEL`,
  `HTTP_X_RELAY_OUTPUT`, `HTTP_X_RELAY_CLIENT`, `HTTP_X_RELAY_USER`. Response headers on the 200:
  `X-Relay-Channel`, `X-Relay-Output`, `X-Relay-Client`, `X-Relay-User`, `X-Relay-Name`.
- `RELAY_DEFAULT_NAME = os.environ.get("DISPATCHARR_RELAY_DEFAULT_NAME", "py")` in
  `dispatcharr/settings.py` is the only definition of the relay name; the nginx `map` key is the
  literal `py`.
- Authorize location: `location = /_dispatcharr/authorize`, `internal;`,
  `uwsgi_pass unix:/app/uwsgi.sock;`, `uwsgi_param HTTP_X_ORIGINAL_URI $request_uri;`,
  `uwsgi_pass_request_body off;`, plus the blanking include.
- Status vocabulary as `authorize_stream()` decides it: `200` authorized, `401` no principal where
  one is required, `403` ACL or channel-flag or membership denial, `404` nothing resolved for the
  identifier, `429` stream limit.
- **What nginx can carry, and the mapping that fixes it.** `ngx_http_auth_request_module` allows on
  2xx, denies with 401 or 403 *verbatim*, and treats **every other subrequest status as an error**,
  answering the client 500. A hop that answered 404 or 429 directly would therefore turn today's
  404 (unknown channel id in a stale playlist) and today's 429 (stream limit) into 500s. So
  `authorize_view` collapses every non-401 denial to **403 plus `X-Authorize-Status: <real code>`**,
  each relay-bound location adds
  `auth_request_set $authorize_status $upstream_http_x_authorize_status;` and
  `error_page 403 = @authorize_denied;`, and one server-level `location @authorize_denied` returns
  the real code. `AuthorizeDenied` keeps its true status on the **inline** path, which no nginx
  touches. Amendment S7.
- `error_page` goes **only inside the relay-bound locations**, never at server level, because a
  server-level one would route *every* 403 in the server through `@authorize_denied` — a static
  file's, an `internal` location's, one the relay itself returned — and hand each of them whatever
  `$authorize_status` happened to hold. (It would not recurse: with `recursive_error_pages` off,
  the default, nginx sets `r->error_page` on the first redirect and never applies `error_page`
  again.) `uwsgi_intercept_errors` is off by default, so a 403 the relay produces is not
  intercepted even by the per-location form.
- `^~` never goes on `/`; the admin regex stays ahead of the XC three-segment regex; exact (`=`)
  locations carry no `^~` (D7).
- `auth_request_set` is the only context in which `$upstream_http_*` from the subrequest is
  readable, which is why `$relay_name` — not `$upstream_http_x_relay_name` — is the `map` key.
- `uwsgi_pass_request_headers` is on by default, so every relay-bound location overrides the five
  params and every non-relay uwsgi location blanks them; a location declaring any `uwsgi_param`
  inherits none from above, so the blanking is an include repeated per location.
- The nested `location ~ ^/api/channels/recordings/\d+/file/$` inside `^~ /api/` is relay-bound but
  **excluded from `auth_request`**: it carries the blanking include like a non-relay location, its
  gate stays DRF authentication plus `network_access_allowed("STREAMS")`, and it gets no row in the
  authorize matrix (spec § PR 4 amendment S5, restated in § PR 5's nginx bullet).
- `^~ /proxy/relay/` is also excluded from `auth_request` and carries the blanking include: it is
  PR 7's control API, gated by the internal token alone (D9), and `authorize_stream` knows no such
  surface.
- In `dev` (and `debug`, which sets `DISPATCHARR_ENV=dev`) there is no nginx: `all-dev.conf`
  includes `vite.conf`, and `get_dvr_stream_base_url()` returns `http://127.0.0.1:5656`. A tune
  there — a DVR recording included — reaches the view with no marker and authorizes inline. No
  task may assume every tune crosses `auth_request`.
- `CLAUDE.md` rules that bite here: DRF serializers for every endpoint, never raw dicts; routes in
  the app's `api_urls.py` and present in the drf-spectacular schema; migrations ship with model
  changes (this PR adds no model change and must add no migration); any URL or header logging goes
  through `redact_url`/`redact_headers` or `scripts/check_credential_logging.py` blocks the commit;
  no channel state in Python memory; no blocking call in a gevent worker; `os.posix_spawn` stays.
- **`git add` and `git commit` run in separate Bash calls**, and the commit message is written with
  the Write tool and passed as `-F <msgfile>` — the pre-commit hook blocks any single call
  containing both verbs, and trips on a heredoc that merely contains them.
- Supply-chain pinning applies to any new `uses:` (40-char SHA + version comment) or `FROM` /
  `COPY --from=` (digest). This PR adds neither; its one Dockerfile line is a plain local `COPY`.
- CI label routing: this PR edits `dispatcharr/settings.py`, `dispatcharr/urls.py` and
  `dispatcharr/utils.py`, and `dispatcharr/` is in `_SHARED_PATH_PREFIXES`
  (`dispatcharr/test_discovery.py:10-18`), so `backend-tests.yml` runs **all 16 labels** regardless
  of what else changed. The branch is `migration/**`, so `lifecycle-tests.yml` and `e2e-tests.yml`
  run in full mode.

## Done criteria (from the spec)

- [ ] The E2E authorize specs pass in full mode — `npx playwright test --project=streaming -g "…"`
      for each new title, and the whole `streaming` project green (Task 11).
- [ ] `apps.proxy.tests` green — `manage.py test --keepdb apps.proxy.tests`.
- [ ] `apps.proxy.live_proxy.tests` green — `manage.py test --keepdb apps.proxy.live_proxy.tests`.
- [ ] `apps.channels.tests` green — `manage.py test --keepdb apps.channels.tests`.
- [ ] `apps.timeshift.tests` green — `manage.py test --keepdb apps.timeshift.tests`.
- [ ] `scripts/check_credential_logging.py apps/channels/tasks.py` exits 0.
- [ ] Issues #87, #95 and #100 are *closeable*: all three `test.fail()` pins are flipped to plain
      `test()` and pass (#100 is closed by construction — see Task 6 Step 3b). The closures
      themselves are performed in PR 8 (spec § PR 5 Done: "with the closure recorded in PR 8's Done
      log rather than performed here"); the orchestrator removes #87's erroneous `wontfix` label by
      hand when the draft PR opens. See amendment S4 for why this plan runs neither `gh issue
      close` nor a label edit.
- [ ] The three `metrics/curated/defects.yml` rows validate — `python3 -m metrics.build
      --validate-only --curated metrics/curated` exits clean (Task 12 Step 6).
- [ ] `e2e/COVERAGE.md` carries the authorize-matrix row (Task 11 Step 8).
- [ ] `CLAUDE.md` corrected: the plaintext-`!=` security bullet, the § Architecture § Auth
      "gated only by `network_access_allowed`" sentence, and the "hidden channels are unlistable
      yet streamable" bullet (Task 12).

## Test environment for this worktree

The edit/commit hooks resolve the project directory from the harness, so in a worktree they do not
run tests automatically. Run them yourself:

1. Start a container for this worktree (idempotent):
   `DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr5 DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-pr5 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr5/.claude/hooks/start-test-container.sh`
2. After editing any file, run the affected-file hook by hand:
   `echo '{"tool_input":{"file_path":"<absolute path of edited file>"}}' | CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr5 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr5 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr5/.claude/hooks/run-affected-tests.sh`
   Exit 2 = blocking failure; read the output.
3. Before every commit, run the commit gate by hand:
   `CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase1-pr5 DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr5 /Users/dion/git/Dispatcharr/.worktrees/phase1-pr5/.claude/hooks/pre-commit-tests.sh --git-hook`
4. Backend tests directly: `docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING dispatcharr-testrunner-pr5 /dispatcharrpy/bin/python manage.py test --keepdb <label> -v1`
5. Frontend: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr5/frontend && npm ci && npm test`. E2E typecheck: `cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr5/e2e && npm ci && npx tsc --noEmit`. A full Playwright project run needs the AIO image built from this worktree (`e2e/README.md`); use a distinct `DISPATCHARR_E2E_CONTAINER`/`_PORT`/`_VOLUME`/`_NETWORK` so the shared `dispatcharr-e2e` stack is untouched, and never pass `--reset`.
6. If the container cannot start, say so in the task report: the work is then unverified, not verified.

### Local notes for this worktree

The six numbered items above are the shared contract every Phase 1 plan carries verbatim. These
four notes are specific to this machine and this worktree, and none of them replaces an item above.

- **Item 1 hangs after the container is ready.** Run it in the foreground with stdin closed and the
  Bash tool's `timeout: 600000`, adding `DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest`:
  ```bash
  DISPATCHARR_TEST_CONTAINER=dispatcharr-testrunner-pr5 \
  DISPATCHARR_TEST_DB_VOLUME=dispatcharr-hookdb-pr5 \
  DISPATCHARR_TEST_IMAGE=ghcr.io/d10scot/dispatcharr:latest \
  /Users/dion/git/Dispatcharr/.worktrees/phase1-pr5/.claude/hooks/start-test-container.sh </dev/null
  ```
  Readiness is `docker exec dispatcharr-testrunner-pr5 pg_isready -h /var/run/postgresql`; once it
  answers, kill the script and carry on.
- **The E2E stack for item 5**, with the pr5-suffixed names. Never `--down`, never `--reset`, and
  never touch the shared `dispatcharr-e2e`, `dispatcharr-e2e-g14`, `e2e-upstream` or
  `dispatcharr-testrunner`:
  ```bash
  DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr5 \
  DISPATCHARR_E2E_PORT=49191 \
  DISPATCHARR_E2E_VOLUME=dispatcharr-e2e-pr5-data \
  DISPATCHARR_E2E_NETWORK=dispatcharr-e2e-pr5-net \
  DISPATCHARR_E2E_IMAGE=dispatcharr-e2e-pr5:local \
  DISPATCHARR_E2E_UPSTREAM_CONTAINER=e2e-upstream-pr5 \
  DISPATCHARR_E2E_UPSTREAM_PORT=9404 \
  DISPATCHARR_E2E_SKIP_UPSTREAM_BUILD=1 \
  scripts/e2e_up.sh
  ```
- **A private fake provider**, because the shared one's host port is unreliable here. Recreate its
  container with `-e UPSTREAM_INTERNAL_ORIGIN=http://e2e-upstream-pr5:8080` — without it every
  subprocess-profile test fails with "188 bytes then EOF" — and run Playwright with:
  ```bash
  E2E_UPSTREAM_CONTROL_URL=http://127.0.0.1:9404 \
  E2E_UPSTREAM_INTERNAL_URL=http://e2e-upstream-pr5:8080 \
  DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr5 \
  PLAYWRIGHT_BASE_URL=http://127.0.0.1:49191 \
  npx playwright test --project=streaming
  ```
- **Playwright `-g` patterns must match exact titles** — `SPA` alone over-matches "spawns" — and
  the bash lifecycle suites need `/opt/homebrew/bin/bash` (5.3); the system bash is 3.2 and the
  suites use associative arrays.

## Spec amendments made by this plan

House convention: a plan may not silently diverge from its spec. Each amendment below is applied to
`docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` **in this PR**, by Task 12, quoting
the text it replaces.

| # | Spec location | Amendment | Why |
| --- | --- | --- | --- |
| **S1** | § PR 5, the `check_user_stream_limits` bullet ("moves *inside* `authorize_stream` unchanged") | The limit check moves into `authorize_stream` for the **live** surfaces only (`stream_ts`, `stream_xc`). `stream_vod`'s call (`apps/proxy/vod_proxy/views.py:781`) and `_serve_catchup`'s (`apps/timeshift/views.py:493`) stay where they are. | Neither identifier the check needs exists at the hop. VOD: the XC entry points resolve `content_id` from an `M3UMovieRelation`/`M3UEpisodeRelation` **inside the view** — the spec's own § ORM reads table keeps those reads in the relay ("the authorize hop resolves the *principal*, not the content object") — so the hop cannot pass a `media_id` for `/movie/…` or `/series/…`, and running it only for the native VOD route would leave the two XC routes unchecked or double-checked. Catch-up: `check_user_stream_limits`'s timeshift branch matches on a `<channel>_<programme>` `media_id` and a pool-derived `client_id` computed ~160 lines into `_serve_catchup`, after session/fingerprint resolution; a hop passing the bare channel uuid would miss the sibling exemption (`conn_media_id.startswith(f"{media_id}_")`, `apps/proxy/utils.py:334-337`) and **429 a legitimate mid-programme seek**. The client-visible contract is unchanged: a limit breach is still 429 on live and still `HttpResponseForbidden`/`429` on the surfaces that already answer that way today. |
| **S2** | § PR 5, "their inline … `check_user_stream_limits` calls are deleted, not duplicated" | Reworded to name the three that are deleted (`network_access_allowed`, the plaintext password compare, `_user_can_access_channel`) and to record the two limit calls that stay, per S1. | Same reason; stated separately so a later grep for `check_user_stream_limits` in the stream views does not read as a regression. |
| **S3** | § The contract › "1. Authorize (PR 5)", the `200` row | `X-Relay-Channel` is consumed by `stream_xc` (which receives a numeric Xtream id and needs the uuid the hop resolved). `stream_ts` keeps using the identifier in its own URL. `X-Relay-Output` carries the Output **Profile id**, and the relay re-fetches the `OutputProfile` row by primary key to call `build_command()`. | The header contract cannot carry a built ffmpeg command, and `apps/proxy/live_proxy/views.py:689` needs the model instance, not the id. What moves to Django is the *resolution rule* (query param → user preference → none), which is the substance of ADR 0005's "any direct read of `M3UAccount`/`OutputProfile` at tune time"; one primary-key read remains in the relay, alongside the `User` row the relay loads from `X-Relay-User` for output-format resolution and client registration. Recorded so PR 6/7 do not read it as an unfixed leak. |
| **S4** | § PR 5, "Remove the erroneous `wontfix` label from issue #87 before closing it" | This PR neither closes #87/#95 nor edits their labels. It flips both `test.fail()` pins and moves both `metrics/curated/defects.yml` rows to `fixed`. PR 8 closes both issues and removes the `wontfix` label in the same action. | The same section's Done list already defers the closure to PR 8 ("issues #87 and #95 closeable, with the closure recorded in PR 8's Done log rather than performed here"), and § PR 8 lists "Issues #87 and #95 closed, referencing PR 5". The label bullet is the odd one out; one PR performing the label edit and another the closure would leave a window where #87 is open, unlabelled and fixed. |
| **S5** | § Documentation and § PR 8, the `e2e/COVERAGE.md` bullet | PR 5 adds **its own** row — the authorize matrix — under a new `Goal` value `P1`. PR 8 still adds the other four (TTFB, Django-down, bounded relay restart, modular role split). | `e2e/README.md:691` ("Update `COVERAGE.md` in the same PR as the test") and `CLAUDE.md` § Testing are the standing rule, and § PR 8's bullet was written before PR 2 and PR 5 existed. `P1` is a new value in a column that has only ever held `G1`–`G15`; **nothing validates that column** — verified by grepping `e2e/tests/guards/`, `scripts/` and `metrics/` for `COVERAGE`, which finds only prose references in spec files — so the value costs nothing but needs stating. Task 11 re-runs that grep and extends whatever it finds. |
| **S6** | § The contract › "1. Authorize (PR 5)", the `401` row ("the XC credential surfaces") | `/proxy/catchup/<uuid>` also answers `401` when no principal resolves. | `catchup_proxy` (`apps/timeshift/views.py:319-323`) returns `{"error": "Authentication required"}` with 401 today for an anonymous request. The matrix's anonymous row is written against `/proxy/ts/stream/<uuid>` and must not be read as making catch-up anonymous. |
| **S7** | § The contract › "1. Authorize (PR 5)", the whole status table; and § Error handling per hop, the "Django down, new tune" row | Through nginx, the hop answers **200, 401 or 403 only**. A 404 or 429 decision is sent as 403 carrying `X-Authorize-Status`, and the relay-bound location's `error_page 403 = @authorize_denied` restores the real code. The inline path answers 401/403/404/429 directly. § Error handling's "Django down, new tune" row becomes **500**, not `{502, 503, 504}`: an unreachable `auth_request` upstream is "any other response code", which the module reports as its own error. PR 8 decides whether to narrow that; this PR states it. | `ngx_http_auth_request_module`, primary source: "If it returns 401 or 403, the access is denied with the corresponding error code. Any other response code returned by the subrequest is considered an error." Without the mapping, an unknown channel id in a cached playlist would answer 500 where it answers 404 today, and a user over their stream limit would answer 500 where they get 429 today — two regressions in a PR whose subject is authorization. Bodies through nginx were always nginx's own for a denial, so nothing is lost there. |
| **S8** | § PR 5, "every relay-bound location gains the `auth_request` + five `auth_request_set` + `uwsgi_param HTTP_X_*` block", which names one exception | There are **two** exceptions, not one. `^~ /proxy/relay/` is also outside the hop and also takes the blanking include, and both exceptions keep `uwsgi_pass relay_py;` rather than `$relay_upstream`. | PR 7's control API is gated by the internal token alone (D9), and `authorize_stream()` would 404 a URI naming no channel — mounting the hop in front of it would break Django→relay control calls the moment PR 7 lands. Neither exception runs a subrequest, so `$relay_name` is unset for them; the `map` default would resolve correctly, but a variable pass nothing feeds is a thing a reader has to disprove. |

No other divergence from the spec exists. One divergence from an **ADR** does, and Task 12 fixes it
rather than recording it: ADR 0005's Consequences bullet says the relay "drops … any direct read of
`M3UAccount`/`OutputProfile` at tune time", which S3 narrows to two primary-key reads. An accepted
ADR that misdescribes the tree is worse than no ADR, so the bullet is amended in this PR.

## File Structure

```
apps/proxy/
  internal_auth.py                          NEW    Two HMAC tokens, the header/META names, and the
                                                   two constant-time request predicates.
  authorize.py                              NEW    authorize_stream(), AuthorizeResult,
                                                   AuthorizeDenied, the surface constants, the
                                                   principal resolvers, resolve_output_profile(),
                                                   mint_client_id(), user_can_access_channel().
  authorize_views.py                        NEW    The AllowAny view nginx calls, its serializers,
                                                   and resolve_authorization() — the marker-or-
                                                   inline helper the stream views use.
  tests/test_internal_auth.py               NEW    Token separation, compare_digest behaviour.
  tests/test_authorize.py                   NEW    The authorize matrix, one test per differing cell.
  tests/test_authorize_view.py              NEW    URI resolution, header emission, status mapping,
                                                   forged-marker rejection, schema presence.
  live_proxy/views.py                       MODIFY stream_ts / stream_xc call resolve_authorization;
                                                   _resolve_output_profile moves out; the copy-
                                                   pasted membership filter (:802-816) is deleted.
  vod_proxy/views.py                        MODIFY stream_vod / stream_xc_movie / stream_xc_episode
                                                   call resolve_authorization; plaintext compares go.
apps/timeshift/views.py                     MODIFY catchup_proxy / _timeshift_proxy_impl call
                                                   resolve_authorization; _authenticate_user and
                                                   _user_can_access_channel move to authorize.py.
apps/channels/tasks.py                      MODIFY _dvr_build_ffmpeg_cmd gains -headers with the
                                                   internal token; new _dvr_redact_cmd for the argv
                                                   debug log at :1738-1741.
apps/channels/tests/test_dvr_internal_principal.py  NEW  The -headers argv shape and _dvr_redact_cmd.
dispatcharr/settings.py                     MODIFY RELAY_DEFAULT_NAME.
dispatcharr/urls.py                         MODIFY path("_dispatcharr/authorize", …).
dispatcharr/utils.py                        MODIFY SENSITIVE_HEADERS gains the two internal headers.
docker/nginx.conf                           MODIFY map + auth_request blocks + blanking includes.
docker/dispatcharr_api_params.conf          NEW    The five-param blanking include.
docker/Dockerfile                           MODIFY One COPY for the include file.
docker/init/03-init-dispatcharr.sh          MODIFY Compute HMAC(SECRET_KEY,"relay-trust") and sed it
                                                   into the RELAY_TRUST_TOKEN placeholder.
e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts  MODIFY  Second and third tests: the
                                                   auth_request block on every relay-bound location,
                                                   and the blanking include everywhere else.
e2e/tests/streaming/authorize-matrix.spec.ts  NEW  The @contract specs for the hop.
e2e/tests/streaming/hidden-channel-streamable.spec.ts  MODIFY  test.fail() → test() (#87).
e2e/tests/streaming/catchup-proxy-mode.spec.ts         MODIFY  test.fail() → test() (#95).
e2e/tests/streaming/xc-vod-playback.spec.ts            MODIFY  test.fail() → test() (#100), which
                                                   this PR closes by construction; the episode-404
                                                   pin (#99) stays inverted.
e2e/COVERAGE.md                             MODIFY One row for the authorize matrix, goal `P1`.
docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md  MODIFY  One Consequences bullet, per S3.
apps/proxy/live_proxy/tests/{test_stream_ts_client_registration,test_ghost_session_cleanup,
  test_live_db_cleanup}.py                  MODIFY Patch the new seam, not the deleted names.
apps/proxy/vod_proxy/tests/{test_vod_redirect,test_vod_db_cleanup}.py  MODIFY  Same.
apps/timeshift/tests/{test_views,test_sessions,test_catchup_redirect}.py  MODIFY  Same; the two
                                                   real-model helper tests move to test_authorize.py.
metrics/curated/defects.yml                 MODIFY Two rows to status fixed.
CLAUDE.md                                   MODIFY Three corrected statements.
docs/superpowers/specs/2026-09-04-phase1-process-split-design.md  MODIFY  Amendments S1-S8.
```

### Task 1: Reset onto merged `main` and re-verify the tree facts

**Files:** Modify none. This task changes no file; it establishes the base every later task edits.
**Interfaces:** Consumes `origin/main` (PR 4 merged, squashed). Produces a worktree whose
`docker/nginx.conf`, `docker/init/03-init-dispatcharr.sh` and `apps/channels/tasks.py` carry PR 4's
content.

- [ ] **Step 1: Confirm PR 4 merged.**
      Run: `gh pr view 175 --repo D10Scot/Dispatcharr --json state,mergedAt -q '.state + " " + (.mergedAt // "null")'`
      Expected: `MERGED <timestamp>`. If it prints `OPEN`, **stop and report** — this plan does not
      execute before PR 4 lands.
- [ ] **Step 2: Reset the branch onto merged `main`.**
      ```bash
      cd /Users/dion/git/Dispatcharr/.worktrees/phase1-pr5
      git fetch origin main
      git status --porcelain
      git reset --hard origin/main
      ```
      Run the three commands in that order. Expected: `git status --porcelain` prints **exactly
      one line**, `?? docs/superpowers/plans/2026-09-05-phase1-pr5-authorize.md` — this plan, which
      is untracked and which `reset --hard` leaves alone. Anything else in that output is someone
      else's work in this worktree: stop and report. After the reset, `git log --oneline -1`
      matches `origin/main`.
- [ ] **Step 3: Re-verify the five file facts this plan cites.**
      Run:
      ```bash
      grep -c 'uwsgi_pass relay_py;' docker/nginx.conf
      grep -n 'RELAY_UPSTREAM' docker/init/03-init-dispatcharr.sh
      grep -n 'def get_dvr_stream_base_url' apps/channels/tasks.py
      grep -n 'RELAY_BOUND_TARGETS' e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts
      grep -n 'supervisorctl' e2e/fixtures/instance.ts | head -3
      ```
      Expected: `11` `uwsgi_pass relay_py;` lines — the nine top-level relay-bound locations plus
      the two Task 9 keeps on a literal group (the nested recordings regex and `^~ /proxy/relay/`),
      which is why Task 9 Step 9 expects `2` of them left afterwards; a `sed -i "s/RELAY_UPSTREAM/…` line
      inside the `all`/`api` role gate; `get_dvr_stream_base_url` defined with a `dev` branch
      returning `127.0.0.1:5656`; `RELAY_BOUND_TARGETS` present; `supervisorctl` present in the
      instance fixture. Any miss means PR 4 landed differently from this plan's assumption —
      report the difference before continuing rather than adapting silently.
- [ ] **Step 4: Start the test container** per § Test environment step 1.
      Run: `docker exec dispatcharr-testrunner-pr5 pg_isready -h /var/run/postgresql`
      Expected: `/var/run/postgresql:5432 - accepting connections`.
- [ ] **Step 5: Record the baseline.**
      Run the four labels this PR must keep green, one at a time, with the § Test environment
      step 4 command: `apps.proxy.tests`, `apps.proxy.live_proxy.tests`, `apps.channels.tests`,
      `apps.timeshift.tests`.
      Expected: all four `OK`. Write the four counts into the task report — a later "was it me?"
      question is unanswerable without them.
- [ ] **Step 6: No commit.** This task produces no diff.

### Task 2: The two internal HMACs and their headers

**Files:** Create `apps/proxy/internal_auth.py`, `apps/proxy/tests/test_internal_auth.py`.
Modify `dispatcharr/utils.py` (`SENSITIVE_HEADERS`, currently at `:65-73`).
Test: `apps/proxy/tests/test_internal_auth.py`, plus the existing redaction tests.
**Interfaces:** Produces `relay_trust_token()`, `internal_principal_token()`,
`request_is_relay_trusted(request)`, `request_is_internal(request)` and the header/META name
constants. Consumed by Tasks 3, 4, 5, 6, 7, 8 and 9.

- [ ] **Step 1: Write the failing test.**
      Create `apps/proxy/tests/test_internal_auth.py`:
      ```python
      """The two internal HMACs (Phase 1 D11) and the predicates that check them."""

      from django.test import SimpleTestCase, override_settings

      from apps.proxy import internal_auth


      class _Req:
          """A request stub: internal_auth only ever reads request.META."""

          def __init__(self, **meta):
              self.META = dict(meta)


      @override_settings(SECRET_KEY="unit-test-secret")
      class InternalAuthTests(SimpleTestCase):
          def test_tokens_are_hex_sha256_digests(self):
              for token in (internal_auth.relay_trust_token(),
                            internal_auth.internal_principal_token()):
                  self.assertEqual(len(token), 64)
                  self.assertTrue(all(c in "0123456789abcdef" for c in token))

          def test_the_two_contexts_produce_different_tokens(self):
              # The whole point of two context strings: a marker leaked through
              # the nginx config cannot be replayed as an internal principal.
              self.assertNotEqual(
                  internal_auth.relay_trust_token(),
                  internal_auth.internal_principal_token(),
              )

          def test_token_changes_with_the_secret_key(self):
              first = internal_auth.relay_trust_token()
              with override_settings(SECRET_KEY="a-different-secret"):
                  self.assertNotEqual(first, internal_auth.relay_trust_token())

          def test_relay_trusted_accepts_the_marker_and_nothing_else(self):
              good = _Req(HTTP_X_DISPATCHARR_AUTHORIZED=internal_auth.relay_trust_token())
              self.assertTrue(internal_auth.request_is_relay_trusted(good))
              for value in ("", "1", "true", internal_auth.internal_principal_token()):
                  with self.subTest(value=value):
                      self.assertFalse(
                          internal_auth.request_is_relay_trusted(
                              _Req(HTTP_X_DISPATCHARR_AUTHORIZED=value)
                          )
                      )

          def test_missing_header_is_not_trusted(self):
              self.assertFalse(internal_auth.request_is_relay_trusted(_Req()))
              self.assertFalse(internal_auth.request_is_internal(_Req()))

          def test_internal_accepts_only_the_internal_token(self):
              good = _Req(HTTP_X_DISPATCHARR_INTERNAL=internal_auth.internal_principal_token())
              self.assertTrue(internal_auth.request_is_internal(good))
              self.assertFalse(
                  internal_auth.request_is_internal(
                      _Req(HTTP_X_DISPATCHARR_INTERNAL=internal_auth.relay_trust_token())
                  )
              )

          def test_a_non_string_header_value_is_rejected_not_raised(self):
              # uWSGI hands strings, but a direct in-process caller may not.
              self.assertFalse(
                  internal_auth.request_is_relay_trusted(_Req(HTTP_X_DISPATCHARR_AUTHORIZED=1))
              )
      ```
- [ ] **Step 2: Run it, expect FAIL.**
      Run: § Test environment step 4 with `apps.proxy.tests.test_internal_auth`.
      Expected: `ModuleNotFoundError: No module named 'apps.proxy.internal_auth'`.
- [ ] **Step 3: Write the module.**
      Create `apps/proxy/internal_auth.py`:
      ```python
      """Two context-separated HMACs of SECRET_KEY, and the headers that carry them.

      Phase 1 D11. Every internal hop in the split authenticates with an HMAC of
      the deployment's own SECRET_KEY, compared with hmac.compare_digest:

        X-Dispatcharr-Authorized = HMAC(SECRET_KEY, "relay-trust")
            nginx sets it on every relay-bound location so the relay will trust
            the X-Relay-* params. It is a secret, not the literal "1", because
            nginx is not always in front of the relay's port: uwsgi's
            http = 0.0.0.0:5656 is published in dev and debug, and the relay's
            own :5657 is reachable from anywhere on a compose network.

        X-Dispatcharr-Internal = HMAC(SECRET_KEY, "internal-principal")
            "this caller is part of this deployment" — the DVR's stream fetch
            here, and /api/relay/... and /proxy/relay/... in PR 6 and PR 7.

      Distinct context strings so a marker leaked through a config file nginx
      reads cannot be replayed as an internal principal.

      Both roles derive the same values because docker/entrypoint.sh generates
      /data/jwt once and every role reads it from the same volume — a deployment
      fact, which is why docker/docker-compose.yml's relay service mounts
      ./data:/data.
      """

      import hashlib
      import hmac

      from django.conf import settings

      RELAY_TRUST_CONTEXT = b"relay-trust"
      INTERNAL_PRINCIPAL_CONTEXT = b"internal-principal"

      # Wire names, for the two producers that spell headers rather than META
      # keys: docker/init/03-init-dispatcharr.sh (nginx) and the DVR's ffmpeg
      # -headers argument.
      HEADER_AUTHORIZED = "X-Dispatcharr-Authorized"
      HEADER_INTERNAL = "X-Dispatcharr-Internal"
      HEADER_RELAY_CHANNEL = "X-Relay-Channel"
      HEADER_RELAY_OUTPUT = "X-Relay-Output"
      HEADER_RELAY_CLIENT = "X-Relay-Client"
      HEADER_RELAY_USER = "X-Relay-User"
      HEADER_RELAY_NAME = "X-Relay-Name"
      # The real status of a denial nginx can only carry as 403. Read back by
      # `auth_request_set $authorize_status $upstream_http_x_authorize_status`
      # and turned into the client's status by `error_page 403 =
      # @authorize_denied`.
      HEADER_AUTHORIZE_STATUS = "X-Authorize-Status"

      # request.META keys, which is how Django sees all of the above.
      META_AUTHORIZED = "HTTP_X_DISPATCHARR_AUTHORIZED"
      META_INTERNAL = "HTTP_X_DISPATCHARR_INTERNAL"
      META_RELAY_CHANNEL = "HTTP_X_RELAY_CHANNEL"
      META_RELAY_OUTPUT = "HTTP_X_RELAY_OUTPUT"
      META_RELAY_CLIENT = "HTTP_X_RELAY_CLIENT"
      META_RELAY_USER = "HTTP_X_RELAY_USER"
      META_ORIGINAL_URI = "HTTP_X_ORIGINAL_URI"


      def _token(context: bytes) -> str:
          secret = (settings.SECRET_KEY or "").encode()
          return hmac.new(secret, context, hashlib.sha256).hexdigest()


      def relay_trust_token() -> str:
          """The value nginx puts in X-Dispatcharr-Authorized."""
          return _token(RELAY_TRUST_CONTEXT)


      def internal_principal_token() -> str:
          """The value an in-deployment caller puts in X-Dispatcharr-Internal."""
          return _token(INTERNAL_PRINCIPAL_CONTEXT)


      def _matches(value, expected: str) -> bool:
          if not isinstance(value, str) or not value or not expected:
              return False
          return hmac.compare_digest(value, expected)


      def request_is_relay_trusted(request) -> bool:
          """True when nginx authorized this request and set the marker itself.

          nginx overrides a client's own header of the same name in every
          relay-bound location and blanks it everywhere else (the 0.8.40
          HTTP_-prefixed *_param rule), so a "" here is a request that was never
          authorized and must fall through to an inline authorize_stream call.
          """
          return _matches(request.META.get(META_AUTHORIZED), relay_trust_token())


      def request_is_internal(request) -> bool:
          """True when the caller proved it holds this deployment's SECRET_KEY."""
          return _matches(request.META.get(META_INTERNAL), internal_principal_token())
      ```
- [ ] **Step 4: Run it, expect PASS.**
      Run: § Test environment step 4 with `apps.proxy.tests.test_internal_auth`.
      Expected: `Ran 7 tests` … `OK`.
- [ ] **Step 5: Mask the two new headers, and the URI that carries XC path credentials.**
      The relay's stream views log `redact_headers(request.headers)` at DEBUG
      (`apps/proxy/vod_proxy/views.py:628`), and from this PR on those headers carry a token
      derived from `SECRET_KEY`. Edit `dispatcharr/utils.py`'s `SENSITIVE_HEADERS`:
      ```python
      SENSITIVE_HEADERS = frozenset(
          {
              "authorization",
              "cookie",
              "x-api-key",
              "proxy-authorization",
              "set-cookie",
              # Phase 1 D11: both are HMACs of SECRET_KEY. Neither is a provider
              # credential, which is what this set was written for, but both
              # would let a reader of a DEBUG log forge the relay's trust marker.
              "x-dispatcharr-authorized",
              "x-dispatcharr-internal",
          }
      )
      ```
      And in the same file, `URL_VALUED_META_KEYS` (`:79-86`) gains the header the authorize hop
      introduces, which carries the Xtream path credentials verbatim
      (`/live/<user>/<pass>/<id>`) into the API process's `request.META`:
      ```python
      URL_VALUED_META_KEYS = frozenset(
          {
              "path-info",
              "query-string",
              "raw-uri",
              "request-uri",
              # X-Original-URI, the URI nginx forwards to the authorize hop. It is
              # the whole request line of the thing being authorized, XC
              # credentials included, so it belongs in the family that goes
              # through redact_url rather than the one that is blanked — the path
              # is the useful part of a log line about a tune.
              "x-original-uri",
          }
      )
      ```
      Nothing logs it today. The safety net should know the name before something does.
- [ ] **Step 6: Test the masking.**
      Append to `apps/proxy/tests/test_internal_auth.py`:
      ```python
      class InternalHeaderRedactionTests(SimpleTestCase):
          def test_redact_headers_masks_both_internal_tokens(self):
              from dispatcharr.utils import redact_headers

              masked = redact_headers(
                  {
                      "X-Dispatcharr-Authorized": "deadbeef",
                      "X-Dispatcharr-Internal": "cafebabe",
                      "X-Relay-Channel": "a-channel-uuid",
                  }
              )
              self.assertNotIn("deadbeef", str(masked))
              self.assertNotIn("cafebabe", str(masked))
              # X-Relay-Channel is a channel uuid, which the product already
              # treats as public-in-URL; it stays readable so a DEBUG log is
              # still worth reading.
              self.assertEqual(masked["X-Relay-Channel"], "a-channel-uuid")

          def test_redact_headers_masks_the_meta_spelling_too(self):
              from dispatcharr.utils import redact_headers

              masked = redact_headers({"HTTP_X_DISPATCHARR_INTERNAL": "cafebabe"})
              self.assertNotIn("cafebabe", str(masked))

          def test_the_original_uri_header_is_redacted_as_a_url(self):
              # It carries the XC path credentials of whatever is being
              # authorized, so it is masked like a URL rather than blanked.
              from dispatcharr.utils import redact_headers

              masked = redact_headers(
                  {"HTTP_X_ORIGINAL_URI": "/live/theuser/thepass/9.ts?token=abc"}
              )
              rendered = str(masked)
              self.assertNotIn("thepass", rendered)
              self.assertIn("/live/", rendered)
      ```
      Run: § Test environment step 4 with `apps.proxy.tests.test_internal_auth`.
      Expected: `Ran 10 tests` … `OK`.
- [ ] **Step 7: Run the guard and the affected labels.**
      Run: `python3 scripts/check_credential_logging.py dispatcharr/utils.py apps/proxy/internal_auth.py`
      Expected: exit 0, no output. Then § Test environment step 4 with `apps.proxy.tests`.
      Expected: `OK`.
- [ ] **Step 8: Commit.**
      Write `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t2.msg` with the Write tool:
      ```
      feat(phase1-pr5): internal HMAC tokens and their headers

      Two context-separated HMACs of SECRET_KEY (D11): "relay-trust" for the
      marker nginx sets on relay-bound locations, "internal-principal" for
      in-deployment callers. Both compared with hmac.compare_digest; neither is
      accepted for the other's context. Both header names join SENSITIVE_HEADERS
      so redact_headers masks them in the VOD path's DEBUG header dump, and
      X-Original-URI — the URI nginx forwards to the authorize hop, XC path
      credentials and all — joins URL_VALUED_META_KEYS so it is redacted as a
      URL rather than printed whole. Nothing logs it yet; the safety net should
      know the name first.
      ```
      Then, in one Bash call:
      `git add apps/proxy/internal_auth.py apps/proxy/tests/test_internal_auth.py dispatcharr/utils.py`
      and, in a **separate** Bash call, the § Test environment step 3 gate followed by
      `git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t2.msg`.

### Task 3: `authorize_stream()` — the whole decision, in one function

**Files:** Create `apps/proxy/authorize.py`, `apps/proxy/tests/test_authorize.py`.
Test: `apps/proxy/tests/test_authorize.py`.
**Interfaces:** Produces `AuthorizeResult`, `AuthorizeDenied`, `INTERNAL_PRINCIPAL`, the six
`SURFACE_*` constants, `authorize_stream(request, surface, *, identifier=None, username=None,
password=None, session_id=None) -> AuthorizeResult`, `resolve_output_profile(request, user)`,
`mint_client_id()`, `user_can_access_channel(user, channel)`, `resolve_xc_user(username, password)`.
Consumes `dispatcharr.utils.network_access_allowed`, `apps.proxy.utils.check_user_stream_limits`,
`apps.proxy.internal_auth`, `apps.accounts.models.User`, `apps.channels.models.Channel`,
`core.models.OutputProfile`, `apps.proxy.live_proxy.url_utils.get_stream_object` (function-local),
`apps.timeshift.sessions.resolve_catchup_playback` (function-local).

Written before any view changes, so the matrix is pinned by unit tests before a single caller moves.

- [ ] **Step 1: Write the surface/denial/result skeleton test.**
      Create `apps/proxy/tests/test_authorize.py` with the imports and the first class:
      ```python
      """The authorize matrix (Phase 1 PR 5), one test per cell that differs.

      Rows are principals; columns are the checks. The four rows that carry the
      behaviour change each have their own class below, and each names why it is
      what it is rather than restating the table.
      """

      from unittest.mock import patch

      from django.test import RequestFactory, TestCase, override_settings

      from apps.accounts.models import User
      from apps.channels.models import Channel, ChannelProfile, ChannelProfileMembership
      from apps.proxy import authorize, internal_auth
      from apps.proxy.authorize import (
          AuthorizeDenied,
          SURFACE_CATCHUP,
          SURFACE_CATCHUP_XC,
          SURFACE_LIVE,
          SURFACE_LIVE_XC,
          SURFACE_VOD,
          SURFACE_VOD_XC,
          authorize_stream,
      )


      class AuthorizeBase(TestCase):
          """Real rows, not mocks: every check here reads a model field, and a
          MagicMock channel would pass every one of them for the wrong reason."""

          @classmethod
          def setUpTestData(cls):
              cls.channel = Channel.objects.create(name="pr5-plain", channel_number=9001)
              cls.hidden = Channel.objects.create(
                  name="pr5-hidden", channel_number=9002, hidden_from_output=True
              )
              cls.adult = Channel.objects.create(
                  name="pr5-adult", channel_number=9003, is_adult=True
              )
              cls.gated = Channel.objects.create(
                  name="pr5-gated", channel_number=9004, user_level=10
              )
              cls.admin = User.objects.create_user(
                  username="pr5-admin", password="x", user_level=User.UserLevel.ADMIN
              )
              cls.standard = User.objects.create_user(
                  username="pr5-standard", password="x", user_level=1
              )
              cls.filtered = User.objects.create_user(
                  username="pr5-filtered",
                  password="x",
                  user_level=1,
                  custom_properties={"hide_adult_content": True},
              )

          def setUp(self):
              self.factory = RequestFactory()

          def _request(self, path="/proxy/ts/stream/x", **meta):
              return self.factory.get(path, **meta)

          def _allow(self, surface, **kwargs):
              """authorize_stream with the network ACL forced open.

              network_access_allowed reads CoreSettings and the client IP; its
              own behaviour is covered by tests/seeded/network-acl.spec.ts and
              by the ACL class below, and leaving it live in every other test
              would make each one a two-variable experiment.
              """
              with patch.object(authorize, "network_access_allowed", return_value=True):
                  return authorize_stream(self._request(), surface, **kwargs)
      ```
- [ ] **Step 2: Run it, expect FAIL.**
      Run: § Test environment step 4 with `apps.proxy.tests.test_authorize`.
      Expected: `ModuleNotFoundError: No module named 'apps.proxy.authorize'`.
- [ ] **Step 3: Write `apps/proxy/authorize.py`.**
      ```python
      """One function decides whether a stream may be served (Phase 1 PR 5, ADR 0005).

      Two callers, never a third:

        * apps/proxy/authorize_views.py's authorize_view, which nginx reaches
          with auth_request once per tune, and
        * resolve_authorization() in the same module, called inline by the seven
          stream views when nginx's trust marker is absent (dev runserver, and
          any deployment shape without nginx in front).

      Same function both ways, so the two paths cannot drift. What this module
      decides — the ACL, the principal, user_level, Channel Profile membership,
      hidden_from_output, is_adult against the user's hide_adult_content, the
      Output Profile and (on the live surfaces) the per-user stream limit — is
      exactly the set of checks that used to be copy-pasted across
      live_proxy/views.py, vod_proxy/views.py and timeshift/views.py.

      What it deliberately does NOT decide:

        * VOD content resolution. The XC movie/series routes resolve an
          M3UMovieRelation/M3UEpisodeRelation to a content uuid inside the view;
          the hop resolves the principal, not the content object.
        * The VOD and catch-up stream limits. Both need an identifier that only
          exists further into their own views (a content uuid from the relation
          above; a <channel>_<programme> media id and a pool-derived client id
          from _serve_catchup's session resolution). Enforcing them here with the
          identifiers available would 429 a legitimate mid-programme seek — the
          sibling exemption in apps/proxy/utils.py matches on exactly those.
      """

      import random
      import time
      from dataclasses import dataclass, field

      from django.conf import settings
      from django.http import Http404

      from apps.accounts.authentication import (
          ApiKeyAuthentication,
          QueryParamJWTAuthentication,
      )
      from apps.accounts.models import User
      from apps.proxy.internal_auth import request_is_internal
      from apps.proxy.utils import check_user_stream_limits
      from dispatcharr.utils import network_access_allowed
      from rest_framework.exceptions import APIException, AuthenticationFailed
      from rest_framework.request import Request
      from rest_framework_simplejwt.authentication import JWTAuthentication

      # --- Surfaces -----------------------------------------------------------
      # One per URL family, because the ACL key, the identifier and the checks
      # differ by family. Not one per view: stream_xc_movie and stream_xc_episode
      # authorize identically.
      SURFACE_LIVE = "live"              # /proxy/ts/stream/<uuid or stream_hash>
      SURFACE_LIVE_XC = "live_xc"        # /live/<u>/<p>/<id> and the bare <u>/<p>/<id>
      SURFACE_CATCHUP = "catchup"        # /proxy/catchup/<uuid>
      SURFACE_CATCHUP_XC = "catchup_xc"  # /timeshift/... and /streaming/timeshift.php
      SURFACE_VOD = "vod"                # /proxy/vod/<type>/<uuid>[/<session>[/<profile>]]
      SURFACE_VOD_XC = "vod_xc"          # /movie/<u>/<p>/<id>.<ext>, /series/...

      ALL_SURFACES = frozenset(
          {
              SURFACE_LIVE,
              SURFACE_LIVE_XC,
              SURFACE_CATCHUP,
              SURFACE_CATCHUP_XC,
              SURFACE_VOD,
              SURFACE_VOD_XC,
          }
      )

      _XC_SURFACES = frozenset({SURFACE_LIVE_XC, SURFACE_CATCHUP_XC, SURFACE_VOD_XC})
      _CHANNEL_SURFACES = frozenset(
          {SURFACE_LIVE, SURFACE_LIVE_XC, SURFACE_CATCHUP, SURFACE_CATCHUP_XC}
      )
      # Surfaces that require a resolved principal. Catch-up has never served an
      # anonymous request (apps/timeshift/views.py answers 401), and the XC
      # families carry credentials in the path by construction. Live is the one
      # that stays anonymous: the channel UUID is the capability, exactly as
      # today, and every cached playlist and tuner URL depends on it (ADR 0005).
      _PRINCIPAL_REQUIRED = frozenset(
          {SURFACE_LIVE_XC, SURFACE_CATCHUP, SURFACE_CATCHUP_XC, SURFACE_VOD_XC}
      )
      # The catch-up XC path is the one surface gated on XC_API rather than
      # STREAMS (apps/timeshift/views.py's _timeshift_proxy_impl). Preserved
      # exactly: an operator who narrowed XC_API expects it to bind here.
      _ACL_KEYS = {SURFACE_CATCHUP_XC: "XC_API"}

      # The union of what the four stream views accept today. /proxy/ts/stream/
      # gains QueryParamJWTAuthentication by this union — a deliberate, small
      # widening that matches what the frontend already does for recordings.
      _AUTHENTICATOR_CLASSES = (
          JWTAuthentication,
          ApiKeyAuthentication,
          QueryParamJWTAuthentication,
      )

      #: The principal for a caller holding X-Dispatcharr-Internal. Not a User:
      #: the DVR has no account, and giving it one would put a real row's
      #: user_level and stream_limit in the path of every recording.
      INTERNAL_PRINCIPAL = object()


      class AuthorizeDenied(Exception):
          """A refusal, carrying the status the client must see.

          401 no principal where one is required, 403 ACL/flag/membership,
          404 nothing resolved for the identifier, 429 stream limit.
          """

          def __init__(self, status: int, detail: str):
              super().__init__(detail)
              self.status = status
              self.detail = detail


      @dataclass(frozen=True)
      class AuthorizeResult:
          """What the hop tells the relay. The five string fields are the five
          X-Relay-* response headers, verbatim; `user` and `trusted` never cross
          the wire and exist only for the inline caller."""

          surface: str
          channel_uuid: str = ""
          output_profile_id: str = ""
          client_id: str = ""
          user_id: str = ""
          relay_name: str = ""
          user: object = None
          trusted: bool = False


      def mint_client_id() -> str:
          """The client id the live path has always minted in the view."""
          return f"client_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"


      def resolve_xc_user(username, password):
          """An Xtream principal, or None. Constant-time compare, plaintext at rest.

          Lifted from apps/timeshift/views.py's _authenticate_user, which already
          used compare_digest; live_proxy and vod_proxy used `!=` and now share
          this one.
          """
          if not username:
              return None
          user = User.objects.filter(username=username).first()
          if user is None:
              return None
          expected = (user.custom_properties or {}).get("xc_password")
          if not expected:
              return None
          import hmac

          if not hmac.compare_digest(str(expected), str(password or "")):
              return None
          return user


      def user_can_access_channel(user, channel) -> bool:
          """Channel Profile membership, unchanged from apps/timeshift/views.py.

          Two bypasses are load-bearing and deliberate: an admin passes, and a
          user with no Channel Profiles at all passes (that is "unrestricted",
          not "restricted to nothing").
          """
          if user.user_level < channel.user_level:
              return False
          if user.user_level >= User.UserLevel.ADMIN:
              return True
          if user.channel_profiles.count() == 0:
              return True
          return (
              type(channel)
              .objects.filter(
                  id=channel.id,
                  channelprofilemembership__enabled=True,
                  channelprofilemembership__channel_profile__in=user.channel_profiles.all(),
              )
              .exists()
          )


      def resolve_output_profile(request, user):
          """?output_profile= then the user's custom_properties. Moved verbatim
          from apps/proxy/live_proxy/views.py:135-151 so the rule has one home."""
          from core.models import OutputProfile

          param = request.GET.get("output_profile")
          if param:
              try:
                  return OutputProfile.objects.get(id=int(param), is_active=True)
              except (OutputProfile.DoesNotExist, ValueError, TypeError):
                  return None
          if user:
              custom = getattr(user, "custom_properties", None) or {}
              profile_id = custom.get("output_profile")
              if profile_id:
                  try:
                      return OutputProfile.objects.get(id=int(profile_id), is_active=True)
                  except (OutputProfile.DoesNotExist, ValueError, TypeError):
                      return None
          return None
      ```
      (continues in Step 4 — one file, split here only so each step stays reviewable.)
- [ ] **Step 4: Append the resolution and decision half of `apps/proxy/authorize.py`.**
      ```python
      def _acl_key(surface: str) -> str:
          return _ACL_KEYS.get(surface, "STREAMS")


      def _drf_user(http_request):
          """The union authenticator set, run explicitly rather than relied upon.

          A fresh rest_framework Request is built over the underlying
          HttpRequest so this behaves identically whether the caller is the
          nginx subrequest view (whose own DRF authentication ran against the
          subrequest's query string) or a stream view calling inline.
          """
          try:
              drf_request = Request(
                  http_request,
                  authenticators=[cls() for cls in _AUTHENTICATOR_CLASSES],
              )
              user = drf_request.user
          except (AuthenticationFailed, APIException):
              return None
          return user if user is not None and user.is_authenticated else None


      def _session_user(http_request):
          """request.user when Django's AuthenticationMiddleware resolved one."""
          user = getattr(http_request, "user", None)
          if user is not None and getattr(user, "is_authenticated", False):
              return user
          return None


      def _catchup_session_user(identifier, session_id):
          """The principal a tokenless catch-up playback URL carries.

          POST /api/catchup/sessions/ mints a session_id bound to a user and a
          programme start; the playback URL then carries no credential at all.
          touch_catchup_session() inside this call is an idempotent TTL refresh,
          so running it here and again in the view is harmless.
          """
          from apps.timeshift.sessions import resolve_catchup_playback

          resolved = resolve_catchup_playback(session_id, identifier)
          if resolved is None:
              return None
          user, _start, _duration = resolved
          return user


      def _resolve_principal(http_request, surface, username, password, identifier, session_id):
          if request_is_internal(http_request):
              return INTERNAL_PRINCIPAL
          if surface in _XC_SURFACES:
              user = resolve_xc_user(username, password)
              if user is None:
                  raise AuthorizeDenied(401, "Invalid credentials")
              return user
          user = _drf_user(http_request) or _session_user(http_request)
          if user is None and surface == SURFACE_CATCHUP and session_id:
              user = _catchup_session_user(identifier, session_id)
          elif user is not None and surface == SURFACE_CATCHUP and session_id:
              # Today's cross-check (apps/timeshift/views.py:313-315): a
              # credentialed request may not drive someone else's session.
              session_user = _catchup_session_user(identifier, session_id)
              if session_user is not None and session_user.id != user.id:
                  raise AuthorizeDenied(403, "Access denied")
          if user is None and surface in _PRINCIPAL_REQUIRED:
              raise AuthorizeDenied(401, "Authentication required")
          return user


      def _resolve_channel(surface, identifier):
          """The channel this tune is for, or None when the surface has none.

          Returns (channel, is_stream_hash). The stream-by-hash case
          (/proxy/ts/stream/<stream_hash>, the admin UI's single-stream preview)
          has no channel at all, so no channel check applies to it — there is
          nothing to apply one to.
          """
          from apps.channels.models import Channel

          if surface == SURFACE_LIVE:
              from apps.proxy.live_proxy.url_utils import get_stream_object

              try:
                  target = get_stream_object(identifier)
              except Http404:
                  raise AuthorizeDenied(404, "Not found") from None
              if isinstance(target, Channel):
                  return target, False
              return None, True
          if surface == SURFACE_CATCHUP:
              channel = Channel.objects.filter(uuid=identifier).first()
          else:
              # The XC families address a channel by its numeric id, with an
              # optional extension the caller has already stripped.
              try:
                  channel = Channel.objects.filter(id=int(identifier)).first()
              except (TypeError, ValueError):
                  channel = None
          if channel is None:
              raise AuthorizeDenied(404, "Not found")
          return channel, False


      def _apply_channel_checks(channel, principal):
          if principal is INTERNAL_PRINCIPAL:
              return
          user = principal
          if user is not None and user.user_level >= User.UserLevel.ADMIN:
              # Before hidden_from_output, deliberately: the admin UI plays any
              # channel from the channels table with the admin's JWT on the
              # request, and 403ing that preview would be a regression, not a
              # fix. _user_can_access_channel granted exactly this bypass
              # already; this generalises it rather than inventing it.
              return
          if channel.hidden_from_output:
              # A property of the channel, needing no principal — which is why
              # this is the one check an anonymous request also fails.
              raise AuthorizeDenied(403, "Forbidden")
          if user is None:
              return
          if user.user_level < channel.user_level:
              raise AuthorizeDenied(403, "Forbidden")
          if channel.is_adult and (getattr(user, "custom_properties", None) or {}).get(
              "hide_adult_content"
          ):
              raise AuthorizeDenied(403, "Forbidden")
          if not user_can_access_channel(user, channel):
              raise AuthorizeDenied(403, "Forbidden")


      def authorize_stream(
          request,
          surface,
          *,
          identifier=None,
          username=None,
          password=None,
          session_id=None,
      ) -> AuthorizeResult:
          """Authorize one tune. Raises AuthorizeDenied; never returns a refusal."""
          if surface not in ALL_SURFACES:
              # Fail closed: an unknown surface means the caller (or the nginx
              # location table) is asking about a URI this function was never
              # written to judge.
              raise AuthorizeDenied(403, "Forbidden")

          http_request = getattr(request, "_request", request)
          principal = _resolve_principal(
              http_request, surface, username, password, identifier, session_id
          )
          user = None if principal is INTERNAL_PRINCIPAL else principal

          if not network_access_allowed(http_request, _acl_key(surface), user):
              raise AuthorizeDenied(403, "Forbidden")

          channel = None
          if surface in _CHANNEL_SURFACES:
              channel, _by_hash = _resolve_channel(surface, identifier)
              if channel is not None:
                  _apply_channel_checks(channel, principal)

          client_id = mint_client_id() if surface in (SURFACE_LIVE, SURFACE_LIVE_XC) else ""

          if user is not None and surface in (SURFACE_LIVE, SURFACE_LIVE_XC):
              media_id = str(channel.uuid) if channel is not None else str(identifier)
              if not check_user_stream_limits(user, client_id, media_id=media_id):
                  raise AuthorizeDenied(
                      429,
                      f"Stream limit exceeded ({user.stream_limit} concurrent streams allowed)",
                  )

          output_profile = resolve_output_profile(http_request, user)

          return AuthorizeResult(
              surface=surface,
              channel_uuid=str(channel.uuid) if channel is not None else "",
              output_profile_id=str(output_profile.id) if output_profile else "",
              client_id=client_id,
              user_id=str(user.id) if user is not None else "",
              relay_name=settings.RELAY_DEFAULT_NAME,
              user=user,
              trusted=False,
          )
      ```
- [ ] **Step 5: Add `RELAY_DEFAULT_NAME` to settings** (needed by Step 4's return).
      In `dispatcharr/settings.py`, beside the other `os.environ.get` reads near `SECRET_KEY`
      (`:26`):
      ```python
      # The relay this deployment's authorize hop names in X-Relay-Name. One
      # relay exists in Phase 1 and the value is always "py"; nginx maps it to
      # an upstream group, so Phase 2's canary is a map entry rather than a code
      # change on either side (ADR 0005).
      RELAY_DEFAULT_NAME = os.environ.get("DISPATCHARR_RELAY_DEFAULT_NAME", "py")
      ```
- [ ] **Step 6: Run the skeleton test, expect the module to import.**
      Run: § Test environment step 4 with `apps.proxy.tests.test_authorize`.
      Expected: `Ran 0 tests in 0.000s` followed by `NO TESTS RAN` — the runner's wording for an
      empty selection, and not `OK`. The point of the step is that the import chain resolves: an
      `ImportError` or `AttributeError` here names the symbol Step 3 or Step 4 left out.
- [ ] **Step 7: Write the matrix tests.**
      Append to `apps/proxy/tests/test_authorize.py`:
      ```python
      class AnonymousRowTests(AuthorizeBase):
          """The row that keeps every cached tuner URL working, and the one flag
          that now applies without a principal."""

          def test_anonymous_streams_an_ordinary_channel_by_uuid(self):
              result = self._allow(SURFACE_LIVE, identifier=str(self.channel.uuid))
              self.assertEqual(result.channel_uuid, str(self.channel.uuid))
              self.assertEqual(result.user_id, "")
              self.assertTrue(result.client_id.startswith("client_"))
              self.assertEqual(result.relay_name, "py")

          def test_anonymous_is_refused_a_hidden_channel(self):
              with self.assertRaises(AuthorizeDenied) as caught:
                  self._allow(SURFACE_LIVE, identifier=str(self.hidden.uuid))
              self.assertEqual(caught.exception.status, 403)

          def test_anonymous_still_streams_an_adult_channel(self):
              # hide_adult_content is a per-user preference; there is no user
              # here, so it is not applicable rather than skipped.
              result = self._allow(SURFACE_LIVE, identifier=str(self.adult.uuid))
              self.assertEqual(result.channel_uuid, str(self.adult.uuid))

          def test_an_unresolvable_identifier_is_404(self):
              with self.assertRaises(AuthorizeDenied) as caught:
                  self._allow(SURFACE_LIVE, identifier="not-a-channel-or-a-hash")
              self.assertEqual(caught.exception.status, 404)


      class AdminRowTests(AuthorizeBase):
          def _as(self, user, surface, **kwargs):
              request = self._request()
              with patch.object(authorize, "network_access_allowed", return_value=True), \
                   patch.object(authorize, "_drf_user", return_value=user):
                  return authorize_stream(request, surface, **kwargs)

          def test_admin_streams_a_hidden_channel(self):
              result = self._as(self.admin, SURFACE_LIVE, identifier=str(self.hidden.uuid))
              self.assertEqual(result.user_id, str(self.admin.id))

          def test_admin_streams_an_adult_channel(self):
              self._as(self.admin, SURFACE_LIVE, identifier=str(self.adult.uuid))

          def test_admin_streams_a_user_level_gated_channel(self):
              self._as(self.admin, SURFACE_LIVE, identifier=str(self.gated.uuid))

          def test_admin_still_hits_the_stream_limit(self):
              # The one check an admin does not bypass: a slot they hold is the
              # same provider slot.
              with patch.object(authorize, "check_user_stream_limits", return_value=False):
                  with self.assertRaises(AuthorizeDenied) as caught:
                      self._as(self.admin, SURFACE_LIVE, identifier=str(self.channel.uuid))
              self.assertEqual(caught.exception.status, 429)


      class NonAdminRowTests(AuthorizeBase):
          def _as(self, user, surface, **kwargs):
              with patch.object(authorize, "network_access_allowed", return_value=True), \
                   patch.object(authorize, "_drf_user", return_value=user):
                  return authorize_stream(self._request(), surface, **kwargs)

          def test_standard_user_is_refused_a_hidden_channel(self):
              with self.assertRaises(AuthorizeDenied) as caught:
                  self._as(self.standard, SURFACE_LIVE, identifier=str(self.hidden.uuid))
              self.assertEqual(caught.exception.status, 403)

          def test_hide_adult_content_user_is_refused_an_adult_channel(self):
              # Issue #87, at the one place every surface goes through.
              with self.assertRaises(AuthorizeDenied) as caught:
                  self._as(self.filtered, SURFACE_LIVE, identifier=str(self.adult.uuid))
              self.assertEqual(caught.exception.status, 403)

          def test_standard_user_still_streams_an_adult_channel_without_the_preference(self):
              self._as(self.standard, SURFACE_LIVE, identifier=str(self.adult.uuid))

          def test_user_level_below_the_channel_is_refused(self):
              with self.assertRaises(AuthorizeDenied) as caught:
                  self._as(self.standard, SURFACE_LIVE, identifier=str(self.gated.uuid))
              self.assertEqual(caught.exception.status, 403)

          def test_membership_filter_applies_when_the_user_has_profiles(self):
              profile = ChannelProfile.objects.create(name="pr5-profile")
              self.standard.channel_profiles.add(profile)
              self.addCleanup(self.standard.channel_profiles.clear)
              ChannelProfileMembership.objects.filter(
                  channel_profile=profile, channel=self.channel
              ).update(enabled=False)
              with self.assertRaises(AuthorizeDenied) as caught:
                  self._as(self.standard, SURFACE_LIVE, identifier=str(self.channel.uuid))
              self.assertEqual(caught.exception.status, 403)


      class InternalPrincipalRowTests(AuthorizeBase):
          """The DVR. No account, no user_level, no profiles — and a recording of
          a hidden or adult channel must not break."""

          def _internal(self, surface, **kwargs):
              request = self._request(
                  HTTP_X_DISPATCHARR_INTERNAL=internal_auth.internal_principal_token()
              )
              with patch.object(authorize, "network_access_allowed", return_value=True):
                  return authorize_stream(request, surface, **kwargs)

          def test_internal_streams_a_hidden_channel(self):
              result = self._internal(SURFACE_LIVE, identifier=str(self.hidden.uuid))
              self.assertEqual(result.channel_uuid, str(self.hidden.uuid))
              self.assertEqual(result.user_id, "")

          def test_internal_streams_an_adult_channel(self):
              self._internal(SURFACE_LIVE, identifier=str(self.adult.uuid))

          def test_internal_skips_the_stream_limit(self):
              with patch.object(authorize, "check_user_stream_limits", return_value=False):
                  self._internal(SURFACE_LIVE, identifier=str(self.channel.uuid))

          def test_internal_does_not_skip_the_network_acl(self):
              request = self._request(
                  HTTP_X_DISPATCHARR_INTERNAL=internal_auth.internal_principal_token()
              )
              with patch.object(authorize, "network_access_allowed", return_value=False):
                  with self.assertRaises(AuthorizeDenied) as caught:
                      authorize_stream(request, SURFACE_LIVE, identifier=str(self.channel.uuid))
              self.assertEqual(caught.exception.status, 403)

          def test_a_wrong_internal_token_is_not_a_principal(self):
              request = self._request(HTTP_X_DISPATCHARR_INTERNAL="deadbeef")
              with patch.object(authorize, "network_access_allowed", return_value=True):
                  with self.assertRaises(AuthorizeDenied) as caught:
                      authorize_stream(request, SURFACE_LIVE, identifier=str(self.hidden.uuid))
              self.assertEqual(caught.exception.status, 403)


      class StreamByHashRowTests(AuthorizeBase):
          """/proxy/ts/stream/<stream_hash> has no channel, so no channel check
          applies — the admin UI's single-stream preview keeps working."""

          # An explicit hash, not one Stream.objects.create() produces: the field
          # is null=True and nothing in save() fills it (apps/channels/models.py
          # :92-98), so a created row's stream_hash is None — and
          # get_stream_object(None) falls through to
          # Stream.objects.get(stream_hash=None), which is an IS NULL match that
          # returns this very row. The test would then pass with the whole hash
          # branch deleted. A literal beats generate_hash_key() here because that
          # classmethod reads CoreSettings for its key list.
          HASH = "a" * 64

          def test_a_stream_hash_authorizes_with_no_channel(self):
              from apps.channels.models import Stream

              stream = Stream.objects.create(
                  name="pr5-stream", url="http://x.invalid/s.ts", stream_hash=self.HASH
              )
              self.assertTrue(stream.stream_hash)
              result = self._allow(SURFACE_LIVE, identifier=stream.stream_hash)
              self.assertEqual(result.channel_uuid, "")


      class XcCredentialRowTests(AuthorizeBase):
          @classmethod
          def setUpTestData(cls):
              super().setUpTestData()
              cls.xc = User.objects.create_user(
                  username="pr5-xc", password="x", user_level=1,
                  custom_properties={"xc_password": "s3cret"},
              )

          def test_correct_credentials_resolve_the_channel_uuid(self):
              result = self._allow(
                  SURFACE_LIVE_XC,
                  identifier=str(self.channel.id),
                  username="pr5-xc",
                  password="s3cret",
              )
              self.assertEqual(result.channel_uuid, str(self.channel.uuid))
              self.assertEqual(result.user_id, str(self.xc.id))

          def test_a_wrong_password_is_401(self):
              with self.assertRaises(AuthorizeDenied) as caught:
                  self._allow(
                      SURFACE_LIVE_XC, identifier=str(self.channel.id),
                      username="pr5-xc", password="wrong",
                  )
              self.assertEqual(caught.exception.status, 401)

          def test_an_unknown_username_is_401_not_404(self):
              # Deliberate: the XC credential surfaces answer 401 for both
              # halves, unlike player_api.php (issue #84, a separate view).
              with self.assertRaises(AuthorizeDenied) as caught:
                  self._allow(
                      SURFACE_LIVE_XC, identifier=str(self.channel.id),
                      username="nobody", password="s3cret",
                  )
              self.assertEqual(caught.exception.status, 401)

          def test_catchup_xc_uses_the_xc_api_acl_key(self):
              with patch.object(authorize, "network_access_allowed", return_value=True) as acl:
                  authorize_stream(
                      self._request(), SURFACE_CATCHUP_XC,
                      identifier=str(self.channel.id),
                      username="pr5-xc", password="s3cret",
                  )
              self.assertEqual(acl.call_args.args[1], "XC_API")

          def test_live_xc_uses_the_streams_acl_key(self):
              with patch.object(authorize, "network_access_allowed", return_value=True) as acl:
                  authorize_stream(
                      self._request(), SURFACE_LIVE_XC,
                      identifier=str(self.channel.id),
                      username="pr5-xc", password="s3cret",
                  )
              self.assertEqual(acl.call_args.args[1], "STREAMS")


      class SurfaceScopeTests(AuthorizeBase):
          def test_vod_surfaces_run_no_channel_check_and_no_limit(self):
              # VOD content is not a Channel; the limit stays in stream_vod
              # (plan amendment S1).
              with patch.object(authorize, "check_user_stream_limits") as limits:
                  result = self._allow(SURFACE_VOD, identifier="ignored")
              limits.assert_not_called()
              self.assertEqual(result.channel_uuid, "")

          def test_catchup_requires_a_principal(self):
              with self.assertRaises(AuthorizeDenied) as caught:
                  self._allow(SURFACE_CATCHUP, identifier=str(self.channel.uuid))
              self.assertEqual(caught.exception.status, 401)

          def test_an_unknown_surface_fails_closed(self):
              with self.assertRaises(AuthorizeDenied) as caught:
                  self._allow("not-a-surface", identifier="x")
              self.assertEqual(caught.exception.status, 403)

          def test_the_output_profile_id_is_resolved_from_the_query(self):
              from core.models import OutputProfile

              profile = OutputProfile.objects.create(name="pr5-out", is_active=True)
              request = self.factory.get(
                  f"/proxy/ts/stream/x?output_profile={profile.id}"
              )
              with patch.object(authorize, "network_access_allowed", return_value=True):
                  result = authorize_stream(
                      request, SURFACE_LIVE, identifier=str(self.channel.uuid)
                  )
              self.assertEqual(result.output_profile_id, str(profile.id))
      ```
- [ ] **Step 8: Run, expect PASS.**
      Run: § Test environment step 4 with `apps.proxy.tests.test_authorize`.
      Expected: all tests `OK`. Two failures are likely first time and both are fixture problems,
      not design problems: `OutputProfile.objects.create(name=…, is_active=True)` may need more
      required fields (read `core/models.py`'s `OutputProfile` and supply them), and
      `ChannelProfileMembership` rows are created by a signal on `Channel.save()` — if the
      `update(enabled=False)` matches zero rows the membership test passes vacuously, so assert
      `self.assertEqual(updated, 1)` on its return value.
- [ ] **Step 9: Move the two real-model helper tests out of the timeshift suite.**
      `apps/timeshift/tests/test_views.py` has a class (around `:1328`, docstring
      "`_authenticate_user` (xc_password custom property) and `_user_can_access_channel`
      (user_level gate) - exercised against real models") whose subject moves to this module.
      Copy the class into `apps/proxy/tests/test_authorize.py`, rename its calls to
      `authorize.resolve_xc_user` / `authorize.user_can_access_channel`, and delete the original.
      Run: § Test environment step 4 with `apps.proxy.tests.test_authorize` and
      `apps.timeshift.tests.test_views`.
      Expected: the moved tests pass in their new home; `test_views.py` still imports (it will not
      be green until Task 7 — record the failure count so Task 7 can show it going to zero).
- [ ] **Step 10: Commit.**
      Write `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t3.msg`:
      ```
      feat(phase1-pr5): authorize_stream, the one decision every stream surface makes

      apps/proxy/authorize.py resolves the principal (internal HMAC, Xtream
      credentials, JWT, API key, query-param JWT, session, anonymous), applies
      the STREAMS/XC_API network ACL, the channel's hidden_from_output, the
      user's hide_adult_content against Channel.is_adult, user_level, Channel
      Profile membership, the Output Profile and — on the live surfaces — the
      per-user stream limit. No caller yet; the views move in the next commits.

      Two rows carry the behaviour change and both are tested: a hidden channel
      is refused even anonymously, and an admin bypasses every channel check but
      not the ACL or the limit. The stream-by-hash surface keeps today's
      behaviour exactly, having no channel to check.
      ```
      `git add apps/proxy/authorize.py apps/proxy/tests/test_authorize.py dispatcharr/settings.py apps/timeshift/tests/test_views.py`
      in one call; the gate then `git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t3.msg` in a separate call.

### Task 4: The `auth_request` view and the marker-or-inline helper

**Files:** Create `apps/proxy/authorize_views.py`, `apps/proxy/tests/test_authorize_view.py`.
Modify `dispatcharr/urls.py` (`urlpatterns`, currently `:13-87`).
**Interfaces:** Produces `authorize_view` (the `AllowAny` DRF view at `/_dispatcharr/authorize`),
`AuthorizeDenialSerializer`, `resolve_authorization(request, surface, **identity)`,
`authorize_error_response(exc)`, `subrequest_error_response(exc)`, `result_from_headers(request,
surface)`. Consumed by Tasks 5, 6, 7 (which use `authorize_error_response`, the true-status form)
and by Task 9's nginx location table (which reads `X-Authorize-Status`).

- [ ] **Step 1: Write the failing test.**
      Create `apps/proxy/tests/test_authorize_view.py`:
      ```python
      """The nginx-facing view, and the trust marker the relay checks."""

      from unittest.mock import patch

      from django.test import Client, TestCase, override_settings

      from apps.accounts.models import User
      from apps.channels.models import Channel
      from apps.proxy import authorize, authorize_views, internal_auth


      class AuthorizeViewTests(TestCase):
          @classmethod
          def setUpTestData(cls):
              cls.channel = Channel.objects.create(name="pr5-view", channel_number=9101)
              cls.hidden = Channel.objects.create(
                  name="pr5-view-hidden", channel_number=9102, hidden_from_output=True
              )
              # stream_limit > 0 is what makes check_user_stream_limits run at
              # all (apps/proxy/utils.py:306), so the 429 test needs a user with
              # one rather than the default 0.
              cls.limited = User.objects.create_user(
                  username="pr5-view-limited", password="x", user_level=1, stream_limit=1
              )

          def setUp(self):
              self.client = Client()

          def _get(self, original_uri, **extra):
              return self.client.get(
                  "/_dispatcharr/authorize",
                  HTTP_X_ORIGINAL_URI=original_uri,
                  **extra,
              )

          def test_a_live_tune_is_200_with_every_relay_header(self):
              response = self._get(f"/proxy/ts/stream/{self.channel.uuid}")
              self.assertEqual(response.status_code, 200)
              self.assertEqual(response["X-Relay-Channel"], str(self.channel.uuid))
              self.assertEqual(response["X-Relay-Name"], "py")
              self.assertTrue(response["X-Relay-Client"].startswith("client_"))
              # Empty, not absent: auth_request_set assigns whatever the header
              # holds, and an absent header leaves the nginx variable unset,
              # which uwsgi_param would then send as the literal string "".
              self.assertEqual(response["X-Relay-User"], "")
              self.assertEqual(response["X-Relay-Output"], "")

          def test_a_hidden_channel_is_403_with_no_status_override(self):
              response = self._get(f"/proxy/ts/stream/{self.hidden.uuid}")
              self.assertEqual(response.status_code, 403)
              self.assertEqual(response["X-Authorize-Status"], "403")

          def test_an_unknown_channel_is_403_carrying_404(self):
              # nginx's auth_request module denies only on 401 and 403 and calls
              # every other status an error, answering the client 500. So a 404
              # decision travels as 403 + X-Authorize-Status, and the
              # relay-bound location's error_page turns it back into a 404.
              response = self._get("/proxy/ts/stream/6f1b0b64-0000-0000-0000-000000000000")
              self.assertEqual(response.status_code, 403)
              self.assertEqual(response["X-Authorize-Status"], "404")

          def test_a_stream_limit_denial_is_403_carrying_429(self):
              with patch.object(authorize, "_drf_user", return_value=self.limited), \
                   patch.object(authorize, "check_user_stream_limits", return_value=False):
                  response = self._get(f"/proxy/ts/stream/{self.channel.uuid}")
              self.assertEqual(response.status_code, 403)
              self.assertEqual(response["X-Authorize-Status"], "429")

          def test_a_401_stays_401(self):
              # The one status nginx passes through as itself, so it must not be
              # collapsed: an XC client with bad credentials has to see 401.
              response = self._get("/live/nobody/wrongpass/1")
              self.assertEqual(response.status_code, 401)

          def test_a_uri_that_resolves_to_a_non_stream_view_is_403(self):
              # Fail closed. Nothing should point auth_request at /api/, but a
              # location-table mistake must not authorize a stream.
              response = self._get("/api/channels/channels/")
              self.assertEqual(response.status_code, 403)

          def test_an_uncatalogued_uri_is_403(self):
              # Not 404: dispatcharr/urls.py's `path("<path:unused_path>", …)`
              # SPA catch-all resolves every path, so resolve() does not raise
              # here — the TemplateView is simply not a stream view, which is the
              # fail-closed 403 above. The Resolver404 branch in the view stays
              # as a guard for a path the converters reject outright.
              response = self._get("/nothing/here/at/all/really")
              self.assertEqual(response.status_code, 403)

          def test_a_missing_original_uri_is_403(self):
              response = self.client.get("/_dispatcharr/authorize")
              self.assertEqual(response.status_code, 403)

          def test_the_query_string_comes_from_the_original_uri(self):
              from core.models import OutputProfile

              profile = OutputProfile.objects.create(name="pr5-view-out", is_active=True)
              response = self._get(
                  f"/proxy/ts/stream/{self.channel.uuid}?output_profile={profile.id}"
              )
              self.assertEqual(response["X-Relay-Output"], str(profile.id))

          def test_a_client_supplied_relay_header_never_reaches_the_decision(self):
              # nginx blanks these on every non-relay location, but the view must
              # not read them regardless: it is reachable in dev without nginx.
              response = self._get(
                  f"/proxy/ts/stream/{self.channel.uuid}",
                  HTTP_X_RELAY_CHANNEL=str(self.hidden.uuid),
                  HTTP_X_RELAY_USER="1",
              )
              self.assertEqual(response["X-Relay-Channel"], str(self.channel.uuid))
              self.assertEqual(response["X-Relay-User"], "")

          def test_the_view_appears_in_the_openapi_schema(self):
              from drf_spectacular.generators import SchemaGenerator

              schema = SchemaGenerator().get_schema(request=None, public=True)
              self.assertIn("/_dispatcharr/authorize", schema["paths"])


      class ResolveAuthorizationTests(TestCase):
          @classmethod
          def setUpTestData(cls):
              cls.channel = Channel.objects.create(name="pr5-trust", channel_number=9103)
              cls.user = User.objects.create_user(username="pr5-trust-user", password="x")

          def setUp(self):
              from django.test import RequestFactory

              self.factory = RequestFactory()

          def test_a_valid_marker_is_trusted_and_skips_authorize_stream(self):
              request = self.factory.get(
                  "/proxy/ts/stream/x",
                  HTTP_X_DISPATCHARR_AUTHORIZED=internal_auth.relay_trust_token(),
                  HTTP_X_RELAY_CHANNEL=str(self.channel.uuid),
                  HTTP_X_RELAY_CLIENT="client_1_2",
                  HTTP_X_RELAY_USER=str(self.user.id),
                  HTTP_X_RELAY_OUTPUT="",
              )
              with patch.object(authorize_views, "authorize_stream") as inline:
                  result = authorize_views.resolve_authorization(
                      request, authorize.SURFACE_LIVE, identifier="x"
                  )
              inline.assert_not_called()
              self.assertTrue(result.trusted)
              self.assertEqual(result.channel_uuid, str(self.channel.uuid))
              self.assertEqual(result.client_id, "client_1_2")
              self.assertEqual(result.user.id, self.user.id)

          def test_a_forged_marker_falls_through_to_the_inline_decision(self):
              request = self.factory.get(
                  "/proxy/ts/stream/x",
                  HTTP_X_DISPATCHARR_AUTHORIZED="1",
                  HTTP_X_RELAY_CHANNEL=str(self.channel.uuid),
              )
              with patch.object(authorize_views, "authorize_stream") as inline:
                  authorize_views.resolve_authorization(
                      request, authorize.SURFACE_LIVE, identifier="x"
                  )
              inline.assert_called_once()

          def test_a_blank_marker_falls_through(self):
              # What every non-relay nginx location sends.
              request = self.factory.get(
                  "/proxy/ts/stream/x", HTTP_X_DISPATCHARR_AUTHORIZED=""
              )
              with patch.object(authorize_views, "authorize_stream") as inline:
                  authorize_views.resolve_authorization(
                      request, authorize.SURFACE_LIVE, identifier="x"
                  )
              inline.assert_called_once()

          def test_a_trusted_user_id_naming_nobody_yields_no_user(self):
              request = self.factory.get(
                  "/proxy/ts/stream/x",
                  HTTP_X_DISPATCHARR_AUTHORIZED=internal_auth.relay_trust_token(),
                  HTTP_X_RELAY_USER="99999999",
              )
              result = authorize_views.resolve_authorization(
                  request, authorize.SURFACE_LIVE, identifier="x"
              )
              self.assertIsNone(result.user)

          def test_the_error_response_carries_the_status_and_a_json_body(self):
              response = authorize_views.authorize_error_response(
                  authorize.AuthorizeDenied(429, "Stream limit exceeded (2 …)")
              )
              self.assertEqual(response.status_code, 429)
              self.assertIn(b"Stream limit exceeded", response.content)
      ```
- [ ] **Step 2: Run it, expect FAIL.**
      Run: § Test environment step 4 with `apps.proxy.tests.test_authorize_view`.
      Expected: `ModuleNotFoundError: No module named 'apps.proxy.authorize_views'`.
- [ ] **Step 3: Write `apps/proxy/authorize_views.py`.**
      ```python
      """The two ways authorize_stream() is reached (Phase 1 PR 5).

      1. authorize_view — what nginx calls with `auth_request` at the internal
         location `= /_dispatcharr/authorize`, once per tune, before it proxies
         a single byte to the relay. It answers 2xx/401/403/404/429 and, on a
         200, carries the decision in five X-Relay-* response headers, which
         nginx copies into variables with auth_request_set (the only context in
         which a subrequest's response headers are readable) and re-emits toward
         the relay as uwsgi_param HTTP_X_RELAY_* values.

      2. resolve_authorization — what each stream view calls. It trusts nginx's
         answer only when X-Dispatcharr-Authorized carries
         HMAC(SECRET_KEY, "relay-trust"); otherwise it authorizes inline, which
         is what makes `manage.py runserver` and any nginx-less shape behave
         identically. Same function underneath, so the two cannot drift.
      """

      from django.http import JsonResponse
      from django.urls import Resolver404, resolve
      from drf_spectacular.utils import OpenApiResponse, extend_schema
      from rest_framework import serializers
      from rest_framework.decorators import api_view, authentication_classes, permission_classes
      from rest_framework.permissions import AllowAny
      from rest_framework.response import Response
      from urllib.parse import urlsplit

      from apps.accounts.models import User
      from apps.proxy.authorize import (
          SURFACE_CATCHUP,
          SURFACE_CATCHUP_XC,
          SURFACE_LIVE,
          SURFACE_LIVE_XC,
          SURFACE_VOD,
          SURFACE_VOD_XC,
          AuthorizeDenied,
          AuthorizeResult,
          authorize_stream,
      )
      from apps.proxy.internal_auth import (
          HEADER_AUTHORIZE_STATUS,
          HEADER_RELAY_CHANNEL,
          HEADER_RELAY_CLIENT,
          HEADER_RELAY_NAME,
          HEADER_RELAY_OUTPUT,
          HEADER_RELAY_USER,
          META_ORIGINAL_URI,
          META_RELAY_CHANNEL,
          META_RELAY_CLIENT,
          META_RELAY_OUTPUT,
          META_RELAY_USER,
          request_is_relay_trusted,
      )


      class AuthorizeDenialSerializer(serializers.Serializer):
          """The body of every non-2xx answer from the hop."""

          error = serializers.CharField()


      def authorize_error_response(exc: AuthorizeDenied) -> JsonResponse:
          """A refusal with its true status. Used by the stream views (inline)."""
          serializer = AuthorizeDenialSerializer({"error": exc.detail})
          return JsonResponse(serializer.data, status=exc.status)


      def subrequest_error_response(exc: AuthorizeDenied) -> JsonResponse:
          """A refusal shaped for what nginx's auth_request module can carry.

          The module allows on 2xx, denies verbatim on 401 and 403, and treats
          every other status as an error — answering the client 500. A 404 or
          429 sent from here would therefore reach a viewer as 500: an unknown
          channel id in a cached playlist, and a user over their stream limit,
          both turning into "something broke".

          So every non-401 denial leaves as 403 with the real code in
          X-Authorize-Status, and each relay-bound location's
          `error_page 403 = @authorize_denied` restores it. 401 is passed
          through as itself, being the other status the module carries.
          """
          status = exc.status if exc.status == 401 else 403
          serializer = AuthorizeDenialSerializer({"error": exc.detail})
          response = JsonResponse(serializer.data, status=status)
          response[HEADER_AUTHORIZE_STATUS] = str(exc.status)
          return response


      def result_from_headers(request, surface: str) -> AuthorizeResult:
          """Rebuild the decision nginx already made, from the params it set.

          Only ever called after request_is_relay_trusted(), so every value here
          was written by nginx: the HTTP_-prefixed uwsgi_param override means a
          client's own header of the same name was replaced, and every non-relay
          location blanks all five.
          """
          from django.conf import settings

          user_id = (request.META.get(META_RELAY_USER) or "").strip()
          user = None
          if user_id:
              user = User.objects.filter(id=user_id).first()
          return AuthorizeResult(
              surface=surface,
              channel_uuid=(request.META.get(META_RELAY_CHANNEL) or "").strip(),
              output_profile_id=(request.META.get(META_RELAY_OUTPUT) or "").strip(),
              client_id=(request.META.get(META_RELAY_CLIENT) or "").strip(),
              user_id=str(user.id) if user is not None else "",
              relay_name=settings.RELAY_DEFAULT_NAME,
              user=user,
              trusted=True,
          )


      def resolve_authorization(request, surface: str, **identity) -> AuthorizeResult:
          """Trust nginx's decision, or make it here. Raises AuthorizeDenied."""
          http_request = getattr(request, "_request", request)
          if request_is_relay_trusted(http_request):
              return result_from_headers(http_request, surface)
          return authorize_stream(http_request, surface, **identity)


      # --- The nginx-facing view ---------------------------------------------
      #
      # The subrequest's own URI is /_dispatcharr/authorize, so the URI being
      # authorized arrives in X-Original-URI ($request_uri, which nginx copies
      # from the parent request and which includes the query string). Rather
      # than re-deriving each surface's URL shape here — a second copy of the
      # urlconf, guaranteed to drift — the path is handed to Django's own
      # resolver and the resulting view function names the surface.

      def _surface_for(match):
          view = getattr(match.func, "cls", None) or match.func
          name = getattr(view, "__name__", "")
          kwargs = dict(match.kwargs)
          if name == "stream_ts":
              return SURFACE_LIVE, {"identifier": kwargs.get("channel_id")}
          if name == "stream_xc":
              raw = str(kwargs.get("channel_id") or "")
              return SURFACE_LIVE_XC, {
                  # stream_xc itself does pathlib.Path(channel_id).stem; the
                  # extension only chooses the output format, never the channel.
                  "identifier": raw.rsplit(".", 1)[0] if "." in raw else raw,
                  "username": kwargs.get("username"),
                  "password": kwargs.get("password"),
              }
          if name == "catchup_proxy":
              return SURFACE_CATCHUP, {"identifier": str(kwargs.get("channel_id") or "")}
          if name in ("timeshift_proxy", "timeshift_proxy_query"):
              return SURFACE_CATCHUP_XC, _timeshift_identity(name, kwargs)
          if name == "stream_vod":
              return SURFACE_VOD, {
                  "identifier": str(kwargs.get("content_id") or ""),
                  "session_id": kwargs.get("session_id"),
              }
          if name in ("stream_xc_movie", "stream_xc_episode"):
              return SURFACE_VOD_XC, {
                  "identifier": str(kwargs.get("stream_id") or ""),
                  "username": kwargs.get("username"),
                  "password": kwargs.get("password"),
              }
          return None, {}


      def _timeshift_identity(name, kwargs):
          if name == "timeshift_proxy":
              raw = str(kwargs.get("channel_id") or "")
              return {
                  "identifier": raw[:-3] if raw.endswith(".ts") else raw,
                  "username": kwargs.get("username"),
                  "password": kwargs.get("password"),
              }
          # The QUERY layout carries its credentials and channel in the query
          # string, which the view reads the same way; this function is handed
          # the parsed query by authorize_view.
          return {}


      @extend_schema(
          operation_id="internal_authorize_stream",
          description=(
              "Internal. nginx calls this with `auth_request` once per tune, at an "
              "`internal;` location, and copies the `X-Relay-*` response headers "
              "toward the relay. Not part of the client API; documented so the "
              "route is discoverable and so the schema records the status "
              "vocabulary the location table depends on."
          ),
          responses={
              200: OpenApiResponse(description="Authorized; the decision is in the X-Relay-* headers."),
              401: AuthorizeDenialSerializer,
              403: OpenApiResponse(
                  response=AuthorizeDenialSerializer,
                  description=(
                      "Denied. X-Authorize-Status carries the real code — 403, or the 404 or "
                      "429 nginx's auth_request module cannot transport, which the "
                      "relay-bound location's error_page restores."
                  ),
              ),
          },
          tags=["internal"],
      )
      @api_view(["GET", "HEAD"])
      @authentication_classes([])
      @permission_classes([AllowAny])
      def authorize_view(request):
          # Every refusal from this view goes through subrequest_error_response,
          # never authorize_error_response: this is the nginx-facing form, and
          # nginx can only carry 401 and 403.
          original = request.META.get(META_ORIGINAL_URI) or ""
          if not original:
              return subrequest_error_response(AuthorizeDenied(403, "Forbidden"))

          split = urlsplit(original)
          http_request = request._request
          # The subrequest inherits the parent's args, but this makes the query
          # string a property of X-Original-URI rather than of nginx's subrequest
          # semantics — which is what lets ?token=, ?session_id= and
          # ?output_profile= behave identically here and in the view.
          http_request.META["QUERY_STRING"] = split.query
          http_request.GET = _query_dict(split.query)

          try:
              match = resolve(split.path)
          except Resolver404:
              return subrequest_error_response(AuthorizeDenied(404, "Not found"))

          surface, identity = _surface_for(match)
          if surface is None:
              return subrequest_error_response(AuthorizeDenied(403, "Forbidden"))
          if surface == SURFACE_CATCHUP_XC and not identity:
              identity = {
                  "identifier": (http_request.GET.get("stream") or "").removesuffix(".ts"),
                  "username": http_request.GET.get("username"),
                  "password": http_request.GET.get("password"),
              }
          if surface == SURFACE_CATCHUP:
              identity["session_id"] = http_request.GET.get("session_id")

          try:
              result = authorize_stream(http_request, surface, **identity)
          except AuthorizeDenied as exc:
              return subrequest_error_response(exc)

          response = Response(status=200)
          response[HEADER_RELAY_CHANNEL] = result.channel_uuid
          response[HEADER_RELAY_OUTPUT] = result.output_profile_id
          response[HEADER_RELAY_CLIENT] = result.client_id
          response[HEADER_RELAY_USER] = result.user_id
          response[HEADER_RELAY_NAME] = result.relay_name
          return response


      def _query_dict(query: str):
          from django.http import QueryDict

          return QueryDict(query, mutable=False)
      ```
- [ ] **Step 4: Mount the route.**
      In `dispatcharr/urls.py`, add the import beside the other stream-view imports (`:8-11`) and
      the route **before** the two XC `re_path`s (a two-segment path cannot collide with the
      three-segment XC form, but keeping every non-SPA route above the catch-all is the file's own
      convention):
      ```python
      from apps.proxy.authorize_views import authorize_view
      ```
      ```python
          # Internal: nginx's auth_request target (Phase 1 PR 5, ADR 0005). The
          # nginx location is `internal;`, so this is unreachable from outside
          # the container in every shape that runs nginx; in dev, where nothing
          # runs nginx, the stream views authorize inline and never call it.
          path("_dispatcharr/authorize", authorize_view, name="authorize"),
      ```
      Place it immediately after the `path("proxy", RedirectView…)` line (`:30`).
- [ ] **Step 5: Run, expect PASS.**
      Run: § Test environment step 4 with `apps.proxy.tests.test_authorize_view`.
      Expected: `OK`. If `test_the_view_appears_in_the_openapi_schema` fails, the view is being
      excluded by drf-spectacular's default filtering — add `@extend_schema(exclude=False)` is
      **not** the fix; check `SPECTACULAR_SETTINGS` in `dispatcharr/settings.py` for a
      `SERVE_URLCONF`/preprocessing hook that drops non-`/api/` paths, and if one exists, record it
      in the task report and assert the route in the urlconf instead of in the schema (the
      convention's intent is that a route is discoverable, and a preprocessing hook that excludes
      the site root by design is not something this PR should change).
- [ ] **Step 6: Commit.**
      Write `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t4.msg`:
      ```
      feat(phase1-pr5): the auth_request view and the marker-or-inline helper

      /_dispatcharr/authorize resolves the URI it is handed in X-Original-URI
      through Django's own resolver — so no second copy of the urlconf exists —
      names the surface from the resolved view, and answers 200 with five
      X-Relay-* headers or a denial.

      Denials leave as 401 or 403 only, with the real code in
      X-Authorize-Status. nginx's auth_request module denies verbatim on those
      two and calls every other status an error, answering the client 500 — so
      a 404 (unknown channel id in a cached playlist) or a 429 (stream limit)
      sent as itself would reach a viewer as 500. The location table restores
      them with error_page; the inline path keeps the true status throughout.

      resolve_authorization() is what the stream views will call: it trusts the
      nginx decision only when X-Dispatcharr-Authorized verifies against
      HMAC(SECRET_KEY, "relay-trust"), and otherwise authorizes inline. A blank
      or forged marker falls through to the inline path, which is the correct
      outcome for every non-relay location and for dev runserver.
      ```
      `git add apps/proxy/authorize_views.py apps/proxy/tests/test_authorize_view.py dispatcharr/urls.py`
      then the gate and `git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t4.msg` in a separate call.

### Task 5: The live views authorize once, in one place

**Files:** Modify `apps/proxy/live_proxy/views.py` (imports `:15-44`, `_resolve_output_profile`
`:135-151`, `stream_ts` `:154-199` and `:544-545`, `:651-652`, `:688-690`, `stream_xc` `:776-831`).
Test: `apps/proxy/live_proxy/tests/test_stream_ts_client_registration.py` (22 patch sites),
`apps/proxy/live_proxy/tests/test_ghost_session_cleanup.py` (10),
`apps/proxy/live_proxy/tests/test_live_db_cleanup.py` (7).
**Interfaces:** Consumes `resolve_authorization`, `authorize_error_response`,
`AuthorizeDenied`, `SURFACE_LIVE`, `SURFACE_LIVE_XC`, `resolve_output_profile`.
Produces `stream_ts(request, channel_id, user=None, force_output_format=None, decision=None)`.

- [ ] **Step 1: Rewrite `stream_ts`'s prologue.**
      Replace the import block's three now-unused names and the inline gates. In
      `apps/proxy/live_proxy/views.py`:
      - `:15` delete `from django.shortcuts import get_object_or_404` (its only two uses are in
        the `stream_xc` block deleted in Step 3).
      - `:20` becomes `from dispatcharr.utils import get_client_ip`.
      - `:22` delete `from apps.channels.models import Channel` (same reason).
      - `:23` delete `from apps.accounts.models import User` (same reason).
      - `:44` delete `from apps.proxy.utils import check_user_stream_limits`.
      - `:3` delete `import random` (its only use is the client-id mint, which moves).
      - add:
        ```python
        from apps.proxy.authorize import (
            SURFACE_LIVE,
            SURFACE_LIVE_XC,
            AuthorizeDenied,
            mint_client_id,
            resolve_output_profile,
        )
        from apps.proxy.authorize_views import authorize_error_response, resolve_authorization
        ```
        `import time` stays (five other uses at `:298-356`); only `random` goes, whose sole use
        was the client-id mint.
      - `:135-151` delete `_resolve_output_profile` entirely and add, in its place:
        ```python
        def _output_profile_for(decision, request, user):
            """The Output Profile this tune runs under.

            When nginx authorized the request, Django already applied the rule
            (?output_profile= then the user's custom_properties) and put the id
            in X-Relay-Output; the row is re-read here because
            OutputProfile.build_command() is model behaviour the relay needs and
            a header cannot carry a built ffmpeg command. Without a trusted
            marker — dev runserver, or any request that did not come through a
            relay-bound location — the same rule runs inline.
            """
            from core.models import OutputProfile

            if decision is not None and decision.trusted:
                if not decision.output_profile_id:
                    return None
                return OutputProfile.objects.filter(
                    id=decision.output_profile_id, is_active=True
                ).first()
            return resolve_output_profile(request, user)
        ```
      - `stream_ts`'s signature and prologue (`:154-199`) become:
        ```python
        @api_view(["GET"])
        @permission_classes([AllowAny])
        def stream_ts(request, channel_id, user=None, force_output_format=None, decision=None):
            """Stream TS data to client with immediate response and keep-alive packets during initialization"""
            if decision is None:
                # `decision` is supplied only by stream_xc, which authorized this
                # same tune under its own surface a moment ago; re-running the hop
                # would re-check a limit that has not changed and mint a second
                # client id.
                try:
                    decision = resolve_authorization(
                        request, SURFACE_LIVE, identifier=channel_id
                    )
                except AuthorizeDenied as exc:
                    return authorize_error_response(exc)
            if user is None:
                user = decision.user

            client_user_agent = None
            proxy_server = ProxyServer.get_instance()
            connection_allocated = False  # Track if connection slot was allocated via get_stream()
            # Initialized before the try so the exception handler can always safely
            # check/clean it up, regardless of where in the setup a failure occurs.
            _client_pre_registered = False
            channel = None
            client_id = None
            channel_display_name = None

            try:
                channel = get_stream_object(channel_id)
                channel_display_name = getattr(channel, "name", None)

                # Minted by the authorize hop (apps/proxy/authorize.py), so the id
                # nginx put in X-Relay-Client is the id this worker registers.
                client_id = decision.client_id or mint_client_id()
                client_ip = get_client_ip(request)
                logger.info(f"[{client_id}] Requested stream for channel {channel_id}")
        ```
        Import `mint_client_id` alongside the other `apps.proxy.authorize` names. Everything from
        `# Extract client user agent early` onward is unchanged **except** that the
        `if user: if not check_user_stream_limits(...)` block (`:192-197`) is deleted — the limit
        now runs in the hop, for both the nginx path and the inline path.
- [ ] **Step 2: Point the three output-profile resolutions at the new helper.**
      `:544`, `:651` and any other `_resolve_output_profile(request, user)` call becomes
      `_output_profile_for(decision, request, user)`. `_resolve_output_format(user,
      force_output_format, request)` is unchanged and stays in this module: the output *format*
      is not part of the header contract, and its `force` argument comes from the XC extension the
      view already parsed.
      Run: `grep -n "_resolve_output_profile\|_output_profile_for" apps/proxy/live_proxy/views.py`
      Expected: no `_resolve_output_profile` remains; two `_output_profile_for` calls.
- [ ] **Step 3: Rewrite `stream_xc`.**
      Replace `:776-831` with:
      ```python
      @api_view(["GET"])
      @permission_classes([AllowAny])
      def stream_xc(request, username, password, channel_id):
          try:
              extension = pathlib.Path(channel_id).suffix
              stream_id = pathlib.Path(channel_id).stem

              try:
                  decision = resolve_authorization(
                      request,
                      SURFACE_LIVE_XC,
                      identifier=stream_id,
                      username=username,
                      password=password,
                  )
              except AuthorizeDenied as exc:
                  return authorize_error_response(exc)

              if extension.lower() == '.mp4':
                  force_format = 'fmp4'
              elif extension.lower() == '.ts':
                  force_format = 'mpegts'
              else:
                  force_format = None
              # X-Relay-Channel is the uuid the hop resolved from the numeric
              # Xtream id — the lookup that used to be a copy of the channel
              # authorization filter, applied here for the fourth time in the
              # tree.
              return stream_ts(
                  request._request,
                  decision.channel_uuid,
                  decision.user,
                  force_output_format=force_format,
                  decision=decision,
              )
          except Http404:
              raise
          finally:
              # stream_ts releases on its own paths; the hop's ORM work is done
              # by the time this returns.
              close_old_connections()
      ```
      This deletes the `user_level__lte` + `channelprofilemembership__enabled` filter
      (`:800-816`), which is one of the two streaming-path copies of that filter the spec's
      corrected count says PR 5 removes. Note the status change it implies: an Xtream client
      asking for a channel it may not see now gets **403 from the hop** rather than the
      `{"error": "Not found"}` 404 this block produced. Both are refusals, the E2E pin at
      `hidden-channel-streamable.spec.ts:151` accepts either, and 403 is the honest one — the
      channel exists.
- [ ] **Step 4: Run the three affected test modules, expect FAIL.**
      Run: § Test environment step 4 with `apps.proxy.live_proxy.tests`.
      Expected: errors of the shape
      `AttributeError: <module 'apps.proxy.live_proxy.views'> does not have the attribute 'network_access_allowed'`
      (and `_resolve_output_profile`). Count them; Step 5 drives the count to zero.
- [ ] **Step 5: Repoint the patch sites at the new seam.**
      In each of `test_stream_ts_client_registration.py`, `test_ghost_session_cleanup.py` and
      `test_live_db_cleanup.py`:
      - Replace `@patch("apps.proxy.live_proxy.views.network_access_allowed", return_value=True)`
        with `@patch("apps.proxy.live_proxy.views.resolve_authorization")` **and** delete the
        corresponding positional parameter's old name from the test signature, adding the new mock
        parameter in the same position (decorators apply bottom-up; the parameter order must
        follow).
      - Replace `@patch("apps.proxy.live_proxy.views._resolve_output_profile", return_value=None)`
        with `@patch("apps.proxy.live_proxy.views._output_profile_for", return_value=None)`; where
        the decorator has no `return_value`, keep it that way.
      - Give the `resolve_authorization` mock a real decision, once, via a helper added to each
        file:
        ```python
        def _decision(user=None, client_id="client_test_1", channel_uuid=""):
            """The authorize hop's answer, as the views now receive it."""
            from apps.proxy.authorize import SURFACE_LIVE, AuthorizeResult

            return AuthorizeResult(
                surface=SURFACE_LIVE,
                channel_uuid=channel_uuid,
                client_id=client_id,
                user_id=str(user.id) if user is not None else "",
                relay_name="py",
                user=user,
            )
        ```
        and set `authorize_mock.return_value = _decision()` in each test body (or
        `@patch(..., return_value=_decision())` where the decorator form reads better).
      - Any test asserting a 403 from the ACL becomes
        `authorize_mock.side_effect = AuthorizeDenied(403, "Forbidden")`.
      Run: § Test environment step 4 with `apps.proxy.live_proxy.tests`.
      Expected: `OK`, with the same test count as Task 1 Step 5 recorded.
- [ ] **Step 6: Run the labels this task can break.**
      Run: § Test environment step 4 with `apps.proxy.tests`, then `apps.proxy.live_proxy.tests`,
      then `apps.channels.tests` (the `_PATH_ALIASES` entry for `apps/proxy/live_proxy/` routes
      changes here to both).
      Expected: three `OK`s.
- [ ] **Step 7: Commit.**
      Write `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t5.msg`:
      ```
      refactor(phase1-pr5): stream_ts and stream_xc authorize through the hop

      Both views call resolve_authorization() first and delete what they used to
      do inline: the STREAMS ACL, the plaintext xc_password compare, the
      copy-pasted user_level/profile-membership filter, the per-user stream
      limit and the Output Profile lookup. stream_xc hands its decision to
      stream_ts rather than making it twice.

      An Xtream client asking for a channel it may not see now gets 403 from the
      hop rather than the 404 the deleted filter produced; the channel exists,
      and the refusal now says so.
      ```
      `git add apps/proxy/live_proxy/views.py apps/proxy/live_proxy/tests/test_stream_ts_client_registration.py apps/proxy/live_proxy/tests/test_ghost_session_cleanup.py apps/proxy/live_proxy/tests/test_live_db_cleanup.py`
      then the gate and `git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t5.msg` in a separate call.

### Task 6: The VOD views authorize through the hop

**Files:** Modify `apps/proxy/vod_proxy/views.py` (`stream_vod` `:609-624` and `:769-786`,
`stream_xc_movie` `:1391-1426`, `stream_xc_episode` `:1428-1460`).
Test: `apps/proxy/vod_proxy/tests/test_vod_redirect.py` (9 sites),
`apps/proxy/vod_proxy/tests/test_vod_db_cleanup.py` (1).
**Interfaces:** Consumes `resolve_authorization`, `authorize_error_response`, `AuthorizeDenied`,
`SURFACE_VOD`, `SURFACE_VOD_XC`. Produces `stream_vod(..., decision=None)`.

- [ ] **Step 1: Rewrite `stream_vod`'s prologue.**
      In `apps/proxy/vod_proxy/views.py`, `:26` keeps `redact_headers, redact_url` and drops
      `network_access_allowed`; add the authorize imports. `:613-624` becomes:
      ```python
      def stream_vod(request, content_type, content_id, session_id=None, profile_id=None,
                     user=None, decision=None):
          """
          Stream VOD content (movies or series episodes) with session-based connection reuse

          Args:
              content_type: 'movie', 'series', or 'episode'
              content_id: ID of the content
              session_id: Optional session ID from URL path (for persistent connections)
              profile_id: Optional M3U profile ID for authentication
              decision: the authorize hop's answer, when an XC entry point already
                  made it for this same request
          """
          if decision is None:
              try:
                  decision = resolve_authorization(
                      request, SURFACE_VOD, identifier=str(content_id), session_id=session_id
                  )
              except AuthorizeDenied as exc:
                  return authorize_error_response(exc)
          if user is None:
              user = decision.user
      ```
      The Redis `vod_session_user:` fallback at `:769-778` **stays**: it resolves a user for a
      request whose token was stripped from a redirect URL, and the hop reproduces it only for the
      native route (`SURFACE_VOD` passes `session_id` through). Leaving it makes the two paths
      agree without the hop having to know the VOD session key layout.
- [ ] **Step 2: Leave the VOD stream limit where it is.**
      `:780-786`'s `check_user_stream_limits(user, session_id, media_id=content_id)` is unchanged
      (plan amendment S1). Add the one-line reason above it:
      ```python
              # Not moved to the authorize hop: the XC movie/series routes resolve
              # content_id from an M3U relation inside this view, so the hop has no
              # media_id to check for two of this function's three entry points.
      ```
- [ ] **Step 3: Rewrite the two XC entry points.**
      For `stream_xc_movie` (`:1391-1426`), replace the four gate statements — the bare
      `network_access_allowed`, the `get_object_or_404(User, …)`, the second
      `network_access_allowed(..., user)` and the two-step `xc_password` compare — with:
      ```python
      @api_view(["GET"])
      @permission_classes([AllowAny])
      def stream_xc_movie(request, username, password, stream_id, extension):
          from apps.vod.models import M3UMovieRelation

          session_id = request.GET.get('session_id')
          profile_id = request.GET.get('profile_id')

          try:
              decision = resolve_authorization(
                  request,
                  SURFACE_VOD_XC,
                  identifier=str(stream_id),
                  username=username,
                  password=password,
                  session_id=session_id,
              )
          except AuthorizeDenied as exc:
              return authorize_error_response(exc)

          # Content resolution stays here on purpose: the hop resolves the
          # principal, not the content object (spec § ORM reads that remain).
          filters = {"movie_id": stream_id, "m3u_account__is_active": True}
          try:
              movie_relation = M3UMovieRelation.objects.select_related('movie').filter(
                  **filters
              ).order_by('-m3u_account__priority', 'id').first()
              if not movie_relation:
                  return JsonResponse({"error": "Movie not found"}, status=404)
          except (M3UMovieRelation.DoesNotExist, M3UMovieRelation.MultipleObjectsReturned):
              return JsonResponse({"error": "Movie not found"}, status=404)

          return stream_vod(
              request._request, 'movie', movie_relation.movie.uuid, session_id, profile_id,
              decision.user, decision=decision,
          )
      ```
      Apply the identical shape to `stream_xc_episode` with `M3UEpisodeRelation`, `episode_id`
      and `'episode'`, keeping its existing `except M3UEpisodeRelation.DoesNotExist` branch as it
      is. Both keep `@permission_classes([AllowAny])`.
      **This closes issue #100, whether or not the PR set out to.** Both routes' wrong-password
      branches read `return Response({"error": "Invalid credentials"}, status=401)`, and neither
      module imports `Response` — verified: `grep -n "^from rest_framework" apps/proxy/vod_proxy/views.py`
      shows the decorators and nothing else — so every wrong credential raises
      `NameError: name 'Response' is not defined` and the client gets a 500. Deleting those
      branches in favour of the hop's 401 makes
      `xc-vod-playback.spec.ts:181`'s pin pass, and Playwright reports an unexpected pass as a
      **failure** of the `streaming` project. Step 5 therefore flips it rather than checking it.
- [ ] **Step 3b: Flip the #100 pin.**
      In `e2e/tests/streaming/xc-vod-playback.spec.ts`, change `test.fail(` at `:181` to `test(`
      and rewrite its comment:
      ```typescript
      // Closed by Phase 1 PR 5. The wrong-password branch that raised
      // `NameError: name 'Response' is not defined` — and answered 500 — is
      // gone: `stream_xc_movie` now resolves its principal through
      // `resolve_authorization`, and the hop's refusal is a real 401.
      //
      // Issue: https://github.com/D10Scot/Dispatcharr/issues/100 — closed by
      // this PR, which is also why it is listed in the PR body beside #87 and
      // #95. The body already asserts `toBe(401)`, so uninverting it asserts
      // the fix rather than passing vacuously.
      ```
      The **episode-404 pin (#99) stays inverted**: Step 3 keeps `stream_xc_episode`'s
      `except M3UEpisodeRelation.DoesNotExist` branch exactly as it is, and that guard is dead
      (`.first()` returns `None` and never raises), so the next line still dereferences
      `episode_relation.episode` and still answers 500 for an unknown episode id. One guard clause
      would close it; adding one is a different change with a different subject.
- [ ] **Step 4: Update the VOD tests.**
      Replace `@patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)`
      with `@patch("apps.proxy.vod_proxy.views.resolve_authorization")` in
      `test_vod_redirect.py` and `test_vod_db_cleanup.py`, giving each mock an `AuthorizeResult`
      the way Task 5 Step 5 does (surface `SURFACE_VOD`, `user=None` unless the test's subject is
      a user).
      Run: § Test environment step 4 with `apps.proxy.vod_proxy.tests`.
      Expected: `OK`.
- [ ] **Step 5: Run both VOD pins and confirm they land where Step 3b says.**
      Run, against the worktree's own E2E stack (§ Test environment step 6), one exact title at a
      time:
      `npx playwright test --project=streaming -g "wrong XC credentials against the movie route are a 401, not a 500"`
      and `-g "an unknown episode id on the XC series route is a 404, not a 500"`.
      Expected: the first **passes** (it is no longer inverted, Step 3b); the second still reports
      as an expected failure. If the second unexpectedly passes, something in this task changed
      the episode route's error path — stop and report rather than flipping it, because #99's fix
      is a guard clause nothing here writes.
- [ ] **Step 6: Commit.**
      Write `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t6.msg`:
      ```
      refactor(phase1-pr5): the VOD views authorize through the hop

      stream_vod, stream_xc_movie and stream_xc_episode call
      resolve_authorization() and drop their inline STREAMS ACL checks and their
      plaintext xc_password compares. The XC routes keep resolving their content
      object themselves: the hop resolves the principal, not the content.

      The VOD stream limit stays in stream_vod. Its media_id comes from the M3U
      relation the XC routes resolve after the hop has already answered, so the
      hop has no identifier to check for two of the three entry points.

      Closes #100 by construction: both wrong-password branches called an
      unimported `Response`, so every wrong XC credential on the movie and
      series routes raised NameError and answered 500. The hop answers 401, and
      xc-vod-playback.spec.ts's pin stops being inverted. The episode-404 pin
      (#99) stays: its dead `except DoesNotExist` guard is untouched here, and
      an unknown episode id still 500s.
      ```
      `git add apps/proxy/vod_proxy/views.py apps/proxy/vod_proxy/tests/test_vod_redirect.py apps/proxy/vod_proxy/tests/test_vod_db_cleanup.py e2e/tests/streaming/xc-vod-playback.spec.ts`
      then the gate and `git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t6.msg` separately.

### Task 7: The catch-up views authorize through the hop

**Files:** Modify `apps/timeshift/views.py` (`_timeshift_proxy_impl` `:157-181`, `catchup_proxy`
`:283-341`, `_authenticate_user` `:757-768`, `_user_can_access_channel` `:771-786`).
Test: `apps/timeshift/tests/test_views.py` (100 patch sites across ~33 stanzas — 34
`_authenticate_user`, 33 `_user_can_access_channel`, 33 `network_access_allowed`; the file's 27
`check_user_stream_limits` patches are **not** in that number and do not move),
`apps/timeshift/tests/test_sessions.py` (18, of which 9 are on `api_views` and stay),
`apps/timeshift/tests/test_catchup_redirect.py` (5, of which 2 are `check_user_stream_limits` and
stay).
**Interfaces:** Consumes `resolve_authorization`, `authorize_error_response`, `AuthorizeDenied`,
`SURFACE_CATCHUP`, `SURFACE_CATCHUP_XC`. Deletes `_authenticate_user` and
`_user_can_access_channel` — both now live in `apps/proxy/authorize.py` as `resolve_xc_user` and
`user_can_access_channel`.

This is the largest test diff in the PR and the one most likely to be mis-sized: the two helper
names being deleted are patched in ~50 places across three files, and every one of them errors
with `AttributeError` the moment the name goes. The steps below do the source change first, watch
it break, then repair by uniform replacement rather than file-by-file reading.

- [ ] **Step 1: Rewrite `_timeshift_proxy_impl`'s prologue.**
      Replace `:157-181` with:
      ```python
      def _timeshift_proxy_impl(
          request, username, password, timestamp, channel_id, client_duration_hint=None,
      ):
          raw_id = channel_id[:-3] if channel_id.endswith(".ts") else channel_id

          try:
              decision = resolve_authorization(
                  request,
                  SURFACE_CATCHUP_XC,
                  identifier=raw_id,
                  username=username,
                  password=password,
              )
          except AuthorizeDenied as exc:
              return _finalize_timeshift_response(authorize_error_response(exc))

          user = decision.user
          try:
              channel = Channel.objects.get(id=int(raw_id))
          except (Channel.DoesNotExist, ValueError, TypeError):
              close_old_connections()
              raise Http404("Channel not found") from None

          return _serve_catchup(
              request, user, channel, timestamp,
              client_duration_hint=client_duration_hint,
          )
      ```
      The `Channel.objects.get` stays: `_serve_catchup` needs the row, the hop returns a uuid over
      a header, and re-reading one indexed row is cheaper than widening the header contract. The
      three deleted calls are `_authenticate_user`, `network_access_allowed(..., "XC_API", user)`
      and `_user_can_access_channel` — all three now inside the hop, with `XC_API` preserved as
      this surface's ACL key.
      **One client-visible status changes here**: wrong Xtream credentials on the catch-up path
      answer `HttpResponseForbidden("Invalid credentials")` = **403** today (`views.py:161-163`)
      and **401** from the hop, which is what the other three XC surfaces already answer and what
      the spec's contract table calls for. Step 8's grep covers the test-side fallout, and the
      Notes for the reviewer list it beside the 404→403 change.
- [ ] **Step 2: Rewrite `catchup_proxy`'s prologue.**
      Replace `:284-333` (from the `network_access_allowed` guard through the
      `_user_can_access_channel` check) with:
      ```python
          session_id = request.GET.get("session_id")
          timestamp = request.GET.get("start")
          # Direct-auth clients may pass ?duration=; API sessions store their own.
          client_duration_hint = request.GET.get("duration")

          try:
              decision = resolve_authorization(
                  request, SURFACE_CATCHUP, identifier=str(channel_id), session_id=session_id,
              )
          except AuthorizeDenied as exc:
              return _finalize_timeshift_response(authorize_error_response(exc))

          user = decision.user

          if session_id:
              # The hop resolved the principal from this same session; what the
              # view still needs from it is the bound programme start and length,
              # which are not authorization. resolve_catchup_playback's TTL touch
              # is idempotent, so running it twice costs one Redis write.
              resolved = resolve_catchup_playback(session_id, channel_id)
              if resolved is not None:
                  _session_user, bound_start, bound_duration = resolved
                  timestamp = bound_start
                  if bound_duration is not None:
                      client_duration_hint = bound_duration

          try:
              channel = Channel.objects.get(uuid=channel_id)
          except Channel.DoesNotExist:
              close_old_connections()
              raise Http404("Channel not found") from None

          if not timestamp:
              return _finalize_timeshift_response(HttpResponseBadRequest("Missing start parameter"))

          return _serve_catchup(
              request, user, channel, timestamp,
              client_duration_hint=client_duration_hint,
          )
      ```
      The three refusals this deletes are now the hop's: 403 for the ACL, 401 for "no principal
      and no valid session", 403 for "a credentialed user driving someone else's session", 403 for
      channel access. Their bodies change from `HttpResponseForbidden`/`JsonResponse` text to the
      hop's serialized `{"error": …}` JSON; the statuses are unchanged.
      Keep `@authentication_classes([JWTAuthentication, ApiKeyAuthentication,
      QueryParamJWTAuthentication])` on the view — the hop runs the same union itself, and leaving
      the decorator means `request.user` is still populated for the logging further down.
- [ ] **Step 3: Delete the two helpers and fix the imports.**
      Delete `_authenticate_user` (`:757-768`) and `_user_can_access_channel` (`:771-786`).
      Run: `grep -n "_authenticate_user\|_user_can_access_channel\|network_access_allowed" apps/timeshift/views.py`
      Expected: no hits. If `network_access_allowed` still has one, it is a surface this plan did
      not enumerate — report it rather than deleting the import. Then drop
      `from dispatcharr.utils import network_access_allowed` (`:61`) and add:
      ```python
      from apps.proxy.authorize import SURFACE_CATCHUP, SURFACE_CATCHUP_XC, AuthorizeDenied
      from apps.proxy.authorize_views import authorize_error_response, resolve_authorization
      ```
      Both imports are module-level: `apps/proxy/authorize.py` imports nothing from
      `apps/timeshift/` at module scope (its one timeshift import is function-local, inside
      `_catchup_session_user`), so this adds no cycle. Verify:
      Run: `docker exec … dispatcharr-testrunner-pr5 /dispatcharrpy/bin/python manage.py check`
      Expected: `System check identified no issues`.
- [ ] **Step 4: Run the timeshift suite, expect FAIL, and record the shape.**
      Run: § Test environment step 4 with `apps.timeshift.tests`.
      Expected: a large number of
      `AttributeError: <module 'apps.timeshift.views' …> does not have the attribute '_authenticate_user'`
      errors, plus the same for `_user_can_access_channel` and `network_access_allowed`. Record the
      count. `check_user_stream_limits` must **not** appear in that list — it is still a module
      attribute of `apps/timeshift/views.py` and still called from `_serve_catchup` (amendment S1).
- [ ] **Step 5: Add the shared decision helper to the three test modules.**
      Add to each of `test_views.py`, `test_sessions.py` and `test_catchup_redirect.py`, near the
      other module-level test helpers:
      ```python
      def _authorized(user=None, surface=None):
          """The hop's answer, as the catch-up views now receive it.

          One helper rather than an AuthorizeResult literal per stanza: the three
          fields these tests care about are the user and the surface, and every
          other field is empty for this path (catch-up mints no client id and
          resolves no Output Profile).
          """
          from apps.proxy.authorize import SURFACE_CATCHUP_XC, AuthorizeResult

          return AuthorizeResult(
              surface=surface or SURFACE_CATCHUP_XC,
              user_id=str(getattr(user, "id", "")) if user is not None else "",
              relay_name="py",
              user=user,
          )
      ```
- [ ] **Step 6: Replace the uniform stanzas in `test_views.py`.**
      Four `Edit(replace_all=True)` operations cover 30 of the 33 stanzas. Verify each count with
      `grep -c` before and after.
      1. Delete the ACL patch (27 occurrences of the continuation form, of the 33 in the file):
         old: `             patch.object(views, "network_access_allowed", return_value=True), \`
         new: *(remove the line)*
      2. Delete the membership patch (29 occurrences):
         old: `             patch.object(views, "_user_can_access_channel", return_value=True), \`
         new: *(remove the line)*
      3. Repoint the principal patch (17 occurrences):
         old: `        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=5)), \`
         new: `        with patch.object(views, "resolve_authorization", return_value=_authorized(MagicMock(id=5))), \`
      4. The `id=1` form (6 occurrences):
         old: `        with patch.object(views, "_authenticate_user", return_value=MagicMock(id=1)), \`
         new: `        with patch.object(views, "resolve_authorization", return_value=_authorized(MagicMock(id=1))), \`
      5. The `self.user` form (4 occurrences):
         old: `        with patch.object(views, "_authenticate_user", return_value=self.user), \`
         new: `        with patch.object(views, "resolve_authorization", return_value=_authorized(self.user)), \`
      6. The `attacker` form (1 occurrence):
         old: `        with patch.object(views, "_authenticate_user", return_value=attacker), \`
         new: `        with patch.object(views, "resolve_authorization", return_value=_authorized(attacker)), \`
      Then handle by hand the **six** non-uniform sites `grep -n` still reports — two shapes the
      continuation-form replacements above cannot match, plus the refusal test: two
      `with patch.object(views, "network_access_allowed", return_value=True):` single-context
      forms (`:5306`, `:5318`); three where the same patch is the **first** line of a `with` chain
      (`:5326`, `:5340`, `:5357`), i.e. `with patch.object(views, "network_access_allowed"…), \`
      rather than an indented continuation; and `:868`'s
      `patch.object(views, "network_access_allowed", return_value=False) as gate` — the
      last is a test of the ACL refusal itself and becomes
      `patch.object(views, "resolve_authorization", side_effect=AuthorizeDenied(403, "Forbidden")) as gate`,
      with its assertion on `gate.called` unchanged and its status assertion still 403.
      Run: `grep -c '_authenticate_user\|_user_can_access_channel\|network_access_allowed' apps/timeshift/tests/test_views.py`
      Expected: `0`.
- [ ] **Step 7: Same treatment for `test_sessions.py` and `test_catchup_redirect.py`.**
      `test_sessions.py`'s 18 sites split into 9 in `apps.timeshift.api_views` (`:110-332`) — those
      patch a **different module**, `api_views`, which this PR does not touch, so **leave every
      one of them alone** — and the rest at `:452-516`, which patch `views` and take the Step 6
      treatment. `test_catchup_redirect.py`'s five sites are one stanza (`:83-89`) plus two
      `check_user_stream_limits` patches (`:190`, `:218`) that **stay**.
      Run: § Test environment step 4 with `apps.timeshift.tests`.
      Expected: `OK`, same test count as Task 1 Step 5 minus the two helper tests moved to
      `apps/proxy/tests/test_authorize.py` in Task 3 Step 9.
- [ ] **Step 8: Check nothing asserted on a refusal's body.**
      Run: `grep -rn "Access denied\|Invalid credentials" apps/timeshift/tests/`
      Expected: no hit inside a test that now goes through the hop. Any hit is a body assertion on
      a response whose shape changed from `HttpResponseForbidden("Access denied")` to
      `{"error": "…"}`; update it to assert the status, and say so in the task report.
- [ ] **Step 9: Commit.**
      Write `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t7.msg`:
      ```
      refactor(phase1-pr5): the catch-up views authorize through the hop

      catchup_proxy and _timeshift_proxy_impl call resolve_authorization() and
      delete their inline gates. _authenticate_user and _user_can_access_channel
      move to apps/proxy/authorize.py as resolve_xc_user and
      user_can_access_channel — the one extracted copy of the channel
      authorization filter in the tree becomes the only copy on the streaming
      path. The XC catch-up surface keeps XC_API as its ACL key.

      check_user_stream_limits stays in _serve_catchup: its timeshift sibling
      exemption matches on a <channel>_<programme> media id and a pool-derived
      client id that only exist after session resolution, and a hop passing the
      bare channel uuid would 429 a legitimate mid-programme seek.

      The three test modules that patched the deleted helpers now patch
      resolve_authorization, one line where there were three.
      ```
      `git add apps/timeshift/views.py apps/timeshift/tests/test_views.py apps/timeshift/tests/test_sessions.py apps/timeshift/tests/test_catchup_redirect.py`
      then the gate and `git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t7.msg` separately.

### Task 8: The DVR becomes an internal principal

**Files:** Modify `apps/channels/tasks.py` (`_dvr_build_ffmpeg_cmd` `:1203-1229`, its call site
`:1729-1731`, the argv debug log `:1738-1741`).
Create `apps/channels/tests/test_dvr_internal_principal.py`.
**Interfaces:** Produces `_dvr_build_ffmpeg_cmd(stream_url, recording_id, hls_m3u8,
hls_seg_pattern, hls_start_number, internal_token=None)` and `_dvr_redact_cmd(cmd)`.
Consumes `apps.proxy.internal_auth.internal_principal_token`.

- [ ] **Step 1: Write the failing test.**
      Create `apps/channels/tests/test_dvr_internal_principal.py`:
      ```python
      """The DVR's internal principal, and the argv log that must not print it.

      run_recording fetches /proxy/ts/stream/<uuid> through ffmpeg with no
      credential of any kind. From Phase 1 PR 4 that fetch goes through nginx
      (get_dvr_stream_base_url's AIO branch), and from PR 5 nginx authorizes it —
      so without an internal principal every recording of a hidden, adult or
      profile-gated channel would break silently.
      """

      from django.test import SimpleTestCase, override_settings

      from apps.channels.tasks import _dvr_build_ffmpeg_cmd, _dvr_redact_cmd
      from apps.proxy.internal_auth import internal_principal_token


      @override_settings(SECRET_KEY="dvr-test-secret")
      class DvrInternalPrincipalTests(SimpleTestCase):
          def _cmd(self, token=None):
              return _dvr_build_ffmpeg_cmd(
                  "http://127.0.0.1:9191/proxy/ts/stream/abc",
                  7,
                  "/data/recordings/x.m3u8",
                  "/data/recordings/x%05d.ts",
                  0,
                  internal_token=token,
              )

          def test_the_header_precedes_the_input(self):
              cmd = self._cmd(internal_principal_token())
              self.assertIn("-headers", cmd)
              self.assertLess(cmd.index("-headers"), cmd.index("-i"))

          def test_the_header_value_ends_in_real_control_characters(self):
              # ffmpeg splits -headers on CR LF and does not unescape a literal
              # backslash-r backslash-n; a header built with escaped text is sent
              # as one malformed line and silently ignored.
              value = self._cmd(internal_principal_token())[
                  self._cmd(internal_principal_token()).index("-headers") + 1
              ]
              self.assertTrue(value.endswith("\r\n"))
              self.assertNotIn("\\r\\n", value)
              self.assertTrue(value.startswith("X-Dispatcharr-Internal: "))

          def test_no_token_means_no_headers_argument(self):
              self.assertNotIn("-headers", self._cmd(None))

          def test_redaction_masks_the_token_and_keeps_the_rest(self):
              cmd = self._cmd(internal_principal_token())
              redacted = _dvr_redact_cmd(cmd)
              self.assertNotIn(internal_principal_token(), " ".join(redacted))
              self.assertIn("ffmpeg", redacted)
              self.assertIn("X-Dispatcharr-Internal: ***\r\n", redacted)

          def test_redaction_masks_credentials_in_the_input_url(self):
              cmd = _dvr_build_ffmpeg_cmd(
                  "http://host.invalid/live/theuser/thepass/9.ts", 7, "a", "b", 0,
              )
              self.assertNotIn("thepass", " ".join(_dvr_redact_cmd(cmd)))

          def test_redaction_returns_a_list_the_caller_can_join(self):
              self.assertIsInstance(_dvr_redact_cmd(self._cmd(None)), list)
      ```
- [ ] **Step 2: Run it, expect FAIL.**
      Run: § Test environment step 4 with `apps.channels.tests.test_dvr_internal_principal`.
      Expected: `ImportError: cannot import name '_dvr_redact_cmd'`.
- [ ] **Step 3: Add the header and the redactor.**
      In `apps/channels/tasks.py`, change the builder's signature and insert the `-headers` pair
      before `"-i"`:
      ```python
      def _dvr_build_ffmpeg_cmd(stream_url, recording_id, hls_m3u8, hls_seg_pattern,
                                hls_start_number, internal_token=None):
          """Build the FFmpeg command for DVR HLS segment recording."""
          from core.utils import dispatcharr_dvr_user_agent

          cmd = [
              "ffmpeg", "-y",
              "-reconnect", "1",
              "-reconnect_streamed", "1",
              "-reconnect_delay_max", "5",
              "-user_agent", dispatcharr_dvr_user_agent(recording_id),
              # Regenerate monotonic PTS to handle erratic/discontinuous timestamps
              # from IPTV sources.
              "-fflags", "+genpts",
              # Tolerate minor TS corruption without aborting the whole process.
              "-err_detect", "ignore_err",
          ]
          if internal_token:
              # The authorize hop's internal-principal row (Phase 1 PR 5): the DVR
              # carries no user credential and must not be judged as anonymous, or
              # every recording of a hidden or adult or profile-gated channel
              # fails. Real CR LF: ffmpeg splits -headers on the control
              # characters and does not unescape a literal backslash pair.
              cmd += ["-headers", f"X-Dispatcharr-Internal: {internal_token}\r\n"]
          cmd += [
              "-i", stream_url,
              "-c", "copy",
              # Shift output timestamps so they start from 0, fixing negative PTS
              # values that can prevent segment boundary detection in the HLS muxer.
              "-avoid_negative_ts", "make_zero",
              "-f", "hls",
              "-hls_time", "4",
              "-hls_list_size", "0",
              "-hls_flags", "append_list+omit_endlist+independent_segments",
              "-start_number", str(hls_start_number),
              "-hls_segment_filename", hls_seg_pattern,
              hls_m3u8,
          ]
          return cmd


      def _dvr_redact_cmd(cmd):
          """The ffmpeg argv, safe to log.

          Two carriers, neither of which scripts/check_credential_logging.py's
          CREDENTIAL_RE matches: the -headers value now holds an HMAC of
          SECRET_KEY, and the -i URL is an Xtream path when
          DISPATCHARR_INTERNAL_TS_BASE_URL points somewhere with credentials in
          it. The guard would not catch either, which is exactly why this is
          here rather than left to the guard.
          """
          from dispatcharr.utils import redact_url

          redacted = []
          mask_next = False
          for arg in cmd:
              text = str(arg)
              if mask_next:
                  head, _, tail = text.partition(":")
                  redacted.append(f"{head}: ***\r\n" if tail else "***")
                  mask_next = False
                  continue
              if text == "-headers":
                  mask_next = True
              elif text.startswith("http://") or text.startswith("https://"):
                  redacted.append(redact_url(text))
                  continue
              redacted.append(text)
          return redacted
      ```
- [ ] **Step 4: Pass the token at the call site and redact the log.**
      `:1729-1731` becomes:
      ```python
                  ffmpeg_cmd = _dvr_build_ffmpeg_cmd(
                      stream_url, recording_id, hls_m3u8, hls_seg_pattern, hls_start_number,
                      internal_token=internal_principal_token(),
                  )
      ```
      with `from apps.proxy.internal_auth import internal_principal_token` added as a
      **function-local** import at the top of `run_recording`'s body, matching this file's existing
      convention (`from core.utils import dispatcharr_dvr_user_agent` is local for the same
      reason). `:1738-1741` becomes:
      ```python
                  logger.debug(
                      f"DVR recording {recording_id}: FFmpeg command: "
                      f"{' '.join(_dvr_redact_cmd(ffmpeg_cmd))}"
                  )
      ```
- [ ] **Step 5: Run, expect PASS, and run the guard.**
      Run: § Test environment step 4 with `apps.channels.tests.test_dvr_internal_principal`, then
      `python3 scripts/check_credential_logging.py apps/channels/tasks.py`.
      Expected: `OK`, then exit 0 with no output.
- [ ] **Step 6: Run the whole channels label.**
      Run: § Test environment step 4 with `apps.channels.tests`.
      Expected: `OK`, including PR 4's `test_dvr_port_resolution.py` — this task changes the
      builder's signature, and `_dvr_build_ffmpeg_cmd`'s other callers (if `grep -n
      "_dvr_build_ffmpeg_cmd" apps/channels/` reports any beyond `:1729` and the tests) must all
      still pass it five positional arguments.
- [ ] **Step 7: Commit.**
      Write `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t8.msg`:
      ```
      feat(phase1-pr5): the DVR fetches its stream as an internal principal

      run_recording's ffmpeg input now carries
      X-Dispatcharr-Internal: HMAC(SECRET_KEY, "internal-principal"), terminated
      with real CR LF because ffmpeg splits -headers on the control characters
      and does not unescape a literal backslash pair. Without it, every
      recording of a hidden, adult or profile-gated channel would break the
      moment the authorize hop is in front of /proxy/ts/stream/.

      The argv debug log goes through a new _dvr_redact_cmd, which masks the
      header value and redacts the input URL. check_credential_logging.py's
      pattern matches neither ffmpeg_cmd nor the token, so the guard would not
      have caught this one.

      In dev there is no nginx and the DVR reaches uwsgi directly, so the header
      is carried but never checked — the same argv in both shapes.
      ```
      `git add apps/channels/tasks.py apps/channels/tests/test_dvr_internal_principal.py`
      then the gate and `git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t8.msg` separately.

### Task 9: nginx issues the subrequest, and blanks the trust params everywhere else

**Files:** Create `docker/dispatcharr_api_params.conf`.
Modify `docker/nginx.conf` (the `upstream` block `:21-23`, every `location` in the `server` block
`:41-285`), `docker/Dockerfile` (`:36-37`), `docker/init/03-init-dispatcharr.sh` (`:67-102`).
**Interfaces:** Consumes `HMAC(SECRET_KEY, "relay-trust")` computed in bash from
`$DJANGO_SECRET_KEY`, which `docker/entrypoint.sh:138` exports before `:353` sources this script.
Produces the `RELAY_TRUST_TOKEN` placeholder substitution and the `auth_request` block on every
relay-bound top-level location.

- [ ] **Step 1: Write the blanking include.**
      Create `docker/dispatcharr_api_params.conf`:
      ```nginx
      # Included by every uwsgi location that is NOT relay-bound, plus the two
      # relay-bound locations that are deliberately outside the authorize hop
      # (the nested recordings-file regex and /proxy/relay/).
      #
      # Why it exists: uwsgi_pass_request_headers is on by default, so a client's
      # own X-Dispatcharr-Authorized or X-Relay-* header would otherwise reach
      # the application untouched. Since nginx 0.8.40 a *_param whose name begins
      # with HTTP_ overrides the same-named client header, so setting these five
      # to "" is what replaces whatever arrived. The relay compares the empty
      # marker in constant time, fails, and authorizes inline — the correct
      # outcome, since a request on one of these locations was never authorized
      # by a subrequest.
      #
      # Why an include repeated per location rather than a server-level block: a
      # location that declares any uwsgi_param of its own inherits none from the
      # enclosing level, which is also why `include uwsgi_params;` is repeated in
      # every location in nginx.conf today.
      #
      # Why it matters at all: D1 keeps one urlconf in both processes, so every
      # Django-bound location can reach a stream view.
      include uwsgi_params;
      uwsgi_param HTTP_X_DISPATCHARR_AUTHORIZED "";
      uwsgi_param HTTP_X_RELAY_CHANNEL "";
      uwsgi_param HTTP_X_RELAY_OUTPUT  "";
      uwsgi_param HTTP_X_RELAY_CLIENT  "";
      uwsgi_param HTTP_X_RELAY_USER    "";
      ```
- [ ] **Step 2: Ship it in the image.**
      In `docker/Dockerfile`, after `COPY ./docker/nginx.conf /etc/nginx/sites-enabled/default`
      (`:37`):
      ```dockerfile
      COPY ./docker/dispatcharr_api_params.conf /etc/nginx/dispatcharr_api_params.conf
      ```
      A plain local `COPY`, so no digest pinning applies (that rule covers `FROM` and
      `COPY --from=`). It is copied to `/etc/nginx/` rather than included from `/app/docker/`
      because that is where the sibling config already lives and because `/app` ownership changes
      per PUID while `/etc/nginx` does not.
- [ ] **Step 3: Add the `map`.**
      In `docker/nginx.conf`, immediately after the `upstream relay_py { … }` block (`:21-23`):
      ```nginx
      # $relay_name is set per relay-bound location by auth_request_set, from the
      # X-Relay-Name header the authorize hop returns (settings.RELAY_DEFAULT_NAME,
      # "py" in Phase 1). auth_request_set is the ONLY context in which a
      # subrequest's response headers are readable, which is why the map keys on
      # $relay_name rather than on $upstream_http_x_relay_name.
      #
      # The values are upstream GROUP names, not addresses: uwsgi_pass to a
      # variable holding a bare host:port needs a `resolver` and fails without
      # one, while a declared group needs none. Phase 2's canary is a second map
      # entry and a second upstream block — not a code change on either side
      # (ADR 0005). `default` covers the two relay-bound locations that run no
      # subrequest, where $relay_name is unset.
      map $relay_name $relay_upstream {
          default relay_py;
          py      relay_py;
      }
      ```
- [ ] **Step 4: Add the authorize location.**
      Inside the `server` block, with the other exact matches (after
      `location = /streaming/timeshift.php`, `:78`):
      ```nginx
          # The authorize hop (Phase 1 PR 5, ADR 0005). `internal;` means nginx
          # serves it only for a subrequest — a client asking for this URI
          # directly gets 404 from nginx, never Django. It goes to the API
          # process like every other Django-bound location: auth_request
          # subrequests do not follow the relay's upstream.
          location = /_dispatcharr/authorize {
              internal;
              include /etc/nginx/dispatcharr_api_params.conf;
              # The subrequest's own URI is this location, so the URI being
              # authorized has to be forwarded explicitly. $request_uri is the
              # parent request's unparsed URI, query string included — the
              # uwsgi_pass equivalent of the auth_request docs' X-Original-URI.
              uwsgi_param HTTP_X_ORIGINAL_URI $request_uri;
              uwsgi_pass_request_body off;
              uwsgi_pass unix:/app/uwsgi.sock;
          }
      ```
- [ ] **Step 5: Put the hop in front of every relay-bound top-level location.**
      Nine locations take the identical block: `= /streaming/timeshift.php`,
      `^~ /proxy/ts/stream/`, `^~ /proxy/vod/`, `^~ /proxy/catchup/`, `^~ /live/`, `^~ /movie/`,
      `^~ /series/`, `^~ /timeshift/`, and the regex `~ ^/[^/]+/[^/]+/[^/]+$`. Each keeps its
      existing `uwsgi_buffering off` / timeout / `client_max_body_size` lines, replaces
      `include uwsgi_params;` with the block below — six `auth_request_set` lines, not five: the
      sixth carries the status nginx cannot transport — and changes `uwsgi_pass relay_py;` to
      `uwsgi_pass $relay_upstream;`. Written once here; apply it nine times:
      ```nginx
              auth_request /_dispatcharr/authorize;
              auth_request_set $relay_name    $upstream_http_x_relay_name;
              auth_request_set $relay_channel $upstream_http_x_relay_channel;
              auth_request_set $relay_output  $upstream_http_x_relay_output;
              auth_request_set $relay_client  $upstream_http_x_relay_client;
              auth_request_set $relay_user    $upstream_http_x_relay_user;
              auth_request_set $authorize_status $upstream_http_x_authorize_status;
              error_page 403 = @authorize_denied;

              include uwsgi_params;
              uwsgi_param HTTP_X_DISPATCHARR_AUTHORIZED "RELAY_TRUST_TOKEN";
              uwsgi_param HTTP_X_RELAY_CHANNEL $relay_channel;
              uwsgi_param HTTP_X_RELAY_OUTPUT  $relay_output;
              uwsgi_param HTTP_X_RELAY_CLIENT  $relay_client;
              uwsgi_param HTTP_X_RELAY_USER    $relay_user;
      ```
      Add the explanatory comment once, on `^~ /proxy/ts/stream/` (the first one a reader meets),
      not nine times:
      ```nginx
          # Relay-bound, and therefore authorized once per tune before a byte
          # moves: 2xx allows, 401/403 are returned to the client verbatim,
          # anything else is nginx's own error — including an unreachable API
          # process, which is a 500 here rather than the 502/504 a failed
          # uwsgi_pass would give (amendment S7). The six auth_request_set lines
          # are the only way to read the subrequest's response headers; the
          # uwsgi_param lines
          # re-emit them toward the relay AND override whatever the client sent
          # under the same names, which is the second of the two layers that
          # make the marker unforgeable. The first is that RELAY_TRUST_TOKEN is
          # HMAC(SECRET_KEY, "relay-trust"), sed'd in at boot by
          # docker/init/03-init-dispatcharr.sh — not the literal "1" — because
          # nginx is not always in front of this port.
          #
          # error_page 403 exists because the module carries only 401 and 403:
          # the hop sends every 404 and 429 decision as a 403 naming the real
          # code in X-Authorize-Status, and @authorize_denied puts it back.
      ```
- [ ] **Step 5b: Add the named location that restores the real status.**
      Once, at server level, after `location /` — a named location is never matched by a URI, so
      its position among the prefix locations is free, and putting it last keeps the matched
      locations readable in evaluation order:
      ```nginx
          # Restores the status the authorize hop actually decided.
          # ngx_http_auth_request_module denies with 401 or 403 verbatim and
          # treats every other subrequest status as an error — which reaches the
          # client as 500 — so the hop collapses 404 and 429 into a 403 naming
          # the real code in X-Authorize-Status, and this puts it back. Without
          # it, an unknown channel id in a cached playlist would answer 500
          # where it answers 404 today, and a viewer over their stream limit
          # would answer 500 where they get 429 today.
          #
          # `if` rather than a `map` because `return` takes a literal code, not
          # a variable. No request body is touched and no rewrite runs here, so
          # this is not the documented `if`-in-location trap.
          #
          # error_page is declared per relay-bound location and deliberately NOT
          # at server level. It would not recurse if it were — with
          # recursive_error_pages off, the default, nginx marks the request on
          # the first redirect and never applies error_page again — but it would
          # route every other 403 in this server here too: a static file's, an
          # internal location's, one the relay itself returned, each handed
          # whatever $authorize_status happened to hold.
          #
          # uwsgi_intercept_errors is off by default, so a 403 the relay itself
          # produces is never routed here — only the subrequest's denial is.
          location @authorize_denied {
              if ($authorize_status = 404) { return 404; }
              if ($authorize_status = 429) { return 429; }
              return 403;
          }
      ```
- [ ] **Step 6: Blank the params on every other uwsgi location.**
      Replace `include uwsgi_params;` with `include /etc/nginx/dispatcharr_api_params.conf;` in:
      `= /proxy/ts/status`, `= /proxy/vod/stats/`, `= /proxy/vod/stop_client/`,
      `= /proxy/catchup/stats/`, `= /proxy/catchup/programs/`, `= /proxy/catchup/stop_client/`,
      `^~ /api/`, `^~ /output/`, `^~ /hdhr`, `^~ /proxy/`, `location /`, **and the two relay-bound
      exceptions**: the nested `~ ^/api/channels/recordings/\d+/file/$` and `^~ /proxy/relay/`.
      Both exceptions keep `uwsgi_pass relay_py;` — a literal group, not `$relay_upstream`, since
      no subrequest sets `$relay_name` for them. Add to each exception the reason it is one:
      ```nginx
              # Deliberately outside the authorize hop: its gate is DRF
              # authentication plus network_access_allowed("STREAMS") on
              # RecordingViewSet.file, which is not a surface authorize_stream()
              # knows, so it gets no row in the authorize matrix. It carries the
              # blanking include like a non-relay location, so a client-supplied
              # X-Relay-* header never reaches the relay on this path.
      ```
      ```nginx
              # Deliberately outside the authorize hop: PR 7's relay control API
              # is gated by the internal token alone (D9), and authorize_stream()
              # would 404 a URI that names no channel. Blanking include for the
              # same reason as above.
      ```
      The static (`/assets/`, `/static/`, `/logos/`), `internal` (`/protected-backups/`), `/ws/`
      and four `proxy_cache` locations need nothing: they use `root`/`alias`/`proxy_pass` and reach
      no stream view.
- [ ] **Step 7: Compute and substitute the token at boot.**
      In `docker/init/03-init-dispatcharr.sh`, inside the existing `all`/`api` role gate, after the
      `RELAY_UPSTREAM` sed (`:93`) and before the IPv6 branch:
      ```bash
          # The relay's trust marker: HMAC(SECRET_KEY, "relay-trust"), the value
          # nginx puts in X-Dispatcharr-Authorized on every relay-bound location
          # (Phase 1 PR 5, D11). python3 rather than openssl: the entrypoint
          # already generates the secret with a python3 heredoc, and nothing in
          # either Dockerfile installs openssl as an app dependency.
          #
          # DJANGO_SECRET_KEY is exported by docker/entrypoint.sh before this
          # script is sourced, from /data/jwt — the same file every role reads,
          # which is what makes the relay derive the identical value in Python.
          RELAY_TRUST_TOKEN=$(python3 - <<'PY'
      import hashlib
      import hmac
      import os

      print(hmac.new(os.environ["DJANGO_SECRET_KEY"].encode(), b"relay-trust", hashlib.sha256).hexdigest())
      PY
      )
          if [[ ! "$RELAY_TRUST_TOKEN" =~ ^[0-9a-f]{64}$ ]]; then
              echo "❌ ERROR: could not derive the relay trust token from DJANGO_SECRET_KEY."
              echo "   nginx would forward an unauthorized marker and every tune would 403."
              exit 1
          fi
          sed -i "s/RELAY_TRUST_TOKEN/${RELAY_TRUST_TOKEN}/g" /etc/nginx/sites-enabled/default
      ```
      A hex digest needs no sed quoting, which is why the guard checks the shape rather than
      escaping the value. The failure is fatal on purpose: a container whose nginx forwards the
      literal `RELAY_TRUST_TOKEN` would 403 every stream, and a loud stop at boot is a better
      failure than that.
- [ ] **Step 8: Prove the config parses, with real substitutions.**
      Run:
      ```bash
      docker run --rm -v "$PWD/docker/nginx.conf:/tmp/nginx.conf:ro" \
        -v "$PWD/docker/dispatcharr_api_params.conf:/etc/nginx/dispatcharr_api_params.conf:ro" \
        nginx:1.24 sh -c '
          sed -e s/NGINX_PORT/9191/g \
              -e s/RELAY_UPSTREAM/127.0.0.1:5657/g \
              -e s/RELAY_TRUST_TOKEN/$(printf %064d 0)/g \
              /tmp/nginx.conf > /etc/nginx/conf.d/default.conf &&
          rm -f /etc/nginx/conf.d/../sites-enabled/default 2>/dev/null;
          nginx -t'
      ```
      Expected: `syntax is ok` and `test is successful`. A `host not found in upstream` here means
      the `RELAY_UPSTREAM` sed did not run — check the expression, not the config.
      This parses against the official `nginx:1.24` image, while production nginx is Ubuntu's
      package (`docker/DispatcharrBase:144`), so also prove the module is compiled into the real
      one after the stack rebuild in Task 10 Step 4:
      ```bash
      docker exec dispatcharr-e2e-pr5 nginx -V 2>&1 | grep -c http_auth_request_module
      ```
      Expected: `1`. Ubuntu's `nginx-core` does ship it, and the greybox test would catch its
      absence anyway — but only after a full stack rebuild, which is a long way to learn it.
- [ ] **Step 9: Count what changed, and prove the counts.**
      Run:
      ```bash
      grep -c '^\s*auth_request /_dispatcharr/authorize;' docker/nginx.conf
      grep -c '^\s*auth_request_set' docker/nginx.conf
      grep -c '^\s*error_page 403 = @authorize_denied;' docker/nginx.conf
      grep -c 'uwsgi_pass \$relay_upstream;' docker/nginx.conf
      grep -c 'uwsgi_pass relay_py;' docker/nginx.conf
      grep -c 'dispatcharr_api_params.conf' docker/nginx.conf
      grep -c '^\s*include uwsgi_params;' docker/nginx.conf
      ```
      Expected, in order: `9`; `54` (nine locations × six — anchored, because the `map` comment
      and the Step 5 explanatory comment both contain the words `auth_request_set` and an
      unanchored count returns 57); `9`; `9`; `2` (the two deliberate exceptions); `14` (eleven
      non-relay uwsgi locations, the two exceptions, and the authorize location Step 4 adds); `9`
      (the nine relay-bound blocks — anchored, since the include file is a separate file and its
      own `include uwsgi_params;` is not in this one).
- [ ] **Step 10: Commit.**
      Write `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t9.msg`:
      ```
      feat(phase1-pr5): nginx authorizes every relay-bound location once per tune

      Nine relay-bound locations gain auth_request /_dispatcharr/authorize, the
      six auth_request_set lines that read the subrequest's response headers,
      and the five uwsgi_param lines that re-emit them toward the relay while
      overriding whatever the client sent. uwsgi_pass takes $relay_upstream, a
      map on the relay name with one entry today.

      Every other uwsgi location switches to a shared include that blanks the
      same five params, because both processes run the same urlconf and either
      can serve a stream view. Two relay-bound locations take the blanking
      include rather than the hop, deliberately: the recordings-file regex is
      gated by DRF auth, and /proxy/relay/ by the internal token.

      The marker is HMAC(SECRET_KEY, "relay-trust"), derived at boot from
      /data/jwt and sed'd in like NGINX_PORT. A container that cannot derive it
      stops rather than serving a config that 403s every tune.

      A named @authorize_denied location restores the status the hop decided.
      The auth_request module carries only 401 and 403 and calls every other
      subrequest status an error, so a 404 or 429 sent as itself would reach a
      viewer as 500 — an unknown channel id in a cached playlist, and a viewer
      over their stream limit, both today's honest statuses.
      ```
      `git add docker/nginx.conf docker/dispatcharr_api_params.conf docker/Dockerfile docker/init/03-init-dispatcharr.sh`
      then the gate and `git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t9.msg` separately.

### Task 10: Pin the location table so the next edit cannot quietly undo it

**Files:** Modify `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`.
**Interfaces:** Consumes `parseLocationBlocks` and `RELAY_BOUND_TARGETS`, both already in that
file from PR 4.

The new tests go in the **existing** file rather than a sibling: `e2e/tests/guards/allowlist.ts`
grants `SUBPROCESS` to this exact path, and a new spec would need an allowlist entry for the same
`docker exec … nginx -T` this file already owns. One file, one capability, no allowlist churn.

- [ ] **Step 1: Widen the file's header comment.**
      The header currently says the file pins `uwsgi_buffering off`. Add a paragraph naming the
      second and third properties: that every relay-bound location runs the authorize subrequest
      with all six `auth_request_set` lines and the `error_page` that restores the status nginx
      cannot transport, and that every location that is *not* behind the hop carries the blanking
      include and no `auth_request` — the pair being what makes the trust marker unforgeable.
- [ ] **Step 2: Add the two tests.**
      Append to `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`:
      ```typescript
      /**
       * The five variables the hop's answer travels in. Order-independent: the
       * assertion is set membership, so reordering the block in nginx.conf is
       * not a failure.
       */
      const AUTH_REQUEST_SET_VARS = [
        '$relay_name',
        '$relay_channel',
        '$relay_output',
        '$relay_client',
        '$relay_user',
        // The sixth carries the status the module cannot transport: a 404 or
        // 429 decision arrives as 403 and error_page turns it back.
        '$authorize_status',
      ];

      test(
        'every relay-bound location authorizes through the hop',
        { tag: '@contract' },
        async () => {
          const { stdout } = await execFileAsync('docker', ['exec', CONTAINER_NAME, 'nginx', '-T']);
          const blocks = parseLocationBlocks(stdout);
          const relayBlocks = blocks.filter((b) => RELAY_BOUND_TARGETS.includes(b.target));

          // Same vacuous-pass guard as the buffering test above: an empty array
          // would pass every loop below while proving nothing.
          expect(
            relayBlocks.map((b) => b.target).sort(),
            `expected every relay-bound location in nginx -T's output; found: ${blocks.map((b) => b.header).join(', ')}`
          ).toEqual([...RELAY_BOUND_TARGETS].sort());

          for (const block of relayBlocks) {
            expect(
              block.body.some((line) => /^\s*auth_request\s+\/_dispatcharr\/authorize\s*;/.test(line)),
              `location "${block.header}" does not issue the authorize subrequest:\n${block.body.join('\n')}`
            ).toBe(true);

            for (const variable of AUTH_REQUEST_SET_VARS) {
              expect(
                block.body.some((line) =>
                  new RegExp(`^\\s*auth_request_set\\s+\\${variable}\\s`).test(line)
                ),
                `location "${block.header}" does not set ${variable} from the subrequest`
              ).toBe(true);
            }

            // The marker: a literal "1" here would let anyone who can reach the
            // relay's port hand it a hand-written X-Relay-Channel. The sed'd
            // value is a 64-character hex digest, and the placeholder itself
            // reaching a running container means 03-init-dispatcharr.sh did not
            // substitute it — which would 403 every tune.
            const marker = block.body.find((line) =>
              /uwsgi_param\s+HTTP_X_DISPATCHARR_AUTHORIZED/.test(line)
            );
            expect(marker, `location "${block.header}" sets no trust marker`).toBeTruthy();
            expect(marker).toMatch(/"[0-9a-f]{64}"/);

            // Without this, a 404 or 429 decision reaches the viewer as 500:
            // the auth_request module denies verbatim on 401 and 403 only.
            expect(
              block.body.some((line) =>
                /^\s*error_page\s+403\s*=\s*@authorize_denied\s*;/.test(line)
              ),
              `location "${block.header}" does not restore the hop's real status`
            ).toBe(true);
          }

          // The named location the error_page above points at. A dangling
          // error_page target is a 500 on every denial, which is the failure
          // this whole block exists to prevent.
          const denied = blocks.find((b) => b.target === '@authorize_denied');
          expect(denied, 'no location @authorize_denied').toBeTruthy();
          expect(denied!.body.some((line) => /\$authorize_status\s*=\s*404/.test(line))).toBe(true);
          expect(denied!.body.some((line) => /\$authorize_status\s*=\s*429/.test(line))).toBe(true);
          expect(denied!.body.some((line) => /^\s*return\s+403\s*;/.test(line))).toBe(true);

          // The authorize location itself must exist and be internal, or every
          // subrequest above is a 404 that nginx reports as a 500.
          const authorize = blocks.find((b) => b.target === '/_dispatcharr/authorize');
          expect(authorize, 'no = /_dispatcharr/authorize location').toBeTruthy();
          expect(authorize!.body.some((line) => /^\s*internal\s*;/.test(line))).toBe(true);
        }
      );

      test(
        'every location outside the hop blanks the trust params',
        { tag: '@contract' },
        async () => {
          const { stdout } = await execFileAsync('docker', ['exec', CONTAINER_NAME, 'nginx', '-T']);
          const blocks = parseLocationBlocks(stdout);

          // Both processes run one urlconf (spec D1), so a stream view is
          // reachable through any Django-bound location. Each of these must
          // therefore overwrite the five params a client could otherwise send.
          const blanked = [
            '/',
            '/api/',
            '/output/',
            '/hdhr',
            '/proxy/',
            '/proxy/relay/',
            '/proxy/ts/status',
            '/proxy/vod/stats/',
            '/proxy/vod/stop_client/',
            '/proxy/catchup/stats/',
            '/proxy/catchup/programs/',
            '/proxy/catchup/stop_client/',
            '/_dispatcharr/authorize',
          ];

          for (const target of blanked) {
            const block = blocks.find((b) => b.target === target);
            expect(block, `no location for ${target}`).toBeTruthy();
            expect(
              block!.body.some((line) => /dispatcharr_api_params\.conf\s*;/.test(line)),
              `location "${block!.header}" does not include the blanking params`
            ).toBe(true);
            expect(
              block!.body.some((line) => /^\s*auth_request\s+\//.test(line)),
              `location "${block!.header}" must not run the authorize subrequest`
            ).toBe(false);
          }

          // The nested recordings-file location never surfaces as its own block
          // (parseLocationBlocks walks by brace depth from each header, so its
          // lines are part of /api/'s body). Assert on that body instead: it is
          // relay-bound, and it must carry neither an auth_request nor a
          // $relay_upstream pass.
          const api = blocks.find((b) => b.target === '/api/')!;
          // Match the location header, not the word in the comment above it: a
          // deleted nested location with its explanatory comment left behind
          // would otherwise still pass.
          expect(
            api.body.some((line) => /location\s+~\s+\^\/api\/channels\/recordings/.test(line)),
            'the nested recordings-file location is gone from ^~ /api/'
          ).toBe(true);
          expect(api.body.some((line) => /^\s*auth_request\s+\//.test(line))).toBe(false);
        }
      );
      ```
- [ ] **Step 3: Typecheck.**
      Run: `cd e2e && npx tsc --noEmit`
      Expected: no output. The non-null assertions (`block!`) are deliberate and follow the
      `expect(...).toBeTruthy()` immediately above each.
- [ ] **Step 4: Run the greybox project against this worktree's stack.**
      Rebuild the stack first (§ Test environment step 6) so the container carries the new
      `nginx.conf` and the include file, then:
      `npx playwright test --project=streaming-greybox -g "authorizes through the hop"` and
      `-g "blanks the trust params"`, then the whole project.
      Expected: three passes, and the pre-existing buffering test still green.
- [ ] **Step 5: Run the guards project.**
      Run: `npx playwright test --project=guards`
      Expected: green. `capabilities.spec.ts` names the offender if a capability was reached for
      without an allowlist entry; this task adds none, which is why it must stay green here rather
      than being discovered in CI.
- [ ] **Step 6: Commit.**
      Write `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t10.msg`:
      ```
      test(phase1-pr5): pin the authorize hop in the resolved nginx config

      Two tests beside the buffering pin, in the same file because
      guards/allowlist.ts already grants it the docker exec nginx -T it needs:
      every relay-bound location runs the subrequest and sets all five
      variables, and every location outside the hop carries the blanking include
      and no auth_request. The marker is asserted to be a 64-character hex
      digest, so a config still holding the RELAY_TRUST_TOKEN placeholder — or
      one that regressed to a literal flag — fails here rather than in
      production.
      ```
      `git add e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts` then the gate and
      `git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t10.msg` separately.

### Task 11: The E2E contract specs, and the two pins that flip

**Files:** Create `e2e/tests/streaming/authorize-matrix.spec.ts`.
Modify `e2e/tests/streaming/hidden-channel-streamable.spec.ts` (`test.fail(` at `:92`),
`e2e/tests/streaming/catchup-proxy-mode.spec.ts` (`test.fail(` at `:216`), `e2e/COVERAGE.md`.
**Interfaces:** Consumes the `upstream`, `seed`, `api`, `waitFor`, `asPrincipal` and
`streamClient` fixtures, `StreamStatusError`, and `./helpers`'s `lockedProfile`,
`catchupTimestamp` and `seedCatchupChannel`.

Both pins are `@contract` tests written to fail while the defect stands. Flipping one is not a
one-character edit: a `test.fail()` body is satisfied by any failure, so a body that stops early
can pass vacuously once inverted. Each flip below adds the assertion the inversion needs.

- [ ] **Step 1: Write the new spec.**
      Create `e2e/tests/streaming/authorize-matrix.spec.ts`. Six tests, chosen so that both
      channel flags are asserted on both native surfaces and on one XC root each; the two flipped
      pins (Steps 3 and 4) cover `is_adult` on the XC live root and on the XC timeshift root.
      ```typescript
      import { test, expect, StreamStatusError } from '../../fixtures';
      import { catchupTimestamp, lockedProfile, seedCatchupChannel } from './helpers';

      /**
       * The authorize hop (Phase 1 PR 5, ADR 0005), from outside the container.
       *
       * Every relay-bound location issues `auth_request /_dispatcharr/authorize`
       * before a byte moves, so these tests exercise the same function the seven
       * stream views call inline — through nginx, which is the shape production
       * runs, and through the `error_page` mapping that puts back the statuses
       * nginx's auth_request module cannot carry.
       *
       * `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts` pins the
       * config; this pins the behaviour. Neither substitutes for the other: a
       * correct location table with a broken decision passes there and fails
       * here.
       *
       * Every refusal below asserts an exact status. `>= 400` would pass on a
       * 400 from a malformed setup, a 404 from a channel that never seeded, or
       * a 500 from a broken hop — and a security contract that passes when the
       * fixture is broken proves nothing.
       */

      test(
        'a channel hidden from output is refused even to an anonymous request',
        { tag: '@contract' },
        async ({ upstream, seed, api, streamClient }) => {
          const scenario = await upstream.scenario({
            channels: [{ id: 1, name: 'PR5 Hidden', tvgId: 'pr5-hidden.e2e', logo: null }],
            rate: 20,
          });
          const proxy = await lockedProfile(api, 'Proxy');
          const { channel } = await seed.upstreamChannel(scenario, {
            channelIds: [1],
            streamProfileId: proxy.id,
            channel: { hidden_from_output: true },
          });

          // hidden_from_output is a property of the channel, so it needs no
          // principal — which is exactly why this row is the one that closes the
          // "unlistable yet streamable" gap for an anonymous caller holding a
          // UUID out of a stale playlist.
          await expectRefused(
            streamClient,
            `/proxy/ts/stream/${channel.uuid}`,
            403,
            'a hidden channel must not stream by UUID alone'
          );
        }
      );

      test(
        'an ordinary channel still streams with no credential at all',
        { tag: '@contract' },
        async ({ upstream, seed, api, streamClient }) => {
          // The other half of the row above, and the reason ADR 0005 rejects
          // signed URLs: every cached playlist, tuner URL and third-party
          // integration points at a bare /proxy/ts/stream/<uuid>. If the hop
          // ever starts requiring a principal here, this fails loudly rather
          // than every user's playlist failing quietly.
          const scenario = await upstream.scenario({
            channels: [{ id: 1, name: 'PR5 Plain', tvgId: 'pr5-plain.e2e', logo: null }],
            rate: 20,
          });
          const proxy = await lockedProfile(api, 'Proxy');
          const { channel } = await seed.upstreamChannel(scenario, {
            channelIds: [1],
            streamProfileId: proxy.id,
          });

          await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
          const packets = await streamClient.readPackets(4);
          expect(packets[0]).toBe(0x47);
          expect(packets[188]).toBe(0x47);
          await streamClient.close();
        }
      );

      test(
        'a client-supplied trust marker does not authorize a hidden channel',
        { tag: '@contract' },
        async ({ upstream, seed, api, streamClient }) => {
          // Two layers are under test at once. The marker is an HMAC of
          // SECRET_KEY, so a guessed value cannot match; and nginx overrides
          // every one of these five params in every relay-bound location, so
          // even a correct guess would be discarded before the relay saw it.
          const scenario = await upstream.scenario({
            channels: [{ id: 1, name: 'PR5 Forge', tvgId: 'pr5-forge.e2e', logo: null }],
            rate: 20,
          });
          const proxy = await lockedProfile(api, 'Proxy');
          const { channel } = await seed.upstreamChannel(scenario, {
            channelIds: [1],
            streamProfileId: proxy.id,
            channel: { hidden_from_output: true },
          });

          await expectRefused(
            streamClient,
            `/proxy/ts/stream/${channel.uuid}`,
            403,
            'a forged marker must not authorize anything',
            {
              'X-Dispatcharr-Authorized': '1',
              'X-Relay-Channel': channel.uuid,
              'X-Relay-User': '1',
            }
          );
        }
      );

      test(
        'a hidden channel is refused on the native catch-up route to a JWT viewer',
        { tag: '@contract' },
        async ({ upstream, seed, api, asPrincipal, streamClient }) => {
          // The native catch-up surface, /proxy/catchup/<uuid>, which no other
          // test in this file reaches: the flipped #95 pin drives the XC
          // timeshift root instead, and the two entry points share
          // _serve_catchup but not their prologues.
          //
          // The principal is the pre-provisioned `standard` roster entry
          // (user_level 1), whose access token `bootstrap` minted before any
          // worker started. asPrincipal is free; POST /api/accounts/token/
          // would spend one of the three logins the whole run is allowed.
          // Nothing here mutates the principal, which is what that roster
          // requires.
          const scenario = await upstream.scenario({
            channels: [{ id: 1, name: 'PR5 Catchup Hidden', tvgId: 'pr5-catchup-hidden.e2e', logo: null }],
            rate: 20,
          });
          const proxy = await lockedProfile(api, 'Proxy');
          const { channel } = await seed.upstreamChannel(scenario, {
            channelIds: [1],
            streamProfileId: proxy.id,
            channel: { hidden_from_output: true },
          });

          const standard = await asPrincipal('standard');
          const token = await standard.freshAccessToken();
          const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

          // `start` is supplied so a 400 ("Missing start parameter") cannot be
          // mistaken for the refusal under test: the hop answers before the
          // view ever looks at it, so the only 403 available here is the
          // hop's.
          await expectRefused(
            streamClient,
            `/proxy/catchup/${channel.uuid}?token=${token}&start=${start}`,
            403,
            'a hidden channel must not serve its archive to a non-admin'
          );
        }
      );

      test(
        'a hidden channel is refused on the XC live root to an ordinary XC user',
        { tag: '@contract' },
        async ({ upstream, seed, api, streamClient }) => {
          // hidden_from_output on an XC root form. The flipped #87 pin covers
          // is_adult on this same route, so between them both flags are
          // asserted on the XC live surface with a credentialed principal.
          const scenario = await upstream.scenario({
            channels: [{ id: 1, name: 'PR5 XC Hidden', tvgId: 'pr5-xc-hidden.e2e', logo: null }],
            rate: 20,
          });
          const proxy = await lockedProfile(api, 'Proxy');
          const { channel } = await seed.upstreamChannel(scenario, {
            channelIds: [1],
            streamProfileId: proxy.id,
            channel: { hidden_from_output: true },
          });
          const viewer = await seed.xcUser({ user_level: 1 });

          await expectRefused(
            streamClient,
            `/live/${viewer.username}/${viewer.xcPassword}/${channel.id}`,
            403,
            'a hidden channel must not stream to an XC client'
          );
        }
      );

      test(
        'an adult channel is refused on the XC catch-up root to a hide_adult_content viewer',
        { tag: '@contract' },
        async ({ upstream, seed, api, waitFor, streamClient }) => {
          // Seeded through seedCatchupChannel, not seed.upstreamChannel with
          // is_catchup patched on: that helper exists because a Channel flagged
          // is_catchup with no catch-up-advertising Stream behind it has no
          // provider stream id for _prepare_catchup_stream_attempt, and the
          // request then fails with "Cannot build timeshift URL" (400) — which
          // an exact-403 assertion catches and a `>= 400` one would not.
          const { channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
          await api.patch(`/api/channels/channels/${channel.id}/`, { is_adult: true });
          const viewer = await seed.xcUser({
            user_level: 1,
            custom_properties: { hide_adult_content: true },
          });
          const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

          await expectRefused(
            streamClient,
            `/timeshift/${viewer.username}/${viewer.xcPassword}/60/${start}/${channel.id}.ts`,
            403,
            'an adult channel must not serve its archive to a filtered viewer'
          );
        }
      );

      /**
       * Open `path` and require an exact refusal status.
       *
       * Only a StreamStatusError of exactly `status` counts. A reset, a DNS
       * failure, a 500 or a different 4xx rethrows, so a broken fixture fails
       * the test instead of reading as "the product refused it" — the failure
       * mode that matters most in a file whose whole subject is refusals.
       */
      async function expectRefused(
        streamClient: { open: (p: string, o?: { headers?: Record<string, string> }) => Promise<void>; close: () => Promise<void> },
        path: string,
        status: number,
        message: string,
        headers?: Record<string, string>
      ): Promise<void> {
        let refused = false;
        try {
          await streamClient.open(path, headers ? { headers } : {});
        } catch (error) {
          if (!(error instanceof StreamStatusError) || error.status !== status) throw error;
          refused = true;
        }
        try {
          expect(refused, message).toBe(true);
        } finally {
          // Abort whatever was opened, so a failing run does not leave an
          // upstream connection held for the rest of the project.
          await streamClient.close();
        }
      }
      ```
      Two things to check against the tree before running, both one grep each: that
      `catchupTimestamp`, `lockedProfile` and `seedCatchupChannel` are all exported from
      `e2e/tests/streaming/helpers.ts` (`grep -n "^export" e2e/tests/streaming/helpers.ts`), and
      that `StreamClient`'s type is importable if `tsc` rejects the structural parameter type
      above — in which case import the class and annotate with it rather than widening the
      signature.
- [ ] **Step 2: Typecheck and run the new spec.**
      Run: `cd e2e && npx tsc --noEmit`, then, against this worktree's stack (§ Test environment
      step 6), each of the six titles in turn:
      `-g "a channel hidden from output is refused even to an anonymous request"`,
      `-g "an ordinary channel still streams with no credential at all"`,
      `-g "a client-supplied trust marker does not authorize a hidden channel"`,
      `-g "a hidden channel is refused on the native catch-up route to a JWT viewer"`,
      `-g "a hidden channel is refused on the XC live root to an ordinary XC user"`,
      `-g "an adult channel is refused on the XC catch-up root to a hide_adult_content viewer"`.
      Expected: six passes. `-g` matches on the full title, so run them one at a time rather than
      trusting a short pattern to select what you meant.
- [ ] **Step 3: Flip the #87 pin.**
      In `e2e/tests/streaming/hidden-channel-streamable.spec.ts`, change `test.fail(` at `:92` to
      `test(`, and replace the block comment above it (`:64-91`) with one that states the closed
      behaviour rather than the open defect:
      ```typescript
      // Closed by Phase 1 PR 5. Every stream surface now authorizes through
      // apps/proxy/authorize.py's authorize_stream(), which applies the user's
      // hide_adult_content against Channel.is_adult — the check every listing
      // path already applied and stream_xc did not. The refusal is a 403 from
      // the authorize hop rather than the 404 stream_xc's deleted filter would
      // have produced: the channel exists, and this user may not have it.
      //
      // Kept in its inverted-pin shape (the try/catch that accepts only 403 or
      // 404, and rethrows anything else) on purpose. A bare "expect a refusal"
      // rewrite would go green on a connection reset or a 500, which is exactly
      // the failure mode a security assertion must not have.
      //
      // Issue: https://github.com/D10Scot/Dispatcharr/issues/87 — closed by
      // PR 8, which references this PR.
      ```
      The body already ends in `expect(served, …).toBe(false)`, so the uninverted test asserts the
      fix rather than passing vacuously. No other change.
- [ ] **Step 4: Flip the #95 pin, and give it the assertion the inversion needs.**
      In `e2e/tests/streaming/catchup-proxy-mode.spec.ts`, change `test.fail(` at `:216` to
      `test(`, rewrite the "KNOWN BUG — issue #95" comment the same way as Step 3, and **add the
      missing assertion**: the body's shape is `if (!refusedAtOpen) { … }`, so once the fix lands
      and `open()` throws a 4xx, the block is skipped and nothing is asserted at all. After the
      `try/catch`, before that `if`, insert:
      ```typescript
          // The pin's inversion made this necessary: with the fix in place
          // open() throws, refusedAtOpen is true, and the block below is
          // skipped — so without this line the test would pass having asserted
          // nothing. The block stays for the case where a future regression
          // serves the archive again: it then proves no playable packets reach
          // this viewer, which is the strong form of the bug.
          expect(
            refusedAtOpen,
            'an adult channel must be refused to a hide_adult_content viewer at open'
          ).toBe(true);
      ```
- [ ] **Step 5: Run both flipped pins and their controls.**
      Run, one exact title at a time:
      `-g "a channel a user cannot list is not streamable by that user"`,
      `-g "an adult channel is unlistable for a hide_adult_content user and listable for an admin"`,
      `-g "an adult channel a user cannot list is also refused on the catch-up path"`,
      `-g "row 8 premise: a Standard viewer with hide_adult_content cannot list an adult channel"`.
      Expected: four passes, none reported as "expected failure". The two controls are
      non-inverted and were passing before this PR; they must still pass, or the premise the pins
      rest on moved rather than the defect closing.
- [ ] **Step 6: Run the whole `streaming` project.**
      Run: `npx playwright test --project=streaming`
      Expected: green. This is the run that catches an over-broad refusal — any existing test that
      tunes anonymously, or as a seeded non-admin, now goes through the hop. Two shapes of failure
      are worth naming in advance: a test seeding a channel into no Channel Profile and then
      streaming it as a profile-holding user (the membership filter now applies on the streaming
      path), and a test relying on a 404 where the hop now answers 403.
- [ ] **Step 7: Run `streaming-failover` too.**
      Run: `npx playwright test --project=streaming-failover`
      Expected: green. Nothing in this PR touches failover, but every one of its tests starts with
      a tune, so it is the cheapest broad check that the hop did not change the cost or the shape
      of connecting.
- [ ] **Step 8: Add the `COVERAGE.md` row, after checking nothing validates the column.**
      `e2e/README.md:691` ("Update `COVERAGE.md` in the same PR as the test") and `CLAUDE.md`
      § Testing are the standing rule; amendment S5 records that this overrides § PR 8's bullet
      for this PR's own row. The `Goal` column has only ever held `G1`–`G15`, and Phase 1 is not a
      goal, so this row introduces `P1`.
      First:
      Run: `grep -rn "COVERAGE" e2e/tests/guards/ scripts/ metrics/`
      Expected: hits in `scripts/metrics/collect_tests.py` (`:39-55`) and prose in
      `scripts/metrics/README.md` and `metrics/curated/*.yml`; nothing in `e2e/tests/guards/`. The
      collector is the only thing that parses the file, and `COVERAGE_ROW_RE` reads the **Status**
      column alone (`done|known-bug|todo`) — it has no `Goal` vocabulary, so `P1` needs no change
      there. What it does mean: the new row's `done` is counted by the metrics collector, so the
      `metrics/**` edit hook's suite must stay green after this edit (Task 12 Step 6 runs it). If
      this grep now finds something that reads the `Goal` column, extend its vocabulary with `P1`
      in this same task and say so in the task report.
      Then add one row to `e2e/COVERAGE.md`, immediately after the **last** `| Streaming |` row
      (the G14 `allowed_networks["STREAMS"]` gap row, currently `:193`) — the `Streaming` rows run
      `:177-193`, and the only row naming `/proxy/ts/stream/` is an `Upstream`/G2 row at `:28`,
      which is not where this belongs:
      ```markdown
      | Streaming | Authorize hop: `hidden_from_output` refuses an anonymous UUID tune, an ordinary channel still streams with none, a forged `X-Dispatcharr-Authorized` authorizes nothing, and both channel flags refuse on the native catch-up route and the XC live and timeshift roots ([#87](https://github.com/D10Scot/Dispatcharr/issues/87), [#95](https://github.com/D10Scot/Dispatcharr/issues/95)) | P1 | done |
      ```
      PR 8 adds the four rows it owns (time to first byte, Django-down, bounded relay restart,
      modular role split).
- [ ] **Step 9: Commit.**
      Write `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t11.msg`:
      ```
      test(phase1-pr5): the authorize matrix end to end, and two pins flipped

      Six @contract tests drive the hop through nginx: a channel hidden from
      output is refused with no principal, an ordinary channel still streams
      with none, a client-supplied trust marker authorizes nothing, and both
      channel flags refuse on the native catch-up route and on the XC live and
      timeshift roots. Every refusal asserts an exact status — a >= 400
      assertion would pass on a 400 from a malformed fixture, which is not
      evidence of a security decision.

      hidden-channel-streamable.spec.ts (#87) and catchup-proxy-mode.spec.ts
      (#95) stop being test.fail() pins. The catch-up one gains an explicit
      assertion on refusedAtOpen: its body only asserted inside an
      if (!refusedAtOpen) block, which the fix now skips, so uninverting it
      without that line would have passed while asserting nothing.
      ```
      `git add e2e/tests/streaming/authorize-matrix.spec.ts e2e/tests/streaming/hidden-channel-streamable.spec.ts e2e/tests/streaming/catchup-proxy-mode.spec.ts e2e/COVERAGE.md`
      then the gate and `git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t11.msg` separately.

### Task 12: The ledger, `CLAUDE.md`, and the spec amendments

**Files:** Modify `metrics/curated/defects.yml` (rows `hidden-channel-streamable` `:15` and
`hidden-catchup-streamable` `:16`, plus one new row for #100), `CLAUDE.md` (three statements),
`docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md` (one Consequences bullet), and
`docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` (amendments S1-S8, plus the
Done log row).
**Interfaces:** Consumes this PR's own number, which exists from the moment the draft PR opens.

- [ ] **Step 1: Correct the three `CLAUDE.md` statements.**
      1. § Known defects and traps › Security, the Xtream bullet. Reworded, not removed — the
         passwords are still plaintext at rest:
         ```markdown
         - Xtream passwords plaintext in `custom_properties["xc_password"]`; the comparison is
           `hmac.compare_digest` on every streaming surface since Phase 1 PR 5 (one implementation,
           `apps/proxy/authorize.py`'s `resolve_xc_user`), but the value at rest is unchanged and
           the listing surfaces still compare their own way. API keys looked up by plaintext value,
           unscoped.
         ```
      2. § Architecture › Auth, the "Streaming is the opposite" sentence:
         ```markdown
         **Auth — two opposite defaults.** REST API is deny-by-default … Streaming is the
         opposite: `stream_ts` is `AllowAny` and a channel UUID is still the capability, but since
         Phase 1 PR 5 every relay-served surface authorizes through one function,
         `apps/proxy/authorize.py`'s `authorize_stream`, reached by nginx `auth_request` once per
         tune and inline where there is no nginx. It applies the STREAMS ACL (XC_API on the XC
         catch-up path), the principal, `user_level`, Channel Profile membership,
         `hidden_from_output`, the user's `hide_adult_content` against `Channel.is_adult`, the
         Output Profile and the live stream limit. An anonymous request with a valid UUID still
         streams an ordinary channel; a channel marked `hidden_from_output` no longer streams to
         anyone but an admin or an internal principal. **A channel UUID is a secret; treat it as
         one.**
         ```
      3. § Known defects and traps, the copy-pasted-filter bullet. The text being replaced opens
         `Channel-authorization filter copy-pasted across **eight** sites` — **eight** is what
         `CLAUDE.md:111` says today, and it is the number to quote and correct, not the twelve the
         spec's own § What the code says arrived at. Two clauses change: the count, and "hidden
         channels are unlistable yet streamable", which becomes closed on the relay-served
         surfaces. The HDHR sentence after it is untouched — a different defect with a different
         fix, and this PR closes neither half of it.
- [ ] **Step 2: Count the sites before you write the number.**
      `grep` counts lines, and one site can span several: `stream_xc`'s deleted block alone held
      two `user_level__lte` lines.
      Run: `grep -rn "user_level__lte" apps/ --include='*.py' | grep -v tests`
      Expected: 17 lines after this PR (19 before it, minus the two in
      `apps/proxy/live_proxy/views.py`), across `apps/channels/api_views.py`,
      `apps/epg/api_views.py`, `apps/output/epg.py` and `apps/output/views.py` — and **none** in
      `apps/proxy/live_proxy/views.py` or `apps/timeshift/views.py`, which is the assertion that
      matters. Then count *sites* — distinct functions applying the filter — by reading those
      four files' hits, and write that number into `CLAUDE.md`. Put the number you counted and how
      you counted it in the task report; the executor before you wrote "eight" and nobody has
      re-derived it since.
- [ ] **Step 3: Apply the eight spec amendments.**
      Edit `docs/superpowers/specs/2026-09-04-phase1-process-split-design.md` per the § Spec
      amendments table above (S1-S8), quoting the replaced text in each case, and tick the Done
      log's "Authorize hop" row with this PR's number once Step 5 has it.
- [ ] **Step 3b: Amend ADR 0005's Consequences bullet.**
      An accepted ADR that misdescribes the tree is worse than no ADR. In
      `docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md` § Consequences, replace:
      ```markdown
      - The relay drops two imports it holds today: `apps.accounts` (user
        resolution) and any direct read of `M3UAccount`/`OutputProfile` at
        tune time, both now resolved by Django before the relay is reached.
      ```
      with:
      ```markdown
      - The relay stops *resolving* a principal or an Output Profile: which user,
        and which profile, are Django's answers, carried in `X-Relay-User` and
        `X-Relay-Output`. It still reads both rows by primary key — `add_client`
        stores the `User`, and `OutputProfile.build_command()` is model behaviour
        a header cannot carry — so the tune-time ORM reads fall from a resolution
        chain to two indexed lookups rather than to zero. `M3UAccount`'s
        tune-time reads move behind the next-source call in PR 6, not here.
      ```
      Nothing else in the ADR changes: its decision, its rejected alternatives and its status all
      stand. Note the amendment beside S3 in the plan's table when reporting.
- [ ] **Step 4: Open the PR as a draft, and get its number.**
      Run: `gh pr create --draft --repo D10Scot/Dispatcharr --base main --head migration/phase1-authorize --title "..." --body-file <a file written with the Write tool>`
      then `gh pr view --repo D10Scot/Dispatcharr --json number -q .number`
      Expected: an integer.
      **Draft, not ready.** `pr-review` triggers on every non-draft `pull_request` event and
      reviews each PR exactly once (`CLAUDE.md` § Agentic workflows), so opening a ready PR here
      would spend that single review on a half-built branch and leave the finished one unreviewed.
      Mark it ready after Task 13 passes.
      The body lists **#87, #95 and #100** as issues this PR closes, and says that the
      `wontfix` label on #87 — applied in error by triage, per `docs/agents/metrics.md` — is
      removed by hand by the orchestrator rather than by this plan. Do not script the label edit.
- [ ] **Step 5: Move the two ledger rows to `fixed`, and add a third for #100.**
      In `metrics/curated/defects.yml`, for `hidden-channel-streamable` and
      `hidden-catchup-streamable`: `status: pinned` → `status: fixed`, `fixed_in: null` → the
      number from Step 4, `status_changed:` → `2026-09-05` (or the day the task runs). Leave
      `issue`, `test`, `title`, `first_seen` and `area` exactly as they are — the `test` paths
      still exist and now hold passing tests, which is what `fixed` means here.
      Both rows move `pinned → fixed`, which the validator's forward-only rule allows.
      #100 has **no row today** — it was filed while writing `xc-vod-playback.spec.ts` and never
      reached the ledger. Add one in the file's existing single-line shape, with the same field
      order every other row uses, straight to `fixed` (`open → fixed` is an allowed move):
      ```yaml
      - {id: xc-vod-wrong-password-nameerror, title: "stream_xc_movie/stream_xc_episode answer 500 on a wrong XC password: the rejection branch calls an unimported Response", area: correctness, severity: medium, status: fixed, source: null, issue: 100, test: e2e/tests/streaming/xc-vod-playback.spec.ts, fixed_in: <the number from Step 4>, carried_as: null, first_seen: 2026-09-01, status_changed: 2026-09-05}
      ```
      `first_seen` is the day the pin was written (`git log --format=%ad --date=short -1 -- e2e/tests/streaming/xc-vod-playback.spec.ts` gives the file's last touch; use the commit that added
      the `test.fail` if they differ). The `test` path is the pin that now passes.
- [ ] **Step 6: Validate the ledger.**
      The edit hook fires on any write under `metrics/`, so this runs itself if the hook is wired;
      run it by hand in this worktree, where it is not.
      Run: `python3 -m metrics.build --validate-only --curated metrics/curated`
      Expected: no errors. Then `scripts/run_metrics_tests.sh build`.
      Expected: pass. Errors are listed all at once, so read the whole output before editing —
      a mistyped `area` or `severity` in the new #100 row is reported beside anything else wrong.
      The offline form does not verify the PR number; the Pages build does, after merge.
- [ ] **Step 7: Commit.**
      Write `/private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t12.msg`:
      ```
      docs(phase1-pr5): CLAUDE.md, the defect ledger and the spec amendments

      CLAUDE.md's three now-wrong statements: the plaintext-!= security bullet
      (compare_digest on every streaming surface, still plaintext at rest), the
      "gated only by network_access_allowed" sentence in § Architecture § Auth,
      and the "hidden channels are unlistable yet streamable" clause — closed on
      the relay-served surfaces, with the copy-pasted-filter count re-derived
      from the tree and HDHomeRun's separate defect explicitly untouched.

      ADR 0005's Consequences bullet said the relay drops any direct read of
      OutputProfile at tune time. It drops the *resolution*, not the read: a
      header cannot carry a built ffmpeg command, so the relay still loads that
      row and the User row by primary key. The bullet now says so.

      metrics/curated/defects.yml moves hidden-channel-streamable (#87) and
      hidden-catchup-streamable (#95) from pinned to fixed, and gains a row for
      #100, which had none — the wrong-XC-password NameError this PR removes by
      construction. The issues themselves are closed by PR 8, which references
      this one.

      Eight spec amendments recorded in the spec itself, each quoting what it
      replaces: where the stream limit is enforced and why, what X-Relay-Channel
      and X-Relay-Output are consumed by, that catch-up answers 401 for an
      anonymous request, that a 404 or 429 decision travels as 403 because
      auth_request carries nothing else, and that two locations sit outside the
      hop rather than one.
      ```
      `git add CLAUDE.md metrics/curated/defects.yml docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md docs/superpowers/specs/2026-09-04-phase1-process-split-design.md docs/superpowers/plans/2026-09-05-phase1-pr5-authorize.md`
      then the gate and `git commit -F /private/tmp/claude-501/-Users-dion-git-Dispatcharr/9de80702-70b9-435e-bd46-fdd28f580c22/scratchpad/pr5-t12.msg` separately.

### Task 13: Full local verification

**Files:** Modify none. Nothing here writes; this is the evidence the PR is what it claims.
**Interfaces:** Consumes the whole worktree.

- [ ] **Step 1: The four backend labels.**
      Run § Test environment step 4 for `apps.proxy.tests`, `apps.proxy.live_proxy.tests`,
      `apps.channels.tests`, `apps.timeshift.tests`, one at a time.
      Expected: four `OK`s, each with a count at least as high as Task 1 Step 5 recorded.
- [ ] **Step 2: The rest of the backend.**
      Run § Test environment step 4 with no label, which expands to all 16 (CI will run all 16
      here anyway, because `dispatcharr/` is a shared prefix).
      Expected: `OK`. A failure outside the four labels above is the interesting kind — record it
      with its module name before touching anything.
- [ ] **Step 3: The credential guard over every Python file this PR touched.**
      Run:
      ```bash
      python3 scripts/check_credential_logging.py \
        apps/proxy/authorize.py apps/proxy/authorize_views.py apps/proxy/internal_auth.py \
        apps/proxy/live_proxy/views.py apps/proxy/vod_proxy/views.py \
        apps/timeshift/views.py apps/channels/tasks.py dispatcharr/utils.py \
        dispatcharr/urls.py dispatcharr/settings.py
      ```
      Expected: exit 0, no output.
- [ ] **Step 4: E2E typecheck and the four projects.**
      Run: `cd e2e && npx tsc --noEmit`, then `--project=guards`, `--project=streaming`,
      `--project=streaming-greybox`, `--project=streaming-failover` against this worktree's stack.
      Expected: four green projects and a clean typecheck.
- [ ] **Step 5: The two bash lifecycle scenarios that touch the split.**
      Run, under Homebrew bash 5.3 (the system bash is 3.2 and the suites use associative arrays).
      The scenario name is a **positional** argument — the script's own usage block
      (`docker/tests/test-puid-pgid.sh:15-30`) is
      `bash docker/tests/test-puid-pgid.sh [--skip-build] [--keep-on-fail] [scenario_name]`, and
      the name carries no `test_` prefix:
      ```bash
      /opt/homebrew/bin/bash docker/tests/test-puid-pgid.sh role_split
      /opt/homebrew/bin/bash docker/tests/test-puid-pgid.sh modular_mode
      ```
      Expected: both pass. `test_role_split` is the only test in the programme that exercises the
      modular relay hop, and it now tunes through `auth_request` — if the trust token did not reach
      the api container's nginx, this is where it shows. Add `--skip-build` only if an image built
      from *this* worktree already exists; a stale one would test PR 4's nginx config.
- [ ] **Step 6: The frontend suite.**
      Run: `cd frontend && npm ci && npm test`
      Expected: green. This PR touches no frontend source; the run is here because
      `Frontend result` is a required check and a surprise there is better found now.
- [ ] **Step 7: Report.**
      State, in the task report: every command run, its result, and — explicitly — anything that
      did **not** run and why. Per § Test environment step 7, a container that would not start
      makes the work unverified, not verified.

## Notes for the reviewer

- **Where the behaviour changes, deliberately.** A `hidden_from_output` channel stops streaming to
  everyone but an admin or an internal principal, including anonymously. An `is_adult` channel
  stops streaming to a `hide_adult_content` user on every relay-served surface. An Xtream client
  asking for a channel it may not see gets 403 rather than 404. Wrong Xtream credentials on the
  **catch-up** path get 401 rather than the 403 `_timeshift_proxy_impl` answers today, matching
  the other three XC surfaces. Wrong Xtream credentials on the **movie and series** routes get a
  real 401 rather than the 500 an unimported `Response` produced (#100). A catch-up refusal's body
  becomes JSON. `/proxy/ts/stream/` accepts `?token=` for the first time, by union with the other
  three views' authenticator sets.
- **What nginx can and cannot carry, and what that costs.** `auth_request` transports only 401 and
  403; every other subrequest status becomes a 500. The hop therefore sends 404 and 429 as 403
  with `X-Authorize-Status`, and `error_page 403 = @authorize_denied` restores them — so the
  client-visible vocabulary is unchanged, but it now depends on an nginx block as well as on
  Django. Two consequences follow. A denial's **body** through nginx is nginx's own page, as it
  already was for any `auth_request` refusal. And Django being down on a **new tune** answers
  **500**, not the `{502, 503, 504}` the spec's § Error handling predicted for PR 8's test — that
  row is amended here (S7) rather than left for PR 8 to discover.
- **Where it does not.** An anonymous request with a valid UUID for an ordinary channel still
  streams — that is the row every cached playlist depends on and the reason ADR 0005 rejects signed
  URLs. `/proxy/ts/stream/<stream_hash>` keeps exactly today's behaviour, having no channel to
  check. The admin preview keeps working, which is what the admin bypass row is for. HDHomeRun is
  untouched: its four views resolve no user at all, which is a different defect with a different
  fix.
- **The two ORM reads the relay keeps** are a `User` row from `X-Relay-User` and an `OutputProfile`
  row from `X-Relay-Output`, both by primary key. What moved to Django is the resolution *rule*,
  not the row fetch; a header cannot carry a built ffmpeg command. Amendment S3 records this so
  PR 6 and PR 7 do not read it as an unfixed leak.
- **Two limit checks stay in their views** (VOD, catch-up) for reasons amendment S1 states in full.
  A grep for `check_user_stream_limits` in the stream views is therefore expected to find two hits
  after this PR, not zero.







