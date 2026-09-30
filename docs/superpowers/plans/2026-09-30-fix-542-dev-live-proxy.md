# Plan: fix #542, dev mode plays live streams again

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. Every file change is Appendix A: a byte-exact `git diff` against the seed. The implementer applies it with `git apply` and does not rewrite it. If it does not apply at the branch base, the implementer stops and reports; it does not hand-merge.

**Goal.** In dev mode (`DISPATCHARR_ENV=dev`, the `all-dev` rung: vite on :9191, no nginx) the browser plays a live channel again, over MPEG-TS and over HLS. This has been broken since Phase 2 stage 2d-3 moved the live surface to `relay-go`. Two changes do it:

1. vite proxies the live surface to `relay-go`: `/proxy/ts/stream/`, `/live/`, `/hls/` and nginx's XC three-segment root.
2. The six dev-mode live-URL builders in the frontend stop sending the browser straight to Django on `:5656`, so their requests reach vite.

**Seed.** `a1e9da653ed3f036ca7aa5d0033518d5fca22a48` (`a1e9da65`, `origin/main`, "docs(phase4): close out 4a"). Every `file:line` below is at `a1e9da65`, read with `git show "a1e9da65:<path>"`.

**Branch.** `fix/542-dev-live-proxy`, off `origin/main`. This plan is the branch's first commit and the fix lands in the same PR, so the PR carries `Closes #542.`

**Authority.** In order of precedence:

1. Orchestrator rulings.
   - **R97**: fix with vite proxy entries to `relay-go` and rely on the relay's inline authorize. No nginx in dev.
   - **R100**, which amends R97:
     - vite entries for `/proxy/ts/stream/`, `/live/`, `/hls/` and the XC regex. The regex is listed last, after `/api`, and carries an optional `(?:\?.*)?`.
     - Drop the dev-mode `:5656` prefix at the six live call sites. Leave the VOD, series and recording-file rewrites untouched.
     - The target port is read from `process.env.DISPATCHARR_RELAY_GO_PORT`, falling back to 5658.
     - State that a dev STREAMS network ACL judges `127.0.0.1`.
     - Pin with a vitest over the proxy table plus same-origin assertions for the builders under `env_mode` `'dev'`, each with a break-check.
     - Specify the live dev-container check.
   - **R111** (plan review round 1, finding 1): the `/api` and `/ws` keys become `'/api/'` and `'/ws/'`, matching nginx's `^~ /api/` and `^~ /ws/` (`docker/nginx.conf:177`, `:274`). Without the trailing slash an XC username starting with `api` or `ws` (`/wsmith/pass/123.ts`) is caught by the prefix before the XC regex and goes to Django or Daphne rather than relay-go. The XC routing test gains a `/wsmith/…` and an `/apiuser/…` row, and B10 and B11 pin them.
2. **The code at `a1e9da65`.** The premise is verified below: § Premise.
3. CLAUDE.md:
   - § Commands and its dev bullets (`CLAUDE.md:43`, `:52`).
   - § Frontend.
   - § Test hooks: the frontend hook runs vitest on an edited `*.test.{js,jsx}`, and the commit gate runs the whole frontend suite for any `frontend/` path.
   - The test-modification rule (§ Delegation, via `implement-review-escalate`).
4. `docker/nginx.conf:304` (`^~ /proxy/ts/stream/`), `:484` (`^~ /hls/`), `:492` (`^~ /live/`) and `:651` (the XC regex), which the dev table mirrors.

**Issues.** `Closes #542.` in the PR body. No other issue is touched.

## Premise, verified at `a1e9da65`

R97's premise has two halves, and only the first held as R97 stated it. R100 exists because the second did not.

**The relay authorizes an untrusted tune itself.**

| Surface | Path through the relay | Evidence |
|---|---|---|
| TS tune `/proxy/ts/stream/<uuid>` | `StreamHandler` calls `authorizeTune()` before `identify()`. With no valid `X-Dispatcharr-Authorized`, `authorizeTune` POSTs the full `RequestURI()`, the peer address and the `Authorization`/`Cookie`/`X-API-Key` headers to Django's `POST /_dispatcharr/authorize-internal`. The decision's values replace the `X-Relay-*` headers, and a denial reaches the viewer as its own 401/403/404/429. | `relay/httpapi/stream.go:247-256`, `relay/httpapi/authorize.go:29-62`, `:113-127`, `relay/control/authorize.go:23`, `dispatcharr/urls.py:59`, `apps/proxy/authorize_views.py:366` |
| XC live roots `/live/u/p/<id>`, `/u/p/<id>` | `XCHandler` wraps `StreamHandler`: the same path, plus the extension-forced format | `relay/httpapi/xc.go:40-41` |
| HLS entry `/proxy/ts/stream/<uuid>?output_format=hls` | The TS route: `authorizeTune`, then `serveHLSEntry`. The multivariant names `/hls/<token>/…` as **absolute paths**, so every later request goes to the entry's origin. | `relay/httpapi/stream.go:300-301`, `relay/httpapi/hls.go:363` |
| HLS session resources `GET /hls/<token>/…`, `DELETE /hls/<token>` | Authorized by the media-session token alone. No nginx marker and no hop are needed. | `relay/httpapi/hls.go:436-449`, `:659-661` |
| The routes exist in all-dev | Everything but the probes sits behind `cfg.DevRoutes`. `relay-go.conf` sets `DISPATCHARR_RELAY_GO_DEV_ROUTES="1"`, `devRoutes()` defaults it on under `DISPATCHARR_ENV=dev` anyway, and `all-dev.conf`'s `[include]` starts `relay-go.conf`. | `relay/httpapi/server.go:62-81`, `docker/supervisord.d/relay-go.conf:43`, `relay/config/config.go:146-156`, `docker/supervisord/all-dev.conf` |
| The relay can reach Django in dev | `BaseURL()` returns `http://127.0.0.1:5656` for `dev` | `relay/control/baseurl.go:63-67` |
| The relay's port is visible to vite | `docker/entrypoint.sh:236` exports `DISPATCHARR_RELAY_GO_PORT` (default 5658) before supervisord starts, and `[program:vite]` inherits it | `docker/entrypoint.sh:236`, `docker/supervisord.d/vite.conf` |

**This half broke: the frontend never sent a live URL to vite in dev.** Every live-player call site built an absolute `http://<host>:5656/…` URL in dev. In the dev container `:5656` is api-uwsgi (`docker/uwsgi.dev.ini:23`), which answers `/proxy/ts/stream/` with the 501 stub (`apps/proxy/stream_routes.py:60`). Pointing those URLs at `:5658` instead would be cross-origin from :9191. `relay-go` sends no CORS headers, so mpegts.js's fetch and hls.js's XHR would both be blocked. The six sites (R100):

