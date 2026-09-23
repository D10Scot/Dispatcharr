# Fix plan, category H — the E2E suite

**Category.** H, the E2E suite: the Playwright suite in `e2e/`, the fake provider in `e2e-upstream/`
and the harness script `scripts/e2e_up.sh`. Eleven tracker issues: #168, #261, #214, #209, #201,
#185, #187, #197, #179, #178, #86. Five of them (#261, #214, #209, #201, #185) were closed on
2026-09-23 as duplicate fix proposals for #168. #168 is planned once.

**Seed SHA.** `a54b09a9` (`main`, 2026-09-23, "metrics(curated): the Phase 2 phase-done milestone
row (#342)"). Every `file:line` below was opened at that SHA. Line numbers drift. Each task's first
step re-greps its anchor rather than trusting the number.

**Ordering position.** Eighth of ten (B, A, J, C, D, E, G, H, I, F). B-7 (`origin/docs/fixplan-B`,
PR #343) and category E's #72 fix both precede this plan and both matter to it; see § Overlap.

**Shape.** Five PRs, no decision memo (no rule-4 policy item falls in this category).

| PR | Branch | Closes | Size |
|---|---|---|---|
| H-1 | `fix/H-1-e2e-up-stack-scoping` | #168, #187 | M |
| H-2 | `fix/H-2-slow-playlist-fault` | #197 | M |
| H-3 | `fix/H-3-authorize-429-e2e` | #179 | S |
| H-4 | `fix/H-4-dvr-internal-principal-e2e` | #178 | S |
| H-5 | `fix/H-5-channel-profiles-flake` | #86 (after E's #72 fix) | S |

H-1 goes first on purpose. It is what makes a private parallel stack safe to tear down, and every
later PR's Playwright verification runs on one.

**Nothing in this plan is implemented.** The only file this branch commits is this document.

---

## Files this plan touches

| File | PRs | Issues |
|---|---|---|
| `scripts/e2e_up.sh` (lines 27–73, 120–128, 181–207 only) | H-1 | #168, #187 |
| `e2e/tests/guards/e2e-up-stacks.spec.ts` (new) | H-1 | #168, #187 |
| `e2e/tests/guards/e2e-up-stub.sh` (new, mode 100755) | H-1 | #168, #187 |
| `e2e/fixtures/instance.ts` (header comment `:10-27`, `down()` doc `:317`) | H-1 | #168 |
| `e2e-upstream/README.md` (`:20-24` container-lifecycle lines) | H-1 | #168 |
| `e2e-upstream/README.md` (`:4`, fault catalogue `:216-250`) | H-2 | #197 |
| `e2e/README.md` (`:20-50` lifecycle, `:63` guards row, `:155-180` destroy prose, new "Running a second stack" subsection) | H-1 | #168, #187 |
| `e2e/README.md` (none) | H-2..H-5 | — |
| `e2e/COVERAGE.md` (Guards table) | H-1 | #168, #187 |
| `e2e/COVERAGE.md` (Lifecycle bounded-restart row `:200`; fault-count sentences `:236`, `:379`) | H-2 | #197 |
| `e2e/COVERAGE.md` (one new Streaming row after `:197`) | H-3 | #179 |
| `e2e/COVERAGE.md` (one new DVR row) | H-4 | #178 |
| `e2e/COVERAGE.md` (Sources row `:191`) | H-5 | #86 |
| `e2e-upstream/src/faults.ts` | H-2 | #197 |
| `e2e-upstream/src/server.ts` (playlist route `:475-506` only) | H-2 | #197 |
| `e2e-upstream/test/faults.test.ts`, `e2e-upstream/test/server.test.ts` (new cases only) | H-2 | #197 |
| `e2e-upstream/CONTRACT.md`, `e2e-upstream/package.json`, `e2e-upstream/package-lock.json` | H-2 | #197 |
| `e2e/fixtures/upstream.ts` (`FaultName`, `FaultOptions`, `FaultResult` doc) | H-2 | #197 |
| `e2e/fixtures/index.ts` (fault doc comment `:318-341`) | H-2 | #197 |
| `e2e/tests/streaming-split/process-restart.spec.ts` (constants `:122-155`, Scenario B `:484-782`) | H-2 | #197 |
| `e2e/playwright.config.ts` (`streaming-split` comment `:194-215`) | H-2 | #197 |
| `e2e/playwright.config.ts` (`streaming-failover` comment `:103-146`) | H-3 | #179 |
| `e2e/tests/streaming-failover/stream-limit-429.spec.ts` (new) | H-3 | #179 |
| `e2e/tests/guards/allowlist.ts` (`GLOBAL_SETTINGS_WRITE` only) | H-3 | #179 |
| `e2e/tests/streaming/authorize-matrix.spec.ts` (comment `:327-334` only) | H-3 | #179 |
| `e2e/tests/dvr/recording-hidden-channel.spec.ts` (new) | H-4 | #178 |
| `CLAUDE.md` (§ Testing, "twelve injectable faults" only) | H-2 | #197 |

No PR touches `apps/`, `relay/`, `frontend/`, `docker/`, `metrics/` or any workflow. H-2 changes
one word of `CLAUDE.md`. No backend
test label covers any of these paths (`python3 scripts/ci_backend_test_labels.py scripts/e2e_up.sh
e2e/README.md e2e-upstream/src/server.ts` prints `[]`). CI coverage comes from `e2e-tests.yml`
(its change pattern includes `scripts/`, `e2e/` and `e2e-upstream/`, and `guards` is a superset of
it) and, for H-1 and H-2, `lifecycle-tests.yml` (its patterns name `scripts/e2e_up.sh` and
`e2e/fixtures/`). No branch touches `docker/`, `relay/httpapi/` or `docker/nginx.conf`, so every
branch is `fix/…`, never `migration/…`.

**No ledger edits.** None of the six live issues has a row in `metrics/curated/defects.yml` (checked:
no `issue: 168|187|197|179|178|86|72`). They are harness and coverage issues, not CLAUDE.md known
defects, and no PR here adds or flips a `test.fail()` pin. No parity-matrix row is touched.

## Overlap with other categories

| File | Other category and issue | What H does there | What the other plan is assumed to do | Order and collision risk |
|---|---|---|---|---|
| `scripts/e2e_up.sh` | **B-7** #182 (PR #343, Task 7.2) | H-1 edits the scoping variables (`:27-53`), `destroy()` (`:68-73`), `--stop` (`:120-128`) and the **provider** block (`:181-207`). H-1 does not touch the app-container `docker run` at `:250-261`. | B-7 resolves the network gateway with `docker network inspect "$NETWORK" -f '{{(index .IPAM.Config 0).Gateway}}'` before the **app** `docker run` at `:254`, fails loudly if empty, and adds `-e DISPATCHARR_TRUSTED_PROXIES="$GATEWAY"`. | B goes first. Hunks are disjoint. **One semantic join:** H-1's stub (`e2e-up-stub.sh`) answers B-7's gateway template **unconditionally** from Task 1.1, so H-1's start-path tests pass in either landing order and B-7 (past review at 123152ef, and gated on B's Q1) owes nothing. |
| `e2e/README.md`, `e2e/COVERAGE.md` | **B-7** #182 (X-Real-IP paragraphs, README `:355-363`, COVERAGE `:170`) | H edits the lifecycle section, the Projects table's `guards` row, a new subsection, and the rows named above. | B-7 rewrites the X-Real-IP prose. | Disjoint paragraphs. B first. |
| `CLAUDE.md` | **B-2** #84 (one sentence in § Known defects, Security) | H-2 changes one word in § Testing ("twelve injectable faults" → thirteen, `CLAUDE.md:160` at the seed). | B-2 edits the Xtream-passwords sentence. | Disjoint paragraphs. B first. None. |
| `e2e/tests/seeded/*` pins | **B-1, B-2** flip `test.fail()` pins in `vod-adult-streamable`, `xc-auth`, `network-acl` | H touches none of those files. | — | None. |
| `.github/workflows/e2e-tests.yml` | **G** (#16 Node 24 actions, owned by G) | **H edits no workflow.** The `guards` job already runs on any `scripts/` or `e2e/` change, which is what H-1's new spec needs. | G bumps action pins and runtimes. | None. |
| `apps/channels/signals.py:234-241`, `apps/channels/api_views.py:873-880` | **E** #72 | **H edits no product code.** H-5 is verification only, and it depends on E's fix. | E makes both `bulk_create` calls conflict-tolerant (the issue's suggested direction: `ignore_conflicts=True` on both). | E first, hard dependency. If E's plan rules #72 out of scope or memo-only, H-5 has no fix to verify and #86 needs re-planning; see Q1. |
| `apps/m3u/tasks.py` | **C-3** (#217, #262, #199 split `refresh_m3u_groups`), **E** #56 | None. H-2 relies only on `fetch_m3u_lines`' `timeout=(30, 60)` at `:207` and on one playlist fetch per refresh (`:1752`). | C and E restructure the refresh. | H-2's delay must stay below the read timeout. If C or E lowers that 60 s timeout, H-2's constant moves with it; the constant's comment carries the formula for this reason. |
| `docker/nginx.conf:696-700` | **G** #81, #180 | None. H-3 only exercises `@authorize_denied`'s 429 line. | G edits forwarded headers and templating. | None. If G's #180 templating rewrite moves the file inside the image, H-3's break-check path (`/etc/nginx/sites-enabled/default`) moves with it. |

---

## Global constraints

A conflict between a constraint and a task step is a **STOP and report**, never a judgement call.

1. **Anchor every command** with an absolute path or a leading `cd <your worktree> &&`.
2. **`set -o pipefail`** on any pipeline whose exit status or emptiness you read. Never
   `2>/dev/null` a git query you interpret. Brace `git show "${ref}:path"`.
3. **Stage and commit in separate Bash calls.** Write the message with the Write tool and commit
   with `git commit -F <file>`.
4. **The test-modification rule, verbatim from the brief.** A test may change only when the
   behaviour it pins is the thing being changed, and every such change is listed in the PR section
   with its before and after assertion. A test that deliberately pins a defect is flipped to pin the
   fix, and the plan shows the flipped test failing before the fix and passing after. Never widen a
   tolerance, lower a count or delete an assertion to make a run green. New behaviour gets a new
   test named after the defect.
5. **A break-check is not optional.** Each task that adds a test names a deliberate wrong edit. Apply
   it, run the one test, **record the failure message and confirm it names the mechanism** (not a
   side effect of the edit), then revert.
6. **Never run `scripts/e2e_up.sh` in any mode against the default stack names** while another agent
   may be using them. Every Playwright verification in H-2..H-5 runs on a private stack with the
   **complete** override set:

   ```bash
   export DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-h<n> \
          DISPATCHARR_E2E_VOLUME=dispatcharr-e2e-h<n>-data \
          DISPATCHARR_E2E_NETWORK=dispatcharr-e2e-h<n>-net \
          DISPATCHARR_E2E_PORT=<free port, e.g. 39<n>91> \
          DISPATCHARR_E2E_IMAGE=dispatcharr-e2e-h<n>:local
   export E2E_BASE_URL=http://localhost:$DISPATCHARR_E2E_PORT
   ```

   H-2 changes the provider, so it **also** uses a private provider, with its own image tag so the
   rebuild does not retag the shared `dispatcharr-e2e-upstream:local`:

   ```bash
   export DISPATCHARR_E2E_UPSTREAM_CONTAINER=e2e-upstream-h2 DISPATCHARR_E2E_UPSTREAM_PORT=9412 \
          DISPATCHARR_E2E_UPSTREAM_IMAGE=dispatcharr-e2e-upstream-h2:local
   export E2E_UPSTREAM_CONTROL_URL=http://127.0.0.1:9412 E2E_UPSTREAM_INTERNAL_URL=http://e2e-upstream-h2:8080
   ```

   A private provider only works once H-1 has taught the script to tell the provider its own name
   (Task 1.2). Before H-1 merges, H-2 rebases onto H-1's branch or recreates its provider by hand
   with `-e UPSTREAM_INTERNAL_ORIGIN=http://e2e-upstream-h2:8080` (the #168 comment's workaround).
   Tear the private stack down with `--down` using the same exports, after H-1 has merged. Before
   that, tear it down by hand (`docker rm -f`, `docker volume rm`, `docker network rm` on the h<n>
   names only), because `--down` before H-1 removes the shared provider.
7. **Occupancy check before writing into any worktree** (CLAUDE.md): `docker ps --filter
   name=dispatcharr-e2e-h<n>` and `stat -f '%Sm %N'` on the files you are about to edit.
8. **The e2e typecheck hook runs on every `e2e/**/*.ts` and `e2e-upstream/**/*.ts` edit.** It is
   blocking. Keep it green; it is the only automated check those trees have locally.
9. **Every new test carries `@contract` or `@characterization`** (ADR 0002), enforced by
   `e2e/tests/guards/tags.spec.ts`. A `@characterization` test carries a comment naming the
   implementation fact it pins.

---

## Per-issue analysis

### #168 — `--down`/`--reset` remove the shared provider, even for an overridden stack

- **Root cause.** The provider is shared by default: `UPSTREAM_NAME` is `e2e-upstream` whatever
  `DISPATCHARR_E2E_CONTAINER`/`_VOLUME`/`_NETWORK` say (`scripts/e2e_up.sh:51`), and the start path
  attaches it to every stack's network (`ensure_on_network`, `:60-66`, called at `:207`). Three
  sites then treat it as if it belonged to the invoking stack alone:
  1. `destroy()` (`:68-73`) runs `docker rm -f "$UPSTREAM_NAME"` unconditionally at `:70`. Both
     `--reset` (`:88-91`) and `--down` (`:129-134`) call it.
  2. `--stop` (`:120-128`) runs `docker stop "$UPSTREAM_NAME"` unconditionally at `:123`. This is
     the half #187 actually hit: `Instance.restart()` (`e2e/fixtures/instance.ts:283-286`) is
     `--stop` then start.
  3. **Found by this plan, not in the issue.** The start path recreates the provider when its image
     id moved (`:190-195`) and the replacement is `docker run --network "$NETWORK"` (`:202-205`),
     attached to the invoking stack's network only. Every sibling stack loses container-name DNS
     to the provider, the same failure as (1), whenever a worktree whose `e2e-upstream/src/`
     differs runs the script. Its scenarios are also lost, which is unavoidable (the registry is an
     in-memory `Map`) but should be said out loud.

  **The #168 comment adds a fourth, related gap.** A *renamed* provider
  (`DISPATCHARR_E2E_UPSTREAM_CONTAINER=e2e-upstream-pr6`) is started without being told its name
  (`:202-205` passes no `-e`), so it advertises its default `UPSTREAM_INTERNAL_ORIGIN`
  (`e2e-upstream/src/server.ts:191-192`, `http://e2e-upstream:8080`) in every playlist, and every
  seeded channel points at a host the private stack cannot resolve. The script's own comment
  (`:44-50`) and `e2e/README.md:43-50` call the override "not safe to change" and blame the
  fixture. That is stale: `e2e/fixtures/upstream.ts:4-8` reads `E2E_UPSTREAM_CONTROL_URL` and
  `E2E_UPSTREAM_INTERNAL_URL`, the provider derives `control` from the request's `Host` header
  (`server.ts:183-189`), and `stream-client.ts:46`'s DNS check is `url.includes('e2e-upstream')`,
  which a suffixed name still matches. The one missing piece is the provider's own origin.
- **Fix.** One helper lists a container's networks with a Go template over the map keys (verified
  on Docker 29.8 by this plan: one name per line plus a trailing blank line; a *stopped* container
  still lists its attachments; a missing container exits 1 with `no such object`). The provider is
  "in use elsewhere" when it is attached to any network other than `$NETWORK`, `bridge`, `host` or
  `none`. `destroy()` then disconnects it from `$NETWORK` and leaves it running when it is in use
  elsewhere, and removes it otherwise. `--stop` leaves it running when it is in use elsewhere. The
  image-moved recreation records the networks first and reconnects each surviving one after
  `docker run`, printing a warning that sibling stacks lost their scenarios. The provider's
  `docker run` gains `-e UPSTREAM_INTERNAL_ORIGIN="http://${UPSTREAM_NAME}:8080"`. `ensure_on_network`
  switches to the same helper, so one parser serves every site. Appendix A has the hunks.
- **Single-stack behaviour is unchanged**, which is what CI and every lifecycle spec depend on: a
  provider attached only to the invoking stack's network is removed by `--down`/`--reset` and
  stopped by `--stop` exactly as today. `e2e/tests/lifecycle/backup-restore.spec.ts:127-128` and
  `e2e/playwright.config.ts:385-387` rely on that and need no change.
- **Tests.** New `e2e/tests/guards/e2e-up-stacks.spec.ts`, driving the real script against a stub
  `docker` (Appendix B), plus a real-Docker check on throwaway containers (Task 1.4). No existing
  test changes.
- **Size** M. **Upstreamable** no (the E2E harness is this fork's). **Duplicates** #261, #214,
  #209, #201, #185, all closed 2026-09-23 → #168 survives. #261's body is the best of the five: its
  review caught that a line grep over `{{json .NetworkSettings.Networks}}` false-positives on real
  output, which is why this plan uses the range template. Its proposed Python test under `tests/`
  is not adopted: `scripts/e2e_up.sh` routes to no backend label, so it would need a new
  `_PATH_ALIASES` entry (a `dispatcharr/` edit that forces the full backend run) to ever run on a
  script change. The `guards` project already runs on every `scripts/` change, needs no container,
  and exempts `tests/guards/` from the capability scan (`capabilities.spec.ts`, `usersOf`:
  `if (rel.startsWith('tests/guards/')) continue;`).

### #187 — a partially scoped invocation falls back to the shared stack

- **Root cause.** Every scoping variable is defaulted independently (`scripts/e2e_up.sh:27`, `:28`,
  `:37`, `:43`, `:51`, `:53`). Nothing checks that a set of them was overridden together, so
  `DISPATCHARR_E2E_CONTAINER=dispatcharr-e2e-pr6` alone yields a private app container on the shared
  **network**, the shared **volume** and the shared **provider**. The `lifecycle` fixture passes the
  whole process environment through (`e2e/fixtures/instance.ts:221-228`), so a half-exported shell
  reaches the script unchanged.
- **Fix.** Fail closed before the mode `case` (so every mode, `--stop` and `--down` included, is
  covered), exit 2, and name the missing variables. Two groups:
  - **The stack's names**: `_CONTAINER`, `_VOLUME`, `_NETWORK`. If any is set non-empty, all three
    and `_PORT` must be. `_PORT` alone stays legal, since it selects no shared resource and the README
    documents it as an independent override.
  - **The provider's**: `_UPSTREAM_CONTAINER` and `_UPSTREAM_PORT`, both or neither. Leaving both
    unset is legal, because after #168's fix sharing the provider is safe.
  - **One cross-check against the Playwright-side variables**, only when they are set: the host of
    `E2E_UPSTREAM_INTERNAL_URL` must equal `$UPSTREAM_NAME`, and the port of
    `E2E_UPSTREAM_CONTROL_URL` must equal `$UPSTREAM_PORT`. That is #187's incident exactly
    (Playwright pointed at `e2e-upstream-pr6`, the script defaulted to `e2e-upstream`), and a
    mismatch is a guaranteed-broken run whose symptom ("stream ended after 188 bytes") names
    nothing.
  - **bash 3.2 trap.** `/bin/bash` on macOS is 3.2.57 (checked), and `set -u` makes an empty
    `"${arr[@]}"` an unbound-variable error before bash 4.4. Build the missing-variable list as a
    string, not an array. `${!v}` indirection is fine in 3.2.
  The alternative the issue offers, one `DISPATCHARR_E2E_STACK=<suffix>` from which every name
  derives, is not taken: three fixtures read `DISPATCHARR_E2E_CONTAINER` directly
  (`instance.ts:60-61`, `greybox/redis.ts:65`, `nginx-stream-buffering.spec.ts:10`,
  `output-profile-sharing.spec.ts:11`), so it would be a wider change for the same safety.
- **Tests.** In the same new guards spec (Appendix B). No existing test changes. CI sets none of
  these variables (`e2e-tests.yml:287-288` sets only `_READY_ATTEMPTS` and `_SKIP_UPSTREAM_BUILD`),
  so CI behaviour is unchanged.
- **Size** S on top of H-1. **Upstreamable** no. **Duplicates** none; related to #168, not a
  duplicate.

### #197 — hold a refresh in flight with a slow-playlist fault instead of thirty decoys

- **Root cause.** Scenario B (`e2e/tests/streaming-split/process-restart.spec.ts:484-782`) needs an
  M3U refresh still in flight when `supervisorctl restart relay-uwsgi` returns. It gets one by
  contention: `SLOW_REFRESH_DECOY_COUNT = 30` (`:155`) inactive accounts against an 8,000-channel
  catalogue (`:154`, `:510-517`), activated (`:649-651`) and triggered in the same `Promise.all` as
  the tracked account (`:660-669`). The provider cannot slow a playlist: its playlist route
  (`e2e-upstream/src/server.ts:475-506`) consults only `not-found` (`:485`) and `auth-failure`
  (`:490`), and both make the refresh fail.
- **Fix.** A thirteenth fault, `slow-playlist`, scenario-wide only, with a required `delayMs` when
  arming (integer, 1..120,000). Armed, the playlist route waits `delayMs` after its credential check
  and then serves the normal 200. Scenario B arms it on a small catalogue after the account's
  create-time refresh has settled, triggers one refresh, and keeps both of its behaviour assertions
  (in flight at restart return, `success:bumped` afterwards) unchanged. Appendices C and D.
- **The delay, as a formula**, carried in the constant's comment (memory: derived thresholds go
  stale): `SLOW_PLAYLIST_DELAY_MS = 30_000`, which must satisfy
  `restart measured (6.9 s, COVERAGE.md:200) × ≥3 < delay < fetch_m3u_lines read timeout (60 s,
  apps/m3u/tasks.py:207)`. A refresh fetches the playlist once (`tasks.py:1752`), so the delay is
  paid once. The headers are withheld for the delay, so `requests`' read timeout is what bounds it.
- **Contract bump.** A new fault is a **minor** bump under `e2e-upstream/CONTRACT.md` § Bump policy
  (`:221-223`): `1.1.0 → 1.2.0` in `CONTRACT.md` and `package.json`, kept equal by
  `e2e/tests/guards/upstream-contract.spec.ts`. `package-lock.json` still says `1.0.0` at `:3` and
  `:9`, a pre-existing drift the guard does not read. Regenerate it with
  `npm install --package-lock-only` in the same PR.
- **Tests.** New provider unit and route tests. Scenario B's setup changes under rule 4 because the
  way it holds the refresh is what #197 changes; its two behaviour assertions do not. The table is
  in H-2.
- **Size** M. **Upstreamable** no. **Duplicates** none.

### #179 — no E2E test drives a 429 through `@authorize_denied`

- **Root cause.** A coverage gap, not a product defect. `docker/nginx.conf:696-700` restores 404
  and 429 from `$authorize_status`. `e2e/tests/streaming/authorize-matrix.spec.ts:323-343` and
  `:345-362` exercise the 404 line, and their comment (`:327-334`) says the 404 row is the only one
  that exercises the restoration. `nginx-stream-buffering.spec.ts:405` pins the 429 line's text
  statically; nothing proves it behaviourally. The 429 is reachable only when
  `check_user_stream_limits` (`apps/proxy/utils.py:347-412`) returns `False`. That happens in
  `authorize_stream`'s live branch (`apps/proxy/authorize.py:475-481`) when a user with
  `stream_limit > 0` is at the limit and `user_limit_settings.terminate_on_limit_exceeded` is
  `false` (`utils.py:400-402`). The default is `true` (`core/models.py:776-782`), which terminates
  the oldest stream instead. So the test needs an instance-wide `CoreSettings` write.
- **Fix.** A new `@contract` spec in the single-worker `streaming-failover` project, which already
  hosts two allowlisted global writes. An XC user with `stream_limit: 1` holds one live stream on
  the XC live root, and a second tune on another channel must answer exactly **429**. A control
  closes the first stream and polls the second tune to success, so the 429 is shown to be the
  limit and not a broken channel. The live branch of `get_user_active_connections` reads the Go
  relay's client registry, which records the user (`relay/httpapi/stream.go:430`,
  `relay/httpapi/channels.go:59`), so the first stream is counted. Appendix E.
- **Global write, argued as ADR 0003 requires.** Group `user_limit_settings` (seeded by
  `core/migrations/022_default_user_limit_settings.py`, so PATCH works), key
  `terminate_on_limit_exceeded` only, merged into a spread copy of the row's `value`. Nothing else
  reads it in a way that matters: it bites only a user with `stream_limit > 0` at the limit, and the
  only other such user in the suite (`e2e/tests/seeded/xc-auth.spec.ts:31`, `stream_limit: 3`)
  never streams. Restored in `test.afterEach` from the value captured before the PATCH (the
  `dvr/comskip.spec.ts` shape, because a timed-out test skips a `finally`). `CoreSettings._get_group`
  invalidates on `post_save` (`core/models.py:378-415`), so no settling sleep. An up-front guard
  fails the test if the row is already `false` (a previous run died mid-write), the
  `catchup-redirect.spec.ts:79-84` shape.
- **Size** S. **Upstreamable** no. **Duplicates** none.

### #178 — no DVR E2E test records a `hidden_from_output` channel

- **Root cause.** A coverage gap. `_dvr_build_ffmpeg_cmd` (`apps/channels/tasks.py:1203-1248`) adds
  `-headers "X-Dispatcharr-Internal: <token>\r\n"` at `:1228-1234`, from `internal_principal_token()`
  at `:1785`. In AIO, `get_dvr_stream_base_url()` (`:1359-1395`) routes the recording through nginx
  on `DISPATCHARR_PORT`, so it meets the authorize hop. Every `dvr` spec records an ordinary
  channel, which an anonymous request may stream, so all of them pass if the header were dropped.
  `grep -rn hidden_from_output e2e/tests/dvr/` is empty.
- **Fix.** A new `@contract` spec in the `dvr` project: seed a `hidden_from_output` channel, prove
  the premise (an anonymous tune of its UUID is refused with exactly 403), schedule a 30 s recording,
  and assert bytes land: the provider shows one live connection, status reaches `completed`, and
  the file endpoint serves bytes starting with `MKV_MAGIC`. It follows
  `recording-execution.spec.ts`'s flagship and cleanup shape. Appendix F.
- **Size** S. **Upstreamable** no. **Duplicates** none.

### #86 — `channel-profiles.spec.ts` bulk-update flakes under four workers

- **Root cause (hypothesis, strong; confirmed only by H-5's measurement).** #72's race, with a
  specific loser. `ATOMIC_REQUESTS = False` (`dispatcharr/settings.py:148`), so
  `ChannelProfileViewSet.create` commits the profile row by autocommit before the `post_save`
  receiver runs. The receiver (`apps/channels/signals.py:234-240`) then reads `Channel.objects.all()`
  and `bulk_create`s one membership per channel, with no `ignore_conflicts`. Meanwhile another
  worker's `ChannelViewSet.create` (`apps/channels/api_views.py:853-880`), inside
  `transaction.atomic()`, inserts channel C, reads `ChannelProfile.objects.all()`, and inserts
  (P, C) for every profile, the new P included once P's insert has committed. The interleaving that
  fails is: P commits; the channel request reads profiles, inserts (P, C) and commits; the receiver
  then reads channels, sees C, and inserts (P, C) again. The **profile** request raises
  `IntegrityError` and answers 500. The channel request cannot be the loser, because its (P, C) insert
  precedes its own commit and the receiver cannot see C before that commit. `seed.channelProfile()`
  throws on the 500, and a retry passes. Every test in `channel-profiles.spec.ts` creates profiles
  while three other `seeded` workers create channels, so the reported test is the likeliest victim,
  not the only possible one. The reporter's auto-channel-sync half was retracted in their own
  comment (a channel-number window exhausted on a long-lived container), and this plan agrees.
- **Fix.** None in H. Category E's #72 fix makes both `bulk_create`s conflict-tolerant, and that
  removes the 500. H-5 measures the mechanism before E's fix (the server-side signature is an
  `IntegrityError` on `dispatcharr_channels_channelprofilemembership`'s unique constraint in the
  container log, visible even when Playwright's retry absorbs the failure), then re-measures after
  it, and closes #86 with the evidence.
- **Tests.** None added or changed. A deterministic reproduction from outside the container is out
  of reach, and the row at `e2e/COVERAGE.md:191` records why provoking #72 on a shared instance is
  refused (D18). E's backend test is the regression guard.
- **Size** S. **Upstreamable** n/a (verification only). **Duplicates** none; #72 is its cause, not a
  duplicate.

---

## PR H-1 — `e2e_up.sh`: a stack tears down only what is its own, and refuses half a scope

- **Branch** `fix/H-1-e2e-up-stack-scoping`
- **Closes** #168, #187.
- **Files** `scripts/e2e_up.sh`, `e2e/tests/guards/e2e-up-stacks.spec.ts` (new),
  `e2e/tests/guards/e2e-up-stub.sh` (new), `e2e/fixtures/instance.ts` (comments),
  `e2e/README.md`, `e2e-upstream/README.md` (`:20-24`), `e2e/COVERAGE.md` (Guards table).
- **Test labels** none on the backend. CI: `e2e-tests.yml` (`guards`, and the matrix because
  `scripts/` changed) and `lifecycle-tests.yml`. Local: `cd e2e && npx playwright test
  --project=guards` (no container, about a second).
- **Upstreamable** no.

### Task 1.1 — the stub and the spec, red first

1. Write `e2e/tests/guards/e2e-up-stub.sh` from Appendix B's sketch: a **stateful** stand-in for
   `docker` (and, with `STUB_AS=curl`, for `curl`) keeping containers, networks, volumes and images
   as files under `$STUB_STATE`, appending every argv to `$STUB_STATE/log`, and answering any
   invocation it does not recognise by appending `UNHANDLED <argv>` to the log and exiting 97.
   `git update-index --chmod=+x` it. It answers B-7's gateway lookup from the start, whether or not
   B-7 has landed (§ Overlap).
2. Write `e2e/tests/guards/e2e-up-stacks.spec.ts` (Appendix B). Every test runs
   `bash <REPO_ROOT>/scripts/e2e_up.sh <mode>` with `spawnSync`, `PATH=<tmpdir>:$PATH`, where
   `<tmpdir>` holds two two-line wrappers, `docker` and `curl`, that `exec` the stub. **Safety
   precheck in `test.beforeEach`**: `bash -c 'command -v docker'` under the same environment must
   print the wrapper's path, or the test throws before the script runs. Every test also uses
   throwaway names (`h1g-<random>-…`) for every scoping variable except in the #187 cases that
   deliberately leave some unset. So a broken `PATH` can never reach a real stack, and the #187
   cases cannot reach the real daemon because the precheck ran first.
3. Tag every test `@characterization`, with the header comment ADR 0002 requires: it pins the local
   harness script's container choreography, which no client observes and which a rewrite of the
   harness may change.
4. Tests (names are the hazard map):
   - `--down of a second stack leaves a provider another stack is attached to running (#168)`:
     provider on netA and netB; `--down` with `NETWORK=netB` → provider exists, its networks are
     exactly `[netA]`, netB is gone, and the log has no `rm -f <provider>`.
   - `--down of the only stack on a provider still removes it`: the control that pins today's
     single-stack (and CI) behaviour.
   - `--stop of a second stack leaves a shared provider running (#187's incident)` and
     `--stop of the only stack on a provider still stops it`.
   - `a provider recreated because its image moved is reattached to every stack it served (#168)`:
     provider on netA and netB with image id `old`; the upstream image now resolves to `new`;
     start with `NETWORK=netB` → the provider's networks are `{netA, netB}` and stdout warns that the
     sibling stacks lost their scenarios.
   - `a renamed provider is told its own name as its internal origin (#168 comment)`: start with
     `UPSTREAM_CONTAINER=h1g-…-up` → the logged provider `run` carries
     `-e UPSTREAM_INTERNAL_ORIGIN=http://h1g-…-up:8080`.
   - `a partially scoped invocation refuses before touching docker (#187)`: for each of `_CONTAINER`,
     `_VOLUME`, `_NETWORK` set alone, and for each mode in `['', '--stop', '--down', '--reset', '--recreate']`:
     exit 2, stderr names every missing variable, and the stub log is empty.
   - `an upstream override without its port refuses (#187)` and the converse.
   - `a Playwright upstream URL that names another provider refuses (#187)`:
     `E2E_UPSTREAM_INTERNAL_URL=http://e2e-upstream-pr6:8080` with `UPSTREAM_CONTAINER` unset → exit 2,
     stderr names both hosts.
   - `a fully scoped stack with the shared provider is accepted`: the memory note's four-variable
     pattern (`_CONTAINER`, `_VOLUME`, `_PORT`, `_NETWORK`) passes the check.
5. Run the spec against the **unfixed** script. Expected: the #168, #187 and origin tests fail, and
   the two single-stack controls pass. Record the failure lines in the PR.

### Task 1.2 — the fix (Appendix A)

1. Add `container_networks` and `upstream_other_networks`. **Do not pipe into `grep -q`** under
   `set -o pipefail`: `grep -q` exits on its first match, the writer can take SIGPIPE, and the
   pipeline then reports 141, so a *found* network reads as a failure. Capture into a variable with
   `|| true` and test `[[ -n … ]]`, as the appendix does.
2. Rewrite `destroy()`, the `--stop` branch, the image-moved recreation and `ensure_on_network`.
3. Add `-e UPSTREAM_INTERNAL_ORIGIN="http://${UPSTREAM_NAME}:8080"` to the provider's `docker run`.
   A provider created before this change keeps its old environment until it is recreated. Say so in
   the comment, and in the README's new subsection.
4. Add `check_scope` before the `case` and call it unconditionally. Build lists as strings (bash
   3.2, see #187 above). Run the spec under `/bin/bash` too:
   `PATH=/bin:$PATH` is not enough, because the spec calls `bash` by name. Add one test-local
   variant that spawns `/bin/bash` explicitly for the partial-scope case, **only** when `/bin/bash`
   exists and reports 3.x. It skips elsewhere (CI's ubuntu has bash 5), with the reason in
   `test.skip`'s message.
5. Replace the stale comment at `:44-50` with what is now true (Appendix A).

### Task 1.3 — B-7's gateway template

The stub already answers B-7's `network inspect <N> -f '{{(index .IPAM.Config 0).Gateway}}'` with a
fixed `172.30.0.1` for any network it knows (Task 1.1, Appendix B). An extra answered shape harms
nothing, and the `UNHANDLED` catch-all still guards every other shape. So there is nothing to add
here: `git log --oneline origin/main -- scripts/e2e_up.sh` (with `set -o pipefail`, stderr kept); if
B-7 has merged, rebase and confirm the start-path tests still pass.

### Task 1.4 — the same claims against real Docker

The stub encodes the implementer's belief about Docker's output, and a stub is exactly what hid
#261's first bug. So repeat the three #168 claims on throwaway containers, with `alpine:3` as the
"provider". Every name carries the prefix `h1r-`, and nothing touches `e2e-upstream` or
`dispatcharr-e2e*`:

```bash
cd <worktree> && set -o pipefail
docker network create h1r-a && docker network create h1r-b
docker run -d --name h1r-up --network h1r-a alpine:3 sleep 900
docker network connect h1r-b h1r-up
env DISPATCHARR_E2E_CONTAINER=h1r-app-b DISPATCHARR_E2E_VOLUME=h1r-vol-b \
    DISPATCHARR_E2E_NETWORK=h1r-b DISPATCHARR_E2E_PORT=59991 \
    DISPATCHARR_E2E_UPSTREAM_CONTAINER=h1r-up DISPATCHARR_E2E_UPSTREAM_PORT=59992 \
    bash scripts/e2e_up.sh --down
docker inspect -f '{{.State.Running}} {{range $n, $_ := .NetworkSettings.Networks}}{{$n}} {{end}}' h1r-up
#   expect: "true h1r-a"
env … DISPATCHARR_E2E_NETWORK=h1r-a … bash scripts/e2e_up.sh --stop      # expect h1r-up stopped
docker start h1r-up
env … DISPATCHARR_E2E_NETWORK=h1r-a … bash scripts/e2e_up.sh --down      # expect h1r-up gone
docker ps -a --filter name=h1r- --format '{{.Names}}'; docker network ls --filter name=h1r- --format '{{.Name}}'
#   expect: both empty. If not, remove the h1r- leftovers by name.
```

Record the output in the PR. A mismatch between this and the stub is a stub bug; fix the stub and
rerun Task 1.1's red run.

### Task 1.5 — break-checks

Each on the fixed tree, one at a time, then reverted:

| Wrong edit | Must redden | Message must name |
|---|---|---|
| `destroy()` back to an unconditional `docker rm -f "$UPSTREAM_NAME"` | the `--down` second-stack test only | the provider being absent afterwards |
| `--stop` back to an unconditional `docker stop` | the `--stop` second-stack test only | the provider not running |
| Drop the reconnect loop in the image-moved branch | the recreate test only | netA missing from the provider's networks |
| Drop the `-e UPSTREAM_INTERNAL_ORIGIN` line | the renamed-provider test only | the missing `-e` |
| Delete the `check_scope` call | every partial-scope case, all five modes (`''`, `--stop`, `--down`, `--reset`, `--recreate`) | exit 0 (not 2) and a non-empty stub log |
| Swap `container_networks` for the old `{{json …}} \| grep` | the #168 tests | the stub's `UNHANDLED` line (the stub answers only the range template) |

The last row proves the spec cannot pass on the parser #261's review rejected. Task 1.4 proves the
range template is what real Docker answers.

### Task 1.6 — docs

1. `e2e/README.md`:
   - `:34-50`: `_UPSTREAM_CONTAINER`/`_PORT` are safe to change **when paired with**
     `E2E_UPSTREAM_CONTROL_URL`/`E2E_UPSTREAM_INTERNAL_URL`. Link the new subsection.
   - Container-lifecycle table (`:26-32`): `--reset`, `--down` and `--stop` act on the provider only
     when no other stack's network is attached to it.
   - `:155-162` and `:175-178`: `destroy()` removes the provider and network *of this stack*. A
     shared provider is disconnected and left running.
   - New subsection **"Running a second stack"** after the lifecycle table: the four stack
     variables (all or none, enforced), the two provider modes (shared, the default and now safe to
     tear down beside; or private: both provider variables plus both Playwright URLs and a private
     `DISPATCHARR_E2E_UPSTREAM_IMAGE` tag), and when to choose private: when your worktree changes
     `e2e-upstream/`, because every start rebuilds the provider from *your* tree and recreates the
     shared one when its image id moves, which drops every sibling stack's scenarios.
   - Projects table, `guards` row (`:63`): add "plus one behavioural check of `scripts/e2e_up.sh`
     against a stub `docker`", and change "runs in about a second" to "runs in a few seconds" (H-1
     adds some twenty spawns of the real script).
2. `e2e-upstream/README.md:20-24`: the same one-sentence correction for `--stop`/`--reset`/`--down`.
3. `e2e/fixtures/instance.ts:10-27` and the `down()` doc at `:317`: `destroy()` removes the network
   and the provider **when this stack is the provider's last**. Comments only.
4. `e2e/COVERAGE.md` Guards table: one row for `e2e-up-stacks.spec.ts`, with Task 1.5's mutations
   as its "Proved by" column, in the table's existing style.

**Test changes under the rule.** None. Every test in this PR is new.

### PR description draft

> **fix(e2e): `e2e_up.sh` tears down only what is its own, and refuses half a scope**
>
> Closes #168 and #187. #261, #214, #209, #201 and #185 were earlier fix proposals for #168 and
> are already closed.
>
> **#168.** The fake provider is shared by default, but `--down`/`--reset` removed it and `--stop`
> stopped it whichever stack asked. A provider recreated because its image moved came back attached
> to the invoking stack's network only. All three now check whether another stack's network is
> attached to the provider. If one is, the provider is disconnected from this stack (or left
> running for `--stop`), and a recreated provider is reconnected to every network it served. A
> renamed provider is now told its own name as `UPSTREAM_INTERNAL_ORIGIN`, so a private provider
> works with no hand-made container.
>
> **#187.** Setting some of `DISPATCHARR_E2E_CONTAINER`/`_VOLUME`/`_NETWORK` without the rest, or
> one provider variable without the other, or a Playwright upstream URL that names a different
> provider, now exits 2 before any `docker` call and names what is missing.
>
> A single stack behaves exactly as before, which is what CI and every lifecycle spec depend on.
> The new guards spec drives the real script against a stub `docker`. The same claims were checked
> against real Docker on throwaway containers (output below).
>
> The lead's memory note `e2e-parallel-stacks` ("never let a subagent run `e2e_up.sh` while a
> sibling runs") can be relaxed once this merges.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR H-2 — a slow-playlist fault, and Scenario B without decoys

- **Branch** `fix/H-2-slow-playlist-fault`
- **Closes** #197.
- **Files** `e2e-upstream/src/faults.ts`, `e2e-upstream/src/server.ts`,
  `e2e-upstream/test/faults.test.ts`, `e2e-upstream/test/server.test.ts`,
  `e2e-upstream/CONTRACT.md`, `e2e-upstream/README.md`, `e2e-upstream/package.json`,
  `e2e-upstream/package-lock.json`, `e2e/fixtures/upstream.ts`, `e2e/fixtures/index.ts`,
  `e2e/tests/streaming-split/process-restart.spec.ts`, `e2e/playwright.config.ts`,
  `e2e/COVERAGE.md` (`:200`, `:236`, `:379`), `CLAUDE.md` (one word).
- **Test labels** none on the backend. `cd e2e-upstream && npm ci && npm test` (vitest), `cd e2e &&
  npm run typecheck && npx playwright test --project=guards`, and one `streaming-split` run on a
  private stack with a private provider (Global constraint 6).
- **Depends on** H-1 (a private provider needs Task 1.2's origin line). Rebase onto H-1 until it
  merges.
- **Upstreamable** no.

### Task 2.1 — the fault (Appendix C), red first

1. Add the provider tests first, in `faults.test.ts`'s `parseFaultRequest` block and `server.test.ts`'s
   `'faults on the stream, playlist and EPG routes'` block (`:383`):
   - `slow-playlist requires delayMs when arming, and not when clearing`
   - `slow-playlist rejects a delayMs that is not an integer between 1 and 120000`
   - `slow-playlist rejects a channel, since a playlist has none`
   - `delayMs is rejected on every other fault`
   - `slow-playlist reports appliedTo 0: it can only affect the next request`
   - `an armed slow-playlist withholds the playlist for delayMs, then serves it unchanged`: arm with
     `delayMs: 400`, time the fetch, assert elapsed `>= 400` and the body byte-equal to an unarmed
     fetch of the same scenario.
   - `a cleared slow-playlist serves the playlist promptly`: elapsed `< 400`.
   - `slow-playlist leaves the EPG and stream routes alone`.
2. Run `npm test`: the new cases fail (unknown fault name). Record.
3. Implement per Appendix C. `npm test` green.
4. **Break-check.** Delete the `await delay(…)` line in the playlist route. Only the "withholds"
   test reddens, with an elapsed time under 400. Revert.
5. Update every count: `faults.ts` class comment (`:212-218`, "Nine of the twelve"), `FaultResult`'s
   doc in `e2e/fixtures/upstream.ts` (`:64-76`), `e2e/fixtures/index.ts:318-326`,
   `e2e-upstream/README.md:4` and `:219`, `e2e/COVERAGE.md:236` and `:379` (both "drive any of the
   twelve faults"; historical unblock notes, so make them count-free: "drive any fault in the
   catalogue"), `CLAUDE.md` § Testing ("a fake provider image with twelve
   injectable faults" → thirteen), and `CONTRACT.md` (`:42-45` "all twelve faults",
   `:153-161` "nine of the twelve"). `slow-playlist` joins the next-request group. Add its row to the
   README's fault table and a scoping sentence beside `range-unsupported`'s (`:246`).
6. `CONTRACT.md`: version `1.2.0`, a new paragraph in § Bump policy recording the minor bump and why
   (a new fault), and one sentence in § Known consumers naming
   `e2e/tests/streaming-split/process-restart.spec.ts` as the fault's only consumer.
   `package.json` `1.2.0`. `npm install --package-lock-only` so the lockfile's `:3`/`:9` read `1.2.0`
   (they read `1.0.0` today). `npx playwright test --project=guards` green.

### Task 2.2 — Scenario B (Appendix D)

1. Delete `SLOW_REFRESH_CHANNEL_COUNT`, `SLOW_REFRESH_DECOY_COUNT` and their comment
   (`process-restart.spec.ts:122-155`). Add `SLOW_PLAYLIST_DELAY_MS = 30_000` with the formula from
   § #197 in its comment.
2. In the test: the slow scenario becomes a two-channel catalogue. Delete the decoy seeding
   (`:518-539`), the activation (`:642-651`) and the batched trigger (`:653-669`). After
   `seed.upstreamM3UAccount(slowScenario)` has settled and `before` is read, arm
   `upstream.fault(slowScenario, 'slow-playlist', { delayMs: SLOW_PLAYLIST_DELAY_MS })`, then trigger
   the one refresh and assert `202`.
3. Rewrite the in-flight comment at `:690-705`: the fix for "this fires reliably" is now a larger
   `SLOW_PLAYLIST_DELAY_MS` within its formula, never a loosened assertion.
4. `e2e/playwright.config.ts:194-215`: the budget comment stops counting decoy settling. **Keep
   `timeout: 600_000`.** Lowering it is not needed and the brief forbids tuning a budget to a green
   run.
5. `e2e/COVERAGE.md:200`: append "held in flight by the provider's `slow-playlist` fault (contract
   1.2.0), not by queue contention".

**Test changes under the rule.** The behaviour Scenario B pins (a refresh dispatched before the
relay-uwsgi restart, provably still in flight when the restart returns, completes afterwards) is
unchanged, and so are the two assertions that pin it. What changes is the mechanism that holds the
refresh in flight, which is #197's subject.

| Test | Before | After |
|---|---|---|
| `process-restart.spec.ts` `'both relay processes restart bounded, and a Celery task queued across the uWSGI one still finishes'`: setup | 8,000-channel catalogue; 30 inactive decoys; decoys activated and triggered with the tracked account in one `Promise.all` | 2-channel catalogue; no decoys; `slow-playlist` armed with `delayMs: SLOW_PLAYLIST_DELAY_MS` after the create-time refresh settles; one trigger |
| same test: trigger precondition | `expect(triggerResponses.every((res) => res.status() === 202), …).toBe(true)` | `expect(triggered.status(), 'the tracked refresh must be queued').toBe(202)`. One request is asserted where 31 were. That is fewer requests, not a weaker check on the one that matters. |
| same test: in-flight assertion | `expect(midRestart, …).not.toBe('success:bumped')` | unchanged |
| same test: completion poll | `.toBe('success:bumped')`, 120 s | unchanged |

### Task 2.3 — measure and break-check on a private stack

1. Bring up a private stack with a private provider (Global constraint 6, `h2`). Run
   `npx playwright test --project=streaming-split -g "both relay processes"` three times. Record
   each run's `midRestart` value (add a `console.log` beside it in the same idiom as the spec's
   `[relay-restart]` lines) and the time from trigger to `success:bumped`. Expect the latter to be
   about 30 s plus the parse.
2. **Break-check.** Arm with `delayMs: 1`. The in-flight assertion must fire with its own message
   ("the refresh had already reached 'success:bumped' …"). Revert.
3. Record the setup-phase wall time before and after (the issue's "about 50 s of runtime").

### PR description draft

> **test(e2e): hold Scenario B's refresh in flight with a slow-playlist fault, not thirty decoys**
>
> Closes #197.
>
> `e2e-upstream` gains a thirteenth fault, `slow-playlist` (scenario-wide, `delayMs` required),
> which withholds the playlist for a fixed time and then serves it normally. Contract 1.1.0 → 1.2.0,
> a minor bump. The lockfile's stale `1.0.0` is corrected in passing.
>
> `process-restart.spec.ts`'s Scenario B now holds one refresh in flight with that fault instead of
> contending thirty decoy accounts against an 8,000-channel catalogue. Its two behaviour assertions
> are unchanged. The delay is 30 s, chosen at least 3× the measured relay-uwsgi restart and under
> `fetch_m3u_lines`' 60 s read timeout. The constant's comment carries that formula.
>
> Measured on a private stack (three runs): <midRestart values>, <trigger→success times>, setup
> <before> → <after>.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR H-3 — a 429 through `@authorize_denied`

- **Branch** `fix/H-3-authorize-429-e2e`
- **Closes** #179.
- **Files** `e2e/tests/streaming-failover/stream-limit-429.spec.ts` (new),
  `e2e/tests/guards/allowlist.ts`, `e2e/playwright.config.ts`,
  `e2e/tests/streaming/authorize-matrix.spec.ts` (comment only), `e2e/COVERAGE.md`.
- **Test labels** none on the backend. `guards` locally, and one `streaming-failover` run on a
  private stack.
- **Upstreamable** no.

### Task 3.1 — the spec (Appendix E)

1. Add `'tests/streaming-failover/stream-limit-429.spec.ts'` to `GLOBAL_SETTINGS_WRITE.allow` with
   the three-part comment ADR 0003 requires (group and key, why nothing else reads it, how teardown
   restores it). § #179 has the argument. Run `--project=guards`: the global-mutation guard is green
   with the entry and red without it (that is the guard's own break-check, record it).
2. Write the spec per Appendix E. Test title:
   `'a user at their stream limit gets 429, not 403 or 500, through the authorize hop'`. Tag
   `@contract`, with a header comment saying why in one sentence: ADR 0003's "every file on a
   capability allowlist is `@characterization`" covers the four capabilities, `GLOBAL_SETTINGS_WRITE`
   is not one of them, and `catchup-redirect.spec.ts` (on that list, `@contract` at `:60`) is the
   precedent.
3. `e2e/playwright.config.ts` `streaming-failover` block: "two specs in this directory mutate
   container-global state" → three, and one paragraph for `user_limit_settings`.
4. `authorize-matrix.spec.ts:327-334`: the comment says the 404 row is the only restoration row.
   Change it to name `streaming-failover/stream-limit-429.spec.ts` as the 429 row. No assertion
   changes.
5. `e2e/COVERAGE.md`: a new Streaming row after `:197`, goal `P1`, status `done`: "Authorize hop,
   429 restoration: an XC user at `stream_limit` with `terminate_on_limit_exceeded` off gets 429
   through `@authorize_denied`, and the same tune succeeds once the first stream closes.
   `tests/streaming-failover/stream-limit-429.spec.ts`".

### Task 3.2 — run and break-check on a private stack (`h3`)

1. `npx playwright test --project=streaming-failover tests/streaming-failover/stream-limit-429.spec.ts`
   green.
2. **Break-check A, the restoration.**
   `docker exec dispatcharr-e2e-h3 sed -i '/authorize_status = 429/d' /etc/nginx/sites-enabled/default
   && docker exec dispatcharr-e2e-h3 nginx -s reload`. If `nginx -s reload` cannot find the master's
   pid file (supervisord runs nginx in the foreground), use `docker exec dispatcharr-e2e-h3
   supervisorctl -c /app/docker/supervisord/supervisorctl.conf restart nginx` instead. Rerun: fails with `StreamStatusError` status
   **403** where 429 was expected (the `return 403` fall-through at `nginx.conf:699`). Restore with
   `scripts/e2e_up.sh --recreate` (same exports), which re-creates the container from the unmodified
   image.
3. **Break-check B, the setting is load-bearing.** Comment out the PATCH. Rerun: the second tune
   succeeds (the default terminates the first stream), and `expectRefused` fails on "was not
   refused". Revert.
4. Confirm teardown: after the run, `GET /api/core/settings/` shows `user_limit_settings` byte-equal
   to its value before the run.

**Test changes under the rule.** None. One comment in `authorize-matrix.spec.ts` changes; no
assertion does.

### PR description draft

> **test(e2e): prove the 429 restoration through the authorize hop**
>
> Closes #179.
>
> `@authorize_denied` restores 404 and 429 from `X-Authorize-Status`. Only the 404 had a
> behavioural test. A new `streaming-failover` spec gives an XC user `stream_limit: 1`, turns
> `user_limit_settings.terminate_on_limit_exceeded` off for its run, holds one live stream and
> asserts the second tune gets exactly 429. A control closes the first stream and shows the same
> tune then succeeds. The global write is allowlisted with its argument, guarded up front against a
> dirty container, and restored in `afterEach`.
>
> Break-checks: deleting the 429 line in the running container's nginx turns the result into 403;
> skipping the setting write lets the second tune through.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR H-4 — the DVR records a hidden channel through the hop

- **Branch** `fix/H-4-dvr-internal-principal-e2e`
- **Closes** #178.
- **Files** `e2e/tests/dvr/recording-hidden-channel.spec.ts` (new), `e2e/COVERAGE.md`.
- **Test labels** none on the backend. One `dvr` run on a private stack.
- **Upstreamable** no.

### Task 4.1 — the spec (Appendix F)

1. Write the spec. Test title:
   `'a recording of a channel hidden from output still captures bytes, because the DVR is the
   internal principal'`. Tag `@contract` (bytes served over HTTP from the recording endpoint).
2. Premise first: an anonymous `streamClient.open('/proxy/ts/stream/<uuid>')` is refused with exactly
   403 (the `expectRefused` shape from `authorize-matrix.spec.ts:362-391`, copied locally, not
   imported across projects). Without it, a passing recording could mean the channel was not hidden.
3. Cleanup follows `recording-execution.spec.ts:36-51`: module-scoped ids set the moment each
   resolves, deleted in `test.afterEach` through `cleanupRecordingAndChannel`.
4. `e2e/COVERAGE.md`: a new DVR row, goal `P1`, `done`: "DVR internal principal: a
   `hidden_from_output` channel, refused to an anonymous tune, still records through nginx's
   authorize hop and serves an MKV. The only end-to-end proof that ffmpeg sends
   `X-Dispatcharr-Internal` and the hop honours it.
   `tests/dvr/recording-hidden-channel.spec.ts`".

### Task 4.2 — run and break-check on a private stack (`h4`)

1. `npx playwright test --project=dvr tests/dvr/recording-hidden-channel.spec.ts` green.
2. **Break-check.** In the running container only:
   `docker exec dispatcharr-e2e-h4 sed -i 's/^    if internal_token:$/    if False:/'
   /app/apps/channels/tasks.py`, confirm with `grep -n "if False:"` that exactly one line changed,
   then `docker exec dispatcharr-e2e-h4 supervisorctl -c /app/docker/supervisord/supervisorctl.conf
   restart celery-dvr`. Rerun: the provider never shows a live connection, or the status never
   reaches `completed`. The failure must be the recording's, not the premise's. Restore with
   `scripts/e2e_up.sh --recreate`.
3. Run the whole `dvr` project once on the fixed tree. It is `workers: 1` and every row records;
   confirm the new row does not disturb its neighbours.

**Test changes under the rule.** None.

### PR description draft

> **test(e2e): the DVR records a hidden channel through the authorize hop**
>
> Closes #178.
>
> Every `dvr` spec recorded an ordinary channel, which an anonymous request may stream, so all of
> them would pass if ffmpeg stopped sending `X-Dispatcharr-Internal`. The new spec records a
> `hidden_from_output` channel through nginx, after proving an anonymous tune of it is refused
> with 403, and asserts the finished recording is served as an MKV.
>
> Break-check: disabling the header in the running container's `celery-dvr` makes the recording
> fail while the premise still holds.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## PR H-5 — `channel-profiles.spec.ts`: measure, then close with E's #72 fix

- **Branch** `fix/H-5-channel-profiles-flake`
- **Closes** #86, **after** category E's #72 PR merges.
- **Files** `e2e/COVERAGE.md` (`:191` only).
- **Test labels** none. Two measurement campaigns on a private stack (`h5`).
- **Upstreamable** n/a.

### Task 5.1 — before E's fix: confirm the mechanism

1. On a private stack built from `main` **before** E's #72 PR, run the `seeded` project eight times
   in a row (`npx playwright test --project=seeded --repeat-each=1`, looped in the shell, **not**
   `--repeat-each=8`, which multiplies tests inside one run and changes the load shape). Keep each
   run's report.
2. After the loop, count **failures, not matching lines**. The constraint name appears on several
   lines of one Django traceback (the `IntegrityError` message and the SQL), so a `grep -c` on it
   overcounts. Count distinct `Internal Server Error: /api/channels/profiles/` lines
   (`docker logs dispatcharr-e2e-h5 2>&1 | grep -c 'Internal Server Error: /api/channels/profiles/'`,
   under `set -o pipefail`), and save the traceback that follows each one. That line reaches the
   container log by this path: `django.request`'s 500 log (`log_response`, ERROR, with `exc_info`)
   propagates because `dispatcharr/settings.py:541` sets `disable_existing_loggers: False` and the
   root logger (`:606-609`) has the `console` handler at `LOG_LEVEL`; `api-uwsgi`'s stdout goes to
   the container's (`docker/supervisord.d/api-uwsgi.conf:13-15`). The mechanism is confirmed when at least one traceback's request is
   `POST /api/channels/profiles/`, the `post_save` receiver `create_profile_memberships` is in its
   stack, and the constraint is the membership table's `(channel_profile_id, channel_id)` unique
   key. Count the Playwright failures and flaky retries too.
3. **If no traceback appears in eight runs,** say so and run eight more. If sixteen runs show none,
   STOP and report: the mechanism is unconfirmed, and closing #86 on E's fix would be a true
   positive for a false reason (memory note). The arithmetic behind the numbers: at the reported
   rate of one failure in six to eight runs (taking 1 in 7), eight clean runs happen about 29%
   of the time with the mechanism present (0.857^8; 34% at 1 in 8), so eight is not evidence of
   absence. Sixteen clean runs happen about 8% of the time (12% at 1 in 8). That is a reasonable
   point to stop and report rather than keep spending runs. The log signature is also more
   sensitive than the Playwright count, because it records a race that retry absorbed.

### Fallback if category E memos or defers #72

Q1's recommendation stands: the fix belongs to E. If E's plan lands without a #72 PR, the lead
flips H-5 into carrying the minimal fix with one ruling, and nothing else here changes shape:

- **Fix.** `ignore_conflicts=True` on both `bulk_create` calls: the receiver's at
  `apps/channels/signals.py:238` and the viewset's at `apps/channels/api_views.py:877` (the omitted
  `channel_profile_ids` branch; the sentinel-`0` branch's copy below it gets the same argument). Both
  populate a set where an existing row is not an error. The receiver relies on `enabled`'s `True`
  default and the viewset passes `enabled=True`, so the rows they would collide on are identical.
- **Test.** `apps/channels/tests/test_profile_membership_race.py`, a `TransactionTestCase`,
  `test_a_profile_created_during_a_channel_create_answers_500`. Two threads, one creating a
  profile through the API and one creating a channel with `channel_profile_ids` omitted, with the
  receiver's `Channel.objects.all()` held open (patched to wait on an `Event` the channel thread
  sets after its commit). Assert neither answers 500 and the new profile's membership set contains
  every channel. Break-check: drop `ignore_conflicts` from the receiver only; the test reddens with
  the `IntegrityError`.
- **Test label** `apps.channels` (app label `dispatcharr_channels`; no model change, so no migration).
  **Upstreamable** yes. **Ledger** none (#72 has no row in `defects.yml`). It also closes #72.
- **Evidence.** The same before/after campaign as Tasks 5.1 and 5.2, with this PR's image as "after".

### Task 5.2 — after E's fix

1. Rebuild the private stack's image from `main` after E's #72 PR (`DISPATCHARR_E2E_IMAGE` absent,
   or `--recreate` with a fresh tag). Repeat Task 5.1's loop with the same count.
2. Expect zero membership `IntegrityError`s and zero `channel-profiles.spec.ts` failures or retries.
3. `e2e/COVERAGE.md:191`: the #86 sentence becomes "diagnosed as #72's race, with the profile
   create as the losing request (N tracebacks in M runs before #<E's PR>, none in M after); fixed by
   #<E's PR>". Status for the #72 half follows E's own edit to that row, if E makes one.
4. The lead closes #86 with the two counts (a tracker write, deferred per the brief).

**Test changes under the rule.** None.

### PR description draft

> **docs(e2e): #86 was #72's race; the flake is gone with its fix**
>
> Closes #86.
>
> Before #<E's PR>, eight `seeded` runs produced <N> `IntegrityError`s on
> `channelprofilemembership`'s unique key, each from `POST /api/channels/profiles/` inside the
> `create_profile_memberships` receiver, and <K> `channel-profiles.spec.ts` failures. After it,
> the same eight runs produced none. The profile create lost the race because it commits its row
> before the receiver reads the channel table, while a concurrent channel create had already
> inserted the same membership inside its own transaction. `COVERAGE.md`'s row records it.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## Open questions

**Q1. If category E does not fix #72, who fixes #86?** H-5 assumes E's plan makes both
`bulk_create` calls conflict-tolerant, the direction #72's own body suggests. If E instead writes a
memo or defers #72, #86 has a confirmed cause and no fix. The two readings lead to different work:
H-5 grows a product change in `apps/channels/signals.py` and `api_views.py` plus the backend
regression test, which is exactly E's #72 PR moved into H. That fallback is written out in full
under PR H-5, so the lead can switch to it with one ruling. Recommendation: keep the fix in E, and
treat Q1 as a check the lead makes when E's plan lands.

Every other choice here has a default the plan adopts and states. The main ones are the #187
two-group rule over a single `STACK` variable, the guards project over a backend label for the
script's test, a 30 s delay for #197, and `streaming-failover` as #179's home.

## Follow-ups for the lead to file

- **The shared provider image flip-flops across worktrees.** Every `e2e_up.sh` start rebuilds
  `dispatcharr-e2e-upstream:local` from the invoking tree (`scripts/e2e_up.sh:167-179`), so two
  worktrees with different `e2e-upstream/src/` recreate the shared provider on every alternate run.
  H-1 keeps the provider attached to every stack and warns about the lost scenarios, and the README
  tells a worktree that changes the provider to use a private one. It does not stop the flip-flop.
  Not filed as an issue.
- Memory note `e2e-parallel-stacks` should be rewritten once H-1 merges. Its "never run
  `e2e_up.sh` while a sibling runs" rule becomes "use the full override set; the script refuses
  half of one".

## Coverage table

| Issue | Disposition | PR section |
|---|---|---|
| #168 | planned | H-1 |
| #261 | closed 2026-09-23, duplicate of #168 | H-1 (via #168) |
| #214 | closed 2026-09-23, duplicate of #168 | H-1 (via #168) |
| #209 | closed 2026-09-23, duplicate of #168 | H-1 (via #168) |
| #201 | closed 2026-09-23, duplicate of #168 | H-1 (via #168) |
| #185 | closed 2026-09-23, duplicate of #168 | H-1 (via #168) |
| #187 | planned (related to #168, not a duplicate) | H-1 |
| #197 | planned | H-2 |
| #179 | planned | H-3 |
| #178 | planned | H-4 |
| #86 | planned, verification only; the fix is E's #72 | H-5 (Q1) |

---

## Appendices

Sketches, not final code. Each is written against the seed and must be re-read against the tree
the implementer branches from.

### Appendix A — `scripts/e2e_up.sh` (H-1)

Replaces `:44-50`'s comment:

```bash
# _UPSTREAM_CONTAINER and _UPSTREAM_PORT start the provider under another
# name and port. The provider is told its name (UPSTREAM_INTERNAL_ORIGIN,
# below), so its playlists point at a host this stack's network resolves.
# Playwright must be told too: E2E_UPSTREAM_CONTROL_URL and
# E2E_UPSTREAM_INTERNAL_URL (e2e/fixtures/upstream.ts). check_scope refuses
# a mismatch between the two sides when both are set.
```

Before the `case` (after the argument-count check at `:79-83`):

```bash
# A second stack is safe only if it is scoped completely (#187). Every
# variable below defaults independently, so a half-exported shell used to act
# on a mix of a private stack and the shared one. Strings, not arrays: under
# set -u, bash < 4.4 (macOS /bin/bash is 3.2) treats an empty "${a[@]}" as
# unbound.
check_scope() {
  local v set_names="" missing="" problems=""
  for v in DISPATCHARR_E2E_CONTAINER DISPATCHARR_E2E_VOLUME DISPATCHARR_E2E_NETWORK; do
    if [[ -n "${!v:-}" ]]; then set_names+=" $v"; else missing+=" $v"; fi
  done
  if [[ -n "$set_names" && -n "$missing" ]]; then
    problems+="  set:${set_names}; also required:${missing}"$'\n'
  fi
  if [[ -n "$set_names" && -z "${DISPATCHARR_E2E_PORT:-}" ]]; then
    problems+="  a scoped stack needs DISPATCHARR_E2E_PORT too"$'\n'
  fi
  local up_c=0 up_p=0
  [[ -n "${DISPATCHARR_E2E_UPSTREAM_CONTAINER:-}" ]] && up_c=1
  [[ -n "${DISPATCHARR_E2E_UPSTREAM_PORT:-}" ]] && up_p=1
  if (( up_c != up_p )); then
    problems+="  DISPATCHARR_E2E_UPSTREAM_CONTAINER and _UPSTREAM_PORT go together"$'\n'
  fi
  local host port
  if [[ -n "${E2E_UPSTREAM_INTERNAL_URL:-}" ]]; then
    host="${E2E_UPSTREAM_INTERNAL_URL#*://}"; host="${host%%[:/]*}"
    [[ "$host" == "$UPSTREAM_NAME" ]] ||
      problems+="  E2E_UPSTREAM_INTERNAL_URL names '$host' but the provider is '$UPSTREAM_NAME'"$'\n'
  fi
  if [[ -n "${E2E_UPSTREAM_CONTROL_URL:-}" ]]; then
    port="${E2E_UPSTREAM_CONTROL_URL##*:}"; port="${port%%/*}"
    [[ "$port" == "$UPSTREAM_PORT" ]] ||
      problems+="  E2E_UPSTREAM_CONTROL_URL uses port '$port' but the provider publishes '$UPSTREAM_PORT'"$'\n'
  fi
  if [[ -n "$problems" ]]; then
    echo "Refusing a partially scoped stack (see e2e/README.md, 'Running a second stack'):" >&2
    printf '%s' "$problems" >&2
    exit 2
  fi
}
check_scope
```

The helpers and the three rewritten sites:

```bash
# One network per line. A Go template over the map's keys, never a grep of
# {{json .NetworkSettings.Networks}}: each real endpoint object carries a
# dozen nested keys, and a line grep for names matches them (#261's review).
# A stopped container still lists its attachments. A missing one exits 1
# with `no such object` on stderr and one blank line on stdout, which the
# sed strips, so it yields no names here.
container_networks() {
  docker inspect -f '{{range $n, $_ := .NetworkSettings.Networks}}{{println $n}}{{end}}' \
    "$1" 2>/dev/null | sed '/^$/d' || true
}

# The provider's networks other than this stack's. Non-empty means another
# stack still uses it (#168). Captured, not piped into grep -q: under
# pipefail a grep -q that exits early can SIGPIPE the writer and report 141.
upstream_other_networks() {
  container_networks "$UPSTREAM_NAME" \
    | grep -vxF -e "$NETWORK" -e bridge -e host -e none || true
}

ensure_on_network() {
  local container="$1"
  if ! container_networks "$container" | grep -qxF "$NETWORK"; then   # see note below
    docker network connect "$NETWORK" "$container" >/dev/null 2>&1 || true
  fi
}

destroy() {
  local others
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  others="$(upstream_other_networks)"
  if [[ -n "$others" ]]; then
    echo "Leaving $UPSTREAM_NAME running for:" $others
    docker network disconnect "$NETWORK" "$UPSTREAM_NAME" >/dev/null 2>&1 || true
  else
    docker rm -f "$UPSTREAM_NAME" >/dev/null 2>&1 || true
  fi
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
}
```

`ensure_on_network`'s `grep -q` sits in an `if !` condition. There the SIGPIPE status would read as
"not attached" and trigger a harmless redundant `connect`, which the `|| true` absorbs. Prefer the
captured-variable form anyway, so the file has one idiom.

`--stop` (`:123-124`):

```bash
    if [[ -n "$(upstream_other_networks)" ]]; then
      echo "Leaving $UPSTREAM_NAME running: another stack's network is attached to it."
    else
      docker stop "$UPSTREAM_NAME" >/dev/null 2>&1 && echo "Stopped $UPSTREAM_NAME." \
        || echo "$UPSTREAM_NAME was not running."
    fi
```

Image-moved recreation (`:190-206`):

```bash
PRIOR_NETWORKS=""
if EXISTING_IMAGE_ID="$(docker inspect -f '{{.Image}}' "$UPSTREAM_NAME" 2>/dev/null)" \
    && [[ "$EXISTING_IMAGE_ID" != "$UPSTREAM_IMAGE_ID" ]]; then
  PRIOR_NETWORKS="$(upstream_other_networks)"
  echo "Recreating $UPSTREAM_NAME: the image moved."
  if [[ -n "$PRIOR_NETWORKS" ]]; then
    echo "  Other stacks use it (" $PRIOR_NETWORKS "). They keep the provider but lose every scenario they had created."
  fi
  docker rm -f "$UPSTREAM_NAME" >/dev/null
fi
…
  docker run -d --name "$UPSTREAM_NAME" \
    --network "$NETWORK" \
    -p "127.0.0.1:${UPSTREAM_PORT}:8080" \
    -e UPSTREAM_INTERNAL_ORIGIN="http://${UPSTREAM_NAME}:8080" \
    "$UPSTREAM_IMAGE" >/dev/null
fi
ensure_on_network "$UPSTREAM_NAME"
for n in $PRIOR_NETWORKS; do
  docker network inspect "$n" >/dev/null 2>&1 && docker network connect "$n" "$UPSTREAM_NAME" >/dev/null 2>&1 || true
done
```

`check_scope` runs after the variables are resolved (it reads `$UPSTREAM_NAME`/`$UPSTREAM_PORT`) and
before the `case`. The helper functions must be defined before `check_scope` is called.

### Appendix B — the stub and the guards spec (H-1)

`e2e/tests/guards/e2e-up-stub.sh`, sketch. State lives in files so the spec can seed it and read it
back:

```
$STUB_STATE/log                       one line per invocation: "<argv>"
$STUB_STATE/c/<name>/image            image id
$STUB_STATE/c/<name>/running          present when running
$STUB_STATE/c/<name>/networks         one network per line
$STUB_STATE/c/<name>/env              one -e value per line (from `run`)
$STUB_STATE/n/<name>                  a network exists
$STUB_STATE/v/<name>                  a volume exists
$STUB_STATE/i/<tag>                   image id for a tag
```

It handles exactly the invocations the script makes. Each is listed with its answer:

| argv shape | effect / output |
|---|---|
| `inspect -f '{{range $n, $_ := .NetworkSettings.Networks}}{{println $n}}{{end}}' C` | cat `networks`, then one blank line (as real Docker prints); if C is absent, print one blank line on stdout, `error: no such object: C` on stderr, exit 1 (as Docker 29.8 does) |
| `inspect -f '{{.Image}}' C` | cat `image`; exit 1 if absent |
| `inspect -f '{{.State.Running}}' C` | `true`/`false` |
| `image inspect [-f '{{.Id}}'] T` | cat `i/T`; exit 1 if absent |
| `build … -t T …` | writes `i/T` from `$STUB_NEXT_IMAGE_ID` (default `sha256:new`) |
| `network inspect N` / `network create N` / `network rm N` | exists? / create / remove |
| `network connect N C` / `network disconnect N C` | add / remove the line |
| `rm -f C` / `stop C` / `start C` | remove dir / drop `running` / add `running` |
| `run -d --name C --network N -p … [-e K=V]… [-v …] IMAGE` | create C, running, networks = N, env lines, image = `i/IMAGE` |
| `ps [-a] --format '{{.Names}}'` | names (running only unless `-a`) |
| `volume rm V`, `logs …` | remove / no output |
| `network inspect N -f '{{(index .IPAM.Config 0).Gateway}}'` (B-7's call, flag after the name; answered unconditionally) | `172.30.0.1` if N exists, else exit 1 |
| `STUB_AS=curl …` | exit 0 |
| anything else | append `UNHANDLED <argv>` to the log, exit 97 |

Two rules the table leaves implicit. **`run`'s argv parser:** `--name`, `--network`, `-p`, `-e` and
`-v` each consume exactly one following value, `-d` consumes none, and the first remaining
positional is the image; anything else is `UNHANDLED`. **Environment:** `runScript` passes
`STUB_STATE=<tmpdir>/state` to the script (the wrappers inherit it), the `curl` wrapper is
`exec env STUB_AS=curl bash <stub> "$@"` and the `docker` wrapper is `exec bash <stub> "$@"`.

The spec's own helpers: `mkStack()` returns the throwaway names and an env object;
`seedContainer(state, name, {image, running, networks})`; `runScript(mode, env)` returns
`{status, stdout, stderr, log}`; and every test ends with
`expect(log.filter((l) => l.startsWith('UNHANDLED'))).toEqual([])`. Keep the literal `docker `
(with the trailing space) out of the spec's string literals where it is easy to, so a later
reviewer need not argue it. `tests/guards/` is exempt from the capability scan anyway (see #168
above), and the spec's header says so and says why the exemption fits: it runs no container, and its
precheck proves the stub is what ran.

### Appendix C — the fault (H-2)

`e2e-upstream/src/faults.ts`:

```ts
export type FaultName = … | 'range-unsupported' | 'slow-playlist';
export const FAULT_NAMES = [ …, 'range-unsupported', 'slow-playlist' ];
const SCENARIO_WIDE_ONLY_FAULTS = ['xc-auth-envelope', 'range-unsupported', 'slow-playlist'];
export const MAX_PLAYLIST_DELAY_MS = 120_000;

export interface FaultRequest { …; /** slow-playlist. Required when arming. */ delayMs?: number; }

// in parseFaultRequest, mirroring catchup-layout-404's required-when-arming shape:
if (request.fault === 'slow-playlist' && request.active) {
  if (typeof body.delayMs !== 'number' || !Number.isInteger(body.delayMs)
      || body.delayMs < 1 || body.delayMs > MAX_PLAYLIST_DELAY_MS) {
    throw new BadRequestError(
      `'slow-playlist' requires 'delayMs', an integer between 1 and ${MAX_PLAYLIST_DELAY_MS}`);
  }
  request.delayMs = body.delayMs;
} else if (body.delayMs !== undefined) {
  if (request.fault !== 'slow-playlist') {
    throw new BadRequestError(`'delayMs' is only meaningful on 'slow-playlist'`);
  }
  // clearing with an explicit delayMs: validate the same way, then store
}
```

`FaultStore.apply`'s `default:` branch already covers it (`appliedTo` stays 0). Add the name to that
branch's comment list.

`e2e-upstream/src/server.ts`, in the playlist route after `credentialsMatch` (`:495-499`) and before
`renderPlaylist` (`:500`):

```ts
    // A refresh the test wants held in flight (#197). Withholds the headers,
    // so the client's read timeout is what bounds a delay — Dispatcharr's
    // fetch_m3u_lines allows 60 s. Scenario-wide only: a playlist has no
    // channel.
    const slow = faults.configOf(scenario.id, 'slow-playlist');
    if (slow && faults.isActive(scenario.id, 'slow-playlist')) {
      await new Promise((resolve) => setTimeout(resolve, slow.delayMs));
      if (res.destroyed) return; // the client gave up; nothing to write
    }
```

Check whether `server.ts` already imports a `sleep`/`delay` helper from `stream.ts` before adding the
inline promise. The `logRequest(scenario, req, url, 200)` that follows logs after the delay, which is
the moment the response is actually sent.

### Appendix D — Scenario B (H-2)

```ts
/**
 * How long the fake provider withholds the tracked account's playlist, so its
 * refresh is still running when `supervisorctl restart relay-uwsgi` returns.
 *
 * Derived, not tuned: at least 3x the measured relay-uwsgi restart
 * (6,867 ms, e2e/COVERAGE.md's bounded-restart row) and below
 * fetch_m3u_lines' 60 s read timeout (apps/m3u/tasks.py, `timeout=(30, 60)`),
 * which a withheld response counts against. A refresh fetches the playlist
 * once, so the delay is paid once. If the in-flight assertion below ever
 * fires, raise this within that bound; if the restart outgrows a third of
 * the timeout, the formula no longer has room and the design needs revisiting.
 */
const SLOW_PLAYLIST_DELAY_MS = 30_000;

// …in the test, replacing :501-539's slow catalogue and decoys:
const slowScenario = await upstream.scenario({
  channels: [
    { id: 1, name: 'split slow refresh 1', tvgId: 'split-slow-refresh-1.e2e', logo: null },
    { id: 2, name: 'split slow refresh 2', tvgId: 'split-slow-refresh-2.e2e', logo: null },
  ],
});
const account = await seed.upstreamM3UAccount(slowScenario); // settles the create-time refresh

// …replacing :642-669, after `before` is read:
await upstream.fault(slowScenario, 'slow-playlist', { delayMs: SLOW_PLAYLIST_DELAY_MS });
const triggered = await api.post(`/api/m3u/refresh/${account.id}/`, {});
expect(triggered.status(), 'the tracked refresh must be queued').toBe(202);
```

The fault needs no explicit clear: the `upstream` fixture deletes its scenarios at teardown, and
`DELETE /scenarios/<id>` clears their faults (`server.ts:470`).

### Appendix E — the 429 spec (H-3)

```ts
// module scope, for afterEach
let settingsRowId: number | undefined;
let originalValue: Record<string, unknown> | undefined;

test.afterEach(async ({ api }) => {
  if (settingsRowId !== undefined && originalValue !== undefined) {
    await api.patch(`/api/core/settings/${settingsRowId}/`, { value: originalValue });
  }
  settingsRowId = undefined; originalValue = undefined;
});

test('a user at their stream limit gets 429, not 403 or 500, through the authorize hop',
  { tag: '@contract' }, async ({ upstream, seed, api, streamClient, baseURL }) => {
  const scenario = await upstream.scenario({ channels: [
    { id: 1, name: 'H3 Limit Held', tvgId: 'h3-limit-held.e2e', logo: null },
    { id: 2, name: 'H3 Limit Second', tvgId: 'h3-limit-second.e2e', logo: null } ], rate: 20 });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel: held } = await seed.upstreamChannel(scenario, { channelIds: [1], streamProfileId: proxy.id });
  const { channel: second } = await seed.upstreamChannel(scenario, { channelIds: [2], streamProfileId: proxy.id });
  const viewer = await seed.xcUser({ user_level: 1, stream_limit: 1 });

  const row = /* read user_limit_settings, as catchup-redirect.spec.ts:50-55 reads its row */;
  expect(row.value.terminate_on_limit_exceeded,
    'a previous run left user_limit_settings dirty').not.toBe(false);
  settingsRowId = row.id; originalValue = row.value;
  await api.patch(`/api/core/settings/${row.id}/`,
    { value: { ...row.value, terminate_on_limit_exceeded: false } });

  await streamClient.open(`/live/${viewer.username}/${viewer.xcPassword}/${held.id}`);
  expectTsAligned(await streamClient.readPackets(200)); // registered in the relay, not just opened

  const secondClient = newStreamClient(baseURL!);
  await expectRefused(secondClient,
    `/live/${viewer.username}/${viewer.xcPassword}/${second.id}`, 429,
    'a user at stream_limit must get 429 back through @authorize_denied');

  await streamClient.close();
  // Control: the refusal was the limit. The relay drops the client when its
  // connection ends, so poll rather than read once.
  await expect.poll(async () => openOutcome(secondClient,
      `/live/${viewer.username}/${viewer.xcPassword}/${second.id}`),
    { timeout: 30_000, intervals: [1_000] }).toBe('ok');
  await secondClient.close();
});
```

`expectRefused` is copied from `authorize-matrix.spec.ts:362-391`. `openOutcome` follows
`process-restart.spec.ts:287`: copy the smallest form that returns `'ok'` on a 200 and the status
otherwise. `newStreamClient` and `lockedProfile` come from `../streaming/helpers`, as
`process-restart.spec.ts:67` imports them.

### Appendix F — the DVR spec (H-4)

```ts
let channelIdToCleanup: number | undefined;
let recordingIdToCleanup: number | undefined;
test.afterEach(/* recording-execution.spec.ts:40-51, verbatim shape */);

test('a recording of a channel hidden from output still captures bytes, because the DVR is the internal principal',
  { tag: '@contract' }, async ({ upstream, seed, api, waitFor, streamClient }) => {
  const scenario = await upstream.scenario({ channels: [
    { id: 1, name: 'H4 DVR Hidden', tvgId: 'h4-dvr-hidden.e2e', logo: null } ] });
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1], channel: { hidden_from_output: true } });
  channelIdToCleanup = channel.id;

  // Premise: the hop refuses this channel to anyone without a principal.
  await expectRefused(streamClient, `/proxy/ts/stream/${channel.uuid}`, 403,
    'the channel must be hidden, or a successful recording proves nothing');

  const recording = await scheduleRecording(api, channel.id, { startInMs: 5_000, durationMs: 30_000 });
  recordingIdToCleanup = recording.id;

  // Bytes flowed provider → relay → ffmpeg: the flagship's own proof (recording-execution.spec.ts:104-125).
  await waitFor.condition(async () => (await upstream.connections(scenario)).live === 1,
    { timeoutMs: 60_000, description: 'the recording to open a provider connection' });

  await waitForRecordingStatus(waitFor, recording.id, ['completed']);
  // Then the finished file, exactly as the flagship reads it (MKV_MAGIC).
});
```

The `connections().live === 1` budget is 60 s here, where the flagship allows 20 s after the
`recording` status. This spec does not wait on that status first. The budget is 5 s to start, plus
beat's 5 s tick, plus ffmpeg's `_first_segment_timeout` of 15 s, plus margin.
