# Fix plan, category J — Phase 2 close-out housekeeping

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Implementers are `sonnet`; every review is `fable` (or `opus` when fable credits are unavailable), per CLAUDE.md § Delegation.

**Goal.** Pay the debts Phase 2 recorded and did not pay: delete the dead HLS package and its two
dead consumers, delete the `RedisKeys` builders nothing calls, rebuild a Django-side ORM ratchet
over the modules Gate 1's retirement left unguarded, fix the isolated coverage driver that drops
every flag after its first.

**Architecture.** No behaviour changes anywhere in this category. Three PRs delete or re-word
code nothing executes; one adds a regression test for a local driver script; one adds a test
module that pins the queries the tune path runs today. Every CLAUDE.md sentence these edits make
false is corrected in the PR that makes it false, and in no other.

**Tech stack.** Python 3 / Django 6 / DRF, bash, Go (comments only), nginx config (comments only),
one gh-aw workflow prompt (body only).

**Spec.** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`, Amendment **A16.12**
items 3, 5, 6 and 7 (what Phase 2 leaves owed), **A16.7** (the nginx comment) and **A10.8** (why
Gate 1's static half was not replaced in 2d). The input list is the lead's `issues-J.md` (eight
items); the only tracker issue in it is **#336**.

---

## Header

| field | value |
|---|---|
| Category | J — Phase 2 close-out housekeeping |
| Measurement seed | **`a54b09a9`** (`main`, 2026-09-23, #342). Every `file:line`, count and hash below was opened or measured there. |
| Ordering | Third of ten: **B, A, J**, C, D, E, G, H, I, F. The lead re-seeds this plan after B and A merge. |
| PRs | J-1 `migration/J-1-delete-hls-proxy`, J-2 `fix/J-2-dead-redis-keys-builders`, J-3 `fix/J-3-tune-path-query-ledger`, J-4 `fix/J-4-isolated-coverage-flags` |
| Implementation order | J-1, then J-2 and J-4 in either order, then J-3 last (J-3 pins `config.py` after J-1 edits it) |
| upstreamable | **no** for all four. Every file touched is fork-only or carries fork-only context (`CLAUDE.md`, `metrics/curated/`, `relay/`, `apps/proxy/redis_keys.py`, the Gate 2 scripts). |

### Files this plan touches

| file | PR | change |
|---|---|---|
| `apps/proxy/hls_proxy/{__init__,server,urls,views}.py` | J-1 | deleted (1,216 lines) |
| `apps/proxy/views.py` | J-1 | deleted (unrouted `ProxyViewSet`, R7) |
| `apps/proxy/signals.py` | J-1 | deleted (never imported, R7) |
| `apps/proxy/config.py:77-88` | J-1 | `HLSConfig` deleted |
| `relay/httpapi/stream.go:392-395`, `relay/httpapi/fanout_test.go:443-449` | J-1 | comments only |
| `docker/nginx.conf:25-29`, `:45-49` | J-1 | comments only (A16.7) |
| `.github/workflows/claude-md-maintenance.md:122` | J-1 | prompt body only |
| `metrics/curated/defects.yml:25` | J-1 | `hls-proxy-dead` → `fixed` |
| `apps/proxy/redis_keys.py` | J-2 | 25 builders deleted, docstring rewritten |
| `apps/proxy/constants.py:1-17`, `apps/proxy/config_helper.py:1-19` | J-2 | docstrings only |
| `apps/proxy/relay_client.py:30-33` | J-2 | docstring only |
| `apps/proxy/tests/test_redis_keys_dead_builders.py` | J-2 | new |
| `apps/proxy/tests/test_tune_path_query_ledger.py` | J-3 | new |
| `scripts/coverage_live_path_isolated.sh` | J-4 | forwards every argument |
| `tests/test_coverage_isolated_dropped_shape_only.py` | J-4 | new |
| `CLAUDE.md` | J-1, J-2, J-3 | the sentences each PR invalidates, listed per PR |

### Overlap with other categories

Checked against `sweep-report.md` and every `issues-*.md`. For each shared file: what this plan
assumes the other plan does there, and which goes first.

| file | other category | assumption | order |
|---|---|---|---|
| `CLAUDE.md` | A, B, D, E, I | They edit Go-defect prose (A), auth/nginx prose (B), VOD prose (D), config-cache prose (E) and property-test prose (I). J edits only the sentences listed per PR below. Every J edit is **anchored by text with `assert count == 1`** and STOPs on a miss, so an earlier rewrite surfaces as a stop rather than a wrong edit. The numeric sentences (LOC, style debt, cross-app imports) are **re-measured on J-1's own tree**, never copied from this plan, because A and B may already have moved them. | A, B first |
| `docker/nginx.conf` | B (#182), G (#81, #180), H (#179) | They edit the `server` block and the location bodies (`:69-74`, `:698`) and `03-init`'s templating. J edits only the two comment paragraphs above `server` (`:25-58`). No textual overlap at the seed. | B first; G, H after |
| `relay/httpapi/*` | A (#222 `fmp4.go`, #302, #306, #296…) | A edits `fmp4.go`, `channel/`, `ffmpeg/` and their tests. J edits two comments in `stream.go:392-395` and `fanout_test.go:443-449`. If A has moved those lines, re-anchor on the quoted text. | A first |
| `apps/proxy/next_source.py` | A (#314 serializer fields), C (#171 `transform_url` `$0`) | J-3 does not edit it; J-3 **measures** it. A lands before J-3 is measured. C lands after: **if C's fix changes the queries next-source runs, C's PR must update J-3's ledger under rule 5** (before/after listed). A pure string rewrite in `transform_url` runs no query and will not. | A before, C after |
| `apps/proxy/authorize.py` | B (#110 VOD `is_adult`) | J-3 measures the **live** authorize hop only. B's VOD filter does not run on it. J-3 is measured after B merges regardless. | B first |
| `apps/proxy/config.py`, `apps/proxy/config_helper.py` | E (#232 `TSConfig` cache shadowing) | J-1 deletes `HLSConfig`; J-2 rewrites `config_helper.py`'s docstring; J-3 pins both modules' model imports and resets `TSConfig`'s cache in its cold helper. **E goes after J.** If E's fix adds a model import to either module, E updates J-3's static expectation under rule 5. If E renames `_proxy_settings_cache`, E updates J-3's `_cold()` helper. | J first |
| `metrics/curated/defects.yml` | most | J-1 edits one row, `hls-proxy-dead`. Rows are one per line, so conflicts are trivial. | any |
| `apps/proxy/relay_client.py` | none found | J-2 edits three docstring lines. | — |

---

## Global Constraints

- **Test-modification rule, verbatim from the brief:** a test may change only when the behaviour it pins is the thing being changed, and every such change is listed in the PR section with its before and after assertion. A test that deliberately pins a defect is flipped to pin the fix, and the plan shows the flipped test failing before the fix and passing after. Never widen a tolerance, lower a count or delete an assertion to make a run green. New behaviour gets a new test named after the defect.
- **No existing test changes in this category.** Every PR below was checked for it. Deleted code has no tests; the three new test modules are additions.
- **Stage and commit in separate Bash calls.** Write commit messages with the Write tool and commit with `git commit -F <file>`. End messages with the attribution line the session's system reminder names.
- **Anchor every command** with an absolute path or a leading `cd` into your own worktree. Brace `git show "${ref}:path"`. Use `set -o pipefail` before reading `$?` through a pipe.
- **Your own test container.** Start one per PR with `DISPATCHARR_TEST_CONTAINER=<pr>`, `DISPATCHARR_TEST_DB_VOLUME=<pr>-db` and `CLAUDE_HOOK_REPO_ROOT=<your worktree>` in front of `.claude/hooks/start-test-container.sh`. The PostToolUse hooks still use `dispatcharr-testrunner` and will refuse on a mount mismatch; that refusal is expected and is **not** a test result. Run the labels yourself against your own container.
- **Gate 2 modules.** J-2 edits `apps/proxy/relay_client.py`, which `scripts/coverage_live_path.coveragerc` lists. It runs the isolated coverage gate before push (memory: *Gate 2 modules need the isolated coverage run*).
- **Collector numbers are arguments, not literals.** Any CLAUDE.md figure J changes is read from `scripts/metrics/collect_code_health.py` or `collect_architecture.py` run against the PR's own tree (`--repo-root`), at implementation time.

---

## Rulings

### R1 — the split, and why J-1 takes the `migration/` prefix

The lead suggested nginx with the `RedisKeys` work. This plan moves it to J-1 instead. Three J edits
force `migration/**` under brief rule 3: the nginx comment (`docker/`), and two Go comments in
`relay/httpapi/` that J-1's deletion makes false. Putting all three in J-1 means exactly one J PR pays
for the full E2E matrix, and it is the PR that deletes a package, which is the one J change where a
full run has any chance of finding something. J-2, J-3 and J-4 then stay on `fix/` branches with one
to three backend labels each.

### R2 — the ORM ratchet: a runtime per-drive query ledger plus a narrow static pin, not the relocated scanner

Item 1 asks for a scope decision. The deleted guard had two halves: a static AST scanner
(`zero_orm_scan.py`) with a line-keyed allowlist, and a runtime check of the SQL the relay executed.

**Relocating the static scanner is the wrong shape now.** Run with its own rule over the five
modules at the seed, it finds **62** flagged sites:

| module | sites | of which |
|---|---|---|
| `next_source.py` | 46 | `.objects` 11, `get_object_or_404` 6, model-method names 29 |
| `authorize.py` | 7 | `.objects` 6, `get_default_output_format` 1 |
| `authorize_views.py` | 1 | `.objects` 1 |
| `config.py` | 7 | `get_proxy_settings` 7 |
| `config_helper.py` | 1 | `get_proxy_settings` 1 |

Before 2d-4 those reads were reachable **from the relay**, so each one was a question. Now every
one of these modules runs in the API process and reads the ORM **by design**: next-source *is* the
database lookup that answers the relay. A per-site allowlist would carry 62 entries keyed by line
number, and the deleted allowlist's own docstring records that a line-keyed ledger goes red when
lines move rather than when a read is added (*true positive for a false reason*). It would fire on
ordinary edits and teach people to regenerate it.

**What is worth ratcheting is the cost of a tune**, which is what the relay-side guard was
ultimately protecting. J-3 pins, for each per-tune Django hop the Go relay or nginx calls, the exact
multiset of queries it runs from a cold cache, keyed by `(verb, table)` and, for
`core_coresettings`, by the settings-group key (the deleted allowlist's `params_fragment` lesson:
two groups produce identical SQL text). An exact **count** per signature also closes the gap the old
runtime half admitted it could not: a second, redundant query of an already-allowed shape now
changes a count. Measured at the seed, in a prototype removed before commit:

| drive | queries | signatures |
|---|---|---|
| authorize hop, live tune by UUID, anonymous | 3 | `core_coresettings` `network_access` ×1, `stream_settings` ×1; `dispatcharr_channels_channel` ×1 |
| next-source, first tune | 15 | `core_coresettings` `proxy_settings` ×1, `stream_settings` ×1; `core_outputprofile` ×1; `core_streamprofile` ×2; `core_useragent` ×1; `dispatcharr_channels_channel` ×2; `dispatcharr_channels_channeloverride` ×1; `dispatcharr_channels_channelstream` ×1; `dispatcharr_channels_stream` ×2; `m3u_m3uaccount` ×1; `m3u_m3uaccountprofile` ×2 |
| next-source, second call on the same channel | 12 | as first tune, minus one `dispatcharr_channels_stream`, one `m3u_m3uaccount`, one `m3u_m3uaccountprofile` |
| release | 1 | `dispatcharr_channels_channel` ×1 |

Two runs of each drive from a cold cache gave identical multisets. The first and second next-source
calls differ because the second takes the assignment-reuse branch; the ledger therefore pins them
as two drives rather than treating the difference as noise.

**`config_helper.py` is not on the tune path** (its callers are catch-up, `apps/timeshift/views.py:40`,
and the DVR retry window, `apps/channels/tasks.py:1125`). So J-3 adds one narrow static test: the
only model import in `config.py` is `CoreSettings`, inside `BaseConfig.get_proxy_settings`, and
`config_helper.py` imports no model at all; neither contains `.objects`. That is the "these modules
read the ORM only here" guard A10.8 describes, at a grain that does not move on ordinary edits.

**Counting discrepancy, recorded.** A10.8 says twelve `EdgeEntry` rows reached four modules. The
allowlist as it stood at `b6ae174b~1` has **ten** rows over **five** modules (`next_source` 2,
`config` 4, `config_helper` 1, `authorize` 2, `authorize_views` 1), because 2d-2 deleted two
`views.py` rows and 2d-1 turned one `config` row into the `config_helper` row. A16.12 item 3's
"10 entries across these five modules, `config` carrying four" is the correct later figure.

### R3 — `RedisKeys`: three builders survive, and `channel_metadata` survives for a test

Measured at the seed, `apps/proxy/redis_keys.py` defines **28** builders, not the 24 the input file
assumed. Each `RedisKeys.<name>` hit was resolved to its import, because `apps/timeshift/redis_keys.py`
defines `TimeshiftRedisKeys` with four same-named builders (`channel_metadata`, `clients`,
`client_metadata`, `client_stop`), and three test files import it **as `RedisKeys`**
(`apps/proxy/tests/test_stream_limits.py:8`, `apps/timeshift/tests/test_stats.py:13`, and 36 local
imports in `apps/timeshift/tests/test_views.py`). None of those three imports `apps.proxy.redis_keys`.

| builder | real callers of `apps.proxy.redis_keys.RedisKeys` | verdict |
|---|---|---|
| `channel_stream` | `apps/channels/models.py`, `core/utils.py:779`, `apps/proxy/next_source.py`, tests | keep |
| `stream_profile` | same, plus `core/utils.py:812` | keep |
| `channel_metadata` | tests only: `apps/channels/tests/test_get_stream_assignment.py:102`, `:266` | keep, with a comment |
| `switch_status` | **none**. The one hit is prose, `apps/proxy/relay_client.py:31`'s module docstring | delete |
| `clients`, `client_metadata` | **none**. Hits in `apps/channels/tests/test_dvr_client_teardown.py:3` and `test_recording_stop_cancel.py:282-283` are historical docstrings | delete |
| the other 22 | none anywhere | delete |

`channel_metadata` builds `live:channel:<uuid>:metadata`, a key no process writes since 2d-3. It
stays because two #190 regression tests seed that exact key to prove `release_stream()` no longer
touches it. Inlining the literal into those tests would change a test for a reason that is not the
behaviour it pins, which rule 5 forbids. Its comment says so.

The census command (re-run at implementation; it must list only the prose and alias hits above):

```bash
cd <worktree> && git grep -n -P '(?<!Timeshift)RedisKeys\.[a-z_]+\b' -- . ':!docs/superpowers' ':!CHANGELOG.md' \
  | grep -v -E 'RedisKeys\.(channel_stream|stream_profile|channel_metadata)\b' \
  | grep -v -E '^apps/(timeshift/tests/test_(views|stats)|proxy/tests/test_stream_limits)\.py:'
```

At the seed that prints exactly four lines: `test_dvr_client_teardown.py:3`,
`test_recording_stop_cancel.py:282` and `:283`, and `relay_client.py:31`.

### R4 — `scripts/coverage_live_path.coveragerc`'s "the dead hls_proxy" clause is left, on A16.7's precedent

`coveragerc:20-21` says "vod_proxy and the dead hls_proxy stay out". After J-1 the second half names a
package that no longer exists. The file's own comment at `:34-38` says any comment-only edit moves the
floor's `rcfile=` hash and must ship with a `--write-floor --shape-only`, which needs a writable pair
of containers and a round. That cost buys one clause. This plan does what A16.7 did for nginx: record
it and leave it for the next PR that edits the rcfile for a real reason. J-1's PR body names it.

### R5 — the `m3u8` dependency stays

`apps/proxy/hls_proxy/server.py:13` is the only `import m3u8` in the tree, so the dependency becomes
unused. It stays in `pyproject.toml`: plugins run unsandboxed from `/app/data/plugins/` and may import
anything the image carries, so removing a package from the image can break a user's plugin without any
test here seeing it. Dropping it also puts `pyproject.toml` and `uv.lock` in the PR, which forces every
backend label. Open question Q2 lets the user overrule this.

### R6 — withdrawn: input item 7 is out of scope

User ruling, 2026-09-23: the `docs/comparisons/*.json` dataset is a local-only comparison file and
stays untracked. This plan does not commit it, ignore it or document it. The ruling number is kept so
R7 and R8 keep their names.

### R7 — `apps/proxy/views.py` and `apps/proxy/signals.py` go with the package

Both exist only to drive the HLS or live proxy singleton the app config no longer builds:

- `apps/proxy/signals.py:8-19` registers a `pre_delete` receiver that looks up `hls_proxy` on the app config. **Nothing imports the module**: `apps/proxy/apps.py` has no `ready()` (its comment at `:8-14` says why), and `git grep 'proxy.signals'` is empty. So the receiver has never been connected since 2d-4, and with the package gone the `getattr` would return `None` anyway.
- `apps/proxy/views.py:9-64` is a `ProxyViewSet` whose `start`/`stop` actions default to type `hls` and call `getattr(app_config, 'hls_proxy')`. No urlconf or router names it (`git grep ProxyViewSet` finds only its definition).

Both files carry open CodeQL alerts, and so does the package. Deleting all three resolves **six**
open alerts at once: #105 (`py/reflective-xss`, `hls_proxy/views.py:23`, tracked as issue #336),
#64, #65, #66 (`py/stack-trace-exposure`, `hls_proxy/views.py:47`, `:79`, `:101`) and #81, #82
(`py/stack-trace-exposure`, `apps/proxy/views.py:39`, `:62`). Only #105 has a tracker issue. The
other five were never ingested, so nothing needs closing by hand.

`apps/proxy/apps.py:8-14`'s comment names `signals.py` in the past tense ("Until Phase 2 stage 2d-4
it … setting self.live_proxy for apps/proxy/signals.py …"). It stays true and is not edited.

---

## Per-item analysis

### Item 1 — Django-side ORM ratchet (A16.12 item 3) → J-3

- **Root cause.** 2d-4 deleted `apps/proxy/live_proxy/tests/{test_zero_orm_reads,zero_orm_allowlist,zero_orm_scan,test_zero_orm_scan}.py` with the package. Their scope-2 walk was the only ratchet over `apps/proxy/{next_source,authorize,authorize_views,config,config_helper}.py`, and `config.py` is in neither Gate 2's `coveragerc` (`scripts/coverage_live_path.coveragerc`'s `[report] include` at the seed lists nine modules, not it) nor any other guard.
- **Fix.** R2: `apps/proxy/tests/test_tune_path_query_ledger.py`, a cold-cache exact query ledger over four drives, plus one static model-import pin over `config.py` and `config_helper.py`.
- **Tests.** Added: five tests in one new module. Changed: none. Removed: none.
- **Size** M. **upstreamable** no. **Duplicates** none.

### Item 2 — dead `RedisKeys` builders (A16.12 item 7) → J-2

- **Root cause.** 2d-1 moved `redis_keys.py` whole out of `live_proxy/` (`apps/proxy/redis_keys.py:3-6`), and 2d-4 deleted every reader and writer of 25 of its 28 builders without auditing the module (A16.12 item 7 says so). `RedisKeys.worker_heartbeat` at `:89-92` is the one CLAUDE.md names (`CLAUDE.md:144`).
- **Fix.** R3: delete 25 builders; keep `channel_stream`, `stream_profile` and `channel_metadata`; rewrite the module docstring, which at `:1-16` still describes "the live relay's channel state" and a re-export shim that no longer exists.
- **Tests.** Added: `apps/proxy/tests/test_redis_keys_dead_builders.py`, two tests (the exact surviving set, and that both boot-trap leaf modules import nothing). Changed: none. Removed: none.
- **Size** S. **upstreamable** no. **Duplicates** none.

### Item 3 — delete `apps/proxy/hls_proxy/` (A16.12 item 5) → J-1

- **Root cause.** The package is unrouted: `apps/proxy/urls.py:7-13` includes `ts_admin_urls`, `stream_routes`, `timeshift.urls` and `vod_proxy.urls`, and `dispatcharr/urls.py` includes no hls urlconf. Its only import from elsewhere in `apps/proxy` is `HLSConfig` from `apps/proxy/config.py:77` (`hls_proxy/server.py:20`), and nothing but the package uses `HLSConfig`.
- **Fix.** Delete the package, `HLSConfig`, and the two dead consumers of R7. Close the `hls-proxy-dead` ledger row. Correct the prose that describes the package as present: CLAUDE.md, two Go comments, the gh-aw maintenance prompt.
- **Tests.** Added: none (R8 below). Changed: none. Removed: none; the package has no tests.
- **#336.** It closes, with `Closes #336` in the PR body. The sweep marked it INVALID because the code is unreachable. Either way the right end state is the file gone and the alert fixed by CodeQL's next analysis of `main`. It currently carries `needs-triage` and `re-triage`. The lead removes both labels at close (deferred tracker write).
- **Size** M (mostly deletion). **upstreamable** no. **Duplicates** none.

**R8 — why the deletion carries no new test.** A test asserting a module does not exist pins nothing
a reader cares about, and it passes whether or not anything still needs the module. The evidence
that nothing does is: the reference census returning nothing, `manage.py check` passing, the whole
`apps.proxy.tests` label passing, `tests.test_openapi_schema` passing (so drf-spectacular never
discovered `ProxyViewSet`), and the collectors moving by exactly the deleted code's share.

### Item 4 — `docker/nginx.conf:47-48` stale canary comment (A16.7) → J-1

- **Root cause.** `docker/nginx.conf:47-49` says "Phase 2's canary is a second map entry and a second upstream block — not a code change on either side (ADR 0005)". Phase 2 used no canary (spec D3; ADR 0006). `:25-29`, twenty lines above, already says so. The same block's `:28` also says "those five", where ADR 0006's Consequences measured **six** `uwsgi_pass $relay_upstream` locations. `grep -c` at the seed confirms six against four `proxy_pass http://relay_go`.
- **What it should say.** The map picks the upstream for the six locations that still reach the relay's uWSGI by name. Phase 2 did not use it: the Go relay took its four locations by a literal `proxy_pass http://relay_go` and had no canary period (ADR 0006). The map's remaining purpose is a future per-channel or scale-out assignment (ADR 0005). Exact text is in J-1 Task 4.
- **Tests.** None. Comments only; `nginx -t` runs in the E2E matrix `migration/**` triggers.
- **Size** S. **upstreamable** no.

### Item 5 — three future-tense shim docstrings → J-2

- **Root cause.** Each still describes 2d-4 as future:
  - `apps/proxy/redis_keys.py:14-15`: "`apps/proxy/live_proxy/redis_keys.py` re-exports `RedisKeys` from here until stage 2d-4 deletes the package."
  - `apps/proxy/config_helper.py:17-18`: the same sentence for `ConfigHelper`.
  - `apps/proxy/constants.py:3-8` and `:13-16`: says `apps/channels/models.py` imports `ChannelMetadataField` at module level, and that the other constants "stay in `apps/proxy/live_proxy/constants.py` … 2d-4 deletes them with it". The first claim is false at the seed: `apps/channels/models.py:1-10` imports `RedisKeys` only, as CLAUDE.md `:105` records.
- **Fix.** Rewrite each docstring in the present tense, naming today's importers. Exact text in J-2 Task 3.
- **Tests.** None of their own. J-2's leaf test covers the rule the two leaf docstrings state.
- **Size** S. **upstreamable** no.

### Item 6 — `scripts/coverage_live_path_isolated.sh` forwards only `$1` → J-4

- **Root cause.** `scripts/coverage_live_path_isolated.sh:104` builds the final in-container call as `bash scripts/coverage_live_path.sh ${1:---report} /tmp/combined`. So `isolated.sh --write-floor --shape-only` becomes `coverage_live_path.sh --write-floor /tmp/combined`. That is a **full** floor write (`scripts/coverage_live_path.sh:586-599`), which measures `missing` from one local round and writes it whenever it is not worse. The floor's own rule is that `missing` comes only from a ≥12-round CI census. So the dropped flag does not merely fail; it can silently lower the floor from local numbers. It is caught today only because the isolated containers mount `/repo` read-only and `write_floor` refuses on a read-only floor (`:452-460`).
- **Fix.** Default to `--report` with `set --` when no argument is given, then forward every argument, shell-quoted, before `/tmp/combined`. The incomplete-round refusal at `:76-81` keeps reading `$1`, which is still the mode.
- **Tests.** Added: `tests/test_coverage_isolated_dropped_shape_only.py`. It stubs `docker` on `PATH`, records every call, and asserts what the final `docker exec` asked the inner script to do. One test fails before the fix; two controls pass on both sides. Changed/removed: none.
- **Routing.** `scripts/coverage_live_path*` is aliased in `dispatcharr/test_discovery.py:53` to Gate 2's own two labels, `apps.proxy.tests` and `apps.channels.tests`. `tests/test_ci_test_routing.py:71` already pins that for this exact script. The new test file adds the root `tests` label.
- **Size** S. **upstreamable** no.

### Item 7 — the untracked `docs/comparisons/` dataset → out of scope (R6)

Withdrawn by user ruling. No PR touches `docs/comparisons/`.

### Item 8 — CLAUDE.md sentences these edits invalidate

| line at seed | sentence | PR |
|---|---|---|
| `:72` | "`apps/proxy` fell from 40,652 … to 16,952 when stage 2d-4 deleted the live relay" | J-1 |
| `:77` | "of what is left, five are `vod_proxy`'s … and four are in the dead `apps/proxy/hls_proxy/`, so the rule binds one live module" | J-1 |
| `:84` | "and `apps/proxy/hls_proxy/` (1,216 lines, 1,018 non-blank) is dead" | J-1 |
| `:104` | "193 cross-app imports over 39 edges" | J-1 |
| `:138` | "Dead or unwired: `apps/proxy/hls_proxy/` (1,216 lines, 1,018 non-blank; Phase 4's to delete);" | J-1 |
| `:140` | "Style debt, re-measured after stage 2d-4 deleted 26,371 lines: … 651 broad `except Exception` …" | J-1 |
| `:154` | "(`hls_proxy` 0%, `plugins` 25%, …), and `hls_proxy`, `plugins` and `vod_proxy` all survive at those figures" | J-1 |
| `:144` | "(`RedisKeys.worker_heartbeat` survives at `apps/proxy/redis_keys.py:90-92`, relocated by 2d-1 and untouched by 2d-4, with nothing reading or writing it)" | J-2 |
| `:158` | "Recorded as a gap, deliberately not replaced in 2d (spec A10.8): … on the post-2d list beside the coverage re-scope." | J-3 |

**Checked and deliberately not edited:** `:105`'s `models_boot_trap_imports` prose (the input file
listed it). No J change moves that tile or the sentence: J-2 deletes builders but no import, and
`apps/channels/models.py:6` still imports `RedisKeys`. `:105`'s "reaching them through it at
twenty-four sites" counts `channel_stream`/`stream_profile` uses in `models.py`, which J-2 leaves
alone. `:156`'s mention of `coverage_live_path_isolated.sh` stays true after J-4.

---

## PR J-1 — delete `apps/proxy/hls_proxy/` and its dead consumers

- **Branch:** `migration/J-1-delete-hls-proxy` (R1: touches `docker/` and `relay/httpapi/`).
- **Closes:** #336. Resolves CodeQL alerts #64, #65, #66, #81, #82, #105. Ledger row `hls-proxy-dead`.
- **Labels:** `apps.proxy.tests` (`python scripts/ci_backend_test_labels.py` over the file list prints `["apps.proxy.tests"]`). Go checks run for the two `relay/httpapi/` files. `migration/**` runs the full E2E matrix.
- **Files:** delete `apps/proxy/hls_proxy/` (four files), `apps/proxy/views.py`, `apps/proxy/signals.py`. Modify `apps/proxy/config.py`, `relay/httpapi/stream.go`, `relay/httpapi/fanout_test.go`, `docker/nginx.conf`, `.github/workflows/claude-md-maintenance.md`, `metrics/curated/defects.yml`, `CLAUDE.md`.

### Task 1: the reference census, before deleting anything

- [ ] **Step 1.** From your worktree, list every reference outside the doomed files:
  ```bash
  cd <wt> && set -o pipefail && git grep -n -P 'hls_proxy|HLSConfig|ProxyViewSet|proxy\.signals|proxy/signals\.py|apps\.proxy\.views\b|apps/proxy/views\.py' \
    -- . ':!docs/superpowers' ':!apps/proxy/hls_proxy' ':!apps/proxy/views.py' ':!apps/proxy/signals.py'
  ```
  At the seed it prints eleven lines: `.github/workflows/claude-md-maintenance.md:122`, `CLAUDE.md:77`, `:84`, `:138`, `:154`, `apps/proxy/apps.py:11`, `apps/proxy/config.py:77`, `metrics/curated/defects.yml:25`, `relay/httpapi/fanout_test.go:444`, `relay/httpapi/stream.go:395`, `scripts/coverage_live_path.coveragerc:21`. (`-P` is required for `\b`. `apps.proxy.views\b` matches no `vod_proxy.views` hit, because `vod_proxy` sits between.) **Any other line is a new caller: STOP and report it.**
- [ ] **Step 2.** Record the collector baseline on this tree, for Task 6:
  ```bash
  cd <wt> && python3 scripts/metrics/collect_code_health.py --repo-root . > /tmp/j1-ch-before.json \
    && python3 scripts/metrics/collect_architecture.py --repo-root . > /tmp/j1-arch-before.json
  ```

### Task 2: delete the code

- [ ] **Step 1.** `git rm -r apps/proxy/hls_proxy apps/proxy/views.py apps/proxy/signals.py`.
- [ ] **Step 2.** In `apps/proxy/config.py`, delete the `HLSConfig` class, `:77-88` at the seed (from `class HLSConfig(BaseConfig):` through `BUFFER_READY_TIMEOUT = 30.0` and the blank line after it). Leave `BaseConfig` and `TSConfig` untouched.
- [ ] **Step 3.** Verify the tree still boots and nothing imports what went:
  ```bash
  docker exec -w /repo <env as in .claude/hooks/run-affected-tests.sh dexec()> <your-container> \
    /dispatcharrpy/bin/python manage.py check
  docker exec … /dispatcharrpy/bin/python -c "import django,os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','dispatcharr.settings_test');django.setup();import importlib,pkgutil,apps.proxy as p;[importlib.import_module(m.name) for m in pkgutil.walk_packages(p.__path__,'apps.proxy.') if '.tests' not in m.name];print('ok')"
  ```
  Expect `ok`, and from `check` only `staticfiles.W004` for the missing `frontend/dist`, which the seed reports too (no frontend build in the test container).
- [ ] **Step 4. Break-check of the verification.** Add `from apps.proxy.hls_proxy.server import ProxyServer` as the first line of `apps/proxy/stats_views.py`, re-run the import walk, require `ModuleNotFoundError: No module named 'apps.proxy.hls_proxy'`, then revert. This proves the walk would have seen a surviving importer.

### Task 3: the two Go comments

Both are comments; no assertion changes. The Go hook runs build, vet, lint and `-race` tests on edit.

- [ ] **Step 1.** `relay/httpapi/stream.go:392-395`. Replace:
  ```go
  	// 2c-6: fmp4 joins mpegts. Anything else is still refused rather than
  	// served under a label that is not true -- and there is no third format to
  	// refuse today (_OUTPUT_FORMAT_MANAGERS registers only fmp4,
  	// server.py:1352-1353, and apps/proxy/hls_proxy/ is dead and unrouted).
  ```
  with:
  ```go
  	// 2c-6: fmp4 joins mpegts. Anything else is still refused rather than
  	// served under a label that is not true -- and there is no third format to
  	// refuse today: the deleted Python relay's _OUTPUT_FORMAT_MANAGERS
  	// registered only fmp4, and the unrouted apps/proxy/hls_proxy/ was deleted
  	// by fix plan J-1.
  ```
- [ ] **Step 2.** `relay/httpapi/fanout_test.go:443-449`. Replace the first two lines of the comment,
  ```go
  		// 2c-6 SERVES fmp4, so this row moved to a format NEITHER relay has.
  		// `hls` is the honest choice: apps/proxy/hls_proxy/ exists, is 1,206
  		// lines, is 0% covered and is routed nowhere, and
  ```
  with:
  ```go
  		// 2c-6 SERVES fmp4, so this row moved to a format NEITHER relay has.
  		// `hls` is the honest choice: apps/proxy/hls_proxy/ was 1,206 lines,
  		// 0% covered and routed nowhere (fix plan J-1 deleted it), and
  ```
  Leave the rest of the comment and the table row unchanged.
- [ ] **Step 3.** `cd <wt>/relay && go build ./... && go vet ./... && go test -race ./httpapi/ && golangci-lint run ./...` and `GOOS=linux golangci-lint run ./...` (memory: build-tagged files escape host lint). All clean.

### Task 4: the nginx comment (A16.7)

- [ ] **Step 1.** `docker/nginx.conf:28`: change "resolve differently than those five" to "resolve differently than those six". ADR 0006's Consequences measured six `uwsgi_pass $relay_upstream` against four `proxy_pass http://relay_go`. Re-confirm on your tree with `grep -c 'uwsgi_pass \$relay_upstream' docker/nginx.conf` (six) before editing; if it is not six, write the number it is.
- [ ] **Step 2.** `docker/nginx.conf:45-49`. Replace:
  ```
  # The values are upstream GROUP names, not addresses: uwsgi_pass to a
  # variable holding a bare host:port needs a `resolver` and fails without
  # one, while a declared group needs none. Phase 2's canary is a second map
  # entry and a second upstream block — not a code change on either side
  # (ADR 0005). Since stage 2d-3 every location still passing to
  ```
  with:
  ```
  # The values are upstream GROUP names, not addresses: uwsgi_pass to a
  # variable holding a bare host:port needs a `resolver` and fails without
  # one, while a declared group needs none. Phase 2 did NOT use this map:
  # the Go relay took its four locations by a literal `proxy_pass
  # http://relay_go` with no canary period (ADR 0006), so every entry here
  # still resolves to relay_py, which serves VOD and catch-up. A second
  # entry and a second upstream block remain how a later per-channel or
  # scale-out assignment would route (ADR 0005). Since stage 2d-3 every location still passing to
  ```
  The sentence that follows (`$relay_upstream runs the hop …`) is unchanged.
- [ ] **Step 2 note.** ADR 0006's parenthetical ("`docker/nginx.conf`'s own comment says 'five'") becomes a record of what the comment said. ADRs are records and are not edited.

### Task 5: the maintenance prompt and the ledger

- [ ] **Step 1.** `.github/workflows/claude-md-maintenance.md:122`: remove `` `hls_proxy/`, `` from the Tier 2 example list, so it reads `` (`entrypoint.aio.sh`, `persistent_lock.py`, `renovate.json`, ``. The lock file runtime-imports this prompt (`claude-md-maintenance.lock.yml:269`, `{{#runtime-import .github/workflows/claude-md-maintenance.md}}`), so a body edit needs no recompile. Run a bare `gh aw compile` anyway and require `git status --short .github/` to show only the `.md`. If a lock changes, stage it too and say so in the PR body.
- [ ] **Step 2.** `metrics/curated/defects.yml:25`, row `hls-proxy-dead`: set `status: fixed`, `fixed_in: <this PR's number>`, `status_changed: <merge date>`. Keep `source` and the title. The move `open → fixed` is legal (`docs/agents/metrics.md`). Validate with `python3 -m metrics.build --validate-only --curated metrics/curated`.

### Task 6: CLAUDE.md

- [ ] **Step 1.** Re-run both collectors into `/tmp/j1-*-after.json` and diff against Task 1 Step 2. At the seed the expected deltas were (prototype, measured on a copy of the tree):

  | metric | before | after |
  |---|---|---|
  | `loc_per_app.apps.proxy` | 16,952 | 15,864 |
  | `except_exception` | 651 | 632 |
  | `cross_app_import_statements` | 193 | 192 |

  Everything else is unchanged: `except_pass_handlers` 200, `bare_except` 16, `os_environ_reads` 176, `function_local_imports` 1,191, 39 edges, one cycle, `reverse_imports_into_proxy` 28. **If B or A has already moved a before-figure, use your tree's numbers; if the delta differs from the table, STOP and attribute it.**
- [ ] **Step 2.** Apply the edits with an anchored script (`assert text.count(old) == 1` per edit, STOP on a miss). `<N_LOC>`, `<N_EXC>`, `<N_XAPP>` are the after-figures from Step 1; `<PR>` is this PR's number.

  | anchor (old) | replacement |
  |---|---|
  | `` `apps/proxy` fell from 40,652 non-blank Python lines to 16,952 when stage 2d-4 deleted the live relay`` | `` `apps/proxy` fell from 40,652 non-blank Python lines to 16,952 when stage 2d-4 deleted the live relay, and to <N_LOC> when #<PR> deleted the dead `hls_proxy` `` |
  | `of what is left, five are `` `vod_proxy` ``'s `` `multi_worker_connection_manager.py` `` and four are in the dead `` `apps/proxy/hls_proxy/` ``, so the rule binds one live module.` | `the five left are all `` `vod_proxy` ``'s `` `multi_worker_connection_manager.py` `` since #<PR> deleted the four in `` `apps/proxy/hls_proxy/` ``, so the rule binds one live module.` |
  | `` and `apps/proxy/hls_proxy/` (1,216 lines, 1,018 non-blank) is dead.`` | `` and `apps/proxy/hls_proxy/`, which never served one, was deleted by #<PR>.`` |
  | `**The apps are a mesh, not a stack**: 193 cross-app imports over 39 edges` | `**The apps are a mesh, not a stack**: <N_XAPP> cross-app imports over 39 edges` |
  | `` Dead or unwired: `apps/proxy/hls_proxy/` (1,216 lines, 1,018 non-blank; Phase 4's to delete); `` | `Dead or unwired: ` |
  | `Style debt, re-measured after stage 2d-4 deleted 26,371 lines: 200 exception handlers whose whole body is `` `pass` ``, 16 bare `` `except:` ``, 651 broad` | `Style debt, re-measured after #<PR> deleted `` `apps/proxy/hls_proxy/` ``: 200 exception handlers whose whole body is `` `pass` ``, 16 bare `` `except:` ``, <N_EXC> broad` |
  | `` (`hls_proxy` 0%, `plugins` 25%, `vod_proxy` 35.6%, `live_proxy` 38.5% vs `timeshift` 78.7%), and `hls_proxy`, `plugins` and `vod_proxy` all survive at those figures; `` | `` (`hls_proxy` 0%, `plugins` 25%, `vod_proxy` 35.6%, `live_proxy` 38.5% vs `timeshift` 78.7%), and `plugins` and `vod_proxy` survive at those figures (`hls_proxy` was deleted by #<PR>); `` |

  If Step 1 shows a moved 200/16/176, update those figures in the same sentence too.
- [ ] **Step 3.** Re-run Task 1 Step 1's census. The expected survivors are only `apps/proxy/apps.py:11` (past tense, R7), `scripts/coverage_live_path.coveragerc:21` (R4), `CLAUDE.md`'s rewritten sentences (which now name the deletion) and the Go comments (likewise).

### Task 7: verify and ship

- [ ] **Step 1.** In your container: `manage.py test --keepdb apps.proxy.tests -v1` and `manage.py test --keepdb tests.test_openapi_schema -v1`. Assert the output ends in `OK` (grep `^OK`, never pipe the runner's exit status — memory: CI backend runner pipes lose exit status). Flush Redis first.
- [ ] **Step 2.** Commit (stage and commit in separate calls). Push. Open the PR with the body below. The full E2E matrix runs because of the branch name.

**PR description draft**

```
relay(fixplan-J): J-1 -- delete apps/proxy/hls_proxy/ and its two dead consumers

## What
Deletes code nothing runs:
- apps/proxy/hls_proxy/ (1,216 lines): unrouted since before this fork (no urlconf includes it).
- apps/proxy/views.py: ProxyViewSet, routed by nothing, defaults to the HLS proxy.
- apps/proxy/signals.py: a pre_delete receiver no module imports, so it never connected.
- HLSConfig in apps/proxy/config.py, used only by the package.

Closes #336. CodeQL alerts #105, #64, #65, #66 (hls_proxy/views.py) and #81, #82
(apps/proxy/views.py) close on the next analysis of main.

## Also in this PR (sentences the deletion makes false, and A16.7)
- CLAUDE.md: seven sentences, numbers re-measured with scripts/metrics collectors.
- relay/httpapi/stream.go and fanout_test.go: two comments that said the package exists.
- docker/nginx.conf: the canary comment spec A16.7 recorded as stale, and "five" -> "six".
- claude-md-maintenance.md: hls_proxy/ removed from the Tier 2 example list.
- metrics/curated/defects.yml: hls-proxy-dead -> fixed.

## Deliberately not in this PR
- The m3u8 dependency stays: plugins may import it (plan R5).
- scripts/coverage_live_path.coveragerc:21 still says "the dead hls_proxy stay out".
  Editing it moves the Gate 2 floor's rcfile= hash; left for the next real rcfile edit (plan R4).

## Tests
No test added: a test that a module is absent pins nothing (plan R8). Evidence instead:
manage.py check, an import walk over every apps.proxy module, apps.proxy.tests, tests.test_openapi_schema,
Go build/vet/lint/-race, and the full E2E matrix (migration/**).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## PR J-2 — delete the dead `RedisKeys` builders and re-tense three docstrings

- **Branch:** `fix/J-2-dead-redis-keys-builders`.
- **Closes:** no tracker issue (A16.12 item 7; spec 2d-6 disclosure).
- **Labels:** `apps.proxy.tests`. The boot-check hook arm (`manage.py check`) fires on `redis_keys.py`, `constants.py` and `config_helper.py`.
- **Files:** modify `apps/proxy/redis_keys.py`, `apps/proxy/constants.py`, `apps/proxy/config_helper.py`, `apps/proxy/relay_client.py` (docstring), `CLAUDE.md`. Create `apps/proxy/tests/test_redis_keys_dead_builders.py`.

### Task 1: the failing test

- [ ] **Step 1.** Create `apps/proxy/tests/test_redis_keys_dead_builders.py`:
  ```python
  """RedisKeys carried builders for keys nothing reads or writes.

  Phase 2 stage 2d-1 moved apps/proxy/redis_keys.py out of live_proxy/ whole,
  and 2d-4 deleted every reader and writer of 25 of its 28 builders without
  auditing it (spec Amendment A16.12 item 7). A dead builder is not harmless:
  it tells a reader the key is live, and CLAUDE.md had to carry a sentence
  explaining that RedisKeys.worker_heartbeat meant nothing.

  The surviving set is pinned exactly, so a builder added back needs a caller
  and a deliberate edit here. channel_metadata survives for one reason only:
  apps/channels/tests/test_get_stream_assignment.py's #190 regression tests
  seed that exact key to prove release_stream() no longer touches it.
  """

  import ast
  import pathlib

  from django.test import SimpleTestCase

  from apps.proxy.redis_keys import RedisKeys

  REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

  SURVIVORS = {"channel_metadata", "channel_stream", "stream_profile"}

  # CLAUDE.md, Structural constraints: apps/channels/models.py imports
  # RedisKeys at module level, so one import added to either module can stop
  # Django booting. The hook's boot check catches that locally; this is the
  # same rule where CI runs it.
  LEAF_MODULES = ("apps/proxy/redis_keys.py", "apps/proxy/constants.py")


  class RedisKeysDeadBuildersTests(SimpleTestCase):
      def test_redis_keys_carried_builders_for_keys_nothing_reads_or_writes(self):
          builders = {
              name for name, value in vars(RedisKeys).items()
              if isinstance(value, staticmethod)
          }
          self.assertEqual(
              builders, SURVIVORS,
              f"unexpected builders: {sorted(builders - SURVIVORS)}; "
              f"missing: {sorted(SURVIVORS - builders)}",
          )

      def test_the_boot_trap_leaf_modules_import_nothing(self):
          for rel in LEAF_MODULES:
              with self.subTest(module=rel):
                  tree = ast.parse((REPO_ROOT / rel).read_text())
                  imports = [
                      ast.unparse(node) for node in ast.walk(tree)
                      if isinstance(node, (ast.Import, ast.ImportFrom))
                  ]
                  self.assertEqual(imports, [], f"{rel} must stay a leaf")
  ```
- [ ] **Step 2.** Run `manage.py test --keepdb apps.proxy.tests.test_redis_keys_dead_builders -v2` in your container. Expect the first test to **FAIL** with `unexpected builders: ['buffer_chunk', …, 'worker_heartbeat']` (25 names) and the second to pass (both leaves import nothing at the seed).

### Task 2: the census and the deletion

- [ ] **Step 1.** Run R3's census command. It must print exactly the four prose lines R3 lists. Anything else is a caller: **STOP**.
- [ ] **Step 2.** Replace `apps/proxy/redis_keys.py` with:
  ```python
  """Redis key builders Django still uses.

  apps/channels/models.py imports RedisKeys at module level (Channel.get_stream,
  release_stream, update_stream_profile and _release_stale_stream_assignment),
  and so do core/utils.py and apps/proxy/next_source.py function-locally.

  THIS MODULE MUST STAY A LEAF -- no imports, at all. It is loaded by every
  migration and every management command through that models.py import, so a
  cycle added here is not a failing test, it is a container that does not
  start. ``.claude/hooks/run-affected-tests.sh``'s boot-check ``case`` arm
  names this file for exactly that reason, and
  apps/proxy/tests/test_redis_keys_dead_builders.py asserts it.

  Phase 2 stage 2d-1 moved this module here from the live relay's package, and
  it then held 28 builders for the Python relay's channel state. The Go relay
  opens no Redis connection, so fix plan J-2 deleted the 25 nothing called.
  """

  class RedisKeys:
      @staticmethod
      def channel_metadata(channel_id):
          """The deleted Python relay's per-channel metadata hash.

          NOTHING WRITES OR READS THIS KEY in production since Phase 2 stage
          2d-3. It is kept only because the #190 regression tests in
          apps/channels/tests/test_get_stream_assignment.py seed this exact key
          to prove release_stream() no longer reads or clears it.
          """
          return f"live:channel:{channel_id}:metadata"

      # Written only by apps/channels/models.py — Channel.get_stream(),
      # release_stream(), update_stream_profile() — and reached only through
      # apps/proxy/next_source.py since Phase 1 PR 6. They were hand-rolled
      # f-strings on both sides of the boundary, which is what made them
      # split-brain; naming them here is what makes a second writer visible.
      @staticmethod
      def channel_stream(channel_pk):
          """Stream id currently assigned to this channel (numeric channel pk)."""
          return f"channel_stream:{channel_pk}"

      @staticmethod
      def stream_profile(stream_id):
          """M3U account profile id serving this stream."""
          return f"stream_profile:{stream_id}"
  ```
  The last two builders and their comment are byte-for-byte the seed's `:159-172`.
- [ ] **Step 3.** Re-run the test module. Both tests pass.
- [ ] **Step 4. Break-checks.** (a) Add back `worker_heartbeat` verbatim from the seed. The first test must fail naming `['worker_heartbeat']`. Revert. (b) Add `import os` as the first line after the docstring. The second test must fail with `apps/proxy/redis_keys.py must stay a leaf` and `['import os']`, and `manage.py check` must still pass (an unused stdlib import is not a cycle, which is why the test exists alongside the hook). Revert. (c) Add `from apps.channels.models import Channel` instead. `manage.py check` must fail with `ImportError: cannot import name … from partially initialized module` (CLAUDE.md's measured symptom), and the test must be red too. Revert.

### Task 3: the three docstrings, plus the relay_client line

- [ ] **Step 1.** `apps/proxy/constants.py:1-17`. Replace the docstring with:
  ```python
  """Channel state and metadata-field names shared by Django and the relay.

  Moved here from the deleted apps/proxy/live_proxy/constants.py in Phase 2
  stage 2d-1 (spec Amendment A10.3). Importers today: apps/proxy/relay_client.py
  (ChannelState), apps/timeshift/views.py and apps/timeshift/stats.py
  (ChannelMetadataField, and ChannelState in views.py), and
  apps/channels/tasks.py function-locally. apps/channels/models.py no longer
  imports anything from here: stage 2d-4 deleted its ChannelMetadataField
  import with issue #190's five ranges.

  THIS MODULE MUST STAY A LEAF -- no imports, at all, for the reason
  ``apps/proxy/redis_keys.py``'s docstring gives.

  Only the two names surviving code needs moved here. The rest of the old
  module went with apps/proxy/live_proxy/ at stage 2d-4.
  """
  ```
  Re-check the importer list with `git grep -n 'from apps.proxy.constants import' -- '*.py' ':!*/tests/*'` before committing; it matched the text above at the seed.
- [ ] **Step 2.** `apps/proxy/config_helper.py:17-18`. Replace the last paragraph,
  ```
  ``apps/proxy/live_proxy/config_helper.py`` re-exports ``ConfigHelper`` from
  here until stage 2d-4 deletes the package.
  ```
  with:
  ```
  Stage 2d-4 deleted ``apps/proxy/live_proxy/config_helper.py``, the
  re-export shim that stood here until then.
  ```
  Also change `:2-3`'s "Moved here from ``apps/proxy/live_proxy/config_helper.py``" to "Moved here from the deleted ``apps/proxy/live_proxy/config_helper.py``", and `:4`'s "Two surfaces stage 2d KEEPS call it" to "Two surfaces call it". The rest is unchanged.
- [ ] **Step 3.** `apps/proxy/relay_client.py:30-33`. The `ADVANCE_TIMEOUT` line names a builder this PR deletes and a wait the Go relay does not perform (`relay/httpapi/control.go:180-195`: `confirmed` is never set, because there is no owner to wait for). Replace:
  ```
    ADVANCE_TIMEOUT (2, 20)  ChannelService.change_stream_url polls
                             RedisKeys.switch_status for up to
                             STREAM_SWITCH_CONFIRM_TIMEOUT = 15s on the
                             non-owner path before answering.
  ```
  with:
  ```
    ADVANCE_TIMEOUT (2, 20)  sized for the deleted Python relay, whose
                             change_stream_url polled a switch-status key
                             for up to 15s on the non-owner path. The Go
                             relay answers without that wait; the budget
                             is unchanged here.
  ```
  **Only this line.** The rest of that docstring (`:14-20`) also describes `live_proxy/` in the present tense. It is not J's and is not edited; the PR body says so.

### Task 4: CLAUDE.md and ship

- [ ] **Step 1.** Anchored edit, `CLAUDE.md:144`. Replace `` (`RedisKeys.worker_heartbeat` survives at `apps/proxy/redis_keys.py:90-92`, relocated by 2d-1 and untouched by 2d-4, with nothing reading or writing it) `` with `` (`RedisKeys.worker_heartbeat` survived 2d-4 with nothing reading or writing it, and #<PR> deleted it with the other 24 dead builders) ``.
- [ ] **Step 2.** In your container: `manage.py check`; `manage.py test --keepdb apps.proxy.tests -v1` and `apps.channels.tests.test_get_stream_assignment -v1`. Assert `^OK`.
- [ ] **Step 3.** Gate 2, because `relay_client.py` is a coveragerc module. The edit is inside the module docstring, which is one statement whatever its length, so `statements` and `missing` must not move. Start two containers named `fixj2-proxy` and `fixj2-channels` (CLAUDE_HOOK_REPO_ROOT set to your worktree), then `COVERAGE_ISOLATED_PREFIX=fixj2 bash scripts/coverage_live_path_isolated.sh --gate`. Require exit 0. Remove both containers afterwards.
- [ ] **Step 4.** Commit, push, open the PR.

**PR description draft**

```
chore(fixplan-J): J-2 -- delete the 25 dead RedisKeys builders; re-tense three shim docstrings

## What
apps/proxy/redis_keys.py held 28 builders for the deleted Python relay's Redis state.
25 have no caller (census in the plan, R3; TimeshiftRedisKeys aliases excluded by import).
Three survive: channel_stream and stream_profile (Django's assignment keys), and
channel_metadata, kept only for the #190 regression tests that seed that key.

New test apps/proxy/tests/test_redis_keys_dead_builders.py pins the surviving set exactly and
asserts both boot-trap leaf modules import nothing. It failed before the deletion (25 names)
and passes after.

## Also
- constants.py, config_helper.py and redis_keys.py docstrings described 2d-4 as future.
- relay_client.py's ADVANCE_TIMEOUT line named a deleted builder and a wait the Go relay
  does not do. Only that line changed; the rest of that docstring's live_proxy prose is
  left for whoever next edits the module.
- CLAUDE.md: the worker_heartbeat sentence.

## Gate 2
relay_client.py is a coveragerc module. The edit is inside the module docstring.
coverage_live_path_isolated.sh --gate: exit 0.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## PR J-3 — the tune-path query ledger (Gate 1's Django-side replacement)

- **Branch:** `fix/J-3-tune-path-query-ledger`. Implement **after J-1 merges** (J-1 edits `config.py`) and after A and B (both touch modules this measures).
- **Closes:** no tracker issue (A16.12 item 3, A10.8).
- **Labels:** `apps.proxy.tests`.
- **Files:** create `apps/proxy/tests/test_tune_path_query_ledger.py`; modify `CLAUDE.md`.

### Task 1: measure the ledger on your tree

The ledger values are typed by hand from a measurement, never generated at test time: a test whose
expected value the code under test computes cannot fail (memory: *the tautological oracle*).

- [ ] **Step 1.** Create the module below with every `LEDGER` value set to `{}`. Run it. Each drive test fails and its message prints the observed multiset. Copy each into `LEDGER` by hand.
- [ ] **Step 2.** Compare with R2's seed table. If a drive differs, attribute it to the A or B commit that moved it (`git log a54b09a9..HEAD -- apps/proxy/ apps/channels/models.py core/models.py`) and say so in the PR body. **Do not accept an unexplained difference.**
- [ ] **Step 3.** Run the module three times in a row (`--keepdb`, Redis flushed before each). All three must pass. A drive that is not deterministic is a finding: STOP and report it rather than loosening anything.

### Task 2: the module

- [ ] **Step 1.** Create `apps/proxy/tests/test_tune_path_query_ledger.py`:
  ```python
  """Every query the tune path runs, per drive, from a cold cache.

  WHY THIS EXISTS. Phase 2 stage 2d-4 deleted Gate 1's static ORM scanner with
  apps/proxy/live_proxy/. Its scope-2 walk was the only ratchet over the
  Django modules the Go relay and nginx call on every tune -- next_source,
  authorize, authorize_views, config and config_helper (spec A10.8, A16.12
  item 3). Those modules now run in the API process and read the ORM by
  design, so relocating the scanner's line-keyed allowlist would be a list
  of 62 expected reads that goes red when lines move. What is worth pinning
  is what a tune COSTS: this module records the exact multiset of queries
  each per-tune hop runs, and fails naming the table when one is added,
  removed or repeated.

  THE SIGNATURE. (verb, table), plus the settings-group key for
  core_coresettings, because two settings groups produce identical SQL text
  and differ only in the bound key (the deleted allowlist's params_fragment
  lesson). Counts are exact, so a second redundant query of an existing
  shape changes a count; the deleted runtime half could not see that.

  COLD, ALWAYS. Every drive clears Django's cache and the process-local
  proxy_settings cache first. A warm cache hides the CoreSettings reads
  (memory: warm state hides a query), and CLAUDE.md records that TSConfig's
  cache attribute shadows BaseConfig's, so both are reset.

  CHANGING A LEDGER ENTRY is a behaviour change to the tune path and follows
  the repo's test-modification rule: the PR lists the entry before and after
  and says why the query moved.
  """

  import ast
  import pathlib
  import re
  from collections import Counter
  from unittest.mock import patch

  from django.core.cache import cache
  from django.db import connection
  from django.test import SimpleTestCase
  from django.test.utils import CaptureQueriesContext

  from apps.proxy import relay_client
  from apps.proxy.config import BaseConfig, TSConfig
  from apps.proxy.tests.test_next_source_api import RelayApiTestCase

  REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

  _STATEMENT = re.compile(
      r'^\s*(SELECT|INSERT|UPDATE|DELETE)\b.*?(?:FROM|INTO|UPDATE)\s+"([a-z0-9_]+)"',
      re.S | re.I,
  )
  _SETTINGS_KEY = re.compile(r"'([a-z_]+)'")

  S = "SELECT"

  # Measured at <implementation SHA>, typed by hand (Task 1).
  LEDGER = {
      # nginx auth_request, once per tune: STREAMS ACL, stream settings, the channel.
      "authorize_live_uuid": {
          (S, "core_coresettings", "network_access"): 1,
          (S, "core_coresettings", "stream_settings"): 1,
          (S, "dispatcharr_channels_channel"): 1,
      },
      # POST /api/relay/channels/<uuid>/next-source, first tune of the channel.
      "next_source_first_tune": {
          (S, "core_coresettings", "proxy_settings"): 1,
          (S, "core_coresettings", "stream_settings"): 1,
          (S, "core_outputprofile"): 1,
          (S, "core_streamprofile"): 2,
          (S, "core_useragent"): 1,
          (S, "dispatcharr_channels_channel"): 2,
          (S, "dispatcharr_channels_channeloverride"): 1,
          (S, "dispatcharr_channels_channelstream"): 1,
          (S, "dispatcharr_channels_stream"): 2,
          (S, "m3u_m3uaccount"): 1,
          (S, "m3u_m3uaccountprofile"): 2,
      },
      # The same call again: the assignment-reuse branch skips three reads.
      "next_source_reuse": {
          (S, "core_coresettings", "proxy_settings"): 1,
          (S, "core_coresettings", "stream_settings"): 1,
          (S, "core_outputprofile"): 1,
          (S, "core_streamprofile"): 2,
          (S, "core_useragent"): 1,
          (S, "dispatcharr_channels_channel"): 2,
          (S, "dispatcharr_channels_channeloverride"): 1,
          (S, "dispatcharr_channels_channelstream"): 1,
          (S, "dispatcharr_channels_stream"): 1,
          (S, "m3u_m3uaccountprofile"): 1,
      },
      # POST /api/relay/channels/<uuid>/release, once per channel stop.
      "release": {
          (S, "dispatcharr_channels_channel"): 1,
      },
  }


  def _signature(query):
      match = _STATEMENT.match(query["sql"])
      if not match:
          return (query["sql"].split()[0].upper(), "?")
      verb, table = match.group(1).upper(), match.group(2)
      if table == "core_coresettings":
          key = _SETTINGS_KEY.search(query["sql"])
          return (verb, table, key.group(1) if key else "?")
      return (verb, table)


  def _cold():
      cache.clear()
      for klass in (BaseConfig, TSConfig):
          klass._proxy_settings_cache = None
          klass._proxy_settings_cache_time = 0


  class TunePathQueryLedgerTests(RelayApiTestCase):
      """RelayApiTestCase supplies the channel, two streams, the fake Redis
      and the internal-header signing the Go relay's own client uses."""

      def _observe(self, call):
          _cold()
          # The reuse check asks the relay whether the channel runs. Nothing
          # listens in a test, so pin the answer instead of dialling :5658.
          absent = relay_client.ChannelSnapshot(present=False, active=False, reachable=True)
          with patch.object(relay_client, "channel_snapshot", return_value=absent):
              with CaptureQueriesContext(connection) as ctx:
                  response = call()
          self.assertEqual(response.status_code, 200, response.content[:300])
          return dict(Counter(_signature(q) for q in ctx.captured_queries))

      def _assert_ledger(self, drive, observed):
          self.assertEqual(
              observed, LEDGER[drive],
              f"{drive}: the tune path's queries moved.\n"
              f"  added or more: {sorted((Counter(observed) - Counter(LEDGER[drive])).items())}\n"
              f"  removed or fewer: {sorted((Counter(LEDGER[drive]) - Counter(observed)).items())}\n"
              f"  observed: {sorted(observed.items())}",
          )

      def _authorize(self):
          return self.client.get(
              "/_dispatcharr/authorize",
              HTTP_X_ORIGINAL_URI=f"/proxy/ts/stream/{self.channel.uuid}",
          )

      def _next_source(self):
          return self._post(self.next_source_path(str(self.channel.uuid)), {})

      def test_the_authorize_hop_runs_no_query_outside_its_ledger(self):
          self._assert_ledger("authorize_live_uuid", self._observe(self._authorize))

      def test_a_first_tune_next_source_runs_no_query_outside_its_ledger(self):
          self._assert_ledger("next_source_first_tune", self._observe(self._next_source))

      def test_a_reused_assignment_next_source_runs_no_query_outside_its_ledger(self):
          self._observe(self._next_source)
          self._assert_ledger("next_source_reuse", self._observe(self._next_source))

      def test_release_runs_no_query_outside_its_ledger(self):
          self._observe(self._next_source)
          path = self.release_path(str(self.channel.uuid))
          self._assert_ledger("release", self._observe(lambda: self._post(path, {})))


  def _model_imports(rel):
      """(enclosing qualname, module, name) for every import from a models module."""
      found, objects = set(), 0
      tree = ast.parse((REPO_ROOT / rel).read_text())

      def visit(node, scope):
          nonlocal objects
          for child in ast.iter_child_nodes(node):
              if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                  visit(child, scope + [child.name])
                  continue
              if isinstance(child, ast.ImportFrom) and child.module and (
                  child.module.endswith(".models") or child.module == "django.db.models"
              ):
                  for alias in child.names:
                      found.add((".".join(scope), child.module, alias.name))
              if isinstance(child, ast.Attribute) and child.attr == "objects":
                  objects += 1
              visit(child, scope)

      visit(tree, [])
      return found, objects


  class ConfigModulesReadOnlyCoreSettingsTests(SimpleTestCase):
      """config.py and config_helper.py sit on every proxy path (config_helper
      is catch-up and DVR, not the live tune, so the ledger above cannot see
      it). Their only ORM access is CoreSettings, through one method."""

      EXPECTED = {
          "apps/proxy/config.py": {("BaseConfig.get_proxy_settings", "core.models", "CoreSettings")},
          "apps/proxy/config_helper.py": set(),
      }

      def test_the_config_modules_gained_no_orm_read_after_gate_1_was_retired(self):
          for rel, expected in self.EXPECTED.items():
              with self.subTest(module=rel):
                  imports, objects = _model_imports(rel)
                  self.assertEqual(imports, expected)
                  self.assertEqual(objects, 0, f"{rel} reaches a manager directly")
  ```
- [ ] **Step 2.** Run the module in your container. All five tests pass.

### Task 3: break-checks

Each is a deliberate wrong edit, run, observed red, reverted. Quote the failure line in the PR body.

- [ ] **(a) A new query on the tune path.** In `apps/proxy/next_source.py`'s `_with_proxy_settings` (`:827` at the seed, run on every next-source answer), insert `from core.models import StreamProfile` and `StreamProfile.objects.count()` just before its `return answer` (`:862`). Both next-source drives must fail with `added or more: [(('SELECT', 'core_streamprofile'), 1)]`. Revert.
- [ ] **(b) A redundant query of an existing shape.** In `apps/proxy/authorize.py`'s `_resolve_channel`, `SURFACE_LIVE` branch (`:383` at the seed), duplicate the line `target = get_stream_object(identifier)`. `test_the_authorize_hop_…` must fail with `added or more: [(('SELECT', 'dispatcharr_channels_channel'), 1)]`. This is the case the deleted runtime half admitted it could not catch. **Not** `:401`'s `Channel.objects.filter(uuid=…)`: that is the catch-up branch, a live tune never reaches it, and duplicating it leaves every test green (measured). Revert.
- [ ] **(c) A warm cache hides reads.** Comment out the `_cold()` call in `_observe` and run the module in one process. At the seed two drives fail: the authorize hop loses `('core_coresettings', 'stream_settings')`, and next-source reuse loses both `core_coresettings` reads and `core_useragent` (the first-tune drive warmed them). This proves the ledger was measured cold. Revert.
- [ ] **(d) A new model import in config.py.** In `apps/proxy/config.py`, add `from core.models import StreamProfile` inside `TSConfig.get_channel_shutdown_delay`. The static test must fail naming `('TSConfig.get_channel_shutdown_delay', 'core.models', 'StreamProfile')`. Revert.

### Task 4: CLAUDE.md and ship

- [ ] **Step 1.** Anchored edit, `CLAUDE.md:158`. Replace `Recorded as a gap, deliberately not replaced in 2d (spec A10.8): a Django-side guard with a new allowlist in a new home is real work unrelated to the cutover, and it is on the post-2d list beside the coverage re-scope.` with:

  `Recorded as a gap in 2d (spec A10.8) and closed after it by #<PR>, deliberately narrower than the scanner: `` `apps/proxy/tests/test_tune_path_query_ledger.py` `` pins, from a cold cache, the exact multiset of queries the authorize hop, next-source (first tune and reuse) and release run, keyed by table and by settings-group key, and pins that `` `config.py` `` and `` `config_helper.py` `` import no model but `` `CoreSettings` ``. The scanner itself was not relocated: those modules read the ORM by design now, so a line-keyed allowlist of their 62 reads would go red when lines move rather than when a read is added.`
- [ ] **Step 2.** `manage.py test --keepdb apps.proxy.tests -v1`. Assert `^OK`.
- [ ] **Step 3.** Commit, push, open the PR.

**PR description draft**

```
test(fixplan-J): J-3 -- the tune-path query ledger replaces Gate 1's Django-side ratchet

## What
Gate 1's static ORM scanner went with apps/proxy/live_proxy/ at 2d-4 and nothing replaced its
scope-2 walk over next_source, authorize, authorize_views, config and config_helper (spec A10.8,
A16.12 item 3). This adds apps/proxy/tests/test_tune_path_query_ledger.py:

- four drives (authorize hop, next-source first tune, next-source reuse, release), each pinned to
  the exact multiset of queries it runs from a cold cache;
- one static pin: config.py imports CoreSettings in get_proxy_settings and nothing else from a
  models module; config_helper.py imports none.

## Why not relocate the scanner
Measured at a54b09a9 its rule flags 62 sites in these five modules (46 in next_source.py). They
all read the ORM by design now, and a line-keyed allowlist goes red when lines move. See plan R2.

## Measured ledger
<the four drives, as typed into LEDGER, and any difference from the plan's seed table with the commit that caused it>

## Break-checks
<the four failure lines from Task 3>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## PR J-4 — the isolated coverage driver forwards every flag

- **Branch:** `fix/J-4-isolated-coverage-flags`.
- **Closes:** no tracker issue (found by 2d-4's implementer, never filed).
- **Labels:** `tests`, `apps.proxy.tests`, `apps.channels.tests` (the last two from the `scripts/coverage_live_path` alias, `dispatcharr/test_discovery.py:53`).
- **Files:** modify `scripts/coverage_live_path_isolated.sh`; create `tests/test_coverage_isolated_dropped_shape_only.py`.

### Task 1: the failing test

- [ ] **Step 1.** Create `tests/test_coverage_isolated_dropped_shape_only.py`:
  ```python
  """scripts/coverage_live_path_isolated.sh forwarded only its first argument.

  The last docker exec built `coverage_live_path.sh ${1:---report} /tmp/combined`,
  so `--write-floor --shape-only` arrived as `--write-floor`: a FULL floor write,
  which records `missing` from one local round. The floor's rule is that
  `missing` comes only from a >=12-round CI census. It was caught only because
  the usual containers mount /repo read-only.

  docker is stubbed on PATH so no container is needed: the stub records every
  call, and the last one is the in-container report/gate/write command.
  """

  import os
  import pathlib
  import subprocess
  import tempfile

  from django.test import SimpleTestCase

  REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
  SCRIPT = REPO_ROOT / "scripts" / "coverage_live_path_isolated.sh"
  STUB = '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$DOCKER_STUB_LOG"\nexit 0\n'


  class IsolatedCoverageForwardsEveryFlagTests(SimpleTestCase):
      def _final_call(self, *args):
          with tempfile.TemporaryDirectory() as tmp:
              tmp = pathlib.Path(tmp)
              (tmp / "bin").mkdir()
              docker = tmp / "bin" / "docker"
              docker.write_text(STUB)
              docker.chmod(0o755)
              log = tmp / "docker.log"
              env = {
                  **os.environ,
                  "PATH": f"{tmp / 'bin'}:{os.environ['PATH']}",
                  "DOCKER_STUB_LOG": str(log),
                  "COVERAGE_ISOLATED_OUT": str(tmp / "out"),
                  "COVERAGE_ISOLATED_PREFIX": "stub",
              }
              proc = subprocess.run(
                  ["bash", str(SCRIPT), *args], env=env,
                  capture_output=True, text=True, timeout=60,
              )
              self.assertEqual(proc.returncode, 0, proc.stderr)
              return log.read_text().splitlines()[-1]

      def test_isolated_coverage_dropped_every_flag_after_the_first(self):
          self.assertIn(
              "coverage_live_path.sh --write-floor --shape-only /tmp/combined",
              self._final_call("--write-floor", "--shape-only"),
          )

      def test_no_argument_still_means_report(self):
          self.assertIn(
              "coverage_live_path.sh --report /tmp/combined", self._final_call()
          )

      def test_gate_is_forwarded_unchanged(self):
          self.assertIn(
              "coverage_live_path.sh --gate /tmp/combined", self._final_call("--gate")
          )
  ```
- [ ] **Step 2.** Run `manage.py test --keepdb tests.test_coverage_isolated_dropped_shape_only -v2` in your container. Expect the first test to **FAIL**, its message showing `…coverage_live_path.sh --write-floor /tmp/combined`. Expect the two controls to pass.

### Task 2: the fix

- [ ] **Step 1.** In `scripts/coverage_live_path_isolated.sh`, after the `PAIRS` array (`:25-28`), add:
  ```bash
  # Every argument is forwarded to the in-container script, not just the first.
  # Until fix plan J-4 the final call was `${1:---report} /tmp/combined`, so
  # `--write-floor --shape-only` arrived as a FULL --write-floor -- one that
  # records `missing` from this single local round, which the floor's rule
  # forbids. No argument still means --report.
  if [ "$#" -eq 0 ]; then set -- --report; fi
  FORWARD="$(printf '%q ' "$@")"
  ```
- [ ] **Step 2.** At `:76`, change `case "${1:---report}" in` to `case "$1" in` (the default is now applied above). Leave `:78`'s `${1}` as is.
- [ ] **Step 3.** At `:104`, change `bash scripts/coverage_live_path.sh ${1:---report} /tmp/combined"` to `bash scripts/coverage_live_path.sh ${FORWARD}/tmp/combined"`. `printf '%q '` leaves a trailing space, so there is exactly one space before `/tmp/combined`.
- [ ] **Step 4.** Re-run the test module. All three pass. Run `bash -n scripts/coverage_live_path_isolated.sh` and, if installed, `shellcheck scripts/coverage_live_path_isolated.sh` (no new findings against the seed's).
- [ ] **Step 5. Break-check.** Restore `${1:---report}` at `:104` only. The first test must fail again with the `--write-floor /tmp/combined` line. Revert.
- [ ] **Step 6.** Run `manage.py test --keepdb tests.test_ci_test_routing -v1`: it already pins this script's routing (`tests/test_ci_test_routing.py:71`) and must stay green.
- [ ] **Step 7.** Commit (separate stage and commit calls), push, open the PR.

**PR description draft**

```
fix(fixplan-J): J-4**PR description draft**

```
fix(fixplan-J): J-4 -- coverage_live_path_isolated.sh forwards every flag

## The bug
The isolated driver's final call was `coverage_live_path.sh ${1:---report} /tmp/combined`, so
`--write-floor --shape-only` ran as a full `--write-floor`: a floor write that records `missing`
from one local round. The Gate 2 floor's rule is that `missing` comes only from a >=12-round CI
census. Found by the 2d-4 implementer; it was masked because the containers mount /repo read-only.

New tests/test_coverage_isolated_dropped_shape_only.py stubs docker on PATH and asserts the
forwarded command. The first test failed before the fix and passes after; two controls pass on
both sides. Break-check: restoring `${1:---report}` turns it red again.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## Prototype verification at the seed

The three new test modules were extracted verbatim from this plan and run at `a54b09a9` in a
dedicated container (`fixplan-J`), then deleted before commit:

| run | result |
|---|---|
| all three modules, seed tree | 10 tests; exactly two red: J-2's surviving-set test (the 25 names) and J-4's `--shape-only` test (`… --write-floor /tmp/combined`); J-3's five green |
| J-2 Task 2's `redis_keys.py` and J-4 Task 2's three edits applied | J-2, J-4 and `apps.channels.tests.test_get_stream_assignment`: 12 tests, `OK`; `bash -n` clean; `manage.py check` unchanged from the seed |
| J-3 break-checks (a), (b) at `:383`, (c), (d) | each red with the message quoted in Task 3; (b) at `:401` stayed green, which is why the plan names `:383` |

J-2's break-check (c) (a cycling import) was not re-run; its symptom is the one CLAUDE.md records as
measured on the 2d-1 branch.

## Decision memos

None. No item in category J is on the brief's policy list (#82, #94, #16, #277, #109, #133). R2
(the ratchet's shape) and R5 (keeping `m3u8`) are judgement calls with a recommendation each; Q1
and Q2 below let the user overrule them before implementation.

---

## Coverage table

| input item | tracker | disposition |
|---|---|---|
| 1 — Django-side ORM ratchet | — | PR J-3 (R2) |
| 2 — dead `RedisKeys` builders | — | PR J-2 (R3) |
| 3 — delete `apps/proxy/hls_proxy/` | **#336** (+ CodeQL #105, and alerts #64, #65, #66, #81, #82 with no issue) | PR J-1 (R7, R8) |
| 4 — `docker/nginx.conf` canary comment | — | PR J-1 Task 4 |
| 5 — three shim docstrings | — | PR J-2 Task 3 |
| 6 — isolated script drops `--shape-only` | — | PR J-4 Tasks 1-2 |
| 7 — `docs/comparisons/` dataset | — | **out of scope** by user ruling 2026-09-23 (R6); stays untracked |
| 8 — CLAUDE.md sentences | — | J-1 Task 6 (seven), J-2 Task 4 (one), J-3 Task 4 (one); `:105` checked and left |

**Tracker notes for the lead (deferred writes).** #336 closes via J-1; remove `needs-triage` and
`re-triage` at close. No duplicates in this category.

**Left deliberately, recorded so they are decisions:** `scripts/coverage_live_path.coveragerc:21`'s
"the dead hls_proxy" clause (R4); `apps/proxy/relay_client.py:14-20`'s present-tense `live_proxy`
prose (J-2 Task 3); `apps/proxy/apps.py:8-14` (past tense, still true); the `m3u8` dependency (R5).

---

## Open questions

- **Q1 — the ORM ratchet's shape.** This plan builds a runtime query ledger over four tune-path
  drives plus a narrow static pin (R2). The alternative is the literal reading of A16.12: relocate
  the static scanner and its line-keyed allowlist, which is about 62 entries. That is a different
  PR of roughly three times the size. Default if unanswered: R2.
- **Q2 — drop `m3u8`?** R5 keeps it for plugin compatibility. Dropping it is a separate one-line
  PR touching `pyproject.toml` and `uv.lock`, which runs every backend label.
