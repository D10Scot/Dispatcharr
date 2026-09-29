# Plan: Phase 4a-2, the browser player plays channels over HLS

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. The frontend code is specified by its contracts below (module exports, signatures, event order, test names and their oracles), not by a diff: the implementer writes it. Every documentation edit is Appendix A, a byte-exact `git diff` against the seed that the implementer applies and does not rewrite; its only non-literal parts are the `⟨…⟩` slots in the Q9 observation row, each of which names exactly what fills it.

**Goal.** The floating browser player plays live **channels** over HLS through hls.js, or natively where only native HLS exists, and ends each media session with `DELETE /hls/<token>` when it closes, switches or the page goes away. A channel played from the channels table, the TV Guide, the DVR page or a recording card or modal requests `/proxy/ts/stream/<uuid>?output_format=hls`. Stream previews by stream hash, and the Stats card's play button, stay on mpegts.js over MPEG-TS with the web-player Output Profile preference, unchanged. Spec D18; § Browser player (4a-2; R18); § 4a-2; rulings R17, R18, R24 (the browser's half of the explicit leave) and R26.

**Seed.** `4ed75d963dee2b43246fd2ef5ab43ab471f58812` (`4ed75d96`): the head of PR #538 (`migration/phase4-4a1b-live-hls`, 4a-1b), reviewed PASS there. **#538 is not merged when this plan is written.** Every `file:line` below is at `4ed75d96` unless it says otherwise, read with `git show "4ed75d96:<path>"`. #538 changes no file under `frontend/` (`git diff --stat d51d3195 4ed75d96 -- frontend` is empty), so every frontend anchor is also true on main `d51d3195`. **The implementer re-greps every anchor at the merge commit this branch is cut from** (Task 1), which is after #538, 4a-1c and 4a-1d have merged (R47), and stops if anything this plan names has moved in shape rather than line.

**Branch.** `migration/phase4-4a2-browser-hls` (spec D1), off `origin/main` once 4a-1d has merged, so the full E2E and lifecycle matrix runs on it.

**Authority.** In order of precedence:

