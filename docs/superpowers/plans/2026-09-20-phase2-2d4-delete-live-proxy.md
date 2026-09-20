# Phase 2 stage 2d-4 — delete `apps/proxy/live_proxy/`

**Goal.** Delete the Python live relay. The Go relay has carried every live viewer since 2d-3's
nginx flip; this PR removes the implementation it replaced, closes the eight module-level import
sites that would otherwise stop Django booting in every role, disposes of every test that pointed
at it, and moves the two artefacts outside the directory that still read files inside it. It is the
largest single deletion in the phase: **101 files, 96 of them Python, 26,371 lines**.

**Architecture.** Django 6 + DRF control plane; a stdlib-only Go relay (`relay/`) serving
`/proxy/ts/stream/`, both XC live roots and the five `/proxy/relay/…` control routes through nginx
since 2d-3. `docker/uwsgi.relay.ini`'s Python relay process **stays**, narrowed to VOD and catch-up
for the remainder of Phase 3. What this PR deletes is the live-path Python package, not the process.

**Tech stack.** Python 3 / Django 6 / DRF, Go (stdlib only), Playwright, GitHub Actions.

**Spec.** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`, § Stage 2d
`### Deletion order — one PR each` **entry 4**, as amended by **A10** (A10.3–A10.8, A10.11,
A10.13–A10.15, A10.17), **A11** (2d-1's shims, which die here), **A12** (2d-2's one handover,
A12.3's `worker_id`) and **A13** (2d-3). This plan's own amendment is **A14**, in Appendix N.

**Branch.** `migration/phase2d-delete-live-proxy`. The `migration/**` prefix is load-bearing: it runs
every Playwright project plus both bash suites in `lifecycle-tests.yml`, bypassing the path filters.

---

## THIS PLAN MUST BE RE-SEEDED BEFORE IT IS IMPLEMENTED

**Seed as written: `e1a7b91f1f66bf8d79b0bd21afdbc1675fc0c464`** — the squash-merge of #327
(`migration/phase2d-admin-wrappers`), now on `main`. Every `file:line`, every count and every
appendix in this plan was opened and measured at that tree. The plan was written before #327 merged
and measured against its branch head `dbe56e74`; the two are the **same tree object**
(`ea83ea94342a407bbed3a5ef6c731a357d3d3199`, and `git diff --stat dbe56e74 e1a7b91f` is empty), so
nothing measured at `dbe56e74` needs re-deriving for the swap — only 2d-3's merge does, below.

**2d-3 (`migration/phase2d-nginx-flip`, plan `docs/superpowers/plans/2026-09-19-phase2-2d3-nginx-flip.md`)
merges before this PR is implemented.** It touches fourteen paths, four of which this PR also
touches. Task 0 re-seeds against the merged 2d-3 tree and re-derives, by content rather than by line
number, every anchor in a file 2d-3 moved.

| Path | 2d-3 changes | 2d-4 changes | Collision |
|---|---|---|---|
| `e2e/COVERAGE.md` | four rows: the relay-control-API row, the TTFB row, the bounded-restart row, and the wrapped `:259-261` bullet (its Appendix K) | **four different rows**, seven mentions, that cite an `apps/proxy/live_proxy/` **path** (`:190`, `:192`, `:193`, `:203` at this seed; `:202` is 2d-6's) | **Line numbers move; no row is edited twice.** Note 2d-3's own replacement text for the relay-control-API row does **not** introduce a `live_proxy` path, and its `:259-261` rewrite removes one Redis assertion and adds no citation. Appendix J anchors on row text, not line numbers. |
| `CLAUDE.md` | six passages (§ Architecture's "no nginx location routes to it", the `uwsgi_buffering off` sentence, § Auth's `auth_request` sentence, § Commands' `all-dev` paragraph, the Phase 1 PR 8 restart paragraph, § Test hooks) | **nineteen replacements** (Appendix K) | **Different sentences, same file.** Appendix K is an anchored replacement script with `assert count == 1`, not line-anchored hunks, for exactly this reason — 2d-2's and 2d-3's idiom. |
| the spec | Amendment A13 + eight in-place corrections + a Done-log row | **Amendment A14** (twelve items) + four in-place corrections + a Done-log row (Appendix N) | **Different passages.** A14 is inserted immediately **before** `## Stage 2d`, so it lands after A13 without needing A13's own text. Task 0 Step 7 verifies A13 arrived and STOPs if it did not. |
| `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts` | removes the Redis half, keeps the test title | **nothing.** Its two `live_proxy` mentions (`:130` `redis_keys.py`, `:132` `output/profile/manager.py`) are prose comments that no guard reads; they are 2d-6's | **None.** |
| `docs/relay-parity-matrix.md` | **nothing** — 2d-3's R12 measured this and keeps row 11's test title precisely so the matrix does not move | the whole Source column, 26 Pin cells, and rows 26/27's new sentinel | **None.** |
| `metrics/curated/**` | **nothing** — 2d-3's R12 | three `defects.yml` rows | **None.** |
| `.github/workflows/**` | **nothing** — 2d-3's File structure says so explicitly, and A10.7's `go-tests.yml` edit is named as 2d-4's | `go-tests.yml`, `backend-tests.yml` | **None.** |
| `relay/` | adds `relay/drain/supervisord_priority_test.go` | edits `relay/internal/relaytest/corpus.go` and `asset_test.go`, adds `relay/internal/relaytest/testdata/` | **None** — different files. |

**Figures 2d-3 is expected to move, and Task 0 re-measures:**

- `e2e/COVERAGE.md`'s line numbers for the five rows this PR edits (2d-3 rewrites four rows above
  and below them; its `@@ -193,11 +193,11 @@` hunk is same-length, and its `@@ -257,8 +257,10 @@`
  hunk adds two lines below every row this PR touches — so the five are **expected not to move**,
  which is a prediction Task 0 checks rather than an assumption it makes).
- `CLAUDE.md`'s line numbers throughout.
- The spec's line numbers throughout, and its length.
- **Nothing else.** In particular the 21 matrix rows, the 38 Python pins, the 53 `live_proxy` Source
  citations, the 101 files in the package, the 16 test labels and both coverage floors are untouched
  by 2d-3.

---

## Global Constraints

Numbered so a task step can cite one. **A conflict between a constraint and a task step is a STOP
and report, never a judgement call.**

1. **Anchor every command** with an absolute path or a leading `cd <your worktree> &&`. The shell's
   cwd is shared or correlated across concurrent agents (`CLAUDE.md` § Repository and direction).
2. **`set -o pipefail` on every pipeline whose emptiness or exit status you intend to read**, and
   never `2>/dev/null` a git query you will interpret. `git show "${ref}:path"` with braces, always.
3. **Stage and commit in separate Bash calls**, and write the commit message with the Write tool,
   committing with `git commit -F <file>`. The commit gate matches on command text.
4. **The Python relay process stays.** `docker/uwsgi.relay.ini`, `docker/supervisord.d/relay-uwsgi.conf`,
   `apps/proxy/vod_proxy/` and `apps/timeshift/` are **out of scope**. So is `apps/proxy/hls_proxy/`
   (R17). If a step appears to need one of them, STOP.
5. **No `docker/` file is edited.** 2d-3 owns the deployment shape; this PR changes no nginx
   location, no supervisord program and no entrypoint. The one exception is *reading* them.
6. **No behaviour change on any surviving surface.** The six `ts/` admin routes keep their URLs,
   names, methods, permission classes and response bodies (2d-2's gate still holds, R2). The five
   `/proxy/relay/…` routes are deleted from Django but are unchanged as *served*: nginx routes them
   to Go, and Django's copy has had no caller in an nginx-fronted shape since 2d-3 (R1).
7. **`missing` in `scripts/coverage_live_path.floor` is not written by this PR.** The only floor edit
   is `--write-floor --shape-only`, which never writes `missing`, `percent`, `measured` or `runs`
   (`scripts/coverage_live_path.sh:440-455`). 2d-5 is where the number moves (R9).
8. **Every new or edited test gets a break-check that is RUN, not described**, with the reversion
   named and the failure message quoted.
9. **Every count in this plan was measured at the seed and names the command that produced it.**
   A count that does not match at Task 0 is a STOP.
10. **A channel UUID and a provider URL are secrets.** Neither appears in a log, a test, a commit
    message or the PR body.
11. **No `--write-floor` on the Go coverage gate.** R12 proves `packages=`, `gomod=`, `shape=` and
    `missing` all provably do not move; a PR that runs one is doing something the measurement says
    it should not need to.
12. **Deleting a test is a disposition, not a tidy-up.** Every deleted test file's entry in R7's
    table names either the Go test that covers the same behaviour or the sentence saying no Go
    analogue exists and why.

---

## Rulings

Each was measured from the tree at the seed. The command is given where a number is.

### R1 — `relay_views.py` and `relay_urls.py` are DELETED, and the `dev` branch of the Django→relay address moves with them

**The question A10.3 left open.** `apps/proxy/relay_views.py:34-41` imports five names from
`apps.proxy.live_proxy` at module level, `relay_urls.py:12` imports `relay_views`, and
`apps/proxy/urls.py:9` includes `relay_urls` — so the file cannot be imported once the package is
gone, and leaving it breaks `manage.py check` for every command in every role. A10.3 declined to
choose between deleting it and keeping a Django-side twin, because the trade turns on a question it
could not settle: nothing dials those routes in any nginx-fronted shape after the flip (A10.11), but
deleting removes the only `IsInternalRelay`-gated surface the control plane still owns, and removes
one of Gate 2's ten boundary modules.

**Measured: a "Django-side twin" is not a thing that can be built.** `relay_views.py` is not an
independent implementation of the five routes; it is a 257-line HTTP wrapper over
`ChannelStatus.get_detailed_channel_info`, `build_live_channel_stats_data`, `ProxyServer` and
`ChannelService` — all four inside the deleted directory, reached at `:91-92`, `:147`, `:161-162`,
`:175`, `:180`, `:213`, `:237` and `:247`. "Keeping it" means writing a second implementation of the
Go relay's in-process channel registry in Python, over Redis keys the Go relay never writes. There
is nothing to keep. **Ruling: delete `apps/proxy/relay_views.py`, `apps/proxy/relay_urls.py` and
`apps/proxy/urls.py:9`'s `path('relay/', include('apps.proxy.relay_urls'))`.**

**The consequence the deletion has that is NOT covered by "nothing dials them": the `dev` shape.**
`apps/proxy/internal_base_url.py:175-179`'s `dev` branch hardcodes `http://127.0.0.1:5656` for
**both** directions, because `resolve_base_url()` is shared. In `DISPATCHARR_ENV=dev` there is no
nginx (`docker/supervisord/all-dev.conf` runs `api-uwsgi`, `relay-uwsgi`, `relay-go`, vite and no
nginx), so `relay_client.get_relay_control_base_url()` resolves to the **API uWSGI**, and what
answers `/proxy/relay/…` there today is `relay_urls` → `relay_views`. Delete them and every
`relay_client` call in dev gets a Django 404 → `RelayRefused(404, path)`: the tune path's reuse check
(`apps/channels/models.py:494`), all six admin wrappers, `combined_stats`, the DVR scans. The dev
shape is not covered by "nginx routes it to Go", because there is no nginx.

**Ruling: `resolve_base_url()` gains a `dev_url` parameter, and `get_relay_control_base_url()` passes
the Go relay's port.** Three candidates were weighed:

- **(a) Leave it, and document `DISPATCHARR_RELAY_BASE_URL=http://127.0.0.1:5658` as a dev
  prerequisite.** Zero code, but the stock `all-dev` container is broken out of the box and the
  breakage is a 404 the caller reports as "the relay refused", which is the least legible failure of
  the three.
- **(b) Set the variable in `docker/docker-compose.dev.yml` / `entrypoint.sh` for `DISPATCHARR_ENV=dev`.**
  Violates Constraint 5, and does nothing for the `manage.py runserver 5656` flow `CLAUDE.md`
  § Commands documents, where there is no entrypoint at all.
- **(c) Teach the resolver.** Chosen. The knowledge belongs in the module whose own docstring
  (`:157-166`) already explains what answers in dev; it is covered by `apps.proxy.tests` with no
  container; it fixes both dev flows; and `DISPATCHARR_RELAY_BASE_URL` still wins, unchanged.

The shape mirrors A10.16's, which 2d-3 applied to `RELAY_GO_UPSTREAM`: read
`DISPATCHARR_RELAY_GO_PORT`, default `5658`, and on a non-integer or out-of-range value log once
naming the variable and carry on with the default rather than raising. Appendix C.2 carries the diff.
`get_control_plane_base_url()` (relay → Django) is **unchanged**: Django is still on 5656 in dev.

**What deleting `relay_views.py` costs, stated rather than absorbed:**

- **Gate 2's denominator goes from ten boundary modules to nine.** The `[report] include` line naming
  it is removed with it (R9), and 2d-5's census measures nine. Said in the PR body, because 2d-5's
  plan cannot be written against a module list it has to rediscover.
- **`IsInternalRelay` keeps exactly one user**, `apps/proxy/authorize_views.py`'s
  `authorize_internal_view` — the Go relay's dev authorize fallback (`dispatcharr/urls.py:47-51`).
  So the permission class does not become dead; `apps/proxy/permissions.py` stays in Gate 2's list.
  Verified: `grep -rn "IsInternalRelay" --include='*.py' .` at the seed returns `permissions.py`'s
  definition, `relay_views.py` ×5, `authorize_views.py` ×1 and their tests.
- **The five routes' OpenAPI entries disappear from the schema.** They are `@extend_schema`'d
  internal routes on a surface the client API does not document as public; `manage.py spectacular`
  is not byte-stable across this PR and is deliberately **not** in the gate (contrast 2d-2, where
  byte-identity was the whole point). Task 8 records the before/after operation-id diff instead, so
  the change is observed rather than assumed.

### R2 — `worker_id` in `ts_admin_views.py` is recomputed locally, and the field stays

A12.3 hands this PR exactly one thing: `change_stream` and `next_stream` open with
`ProxyServer.get_instance()` (`apps/proxy/ts_admin_views.py:58`, `:403`) and use it for `worker_id`
alone, which appears in **four** response bodies (`:196`, `:210`, `:542`, `:555`).
`ProxyServer.worker_id` is `f"{hostname}:{pid}"`, `apps/proxy/live_proxy/server.py:95-98`.

**Measured, so the decision is not about a blast radius nobody checked:**

- `grep -rn "worker_id" frontend/src` → **nothing** (A12.3's own measurement, re-run at this seed).
- `grep -rn "worker_id" e2e/` → **one hit**, `e2e/fixtures/types.ts:455`, and it is on
  `ChannelStatusClient` — a *client* entry in the relay's status payload, filled by the Go relay and
  measured present by 2d-3's R15. It is not this field.
- No test anywhere asserts it on these four bodies: `apps/proxy/tests/test_admin_control_views.py`
  (25 tests, the 2d-2 arrival that drives all six routes) never mentions `worker_id`; the only test
  that sets it, `apps/proxy/tests/test_stream_switch.py:73`, is in the half R7 deletes.

**Ruling: recompute it in a module-local `_worker_id()` helper, byte-identical to `server.py:95-98`.**
A12.3 declined recomputation because 2d-2's constraint was *no behaviour change*, and the singleton's
pid could in principle predate a fork; with `ProxyServer` gone, recomputation is the only way to keep
the same value, and the fork caveat inverts — `os.getpid()` at request time is the *current* worker,
which is what the field has claimed to be since Phase 1 PR 4 routed these views to the api role.
Two function-local imports go; nothing else in the four bodies changes.

**Not done here, and named so it is a decision rather than an omission:** the field has never been
the *relay's* worker id, and now there is no Python relay for it to be misread as. Renaming or
removing it is a contract change to four response bodies with no forcing function in this PR, and it
belongs in the post-2d list beside `logging.getLogger("live_proxy.views")` (A12.4, 2d-6's).

### R3 — the three function-local `url_utils` importers re-point at `apps.proxy.next_source`

`apps/proxy/live_proxy/url_utils.py:24` is `from apps.proxy.next_source import get_stream_object,
transform_url  # noqa: F401`, and its comment at `:18-23` calls those two re-exports **PERMANENT**
because "apps/m3u/connection_pool.py:81 and dispatcharr/consumers.py:116 both import it from here
… and neither should have to learn that it moved." They are not permanent; they die with the file,
and the three importers learn it now:

| Site | Name | New import |
|---|---|---|
| `apps/proxy/authorize.py:380` | `get_stream_object` | `from apps.proxy.next_source import get_stream_object` |
| `apps/m3u/connection_pool.py:81` | `transform_url` | `from apps.proxy.next_source import transform_url` |
| `dispatcharr/consumers.py:120` | `transform_url` | `from apps.proxy.next_source import transform_url` |

All three are **function-local**, so the patched-target semantics are preserved exactly: the import
runs at call time, after a `mock.patch` has replaced the attribute on the source module. The real
definitions are `apps/proxy/next_source.py:244` and `:262` and are not touched.

**The coupled test edit, and why it must land in the same commit.** `tests/test_websocket_consumer_filter.py`
patches `"apps.proxy.live_proxy.url_utils.transform_url"` at `:233`, `:256` and `:314`. If the
production import is re-pointed and the patch string is not, `test_m3u_profile_test_rejects_oversized_fields`'s
`mock_transform.assert_not_called()` **passes vacuously** — it would assert a mock that was never in
the call path. That is the "a test can go hollow without changing" shape, and it is invisible to a
diff review. The two edits are one commit, and Task 5's break-check is the *positive* assertion
(`test_m3u_profile_test_runs_for_admin`'s `assert_called_once`), which is the one that goes red if
the pair disagrees.

`url_utils`'s other four names — `generate_stream_url`, `validate_stream_url`, `read_cached_alternates`,
`_cache_alternates`, `tune_extras` — have no importer outside the package
(`grep -rn "url_utils" --include='*.py' . | grep -v "^./apps/proxy/live_proxy/"`, five hits, all
either the three above or prose) and die with it.

### R4 — `apps/proxy/tasks.py` is deleted whole, with the beat entry that names it; `core/tasks.py`'s twin stays

A10.3 site 7 calls this "a capability decision 2d-4 must make", with "delete it (with
`core/tasks.py:428-436`'s dead twin, A10.11) or re-point it at `relay_client.list_channels()`" as
the two options. **Measured, the two halves of that sentence pull apart, and the answer is different
for each.**

`apps/proxy/tasks.py` is 37 lines and holds exactly one thing: a `@shared_task fetch_channel_stats`
that calls `build_live_channel_stats_data(redis_client)` — `channel_status.py:633`, which works by
`SCAN`ning `live:channel:*:metadata`, keys the Go relay never writes. Its only reference anywhere is
`dispatcharr/settings.py:430`'s beat entry, which ships `"enabled": False` at `:432`.
(`grep -rn "proxy\.tasks\|proxy import tasks" --include='*.py' --include='*.yml' .` → one line.)
**Ruling: delete the file, and delete `dispatcharr/settings.py:428-433`'s `"fetch-channel-statuses"`
entry with it.** Re-pointing it at `relay_client.list_channels()` was declined for one measured
reason: that function already exists, in `core/tasks.py`, with tests — re-pointing would ship a
second copy of a task that has shipped disabled since before this programme started.

**`core/tasks.py`'s `fetch_channel_stats` is KEPT, and A10.11's "deletable in 2d-4" is narrowed in
place by Amendment A14.2.** It is not the same thing: it already goes through
`relay_client.list_channels()` (`core/tasks.py:428-431`), it already degrades correctly on
`RelayUnavailable`, `RelayRefused` and `ImproperlyConfigured`, and it carries four green tests in
`core/tests/test_fetch_channel_stats.py`. It imports nothing from `apps.proxy.live_proxy` — one of
those four tests exists to assert exactly that. A10.11 called it dead because its only caller,
`beat_periodic_task` (`core/tasks.py:49-52`), is referenced by no schedule, migration or module
(confirmed: `grep -rn "beat_periodic_task" --include='*.py' .` returns the definition and nothing
else). **That is a property 2d-4 neither creates nor cures**, and deleting working, tested code
because it is currently unreferenced is the widening this phase's charter warns against. It stays;
the orphaned `beat_periodic_task` goes on the post-2d list.

**One residue, disclosed:** removing the beat entry leaves any existing install's
`django_celery_beat` `PeriodicTask` row named `fetch-channel-statuses` in the database.
`DatabaseScheduler` syncs entries *from* the schedule and does not delete an entry that left it, so
the row survives — inert, because it ships `enabled=False` and because the task name it holds no
longer resolves, so beat would refuse to dispatch it even if someone enabled it by hand. A data
migration to remove it is not shipped: it would be a migration whose only effect is tidiness on
installs that have one, and `CLAUDE.md` already records that 16 migrations have no reverse.

### R5 — `apps.py`'s `ready()`, and the two `getattr` consumers no import grep finds

`apps/proxy/apps.py:9-15`'s `ProxyConfig.ready()` imports `.live_proxy.server.ProxyServer` at `:12`
and sets `self.live_proxy = LiveProxyServer.get_instance()` at `:15` in every process that is not
`manage.py`. Two consumers reach the attribute by name:

- `apps/proxy/signals.py:17-20` — a `pre_delete` receiver that stops every local stream manager.
- `apps/proxy/management/commands/proxy.py:40-69` — the `proxy` management command's `start`, `stop`
  and `shutdown` actions.

**Ruling.** `ProxyConfig.ready()` loses its whole body; the method is removed rather than left as a
`pass`, since `AppConfig.ready()` is a no-op by default. `signals.py` loses its `live_proxy` branch
(`:17-20`) and keeps the `hls_proxy` one verbatim — R17: `hls_proxy` is Phase 4's, and its
`getattr(proxy_app, 'hls_proxy', None)` has returned `None` since before this programme started
(nothing has ever set the attribute), so removing it would be a second, unrelated cleanup in the
same receiver. `apps/proxy/management/commands/proxy.py` is **deleted whole**: all three of its
actions drive the singleton and nothing else, `grep -rn "manage.py proxy\|call_command..proxy" .`
returns nothing outside its own file, and a command whose every action is a no-op against a `None`
attribute is worse than an absent command.

`apps/proxy/live_proxy/apps.py`'s `LiveProxyConfig` (a second `ready()` doing the same thing) is
inside the deleted directory and goes with it, as does `dispatcharr/settings.py:107`'s
`"apps.proxy.live_proxy"` `INSTALLED_APPS` entry — the boot-fatal site, and the mechanism that takes
the label count 16 → 15 (R10). The package carries **no migrations**
(`find apps/proxy/live_proxy -name migrations -o -name '0*.py'` → empty), so removing the app from
`INSTALLED_APPS` has no migration consequence at all.

### R6 — the live URL patterns SURVIVE, pointed at `apps/proxy/stream_routes.py`, because the authorize hop resolves them through Django's own urlconf

**This ruling replaces a first draft that deleted them, and the replacement was forced by executing
the plan rather than by reading it.** `dispatcharr/urls.py:9` imports `stream_xc` from the deleted
package and `:69-78` registers it on two root-level patterns; `apps/proxy/urls.py:11` includes
`live_proxy/urls.py`, which registers `stream/<str:channel_id>`. After 2d-3 nginx serves all three
shapes from the Go relay, so the obvious reading is that the patterns go with the imports. **That
reading is wrong, and wrong in production.**

`apps/proxy/authorize_views.py:214-228`'s `_surface_for()` hands the URI in `X-Original-URI` to
**Django's own resolver** and keys on the matched view's `__name__` — `"stream_ts"`, `"stream_xc"`.
Its own comment says why it is written that way: *"rather than re-deriving each surface's URL shape
here — a second copy of the urlconf, guaranteed to drift"*. Delete the patterns and every
`auth_request` subrequest for a live tune resolves to the **SPA catch-all**, so `authorize_view`
answers **403** and nginx never reaches the Go relay. **Every live tune fails, in every
nginx-fronted deployment, on the one surface this whole phase exists to keep working — and every Go
test stays green through it.** Measured: 22 failures and 5 errors in `apps.proxy.tests`, all on the
authorize hop, against a seed baseline of `Ran 428 tests … OK`.

**Ruling: a new `apps/proxy/stream_routes.py` (Appendix O) carries both callables and both pattern
groups.** They exist to be RESOLVED and never to be called:

- **Same paths, same pattern text, same `XC_STREAM_ID_PATTERN` and `\Z`, same view `__name__`s** —
  so `_surface_for` is untouched and Phase 1 D7's three-segment regex trap is unchanged.
- **Same namespace.** `app_name = "live_proxy"`, verbatim from `live_proxy/urls.py:4`, so
  `proxy:live_proxy:stream` still reverses. Nothing in the tree reverses it
  (`grep -rn "live_proxy:stream"` is empty, and `ts_admin_urls.py:11-13` records the same fact for
  its own six), but Global Constraint 6 is *no behaviour change on a surviving surface*, and
  keeping the name costs one line where changing it would be an unstated contract change.
- **501, not 404, in the one shape that can reach them.** Behind nginx nothing does. In
  `DISPATCHARR_ENV=dev` — where `docker/supervisord/all-dev.conf` *does* start `relay-go`, verified
  at the seed — a request arriving here is a developer on the wrong port, and a 404 is
  indistinguishable from an unknown channel, which is the one thing a developer debugging a tune
  must not be told wrongly. The body names `DISPATCHARR_RELAY_GO_PORT`.
- **Its logger is `logging.getLogger("live_proxy")`**, `next_source.py:34-38`'s precedent. That
  gives 2d-6's logger rename **two** sites rather than one (with `ts_admin_views.py`'s, A12.4) —
  stated here so it is a decision.
- **It is deliberately NOT added to Gate 2's `[report] include`** (R9): nine statements of stub on a
  path nginx never sends to Django, and adding it would move `modules=` a second time for no
  ratchet value. The coveragerc comment says so, and 2d-5's re-census may take it.

`tests/test_urls_xc_three_segment.py` therefore **keeps all five of its assertions** — they were
right all along — and takes one docstring paragraph recording that the patterns now exist for the
authorize hop rather than for routing. `e2e/tests/streaming/spa-three-segment-route.spec.ts` needs
no edit either way.

### R7 — seventeen test files outside the package, per-file

A10.14 enumerates eleven files (thirteen before A11.4 moved two to 2d-1) by counting **import
statements**. Re-derived at this seed with a classifier that separates module-level imports,
function-local imports, `mock.patch` **string** targets and prose — three kinds A10.14's grep does
not distinguish — the affected set is **fifteen files across four labels**, and the breakage is of
three different kinds. **Executing the plan found two more, and neither names `live_proxy`
anywhere, so no grep over the deleted directory could have reached them — see the addendum below.
The total is seventeen.**

- **A module-level `from apps.proxy.live_proxy…` fails collection and reddens the whole label.**
  Nine files: `apps/channels/tests/{test_channel_stream_reuse, test_get_stream_assignment,
  test_ts_proxy_ghost_clients, test_ts_proxy_initializing, test_ts_proxy_teardown}.py` and
  `apps/proxy/tests/{test_boundary_error_arms, test_combined_stats, test_relay_status_shape,
  test_stream_switch}.py`.
- **A function-local import or a `mock.patch("apps.proxy.live_proxy…")` string fails only that
  test, at run time.** Four files: `apps/channels/tests/{test_recording_pipeline,
  test_ts_proxy_keepalive, test_ts_proxy_keepalive_duration}.py` and
  `tests/test_websocket_consumer_filter.py`. **A10.14 lists the two keepalive files among its
  collection-breakers and they are not** — both have only function-local imports
  (`test_ts_proxy_keepalive.py:25`, `:76`, `:207`, `:266`; `test_ts_proxy_keepalive_duration.py:15`),
  and `test_recording_pipeline.py` and `test_websocket_consumer_filter.py` are not on A10.14's list
  at all. Corrected in place by A14.3.
- **An assertion that goes false.** Two files, neither of which imports or patches anything:
  `tests/test_ci_test_routing.py` (3 of 5 tests fail — they assert the label
  `apps.proxy.live_proxy.tests` exists) and `core/tests/test_fetch_channel_stats.py` (stays green,
  goes tautological).

Command: a classifier over every `*.py` outside the package, written to the scratchpad, printing
import / patch-string / other counts per file. Its output is Appendix A.1's provenance and Task 0
Step 3 re-runs it.

**The four labels: `apps.channels.tests`, `apps.proxy.tests`, `core.tests` and the bare `tests`.**
Two of them — `apps.channels.tests` and `apps.proxy.tests` — are in
`.github/workflows/backend-tests.yml:180`'s coverage matrix, so `coverage-gate` fails with them on
top of the plain `test` matrix.

**The disposition table.** Three shapes, per A10.14: **KEEP** (re-point the import; the subject is
Django's), **SPLIT** (keep one class, delete another in the same file), **DELETE** (the subject is
gone). Every DELETE names its Go cover or says there is none.

| # | File | Tests | Label | Disposition | Why |
|---|---|---|---|---|---|
| 1 | `apps/channels/tests/test_channel_stream_reuse.py` | 7 | channels | **KEEP**, one import line | Every test drives `Channel._stream_assignment_is_reusable()` with `relay_client.channel_snapshot` mocked. `RedisKeys` → `apps.proxy.redis_keys`. Its fake Redis implements only `get` — proof the metadata ranges R8 deletes are unreachable from it. |
| 2 | `apps/channels/tests/test_get_stream_assignment.py` | 5 | channels | **KEEP**, two import lines | Subject is `Channel.get_stream()` / `_release_stale_stream_assignment()`. Uses `ChannelState.{ACTIVE,WAITING_FOR_CLIENTS,BUFFERING,INITIALIZING,CONNECTING,STOPPED}` and `ChannelMetadataField.STATE`, all present in `apps/proxy/constants.py`. |
| 3 | `apps/channels/tests/test_recording_pipeline.py` | 29 | channels | **KEEP**, two patch strings | One of 29 tests touches `live_proxy`, and only as `@patch("apps.proxy.live_proxy.config_helper.ConfigHelper.…")`. The shim re-exports the **same class object**, so re-pointing to `apps.proxy.config_helper` is behaviour-identical, not merely equivalent. Subject is `apps/channels/tasks.py:1121-1128`, which 2d-1 already re-pointed. |
| 4 | `apps/channels/tests/test_ts_proxy_ghost_clients.py` | 13 | channels | **DELETE** | All thirteen drive `ClientManager.remove_ghost_clients` and the two `ChannelStatus` builders. The ghost sweep is **deliberately deleted, not ported** (spec D2 / 2c-3: the Go client registry is a process-memory map with no TTL and no heartbeat, so a client entry cannot outlive the goroutine that made it). Go cover for the surviving half — idempotent registration — is `relay/channel/fanout_test.go::TestASecondAttachUnderAnAttachedClientIDIsRefused` and `relay/httpapi/fanout_test.go::TestADuplicateClientIDIsRefusedAtTheTuneSurface`; **the sweep itself has no Go analogue and none is wanted.** Parity-matrix row 13's Notes name this file as "the partial cover the spec records" and are rewritten by R11. |
| 5 | `apps/channels/tests/test_ts_proxy_initializing.py` | 21 | channels | **SPLIT** | `StreamManagerFinallyBlockTests` (14) drives `StreamManager.run()`'s finally block, whose every assertion is about **ownership arbitration between two uWSGI workers** — D2 deletes the mechanism. Go cover for the state outcomes: `relay/channel/manager_test.go::TestAnUpstreamFailurePutsTheChannelInError`, `relay/channel/failover_test.go::TestAnExhaustedChannelEndsInErrorNamingTheCount` (the direct analogue of `test_error_message_includes_stream_count`); **no Go analogue for the lease half, and there cannot be one.** `PreActiveStateTests` (7) pins `ChannelState.PRE_ACTIVE`'s membership and frozen-ness — a constant 2d-1 relocated — and is **kept**, re-pointed. See the note below on why it is kept although its production reader dies. |
| 6 | `apps/channels/tests/test_ts_proxy_keepalive.py` | 19 | channels | **SPLIT** | 17 of 19 drive `output/ts/generator._should_send_keepalive` (owner and non-owner branches) and `client_manager._do_stats_update` / `remove_client`. Go cover: `relay/httpapi/keepalive_test.go::TestAnUnhealthyChannelSendsKeepalivesAtTheBufferHeadAndAHealthyOneDoesNot` (whose header comment cites `output/ts/generator.py:387-405, :542-551` by line — the exact code these test), plus `::TestHealthyOnTheListPayloadFollowsTheHealthMonitor` and `::TestAClientWithNoBytesGetsAnErrorPacketWhenEverySourceFails`. **No Go analogue** for the non-owner branch (there is no non-owner), for `_do_stats_update`'s WebSocket fan-out (the Go relay posts to `/api/relay/events`; `relay/httpapi/events_test.go`) or for `remove_client`'s non-blocking latency assertion. `KeepaliveTimingTests` (2) imports `apps.proxy.config.TSConfig` and **no `live_proxy` name at all** — it survives with zero edits, and the file is therefore kept with 17 tests removed rather than deleted. |
| 7 | `apps/channels/tests/test_ts_proxy_keepalive_duration.py` | 4 | channels | **DELETE** | All four drive `StreamGenerator._stream_data_generator`'s keepalive cap through five patched attributes of a dying module. Go cover: `relay/httpapi/keepalive_test.go::TestAClientIsDroppedOnceTheKeepaliveCapIsReached`; the "cap comes from config, not a literal" property is covered structurally by `relay/httpapi/fanout_test.go::TestTheTwoPortedConstantsMatchTheirPythonLiterals`. The fourth test (`test_timer_resets_when_real_data_resumes`) **asserts nothing** — its body ends in a comment reading "Test passes if no exception" — so it is not a loss. |
| 8 | `apps/channels/tests/test_ts_proxy_teardown.py` | 52 | channels | **DELETE** | The largest file in the set (1,034 lines) and the one `dispatcharr/test_discovery.py:33-36` names as the reason the `apps/proxy/live_proxy/` alias exists. All 52 tests are multi-worker teardown coordination: local-vs-remote registries, `_broadcast_upstream_stop` pub/sub, the owner lease, the orphan sweep, `_spawn_on_hub`. Go cover exists for the *outcomes*: `relay/channel/fanout_test.go::TestTheShutdownDelayKeepsAChannelForAReconnectingClient` / `::TestAClientArrivingAsTheLastOneLeavesKeepsItsChannel` / `::TestADelayedStopNeverEvictsAReplacementChannel`; `relay/httpapi/control_test.go::TestDeletingAChannelStopsItAndReportsItsPreviousState`; `relay/channel/manager_test.go::TestAReleaseCannotStopAChannelAConcurrentAttachJustJoined` / `::TestAFinishedChannelIsNotHandedToANewClient` / `::TestAChannelWithFlowingBytesBecomesActive`; `relay/channel/failover_test.go::TestTheSlotIsReleasedOnceWhenTheSourceGoroutineReturns`. **No Go counterpart, and none is possible**, for the nine classes about *which process* owns a channel — parity-matrix rows 26 and 27 are exactly this territory and both say "Deleted, not ported." Two behaviours have no cover on either side and are recorded as gaps rather than claimed: `_init_wait_abort_reason`'s "stalled" arm and `_pre_active_no_clients_should_stop`'s two-timeout selection. See the `release_source` note below. |
| 9 | `apps/proxy/tests/test_boundary_error_arms.py` | 15 | proxy | **SPLIT**, and this is the most load-bearing KEEP in the set | Its docstring says it exists to cover "error arms in already-96%+ **boundary modules**" — i.e. the very modules Gate 2 measures after this PR. 13 of 15 tests drive `apps/proxy/{config_helper,config,authorize,control_plane,relay_client}.py`, all surviving. `LiveProxyAppsReadyTests` (2 tests, `:45-64`) drives `LiveProxyConfig.ready()` and is deleted with it; no Go analogue and none needed. The one import, `:15`, re-points to `apps.proxy.config_helper`. |
| 10 | `apps/proxy/tests/test_combined_stats.py` | 7 | proxy | **SPLIT** | `BuildLiveChannelStatsDataTests` (3) drives `build_live_channel_stats_data`'s Redis SCAN and dies with it — Go cover for the payload is `relay/httpapi/golden_test.go::TestTheListPayloadMatchesDjangosSerializer` and `::TestEveryOptionalFieldIsAbsentRatherThanNull`, and for the client cap `relay/httpapi/fanout_test.go::TestTheClientListIsCappedAtTenUnlessClientsAllIsAsked`; **the SCAN enumeration itself has no Go analogue, which is the point of D2.** `CombinedStatsApiTests` (4) drives `apps/proxy/stats_views.py` through `relay_client.list_channels` and does not use the dying import at all. |
| 11 | `apps/proxy/tests/test_relay_status_shape.py` | 10 | proxy | **DELETE**, with one assertion re-homed | All ten drive the two `ChannelStatus` builders directly against a hand-rolled fake Redis, asserting the raw dict before any serializer. There is no Python successor: `relay_views.py` is their *caller*, not a reimplementation, and R1 deletes it. Nine of the ten assertions are independently pinned in Go (`relay/httpapi/detail_golden_test.go::TestOwnerAndSourceFPSDifferBetweenTheTwoEndpoints` for the `ffmpeg_speed` float; `relay/httpapi/control_test.go:83-84,152,164-165,174` for `state` null-vs-present; `::TestTheClientListIsCappedAtTenUnlessClientsAllIsAsked` for the 10/all/true-count trio; `relay/httpapi/detail.go:159-161`'s `string`+`omitempty` for the three DVR fields). **One is orphaned on both sides** — `width`/`height`/`video_bitrate` must be *absent* when unset — and **Task 7 Step 4** re-homes it into `relay/httpapi/detail_golden_test.go` as `TestTheDetailPayloadOmitsTheDVRVideoFieldsWhenNothingSetThem` — the DETAIL golden, because the three fields exist on the detail payload alone — rather than letting it go. Its break-check is one struct tag (Task 7 Step 4b, run). |
| 12 | `apps/proxy/tests/test_stream_switch.py` | 11 | proxy | **SPLIT** | `OwnerPathTests` + `NonOwnerPathTests` (9) drive `ChannelService.change_stream_url`'s owner/follower split and the `live:events:` confirmation protocol — no successor; Go cover for the outcomes is `relay/httpapi/advance_test.go::TestAnAdvanceSwitchesTheChannelAndKeepsTheClientFed`, `::TestAnAdvanceToTheURLAlreadyPlayingSucceedsAndSwitchesNothing`, `::TestAnAdvanceRefusesAMalformedBodyAndAnUnknownChannel`, `relay/httpapi/control_test.go::TestTheNamesComeOffTheWireAndAreAbsentWhenTheAnswerCarriedNone`; **no Go analogue for the follower confirmation protocol**, and the HTTP statuses it produced (504 unconfirmed, 502 reported failure) are pinned on the Django side by `test_admin_control_views.py`, which survives. `ChangeStreamViewTests` (2) drives `ts_admin_views.change_stream`'s integer coercion and is **kept**, minus two now-vestigial `patch.object(views_module.ProxyServer, …)` lines: since 2d-2 the view's `ProxyServer` import is function-local in `ts_admin_views`, so those patches already reach a module the view under test does not touch. |
| 13 | `tests/test_websocket_consumer_filter.py` | 23 | tests | **KEEP**, three patch strings | See R3. All 23 drive `dispatcharr/consumers.py`. |
| 14 | `tests/test_ci_test_routing.py` | 5 | tests | **REWRITE**, 2 tests changed | Consequence of R10's two `_PATH_ALIASES` edits, not of an import. See R10. |
| 16 | `apps/proxy/tests/test_relay_control_api.py` | 23 | proxy | **DELETE** | **Found by executing the plan.** It imports `relay_views` at `:20` and patches `relay_views.ProxyServer` at `:84`/`:97`, and contains **no `live_proxy` reference at all** — it is broken by **R1's own ruling**, not by the deletion, so the classifier was structurally unable to find it. Its subject is the five `/proxy/relay/…` routes R1 deletes. Go cover: `relay/httpapi/control_test.go` for the routes' behaviour, `relay/httpapi/golden_test.go` and `detail_golden_test.go` for their payloads, pinned against Django's own serializer. |
| 17 | `apps/proxy/tests/test_internal_base_url.py` | 8 | proxy | **REWRITE**, 1 test + 1 rename | **Found by executing the plan**, same blind spot: it pins `get_relay_control_base_url()` at `http://127.0.0.1:5656` in dev, which is exactly the property R1's `dev_url` change breaks. `test_dev_is_the_single_runserver_process` becomes `test_dev_names_the_go_relay_in_one_direction_and_django_in_the_other` and asserts **both** directions — the better pin, since the half a careless edit breaks silently is `control_plane`'s. Its sibling `…_share_one_address_and_differ_only_in_override` is renamed `…_outside_dev_and_…`, because that is now what it asserts. |
| 15 | `core/tests/test_fetch_channel_stats.py` | 4 | core | **KEEP**, one test's docstring | Three tests are untouched. `test_core_tasks_no_longer_imports_a_relay_module_at_module_level` stays **green** but becomes tautological — it asserts the absence of a module that no longer exists anywhere. Kept, with one sentence added to its docstring saying so, because deleting it would remove the only guard against `core/tasks.py` growing a module-level relay import again, and `apps.proxy.relay_client` (which it must *not* import at module level, for the reason `:5-7` gives) is still a module it could import. |

**Net: 5 deleted whole, 5 split, 5 kept, 2 rewritten** — the four labels in the table above,
counted. Two of those five keeps are worth naming because the bucket is not uniform: rows 1, 2, 3
and 13 are kept by **re-pointing an import or a patch string**, while row 15
(`core/tests/test_fetch_channel_stats.py`) is kept by adding **one docstring sentence** and has
nothing to re-point. The two rewrites are rows 14 and 17, both of which change assertions rather
than imports. (An earlier draft said "6 kept by re-pointing, 1 rewritten", which matched neither
the table's labels nor row 15's actual edit.) Test-count effect,
measured by counting `def test_` in each deleted region:

| Label | Removed | Added | Net |
|---|---|---|---|
| `apps.proxy.live_proxy.tests` | **406** — the whole label (53 test files) | — | label ceases to exist |
| `apps.channels.tests` | **100** (13 + 14 + 17 + 4 + 52) | **1** (R8's break-check) | −99 |
| `apps.proxy.tests` | **24** (2 + 3 + 10 + 9) | — | −24 |
| `tests` | **4** (1 in `test_ci_test_routing.py`, 3 in `test_urls_xc_three_segment.py`) | **1** (R6's new catch-all assertion) | −3 |
| `core.tests` | — | — | 0 |

The 406 figure is A12.6's, measured one PR ago; the spec's "~564 tests" in the deletion-list entry
predates 2d-2 moving a 23-test file out of the package and is left as the historical measurement it
is. Task 12 re-measures every label rather than asserting any of these.

**The addendum, and the lesson it generalises to.** Rows 16 and 17 were not in the classifier's
output and could not have been: it searched for files naming the deleted *directory*, and these two
name things **R1's own rulings** remove. A deletion's blast radius is the files that name the
deleted thing **plus** the files that name anything else the deletion forces you to remove — and
only executing the plan finds the second set. Both are recorded in Amendment A14.3.

**Two notes the table is too narrow for.**

*Why `PreActiveStateTests` (file 5) is kept although nothing reads `PRE_ACTIVE` after this PR.*
`ChannelState.PRE_ACTIVE`'s only production reader is the dying `input/manager.py` finally block, so
after 2d-4 these seven tests pin a constant nothing uses. The alternative is deleting the constant
from `apps/proxy/constants.py` and the tests with it. **Declined**: 2d-1 moved `ChannelState` whole
into a Django-owned module eight days ago on the explicit ground that surviving code imports it, the
frozenset is four lines, and a constant with a shape test is cheaper to keep than to re-derive if a
Phase 3 reader wants it. Recorded here so nobody discovers it as an oversight. It is on the post-2d
list.

*The one surviving contract inside `test_ts_proxy_teardown.py`.* `CleanRedisKeysOrderTests` (3 of
its 52 tests) patches `apps.proxy.control_plane.release_source` — a **surviving** module — and
asserts the exact call `release_source(CHANNEL_ID, stream_id=…, m3u_profile_id=…, channel_pk=…)`.
That contract is not lost with the file: it is independently pinned on both sides, by
`apps/proxy/tests/test_next_source_api.py::ReleaseRouteTests::test_release_frees_metadata_ids_when_identifier_resolves_to_neither_row`
(which passes exactly those three keys over HTTP) and by
`relay/control/release_test.go::TestReleaseSendsAllThreeKeysAndReadsTheFlag` /
`::TestReleaseFollowsTheDispositionTable`. Verified by reading all five.

### R8 — #190's five metadata-hash ranges are deleted, and the delete gets the break-check the suite cannot give it

A10.17 rules that [#190](https://github.com/D10Scot/Dispatcharr/issues/190) "closes only if 2d-4
deletes those five ranges", all in `apps/channels/models.py`, a file 2d does not delete. Measured at
this seed (`grep -n "ChannelMetadataField\|channel_metadata" apps/channels/models.py`):

| Range | Method | What |
|---|---|---|
| `:515-519` | `_release_stale_stream_assignment()` | read — `hget(metadata, M3U_PROFILE)`, reached only when `get(RedisKeys.stream_profile(stream_id))` returned nothing |
| `:694-702` | `release_stream()`, fallback branch | read ×2 — `hget(metadata, STREAM_ID)` and `hget(metadata, M3U_PROFILE)`, reached only when `get(RedisKeys.channel_stream(self.id))` is falsy |
| `:715-721` | `release_stream()`, fallback branch | write — `hdel(metadata, STREAM_ID, M3U_PROFILE)` after that recovery |
| `:745-750` | `release_stream()`, primary branch | read — `hget(metadata, M3U_PROFILE)`, reached only when the `stream_profile:<id>` key is missing |
| `:771-778` | `release_stream()`, primary branch | write — the **unconditional** `hdel` at the end of every successful release |

After 2d-3 every read returns `None` and every `hdel` is a no-op, because the Go relay writes no
`live:channel:*:metadata` key. **Ruling: delete all five, and with them `apps/channels/models.py:7`'s
`from apps.proxy.constants import ChannelMetadataField`** — measured, that import has no other user
in the file, so removing the five ranges removes half of 2d-1's boot trap as a side effect. (It does
**not** remove the trap: `:6`'s `RedisKeys` import stays, reached at twenty-six sites, and the
`models_boot_trap_imports` metric — which counts `apps.proxy.live_proxy` imports specifically — has
read 0 since 2d-1 and is unaffected either way.)

**The delete is test-invisible, and that cuts both ways.** Exhaustively checked: **no test in the
tree would fail if all five ranges were deleted.** Three independent confirmations, each verified by
reading the test rather than grepping it:

1. Every caller of `release_stream()` / `_release_stale_stream_assignment()` in the suite seeds the
   *primary* Django-owned keys (`channel_stream:<pk>`, `stream_profile:<id>`), which is exactly the
   branch that skips all four fallback reads — `apps/m3u/tests/test_connection_pool.py:374-375`,
   `apps/channels/tests/test_get_stream_assignment.py:91-93`.
2. Nothing asserts the `hdel`. A tree-wide `grep -rn "hdel"` over `apps/`, `core/` and `tests/`
   returns the two production sites, timeshift's unrelated ones, and exactly one test-side
   occurrence: `apps/proxy/tests/test_next_source_api.py:52`'s `FakeRelayApiRedis.hdel`, a
   tolerance stub whose own comment says it exists so a real release "won't error".
3. The fakes say so themselves. `test_channel_stream_reuse.py`'s `_Redis` has no `hget` at all, and
   `test_next_source_api.py:46-49` states outright that "no metadata hash is ever seeded in these
   tests."

**So the plan ships a break-check rather than relying on a green run** (Task 5). `MetadataOnlyReleaseTests`
in `apps/channels/tests/test_get_stream_assignment.py` seeds **only** the metadata hash — no
`channel_stream:` and no `stream_profile:` key — and asserts two things: that `release_stream()`
returns `False` **and does not release a provider slot**, and that the hash is left exactly as it was
found. The second needs an `hdel` on that file's fake Redis, which it did not have — and its absence
was itself one of the three proofs above, so the test that observes these ranges is the test that
adds it.

**The reversion that bites is the `:694-721` RECOVERY BRANCH, not the `:745-750` read**, and an
earlier draft of this ruling named the wrong one: with no `channel_stream:` key seeded,
`release_stream()` takes the first branch and never reaches `:745-750` at all. **Run**, restoring
`:694-721`:

```
FAIL: test_a_metadata_only_assignment_is_no_longer_recoverable
    self.assertIs(self.channel.release_stream(), False)
AssertionError: True is not False
FAIL: test_the_metadata_hash_is_left_exactly_as_it_was_found
AssertionError: {} != {'stream_id': '5922', 'm3u_profile': '404'}
Ran 2 tests in 0.030s
FAILED (failures=2)
```

**The ledger row is NOT flipped here.** `metrics/curated/defects.yml`'s
`release-stream-relay-key-fallback` row is `status: open`; `metrics/build/curated.py:316-317`
requires a `fixed` row to carry `fixed_in`, and `:326-327` checks that PR number is **merged** — a
PR cannot name itself. The row is 2d-6's, exactly as #273's and #295's are. Stated in the PR body so
the omission is a decision.

### R9 — Gate 2 (Python): the rcfile loses two include lines, `--shape-only` re-baselines both hashes, and the gate is slack until 2d-5

`scripts/coverage_live_path.coveragerc:23-34`'s `[report] include` names `apps/proxy/live_proxy/*`
plus ten files. After this PR the glob matches nothing and one of the ten
(`apps/proxy/relay_views.py`, R1) no longer exists. **Ruling: both lines are removed here**, and
the surviving module list is **nine**:

```
apps/proxy/authorize.py        apps/proxy/internal_base_url.py   apps/proxy/relay_client.py
apps/proxy/authorize_views.py  apps/proxy/next_source.py         apps/proxy/relay_serializers.py
apps/proxy/control_plane.py    apps/proxy/permissions.py
apps/proxy/internal_auth.py
```

**This refines the spec's PR-5 entry, which assigns the rcfile edit to 2d-5** (Amendment A14.5).
Reason: `--write-floor --shape-only` recomputes `modules=`, `module_count=` **and** `rcfile=` in one
command (`scripts/coverage_live_path.sh:458-540`), so doing both here costs nothing and leaves no
config line pointing at a deleted directory — the same dangling-reference class this PR closes in
the guards, the defect ledger and two workflows. What stays genuinely 2d-5's is `missing`: the
*number*, which is the whole substance of "re-scope", and which needs the worst of ≥12 CI rounds on
a tree that can only exist after the delete.

**The predicted hashes, and why the plan does not ask the implementer to type them.** The gate hashes
`sorted(json["files"].keys())` with `sha256(...).hexdigest()[:12]`
(`scripts/coverage_live_path.sh:216-236`). Computed over the nine paths above that is
**`7804792af4f7`, 9 files**; over ten (if `relay_views.py` were kept) it would be `e76dc7dcf590`.
These are *predictions from the include list*, not measurements of coverage's own resolution, so
**Task 9 takes the value from `--write-floor --shape-only`'s own output and compares it with the
prediction, STOPping and naming both if they differ.** A disagreement means coverage resolved a file
the include list does not obviously name, which is a finding, not a number to overwrite.

**`missing` stays at `1525` and the floor says why.** `--shape-only` calls `read_totals()` not at
all (`:440-455`), so there is no ratchet figure to refuse or accidentally accept. The floor's header
gains one sentence, in Appendix H.2: *the gate is deliberately slack between 2d-4 and 2d-5 — a floor
of 1525 over a denominator of roughly a tenth its former size is mechanically green and
substantively toothless, and `migration/phase2d-gate2-recensus` is the PR that makes it real.*

**A measurement run is still required.** `--shape-only` skips `read_totals()` but still calls
`read_modules()`, which reads `live-path.json` — so `report()` must have run. Task 9 does one clean
isolated round first. `scripts/coverage_live_path_isolated.sh:25-28`'s label list loses
`"liveproxy:apps.proxy.live_proxy.tests"` and becomes two entries; that edit is part of R10.

**Statement-count drift is expected and not compared.** `statements` is recorded provenance
(`CLAUDE.md` § Testing). It falls by the whole of `relay_views.py` plus every re-pointed line, and
rises by R1's `dev_url` parameter in `internal_base_url.py` — a handful of statements in a module
inside the denominator. Neither is checked.

### R10 — sixteen labels become fifteen, and six places know the number

`dispatcharr/settings.py:107`'s `INSTALLED_APPS` entry is the mechanism:
`dispatcharr/test_discovery.py` AST-parses that list. Measured by running
`iter_test_package_labels()` directly at the seed: **16** labels, the bare repo-root `tests`
directory among them. After this PR: **15**.

| Site | Edit |
|---|---|
| `dispatcharr/settings.py:107` | the `"apps.proxy.live_proxy"` entry is removed (R5) |
| `dispatcharr/test_discovery.py:57` | the `_PATH_ALIASES` entry `("apps/proxy/live_proxy/", ("apps.proxy.live_proxy", "apps.channels"))` is **removed** — the path it maps no longer exists |
| `dispatcharr/test_discovery.py:58` | the `("scripts/coverage_live_path", …)` alias drops `"apps.proxy.live_proxy"` and becomes a **two**-label alias. **It must keep working**: it is what stops an edit to Gate 2's own script, rcfile, floor or floor companion from selecting zero labels, and 2d-5 edits exactly those files |
| `dispatcharr/test_discovery.py:33-36` | the `_PATH_ALIASES` header comment's `apps/proxy/live_proxy/` paragraph, which cites `test_ts_proxy_teardown.py` by name, is removed with the alias |
| `tests/test_ci_test_routing.py:44-56` | `test_live_proxy_change_runs_channels_tests` is **deleted** — its subject directory is gone |
| `tests/test_ci_test_routing.py:58-81` | `test_coverage_gate_script_change_runs_its_own_three_labels` is renamed to `…_its_own_two_labels` and its `expected` set shrinks to two |
| `.github/workflows/backend-tests.yml:180` | the coverage matrix drops `apps.proxy.live_proxy.tests`, leaving `[apps.proxy.tests, apps.channels.tests]` |
| `scripts/coverage_live_path_isolated.sh:25-28` | the label list drops `"liveproxy:apps.proxy.live_proxy.tests"` |
| `.claude/hooks/run-affected-tests.sh:147-149` | the boot-check `case` arm drops its three `apps/proxy/live_proxy/…` shim paths, keeping the three `apps/proxy/…` homes 2d-1 added. The arm matches **by literal path**, which is exactly how this guard would be lost silently |

`scripts/ci_backend_test_labels.py` needs **no** edit: it lists no labels, it loads
`test_discovery.py` by path and delegates (`:36-37`). That is the property that makes the commit
gate and CI unable to disagree, and this PR relies on it rather than editing two lists.

### R11 — the parity matrix's Source column, and rows 26 and 27 get a `retired:` sentinel the guard learns to read

**The breakage, measured.** `e2e/tests/guards/parity-matrix.spec.ts` is the **only** thing in `e2e/`
that mechanically depends on `apps/proxy/live_proxy/` existing; every other `live_proxy` mention in
the tree (28 hits across 13 files) is a comment or a `COVERAGE.md` citation that no guard reads.
Two of its seven tests go red:

- `'every row cites source that resolves'` (`:196-224`) → **53 findings**, one per deleted-file
  citation, across **21 rows**, each reading `no such file: apps/proxy/live_proxy/<path>`; and
  **18 of those rows** would additionally hit the separate zero-citation branch at `:202-209`.
- `'every pin resolves'` (`:226-263`) → **38 findings** across **26 rows**, each
  `pin names no such file: apps/proxy/live_proxy/tests/test_*.py`.

Every figure in A10.5 is **confirmed exactly at this seed** — 30 rows; 86 Source citations of which
53 are under the deleted directory; 38 Python pins, all of them there; 37 Go pins; 24 distinct
`live_proxy` paths (10 in Source, 14 in Pin, disjoint); and the eighteen-row list 1, 2, 4, 5, 6, 7,
8, 9, 10, 11, 12, 13, 15, 18, 26, 27, 28, 29. Zero citations are broken today, so every breakage is
this PR's own.

**The Pin column is the easy half.** All 26 rows carrying a `live_proxy` Python pin also carry at
least one Go pin, so dropping all 38 leaves every row pinned and `GO_PARITY_CLOSED`
(`parity-matrix.ts:598`) still satisfied — which is not luck: that flag asserts exactly this
property, and its own doc comment at `:592-596` was written for this PR ("the property cannot
silently reopen when 2d starts deleting Python").

**The Source column is the hard half, and the ruling is that it names where the behaviour LIVES.**
On each of the 21 rows, the `live_proxy` citations are replaced by citations into `relay/`; any
non-`live_proxy` citation already on the row is kept in place. Appendix E carries all 21 cells, by row id.

**Rows 26 and 27 need a decision, not an edit** — A10.5 says so, names three candidate shapes and
asks that the third be argued hardest against. Their Source cells cite nothing but
`apps/proxy/live_proxy/server.py` (four citations on row 26, one on row 27), they are `white-box-only`
so `testRefProblem` never sees their Pin, and the Source check has **no** white-box exemption
(`parity-matrix.spec.ts:202-207` pushes a finding when `citations.length === 0`). Both are
"deleted, not ported" behaviours with, by construction, no Go source to point at: row 26 is
`server.py`'s greenlet/OS-thread topology, which D2 replaces with goroutines and a `sync.RWMutex`;
row 27 is `_execute_redis_command` swallowing every Redis exception to `None`, and D2 removes Redis
from the live path entirely, so there is no analogous call to swallow anything.

- **(c) exempt `white-box-only` rows from the Source check.** *Argued hardest against, and refused.*
  `WHITE_BOX_ONLY` is compared with `toEqual` because, in `parity-matrix.ts:513-522`'s own words,
  "this marker is the one word that can make an inconvenient row stop counting, so both adding and
  removing one must be a deliberate edit with a stated reason." Widening what that word exempts is
  the same move one level up, and it is worse than the original in two ways: it is **retroactive**
  (every future white-box row silently stops needing a citation, with no edit anywhere to notice)
  and it **conflates two properties** — "no black-box test can reach this" and "this code no longer
  exists" — which are independent. Row 12's fMP4 timeout is white-box-adjacent and very much still
  exists in Go.
- **(b) re-point both Sources at a surviving file describing the same mechanism.** Refused as
  dishonest for row 27 in particular: the Source column means "where the behaviour lives", and
  citing a Go file as the source of a behaviour the Go relay does **not** have inverts the column.
  Measured, there is no surviving file for either: `grep -rn "_spawn_on_hub" --include='*.py' .`
  returns four files, all inside the deleted package except
  `apps/channels/tests/test_ts_proxy_teardown.py`, which R7 deletes; row 27's only surviving
  external description is `CLAUDE.md`'s fail-open sentence, which R15 rewrites in this same PR.
- **(a) teach the guard a `retired:` Source form.** **Chosen.** It matches the matrix header's own
  retirement convention (`docs/relay-parity-matrix.md:10-11`: an id is never reused or renumbered;
  a retired row keeps its id and says so in its Notes), which today is prose the guard cannot read.
  And it is built to answer (c)'s objection head-on rather than to dodge it: the new form is backed
  by a **`RETIRED_SOURCES` allowlist constant compared with `toEqual`**, in `WHITE_BOX_ONLY`'s exact
  idiom — an array of `{id, why}`, with the same two sibling assertions (the row's Notes cell must
  be non-empty; the entry's `why` must be non-empty). So the one word that makes a row stop needing
  a citation is itself counted, and adding one is as deliberate an edit as adding a white-box
  marker. Appendix F carries the guard change, the constant and the three assertions.

`GATE_1_CLOSED` (`:570`), `GO_PARITY_CLOSED` (`:598`) and `HIGHEST_ROW_ID` (`:552`) need no change
under this scheme, and `GATE_1_CLOSED` is what forbids the other escape hatch — reopening a row to
`owed:` rather than re-pointing it.

**Two honesty caveats carried into the rows' Notes rather than smoothed over**, because the Go
citation is genuinely weaker than the Python one it replaces:

- **Row 4** (`speed=` is a cumulative average since process start). The behaviour is **ffmpeg's own**
  and is implemented in neither relay — the row's existing Notes already say so about the Python
  code. The new Source citation is the *observation* site, not an implementation, and the Notes say
  that in one added sentence.
- **Row 13** (client registration idempotent; ghost sweep on a stale heartbeat). The Go citation
  covers the **first clause only**. The row's Notes already record that "Row 13's second half has
  two mechanisms and neither has a Go analogue … deleted rather than ported (2c-3)"; one sentence
  is added saying the Source cell therefore cites the surviving half, and that
  `apps/channels/tests/test_ts_proxy_ghost_clients.py`, which the Notes name as the partial cover,
  is deleted by this PR.

**One thing found and deliberately not fixed.** Row 15's Source cites `views.py:825` and
`:845-851`, which have described `stream_ts`'s exception handler rather than `stream_xc`'s hand-off
since **2b-2** (`04841a47`) shifted the file by 38 lines. The guard cannot see it — it checks that a
line exists, never that it is the right line (`parity-matrix.spec.ts:43-46` says so). The
replacement Source cell describes the hand-off correctly, so the drift is repaired as a side effect;
it is recorded here only so a reader reconciling old cells against new does not conclude the new
ones moved something. A10.5 does not mention it.

### R12 — the ffmpeg stderr corpus moves into the Go module, and the Go coverage gate provably does not move

A10.6's functional coupling: `relay/internal/relaytest/corpus.go:56-57` builds
`<repo>/apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/<name>.stderr` and **panics**
rather than skipping if it cannot read it (`:67`). **13** Go test lines read it in-process
(`Corpus` ×4, `CorpusSpeeds` ×8, `CorpusElapsed` ×1) and **11** more hand `CorpusPath(...)` to the
exec'd stand-in, which opens the same absolute path in a child process (`standin.go:381`). A10.6's
two counts are exact at this seed.

**Ruling: `git mv` the four fixture files — `CAPTURE.md`, `normal.stderr`, `slow-trickle.stderr`,
`truncation.stderr`, 26,180 bytes — into `relay/internal/relaytest/testdata/ffmpeg_stderr/`, and
change one expression in `corpus.go`.** The "never copied, read in place" rationale in its header
(`:13-22`) evaporates the moment there is no second copy to diverge from, and it is rewritten to say
so rather than deleted.

**The mechanics, measured rather than assumed** (a three-package probe reproducing the exact
topology was built and run in the scratchpad; results in Appendix D.1's preamble):

- A bare relative string `"testdata/ffmpeg_stderr/x.stderr"` is **wrong here** and was confirmed
  wrong by running it: `go test` sets the working directory to the **calling** package's directory,
  so it resolves against `relay/ffmpeg`, `relay/httpapi` or `relay/channel` and fails with
  `no such file or directory`. `relay/httpapi/golden_test.go:23`'s bare `"testdata/…"` is safe only
  because it is same-package, and is **not** a model to copy here.
- `runtime.Caller(0)` is the answer, and `corpus.go` **already uses that idiom** — `repoRoot()` at
  `:28-39` is a four-deep `filepath.Dir` walk from this file's own path, and its own comment gives
  precisely this reason. The edit shortens it: a one-deep `pkgDir()` beside it, with `RepoRoot()`
  re-expressed on top so there is a single `runtime.Caller` call site.
- The return value **stays absolute**, which is load-bearing: the 11 `CorpusPath` sites pass it
  through argv to a re-exec'd child that `os.ReadFile`s the string verbatim and has no cwd of its
  own to resolve against.
- `testdata/` under a Go package is the right home and being reached from a non-`_test.go` file does
  not matter: `go help packages` — "directories named 'testdata'" are ignored by the go tool — so it
  adds no package, and the data is read at runtime via `os.ReadFile`, with no build-time dependency.
  `go build ./...`, `go vet ./...`, `golangci-lint` (whose default `exclude-dirs` includes
  `testdata$` and whose config is at the repo root, naming none) and
  `scripts/check_go_stdlib_only.sh` (three checks: `go.sum` empty, `go list -m all`, a redis grep
  over `go list -deps ./...`) are all unaffected — each verified against the probe.
  **`relay/httpapi/testdata/` already exists**, so this is house practice, not a new pattern.
- **Zero test-file edits.** All 24 call sites pass a *name*, never a path.
- One inherited fragility, stated so it is not introduced by accident: `-trimpath` breaks any
  `runtime.Caller`-derived path (measured). It appears **once** in the repo, at
  `docker/Dockerfile:50`, on a `go build` of the production binary — never on a `go test`. Nothing
  in `go-tests.yml`, `.claude/hooks/run-go-checks.sh` or `.golangci.yml` passes it. The invariant to
  preserve is "no `-trimpath` on a test invocation"; this PR neither introduces nor worsens it.

**`RepoRoot()` survives**, because `relay/drain/drain_test.go:40` reads
`docker/supervisord.d/relay-go.conf` through it — and after 2d-3 a second Go test does too
(2d-3's `relay/drain/supervisord_priority_test.go`). After the corpus move that is the module's
**only** repo-relative read.

**`asset_test.go`: the digest pin is deleted with its reason; the length and the two `upstream.py`
values are kept as constants with their derivation.** `relay/internal/relaytest/asset_test.go:9-16`
states the digest's whole purpose — it was produced by the Python harness's `synthetic_ts()`, "so it
proves the two implementations agree rather than that this one is deterministic (hollow shape 1)."
Once one implementation is gone it proves only that `SyntheticTS` is deterministic, which
`parity-matrix.ts`'s own vocabulary calls a hollow test. The 96,256-byte length assertion at `:20`
and the two `upstream.py` pins at `:71-83` stay, with their **derivations** rather than bare digits
in the comment — `NominalByteRate = 250000` is `2_000_000 // 8`, 2 Mbit/s, the bitrate
`e2e-upstream/scripts/make-asset.sh` builds its own asset at (a **surviving** file, which is the
right provenance anchor); `WriteChunk = 9400` is `TS_PACKET_SIZE * 50`. Appendix D.1 carries both
files.

**`scripts/capture_ffmpeg_stderr.py` survives where it is, with two docstring lines re-pointed.**
It is at `scripts/`, outside the deleted tree; it regenerates the corpus and `CAPTURE.md:4` forbids
hand-editing the fixtures, so it is the only way to make another one; and
`relay/channel/source_transcode_real_test.go:15`, `:38` and `:93` cite it at three live `file:line`s
as the authority for parity-matrix row 4's real-ffmpeg pin. It is in no workflow
(`grep -rn "capture_ffmpeg_stderr" .github/` → nothing) and no test imports it. Its docstring's
`docker exec` example and `CAPTURE.md:9-10` and `:28` name the old fixtures path; all three are
re-pointed. No code change: the script takes `out_dir` as `sys.argv[1]`.

**The Go coverage gate needs no edit, for three independent reasons** (Constraint 11):
`packages=` is a hash of `go list -deps .`, which returns the same **ten** linked packages (a
`testdata` directory is not a package, and `relay/internal/relaytest` was already outside the linked
set — it and `credlint` hold 767 statements the gate has never counted); `gomod=` hashes
`relay/go.mod`, which this PR does not touch (`corpus.go` already imports `os`, `path/filepath` and
`runtime`); and `shape=`/`statements=`/`missing=` are measured per linked package, so an edit inside
`relaytest` moves none of them. Verified by running `go list -deps .` from `relay/` at the seed and
diffing against the committed `scripts/coverage_relay_go.floor.packages`.

### R13 — `go-tests.yml`'s `differential` job is deleted, and the lost capability is stated precisely

`apps/proxy/live_proxy/tests/test_relay_differential.py` is inside the deleted directory, and
A9.6 and PR #317 both record it as a legitimate 2d deletion. The mechanical consequence A10.7 names,
verified at this seed with **no line drift from `1326de3e`** (`git diff --name-only 1326de3e e1a7b91f`
touches neither workflow):

| Edit | Line(s) at the seed |
|---|---|
| delete the `differential` job, leading comment included | `:367-465` |
| remove it from `go-result`'s `needs` | `:472` |
| drop `DIFFERENTIAL_RESULT` from the `env` block | `:482` |
| remove it from the success loop | `:496-502` (the pair list wraps across `:496-497`) |
| drop it from the echo naming each job | `:485` |
| remove **both** `live_proxy` clauses from the change-detector pattern | `:114` |

Note the pattern at `:114` carries two: `apps/proxy/live_proxy/tests/harness/` and
`apps/proxy/live_proxy/tests/test_relay_differential\.py$`. Both go, and nothing replaces them —
the corpus they existed for now lives under `relay/`, which the pattern's leading `^(relay/` already
covers. That is the one genuinely load-bearing half of this edit: leave the harness clause in and it
matches a path that cannot change; take the corpus out from under `^relay/` and a corpus-breaking
change would stop triggering the Go workflow at all, with `Go result` still green via the
not-required branch.

**The capability that is lost, stated precisely, because the obvious phrasing is wrong.** The
`differential` job is *not* the only place `relay-go` runs beside real stores — `docker/Dockerfile:50`
builds it, `docker/supervisord/all.conf:19` starts it in every AIO container, and
`docker/healthcheck.sh:28-34` probes it, so every E2E container already runs it next to a real
Postgres and Redis. What it uniquely does is **drive** it: it is the only job that sends the Go
binary a tune and asserts on the bytes that come back, against a real Django with a real
`SECRET_KEY` (`LiveServerTestCase`). Nothing replaces it. What it *proved* — two implementations
agreeing byte for byte — has no meaning once there is one implementation; what it *incidentally
provided*, a Go-binary-against-real-Django integration point, has been assumed by the E2E suite
since 2d-3, which drives `relay-go` through nginx end to end on every `migration/**` run. 2d-3's
own plan states this in its R13, one PR ahead, so nobody discovers in 2d-4 that a job vanished.

**Gate 2's Python census is unperturbed by the deletion**, which is worth saying because the
differential test lived in a measured label: it SKIPs in every run of that label other than the
`differential` job's, deterministically, because `DISPATCHARR_RELAY_GO_BIN` is unset there. A skipped
test contributes no covered statements, so removing it removes none.

### R14 — three `defects.yml` rows are re-pointed at their Go pins, and `--validate-only` joins this PR's gate

`metrics/build/curated.py:322-325` resolves every defect's `test` path against the repo and appends
`test path … does not exist`; `:314-315` forbids a `status: pinned` row without both an issue and a
test. Three rows, all `pinned`, name a file this PR deletes:

| Row | id / issue | Current `test` | New `test` |
|---|---|---|---|
| `defects.yml:21` | `max-stream-switches-unbounded` / #221 | `apps/proxy/live_proxy/tests/test_manager_stderr_failover.py` | `relay/channel/source_transcode_test.go` |
| `:22` | `fmp4-timeout-no-switch-exemption` / #222 | `apps/proxy/live_proxy/tests/test_fmp4_client_timeout.py` | `relay/httpapi/fmp4_test.go` |
| `:32` | `ffmpeg-speed-scientific-notation` / #227 | the same `test_manager_stderr_failover.py` | `relay/ffmpeg/progress_test.go` |

Each target is the Go half of the same parity-matrix row's Pin (rows 6, 12 and 28 respectively),
read out of the matrix rather than guessed: row 6 pins
`relay/channel/source_transcode_test.go::TestABufferingFailoverIgnoresMaxStreamSwitches`, row 28
pins `relay/ffmpeg/progress_test.go::TestAScientificNotationSpeedIsUnderReportedAsItsMantissa`, and
row 12's Go pin is `relay/httpapi/fmp4_test.go::TestAStalledFMP4ClientIsDroppedWhileATSClientIsNot`.
The `test` field is a **path**, not a `::` reference, so only the path is written.

**The timing trap A10.15 names, and the fix.** The commit gate runs
`python -m metrics.build --validate-only` only when a `metrics/` path is staged
(`.claude/hooks/pre-commit-tests.sh:185`), so a version of this PR that deleted the tests without
touching `metrics/` would not be told — the three broken rows would first surface in `pages.yml:90`
on `main` after merge, with nothing red on the PR. Because this PR *does* stage a `metrics/` path,
the gate runs; Task 11 runs it explicitly anyway, so it is a gate item rather than a side effect.

**No `milestones.yml` row.** A milestone row carries the merge SHA and a merge commit cannot name
itself (A9.9, 2c-9's R13, #276's precedent, and 2d-1's A11.5). Nothing in `metrics/curated/` moves
here except the three defect paths.

### R15 — the CLAUDE.md sentences this PR makes false

Per-PR correction is the standing convention; 2d-6 is the consolidation pass, not the only place.
The rule applied is narrow: **a sentence this PR makes FALSE is corrected here; a sentence that
merely describes `live_proxy` as existing is 2d-6's.** **Nineteen** replacements, each quoted in
Appendix K with its `assert count == 1` anchor. The first eleven are listed below; the rest close
contradictions this PR would otherwise introduce — § Test hooks' blocking list still naming the
three deleted shims three lines above the bullet that says they are gone; § Testing still describing
`go-tests.yml`'s `differential` job as live, which R13 deletes; § Structural constraints still
saying `models.py:6-7` imports two names, which R8 makes one; and § Routing still naming
`live_proxy/urls.py`:

1. **§ Test hooks, the boot-check bullet** — names "the three old paths stay in it until 2d-4
   deletes the package"; 2d-4 is now, and the arm has three paths, not six (R10).
2. **§ Test hooks, the container bullet's "16/16 backend packages"** and the `PreToolUse` paragraph's
   "Baseline **16/16** backend packages pass (2,212 tests, 28.5s)" → **15/15**, with the new test
   count measured in Task 12 rather than guessed.
3. **§ Testing, "16 labels; 2,212 backend tests"** → 15 labels and the measured count.
4. **§ Testing, `_PATH_ALIASES`' paragraph** — names the `apps/proxy/live_proxy/` alias and
   `test_ts_proxy_teardown.py` (R10 deletes both).
5. **§ Testing, the Gate 2 paragraph** — "a 38-file module list", "currently 7,978 statements",
   "the ten Phase 1 boundary modules" and "`scripts/coverage_live_path*` is routed to Gate 2's own
   three labels" all become false (R9, R10).
6. **§ Testing, the Gate 1 paragraph** — "Gate 1 is closed" is rewritten to record that its static
   half is **retired rather than met** (A10.8), including the `apps/proxy/config.py` gap R16 states.
7. **§ Testing, the harness sentence** — "The backend suite can now spawn a subprocess —
   `apps/proxy/live_proxy/tests/harness/`" describes a directory this PR deletes.
8. **§ Testing, the `relaytest` sentence** — "its synthetic TS asset … pinned to it by a SHA-256
   digest, so the two implementations can be driven from the same bytes" is false the moment R12
   deletes the digest.
9. **§ Architecture, the `live_proxy/server.py` ownership paragraph** — "One uWSGI worker owns a
   channel's upstream, elected by `redis.set(…)` (`live_proxy/server.py`)" describes a deleted file
   as the live mechanism.
10. **§ Known defects, the fail-open bullet** — cites `live_proxy/server.py` and
    `_execute_redis_command`; it is parity-matrix row 27's only surviving external description
    (R11), and it is rewritten to say the mechanism was deleted rather than fixed.
11. **§ Known defects, #190's bullet** — its five ranges are deleted by R8, so the whole bullet is
    replaced by one sentence recording that the coupling is gone and what closed it.

Two further corrections A10.17 assigns to **2d-6** are deliberately **not** made here and are named
in the PR body so they are not rediscovered: the "two fallback-path reads" → three arithmetic (moot
after R8 deletes all three, and 2d-6 rewrites the surrounding paragraph anyway), and the #222
"changes five artefacts together" → three.

### R16 — Gate 1's runtime half dies with the package; the gap is recorded, not filled

`apps/proxy/live_proxy/tests/test_zero_orm_reads.py` (730 lines) and `zero_orm_allowlist.py`
(748 lines) are both inside the deleted tree and nothing outside imports either
(`grep -rn "zero_orm" --include='*.py' . | grep -v "^./apps/proxy/live_proxy/"` → empty), so the
deletion is clean. What "the relay performs zero ORM reads" means afterwards is
`scripts/check_go_stdlib_only.sh` plus the `go.sum`-is-empty fact: the Go binary links no Postgres
driver, so the property is structural rather than asserted — strictly stronger for the relay itself.

**What is lost is not about the relay, and it is recorded rather than replaced.** The scanner's
scope-2 walk followed import edges *out of* the package and reached four surviving modules —
`apps/proxy/{next_source,authorize,authorize_views,config}.py`. `apps/proxy/config.py` is the
awkward one: it carried **five** of the twelve edges and, after R9, it is in **neither** gate — it is
not among the coveragerc's boundary modules either, so the single most-edged module in Gate 1's walk
loses its ORM ratchet and has no coverage floor over it at the same moment. **Ruling (A10.8's,
applied): record the gap, build no replacement.** A Django-side "these four modules read the ORM only
here" guard is a new test with a new allowlist in a new home — real work, unrelated to the cutover,
and precisely the widening this phase's charter warns against. It goes on the post-2d list beside
the coverage re-scope, and CLAUDE.md § Testing says so in this PR (R15 item 6) rather than in 2d-6.

### R17 — `apps/proxy/hls_proxy/` is out of scope

1,206 lines of dead code (`_OUTPUT_FORMAT_MANAGERS` registers only `fmp4`; there is no HLS output).
It is not in `apps/proxy/live_proxy/`, nothing this PR touches imports it, and deleting it is Phase
4's. The one place it surfaces is `apps/proxy/signals.py:13-16`'s `hls_proxy` branch, which R5
**keeps verbatim** for exactly this reason. Stated in the PR body's "what this PR does not do".

### R18 — what else in the tree names the deleted tree, and why none of it is this PR's

Measured with `grep -rn 'live_proxy'` over each tree, classified:

- **`e2e/`** — 27 hits in 12 files, plus one in `e2e-upstream/README.md`: 22 prose comments, 5 `COVERAGE.md` citations, 1 `e2e-upstream/README.md`
  line. **Zero guard-checked paths, zero test-title pins, zero functional reads.** The five
  `COVERAGE.md` citations are this PR's (Appendix J.2) because they name a path; the remaining
  **17** `.ts` comments are 2d-6's. No guard reads `COVERAGE.md` (`grep -rn 'COVERAGE' e2e/tests/guards/` → nothing), so all
  of it is silent staleness either way.
- **`relay/`** — `grep -rn 'apps/proxy/live_proxy' relay/` is 37 lines and `grep -rn 'live_proxy'`
  is 45; one of them (`corpus.go:56`) is the functional read R12 fixes and the rest are provenance
  comments. The larger figure is `grep -rn '\.py' relay/ | grep -v live_proxy` at **694** lines —
  several hundred Go doc comments citing the deleted Python by bare filename
  (`input/manager.py` ×140, `views.py` ×74, `channel_status.py` ×52). **None is fixed in 2d**, per
  A10.6: they break no build and rewriting them is not worth a PR. Recorded so nobody mistakes the
  dangling-reference count for the size of the problem or for a budget to work through. The
  provenance comments inside `corpus.go` and `asset_test.go` that R12 *does* touch are rewritten
  because those two files are being edited anyway and because their values must survive with their
  derivations, not as bare digits.
- **`.github/`** — four lines must change (R13's three in `go-tests.yml` plus
  `backend-tests.yml:180`, R10). Two more are harmless prose in `domain-fuzz-campaign.md:96` and its
  generated `.lock.yml:562`; they are 2d-6's, and when they move they move together via a **bare**
  `gh aw compile`.
- **`apps/proxy/*.py`** — three 2d-1 docstrings describe the re-export shims and
  `apps/proxy/live_proxy/constants.py` (`apps/proxy/redis_keys.py:14-15`,
  `apps/proxy/config_helper.py:17-18`, `apps/proxy/constants.py:13-17`). All three are phrased
  forward ("until stage 2d-4"), so they read as history rather than as false claims once this PR
  lands; **2d-6's, and named here so that is a decision rather than an omission.**
- **`scripts/metrics/`** — `collect_architecture.py` computes `models_module_level_live_proxy_imports`
  over `apps/channels/models.py` alone and keeps working (it reads 0, as it has since 2d-1);
  `tests/test_collect_architecture.py` uses the string `from apps.proxy import live_proxy` as
  *synthetic module source* for that parser and is unaffected. Neither is edited.
  `reverse_imports_into_proxy` falls from 29 to **28** (`dispatcharr/urls.py:9`'s `stream_xc` import
  is the one that goes; every re-pointed import still names `apps.proxy`). It is a headline tile with
  a `target: 0` and no gate; the drift is expected and named in the PR body.

---

## File structure

**Deleted (9 paths + one directory of 97 files)**

| Path | Why |
|---|---|
| `apps/proxy/live_proxy/` | the package, **97 files** after four move out (R12); 96 `.py`, 26,371 lines, 53 test files, 406 tests |
| `apps/proxy/relay_views.py` | R1 |
| `apps/proxy/relay_urls.py` | R1 |
| `apps/proxy/tasks.py` | R4 |
| `apps/proxy/management/commands/proxy.py` | R5 |
| `apps/channels/tests/test_ts_proxy_ghost_clients.py` | R7 #4 |
| `apps/channels/tests/test_ts_proxy_keepalive_duration.py` | R7 #7 |
| `apps/channels/tests/test_ts_proxy_teardown.py` | R7 #8 |
| `apps/proxy/tests/test_relay_status_shape.py` | R7 #11 |
| `apps/proxy/tests/test_relay_control_api.py` | R7 #16 |

**Moved (4 files, `git mv`)**

`apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/{CAPTURE.md, normal.stderr,
slow-trickle.stderr, truncation.stderr}` → `relay/internal/relaytest/testdata/ffmpeg_stderr/`
(26,180 bytes; R12).

**Created (2)**

| Path | What |
|---|---|
| `apps/proxy/stream_routes.py` | R6 — the live URL patterns and the two callables the authorize hop resolves. Appendix O |
| `relay/internal/relaytest/testdata/` | the directory, by the move above |

**Modified — Python production (13)**

| Path | What | Ruling |
|---|---|---|
| `dispatcharr/settings.py` | `INSTALLED_APPS` entry; the `fetch-channel-statuses` beat entry | R5, R4 |
| `dispatcharr/urls.py` | the `stream_xc` import re-pointed at `stream_routes`; both `re_path`s spliced from it | R6 |
| `dispatcharr/consumers.py` | one function-local import | R3 |
| `apps/proxy/urls.py` | the `relay/` include dropped; the `ts/` include re-pointed at `stream_routes` | R1, R6 |
| `apps/proxy/apps.py` | `ready()` removed | R5 |
| `apps/proxy/signals.py` | the `live_proxy` branch; `hls_proxy`'s kept verbatim | R5, R17 |
| `apps/proxy/authorize.py` | one function-local import | R3 |
| `apps/proxy/ts_admin_views.py` | `_worker_id()`; two function-local imports removed | R2 |
| `apps/proxy/internal_base_url.py` | `resolve_base_url(..., dev_url=...)` | R1 |
| `apps/proxy/relay_client.py` | passes the Go relay's dev port | R1 |
| `apps/m3u/connection_pool.py` | one function-local import | R3 |
| `apps/channels/models.py` | #190's five ranges and the now-unused `ChannelMetadataField` import | R8 |
| `scripts/capture_ffmpeg_stderr.py` | two docstring lines | R12 |

**Modified — tests (12)**

`apps/channels/tests/{test_channel_stream_reuse, test_get_stream_assignment, test_recording_pipeline,
test_ts_proxy_initializing, test_ts_proxy_keepalive}.py`;
`apps/proxy/tests/{test_boundary_error_arms, test_combined_stats, test_stream_switch,
test_internal_base_url}.py`;
`tests/{test_websocket_consumer_filter, test_ci_test_routing, test_urls_xc_three_segment}.py`;
`core/tests/test_fetch_channel_stats.py` (one docstring). R6, R7. **Twelve.**

**Modified — Go (3)**

`relay/internal/relaytest/corpus.go`, `relay/internal/relaytest/asset_test.go` (R12), and
`relay/httpapi/detail_golden_test.go` (R7 #11's re-homed assertion).

**Modified — routing, gates and CI (8)**

`dispatcharr/test_discovery.py`, `.claude/hooks/run-affected-tests.sh`,
`scripts/coverage_live_path.coveragerc`, `scripts/coverage_live_path.floor`,
`scripts/coverage_live_path.floor.modules`, `scripts/coverage_live_path_isolated.sh`,
`.github/workflows/backend-tests.yml`, `.github/workflows/go-tests.yml`. R9, R10, R13.

**Modified — guards, docs and metrics (7)**

`docs/relay-parity-matrix.md`, `e2e/tests/guards/parity-matrix.ts`,
`e2e/tests/guards/parity-matrix.spec.ts`, `e2e/COVERAGE.md`, `metrics/curated/defects.yml`,
`CLAUDE.md`, `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`. R11, R14, R15, A14.

**Deliberately not touched**, each checked rather than assumed:

- `docker/**` — Constraint 5; 2d-3 owns the deployment shape and this PR changes none of it.
- `frontend/**` — `grep -rn "worker_id\|proxy/relay" frontend/src` returns nothing on either; the
  six admin routes keep their literal paths (R2).
- `apps/proxy/vod_proxy/**`, `apps/timeshift/**` — Constraint 4. Neither imports `relay_client`
  (A10.11) and neither imports `live_proxy` after 2d-1.
- `apps/proxy/hls_proxy/**` — R17, Phase 4's.
- `core/tasks.py`'s `fetch_channel_stats` — R4; only its test file's docstring moves.
- `scripts/ci_backend_test_labels.py` — R10; it lists no labels.
- `scripts/coverage_relay_go.*` — R12, Constraint 11.
- `scripts/metrics/collect_architecture.py` and its tests — R18.
- The ~694 Go doc-comment citations of deleted Python filenames — R18, A10.6.

---

## Task 0: verify the seed

**Files modified:** none. **Every mismatch below is a STOP and report, not a judgement call.**

- [ ] **Step 1 — the tree.** From your worktree root:
      `git log --oneline -1` and `git status --porcelain`. The head must be the merge of
      **2d-3** (`migration/phase2d-nginx-flip`), and `git status` must be empty. If 2d-3 has not
      merged, STOP: this plan's Task 0 Steps 6–9 are written against its tree.
      **2d-3 is being implemented now** and merges before this PR is. Its merge is the ONLY thing
      between this plan's seed and the tree you are about to edit: #327 has merged as
      `e1a7b91f1f66bf8d79b0bd21afdbc1675fc0c464`, which is this plan's seed, so
      ```
      git diff --stat e1a7b91f HEAD
      ```
      must name **only** the fourteen paths 2d-3's own File structure lists. Anything else is a
      commit this plan has not seen — STOP and report it. The re-seed table above says which of
      this plan's figures that merge is expected to move (line numbers in `CLAUDE.md`, the spec and
      `e2e/COVERAGE.md`, and nothing else); Steps 6–9 re-derive them by content.
- [ ] **Step 2 — the package is still whole.**
      `find apps/proxy/live_proxy -type f | wc -l` → **101**;
      `find apps/proxy/live_proxy -name '*.py' | wc -l` → **96**;
      `find apps/proxy/live_proxy/tests -name 'test_*.py' | wc -l` → **53**;
      `find apps/proxy/live_proxy -type f ! -name '*.py' | sort` → exactly five paths, the four
      fixtures plus `tests/harness/README.md`.
- [ ] **Step 3 — the reference classifier.** Write Appendix A.1's script to your scratchpad and
      run it. Its output must match Appendix A.1's recorded output **line for line**. A new file in
      the list is a reference this plan does not dispose of — STOP. A missing one means 2d-3 or a
      later commit already handled it — STOP and report which. **Note what the classifier cannot
      see** (R7's addendum): it finds files naming the deleted *directory*, not files broken by
      this plan's own rulings. Two such were found by executing the plan and are rows 16-17 of R7's
      table; a third would show up the same way, as a red label, not here.
- [ ] **Step 3b — every appendix applies, before any of them is applied for real.**
      ```
      for d in <your scratch>/appendices/*.diff; do
        git apply --check --whitespace=error "$d" || echo "FAILS: $d"
      done
      ```
      **Every one must be silent.** The appendix set is *disjoint* — no file appears in two
      appendices — so `git apply` cannot conflict whichever order they run in, and this check is
      therefore complete rather than indicative. Any failure is a STOP: it means the re-seed moved
      a file an appendix was generated against.
- [ ] **Step 4 — the nine module-level import sites.**
      ```
      grep -rn "live_proxy" --include='*.py' apps dispatcharr core scripts metrics tests \
        | grep -v "^apps/proxy/live_proxy/" | grep -cE "^[^:]+:[0-9]+:(from|import) "
      ```
      Expect **12** (the nine A10.3 names minus the three 2d-1 closed, plus the three
      function-local `url_utils` importers and `ts_admin_views`' two). Appendix A's per-file table
      is the authority; this is the cheap cross-check.
- [ ] **Step 5 — the two coverage floors.**
      `grep -E "^(modules|module_count|rcfile|missing|statements)=" scripts/coverage_live_path.floor`
      → `modules=8cb5c65dac3e`, `module_count=38`, `rcfile=3af0a78b9b6f`, `missing=1525`,
      `statements=8073`. And `grep -E "^(packages|gomod|missing)=" scripts/coverage_relay_go.floor`
      → `packages=0321b777fc5d`, `gomod=92baf312d30d`, `missing=589`. **The Go floor must be
      byte-identical at the end of this PR** (Constraint 11).
- [ ] **Step 6 — the parity matrix.** `grep -c '^| ' docs/relay-parity-matrix.md` and the counts
      Appendix E's script prints on a dry run: **30 rows, 86 Source citations (53 under the deleted
      directory), 38 Python pins, 37 Go pins**. 2d-3's R12 asserts it does not touch this file; a
      different count means it did — STOP.
- [ ] **Step 7 — the spec's A13 anchor.** `grep -n "^#### Amendment A13" docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`
      → exactly one line. Appendix N inserts A14 after it. Zero lines means 2d-3 did not land its
      amendment — STOP.
- [ ] **Step 8 — the five `e2e/COVERAGE.md` rows this PR edits.** Locate each **by content**, not
      by line number, since 2d-3 rewrote four rows in the same table:
      `grep -n "apps/proxy/live_proxy" e2e/COVERAGE.md` → expect **five** lines. If 2d-3's own
      edits changed the count, Appendix J will not apply — STOP and report the actual list.
- [ ] **Step 9 — 2d-3's own artefacts are present**, so the plan is measuring the right tree:
      `test -f docker/dispatcharr_api_params_proxy.conf && test -f relay/drain/supervisord_priority_test.go`
      and `grep -c "proxy_pass http://relay_go" docker/nginx.conf` → **4**.
- [ ] **Step 10 — your container.** The shared `dispatcharr-testrunner` is bind-mounted at one
      worktree and the `PostToolUse` hooks always use it (`CLAUDE.md` § Test hooks). Either
      re-point it at this tree or start your own per brief-common rule 6, named `impl2d4`. Record
      which you did; if you started your own, every `docker exec` below names it and the edit hook
      will still target the shared one — say so in your report rather than describing unverified
      work as verified.

---

## Task 1: move the ffmpeg stderr corpus into the Go module

**Files:** `relay/internal/relaytest/corpus.go`, `relay/internal/relaytest/asset_test.go`, four
moved fixtures, `scripts/capture_ffmpeg_stderr.py`. **Ruling:** R12.

This task is first because it is the only edit that makes the Go module depend on the Python tree
*less*; every later task can then delete freely.

- [ ] **Step 1 — move the files.**
      ```
      mkdir -p relay/internal/relaytest/testdata/ffmpeg_stderr
      git mv apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/CAPTURE.md \
             apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/normal.stderr \
             apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/slow-trickle.stderr \
             apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/truncation.stderr \
             relay/internal/relaytest/testdata/ffmpeg_stderr/
      ```
      Verify: `find relay/internal/relaytest/testdata -type f | wc -l` → **4**;
      `du -b relay/internal/relaytest/testdata/ffmpeg_stderr/* | awk '{s+=$1} END {print s}'`
      → **26180**. `git status --porcelain` must show four `R` entries and no `D`+`A` pair — a
      rename git did not detect means the bytes changed, which `CAPTURE.md:4` forbids: STOP.
- [ ] **Step 2 — `git apply` Appendix D.1.** One diff over `corpus.go` (the header rewrite,
      `pkgDir()`, `RepoRoot()` re-expressed on it, and the one `filepath.Join`) and `asset_test.go`
      (the digest test deleted with its reason; the length and the two `upstream.py` value pins
      kept, re-anchored on their derivations).
- [ ] **Step 3 — `CAPTURE.md`'s two path mentions and `scripts/capture_ffmpeg_stderr.py`'s
      docstring example.** Both name the old fixtures directory in a `docker exec` example. **Not
      an appendix**: `CAPTURE.md` moves in Step 1 and `git` records it as a rename, so a diff over
      it would fight the move. Edit both by hand and verify with
      `grep -rn "live_proxy" relay/internal/relaytest/testdata/ scripts/capture_ffmpeg_stderr.py`
      → no hits. The script itself needs **no** code change (it takes `out_dir` as `sys.argv[1]`)
      and **stays where it is**: `relay/channel/source_transcode_real_test.go:15`, `:38` and `:93`
      cite it at three live `file:line`s.
- [ ] **Step 4 — run the Go module, all of it.** From `relay/`:
      ```
      go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
      ```
      All four green. Then `GOOS=linux golangci-lint run ./...` — build-tagged files are invisible
      to a darwin-only lint pass.
- [ ] **Step 5 — the break-check, RUN not read.** The relocation's whole risk is that a
      package-relative path resolves against the **caller's** directory. Replace `pkgDir()`'s body
      with a cwd-relative string — **but keep `runtime` used**, or the reversion does not compile
      and proves nothing:
      ```go
      func pkgDir() string {
          _, _, _, _ = runtime.Caller(0)   // keep the import live; A14.8 makes this the
          return "testdata"                // module's ONLY runtime.Caller site, so dropping
      }                                    // it orphans the import and every package fails
      ```
      (Without the blank use: `vet: internal/relaytest/corpus.go:9:2: "runtime" imported and not
      used`, and `./ffmpeg`, `./httpapi` and `./channel` all report `[build failed]` — a compile
      error, not the property under test. An earlier draft of this step said to delete the body
      outright and would have produced exactly that.)

      Then `go test -race ./ffmpeg/`. Expect, verbatim:
      ```
      panic: relaytest: reading the slow-trickle corpus: open testdata/testdata/ffmpeg_stderr/slow-trickle.stderr: no such file or directory
      ```
      **Note the doubled `testdata/testdata/`**: `CorpusPath` is
      `filepath.Join(pkgDir(), "testdata", …)`, so substituting `"testdata"` for `pkgDir()`
      prefixes rather than replaces — which is itself a reminder that the value must stay absolute.
      Then `go test -race ./internal/relaytest/` → **`ok`**. Both halves matter: the second is why a
      bare relative string would have looked correct in the one package a maintainer would test
      first. Revert and `go build ./...`.
- [ ] **Step 6 — the stdlib-only and credential-logging assertions.**
      `scripts/check_go_stdlib_only.sh relay` and `scripts/check_go_credential_logging.sh`, both
      clean, both from the repo root.
- [ ] **Step 7 — the Go coverage gate does not move.** From the repo root,
      `bash scripts/coverage_relay_go.sh --gate`. Expect exit 0 with `packages=0321b777fc5d`
      unchanged. If any shape hash moved, STOP: R12 says it cannot, and a move is a finding, not a
      floor to rewrite (Constraint 11).

---

## Task 2: the three `url_utils` importers, and their coupled patch strings

**Files:** `apps/proxy/authorize.py`, `apps/m3u/connection_pool.py`, `dispatcharr/consumers.py`,
`tests/test_websocket_consumer_filter.py`. **Ruling:** R3.

- [ ] **Step 1 — `git apply` Appendix B.** It carries all four edits in one patch **on purpose**:
      R3 explains that splitting them lets `assert_not_called()` pass vacuously.
- [ ] **Step 2 — run the two labels.**
      `docker exec <container> ... python manage.py test --keepdb tests apps.m3u.tests` — both
      `^OK`. (Note `^OK`, not just `Ran N tests`: `CI_BACKEND_RUNNER` runs under `bash -c` without
      `pipefail` and a pipe launders the exit status.)
- [ ] **Step 3 — the break-check, RUN not read.** Revert **only** `dispatcharr/consumers.py:120`
      to the old path, leaving the three patch strings re-pointed, and run
      `python manage.py test --keepdb tests.test_websocket_consumer_filter`. Expect
      `test_m3u_profile_test_runs_for_admin` red with
      `AssertionError: Expected 'transform_url' to have been called once. Called 0 times.` —
      the positive assertion, which is the one that bites. Note in your report that
      `test_m3u_profile_test_rejects_oversized_fields` stays **green** through this reversion: that
      is the hollow test R3 warns about, demonstrated rather than described. Revert the reversion.

---

## Task 3: `worker_id` in `ts_admin_views.py`

**Files:** `apps/proxy/ts_admin_views.py`. **Ruling:** R2.

- [ ] **Step 1 — `git apply` Appendix L.** A module-level `import os` / `import socket` and a
      `_worker_id()` helper; the two function-local `ProxyServer` imports and the two
      `proxy_server = ProxyServer.get_instance()` lines removed; the four
      `"worker_id": proxy_server.worker_id` become `"worker_id": _worker_id()`.
- [ ] **Step 2 — verify nothing else in the file reaches the package.**
      `grep -n "live_proxy" apps/proxy/ts_admin_views.py` → only the **prose** lines at `:3`,
      `:13`, `:36-39` and `:42`'s `logging.getLogger("live_proxy.views")`, which A12.4 assigns to
      2d-6. Zero `import` lines. If any import remains, STOP.
- [ ] **Step 3 — run `apps.proxy.tests`.** `^OK`, 428 tests at the seed.
- [ ] **Step 4 — the shape check, run not read.** In a Django shell in your container,
      `from apps.proxy.ts_admin_views import _worker_id; import socket, os;
      assert _worker_id() == f"{socket.gethostname()}:{os.getpid()}"`. Paste the output.
      This is what "byte-identical to `server.py:95-98`" means and it is cheap to prove.

---

## Task 4: `relay_views.py`, `relay_urls.py`, and the `dev` address

**Files:** `apps/proxy/relay_views.py` (deleted), `apps/proxy/relay_urls.py` (deleted),
`apps/proxy/urls.py`, `apps/proxy/internal_base_url.py`, `apps/proxy/relay_client.py`, and a new
test in `apps/proxy/tests/test_boundary_error_arms.py`. **Ruling:** R1.

- [ ] **Step 1 — record what the surface looks like before.** In your container,
      `python manage.py spectacular --file /tmp/schema-before.yaml` and
      `grep -c "internal_relay" /tmp/schema-before.yaml`. Record the number. This is **not** a
      byte-identity gate (R1 says why); it is the measurement that makes the schema change
      observed rather than discovered.
- [ ] **Step 2 — create `apps/proxy/stream_routes.py` verbatim from Appendix O**, then
      `git add` it. **R6**: without it the tree does not import, and with it deleted the authorize
      hop 403s every live tune. Verify: `python -m py_compile apps/proxy/stream_routes.py`.
- [ ] **Step 3 — delete the two modules and re-point the include.**
      `git rm apps/proxy/relay_views.py apps/proxy/relay_urls.py`, then `git apply` Appendix C.1
      (`apps/proxy/urls.py`: the `relay/` include goes, the `ts/` one moves to `stream_routes`).
- [ ] **Step 4 — `git apply` Appendix C.2**: `internal_base_url.py`'s `dev_url` parameter and the
      `DISPATCHARR_RELAY_GO_PORT` reader, and `relay_client.py`'s call passing it.
- [ ] **Step 5 — `git apply` Appendix C.3**: `DevRelayAddressTests`, five tests in
      `apps/proxy/tests/test_boundary_error_arms.py` — the dev branch resolves to 5658 by default;
      an explicit `DISPATCHARR_RELAY_GO_PORT` is honoured; a non-integer value logs once naming the
      variable and falls back; the operator override still wins; and
      `get_control_plane_base_url()`'s dev branch is **still** 5656, which is the half a careless
      edit would break silently.
- [ ] **Step 6 — run `apps.proxy.tests`.** `^OK`. It is still collectable at this point because
      Task 7 has not run: `test_boundary_error_arms.py:15` still imports the shim.
- [ ] **Step 7 — the break-check, RUN not read.** Revert `relay_client.py`'s `dev_url=` argument
      (so both directions resolve to 5656 again) and re-run. Expect the new
      `test_the_dev_branch_reaches_the_go_relay_not_the_api` red with
      `AssertionError: 'http://127.0.0.1:5656' != 'http://127.0.0.1:5658'`. Revert.
- [ ] **Step 8 — the schema diff.** Re-run `spectacular` to `/tmp/schema-after.yaml` and
      `diff <(grep operationId /tmp/schema-before.yaml) <(grep operationId /tmp/schema-after.yaml)`.
      Expect exactly the five `internal_relay_*` operation ids removed and **nothing else**.
      Anything else removed or added is a STOP: Constraint 6 says the surviving surface does not
      move.

---

## Task 5: #190's five metadata-hash ranges

**Files:** `apps/channels/models.py`, `apps/channels/tests/test_get_stream_assignment.py`.
**Ruling:** R8.

- [ ] **Step 1 — `git apply` Appendix M.1.** The five ranges and `models.py:7`'s now-unused
      `ChannelMetadataField` import.
- [ ] **Step 2 — verify the import is genuinely unused before you trust the patch.**
      `grep -c "ChannelMetadataField" apps/channels/models.py` → **0** after the patch.
      Then, for `RedisKeys`, check the **property** rather than a line count, because the count does
      move: `grep -n "^from apps.proxy.redis_keys import RedisKeys" apps/channels/models.py` → line
      **6**, still present, and `grep -c "RedisKeys" apps/channels/models.py` → **25**, down from
      **31** at the seed (M.1 removes eight such lines and adds two). An earlier draft said "26,
      unchanged" — 26 is CLAUDE.md's count of *sites that reach these keys*, a different
      measurement, and it was never this file's line count.
- [ ] **Step 3 — `git apply` Appendix M.2**: `MetadataOnlyReleaseTests`, two tests plus the
      `hdel` its fake Redis needs. They seed **only** the metadata hash and assert that
      `release_stream()` returns `False` without releasing a provider slot, and that the hash is
      left exactly as it was found.
- [ ] **Step 4 — run `apps.channels.tests`.** `^OK`. (It is still collectable: Task 7 has not run.)
- [ ] **Step 5 — the break-check, RUN not read.** Restore the **`:694-721` recovery branch** —
      NOT the `:745-750` read, which this test never reaches, because with no `channel_stream:` key
      seeded `release_stream()` returns at the first branch. Re-run the two tests. Expect, verbatim:
      ```
      FAIL: test_a_metadata_only_assignment_is_no_longer_recoverable
          self.assertIs(self.channel.release_stream(), False)
      AssertionError: True is not False
      FAIL: test_the_metadata_hash_is_left_exactly_as_it_was_found
      AssertionError: {} != {'stream_id': '<id>', 'm3u_profile': '<id>'}
      Ran 2 tests in 0.030s
      FAILED (failures=2)
      ```
      Revert. **Record in your report that these two tests are the only thing in the tree that
      observes these five ranges in either direction** — R8's measurement, which is why the plan
      ships a break-check rather than trusting a green suite.
- [ ] **Step 6 — `makemigrations --check` for this app.** `python manage.py makemigrations --check
      --dry-run dispatcharr_channels` → no changes. **Note (A11.8, measured one PR ago): a bare
      `makemigrations --check` is NOT clean at the seed** — `core` reports a pending
      `0028_alter_streamprofile_parameters`, pre-existing and neither caused nor fixed here. Resolve
      the app label through `apps.get_app_configs()`, never by guessing the directory name: the
      guess `channels` hits the Django Channels library and exits 0 saying nothing.

---

## Task 6: close the eight remaining boot sites

**Files:** `dispatcharr/settings.py`, `dispatcharr/urls.py`, `apps/proxy/urls.py`,
`apps/proxy/apps.py`, `apps/proxy/signals.py`, `apps/proxy/tasks.py` (deleted),
`apps/proxy/management/commands/proxy.py` (deleted), `tests/test_urls_xc_three_segment.py`.
**Rulings:** R4, R5, R6.

**This task and Task 7 leave the tree un-importable between them.** Do not run a label until Task 7
Step 4.

- [ ] **Step 1 — `git apply` Appendix C.4**: `dispatcharr/settings.py` (the `INSTALLED_APPS` entry
      and the `fetch-channel-statuses` beat entry), `apps/proxy/apps.py` (`ready()` removed) and
      `apps/proxy/signals.py` (the `live_proxy` branch; `hls_proxy`'s kept **verbatim**, R17).
- [ ] **Step 1b — `git apply` Appendix C.5**: `dispatcharr/urls.py` — the `stream_xc` import
      re-pointed at `apps.proxy.stream_routes`, and both XC `re_path`s replaced by
      `*stream_routes.xc_urlpatterns`, so the pattern text has one home. **R6**: these patterns
      survive; deleting them 403s every live tune.
- [ ] **Step 2 — delete two files.**
      `git rm apps/proxy/tasks.py apps/proxy/management/commands/proxy.py`. Then verify nothing
      names either: `grep -rn "proxy\.tasks\|proxy import tasks" --include='*.py' --include='*.yml' .`
      → empty, and `grep -rn "commands.proxy\|call_command(.proxy" --include='*.py' .` → empty.
- [ ] **Step 3 — verify the beat schedule still parses.** `grep -n "fetch-channel-statuses"
      dispatcharr/settings.py` → empty, and `grep -c "\"task\":" dispatcharr/settings.py` one lower
      than at the seed. Record both numbers.

---

## Task 7: delete the package, and dispose of every test outside it

**Files:** `apps/proxy/live_proxy/` (deleted); the eleven modified and four deleted test files of
R7. **Rulings:** R7, R1.

- [ ] **Step 1 — delete the directory.**
      `git rm -r apps/proxy/live_proxy` — then
      `git status --porcelain | grep -c '^D  apps/proxy/live_proxy/'` → **97** (101 minus the four
      Task 1 moved). Any other number means Task 1's move did not take: STOP.
- [ ] **Step 2 — delete the five test files R7 disposes of whole.**
      ```
      git rm apps/channels/tests/test_ts_proxy_ghost_clients.py \
             apps/channels/tests/test_ts_proxy_keepalive_duration.py \
             apps/channels/tests/test_ts_proxy_teardown.py \
             apps/proxy/tests/test_relay_status_shape.py \
             apps/proxy/tests/test_relay_control_api.py
      ```
      The fifth is R7 #16 — the file that names no `live_proxy` and is broken by R1's ruling.
- [ ] **Step 3 — `git apply` Appendix A.2**, the eight remaining test-file edits: the re-pointed
      import (`test_channel_stream_reuse.py`), the two re-pointed patch strings
      (`test_recording_pipeline.py`), the splits (`test_ts_proxy_initializing.py`,
      `test_ts_proxy_keepalive.py`, `test_combined_stats.py`, `test_stream_switch.py`),
      `test_internal_base_url.py`'s rewrite (R7 #17) and `test_urls_xc_three_segment.py`'s docstring
      (R6). `test_get_stream_assignment.py` went in Task 5 (M.2) and
      `test_boundary_error_arms.py` in Task 4 (C.3), so neither is here — the appendix set is
      disjoint by file.
- [ ] **Step 4 — re-home the orphaned assertion (R7 #11).** `git apply` Appendix D.4:
      `relay/httpapi/detail_golden_test.go` gains
      `TestTheDetailPayloadOmitsTheDVRVideoFieldsWhenNothingSetThem`. This is the one assertion of
      `test_relay_status_shape.py`'s ten with no cover on either side. **The DETAIL golden, not the
      list one**: `width`/`height`/`video_bitrate` exist on the detail payload alone
      (`relay/httpapi/detail.go:159-161`), so the list test's absence list could never have carried
      them, and the detail golden's own fixture is one fully-populated channel — hence a new test
      that blanks the three rather than an addition to an existing list.
- [ ] **Step 4b — its break-check, RUN not read.** Drop `,omitempty` from `Width` in
      `relay/httpapi/detail.go:159` and run `go test -race -run TestTheDetailPayloadOmitsTheDVR
      ./httpapi/`. Expect
      `detail_golden_test.go:NNN: an unset "width" still renders, as : DRF declares it required=False …`.
      Revert.
- [ ] **Step 5 — `manage.py check`, in the shape that actually exercises the trap.**
      ```
      python manage.py check
      python manage.py showmigrations dispatcharr_channels
      ```
      Both green. **The second is not redundant**: A11.8 measured that `DISPATCHARR_ROLE` appears in
      no Python file in the tree, so "check in every role" is one check — what the pair covers is
      `check` plus a command that drives the **migration loader**, which is the boot trap's victim.
- [ ] **Step 6 — the whole backend suite, label by label.** Run all **15**. Every one `^OK`. Then
      `python -c "import sys; sys.path.insert(0,'.'); ..."` on
      `dispatcharr/test_discovery.py:iter_test_package_labels()` → a 15-element list with no
      `apps.proxy.live_proxy.tests`. Record the list and each label's test count; Task 12 needs
      them for CLAUDE.md.
- [ ] **Step 7 — the break-check for the split files, RUN not read.** For each of the five SPLIT
      files, the reversion is the same shape and it must be run once, on
      `apps/proxy/tests/test_boundary_error_arms.py` (the most load-bearing KEEP, R7 #9): revert
      `:15` to `apps.proxy.live_proxy.config_helper` and run the label. Expect, **measured**:
      ```
      ERROR: apps.proxy.tests.test_boundary_error_arms (unittest.loader._FailedTest…)
      ModuleNotFoundError: No module named 'apps.proxy.live_proxy.config_helper'
      Ran 363 tests in 1.372s
      FAILED (errors=1)
      ```
      Paste all four lines. **Note the mechanism, because an earlier draft of this step got it
      wrong and would have made an implementer STOP**: Django's runner substitutes a `_FailedTest`
      placeholder for the unimportable module and **runs the rest of the label**, so the count
      drops by that module's tests rather than to zero. The label still goes red, which is the
      property that matters. Revert.
- [ ] **Step 8 — `scripts/check_credential_logging.py`** over every touched `*.py`. Zero findings.

---

## Task 8: labels, hooks and the two workflows

**Files:** `dispatcharr/test_discovery.py`, `tests/test_ci_test_routing.py`,
`.claude/hooks/run-affected-tests.sh`, `scripts/coverage_live_path_isolated.sh`,
`.github/workflows/backend-tests.yml`, `.github/workflows/go-tests.yml`. **Rulings:** R10, R13.

- [ ] **Step 1 — `git apply` Appendix I.1**: `test_discovery.py` (the deleted alias, the two-label
      alias, and the header comment paragraph) and `tests/test_ci_test_routing.py` (one test
      deleted, one renamed and its expected set shrunk).
- [ ] **Step 2 — `git apply` Appendix I.2**: `run-affected-tests.sh`'s `case` arm (three paths, not
      six) and its comment; `coverage_live_path_isolated.sh`'s label list (two entries).
- [ ] **Step 3 — `git apply` Appendix I.3**: `backend-tests.yml:180`'s matrix.
- [ ] **Step 4 — `git apply` Appendix I.4**: `go-tests.yml` — the `differential` job, its `needs`
      entry, its `env` entry, the success loop, the echo, and **both** `live_proxy` clauses in the
      change detector.
- [ ] **Step 5 — verify the routing, from the function CI uses.**
      ```
      python scripts/ci_backend_test_labels.py apps/proxy/next_source.py
      python scripts/ci_backend_test_labels.py scripts/coverage_live_path.floor
      python scripts/ci_backend_test_labels.py dispatcharr/settings.py
      ```
      Expect `["apps.proxy.tests"]`, `["apps.channels.tests","apps.proxy.tests"]` (order as the
      function returns it), and all fifteen. The middle one is the load-bearing case: it is what
      stops 2d-5's own edits from selecting zero labels.
- [ ] **Step 6 — run the `tests` label.** `^OK`.
- [ ] **Step 7 — the break-check, RUN not read.** Delete the
      `("scripts/coverage_live_path", …)` alias entirely and run
      `python manage.py test --keepdb tests.test_ci_test_routing`. Expect
      `test_coverage_gate_script_change_runs_its_own_two_labels` red. The message is
      `assertSetEqual`'s — `AssertionError: Items in the second set but not the first:` followed by
      the two labels — not a bare `!=`. Revert. This is the
      PR #252 gap in its current form and the reason the alias must not simply be deleted along
      with its sibling.
- [ ] **Step 8 — zizmor on both edited workflows.** At the version pinned in
      `.github/workflows/actions-lint.yml`, **zero findings** on `go-tests.yml` and
      `backend-tests.yml`. Online audits on (a token in `$GH_TOKEN`/`$GITHUB_TOKEN`/`gh auth token`);
      if it degrades to offline, say so in your report rather than calling it clean.
- [ ] **Step 9 — `actionlint`** on both, via `lint.yml`'s pinned container. Clean.

---

## Task 9: Gate 2 (Python) — the rcfile, one clean round, and the shape-only re-baseline

**Files:** `scripts/coverage_live_path.coveragerc`, `scripts/coverage_live_path.floor`,
`scripts/coverage_live_path.floor.modules`. **Ruling:** R9. **Constraint 7 governs this whole task.**

- [ ] **Step 1 — `git apply` Appendix H.1**: the rcfile loses `apps/proxy/live_proxy/*` and
      `apps/proxy/relay_views.py` from `[report] include`. Nine entries remain.
- [ ] **Step 2 — one clean isolated round, from a WRITABLE checkout.**
      `bash scripts/coverage_live_path_isolated.sh` (two labels now). `--write-floor` refuses to run
      against the read-only `/repo` mount the standard hook container uses and says so; run it from
      your own clone or a scratch container with `/repo` mounted `rw`.
      **Every label must be `^OK`.** A failed label invalidates the measurement rather than
      degrading it — a tree missing `hypothesis` once reported 3,230 statements where the same tree
      with it reported 3,169, a 61-statement inflation moving the way a regression moves.
- [ ] **Step 3 — the re-baseline.** `bash scripts/coverage_live_path.sh --write-floor --shape-only`.
- [ ] **Step 4 — check the printed hash against this plan's prediction.** Expect
      `modules=7804792af4f7`, `module_count=9`, and a new `rcfile=` hash. **If `modules=` is
      anything else, STOP and report both values**: R9 derived `7804792af4f7` from the include list
      by hand, and a disagreement means coverage resolved a file the include list does not obviously
      name, which is a finding rather than a number to overwrite.
- [ ] **Step 5 — verify what did NOT move.**
      `git diff scripts/coverage_live_path.floor` must show changes to `shape`? no —
      to **`statements`, `modules`, `module_count` and `rcfile` only**. `missing=1525`,
      `percent=81.11`, `measured=2026-09-13` and `runs=12` must be byte-identical. If `missing`
      moved, `--shape-only` was not passed: revert the floor and redo Step 3.
- [ ] **Step 6 — `git apply` Appendix H.2**: the floor header gains R9's one-sentence statement
      that the gate is deliberately slack until `migration/phase2d-gate2-recensus`.
- [ ] **Step 7 — the gate.** `bash scripts/coverage_live_path.sh --gate` → exit 0, and it should
      print a large "FEWER missed than the floor" figure. Paste it: that number **is** the slack,
      and 2d-5's plan needs it.
- [ ] **Step 8 — the companion is consistent.**
      `wc -l scripts/coverage_live_path.floor.modules` → **9**, and no line starts
      `apps/proxy/live_proxy/`.

---

## Task 10: the parity matrix and its guard

**Files:** `docs/relay-parity-matrix.md`, `e2e/tests/guards/parity-matrix.ts`,
`e2e/tests/guards/parity-matrix.spec.ts`. **Ruling:** R11.

- [ ] **Step 1 — `git apply` Appendix F**: the guard's `retired:` Source form, the
      `RETIRED_SOURCES` constant and its three assertions, in `WHITE_BOX_ONLY`'s idiom.
- [ ] **Step 2 — run Appendix E's script** (the matrix). It addresses every row **by id**, asserts
      each matched exactly once and each carried the number of `live_proxy` Source citations this
      plan measured, and prints exactly:
      ```
      ok, 21 Source cells, 26 Pin cells, 2 Notes cells
      ```
      Any other line, or any assertion firing, is a STOP: it means 2d-3 or a later commit moved a
      row after Task 0 Step 6 measured it.
- [ ] **Step 3 — `cd e2e && npm run typecheck`.** Clean. (The edit hook runs `tsc --noEmit` on
      every `e2e/**/*.ts` write and both packages typecheck clean today — it is a ratchet.)
- [ ] **Step 4 — run the guards.** `npx playwright test --project=guards`. All green, and
      `parity-matrix.spec.ts`'s summary line must read `30 rows — 28 pinned, 0 owed, 2
      white-box-only`. `guards` needs no container.
- [ ] **Step 5 — four break-checks, RUN not read.** Each is one edit, each must be reverted:
      1. **The Source check still bites.** Change row 1's first Go citation to a line past the end
         of its file. Expect `… (row 1) — relay/…:9999 runs past the end of the file, which has N
         lines`.
      2. **A deleted path is still caught.** Change row 2's Source to
         `` `apps/proxy/live_proxy/server.py:1` ``. Expect
         `no such file: apps/proxy/live_proxy/server.py`.
      3. **`retired:` is counted, not a free pass.** Change row 1's Source cell to
         `retired: nothing to see here`. Expect the new allowlist test red, naming row 1 —
         `expect(retiredRows).toEqual([26, 27])` failing with `[1, 26, 27]`. This is the assertion
         that answers option (c)'s objection, and it is the one that must be seen to fire.
      4. **The `why` and Notes siblings bite.** Empty `RETIRED_SOURCES[0].why`, expect the
         `why` assertion red; restore it and empty row 26's Notes cell, expect the Notes assertion
         red.
- [ ] **Step 6 — confirm the three flags did not move.**
      `grep -n "GATE_1_CLOSED\|GO_PARITY_CLOSED\|HIGHEST_ROW_ID" e2e/tests/guards/parity-matrix.ts`
      → `= true`, `= true`, `= 30`, all unchanged from the seed.

---

## Task 11: the defect ledger and `e2e/COVERAGE.md`

**Files:** `metrics/curated/defects.yml`, `e2e/COVERAGE.md`. **Rulings:** R14, R18.

- [ ] **Step 1 — `git apply` Appendix J.1**: the three `defects.yml` `test:` paths.
- [ ] **Step 2 — `python -m metrics.build --validate-only`.** Green. Run it explicitly rather than
      relying on the commit gate: A10.15's trap is that the gate runs it only when a `metrics/`
      path is staged, and this is the PR that would otherwise discover the breakage on `main`.
- [ ] **Step 3 — the break-check, RUN not read.** Point `defects.yml:21`'s `test` at
      `relay/channel/does_not_exist_test.go` and re-run. Expect
      `defects.yml … test path relay/channel/does_not_exist_test.go does not exist`. Revert.
- [ ] **Step 4 — `git apply` Appendix J.2**: `e2e/COVERAGE.md`'s five rows citing a deleted path.
      Each re-points at the surviving mechanism (three at the Go relay's route, two at
      `apps/proxy/next_source.py`'s `transform_url`), and none is one of the four rows 2d-3 rewrote.
- [ ] **Step 5 — `grep -n "apps/proxy/live_proxy" e2e/COVERAGE.md`** → **exactly one line,
      `:202`**, the reconnect open question, which A10.10's own table assigns to **2d-6** along with
      `:50` (both describe mechanisms rather than cite paths). Zero would mean you edited a row this
      PR does not own. `grep -rn "apps/proxy/live_proxy" e2e/ --include='*.ts' | wc -l` → **17**,
      all prose comments, 2d-6's (R18). Record both so 2d-6 has them.
- [ ] **Step 6 — no `milestones.yml` row** (R14). `git diff --name-only metrics/` must name
      `metrics/curated/defects.yml` and nothing else.

---

## Task 12: CLAUDE.md, the spec, and the Done-log row

**Files:** `CLAUDE.md`, `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`.
**Rulings:** R15, A14.

- [ ] **Step 1 — collect the numbers Appendix K needs**, from Task 7 Step 6's recorded output: the
      label count (**15**), the total backend test count, and the suite's wall time. Appendix K's
      script takes them as arguments rather than baking them, because every predecessor plan that
      baked a measured number into an appendix shipped a stale one.
- [ ] **Step 2 — run Appendix K's script** (CLAUDE.md). **Nineteen** verbatim-string
      replacements, each `assert count == 1`. It prints exactly `ok, 19 edits`. Verbatim-string
      replacement, not line-anchored hunks, because 2d-3 moved every line number in this file (see
      the re-seed table).
- [ ] **Step 3 — verify by replacement count and by grep**, not by eye. **Two patterns, two
      different numbers — do not conflate them**, which an earlier draft of this step did:
      ```
      grep -c "apps/proxy/live_proxy" CLAUDE.md   # -> 7   (full paths)
      grep -c "live_proxy" CLAUDE.md              # -> 13  (paths + bare mentions + logger names)
      ```
      The nineteen replacements close every sentence this PR makes **false**; what remains describes
      deleted behaviour in § Known defects, or names the `live_proxy` logger, and is 2d-6's. Record
      both counts and the line numbers so 2d-6 has its worklist.
- [ ] **Step 3b — the two contradictions this PR would otherwise introduce are gone.** Both must
      print **0**:
      ```
      grep -c "and their three .live_proxy/. re-export shims" CLAUDE.md
      grep -c "The \*\*differential\*\* job" CLAUDE.md
      ```
      **Note the first pattern carefully.** The clause to be rid of is § Test hooks' blocking
      **list**, which named the shims as live. The bullet three lines below deliberately still says
      "stage 2d-4 **deleted** the three `live_proxy/` re-export shims" — past tense, and the
      correction itself — so a looser `grep -c "three .live_proxy/. re-export shims"` prints **1**
      and would STOP a correct run on its own fix.
- [ ] **Step 4 — run Appendix N's script** (the spec): Amendment **A14** (twelve items) inserted
      before `## Stage 2d` so it lands after A13, **four** in-place corrections, and the Done-log
      row. `assert count == 1` on all six anchors; it prints exactly `ok, 6 edits`.
- [ ] **Step 5 — verify the spec carries no contradicting pair.** The requirement is that no old
      sentence stands **unqualified** beside its contradiction — not that the old words vanish.
      Appendix N corrects two of its four sites by **annotating in place**, which is the right idiom
      for a document whose amendments are a change log, so the old phrase survives *inside* the
      superseding sentence. The measured expectations, and each is a STOP if it differs:
      ```
      grep -c   "Deletable in 2d-4"                            # -> 0  (correction 1: replaced)
      grep -c   "Re-scope Gate 2 to the ten"                   # -> 0  (correction 4: replaced)
      grep -c   "Eleven across two labels by the time 2d-4"    # -> 1  (correction 2: annotated in
                                                               #        place; the hit is INSIDE
                                                               #        "Amendment A14.3 supersedes
                                                               #        this count: SEVENTEEN…")
      grep -ic  "ten survivors"                                # -> 5  (correction 3 annotates the
                                                               #        DEFINITION at A10.4 with
                                                               #        "(nine after A14.1)"; the
                                                               #        four later uses inherit it)
      ```
      For the two annotated ones, read the hit rather than counting it: correction 2's must be
      preceded by its superseding clause, and correction 3's definition site must carry the
      parenthetical. A bare old sentence with no annotation **is** the failure mode every amendment
      in this document is written to avoid.
- [ ] **Step 6 — `python -m metrics.build --validate-only`** once more (Appendix N touches no
      `metrics/` path, but Task 11 did and this is the last chance to notice).

---

## Task 13: the full local gate, then the PR

- [ ] **Step 1 — the backend, all fifteen labels**, each `^OK`. Then `scripts/coverage_live_path.sh
      --gate` green.
- [ ] **Step 2 — the frontend.** `cd frontend && npm run build && npm test`. Nothing in this PR
      touches `frontend/`; run it because `Frontend result` is a required check and a surprise here
      is worth finding locally.
- [ ] **Step 3 — Go, all of it.** From `relay/`: `go build ./... && go vet ./... && go test -race
      ./... && golangci-lint run ./...`, plus `GOOS=linux golangci-lint run ./...`, plus
      `scripts/check_go_stdlib_only.sh relay`, `scripts/check_go_credential_logging.sh` and
      `scripts/coverage_relay_go.sh --gate`.
- [ ] **Step 4 — E2E's cheap half.** `cd e2e && npm run typecheck`, then
      `npx playwright test --project=guards`. Both green, no container needed. The heavy projects
      run in CI; this PR touches no `e2e/` test file other than the guards' own source.
- [ ] **Step 5 — `git diff --stat origin/main` names exactly the paths in § File structure**, and
      no others. Count them and say the number in your report. Expect **154**, which is what
      § File structure's own groups sum to: **106** deletions (97 in the package, 9 standalone),
      **4** renames, **1** new file and **43** modifications (13 Python production + 12 tests +
      3 Go + 8 routing/gates/CI + 7 guards/docs/metrics). Two of the 43 arrive late and are easy to
      miss when counting early: `scripts/capture_ffmpeg_stderr.py` (Task 1 Step 3, a by-hand
      docstring edit) and `scripts/coverage_live_path.floor.modules` (Task 9 Step 3, written by
      `--write-floor --shape-only`).
- [ ] **Step 6 — stage and commit in separate Bash calls**, message written with the Write tool and
      committed with `git commit -F <file>`. End it with the two attribution lines from
      brief-common rule 5.
- [ ] **Step 7 — push and open a DRAFT PR** with the body below. Wait for `Backend result`,
      `Frontend result`, `E2E result`, `Lifecycle result` and `Go result` before marking it ready.
- [ ] **Step 8 — remove your container and volume** if you started one.

---

## PR body template

Title: `relay(phase2): 2d-4 — delete apps/proxy/live_proxy/`

```markdown
## What

Deletes the Python live relay. The Go relay has carried every live viewer since 2d-3's nginx flip;
this removes the implementation it replaced — **97 files, 26,371 lines, 406 tests** — and closes
everything that pointed at it.

- **The package**, plus `apps/proxy/relay_views.py`, `apps/proxy/relay_urls.py`,
  `apps/proxy/tasks.py` and the `proxy` management command, none of which can be imported without
  it.
- **The eight remaining module-level import sites** (spec A10.3), `dispatcharr/settings.py`'s
  `INSTALLED_APPS` entry among them — the boot-fatal one — plus `apps/proxy/apps.py`'s `ready()`
  and the two `getattr(proxy_app, 'live_proxy')` consumers no import grep finds.
- **Three function-local `url_utils` importers** re-pointed at `apps.proxy.next_source`, where
  both names have actually lived since Phase 1 PR 6.
- **`resolve_base_url()` gains a per-direction `dev_url`.** Deleting `relay_views.py` leaves the
  `dev` shape — the only one with no nginx — with no `/proxy/relay/` route at all, so the
  Django→relay direction now names the Go relay's port there. The relay→Django direction is
  unchanged at :5656, and `DISPATCHARR_RELAY_BASE_URL` still wins ahead of both.
- **`worker_id` recomputed locally** in `ts_admin_views.py`, byte-identical to what
  `ProxyServer.worker_id` returned. The four response bodies are unchanged.
- **#190's five metadata-hash ranges deleted** from `apps/channels/models.py`, with a new test for
  the behaviour that changes — because nothing in the tree observed it in either direction.
- **Seventeen test files disposed of** per-file: 5 deleted whole, 5 split, 5 kept (four by
  re-pointing an import, one by a docstring), 2 rewritten. Every delete names the Go test that
  covers the same behaviour or says plainly that none exists. **Two of the seventeen name
  `live_proxy` nowhere** and are broken by this PR's own rulings rather than by the directory's
  absence — `test_relay_control_api.py` (it imports `relay_views`) and `test_internal_base_url.py`
  (it pins the dev address). Only executing the plan found them.
- **The parity matrix's Python column replaced** with Go citations, and rows 26/27 given a
  `retired:` Source sentinel the guard learns to read — backed by a `RETIRED_SOURCES` allowlist
  compared with `toEqual`, in `WHITE_BOX_ONLY`'s idiom.
- **The ffmpeg stderr corpus moved** into `relay/internal/relaytest/testdata/ffmpeg_stderr/`, and
  `go-tests.yml`'s `differential` job deleted.
- **16 labels → 15**, and Gate 2's module list 38 → 9.

## What this PR does NOT do

- **It does not move Gate 2's `missing`.** The only floor edit is `--write-floor --shape-only`,
  which never writes `missing`, `percent`, `measured` or `runs`. **The gate is deliberately slack
  until `migration/phase2d-gate2-recensus` (2d-5)**: a floor of 1525 over a denominator roughly a
  tenth its former size is mechanically green and substantively toothless, and the floor's own
  header now says so. 2d-5's census can only be taken on this tree, and its plan needs this PR's
  per-file test dispositions, which § File structure enumerates.
- **It touches no `docker/` file.** 2d-3 owns the deployment shape.
- **It does not delete `apps/proxy/hls_proxy/`** (Phase 4's), which is why `signals.py` keeps its
  `hls_proxy` branch verbatim beside the deleted `live_proxy` one.
- **It does not flip #190's ledger row.** `metrics/build/curated.py` requires a `fixed` row to
  carry a merged `fixed_in` PR number, and a PR cannot name itself — 2d-6's, like #273's and
  #295's.
- **It does not build a replacement for Gate 1's static half.** Retired, not met (spec A10.8), and
  the `apps/proxy/config.py` gap is recorded in CLAUDE.md § Testing rather than filled: it carried
  five of the scanner's twelve scope-2 edges and is now in neither gate.
- **It does not rewrite the ~694 Go doc comments** citing deleted Python filenames, the 23 prose
  `live_proxy` comments under `e2e/`, `COVERAGE.md:50`/`:202`, or
  `domain-fuzz-campaign.{md,lock.yml}` — all 2d-6's, per A10.6 and A10.10's own table.
- **It does not rename `ts_admin_views.py`'s `logging.getLogger("live_proxy.views")`** (A12.4,
  2d-6's), and it does not rename or remove `worker_id`, which is a contract change to four
  response bodies with no forcing function here.

## The capability that is genuinely lost, stated precisely

`go-tests.yml`'s `differential` job was **not** the only place `relay-go` ran beside real stores —
every E2E container already does. What it uniquely did was **drive** it: send the Go binary a tune
and assert on the bytes, against a real Django with a real `SECRET_KEY`. Nothing replaces it. What
it *proved* — two implementations agreeing byte for byte — has no meaning once there is one; what
it *incidentally provided*, a Go-binary-against-real-Django integration point, the E2E suite has
done through nginx on every `migration/**` run since 2d-3. 2d-3's own plan says so one PR ahead, so
this is a handover and not a discovery.

## Expected metric drift

`reverse_imports_into_proxy` 29 → 28 (`dispatcharr/urls.py`'s `stream_xc` import is the one that
goes; every re-pointed import still names `apps.proxy`). `models_boot_trap_imports` stays **0**,
where 2d-1 put it. Neither is gated.

## Gate

- `Backend result` green with **15** labels including `coverage-gate`.
- `tests/test_ci_test_routing.py` green, and `scripts/ci_backend_test_labels.py` verified on three
  paths including `scripts/coverage_live_path.floor` — the alias 2d-5 depends on.
- `E2E result` green including `guards`, with the rewritten `parity-matrix.spec.ts`.
- `Go result` green — the corpus move and the workflow edit both trigger it. The **Go coverage
  gate needs no floor edit**: `packages=` hashes `go list -deps .`, `relaytest` was already outside
  the linked set, `testdata/` is not a package, and `relay/go.mod` is untouched.
- `Lifecycle result` and `Frontend result` green.
- `python -m metrics.build --validate-only` green — run explicitly, because the commit gate runs it
  only when a `metrics/` path is staged and A10.15's trap is that it would otherwise surface on
  `main`.
- `manage.py check` **and** `manage.py showmigrations dispatcharr_channels` green — the pair that
  covers the boot path, since `DISPATCHARR_ROLE` appears in no Python file and the trap's victim is
  the migration loader (A11.8).
- No pending migration for `dispatcharr_channels`. A bare `makemigrations --check` is **not** clean
  at the seed — `core` has pre-existing drift (A11.8) — and this PR neither causes nor fixes it.
- `scripts/check_credential_logging.py` zero findings; zizmor zero findings on both edited
  workflows.
```

---


## Self-review

Every `file:line`, every count and every anchor was opened at the seed. Then **the whole plan was
executed**: every appendix applied to a throwaway worktree at the seed, all fifteen labels run in a
dedicated container (`plan2d4`, per brief-common rule 6 — not the shared `dispatcharr-testrunner`,
which is mounted at another agent's tree), the Go gate run, and the e2e guards run.

**The assembly is proved, not asserted, and proved from the DOCUMENT rather than from the scratch
files.** The appendix set is **disjoint by file** — no file appears in two appendices — so
`git apply` cannot conflict whatever order they run in. A script parses this markdown, extracts the
first fenced block under every `### Appendix …` heading, replays all of them into a pristine
worktree at the seed **in task order**, runs the three anchored scripts, and diffs the result
against the tree every check below was run on:

```
extracted 28 appendices: A.1 A.2 A.2a B C.1 C.2 C.3 C.4 C.5 D.1 D.4 E F H.1 H.2
                         I.1 I.2 I.3 I.4 J.1 J.2 K L M.1 M.2 N O R

=== every appendix applied in task order, from the DOCUMENT ===
IDENTICAL — the document's own appendices reproduce the verified tree
```

So the published text is what was tested, not a description of it. (Task 1 Step 3's two by-hand
edits — `CAPTURE.md`'s and `capture_ffmpeg_stderr.py`'s path mentions — are replayed by copy, since
`CAPTURE.md` is a `git mv` in the same task and a diff over it would fight the rename.)

**What was run against the composed tree.** All fifteen labels green, **2,083 tests**:

| Label | Tests | | Label | Tests |
|---|---|---|---|---|
| `apps.accounts.tests` | 28 | | `apps.plugins.tests` | 12 |
| `apps.backups.tests` | 73 | | `apps.proxy.tests` | **380** |
| `apps.channels.tests` | **343** | | `apps.proxy.vod_proxy.tests` | 53 |
| `apps.connect.tests` | 5 | | `apps.timeshift.tests` | 349 |
| `apps.dashboard.tests` | 0 (no test files) | | `apps.vod.tests` | 47 |
| `apps.epg.tests` | 295 | | `core.tests` | 105 |
| `apps.m3u.tests` | 164 | | `tests` | 158 |
| `apps.output.tests` | 71 | | **total** | **2,083** |

Seed baseline 2,212 across 16 labels, and `apps.proxy.tests` alone measured at `Ran 428 tests … OK`
on the unmodified seed **in the same container** — so every failure seen during development was
caused by this plan rather than inherited. `iter_test_package_labels()` returns exactly 15.

- `manage.py check` clean (only the pre-existing `staticfiles.W004`); `showmigrations
  dispatcharr_channels` drives the migration loader; `makemigrations --check --dry-run
  dispatcharr_channels` → `No changes detected`.
- `ci_backend_test_labels.py scripts/coverage_live_path.floor` →
  `["apps.channels.tests", "apps.proxy.tests"]` — the 2d-5-critical case.
- `metrics.build --validate-only` → `ok: 46 metrics, 36 milestones, 32 defects`;
  `check_credential_logging.py` zero findings.
- **Go**: `build`, `vet`, `test -race ./...` exit 0 over 11 packages, `golangci-lint` `0 issues.`
  native **and** `GOOS=linux`, `check_go_stdlib_only.sh` OK, `check_go_credential_logging.sh`
  12 packages clean, `coverage_relay_go.sh --gate` **GATE PASSED** (`missing=588` vs floor 589).
- **e2e** — the gap the first draft could not close: `npm ci`, `npx tsc --noEmit` exit 0,
  `npx playwright test --project=guards` **18 passed**, with
  `parity matrix (Go): 28 of 28 pinned rows carry a Go reference; 2 row(s) are not pinnable.`
- **Break-checks run**: the corpus's package-relative path (Task 1 Step 5 — panics from the calling
  packages, passes in `relaytest`'s own); the re-homed detail assertion (one struct tag); the `dev_url` reversion; the
  `_PATH_ALIASES` deletion; and the #190 reversion, which is quoted verbatim in R8 and Task 5.

**What changed because the plan was executed, and could not have been found by reading it.**

1. **R6 is the reverse of its first draft.** Deleting the live URL patterns 403s every tune behind
   nginx, because the authorize hop resolves them through Django's own urlconf. 22 failures, 5
   errors. `apps/proxy/stream_routes.py` is the answer.
2. **R7 is seventeen files, not fifteen.** Two are broken by this plan's *own rulings* and name
   `live_proxy` nowhere, so the classifier was structurally unable to find them.
3. **R8's break-check named the wrong reversion** and quoted a message neither reversion produced.
   The test is sound; the instruction was not. Both are now measured and quoted.
4. **Appendix A.2 overlapped Appendix B on one file**, so the set could not be applied in task
   order. The set is now disjoint by construction, and the replay proves it.

**What remains unverified, stated as such.** Task 9's coverage round
(`coverage_live_path_isolated.sh` + `--write-floor --shape-only`) — the `modules=7804792af4f7`
prediction is a hand computation from the include list using the gate's own formula, and Task 9
Step 4 **STOPs** on a mismatch rather than accepting whatever prints. `manage.py spectacular`
(Task 4). The frontend suite and the heavy Playwright projects. Task 2 Step 3's break-check, which
can only run at Task 2 while `url_utils.py` still exists.

**One open question for the orchestrator.** 2d-3's Appendix F also edits **§ Test hooks** in
`CLAUDE.md`, where Appendix K's first two edits land. They target different sentences, but the
re-seed must check; `assert count == 1` is the backstop, and it stops rather than editing something
else.

---

## Appendices

**Regenerated as one set from the tree the verification ran on.** Two properties make them
reviewable and, more importantly, make their application provable:

1. **Disjoint by file.** No file appears in two appendices. `git apply` therefore cannot conflict
   whatever order they run in, so Task 0 Step 3b's `--check` sweep is a complete proof rather than
   an indicative one, and the task order below is narrative rather than load-bearing.
2. **Replayed.** A pristine worktree at the seed, every appendix applied in task order, the three
   scripts run, then `diff -r` against the tree they were generated from → **identical**.

Three are **anchored Python scripts** rather than diffs — E (the matrix), K (`CLAUDE.md`) and N (the
spec) — in 2d-2's and 2d-3's established idiom, because 2d-3 moves every line number in the last two
and because a diff of twenty-one 600-character table rows is unreadable in review. Each asserts every
anchor matched **exactly once** and prints its own count, which the task steps quote verbatim.

| Appendix | Files | Task |
|---|---|---|
| A.1 | the reference classifier (script, provenance) | 0 |
| D.1 | `relay/internal/relaytest/{corpus.go,asset_test.go}` | 1 |
| B | `apps/proxy/authorize.py`, `apps/m3u/connection_pool.py`, `dispatcharr/consumers.py`, `tests/test_websocket_consumer_filter.py` | 2 |
| L | `apps/proxy/ts_admin_views.py` | 3 |
| O | `apps/proxy/stream_routes.py` (new file, verbatim) | 4 |
| C.1 | `apps/proxy/urls.py` | 4 |
| C.2 | `apps/proxy/{internal_base_url.py,relay_client.py}` | 4 |
| C.3 | `apps/proxy/tests/test_boundary_error_arms.py` | 4 |
| M.1 | `apps/channels/models.py` | 5 |
| M.2 | `apps/channels/tests/test_get_stream_assignment.py` | 5 |
| C.4 | `dispatcharr/settings.py`, `apps/proxy/{apps.py,signals.py}` | 6 |
| C.5 | `dispatcharr/urls.py` | 6 |
| A.2 | the eight remaining test files | 7 |
| D.4 | `relay/httpapi/detail_golden_test.go` | 7 |
| I.1 | `dispatcharr/test_discovery.py`, `tests/test_ci_test_routing.py` | 8 |
| I.2 | `.claude/hooks/run-affected-tests.sh`, `scripts/coverage_live_path_isolated.sh` | 8 |
| I.3 | `.github/workflows/backend-tests.yml` | 8 |
| I.4 | `.github/workflows/go-tests.yml` | 8 |
| H.1 | `scripts/coverage_live_path.coveragerc` | 9 |
| H.2 | `scripts/coverage_live_path.floor` (header only) | 9 |
| E | `docs/relay-parity-matrix.md` (script) | 10 |
| F | `e2e/tests/guards/parity-matrix{.ts,.spec.ts}` | 10 |
| J.1 | `metrics/curated/defects.yml` | 11 |
| J.2 | `e2e/COVERAGE.md` | 11 |
| K | `CLAUDE.md` (script) | 12 |
| N | the spec (script) | 12 |

**38 files, 21 diffs, 1 verbatim file, 3 scripts, plus A.1's provenance script.** Everything an
earlier draft carried under Appendix G is gone: it was a byte-identical duplicate of A.2.

### Appendix A.1 — the reference classifier (Task 0 Step 3)

Provenance for R7's table. It separates module-level imports, function-local imports,
`mock.patch` **string** targets and prose — three kinds A10.14's grep does not distinguish.
**What it cannot see** is R7's addendum: files broken by this plan's own rulings rather than
by the directory's absence.

```python
import os, re, collections, sys
root = "/Users/dion/git/Dispatcharr/.worktrees/plan2d4-seed"
os.chdir(root)
IMPORT_RE = re.compile(r'^\s*(from\s+apps\.proxy\.live_proxy|import\s+apps\.proxy\.live_proxy|from\s+\.live_proxy|from\s+apps\.proxy\s+import\s+live_proxy)')
PATCH_RE = re.compile(r'["\'](apps\.proxy\.live_proxy[\w\.]*)["\']')
rows = collections.defaultdict(lambda: {"imports":0,"patch":0,"other":0,"patch_targets":set()})
for dirpath, dirnames, filenames in os.walk("."):
    dirnames[:] = [d for d in dirnames if d not in (".git",".worktrees","node_modules",".venv")]
    for fn in filenames:
        if not fn.endswith(".py"): continue
        p = os.path.join(dirpath, fn)[2:]
        if p.startswith("apps/proxy/live_proxy/"): continue
        try: txt = open(p, encoding="utf-8").read()
        except Exception: continue
        if "live_proxy" not in txt: continue
        for ln in txt.splitlines():
            if "live_proxy" not in ln: continue
            if IMPORT_RE.match(ln): rows[p]["imports"] += 1
            elif PATCH_RE.search(ln):
                rows[p]["patch"] += 1
                rows[p]["patch_targets"].update(PATCH_RE.findall(ln))
            else: rows[p]["other"] += 1
for p in sorted(rows):
    r = rows[p]
    print(f"{p}\timp={r['imports']}\tstr={r['patch']}\tother={r['other']}")
    if r["patch_targets"]:
        print("    targets:", ", ".join(sorted(r["patch_targets"])))
```

### Appendix D.1 — the Go corpus move and the digest pin (R12), Task 1

The four fixture files move by `git mv` in Task 1 Step 1 and carry no content change, so they
are not in the diff — `git status` must show four `R` entries and no `D`+`A` pair.

**The one thing to read the diff for**: `pkgDir()` is a ONE-deep `runtime.Caller` walk and
`RepoRoot()` is re-expressed on top of it, so there is a single `runtime.Caller` call site and
`relay/drain`'s tests keep working. `CorpusPath` still returns an ABSOLUTE path, which the
eleven argv callers require.

```diff
diff --git a/relay/internal/relaytest/asset_test.go b/relay/internal/relaytest/asset_test.go
index 3019a0ed..b36816f9 100644
--- a/relay/internal/relaytest/asset_test.go
+++ b/relay/internal/relaytest/asset_test.go
@@ -1,29 +1,27 @@
 package relaytest
 
 import (
-	"crypto/sha256"
-	"encoding/hex"
 	"testing"
 )
 
-// THE CROSS-IMPLEMENTATION PIN. This digest was produced by the PYTHON
-// harness's synthetic_ts() -- apps/proxy/live_proxy/tests/harness/asset.py --
-// not by the Go above it, so it proves the two implementations agree rather
-// than that this one is deterministic (hollow shape 1). Regenerate it with the
-// snippet in this PR's Task, never by running the Go.
+// THE CROSS-IMPLEMENTATION DIGEST PIN WAS DELETED BY PHASE 2 STAGE 2d-4, AND
+// THAT IS THE POINT. Its own header said what it was for: the sha256 came from
+// the PYTHON harness's synthetic_ts(), "so it proves the two implementations
+// agree rather than that this one is deterministic (hollow shape 1)". With
+// apps/proxy/live_proxy/ deleted there is one implementation, and the digest
+// would prove only that SyntheticTS is a pure function of its arguments --
+// which is the hollow shape the pin was written to avoid. It was deleted
+// rather than regenerated from the Go, because regenerating it is exactly the
+// move its own comment forbade.
 //
-// It is what makes a differential test possible at all: drive the Python relay
-// and the Go relay from the same bytes and compare what each client receives.
-func TestSyntheticTSMatchesThePythonHarness(t *testing.T) {
-	const want = "e565411f3bbe6d0ab88a4dcd45d9e2a9ca1f65e049846dc5f61a2ec162f57f89"
+// What survives is the SHAPE, which still pins the asset against the e2e fake
+// provider rather than against a deleted Python file: 512 packets of 188
+// bytes is 96,256, and PacketSize/PacketPID below read the same bytes back.
+func TestSyntheticTSHasThePacketCountAndSizeItsCallersAssume(t *testing.T) {
 	data := SyntheticTS(512, 0x100)
-	if len(data) != 96256 {
-		t.Fatalf("SyntheticTS(512, 0x100) is %d bytes, want 96256", len(data))
-	}
-	sum := sha256.Sum256(data)
-	if got := hex.EncodeToString(sum[:]); got != want {
-		t.Fatalf("SyntheticTS(512, 0x100) hashes to %s, want %s -- the Go asset has "+
-			"diverged from harness/asset.py's synthetic_ts()", got, want)
+	if want := 512 * PacketSize; len(data) != want {
+		t.Fatalf("SyntheticTS(512, 0x100) is %d bytes, want %d (512 x %d)",
+			len(data), want, PacketSize)
 	}
 }
 
@@ -68,17 +66,22 @@ func corrupted(packet []byte) []byte {
 	return out
 }
 
-// Global Constraint 8's ratchet, found missing by review: NominalByteRate and
-// WriteChunk named a file with no line and nothing asserted them.
-// apps/proxy/live_proxy/tests/harness/upstream.py:29 (NOMINAL_BYTE_RATE) and
-// :31 (_WRITE_CHUNK) are what these mirror, verified against this tree.
-func TestNominalByteRateAndWriteChunkMatchThePythonHarness(t *testing.T) {
-	if NominalByteRate != 250000 {
-		t.Errorf("NominalByteRate = %d, want 250000 (apps/proxy/live_proxy/tests/harness/upstream.py:29)",
-			NominalByteRate)
+// These two mirrored apps/proxy/live_proxy/tests/harness/upstream.py:29
+// (NOMINAL_BYTE_RATE) and :31 (_WRITE_CHUNK), which stage 2d-4 deleted. The
+// assertions are kept, re-anchored on the DERIVATIONS rather than the deleted
+// file, so the numbers stay checkable:
+//
+//	NominalByteRate = 2_000_000 / 8 -- "rate 1.0" is 2 Mbit/s, the bitrate
+//	e2e-upstream/scripts/make-asset.sh builds its own asset at. That file
+//	survives 2d and is the right anchor.
+//	WriteChunk = PacketSize * 50 -- fifty whole TS packets per write.
+func TestNominalByteRateAndWriteChunkKeepTheirDerivations(t *testing.T) {
+	if want := 2_000_000 / 8; NominalByteRate != want {
+		t.Errorf("NominalByteRate = %d, want %d (2 Mbit/s in bytes per second, "+
+			"e2e-upstream/scripts/make-asset.sh's bitrate)", NominalByteRate, want)
 	}
-	if WriteChunk != 9400 {
-		t.Errorf("WriteChunk = %d, want 9400 (apps/proxy/live_proxy/tests/harness/upstream.py:31)", WriteChunk)
+	if want := PacketSize * 50; WriteChunk != want {
+		t.Errorf("WriteChunk = %d, want %d (fifty whole TS packets)", WriteChunk, want)
 	}
 }
 
diff --git a/relay/internal/relaytest/corpus.go b/relay/internal/relaytest/corpus.go
index 0aa3bde4..2f47be90 100644
--- a/relay/internal/relaytest/corpus.go
+++ b/relay/internal/relaytest/corpus.go
@@ -10,51 +10,63 @@ import (
 	"strconv"
 )
 
-// The captured real-ffmpeg stderr corpus, READ IN PLACE from the Python
-// harness's own fixtures directory and never copied into this module.
+// The captured real-ffmpeg stderr corpus, in this package's own testdata
+// directory since Phase 2 stage 2d-4.
 //
-// apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/CAPTURE.md is
-// the authority on what these files are: verbatim captures from ffmpeg 8.1.2,
-// CR separators included, never hand-edited. Two copies of a corpus that must
-// not be edited is one copy nobody remembers to regenerate, so the Go tests
-// open the same bytes the Python tests open. Every rule that file states
-// about the corpus -- the digits are a timing measurement, only the SHAPE is
-// asserted -- binds the Go tests too.
+// It used to be READ IN PLACE from the Python harness's fixtures directory
+// and never copied, because "two copies of a corpus that must not be edited
+// is one copy nobody remembers to regenerate". Stage 2d-4 deleted
+// apps/proxy/live_proxy/, so there is no second copy to diverge from and the
+// rationale went with it; the files moved here rather than being duplicated.
+//
+// testdata/ffmpeg_stderr/CAPTURE.md moved with them and is still the
+// authority on what they are: verbatim captures from ffmpeg 8.1.2, CR
+// separators included, never hand-edited, regenerated only by
+// scripts/capture_ffmpeg_stderr.py. Every rule it states about the corpus --
+// the digits are a timing measurement, only the SHAPE is asserted -- binds
+// these tests.
 
-// CorpusNames are the three captures, harness/ffmpeg_stderr.py:15's
-// CORPUS_NAMES.
+// CorpusNames are the three captures.
 var CorpusNames = []string{"normal", "slow-trickle", "truncation"}
 
-// repoRoot locates the repository from this file's own path: relay/internal/
-// relaytest/corpus.go is four levels below it. runtime.Caller rather than
-// the working directory, because `go test` sets the cwd to the PACKAGE
-// directory, which is a different depth for every package that reads the
-// corpus.
-func repoRoot() string {
+// pkgDir is this file's own directory, from its compiled-in path.
+//
+// runtime.Caller rather than a relative string, and this is the whole reason
+// the corpus move needed a code change at all: `go test` sets the working
+// directory to the PACKAGE being tested, and Corpus() is called from
+// relay/ffmpeg, relay/httpapi and relay/channel as well as from here. A bare
+// "testdata/..." resolves against the CALLER's directory and is found only in
+// this package -- green in the one place a maintainer would look first, and
+// a panic everywhere else.
+//
+// The value stays ABSOLUTE because CorpusPath's eleven callers hand it through
+// argv to a re-exec'd stand-in (standin.go), which has no cwd of its own to
+// resolve against. Note -trimpath would defeat this; nothing runs `go test`
+// with it (docker/Dockerfile's `go build -trimpath` is the production binary).
+func pkgDir() string {
 	_, file, _, ok := runtime.Caller(0)
 	if !ok {
 		panic("relaytest: runtime.Caller failed")
 	}
-	return filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(file))))
+	return filepath.Dir(file)
 }
 
 // RepoRoot is the repository root, resolved from this file's own compiled-in
-// path. Exported because this package is the module's ONE answer to "where is
-// the repo from a test": relay/drain's own test reads
+// path: relay/internal/relaytest is three levels below it. Exported because
+// this package is the module's ONE answer to "where is the repo from a test",
+// and since stage 2d-4 moved the corpus into testdata/ it is the module's only
+// repo-relative read left: relay/drain's tests read
 // docker/supervisord.d/relay-go.conf through it, and a second, independently
 // maintained directory walk is the kind of drift that goes wrong quietly.
-//
-// runtime.Caller rather than the working directory, for the reason repoRoot's
-// own comment gives: `go test` sets the cwd to the PACKAGE directory, which is
-// a different depth for every package that asks.
-func RepoRoot() string { return repoRoot() }
+func RepoRoot() string {
+	return filepath.Dir(filepath.Dir(filepath.Dir(pkgDir())))
+}
 
 // CorpusPath is the absolute path of one capture.
 func CorpusPath(name string) string {
 	for _, known := range CorpusNames {
 		if known == name {
-			return filepath.Join(repoRoot(), "apps", "proxy", "live_proxy", "tests", "harness",
-				"fixtures", "ffmpeg_stderr", name+".stderr")
+			return filepath.Join(pkgDir(), "testdata", "ffmpeg_stderr", name+".stderr")
 		}
 	}
 	panic(fmt.Sprintf("relaytest: unknown corpus %q", name))
```

### Appendix B — the three `url_utils` importers and their coupled patch strings (R3), Task 2

**One patch on purpose.** R3 explains that splitting the production import from the three
patch strings lets `assert_not_called()` pass vacuously — the "a test can go hollow without
changing" shape, invisible to a diff review.

```diff
diff --git a/apps/m3u/connection_pool.py b/apps/m3u/connection_pool.py
index 375714ee..61952cc7 100644
--- a/apps/m3u/connection_pool.py
+++ b/apps/m3u/connection_pool.py
@@ -78,7 +78,7 @@ def _fingerprint_from_profile_stream_url(profile) -> Optional[str]:
         return None
 
     try:
-        from apps.proxy.live_proxy.url_utils import transform_url
+        from apps.proxy.next_source import transform_url
 
         transformed = transform_url(
             sample_url,
diff --git a/apps/proxy/authorize.py b/apps/proxy/authorize.py
index ea5fd9e0..a5222155 100644
--- a/apps/proxy/authorize.py
+++ b/apps/proxy/authorize.py
@@ -377,7 +377,7 @@ def _resolve_channel(surface, identifier):
     from apps.channels.models import Channel
 
     if surface == SURFACE_LIVE:
-        from apps.proxy.live_proxy.url_utils import get_stream_object
+        from apps.proxy.next_source import get_stream_object
 
         try:
             target = get_stream_object(identifier)
diff --git a/dispatcharr/consumers.py b/dispatcharr/consumers.py
index 41cd9a03..58ec7eca 100644
--- a/dispatcharr/consumers.py
+++ b/dispatcharr/consumers.py
@@ -117,7 +117,7 @@ class MyWebSocketConsumer(AsyncWebsocketConsumer):
             if not user_is_admin(self.scope.get("user")):
                 return
 
-            from apps.proxy.live_proxy.url_utils import transform_url
+            from apps.proxy.next_source import transform_url
 
             url = data.get("url") or ""
             search = data.get("search") or ""
diff --git a/tests/test_websocket_consumer_filter.py b/tests/test_websocket_consumer_filter.py
index 99013454..b606282b 100644
--- a/tests/test_websocket_consumer_filter.py
+++ b/tests/test_websocket_consumer_filter.py
@@ -230,7 +230,7 @@ class ConsumerM3UProfileTestReceiveTests(SimpleTestCase):
             "replace": "b",
         }
         with patch(
-            "apps.proxy.live_proxy.url_utils.transform_url",
+            "apps.proxy.next_source.transform_url",
             return_value="http://example.com/b",
         ) as mock_transform:
             async_to_sync(consumer.receive)(json.dumps(payload))
@@ -253,7 +253,7 @@ class ConsumerM3UProfileTestReceiveTests(SimpleTestCase):
             "replace": "b",
         }
         with patch(
-            "apps.proxy.live_proxy.url_utils.transform_url"
+            "apps.proxy.next_source.transform_url"
         ) as mock_transform, patch(
             "dispatcharr.consumers.regex.sub"
         ) as mock_sub:
@@ -311,7 +311,7 @@ class ConsumerM3UProfileTestReceiveTests(SimpleTestCase):
             "replace": "b",
         }
         with patch(
-            "apps.proxy.live_proxy.url_utils.transform_url",
+            "apps.proxy.next_source.transform_url",
             return_value="http://example.com/b",
         ), patch(
             "dispatcharr.consumers.regex.sub",
```

### Appendix L — `worker_id` in `ts_admin_views.py` (R2), Task 3

```diff
diff --git a/apps/proxy/ts_admin_views.py b/apps/proxy/ts_admin_views.py
index 2945192b..7fbf00f1 100644
--- a/apps/proxy/ts_admin_views.py
+++ b/apps/proxy/ts_admin_views.py
@@ -13,13 +13,14 @@ the API socket; only `^~ /proxy/ts/stream/` is relay-bound). Stage 2d-4
 deletes apps/proxy/live_proxy/ and this surface has to survive it, which is
 the whole reason for the move.
 
-The two remaining live_proxy references are function-local on purpose and
-are named in the stage 2d-4 dependency list: ProxyServer, for worker_id,
-inside change_stream and next_stream.
+Stage 2d-4 removed the two function-local ProxyServer imports 2d-2 left
+here. See _worker_id() below.
 """
 
 import json
 import logging
+import os
+import socket
 
 from django.core.exceptions import ImproperlyConfigured
 from django.db import close_old_connections
@@ -42,22 +43,31 @@ from dispatcharr.utils import redact_url
 logger = logging.getLogger("live_proxy.views")
 
 
+def _worker_id():
+    """The value ProxyServer.worker_id carried, computed where it is read.
+
+    f"{hostname}:{pid}" -- apps/proxy/live_proxy/server.py:95-98 verbatim,
+    which is what change_stream and next_stream wanted the singleton for and
+    the only thing they wanted it for. Stage 2d-2 declined to recompute it
+    because its constraint was no behaviour change and the singleton's pid
+    could in principle predate a fork; with the package deleted this is the
+    only way to keep the same value, and the fork caveat inverts -- getpid()
+    at request time names the worker actually answering, which is what this
+    field has been since Phase 1 PR 4 routed these views to the api role.
+
+    It has never been the RELAY's worker id and there is no Python relay for
+    it to be misread as any more. Renaming or removing it is a contract
+    change to four response bodies with no forcing function here; it is on
+    the post-2d list beside this module's logger name.
+    """
+    return f"{socket.gethostname()}:{os.getpid()}"
+
+
 @csrf_exempt
 @api_view(["POST"])
 @permission_classes([IsAdmin])
 def change_stream(request, channel_id):
     """Change stream URL for existing channel with enhanced diagnostics"""
-    # Function-local, in this module's own idiom (D10) and for the reason
-    # 2d-2 exists: ProxyServer lives in the package 2d-4 deletes, this
-    # module survives it, and a module-level import here would be a tenth
-    # boot-trap site (Amendment A10.3) in a surviving file. worker_id --
-    # hostname:pid, server.py:96-98 -- is the only thing these two views
-    # want from it, and it is in both of their response bodies. Called
-    # here rather than lazily at the two bodies that read it so the
-    # singleton is constructed at exactly the point it is today.
-    from apps.proxy.live_proxy.server import ProxyServer
-
-    proxy_server = ProxyServer.get_instance()
     from apps.proxy import relay_client
 
     try:
@@ -193,7 +203,7 @@ def change_stream(request, channel_id):
                 "channel": channel_id,
                 "url": new_url,
                 "owner": result.get("direct_update", False),
-                "worker_id": proxy_server.worker_id,
+                "worker_id": _worker_id(),
             }
             if stream_id:
                 error_data["stream_id"] = stream_id
@@ -207,7 +217,7 @@ def change_stream(request, channel_id):
             "channel": channel_id,
             "url": new_url,
             "owner": result.get("direct_update", False),
-            "worker_id": proxy_server.worker_id,
+            "worker_id": _worker_id(),
         }
 
         # Include stream_id in response if it was used
@@ -399,10 +409,6 @@ def stop_client(request, channel_id):
 @permission_classes([IsAdmin])
 def next_stream(request, channel_id):
     """Switch to the next available stream for a channel"""
-    # Function-local: see change_stream above.
-    from apps.proxy.live_proxy.server import ProxyServer
-
-    proxy_server = ProxyServer.get_instance()
     from apps.proxy import relay_client
 
     try:
@@ -539,7 +545,7 @@ def next_stream(request, channel_id):
                     "current_stream_id": current_stream_id,
                     "next_stream_id": next_stream_id,
                     "owner": result.get("direct_update", False),
-                    "worker_id": proxy_server.worker_id,
+                    "worker_id": _worker_id(),
                 },
                 status=504 if result.get("confirmed") is False else 502,
             )
@@ -552,7 +558,7 @@ def next_stream(request, channel_id):
             "new_stream_id": next_stream_id,
             "new_url": stream_info["url"],
             "owner": result.get("direct_update", False),
-            "worker_id": proxy_server.worker_id,
+            "worker_id": _worker_id(),
         }
 
         return JsonResponse(response_data)
```

### Appendix O — `apps/proxy/stream_routes.py` (new file, verbatim) — R6, Task 4 Step 2

**Without this file the tree does not import, and without its URL patterns the authorize hop
403s every live tune behind nginx.** Its header is the ruling in prose.

```python
"""The live-stream URL patterns Django keeps so the authorize hop can resolve.

Phase 2 stage 2d-4 deleted apps/proxy/live_proxy/, and with it stream_ts and
stream_xc -- the two views nginx has routed to the Go relay since 2d-3. The URL
PATTERNS cannot go with them, and the reason is not routing:

    apps/proxy/authorize_views.py's _surface_for() hands the URI in
    X-Original-URI to DJANGO'S OWN RESOLVER and keys on the matched view's
    __name__ ("stream_ts", "stream_xc"). Its comment says why it is written
    that way -- "rather than re-deriving each surface's URL shape here, a
    second copy of the urlconf, guaranteed to drift".

So with these patterns removed, every `auth_request` subrequest for a live tune
resolves to the SPA catch-all and authorize_view answers 403 -- in production,
on the one surface this whole phase exists to keep working. Measured: removing
them turns 22 tests in apps/proxy/tests red, all of them on the authorize hop.

These two callables therefore exist to BE RESOLVED, never to be called. nginx
sends /proxy/ts/stream/ and both XC live roots to the Go relay, so nothing
reaches them in any shape that runs nginx. The one shape that does not is
DISPATCHARR_ENV=dev, where docker/supervisord/all-dev.conf starts relay-go and
the Go relay serves the same paths on its own port (DISPATCHARR_RELAY_GO_PORT,
5658 by default) -- so a request arriving here is a developer pointing at the
wrong port, and saying so plainly is more useful than a 404 that looks like a
missing channel.
"""

import logging

from django.http import JsonResponse
from django.urls import path, re_path
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from dispatcharr.utils import XC_STREAM_ID_PATTERN

# "live_proxy", not "live_proxy.views": apps/proxy/next_source.py:34-38's
# precedent, and this is not a views module. Renaming it once the directory
# behind the name is gone is 2d-6's, which now has TWO sites -- this one and
# apps/proxy/ts_admin_views.py's (spec Amendment A12.4).
logger = logging.getLogger("live_proxy")

_MOVED = {
    "error": "This endpoint is served by the Go relay.",
    "detail": (
        "Phase 2 stage 2d-3 pointed nginx at the Go relay for /proxy/ts/stream/ "
        "and both Xtream live roots. Reaching Django here means no nginx is in "
        "front: in DISPATCHARR_ENV=dev, tune against the relay's own port "
        "(DISPATCHARR_RELAY_GO_PORT, 5658 by default)."
    ),
}


def _moved():
    # 501, not 404: a 404 is indistinguishable from an unknown channel, which
    # is the one thing a developer debugging a tune must not be told wrongly.
    return JsonResponse(_MOVED, status=501)


@csrf_exempt
@api_view(["GET", "HEAD"])
@permission_classes([AllowAny])
def stream_ts(request, channel_id):
    """Resolved by _surface_for as SURFACE_LIVE. Never called behind nginx."""
    logger.warning("stream_ts reached Django; the Go relay serves this route")
    return _moved()


@csrf_exempt
@api_view(["GET", "HEAD"])
@permission_classes([AllowAny])
def stream_xc(request, username, password, channel_id):
    """Resolved by _surface_for as SURFACE_LIVE_XC. Never called behind nginx."""
    logger.warning("stream_xc reached Django; the Go relay serves this route")
    return _moved()


# The namespace is UNCHANGED from apps/proxy/live_proxy/urls.py:4, deliberately:
# Global Constraint 6 is no behaviour change on a surviving surface, and
# `proxy:live_proxy:stream` is a reversible name even though nothing in the tree
# reverses it (`grep -rn "live_proxy:stream"` is empty, and
# apps/proxy/ts_admin_urls.py:11-13 records the same fact for its own six).
# Keeping it costs nothing; changing it would be an unstated contract change.
app_name = "live_proxy"

urlpatterns = [
    path("stream/<str:channel_id>", stream_ts, name="stream"),
]

# The two root-level Xtream live patterns, verbatim from dispatcharr/urls.py,
# spliced back into the root urlconf so the pattern text has one home.
# XC_STREAM_ID_PATTERN and \Z are load-bearing exactly as they were: Phase 1
# D7's three-segment regex trap is unchanged, and
# tests/test_urls_xc_three_segment.py still pins it.
xc_urlpatterns = [
    re_path(
        rf"^live/(?P<username>[^/]+)/(?P<password>[^/]+)/(?P<channel_id>{XC_STREAM_ID_PATTERN})\Z",
        stream_xc,
        name="xc_live_stream_endpoint",
    ),
    re_path(
        rf"^(?P<username>[^/]+)/(?P<password>[^/]+)/(?P<channel_id>{XC_STREAM_ID_PATTERN})\Z",
        stream_xc,
        name="xc_stream_endpoint",
    ),
]
```

### Appendix C.1 — `apps/proxy/urls.py` (R1, R6), Task 4

```diff
diff --git a/apps/proxy/urls.py b/apps/proxy/urls.py
index 76891f8f..6023815c 100644
--- a/apps/proxy/urls.py
+++ b/apps/proxy/urls.py
@@ -6,9 +6,8 @@ app_name = 'proxy'
 
 urlpatterns = [
     path('stats/', stats_views.combined_stats, name='combined_stats'),
-    path('relay/', include('apps.proxy.relay_urls')),
     path('ts/', include('apps.proxy.ts_admin_urls')),
-    path('ts/', include('apps.proxy.live_proxy.urls')),
+    path('ts/', include('apps.proxy.stream_routes')),
     path('catchup/', include('apps.timeshift.urls')),
     path('vod/', include('apps.proxy.vod_proxy.urls')),
 ]
```

### Appendix C.2 — the `dev` address, both directions (R1), Task 4

`resolve_base_url()` gains `dev_url`; `dev_relay_url()` reads `DISPATCHARR_RELAY_GO_PORT` with
A10.16's default-and-validate shape; `relay_client.get_relay_control_base_url()` passes it.
`get_control_plane_base_url()` is deliberately untouched — Django is still on :5656 in dev,
and `docker/supervisord/all-dev.conf` does start `relay-go` on 5658.

```diff
diff --git a/apps/proxy/internal_base_url.py b/apps/proxy/internal_base_url.py
index bcf60205..d331a1a3 100644
--- a/apps/proxy/internal_base_url.py
+++ b/apps/proxy/internal_base_url.py
@@ -46,6 +46,9 @@ logger = logging.getLogger(__name__)
 # than one per call. Callers still see the exception every time.
 _host_validation_warned = False
 
+# Same one-warning-per-process policy, for the dev relay port.
+_relay_go_port_warned = False
+
 
 def _var_only_subject(var_name):
     # Used where the value itself must not be echoed at all -- a
@@ -145,7 +148,57 @@ def validated_base_url(url, var_name=None):
     )
 
 
-def resolve_base_url(*, override_var, modular_host_var, modular_host_default):
+DEV_API_URL = "http://127.0.0.1:5656"
+
+# The Go relay's default listener (relay/config/config.go:63,
+# docker/healthcheck.sh:33, docker/supervisord.d/relay-go.conf). Only the
+# dev branch needs it: every other branch reaches nginx, which routes
+# ^~ /proxy/relay/ to the Go relay itself since stage 2d-3.
+RELAY_GO_DEFAULT_PORT = "5658"
+
+
+def dev_relay_url():
+    """Where /proxy/relay/... answers in dev, now that Django does not.
+
+    Stage 2d-4 deleted apps/proxy/relay_views.py and relay_urls.py with
+    the package they wrapped, so the API process serves no /proxy/relay/
+    route at all. In every shape but dev that is invisible -- nginx has
+    routed those four paths to the Go relay since 2d-3 -- but dev runs no
+    nginx (docker/supervisord/all-dev.conf), so this direction must name
+    the Go relay's own port rather than the API's.
+
+    Reads DISPATCHARR_RELAY_GO_PORT with the default-and-validate shape
+    docker/init/03-init-dispatcharr.sh:88-93 already uses for
+    DISPATCHARR_RELAY_PORT, and which Amendment A10.16 required of the
+    RELAY_GO_UPSTREAM sed: a non-integer or out-of-range value logs once
+    naming the variable and falls back, rather than raising. A bad port in
+    a dev-only address is not worth failing a tune for, and the operator
+    override DISPATCHARR_RELAY_BASE_URL still wins ahead of this.
+    """
+    raw = os.environ.get("DISPATCHARR_RELAY_GO_PORT", "").strip()
+    port = RELAY_GO_DEFAULT_PORT
+    if raw:
+        try:
+            value = int(raw)
+        except ValueError:
+            value = None
+        if value is not None and 1 <= value <= 65535:
+            port = str(value)
+        else:
+            global _relay_go_port_warned
+            if not _relay_go_port_warned:
+                logger.warning(
+                    "DISPATCHARR_RELAY_GO_PORT is not a port number; "
+                    "using %s for the dev relay address.",
+                    RELAY_GO_DEFAULT_PORT,
+                )
+                _relay_go_port_warned = True
+    return f"http://127.0.0.1:{port}"
+
+
+def resolve_base_url(
+    *, override_var, modular_host_var, modular_host_default, dev_url=DEV_API_URL
+):
     """The D9 four-branch formula, once, for whichever direction asks.
 
     Same shape as get_dvr_stream_base_url() (apps/channels/tasks.py),
@@ -154,15 +207,14 @@ def resolve_base_url(*, override_var, modular_host_var, modular_host_default):
     DISPATCHARR_PORT. Every branch validates before returning, so a
     misconfigured host fails loudly here instead of as an opaque 400.
 
-    The dev branch has no nginx to go through, so it names the
-    application port directly. What answers there depends on how dev
-    was started: a bare `manage.py runserver 5656` is one process
-    serving both sides, while docker/supervisord/all-dev.conf runs
-    api-uwsgi AND relay-uwsgi with no nginx, so :5656 is the API
-    uWSGI and /proxy/relay/... is served by the API process. Both
-    work -- one Redis, and ChannelService reaches a channel's owner
-    over live:events: pub/sub either way -- but the second cannot
-    clear a StreamManager it does not hold (see reset_tried).
+    The dev branch has no nginx to go through, so it names an application
+    port directly -- and since stage 2d-4 the two directions name
+    DIFFERENT ones, which is why it is a parameter. Relay -> Django is
+    still :5656, Django's own port under both `manage.py runserver 5656`
+    and docker/supervisord/all-dev.conf's api-uwsgi. Django -> relay is
+    the Go relay's :5658 (dev_relay_url), because Django no longer serves
+    /proxy/relay/ in any shape. DISPATCHARR_PORT is read by neither: it
+    names vite's port in dev (CLAUDE.md section Commands).
     """
     explicit = os.environ.get(override_var)
     if explicit:
@@ -173,9 +225,6 @@ def resolve_base_url(*, override_var, modular_host_var, modular_host_default):
         port = os.environ.get("DISPATCHARR_PORT", "9191")
         return validated_base_url(f"http://{host}:{port}", modular_host_var)
     if env == "dev":
-        # Hardcoded, not read from DISPATCHARR_PORT: in dev the port
-        # that answers is uWSGI's / runserver's own, not nginx's, and
-        # DISPATCHARR_PORT names vite's (CLAUDE.md section Commands).
-        return validated_base_url("http://127.0.0.1:5656")
+        return validated_base_url(dev_url)
     port = os.environ.get("DISPATCHARR_PORT", "9191")
     return validated_base_url(f"http://127.0.0.1:{port}")
diff --git a/apps/proxy/relay_client.py b/apps/proxy/relay_client.py
index 175b5dc1..d4b98e43 100644
--- a/apps/proxy/relay_client.py
+++ b/apps/proxy/relay_client.py
@@ -57,7 +57,7 @@ from apps.proxy.internal_auth import (
     build_internal_request_header,
     internal_principal_token,
 )
-from apps.proxy.internal_base_url import resolve_base_url
+from apps.proxy.internal_base_url import dev_relay_url, resolve_base_url
 from apps.proxy.constants import ChannelState
 
 logger = logging.getLogger(__name__)
@@ -110,11 +110,18 @@ class RelayRefused(Exception):
 
 
 def get_relay_control_base_url():
-    """Where the relay answers, for this deployment shape (D9)."""
+    """Where the relay answers, for this deployment shape (D9).
+
+    dev_url is the one branch that differs from the Django-bound
+    direction: since stage 2d-4 Django serves no /proxy/relay/ route, so
+    in dev -- the only shape with no nginx in front -- this direction
+    names the Go relay's own listener rather than the API's.
+    """
     return resolve_base_url(
         override_var="DISPATCHARR_RELAY_BASE_URL",
         modular_host_var="DISPATCHARR_WEB_HOST",
         modular_host_default="web",
+        dev_url=dev_relay_url(),
     )
 
 
```

### Appendix C.3 — `DevRelayAddressTests` (R1), Task 4

Five tests, including the one that pins the direction a careless edit breaks silently.

```diff
diff --git a/apps/proxy/tests/test_boundary_error_arms.py b/apps/proxy/tests/test_boundary_error_arms.py
index e730941a..08a42271 100644
--- a/apps/proxy/tests/test_boundary_error_arms.py
+++ b/apps/proxy/tests/test_boundary_error_arms.py
@@ -4,15 +4,16 @@ exactly. Every line enumerated from a fresh live-path.json measurement,
 not the plan's own table -- authorize.py alone drifted +17 statements
 since the reachability brief.
 """
+import os
 from unittest.mock import MagicMock, patch
 
 from django.test import SimpleTestCase
 from rest_framework.exceptions import APIException
 
 from apps.accounts.models import User
-from apps.proxy import authorize, control_plane, relay_client
+from apps.proxy import authorize, control_plane, internal_base_url, relay_client
 from apps.proxy.config import TSConfig as Config
-from apps.proxy.live_proxy.config_helper import ConfigHelper
+from apps.proxy.config_helper import ConfigHelper
 
 
 class ConfigHelperDefaultLadderTests(SimpleTestCase):
@@ -42,26 +43,6 @@ class ConfigHelperDefaultLadderTests(SimpleTestCase):
         delegate.assert_called_once()
 
 
-class LiveProxyAppsReadyTests(SimpleTestCase):
-    def test_ready_starts_the_proxy_server_outside_manage_py(self):
-        from apps.proxy.live_proxy.apps import LiveProxyConfig
-
-        config = LiveProxyConfig.__new__(LiveProxyConfig)
-        with patch("sys.argv", ["/usr/bin/uwsgi"]), patch(
-            "apps.proxy.live_proxy.server.ProxyServer.get_instance"
-        ) as get_instance:
-            config.ready()
-        get_instance.assert_called_once()
-
-    def test_ready_is_a_no_op_under_manage_py(self):
-        from apps.proxy.live_proxy.apps import LiveProxyConfig
-
-        config = LiveProxyConfig.__new__(LiveProxyConfig)
-        with patch("sys.argv", ["manage.py", "test"]), patch(
-            "apps.proxy.live_proxy.server.ProxyServer.get_instance"
-        ) as get_instance:
-            config.ready()
-        get_instance.assert_not_called()
 
 
 class UserCanAccessChannelAdminBypassTests(SimpleTestCase):
@@ -172,3 +153,60 @@ class RelayClientStopChannelsGenericExceptionArmTests(SimpleTestCase):
         self.assertEqual(seen, ["a", "b", "c"])
         self.assertEqual(stopped, ["a", "c"])
         self.assertIn("Failed to stop proxy session for channel b", logs.output[0])
+
+
+class DevRelayAddressTests(SimpleTestCase):
+    """Stage 2d-4's dev branch: the two internal directions stopped agreeing.
+
+    apps/proxy/relay_views.py and relay_urls.py were deleted with the package
+    they wrapped, so Django serves no /proxy/relay/ route in any shape. Every
+    shape but dev reaches nginx, which has routed ^~ /proxy/relay/ to the Go
+    relay since 2d-3; dev runs no nginx -- docker/supervisord/all-dev.conf,
+    which DOES start relay-go -- so the Django -> relay direction must name the
+    Go relay's own listener.
+    """
+
+    def setUp(self):
+        internal_base_url._relay_go_port_warned = False
+
+    def _dev(self, **env):
+        base = {"DISPATCHARR_ENV": "dev", "DISPATCHARR_RELAY_BASE_URL": ""}
+        base.update(env)
+        return patch.dict(os.environ, base, clear=False)
+
+    def test_the_dev_branch_reaches_the_go_relay_not_the_api(self):
+        with self._dev(DISPATCHARR_RELAY_GO_PORT=""):
+            self.assertEqual(
+                relay_client.get_relay_control_base_url(), "http://127.0.0.1:5658"
+            )
+
+    def test_an_explicit_relay_go_port_is_honoured(self):
+        with self._dev(DISPATCHARR_RELAY_GO_PORT="15658"):
+            self.assertEqual(
+                relay_client.get_relay_control_base_url(), "http://127.0.0.1:15658"
+            )
+
+    def test_a_non_integer_relay_go_port_warns_once_and_falls_back(self):
+        with self._dev(DISPATCHARR_RELAY_GO_PORT="not-a-port"):
+            with self.assertLogs(internal_base_url.logger, level="WARNING") as logs:
+                first = relay_client.get_relay_control_base_url()
+            second = relay_client.get_relay_control_base_url()
+        self.assertEqual(first, "http://127.0.0.1:5658")
+        self.assertEqual(second, "http://127.0.0.1:5658")
+        self.assertEqual(len(logs.output), 1)
+        self.assertIn("DISPATCHARR_RELAY_GO_PORT", logs.output[0])
+
+    def test_the_operator_override_still_wins_ahead_of_the_default(self):
+        with self._dev(DISPATCHARR_RELAY_BASE_URL="http://relay.example:9999"):
+            self.assertEqual(
+                relay_client.get_relay_control_base_url(), "http://relay.example:9999"
+            )
+
+    def test_the_relay_to_django_direction_is_still_the_api_port(self):
+        # The half a careless edit would break silently: control_plane asks
+        # DJANGO, which is still :5656 in dev under both `runserver 5656` and
+        # docker/supervisord/all-dev.conf's api-uwsgi.
+        with self._dev(DISPATCHARR_INTERNAL_API_BASE_URL=""):
+            self.assertEqual(
+                control_plane.get_control_plane_base_url(), "http://127.0.0.1:5656"
+            )
```

### Appendix M.1 — #190's five ranges in `apps/channels/models.py` (R8), Task 5

The three reads, the two `hdel`s, and `models.py:7`'s now-unused `ChannelMetadataField`
import. `:6`'s `RedisKeys` import stays — twenty-six sites still use it.

```diff
diff --git a/apps/channels/models.py b/apps/channels/models.py
index 28b61969..d6e93ad4 100644
--- a/apps/channels/models.py
+++ b/apps/channels/models.py
@@ -4,7 +4,6 @@ from django.conf import settings
 from core.models import StreamProfile, CoreSettings
 from core.utils import RedisClient, custom_properties_as_dict
 from apps.proxy.redis_keys import RedisKeys
-from apps.proxy.constants import ChannelMetadataField
 import logging
 import uuid
 from django.utils import timezone
@@ -512,22 +511,6 @@ class Channel(models.Model):
                     profile_id_bytes,
                 )
 
-        if profile_id is None:
-            metadata_key = RedisKeys.channel_metadata(str(self.uuid))
-            meta_profile_id = redis_client.hget(
-                metadata_key, ChannelMetadataField.M3U_PROFILE
-            )
-            if meta_profile_id:
-                try:
-                    profile_id = int(meta_profile_id)
-                except (ValueError, TypeError):
-                    logger.debug(
-                        "Invalid profile ID in metadata for stale assignment on "
-                        "channel %s: %s",
-                        self.uuid,
-                        meta_profile_id,
-                    )
-
         if profile_id is not None:
             release_profile_slot(profile_id, redis_client)
         else:
@@ -690,42 +673,19 @@ class Channel(models.Model):
 
         stream_id = redis_client.get(RedisKeys.channel_stream(self.id))
         if not stream_id:
-            # Primary key missing — try metadata hash fallback.
-            # The proxy may have already cleaned up channel_stream/stream_profile
-            # keys, but the metadata hash can still have the stream_id and profile.
-            metadata_key = RedisKeys.channel_metadata(str(self.uuid))
-            meta_stream_id = redis_client.hget(
-                metadata_key, ChannelMetadataField.STREAM_ID
-            )
-            meta_profile_id = redis_client.hget(
-                metadata_key, ChannelMetadataField.M3U_PROFILE
-            )
-
-            if meta_stream_id and meta_profile_id:
-                stream_id = int(meta_stream_id)
-                profile_id = int(meta_profile_id)
-                logger.debug(
-                    f"Channel {self.uuid}: recovered stream_id={stream_id}, "
-                    f"profile_id={profile_id} from metadata fallback"
-                )
-                # Clean up any remaining keys
-                redis_client.delete(RedisKeys.channel_stream(self.id))
-                redis_client.delete(RedisKeys.stream_profile(stream_id))
-
-                # Clear metadata fields so duplicate release_stream() calls
-                # won't find them and DECR again
-                redis_client.hdel(
-                    metadata_key,
-                    ChannelMetadataField.STREAM_ID,
-                    ChannelMetadataField.M3U_PROFILE,
-                )
-
-                release_profile_slot(profile_id, redis_client)
-                return True
-
+            # The metadata-hash fallback that stood here -- issue #190's
+            # recovery branch, which read STREAM_ID and M3U_PROFILE out of
+            # live:channel:<uuid>:metadata and hdel'd them afterwards so a
+            # duplicate release could not DECR twice -- was deleted by
+            # Phase 2 stage 2d-4. That hash is the relay's, and the Go relay
+            # writes no live:channel:* key at all (spec D2), so every read
+            # here returned None and every hdel was a no-op from the 2d-3
+            # cutover onward. What is lost is a recovery that could not
+            # recover; what is gained is that this method no longer touches
+            # a relay-owned key from the API process.
             logger.debug(
-                f"Channel {self.uuid}: no stream info found in primary keys "
-                f"or metadata fallback"
+                f"Channel {self.uuid}: no stream info found for "
+                f"{RedisKeys.channel_stream(self.id)}"
             )
             return False
 
@@ -743,23 +703,13 @@ class Channel(models.Model):
             redis_client.delete(RedisKeys.stream_profile(stream_id))  # Remove profile association
             profile_id = int(profile_id)
         else:
-            # stream_profile key missing — try metadata hash fallback
-            metadata_key = RedisKeys.channel_metadata(str(self.uuid))
-            meta_profile_id = redis_client.hget(
-                metadata_key, ChannelMetadataField.M3U_PROFILE
+            # The metadata-hash fallback read that stood here went with the
+            # rest of #190 in Phase 2 stage 2d-4 (see the branch above).
+            logger.warning(
+                f"Channel {self.uuid}: no profile found for "
+                f"{RedisKeys.stream_profile(stream_id)}"
             )
-            if meta_profile_id:
-                profile_id = int(meta_profile_id)
-                logger.debug(
-                    f"Channel {self.uuid}: recovered profile_id={profile_id} "
-                    f"from metadata fallback ({RedisKeys.stream_profile(stream_id)} was missing)"
-                )
-            else:
-                logger.warning(
-                    f"Channel {self.uuid}: no profile found for "
-                    f"{RedisKeys.stream_profile(stream_id)} or in metadata fallback"
-                )
-                return False
+            return False
         logger.debug(
             f"Channel {self.uuid}: found profile_id={profile_id} for "
             f"stream {stream_id}"
@@ -767,16 +717,12 @@ class Channel(models.Model):
 
         release_profile_slot(profile_id, redis_client)
 
-        # Clear metadata fields so duplicate release_stream() calls
-        # (e.g. from _clean_redis_keys or ChannelService.stop_channel)
-        # won't find them via fallback and DECR again
-        metadata_key = RedisKeys.channel_metadata(str(self.uuid))
-        redis_client.hdel(
-            metadata_key,
-            ChannelMetadataField.STREAM_ID,
-            ChannelMetadataField.M3U_PROFILE,
-        )
-
+        # The unconditional hdel of the relay's metadata hash that ran here
+        # on EVERY successful release -- the largest of issue #190's five
+        # ranges -- went in Phase 2 stage 2d-4. It existed so a duplicate
+        # release could not find STREAM_ID/M3U_PROFILE via the fallback and
+        # DECR the provider counter twice; with the fallback gone there is
+        # nothing for it to clear and nothing left to find.
         return True
 
     def update_stream_profile(self, new_profile_id):
```

### Appendix M.2 — the #190 break-check (R8), Task 5

`MetadataOnlyReleaseTests`, plus the `hdel` its fake Redis needs — whose **absence** was one of
the three proofs R8 gives that nothing observed these ranges, which is why the test that
observes them is the test that adds it. Reversion and message are in Task 5 Step 5, measured.

```diff
diff --git a/apps/channels/tests/test_get_stream_assignment.py b/apps/channels/tests/test_get_stream_assignment.py
index 2f256eca..aa5b3dbf 100644
--- a/apps/channels/tests/test_get_stream_assignment.py
+++ b/apps/channels/tests/test_get_stream_assignment.py
@@ -6,8 +6,8 @@ from django.test import TestCase
 
 from apps.channels.models import Channel, ChannelStream, Stream
 from apps.m3u.models import M3UAccount, M3UAccountProfile
-from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
-from apps.proxy.live_proxy.redis_keys import RedisKeys
+from apps.proxy.constants import ChannelMetadataField, ChannelState
+from apps.proxy.redis_keys import RedisKeys
 
 
 class FakeAssignmentRedis:
@@ -43,6 +43,19 @@ class FakeAssignmentRedis:
     def hget(self, key, field):
         return self._hashes.get(key, {}).get(field)
 
+    def hdel(self, key, *fields):
+        # Added by Phase 2 stage 2d-4 for MetadataOnlyReleaseTests below. Its
+        # absence before then was itself one of the three proofs R8 gives that
+        # nothing in the tree observed issue #190's five ranges.
+        bucket = self._hashes.get(key)
+        if not bucket:
+            return 0
+        removed = 0
+        for field in fields:
+            if bucket.pop(field, None) is not None:
+                removed += 1
+        return removed
+
     def hset(self, key, mapping=None, **kwargs):
         bucket = self._hashes.setdefault(key, {})
         if mapping:
@@ -213,3 +226,79 @@ class ChannelGetStreamAssignmentTests(TestCase):
             self.assertFalse(
                 self.channel._stream_assignment_is_reusable(self.redis, self.stream.id)
             )
+
+
+class MetadataOnlyReleaseTests(TestCase):
+    """Issue #190's five ranges are gone, and this is what that changed.
+
+    Phase 2 stage 2d-4 deleted every read of and write to
+    live:channel:<uuid>:metadata from apps/channels/models.py. Before it,
+    release_stream()'s recovery branch (:694-721) could rebuild a stream_id and
+    a profile_id from that hash when the Django-owned channel_stream: key was
+    already gone, release the provider slot and report success. After it, the
+    branch is gone and release_stream() reports failure instead.
+
+    NOTHING ELSE IN THE TREE OBSERVES THAT CHANGE. Every other caller of
+    release_stream() seeds the primary Django-owned keys, which is exactly the
+    branch that skipped all four fallback reads; no test ever asserted the
+    hdel; and two of the fakes had no hget or hdel at all -- the 2d-4 plan's
+    ruling R8 records the audit. The delete was test-invisible in BOTH
+    directions, which is why this test exists rather than a green suite being
+    taken as evidence.
+
+    The reversion that makes it bite is therefore the :694-721 recovery branch,
+    NOT the :745-750 read: with no channel_stream: key seeded, release_stream()
+    takes the first branch and never reaches :745-750 at all.
+    """
+
+    def setUp(self):
+        self.account = M3UAccount.objects.create(name="meta-only", max_streams=1)
+        self.profile = M3UAccountProfile.objects.create(
+            m3u_account=self.account, name="p", max_streams=1,
+            search_pattern="", replace_pattern="",
+        )
+        self.stream = Stream.objects.create(
+            name="s", url="http://e/s", m3u_account=self.account
+        )
+        self.channel = Channel.objects.create(name="c", channel_number=1)
+        ChannelStream.objects.create(channel=self.channel, stream=self.stream, order=0)
+        self.redis = FakeAssignmentRedis()
+        self.metadata_key = RedisKeys.channel_metadata(str(self.channel.uuid))
+        # ONLY the relay's metadata hash: no channel_stream:, no stream_profile:.
+        # This is precisely the shape the deleted recovery branch existed for.
+        self.redis.hset(
+            self.metadata_key,
+            {
+                ChannelMetadataField.STREAM_ID: str(self.stream.id),
+                ChannelMetadataField.M3U_PROFILE: str(self.profile.id),
+            },
+        )
+
+    @patch("apps.channels.models.release_profile_slot")
+    @patch("apps.channels.models.RedisClient.get_client")
+    def test_a_metadata_only_assignment_is_no_longer_recoverable(
+        self, mock_get_client, mock_release
+    ):
+        mock_get_client.return_value = self.redis
+
+        self.assertIs(self.channel.release_stream(), False)
+
+        # And the slot is NOT released, which is the consequence that matters:
+        # the deleted branch called release_profile_slot() on the id it had
+        # recovered from the hash.
+        mock_release.assert_not_called()
+
+    @patch("apps.channels.models.release_profile_slot")
+    @patch("apps.channels.models.RedisClient.get_client")
+    def test_the_metadata_hash_is_left_exactly_as_it_was_found(
+        self, mock_get_client, mock_release
+    ):
+        # The other half of the delete: both hdel calls are gone, so a release
+        # no longer reaches into a key the Go relay owns and never writes. The
+        # fake's hdel (above) is what makes this observable at all.
+        mock_get_client.return_value = self.redis
+        before = dict(self.redis._hashes[self.metadata_key])
+
+        self.channel.release_stream()
+
+        self.assertEqual(self.redis._hashes[self.metadata_key], before)
```

### Appendix C.4 — the boot sites (R4, R5), Task 6

`INSTALLED_APPS`, the disabled beat entry, `ProxyConfig.ready()` and `signals.py`'s
`live_proxy` branch. `signals.py`'s `hls_proxy` branch is kept **verbatim** (R17).

```diff
diff --git a/apps/proxy/apps.py b/apps/proxy/apps.py
index 43005dea..071ad865 100644
--- a/apps/proxy/apps.py
+++ b/apps/proxy/apps.py
@@ -1,4 +1,3 @@
-import sys
 from django.apps import AppConfig
 
 class ProxyConfig(AppConfig):
@@ -6,10 +5,10 @@ class ProxyConfig(AppConfig):
     name = 'apps.proxy'
     verbose_name = "Stream Proxies"
 
-    def ready(self):
-        """Initialize proxy servers when Django starts"""
-        if 'manage.py' not in sys.argv:
-            from .live_proxy.server import ProxyServer as LiveProxyServer
-
-            # HLS proxy retained in-tree but unused; live uses a singleton.
-            self.live_proxy = LiveProxyServer.get_instance()
+    # ready() is deliberately absent. Until Phase 2 stage 2d-4 it imported
+    # apps/proxy/live_proxy/server.py and instantiated the ProxyServer
+    # singleton in every process that is not manage.py, setting
+    # self.live_proxy for apps/proxy/signals.py and the `proxy` management
+    # command to reach by getattr. The Go relay is that process now, so
+    # there is no singleton to build and AppConfig.ready() is a no-op by
+    # default -- an empty override would say less than its absence.
diff --git a/apps/proxy/signals.py b/apps/proxy/signals.py
index 7ceaf731..c9be78c1 100644
--- a/apps/proxy/signals.py
+++ b/apps/proxy/signals.py
@@ -14,10 +14,6 @@ def cleanup_proxy_servers(sender, **kwargs):
         if hls_proxy is not None:
             for channel_id in list(hls_proxy.stream_managers.keys()):
                 hls_proxy.stop_channel(channel_id)
-        live_proxy = getattr(proxy_app, 'live_proxy', None)
-        if live_proxy is not None:
-            for channel_id in list(live_proxy.stream_managers.keys()):
-                live_proxy.stop_channel(channel_id)
         logger.info("Proxy servers cleaned up successfully")
     except Exception as e:
         logger.error(f"Error during proxy server cleanup: {e}")
diff --git a/dispatcharr/settings.py b/dispatcharr/settings.py
index abdeff08..51b89d29 100644
--- a/dispatcharr/settings.py
+++ b/dispatcharr/settings.py
@@ -104,7 +104,6 @@ INSTALLED_APPS = [
     "apps.m3u",
     "apps.output",
     "apps.proxy.apps.ProxyConfig",
-    "apps.proxy.live_proxy",
     "apps.vod.apps.VODConfig",
     "apps.connect.apps.ConnectConfig",
     "core",
@@ -424,13 +423,6 @@ CELERY_WORKER_MAX_MEMORY_PER_CHILD = 524_288  # 512 MB in KB
 
 CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers.DatabaseScheduler"
 CELERY_BEAT_SCHEDULE = {
-    # Explicitly disable the old fetch-channel-statuses task
-    # This ensures it gets disabled when DatabaseScheduler syncs
-    "fetch-channel-statuses": {
-        "task": "apps.proxy.tasks.fetch_channel_stats",
-        "schedule": 2.0,  # Original schedule (doesn't matter since disabled)
-        "enabled": False,  # Explicitly disabled
-    },
     # Keep the file scanning task
     "scan-files": {
         "task": "core.tasks.scan_and_process_files",  # Direct task call
```

### Appendix C.5 — `dispatcharr/urls.py` (R6), Task 6

The import re-pointed at `apps.proxy.stream_routes`, and both XC `re_path`s replaced by
`*stream_routes.xc_urlpatterns` so the pattern text has one home. **These patterns survive.**

```diff
diff --git a/dispatcharr/urls.py b/dispatcharr/urls.py
index b9c42e41..11bddcd4 100644
--- a/dispatcharr/urls.py
+++ b/dispatcharr/urls.py
@@ -6,7 +6,7 @@ from django.views.generic import TemplateView, RedirectView
 from .routing import websocket_urlpatterns
 from apps.output.views import xc_player_api, xc_panel_api, xc_get, xc_xmltv
 from apps.proxy.authorize_views import authorize_internal_view, authorize_view
-from apps.proxy.live_proxy.views import stream_xc
+from apps.proxy import stream_routes
 from apps.proxy.vod_proxy.views import stream_xc_movie, stream_xc_episode
 from apps.timeshift.views import timeshift_proxy, timeshift_proxy_query
 from dispatcharr.utils import XC_STREAM_ID_PATTERN
@@ -54,28 +54,19 @@ urlpatterns = [
     re_path("panel_api.php", xc_panel_api, name="xc_panel_api"),
     re_path("get.php", xc_get, name="xc_get"),
     re_path("xmltv.php", xc_xmltv, name="xc_xmltv"),
-    # channel_id is constrained to XC_STREAM_ID_PATTERN (dispatcharr/utils.py) —
-    # the shape a real Xtream client sends: digits, optionally with an
-    # extension (stream_xc does pathlib.Path(channel_id).stem / .suffix, then
-    # int(channel_id)) — so a same-shaped SPA deep link (e.g.
-    # /settings/example/page) falls through to the SPA catch-all instead of
-    # stream_xc's get_object_or_404(User, ...) 404. See docs/superpowers/
-    # plans/2026-09-04-phase1-pr2-ttfb-test.md's Spec amendments for why this
-    # can't be fixed inside stream_xc itself.
-    # \Z, not $: `$` also matches just before a trailing '\n', so a
-    # %0A-suffixed channel_id would route (and, via _XC_STREAM_ID_RE's own
-    # \A...\Z in utils.py, would NOT be redacted) — the two would disagree on
-    # exactly that input. \Z matches only the absolute end of the string.
-    re_path(
-        rf"^live/(?P<username>[^/]+)/(?P<password>[^/]+)/(?P<channel_id>{XC_STREAM_ID_PATTERN})\Z",
-        stream_xc,
-        name="xc_live_stream_endpoint",
-    ),
-    re_path(
-        rf"^(?P<username>[^/]+)/(?P<password>[^/]+)/(?P<channel_id>{XC_STREAM_ID_PATTERN})\Z",
-        stream_xc,
-        name="xc_stream_endpoint",
-    ),
+    # The two XC live-stream patterns, unchanged in shape and moved to
+    # apps/proxy/stream_routes.py with the view they name. Phase 2 stage 2d-4
+    # deleted apps/proxy/live_proxy/views.py's stream_xc, and nginx has served
+    # both shapes from the Go relay since 2d-3 -- but the PATTERNS cannot go,
+    # and the reason is not routing: apps/proxy/authorize_views.py's
+    # _surface_for() hands the URI in X-Original-URI to DJANGO'S OWN RESOLVER
+    # and keys on the matched view's __name__. Remove them and every
+    # auth_request subrequest for an XC live tune resolves to the SPA catch-all
+    # and authorize_view answers 403 -- in production. XC_STREAM_ID_PATTERN and
+    # \Z are therefore load-bearing exactly as before (Phase 1 D7's
+    # three-segment regex trap), and tests/test_urls_xc_three_segment.py still
+    # pins them. See apps/proxy/stream_routes.py's header.
+    *stream_routes.xc_urlpatterns,
     path(
         "timeshift/<str:username>/<str:password>/<str:duration>/<str:timestamp>/<str:channel_id>",
         timeshift_proxy,
```

### Appendix A.2 — the eight remaining test-file dispositions (R6, R7), Task 7

`test_get_stream_assignment.py` (M.2) and `test_boundary_error_arms.py` (C.3) are NOT here:
the set is disjoint by file. `test_urls_xc_three_segment.py` keeps all five assertions and
takes a docstring paragraph — an earlier draft rewrote it, which R6's reversal undoes.

```diff
diff --git a/apps/channels/tests/test_channel_stream_reuse.py b/apps/channels/tests/test_channel_stream_reuse.py
index 5c8fc9b3..8a740385 100644
--- a/apps/channels/tests/test_channel_stream_reuse.py
+++ b/apps/channels/tests/test_channel_stream_reuse.py
@@ -12,7 +12,7 @@ from django.test import TestCase
 
 from apps.channels.models import Channel
 from apps.proxy import relay_client
-from apps.proxy.live_proxy.redis_keys import RedisKeys
+from apps.proxy.redis_keys import RedisKeys
 
 
 class _Redis:
diff --git a/apps/channels/tests/test_recording_pipeline.py b/apps/channels/tests/test_recording_pipeline.py
index 21254b30..7516d27c 100644
--- a/apps/channels/tests/test_recording_pipeline.py
+++ b/apps/channels/tests/test_recording_pipeline.py
@@ -509,8 +509,8 @@ class FfmpegRetryTests(TestCase):
         self.assertEqual(dvr_tasks._dvr_ffmpeg_retry_backoff_seconds(1), 0.25)
         self.assertEqual(dvr_tasks._dvr_ffmpeg_retry_backoff_seconds(12), 3.0)
 
-    @patch("apps.proxy.live_proxy.config_helper.ConfigHelper.stream_timeout", return_value=60)
-    @patch("apps.proxy.live_proxy.config_helper.ConfigHelper.failover_grace_period", return_value=20)
+    @patch("apps.proxy.config_helper.ConfigHelper.stream_timeout", return_value=60)
+    @patch("apps.proxy.config_helper.ConfigHelper.failover_grace_period", return_value=20)
     def test_retry_window_matches_live_proxy_timeouts(self, _grace, _stream):
         from apps.channels.tasks import _dvr_ffmpeg_retry_window_seconds
 
diff --git a/apps/channels/tests/test_ts_proxy_initializing.py b/apps/channels/tests/test_ts_proxy_initializing.py
index 1629c744..dd0c192f 100644
--- a/apps/channels/tests/test_ts_proxy_initializing.py
+++ b/apps/channels/tests/test_ts_proxy_initializing.py
@@ -1,210 +1,28 @@
-"""Tests for stuck INITIALIZING state fix.
-
-Covers:
-  - stream_manager.run() finally block: ownership check + state guard fallback
-  - ChannelState.PRE_ACTIVE contains the correct states
-  - INITIALIZING is included in the cleanup task grace period check
+"""ChannelState.PRE_ACTIVE contains the correct states and is immutable.
+
+This file used to carry two halves. The other one, StreamManagerFinallyBlockTests,
+drove StreamManager.run()'s finally block and asserted the arbitration between
+two uWSGI workers -- which worker holds the owner key, whether a new owner took
+over, whether the state guard writes ERROR. Phase 2 stage 2d-4 deleted it with
+apps/proxy/live_proxy/: spec D2 gives the Go relay one process and no ownership
+lease at all, so there is nothing left to arbitrate. The state OUTCOMES it
+asserted are pinned on the Go side by
+relay/channel/manager_test.go::TestAnUpstreamFailurePutsTheChannelInError and
+relay/channel/failover_test.go::TestAnExhaustedChannelEndsInErrorNamingTheCount,
+which is the direct analogue of its test_error_message_includes_stream_count.
+There is no Go analogue of the lease half and there cannot be one.
+
+What survives is a shape pin on a constant stage 2d-1 relocated into
+apps/proxy/constants.py. Its last production reader went with the package, so
+this is deliberately a pin on a constant nothing currently reads -- kept rather
+than deleted with it, because the frozenset is four lines and re-deriving it
+for Phase 3 would cost more than carrying it. Recorded in the 2d-4 plan's
+ruling R7 so it is a decision rather than an oversight.
 """
-import time
-import threading
-from unittest.mock import MagicMock, patch
-
 from django.test import TestCase
 
-from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
-from apps.proxy.live_proxy.redis_keys import RedisKeys
-from apps.proxy.live_proxy.input.manager import StreamManager
-
-
-# ---------------------------------------------------------------------------
-# Helpers
-# ---------------------------------------------------------------------------
-
-CHANNEL_ID = "00000000-0000-0000-0000-000000000001"
-
-
-def _make_stream_manager(tried_stream_ids=None, max_retries=3):
-    """Build a StreamManager via __new__ (bypasses __init__) with the
-    minimum attributes required by the run() finally block."""
-    sm = StreamManager.__new__(StreamManager)
-    sm.channel_id = CHANNEL_ID
-    sm.worker_id = "worker-1"
-    sm.max_retries = max_retries
-    sm.tried_stream_ids = tried_stream_ids if tried_stream_ids is not None else set()
-    sm.running = False  # while-loop exits immediately
-    sm.connected = False
-    sm.transcode_process_active = False
-    sm._buffer_check_timers = []
-    sm.url = "http://example.com/stream"
-    sm.url_switching = False
-    sm.url_switch_start_time = 0
-    sm.url_switch_timeout = 30
-    sm.stop_requested = False
-    sm.stopping = False
-    sm.socket = None
-    sm.transcode_process = None
-    sm.current_response = None
-    sm.current_session = None
-    sm.current_stream_id = None
-
-    buffer = MagicMock()
-    buffer.redis_client = MagicMock()
-    buffer.channel_id = CHANNEL_ID
-    sm.buffer = buffer
-
-    return sm
-
-
-def _run_finally_block(sm, owner_value, current_state):
-    """Invoke StreamManager.run() so its finally block executes against real code.
-
-    Patches threading.Thread and ConfigHelper so the try-block is inert
-    (self.running=False makes the while-loop exit immediately).
-
-    Returns True if the finally block wrote ERROR to Redis.
-    """
-    redis = sm.buffer.redis_client
-
-    # Mock the owner key GET — the finally block calls redis.get(owner_key)
-    def get_side_effect(key):
-        if "owner" in key:
-            return owner_value
-        return None
-
-    redis.get.side_effect = get_side_effect
-
-    # Mock hget for state field lookup in the PRE_ACTIVE guard
-    if current_state is not None:
-        redis.hget.return_value = current_state.encode('utf-8')
-    else:
-        redis.hget.return_value = None
-
-    # Reset hset so we can detect whether ERROR was written
-    redis.hset.reset_mock()
-    redis.setex.reset_mock()
-
-    with patch.object(threading, 'Thread', return_value=MagicMock()):
-        with patch('apps.proxy.live_proxy.input.manager.ConfigHelper') as mock_cfg:
-            mock_cfg.max_stream_switches.return_value = 0
-            mock_cfg.max_retries.return_value = sm.max_retries
-            sm.run()
-
-    # Check if hset was called with ERROR state
-    if redis.hset.called:
-        mapping = redis.hset.call_args[1].get('mapping', {})
-        return mapping.get(ChannelMetadataField.STATE) == ChannelState.ERROR
-    return False
-
-
-# ---------------------------------------------------------------------------
-# stream_manager.run() finally block: ownership + state guard behavior
-# ---------------------------------------------------------------------------
-
-class StreamManagerFinallyBlockTests(TestCase):
-    """The run() finally block writes ERROR if the worker is still the owner
-    (normal case) OR if ownership expired and the channel is still in a
-    pre-active state (no new owner has taken over)."""
-
-    # --- Owner still valid: always write ERROR ---
-
-    def test_owner_writes_error_regardless_of_state(self):
-        """When we're still the owner, always write ERROR."""
-        sm = _make_stream_manager()
-        owner = sm.worker_id.encode('utf-8')
-        self.assertTrue(_run_finally_block(sm, owner, ChannelState.ACTIVE))
-
-    def test_owner_writes_error_on_initializing(self):
-        """Owner + INITIALIZING = write ERROR."""
-        sm = _make_stream_manager()
-        owner = sm.worker_id.encode('utf-8')
-        self.assertTrue(_run_finally_block(sm, owner, ChannelState.INITIALIZING))
-
-        mapping = sm.buffer.redis_client.hset.call_args[1]['mapping']
-        self.assertEqual(mapping[ChannelMetadataField.STATE], ChannelState.ERROR)
-
-    # --- Ownership expired, no new owner: use state guard ---
-
-    def test_no_owner_initializing_writes_error(self):
-        """Ownership expired + INITIALIZING = write ERROR."""
-        sm = _make_stream_manager()
-        self.assertTrue(_run_finally_block(sm, None, ChannelState.INITIALIZING))
-
-    def test_no_owner_connecting_writes_error(self):
-        """Ownership expired + CONNECTING = write ERROR."""
-        sm = _make_stream_manager()
-        self.assertTrue(_run_finally_block(sm, None, ChannelState.CONNECTING))
-
-    def test_no_owner_buffering_writes_error(self):
-        """Ownership expired + BUFFERING = write ERROR."""
-        sm = _make_stream_manager()
-        self.assertTrue(_run_finally_block(sm, None, ChannelState.BUFFERING))
-
-    def test_no_owner_waiting_for_clients_writes_error(self):
-        """Ownership expired + WAITING_FOR_CLIENTS = write ERROR."""
-        sm = _make_stream_manager()
-        self.assertTrue(_run_finally_block(sm, None, ChannelState.WAITING_FOR_CLIENTS))
-
-    def test_no_owner_active_does_not_write(self):
-        """Ownership expired + ACTIVE = do NOT write ERROR."""
-        sm = _make_stream_manager()
-        self.assertFalse(_run_finally_block(sm, None, ChannelState.ACTIVE))
-
-    def test_no_owner_error_does_not_write(self):
-        """Ownership expired + already ERROR = do NOT write again."""
-        sm = _make_stream_manager()
-        self.assertFalse(_run_finally_block(sm, None, ChannelState.ERROR))
-
-    def test_no_owner_no_state_does_not_write(self):
-        """Ownership expired + no state metadata = do NOT write."""
-        sm = _make_stream_manager()
-        self.assertFalse(_run_finally_block(sm, None, None))
-
-    # --- New owner took over: never clobber ---
-
-    def test_new_owner_initializing_does_not_write(self):
-        """Another worker owns the channel — do NOT clobber."""
-        sm = _make_stream_manager()
-        self.assertFalse(_run_finally_block(sm, b"other-worker", ChannelState.INITIALIZING))
-
-    def test_new_owner_active_does_not_write(self):
-        """Another worker owns the channel and is ACTIVE — do NOT write."""
-        sm = _make_stream_manager()
-        self.assertFalse(_run_finally_block(sm, b"other-worker", ChannelState.ACTIVE))
-
-    # --- Stopping key and error messages ---
-
-    def test_stopping_key_set_on_error_update(self):
-        """When ERROR is written, stopping key must also be set."""
-        sm = _make_stream_manager()
-        _run_finally_block(sm, None, ChannelState.INITIALIZING)
-
-        sm.buffer.redis_client.setex.assert_called_once()
-        args = sm.buffer.redis_client.setex.call_args[0]
-        self.assertIn("stopping", args[0])
-        self.assertEqual(args[1], 60)
-
-    def test_error_message_includes_stream_count(self):
-        """When multiple streams were tried, error message reflects that."""
-        sm = _make_stream_manager(tried_stream_ids={1, 2, 3})
-        _run_finally_block(sm, None, ChannelState.INITIALIZING)
-
-        mapping = sm.buffer.redis_client.hset.call_args[1]['mapping']
-        error_msg = mapping[ChannelMetadataField.ERROR_MESSAGE]
-        self.assertIn("3 stream options failed", error_msg)
-
-    def test_error_message_with_no_streams_tried(self):
-        """When no alternate streams were tried, shows retry count."""
-        sm = _make_stream_manager(tried_stream_ids=set(), max_retries=5)
-        _run_finally_block(sm, None, ChannelState.INITIALIZING)
-
-        mapping = sm.buffer.redis_client.hset.call_args[1]['mapping']
-        error_msg = mapping[ChannelMetadataField.ERROR_MESSAGE]
-        self.assertIn("5", error_msg)
-
+from apps.proxy.constants import ChannelState
 
-# ---------------------------------------------------------------------------
-# ChannelState.PRE_ACTIVE: verify contents and immutability
-# ---------------------------------------------------------------------------
 
 class PreActiveStateTests(TestCase):
     """Verify PRE_ACTIVE contains the correct states and is immutable."""
diff --git a/apps/channels/tests/test_ts_proxy_keepalive.py b/apps/channels/tests/test_ts_proxy_keepalive.py
index 84f764ef..c4cced12 100644
--- a/apps/channels/tests/test_ts_proxy_keepalive.py
+++ b/apps/channels/tests/test_ts_proxy_keepalive.py
@@ -18,290 +18,9 @@ from django.test import TestCase
 # _should_send_keepalive: owner worker path
 # ---------------------------------------------------------------------------
 
-class OwnerWorkerKeepaliveTests(TestCase):
-    """Owner worker has a stream_manager; keepalive logic uses it directly."""
 
-    def _make_generator(self, healthy, at_buffer_head, consecutive_empty):
-        from apps.proxy.live_proxy.output.ts.generator import StreamGenerator
-        gen = StreamGenerator.__new__(StreamGenerator)
-        gen.channel_id = "00000000-0000-0000-0000-000000000001"
-        gen.client_id = "test-client"
 
-        buffer = MagicMock()
-        buffer.index = 10 if at_buffer_head else 100
-        gen.local_index = 10
-        gen.buffer = buffer
 
-        stream_manager = MagicMock()
-        stream_manager.healthy = healthy
-        gen.stream_manager = stream_manager
-
-        gen.consecutive_empty = consecutive_empty
-        return gen
-
-    def test_owner_healthy_returns_false(self):
-        """Owner worker, healthy stream -> no keepalive."""
-        gen = self._make_generator(healthy=True, at_buffer_head=True, consecutive_empty=10)
-        self.assertFalse(gen._should_send_keepalive(gen.local_index))
-
-    def test_owner_unhealthy_at_head_returns_true(self):
-        """Owner worker, unhealthy stream, at buffer head -> send keepalive."""
-        gen = self._make_generator(healthy=False, at_buffer_head=True, consecutive_empty=10)
-        self.assertTrue(gen._should_send_keepalive(gen.local_index))
-
-    def test_owner_unhealthy_not_at_head_returns_false(self):
-        """Owner worker, unhealthy stream, but NOT at buffer head -> no keepalive."""
-        gen = self._make_generator(healthy=False, at_buffer_head=False, consecutive_empty=10)
-        self.assertFalse(gen._should_send_keepalive(gen.local_index))
-
-    def test_owner_insufficient_consecutive_empty_returns_false(self):
-        """Owner worker, unhealthy, at head but consecutive_empty < 5 -> no keepalive."""
-        gen = self._make_generator(healthy=False, at_buffer_head=True, consecutive_empty=3)
-        self.assertFalse(gen._should_send_keepalive(gen.local_index))
-
-    def test_owner_exactly_5_consecutive_empty_returns_true(self):
-        """consecutive_empty == 5 is the minimum threshold."""
-        gen = self._make_generator(healthy=False, at_buffer_head=True, consecutive_empty=5)
-        self.assertTrue(gen._should_send_keepalive(gen.local_index))
-
-
-# ---------------------------------------------------------------------------
-# _should_send_keepalive: non-owner worker path
-# ---------------------------------------------------------------------------
-
-class NonOwnerWorkerKeepaliveTests(TestCase):
-    """Non-owner worker has stream_manager=None; health determined from Redis."""
-
-    def _make_generator(self, consecutive_empty=10):
-        from apps.proxy.live_proxy.output.ts.generator import StreamGenerator
-        gen = StreamGenerator.__new__(StreamGenerator)
-        gen.channel_id = "00000000-0000-0000-0000-000000000002"
-        gen.client_id = "test-client-nonowner"
-
-        buffer = MagicMock()
-        buffer.index = 10
-        gen.local_index = 10
-        gen.buffer = buffer
-
-        gen.stream_manager = None  # non-owner worker
-        gen.consecutive_empty = consecutive_empty
-
-        # Attributes added by health-check throttling (set in __init__)
-        gen._last_health_check_time = 0.0
-        gen._last_health_check_result = False
-        gen._health_check_interval = 2.0
-        gen.proxy_server = None
-
-        return gen
-
-    def _mock_proxy_server(self, last_data_value):
-        """Return a mock ProxyServer with a redis_client pre-configured."""
-        server = MagicMock()
-        redis_client = MagicMock()
-        server.redis_client = redis_client
-        redis_client.get.return_value = last_data_value
-        return server
-
-    def test_non_owner_fresh_data_returns_false(self):
-        """Non-owner, last_data < 10s ago -> stream healthy -> no keepalive."""
-        gen = self._make_generator()
-        fresh_ts = str(time.time() - 2.0).encode()
-        server = self._mock_proxy_server(fresh_ts)
-
-        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
-            MockPS.get_instance.return_value = server
-            result = gen._should_send_keepalive(gen.local_index)
-
-        self.assertFalse(result, "Fresh data should NOT trigger keepalive")
-
-    def test_non_owner_stale_data_returns_true(self):
-        """Non-owner, last_data >= 10s ago -> stream unhealthy -> send keepalive."""
-        gen = self._make_generator()
-        stale_ts = str(time.time() - 12.0).encode()
-        server = self._mock_proxy_server(stale_ts)
-
-        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
-            MockPS.get_instance.return_value = server
-            result = gen._should_send_keepalive(gen.local_index)
-
-        self.assertTrue(result, "Stale data (12s) should trigger keepalive")
-
-    def test_non_owner_exactly_at_timeout_returns_true(self):
-        """Data age exactly equal to CONNECTION_TIMEOUT (10s) -> send keepalive."""
-        gen = self._make_generator()
-        ts = str(time.time() - 10.0).encode()
-        server = self._mock_proxy_server(ts)
-
-        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
-            MockPS.get_instance.return_value = server
-            result = gen._should_send_keepalive(gen.local_index)
-
-        self.assertTrue(result, "Data at exactly timeout threshold should trigger keepalive")
-
-    def test_non_owner_no_redis_key_returns_true(self):
-        """Non-owner, last_data key missing from Redis -> assume unhealthy."""
-        gen = self._make_generator()
-        server = self._mock_proxy_server(None)
-
-        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
-            MockPS.get_instance.return_value = server
-            result = gen._should_send_keepalive(gen.local_index)
-
-        self.assertTrue(result, "Missing last_data key should trigger keepalive")
-
-    def test_non_owner_redis_client_none_returns_false(self):
-        """Non-owner, redis_client is None (disconnected) -> conservative, no keepalive."""
-        gen = self._make_generator()
-        server = MagicMock()
-        server.redis_client = None
-
-        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
-            MockPS.get_instance.return_value = server
-            result = gen._should_send_keepalive(gen.local_index)
-
-        self.assertFalse(result, "No redis_client -> conservative, no keepalive")
-
-    def test_non_owner_redis_exception_returns_false(self):
-        """Non-owner, Redis raises an exception -> conservative, no keepalive."""
-        gen = self._make_generator()
-
-        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
-            MockPS.get_instance.side_effect = Exception("Redis error")
-            result = gen._should_send_keepalive(gen.local_index)
-
-        self.assertFalse(result, "Redis error -> conservative, no keepalive")
-
-    def test_non_owner_not_at_buffer_head_returns_false(self):
-        """Non-owner, NOT at buffer head -> no keepalive regardless of Redis."""
-        gen = self._make_generator()
-        gen.buffer.index = 100  # far ahead of local_index=10
-        server = self._mock_proxy_server(None)
-
-        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
-            MockPS.get_instance.return_value = server
-            result = gen._should_send_keepalive(gen.local_index)
-
-        self.assertFalse(result)
-
-    def test_non_owner_insufficient_consecutive_empty_returns_false(self):
-        """Non-owner, at head, but consecutive_empty < 5 -> no keepalive."""
-        gen = self._make_generator(consecutive_empty=2)
-        stale_ts = str(time.time() - 30.0).encode()
-        server = self._mock_proxy_server(stale_ts)
-
-        with patch("apps.proxy.live_proxy.output.ts.generator.ProxyServer") as MockPS:
-            MockPS.get_instance.return_value = server
-            result = gen._should_send_keepalive(gen.local_index)
-
-        self.assertFalse(result)
-
-
-# ---------------------------------------------------------------------------
-# _do_stats_update: error handling and WebSocket dispatch
-# ---------------------------------------------------------------------------
-
-class DoStatsUpdateTests(TestCase):
-    """_do_stats_update runs the actual Redis scan + WebSocket call."""
-
-    def _make_client_manager(self):
-        from apps.proxy.live_proxy.client_manager import ClientManager
-        cm = ClientManager.__new__(ClientManager)
-        cm.channel_id = "00000000-0000-0000-0000-000000000004"
-        cm._heartbeat_running = False
-        return cm
-
-    def test_do_stats_update_calls_send_websocket_update(self):
-        """_do_stats_update must call send_websocket_update with channel_stats."""
-        cm = self._make_client_manager()
-
-        with patch("apps.proxy.live_proxy.client_manager.send_websocket_update") as mock_ws, \
-             patch(
-                 "apps.proxy.live_proxy.channel_status.build_live_channel_stats_data",
-                 return_value={"channels": [], "count": 0},
-             ), \
-             patch("core.utils.RedisClient.get_client", return_value=MagicMock()):
-            cm._do_stats_update()
-
-        mock_ws.assert_called_once()
-        event_type = mock_ws.call_args[0][1]
-        self.assertEqual(event_type, "update")
-        payload = mock_ws.call_args[0][2]
-        self.assertEqual(payload["type"], "channel_stats")
-
-    def test_do_stats_update_does_not_raise_on_redis_error(self):
-        """Redis failure must be swallowed (logged), not propagated."""
-        cm = self._make_client_manager()
-
-        with patch("core.utils.RedisClient.get_client", side_effect=Exception("Redis down")):
-            try:
-                cm._do_stats_update()
-            except Exception as e:
-                self.fail(f"_do_stats_update raised an exception: {e}")
-
-    def test_do_stats_update_uses_build_live_channel_stats_data(self):
-        """Must build live stats via the shared builder."""
-        cm = self._make_client_manager()
-        mock_redis = MagicMock()
-
-        with patch("apps.proxy.live_proxy.client_manager.send_websocket_update"), \
-             patch(
-                 "apps.proxy.live_proxy.channel_status.build_live_channel_stats_data",
-                 return_value={"channels": [{"channel_id": "ch-1"}], "count": 1},
-             ) as mock_build, \
-             patch("core.utils.RedisClient.get_client", return_value=mock_redis):
-            cm._do_stats_update()
-
-        mock_build.assert_called_once_with(mock_redis)
-
-
-# ---------------------------------------------------------------------------
-# Integration: remove_client must not block on WebSocket
-# ---------------------------------------------------------------------------
-
-class ClientRemoveIntegrationTests(TestCase):
-    """When remove_client() fires, _trigger_stats_update must not block."""
-
-    def test_remove_client_does_not_block_on_websocket(self):
-        """remove_client() must return quickly even if WebSocket is slow."""
-        from apps.proxy.live_proxy.client_manager import ClientManager
-
-        cm = ClientManager.__new__(ClientManager)
-        cm.channel_id = "00000000-0000-0000-0000-000000000005"
-        cm._heartbeat_running = False
-        cm.clients = {"test-client-1"}
-        cm.last_heartbeat_time = {"test-client-1": time.time()}
-        cm.last_active_time = time.time()
-        cm.client_set_key = f"live:channel:{cm.channel_id}:clients"
-        cm.client_ttl = 60
-        cm.worker_id = "worker-1"
-        cm.proxy_server = MagicMock()
-        cm.proxy_server.am_i_owner.return_value = False
-        cm.lock = threading.Lock()
-
-        mock_redis = MagicMock()
-        mock_redis.hgetall.return_value = {b"ip_address": b"127.0.0.1"}
-        mock_redis.scard.return_value = 1
-        cm.redis_client = mock_redis
-
-        slow_ws_called = threading.Event()
-
-        def slow_websocket(*args, **kwargs):
-            time.sleep(2.0)
-            slow_ws_called.set()
-
-        start = time.time()
-        with patch("apps.proxy.live_proxy.client_manager.send_websocket_update", side_effect=slow_websocket):
-            cm.remove_client("test-client-1")
-        elapsed = time.time() - start
-
-        self.assertLess(elapsed, 1.0,
-                        f"remove_client() blocked for {elapsed:.2f}s waiting for WebSocket "
-                        f"(should dispatch to background thread and return immediately)")
-
-
-# ---------------------------------------------------------------------------
-# DVR timeout threshold vs keepalive timing
-# ---------------------------------------------------------------------------
 
 class KeepaliveTimingTests(TestCase):
     """Verify that keepalive threshold gives sufficient margin before DVR timeout."""
diff --git a/apps/proxy/tests/test_combined_stats.py b/apps/proxy/tests/test_combined_stats.py
index b69ac431..4e46db60 100644
--- a/apps/proxy/tests/test_combined_stats.py
+++ b/apps/proxy/tests/test_combined_stats.py
@@ -8,45 +8,8 @@ from rest_framework.test import APIRequestFactory, force_authenticate
 
 from apps.accounts.models import User
 from apps.proxy import stats_views
-from apps.proxy.live_proxy.channel_status import build_live_channel_stats_data
 
 
-class BuildLiveChannelStatsDataTests(TestCase):
-    @patch("apps.proxy.live_proxy.channel_status.ChannelStatus.get_basic_channel_info")
-    def test_builds_channel_list_from_metadata_scan(self, mock_get_info):
-        mock_get_info.side_effect = lambda ch_id, **kwargs: {"channel_id": ch_id}
-
-        redis = MagicMock()
-        redis.scan.return_value = (
-            0,
-            [
-                "live:channel:abc-uuid:metadata",
-                "live:channel:def-uuid:metadata",
-            ],
-        )
-
-        result = build_live_channel_stats_data(redis)
-
-        self.assertEqual(result["count"], 2)
-        self.assertEqual(
-            [ch["channel_id"] for ch in result["channels"]],
-            ["abc-uuid", "def-uuid"],
-        )
-
-    def test_returns_empty_when_redis_unavailable(self):
-        result = build_live_channel_stats_data(None)
-        self.assertEqual(result, {"channels": [], "count": 0})
-
-    @patch("apps.proxy.live_proxy.channel_status.ChannelStatus.get_basic_channel_info")
-    def test_returns_empty_on_error(self, mock_get_info):
-        mock_get_info.side_effect = RuntimeError("redis blew up")
-
-        redis = MagicMock()
-        redis.scan.return_value = (0, ["live:channel:abc-uuid:metadata"])
-
-        result = build_live_channel_stats_data(redis)
-
-        self.assertEqual(result, {"channels": [], "count": 0})
 
 
 class CombinedStatsApiTests(TestCase):
diff --git a/apps/proxy/tests/test_internal_base_url.py b/apps/proxy/tests/test_internal_base_url.py
index 33538d84..60b676ae 100644
--- a/apps/proxy/tests/test_internal_base_url.py
+++ b/apps/proxy/tests/test_internal_base_url.py
@@ -51,10 +51,22 @@ class ResolveBaseUrlTests(SimpleTestCase):
                 relay_client.get_relay_control_base_url(), "http://api-1:8080"
             )
 
-    def test_dev_is_the_single_runserver_process(self):
+    def test_dev_names_the_go_relay_in_one_direction_and_django_in_the_other(self):
+        """The one branch where the two directions stopped agreeing.
+
+        Stage 2d-4 deleted apps/proxy/relay_views.py, so Django serves no
+        /proxy/relay/ route in any shape. Every shape but dev reaches nginx,
+        which has routed ^~ /proxy/relay/ to the Go relay since 2d-3; dev runs
+        no nginx (docker/supervisord/all-dev.conf, which does start relay-go),
+        so Django -> relay must name the Go relay's own listener while
+        relay -> Django stays on Django's.
+        """
         with _env(DISPATCHARR_ENV="dev", DISPATCHARR_PORT="9191"):
             self.assertEqual(
-                relay_client.get_relay_control_base_url(), "http://127.0.0.1:5656"
+                relay_client.get_relay_control_base_url(), "http://127.0.0.1:5658"
+            )
+            self.assertEqual(
+                control_plane.get_control_plane_base_url(), "http://127.0.0.1:5656"
             )
 
     def test_aio_is_loopback_nginx(self):
@@ -63,7 +75,7 @@ class ResolveBaseUrlTests(SimpleTestCase):
                 relay_client.get_relay_control_base_url(), "http://127.0.0.1:9191"
             )
 
-    def test_both_directions_share_one_address_and_differ_only_in_override(self):
+    def test_both_directions_share_one_address_outside_dev_and_differ_only_in_override(self):
         with _env(DISPATCHARR_ENV="modular", DISPATCHARR_WEB_HOST="w"):
             self.assertEqual(
                 relay_client.get_relay_control_base_url(),
diff --git a/apps/proxy/tests/test_stream_switch.py b/apps/proxy/tests/test_stream_switch.py
index bc9e8395..f20d1bf0 100644
--- a/apps/proxy/tests/test_stream_switch.py
+++ b/apps/proxy/tests/test_stream_switch.py
@@ -8,11 +8,6 @@ from rest_framework.test import APIRequestFactory, force_authenticate
 
 from apps.accounts.models import User
 from apps.proxy import relay_client
-from apps.proxy.live_proxy import views as views_module
-from apps.proxy.live_proxy.constants import ChannelMetadataField
-from apps.proxy.live_proxy.redis_keys import RedisKeys
-from apps.proxy.live_proxy.services import channel_service as cs_module
-from apps.proxy.live_proxy.services.channel_service import ChannelService
 from apps.proxy.ts_admin_views import change_stream
 
 
@@ -78,202 +73,8 @@ def make_proxy_server(redis, owner):
     return proxy
 
 
-class OwnerPathTests(TestCase):
-    def _run(self, manager_url="http://provider.example/stream/296622.ts"):
-        redis = FakeRedis()
-        proxy = make_proxy_server(redis, owner=True)
-
-        manager = MagicMock()
-        manager.url = manager_url
-        manager.update_url.return_value = True
-        proxy.stream_managers[CHANNEL_ID] = manager
-
-        with patch.object(cs_module.ProxyServer, "get_instance", return_value=proxy), \
-             patch("django.db.close_old_connections"):
-            result = ChannelService.change_stream_url(
-                CHANNEL_ID, NEW_URL, "test-agent",
-                target_stream_id=144065, m3u_profile_id=7,
-                stream_name="Alt Feed",
-            )
-        return result, redis, manager
-
-    def test_owner_switch_persists_stream_id_metadata(self):
-        result, redis, manager = self._run()
-
-        manager.update_url.assert_called_once_with(NEW_URL, 144065, 7)
-        self.assertTrue(result["success"])
-        self.assertTrue(result["direct_update"])
-
-        metadata = redis.hashes[RedisKeys.channel_metadata(CHANNEL_ID)]
-        self.assertEqual(metadata[ChannelMetadataField.URL], NEW_URL)
-        self.assertEqual(metadata[ChannelMetadataField.STREAM_ID], "144065")
-        self.assertEqual(metadata[ChannelMetadataField.M3U_PROFILE], "7")
-        self.assertEqual(metadata[ChannelMetadataField.STREAM_NAME], "Alt Feed")
-
-    def test_owner_same_url_is_success_and_repairs_metadata(self):
-        result, redis, manager = self._run(manager_url=NEW_URL)
-
-        manager.update_url.assert_not_called()
-        self.assertTrue(result["success"])
-
-        metadata = redis.hashes[RedisKeys.channel_metadata(CHANNEL_ID)]
-        self.assertEqual(metadata[ChannelMetadataField.STREAM_ID], "144065")
-
-    def test_owner_switch_persists_channel_name_and_m3u_profile_name(self):
-        """PIN. Phase 2 PR 2b-1, review hop 9. Every other test in this class
-        calls change_stream_url with stream_name alone -- channel_name and
-        m3u_profile_name default to None, so nothing here could tell a
-        threaded value from a dropped one. This one supplies real, distinct
-        values for both."""
-        redis = FakeRedis()
-        proxy = make_proxy_server(redis, owner=True)
-
-        manager = MagicMock()
-        manager.url = "http://provider.example/stream/296622.ts"
-        manager.update_url.return_value = True
-        proxy.stream_managers[CHANNEL_ID] = manager
-
-        with patch.object(cs_module.ProxyServer, "get_instance", return_value=proxy), \
-             patch("django.db.close_old_connections"):
-            ChannelService.change_stream_url(
-                CHANNEL_ID, NEW_URL, "test-agent",
-                target_stream_id=144065, m3u_profile_id=7,
-                stream_name="Alt Feed",
-                channel_name="Real Hop 9 Channel Name",
-                m3u_profile_name="Real Hop 9 Profile Name",
-            )
-
-        metadata = redis.hashes[RedisKeys.channel_metadata(CHANNEL_ID)]
-        self.assertEqual(
-            metadata[ChannelMetadataField.CHANNEL_NAME], "Real Hop 9 Channel Name"
-        )
-        self.assertEqual(
-            metadata[ChannelMetadataField.M3U_PROFILE_NAME], "Real Hop 9 Profile Name"
-        )
 
 
-class NonOwnerPathTests(TestCase):
-    def _run(self, owner_outcome):
-        redis = FakeRedis()
-        proxy = make_proxy_server(redis, owner=False)
-        status_key = RedisKeys.switch_status(CHANNEL_ID)
-
-        if owner_outcome is not None:
-            original_publish = redis.publish
-
-            def publish_and_confirm(channel, message):
-                original_publish(channel, message)
-                redis.store[status_key] = owner_outcome
-
-            redis.publish = publish_and_confirm
-
-        with patch.object(cs_module.ProxyServer, "get_instance", return_value=proxy), \
-             patch.object(cs_module, "STREAM_SWITCH_CONFIRM_TIMEOUT", 0.3), \
-             patch.object(cs_module, "STREAM_SWITCH_POLL_INTERVAL", 0.05):
-            result = ChannelService.change_stream_url(
-                CHANNEL_ID, NEW_URL, "test-agent",
-                target_stream_id=144065, m3u_profile_id=7,
-                stream_name="Alt Feed",
-            )
-        return result, redis
-
-    def test_pubsub_event_carries_stream_id(self):
-        result, redis = self._run(owner_outcome="switched")
-
-        self.assertEqual(len(redis.published), 1)
-        payload = json.loads(redis.published[0][1])
-        self.assertEqual(payload["stream_id"], 144065)
-        self.assertEqual(payload["m3u_profile_id"], 7)
-        self.assertEqual(payload["stream_name"], "Alt Feed")
-        self.assertEqual(payload["url"], NEW_URL)
-
-    def test_pubsub_event_carries_channel_name_and_m3u_profile_name(self):
-        """PIN. pr-review bot finding, verified and confirmed blocking: the
-        follower branch of change_stream_url published stream_name alone --
-        _publish_stream_switch_event had no parameters for channel_name/
-        m3u_profile_name at all, so an operator-initiated change_stream or
-        next_stream issued against a follower worker reached the owner with
-        both names unset. The owner's event handler then called
-        _update_channel_metadata with them None, leaving the pre-switch
-        m3u_profile_name in the hash -- the same stale-name shape fixed for
-        the automatic-failover path at input/manager.py:2162, reintroduced
-        here, and worse than before this PR because the ORM fallback that
-        used to paper over it (channel_service.py:343) is gone. Every other
-        test in this class calls change_stream_url with stream_name alone,
-        so none of them could catch a dropped channel_name/m3u_profile_name;
-        this one supplies real, distinct values for both."""
-        redis = FakeRedis()
-        proxy = make_proxy_server(redis, owner=False)
-        status_key = RedisKeys.switch_status(CHANNEL_ID)
-
-        original_publish = redis.publish
-
-        def publish_and_confirm(channel, message):
-            original_publish(channel, message)
-            redis.store[status_key] = "switched"
-
-        redis.publish = publish_and_confirm
-
-        with patch.object(cs_module.ProxyServer, "get_instance", return_value=proxy), \
-             patch.object(cs_module, "STREAM_SWITCH_CONFIRM_TIMEOUT", 0.3), \
-             patch.object(cs_module, "STREAM_SWITCH_POLL_INTERVAL", 0.05):
-            ChannelService.change_stream_url(
-                CHANNEL_ID, NEW_URL, "test-agent",
-                target_stream_id=144065, m3u_profile_id=7,
-                stream_name="Alt Feed",
-                channel_name="Real Follower Channel Name",
-                m3u_profile_name="Real Follower Profile Name",
-            )
-
-        self.assertEqual(len(redis.published), 1)
-        payload = json.loads(redis.published[0][1])
-        self.assertEqual(payload["channel_name"], "Real Follower Channel Name")
-        self.assertEqual(payload["m3u_profile_name"], "Real Follower Profile Name")
-
-    def test_switch_confirmed_by_owner_reports_success(self):
-        result, _ = self._run(owner_outcome="switched")
-
-        self.assertTrue(result["success"])
-        self.assertFalse(result["direct_update"])
-        self.assertTrue(result["event_published"])
-
-    def test_switch_failed_by_owner_reports_failure(self):
-        result, _ = self._run(owner_outcome="failed")
-
-        self.assertFalse(result["success"])
-        self.assertIn("failed", result["message"].lower())
-
-    def test_no_confirmation_times_out_and_reports_failure(self):
-        result, _ = self._run(owner_outcome=None)
-
-        self.assertFalse(result["success"])
-        self.assertIs(result["confirmed"], False)
-        self.assertIn("not confirmed", result["message"])
-
-    def test_stale_status_key_is_cleared_before_publishing(self):
-        redis = FakeRedis()
-        proxy = make_proxy_server(redis, owner=False)
-        status_key = RedisKeys.switch_status(CHANNEL_ID)
-        redis.store[status_key] = "switched"
-
-        deleted_before_publish = []
-        original_publish = redis.publish
-
-        def tracking_publish(channel, message):
-            deleted_before_publish.append(status_key not in redis.store)
-            original_publish(channel, message)
-
-        redis.publish = tracking_publish
-
-        with patch.object(cs_module.ProxyServer, "get_instance", return_value=proxy), \
-             patch.object(cs_module, "STREAM_SWITCH_CONFIRM_TIMEOUT", 0.2), \
-             patch.object(cs_module, "STREAM_SWITCH_POLL_INTERVAL", 0.05):
-            result = ChannelService.change_stream_url(
-                CHANNEL_ID, NEW_URL, "test-agent", target_stream_id=144065,
-            )
-
-        self.assertEqual(deleted_before_publish, [True])
-        self.assertFalse(result["success"])
 
 
 class ChangeStreamViewTests(TestCase):
@@ -304,10 +105,12 @@ class ChangeStreamViewTests(TestCase):
         return request
 
     def test_a_non_integer_stream_id_is_rejected_with_400(self):
-        proxy = make_proxy_server(FakeRedis(), owner=True)
-
-        with patch.object(views_module.ProxyServer, "get_instance", return_value=proxy):
-            response = change_stream(self._post({"stream_id": "abc"}), CHANNEL_ID)
+        # No ProxyServer patch: stage 2d-2 moved change_stream into
+        # ts_admin_views, whose ProxyServer import was function-local, and
+        # stage 2d-4 removed it outright (worker_id is computed locally now).
+        # The patch that stood here already reached a module the view under
+        # test did not touch.
+        response = change_stream(self._post({"stream_id": "abc"}), CHANNEL_ID)
 
         self.assertEqual(response.status_code, 400)
         payload = json.loads(response.content)
@@ -317,7 +120,6 @@ class ChangeStreamViewTests(TestCase):
         self.assertNotIn("invalid literal", payload["error"])
 
     def test_stream_id_is_coerced_to_int_before_reaching_the_service(self):
-        proxy = make_proxy_server(FakeRedis(), owner=True)
         resolved_answer = {
             "source": {
                 "url": NEW_URL,
@@ -329,8 +131,7 @@ class ChangeStreamViewTests(TestCase):
             "error": None,
         }
 
-        with patch.object(views_module.ProxyServer, "get_instance", return_value=proxy), \
-             patch("apps.proxy.next_source.resolve_source",
+        with patch("apps.proxy.next_source.resolve_source",
                    return_value=resolved_answer) as resolve_source_mock, \
              patch.object(
                  relay_client, "advance",
diff --git a/tests/test_urls_xc_three_segment.py b/tests/test_urls_xc_three_segment.py
index dae8a603..31ed6ab1 100644
--- a/tests/test_urls_xc_three_segment.py
+++ b/tests/test_urls_xc_three_segment.py
@@ -6,7 +6,17 @@ three-segment, no-trailing-slash shape. See docs/superpowers/specs/
 and this plan's Task 1 for why: stream_xc's get_object_or_404(User, ...) is
 the first statement in the view, and Http404 never escapes DRF's own
 exception_handler to reach Django's catch-all, so the URL pattern itself is
-the only lever outside apps/proxy/live_proxy/.
+the only lever.
+
+Phase 2 stage 2d-4 deleted apps/proxy/live_proxy/ and with it the real
+stream_xc, but NOT these two patterns, and the reason is not routing: nginx
+has sent both XC live shapes to the Go relay since stage 2d-3. It is that
+apps/proxy/authorize_views.py's _surface_for() hands the URI in X-Original-URI
+to Django's own resolver and keys on the matched view's __name__ -- so with
+these patterns gone, every auth_request subrequest for an XC live tune
+resolves to the SPA catch-all and authorize_view answers 403, in production.
+They now name apps/proxy/stream_routes.py's stream_xc, which exists to be
+RESOLVED and never to be called behind nginx. See that module's header.
 """
 
 from django.test import SimpleTestCase
```

### Appendix A.2a — the class-deletion script that produced A.2's splits

Kept so a reviewer can see that no class was deleted by line number. It does not need to be
run: A.2 carries its output.

```python
#!/usr/bin/env python3
"""Appendix A.2 -- the test-file dispositions of ruling R7.

Run from the repository root, AFTER `git rm`-ing the four files R7 deletes
whole. It performs three kinds of edit, each asserted:

  * RE-POINT  -- a `live_proxy` import or mock.patch string that has a
                 surviving target (the 2d-1 shims' new homes, or
                 apps.proxy.next_source for url_utils' two re-exports);
  * DROP      -- an import whose only user is a class this script deletes;
  * DELETE    -- a whole test class whose subject went with the package.

A class is deleted by name, from its `class X` line to the line before the
next top-level `class`/`def`/decorator or EOF, and the script asserts the name
appears exactly once. Nothing is addressed by line number.
"""
import pathlib
import re
import sys

edits = 0


def sub(rel, old, new, count=1):
    global edits
    p = pathlib.Path(rel)
    t = p.read_text(encoding="utf-8")
    n = t.count(old)
    assert n == count, f"{rel}: anchor matched {n} times, expected {count}\n---\n{old!r}"
    p.write_text(t.replace(old, new), encoding="utf-8")
    edits += n


def drop_class(rel, name):
    """Delete `class <name>` and its whole body."""
    global edits
    p = pathlib.Path(rel)
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    starts = [i for i, l in enumerate(lines) if re.match(rf"class {re.escape(name)}\b", l)]
    assert len(starts) == 1, f"{rel}: class {name} found {len(starts)} times"
    start = starts[0]
    # Walk back over a contiguous run of decorators and their comments.
    while start > 0 and (lines[start - 1].startswith("@") or lines[start - 1].startswith("#")):
        start -= 1
    end = len(lines)
    for i in range(starts[0] + 1, len(lines)):
        if re.match(r"(class |def |@)", lines[i]):
            end = i
            # Take the blank lines that separated it from what follows.
            while end > starts[0] + 1 and lines[end - 1].strip() == "":
                end -= 1
            break
    del lines[start:end]
    p.write_text("".join(lines), encoding="utf-8")
    edits += 1


# ---------------------------------------------------------- KEEP by re-point
sub("apps/channels/tests/test_channel_stream_reuse.py",
    "from apps.proxy.live_proxy.redis_keys import RedisKeys",
    "from apps.proxy.redis_keys import RedisKeys")

sub("apps/channels/tests/test_get_stream_assignment.py",
    "from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState\n"
    "from apps.proxy.live_proxy.redis_keys import RedisKeys",
    "from apps.proxy.constants import ChannelMetadataField, ChannelState\n"
    "from apps.proxy.redis_keys import RedisKeys")

sub("apps/channels/tests/test_recording_pipeline.py",
    '@patch("apps.proxy.live_proxy.config_helper.ConfigHelper.stream_timeout", return_value=60)',
    '@patch("apps.proxy.config_helper.ConfigHelper.stream_timeout", return_value=60)')
sub("apps/channels/tests/test_recording_pipeline.py",
    '@patch("apps.proxy.live_proxy.config_helper.ConfigHelper.failover_grace_period", return_value=20)',
    '@patch("apps.proxy.config_helper.ConfigHelper.failover_grace_period", return_value=20)')

sub("apps/proxy/tests/test_boundary_error_arms.py",
    "from apps.proxy.live_proxy.config_helper import ConfigHelper",
    "from apps.proxy.config_helper import ConfigHelper")

# --------------------------------------------------------------- SPLIT files
# test_ts_proxy_initializing.py: Half A dies, PreActiveStateTests stays.
drop_class("apps/channels/tests/test_ts_proxy_initializing.py", "StreamManagerFinallyBlockTests")
sub("apps/channels/tests/test_ts_proxy_initializing.py",
    "from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState\n"
    "from apps.proxy.live_proxy.redis_keys import RedisKeys\n"
    "from apps.proxy.live_proxy.input.manager import StreamManager\n",
    "from apps.proxy.constants import ChannelState\n")

# test_ts_proxy_keepalive.py: only KeepaliveTimingTests survives.
for cls in (
    "OwnerWorkerKeepaliveTests",
    "NonOwnerWorkerKeepaliveTests",
    "DoStatsUpdateTests",
    "ClientRemoveIntegrationTests",
):
    drop_class("apps/channels/tests/test_ts_proxy_keepalive.py", cls)

# test_boundary_error_arms.py: the two LiveProxyConfig.ready() tests go.
drop_class("apps/proxy/tests/test_boundary_error_arms.py", "LiveProxyAppsReadyTests")

# test_combined_stats.py: the builder's three tests go with the import.
drop_class("apps/proxy/tests/test_combined_stats.py", "BuildLiveChannelStatsDataTests")
sub("apps/proxy/tests/test_combined_stats.py",
    "from apps.proxy.live_proxy.channel_status import build_live_channel_stats_data\n", "")

# test_stream_switch.py: the owner/follower halves go; ChangeStreamViewTests stays.
drop_class("apps/proxy/tests/test_stream_switch.py", "OwnerPathTests")
drop_class("apps/proxy/tests/test_stream_switch.py", "NonOwnerPathTests")
sub("apps/proxy/tests/test_stream_switch.py",
    "from apps.proxy.live_proxy import views as views_module\n"
    "from apps.proxy.live_proxy.constants import ChannelMetadataField\n"
    "from apps.proxy.live_proxy.redis_keys import RedisKeys\n"
    "from apps.proxy.live_proxy.services import channel_service as cs_module\n"
    "from apps.proxy.live_proxy.services.channel_service import ChannelService\n",
    "")

print("edits:", edits)
```

### Appendix D.4 — the re-homed absence assertion (R7 #11), Task 7

The **detail** golden, not the list one: `width`/`height`/`video_bitrate` exist on the detail
payload alone (`relay/httpapi/detail.go:159-161`). Break-check in Task 7 Step 4b, run.

```diff
diff --git a/relay/httpapi/detail_golden_test.go b/relay/httpapi/detail_golden_test.go
index 80390fc4..d534e352 100644
--- a/relay/httpapi/detail_golden_test.go
+++ b/relay/httpapi/detail_golden_test.go
@@ -243,3 +243,58 @@ func TestTheDetailPayloadOmitsTheTwoFieldsNothingWrites(t *testing.T) {
 		}
 	}
 }
+
+// RE-HOMED BY PHASE 2 STAGE 2d-4. The one assertion of
+// apps/proxy/tests/test_relay_status_shape.py's ten that had no cover on
+// either side -- its test_the_three_dvr_fields_are_absent_when_redis_has_none.
+// That file drove the deleted ChannelStatus builders directly, so it went with
+// apps/proxy/live_proxy/; the property it pinned did not, and the golden above
+// cannot carry it because its fixture is one fully-populated channel.
+//
+// The three fields are `string` + `,omitempty` at detail.go:159-161 and are
+// assigned only when the source stats carry them (:311-318), so an unset field
+// must VANISH rather than render as "" -- the same contract
+// TestEveryOptionalFieldIsAbsentRatherThanNull holds the LIST payload to, and
+// a distinct one, because width/height/video_bitrate exist on the detail
+// payload alone.
+func TestTheDetailPayloadOmitsTheDVRVideoFieldsWhenNothingSetThem(t *testing.T) {
+	payload := detailGoldenPayload()
+	payload.Width = ""
+	payload.Height = ""
+	payload.VideoBitrate = ""
+
+	encoded, err := json.Marshal(payload)
+	if err != nil {
+		t.Fatalf("encoding the payload: %v", err)
+	}
+	var decoded map[string]any
+	if err := json.Unmarshal(encoded, &decoded); err != nil {
+		t.Fatalf("decoding: %v", err)
+	}
+	for _, key := range []string{"width", "height", "video_bitrate"} {
+		if _, present := decoded[key]; present {
+			t.Errorf("an unset %q still renders, as %v: DRF declares it required=False "+
+				"with no default, so the key must vanish rather than carry an empty "+
+				"string", key, decoded[key])
+		}
+	}
+	// And they DO render when set, so a struct-tag typo cannot make this pass.
+	for _, key := range []string{"width", "height", "video_bitrate"} {
+		if _, present := mustDecodeDetail(t, detailGoldenPayload())[key]; !present {
+			t.Errorf("the populated detail payload is missing %q", key)
+		}
+	}
+}
+
+func mustDecodeDetail(t *testing.T, payload any) map[string]any {
+	t.Helper()
+	encoded, err := json.Marshal(payload)
+	if err != nil {
+		t.Fatalf("encoding the payload: %v", err)
+	}
+	var decoded map[string]any
+	if err := json.Unmarshal(encoded, &decoded); err != nil {
+		t.Fatalf("decoding: %v", err)
+	}
+	return decoded
+}
```

### Appendix I.1 — routing (R10), Task 8

```diff
diff --git a/dispatcharr/test_discovery.py b/dispatcharr/test_discovery.py
index bee591e8..3b1fc16e 100644
--- a/dispatcharr/test_discovery.py
+++ b/dispatcharr/test_discovery.py
@@ -30,10 +30,6 @@ _SHARED_PATH_PREFIXES: tuple[str, ...] = (
 #                          Xtream surfaces, so both must run.
 #   apps/hdhr/             no tests of its own; the HDHomeRun lineup is built
 #                          from channels and shares the output app's listing.
-#   apps/proxy/live_proxy/  the proxy has its own tests, but its richest ones
-#                           are apps/channels/tests/test_ts_proxy_teardown.py,
-#                           which builds a real ProxyServer ten times. Editing
-#                           the proxy is the worst moment to skip them.
 #   scripts/coverage_live_path  not an app directory at all -- this is Gate 2's
 #                           own measurement script, rcfile, floor and floor
 #                           companion. Before this alias existed, editing any
@@ -45,7 +41,7 @@ _SHARED_PATH_PREFIXES: tuple[str, ...] = (
 #                           job (gated on that same flag, see backend-tests.yml)
 #                           never ran, so the shape guard this script implements
 #                           was never exercised by the one kind of change most
-#                           likely to need it. Routes to Gate 2's own three
+#                           likely to need it. Routes to Gate 2's own two
 #                           labels (the same fixed set backend-tests.yml's
 #                           coverage-label matrix always runs), not "__all__":
 #                           editing the measurement script has no bearing on
@@ -54,8 +50,7 @@ _PATH_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
     ("apps/api/", ("__all__",)),
     ("apps/vod/", ("apps.vod", "apps.output")),
     ("apps/hdhr/", ("apps.output", "apps.channels")),
-    ("apps/proxy/live_proxy/", ("apps.proxy.live_proxy", "apps.channels")),
-    ("scripts/coverage_live_path", ("apps.proxy", "apps.proxy.live_proxy", "apps.channels")),
+    ("scripts/coverage_live_path", ("apps.proxy", "apps.channels")),
 )
 
 
diff --git a/tests/test_ci_test_routing.py b/tests/test_ci_test_routing.py
index 398f5676..41f02907 100644
--- a/tests/test_ci_test_routing.py
+++ b/tests/test_ci_test_routing.py
@@ -41,21 +41,14 @@ class ChangedPathRoutingTests(SimpleTestCase):
         self.assertIn("apps.vod.tests", labels)
         self.assertIn("apps.output.tests", labels)
 
-    def test_live_proxy_change_runs_channels_tests(self):
-        """Pins: apps/proxy/live_proxy/ had no alias and matched by prefix only.
-
-        Prefix matching selected apps.proxy.live_proxy.tests alone, skipping
-        apps/channels/tests/test_ts_proxy_teardown.py -- the richest proxy
-        coverage in the tree, and the only place a real ProxyServer is built.
-        """
-        self.assertIn("apps.proxy.live_proxy.tests", self.available)
-        self.assertIn("apps.channels.tests", self.available)
-
-        labels = self._labels("apps/proxy/live_proxy/server.py")
-        self.assertIn("apps.proxy.live_proxy.tests", labels)
-        self.assertIn("apps.channels.tests", labels)
-
-    def test_coverage_gate_script_change_runs_its_own_three_labels(self):
+    # test_live_proxy_change_runs_channels_tests stood here until Phase 2
+    # stage 2d-4. It pinned the apps/proxy/live_proxy/ alias -- which existed
+    # because prefix matching selected apps.proxy.live_proxy.tests alone and
+    # skipped apps/channels/tests/test_ts_proxy_teardown.py. Both the alias and
+    # the directory it named were deleted with the package, and a routing test
+    # for a path that cannot change is not a pin.
+
+    def test_coverage_gate_script_change_runs_its_own_two_labels(self):
         """Pins: scripts/coverage_live_path* had no alias and matched no app prefix.
 
         _labels_under_installed_app_tree only matches a path under an app's own
@@ -67,7 +60,7 @@ class ChangedPathRoutingTests(SimpleTestCase):
         the one kind of change most likely to need it -- exactly the gap #252's
         module-list fix landed into unexercised.
         """
-        expected = {"apps.proxy.tests", "apps.proxy.live_proxy.tests", "apps.channels.tests"}
+        expected = {"apps.proxy.tests", "apps.channels.tests"}
         self.assertLessEqual(expected, self.available)
 
         for path in (
```

### Appendix I.2 — the boot-check hook arm and the isolated script (R10), Task 8

```diff
diff --git a/.claude/hooks/run-affected-tests.sh b/.claude/hooks/run-affected-tests.sh
index 01772aaf..4249b12f 100755
--- a/.claude/hooks/run-affected-tests.sh
+++ b/.claude/hooks/run-affected-tests.sh
@@ -131,22 +131,23 @@ if [[ "$REL" == */models.py || "$REL" == models.py ]]; then
 fi
 
 # -------------------------------------------------------------- boot check ---
-# apps/channels/models.py:6-7 imports apps/proxy/redis_keys.py and
-# apps/proxy/constants.py at module level, so one added import in either stops
-# Django booting for every migration and command. Phase 2 stage 2d-1 moved those
-# two names out of apps/proxy/live_proxy/ (spec Amendment A10.3) along with
-# ConfigHelper, which the catch-up surface imports at module level -- the trap
-# moved house, it did not go away, and this arm moved with it.
+# apps/channels/models.py:6 imports apps/proxy/redis_keys.py at module level,
+# so one added import there stops Django booting for every migration and
+# command. Phase 2 stage 2d-1 moved that name -- with ChannelMetadataField,
+# ChannelState and ConfigHelper -- out of apps/proxy/live_proxy/ (spec
+# Amendment A10.3): the trap moved house, it did not go away, and this arm
+# moved with it. apps/proxy/constants.py and config_helper.py stay in the arm
+# although models.py imports neither any more (stage 2d-4 deleted its
+# ChannelMetadataField import with issue #190's five ranges):
+# apps/timeshift/views.py:40-41 imports both at module level, and the urlconf
+# is loaded by manage.py check.
 #
-# The three apps/proxy/live_proxy/ paths stay until stage 2d-4 deletes the
-# package: they are re-export shims every relay module still imports, and
-# apps/proxy/apps.py's ready() reaches them in every process that is not
-# manage.py. THIS ARM MATCHES BY LITERAL PATH -- a file renamed out of it stops
-# being checked with no error and no output, which is how it would be lost.
+# Stage 2d-4 deleted the three apps/proxy/live_proxy/ re-export shims that
+# stood beside these three, with the package. THIS ARM MATCHES BY LITERAL PATH
+# -- a file renamed out of it stops being checked with no error and no output,
+# which is how it would be lost.
 case "$REL" in
-  apps/proxy/constants.py|apps/proxy/redis_keys.py|apps/proxy/config_helper.py|\
-  apps/proxy/live_proxy/constants.py|apps/proxy/live_proxy/redis_keys.py|\
-  apps/proxy/live_proxy/config_helper.py)
+  apps/proxy/constants.py|apps/proxy/redis_keys.py|apps/proxy/config_helper.py)
     if container_ok; then
       OUT="$(dexec manage.py check)"; [ $? -eq 0 ] ||
         block "django check failed after editing ${REL}" \
diff --git a/scripts/coverage_live_path_isolated.sh b/scripts/coverage_live_path_isolated.sh
index 55c91fed..8aa9c955 100755
--- a/scripts/coverage_live_path_isolated.sh
+++ b/scripts/coverage_live_path_isolated.sh
@@ -24,7 +24,6 @@ DJANGO_SECRET_KEY_FOR_EXEC="${DJANGO_SECRET_KEY:-hook-test-secret}"
 
 declare -a PAIRS=(
   "proxy:apps.proxy.tests"
-  "liveproxy:apps.proxy.live_proxy.tests"
   "channels:apps.channels.tests"
 )
 
```

### Appendix I.3 — `backend-tests.yml`'s coverage matrix (R10), Task 8

```diff
diff --git a/.github/workflows/backend-tests.yml b/.github/workflows/backend-tests.yml
index 4c7cebe6..60cf203c 100644
--- a/.github/workflows/backend-tests.yml
+++ b/.github/workflows/backend-tests.yml
@@ -177,7 +177,7 @@ jobs:
     strategy:
       fail-fast: false
       matrix:
-        label: [apps.proxy.tests, apps.proxy.live_proxy.tests, apps.channels.tests]
+        label: [apps.proxy.tests, apps.channels.tests]
     container:
       image: ${{ needs.plan.outputs.base_image }} # zizmor: ignore[unpinned-images]
       credentials:
```

### Appendix I.4 — `go-tests.yml`: the `differential` job (R13), Task 8

The job, its `needs` entry, its `env` entry, the success loop, the echo, the header comment's
claim about it, and **both** `live_proxy` clauses in the change detector. **Verified**: the
result re-parses with `yaml.safe_load`, and zizmor and actionlint are clean on it.

```diff
diff --git a/.github/workflows/go-tests.yml b/.github/workflows/go-tests.yml
index 565f5c36..f2bac094 100644
--- a/.github/workflows/go-tests.yml
+++ b/.github/workflows/go-tests.yml
@@ -9,10 +9,14 @@ name: Go Tests
 # check "Expected" forever and blocking the merge.
 #
 # The coverage ratchet IS here, as of 2c-9: `build` measures (one `go test
-# -race` run, now with -coverprofile), `coverage` gates against
-# scripts/coverage_relay_go.floor on a bare runner, and `differential` runs
-# the one test that drives BOTH relays from the same bytes. All three are in
-# `Go result`'s needs below.
+# -race` run, now with -coverprofile) and `coverage` gates against
+# scripts/coverage_relay_go.floor on a bare runner. Both are in `Go result`'s
+# needs below. The third job that used to sit beside them, `differential`,
+# drove BOTH relays from the same bytes; Phase 2 stage 2d-4 deleted it with
+# the Python relay, because what it proved -- two implementations agreeing --
+# has no meaning once there is one. What it incidentally provided, a Go binary
+# driven against a real Django, the E2E suite has done through nginx since
+# stage 2d-3.
 on:
   push:
     branches: [main]
@@ -107,11 +111,19 @@ jobs:
           # scripts/coverage_relay_go.* is here and NOT under the Python
           # gate's scripts/coverage_live_path prefix, deliberately: that
           # prefix is a _PATH_ALIASES entry in dispatcharr/test_discovery.py
-          # that routes to three DJANGO labels, so a file named
+          # that routes to DJANGO labels, so a file named
           # coverage_live_path_go.sh would have run the Python backend suite
-          # for a Go-only change. The differential test is named too, because
-          # it is the one Python file this workflow's `differential` job runs.
-          pattern='^(relay/|\.golangci\.yml$|scripts/check_go_stdlib_only\.sh$|scripts/check_go_credential_logging\.sh$|scripts/coverage_relay_go\.|\.github/workflows/go-tests\.yml$|apps/proxy/live_proxy/tests/harness/|apps/proxy/live_proxy/tests/test_relay_differential\.py$)'
+          # for a Go-only change.
+          #
+          # Phase 2 stage 2d-4 removed the two apps/proxy/live_proxy/ clauses
+          # that stood here (the subprocess harness and the differential test)
+          # with the package and the `differential` job. Nothing replaces them:
+          # the ffmpeg stderr corpus the harness clause existed for now lives
+          # in relay/internal/relaytest/testdata/, which the leading `^relay/`
+          # already covers. That is the load-bearing half -- a corpus outside
+          # `^relay/` would stop triggering this workflow at all, and `Go
+          # result` would stay green through its not-required branch.
+          pattern='^(relay/|\.golangci\.yml$|scripts/check_go_stdlib_only\.sh$|scripts/check_go_credential_logging\.sh$|scripts/coverage_relay_go\.|\.github/workflows/go-tests\.yml$)'
           if printf '%s\n' "$changed" | grep -qE "$pattern"; then
             echo "go=true" >> "$GITHUB_OUTPUT"
           else
@@ -364,112 +376,12 @@ jobs:
             exit 1
           fi
 
-  # Spec Amendment A2.4: the one test that drives BOTH relays from the same
-  # synthetic asset and compares what each delivers. It lives with the Python
-  # harness because that is what can start a real Django, a real Redis and a
-  # real fake upstream — and it runs HERE rather than in a backend label
-  # because it needs a compiled relay-go, which the base image does not ship
-  # and backend-tests.yml has no reason to build.
-  #
-  # It SKIPS when DISPATCHARR_RELAY_GO_BIN is unset, which is every other run
-  # of apps.proxy.live_proxy.tests — deterministically, in both
-  # backend-tests.yml's `test` and its `coverage-label` jobs, so Gate 2's
-  # Python census sees the same thing either way and is not perturbed. The
-  # step below asserts the skip did NOT happen here, because a silently
-  # skipped differential test is green for the one reason it must never be.
-  differential:
-    name: Cross-implementation differential
-    runs-on: ubuntu-latest
-    needs: changes
-    if: needs.changes.outputs.go == 'true'
-    timeout-minutes: 20
-    permissions:
-      contents: read
-      packages: read
-    container:
-      image: ${{ needs.changes.outputs.base_image }} # zizmor: ignore[unpinned-images]
-      credentials:
-        username: ${{ github.actor }}
-        password: ${{ secrets.GITHUB_TOKEN }}
-      options: --entrypoint "" --init
-    env:
-      DISPATCHARR_ENV: aio
-      DJANGO_SECRET_KEY: ci-test-secret-key
-      POSTGRES_DB: dispatcharr
-      POSTGRES_USER: dispatch
-      POSTGRES_PASSWORD: secret
-      DISPATCHARR_LOG_LEVEL: WARNING
-      SYNC_PYTHON_DEPS: 'true'
-    steps:
-      - name: Checkout code
-        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
-        with:
-          persist-credentials: false
-
-      - name: Set up Go
-        uses: actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e # v7.0.0
-        with:
-          go-version-file: relay/go.mod
-
-      - name: Build relay-go
-        working-directory: ./relay
-        run: go build -o /tmp/relay-go .
-
-      - name: Drive both relays from the same bytes
-        shell: bash
-        env:
-          GITHUB_WORKSPACE: ${{ github.workspace }}
-          DISPATCHARR_RELAY_GO_BIN: /tmp/relay-go
-          # REDIRECTED, NOT PIPED, and the difference is the whole job.
-          # ci_bootstrap_backend.sh runs this through `exec bash -c "$CI_BACKEND_RUNNER"`
-          # -- a fresh shell with no `pipefail` -- so `… | tee` would exit with
-          # tee's 0 and a FAILING differential would report green. Verified:
-          # `bash -c 'bash -c "exit 7" 2>&1 | tee /tmp/x'` exits 0, and the
-          # same command with `> /tmp/x 2>&1` exits 7. The two other
-          # CI_BACKEND_RUNNER call sites in this repository are single commands,
-          # so nothing upstream was protecting this one.
-          CI_BACKEND_RUNNER: >-
-            python manage.py test --keepdb -v2
-            apps.proxy.live_proxy.tests.test_relay_differential
-            > /tmp/differential.log 2>&1
-        run: bash scripts/ci_bootstrap_backend.sh
-
-      - name: Show the differential log
-        if: always()
-        shell: bash
-        run: cat /tmp/differential.log
-
-      # THREE assertions, because the step above can only be trusted for two
-      # of them. A skip is the "silence read as pass" shape -- the job green
-      # because the test never ran -- and Django prints "skipped=N" in its
-      # summary only when something skipped, so its absence is the assertion.
-      # A nonzero "Ran N tests" says the module ran at all. And the FINAL
-      # STATUS LINE must be exactly OK: "Ran 1 test … FAILED (failures=1)"
-      # satisfies both of the other two, which is what makes the third one
-      # load-bearing rather than belt-and-braces.
-      - name: Assert the differential test ran and passed
-        shell: bash
-        run: |
-          set -euo pipefail
-          grep -qE '^Ran [1-9][0-9]* tests?' /tmp/differential.log \
-            || { echo "the runner reported no tests; the module did not run"; exit 1; }
-          if grep -q 'skipped=' /tmp/differential.log; then
-            echo "the differential test SKIPPED in the one job that must not skip it:"
-            grep -n 'skipped\|DISPATCHARR_RELAY_GO_BIN' /tmp/differential.log | head -20
-            exit 1
-          fi
-          if ! grep -qE '^OK$' /tmp/differential.log; then
-            echo "the differential test RAN and did not pass:"
-            grep -nE '^(FAILED|ERROR|OK)' /tmp/differential.log | head -5
-            exit 1
-          fi
-
   # The one check in this workflow that may be required. It always reports,
   # because it is not gated on anything — see the comment on the triggers.
   go-result:
     name: Go result
     runs-on: ubuntu-latest
-    needs: [changes, build, lint, coverage, differential]
+    needs: [changes, build, lint, coverage]
     if: always()
     timeout-minutes: 5
     steps:
@@ -479,10 +391,9 @@ jobs:
           BUILD_RESULT: ${{ needs.build.result }}
           LINT_RESULT: ${{ needs.lint.result }}
           COVERAGE_RESULT: ${{ needs.coverage.result }}
-          DIFFERENTIAL_RESULT: ${{ needs.differential.result }}
           GO_REQUIRED: ${{ needs.changes.outputs.go }}
         run: |
-          echo "changes=$CHANGES_RESULT build=$BUILD_RESULT lint=$LINT_RESULT coverage=$COVERAGE_RESULT differential=$DIFFERENTIAL_RESULT go-required=$GO_REQUIRED"
+          echo "changes=$CHANGES_RESULT build=$BUILD_RESULT lint=$LINT_RESULT coverage=$COVERAGE_RESULT go-required=$GO_REQUIRED"
           if [ "$CHANGES_RESULT" != "success" ]; then
             echo "Change detection itself failed — cannot prove the Go jobs were unnecessary."
             exit 1
@@ -494,10 +405,10 @@ jobs:
           # `skipped` here means a gated job never ran on a run that needed
           # it, so only an exact `success` may report green.
           for pair in "build:$BUILD_RESULT" "lint:$LINT_RESULT" \
-                      "coverage:$COVERAGE_RESULT" "differential:$DIFFERENTIAL_RESULT"; do
+                      "coverage:$COVERAGE_RESULT"; do
             if [ "${pair#*:}" != "success" ]; then
               echo "The Go jobs were required and ${pair%%:*} did not succeed."
               exit 1
             fi
           done
-          echo "Go build, vet, tests, lint, the coverage gate and the differential passed."
+          echo "Go build, vet, tests, lint and the coverage gate passed."
```

### Appendix H.1 — `scripts/coverage_live_path.coveragerc` (R9), Task 9

Nine entries remain. The comment records the `stream_routes.py` decision (R6): not added,
because adding it would move `modules=` a second time for no ratchet value.

```diff
diff --git a/scripts/coverage_live_path.coveragerc b/scripts/coverage_live_path.coveragerc
index b5ac5246..c5971448 100644
--- a/scripts/coverage_live_path.coveragerc
+++ b/scripts/coverage_live_path.coveragerc
@@ -17,18 +17,23 @@ omit =
 parallel = True
 data_file = ${COVERAGE_LIVE_PATH_DATA_DIR}/.coverage
 
-# The ten Phase 1 boundary modules plus the relay, and nothing else: vod_proxy
-# and the dead hls_proxy stay out, matching D1's scope line.
+# The nine surviving Phase 1 boundary modules, and nothing else: vod_proxy and
+# the dead hls_proxy stay out, matching D1's scope line. Phase 2 stage 2d-4
+# removed `apps/proxy/live_proxy/*` with the package and `relay_views.py` with
+# the four /proxy/relay/ routes the Go relay took over at 2d-3, taking the
+# resolved file set from 38 to 9. apps/proxy/stream_routes.py is deliberately
+# NOT added: it is nine statements of stub on a path nginx never sends to
+# Django, and adding it would move `modules=` a second time for no ratchet
+# value. 2d-5's re-census may take it. THE FLOOR'S `missing` IS DELIBERATELY
+# SLACK UNTIL THEN -- see scripts/coverage_live_path.floor's header.
 [report]
 include =
-    apps/proxy/live_proxy/*
     apps/proxy/authorize.py
     apps/proxy/authorize_views.py
     apps/proxy/control_plane.py
     apps/proxy/next_source.py
     apps/proxy/relay_client.py
     apps/proxy/relay_serializers.py
-    apps/proxy/relay_views.py
     apps/proxy/permissions.py
     apps/proxy/internal_auth.py
     apps/proxy/internal_base_url.py
```

### Appendix H.2 — the floor's header (R9), Task 9

The header paragraph only. The `missing`/`modules`/`rcfile` VALUES are written by
`--write-floor --shape-only` in Task 9 Step 3, never by hand.

```diff
diff --git a/scripts/coverage_live_path.floor b/scripts/coverage_live_path.floor
index 3b452eb0..15abdf1b 100644
--- a/scripts/coverage_live_path.floor
+++ b/scripts/coverage_live_path.floor
@@ -1,6 +1,18 @@
 # Gate 2's ratchet floor. See docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
 # (Stage 2a > Gate 2) and docs/superpowers/plans/2026-09-10-phase2-2a7-coverage-gate.md.
 #
+# ** THIS FLOOR IS DELIBERATELY SLACK BETWEEN 2d-4 AND 2d-5, AND `missing` BELOW IS NOT
+# ** A MEASUREMENT OF THE TREE IT SITS ON. Phase 2 stage 2d-4 deleted
+# ** apps/proxy/live_proxy/ and apps/proxy/relay_views.py, taking the resolved file set
+# ** from 38 modules to 9 and the denominator with it. That PR shipped
+# ** `--write-floor --shape-only`, which rewrites `modules`, `module_count`, `rcfile` and
+# ** the informational `statements` and DELIBERATELY DOES NOT TOUCH `missing`, `percent`,
+# ** `measured` or `runs` -- so 1525 is still the figure the pre-delete tree earned, over
+# ** a denominator roughly a tenth its former size. The gate is mechanically green and
+# ** substantively toothless until `migration/phase2d-gate2-recensus` (2d-5) carries the
+# ** >=12-round CI census that makes the number real, under the stopping rule this header
+# ** prescribes below. A green run in that window proves the SHAPE checks, not coverage.
+#
 # `missing` is the ratchet -- a MAXIMUM, not a target, and lower is better. It is set
 # from the WORST run of at least twelve on the tree that earned it, which is why this
 # gate carries no separate tolerance parameter: the measured spread is already inside
```

### Appendix E — the parity matrix's Source and Pin columns (R11), Task 10

Addresses every row **by id**, asserts each matched exactly once, and asserts each carried
the number of `live_proxy` Source citations this plan measured — so a row that moved fails
loudly rather than being rewritten from a stale expectation. Prints exactly
`ok, 21 Source cells, 26 Pin cells, 2 Notes cells`.

```python
#!/usr/bin/env python3
"""Appendix E -- the parity matrix's Python column, replaced.

Run from the repository root. It rewrites, for each row that carried at least
one `apps/proxy/live_proxy/` citation:

  * the SOURCE cell -- every live_proxy citation replaced by citations into
    relay/, every other citation kept in place and in order (ruling R11);
  * the PIN cell -- every `apps/proxy/live_proxy/tests/...::name` reference
    dropped, every Go and .spec.ts reference kept in order.

Rows 26 and 27 take the new `retired:` Source sentinel instead (R11), which
Appendix F teaches the guard to read.

Every row is addressed BY ID and asserted to match exactly once, and every row
is asserted to have carried the number of live_proxy Source citations this plan
measured at the seed -- so a row that moved under this PR's feet fails loudly
rather than being rewritten from a stale expectation.
"""
import pathlib
import re
import sys

MATRIX = pathlib.Path("docs/relay-parity-matrix.md")

# row id -> (expected number of live_proxy Source citations at the seed,
#            the replacement Source cell, verbatim and complete)
SOURCES = {
    1: (2, "`relay/ffmpeg/detector.go:1-97`, `relay/channel/source_transcode.go:320-341`"),
    2: (3, "`relay/channel/health.go:41-120`, `relay/channel/failover.go:100-110`, `relay/channel/tuning.go:47-55`"),
    3: (3, "`apps/proxy/config.py:9-10`, `relay/channel/channel.go:410-425`"),
    4: (2, "`relay/ffmpeg/progress.go:20-40`, `relay/ffmpeg/detector.go:8-60`"),
    5: (1, "`relay/channel/tuning.go:10-30`, `relay/channel/channel.go:170-185`"),
    6: (2, "`relay/channel/channel.go:450-485`, `relay/channel/failover.go:280-295`"),
    7: (2, "`relay/buffer/ring.go:104-120`, `relay/buffer/ring.go:224-245`"),
    8: (2, "`relay/buffer/ring.go:340-380`, `relay/httpapi/stream.go:940-960`"),
    9: (2, "`relay/buffer/ring.go:160-200`"),
    10: (2, "`relay/channel/manager.go:190-240`, `relay/channel/manager.go:385-405`"),
    11: (2, "`relay/output/profile.go:14-30`, `relay/channel/output.go:90-140`"),
    12: (4, "`relay/httpapi/fmp4.go:110-160`, `relay/httpapi/fmp4.go:222-240`"),
    13: (3, "`relay/channel/client.go:30-50`, `relay/channel/manager.go:215-230`"),
    14: (6, "`apps/proxy/relay_serializers.py:59`, `apps/proxy/relay_serializers.py:129`, `apps/proxy/relay_serializers.py:60`, `apps/proxy/relay_serializers.py:136`, `relay/httpapi/detail.go:10-25`, `relay/httpapi/channels.go:178-190`"),
    15: (3, "`relay/httpapi/xc.go:18-60`"),
    17: (2, "`dispatcharr/utils.py:342-370`, `apps/proxy/authorize.py:486-503`, `apps/proxy/relay_serializers.py:29`, `apps/proxy/relay_serializers.py:79`, `relay/channel/client.go:42-52`, `relay/httpapi/stream.go:558-570`"),
    18: (2, "`relay/httpapi/detail.go:138-150`"),
    26: (4, "retired: server.py's greenlet and OS-thread topology, deleted with apps/proxy/live_proxy/ in stage 2d-4; spec D2 replaces it with goroutines behind a sync.RWMutex and there is no Go code that implements the mechanism this row records"),
    27: (1, "retired: `_execute_redis_command` swallowing every Redis exception to None, deleted with apps/proxy/live_proxy/ in stage 2d-4; spec D2 removes Redis from the live path, so there is no analogous call in the Go relay to cite"),
    28: (3, "`relay/ffmpeg/progress.go:20-40`, `relay/httpapi/detail.go:485-500`, `relay/httpapi/channels.go:85-95`"),
    29: (2, "`relay/channel/source_proxy.go:40-55`, `relay/channel/stats.go:10-25`, `relay/channel/channel.go:120-135`"),
}

# row id -> a sentence appended to the Notes cell, where the Go citation is
# weaker than the Python one it replaces (R11).
NOTES_APPEND = {
    4: (
        " Stage 2d-4 replaced this row's Source with the Go progress parser and buffering "
        "detector, which are where the value is OBSERVED; the cumulative-average behaviour "
        "itself is ffmpeg's and is implemented in neither relay, exactly as this row already "
        "said of the Python code."
    ),
    13: (
        " Stage 2d-4's Source replacement cites the surviving half only -- idempotent "
        "registration. The ghost-sweep half has no Go code to cite, for the reason this row "
        "already gives, and `apps/channels/tests/test_ts_proxy_ghost_clients.py`, named above "
        "as the partial cover, was deleted with the package."
    ),
}

LP_CITATION = re.compile(r"`apps/proxy/live_proxy/[^`]+`")
LP_PIN_REF = re.compile(r"`apps/proxy/live_proxy/tests/[^`]+`")


def cells(line):
    """The five cells of a matrix row line, with their surrounding spaces."""
    parts = line.rstrip("\n").split("|")
    # A row line is "| a | b | c | d | e |": split gives ['', a, b, c, d, e, ''].
    assert len(parts) == 7, f"row has {len(parts) - 2} cells, expected 5: {line!r}"
    return parts


def main():
    text = MATRIX.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    seen = set()
    pin_edits = 0

    for i, line in enumerate(lines):
        if not line.startswith("| "):
            continue
        parts = line.rstrip("\n").split("|")
        if len(parts) != 7:
            continue
        if not parts[1].strip().isdigit():
            continue
        rid = int(parts[1].strip())

        source, pin, notes = parts[3], parts[4], parts[5]
        changed = False

        if rid in SOURCES:
            expected, replacement = SOURCES[rid]
            found = len(LP_CITATION.findall(source))
            assert found == expected, (
                f"row {rid}: Source carries {found} live_proxy citations, "
                f"the plan measured {expected} at the seed"
            )
            assert rid not in seen, f"row {rid} appears twice"
            parts[3] = f" {replacement} "
            seen.add(rid)
            changed = True

        if LP_PIN_REF.search(pin):
            kept = [
                ref
                for ref in re.findall(r"`[^`]+`", pin)
                if not ref.startswith("`apps/proxy/live_proxy/tests/")
            ]
            assert kept, f"row {rid}: dropping the live_proxy pins would leave the cell empty"
            parts[4] = " " + ", ".join(kept) + " "
            pin_edits += 1
            changed = True

        if rid in NOTES_APPEND:
            assert notes.strip(), f"row {rid}: Notes cell is empty, nothing to append to"
            parts[5] = notes.rstrip() + NOTES_APPEND[rid] + " "
            changed = True

        if changed:
            lines[i] = "|".join(parts) + "\n"

    missing = set(SOURCES) - seen
    assert not missing, f"rows named in the plan but not found in the matrix: {sorted(missing)}"

    MATRIX.write_text("".join(lines), encoding="utf-8")
    print(f"ok, {len(seen)} Source cells, {pin_edits} Pin cells, {len(NOTES_APPEND)} Notes cells")


if __name__ == "__main__":
    sys.exit(main())
```

### Appendix F — the `retired:` Source sentinel and its allowlist (R11), Task 10

**Verified this round, which the first draft could not do**: `npx tsc --noEmit` exit 0,
`playwright test --project=guards` 18 passed, and all four break-checks bite — including the
one that answers option (c), where `retired:` on row 1 fails `toEqual` with `[1, 26, 27]`.

```diff
diff --git a/e2e/tests/guards/parity-matrix.spec.ts b/e2e/tests/guards/parity-matrix.spec.ts
index 9922c9d8..9a365207 100644
--- a/e2e/tests/guards/parity-matrix.spec.ts
+++ b/e2e/tests/guards/parity-matrix.spec.ts
@@ -114,11 +114,13 @@ import {
   GO_PARITY_CLOSED,
   goRefs,
   HIGHEST_ROW_ID,
+  isRetiredSource,
   MATRIX_REL,
   parseMatrix,
   parsePin,
   PRS,
   readMatrix,
+  RETIRED_SOURCES,
   WHITE_BOX_ONLY,
   testRefProblem,
 } from './parity-matrix';
@@ -198,12 +200,17 @@ test('every row cites source that resolves', { tag: '@characterization' }, async
   const findings: string[] = [];
 
   for (const row of rows) {
+    // A `retired:` row cites nothing because there is nothing left to cite.
+    // It is not a free pass: the row must be in RETIRED_SOURCES, which the
+    // allowlist test below compares with toEqual.
+    if (isRetiredSource(row.source)) continue;
     const citations = citationsIn(row.source);
     if (citations.length === 0) {
       findings.push(
         `${MATRIX_REL}:${row.line} (row ${row.id}) — Source cell carries no citation. ` +
-          'Every row names the Python source it was derived from, as `path:line` or ' +
-          '`path:start-end` in backticks.',
+          'Every row names the source it was derived from, as `path:line` or ' +
+          '`path:start-end` in backticks, or the `retired: <reason>` sentinel for a ' +
+          'behaviour whose code no longer exists.',
       );
       continue;
     }
@@ -304,6 +311,41 @@ test('white-box-only rows are confined to an allowlist', { tag: '@characterizati
   ).toEqual([]);
 });
 
+test('retired-source rows are confined to an allowlist', { tag: '@characterization' }, async () => {
+  const rows = parseMatrix(await readMatrix());
+
+  const marked = rows.filter((row) => isRetiredSource(row.source));
+  const actual = marked.map((row) => row.id).sort((a, b) => a - b);
+  const allowed = RETIRED_SOURCES.map((row) => row.id).sort((a, b) => a - b);
+
+  // `toEqual`, not `toContain`, for WHITE_BOX_ONLY's reason one level up: the
+  // word `retired:` is the only thing that can make a row stop citing source,
+  // so both adding and removing one must be a deliberate edit in two places.
+  expect(
+    actual,
+    'A row whose Source is `retired:` cites no file, so marking one is a deliberate edit in ' +
+      'two places: the matrix, and RETIRED_SOURCES in e2e/tests/guards/parity-matrix.ts, where ' +
+      'it must carry a `why`. Say in the diff what deleted the code.',
+  ).toEqual(allowed);
+
+  const unjustified = marked
+    .filter((row) => row.notes === '')
+    .map((row) => `${MATRIX_REL}:${row.line} (row ${row.id})`);
+  expect(
+    unjustified,
+    'A retired row must justify itself in its Notes cell, not only in the guard.',
+  ).toEqual([]);
+
+  const unexplained = RETIRED_SOURCES.filter((row) => row.why.trim() === '').map(
+    (row) => `RETIRED_SOURCES[id=${row.id}]`,
+  );
+  expect(
+    unexplained,
+    'Every RETIRED_SOURCES entry must carry a non-empty `why` — the allowlist half of the ' +
+      'justification this test requires from the matrix half above.',
+  ).toEqual([]);
+});
+
 test('Gate 1: the matrix is fully pinned when the flag says so', { tag: '@characterization' }, async () => {
   const rows = parseMatrix(await readMatrix());
   const owed = rows.filter((row) => parsePin(row.pin)?.kind === 'owed');
diff --git a/e2e/tests/guards/parity-matrix.ts b/e2e/tests/guards/parity-matrix.ts
index 6dfd06b7..f26ea912 100644
--- a/e2e/tests/guards/parity-matrix.ts
+++ b/e2e/tests/guards/parity-matrix.ts
@@ -510,6 +510,49 @@ export async function testRefProblem(ref: TestRef): Promise<string | undefined>
 
 export type WhiteBoxRow = { id: number; why: string };
 
+/** The `retired:` Source sentinel, matched on the whole trimmed cell. */
+const RETIRED_SOURCE = /^retired:\s*\S/;
+
+/** True when a row's Source cell is the retired sentinel rather than citations. */
+export function isRetiredSource(source: string): boolean {
+  return RETIRED_SOURCE.test(source.trim());
+}
+
+/**
+ * Rows whose Source is `retired:` — the behaviour was deleted, not ported, so
+ * there is no file in the tree to cite.
+ *
+ * Compared with `toEqual`, in WHITE_BOX_ONLY's idiom and for exactly its
+ * reason. `retired:` is a second word that can make an inconvenient row stop
+ * being checked, and the objection to simply exempting white-box rows from the
+ * Source check was that such an exemption is retroactive and silent: every
+ * future white-box row would stop needing a citation with no edit anywhere to
+ * notice. This list is the answer to that objection rather than a way around
+ * it — the word is counted, and adding one is two deliberate edits.
+ *
+ * Note these are NOT required to be white-box rows. 26 and 27 happen to be
+ * both, but the two properties are independent: `white-box-only` says no
+ * client can observe the behaviour, `retired:` says the code that produced it
+ * is gone. Row 12's fMP4 timeout is close to the first and very much alive in
+ * Go.
+ */
+export const RETIRED_SOURCES: readonly WhiteBoxRow[] = [
+  {
+    id: 26,
+    why:
+      "server.py's greenlet and OS-thread topology went with apps/proxy/live_proxy/ in Phase 2 " +
+      'stage 2d-4. Spec D2 replaces it with goroutines behind a sync.RWMutex, so no Go file ' +
+      'implements the mechanism this row records and none can honestly be cited as its source.',
+  },
+  {
+    id: 27,
+    why:
+      '_execute_redis_command went with the package in stage 2d-4. D2 removes Redis from the ' +
+      'live path entirely, so there is no analogous call in the Go relay -- citing one would ' +
+      'invert what the Source column means.',
+  },
+];
+
 /**
  * Rows no test can pin, because no client can observe them.
  *
```

### Appendix J.1 — `metrics/curated/defects.yml` (R14), Task 11

**Verified**: `python -m metrics.build --validate-only` → `ok: 46 metrics, 36 milestones, 32 defects`.

```diff
diff --git a/metrics/curated/defects.yml b/metrics/curated/defects.yml
index 837b7539..c96f921b 100644
--- a/metrics/curated/defects.yml
+++ b/metrics/curated/defects.yml
@@ -18,8 +18,8 @@
 - {id: xc-account-enumeration, title: "player_api.php distinguishes an unknown username (404) from a wrong password (401)", area: security, severity: medium, status: pinned, source: null, issue: 84, test: e2e/tests/seeded/xc-auth.spec.ts, fixed_in: null, carried_as: null, first_seen: 2026-08-30, status_changed: 2026-08-30}
 - {id: m3u-unescaped-quote, title: "Unescaped double quote in tvg-name/group-title breaks the EXTINF line", area: correctness, severity: medium, status: pinned, source: null, issue: 80, test: e2e/tests/seeded/output-m3u.spec.ts, fixed_in: null, carried_as: null, first_seen: 2026-08-30, status_changed: 2026-08-30}
 - {id: channel-stopping-ttl-race, title: "Channel-stopping key written with 60s TTL on five paths and 30s on three", area: correctness, severity: medium, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-22}
-- {id: max-stream-switches-unbounded, title: "MAX_STREAM_SWITCHES does not bound buffering-triggered switches", area: correctness, severity: medium, status: pinned, source: "CLAUDE.md#known-defects-and-traps", issue: 221, test: apps/proxy/live_proxy/tests/test_manager_stderr_failover.py, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-09-10}
-- {id: fmp4-timeout-no-switch-exemption, title: "fMP4 generator's _is_timeout lacks the TS generator's url_switching exemption", area: correctness, severity: medium, status: pinned, source: "CLAUDE.md#known-defects-and-traps", issue: 222, test: apps/proxy/live_proxy/tests/test_fmp4_client_timeout.py, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-09-10}
+- {id: max-stream-switches-unbounded, title: "MAX_STREAM_SWITCHES does not bound buffering-triggered switches", area: correctness, severity: medium, status: pinned, source: "CLAUDE.md#known-defects-and-traps", issue: 221, test: relay/channel/source_transcode_test.go, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-09-10}
+- {id: fmp4-timeout-no-switch-exemption, title: "fMP4 generator's _is_timeout lacks the TS generator's url_switching exemption", area: correctness, severity: medium, status: pinned, source: "CLAUDE.md#known-defects-and-traps", issue: 222, test: relay/httpapi/fmp4_test.go, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-09-10}
 - {id: read-only-fields-misplaced, title: "read_only_fields on the serializer class instead of Meta: M3UAccount.locked is writable over the API", area: correctness, severity: low, status: open, source: null, issue: 15, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-24, status_changed: 2026-08-24}
 - {id: interval-schedule-create-race, title: "M3U/EPG source creation 500s permanently after a concurrent-create race duplicates an IntervalSchedule", area: correctness, severity: high, status: open, source: null, issue: 7, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-24, status_changed: 2026-08-24}
 - {id: hls-proxy-dead, title: "apps/proxy/hls_proxy (1,206 lines) is dead: no HLS output exists", area: dead-code, severity: low, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: null, test: null, fixed_in: null, carried_as: null, first_seen: 2026-08-22, status_changed: 2026-08-22}
@@ -29,7 +29,7 @@
 - {id: xc-vod-wrong-password-nameerror, title: "stream_xc_movie/stream_xc_episode answer 500 on a wrong XC password: the rejection branch calls an unimported Response", area: correctness, severity: medium, status: fixed, source: null, issue: 100, test: e2e/tests/streaming/xc-vod-playback.spec.ts, fixed_in: 176, carried_as: null, first_seen: 2026-09-01, status_changed: 2026-09-05}
 - {id: release-stream-relay-key-fallback, title: "A control-plane write to the relay metadata hash on every successful Channel.release_stream(), plus two fallback-path reads (release_stream()'s recovery branch and _release_stale_stream_assignment())", area: correctness, severity: low, status: open, source: "CLAUDE.md#known-defects-and-traps", issue: 190, test: null, fixed_in: null, carried_as: null, first_seen: 2026-09-06, status_changed: 2026-09-06}
 - {id: ffmpeg-unrunnable-without-ld-library-path, title: "ffmpeg is installed but unrunnable wherever docker/entrypoint.sh has not exported LD_LIBRARY_PATH: two librist in the image and ld.so.conf ordering picks the wrong one", area: operational, severity: low, status: open, source: null, issue: 226, test: null, fixed_in: null, carried_as: null, first_seen: 2026-09-10, status_changed: 2026-09-10}
-- {id: ffmpeg-speed-scientific-notation, title: "ffmpeg_speed is parsed with [0-9.]+, which stops at the e of a scientific-notation speed=, so a real speed=1.41e+03x is reported as 1.41", area: correctness, severity: low, status: pinned, source: null, issue: 227, test: apps/proxy/live_proxy/tests/test_manager_stderr_failover.py, fixed_in: null, carried_as: null, first_seen: 2026-09-10, status_changed: 2026-09-10}
+- {id: ffmpeg-speed-scientific-notation, title: "ffmpeg_speed is parsed with [0-9.]+, which stops at the e of a scientific-notation speed=, so a real speed=1.41e+03x is reported as 1.41", area: correctness, severity: low, status: pinned, source: null, issue: 227, test: relay/ffmpeg/progress_test.go, fixed_in: null, carried_as: null, first_seen: 2026-09-10, status_changed: 2026-09-10}
 - {id: proxy-settings-cache-cleared-on-wrong-class, title: "CoreSettings' post_save receiver calls BaseConfig.clear_proxy_settings_cache(), which never clears the TSConfig attribute every relay reader populates, so a proxy_settings change is invisible to every process until the 10-second TTL expires", area: correctness, severity: medium, status: open, source: null, issue: 232, test: null, fixed_in: null, carried_as: null, first_seen: 2026-09-10, status_changed: 2026-09-10}
 - {id: fmp4-bsf-retry-dead-branch, title: "FMP4RemuxManager._handle_bsf_error sets self.running = True then immediately tests `if not self.running:`, so the stop()-during-restart cleanup branch can never execute", area: dead-code, severity: low, status: open, source: null, issue: 244, test: null, fixed_in: null, carried_as: null, first_seen: 2026-09-10, status_changed: 2026-09-10}
 - {id: coverage-isolated-label-set-e-voids-round, title: "coverage_live_path_isolated.sh's set -e loop aborted the whole census round on the first failing label, with no measurement and no indication which label died -- closed once by a docs PR that only described the fix via keyword-matching, before any code changed", area: correctness, severity: low, status: fixed, source: null, issue: 266, test: null, fixed_in: 275, carried_as: null, first_seen: 2026-09-12, status_changed: 2026-09-13}
```

### Appendix J.2 — `e2e/COVERAGE.md` (R18), Task 11

Four rows, seven mentions. `:202` is deliberately left, with `:50` — A10.10's own table
assigns both to 2d-6, and Task 11 Step 5 expects exactly one survivor for that reason.

```diff
diff --git a/e2e/COVERAGE.md b/e2e/COVERAGE.md
index 869729a2..badc8327 100644
--- a/e2e/COVERAGE.md
+++ b/e2e/COVERAGE.md
@@ -187,10 +187,10 @@ resolve (see the G8/G10 Gap rows).
 | Harness | **Observation:** four WebSocket handler/sender pairs are dead in one direction or the other. `frontend/src/WebSocket.jsx` has `case` handlers for `epg_file`, `epg_channels` and `epg_sources_changed` that no backend `send_websocket_update` call anywhere under `apps/` ever sends; conversely `apps/channels/tasks.py` sends `epg_tvg_id_setting_progress` (pinned by `epg-field-copy.spec.ts` test 13) with no matching `case` in `WebSocket.jsx`, which handles the sibling `epg_name_setting_progress` but not this one — so a browser client with that panel open never sees the progress the API already reports | G14 | done |
 | Sources | **Observation:** `apps/channels/tests/test_epg_matching.py` (the backend unit suite) does not test `epg_matching.py` — its name suggests coverage this goal's own `epg-matching.spec.ts` is the first to actually provide for the fuzzy/exact-match code paths | G14 | done |
 | Sources | **Observation, not testable without the ML band:** `match_channels_to_epg` derives `is_bulk_matching = len(channels_data) > 1`, so a one-element collection call runs the *single*-channel thresholds, while `run_single_channel_epg_match` hardcodes `is_bulk_matching=False` unconditionally — the two code paths can disagree on a one-channel call depending on which one handled it. Any bulk-path score in `[50, 80)` reaches `get_sentence_transformer()`, so showing the disagreement needs a pair inside that band — squarely the ML band this goal forbids entering. A test for it was specified (would have been test 9) and cut for that reason before implementation | G14 | done |
-| Streaming | **Observation:** the `channel_stats` beat entry ships disabled. `dispatcharr/settings.py`'s `CELERY_BEAT_SCHEDULE["fetch-channel-statuses"]` (`apps.proxy.tasks.fetch_channel_stats`) is `enabled: False`, and `core/tasks.py:beat_periodic_task` is referenced by no schedule or migration — unreachable on a stock instance. `channel_stats` is emitted only request/event-driven: the bare admin `GET /proxy/ts/status` (`apps/proxy/live_proxy/views.py`, emits even with zero channels) and `client_manager.py:_trigger_stats_update` on client connect/disconnect. So an idle instance is silent, contradicting the spec's own Facts table, which carried forward `e2e/fixtures/ws.ts:86`'s doc comment ("a socket on a live instance sees `channel_stats` roughly once a second") as though it applied to this idle project — the root `CLAUDE.md` makes no such once-a-second claim and already describes the poll-driven, event-side-effect emission this row confirms. `ws-product-events.spec.ts` test 15 drives the emission itself by polling `/proxy/ts/status` rather than relying on ambient traffic | G14 | done |
+| Streaming | **Observation:** the `channel_stats` beat entry ships disabled. `apps/proxy/tasks.py`'s `fetch_channel_stats` and the disabled `CELERY_BEAT_SCHEDULE["fetch-channel-statuses"]` entry that named it were both deleted by Phase 2 stage 2d-4 (its builder scanned `live:channel:*:metadata`, keys the Go relay never writes); `core/tasks.py`'s same-named function survives and asks the relay over HTTP. Historically the entry is `enabled: False`, and `core/tasks.py:beat_periodic_task` is referenced by no schedule or migration — unreachable on a stock instance. `channel_stats` is emitted only request/event-driven: the bare admin `GET /proxy/ts/status` (`apps/proxy/ts_admin_views.py`, emits even with zero channels) and, before Phase 2 stage 2d-4, the Python relay's `client_manager.py:_trigger_stats_update` on client connect/disconnect. So an idle instance is silent, contradicting the spec's own Facts table, which carried forward `e2e/fixtures/ws.ts:86`'s doc comment ("a socket on a live instance sees `channel_stats` roughly once a second") as though it applied to this idle project — the root `CLAUDE.md` makes no such once-a-second claim and already describes the poll-driven, event-side-effect emission this row confirms. `ws-product-events.spec.ts` test 15 drives the emission itself by polling `/proxy/ts/status` rather than relying on ambient traffic | G14 | done |
 | Sources | **Not reproduced:** [#72](https://github.com/D10Scot/Dispatcharr/issues/72) (`ChannelProfileMembership` unique-constraint race between `create_profile_memberships`'s `post_save` receiver and `ChannelViewSet.create`'s no-`channel_profile_ids` path, both unguarded `bulk_create`s) is not provoked by `channel-bulk-ops.spec.ts`: this file creates channels, never concurrently with a profile-membership operation, because a reproduction that fails to fire is a green test proving nothing, and one that succeeds leaves a partially-populated membership set on a shared instance (D18). [#86](https://github.com/D10Scot/Dispatcharr/issues/86) — an intermittent failure in G3's `channel-profiles.spec.ts` under four-worker load, observed three times and never diagnosed — is the same shape as #72's hypothesis and is recorded here as its likely symptom, not proof of mechanism | G14 | todo |
-| Accounts | **Gap, unowned:** every global `CoreSettings` group with a behavioural effect beyond G14's one exception (`network_access["XC_API"]`, restored in `afterEach`) is unexercised: `epg_settings.epg_match_mode` advanced normalisation, `stream_settings.default_user_agent`, `system_settings.preferred_region` (see the characterized-defect row above), and every `network_access` scope this goal didn't touch — each an instance-wide write four uWSGI workers share. Precedent that a scoped, single-worker test of a global row is possible: `proxy_settings` and `stream_settings.default_stream_profile` are already exercised from single-worker `streaming-failover`/`streaming-greybox` projects. Named explicitly: `network_access["STREAMS"]` is the only ACL on `/proxy/ts/stream/<uuid>` (`apps/proxy/live_proxy/views.py:stream_ts` calls `network_access_allowed(request, "STREAMS")` with no user) — the endpoint the relay extraction moves, and the one `CLAUDE.md` says becomes a Django-minted HMAC-signed URL. This row was handed to G12 in the original spec and G12 declined it, so it is unowned rather than assigned to a named goal | G14 | todo |
-| Streaming | **Gap:** the per-user `allowed_networks["STREAMS"]` branch is a cheaper observable for the same scope as the row above, needing no global write: `apps/proxy/live_proxy/views.py:stream_xc` passes `user` to `network_access_allowed`, so pointing one seeded user's `custom_properties.allowed_networks.STREAMS` at a CIDR no client can match makes the XC live route refuse, row-scoped and reversible — the same shape `network-acl.spec.ts` test 4 already proves for `XC_API`. It is a `streaming`-project test (needs a byte-level client), so this row is for whichever goal next owns those projects | G14 | todo |
+| Accounts | **Gap, unowned:** every global `CoreSettings` group with a behavioural effect beyond G14's one exception (`network_access["XC_API"]`, restored in `afterEach`) is unexercised: `epg_settings.epg_match_mode` advanced normalisation, `stream_settings.default_user_agent`, `system_settings.preferred_region` (see the characterized-defect row above), and every `network_access` scope this goal didn't touch — each an instance-wide write four uWSGI workers share. Precedent that a scoped, single-worker test of a global row is possible: `proxy_settings` and `stream_settings.default_stream_profile` are already exercised from single-worker `streaming-failover`/`streaming-greybox` projects. Named explicitly: `network_access["STREAMS"]` is the only ACL on `/proxy/ts/stream/<uuid>` (`apps/proxy/authorize.py`'s `authorize_stream` calls `network_access_allowed(request, "STREAMS")` with no user) — the endpoint the relay extraction moves, and the one `CLAUDE.md` says becomes a Django-minted HMAC-signed URL. This row was handed to G12 in the original spec and G12 declined it, so it is unowned rather than assigned to a named goal | G14 | todo |
+| Streaming | **Gap:** the per-user `allowed_networks["STREAMS"]` branch is a cheaper observable for the same scope as the row above, needing no global write: the XC live root passes `user` to `network_access_allowed` (`apps/proxy/authorize.py`'s `authorize_stream`, reached by nginx `auth_request`), so pointing one seeded user's `custom_properties.allowed_networks.STREAMS` at a CIDR no client can match makes the XC live route refuse, row-scoped and reversible — the same shape `network-acl.spec.ts` test 4 already proves for `XC_API`. It is a `streaming`-project test (needs a byte-level client), so this row is for whichever goal next owns those projects | G14 | todo |
 | Streaming | Authorize hop: `hidden_from_output` refuses an anonymous UUID tune on `/proxy/ts/stream/`, still refuses a forged `X-Dispatcharr-Authorized`/`X-Relay-*`, and refuses on `/proxy/catchup/` and the XC live root, while an ordinary channel still streams with no credential at all; `is_adult` against a `hide_adult_content` viewer refuses on both native routes (`/proxy/ts/stream/`, `/proxy/catchup/`) and both XC roots (live, timeshift) ([#87](https://github.com/D10Scot/Dispatcharr/issues/87), [#95](https://github.com/D10Scot/Dispatcharr/issues/95)) | P1 | done |
 | Streaming | Relay events: a `dead-air` failover posts `stream_switch` to `/api/relay/events` (not `channel_failover` — that type is reachable only from the ffmpeg buffering-timeout path, structurally dead for the Proxy profile this test locks), Django writes the `SystemEvent` row that `GET /api/core/system-events/` returns, and pushes a `relay_event` WebSocket message whose payload carries the channel uuid and no provider URL | P1 | done |
 | Streaming | Relay control API: `^~ /proxy/relay/` reaches the relay (`uwsgi_pass relay_py`), is not `internal;` so Django can dial it as an ordinary client from the worker role and through the api role's own nginx, runs no `auth_request` because the internal token is the whole gate, still blanks the four `X-Relay-*` params and the `X-Dispatcharr-Authorized` marker, and carries a read timeout above the 15s the owner-confirmation poll can take | P1 | done |
@@ -200,7 +200,7 @@ resolve (see the G8/G10 Gap rows).
 | Lifecycle | Bounded relay restart: `supervisorctl restart relay-uwsgi` returns the relay to RUNNING and it serves a fresh tune with aligned TS **7559ms** after the restart command was issued, inside the 30s ceiling that `stopwaitsecs=20` plus `startsecs=5` has to fit within. An M3U refresh dispatched immediately before the restart still completes afterwards (`updated_at` bumped, status `success`) — the Celery broker and result backend live in the same Redis DB 0 as the relay's channel state, so a blind flush on a start path would take all three. `tests/streaming-split/process-restart.spec.ts` | P1 | done |
 | Lifecycle | Modular role split: `api`, `relay` and `worker` containers on one network, with TS bytes read through the `api` container's nginx and the relay reached across the compose network. The only test of the cross-container relay hop in either direction — `scripts/e2e_up.sh` is AIO-only — and therefore the only place a `DISPATCHARR_WEB_HOST` that Django's `get_host()` rejects (an underscore in a container name) would surface. `docker/tests/test-puid-pgid.sh`'s `test_role_split`, run by `lifecycle-tests.yml`'s `suites` job in full mode. The same scenario, not a second one: the bash-suite bullet list below already names it as "the programme's only cross-container relay scenario"; this row is the flow entry it never got | P1 | done |
 | Streaming | **Open question (found by the bounded-restart test):** the code reads as if a viewer reconnecting to the **same** channel after a relay restart can only be cleared by `_check_orphaned_metadata`'s 30s sweep, not by the restart's own bound. `_channel_setup_needed` (`apps/proxy/live_proxy/views.py`) returns "no setup needed" for a channel whose metadata still says `active` and never consults the dead owner's `live:worker:<id>:heartbeat` — the zombie check in `ProxyServer.check_if_channel_exists` sits behind that early return and is unreachable from the tune path — so the reconnecting client would attach as a follower to a channel nobody owns until the sweep runs, and the sweep declines to clean a channel that still has a live client, exactly what a retrying reconnect keeps supplying. A single hand measurement came in at **≤17s** to 1880 delivered bytes (rather than a 200 with nothing, what a follower on an ownerless channel answers) — under both the 30s sweep this reading names as the only thing that can clear the state and the 30s restart ceiling. Its clock starts before the blocking restart call, the same origin as the bounded-restart figure above, and up to 10s of the measuring probe's own timeout can only make the number look slower than the true first byte, never faster. So either the mechanism does not bite the way the code reads, or the sweep ran early on this run. The test tunes a channel that was *not* running when the relay went away, and this is filed as an open question ([#195](https://github.com/D10Scot/Dispatcharr/issues/195)) rather than asserted as a defect | P1 | todo |
-| Sources | **Gap:** `M3UAccountProfile.search_pattern`/`replace_pattern` URL rewriting is unproven, naming `apps/proxy/live_proxy/url_utils.py:transform_url` as the mechanism and the provider's `ScenarioLog` as the observable — cut before this goal started | G14 | todo |
+| Sources | **Gap:** `M3UAccountProfile.search_pattern`/`replace_pattern` URL rewriting is unproven, naming `apps/proxy/next_source.py:transform_url` as the mechanism and the provider's `ScenarioLog` as the observable — cut before this goal started | G14 | todo |
 | Sources | **Gap:** `ServerGroup` credential pooling is unproven, naming `apps/m3u/connection_pool.py:group_has_capacity_for_profile` and the two-account, two-stream setup it needs — cut before this goal started, cross-referencing [#68](https://github.com/D10Scot/Dispatcharr/issues/68) | G14 | todo |
 | Upstream | **Gap, `e2e-upstream`'s scope:** the provider's `ScenarioLog` records `method`, `path` and `status` but no request headers (`e2e-upstream/src/server.ts:logRequest`), so nothing Dispatcharr sends upstream as a `User-Agent` — including `stream_settings.default_user_agent`, the unowned-`CoreSettings` gap above — is observable through it. Closing it is one field on the log entry | G14 | todo |
 | Sources | **Gap:** the bulk-path fuzzy "no match" characterization test (would have been test 8) was implemented, its own assertions and the file's typecheck passed, and it was cut before shipping — see `epg-matching.spec.ts`'s header. Mechanism: `_active_epg_fuzzy_queryset` admits every active source's `EPGData` with no scoping to the test's own source; two `seed.channel()`/`seed.generatedName('epg')`-shaped names (worker/run/test-id digits, stripped to nothing by `normalize_name`) share enough character-level structure to land inside the bulk path's `[50, 80)` ML band by coincidence — measured at fuzzy 56.91 against a leftover row from an unrelated `epg-ingest.spec.ts` run — triggering `get_sentence_transformer()` and a real ~88 MB model download, then matching the two unrelated generated names via the ML "desperate last resort" branch at cosine 0.91 (the aggressive-ML finding, folded in here rather than filed separately). The test's own ws-based settle signal also resolved before the ML-delayed match actually committed — a second, independent defect in the test design, not just in the pair choice. What a future owner needs: a fixture-scoped way to deactivate other sources during the test, or a dedicated single-worker project. G14's own shipped tests 6, 7, 10, 11, 12 and 13 each leave behind an active upstream EPG source with a generated-shape `EPGData` name of exactly this kind — six more candidates per run for the next test that lands in this band by coincidence, not just the one leftover row measured above | G14 | todo |
```

### Appendix K — `CLAUDE.md` (R15), Task 12

**Nineteen** replacements. Takes the measured label count, backend test count and suite wall
time as **arguments**, because every predecessor plan that baked a measured number into an
appendix shipped a stale one. Prints `ok, 19 edits`.

```python
#!/usr/bin/env python3
"""Appendix K -- CLAUDE.md, the eleven passages 2d-4 makes FALSE.

Run from the repository root:

    python3 appK_claudemd.py <label-count> <backend-test-count> <suite-seconds>

Verbatim-string replacement with `assert count == 1` on every anchor, not
line-anchored hunks: stage 2d-3 moved every line number in this file, and a
diff would go stale between this plan being written and being run.

The rule applied (ruling R15) is narrow: a sentence this PR makes FALSE is
corrected here; a sentence that merely describes apps/proxy/live_proxy/ as
existing is 2d-6's consolidation pass. The measured numbers are ARGUMENTS
rather than literals, because every predecessor plan that baked a measured
number into an appendix shipped a stale one.
"""
import pathlib
import sys

edits = 0


def sub(old, new, path=pathlib.Path("CLAUDE.md")):
    global edits
    t = path.read_text(encoding="utf-8")
    n = t.count(old)
    assert n == 1, f"anchor matched {n} times, expected 1:\n---\n{old[:200]!r}"
    path.write_text(t.replace(old, new), encoding="utf-8")
    edits += 1


def main(labels, tests, seconds):
    # 1 -- section Test hooks, the boot-check bullet.
    sub(
        "Phase 2 stage 2d-1 moved those two out of `live_proxy/` into `apps/proxy/redis_keys.py` "
        "and `apps/proxy/constants.py` — **the arm moved with them, and the three old paths stay "
        "in it until 2d-4 deletes the package**, because they are still re-export shims every "
        "relay module imports.",
        "Phase 2 stage 2d-1 moved those two out of `live_proxy/` into `apps/proxy/redis_keys.py` "
        "and `apps/proxy/constants.py`, and the arm moved with them; stage 2d-4 deleted the three "
        "`live_proxy/` re-export shims that stood beside them, with the package, so the arm is "
        "three literal paths rather than six. `apps/proxy/config_helper.py` is in it although "
        "`apps/channels/models.py` imports neither it nor `constants.py` any more: "
        "`apps/timeshift/views.py` imports both at module level and the urlconf is loaded by "
        "`manage.py check`.",
    )

    # 2 -- the PreToolUse commit-gate baseline.
    sub(
        "Baseline **16/16** backend packages pass (2,212 tests, 28.5s).",
        f"Baseline **{labels}/{labels}** backend packages pass ({tests} tests, {seconds}s) — "
        "Phase 2 stage 2d-4 deleted `apps.proxy.live_proxy.tests` with the package.",
    )

    # 3 -- section Testing, the label count.
    sub(
        "(AST-parses `INSTALLED_APPS`). 16 labels; 2,212 backend tests, 6,134 frontend tests.",
        f"(AST-parses `INSTALLED_APPS`). {labels} labels; {tests} backend tests, 6,134 frontend "
        "tests.",
    )

    # 4 -- section Testing, the _PATH_ALIASES paragraph.
    sub(
        "`apps/proxy/live_proxy/` to both `apps.proxy.live_proxy.tests` and `apps.channels.tests` "
        "(whose `tests/test_ts_proxy_teardown.py` builds a real `ProxyServer` ten times), and "
        "`scripts/coverage_live_path` (no trailing slash — it matches the script, the rcfile, the "
        "floor and the floor companion, none of which sit under an app's own filesystem prefix) "
        "to Gate 2's own three labels,",
        "and `scripts/coverage_live_path` (no trailing slash — it matches the script, the rcfile, "
        "the floor and the floor companion, none of which sit under an app's own filesystem "
        "prefix) to Gate 2's own two labels (the `apps/proxy/live_proxy/` alias went with the "
        "directory at stage 2d-4),",
    )

    # 5 -- section Testing, Gate 2's scope.
    sub(
        "`scripts/coverage_live_path.sh` measures statement coverage over "
        "`apps/proxy/live_proxy/**` plus the ten Phase 1 boundary modules — a 38-file module list "
        "`scripts/coverage_live_path.coveragerc` fixes (currently 7,978 statements, a figure the "
        "gate records but does not enforce — see below)",
        "`scripts/coverage_live_path.sh` measures statement coverage over the **nine** surviving "
        "Phase 1 boundary modules — `scripts/coverage_live_path.coveragerc` fixes the list, which "
        "stage 2d-4 took from 38 files to 9 by deleting `apps/proxy/live_proxy/**` and "
        "`relay_views.py`. **Between 2d-4 and 2d-5 the floor's `missing` is deliberately slack**: "
        "2d-4 shipped `--write-floor --shape-only`, which rewrites the shape hashes and never "
        "touches `missing`, so 1525 is still the figure the pre-delete tree earned over a "
        "denominator roughly a tenth its size. `migration/phase2d-gate2-recensus` carries the "
        "≥12-round CI census that makes it real",
    )

    # 5b -- the same paragraph's routing sentence.
    sub(
        "`scripts/coverage_live_path*` is routed to Gate 2's own three labels in "
        "`dispatcharr/test_discovery.py`'s `_PATH_ALIASES`,",
        "`scripts/coverage_live_path*` is routed to Gate 2's own two labels in "
        "`dispatcharr/test_discovery.py`'s `_PATH_ALIASES`,",
    )

    # 6 -- section Testing, Gate 1.
    sub(
        "**Gate 1 is closed.** `apps/proxy/live_proxy/tests/test_zero_orm_reads.py` holds the "
        "relay to `zero_orm_allowlist.py` two ways — an AST scan of the package and its "
        "in-process import edges, and a runtime record of every SQL statement five real drives "
        "execute, attributed to the relay by stack frame. **The static half is a ratchet, not a "
        "proof**: it cannot see a property that queries, a `getattr` dispatch, or an ORM read "
        "more than one import hop out of the package, so a green static run is never evidence of "
        "zero ORM reads — the runtime half carries that.",
        "**Gate 1 was closed, and stage 2d-4 RETIRED it rather than meeting it.** "
        "`test_zero_orm_reads.py` and `zero_orm_allowlist.py` lived inside "
        "`apps/proxy/live_proxy/` and went with it. What \"the relay performs zero ORM reads\" "
        "means now is `scripts/check_go_stdlib_only.sh` plus the empty `go.sum`: the Go binary "
        "links no Postgres driver, so the property is structural rather than asserted — strictly "
        "stronger for the relay itself. **What is lost is not about the relay**: the scanner's "
        "scope-2 walk also ratcheted four surviving modules, and `apps/proxy/config.py` carried "
        "five of its twelve edges while being in neither gate afterwards — the most-edged module "
        "in that walk lost its ORM ratchet and has no coverage floor over it at the same moment. "
        "Recorded as a gap, deliberately not replaced in 2d (spec A10.8): a Django-side guard "
        "with a new allowlist in a new home is real work unrelated to the cutover, and it is on "
        "the post-2d list beside the coverage re-scope.",
    )

    # 7 -- section Testing, the subprocess harness.
    sub(
        "**The backend suite can now spawn a subprocess** — `apps/proxy/live_proxy/tests/harness/` "
        "(Phase 2 PR 2a-2) drives the relay's unmodified `os.posix_spawn` call sites against a "
        "scripted stand-in reached through a `StreamProfile` row and `PATH`, with real ffmpeg "
        "reserved for the tests that need a real remuxer's bytes;",
        "The subprocess harness that made the backend suite able to spawn a process — "
        "`apps/proxy/live_proxy/tests/harness/` (Phase 2 PR 2a-2) — went with the package at "
        "stage 2d-4; `relay/internal/relaytest` is its surviving counterpart, and the captured "
        "real-ffmpeg stderr corpus moved into `relay/internal/relaytest/testdata/ffmpeg_stderr/` "
        "with `CAPTURE.md`.",
    )

    # 8 -- section Testing, the relaytest digest sentence.
    sub(
        "`relay/internal/relaytest` is the Go suite's counterpart to "
        "`apps/proxy/live_proxy/tests/harness/`, its synthetic TS asset byte-identical to "
        "`harness/asset.py`'s and pinned to it by a SHA-256 digest, so the two implementations "
        "can be driven from the same bytes.",
        "`relay/internal/relaytest`'s synthetic TS asset was pinned byte-for-byte to "
        "`harness/asset.py`'s by a SHA-256 digest until stage 2d-4, which deleted the pin with "
        "its own stated reason: with one implementation left it proved only that `SyntheticTS` is "
        "deterministic, which is the hollow shape it was written to avoid. The asset's packet "
        "count and size survive as a shape assertion, and the two `upstream.py` constants survive "
        "re-anchored on their derivations (2 Mbit/s, fifty TS packets) rather than on a deleted "
        "file.",
    )

    # 9 -- section Architecture, the ownership paragraph.
    sub(
        "One uWSGI worker owns a channel's upstream, elected by "
        '`redis.set("live:channel:{id}:owner", worker_id, nx=True, ex=30)` (`live_proxy/server.py`);',
        "Until Phase 2 stage 2d-4 one uWSGI worker owned a channel's upstream, elected by "
        '`redis.set("live:channel:{id}:owner", worker_id, nx=True, ex=30)` in `live_proxy/server.py` '
        "— a file that no longer exists. The Go relay is one process with one in-memory registry "
        "(spec D2) and there is no lease. The paragraph below describes the deleted Python design, "
        "kept until 2d-6 rewrites this section because the VOD and catch-up surfaces still read the "
        "same Redis shapes:",
    )

    # 10 -- section Known defects, the fail-open bullet (parity-matrix row 27's last
    # surviving external description).
    sub(
        "The lease **fails open** three ways (`live_proxy/server.py` and "
        "`_execute_redis_command` swallowing exceptions to `None`); `release_ownership` is "
        "GET→compare→DELETE, `extend_ownership` GET→EXPIRE, both non-atomic. **If you carry this "
        "design forward: lease token in the write path via Lua, never fail open.**",
        "The lease **failed open** three ways (`live_proxy/server.py` and "
        "`_execute_redis_command` swallowing exceptions to `None`); `release_ownership` was "
        "GET→compare→DELETE, `extend_ownership` GET→EXPIRE, both non-atomic. **Phase 2 stage 2d-4 "
        "deleted all of it with the package** — the defect is retired by elimination, not fixed, "
        "and parity-matrix row 27 carries it with the `retired:` Source sentinel. **If you carry "
        "this design forward anywhere: lease token in the write path via Lua, never fail open.**",
    )

    # 11 -- section Known defects, #190.
    sub(
        "- **A control-plane write to the relay metadata hash on every successful "
        "`Channel.release_stream()`, plus two fallback-path reads**",
        "- **#190 is closed by deletion.** Stage 2d-4 removed all five of its ranges from "
        "`apps/channels/models.py` — three reads and two `hdel`s against "
        "`live:channel:<uuid>:metadata`, a key the Go relay never writes, so every read had "
        "returned `None` and every `hdel` had been a no-op since the 2d-3 cutover. What it "
        "described, for the record: **a control-plane write to the relay metadata hash on every "
        "successful `Channel.release_stream()`, plus THREE fallback-path reads**",
    )

    # 12 -- section Test hooks' blocking list, which still names the three
    # live_proxy shims and so CONTRADICTS edit 1 three lines later.
    sub(
        "`apps/proxy/{constants,redis_keys,config_helper}.py` and their three `live_proxy/` "
        "re-export shims (`manage.py check`)",
        "`apps/proxy/{constants,redis_keys,config_helper}.py` (`manage.py check`)",
    )

    # 13 -- section Testing, go-tests.yml's differential job, which R13 deletes.
    sub(
        "**Since 2c-9 it also carries the Go coverage ratchet and the cross-implementation "
        "differential**, both in `Go result`'s `needs`.",
        "**Since 2c-9 it also carries the Go coverage ratchet**, in `Go result`'s `needs`. The "
        "cross-implementation differential sat beside it until Phase 2 stage 2d-4 deleted the "
        "job with the Python relay: what it proved, two implementations agreeing byte for byte, "
        "has no meaning once there is one, and the Go-binary-against-real-Django integration it "
        "incidentally provided is what the E2E suite has done through nginx since 2d-3.",
    )
    sub(
        "The **differential** job is the only one that builds `relay-go` and boots Postgres and "
        "Redis together; it runs `apps/proxy/live_proxy/tests/test_relay_differential.py`, which "
        "starts the Go binary against the test's own `LiveServerTestCase` Django and compares "
        "what both relays deliver from one `FakeUpstream` — and which SKIPS in every other run "
        "of that label, deterministically, because `DISPATCHARR_RELAY_GO_BIN` is unset there, so "
        "Gate 2's Python census is unperturbed. ",
        "",
    )

    # 14 -- section Structural constraints: models.py imports one name now, not
    # two, and the shims are gone rather than pending.
    sub(
        "`apps/channels/models.py:6–7` imports `RedisKeys` and `ChannelMetadataField` at "
        "**module level**",
        "`apps/channels/models.py:6` imports `RedisKeys` at **module level** (stage 2d-4 deleted "
        "the `ChannelMetadataField` import with issue #190's five ranges)",
    )
    sub(
        "The three old paths stay as re-export shims until 2d-4, so every module inside the "
        "package and the seven test files outside it that name one of them keep working "
        "unedited.",
        "The three old paths were re-export shims until stage 2d-4 deleted them with the "
        "package.",
    )

    # 15 -- section Routing: live_proxy/urls.py no longer exists.
    sub(
        "and `apps/proxy/live_proxy/urls.py` registers only `stream/`;",
        "and `apps/proxy/stream_routes.py` registers only `stream/` — kept, with both XC live "
        "patterns, because `apps/proxy/authorize_views.py`'s `_surface_for()` resolves the tune "
        "URI through Django's own urlconf and keys on the view's `__name__`, so deleting them "
        "would 403 every live tune behind nginx;",
    )

    # 16 -- the same bullet's opening clause: models.py imports ONE leaf module
    # now, so "two" contradicts edit 14 and the tail of edit 1.
    sub(
        "- The boot check exists because `apps/channels/models.py:6\u20137` imports two leaf "
        "modules at module level; a cycle there breaks `manage.py check` for every command. "
        "Phase 2 stage 2d-1 moved those two out of `live_proxy/`",
        "- The boot check exists because `apps/channels/models.py:6` imports a leaf module at "
        "module level; a cycle there breaks `manage.py check` for every command. Phase 2 stage "
        "2d-1 moved it, with the three other names the catch-up surface imports, out of "
        "`live_proxy/`",
    )

    print(f"ok, {edits} edits")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: appK_claudemd.py <label-count> <backend-test-count> <suite-seconds>")
    main(*sys.argv[1:])
```

### Appendix N — Amendment A14, four in-place spec corrections, and the Done-log row, Task 12

A14 carries **twelve** items and is inserted immediately **before** `## Stage 2d`, so it lands
after A13 without needing to know A13's own text. A14.1b is the F1 ruling — the one a future
reader of the spec most needs, since A10.3 lists those two urlconf sites as imports to close
and says nothing about the patterns. Prints `ok, 6 edits`.

```python
#!/usr/bin/env python3
"""Appendix N -- Amendment A14, four in-place corrections, and the Done-log row.

(A14 carries TWELVE items since the fix round: A14.1b is F1.)

Run from the repository root. `assert count == 1` on every anchor. A14 is
inserted immediately before `## Stage 2d`, so it lands after A13 without
needing to know A13's own text.

The four corrections, each a sentence THIS PR makes false. Task 12 Step 5
greps for each OLD phrase and expects zero hits afterwards:

  1. A10.11's "Deletable in 2d-4" about core/tasks.py's fetch_channel_stats.
  2. A10.14's "eleven files by the time 2d-4 runs".
  3. A10.4's "The ten survivors".
  4. The deletion list's PR 5 entry giving the rcfile edit to 2d-5.
"""
import pathlib

SPEC = pathlib.Path("docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md")
edits = 0

A14 = r"""#### Amendment A14 (stage 2d-4) — twelve rulings from deleting the Python relay

**Measured on the merged 2d-3 tree**, with every disposition opened at the file rather than
inferred from a grep. Where an item contradicts a sentence in A10 or in § Stage 2d's deletion list,
that sentence is **edited in place** and the item says so.

**A14.1 — `relay_views.py` and `relay_urls.py` are deleted, and a "Django-side twin" was never a
thing that could be built.** A10.3 left the choice to this plan because it could not settle the
trade from the tree. Measured: `relay_views.py` is a 257-line HTTP wrapper over `ChannelStatus`,
`build_live_channel_stats_data`, `ProxyServer` and `ChannelService`, reached at eight sites — all
four inside the deleted directory. "Keeping it" means writing a second implementation of the Go
relay's in-process channel registry in Python over Redis keys the Go relay never writes. Two
consequences are stated rather than absorbed: Gate 2's denominator goes from ten boundary modules
to **nine**, which 2d-5's census must be planned against; and `IsInternalRelay` keeps exactly one
user, `authorize_views.py`'s `authorize_internal_view`, so `permissions.py` stays in the gate's
list.

**A14.1b — THE URL PATTERNS DO NOT GO WITH THE IMPORTS, and nothing in A10 says so.** A10.3 lists
`dispatcharr/urls.py:9` (site 5) and `apps/proxy/urls.py:10` (site 6) as module-level import sites
to close, which they are. What it does not say is that the PATTERNS those imports feed must stay.
`apps/proxy/authorize_views.py:214-228`'s `_surface_for()` hands the URI in `X-Original-URI` to
**Django's own resolver** and keys on the matched view's `__name__` — `"stream_ts"`, `"stream_xc"` —
deliberately, as its own comment says: "rather than re-deriving each surface's URL shape here — a
second copy of the urlconf, guaranteed to drift". Delete the patterns and every `auth_request`
subrequest for a live tune resolves to the **SPA catch-all**, so `authorize_view` answers **403** and
nginx never reaches the Go relay: **every live tune fails, in every nginx-fronted deployment, on the
one surface this phase exists to keep working** — and every Go test stays green through it. Measured
by executing the plan: 22 failures and 5 errors in `apps.proxy.tests`, all on the authorize hop,
against a seed baseline of 428 OK. **Ruling: the patterns survive, pointed at a new
`apps/proxy/stream_routes.py`** whose two callables exist to be RESOLVED and never called — same
paths, same pattern text, same `XC_STREAM_ID_PATTERN` and `\Z`, same view `__name__`s, same
`app_name = "live_proxy"` namespace, so `_surface_for` is untouched and Phase 1 D7's three-segment
regex trap is unchanged. Behind nginx nothing reaches them; in `dev` each answers **501 naming the
Go relay's port**, deliberately not 404, which is indistinguishable from an unknown channel.
`tests/test_urls_xc_three_segment.py` therefore keeps all five of its assertions and takes a
docstring paragraph instead of the rewrite an earlier draft gave it.

**A14.2 — the deletion breaks the `dev` shape, and A10.11's "deletable in 2d-4" is narrowed in
place.** `internal_base_url.py`'s `dev` branch hardcodes `http://127.0.0.1:5656` for **both**
directions because `resolve_base_url()` is shared, and dev runs no nginx — so after the delete
every `relay_client` call in dev reaches a Django with no `/proxy/relay/` route and gets a 404.
`resolve_base_url()` therefore gains a `dev_url` parameter and `get_relay_control_base_url()`
passes the Go relay's port, read from `DISPATCHARR_RELAY_GO_PORT` with A10.16's
default-and-validate shape. **Separately, `core/tasks.py`'s `fetch_channel_stats` is KEPT**: it
already goes through `relay_client.list_channels()`, it degrades correctly on all three exception
classes, and it carries four green tests. A10.11 called it dead because `beat_periodic_task` is
unreferenced — a property 2d-4 neither creates nor cures, and deleting working tested code for it
is the widening this phase's charter warns against. `apps/proxy/tasks.py` IS deleted, with the
disabled beat entry that names it: its builder scans `live:channel:*:metadata`.

**A14.3 — fifteen test files outside the package are affected, not eleven, and the breakage has
three kinds — and SEVENTEEN once the plan was executed.** A10.14 counts *import statements*. Re-derived with a classifier that separates
module-level imports, function-local imports, `mock.patch` **string** targets and prose: **nine**
files fail collection (and redden their whole label); **four** fail per-test at run time —
including `test_ts_proxy_keepalive.py` and `test_ts_proxy_keepalive_duration.py`, which A10.14
lists as collection-breakers and which have only function-local imports, plus
`test_recording_pipeline.py` and `tests/test_websocket_consumer_filter.py`, which A10.14 does not
list at all; and **two** carry assertions that go false with no import or patch anywhere
(`tests/test_ci_test_routing.py`, three of whose five tests fail, and
`core/tests/test_fetch_channel_stats.py`, which stays green and goes tautological). A fourth label,
the bare repo-root `tests`, is dragged in. A10.14's enumeration is edited in place.

**Two more were found only by executing the plan, and neither names `live_proxy` anywhere**, so no
grep over the deleted directory could have reached them: `apps/proxy/tests/test_relay_control_api.py`
imports `relay_views`, which **A14.1's own ruling** deletes (disposition: delete; Go cover
`relay/httpapi/control_test.go` and the two golden tests); and
`apps/proxy/tests/test_internal_base_url.py` pins the exact dev address **A14.2** changes
(disposition: rewrite, asserting both directions in one test, since the half a careless edit breaks
silently is `control_plane`'s). **The generalisable lesson**: a deletion's blast radius is the files
that name the deleted thing PLUS the files that name anything else the deletion forces you to
remove, and only executing the plan finds the second set.

**A14.4 — the disposition is 5 deleted whole, 5 split, 5 kept (four by re-pointing an import, one
by a docstring) and 2 rewritten**, and
every delete names its Go cover or says plainly there is none. Behaviours with no cover on either
side after this PR, recorded as gaps rather than claimed: the non-owner keepalive branch,
`_do_stats_update`'s WebSocket fan-out, `remove_client`'s non-blocking latency,
`_init_wait_abort_reason`'s "stalled" arm, `_pre_active_no_clients_should_stop`'s two-timeout
selection, the follower pub/sub switch-confirmation protocol and the ghost-client sweep — the last
two deliberately, by D2 and 2c-3. One orphaned assertion is re-homed rather than lost:
`width`/`height`/`video_bitrate` must be ABSENT when unset, which nothing pins on either side, and
which is re-homed as `relay/httpapi/detail_golden_test.go::TestTheDetailPayloadOmitsTheDVRVideoFieldsWhenNothingSetThem`
— the DETAIL golden, not the list one, because `width`/`height`/`video_bitrate` exist on the detail
payload alone (`relay/httpapi/detail.go:159-161`) and the list test's absence list could never have
carried them. Its break-check is one struct tag: dropping `,omitempty` from `Width` reddens it.

**A14.5 — the rcfile edit moves from 2d-5 to 2d-4, and the deletion list's PR 5 entry is corrected
in place.** `--write-floor --shape-only` recomputes `modules=`, `module_count=` **and** `rcfile=`
in one command, so removing the two dead `[report] include` lines here costs nothing and leaves no
config line pointing at a deleted directory. What stays 2d-5's is `missing` — the number, which is
the whole substance of "re-scope" and which needs the worst of ≥12 CI rounds on a tree that can
only exist after the delete. The floor's header gains a paragraph saying, in as many words, that
the gate is slack in that window and that a green run there proves the shape checks and not
coverage.

**A14.6 — the parity matrix's Source column names where the behaviour LIVES, and rows 26 and 27 get
a `retired:` sentinel the guard learns to read.** A10.5's three candidate shapes, with the third
argued hardest against as it asked. Exempting `white-box-only` rows from the Source check is
refused for two reasons beyond the one A10.5 gives: it is **retroactive** — every future white-box
row silently stops needing a citation, with no edit anywhere to notice — and it **conflates** "no
black-box test can reach this" with "this code no longer exists", which are independent (row 12's
fMP4 timeout is close to the first and very much alive in Go). Re-pointing both Sources at a
surviving file is refused as dishonest for row 27 in particular: citing a Go file as the source of
a behaviour the Go relay does not have inverts what the column means. The chosen form is backed by
a **`RETIRED_SOURCES` allowlist compared with `toEqual`**, in `WHITE_BOX_ONLY`'s exact idiom and
with its two sibling assertions, so the one word that makes a row stop citing source is itself
counted. It is explicitly **not** tied to `white-box-only`: 26 and 27 happen to be both, and the
two properties are independent.

**A14.7 — every A10.5 figure is confirmed exactly at the merged 2d-2 tree**, including the
eighteen-row list, and zero citations are broken before this PR — so every breakage is its own. One
thing A10.5 does not mention was found and is repaired as a side effect: **row 15's Source has been
stale since 2b-2**, whose 38-line shift in `views.py` made `:825` a blank line and `:845-851`
`stream_ts`'s exception handler rather than `stream_xc`'s hand-off. The guard cannot see it — it
checks that a line exists, never that it is the right line.

**A14.8 — the corpus relocation needs `runtime.Caller`, and a bare relative path was measured
wrong rather than reasoned wrong.** A three-package probe reproducing the topology confirmed that
`"testdata/..."` resolves against the **calling** package's directory and is found only inside
`relaytest` itself — green in the one package a maintainer would test first, a panic in the three
that actually read the corpus. `corpus.go` already uses the idiom (`repoRoot()` is a four-deep
`runtime.Caller` walk), so the edit shortens it to a one-deep `pkgDir()` with `RepoRoot()`
re-expressed on top, keeping one `runtime.Caller` call site. The return value stays **absolute**,
which is load-bearing: eleven callers hand it through argv to a re-exec'd child. `testdata/` under
a Go package adds no package, no module and no import path, so `go build`, `go vet`,
`golangci-lint` and `scripts/check_go_stdlib_only.sh` are all unaffected — each verified rather
than assumed. One inherited fragility is recorded rather than introduced: `-trimpath` defeats any
`runtime.Caller`-derived path, and it appears once in the repo, on `docker/Dockerfile:50`'s
production `go build`, never on a `go test`.

**A14.9 — the Go coverage gate provably does not move, so this PR runs no `--write-floor` on it.**
Three independent reasons: `packages=` hashes `go list -deps .`, which returns the same ten linked
packages (`relaytest` was already outside the linked set); `gomod=` hashes a file this PR does not
touch; and `statements`/`missing` are measured per linked package, so an edit inside `relaytest`
moves neither. A PR that runs one is doing something the measurement says it should not need to.

**A14.10 — #190 closes, and the delete is test-invisible in both directions.** All five ranges go,
and with them `apps/channels/models.py`'s `ChannelMetadataField` import, which has no other user in
the file. Exhaustively checked: **no test in the tree would fail if all five were deleted** —
every caller seeds the primary Django-owned keys, which is exactly the branch that skips all four
fallback reads; nothing asserts the `hdel` (the one test-side occurrence is a tolerance stub whose
own comment says so); and two of the fakes have no `hget` at all. So this PR ships a break-check
rather than trusting a green run: a new test seeds ONLY the metadata hash and asserts
`release_stream()` returns `False`. **The ledger row is 2d-6's**, not this PR's:
`metrics/build/curated.py` requires a `fixed` row to carry a `fixed_in` PR number and checks it is
merged, and a PR cannot name itself.

**A14.11 — what this PR deliberately leaves, each with its reason.** `apps/proxy/hls_proxy/` is
Phase 4's, which is why `signals.py`'s `hls_proxy` branch is kept verbatim beside the deleted
`live_proxy` one. The ~694 Go doc-comment citations of deleted Python filenames are not fixed
(A10.6). The 23 prose `live_proxy` comments under `e2e/` and the two in
`.github/workflows/domain-fuzz-campaign.{md,lock.yml}` are 2d-6's; the five `e2e/COVERAGE.md`
rows that cite a *path* are this PR's, and `COVERAGE.md:50` and `:202` stay 2d-6's per A10.10's own
table. `ChannelState.PRE_ACTIVE` keeps its seven-test shape pin although its last production reader
went with the package — the frozenset is four lines and re-deriving it for Phase 3 would cost more
than carrying it, which is a decision rather than an oversight. `reverse_imports_into_proxy` falls
29 → 28, expected drift on a headline tile with no gate.

"""

DONE_LOG_ROW = """- **2d-4** (`migration/phase2d-delete-live-proxy`) — deleted `apps/proxy/live_proxy/` (97 files,
  26,371 lines, 406 tests) and with it `relay_views.py`, `relay_urls.py`, `apps/proxy/tasks.py` and
  the `proxy` management command; closed the eight remaining module-level import sites including
  `INSTALLED_APPS`; re-pointed the three `url_utils` importers at `apps.proxy.next_source` and
  gave `resolve_base_url()` a per-direction `dev_url` so the dev shape reaches the Go relay;
  recomputed `worker_id` locally; deleted #190's five metadata-hash ranges with a break-check for
  the behaviour they changed; kept the live URL patterns, pointed at a new `apps/proxy/stream_routes.py`,
  because the authorize hop resolves the tune URI through Django's own urlconf and deleting them
  403s every live tune behind nginx; disposed of seventeen outside test files (5 deleted whole, 5 split,
  5 kept, 2 rewritten); replaced the parity matrix's Python column with Go citations and gave
  rows 26/27 a guard-checked `retired:` sentinel; moved the ffmpeg stderr corpus into
  `relay/internal/relaytest/testdata/`; deleted `go-tests.yml`'s `differential` job; took the label
  count 16 → 15 and Gate 2's module list 38 → 9 with a `--shape-only` re-baseline that leaves
  `missing` slack until 2d-5. Amendment A14.
"""


def sub(old, new):
    global edits
    t = SPEC.read_text(encoding="utf-8")
    n = t.count(old)
    assert n == 1, f"anchor matched {n} times, expected 1:\n---\n{old[:200]!r}"
    SPEC.write_text(t.replace(old, new), encoding="utf-8")
    edits += 1


def main():
    # --- A14 itself, inserted before the Stage 2d heading (i.e. after A13).
    sub("## Stage 2d — cutover, and its trap\n", A14 + "## Stage 2d — cutover, and its trap\n")

    # --- correction 1: A10.11's core/tasks.py sentence.
    sub(
        "**Deletable in 2d-4** along with the rest of that emission path (A10.3 site 7).",
        "**Amendment A14.2 narrows this: `core/tasks.py`'s half is KEPT** -- it already goes "
        "through `relay_client.list_channels()`, degrades correctly on all three exception "
        "classes and carries four green tests, and its caller's unreferencedness is a property "
        "2d-4 neither creates nor cures. What 2d-4 deletes is `apps/proxy/tasks.py` (A10.3 site "
        "7), whose builder scans `live:channel:*:metadata`, and the disabled beat entry that "
        "names it.",
    )

    # --- correction 2: A10.14's count.
    sub(
        "(**Eleven across two labels by the time 2d-4",
        " **Amendment A14.3 supersedes this count: SEVENTEEN files across FOUR labels, and the "
        "breakage has three kinds** — nine fail collection, four fail per-test at run time (two "
        "of them listed below as collection-breakers although their imports are function-local, "
        "and two not listed here at all), and two carry assertions that go false with no import "
        "or patch anywhere. The enumeration below counts import STATEMENTS, which is why it "
        "misses the last six, and two more that name `live_proxy` nowhere at all.** "
        "(**Eleven across two labels by the time 2d-4",
    )

    # --- correction 3: A10.4's "ten survivors".
    sub(
        "The **ten survivors** are lines 1-5 and 34-38:",
        "The **ten survivors** are lines 1-5 and 34-38 (**nine after Amendment A14.1**, which "
        "deletes `relay_views.py`):",
    )

    # --- correction 4: the deletion list's PR 5 entry.
    sub(
        "Re-scope Gate 2 to the ten\n   surviving boundary modules (`scripts/coverage_live_path.coveragerc`'s `[report] include` loses\n   `apps/proxy/live_proxy/*`), and set `missing` from the worst of a ≥12-round **CI** census on the\n   post-delete tree,",
        "Re-scope Gate 2 to the **nine**\n   surviving boundary modules and set `missing` from the worst of a ≥12-round **CI** census on the\n   post-delete tree. **Amendment A14.5 moves the rcfile edit itself to PR 4**, which removes both\n   dead `[report] include` lines with its `--shape-only` re-baseline — one command rewrites\n   `modules=` and `rcfile=` together, so there is no reason for a config line to name a deleted\n   directory for a whole PR. What remains here is the NUMBER,",
    )

    # --- the Done-log row.
    sub("## Done log\n\nFilled in as PRs merge; this spec lands as its own PR 0.\n",
        "## Done log\n\nFilled in as PRs merge; this spec lands as its own PR 0.\n\n" + DONE_LOG_ROW)

    print(f"ok, {edits} edits")


if __name__ == "__main__":
    main()
```

### Appendix R — the replay proof (Task 0 Step 3b's justification)

Not applied by any task. It is the script this plan was verified with, kept so a reviewer can
reproduce the claim that the appendix set composes.

```bash
#!/bin/bash
# Replay the 2d-4 appendices into a pristine worktree in TASK ORDER and prove
# the result is byte-identical to the tree they were generated from.
set -euo pipefail
S=/private/tmp/claude-501/-Users-dion-git-Dispatcharr/58c32b58-c2f1-479a-a5cb-62753eaf67d6/scratchpad/plan-2d4
A=$S/final
R=/Users/dion/git/Dispatcharr
W=$R/.worktrees/plan2d4-replay
SEED=e1a7b91f1f66bf8d79b0bd21afdbc1675fc0c464

git -C "$R" worktree remove "$W" --force >/dev/null 2>&1 || true
git -C "$R" worktree add "$W" "$SEED" --detach >/dev/null
cd "$W"

echo "--- Task 1: the corpus move + the Go edits"
mkdir -p relay/internal/relaytest/testdata/ffmpeg_stderr
git mv apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/CAPTURE.md \
       apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/normal.stderr \
       apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/slow-trickle.stderr \
       apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/truncation.stderr \
       relay/internal/relaytest/testdata/ffmpeg_stderr/
git apply --whitespace=error "$A/D1.diff"

echo "--- Task 2: the url_utils importers and their patch strings"
git apply --whitespace=error "$A/B.diff"

echo "--- Task 3: worker_id"
git apply --whitespace=error "$A/L.diff"

echo "--- Task 4: relay_views/relay_urls, stream_routes, the dev address"
cp "$A/stream_routes.py" apps/proxy/stream_routes.py
git add apps/proxy/stream_routes.py
git rm -q apps/proxy/relay_views.py apps/proxy/relay_urls.py
git apply --whitespace=error "$A/C1.diff"
git apply --whitespace=error "$A/C2.diff"
git apply --whitespace=error "$A/C3.diff"

echo "--- Task 5: #190"
git apply --whitespace=error "$A/M1.diff"
git apply --whitespace=error "$A/M2.diff"

echo "--- Task 6: the boot sites"
git apply --whitespace=error "$A/C4.diff"
git apply --whitespace=error "$A/C5.diff"
git rm -q apps/proxy/tasks.py apps/proxy/management/commands/proxy.py

echo "--- Task 7: the package, the test dispositions, the re-homed assertion"
git rm -r -q apps/proxy/live_proxy
git rm -q apps/channels/tests/test_ts_proxy_ghost_clients.py \
           apps/channels/tests/test_ts_proxy_keepalive_duration.py \
           apps/channels/tests/test_ts_proxy_teardown.py \
           apps/proxy/tests/test_relay_status_shape.py \
           apps/proxy/tests/test_relay_control_api.py
git apply --whitespace=error "$A/A2.diff"
git apply --whitespace=error "$A/D4.diff"

echo "--- Task 8: labels, hooks, workflows"
git apply --whitespace=error "$A/I1.diff"
git apply --whitespace=error "$A/I2.diff"
git apply --whitespace=error "$A/I3.diff"
git apply --whitespace=error "$A/I4.diff"

echo "--- Task 9: Gate 2"
git apply --whitespace=error "$A/H1.diff"
git apply --whitespace=error "$A/H2.diff"

echo "--- Task 10: the matrix and its guard"
python3 "$S/appE_matrix.py"
git apply --whitespace=error "$A/F.diff"

echo "--- Task 11: the ledger and COVERAGE.md"
git apply --whitespace=error "$A/J1.diff"
git apply --whitespace=error "$A/J2.diff"

echo "--- Task 12: CLAUDE.md and the spec"
python3 "$S/appK_claudemd.py" 15 2083 24.0
python3 "$S/appN_spec.py"

echo
echo "=== PROOF: diff -r against the tree the appendices were generated from ==="
diff -r -q -x .git -x node_modules -x '*.bak' -x __pycache__ \
  "$W" "$R/.worktrees/plan2d4-final" && echo "IDENTICAL — replay reproduces the source tree exactly"
```