| # | Site | Seed lines | Non-dev form it now always uses |
|---|---|---|---|
| 1 | `ChannelsTable.jsx` `getChannelURL` (Copy URL) | `:647-661` | `${protocol}//${host}${path}` |
| 2 | `ChannelsTable.jsx` `handleWatchStream` (the channel's HLS entry) | `:663-675` | `${protocol}//${host}${uri}` |
| 3 | `ChannelTableStreams.jsx` `handleWatchStream` | `:402-414` | the relative `buildLiveStreamUrl(...)` |
| 4 | `StreamsTable.jsx` `handleWatchStream` | `:953-959` | the relative `buildLiveStreamUrl(...)` |
| 5 | `StreamConnectionCard.jsx` `handlePreviewChannel` | `:510-525` | `${protocol}//${host}${uri}` |
| 6 | `RecordingCardUtils.js` `getShowVideoUrl` (Guide, DVR, RecordingCard, RecordingDetailsModal, ProgramDetailModal) | `:62-68` | the relative `buildChannelHlsUrl(...)` |

**Measured, not only read.** The planner built the fork image from the prototype tree and ran it as `dispatcharr-dev-542`:

- Build: the prototype is Appendix A applied to the seed, on the base by digest `ghcr.io/d10scot/dispatcharr@sha256:a199d4e9…`, which ships ffmpeg 9.0.
- Run: `DISPATCHARR_ENV=dev`, a scratch export bind-mounted at `/app`.
- Source: a private fake provider `e2e-upstream-542` on a private network.

Every request below went through vite on :9191:

| Request (through vite) | Result |
|---|---|
| `GET /proxy/ts/stream/<uuid>?output_format=mpegts` | **200** `video/mp2t`, 3,326,284 bytes in 20 s, every 188th byte `0x47` |
| the same, sent straight to `:5656` (the seed's dev URL) | **501** (the stub). This is the defect. |
| channel set `hidden_from_output`, anonymous tune | **403**. The inline authorize runs and decides. |
| the same with `?token=<admin JWT>` | **200** |
| `GET /live/xc542/xcpw/1.ts` | **200** `video/mp2t` |
| `GET /xc542/xcpw/1.ts`, `GET /xc542/xcpw/1?x=1` (the regex key) | **200** `video/mp2t`, first byte at ~5.1 s (channel start) |
| `GET /proxy/ts/stream/<uuid>?output_format=hls` | **502** `{"error": "HLS output failed"}`: see below |

**The HLS 502 is not caused by vite or by dev mode.** It is the relay's own `failureBody`, which is only reached after the authorize, the tune and `AttachHLS`. The same 502 came back:

- sent straight to `relay-go` on `127.0.0.1:5658` inside the container, bypassing vite;
- from an **AIO** container (`DISPATCHARR_ENV=aio`, nginx in front) of the same image against the same provider, which served TS correctly.

With `ffprobe` wrapped to capture its stderr, the probe (`-probesize 3000000 -analyzeduration 3000000 -f mpegts -i pipe:0 -show_streams -of json`) reported `pipe:0: End of file`. The relay's feed closed stdin before writing the bytes ffprobe needed. The same argv run by hand as the relay's user, against a `curl` of the same upstream, exits 0.

**The planner does not know why.** The environment is local arm64 Docker Desktop. The 4a E2E HLS specs pass in CI on amd64 against the same provider image. This is recorded as open question Q1 and is out of this PR's scope: nothing this plan changes is on the relay's side of the hop. It does mean that on this environment the HLS half of the live check can only show parity with AIO, not playback. The live check below says so.

## Global constraints

1. **Only `frontend/` and `CLAUDE.md` change.** No Go, no Python, no nginx, no workflow, no migration. So neither coverage gate runs and no parity-matrix row is added: the relay behaviour relied on is dev-only and unchanged.
2. **No new dependency.** `devProxy.js` imports nothing.
3. **Production is unchanged.** Every site's non-dev branch already built the form it now always builds. vite's `server.proxy` is used only by `vite` / `npm run dev` and never by `npm run build`.
4. **The VOD, series, recording-file and logo/poster API `:5656` rewrites stay.** These are:
   - `RecordingCardUtils.js:41` and `:57`: the logo/poster API URLs (`/api/channels/logos/<id>/cache/`), gated on `import.meta.env.DEV` rather than `env_mode`;
   - `RecordingCardUtils.js:106` (the recording file), `VODModalUtils.js:78`, `SeriesModalUtils.js:147`;
   - `ProgramDetailModal.jsx:46`, which resolves API image URLs.

    Django's api-uwsgi serves those paths on `:5656` in dev, so they are not #542. `api.js:21-23`'s DEV host is not touched either.
5. **The test-modification rule.** Existing tests change only where the behaviour they pin is what this PR changes. Each change is listed in § Tests changed with its before and after.
6. **Lint: no new error.** `npx eslint` over the eighteen changed frontend files reports exactly the three errors the seed already has in them:
   - `RecordingCard.jsx:211` `no-empty`
   - `StreamConnectionCard.jsx:451` (`:449` after) `no-unused-vars` `table`
   - `RecordingDetailsModal.jsx:135` `no-unused-vars` `posterUrl`

   The unused `useSettingsStore` import and `env_mode` binding each site's removal would leave behind are removed too, so no new `no-unused-vars` appears.
7. **Formatting.** `npx prettier --write` runs only on files that were prettier-clean at the seed, plus the two new files: `ChannelsTable.jsx`, `Guide.jsx`, `devProxy.js`, `devProxy.test.js`. Files that were not clean at the seed are left in their seed style so the diff stays reviewable. Appendix A already reflects this.

## Files this plan touches

| File | Change |
|---|---|
| `frontend/devProxy.js` | **new**: the dev proxy table, `relayGoPort(env)`, `XC_LIVE_ROOT` |
| `frontend/vite.config.js` | `server.proxy` becomes `devProxy(process.env)` |
| `frontend/src/__tests__/devProxy.test.js` | **new**: the proxy-table pin |
| `frontend/src/components/tables/ChannelsTable.jsx` | sites 1 and 2 |
| `frontend/src/components/tables/ChannelTableStreams.jsx` | site 3 |
| `frontend/src/components/tables/StreamsTable.jsx` | site 4 |
| `frontend/src/components/cards/StreamConnectionCard.jsx` | site 5 |
| `frontend/src/utils/cards/RecordingCardUtils.js` | site 6: `getShowVideoUrl(channel)` drops its `env_mode` parameter |
| `frontend/src/pages/Guide.jsx`, `frontend/src/components/ProgramDetailModal.jsx` | callers of site 6. The argument is dropped, and so are the `env_mode` binding and store import it leaves unused. |
| `frontend/src/pages/DVR.jsx`, `frontend/src/components/cards/RecordingCard.jsx`, `frontend/src/components/forms/RecordingDetailsModal.jsx` | callers of site 6: the argument only. Each still reads `env_mode` for `getRecordingUrl`. |
| `frontend/src/utils/cards/__tests__/RecordingCardUtils.test.js`, `frontend/src/components/tables/__tests__/ChannelTableStreams.test.jsx` | changed tests (§ Tests changed) |
| `frontend/src/components/tables/__tests__/ChannelsTable.test.jsx`, `.../StreamsTable.test.jsx`, `frontend/src/components/cards/__tests__/StreamConnectionCard.test.jsx` | added tests only |
| `CLAUDE.md` | `:43`'s `npm run dev` comment, plus one new bullet after `:52` |

**Why `getShowVideoUrl` loses its parameter rather than ignoring it.** A parameter kept and ignored would leave five call sites passing a value that changes nothing, and the next reader would reasonably re-add a dev branch to honour it. No test asserts the arguments `getShowVideoUrl` is called with; all five callers' tests mock it by return value. JavaScript ignores an extra argument, so a missed caller would still work, but Appendix A updates all five.

## Tasks

### Task 1: confirm the base

```bash
cd <worktree> && set -o pipefail && git merge-base --is-ancestor a1e9da653ed3f036ca7aa5d0033518d5fca22a48 HEAD && \
  git diff --stat a1e9da65 HEAD -- frontend CLAUDE.md
```

If the second command lists any file, re-read that file's hunks in Appendix A against it.

### Task 2: apply Appendix A

Save Appendix A's body to a file and run `git apply --check <file> && git apply <file>`. A failure is a stop-and-report, never a hand-merge.

Then commit, staging and committing in separate calls, with the message from a file. The commit gate runs the whole frontend suite for `frontend/` paths, and `CLAUDE.md` maps to no backend label.

### Task 3: verify

Run, and report each result verbatim:

1. `cd frontend && npx vitest --run` over the whole suite. Expected: all pass. At the prototype: 207 files and 6,250 tests passed.
2. `npx eslint` over the eighteen changed frontend files (`git diff --name-only a1e9da65 -- frontend`). Expected: `3 errors`, exactly the seed errors in constraint 6.
3. `npm run build`. Expected: exit 0. It proves `vite.config.js` still loads with the new import.
4. Every break-check in § Break-checks. Apply the named wrong edit, confirm the named test reddens with the quoted message, then revert.
5. The live check in § Live check.

### Task 4: PR

Push the branch and open the PR as a **draft** (`gh pr create --repo D10Scot/Dispatcharr --draft --base main …`), with § PR description as its body. It stays a draft until the internal review passes (`pr-merge-gate` marks it ready).

## Tests

### Tests added

`frontend/src/__tests__/devProxy.test.js` (new, `@vitest-environment node`) pins the table.

**How it matches a URL.** `routeOf()` applies vite's own rule from vite 7.3.5's `doesProxyContextMatchUrl` (the version `package-lock.json` and `package.json`'s `resolutions` pin), in `node_modules/vite/dist/node/chunks/config.js:22085`, and its `for…in` loop at `:22057`:

- keys are tried in insertion order;
- a key starting with `^` is a `RegExp` tested against the URL including its query string;
- any other key is a prefix;
- the first match wins.

The test encodes vite's documented behaviour. It is not an output of the code under test.

**What it asserts:**

- `is the table vite.config.js serves`: `viteConfig.server.proxy` deep-equals `devProxy(process.env)`.
- `sends %s to relay-go`: each of these routes to the expected key, and that key's target is `http://127.0.0.1:5658`:
  - two `/proxy/ts/stream/<uuid>?output_format=…` URLs;
  - `/hls/<token>/video.m3u8` and `/hls/<token>/video/12.m4s`;
  - `/live/user/pass/123.ts`;
  - `/user/pass/123`, `/user/pass/123.ts` and `/user/pass/123.m3u8?token=x`;
  - `/wsmith/pass/123.ts` and `/apiuser/pass/123.ts`: XC usernames that begin with a backend prefix (R111).
- `keeps %s on its own backend, not the XC root`: `/api/channels/5` and `/api/channels/recordings/4/hls/index.m3u8` route to `/api/`, and `/ws/x/5` routes to `/ws/`.
- `leaves %s to vite`: SPA routes, `/src/…`, `/node_modules/.vite/deps/…`, vite's own `/@vite/client` and `/@fs/app/frontend/src/main.jsx`, `/proxy/ts/status` and `/proxy/vod/movie/1` match no key.

**No request needs a bare `/api` or `/ws`.** Re-verified at `a1e9da65`:
- `grep -rnoE "/api[^/a-zA-Z_.']" frontend/src` and `grep -rnoE "/ws[^/a-zA-Z_.]" frontend/src` (non-test) match only `api.js:3458` and `:3487`, which are `/api/accounts/api-keys/…`;
- every `api.js` request is built as `${host}/api/…`;
- `WebSocket.jsx:87-94` dials `…/ws/?token=` (directly on `:8001` in dev);
- Swagger is at `/api/swagger/`.

A developer typing a bare `http://127.0.0.1:9191/api` now gets the SPA rather than Django, which is exactly what nginx does in production.
- `is nginx's XC live root plus an optional query string`: reads `docker/nginx.conf`, extracts the `location ~ ^/[^/]+/[^/]+/…$` regex, and asserts `XC_LIVE_ROOT` is exactly that with `(?:\?.*)?` inserted before `$`.
- `lists the XC regex last`.
- `reads the relay port from %j`: `{}`, `''` and `'abc'` give 5658, and `'6000'` gives 6000, in both `relayGoPort` and the `/hls/` target.

**Same-origin assertions under `env_mode` `'dev'`, one per site.** Each carries the message `a dev-mode live URL must go through vite, never straight to :5656`:

| Site | Test | Asserts |
|---|---|---|
| 1 | `ChannelsTable.test.jsx` › `dev mode (#542)` › `copies a same-origin channel URL` | `copyToClipboard` got `${window.location.origin}/proxy/ts/stream/uuid-1` |
| 2 | `ChannelsTable.test.jsx` › `dev mode (#542)` › `plays a channel same-origin` | `showVideo` got `${window.location.origin}/proxy/ts/stream/uuid-abc?output_format=hls` |
| 3 | `ChannelTableStreams.test.jsx` › `stays same-origin in dev mode (#542)` (changed, below) | `/proxy/ts/stream/hash-abc?output_format=mpegts` |
| 4 | `StreamsTable.test.jsx` › `handleWatchStream (via row actions)` › `stays same-origin in dev mode (#542)` | `/proxy/ts/stream/hash-abc?output_format=mpegts` |
| 5 | `StreamConnectionCard.test.jsx` › `previews same-origin in dev mode (#542)` | `${window.location.origin}/proxy/ts/stream/ch-uuid-1?output_format=mpegts` |
| 6 | `RecordingCardUtils.test.js` › `getShowVideoUrl` › `stays same-origin when the caller is in dev mode (#542)` (changed, below) | `getShowVideoUrl(channel, 'dev')` is `/proxy/ts/stream/channel-123?output_format=hls` |

Site 6's pin deliberately still passes `'dev'`. A future edit that re-adds the parameter and a dev branch reddens it.

### Tests changed (the behaviour each pins is what this PR changes)

| File | Test | Before | After |
|---|---|---|---|
| `RecordingCardUtils.test.js:169-176` | `prepends dev server URL in dev mode with output params` becomes `stays same-origin when the caller is in dev mode (#542)` | `getShowVideoUrl(channel, 'dev')` matches `/^https?:\/\/.*:5656\/proxy\/ts\/stream\/channel-123\?output_format=hls$/` | the same call `toBe('/proxy/ts/stream/channel-123?output_format=hls')` |
| `ChannelTableStreams.test.jsx:449-455` | `prefixes hostname in dev mode` becomes `stays same-origin in dev mode (#542)` | `expect(calledUrl).toContain(':5656')` | `expect(calledUrl).toBe('/proxy/ts/stream/hash-abc?output_format=mpegts')` |
| `RecordingCardUtils.test.js:153`, `:164` | `returns the channel HLS entry URL`, `ignores the web-player Output Profile preference (R18)` | `getShowVideoUrl(channel, 'production')` | `getShowVideoUrl(channel)`. This is a call-shape edit for the new signature: the assertions are unchanged and the pinned value is identical. |

Unchanged and still valid: `FloatingVideoUtils.test.js:497`, `:521-522`. They feed `isChannelHlsUrl` and `hlsSessionUrlOf` an absolute `:5656` URL as input, and both helpers still accept absolute URLs.

### Break-checks

Each was run at the prototype. The implementer re-runs each, confirms the test reddens with a message naming the mechanism, and reverts.

| # | Wrong edit | Test that reddens | Message (as observed) |
|---|---|---|---|
| B1 | In `devProxy.js`, move `[XC_LIVE_ROOT]: relay()` to the top of the returned object | `keeps /api/channels/5 …`, `keeps /ws/x/5 …`, `lists the XC regex last` | `/api/channels/5 left its own backend: the XC regex must come after /api/ and /ws/` |
| B2 | Delete `(?:\\?.*)?` from `XC_LIVE_ROOT` | `sends /user/pass/123.m3u8?token=x to relay-go`, `is nginx's XC live root plus an optional query string` | `/user/pass/123.m3u8?token=x matched the wrong key: expected undefined …`, `devProxy.js has drifted from docker/nginx.conf` |
| B3 | Restore `frontend/vite.config.js` to the seed (`git show "a1e9da65:frontend/vite.config.js"`) | `is the table vite.config.js serves` | `vite.config.js does not take its proxy table from devProxy()` |
| B4 | In `devProxy.js`, target `http://127.0.0.1:5656` instead of `relayGoPort(env)` | every `sends … to relay-go` | `/proxy/ts/stream/… does not point at relay-go` |
| B5 | Restore `ChannelsTable.jsx` to the seed | `plays a channel same-origin`, `copies a same-origin channel URL` | `a dev-mode live URL must go through vite, never straight to :5656: expected 'http://localhost:5656/proxy/ts/stream…'` |
| B6 | Restore `ChannelTableStreams.jsx` to the seed | `stays same-origin in dev mode (#542)` | as B5 |
| B7 | Restore `StreamsTable.jsx` to the seed | `stays same-origin in dev mode (#542)` | as B5 |
| B8 | Restore `StreamConnectionCard.jsx` to the seed | `previews same-origin in dev mode (#542)` | as B5 |
| B9 | Restore `RecordingCardUtils.js` to the seed | `stays same-origin when the caller is in dev mode (#542)` | as B5 |
| B10 | In `devProxy.js`, restore the key `'/ws'` (no trailing slash) | `sends /wsmith/pass/123.ts to relay-go`, `keeps /ws/x/5 …` | `/wsmith/pass/123.ts matched the wrong key: expected '/ws' to be '^/[^/]+/[^/]+/\d+(?:\.[A-Za-z0-9]+)?(…'` |
| B11 | In `devProxy.js`, restore the key `'/api'` (no trailing slash) | `sends /apiuser/pass/123.ts to relay-go`, both `keeps /api/… …` rows | `/apiuser/pass/123.ts matched the wrong key: expected '/api' to be '^/[^/]+/[^/]+/\d+(?:\.[A-Za-z0-9]+)?(…'` |

**Known limit of the nginx drift pin.** `frontend-tests.yml`'s change detector (`:85`) runs the suite only when a `frontend/` path changes. An edit to `docker/nginx.conf` alone therefore does not run it, and a drift is reported on the next frontend PR rather than on the nginx one. This is accepted rather than widening the workflow filter (open question Q3).

## Live check (the implementer runs it; manual, not automated)

E2E runs an AIO image, never dev, so this is the only end-to-end proof. Use private names only:

- containers `dispatcharr-dev-542` and `e2e-upstream-542`;
- network `dispatcharr-dev-542-net`;
- volume `dispatcharr-dev-542-data`;
- image `dispatcharr-dev-542:local`.

Never touch `dispatcharr-testrunner`, `e2e-upstream` or `dispatcharr-e2e`.

**Do not use `docker/docker-compose.dev.yml` as shipped.** Its image is `ghcr.io/dispatcharr/dispatcharr:base`: the upstream namespace, and a base image that carries no `/usr/local/bin/relay-go`. The planner checked `ghcr.io/d10scot/dispatcharr:base` locally and it has none either, because only `docker/Dockerfile`'s final stage copies it in. So `[program:relay-go]` cannot start there and nothing answers on :5658 (open question Q2, filed as #558). Build the fork's own image instead.

**Mount a scratch export at `/app`, never the worktree.** The dev rung's `99-init-dev.sh` runs `npm install` into `/app/frontend`.

**Resolve the base digest with the tool.** A local `:base` tag can be stale: the planner's was, shipping ffmpeg 8.1.2.

```bash
S=<scratch dir>; W=<worktree>
BASE=$(docker buildx imagetools inspect ghcr.io/d10scot/dispatcharr:base --format '{{.Manifest.Digest}}')
cd "$W" && docker build -f docker/Dockerfile --build-arg BASE_IMAGE="ghcr.io/d10scot/dispatcharr@${BASE}" -t dispatcharr-dev-542:local .
git -C "$W" archive HEAD | (mkdir -p "$S/app542" && tar -x -C "$S/app542")
docker network create dispatcharr-dev-542-net
docker run -d --name e2e-upstream-542 --network dispatcharr-dev-542-net -p 127.0.0.1:19402:8080 \
  -e UPSTREAM_INTERNAL_ORIGIN=http://e2e-upstream-542:8080 dispatcharr-e2e-upstream:local
docker run -d --name dispatcharr-dev-542 --network dispatcharr-dev-542-net \
  -p 127.0.0.1:19191:9191 -p 127.0.0.1:15656:5656 \
  -e DISPATCHARR_ENV=dev -e REDIS_HOST=localhost -e CELERY_BROKER_URL=redis://localhost:6379/0 \
  -v "$S/app542:/app" -v dispatcharr-dev-542-data:/data dispatcharr-dev-542:local
```

**Wait**, with a Monitor until-loop rather than sleeps, until both of these answer:

- `curl -sf http://127.0.0.1:19191/`
- `docker exec dispatcharr-dev-542 curl -sf http://127.0.0.1:5658/healthz`

The first boot runs `npm install` and `uv sync`, which takes a few minutes.

**Seed a channel through vite**, all against `B=http://127.0.0.1:19191`:

1. `POST $B/api/accounts/initialize-superuser/` with `{"username","password","email"}`.
2. `POST $B/api/accounts/token/` to get the access JWT.
3. `POST http://127.0.0.1:19402/scenarios` with `{"channels":[{"id":1,"name":"Dev542","tvgId":"dev542","logo":null}]}`, and keep the `internal` URL from the answer.
4. `POST $B/api/channels/streams/` with `{"name":…,"url":"<internal>/stream/1.ts"}`.
5. `POST $B/api/channels/channels/` with `{"name":…,"streams":[<stream id>]}`, and keep its `uuid`.

**Scripted check.** Save the script below and run `check542.sh http://127.0.0.1:19191 <uuid>`. Also run each negative control:

- `curl http://127.0.0.1:15656/proxy/ts/stream/<uuid>?output_format=mpegts` gives **501** (the seed's dev URL).
- PATCH the channel `hidden_from_output: true`: an anonymous TS tune through :19191 gives **403**, and the same with `&token=<JWT>` gives **200**. PATCH it back afterwards.
- `GET /live/<user>/<xc pass>/<channel id>.ts` and `GET /<user>/<xc pass>/<channel id>.ts` through :19191 give **200** `video/mp2t`. First create a user with `custom_properties: {"xc_password": …}` and `user_level: 10`. Use `--max-time 20`: the first byte waits for the channel to start (~5 s).

```bash
#!/usr/bin/env bash
# Plays one channel over TS and over HLS through vite (the #542 live check).
# Usage: check542.sh <vite base, e.g. http://127.0.0.1:9191> <channel uuid>
set -euo pipefail
B=$1; U=$2; T=$(mktemp -d)
echo "== TS"
curl -s --max-time 20 -o "$T/ts" -w 'status %{http_code} type %{content_type}\n' "$B/proxy/ts/stream/$U?output_format=mpegts" || true
python3 - "$T/ts" <<'PY'
import sys
d = open(sys.argv[1], 'rb').read()
n = len(d) // 188 * 188
print('bytes', len(d), 'ts-sync', n > 0 and all(d[i] == 0x47 for i in range(0, n, 188)))
PY
echo "== HLS entry"
curl -s --max-time 70 -o "$T/multi" -w 'status %{http_code} type %{content_type}\n' "$B/proxy/ts/stream/$U?output_format=hls"
cat "$T/multi"
media=$(grep -v '^#' "$T/multi" | grep 'video' | head -1)
[ -n "$media" ] || media=$(grep -v '^#' "$T/multi" | head -1)
session=$(printf '%s' "$media" | cut -d/ -f1-3)
echo "== media playlist $media"
curl -s --max-time 55 -o "$T/media" -w 'status %{http_code}\n' "$B$media"
init=$(grep -o 'URI="[^"]*"' "$T/media" | head -1 | cut -d'"' -f2)
seg=$(grep -v '^#' "$T/media" | grep . | head -1)
dir=$(dirname "$media")
echo "== init $init";    curl -s --max-time 20 -o /dev/null -w 'status %{http_code} %{size_download}B\n' "$B$dir/$init"
echo "== segment $seg";  curl -s --max-time 20 -o /dev/null -w 'status %{http_code} %{size_download}B\n' "$B$dir/$seg"
echo "== leave";         curl -s --max-time 10 -o /dev/null -w 'status %{http_code}\n' -X DELETE "$B$session"
rm -rf "$T"
```

Pipe the output through `sed -E 's#/hls/v1\.[^/]+#/hls/<token>#g'` before it goes in a report: the media-session token is a bearer credential.

**Expected results:**

- **TS:** 200, `video/mp2t`, `ts-sync True`. This is the pass criterion for the TS half.
- **HLS:** the entry answers 200 with a multivariant whose URIs begin `/hls/<token>/`. The media playlist, the init segment and one media segment answer 200 through :19191, and the leave answers 204.

**If the entry answers 502 `HLS output failed`**, as it did for the planner on arm64, the HLS half is judged by **parity**:

- send the same entry straight to `relay-go` (`docker exec dispatcharr-dev-542 curl … http://127.0.0.1:5658/proxy/ts/stream/<uuid>?output_format=hls`);
- send it to an AIO container of the same image (`DISPATCHARR_ENV=aio`, no bind mount, `-p 127.0.0.1:19192:9191`, its own data volume) through its nginx.

If both give the same 502, vite is not the cause, and the report says "HLS through vite reached the relay and was authorized; the relay's HLS output fails on this host independently of dev mode (Q1)". Never describe HLS playback as verified unless the segments answered 200.

**In a browser (optional, recommended):** open `http://127.0.0.1:19191`, sign in, and click the play button on the channel's row. DevTools' Network tab should show `…:19191/proxy/ts/stream/<uuid>?output_format=hls` (not `:5656`), then `…:19191/hls/<token>/…`. A stream preview from the Streams table should show `…:19191/proxy/ts/stream/<hash>?output_format=mpegts` playing. The browser reaches the API at `:5656` (`api.js:21-23`), so publish the API on the host's own `5656`, not `15656`, or sign-in fails; only do that if host port 5656 is free.

**Tidy-up, by name:**

```bash
docker rm -f dispatcharr-dev-542 e2e-upstream-542 dispatcharr-dev-542-aio
docker network rm dispatcharr-dev-542-net
docker volume rm dispatcharr-dev-542-data dispatcharr-dev-542-aio-data
docker rmi dispatcharr-dev-542:local
```

**The STREAMS network ACL in dev judges `127.0.0.1`.** vite's proxy does not set `X-Forwarded-For` (no `xfwd`), and the relay's untrusted path reports the socket peer (`relay/httpapi/stream.go:619-622`, `peerAddress`). That peer is vite on loopback, so `authorize_stream` evaluates a STREAMS ACL against `127.0.0.1` for every dev tune, whatever the browser's address. This is acceptable for dev, and CLAUDE.md's new bullet states it.

## Open questions, with recommendations

- **Q1. The relay's HLS output fails on local arm64 Docker, in dev and in AIO alike.** ffprobe on the relay's feed reports `pipe:0: End of file`. **Recommendation:** a separate issue, not this PR. It is out of R100's scope, sits on the relay's side of the hop, and has an AIO reproduction. Include the ffprobe-wrapper method in the issue. The planner does not know the cause.
- **Q2. `docker/docker-compose.dev.yml` cannot run `relay-go`.** Its image is the upstream `ghcr.io/dispatcharr/dispatcharr:base`, and no base image carries the binary. CLAUDE.md's "Inside Docker, `DISPATCHARR_ENV=dev` selects the `all-dev` rung, which DOES start `relay-go`" is true only for an image built from `docker/Dockerfile`. So after this PR, the shipped dev compose still plays nothing live, whereas a bare `npm run dev` + `runserver 5656` + a hand-started `relay-go`, or the fork's full image in dev mode, now does. **Filed as [#558](https://github.com/D10Scot/Dispatcharr/issues/558)** ("Dev compose runs no relay-go: the :base image carries no relay-go binary", `Refs #542`). Possible fixes are pointing the compose at the fork's image or building `relay-go` in `99-init-dev.sh`. Do not widen this PR. The new CLAUDE.md bullet names #558; the seed's `:52` "DOES start `relay-go`" sentence is left to #558.
- **Q3. The nginx drift pin runs only on frontend PRs** (§ Break-checks). **Recommendation:** accept it. The regex has not changed since stage 2d-3, and widening `frontend-tests.yml`'s filter is a workflow edit outside R100.

## PR description

```markdown
## Summary

Dev mode (`DISPATCHARR_ENV=dev`: vite on :9191, no nginx) played no live stream since Phase 2 stage 2d-3, over TS or HLS. Two things stood in the way:

- vite proxied only `/api` and `/ws`, while the live surface is `relay-go` on `DISPATCHARR_RELAY_GO_PORT` (5658).
- In dev, every live-player URL builder sent the browser straight to Django on `:5656`, which answers `/proxy/ts/stream/` with a 501 stub. So a vite entry alone would never have been reached.

This PR (rulings R97, R100):

- adds `frontend/devProxy.js`, the dev proxy table. `/proxy/ts/stream/`, `/live/`, `/hls/` and nginx's XC three-segment root, listed last and with an optional query string, go to `relay-go`. `vite.config.js` takes its `server.proxy` from it.
- drops the dev-mode `:5656` prefix at the six live call sites, so each uses the same-origin URL its production branch already built. `getShowVideoUrl` loses its `env_mode` parameter, and its five callers follow.
- leaves the VOD, series and recording-file `:5656` rewrites alone: Django serves those in dev.
- adds a CLAUDE.md bullet on the dev live path.

With no nginx there is no `auth_request` hop. The relay authorizes each tune itself through `POST /_dispatcharr/authorize-internal` (`relay/httpapi/authorize.go`). In dev the STREAMS network ACL therefore judges `127.0.0.1`, because every request reaches the relay from vite.

Plan: `docs/superpowers/plans/2026-09-30-fix-542-dev-live-proxy.md` (this PR's first commit).

## Tests

- New `frontend/src/__tests__/devProxy.test.js` pins the proxy table:
  - the keys and the relay port;
  - the XC regex after `/api/` and `/ws/`, which keep nginx's trailing slash so `/wsmith/…` and `/apiuser/…` XC URLs still reach the relay;
  - `/u/p/123.ts` and `/u/p/123?x` routed, `/api/x/5` not;
  - SPA and vite module paths left alone;
  - the regex equal to nginx's plus the query suffix;
  - that `vite.config.js` serves it.
- One same-origin assertion per call site under `env_mode: 'dev'`.
- Two existing dev-mode tests changed, because the behaviour they pinned is the defect (listed with before and after in the plan). Two `getShowVideoUrl` calls lose their now-unused second argument.
- Break-checks B1-B11 in the plan, each re-run.

## Live check

<results of the plan's live check, tokens redacted>

## Not in this PR

- Q1: relay HLS output fails on local arm64 in dev and AIO alike.
- Q2, #558: `docker-compose.dev.yml`'s image has no `relay-go` binary, so this fix needs a running `relay-go` that the `:base`-image dev compose lacks.

Closes #542.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01SEwWnPPgR8hqEtrynUeE6a
```

## Appendix A: the change, against `a1e9da65`

Apply with `git apply`. Generated by `git diff a1e9da65 -- frontend CLAUDE.md` from the prototype. `git apply --check` passes at `a1e9da65`.

```diff
diff --git a/CLAUDE.md b/CLAUDE.md
index d4660b21..101c9684 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -40,7 +40,7 @@ TEST_USE_SQLITE=1 python manage.py test        # no-Postgres fallback; PG-only t
 uv run python manage.py makemigrations <app>
 
 cd frontend && npm install
-npm run dev    # Vite :9191, proxies /api -> :5656, /ws -> :8001
+npm run dev    # Vite :9191, proxies /api -> :5656, /ws -> :8001, the live surface -> :5658
 npm run build && npm test                      # vitest --run
 npm run lint   # ~112 pre-existing errors, disabled in CI. No format script: npx prettier --write
 
@@ -50,6 +50,7 @@ scripts/check_go_stdlib_only.sh relay           # the module must stay stdlib-on
 
 - `manage.py` rewrites `DJANGO_SETTINGS_MODULE` to `dispatcharr.settings_test` for `test` only. **Never pass `--settings=dispatcharr.settings` to `test` on a live instance** — it targets the production database.
 - Since Phase 1 PR 6 the relay asks Django for its source over HTTP, and with `DISPATCHARR_ENV` unset `get_control_plane_base_url()` falls to the AIO branch (`http://127.0.0.1:9191`), which makes every tune answer "Control plane unreachable" against a bare `runserver`. `DISPATCHARR_ENV=dev` points that call at `http://127.0.0.1:5656` unconditionally — the dev branch is hardcoded, not read from a port variable — while a bare `runserver` binds `:8000` by default, so pass the port explicitly (`runserver 5656`, as the Commands block above does) rather than relying on "the dev process's own port"; `DISPATCHARR_INTERNAL_API_BASE_URL=http://127.0.0.1:8000` is the escape hatch when `runserver` must keep its default port instead. An override or a `DISPATCHARR_WEB_HOST` whose host Django's own `get_host()` would refuse (an underscore anywhere in it) is caught at resolve time — using Django's own `split_domain_port`, naming the responsible variable, and never echoing a URL's userinfo — rather than being dialled and failing later as an opaque 400: `next_source()` propagates it as `ImproperlyConfigured` so a misconfigured deployment fails visibly on the first tune, while `release_source()` and `post_events()` catch it, log once per call (the variable name only) and return `False`, since aborting a channel teardown or an event post cannot fix the configuration and would instead leak the channel's Redis keys, its ownership lease and a still-running ffmpeg — reachable in the worker role, which stops channels but never tunes, and in a relay restarted after the tune. The reverse direction (Django asking the relay, `apps/proxy/relay_client.py`) got the same three-way policy once PR 7's fix round named every call site: `Channel._stream_assignment_is_reusable()` (the tune path) lets `ImproperlyConfigured` propagate uncaught, same reasoning as `next_source()`; the five admin views in `apps/proxy/ts_admin_views.py` answer with a fixed body (never the exception text or the rejected value) while logging the variable name only; five callers degrade exactly as they already do for an unreachable relay, logging once (`apps/proxy/stats_views.py`'s `combined_stats` — a 200 with an empty live section, not a 500 — plus `attempt_stream_termination`, `get_user_active_connections`'s live branch, `fetch_channel_stats` and `_stop_dvr_clients`). `relay_client.stop_channels()` also stops looping in a bulk M3U delete rather than repeating a doomed round trip for every remaining identifier, but only on a connection-level failure (`RelayUnavailable(transport=True)`, set at the `requests.ConnectionError` raise site — the narrower branch, checked first; `ConnectTimeout` inherits it, but a `ReadTimeout` from one stuck channel's teardown does not and stays per-channel) or `ImproperlyConfigured` — both mean every remaining identifier would fail the same way. A `RelayRefused`, or a `RelayUnavailable` that is NOT a transport failure (a redirect, a 5xx, a garbled 2xx body — the relay answered at least once and this one request failed), is per-channel and keeps the loop going; the coarser first draft aborted on any `RelayUnavailable` and could strand channels a single slow teardown or transient 5xx would have let stop fine. See spec Amendment S11 rulings 22-23. Since Phase 2 stage 2d-4 the dev process also calls *itself* in the other direction, but the two directions no longer share a port: `Channel.get_stream()`'s reuse check and every other `relay_client` call (`advance`, `stop_channels`, …) resolve through `resolve_base_url(..., dev_url=dev_relay_url())`, so in `dev` they go to `http://127.0.0.1:5658` — the Go relay's own port (`DISPATCHARR_RELAY_GO_PORT`) — never `:5656`, because Django itself serves no `/proxy/relay/…` route in any shape any more (R1 deleted `relay_views.py`/`relay_urls.py` with the package). Under a bare `manage.py runserver 5656` nothing listens on `:5658` unless `relay-go` is started separately, so the call gets a connection refusal: `relay_client.channel_snapshot()` catches it as `RelayUnavailable`, logs one WARNING (`"Relay could not answer for channel %s: %s"`) and returns `present=False, active=False` — not a 500 — so `_stream_assignment_is_reusable()` falls back to a bare Redis `stream_profile`-key check instead of the relay's real answer. Start `relay-go` alongside a bare `runserver`, or point `DISPATCHARR_RELAY_BASE_URL` at wherever one answers, to get the relay's actual state instead of the fallback. Inside Docker, `DISPATCHARR_ENV=dev` selects the `all-dev` rung, which DOES start `relay-go` (`docker/supervisord/all-dev.conf`'s `[include]` lists `relay-go.conf`), so every `relay_client` call there reaches a real out-of-process relay with a real channel registry — `reset_tried` is no longer a silent no-op there, because that was a property of the old in-process Python relay answering on the API process with an empty `stream_managers`, and that process no longer exists in any shape.
+- Since #542 vite also proxies the live surface to `relay-go`: `/proxy/ts/stream/`, `/live/`, `/hls/` and nginx's XC three-segment root, the last listed after `/api/` and `/ws/` because it matches their three-segment paths too, and those two keep nginx's trailing slash so an XC username such as `wsmith` is not caught by them (`frontend/devProxy.js`, port from `DISPATCHARR_RELAY_GO_PORT`, default 5658). It needs a running `relay-go`, which the `:base`-image dev compose lacks ([#558](https://github.com/D10Scot/Dispatcharr/issues/558)). The browser player's live URLs are same-origin in dev as in production; the VOD, series and recording-file URLs still go to `:5656`, where Django serves them. With no nginx there is no `auth_request` hop, so the relay authorizes each tune itself through `POST /_dispatcharr/authorize-internal` (`relay/httpapi/authorize.go`), and because every request reaches it from vite, a STREAMS network ACL judges `127.0.0.1`.
 - Tests need Postgres and Redis. `scripts/ci_bootstrap_backend.sh` is what CI runs; assumes the base image's layout.
 - Docker: `docker/docker-compose.{dev,aio}.yml` + `docker-compose.yml` (modular); `DISPATCHARR_ENV` picks the deployment shape and `DISPATCHARR_ROLE` (`all`/`api`/`relay`/`worker`) picks which supervisord programs the container runs. `docker/tests/test-puid-pgid.sh` and `test-tls-postgres.sh` are good integration tests, run by `lifecycle-tests.yml`'s `suites` job in full mode.
 
diff --git a/frontend/devProxy.js b/frontend/devProxy.js
new file mode 100644
index 00000000..40adebcf
--- /dev/null
+++ b/frontend/devProxy.js
@@ -0,0 +1,55 @@
+// The vite dev server's proxy table (#542).
+//
+// With DISPATCHARR_ENV=dev there is no nginx: vite serves the SPA on :9191 and
+// forwards what nginx would have routed elsewhere. /api/ and /ws/ go to
+// Django and Daphne as before. The live surface -- the TS tune, the XC live
+// roots and the HLS session resources -- goes to relay-go, which is where
+// nginx sends it in production (docker/nginx.conf: ^~ /proxy/ts/stream/,
+// ^~ /hls/, ^~ /live/ and the XC three-segment regex). With no nginx there is
+// no auth_request hop, and the relay asks Django itself
+// (relay/httpapi/authorize.go, the dev fallback), so nothing here authorizes
+// anything.
+//
+// ORDER IS LOAD-BEARING. vite tries the keys in insertion order and takes the
+// first that matches; a key starting with ^ is a RegExp tested against the
+// request URL WITH its query string. The XC regex also matches three-segment
+// /api/ and /ws/ paths ending in a number, which nginx settles by preferring
+// ^~ prefixes over regexes, so here it is listed last. The two prefixes keep
+// nginx's trailing slash (^~ /api/, ^~ /ws/): without it an XC username
+// starting with "api" or "ws" (/wsmith/pass/123.ts) would match them first.
+
+// A missing or non-integer DISPATCHARR_RELAY_GO_PORT means 5658, as
+// docker/init/03-init-dispatcharr.sh does for nginx's upstream. relay-go
+// itself refuses to start on a non-integer value (relay/config/config.go).
+export const relayGoPort = (env) => {
+  const raw = env.DISPATCHARR_RELAY_GO_PORT;
+  return raw && /^\d+$/.test(raw) ? raw : '5658';
+};
+
+// docker/nginx.conf's XC live root, plus an optional query string.
+export const XC_LIVE_ROOT = '^/[^/]+/[^/]+/\\d+(?:\\.[A-Za-z0-9]+)?(?:\\?.*)?$';
+
+export const devProxy = (env) => {
+  const relay = () => ({
+    target: `http://127.0.0.1:${relayGoPort(env)}`,
+    changeOrigin: true,
+    secure: false,
+  });
+  return {
+    '/api/': {
+      target: 'http://127.0.0.1:5656',
+      changeOrigin: true,
+      secure: false,
+    },
+    '/ws/': {
+      target: 'http://127.0.0.1:8001',
+      changeOrigin: true,
+      secure: false,
+      ws: true,
+    },
+    '/proxy/ts/stream/': relay(),
+    '/live/': relay(),
+    '/hls/': relay(),
+    [XC_LIVE_ROOT]: relay(),
+  };
+};
diff --git a/frontend/src/__tests__/devProxy.test.js b/frontend/src/__tests__/devProxy.test.js
new file mode 100644
index 00000000..56eaeef4
--- /dev/null
+++ b/frontend/src/__tests__/devProxy.test.js
@@ -0,0 +1,99 @@
+// @vitest-environment node
+/* global process */
+import { readFileSync } from 'node:fs';
+import { describe, expect, it } from 'vitest';
+import viteConfig from '../../vite.config.js';
+import { devProxy, relayGoPort, XC_LIVE_ROOT } from '../../devProxy.js';
+
+// vite's own rule (vite 7, doesProxyContextMatchUrl): the keys are tried in
+// insertion order, a key starting with ^ is a RegExp tested against the URL
+// with its query string, any other key is a prefix. First match wins.
+const routeOf = (table, url) =>
+  Object.keys(table).find((key) =>
+    key.startsWith('^') ? new RegExp(key).test(url) : url.startsWith(key)
+  );
+
+const RELAY = 'http://127.0.0.1:5658';
+const table = devProxy({});
+
+describe('the dev proxy table (#542)', () => {
+  it('is the table vite.config.js serves', () => {
+    expect(
+      viteConfig.server.proxy,
+      'vite.config.js does not take its proxy table from devProxy()'
+    ).toEqual(devProxy(process.env));
+  });
+
+  it.each([
+    [
+      '/proxy/ts/stream/0b6f2c1e-7c55-4f53-9a55-2b5f3f5b8a10?output_format=mpegts',
+      '/proxy/ts/stream/',
+    ],
+    [
+      '/proxy/ts/stream/0b6f2c1e-7c55-4f53-9a55-2b5f3f5b8a10?output_format=hls',
+      '/proxy/ts/stream/',
+    ],
+    ['/hls/v1.abc.def/video.m3u8', '/hls/'],
+    ['/hls/v1.abc.def/video/12.m4s', '/hls/'],
+    ['/live/user/pass/123.ts', '/live/'],
+    ['/user/pass/123', XC_LIVE_ROOT],
+    ['/user/pass/123.ts', XC_LIVE_ROOT],
+    ['/user/pass/123.m3u8?token=x', XC_LIVE_ROOT],
+    ['/wsmith/pass/123.ts', XC_LIVE_ROOT],
+    ['/apiuser/pass/123.ts', XC_LIVE_ROOT],
+  ])('sends %s to relay-go', (url, key) => {
+    expect(routeOf(table, url), `${url} matched the wrong key`).toBe(key);
+    expect(table[key].target, `${key} does not point at relay-go`).toBe(RELAY);
+  });
+
+  it.each([
+    ['/api/channels/5', '/api/'],
+    ['/api/channels/recordings/4/hls/index.m3u8', '/api/'],
+    ['/ws/x/5', '/ws/'],
+  ])('keeps %s on its own backend, not the XC root', (url, key) => {
+    expect(
+      routeOf(table, url),
+      `${url} left its own backend: the XC regex must come after /api/ and /ws/`
+    ).toBe(key);
+  });
+
+  it.each([
+    '/',
+    '/channels',
+    '/guide',
+    '/plugins/browse',
+    '/src/pages/Guide.jsx',
+    '/node_modules/.vite/deps/react.js?v=1234',
+    '/@vite/client',
+    '/@fs/app/frontend/src/main.jsx',
+    '/proxy/ts/status',
+    '/proxy/vod/movie/1',
+  ])('leaves %s to vite', (url) => {
+    expect(routeOf(table, url), `${url} is proxied`).toBeUndefined();
+  });
+
+  it("is nginx's XC live root plus an optional query string", () => {
+    const nginx = readFileSync(
+      new URL('../../../docker/nginx.conf', import.meta.url),
+      'utf8'
+    );
+    const regex = nginx.match(/location ~ (\^\/\[\^\/\]\+\/\S+\$) \{/)[1];
+    expect(XC_LIVE_ROOT, 'devProxy.js has drifted from docker/nginx.conf').toBe(
+      regex.replace(/\$$/, '(?:\\?.*)?$')
+    );
+  });
+
+  it('lists the XC regex last', () => {
+    expect(Object.keys(table).at(-1)).toBe(XC_LIVE_ROOT);
+  });
+
+  it.each([
+    [{}, '5658'],
+    [{ DISPATCHARR_RELAY_GO_PORT: '' }, '5658'],
+    [{ DISPATCHARR_RELAY_GO_PORT: 'abc' }, '5658'],
+    [{ DISPATCHARR_RELAY_GO_PORT: '6000' }, '6000'],
+  ])('reads the relay port from %j', (env, port) => {
+    expect(relayGoPort(env)).toBe(port);
+    expect(devProxy(env)['/hls/'].target).toBe(`http://127.0.0.1:${port}`);
+  });
+});
diff --git a/frontend/src/components/ProgramDetailModal.jsx b/frontend/src/components/ProgramDetailModal.jsx
index fb715269..4472ceec 100644
--- a/frontend/src/components/ProgramDetailModal.jsx
+++ b/frontend/src/components/ProgramDetailModal.jsx
@@ -14,7 +14,6 @@ import {
 import { Calendar, Video } from 'lucide-react';
 import API from '../api';
 import useVideoStore from '../store/useVideoStore';
-import useSettingsStore from '../store/settings';
 import { getShowVideoUrl } from '../utils/cards/RecordingCardUtils';
 import { formatSeasonEpisode } from '../utils/guideUtils';
 import {
@@ -73,7 +72,6 @@ export default function ProgramDetailModal({
   const [detailData, setDetailData] = useState(null);
 
   const showVideo = useVideoStore((s) => s.showVideo);
-  const env_mode = useSettingsStore((s) => s.environment.env_mode);
   const { timeFormat } = useDateTimeFormat();
 
   useEffect(() => {
@@ -106,11 +104,11 @@ export default function ProgramDetailModal({
 
   const handleWatchLive = useCallback(() => {
     if (!channel) return;
-    showVideo(getShowVideoUrl(channel, env_mode), 'live', {
+    showVideo(getShowVideoUrl(channel), 'live', {
       name: channel.name,
     });
     onClose();
-  }, [channel, env_mode, showVideo, onClose]);
+  }, [channel, showVideo, onClose]);
 
   const handleRecord = useCallback(() => {
     if (onRecord) onRecord(program);
diff --git a/frontend/src/components/cards/RecordingCard.jsx b/frontend/src/components/cards/RecordingCard.jsx
index 97481deb..76b616e7 100644
--- a/frontend/src/components/cards/RecordingCard.jsx
+++ b/frontend/src/components/cards/RecordingCard.jsx
@@ -121,7 +121,7 @@ const RecordingCard = ({
 
   const handleWatchLive = () => {
     if (!channel) return;
-    showVideo(getShowVideoUrl(channel, env_mode), 'live', {
+    showVideo(getShowVideoUrl(channel), 'live', {
       name: channel.name,
     });
   };
diff --git a/frontend/src/components/cards/StreamConnectionCard.jsx b/frontend/src/components/cards/StreamConnectionCard.jsx
index 364c5335..3c373d9c 100644
--- a/frontend/src/components/cards/StreamConnectionCard.jsx
+++ b/frontend/src/components/cards/StreamConnectionCard.jsx
@@ -83,8 +83,6 @@ const StreamConnectionCard = ({
   const users = useUsersStore((s) => s.users);
   // Get settings for speed threshold and environment mode
   const settings = useSettingsStore((s) => s.settings);
-  const env_mode =
-    useSettingsStore((s) => s.environment?.env_mode) || 'production';
   // Get video preview function
   const showVideo = useVideoStore((s) => s.showVideo);
 
@@ -515,10 +513,7 @@ const StreamConnectionCard = ({
     if (!actualChannel?.uuid) return;
 
     const uri = buildLiveStreamUrl(`/proxy/ts/stream/${actualChannel.uuid}`);
-    let url = `${window.location.protocol}//${window.location.host}${uri}`;
-    if (env_mode === 'dev') {
-      url = `${window.location.protocol}//${window.location.hostname}:5656${uri}`;
-    }
+    const url = `${window.location.protocol}//${window.location.host}${uri}`;
 
     showVideo(url, 'live', { name: actualChannel.name });
   };
diff --git a/frontend/src/components/cards/__tests__/StreamConnectionCard.test.jsx b/frontend/src/components/cards/__tests__/StreamConnectionCard.test.jsx
index 41f5f187..a6e76080 100644
--- a/frontend/src/components/cards/__tests__/StreamConnectionCard.test.jsx
+++ b/frontend/src/components/cards/__tests__/StreamConnectionCard.test.jsx
@@ -821,6 +821,36 @@ describe('StreamConnectionCard', () => {
       });
     });
 
+    it('previews same-origin in dev mode (#542)', async () => {
+      const showVideo = vi.fn();
+      vi.mocked(useVideoStore).mockImplementation((selector) =>
+        selector({ showVideo })
+      );
+      vi.mocked(useSettingsStore).mockImplementation((selector) =>
+        selector({ ...mockSettingsState, environment: { env_mode: 'dev' } })
+      );
+      vi.mocked(getChannelStreams).mockResolvedValue([
+        { id: 10, name: 'Stream A', url: 'http://a.com', m3u_profile: null },
+      ]);
+      const { getStreamOptions } =
+        await import('../../../utils/cards/StreamConnectionCardUtils.js');
+      vi.mocked(getStreamOptions).mockReturnValue([
+        { value: '10', label: 'Stream A' },
+      ]);
+
+      render(<StreamConnectionCard {...defaultProps()} />);
+      await waitFor(() => screen.getByTestId('icon-circle-play'));
+      fireEvent.click(screen.getByTestId('icon-circle-play').closest('button'));
+
+      await waitFor(() => expect(showVideo).toHaveBeenCalled());
+      expect(
+        showVideo.mock.calls[0][0],
+        'a dev-mode live URL must go through vite, never straight to :5656'
+      ).toBe(
+        `${window.location.origin}/proxy/ts/stream/ch-uuid-1?output_format=mpegts`
+      );
+    });
+
     it('calls showVideo with correct url and type when preview is clicked', async () => {
       const showVideo = vi.fn();
       vi.mocked(useVideoStore).mockImplementation((selector) =>
diff --git a/frontend/src/components/forms/RecordingDetailsModal.jsx b/frontend/src/components/forms/RecordingDetailsModal.jsx
index ae2aabe1..0781a263 100644
--- a/frontend/src/components/forms/RecordingDetailsModal.jsx
+++ b/frontend/src/components/forms/RecordingDetailsModal.jsx
@@ -284,7 +284,7 @@ const RecordingDetailsModal = ({
       if (!ch) return;
       useVideoStore
         .getState()
-        .showVideo(getShowVideoUrl(ch, env_mode), 'live', { name: ch.name });
+        .showVideo(getShowVideoUrl(ch), 'live', { name: ch.name });
     }
   };
 
diff --git a/frontend/src/components/tables/ChannelTableStreams.jsx b/frontend/src/components/tables/ChannelTableStreams.jsx
index 62505eb9..e79213a5 100644
--- a/frontend/src/components/tables/ChannelTableStreams.jsx
+++ b/frontend/src/components/tables/ChannelTableStreams.jsx
@@ -20,7 +20,6 @@ import './table.css';
 import useChannelsTableStore from '../../store/channelsTable';
 import usePlaylistsStore from '../../store/playlists';
 import useVideoStore from '../../store/useVideoStore';
-import useSettingsStore from '../../store/settings';
 import CatchupIndicator from '../CatchupIndicator';
 import {
   closestCenter,
@@ -397,20 +396,16 @@ const ChannelStreams = ({ channel }) => {
   const authUser = useAuthStore((s) => s.user);
   const showVideo = useVideoStore((s) => s.showVideo);
   const isVideoVisible = useVideoStore((s) => s.isVisible);
-  const env_mode = useSettingsStore((s) => s.environment.env_mode);
 
   const handleWatchStream = useCallback(
     (streamHash, streamName, streamId) => {
-      let vidUrl = buildLiveStreamUrl(`/proxy/ts/stream/${streamHash}`);
-      if (env_mode === 'dev') {
-        vidUrl = `${window.location.protocol}//${window.location.hostname}:5656${vidUrl}`;
-      }
+      const vidUrl = buildLiveStreamUrl(`/proxy/ts/stream/${streamHash}`);
       const meta = {};
       if (streamName) meta.name = streamName;
       if (streamId != null) meta.streamId = streamId;
       showVideo(vidUrl, 'live', Object.keys(meta).length ? meta : null);
     },
-    [env_mode, showVideo]
+    [showVideo]
   );
 
   const [data, setData] = useState(channelStreams || []);
diff --git a/frontend/src/components/tables/ChannelsTable.jsx b/frontend/src/components/tables/ChannelsTable.jsx
index 70daeea3..2384dd8c 100644
--- a/frontend/src/components/tables/ChannelsTable.jsx
+++ b/frontend/src/components/tables/ChannelsTable.jsx
@@ -22,7 +22,6 @@ import ChannelBatchForm from '../forms/ChannelBatch';
 import RecordingForm from '../forms/Recording';
 import { copyToClipboard, useDebounce } from '../../utils';
 import useVideoStore from '../../store/useVideoStore';
-import useSettingsStore from '../../store/settings';
 import {
   ArrowDownWideNarrow,
   ArrowUpDown,
@@ -326,7 +325,6 @@ const ChannelsTable = ({ onReady }) => {
   });
 
   // store/settings
-  const env_mode = useSettingsStore((s) => s.environment.env_mode);
   const outputProfiles = useOutputProfilesStore((s) => s.profiles);
   const showVideo = useVideoStore((s) => s.showVideo);
 
@@ -644,34 +642,25 @@ const ChannelsTable = ({ onReady }) => {
     setRecordingModalOpen(true);
   }, []);
 
-  const getChannelURL = useCallback(
-    (channel) => {
-      if (!channel || !channel.uuid) {
-        console.error('Invalid channel object or missing UUID:', channel);
-        return '';
-      }
+  const getChannelURL = useCallback((channel) => {
+    if (!channel || !channel.uuid) {
+      console.error('Invalid channel object or missing UUID:', channel);
+      return '';
+    }
 
-      const path = `/proxy/ts/stream/${channel.uuid}`;
-      if (env_mode == 'dev') {
-        return `${window.location.protocol}//${window.location.hostname}:5656${path}`;
-      }
-      return `${window.location.protocol}//${window.location.host}${path}`;
-    },
-    [env_mode]
-  );
+    const path = `/proxy/ts/stream/${channel.uuid}`;
+    return `${window.location.protocol}//${window.location.host}${path}`;
+  }, []);
 
   const handleWatchStream = useCallback(
     (channel) => {
       if (!channel || !channel.uuid) return;
       const path = `/proxy/ts/stream/${channel.uuid}`;
       const uri = buildChannelHlsUrl(path);
-      let url = `${window.location.protocol}//${window.location.host}${uri}`;
-      if (env_mode == 'dev') {
-        url = `${window.location.protocol}//${window.location.hostname}:5656${uri}`;
-      }
+      const url = `${window.location.protocol}//${window.location.host}${uri}`;
       showVideo(url, 'live', { name: channel.name, channelId: channel.id });
     },
-    [env_mode, showVideo]
+    [showVideo]
   );
 
   const onRowSelectionChange = (newSelection) => {
diff --git a/frontend/src/components/tables/StreamsTable.jsx b/frontend/src/components/tables/StreamsTable.jsx
index 7dcf6549..84d09d38 100644
--- a/frontend/src/components/tables/StreamsTable.jsx
+++ b/frontend/src/components/tables/StreamsTable.jsx
@@ -51,7 +51,6 @@ import {
   useMantineTheme,
 } from '@mantine/core';
 import { useNavigate } from 'react-router-dom';
-import useSettingsStore from '../../store/settings';
 import useVideoStore from '../../store/useVideoStore';
 import useChannelsTableStore from '../../store/channelsTable';
 import useWarningsStore from '../../store/warnings';
@@ -349,7 +348,6 @@ const StreamsTable = ({ onReady }) => {
   );
   const channelProfiles = useChannelsStore((s) => s.profiles);
   const selectedProfileId = useChannelsStore((s) => s.selectedProfileId);
-  const env_mode = useSettingsStore((s) => s.environment.env_mode);
   const showVideo = useVideoStore((s) => s.showVideo);
   const videoIsVisible = useVideoStore((s) => s.isVisible);
 
@@ -951,10 +949,7 @@ const StreamsTable = ({ onReady }) => {
   };
 
   function handleWatchStream(streamHash, streamName) {
-    let vidUrl = buildLiveStreamUrl(`/proxy/ts/stream/${streamHash}`);
-    if (env_mode == 'dev') {
-      vidUrl = `${window.location.protocol}//${window.location.hostname}:5656${vidUrl}`;
-    }
+    const vidUrl = buildLiveStreamUrl(`/proxy/ts/stream/${streamHash}`);
     showVideo(vidUrl, 'live', streamName ? { name: streamName } : null);
   }
 
diff --git a/frontend/src/components/tables/__tests__/ChannelTableStreams.test.jsx b/frontend/src/components/tables/__tests__/ChannelTableStreams.test.jsx
index 1b72ed35..cf48e957 100644
--- a/frontend/src/components/tables/__tests__/ChannelTableStreams.test.jsx
+++ b/frontend/src/components/tables/__tests__/ChannelTableStreams.test.jsx
@@ -446,12 +446,15 @@ describe('ChannelStreams', () => {
       expect(buildLiveStreamUrl).toHaveBeenCalledWith('/proxy/ts/stream/s-1');
     });
 
-    it('prefixes hostname in dev mode', () => {
+    it('stays same-origin in dev mode (#542)', () => {
       const { mockShowVideo } = setupMocks({ envMode: 'dev' });
       render(<ChannelStreams channel={makeChannel()} />);
       fireEvent.click(screen.getByTestId('icon-eye').closest('button'));
       const calledUrl = mockShowVideo.mock.calls[0][0];
-      expect(calledUrl).toContain(':5656');
+      expect(
+        calledUrl,
+        'a dev-mode live URL must go through vite, never straight to :5656'
+      ).toBe('/proxy/ts/stream/hash-abc?output_format=mpegts');
     });
 
     it('does not prefix hostname in production mode', () => {
diff --git a/frontend/src/components/tables/__tests__/ChannelsTable.test.jsx b/frontend/src/components/tables/__tests__/ChannelsTable.test.jsx
index 350020f8..0d4c0dd0 100644
--- a/frontend/src/components/tables/__tests__/ChannelsTable.test.jsx
+++ b/frontend/src/components/tables/__tests__/ChannelsTable.test.jsx
@@ -1054,6 +1054,57 @@ describe('ChannelsTable', () => {
     });
   });
 
+  describe('dev mode (#542)', () => {
+    const devMode = () =>
+      vi.mocked(useSettingsStore).mockImplementation((sel) =>
+        sel({ environment: { env_mode: 'dev' } })
+      );
+
+    it('plays a channel same-origin', () => {
+      const channel = makeChannel({ uuid: 'uuid-abc', name: 'ESPN' });
+      const showVideoMock = vi.fn();
+      const { tableInstance } = setupMocks();
+      devMode();
+      vi.mocked(useVideoStore).mockImplementation((sel) =>
+        sel({ showVideo: showVideoMock })
+      );
+      vi.mocked(buildChannelHlsUrl).mockReturnValue(
+        '/proxy/ts/stream/uuid-abc?output_format=hls'
+      );
+      render(<ChannelsTable />);
+      const col = getActionsCol();
+      const { getByTestId } = render(
+        col.cell({ row: { original: channel }, table: tableInstance })
+      );
+      fireEvent.click(getByTestId('icon-circle-play').closest('button'));
+      expect(
+        showVideoMock.mock.calls[0][0],
+        'a dev-mode live URL must go through vite, never straight to :5656'
+      ).toBe(
+        `${window.location.origin}/proxy/ts/stream/uuid-abc?output_format=hls`
+      );
+    });
+
+    it('copies a same-origin channel URL', () => {
+      const channel = makeChannel({ uuid: 'uuid-1' });
+      const { tableInstance } = setupMocks();
+      devMode();
+      render(<ChannelsTable />);
+      const col = getActionsCol();
+      const { getAllByTestId } = render(
+        col.cell({ row: { original: channel }, table: tableInstance })
+      );
+      const copyBtn = getAllByTestId('unstyled-button').find((el) =>
+        el.textContent.includes('Copy URL')
+      );
+      fireEvent.click(copyBtn);
+      expect(
+        copyToClipboard.mock.calls[0][0],
+        'a dev-mode live URL must go through vite, never straight to :5656'
+      ).toBe(`${window.location.origin}/proxy/ts/stream/uuid-1`);
+    });
+  });
+
   // ── Recording form ─────────────────────────────────────────────────────────
 
   describe('Recording form', () => {
diff --git a/frontend/src/components/tables/__tests__/StreamsTable.test.jsx b/frontend/src/components/tables/__tests__/StreamsTable.test.jsx
index 817621b4..c4a9c98a 100644
--- a/frontend/src/components/tables/__tests__/StreamsTable.test.jsx
+++ b/frontend/src/components/tables/__tests__/StreamsTable.test.jsx
@@ -811,6 +811,30 @@ describe('StreamsTable', () => {
   // ── handleWatchStream ──────────────────────────────────────────────────────
 
   describe('handleWatchStream (via row actions)', () => {
+    it('stays same-origin in dev mode (#542)', async () => {
+      const mockShowVideo = vi.fn();
+      setupMocks({
+        totalCount: 5,
+        streams: [makeStream()],
+        showVideo: mockShowVideo,
+        envMode: 'dev',
+      });
+      render(<StreamsTable />);
+      await waitFor(() => expect(capturedTableOptions).not.toBeNull());
+      const actionsCell = capturedTableOptions.bodyCellRenderFns?.actions;
+      const row = {
+        original: makeStream({ stream_hash: 'hash-abc', name: 'My Stream' }),
+      };
+      const { getByText } = render(
+        actionsCell({ cell: { column: { id: 'actions' } }, row })
+      );
+      fireEvent.click(getByText('Preview Stream'));
+      expect(
+        mockShowVideo.mock.calls[0][0],
+        'a dev-mode live URL must go through vite, never straight to :5656'
+      ).toBe('/proxy/ts/stream/hash-abc?output_format=mpegts');
+    });
+
     it('calls buildLiveStreamUrl and showVideo via the actions cell renderer', async () => {
       const mockShowVideo = vi.fn();
       setupMocks({ totalCount: 5, streams: [makeStream()], showVideo: mockShowVideo });
diff --git a/frontend/src/pages/DVR.jsx b/frontend/src/pages/DVR.jsx
index 8829d0a0..a5964ac8 100644
--- a/frontend/src/pages/DVR.jsx
+++ b/frontend/src/pages/DVR.jsx
@@ -210,10 +210,7 @@ const DVRPage = () => {
       // call into child RecordingCard behavior by constructing a URL like there
       const channel = channelsById[rec.channel];
       if (!channel) return;
-      const url = getShowVideoUrl(
-        channel,
-        useSettingsStore.getState().environment.env_mode
-      );
+      const url = getShowVideoUrl(channel);
       useVideoStore.getState().showVideo(url, 'live', { name: channel.name });
     }
   };
diff --git a/frontend/src/pages/Guide.jsx b/frontend/src/pages/Guide.jsx
index 863157f4..e305c751 100644
--- a/frontend/src/pages/Guide.jsx
+++ b/frontend/src/pages/Guide.jsx
@@ -10,7 +10,6 @@ import React, {
 import useChannelsStore from '../store/channels';
 import useLogosStore from '../store/logos';
 import useVideoStore from '../store/useVideoStore';
-import useSettingsStore from '../store/settings';
 import {
   ActionIcon,
   Badge,
@@ -124,8 +123,6 @@ export default function TVChannelGuide({ startDate, endDate }) {
   const [selectedGroupId, setSelectedGroupId] = useState('all');
   const [selectedProfileId, setSelectedProfileId] = useState('all');
 
-  const env_mode = useSettingsStore((s) => s.environment.env_mode);
-
   const guideRef = useRef(null);
   const timelineRef = useRef(null); // New ref for timeline scrolling
   const listRef = useRef(null);
@@ -775,11 +772,11 @@ export default function TVChannelGuide({ startDate, endDate }) {
     (channel, event) => {
       event.stopPropagation();
 
-      showVideo(getShowVideoUrl(channel, env_mode), 'live', {
+      showVideo(getShowVideoUrl(channel), 'live', {
         name: channel.name,
       });
     },
-    [env_mode, showVideo]
+    [showVideo]
   );
 
   const handleProgramClick = useCallback(
diff --git a/frontend/src/utils/cards/RecordingCardUtils.js b/frontend/src/utils/cards/RecordingCardUtils.js
index 1ab5d754..a29fc6d6 100644
--- a/frontend/src/utils/cards/RecordingCardUtils.js
+++ b/frontend/src/utils/cards/RecordingCardUtils.js
@@ -59,13 +59,8 @@ export const getPosterUrl = (posterLogoId, customProperties, posterUrl) => {
   return purl || defaultLogo;
 };
 
-export const getShowVideoUrl = (channel, env_mode) => {
-  let url = `/proxy/ts/stream/${channel.uuid}`;
-  if (env_mode === 'dev') {
-    url = `${window.location.protocol}//${window.location.hostname}:5656${url}`;
-  }
-  return buildChannelHlsUrl(url);
-};
+export const getShowVideoUrl = (channel) =>
+  buildChannelHlsUrl(`/proxy/ts/stream/${channel.uuid}`);
 
 export const runComSkip = async (recording) => {
   await API.runComskip(recording.id);
diff --git a/frontend/src/utils/cards/__tests__/RecordingCardUtils.test.js b/frontend/src/utils/cards/__tests__/RecordingCardUtils.test.js
index 4ca6520b..81e2b1e1 100644
--- a/frontend/src/utils/cards/__tests__/RecordingCardUtils.test.js
+++ b/frontend/src/utils/cards/__tests__/RecordingCardUtils.test.js
@@ -150,7 +150,7 @@ describe('RecordingCardUtils', () => {
   describe('getShowVideoUrl', () => {
     it('returns the channel HLS entry URL', () => {
       const channel = { uuid: 'channel-123' };
-      const result = getShowVideoUrl(channel, 'production');
+      const result = getShowVideoUrl(channel);
 
       expect(result).toBe('/proxy/ts/stream/channel-123?output_format=hls');
     });
@@ -161,18 +161,19 @@ describe('RecordingCardUtils', () => {
         JSON.stringify({ webPlayerOutputProfileId: 5 })
       );
       const channel = { uuid: 'channel-123' };
-      const result = getShowVideoUrl(channel, 'production');
+      const result = getShowVideoUrl(channel);
 
       expect(result).toBe('/proxy/ts/stream/channel-123?output_format=hls');
     });
 
-    it('prepends dev server URL in dev mode with output params', () => {
+    it('stays same-origin when the caller is in dev mode (#542)', () => {
       const channel = { uuid: 'channel-123' };
       const result = getShowVideoUrl(channel, 'dev');
 
-      expect(result).toMatch(
-        /^https?:\/\/.*:5656\/proxy\/ts\/stream\/channel-123\?output_format=hls$/
-      );
+      expect(
+        result,
+        'a dev-mode live URL must go through vite, never straight to :5656'
+      ).toBe('/proxy/ts/stream/channel-123?output_format=hls');
     });
   });
 
diff --git a/frontend/vite.config.js b/frontend/vite.config.js
index 3e8996fa..8907edeb 100644
--- a/frontend/vite.config.js
+++ b/frontend/vite.config.js
@@ -1,5 +1,8 @@
 import { defineConfig } from 'vite';
 import react from '@vitejs/plugin-react-swc';
+import { devProxy } from './devProxy.js';
+
+/* global process */
 
 // https://vite.dev/config/
 export default defineConfig({
@@ -11,20 +14,9 @@ export default defineConfig({
   server: {
     port: 9191,
     // Without this, /api/* is served as the React SPA in debug mode and
-    // Swagger UI at /api/swagger/ never loads the OpenAPI schema.
-    proxy: {
-      "/api": {
-        target: "http://127.0.0.1:5656",
-        changeOrigin: true,
-        secure: false,
-      },
-      "/ws": {
-        target: "http://127.0.0.1:8001",
-        changeOrigin: true,
-        secure: false,
-        ws: true,
-      },
-    },
+    // Swagger UI at /api/swagger/ never loads the OpenAPI schema; and since
+    // #542 the live surface is proxied to relay-go (devProxy.js).
+    proxy: devProxy(process.env),
   },
 
   test: {
```