1. The owner's and orchestrator's rulings R1-R73 (the orchestrator's `rulings.md`). The ones this PR carries: R68-R71 and R73, which answer this plan's own round-0 questions (§ Rulings); R17 and R18 (channels over HLS through hls.js; previews and the web-player Output Profile preference stay on TS), R26 (the Stats card's play button stays on TS), R24 (the browser's explicit leave on close and switch; the E2E never waits out the idle timeout), R15 (no new externally visible identifier is Dispatcharr-named: this PR adds none), R45 (no hardware gate), R47 (implementations land serially).
2. The Phase 4 spec, `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md` at `4ed75d96`, as amended by this plan's own PR (§ Spec amendments in this PR): D2 (`:211`), D3 (`:212`), D5 (`:214`), D18 (`:229`), § Entry (`:307-320`), § Session resources (`:322-337`), § The media-session token (`:339-360`), § Browser player (`:989-1037`), § Testing and gates' E2E bullet for 4a-2 (`:1206-1208`), § 4a-2 (`:1537-1559`), Q9 (`:1616`).
3. **The code as committed at `4ed75d96`**, which is what the browser actually talks to: `relay/httpapi/hls.go` (the entry and the `/hls/` handlers), `relay/httpapi/server.go:79-81` (the three `/hls/` routes), `relay/control/mediasession.go` (the token's shape), `docker/nginx.conf:304-365` (`^~ /proxy/ts/stream/`) and `:484-491` (`^~ /hls/`), `apps/proxy/authorize.py:82-97` (the principal rule and the hop's authenticators) and `:251-297` (`resolve_output_format`). The 4a-1b plan (`docs/superpowers/plans/2026-09-28-phase4-4a1b-live-hls.md` on main) names what 4a-2 relies on in its overlap row (`:38`): the `?output_format=hls` entry, `?token=` JWT authorization reaching the hop unchanged, and an idempotent 204 from `DELETE /hls/<token>`.
4. CLAUDE.md (§ Frontend: all HTTP through `api.js`, new global state in Zustand stores, Mantine only, no new UI library; the frontend and e2e hooks; the commit gate), `docs/adr/0002-e2e-test-taxonomy.md` (every E2E test is `@contract` or `@characterization`), `docs/adr/0003-e2e-frontend-and-shared-state-contract.md`, `e2e/README.md` and `e2e/COVERAGE.md` (updated in the same PR as the tests), ADR 0008.

**Issues.** This PR closes no issue. Nothing it carries is tracked by an open issue, so neither its commits nor its description carry a closing keyword or a `Refs`.

## Global constraints

1. **No server change.** No file outside `frontend/`, `e2e/`, `CLAUDE.md` and `e2e/COVERAGE.md` changes. No Go, no Python, no nginx, no migration. So the Go coverage ratchet (R21) and Python Gate 2 do not run for this PR, and no parity-matrix row is added: the relay behaviour the browser relies on is already pinned by 4a-1b's rows.
2. **All HTTP the application makes goes through `api.js`** (CLAUDE.md § Frontend). The one new request the application code makes, the leave, is `API.leaveHlsSession`. The requests hls.js and mpegts.js make are the libraries' own, as today's recordings path (`FloatingVideo.jsx:349-411`) and live path (`:476-524`) already are.
3. **No new global state.** The player's per-session state (the entry URL, the session URL, the pending leave, the re-entry count) is component-local, in `FloatingVideo.jsx` refs and closures. `useVideoStore` (`frontend/src/store/useVideoStore.jsx`) is unchanged. No React Context.
4. **No new dependency, and no version change.** hls.js stays at the lockfile's 1.6.15 (`frontend/package-lock.json`, `node_modules/hls.js`; `frontend/package.json` declares `^1.5.20`), mpegts.js at its locked version. Mantine only (CLAUDE.md § Frontend).
5. **mpegts.js and the TS path are unchanged in behaviour.** `initializeLivePlayer` (`FloatingVideo.jsx:445-555`) is not edited; the existing `Live Stream Player`, `Close functionality` and `Player cleanup` tests in `FloatingVideo.test.jsx` (`:172-251`, `:414-447`, `:493-548`) pass with no assertion changed. `buildLiveStreamUrl` (`FloatingVideoUtils.js:8-14`) is not edited.
6. **The test-modification rule.** An existing test changes only where the behaviour it pins is the thing this PR changes, and every such change, and every test-support edit that changes no assertion (a module mock gaining an export), is listed in § Tests changed with its before and after.
7. **The token is never logged.** The media-session token is a bearer credential (spec § The media-session token). No `console.*` call in this PR prints a session URL or token; the leave's failure log names only the HTTP status.
8. **The E2E adds no project, no workflow change and no global settings write.** One spec file joins the `frontend` project; it writes only browser `localStorage` (the player preferences, page-local) and reads through the API.
9. **No hardware gate** (R45), and no AVPlayer gate: the browser is the subject, and the `frontend` project's Chromium is where it is measured.

## Overlap with sibling plans

The implementations land serially, **4a-1c, then 4a-1d, then 4a-2, then 4a-3** (R47). This branch rebases onto 4a-1d.

| Plan | Its files | Boundary with 4a-2 |
|---|---|---|
| **4a-1b** live HLS (#538, merged before this starts) | `relay/httpapi/hls.go`, `relay/session`, `relay/control/mediasession.go`, `docker/nginx.conf` (`^~ /hls/`), `apps/proxy/authorize.py` (the `hls`/`m3u8` aliases), `e2e/fixtures/hls.ts`, `e2e/tests/streaming/hls-*.spec.ts` | Read, never edited. 4a-2 consumes exactly the three things the 4a-1b plan's overlap row names (`:38`): the `?output_format=hls` entry answering a multivariant, `QueryParamJWTAuthentication` reaching the hop on the native path, and `DELETE /hls/<token>` answering 204 idempotently. The E2E imports `MEDIA_SESSION_TOKEN_RE` from `e2e/fixtures/hls.ts` and `readChannelStatus` from `e2e/fixtures/channel-status.ts`, unchanged. |
| **4a-1c** slot reclaim | `relay/channel/reclaim.go`, `relay/session/silence.go`, `apps/channels/models.py`, `apps/proxy/next_source.py`, three `streaming` specs | No shared file. 4a-1c's case (a) (a leave that has stopped a channel before its release POST lands) is what makes the browser's own zap fast on a single-slot provider; this PR's "a switch waits for the previous leave" (Decision 5) is the browser half of it. |
| **4a-1d** automatic profile | `forms/Channel.jsx`, `utils/forms/ChannelUtils.js`, `forms/User.jsx`, `forms/settings/StreamSettingsForm.jsx`, `forms/settings/UiSettingsForm.jsx` (the web-player select's data), `tables/ChannelsTable.jsx` (`:1288-1290` and `:1421-1423`, the two link-builder selects), `tables/OutputProfilesTable.jsx`, a new `utils/outputProfiles.js`, and new tests in `ChannelsTable.test.jsx` and a new `UiSettingsForm.test.jsx` | **Two shared files.** `ChannelsTable.jsx`: 4a-1d edits `:1288-1290` and `:1421-1423`, 4a-2 edits `:47` (the import) and `:662-674` (`handleWatchStream`), hundreds of lines apart. `ChannelsTable.test.jsx`: 4a-1d adds an `it` for the link builders; 4a-2 edits the module mock at `:57-59`, the import at `:443` and the preview test at `:1000-1021`. The rebase resolves both textually. 4a-1d's HLS Output Profile rows never reach the browser player: an `hls` tune ignores `X-Relay-Output` (D12) and `buildChannelHlsUrl` sends no `output_profile`. **One consequence to name:** a channel an admin sets to "HLS (Automatic)" may copy HEVC or AC-3-only audio (4a-1d's per-rendition decisions); Chromium and Firefox cannot decode HEVC or AC-3 through MSE (§ Codec limits), so the player shows its "format can't be played" message for that channel. |
| **4a-3** rewind window, linger, lingering reclaim | `relay/channel/manager.go`, `relay/session`, `relay/hls` (the disk store), the four `rewind_*` settings and their settings form, the Stats page's `lingering_since` line | No shared file. The window makes the media playlist long (up to 1,800 entries); hls.js's `backBufferLength: 120` (spec § Browser player) keeps only two minutes of it in browser memory, and `liveSyncDurationCount: 3` starts the browser at the live edge. Seeking back into the window in the browser player is not in 4a-2 or 4a-3. The explicit leave this PR sends sets 4a-3's behind-live grace to 0 (R25), which is what the browser wants. |

## How the browser reaches HLS through nginx, verified at `4ed75d96`

The brief's question: with no server change, how does the browser obtain the HLS entry URL, and what does the relay answer? Each step below was read in the code at the seed.

1. **The entry URL is built by the frontend**, as today: `/proxy/ts/stream/<channel uuid>?output_format=hls` (spec D2; `buildChannelHlsUrl`). No API call is needed to obtain it.
2. **nginx `^~ /proxy/ts/stream/`** (`docker/nginx.conf:304-365`) runs `auth_request /_dispatcharr/authorize` and `proxy_pass http://relay_go` with `proxy_read_timeout 300s`. The hop's authenticators (`apps/proxy/authorize.py:93-97`) are `JWTAuthentication` (the `Authorization: Bearer` header hls.js's `xhrSetup` sends), `ApiKeyAuthentication` and `QueryParamJWTAuthentication` (`?token=`, the native path; `apps/accounts/authentication.py:91-104`). The hop resolves the format from the request's own `output_format` (`resolve_output_format`, `authorize.py:268-297`, with `"hls"` in `_FORMAT_ALIASES` at `:258`) and hands it to the relay as `X-Relay-Output-Format`. An anonymous request with a valid UUID is still allowed on this surface (`_PRINCIPAL_REQUIRED` excludes it, `:82-84`), so the player works signed out exactly as the TS path does.
3. **The relay answers the entry itself, with no redirect.** `serveHLSEntry` (`relay/httpapi/hls.go:200-354`) attaches the client, starts or joins the channel's HLS pipeline, waits up to `defaultReadyWait` (43 s, `:51`, R57) for the first-generation init segments, mints a session, and answers **200** `application/vnd.apple.mpegurl`, `Cache-Control: no-store`, with the multivariant rendered under `"/hls/" + token` (`:318`). Its failures are 502 (no video, output failed), 503 with `Retry-After: 1` (not ready in time, channel ending), and the hop's own 401/403/404/429 before the relay is reached.
4. **Same origin, with no URL rewriting.** The multivariant's URIs are **absolute paths** (`/hls/<token>/video.m3u8`, spec D3), so hls.js resolves them against the entry URL's origin: the page's own origin in production, where every entry URL is relative (`getShowVideoUrl`) or built from `window.location.host` (`ChannelsTable.jsx:667`). Media playlists name init and media segments **relatively** (`video/init-0.mp4`, `video/12.m4s`), so every segment URL carries the token as its second path segment.
5. **nginx `^~ /hls/`** (`docker/nginx.conf:484-491`) is `proxy_pass http://relay_go` with no `auth_request`, `proxy_read_timeout 60s`, and the blanking include; it passes every method, so `DELETE /hls/<token>` needs nothing more (spec § Session resources: "nginx needs no change for it"). The relay's routes are `GET /hls/{token}/{file}`, `GET /hls/{token}/{rendition}/{file}` and `DELETE /hls/{token}` (`relay/httpapi/server.go:79-81`). The `Authorization` header hls.js sends on these requests is ignored (`hls.go:387-393`), as the spec says.
6. **The token the leave needs is visible to hls.js before any media playlist is fetched**: `Hls.Events.MANIFEST_LOADED`'s `data.levels[i].url` and `data.audioTracks[i].url` are the multivariant's URIs resolved to absolute URLs (prototyped, Appendix B.2). The token matches `^v1\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}$` (`relay/control/mediasession.go`: a 22-character sid and a 43-character MAC, both unpadded base64url), which `e2e/fixtures/hls.ts:17` already encodes as `MEDIA_SESSION_TOKEN_RE`.
7. **What the relay does with the leave:** `HLSLeaveHandler` (`hls.go:607-619`) answers 204 only after the session's `client_disconnect`, pipeline release and client release have run, so a zap that tunes B the moment A's `DELETE` returns finds A already gone from the registry the stream-limit hop and 4a-1c's reclaim count. A valid MAC with an unknown or ended sid is also 204; only a malformed token is 403.

**Development mode is not a working path, before or after this PR.** With `import.meta.env.DEV` or `env_mode === 'dev'`, every live URL the frontend builds points at `:5656` (`RecordingCardUtils.js:64-66`, `ChannelsTable.jsx:669-671`), which is the API uWSGI's HTTP port with no nginx. There, `/proxy/ts/stream/<id>` resolves to Django's 501 stub (`apps/proxy/stream_routes.py:58-66`) and `/hls/` to nothing. Live TS preview has been broken in dev since Phase 2 stage 2d-3; this PR keeps the dev branch's URL shape exactly (so the dev-mode vitest assertions change only in `output_format`) and does not fix it (§ Rulings, R70).

## Codec limits, measured

Appendix B.1 has the commands. What the E2E rests on:

- **CI's Chromium** (Playwright 1.62.1, headless shell, Chromium 151.0.7922.34, **linux/amd64**, the `e2e-tests.yml` runner shape): `MediaSource.isTypeSupported` is **true** for `video/mp4; codecs="avc1.64002a,mp4a.40.2"`, `avc1.64001f` and `audio/mp4; codecs="mp4a.40.2"`, and **false** for `ac-3` and `ec-3`. D8's transcode output (H.264 High, stereo AAC-LC) therefore plays; the `ac3` and `eac3` variants are dropped by hls.js at `MANIFEST_PARSED` (prototyped: only the `mp4a.40.2` level survived, Appendix B.2), so the browser always plays the `aac` group. (Measured under qemu emulation on an arm64 host, which needed `--no-sandbox --single-process`; codec support is a property of the build, not of those flags.)
- **Playwright's linux/arm64 Chromium** (same version) reports **false** for H.264 and AAC too. The playback E2E cannot run on an arm64 Linux host (a local arm64 container stack); macOS arm64 Chromium reports true, and CI is amd64. This is "measure a gate where it is enforced": the spec runs in CI.
- **Chromium 151 answers `canPlayType('application/vnd.apple.mpegurl')` with `"maybe"`** on macOS and on linux/amd64 (R17: Chrome 142+ has native HLS). So the player must test `Hls.isSupported()` **before** `canPlayType`, as the recordings path already does (`FloatingVideo.jsx:349`, `:412`), or Chromium would take the native path and never send a leave. A vitest pins the order (Test F7).
- **HEVC** is false in the headless shell (true in headed macOS Chromium). D8's transcode never emits HEVC; 4a-1d's automatic mode may copy it (the overlap row above).
- **Firefox** decodes H.264 and AAC through MSE and not AC-3, which is why the HLS error text no longer says "try Chrome or Edge" (spec § Browser player). Not measured here: no Firefox project exists in this suite.
- **iPhone Safari** has no `MediaSource`, only `ManagedMediaSource`, which hls.js 1.6 uses (`preferManagedMediaSource` defaults to true). WebKit requires a media element fed by `ManagedMediaSource` to have `disableRemotePlayback` set or to offer an AirPlay alternative source. Not measured (no device, no iOS Safari runner); no `disableRemotePlayback` is set (R69, § Residual risks).

## Decisions the spec leaves open

Each is this plan's ruling, open to challenge. Those that changed spec text were put to the orchestrator and are ruled (§ Rulings).

1. **hls.js's entry timeout is raised to 65 s and its playlist timeout to 50 s.** hls.js 1.6.15's defaults (`src/config.ts:479-510` of the 1.6.15 package) are a 20 s manifest `maxLoadTimeMs` and a 10 s playlist `maxTimeToFirstByteMs`. If hls.js aborts the entry, the relay abandons the session (`hls.go:286-289`), the pipeline's refcount reaches zero and it stops, and any hls.js retry starts a cold encode again, so a slow start never finishes. So each timeout is derived from the relay's worst legitimate answer for that request:
   - **The entry** (`/proxy/ts/stream/…`, the manifest). Before `serveHLSEntry`'s ready wait starts, `Channels.Attach` runs `startTune`, whose `next-source` call is bounded by `tuneBudget = 2 × (ConnectTimeout 2 s + ReadTimeout 5 s) + RetryDelay 100 ms` = **14.1 s** (`relay/httpapi/stream.go:193`, `relay/control/nextsource.go:31-33`). The ready wait is then up to **43 s** (`hls.go:51`, R57; 4a-1b measured a cold 1080i software entry at 15-20 s). So the relay's worst legitimate entry answer is about 57.1 s plus the hop. `HLS_ENTRY_TIMEOUT_MS` = 14 100 + 43 000 + a 7 900 ms margin = **65 000 ms**, under nginx's `proxy_read_timeout 300s` on `^~ /proxy/ts/stream/` (`docker/nginx.conf:350`).
   - **A media playlist** (`/hls/<token>/<rendition>.m3u8`). The relay waits up to `playlistWait` = 43 s for the first segment (`hls.go:52`, `:528`), with no tune in front of it. `HLS_PLAYLIST_TIMEOUT_MS` = **50 000 ms**, above 43 s and under nginx's 60 s `proxy_read_timeout` on `^~ /hls/` (`nginx.conf:488`).
   - The config is `manifestLoadPolicy.default = { maxTimeToFirstByteMs: Infinity, maxLoadTimeMs: HLS_ENTRY_TIMEOUT_MS, timeoutRetry: null, errorRetry: { maxNumRetry: 1, retryDelayMs: 1000, maxRetryDelayMs: 1000 } }` and `playlistLoadPolicy.default = { maxTimeToFirstByteMs: HLS_PLAYLIST_TIMEOUT_MS, maxLoadTimeMs: HLS_PLAYLIST_TIMEOUT_MS, timeoutRetry: { maxNumRetry: 2, retryDelayMs: 0, maxRetryDelayMs: 0 }, errorRetry: { maxNumRetry: 2, retryDelayMs: 1000, maxRetryDelayMs: 8000 } }`. With these, the relay's own 503 always arrives before either timeout.
   - `timeoutRetry: null` on the manifest, because a manifest timeout means the relay has already given up on that entry. `errorRetry` keeps one retry of a 503, which is a new cold entry. The fragment policy stays at hls.js's default.
   - The constants live in `FloatingVideoUtils.js`, with comments naming `stream.go:193`, `hls.go:51-52` and `nginx.conf:350`/`:488` as the values they are derived from and bounded by.
2. **`lowLatencyMode: false` and `enableWorker: true`**, as the recordings path sets (`FloatingVideo.jsx:369-370`). hls.js 1.6 defaults `lowLatencyMode` to **true**; the relay serves no LL-HLS (spec non-goals), and saying so costs nothing. `liveSyncDurationCount: 3` is hls.js's own default, so the test that asserts it pins nothing on its own (the memory "a pin that supplies the default pins nothing"); it is set for the spec's explicitness, and the break-checks use the non-default values (`backBufferLength: 120`, whose default is `Infinity`, and the load policies).
3. **The token comes from `MANIFEST_LOADED`, not from a playlist request.** The first level's `url`, else the first audio track's, is passed to `hlsSessionUrlOf`. `MANIFEST_LOADED` fires before hls.js filters levels by codec, so even a multivariant whose every variant the browser refuses (`MANIFEST_INCOMPATIBLE_CODECS_ERROR`) still yields its session, and the player leaves it rather than holding a slot for the idle timeout.
4. **hls.js is destroyed first, then the leave is sent.** Otherwise a playlist reload in flight between the leave and the destroy is answered 403 (the session is gone), and hls.js would report it as an error on a player that is closing. The HLS player's `destroy()` (a) sets a `destroyed` flag its event handlers check first, (b) removes its `pagehide` listener, (c) calls `hls.destroy()`, and then (d) calls `API.leaveHlsSession(sessionUrl)` once, if the **current** session's URL was seen and not already left. The session URL and its "left" flag are per session, not per player: each hls.js instance's `MANIFEST_LOADED` **replaces** both (a new URL, left = false), so after a re-entry (Decision 7) or a back-forward-cache restore (Decision 6) the leave names the newest session, never the one already ended. `safeDestroyPlayer` (`FloatingVideo.jsx:185-225`) is unchanged: it clears `src` and calls `pause()` then `destroy()` on whatever player object is current, which is harmless before `hls.destroy()` (hls.js's `emptied` handler only logs, through a logger that is a no-op when `debug` is false, `src/controller/buffer-controller.ts:1573-1580` and `src/utils/logger.ts:33-41`).
5. **A switch waits for the previous leave, for at most 2 s.** When `streamUrl` changes, React runs the old effect's cleanup (`safeDestroyPlayer`, which sends the leave) before the new effect. The new HLS entry awaits `Promise.race([pendingLeave, 2 s])` before it constructs hls.js. The leave's 204 is written only after the old session's releases have run (§ How the browser reaches HLS, 7), so on a single-slot provider the new tune finds the slot's holder already gone (4a-1c's case (a)) rather than finding an ACTIVE session that is not yet silent and answering 503. The bound keeps a hung leave from blocking playback. Only the HLS entry waits: the TS path (`initializeLivePlayer`) stays synchronous, because making it wait would change its existing tests' timing (Global constraint 5); a switch from an HLS channel to a TS preview is the one zap that does not wait, and 4a-1c's reclaim covers it. The pending leave is a ref (`pendingLeaveRef`) in `FloatingVideo`, not global state.
6. **`pagehide` sends the leave with `keepalive: true`** and marks the session left, so a later `destroy()` does not send it again. If the page was put in the back-forward cache and is shown again, hls.js's next request is refused 403 and the player re-enters once (Decision 7), which is exactly the recovery a restored page needs.
7. **403 and 410 from `/hls/`** (ruling R68). Any hls.js `ERROR` event (fatal or not) whose `data.response?.code` is 403 or 410 and whose URL's path starts with `/hls/` ends that session in the player (the session is gone either way, so no leave is sent for it: its left flag is set). **The URL is `data.url ?? data.response?.url ?? data.frag?.url`**: hls.js 1.6.15 puts a playlist error's URL at the top level (`src/loader/playlist-loader.ts:686-699`) but a fragment error's only in `response.url` and `frag` (`src/loader/fragment-loader.ts:221-239`), and an ended session answers segment GETs 403 too (`hls.go:404-407`, `:430-432`). Prototyped (Appendix B.3): the first 403 on the video playlist is non-fatal and the second is fatal, so acting on the first saves one round trip. **The first such event disarms the instance synchronously**, before anything is awaited: it sets the instance's `destroyed` flag (so every later event from it, such as the `audioTrackLoadError` 403 that follows the video one in B.3, is ignored) and calls its `hls.destroy()`. **The once-guard counts re-entries, not 403 events**: one per player object. Then:
   - **403** (session unknown: a relay restart, an admin's client stop, stream-limit termination, a restored page): the player re-enters **once** (spec; R68), by building a new hls.js instance on the same entry URL after refreshing the JWT (`await API.getAuthToken()`, which refreshes an expired access token, `api.js:88-90`), because a long session's JWT may have expired and the entry is the one request that needs it. A 403 from `/hls/` on an instance built by the re-entry shows "The playback session ended." and does not re-enter. Re-entering also brings back, once, a browser viewer an admin stopped or the stream limit terminated (§ Rulings, R68).
   - **410** (the channel stopped, `hls.go:417-420`): the player does **not** re-enter (R68). Re-entering would restart a channel an admin had just stopped. After 4a-1c a 410 may also mean the session went silent and its channel was reclaimed for another tune (`resumeHLS` answers 410 when its channel is absent, `hls.go:455-464`; ruling R66), which is equally a reason not to re-enter: re-entering would take the slot back from the tune that reclaimed it. The player therefore shows "The channel stopped, or this idle session was ended."
8. **The other hls.js errors.** A fatal error on the **manifest** (the entry: `manifestLoadError`, `manifestLoadTimeOut`, `manifestParsingError`, `manifestIncompatibleCodecsError`) shows its message and does not recover: the entry has already had its one `errorRetry`, and a 4xx from the hop is a decision, not a fault. A fatal `NETWORK_ERROR` on a playlist or segment (other than 403/410 above) calls `hls.startLoad()`, as the recordings path does (`FloatingVideo.jsx:386-391`), at most three times per session, then shows its message. A fatal `MEDIA_ERROR` calls `hls.recoverMediaError()` once, then shows its message. Messages come from `getHlsLivePlayerErrorMessage` (the contract below); none mentions a browser brand.
9. **The native path** (hls.js unsupported, `canPlayType` non-empty) sets `video.src` to the absolute entry URL with `token=<access token>` appended as a query parameter (the recordings path's `withRecordingAuthToken` shape, `FloatingVideo.jsx:22-31`, generalised into `withAccessTokenParam(url, token)` in `FloatingVideoUtils.js`). No leave is sent: the token is not observable there (spec § Browser player), and the idle timeout and 4a-1c's silence rule cover it. **The JWT in the URL is logged by nginx's access log**, as the recordings path's already is (spec § Risks names the same class for the media-session token). With neither hls.js nor native HLS, the player shows "This browser can't play live channels." and requests nothing.
10. **The player chooses by URL**: `contentType === 'vod'` keeps the VOD path; otherwise `isChannelHlsUrl(streamUrl)` picks the new HLS live path, and everything else keeps `initializeLivePlayer`. `isChannelHlsUrl` is true only for a `/proxy/ts/stream/` path whose `output_format` query parameter is `hls`, so the recordings path's own `.m3u8` URLs (`/api/channels/recordings/<pk>/hls/…`) never reach it, and `contentType` for those stays `'vod'` as today.
11. **Two `data-testid`s are added for the E2E**, and nothing else in the rendered tree changes: `floating-video` on the player's outer `div` (`FloatingVideo.jsx:943-956`) and `floating-video-close` on its `CloseButton` (`:988-1000`). The suite selects by test id, not by text (`e2e/tests/frontend/helpers.ts`'s header; `e2e/tests/guards/testid.spec.ts`).

## Contracts

### `frontend/src/utils/components/FloatingVideoUtils.js` (additions; nothing existing is edited)

```js
// The relay's entry and first-playlist waits (relay/httpapi/hls.go:51-52,
// defaultReadyWait = defaultPlaylistWait = QuickProbe 3 s + FullProbe 8 s +
// 3 × StallTimeout 10 s + 2 s, ruling R57).
export const HLS_RELAY_WAIT_MS = 43_000;
// The next-source budget the relay spends before the entry's ready wait starts
// (relay/httpapi/stream.go:193, tuneBudget = 2 × (2 s + 5 s) + 100 ms).
export const HLS_RELAY_TUNE_BUDGET_MS = 14_100;
// The entry (manifest) timeout: the tune budget plus the ready wait plus a margin,
// under nginx's 300 s proxy_read_timeout on ^~ /proxy/ts/stream/ (docker/nginx.conf:350).
export const HLS_ENTRY_TIMEOUT_MS = HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_WAIT_MS + 7_900; // 65 000
// The media-playlist timeout: above the relay's 43 s first-segment wait, under nginx's
// 60 s proxy_read_timeout on ^~ /hls/ (docker/nginx.conf:488).
export const HLS_PLAYLIST_TIMEOUT_MS = 50_000;
// How long a switch waits for the previous session's leave (Decision 5).
export const HLS_LEAVE_WAIT_MS = 2_000;
// v1.<22-char sid>.<43-char MAC>, relay/control/mediasession.go.
export const MEDIA_SESSION_TOKEN_RE = /^v1\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}$/;

export const buildChannelHlsUrl = (path) => string;
  // `${path}?output_format=hls`. Never reads the player preferences (R18).
export const isChannelHlsUrl = (url) => boolean;
  // Parses url against window.location.origin; true iff the pathname starts with
  // '/proxy/ts/stream/' and searchParams.get('output_format') === 'hls'. False for
  // null, '', or an unparsable string.
export const hlsSessionUrlOf = (playlistUrl) => string | null;
  // u = new URL(playlistUrl, window.location.origin); the pathname's first segment must
  // be 'hls' and its second must match MEDIA_SESSION_TOKEN_RE. Returns
  // `${u.origin}/hls/${token}` (the PLAYLIST's origin, never window.location.origin),
  // else null.
export const withAccessTokenParam = (url, token) => string;
  // Sets `token` in url's query (URLSearchParams), keeping every other parameter;
  // returns url unchanged when token is falsy.
export const buildLiveHlsConfig = (getAccessToken) => object;
  // The hls.js config for a live channel: { enableWorker: true, lowLatencyMode: false,
  // liveSyncDurationCount: 3, backBufferLength: 120, manifestLoadPolicy, playlistLoadPolicy
  // (Decision 1, built from HLS_ENTRY_TIMEOUT_MS and HLS_PLAYLIST_TIMEOUT_MS), xhrSetup }. xhrSetup(xhr) calls
  // getAccessToken() on EVERY request and sets `Authorization: Bearer <token>` when it
  // returns a token, nothing otherwise.
export const getHlsLivePlayerErrorMessage = ({ status, details, sessionEnded, channelStopped }) => string;
  // channelStopped → 'The channel stopped, or this idle session was ended.'; sessionEnded → 'The playback session ended.';
  // status 401 or 403 → 'You are not allowed to watch this channel.';
  // 404 → 'Channel not found.'; 429 → 'Stream limit reached. Close another stream and try again.';
  // 502 → 'The channel's source is unavailable.'; 503 → 'The channel is not ready yet. Try again in a moment.';
  // details 'manifestIncompatibleCodecsError' or 'bufferIncompatibleCodecsError' → 'This channel's video or audio format can't be played in this browser.';
  // otherwise `Playback error: ${details || 'unknown'}`. Never names a browser.
```

### `frontend/src/api.js` (one addition to `class API`)

```js
/**
 * End a live HLS media session: DELETE /hls/<token> (Phase 4 spec D5, § Session
 * resources). `sessionUrl` is `<origin>/hls/<token>` from hlsSessionUrlOf, never built
 * from `host`, because the session lives on the origin the entry was answered from.
 * Sends no Authorization header (the relay authorises /hls/ by the token alone, and a
 * pagehide call cannot wait for a token refresh). Never throws and never shows a
 * notification: resolves true on 2xx, false otherwise, logging only the status.
 */
static async leaveHlsSession(sessionUrl, { keepalive = false } = {}) → Promise<boolean>
```

It calls the file's own `request(sessionUrl, { method: 'DELETE', auth: false, keepalive })` (`api.js:38-82`), which returns `''` for a 204 body, and catches every throw, logging `console.warn('Leaving the HLS session failed', error.status ?? 'network error')`.

### `frontend/src/utils/cards/RecordingCardUtils.js`

`getShowVideoUrl(channel, env_mode)` (`:62-68`) returns `buildChannelHlsUrl(url)` instead of `buildLiveStreamUrl(url)`; the dev prefix is unchanged. The import at `:5` changes to `buildChannelHlsUrl`.

### `frontend/src/components/tables/ChannelsTable.jsx`

`handleWatchStream` (`:662-674`) builds `buildChannelHlsUrl(path)` instead of `buildLiveStreamUrl(path)`; everything else in it is unchanged. The import at `:47` changes to `buildChannelHlsUrl` (the file has no other use of `buildLiveStreamUrl`: `grep -n buildLiveStreamUrl` at the seed finds `:47` and `:666` only). `getChannelURL` (`:646-660`, the "Copy URL" item) is unchanged: it copies a bare TS URL.

### Unchanged call sites (listed, so the reviewer can check none was missed)

`StreamsTable.jsx:954` and `ChannelTableStreams.jsx:404` (previews by stream hash, R18) and `StreamConnectionCard.jsx:516` (the Stats card, R26) keep `buildLiveStreamUrl`. `Guide.jsx:778`, `DVR.jsx:213`, `RecordingCard.jsx:124`, `RecordingDetailsModal.jsx:287` and `ProgramDetailModal.jsx:109` call `getShowVideoUrl` and change behaviour through it, with no edit. `grep -rn "buildLiveStreamUrl\|getShowVideoUrl\|/proxy/ts/stream" frontend/src --include='*.js' --include='*.jsx'` outside `__tests__` at the seed lists exactly these sites plus the two builders.

### `frontend/src/components/FloatingVideo.jsx`

- Imports `API` from `'../api'` and the new utils.
- New ref `pendingLeaveRef` (a promise or null).
- New function `initializeHlsLivePlayer()`, chosen by the effect at `:566-571` per Decision 10. Its shape:
  1. If `!videoRef.current || !streamUrl`, return. Set loading, clear the error, `setShowControls(false)`. Restore volume and muted from `getPlayerPrefs()`, as `initializeLivePlayer` does (`:500-504`).
  2. Build the absolute entry URL (`new URL(streamUrl, window.location.origin).href`).
  3. **Set `playerRef.current` synchronously** to the HLS player object `{ pause, destroy }` before any `await`, so a close or switch during the leave wait cancels this init (its `destroy()` sets `destroyed`).
  4. If `Hls.isSupported()`: await `Promise.race([pendingLeaveRef.current ?? Promise.resolve(), timeout(HLS_LEAVE_WAIT_MS)])` (clear the timer), then `await API.getAuthToken()` (refreshes an access token that expired while the page sat idle; the init is async already, so this costs nothing, and the TS path's lack of it is not copied); if `destroyed`, return. Build `new Hls(buildLiveHlsConfig(() => useAuthStore.getState().accessToken))`, register `MANIFEST_LOADED` (Decision 3), `MANIFEST_PARSED` (call `video.play()`, and on rejection show "Auto-play was prevented. Click play to start."), `ERROR` (Decisions 7-8), then `attachMedia(video)` and, on `MEDIA_ATTACHED`, `loadSource(entryUrl)`. Loading clears on the video element's `playing` event. Register `window` `pagehide` (Decision 6).
  5. Else if `video.canPlayType('application/vnd.apple.mpegurl')`: `video.src = withAccessTokenParam(entryUrl, useAuthStore.getState().accessToken)`, `video.load()`, and `play()` on `canplay`.
  6. Else show "This browser can't play live channels." and stop loading.
- The HLS player object's `destroy()` follows Decision 4 and stores the leave's promise in `pendingLeaveRef.current`. Its `pause()` pauses the video element.
- Re-entry (Decision 7) builds a fresh hls.js instance on the same entry URL inside the same player object, so `playerRef.current` never changes identity during a re-entry.
- The two test ids (Decision 11).
- `initializeLivePlayer`, `initializeVODPlayer`, `safeDestroyPlayer`, `handleClose` and the render tree are otherwise unchanged.

## Tasks

### Task 1: re-grep the anchors and cut the branch

- `git fetch origin && git worktree add .worktrees/impl-4a2 -b migration/phase4-4a2-browser-hls origin/main` after 4a-1d's merge (worktree-per-change).
- Re-read every anchor in § Contracts, § How the browser reaches HLS and § Tests changed at the new base. The frontend anchors move only if 4a-1c or 4a-1d touched those files (4a-1d touches `ChannelsTable.jsx` and `ChannelsTable.test.jsx`; re-anchor those two by content). Confirm `relay/httpapi/hls.go`'s `defaultReadyWait` is still 43 s (`HLS_RELAY_WAIT_MS` mirrors it) and `docker/nginx.conf`'s `^~ /hls/` still has `proxy_read_timeout 60s`. If either moved, stop and report: Decision 1's numbers depend on both.
- Run `cd frontend && npm ci && npm test` on the untouched branch and record the counts (the seed's seven affected files: 300 tests, all passing, Appendix B.4).

### Task 2: `FloatingVideoUtils.js` and its tests

Implement the additions in § Contracts. Add the `FloatingVideoUtils.test.js` tests U1-U7 below. The `output_profile=5` assertion moves here from `RecordingCardUtils.test.js` (Tests changed, 2).

### Task 3: `api.js`'s `leaveHlsSession` and its test

Implement § Contracts. Add `frontend/src/__tests__/api.leaveHlsSession.test.js` (tests A1-A4). This is `api.js`'s first test file; it stubs `fetch` with `vi.stubGlobal` and does not mock `api.js` itself.

### Task 4: the two channel call sites and their tests

`RecordingCardUtils.js` and `ChannelsTable.jsx` per § Contracts; `RecordingCardUtils.test.js` and `ChannelsTable.test.jsx` per § Tests changed, 1-3 and 7.

### Task 5: `FloatingVideo.jsx`'s HLS live path and its tests

Implement § Contracts and Decisions 3-11. Add the `FloatingVideo.test.jsx` tests F1-F12 in a new `describe('Live channel over HLS')`, with the mock and fixture additions in § Tests changed, 8.

### Task 6: the two tightened preview tests and the mock export

`StreamConnectionCard.test.jsx`, `StreamsTable.test.jsx` and `ChannelTableStreams.test.jsx` per § Tests changed, 4-6. Run each break-check in § Break-checks against these.

### Task 7: the E2E spec, the COVERAGE rows and CLAUDE.md

Add `e2e/tests/frontend/player-hls.spec.ts` (E1, E2). Apply Appendix A's two hunks. Then the E2E halves of break-checks 1 and 2 (R73): **two** throwaway commits, one wrong edit each, each pushed, its CI `frontend` result observed, and each undone by its own revert commit before the implementation review is dispatched; no force-push, no amend. The review is pinned to the SHA after the second revert. Fill the Q9 row's `⟨…⟩` slots from the PR's CI run of E2 (the `Q9:` log line and the run id). No local stack (the memory "E2E fix briefs forbid local stacks"): the `frontend` project on the PR's CI run is the verification, and `tsc --noEmit` (the e2e hook) is the local check.

### Task 8: gates and the PR

§ Gates, then the PR from § PR description draft, opened as a draft.

## Tests added

### vitest: `frontend/src/utils/components/__tests__/FloatingVideoUtils.test.js`

- **U1** `describe('buildLiveStreamUrl')`, `it('forces mpegts output')`: `buildLiveStreamUrl('/proxy/ts/stream/h')` is `'/proxy/ts/stream/h?output_format=mpegts'` with empty prefs; and `it('appends the web-player Output Profile preference')`: with `localStorage['dispatcharr-player-prefs'] = '{"webPlayerOutputProfileId":5}'`, `buildLiveStreamUrl('/proxy/ts/stream/channel-123')` is `'/proxy/ts/stream/channel-123?output_format=mpegts&output_profile=5'` (moved from `RecordingCardUtils.test.js:158-169`, same literal).
- **U2** `describe('buildChannelHlsUrl')`, `it('requests the hls output format')`: `'/proxy/ts/stream/u'` → `'/proxy/ts/stream/u?output_format=hls'`; `it('ignores the web-player Output Profile preference (R18)')`: with the preference set to 5, the same string, and `not.toContain('output_profile')`.
- **U3** `describe('isChannelHlsUrl')`: true for `'/proxy/ts/stream/u?output_format=hls'` and `'http://h:5656/proxy/ts/stream/u?output_format=hls'`; false for `'/proxy/ts/stream/u?output_format=mpegts'`, `'/api/channels/recordings/7/hls/index.m3u8'`, `'http://example.com/stream.ts'`, `null` and `''`.
- **U4** `describe('hlsSessionUrlOf')`, with `T = 'v1.' + 'A'.repeat(22) + '.' + 'B'.repeat(43)`: `'http://localhost:3000/hls/' + T + '/video.m3u8'` → `'http://localhost:3000/hls/' + T`; `'http://h:5656/hls/' + T + '/video.m3u8'` → `'http://h:5656/hls/' + T` (the playlist's own origin, not jsdom's `http://localhost:3000`); `'/hls/' + T + '/aac/12.m4s'` → `window.location.origin + '/hls/' + T`; a token with a 42-character MAC → `null`; `'/api/channels/recordings/7/hls/index.m3u8'` → `null`; `'/proxy/ts/stream/u'` → `null`.
- **U5** `describe('buildLiveHlsConfig')`: `backBufferLength` is 120; `lowLatencyMode` is false; `liveSyncDurationCount` is 3; `manifestLoadPolicy.default.maxLoadTimeMs` is greater than `HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_WAIT_MS` (57 100) and less than 300 000 (nginx's entry location, `nginx.conf:350`); `manifestLoadPolicy.default.timeoutRetry` is null; `playlistLoadPolicy.default.maxTimeToFirstByteMs` and `.maxLoadTimeMs` are each greater than `HLS_RELAY_WAIT_MS` and less than 60 000 (nginx's `/hls/` location, `:488`); and `HLS_RELAY_WAIT_MS` is 43000 and `HLS_RELAY_TUNE_BUDGET_MS` is 14100 (the literals, so a change to either relay bound has to be carried here on purpose).
- **U6** `it('xhrSetup reads the access token on every request')`: a getter returning `'a'` then `'b'`; two calls of `xhrSetup` on two fake XHRs set `Authorization` to `'Bearer a'` then `'Bearer b'`; a getter returning `null` sets no header.
- **U7** `describe('getHlsLivePlayerErrorMessage')`: each row of the contract's mapping returns its string; and `it('never names a browser')`: over every row, the message matches neither `/chrome/i` nor `/edge/i`.

### vitest: `frontend/src/__tests__/api.leaveHlsSession.test.js` (new)

- **A1** `it('sends DELETE to the session URL with no Authorization header')`: `fetch` is called once with `'http://localhost:3000/hls/<T>'` and options whose `method` is `'DELETE'` and whose `headers` carry no `Authorization`; resolves `true` on a 204.
- **A2** `it('passes keepalive through')`: `{ keepalive: true }` reaches `fetch`'s options.
- **A3** `it('never throws on a refusal or a network failure')`: a 403 response resolves `false`; a rejected `fetch` resolves `false`.
- **A4** `it('shows no notification')`: `@mantine/notifications`'s `notifications.show` (mocked) is never called across A1-A3's cases.

### vitest: `frontend/src/components/__tests__/FloatingVideo.test.jsx`, `describe('Live channel over HLS')`

Every test flushes pending promises (`await act(async () => {})`) after render, because the HLS init is async (Decision 5, and the `getAuthToken` await). The store state is `{ isVisible: true, streamUrl: '/proxy/ts/stream/ch-1?output_format=hls', contentType: 'live' }` unless a test says otherwise; "Fire instance N's event" means calling `fireHls(hlsInstances[N], event, data)` (§ Tests changed, 8); `MANIFEST_LOADED` is fired with `{ levels: [{ url: 'http://localhost:3000/hls/' + T + '/video.m3u8' }], audioTracks: [] }`.

- **F1** `it('plays a channel HLS URL through hls.js, not mpegts.js')`: after a flush, `hlsInstances` has length 1; `mpegts.createPlayer` is not called; after instance 0's `MEDIA_ATTACHED` handler runs, `hlsInstances[0].loadSource` is called with `'http://localhost:3000/proxy/ts/stream/ch-1?output_format=hls'`.
- **F2** `it('uses the live HLS config')`: `capturedHlsConfig.backBufferLength` is 120, and `capturedHlsConfig.manifestLoadPolicy?.default?.maxLoadTimeMs` (optional chaining, so an absent policy fails as `undefined` rather than as a `TypeError`) is greater than 57100 (the component passes `buildLiveHlsConfig`'s result, not the recordings config).
- **F3** `it('closing the player destroys hls.js, then leaves the session')`: fire instance 0's `MANIFEST_LOADED`, click close; `API.leaveHlsSession` is called once with `('http://localhost:3000/hls/' + T)` and no `keepalive: true`, and `hlsInstances[0].destroy.mock.invocationCallOrder[0]` is less than `API.leaveHlsSession.mock.invocationCallOrder[0]`.
- **F4** `it('sends no leave before the manifest names a session')`: close without firing `MANIFEST_LOADED`; `API.leaveHlsSession` is not called.
- **F5** `it('a switch waits for the previous leave before the next entry')`: fire `MANIFEST_LOADED`; make `leaveHlsSession` return a pending promise; rerender with `streamUrl` `'/proxy/ts/stream/ch-2?output_format=hls'`; flush microtasks: `hlsInstances` has length 1 (ch-1 only); resolve the promise and flush: `hlsInstances` has length 2 and instance 1 loads `'…/proxy/ts/stream/ch-2?output_format=hls'`.
- **F6** `it('a leave that never answers delays the next entry by at most HLS_LEAVE_WAIT_MS')`: fake timers; a leave promise that never settles; after the switch, advance 1999 ms and flush: `hlsInstances` has length 1; advance 1 ms more and flush: length 2.
- **F7** `it('prefers hls.js over native HLS')`: `HTMLVideoElement.prototype.canPlayType` returns `'maybe'` and `Hls.isSupported` returns true; after a flush `hlsInstances` has length 1 and `video.src` is not set to the entry URL.
- **F8** `it('pagehide leaves with keepalive, once')`: fire `MANIFEST_LOADED`, dispatch `pagehide` on `window`: `leaveHlsSession` is called with `(sessionUrl, { keepalive: true })`; then click close: it is not called again.
- **F9** `it('a 403 from /hls/ re-enters once, then shows that the session ended')`: fire instance 0's `ERROR` handler with `{ type: 'networkError', details: 'levelLoadError', fatal: false, response: { code: 403 }, url: 'http://localhost:3000/hls/' + T + '/video.m3u8' }`; `hlsInstances[0].destroy` has been called synchronously (before any flush); flush: `hlsInstances` has length 2, instance 1 loads the same entry URL, and `API.getAuthToken` has been called **exactly 2 times** (once by the first entry, once by the re-entry), with `API.getAuthToken.mock.invocationCallOrder[1]` less than `hlsInstances[1].attachMedia.mock.invocationCallOrder[0]` (the re-entry's refresh precedes the new instance's attach; the first entry's call alone cannot satisfy this); fire the same error on instance 1 and flush: `hlsInstances` still has length 2, and "The playback session ended." is shown.
- **F9b** `it('two 403s from one expired session re-enter exactly once')`: fire instance 0's `ERROR` with the video `levelLoadError` 403, then, **before** flushing, instance 0's `ERROR` with `{ type: 'networkError', details: 'audioTrackLoadError', fatal: false, response: { code: 403 }, url: 'http://localhost:3000/hls/' + T + '/aac.m3u8' }` (B.3's order); flush: `hlsInstances` has length 2, and "The playback session ended." is **not** shown.
- **F9c** `it('after a re-entry, closing leaves the new session')`: fire instance 0's `MANIFEST_LOADED` with T, then its 403; flush; fire instance 1's `MANIFEST_LOADED` with `T2 = 'v1.' + 'C'.repeat(22) + '.' + 'D'.repeat(43)`; click close: `API.leaveHlsSession` is called exactly once, with `'http://localhost:3000/hls/' + T2`.
- **F9d** `it('a 403 on a segment re-enters too')`: fire instance 0's `ERROR` with `{ type: 'networkError', details: 'fragLoadError', fatal: false, response: { code: 403, url: 'http://localhost:3000/hls/' + T + '/aac/12.m4s' }, frag: { url: 'http://localhost:3000/hls/' + T + '/aac/12.m4s' } }` and no top-level `url`; flush: `hlsInstances` has length 2.
- **F10** `it('a 410 from /hls/ is not re-entered')`: fire the `ERROR` handler with `response: { code: 410 }` and a `/hls/` URL: no second instance, and "The channel stopped, or this idle session was ended." is shown.
- **F11** `it('a manifest refusal shows its message and does not recover')`: fire `{ type: 'networkError', details: 'manifestLoadError', fatal: true, response: { code: 429 }, url: 'http://localhost:3000/proxy/ts/stream/ch-1?output_format=hls' }`: `startLoad` is not called, and "Stream limit reached. Close another stream and try again." is shown.
- **F12** `it('falls back to native HLS with the access token in the query')`: `Hls.isSupported` returns false and `canPlayType` returns `'maybe'`: after a flush `hlsInstances` is empty, and `video.src` is `'http://localhost:3000/proxy/ts/stream/ch-1?output_format=hls&token=test-token'`. And `it('says so when neither exists')`: `canPlayType` returns `''`: "This browser can't play live channels." is shown.

### E2E: `e2e/tests/frontend/player-hls.spec.ts` (new; `frontend` project)

A local helper builds the channel exactly as `hls-sessions.spec.ts:16-27` does, importing `lockedProfile` (and `withDeadline`) from `'../streaming/helpers'` as `stats.spec.ts:2` does (one scenario channel, `asset: 'mpeg2-576i-mp2'`, `rate: 1`, the locked Proxy stream profile, `seed.upstreamChannel`), so the relay encodes SD in software on CI. Both tests set the player preferences before the first navigation with `adminPage.addInitScript`: `localStorage['dispatcharr-player-prefs'] = JSON.stringify({ webPlayerOutputProfileId: <the first id from GET /api/core/outputprofiles/>, muted: true })` (muted, so autoplay never depends on the headless autoplay policy). Both open the player from the TV Guide: `gotoSurface(adminPage, guideSurface)`, `getByPlaceholder('Search channels...').fill(channel.name)`, then click `getByTestId('guide-grid').getByAltText(channel.name, { exact: false })` (the logo's `onClick` is `handleLogoClick`, `GuideRow.jsx:138`, which calls `getShowVideoUrl`, `Guide.jsx:774-783`). Both record every request with `adminPage.on('request', …)` from before the click. The session token is the second path segment of the `/hls/…` requests; the test asserts there is exactly one distinct token and that it matches `MEDIA_SESSION_TOKEN_RE` (`e2e/fixtures/hls.ts:17`).

- **E1** `test('a channel plays over HLS in the browser player, and closing the player leaves its session', { tag: '@contract' }, …)`, fixtures `adminPage, api, seed, upstream, streamClient, pageErrors`:
  1. A TS client holds the channel open first (`streamClient.open('/proxy/ts/stream/<uuid>')`, `withDeadline(streamClient.readPackets(20), 30_000, …)`), as `hls-sessions.spec.ts:94-97` does, so the channel is still running when the status is read after the leave (with no other client, the leave would stop it).
  2. The entry: the first request to `/proxy/ts/stream/<uuid>` from the page has `searchParams.get('output_format')` `toBe('hls')` (message: "the channel is tuned over HLS") and `searchParams.has('output_profile')` `toBe(false)` (message: "R18: an HLS tune carries no Output Profile, although the preference is set").
  3. Playback: `expect.poll` on `video.currentTime` (`getByTestId('floating-video').locator('video')`) until it is above 0 (60 s budget: a cold SD software entry), read it as `t0`, then `expect.poll` until it exceeds `t0 + 3` (30 s budget), and `video.paused` is false.
  4. Presence: `readChannelStatus(api, uuid)`'s clients' `output_format`s, sorted, equal `['hls', 'mpegts']`.
  5. `await pageErrors.expectClean()` (everything up to here is held to the page-error rule), then `pageErrors.waiveAutomaticCheck('closing the player destroys hls.js, which aborts whichever playlist or segment request is in flight by design (FloatingVideo.jsx HLS destroy); the check above covered the whole playback')`.
  6. The leave: start `adminPage.waitForResponse(predicate, { timeout: 15_000 })` for a `DELETE` whose path starts with `/hls/` (an explicit timeout: `e2e/playwright.config.ts` sets no `actionTimeout`, so without one the wait would run to the test's own timeout and fail as that), click `getByTestId('floating-video-close')`; the response's path is `'/hls/' + token` and its status is 204.
  7. The very next `readChannelStatus` read: the clients' `output_format`s equal `['mpegts']` (no wait: the 204 is written after the release, `hls.go:597-604`).
- **E2** `test('Q9: how often hls.js reloads a live playlist while the player is paused', { tag: '@characterization' }, …)`, fixtures `adminPage, api, seed, upstream, pageErrors`. The characterization comment names the implementation fact: it records hls.js 1.6.15's live-playlist reload behaviour with a paused media element (spec Q9), which a different player library or version may change; it pins nothing about Mino. Steps: play as E1 steps 2-3 (no TS client); pause with `video.evaluate((v) => v.pause())`; count, over the next 20 s, the GETs of `/hls/<token>/video.m3u8` and of `.m4s` under `/hls/<token>/`; assert only that `video.paused` is true at the end of the window; record `{ videoPlaylistReloads, segmentsFetched, windowSeconds: 20 }` with `testInfo.annotations.push({ type: 'Q9', description: … })`, `testInfo.attach('q9.json', …)` and a `console.log` line starting `Q9:`; then `expectClean`, waive (the same reason as E1), and close. It does **not** resume: if hls.js stopped reloading, the session would have departed at the 12 s idle timeout, and a resumed player's 403 would fail the page-error check for the very outcome the measurement exists to report.

Both tests fit the `frontend` project's 120 s budget in the expected case: the prototype's hls.js entry and playback are sub-second once the relay answers, the relay's cold SD entry is well under the 43 s wait, and E2's window is 20 s. The worst-case sum of E1's non-gate budgets (the TS read's 30 s, the first `currentTime`'s 60 s, the advance's 30 s) equals the 120 s project timeout, so a pathologically slow run fails as a test timeout rather than on the named `expect.poll`. That is accepted: these timeouts are generous non-gates (spec § Testing and gates), and none is lowered to make room.

## Tests changed

Every change, with its before and after, at `4ed75d96`.

1. **`frontend/src/utils/cards/__tests__/RecordingCardUtils.test.js:151-156`** (the behaviour it pins, `getShowVideoUrl`'s URL, is what this PR changes). Before: `it('returns proxy URL with mpegts output format for channel')`, `expect(result).toBe('/proxy/ts/stream/channel-123?output_format=mpegts')`. After: `it('returns the channel HLS entry URL')`, `expect(result).toBe('/proxy/ts/stream/channel-123?output_format=hls')`.
2. **`RecordingCardUtils.test.js:158-169`**. Before: `it('includes output_profile when set in player prefs')`, with the preference 5, `expect(result).toBe('/proxy/ts/stream/channel-123?output_format=mpegts&output_profile=5')`. After: `it('ignores the web-player Output Profile preference (R18)')`, same setup, `expect(result).toBe('/proxy/ts/stream/channel-123?output_format=hls')`. The old literal is not deleted: it moves to U1 against `buildLiveStreamUrl`, whose behaviour it always described (spec § Browser player's vitest list).
3. **`RecordingCardUtils.test.js:171-177`**. Before: `it('prepends dev server URL in dev mode with output params')`, `toMatch(/^https?:\/\/.*:5656\/proxy\/ts\/stream\/channel-123\?output_format=mpegts$/)`. After: the same title, `toMatch(/^https?:\/\/.*:5656\/proxy\/ts\/stream\/channel-123\?output_format=hls$/)`.
4. **`frontend/src/components/cards/__tests__/StreamConnectionCard.test.jsx:801`**, tightened to pin R26 (spec § Browser player). Before: `expect.stringContaining('/proxy/ts/stream/ch-uuid-1')`. After: `expect.stringMatching(/\/proxy\/ts\/stream\/ch-uuid-1\?output_format=mpegts/)`. The file does not mock `FloatingVideoUtils`, so the real `buildLiveStreamUrl` produces the URL.
5. **`frontend/src/components/tables/__tests__/StreamsTable.test.jsx`**, tightened to pin R18 (spec amended by this plan). Before, the module mock at `:34-36` is `buildLiveStreamUrl: vi.fn((path) => path)` and the test at `:812-831` asserts only `expect(mockShowVideo).toHaveBeenCalled()`. After: the mock is `buildLiveStreamUrl: vi.fn((path) => \`${path}?output_format=mpegts\`)` and `buildChannelHlsUrl: vi.fn((path) => \`${path}?output_format=hls\`)`; the test imports `buildLiveStreamUrl` from the mocked module and adds, **in this order after the existing `toHaveBeenCalled()`**, `expect(mockShowVideo).toHaveBeenCalledWith('/proxy/ts/stream/hash-abc?output_format=mpegts', 'live', expect.objectContaining({ name: 'My Stream' }))` and then `expect(buildLiveStreamUrl).toHaveBeenCalledWith('/proxy/ts/stream/hash-abc')`. The URL assertion comes first so the break-check's red names the URL. Why: at the seed, the break-check "point stream previews at HLS" reddens this test only with `AssertionError: expected "vi.fn()" to be called at least once` plus the unhandled `Error: [vitest] No "buildChannelHlsUrl" export is defined on the "../../../utils/components/FloatingVideoUtils.js" mock` (measured, Appendix B.4): the mock's missing export, not the URL. No other test in the file reads the mock's return value (`grep -n buildLiveStreamUrl` finds only `:35` and the title at `:812`).
6. **`frontend/src/components/tables/__tests__/ChannelTableStreams.test.jsx:24-26`**, test support only. Before: the mock exports `buildLiveStreamUrl: vi.fn((path) => \`${path}?output_format=mpegts\`)`. After: it also exports `buildChannelHlsUrl: vi.fn((path) => \`${path}?output_format=hls\`)`. No assertion changes; the existing assertions (`:420-445`) already pin the TS builder, and with the export present a wrong edit reddens on them rather than on the mock.
7. **`frontend/src/components/tables/__tests__/ChannelsTable.test.jsx`** (the behaviour it pins, the channels table's play URL, is what this PR changes). The mock at `:57-59` gains `buildChannelHlsUrl: vi.fn((path) => path)` beside `buildLiveStreamUrl`; the import at `:443` adds `buildChannelHlsUrl`. The preview test at `:1000-1021`: before, `vi.mocked(buildLiveStreamUrl).mockReturnValue('/proxy/ts/stream/uuid-abc')` and `expect(showVideoMock).toHaveBeenCalledWith(expect.stringContaining('uuid-abc'), 'live', expect.objectContaining({ name: 'ESPN' }))`. After: `vi.mocked(buildChannelHlsUrl).mockReturnValue('/proxy/ts/stream/uuid-abc?output_format=hls')`, `expect(buildChannelHlsUrl).toHaveBeenCalledWith('/proxy/ts/stream/uuid-abc')`, `expect(buildLiveStreamUrl).not.toHaveBeenCalled()`, and `expect(showVideoMock).toHaveBeenCalledWith(expect.stringContaining('/proxy/ts/stream/uuid-abc?output_format=hls'), 'live', expect.objectContaining({ name: 'ESPN' }))`. The Copy URL test (`:1069-1088`) is unchanged.
8. **`frontend/src/components/__tests__/FloatingVideo.test.jsx`**, test support only, no existing assertion changed. No existing test reads `mockHlsInstance`'s spies (`grep -n mockHlsInstance` finds only its definition at `:23` and its use at `:52`); the existing hls.js tests (`:285-334`) read only `capturedHlsConfig` and `Hls.isSupported`. The edits:
   - The mock's constructor (`:47-53`). Before: it records `capturedHlsConfig` and `Object.assign(this, mockHlsInstance)`, so every instance shares one set of spies and nothing counts instances. After: it still records `capturedHlsConfig` (and still throws under `forceHlsInitError`), then gives **each instance its own** `attachMedia`, `loadSource`, `destroy`, `startLoad` and `recoverMediaError` spies, a `handlers` map, and an `on` spy that appends `(event, handler)` to `handlers`, and pushes `this` onto a module-level `hlsInstances` array. `mockHlsInstance` (`:23-28`) is deleted, since nothing reads it.
   - A helper `fireHls(instance, event, data)` calls every handler that instance registered for `event` with `(event, data)`.
   - The mock's `static Events` (`:37-40`) gains `MANIFEST_LOADED: 'manifestLoaded'` and `MANIFEST_PARSED: 'manifestParsed'`.
   - `beforeEach` (`:95-127`) sets `hlsInstances = []` (beside `capturedHlsConfig = null`, `:97`) and `Hls.isSupported.mockReturnValue(true)`.
   - A new `vi.mock('../../api', () => ({ default: { leaveHlsSession: vi.fn(() => Promise.resolve(true)), getAuthToken: vi.fn(() => Promise.resolve('fresh-token')) } }))`, because the component now imports `API`.
   - `act` is added to the `@testing-library/react` import (`:1`).

**Not changed, verified at the seed:** `Guide.test.jsx:284`/`:431`, `DVR.test.jsx:166`/`:243`, `RecordingCard.test.jsx:28`/`:244`, `RecordingDetailsModal.test.jsx:31`/`:222` and `ProgramDetailModal.test.jsx:12` each mock `getShowVideoUrl` and assert no URL; `useVideoStore.test.jsx`, `VODModal.test.jsx` and `SeriesModal.test.jsx` do not touch the live builders.

## Break-checks

Each is: the named wrong edit, the test that reddens, the message that names the mechanism, then the revert. The implementer records each run's actual message in the PR body.

1. **(spec)** Point `getShowVideoUrl` back at `buildLiveStreamUrl` (`RecordingCardUtils.js`). → `RecordingCardUtils.test.js`'s "returns the channel HLS entry URL" fails `expected '/proxy/ts/stream/channel-123?output_format=mpegts' to be '/proxy/ts/stream/channel-123?output_format=hls'`; and E1 fails at step 2 with `the channel is tuned over HLS … Expected: "hls" Received: "mpegts"` (E1 plays from the Guide, whose logo click goes through `getShowVideoUrl`). The E2E half is shown per ruling R73: a throwaway commit carrying **only** this wrong edit is pushed, its CI run's `frontend` result is observed and linked in the PR body, and it is undone by its own revert commit (no force-push, no history rewrite).
2. **(spec)** Skip the leave on close: delete the `API.leaveHlsSession` call from the HLS player's `destroy()`. → F3 fails `expected "vi.fn()" to be called 1 times, but got 0 times`; and E1 fails at step 6 with `page.waitForResponse: Timeout 15000ms exceeded while waiting for event "response"` (no `DELETE /hls/…` is sent). The E2E half on its **own** throwaway commit, pushed, observed and reverted per R73: it cannot share break-check 1's commit, because that one's wrong edit fails E1 at step 2 and E1 never reaches the close.
3. **(spec)** Point stream previews at HLS: in `StreamsTable.jsx`'s `handleWatchStream` (`:954`), call `buildChannelHlsUrl` instead of `buildLiveStreamUrl`. → the tightened `StreamsTable.test.jsx` preview test fails at its `mockShowVideo` URL assertion (ordered before the `buildLiveStreamUrl` one, § Tests changed, 5): `expected "spy" to be called with arguments: [ '/proxy/ts/stream/hash-abc?output_format=mpegts', 'live', … ]`, received `'/proxy/ts/stream/hash-abc?output_format=hls'`, with no unhandled mock error (the mock now has the export).
4. **(spec)** Point the Stats card at HLS: `StreamConnectionCard.jsx:516` calls `buildChannelHlsUrl`. → the tightened `StreamConnectionCard.test.jsx` test fails `expected "spy" to be called with arguments: [ StringMatching /\/proxy\/ts\/stream\/ch-uuid-1\?output_format=mpegts/, 'live', … ]` against `…?output_format=hls` (R26).
5. **Leave before destroy.** Swap Decision 4's order in `destroy()` (send the leave, then `hls.destroy()`). → F3 fails on `expect(destroyOrder).toBeLessThan(leaveOrder)`, naming the two invocation orders.
6. **No wait on a switch.** Drop the `await Promise.race([pendingLeaveRef.current, …])`. → F5 fails at its pre-resolve check: `expected [ {…}, {…} ] to have a length of 1 but got 2` (instance 1 was built before the leave answered).
7. **The hls.js defaults.** Build the live Hls from `{ xhrSetup }` only (no `buildLiveHlsConfig`). → F2 fails `expected undefined to be greater than 57100` (`manifestLoadPolicy` is absent), naming the timeout the relay's cold start needs; U5 is unaffected (it tests the builder), which is why F2 exists.
8. **Unbounded re-entry.** Remove the once-guard on 403 re-entry. → F9 fails after the second 403: `expected [ {…}, {…}, {…} ] to have a length of 2 but got 3`.
9. **Native first.** Test `canPlayType` before `Hls.isSupported()`. → F7 fails: `expected [] to have a length of 1 but got +0` (no hls.js instance; the native path took it), which is the Chromium 151 case (§ Codec limits).
10. **Count 403 events, not re-entries.** Make the once-guard a counter of 403 events that stops at one, and leave instance 0 armed until after the `getAuthToken` await. → F9b fails: `expected [ {…} ] to have a length of 2 but got 1`, or, with the text check, "The playback session ended." is found (the audio 403 was counted as the second).
11. **Stale session URL.** Keep the session URL from instance 0 across the re-entry (do not replace it at instance 1's `MANIFEST_LOADED`). → F9c fails: `expected "vi.fn()" to be called with arguments: [ 'http://localhost:3000/hls/v1.CCCC…' ]`, received the T URL, or no call (the left flag was set).
12. **Top-level URL only.** Read only `data.url` in the 403 detector. → F9d fails: `expected [ {…} ] to have a length of 2 but got 1` (the segment 403 was not recognised).
13. **No refresh on re-entry.** Drop the `await API.getAuthToken()` from the re-entry path (the first entry's stays). → F9 fails `expected "vi.fn()" to be called 2 times, but got 1 times`.

## Gates

- `cd frontend && npm test` (vitest, whole suite) and `npm run build`, green. Record the before and after counts (Task 1).
- `npm run lint`: no new error in a touched file (CI does not run it; CLAUDE.md records ~112 pre-existing errors). Run it on the touched files before and after and list the two counts in the PR body.
- The e2e package typechecks (`tsc --noEmit`, the e2e hook), and the `guards` project passes locally (it needs no container): `tags.spec.ts` (E1 `@contract`, E2 `@characterization` with its comment), `pageerrors-enforcement.spec.ts` (both tests destructure `pageErrors`), `testid.spec.ts`.
- CI on the PR: `Frontend result`, `E2E result` (the `frontend` project runs E1 and E2; the `migration/` branch runs every project), `Lifecycle result`, `Backend result`, `Go result`, all green. Nothing in the backend or Go changes, so the last three are the unchanged suites.
- Not applicable, and the PR body says so: the Go coverage census (no Go change), Python Gate 2 (no coveragerc module touched), parity rows (no relay behaviour changes), the AVPlayer manual gate (the browser is the subject; R45).

## PR description draft

> **Phase 4a-2: the browser player plays live channels over HLS.**
>
> Channel playback (the channels table, the TV Guide, the DVR page, recording cards and modals) now requests `/proxy/ts/stream/<uuid>?output_format=hls` and plays through hls.js, or natively where only native HLS exists, so Firefox plays live channels too. Closing or switching the player, or leaving the page, ends the HLS session at once with `DELETE /hls/<token>`; a switch waits up to 2 s for that leave so a single-slot provider sees the release before the next tune. Stream previews by stream hash and the Stats card's play button stay on mpegts.js over TS with the web-player Output Profile preference, unchanged (owner rulings R18, R26). Spec D18. No server change.
>
> **hls.js configuration.** `backBufferLength: 120`, `liveSyncDurationCount: 3`, `lowLatencyMode: false`, the JWT on every request through `xhrSetup`, a 65 s entry timeout (the relay's 14.1 s next-source budget plus its 43 s ready wait, plus margin) and a 50 s playlist timeout (above its 43 s first-segment wait), which hls.js 1.6's 20 s and 10 s defaults would abandon on a cold software start. A 403 from `/hls/` re-enters once; a 410 does not (R68).
>
> **Tests.** New vitest: `FloatingVideoUtils.test.js` (U1-U7), `api.leaveHlsSession.test.js` (A1-A4, `api.js`'s first test file), `FloatingVideo.test.jsx` (F1-F12, F9b-F9d). New E2E: `e2e/tests/frontend/player-hls.spec.ts`, E1 (`@contract`: a Guide play tunes `output_format=hls` with no `output_profile`, `currentTime` advances in CI's Chromium, the `hls` client is listed, and close sends `DELETE /hls/<token>` → 204 with the client gone on the next status read) and E2 (`@characterization`: spec Q9, hls.js's reload cadence while paused, recorded, not gated: ⟨N⟩ reloads of `video.m3u8` in 20 s on run ⟨id⟩).
>
> **Changed tests, before → after:**
> 1. `RecordingCardUtils.test.js:151-156`: `…?output_format=mpegts` → `…?output_format=hls`.
> 2. `RecordingCardUtils.test.js:158-169`: `…?output_format=mpegts&output_profile=5` → `…?output_format=hls` (the preference is ignored, R18); the old literal moves to a `buildLiveStreamUrl` test.
> 3. `RecordingCardUtils.test.js:171-177`: dev-mode regex `…output_format=mpegts$` → `…output_format=hls$`.
> 4. `StreamConnectionCard.test.jsx:801`: `stringContaining('/proxy/ts/stream/ch-uuid-1')` → `stringMatching(/…ch-uuid-1\?output_format=mpegts/)` (tightened, R26).
> 5. `StreamsTable.test.jsx:34-36`, `:812-831`: an identity mock and `toHaveBeenCalled()` → a mock appending `?output_format=mpegts` plus a `buildChannelHlsUrl` export, and `toHaveBeenCalledWith('/proxy/ts/stream/hash-abc?output_format=mpegts', …)` (tightened, R18).
> 6. `ChannelTableStreams.test.jsx:24-26`: the mock gains a `buildChannelHlsUrl` export; no assertion changes.
> 7. `ChannelsTable.test.jsx:57-59`, `:443`, `:1000-1021`: the mock gains `buildChannelHlsUrl`; the preview test's `buildLiveStreamUrl` → `buildChannelHlsUrl` and `stringContaining('uuid-abc')` → `stringContaining('/proxy/ts/stream/uuid-abc?output_format=hls')`, plus `buildLiveStreamUrl` not called.
> 8. `FloatingVideo.test.jsx`: the hls.js mock records each instance with its own spies (`hlsInstances`, `fireHls`) instead of sharing `mockHlsInstance`, gains two event names, and `api` is mocked; no existing assertion changes.
>
> **Break-checks** (named wrong edit → test → message): ⟨the thirteen from the plan, each with the message as run; for 1 and 2, the throwaway commit, its CI run and its revert commit, per R73⟩.
>
> **Codec limits.** CI's Chromium (Playwright 1.62.1, linux/amd64) decodes H.264 and AAC through MSE, not AC-3 or E-AC-3, so the browser always plays the `aac` group; Playwright's linux/arm64 Chromium decodes neither, so the playback E2E does not run on an arm64 Linux host. A channel set to "HLS (Automatic)" that copies HEVC or AC-3-only audio shows "This channel's video or audio format can't be played in this browser." in Chromium and Firefox.
>
> **Gates.** No Go, Python, nginx or migration change: no Go census, no Python Gate 2, no parity row, no AVPlayer gate (R45). `npm test` ⟨before → after counts⟩, `npm run build`, lint on touched files ⟨before → after⟩.
>
> Plan: `docs/superpowers/plans/2026-09-29-phase4-4a2-browser-hls.md` (reviewed PASS at ⟨sha⟩).
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

## Spec amendments in this PR

This plan PR carries them; the implementation PR edits no spec text. All are in § Browser player (4a-2; R18), plus one Changelog entry at the end of the Changelog:

- The hls.js config list gains the load policies: 65 s on the entry, 50 s on a media playlist (Decision 1).
- A 410 from `/hls/` is not re-requested (Decision 7; ruling R68).
- The leave bullet gains destroy-before-leave and the bounded wait on a switch (Decisions 4-5).
- The vitest list is corrected: the five page and card tests do not change; `StreamsTable.test.jsx` is tightened; `ChannelTableStreams.test.jsx`'s mock gains an export.
- A new bullet, "Browser facts the E2E rests on": the codec measurements, the `Hls.isSupported()`-first order, and the Q9 prototype.

## Rulings

The four questions this plan raised at `0f518924` were ruled by the orchestrator on 2026-09-29; R73 re-ruled R71 after round-1 review finding 2.

- **R68.** The browser player re-enters **once** on a 403 from `/hls/` (the spec), and **never** on a 410. Decision 7 and the spec amendment carry it. The 403 re-entry makes a relay restart and a restored back-forward-cache page recover; the accepted cost is that a browser viewer an admin stopped through `DELETE /proxy/ts/stop_client/<uuid>`, or one the stream limit terminated, comes back once (the relay's 403 does not say which, by design, spec § Session resources), and under `terminate_on_limit_exceeded` two browser viewers of one limit-1 user can each displace the other once.
- **R69.** No `disableRemotePlayback` for iPhone Safari's `ManagedMediaSource` path: unverified, and the browser is secondary to the native app. Recorded as a follow-up (§ Residual risks).
- **R70.** Development mode plays no live stream, TS or HLS, since Phase 2 stage 2d-3 (§ How the browser reaches HLS, last paragraph). The orchestrator files a follow-up issue; not 4a-2's scope.
- **R71**, re-ruled by **R73.** The E2E halves of break-checks 1 and 2 use **two** throwaway commits, one wrong edit each, each pushed, its CI run observed, then undone by its own revert commit, with no force-push and no history rewrite (Task 7, § Break-checks). There is no "skip the CI run" option.

## Residual risks

- **Q9 is a prototype until CI measures it.** The prototype (Appendix B.2) saw hls.js keep reloading every 2.0 s while paused. If CI shows it stopping, a paused browser viewer departs at the idle timeout and the spec's Q9 follow-up (leave on pause, re-tune on play) applies, as a follow-up PR, not in this one.
- **The JWT in the native path's URL** reaches nginx's access log, as the recordings path's already does. Native-only browsers are rare after R17 (Chromium 151 prefers hls.js here).
- **A switch from an HLS channel to a TS preview does not wait for the leave** (Decision 5); 4a-1c's reclaim covers the single-slot case.
- **iPhone Safari may not play at all** (R69, a follow-up): hls.js 1.6 plays there through `ManagedMediaSource`, which WebKit requires to have `disableRemotePlayback` set or an AirPlay alternative source, and hls.js 1.6.15 sets neither (`grep -rn disableRemotePlayback` in its `src/` is empty). The fix would be one line, `video.disableRemotePlayback = true` when `!('MediaSource' in window) && 'ManagedMediaSource' in window`; it is not in this PR.
- **A 410 after a reclaim reads as "stopped" to the viewer** (Decision 7): the message names both causes, and the viewer presses play to tune again.

## Appendix A: documentation hunks (byte-exact, against `4ed75d96`)

Both hunks were checked with `git apply --check` against `git archive 4ed75d96 CLAUDE.md e2e/COVERAGE.md`. The Q9 row's `⟨…⟩` slots are filled from E2's CI run: `⟨N⟩` and `⟨M⟩` from its `Q9:` log line, `⟨run id⟩` the Actions run id, and the last slot one sentence choosing the branch the numbers show.

### A.1 `CLAUDE.md`

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -98,7 +98,7 @@
 
 **Events and plugins.** Every interesting transition calls `log_system_event()` (`core/utils.py`), writing a `SystemEvent` row and fanning out to Connect (webhook/script/API) on its own greenlet; vocabulary is a fixed dict at `apps/connect/models.py`. Since Phase 1 PR 6 the relay itself no longer calls it directly — the thirteen transitions that used to call it directly (and any new ones, such as the degraded-failover `channel_error`) post to `POST /api/relay/events` instead, and `core/relay_events.py` makes the `log_system_event()` call on the API process. **Use this extension point before adding polling anywhere.** Plugins live outside `INSTALLED_APPS` in `/app/data/plugins/<name>/` (see `Plugins.md`), run arbitrary Python in-process, unsandboxed; `dispatcharr/celery.py` calls `PluginManager.discover_plugins()` in `worker_process_init` — per forked child, deliberately, so children don't inherit DB connections.
 
-**Frontend.** `frontend/src/store/*.jsx` — Zustand, one store per domain; **new global state goes here, not React Context**. `frontend/src/api.js` — all HTTP; **components must not call fetch/axios directly**. `frontend/src/WebSocket.jsx` — one consumer on `/ws/`, generic `updates` group. Mantine 8; **do not add UI libraries.** `api.js` and `WebSocket.jsx` are the two largest files in the tree with no tests.
+**Frontend.** `frontend/src/store/*.jsx` — Zustand, one store per domain; **new global state goes here, not React Context**. `frontend/src/api.js` — all HTTP; **components must not call fetch/axios directly**. `frontend/src/WebSocket.jsx` — one consumer on `/ws/`, generic `updates` group. Mantine 8; **do not add UI libraries.** `api.js` and `WebSocket.jsx` are the two largest files in the tree with almost no tests: `api.js`'s one test file covers only `leaveHlsSession` (Phase 4a-2). The floating player (`frontend/src/components/FloatingVideo.jsx`) plays live **channels** over HLS through hls.js, leaving each media session with `DELETE /hls/<token>` on close, switch and `pagehide`, and plays **stream previews** and the Stats card's play button over MPEG-TS through mpegts.js (Phase 4 spec D18, rulings R18 and R26); the URL decides, `output_format=hls` or not.
 
 ## Structural constraints on refactoring
 
```

### A.2 `e2e/COVERAGE.md`

```diff
--- a/e2e/COVERAGE.md
+++ b/e2e/COVERAGE.md
@@ -213,6 +213,8 @@
 | Streaming | Live HLS failover: an upstream fault on `h264-1080i-aac-ac3` switches the channel to an alternate carrying `mpeg2-576i-mp2`, and the next media playlist carries `EXT-X-DISCONTINUITY` and a new `EXT-X-MAP` with the media sequence continuing and the multivariant's `CODECS` unchanged. `tests/streaming/hls-failover.spec.ts` | 4a-1b | done |
 | Streaming | **Observation (spec Q6, ruling R29), measured on CI's software encoder, not a gate:** the failover gap from the switch (the first status poll naming the alternate) to the new generation's first segment was 8.68 s (CI run 36495275297, one run, at 250 ms poll resolution; the fault-to-flip time was 0.80 s); the software transcode of `h264-1080i-aac-ac3` (1080i → 1080p50, libx264) published 1.044 of real time (42.0 s of segments over the 40 s window, run 36495275297) over a 40 s window under the `streaming` project's two workers. At or above real time, so no finding. `tests/streaming/hls-failover.spec.ts`, `tests/streaming/hls-realtime.spec.ts` | 4a-1b | done |
 | Streaming | **Gap, pinned in Go only:** idle departure (`max(12 s, 6 × TARGETDURATION)`), the resume within 300 s, the sweeper's removals and the self-stop paths are pinned by `relay/session` and `relay/httpapi` tests with an injected clock and a stand-in encoder, never by an E2E that waits out a timeout (ruling R24). No E2E plays HLS in a browser or in AVPlayer: hls.js is 4a-2's `frontend` project, and AVPlayer is the manual gate recorded in the 4a-1b PR body (spec § Testing and gates). | 4a-1b | done |
+| Frontend | Live channel playback over HLS in the browser player (Phase 4a-2, spec D18): a channel played from the TV Guide's channel logo requests `/proxy/ts/stream/<uuid>?output_format=hls` with no `output_profile`, although the web-player Output Profile preference is set (R18); it plays through hls.js in CI's Chromium (`currentTime` advances); `/proxy/ts/status/<uuid>` lists it as an `hls` client; and closing the player sends `DELETE /hls/<token>` for the token the player's own media playlists carried, answered 204, after which the `hls` client is gone on the very next status read. The Channels table's play button builds the same entry through `buildChannelHlsUrl`, pinned by vitest (`ChannelsTable.test.jsx`), not by this spec. `tests/frontend/player-hls.spec.ts` | 4a-2 | done |
+| Frontend | **Observation (spec Q9), measured on CI, not a gate:** while the browser player is paused on a live HLS channel, hls.js 1.6 reloaded `video.m3u8` ⟨N⟩ times in 20 s (CI run ⟨run id⟩), fetching ⟨M⟩ segments. ⟨One sentence: it keeps reloading, as AVPlayer does (M7), so no leave-on-pause is needed; or it stops, and spec Q9's follow-up applies.⟩ `tests/frontend/player-hls.spec.ts` | 4a-2 | done |
 
 The ten G1 rows above are covered by these specs (the two seeding rows
 share one file, as do the two principal rows):
```

## Appendix B: how the measurements were taken

All in the planner's scratchpad (`…/scratchpad/phase4/`), never in the repository.

**B.1 Codec support.** A Node script launched Playwright's Chromium and evaluated `MediaSource.isTypeSupported` for `video/mp4; codecs="avc1.64002a,mp4a.40.2"`, `avc1.64002a`, `avc1.64001f`, `audio/mp4; codecs="mp4a.40.2"`, `ac-3`, `ec-3` and `hvc1.1.6.L120.90`, plus `document.createElement('video').canPlayType('application/vnd.apple.mpegurl')`.
- macOS arm64, the repository's own `e2e/node_modules/playwright` (1.62.1), headless and headed: Chromium 151.0.7922.34; H.264 and AAC true, AC-3 and E-AC-3 false, HEVC false headless and true headed, native HLS `"maybe"`.
- `mcr.microsoft.com/playwright:v1.62.1-noble`, `npm i playwright@1.62.1`, **linux/arm64**, headless: H.264, AAC, AC-3, E-AC-3 and HEVC all false; native HLS `""`.
- The same image under `docker run --platform linux/amd64` (qemu), `npx playwright install chromium`, launch args `--no-sandbox --disable-gpu --no-zygote --single-process --disable-dev-shm-usage` (Chromium crashes under qemu without them): the headless shell and `channel: 'chromium'` both Chromium 151.0.7922.34, H.264 and AAC true, AC-3 false, native HLS `"maybe"`. (`channel: 'chrome'`, Chrome 154, the same.)

**B.2 hls.js against a relay-shaped server.** ffmpeg 9.0.1 cut a 300 s 640×360 25 fps H.264 High (`-g 50 -sc_threshold 0`) and 128 kb/s AAC test signal into fMP4 HLS renditions (`-hls_segment_type fmp4`, 2 s). A Node `http` server served: `/proxy/ts/stream/abc?output_format=hls` answering the § Playlists multivariant shape (two `EXT-X-MEDIA` audio groups `aac` and `ac3`, two `EXT-X-STREAM-INF` on one video playlist, `CODECS` `avc1.64001e,mp4a.40.2` and `avc1.64001e,ac-3`, every URI `/hls/<token>/…` with a well-formed 69-character token); media playlists as a 10-segment sliding live window advancing with the wall clock, `EXT-X-MAP` and segments relative; `DELETE /hls/<token>` → 204. hls.js 1.6.15's `dist/hls.min.js` (from `npm pack hls.js@1.6.15`) ran in Playwright's macOS Chromium 151 with this plan's config. Results: `MANIFEST_LOADED`'s `levels[].url` and `audioTracks[].url` were absolute `http://127.0.0.1:8765/hls/<token>/…` URLs; `MANIFEST_PARSED` kept one level, audio codec `mp4a.40.2` (the `ac-3` variant dropped); playback started; **paused for 30 s**, hls.js reloaded `video.m3u8` 15 times and `aac.m3u8` 15 times, at intervals of 1996-2003 ms, fetched 31 segments, and sent `Authorization` on every `/hls/` request; resumed 36 s behind the live edge; `hls.destroy()` then `fetch(sessionUrl, { method: 'DELETE', keepalive: true })` answered 204.

**B.3 A 403 from `/hls/`.** The same server, answering every `/hls/` GET with 403 `{"error": "invalid or expired media session"}` after 6 s. hls.js reported `networkError`/`levelLoadError`, `fatal: false`, `response.code` 403, `url` the video playlist; then `audioTrackLoadError`, non-fatal, 403; then `levelLoadError`, **`fatal: true`**, 403. Chromium also logged `Failed to load resource: the server responded with a status of 403 (Forbidden)` for each, which the E2E's page-error collector would count (why E1 and E2 never provoke one).

**B.4 The seed's vitest.** `git archive 4ed75d96 | tar -x`, `npm ci`, then `npx vitest --run` over `RecordingCardUtils.test.js`, `FloatingVideo.test.jsx`, `StreamsTable.test.jsx`, `StreamConnectionCard.test.jsx`, `ChannelsTable.test.jsx`, `ChannelTableStreams.test.jsx` and `FloatingVideoUtils.test.js`: 7 files, 300 tests, all passing. Then break-check 3's wrong edit at the seed (a `buildChannelHlsUrl` export added to `FloatingVideoUtils.js`, and `StreamsTable.jsx:954` calling it): `StreamsTable.test.jsx` failed 1 of 46 with `AssertionError: expected "vi.fn()" to be called at least once` and one unhandled `Error: [vitest] No "buildChannelHlsUrl" export is defined on the "../../../utils/components/FloatingVideoUtils.js" mock. Did you forget to return it from "vi.mock"?`. The scratch files were restored from `git show "4ed75d96:…"`.
