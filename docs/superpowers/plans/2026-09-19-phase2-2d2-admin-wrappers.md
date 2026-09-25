# Phase 2 Stage 2d-2 — the admin wrappers relocation

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the five `IsAdmin` control views the admin Stats UI drives — `change_stream`, `channel_status`, `stop_channel`, `stop_client`, `next_stream` — and the six URL patterns that register them out of `apps/proxy/live_proxy/`, so that the whole admin control surface survives stage 2d-4's deletion of that directory with no route re-created from memory and no behaviour changed.

**Architecture:** Two new modules under `apps/proxy/`, in `relay_views.py`/`relay_urls.py`'s idiom: `ts_admin_views.py` takes the five function bodies verbatim, `ts_admin_urls.py` takes the six patterns with their `name=` strings unchanged, and `apps/proxy/urls.py` mounts it at the same `ts/` prefix ahead of the `live_proxy` include that still carries `stream/`. `apps/proxy/live_proxy/views.py` loses 522 lines and **not one import** (R3 — removing the orphaned ones moves six Gate 1 SITES and stales twenty prose citations, measured). Gate 1 loses two `EdgeEntry` rows whose only importers left the package. The test file for those five views moves with them and gains the permission pin nothing in the tree ever carried (R9).

**Tech Stack:** Python 3.13 / Django 6 / DRF; no new dependency, no migration, no Go, no `docker/` edit, no workflow edit, no frontend edit, no nginx edit. `coverage` 7.16.0 for the Gate 2 probe; `manage.py check` and `manage.py spectacular` for the two shape proofs.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` — § Stage 2d's `### Deletion order — one PR each` entry **2**, Amendment **A10.3** (its closing paragraph assigns these five to 2d-2 and names `apps/proxy/live_proxy/urls.py:8-13`), **A10.11** (the seven `relay_client` call sites inside the five — corrected in place here, see R12), **A10.14** (the four `apps.proxy.tests` files — one import count corrected here). This PR adds **Amendment A12** and its Done-log row.

**Seed:** `d5be64d58940eeb4a3ad3e6af0bd2e6c1eb32410` — `relay(phase2): 2d-1 — the boot-trap relocation (#325)`. Every `file:line`, count, hash and expected output below was measured at that commit. The plan was first written against `57618a28`, the commit before 2d-1 merged, and **re-seeded here against 2d-1's merge**: every appendix was re-applied to `d5be64d5` and re-run, and the figures 2d-1 moved are marked below with what they were and what they are.

## Re-seeded against 2d-1's merge

**Stage 2d-1 merged as `d5be64d5` (PR #325).** This plan was written against `57618a28`, the commit before it, and its header promised a re-seed; this section is that re-seed, run rather than reasoned. Every appendix was re-applied to `d5be64d5` and every figure re-measured. **Nothing in the plan's rulings changed and no appendix needed regenerating** — the three predictions that mattered all held:

- Appendix D applies to the real post-2d-1 `zero_orm_allowlist.py` **cleanly, at offset −20 on all three hunks**, which is what the plan predicted to the line.
- Appendices F and G — the two verbatim-string scripts written specifically because 2d-1 edits their files — run with all seven `count == 1` assertions holding, and their anchors place Amendment A12 **after** A11 (`:3708` against `:3588`) and the 2d-2 Done-log row **immediately after** 2d-1's (`:4276` against `:4275`), without this plan ever naming either.
- The five views and their six patterns are untouched by 2d-1: `live_proxy/views.py` is still 1417 lines with the same 26 imports and the same five `def` line numbers, so Appendices A and C hold verbatim.

What 2d-1 actually did to this PR's files, verified at `d5be64d5` rather than read from its plan:

| This PR's file | 2d-1 touched it? | Verified consequence at `d5be64d5` |
|---|---|---|
| `apps/proxy/live_proxy/views.py` | **No** | Confirmed: still **1417 lines**, **26** imports, the five `def`s still at `:901`, `:1088`, `:1152`, `:1194`, `:1242`, `@csrf_exempt` still at `:898`. Appendix C applies unchanged and every line number in R1–R6 holds. |
| `apps/proxy/live_proxy/urls.py` | **No** | Appendix B.2 accepted by `git apply --check` at `d5be64d5`. |
| `apps/proxy/urls.py` | **No** — 2d-1 listed it under "deliberately not touched" (A10.3 site 6, 2d-4's) | Same hunk, accepted. |
| `apps/proxy/tests/test_stream_switch.py` | **No** — 2d-1's R5 explicitly left `:12`/`:13` alone | Appendix B.3 accepted. |
| `apps/proxy/live_proxy/tests/zero_orm_allowlist.py` | **Yes**, in seven places — one `Site` deleted at `:111-130`, one `EdgeEntry` re-pointed (now `apps.proxy.config_helper`/`ConfigHelper`, `hits=1`, at `apps/proxy/config_helper.py:66`), six prose citations rewritten | **Measured**: `git apply` accepts Appendix D with `Hunk #1 succeeded at 257 (offset -20 lines)` and the same −20 on #2 and #3 — the offset the plan predicted, to the line. The two `views.py` `EdgeEntry` rows moved `:281`→**`:261`** and `:322`→**`:302`**, and `channel_service.py`'s `:365`→**`:345`**, so the range Task 4 deletes is now **`:260`–`:343`** rather than `:280`–`:363`. Twelve `importer=` lines still, and the re-pointed `config_helper` entry sits at `:427`, well below every hunk. |
| `CLAUDE.md` | **Yes** — § Test hooks and § Structural constraints | Different sentences from this PR's. Appendix F ran at `d5be64d5` with both `count == 1` assertions holding: `CLAUDE.md: 2 replacements`. Writing it as a verbatim-string script rather than a hunk is what made that a non-event. |
| `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` | **Yes** — Amendment A11, in-place corrections to deletion-list entries 1 and 4, A10.14 rewritten to eleven files across two labels, a Done-log row | Appendix G ran with all five `count == 1` assertions holding: `spec: 5 edits`. The anchors did their job — **A12 landed at `:3708`, after A11 at `:3588`**, and the 2d-2 Done-log row at `:4276`, **immediately after** 2d-1's at `:4275`, without this plan naming either. |

None of the four names 2d-1 relocated — `RedisKeys`, `ChannelMetadataField`, `ChannelState`, `ConfigHelper` — is used by any of the five views this PR moves. Re-measured at `d5be64d5`: `sed -n '898,1417p' … | grep -E "\b(RedisKeys|ChannelMetadataField|ChannelState|ConfigHelper)\b"` returns **nothing, exit 1**. (`views.py` still imports all three in-package names at module level, from 2d-1's shims, but only `stream_ts` and its helpers use them.) **So there is no import in this PR that must be re-pointed at 2d-1's new homes, and nothing this PR writes may import `apps.proxy.live_proxy.{redis_keys,constants,config_helper}` under either spelling.**

## Global Constraints

Every task's requirements implicitly include all of these. A conflict with any is a **STOP and report**, not an amendment you make yourself.

1. **Branch: `migration/phase2d-admin-wrappers`.** The `migration/**` prefix is load-bearing — it bypasses the E2E path filters and runs every Playwright project plus both bash suites in `lifecycle-tests.yml`. Ten E2E specs drive the views this PR moves (R10); that gate is the point.
2. **No behaviour change.** Same resolved paths, same URL-pattern `name=` strings, same permission class, same HTTP methods, same request parsing, same response bodies, same status codes, same log lines, same logger name. The two proofs are mechanical and both are in Task 6: the generated OpenAPI schema must be **byte-identical**, and the `/proxy/ts/` resolver dump must differ in the view module and the app namespace and in nothing else.
3. **No route added, removed, or re-ordered relative to any other route.** Six patterns move; the seventh (`stream/`) stays where it is.
4. **Do not edit `apps/proxy/live_proxy/**` beyond the two files Tasks 3 and 4 name** (`views.py`, `tests/zero_orm_allowlist.py`) and the `git mv` of Task 5. 2d-4 deletes that directory; every other edit there is churn on a corpse. This is 2d-1's Constraint 5, carried.
5. **Do not remove a single import from `apps/proxy/live_proxy/views.py`,** including the five the move orphans. R3 is the measurement; it costs six Gate 1 `lineno` edits and stales about twenty prose citations in the allowlist, for nothing.
6. **Do not edit `scripts/coverage_live_path.{sh,coveragerc,floor,floor.modules}`.** R7 is why. If `--gate` fails, that is a **STOP and report**, not a re-baseline.
7. **Do not edit `docker/`, `.github/workflows/`, `frontend/`, `e2e/`, `relay/`, `metrics/curated/` or `docs/relay-parity-matrix.md`.** Each was checked and none of them needs to move (R11); if you believe one does, stop and report rather than editing it.
8. **Do not touch `dispatcharr/settings.py`, `dispatcharr/urls.py`, `apps/proxy/apps.py`, `apps/proxy/tasks.py`, `apps/proxy/relay_views.py`, `apps/proxy/relay_urls.py`** — A10.3 sites 1, 3, 5, 7, 9, all 2d-4's. **Site 6 is the exception and it is deliberate:** `apps/proxy/urls.py:10`'s `include('apps.proxy.live_proxy.urls')` is A10.3's site 6 and stays 2d-4's one-line deletion — this PR touches that file **by addition only**, adding a second `ts/` include above it (Task 2) and changing nothing else in it. If you find yourself editing or removing line 10, stop: that is 2d-4's, and Task 2 Step 3's six-line `path(` check is what catches it.
9. **`scripts/check_credential_logging.py` stays at zero findings** for every `*.py` this PR touches. Measured zero on the finished shape.
10. **A channel UUID and a provider URL are secrets.** Nothing this PR adds may print either. The one moved line that formats a URL already goes through `redact_url`, and it stays that way.
11. **Do not use the shared `dispatcharr-testrunner` container.** Start your own, named for this PR, and remove it and its volume when you finish. The `PostToolUse` hook does not see `DISPATCHARR_TEST_CONTAINER` and always uses the shared name against whichever worktree it is mounted at; its refusal on a mount mismatch is correct behaviour, not a problem to work around.
12. **Stage and commit in separate Bash calls.** Write commit messages with the Write tool and commit with `git commit -F <file>`; one command containing both `git` and `commit` plus a heredoc trips the commit gate, and so does a heredoc whose text merely contains those two words.
13. **`gh` always with `--repo D10Scot/Dispatcharr`.**
14. **Anchor every command with an absolute path or a leading `cd <your worktree> &&`.** The shell cwd is shared or correlated across concurrent agents.
15. **`set -o pipefail` on any pipeline whose emptiness or exit status you intend to read**, and never `2>/dev/null` a git query you plan to interpret. Never pipe a `manage.py test` run — redirect it to a file and read `$?` and `^OK` separately.
16. **If the tests did not run, say they did not run.** Never describe unverified work as verified.

---

## Rulings

Each was measured at the seed, with the command that produced it. Five of them were changed by running the thing rather than reading it, and each says so.

### R1 — Two new modules, `ts_admin_views.py` and `ts_admin_urls.py`, in `relay_views.py`/`relay_urls.py`'s idiom

The five views go to **`apps/proxy/ts_admin_views.py`** and the six patterns to **`apps/proxy/ts_admin_urls.py`**.

`apps/proxy/` already has exactly this shape for exactly this kind of thing: `relay_urls.py` (33 lines, `app_name = "relay_control"`, four patterns) is included from `apps/proxy/urls.py:9` and points at `relay_views.py`. A second `<surface>_urls.py`/`<surface>_views.py` pair is the tree's own spelling, not an invention.

`ts_` rather than `admin_` because the prefix these six routes live under is `ts/` and because `apps/proxy/` will still hold a VOD and a catch-up admin surface after 2d-4; `admin_views.py` would claim a name three surfaces could want. Neither basename exists at the seed (`ls apps/proxy/*.py` lists 23 files; `ts_admin_views.py` and `ts_admin_urls.py` are not among them).

**Not one module.** The views module is 577 lines and imports `apps.proxy.next_source`, which imports `apps.channels.models`; the urlconf module is 31 lines and must be importable by `apps/proxy/urls.py`. Keeping them apart is what makes the urlconf readable as a table.

**Not `apps/proxy/views.py`.** That file exists (it holds a `proxy_server.stop_channel(channel_id)` call at `:52`) and is not this surface.

### R2 — The urlconf splits, the paths and `name=` strings are byte-identical, and the app namespace changes

`apps/proxy/urls.py` gains **one line**, immediately before the existing `ts/` include:

```python
    path('ts/', include('apps.proxy.ts_admin_urls')),
    path('ts/', include('apps.proxy.live_proxy.urls')),
```

and `apps/proxy/live_proxy/urls.py` drops six of its seven patterns, keeping `stream/`.

**Two includes on the same prefix resolve correctly, and the order is a readability choice rather than a correctness one.** Django's `URLResolver.resolve` collects the `Resolver404` from a non-matching include and continues to the next pattern, so `/proxy/ts/stream/<uuid>` falls through the new include to the old one. Measured, not assumed — break-check **BC-4** (Task 7) swapped the two lines and ran `apps.proxy.tests.test_admin_control_views`: `Ran 25 tests ... OK`. The order in the appendix is `ts_admin` first so that 2d-4, which deletes the second line with the directory, is a one-line deletion that leaves a correct file.

**What is byte-identical across the move**, measured by the `/proxy/ts/` resolver dump of Task 0 Step 5 and Task 6 Step 2:

| | before | after |
|---|---|---|
| path | `/proxy/ts/status`, `/proxy/ts/status/<str:channel_id>`, `/proxy/ts/stop/<str:channel_id>`, `/proxy/ts/stop_client/<str:channel_id>`, `/proxy/ts/change_stream/<str:channel_id>`, `/proxy/ts/next_stream/<str:channel_id>` | identical |
| `name=` | `channel_status`, `channel_status_detail`, `stop_channel`, `stop_client`, `change_stream`, `next_stream` | identical |
| permission classes | `IsAdmin` on all six | identical |
| view module | `apps.proxy.live_proxy.views` | `apps.proxy.ts_admin_views` |
| namespace | `proxy:live_proxy:<name>` | `proxy:ts_admin:<name>` |

**The namespace is the one thing that changes, and nothing consumes it.** Two measurements, and the second is the decisive one. `grep -rn "reverse(" apps/ core/ dispatcharr/ tests/` returns **21** hits tree-wide, **two** of them in `apps/proxy/`, and neither of those two names any of these six (`test_authorize_internal_view.py:89`'s `reverse("authorize-internal")` and an unrelated `list.reverse()`); none of the other nineteen names a `live_proxy` route either. More directly: `git grep -n "live_proxy:"` over the whole tracked tree returns **nothing** outside this plan document, so no namespaced reverse of any of these names exists to break. `frontend/src/api.js` dials literal paths (`:2465`, `:2548`, `:2561`, `:2617`, `:3317`, `:3334`). The alternative — giving the new module `app_name = 'live_proxy'` to preserve the namespace — registers two resolvers under one instance namespace, where the later silently wins the `namespace_dict` entry and reverse lookups into the earlier one fail; a landmine bought to preserve a name nothing reads. Declined, and recorded in Amendment A12.2.

**The strongest evidence that the surface did not move is not the dump.** `manage.py spectacular` was run on the seed and on the finished shape and the two YAML files are **byte-identical** (`diff -q` → no output, exit 0; 12 `proxy/ts` lines on both). drf-spectacular walks the urlconf, resolves every callable and reads its permission classes, so an identical schema is a stronger statement than any hand-written assertion about six routes. Task 6 Step 1 is that diff.

### R3 — `live_proxy/views.py` keeps every import the move orphans, and this is the ruling running the label changed

The move leaves five module-level names unused in `views.py`: `json` (`:1`), `ImproperlyConfigured` (`:5`), `csrf_exempt` (`:14`), `send_websocket_update` (`:30`) and `IsAdmin` (`:24`, one name of a three-name import). The first draft of this plan removed all five. **Do not.**

Removing them deletes four whole statements and one name-line — **five lines above line 896** — and every Gate 1 `Site.lineno` in that file is an absolute line number. Measured, by making the edit and running the label:

```
FAIL: test_every_orm_site_in_the_relay_package_is_allowlisted
unlisted (add to SITES with a reason, or remove the read):
  apps/proxy/live_proxy/views.py:127   apps/proxy/live_proxy/views.py:147
  apps/proxy/live_proxy/views.py:439   apps/proxy/live_proxy/views.py:457
  apps/proxy/live_proxy/views.py:463   apps/proxy/live_proxy/views.py:761
listed but gone (delete the entry -- the ratchet runs both ways ...):
  apps/proxy/live_proxy/views.py:132   apps/proxy/live_proxy/views.py:152
  apps/proxy/live_proxy/views.py:444   apps/proxy/live_proxy/views.py:462
  apps/proxy/live_proxy/views.py:468   apps/proxy/live_proxy/views.py:766
```

Six SITES, every one of them shifted by exactly five. **Twenty-one edits, counted rather than estimated**, at the seed `d5be64d5`: the six `lineno=` assignments themselves (`zero_orm_allowlist.py:113`, `:135`, `:163`, `:198`, `:223`, `:243`) plus **fifteen** prose citations of those six numbers, one per line, at `:149`, `:150`, `:185`, `:186`, `:192`, `:193`, `:218`, `:486`, `:509`, `:518`, `:581`, `:590`, `:602`, `:644`, `:743`. Every one would go stale: the exact failure this programme keeps finding and 2d-1's R7 names. (`:462` and `:468` are cited nowhere in prose; `:444` is cited six times and `:152` five, which is what makes the tidy-up expensive rather than tedious.)

**Re-derive those twenty-one with the greps below rather than adjusting the numbers — the shift is not uniform.** 2d-1 moved most of this file up by twenty, but its own prose corrections below the deleted `Site` changed line counts locally, so two of the fifteen moved *down* by one instead (`:643`→`:644`, `:742`→`:743`) while the other thirteen moved up by twenty. Subtracting a constant produces two wrong citations and no error:

```bash
grep -nE "^        lineno=(132|152|444|462|468|766)," apps/proxy/live_proxy/tests/zero_orm_allowlist.py   # the six
grep -nE "views\.py:(132|152|444|462|468|766)" apps/proxy/live_proxy/tests/zero_orm_allowlist.py        # the fifteen
```

The six `views.py` line numbers those greps search for — 132, 152, 444, 462, 468, 766 — are the ones that **do not** move, because `views.py` is not a file 2d-1 touches. Deleting the five *functions* shifts nothing, because all six SITES are above line 898.

So: **`views.py` loses lines 896–1417 and nothing else.** Five unused imports ride along in a file 2d-4 deletes wholesale. Note that **four names in that import block were already unused at the seed, before this PR touches anything** — `re` (`:3`), `UUID` (`:37`), `permission_classes_by_method` and `permission_classes_by_action` (`:25-26`) — so a tidy-up here would not even be a tidy-up of this PR's making. Recorded as a finding, not fixed.

### R4 — Three `live_proxy` dependencies, three different answers, and only one survives as an import

The five views reach thirteen module-level names in `views.py`. Ten are Django, DRF or first-party-but-not-`live_proxy` (`json`, `ImproperlyConfigured`, `close_old_connections`, `JsonResponse`, `Http404`, `csrf_exempt`, `api_view`, `permission_classes`, `IsAdmin`, `redact_url`, `send_websocket_update`) and move as ordinary imports. Three come from inside the doomed package, and they get three different treatments.

**(i) `get_stream_object` is not a `live_proxy` symbol at all.** `views.py:31-35` imports it from `.url_utils`, but `url_utils.py:24` is a re-export: the definition is `apps/proxy/next_source.py:244`, and `url_utils.py:18-23`'s own comment says the re-export is permanent for the benefit of callers that "should not have to learn that it moved." The new module imports it **from its definition site** — `from apps.proxy.next_source import get_stream_object` — and reaches the same function object. Zero `live_proxy` coupling, and `apps.proxy.next_source` is one of Gate 2's ten surviving boundary modules.

**(ii) `logger` becomes `logging.getLogger("live_proxy.views")`.** `views.py:48`'s `get_logger()` (`live_proxy/utils.py:102-122`) derives its name from the *calling module's* basename, so all five views log to `live_proxy.views` today. Importing `get_logger` into a surviving module would re-create the coupling for a naming convenience; deriving a new name would change every log line the move carries. Naming it literally is `apps/proxy/next_source.py:34-38`'s precedent applied one level down — that module took `logging.getLogger("live_proxy")` for this exact reason, in its own words "so every moved line still logs to the stream it logs to today." `live_proxy` is not a configured logger in `settings.LOGGING`; both spellings reach the same root handler at the same level, so the only difference a rename would make is the `{name}` field, and this PR makes none. Renaming it once the directory behind the name is gone is 2d-6's, and A12.4 says so. The moved test asserts through `assertLogs(views.logger, ...)` at five places, which takes the `Logger` object and is indifferent to its name — so this ruling is a deliberate choice, not one a test forced.

**(iii) `ProxyServer` stays, function-local, and is this PR's one handover to 2d-4.** `change_stream` and `next_stream` open with `proxy_server = ProxyServer.get_instance()` and use it for exactly one thing: `proxy_server.worker_id`, in four response bodies (`views.py:1039`, `:1053`, `:1381`, `:1394`). `worker_id` is `f"{hostname}:{pid}"`, set at `server.py:96-98`. Three options were weighed:

- *Module-level import in the new module* — rejected: it adds a **tenth** module-level `apps.proxy.live_proxy` import site (A10.3 enumerates nine) in a file that exists to survive the directory's deletion. That is the thing this stage is for.
- *Compute `f"{socket.gethostname()}:{os.getpid()}"` locally* — rejected: it is the same string in the deployment shapes that matter and **not provably** the same one in a shape where the singleton was constructed before a fork. "No behaviour change" is Constraint 2, and a reimplementation is a change whose equality is an argument rather than an identity.
- **Function-local import, chosen** — the idiom this very file already uses for `relay_client` and `next_source`, with the same D10 reasoning. Two sites: `ts_admin_views.py:58` and `:402`. The `ProxyServer.get_instance()` call keeps its **position** as the first statement of each view, so the singleton is constructed at exactly the point it is today, including on the paths that never read `worker_id` (the 400 for a non-integer `stream_id` is one).

That is the whole of this PR's handover to 2d-4: **two function-local imports of `apps.proxy.live_proxy.server` in one surviving file**, which 2d-4 closes by deciding what `worker_id` means once there is no Python relay. A12.3 records it so 2d-4's plan does not discover it.

### R5 — The function-local `relay_client` and `next_source` imports stay function-local, and that is load-bearing

Seven function-local imports travel with the five views: `from apps.proxy import relay_client` ×5, `from apps.proxy.next_source import resolve_source` ×2, `from apps.proxy.next_source import channel_stream_profile_ref` ×1. They stay exactly where they are, at the same position in each body.

This is not tidiness. `apps/proxy/tests/test_admin_control_views.py` patches `"apps.proxy.next_source.resolve_source"` **by module path** at four places (`:108`, `:146`, `:259`, `:289`), which only reaches the view because the import is late-bound. Break-check **BC-3** (Task 7) hoisted it to module level and the label went red — `AssertionError: 500 != 200` in both `change_stream` tests. Measured.

### R6 — Gate 1: two `EdgeEntry` rows die, no `Site` moves, the runtime half is untouched, and one surviving entry's prose needs fixing

Nothing in § Stage 2d or Amendment A10 anticipates a Gate 1 consequence for 2d-2. There is one, it is real, and it was found by running the label rather than by reading the allowlist.

**(i) No `Site` changes.** `zero_orm_allowlist.py`'s six `Site` entries with `path="apps/proxy/live_proxy/views.py"` are at `lineno` 132, 152, 444, 462, 468 and 766 — every one of them inside `stream_ts` or a module-level helper, none inside the five views. `next_stream`'s `channel.streams.all().order_by(...)` (`views.py:1280`) is not a `Site` because `zero_orm_scan`'s shapes do not flag a related-manager call. Constraint 5 is what keeps these six where they are.

**(ii) Two of the five `EdgeEntry` rows whose `importer` is `views.py` lose their only importer.** `import_edges()` walks every first-party `ImportFrom` in the package, function-local ones included, and `test_every_in_process_import_edge_is_allowlisted` is a bare `assertEqual(found, allowed)` — a stale entry fails it with a set difference and no message.

| module.name | hits | pr | only importers in `views.py` | disposition |
|---|---|---|---|---|
| `apps.proxy.next_source.channel_stream_profile_ref` | 7 | `2c-8` | `:980`, inside `change_stream` | **delete** |
| `apps.proxy.next_source.resolve_source` | 39 | `2b-3` | `:943` (`change_stream`), `:1325` (`next_stream`) | **delete** |
| `apps.proxy.authorize.resolve_output_format` | 1 | `2b-2` | `_resolve_output_format`, `views.py:114` | keep |
| `apps.proxy.authorize.resolve_output_profile` | 2 | `2b-2` | `_output_profile_for`, `views.py:136` | keep |
| `apps.proxy.authorize_views.resolve_authorization` | 1 | `Phase 1 PR 5` | `stream_ts` | keep |

`apps.proxy.relay_client`, which all five views import function-locally, is not in `EDGES` at all — the test filters on `if zero_orm_scan.scan_edge(e)` and that subtree reaches no ORM — so its departure is invisible.

**This is a narrowing of Gate 1's static reach, and it is the right narrowing.** Both deleted entries' own `reason` text already said the read runs in the API process: the `channel_stream_profile_ref` entry ends "IN THE API PROCESS EITHER WAY: PR 4's routing put change_stream on the api role, so this import is not executed in the relay process at all." 2d-2 makes the file layout say what the process layout already said. The runtime half is unaffected and was checked rather than assumed: `test_zero_orm_reads.py`'s five drives are `/proxy/ts/stream/` tunes (`:373`, `:409`, `:574`) and `internal_get` calls on `/proxy/relay/…` (`:451`, `:477`) — **none of them reaches any of the five views**, so no query's stack-frame attribution changes.

**(iii) One surviving entry cites the deleted one twice, and the first draft left both dangling.** The `channel_service.py` → `resolve_source` entry opens "The same symbol as the views.py edge **above**" and closes `closed_by="As the views.py edge above -- ..."`. Both are rewritten in place by Appendix D, and a block comment replaces the deleted rows so the deletion is legible to whoever reads `EDGES` next.

**(iv) A first-draft error worth recording, because the same mistake is easy to repeat.** Deleting "the two `views.py` entries" by line range deleted **three**: the `channel_service.py` entry begins at `:364` and the second `views.py` entry ends at `:363`, and the label reported `('apps/proxy/live_proxy/services/channel_service.py', 'apps.proxy.next_source', 'resolve_source')` as found-but-not-allowed. The exact range was `:280`–`:363` at the pre-2d-1 seed and is **`:260`–`:343`** at `d5be64d5`, which is the point: Task 4 Step 1 derives it from the file rather than quoting either number, and asserts on the three boundary lines before touching anything.

### R7 — Gate 2: `modules=` cannot move, `statements` falls by 216, `missing` cannot rise, and this PR ships no floor edit

The new modules land **outside** Gate 2's denominator and both old files stay inside it, so the resolved file set — which is what `modules=` hashes — cannot move.

**(a) coverage's own matcher.** Running coverage 7.16.0's `prep_patterns` + `GlobMatcher` over `scripts/coverage_live_path.coveragerc:23-34`'s `[report] include`:

```
apps/proxy/ts_admin_views.py         False
apps/proxy/ts_admin_urls.py          False
apps/proxy/live_proxy/views.py       True
apps/proxy/live_proxy/urls.py        True
```

The two new files are outside the ten named boundary modules and outside `apps/proxy/live_proxy/*`; the two edited files still match.

**(b) the cheap file-set probe** (2d-1's Task 7 Step 2 method, reused — `[run] source = apps/proxy` triggers coverage's unexecuted-file walk, so the resolved set is a property of the tree and a `coverage run` over a no-op script reproduces it in seconds):

| tree | digest | files | statements |
|---|---|---|---|
| seed `d5be64d5` | `8cb5c65dac3e` | 38 | **7983** |
| this PR's shape | `8cb5c65dac3e` | 38 | **7767** |
| (pre-2d-1, for provenance) `57618a28` → its shape | `8cb5c65dac3e` | 38 | 8202 → 7986 |

`8cb5c65dac3e` / 38 is `scripts/coverage_live_path.floor`'s own `modules=`/`module_count=`. The 216-statement drop is exactly the five views' statement count, measured independently with `coverage.parser.PythonParser`: `views.py` holds 620 statements, 216 of them in lines 898–1417 and 404 below. `live_proxy/urls.py` contributes nothing to the move — `urlpatterns = [...]` is one statement whether it holds one pattern or seven. `rcfile=` cannot move: the rcfile is not edited (Constraint 6).

**The drop is 216 on either tree, because it is the five views' own statement count and nothing else.** 2d-1 moved the baseline from 8202 to 7983 — its three shims hold 1, 25 and 1 statements where the originals held 85, 88 and 73 — and left the digest alone, because a shim still matches `apps/proxy/live_proxy/*` and still carries a statement. `views.py` is untouched by 2d-1, so `PythonParser` still reports **620 / 216 / 404** on it. Task 0 Step 7 records what the probe actually prints; a digest that is not `8cb5c65dac3e` is a **STOP**.

**`missing` can only fall.** Every one of the 216 statements leaves the denominator carrying its own missing-or-covered status with it, and this PR adds no statement to any file inside the denominator (`urls.py` loses six list elements from one statement; `views.py` loses functions and gains nothing). So `missing` falls by however many of the 216 were uncovered and never rises. **And the floor is not lowered either**, for the reason `scripts/coverage_live_path.floor:277-283` gives: plain `--write-floor` writes one local run's figure where this floor's policy is the worst of ≥12 rounds measured in CI. 2d-5 (`migration/phase2d-gate2-recensus`) is the PR where `missing` legitimately moves. A drop bought by removing statements from the denominator is not a coverage improvement anyone should ratchet on — the identical argument 2d-1's R4 makes, one PR later.

### R8 — The tests follow the code, and A10.14's eleven stay eleven

`apps/proxy/live_proxy/tests/test_admin_control_views.py` (409 lines, **23 tests**) is the test file for these five views and nothing else; its docstring opens "The five IsAdmin views are wrappers now, and nothing else changed." It moves to `apps/proxy/tests/test_admin_control_views.py` with **one** line changed (`from apps.proxy.live_proxy import views` → `from apps.proxy import ts_admin_views as views`) and one class appended (R9).

The alternative — leaving it behind with a re-pointed import — puts the only test of a surviving surface inside the directory 2d-4 deletes, so 2d-4 would delete it or notice it in a red run. This is 2d-1's R6 one level down: the tests are part of the surface, and moving them is the cheapest thing in the PR.

**Everything the file patches keeps working after the move**, checked name by name: `mock.patch.object(views, "close_old_connections")` (`:39`) and `mock.patch.object(views, "send_websocket_update")` (`:172`) need those two to be module attributes of the new module, and they are; `mock.patch.object(relay_client, ...)` patches the shared module object and is indifferent to the importer; `assertLogs(views.logger, ...)` (`:356`, `:366`, `:376`, `:390`, `:405`) takes a `Logger` object; every request is made by URL through `APIClient`, and the URLs do not change.

`apps/proxy/tests/test_stream_switch.py:16`'s `from apps.proxy.live_proxy.views import change_stream` is re-pointed at the new module, and **only that line**. Its `patch.object(views_module.ProxyServer, "get_instance", ...)` at `:309` and `:332` keeps working untouched: that patches the `ProxyServer` **class** attribute, reached through whichever module happens to name the class, and `views.py` still imports `ProxyServer` for `stream_ts`.

**A10.14's count does not move.** Its `apps.proxy.tests` bullet lists four files; `test_stream_switch.py` drops from six `live_proxy` imports to five and stays on the list (its other five are `constants`, `redis_keys`, `services`, `services.channel_service` and `views` itself). The file arriving in that directory imports no `live_proxy` name at all after the move, so it does not join the list. 2d-1's R6 takes the list from thirteen files to eleven; 2d-2 leaves it at **eleven**, and corrects the one import count in place (A12.5).

Measured label counts, seed → this PR's shape:

| label | seed | after | delta |
|---|---|---|---|
| `apps.proxy.tests` | 403 | **428** | +25 (23 moved, 2 new) |
| `apps.proxy.live_proxy.tests` | 429 | **406** | −23 |
| `apps.channels.tests` | 441 | **441** | 0 |

All three green on both trees. Both affected labels are in `.github/workflows/backend-tests.yml:180`'s coverage matrix, so the moved tests stay inside Gate 2's combined measurement.

### R9 — Nothing in the tree pinned the permission class, and the PR whose gate is "permission classes unchanged" is the one to fix that

All 23 tests in `test_admin_control_views.py` authenticate as an admin (`setUp`, `:26-29`), and a tree-wide grep finds no test anywhere asserting a 401 or 403 on any of these six routes. **A move that dropped `IsAdmin` from any of the five views would have been green in every label**, and § Stage 2d entry 2's gate is exactly "keeping URLs, names and permission classes unchanged."

So this PR adds one class, `AdminControlPermissionTests`, two tests, six routes each, with `subTest` so the failure names the route. Measured behaviour at the seed, on all six: anonymous **401**, an authenticated `STREAMER` or `STANDARD` **403**.

**The break-check that matters here failed to fail, and that is disclosed rather than hidden.** Removing `@permission_classes([IsAdmin])` outright leaves the label **green** (BC-1, Task 7) — `dispatcharr/settings.py:325-327` sets `DEFAULT_PERMISSION_CLASSES` to the same `apps.accounts.permissions.IsAdmin`, so the decorator and its absence are the same behaviour. The new tests therefore pin the **effective authorization**, not the decorator, which is the right thing to pin and is not what a careless reading of them would say. The check that does bite is the realistic mistake: `IsAdmin` → `AllowAny`, the value sitting on `stream_ts`'s own decorator eleven lines away in the file being copied from. BC-2 reddens with `AssertionError: 503 != 401` and `route='/proxy/ts/stop/abc'`.

### R10 — E2E and nginx: nothing to edit, and ten specs drive the moved views

**No nginx change.** All six routes are API-process-bound today and stay so: `docker/nginx.conf:62`'s `location = /proxy/ts/status` and `:248`'s `location ^~ /proxy/` (whose own comment names "`/proxy/ts/{change_stream,status/<id>,stop,stop_client,next_stream}`, all short and IsAdmin") both `uwsgi_pass unix:/app/uwsgi.sock`. Only `^~ /proxy/ts/stream/` is relay-bound, and `stream_ts` does not move. nginx routes on paths, and no path changes.

**`e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts` is unaffected**: its third test lists `/proxy/ts/status` among thirteen Django-bound targets that must blank the trust params (`:330`), an assertion about `docker/nginx.conf`, which this PR does not touch.

**Ten specs exercise the moved views over HTTP**, which is what makes `E2E result` a real gate here rather than a formality: `e2e/fixtures/channel-status.ts:29`'s `readChannelStatus` GETs `/proxy/ts/status/<uuid>` and is imported by `streaming/single-client`, `streaming/shared-upstream`, `streaming/stream-profiles`, `streaming-failover/mid-stream-switch`, `streaming-failover/failover-dead-air`, `streaming-failover/failover-events`, `streaming-failover/failover-connect-failure`, `streaming-failover/failover-buffering` and `streaming-greybox/output-profile-sharing`; `streaming-failover/mid-stream-switch.spec.ts` POSTs `/proxy/ts/change_stream/`; and `seeded/ws-product-events.spec.ts` reads the collection form.

### R11 — `metrics/curated/`, the parity matrix and every other doc were checked and none moves

Each was measured, because "probably nothing" is how a red `pages.yml` run on `main` happens.

- **`metrics/curated/defects.yml`** — `grep -n "test_admin_control\|live_proxy/views" metrics/curated/*.yml` returns nothing, so no `test:` path this PR moves is cited and `metrics/build/curated.py:320-325` has nothing to fail on. A10.15's three at-risk rows are 2d-4's and none of them is this file.
- **`scripts/metrics/collect_architecture.py`** — `models_boot_trap_imports` counts module-level `apps.proxy.live_proxy` imports in `apps/channels/models.py` only, which this PR does not touch; `reverse_imports_into_proxy` counts non-test imports **outside** `apps/proxy/` that import from it, and every file this PR edits or creates is inside `apps/proxy/`. Neither number moves, so there is no catalogue note and no milestone row.
- **`docs/relay-parity-matrix.md`** — its four citations into `live_proxy/views.py` are `:162-166`, `:195-206`, `:825` and `:845-851` (rows 15 and 17), all below 896 and all inside `stream_ts`. Nothing to re-point. A10.5's column replacement stays 2d-4's.
- **Every other file in `docs/` citing a line ≥ 896 of that file** is a past plan or the Phase 1 spec (`2026-09-13-phase2-2c8-control-drain.md:2379`, `2026-09-11-phase2-2b1-names-and-profiles.md:1073`, `2026-09-04-phase1-process-split-design.md:107` and `:1429`). Plans are records of what was true when written and are not retro-edited; the standing convention. The **only** live document citing the moved range is the Phase 2 spec's A10.11 (`:3359` at `d5be64d5`; `:3344` before 2d-1 added Amendment A11 above it), corrected in place by Task 9.
- **`CLAUDE.md` § Known defects'** `channel_stream:*` bullet says "The relay still *reads* them directly (`live_proxy/views.py`)". Checked: `RedisKeys.channel_stream`/`stream_profile` are read at `views.py:433` and `:436`, inside `stream_ts`. The sentence stays true.

### R12 — Two CLAUDE.md sentences and three spec passages, corrected in this PR

Per the standing per-PR convention (§ Documentation, "a PR that changes a fact CLAUDE.md states should correct it in the same PR"; 2d-6 is the consolidation pass, not the only place).

- **`CLAUDE.md:50` (§ Commands)** — "the five `live_proxy/views.py` admin views answer with a fixed body ... while logging the variable name only". The file name changes.
- **`CLAUDE.md:93` (§ Routing)** — "**Every `live_proxy` endpoint is keyed by the channel's UUID *string*, never its numeric id** — all seven routes capture `<str:channel_id>`". Two things are wrong with it after this PR and **one was already wrong before it**: the seven routes now live in two urlconfs, and `path('status', ...)` has never captured `channel_id` at all (`channel_status(request, channel_id=None)`), so "all seven" was six even at the seed. The replacement says both accurately.
- **The spec's A10.11** (`:3359`) — the seven `relay_client` call sites move from `apps/proxy/live_proxy/views.py:1009, :1107, :1114, :1159, :1206, :1261, :1343` to `apps/proxy/ts_admin_views.py:166, :264, :271, :316, :363, :421, :503`. Both lists were verified line by line at the seed and on the finished shape.
- **The spec's A10.14** — the `apps.proxy.tests` bullet's `test_stream_switch.py (6)` becomes six-then-five (R8).
- **The spec's deletion list, entry 2** — widened in place to name what this PR actually owns, which is more than "move the wrappers": the urlconf split and its namespace change, the two Gate 1 `EdgeEntry` deletions, the test relocation, the permission pin, and the two function-local `ProxyServer` imports handed to 2d-4.

### R13 — Two known non-failures on this tree, and neither is this PR's

- **`test_a_buffering_threshold_change_does_not_reach_a_running_channel`** (`apps.proxy.live_proxy.tests.test_manager_stderr_failover`) is issue **#259**, carried from 2d-1's R12 — **with its stopping rule corrected, because 2d-1's implementer measured the rule itself and it was unsound.** On that host the test fails roughly **eight runs in ten on the unmodified tree**, so "three in a row is new, stop" would fire on a clean checkout more often than not. What this plan asks instead: **re-run; do not attribute it to this PR, and never lower the asserted count.** Escalate only if it fires **in CI**, or on a host where the same label has just been shown green on `origin/main` — a quiescent machine. Anything else is measuring the host's load, not the branch.

  This plan's own runs are a case in point and are recorded rather than generalised from: it fired once during the pre-2d-1 measurements and passed on **six** subsequent runs of that label across both seeds, including all four at `d5be64d5`. That is the same distribution seen from the other side; neither sample says anything about the code.
- **`manage.py check` reports one warning in the test container, before and after**: `?: (staticfiles.W004) The directory '/repo/frontend/dist' in the STATICFILES_DIRS setting does not exist.` Exit code 0. It is the container having no built frontend, not a finding. Expect it; the gate is exit 0 and no `ERRORS:` section.

### R14 — The frontend gate is four files, 149 tests, and zero frontend edits

§ Stage 2d entry 2's gate is "existing frontend Stats/admin-UI tests unchanged and green," which has two halves and the first is checkable with `git diff`.

**Unchanged**: `git diff --stat origin/main -- frontend/` must be **empty**. Nothing in `frontend/` changes, because nothing the frontend sees changes: `frontend/src/api.js` dials the six literal paths at `:2465` (`getChannelStats`), `:2548` (`stopChannel`), `:2561` (`stopClient`), `:2617`, `:3317` (`switchStream`) and `:3334` (`nextStream`), and every one is byte-identical after the move.

**Green**: the four files that exercise those calls, found with `grep -rln "stopChannel\|switchStream\|nextStream\|getChannelStats\|stopClient" frontend/src --include='*.test.*'` —

```
frontend/src/utils/cards/__tests__/StreamConnectionCardUtils.test.js
frontend/src/utils/pages/__tests__/StatsUtils.test.js
frontend/src/components/cards/__tests__/StreamConnectionCard.test.jsx
frontend/src/pages/__tests__/Stats.test.jsx
```

Measured at the seed: `Test Files  4 passed (4)`, `Tests  149 passed (149)`. Their three non-test consumers are `frontend/src/pages/Stats.jsx`, `frontend/src/components/cards/StreamConnectionCard.jsx` and `frontend/src/store/channelsTable.jsx`, none of which names a backend module. The whole suite runs too (Task 6 Step 6): the named four are the gate the spec states, the whole suite is the gate the ruleset enforces.

---

## File structure

**Created:**

| Path | Responsibility |
|---|---|
| `apps/proxy/ts_admin_views.py` | The five `IsAdmin` views, verbatim, plus their imports and one module logger. 577 lines. Two function-local `apps.proxy.live_proxy.server` imports (R4 iii) and no other `live_proxy` reference. |
| `apps/proxy/ts_admin_urls.py` | The six URL patterns, `app_name = 'ts_admin'`. 31 lines. |

**Modified:**

| Path | Change |
|---|---|
| `apps/proxy/urls.py` | One line added: a second `ts/` include, ahead of the existing one. |
| `apps/proxy/live_proxy/urls.py` | Six of seven patterns removed; `stream/` stays. |
| `apps/proxy/live_proxy/views.py` | Lines 896–1417 deleted. **No import removed** (R3). |
| `apps/proxy/live_proxy/tests/zero_orm_allowlist.py` | Two `EdgeEntry` rows deleted with a block comment in their place; the surviving `channel_service.py` entry's two references to them rewritten (R6). |
| `apps/proxy/tests/test_stream_switch.py` | One import line (`:16`). |
| `CLAUDE.md` | § Commands (one clause) and § Routing (one sentence). |
| `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` | Amendment A12, three in-place corrections, the Done-log row. |

**Moved:**

| From | To |
|---|---|
| `apps/proxy/live_proxy/tests/test_admin_control_views.py` | `apps/proxy/tests/test_admin_control_views.py` — one import line changed, one test class appended. |

**Deliberately not touched, each for a stated reason:** `scripts/coverage_live_path.*` (R7, Constraint 6); `metrics/curated/**` and `docs/relay-parity-matrix.md` (R11, measured); `docker/nginx.conf` and every other `docker/` file (R10 — no path changes, so no location changes); `frontend/**` (R14's gate is that it is untouched and green); `e2e/**` (R10); `dispatcharr/settings.py`, `dispatcharr/urls.py`, `apps/proxy/apps.py`, `apps/proxy/tasks.py`, `apps/proxy/relay_views.py`, `apps/proxy/relay_urls.py` (A10.3 sites, 2d-4's); `apps/proxy/live_proxy/tests/harness/control.py` (it drives these five by URL over a `LiveServerTestCase` and the URLs do not change); `apps/proxy/live_proxy/views.py`'s import block (R3).

---

## Task 0: Verify the seed, on the tree 2d-1's merge produced

Runs before anything else. Every figure in this plan was measured at `d5be64d5`, the merge of stage 2d-1; this task is what confirms the tree still is that one and records the numbers later tasks compare against.

**Files:** none modified.

**Interfaces:**
- Consumes: `origin/main` with 2d-1 merged.
- Produces: a go/no-go for Tasks 1–10, and six recorded numbers.

- [ ] **Step 1: Create the worktree, the branch and the container**

```bash
cd /Users/dion/git/Dispatcharr && git fetch origin
git worktree add /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers \
  -b migration/phase2d-admin-wrappers origin/main
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers && git rev-parse HEAD
DISPATCHARR_TEST_CONTAINER=plan2d2impl DISPATCHARR_TEST_DB_VOLUME=plan2d2impl-hookdb \
  CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers \
  /Users/dion/git/Dispatcharr/.claude/hooks/start-test-container.sh
```

Record the SHA. **It must be `d5be64d5` or a descendant** — check with `git merge-base --is-ancestor d5be64d5 HEAD && echo ok`. If it is not, **STOP and report**: this PR's Gate 1 hunk, its CLAUDE.md edits and its spec edits are all written against a tree that has 2d-1 in it. If it is a *later* descendant, the appendices should still apply — Appendix D is the one to watch, and Task 0 Step 6 is where you find out.

Every later `docker exec` in this plan uses that container. A convenience wrapper, mirroring `.claude/hooks/run-affected-tests.sh:87-92`:

```bash
dex() {
  docker exec -w /repo \
    -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
    -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
    -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
    -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
    -e PYTHONPATH=/repo plan2d2impl /dispatcharrpy/bin/python "$@"
}
```

- [ ] **Step 2: The five views are still where this plan says they are**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
grep -n "^def \|^@csrf_exempt\|^@api_view\|^@permission_classes" apps/proxy/live_proxy/views.py | sed -n '/89[0-9]/,$p'
wc -l apps/proxy/live_proxy/views.py
```

Expected, unchanged from the seed because 2d-1 does not touch this file: `1417` lines, and the five definitions at `change_stream` **901**, `channel_status` **1088**, `stop_channel` **1152**, `stop_client` **1194**, `next_stream` **1242**, with `@csrf_exempt` at **898** opening the block. **If `wc -l` is not 1417, STOP** — Appendix C is a line-range deletion and every number in R3 and R7 is keyed to this file.

- [ ] **Step 3: The five need nothing 2d-1 relocated**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
sed -n '898,1417p' apps/proxy/live_proxy/views.py \
  | grep -nE "\b(RedisKeys|ChannelMetadataField|ChannelState|ConfigHelper)\b" ; echo "exit=$?"
```

Expected: **no output, `exit=1`**. If any of 2d-1's four names appears in the five views, this plan's R4 table is wrong and the new module would need an import from 2d-1's new homes (`apps/proxy/{redis_keys,constants,config_helper}.py`) — **never** from `apps.proxy.live_proxy.*`. STOP and report.

- [ ] **Step 4: The `relay_client` call sites A10.11 names**

```bash
grep -nE "= relay_client\." apps/proxy/live_proxy/views.py
```

Expected exactly seven, at **1009, 1107, 1114, 1159, 1206, 1261, 1343** — A10.11's list verbatim. Task 9 re-points it at the new module's seven.

**The pattern is anchored on the assignment for a reason.** The obvious spelling, `grep -n "relay_client\.\(advance\|get_channel\|list_channels\|stop_channel\|stop_client\)("`, returns **nine** lines at the seed: the seven call sites plus two comments that name `relay_client.advance()` in prose (`:942` and `:1324`). Counting those as call sites is how a re-measurement of A10.11 drifts from seven to nine.

- [ ] **Step 5: The `/proxy/ts/` URL table, before**

Write this to `/tmp/urldump.py` and copy it into the container (`docker cp /tmp/urldump.py plan2d2impl:/tmp/urldump.py`):

```python
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dispatcharr.settings")
django.setup()
from django.urls import get_resolver
from django.urls.resolvers import URLResolver

rows = []
def walk(res, prefix="", ns=()):
    for p in res.url_patterns:
        if isinstance(p, URLResolver):
            walk(p, prefix + str(p.pattern), ns + ((p.namespace,) if p.namespace else ()))
        else:
            cb = p.callback
            pc = getattr(cb, "permission_classes", None) or getattr(getattr(cb, "cls", None), "permission_classes", None)
            rows.append(("/" + prefix + str(p.pattern),
                         ":".join(ns + ((p.name,) if p.name else ())),
                         getattr(cb, "__module__", "?"),
                         ",".join(sorted(c.__name__ for c in (pc or [])))))
walk(get_resolver())
for r in sorted(rows):
    if r[0].startswith("/proxy/ts/"):
        print("|".join(r))
```

```bash
dex /tmp/urldump.py 2>/dev/null | grep '^/proxy/ts/' > /tmp/urls-before.txt && cat /tmp/urls-before.txt
```

Expected, seven lines:

```
/proxy/ts/change_stream/<str:channel_id>|proxy:live_proxy:change_stream|apps.proxy.live_proxy.views|IsAdmin
/proxy/ts/next_stream/<str:channel_id>|proxy:live_proxy:next_stream|apps.proxy.live_proxy.views|IsAdmin
/proxy/ts/status|proxy:live_proxy:channel_status|apps.proxy.live_proxy.views|IsAdmin
/proxy/ts/status/<str:channel_id>|proxy:live_proxy:channel_status_detail|apps.proxy.live_proxy.views|IsAdmin
/proxy/ts/stop/<str:channel_id>|proxy:live_proxy:stop_channel|apps.proxy.live_proxy.views|IsAdmin
/proxy/ts/stop_client/<str:channel_id>|proxy:live_proxy:stop_client|apps.proxy.live_proxy.views|IsAdmin
/proxy/ts/stream/<str:channel_id>|proxy:live_proxy:stream|apps.proxy.live_proxy.views|AllowAny
```

And the schema baseline, which is the stronger of the two proofs:

```bash
dex manage.py spectacular --file /tmp/schema-before.yml >/dev/null 2>&1; echo "rc=$?"
docker exec plan2d2impl sh -c 'grep -c "proxy/ts" /tmp/schema-before.yml'
```

Expected: `rc=0`, `12`.

- [ ] **Step 6: The Gate 1 allowlist is where Appendix D expects it**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
grep -n "^        importer=" apps/proxy/live_proxy/tests/zero_orm_allowlist.py
git apply --check /path/to/appendix-d.diff && echo "APPENDIX D APPLIES"
```

Expected: **twelve** `importer=` lines, of which the **first two** are `apps/proxy/live_proxy/views.py` and the **third** is `apps/proxy/live_proxy/services/channel_service.py`. The pattern is anchored to the eight-space indent of a real `EdgeEntry` field because Appendix D's own replacement block comment contains the token `importer="apps/proxy/live_proxy/views.py"`, so an unanchored `grep -c` counts eleven after the edit rather than ten (Task 4 Step 3). 2d-1 deletes a `Site` above this block and re-points an `EdgeEntry` below it, so the hunk should apply with a line offset (`git apply` prints `Hunk #1 succeeded at N (offset -20 lines)` or similar, and that is fine).

**If `git apply --check` fails**, do not force it and do not hand-edit blind. Re-derive the range: the block to delete runs from the `EdgeEntry(` line whose next line is `importer="apps/proxy/live_proxy/views.py"` (the first of the twelve) through the `),` immediately **before** the `EdgeEntry(` whose importer is `channel_service.py`. R6(iv) is the first draft getting that boundary wrong by one entry.

- [ ] **Step 7: The Gate 2 file-set probe, before**

```bash
docker exec -e COVERAGE_LIVE_PATH_DATA_DIR=/tmp/cvprobe -w /repo plan2d2impl /bin/sh -c '
  rm -rf /tmp/cvprobe && mkdir -p /tmp/cvprobe && printf "pass\n" > /tmp/cvprobe/noop.py && cd /repo &&
  /dispatcharrpy/bin/python -m coverage run --rcfile=scripts/coverage_live_path.coveragerc /tmp/cvprobe/noop.py >/dev/null 2>&1 &&
  /dispatcharrpy/bin/python -m coverage combine --rcfile=scripts/coverage_live_path.coveragerc >/dev/null 2>&1 &&
  /dispatcharrpy/bin/python -m coverage json --rcfile=scripts/coverage_live_path.coveragerc -o /tmp/cvprobe/j.json >/dev/null 2>&1 &&
  /dispatcharrpy/bin/python -c "
import json,hashlib
d=json.load(open(\"/tmp/cvprobe/j.json\"))
f=sorted(d[\"files\"].keys())
print(\"digest\", hashlib.sha256(\"\n\".join(f).encode()).hexdigest()[:12], \"files\", len(f), \"statements\", d[\"totals\"][\"num_statements\"])
"'
```

Expected, measured at `d5be64d5`: `digest 8cb5c65dac3e files 38 statements 7983`. **A digest that is not `8cb5c65dac3e` is a STOP** — record the number, whatever it is, because Task 6 compares against it.

- [ ] **Step 8: Three green labels and the frontend four**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
for L in apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests; do
  docker exec plan2d2impl redis-cli flushall >/dev/null
  dex manage.py test --keepdb "$L" -v1 > "/tmp/base-$L.log" 2>&1
  printf '%s rc=%s %s\n' "$L" "$?" "$(grep -E '^(Ran |OK|FAILED)' /tmp/base-$L.log | tr '\n' ' ')"
done
```

Expected, measured at `d5be64d5` and identical to the pre-2d-1 figures (2d-1 adds no test to these labels and re-points imports only): `apps.proxy.tests` **403 OK**, `apps.proxy.live_proxy.tests` **429 OK (skipped=1)**, `apps.channels.tests` **441 OK**. Record whatever they actually are; Task 6 expects +25 / −23 / 0 against **these** numbers, not against the ones printed above. R13's flake may fire on the second label — re-run it once before treating a failure as real.

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers/frontend && npm ci
npx vitest --run src/utils/cards/__tests__/StreamConnectionCardUtils.test.js \
  src/utils/pages/__tests__/StatsUtils.test.js \
  src/components/cards/__tests__/StreamConnectionCard.test.jsx \
  src/pages/__tests__/Stats.test.jsx
```

Expected: `Test Files  4 passed (4)`, `Tests  149 passed (149)`.

- [ ] **Step 9: Write nothing.** This task produces numbers, not files.

---

## Task 1: `apps/proxy/ts_admin_views.py`

**Files:** Create `apps/proxy/ts_admin_views.py`.

**Interfaces:**
- Consumes: `apps.proxy.next_source.get_stream_object`, `apps.accounts.permissions.IsAdmin`, `core.utils.send_websocket_update`, `dispatcharr.utils.redact_url`, and — function-locally — `apps.proxy.relay_client`, `apps.proxy.next_source.{resolve_source,channel_stream_profile_ref}` and `apps.proxy.live_proxy.server.ProxyServer`.
- Produces: `change_stream`, `channel_status`, `stop_channel`, `stop_client`, `next_stream`.

- [ ] **Step 1: Write the file exactly as Appendix A gives it**

Appendix A is the whole file, verbatim. It is **not** a paraphrase of `views.py:898-1417`: it is those 520 lines with two insertions, both function-local `ProxyServer` imports (R4 iii), under a new header. Do not retype the bodies — extract them:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
sed -n '898,1417p' apps/proxy/live_proxy/views.py > /tmp/wrappers.py
```

and check the result against Appendix A. The five bodies must be byte-identical apart from the two inserted comment-plus-import blocks.

- [ ] **Step 2: Confirm the module imports, and confirm what it does not import**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
grep -n "^import \|^from \|live_proxy" apps/proxy/ts_admin_views.py
```

Expected: eleven module-level import statements, none of them naming `live_proxy`, plus exactly **two** occurrences of `from apps.proxy.live_proxy.server import ProxyServer`, at `:58` and `:402`, each indented inside a function. **Any module-level `apps.proxy.live_proxy` import in this file is a STOP** (Constraint 8 and the whole point of the stage).

- [ ] **Step 3: Confirm `get_stream_object` is the same object**

```bash
dex -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','dispatcharr.settings'); django.setup()
from apps.proxy.live_proxy.url_utils import get_stream_object as a
from apps.proxy.next_source import get_stream_object as b
print('same object:', a is b)"
```

Expected: `same object: True`. This is R4(i)'s whole argument; if it is False, the re-export at `url_utils.py:24` has changed shape and the new module must import from wherever the definition now lives.

- [ ] **Step 4: Do not commit yet.** The tree is red between Tasks 1 and 5 — Task 6 Step 0 explains why they are one commit.

---

## Task 2: `apps/proxy/ts_admin_urls.py`, and the two urlconf edits

**Files:** Create `apps/proxy/ts_admin_urls.py`; modify `apps/proxy/urls.py` and `apps/proxy/live_proxy/urls.py`.

- [ ] **Step 1: Write `apps/proxy/ts_admin_urls.py` exactly as Appendix B.1 gives it**

Six patterns, `app_name = 'ts_admin'`. The six `name=` strings must be byte-identical to `live_proxy/urls.py`'s: `change_stream`, `channel_status`, `channel_status_detail`, `stop_channel`, `stop_client`, `next_stream`.

- [ ] **Step 2: Apply Appendix B.2 — the two urlconf edits**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
git apply --check --whitespace=error /path/to/appendix-b2.diff && git apply /path/to/appendix-b2.diff
```

`apps/proxy/urls.py` gains one line **above** the existing `ts/` include; `apps/proxy/live_proxy/urls.py` loses six of seven patterns.

- [ ] **Step 3: Confirm the prefix is served by two includes and nothing else moved**

```bash
grep -n "path(" apps/proxy/urls.py
```

Expected six lines: `stats/`, `relay/`, `ts/` (ts_admin), `ts/` (live_proxy), `catchup/`, `vod/`, in that order. **No other line of that file changes.**

---

## Task 3: `apps/proxy/live_proxy/views.py` loses the five

**Files:** Modify `apps/proxy/live_proxy/views.py`.

- [ ] **Step 1: Delete lines 896–1417 and nothing else**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
sed -n '894,898p;1415,1417p' apps/proxy/live_proxy/views.py
```

Expected: lines 896 and 897 blank, 898 `@csrf_exempt`, 1417 `        close_old_connections()`. Then apply Appendix C (a 522-line deletion hunk), or equivalently:

```bash
head -895 apps/proxy/live_proxy/views.py > /tmp/views.new && mv /tmp/views.new apps/proxy/live_proxy/views.py
```

- [ ] **Step 2: Assert the file's shape afterwards**

```bash
wc -l apps/proxy/live_proxy/views.py
grep -c "^import \|^from " apps/proxy/live_proxy/views.py
grep -n "def change_stream\|def channel_status\|def stop_channel\|def stop_client\|def next_stream" apps/proxy/live_proxy/views.py; echo "exit=$?"
tail -3 apps/proxy/live_proxy/views.py
```

Expected: **895** lines; the import count **26, unchanged** (Constraint 5 — count it before the deletion as well and compare the two, rather than trusting the number written here); **no output and `exit=1`** from the third; and a tail of `        # by the time this returns.` / `        close_old_connections()` — `stream_xc`'s own `finally`, which is now the last thing in the file.

- [ ] **Step 3: Do not remove `json`, `ImproperlyConfigured`, `csrf_exempt`, `send_websocket_update` or `IsAdmin`**

R3. If a linter or a reviewer asks for it, the answer is the measured six-SITE shift and the twenty stale prose citations, and the file is deleted wholesale at 2d-4.

---

## Task 4: Gate 1 — the two `EdgeEntry` rows whose importer left

**Files:** Modify `apps/proxy/live_proxy/tests/zero_orm_allowlist.py`.

- [ ] **Step 1: Assert the three boundary lines before deleting anything**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
python3 - <<'PY'
import pathlib
p = pathlib.Path("apps/proxy/live_proxy/tests/zero_orm_allowlist.py")
L = p.read_text().split("\n")
first = next(i for i, l in enumerate(L) if l.strip() == "EDGES = (")
a = first + 1                                  # the first EdgeEntry(
b = next(i for i, l in enumerate(L) if 'importer="apps/proxy/live_proxy/services/channel_service.py"' in l)
print("delete 1-based", a + 1, "through", b - 1)
print(repr(L[a]), repr(L[b - 2]), repr(L[b - 1]))
PY
```

Expected: `L[a]` is `    EdgeEntry(`, `L[b-2]` is `    ),` and `L[b-1]` is `    EdgeEntry(` — so the range to delete ends at the `),` and **not** at the `EdgeEntry(` that follows it. R6(iv) is what happens when it does not.

- [ ] **Step 2: Apply Appendix D**

```bash
git apply --check --whitespace=error /path/to/appendix-d.diff && git apply /path/to/appendix-d.diff
```

It does three things: deletes the two `EdgeEntry` rows, leaves a twelve-line block comment in their place recording what went and why, and rewrites the two sentences in the surviving `channel_service.py` entry that pointed at "the views.py edge above" (R6 iii).

- [ ] **Step 3: Confirm the count**

```bash
grep -c "^        importer=" apps/proxy/live_proxy/tests/zero_orm_allowlist.py
grep -c "importer=" apps/proxy/live_proxy/tests/zero_orm_allowlist.py
grep -n "the views.py edge above" apps/proxy/live_proxy/tests/zero_orm_allowlist.py; echo "exit=$?"
```

Expected, measured on the applied tree: **ten** from the first (twelve minus two) and **eleven** from the second — the unanchored count includes the token inside Appendix D's own replacement block comment, which is why Task 0 Step 6 and this step both anchor on the eight-space indent. An unanchored `10` would mean the block comment did not land. And **no output, `exit=1`** from the third: no surviving entry may point at a deleted one.

---

## Task 5: The tests follow the code

**Files:** `git mv apps/proxy/live_proxy/tests/test_admin_control_views.py apps/proxy/tests/test_admin_control_views.py`; modify the moved file and `apps/proxy/tests/test_stream_switch.py`.

- [ ] **Step 1: Move the file with git, so the rename is legible in the diff**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
git mv apps/proxy/live_proxy/tests/test_admin_control_views.py apps/proxy/tests/test_admin_control_views.py
```

- [ ] **Step 2: Apply Appendix E — one import line, one appended class**

```bash
git apply --check --whitespace=error /path/to/appendix-e.diff && git apply /path/to/appendix-e.diff
```

`from apps.proxy.live_proxy import views` becomes `from apps.proxy import ts_admin_views as views`. The alias is deliberate: it leaves all five `assertLogs(views.logger, ...)` calls and both `mock.patch.object(views, ...)` calls untouched, so the diff is one line rather than nine.

- [ ] **Step 3: Apply Appendix B.3 — `test_stream_switch.py:16`**

One line. Leave `:11`'s `from apps.proxy.live_proxy import views as views_module` alone: it is how `:309` and `:332` reach the `ProxyServer` class, which still lives there (R8).

- [ ] **Step 4: Confirm nothing else in either test file changed**

```bash
git diff --cached -M --stat -- apps/proxy/tests/ apps/proxy/live_proxy/tests/
```

Expected, measured on the applied and staged tree:

```
 apps/proxy/live_proxy/tests/zero_orm_allowlist.py  | 111 ++++-----------------
 .../tests/test_admin_control_views.py              |  43 +++++++-
 apps/proxy/tests/test_stream_switch.py             |   2 +-
```

**Both directories must be in the pathspec.** `git diff -M` pairs a rename only when both halves are inside it, so `-- apps/proxy/tests/` alone shows the moved file as a 450-line addition and hides the fact that it is a rename at all — which reads exactly like an implementer having retyped the file instead of moving it. A `450 +++` line here is a **STOP**: either the pathspec was narrowed or `git mv` was not used.

---

## Task 6: One commit, then the six proofs

- [ ] **Step 0: Why Tasks 1–5 are one commit, and this is a deliberate departure from one-task-one-commit**

The tree is red between them and there is no ordering that makes it green. After Task 2 the six patterns point at the new module while `test_admin_control_views.py` still patches attributes on the old one, so the label fails; after Task 3 the old module no longer defines what `test_stream_switch.py` imports. Committing a red tree is worse than committing five tasks together, so Tasks 1–5 land as **one commit** and this step is the disclosure. (2c-8's Done-log row records the same decision for its Tasks 2–4, with the same reasoning.)

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers && git add -A
```

Then, in a **separate** Bash call, with the message written to a file by the Write tool (Constraint 12):

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers && git commit -F /path/to/msg-code.txt
```

The commit gate will run `apps.proxy.tests`, `apps.proxy.live_proxy.tests` and `apps.channels.tests` — `dispatcharr/test_discovery.py`'s `_PATH_ALIASES` routes `apps/proxy/live_proxy/` to the middle two and the rest of `apps/proxy/` to the first, which is exactly `backend-tests.yml:180`'s coverage matrix. Expect the gate to take about 70 seconds, almost all of it the `live_proxy` label.

- [ ] **Step 1: The OpenAPI schema is byte-identical (the strong proof)**

```bash
dex manage.py spectacular --file /tmp/schema-after.yml >/dev/null 2>&1; echo "rc=$?"
docker exec plan2d2impl sh -c 'diff /tmp/schema-before.yml /tmp/schema-after.yml && echo "SCHEMA IDENTICAL"'
```

Expected: `rc=0` and `SCHEMA IDENTICAL`. drf-spectacular walks the urlconf, resolves every callable and reads its permission classes, so this one line covers Constraint 2's "same paths, same methods, same permission classes" for the whole site at once. **A non-empty diff is a STOP**, and the diff itself names what moved.

- [ ] **Step 2: The `/proxy/ts/` resolver dump differs in exactly two columns**

```bash
dex /tmp/urldump.py 2>/dev/null | grep '^/proxy/ts/' > /tmp/urls-after.txt
diff /tmp/urls-before.txt /tmp/urls-after.txt
cut -d'|' -f1,4 /tmp/urls-before.txt > /tmp/a && cut -d'|' -f1,4 /tmp/urls-after.txt > /tmp/b && diff /tmp/a /tmp/b && echo "PATHS AND PERMISSIONS IDENTICAL"
```

Expected from the first `diff`: six changed lines, each changing `proxy:live_proxy:` to `proxy:ts_admin:` and `apps.proxy.live_proxy.views` to `apps.proxy.ts_admin_views`, and the `stream` line unchanged. Expected from the second: **no output** and `PATHS AND PERMISSIONS IDENTICAL`. Any path or permission-class difference is a STOP.

- [ ] **Step 3: Three labels**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
for L in apps.proxy.tests apps.proxy.live_proxy.tests apps.channels.tests; do
  docker exec plan2d2impl redis-cli flushall >/dev/null
  dex manage.py test --keepdb "$L" -v1 > "/tmp/after-$L.log" 2>&1
  printf '%s rc=%s %s\n' "$L" "$?" "$(grep -E '^(Ran |OK|FAILED)' /tmp/after-$L.log | tr '\n' ' ')"
done
```

Expected, against Task 0 Step 8's recorded numbers: `apps.proxy.tests` **+25** and OK, `apps.proxy.live_proxy.tests` **−23** and OK, `apps.channels.tests` **unchanged** and OK. Measured at `d5be64d5` with the change applied, those are **428**, **406** and **441**, all green. Do not pipe these — redirect and read `$?` and `^OK` separately (Constraint 15; `CI_BACKEND_RUNNER` pipes have laundered an exit status before).

R13's flake lives on the middle label. If it fires, **re-run that label and move on** — it fails about eight runs in ten on a loaded host even on an unmodified tree, so a local repeat count proves nothing about this branch. Escalate only if it fires in CI, or on a host where the same label has just been shown green on `origin/main`.

- [ ] **Step 4: `manage.py check` and the credential-logging ratchet**

```bash
dex manage.py check 2>&1 | sed -n '/System check/,$p'
python3 scripts/check_credential_logging.py \
  apps/proxy/ts_admin_views.py apps/proxy/ts_admin_urls.py \
  apps/proxy/urls.py apps/proxy/live_proxy/urls.py apps/proxy/live_proxy/views.py \
  apps/proxy/live_proxy/tests/zero_orm_allowlist.py \
  apps/proxy/tests/test_admin_control_views.py apps/proxy/tests/test_stream_switch.py
echo "credlint rc=$?"
```

Expected: `System check identified 1 issue (0 silenced).` with only `staticfiles.W004` under `WARNINGS:` and **no `ERRORS:` section** (R13), and `credlint rc=0` with no output.

- [ ] **Step 5: The Gate 2 probe, after**

Re-run Task 0 Step 7's command unchanged. Expected: **the same digest and the same file count as Step 7 recorded**, and `statements` exactly **216 lower** — measured at `d5be64d5`, `7983 → 7767`.

A different digest is a **STOP**: the likely cause is a new module accidentally created under `apps/proxy/live_proxy/`, or `views.py` reduced to zero statements (`skip_empty = True` drops such a file from the report). Do not re-baseline; diff the printed file list against `scripts/coverage_live_path.floor.modules`.

**Do not run `scripts/coverage_live_path_isolated.sh --write-floor`, and do not act on `--gate`'s own invitation to.** R7. If you run `--gate` at all, expect it green with `missing` at or below the floor's, and leave the floor alone.

- [ ] **Step 6: The frontend, unchanged and green**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
git diff --stat origin/main -- frontend/ ; echo "frontend diff exit=$?"
cd frontend && npx vitest --run src/utils/cards/__tests__/StreamConnectionCardUtils.test.js \
  src/utils/pages/__tests__/StatsUtils.test.js \
  src/components/cards/__tests__/StreamConnectionCard.test.jsx \
  src/pages/__tests__/Stats.test.jsx
npm test
```

Expected: **empty** `git diff --stat` output (R14's first half; anything at all there is a STOP), `Tests  149 passed (149)` from the four, and the whole suite green.

---

## Task 7: The break-checks

Five, run in order, each reverted before the next. Two of them are the interesting ones: one that **stays green** and says why, and one that catches the mistake this PR is most likely to make.

**Files:** none permanently modified.

| # | the reversion | expected result | what it proves |
|---|---|---|---|
| BC-1 | delete `@permission_classes([IsAdmin])` from `stop_channel` in `ts_admin_views.py` | **GREEN** — `Ran 25 tests ... OK` | Nothing. `dispatcharr/settings.py:325-327` makes `IsAdmin` the DRF default, so the decorator's absence is the same behaviour. Run it anyway: the point is that R9's new tests pin the **effective authorization**, not the decorator, and a reader who assumes otherwise will write a weaker test next time. |
| BC-2 | change that same decorator to `@permission_classes([AllowAny])` (adding the import) | **RED** — `FAILED (failures=3)`, `AssertionError: 503 != 401` and `403` twice, each naming `route='/proxy/ts/stop/abc'` | The realistic mistake. `AllowAny` is eleven lines from `IsAdmin` in the file being copied from — `stream_ts`'s own decorator — and before R9 nothing in the tree would have caught it. |
| BC-3 | hoist `from apps.proxy.next_source import resolve_source` to module level in `ts_admin_views.py`, deleting **`change_stream`'s copy only** (the one at `:100`; leave `next_stream`'s at `:485`) | **RED** — `FAILED (failures=2)`, `AssertionError: 500 != 200`, both `change_stream` tests | R5. The four `mock.patch("apps.proxy.next_source.resolve_source")` targets reach the view only through late binding. |
| BC-4 | swap the two `ts/` includes in `apps/proxy/urls.py` so `live_proxy` comes first | **GREEN** — `Ran 25 tests ... OK` | R2. Django's resolver continues past a non-matching include, so the order is a readability and 2d-4-convenience choice, not a correctness one. Recording it stops a future reader treating the order as load-bearing. |
| BC-5 | delete the `ts_admin_urls` include line entirely | **RED** — `FAILED (failures=29, errors=12)` | The routing is what the tests actually reach; a green run here would mean the six routes were resolving through some other path. |

- [ ] **Step 1: Run BC-1 and BC-2**

Each against `apps.proxy.tests.test_admin_control_views` alone (25 tests, ~0.12s), restoring the file from a copy taken first. Record the exact failure text of BC-2 for the PR body.

- [ ] **Step 2: Run BC-3**

**Why BC-3 is deliberately the narrow reversion.** Deleting **both** function-local copies is the fuller experiment and it was run: `FAILED (failures=3, errors=11)`, the three failures being the two `change_stream` tests and `test_next_stream_passes_channel_name_and_m3u_profile_name_through`, all `500 != 200`. The eleven errors are not additional findings — they are the `psycopg.OperationalError: the connection is closed` cascade the moved file's own `setUp` comment (`:30-38`) describes, set off once a fourth affected test errors inside the `TestCase`'s atomic block. That cascade buries the signal, so the break-check the table prescribes is the one-copy form, whose output is two named failures and nothing else. Both were measured; if you run the both-copies form instead, expect `failures=3, errors=11` and read it as the same finding.

Note also that the two copies are **not** the same string: `change_stream`'s sits at twelve spaces of indent inside its `if stream_id:` block, `next_stream`'s at eight. A `str.replace(..., 2)` over one spelling silently edits one of them and reports success — which is how this plan's first draft came to describe a two-copy reversion while quoting a one-copy result.

- [ ] **Step 3: Run BC-4 and BC-5**

- [ ] **Step 4: Confirm the tree is back**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers && git status --porcelain
```

Expected: **empty**. A break-check left in place is the worst possible outcome of this task.

---

## Task 8: `CLAUDE.md`

**Files:** Modify `CLAUDE.md`.

- [ ] **Step 1: Apply Appendix F**

It is a **verbatim-string replacement script**, not a diff hunk, because 2d-1 edits this same file in § Test hooks and § Structural constraints and a hunk against the pre-2d-1 line numbers would not apply. Each replacement asserts its `OLD` string is present exactly once before writing, so a silent miss is impossible.

- [ ] **Step 2: Confirm both sentences moved and nothing else did**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
grep -c "live_proxy/views.py\` admin views" CLAUDE.md
grep -n "all seven routes capture" CLAUDE.md; echo "exit=$?"
git diff --stat -- CLAUDE.md
```

Expected, measured by running Appendix F at the seed: `0` from the first, **no output and `exit=1`** from the second, and `CLAUDE.md | 4 +-` from the third — two lines changed, one per replacement, and nothing else.

- [ ] **Step 3: Commit Task 8**

Docs only; `scripts/ci_backend_test_labels.py` routes `CLAUDE.md` to no backend label, so the gate runs nothing. That is correct.

---

## Task 9: Amendment A12, three in-place corrections, and the Done-log row

Three of this plan's rulings refine or contradict the spec, and the spec must never carry both an old sentence and a contradicting new one. Each is edited **in place** and the amendment says so.

**Files:** Modify `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`.

- [ ] **Step 1: Apply Appendix G**

Also a verbatim-string replacement script, for the same reason as Appendix F: 2d-1 inserts Amendment A11 and edits three A10 bullets in this file. It carries five things:

1. **Amendment A12**, eight items, inserted immediately before `## Stage 2d — cutover, and its trap` — i.e. **after** 2d-1's A11, which the anchor string makes automatic.
2. **A10.11's seven `relay_client` call sites**, re-pointed in place at the new module (R12).
3. **A10.14's `apps.proxy.tests` bullet**, gaining the one clause that keeps its import count true (R8).
4. **The deletion list's entry 2**, widened in place to name what this PR actually owns (R12).
5. **The Done-log row**, inserted immediately before `## Risks` so it lands after 2d-1's row without this plan needing to know that row's text.

- [ ] **Step 2: Verify no contradictory pair survives**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
S=docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
grep -n "live_proxy/views.py:1009" $S
grep -c "^#### Amendment A12" $S
grep -c "ts_admin_views.py:166" $S
grep -c "2d-2 -- the admin wrappers relocation" $S
```

Expected, measured by running Appendix G at the seed:

- **exactly one** hit for `live_proxy/views.py:1009`, at **A10.11 itself**, and that line must also contain `before 2d-2 moved them`. The old list is kept as provenance rather than deleted — a reader tracing a `relay_client` call site from a pre-2d-2 log or plan needs it — but it may not stand anywhere as a statement of where the call sites *are*. If the grep returns a hit on a line that does **not** carry that clause, a second copy has appeared and the spec now contradicts itself: **STOP**.
- `1` A12 heading.
- **`2`** hits for `ts_admin_views.py:166` — A10.11's corrected list and A12.1's restatement of it.
- `1` Done-log row.

- [ ] **Step 3: Commit Task 9**

---

## Task 10: Open the PR

- [ ] **Step 1: Push and open a draft PR**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
git push -u origin migration/phase2d-admin-wrappers
gh pr create --repo D10Scot/Dispatcharr --draft --base main \
  --title "relay(phase2): 2d-2 -- the admin wrappers leave live_proxy" \
  --body-file /path/to/pr-body.md
```

- [ ] **Step 2: Remove the container and its volume**

```bash
docker rm -f plan2d2impl >/dev/null 2>&1
docker volume rm plan2d2impl-hookdb >/dev/null 2>&1
```

- [ ] **Step 3: Watch the required checks**

`Backend result`, `Frontend result`, `E2E result`, `Lifecycle result`, `agent`, `safe_outputs`. The `migration/**` prefix means the full Playwright matrix runs; R10 names the ten specs that actually drive the moved views, and `streaming-failover/mid-stream-switch.spec.ts` is the one that exercises `change_stream` end to end.

### PR body template

```markdown
## What

Stage 2d-2. The five `IsAdmin` control views the admin Stats UI drives --
`change_stream`, `channel_status`, `stop_channel`, `stop_client`,
`next_stream` -- move out of `apps/proxy/live_proxy/views.py` into
`apps/proxy/ts_admin_views.py`, and the six URL patterns that register them
move out of `apps/proxy/live_proxy/urls.py` into `apps/proxy/ts_admin_urls.py`,
mounted at the same `ts/` prefix. Stage 2d-4 deletes that directory; this
surface has to survive it.

Nothing about what they do changes. The proof is mechanical: `manage.py
spectacular` produces a **byte-identical** OpenAPI document before and after,
and the `/proxy/ts/` resolver dump differs in the view module and the app
namespace and in nothing else.

## The one thing that is not identical

The app namespace: `proxy:live_proxy:stop_channel` becomes
`proxy:ts_admin:stop_channel`, and so for the other five. Nothing reverses
them -- `reverse(` appears nowhere in the tree against any of these six names,
and `frontend/src/api.js` dials the literal paths. Preserving the namespace
would have meant two resolvers registered under one instance namespace, where
the later silently wins and reverse lookups into the earlier one fail. See
Amendment A12.2.

## Nothing in the tree pinned the permission class

All 23 tests in the moved file authenticate as an admin, and no test anywhere
asserted a 401 or 403 on any of these six routes -- so a move that dropped
`IsAdmin` would have been green in every label, and "permission classes
unchanged" is this PR's own gate. `AdminControlPermissionTests` closes that:
anonymous 401, `STREAMER`/`STANDARD` 403, six routes each.

Disclosed rather than hidden: **deleting the decorator outright leaves the
suite green**, because `DEFAULT_PERMISSION_CLASSES` is the same class. The new
tests pin the effective authorization, not the decorator. The break-check that
bites is `IsAdmin` -> `AllowAny` -- the value sitting on `stream_ts`'s own
decorator eleven lines away in the file this PR copies from -- and it reddens
naming the route.

## Gate 1 loses two entries, and that is the right direction

`zero_orm_allowlist.py`'s `EDGES` loses
`views.py -> apps.proxy.next_source.channel_stream_profile_ref` (7 hits, 2c-8)
and `views.py -> ...resolve_source` (39 hits, 2b-3): `change_stream` and
`next_stream` were their only importers and they are no longer in the package
the scanner scopes. Both entries' own `reason` text already said the read runs
"IN THE API PROCESS EITHER WAY"; this makes the file layout say what the
process layout already said. No `Site` moves, and the runtime half never drove
either view. The surviving `channel_service.py` entry's two references to the
deleted one are rewritten rather than left dangling.

## Gate 2

`modules=` does not move -- both new files are outside the rcfile's `include`
and both edited files are still inside it -- and `statements` falls by exactly
216, the five views' own count. `missing` can only fall. **No floor edit**: a
drop bought by removing statements from the denominator is not a coverage
improvement to ratchet on, and 2d-5 is where `missing` legitimately moves.

## What this PR does NOT do

- It does not delete `apps/proxy/live_proxy/` or anything in it (2d-4).
- It does not touch `dispatcharr/settings.py`'s `INSTALLED_APPS`,
  `dispatcharr/urls.py`, `apps/proxy/apps.py`, `apps/proxy/tasks.py`,
  `apps/proxy/relay_views.py` or `apps/proxy/relay_urls.py` -- A10.3 sites,
  all 2d-4's.
- It does not remove the five imports the move orphans in
  `live_proxy/views.py`. Removing them shifts six Gate 1 `Site` linenos by five
  and stales about twenty prose citations in the allowlist, for a file 2d-4
  deletes wholesale.
- It does not touch nginx. All six routes are API-process-bound today
  (`nginx.conf:62`, `:248`) and no path changes.
- It does not touch `metrics/curated/`, `docs/relay-parity-matrix.md` or the
  frontend. Each was checked rather than assumed.

## Handed to 2d-4

Two function-local `from apps.proxy.live_proxy.server import ProxyServer`
imports in `apps/proxy/ts_admin_views.py` (`:58`, `:402`), for `worker_id`
alone -- `hostname:pid`, in four response bodies. Recorded in Amendment A12.3
so 2d-4's plan does not discover it.

## Gate

`manage.py check` green (one pre-existing `staticfiles.W004` in the test
container); three labels green at +25 / -23 / 0; `Backend result` green
including the coverage gate; frontend suite green and `git diff -- frontend/`
empty; `E2E result` green, with ten specs driving the moved views;
`scripts/check_credential_logging.py` zero findings.
```

---

## Appendices

Every appendix below was produced by making the change in a scratch worktree at the seed, running it, and capturing the result — not by writing it out. Appendices A and B.1 are whole new files, verbatim. Appendices B.2, B.3, C, D and E are unified diffs; all were generated at `57618a28` and **re-verified against `d5be64d5`** after 2d-1 merged (B.2, B.3 and D accepted by `git apply --check`, D at offset −20; E accepted after the `git mv`; C's assertions re-run). Appendices F and G are verbatim-string replacement scripts rather than diffs, because 2d-1 edits both of their files and a hunk against the pre-2d-1 line numbers would not apply; each asserts its `OLD` string is present exactly once before writing, so a silent miss is impossible. Both were re-run against `d5be64d5` and every assertion held.

### Appendix A — `apps/proxy/ts_admin_views.py`, whole file

577 lines. Lines 45 onward are `apps/proxy/live_proxy/views.py:898-1417` verbatim, with exactly two insertions: the nine-line comment-plus-import block at `:50-58` and its three-line echo at `:401-403` (comment, import, blank — R4 iii). The two `ProxyServer` imports land at `:58` and `:402`, which is what Task 1 Step 2's grep asserts.

```python
"""The five IsAdmin control views the admin Stats UI drives.

Moved here from apps/proxy/live_proxy/views.py by Phase 2 stage 2d-2,
unchanged: the same URLs, the same URL-pattern names, the same permission
class, the same methods, the same bodies and the same JSON. Nothing about
what they do moved -- only where they live.

They are Django's side of the relay boundary: every one of them is a thin
wrapper over apps/proxy/relay_client.py, and every one of them already runs
in the API process rather than the relay (docker/nginx.conf's
`location = /proxy/ts/status` and `location ^~ /proxy/`, both uwsgi_pass to
the API socket; only `^~ /proxy/ts/stream/` is relay-bound). Stage 2d-4
deletes apps/proxy/live_proxy/ and this surface has to survive it, which is
the whole reason for the move.

The two remaining live_proxy references are function-local on purpose and
are named in the stage 2d-4 dependency list: ProxyServer, for worker_id,
inside change_stream and next_stream.
"""

import json
import logging

from django.core.exceptions import ImproperlyConfigured
from django.db import close_old_connections
from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes

from apps.accounts.permissions import IsAdmin
from apps.proxy.next_source import get_stream_object
from core.utils import send_websocket_update
from dispatcharr.utils import redact_url

# The same logger name these five lines log to today. views.py builds it
# with live_proxy/utils.py's get_logger(), which derives "live_proxy" plus
# the calling module's basename -- "live_proxy.views" for all five. Naming
# it literally here is apps/proxy/next_source.py:34-38's precedent applied
# one level down: that module took "live_proxy" rather than reintroduce the
# import, "so every moved line still logs to the stream it logs to today."
# Renaming it once the directory behind the name is gone is 2d-6's.
logger = logging.getLogger("live_proxy.views")


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAdmin])
def change_stream(request, channel_id):
    """Change stream URL for existing channel with enhanced diagnostics"""
    # Function-local, in this module's own idiom (D10) and for the reason
    # 2d-2 exists: ProxyServer lives in the package 2d-4 deletes, this
    # module survives it, and a module-level import here would be a tenth
    # boot-trap site (Amendment A10.3) in a surviving file. worker_id --
    # hostname:pid, server.py:96-98 -- is the only thing these two views
    # want from it, and it is in both of their response bodies. Called
    # here rather than lazily at the two bodies that read it so the
    # singleton is constructed at exactly the point it is today.
    from apps.proxy.live_proxy.server import ProxyServer

    proxy_server = ProxyServer.get_instance()
    from apps.proxy import relay_client

    try:
        data = json.loads(request.body)
        new_url = data.get("url")
        user_agent = data.get("user_agent")
        stream_id = data.get("stream_id")
        m3u_profile_id = None
        stream_name = None
        channel_name = None
        m3u_profile_name = None
        transcode = False
        stream_profile = None
        ffmpeg_stream_profile = None

        # Coerce at the boundary: the Stats card's Select yields a string id
        # and, in the split deployment, this travels to the relay as JSON
        # and lands in tried_stream_ids/current_stream_id, which
        # _try_next_stream later sorts alongside int ids from Django --
        # sorted({int, str}) raises TypeError and tears the channel down on
        # the next automatic failover (Phase 1 PR 6 fix wave B, final-review
        # Blocking finding). Reject a non-integer here instead of failing
        # later, opaquely, in the relay's main loop.
        if stream_id is not None:
            try:
                stream_id = int(stream_id)
            except (TypeError, ValueError):
                return JsonResponse(
                    {"error": "stream_id must be an integer"}, status=400
                )

        # If stream_id is provided, get the URL and user_agent from it
        if stream_id:
            logger.info(
                f"Stream ID {stream_id} provided, looking up stream info for channel {channel_id}"
            )
            # Resolved here, in the API process, where the ORM is (ruling
            # 11); the result is applied on the relay via
            # relay_client.advance() below.
            from apps.proxy.next_source import resolve_source

            answer = resolve_source(channel_id, target_stream_id=stream_id, reason="operator")
            stream_info = answer["source"] or {"error": answer["error"]}

            if "error" in stream_info:
                return JsonResponse(
                    {"error": stream_info["error"], "stream_id": stream_id}, status=404
                )

            # Use the info from the stream
            new_url = stream_info["url"]
            user_agent = stream_info["user_agent"]
            m3u_profile_id = stream_info.get("m3u_profile_id")
            # Phase 2 PR 2b-1: the Source carries the names now. Before this
            # PR the key did not exist, so this was always None and the relay
            # re-resolved the name by primary key
            # (services/channel_service.py:911).
            stream_name = stream_info.get("stream_name")
            channel_name = stream_info.get("channel_name")
            m3u_profile_name = stream_info.get("m3u_profile_name")
            # Phase 2 PR 2c-8: the Go relay builds no command line, so the
            # profile Django resolved travels with the source.
            transcode = stream_info.get("transcode", False)
            stream_profile = stream_info.get("stream_profile")
            ffmpeg_stream_profile = stream_info.get("ffmpeg_stream_profile")
        elif not new_url:
            return JsonResponse(
                {"error": "Either url or stream_id must be provided"}, status=400
            )

        if not stream_id:
            # A bare url with no stream_id: nothing resolved a Stream row, so
            # the profile is the CHANNEL's own -- which is what the Python
            # relay uses on this path too, since StreamManager keeps its own
            # across update_url. Built here because the Go relay builds no
            # command line (Phase 2 PR 2c-8, Amendment A4.1).
            from apps.proxy.next_source import channel_stream_profile_ref

            try:
                channel = get_stream_object(channel_id)
            except Http404:
                # Best-effort enrichment of a call that did no DB lookup at
                # all before 2c-8. An identifier that names no row leaves the
                # three fields unset, exactly as they were, and the Go relay
                # answers 400 because it genuinely cannot spawn without an
                # argv -- honest, and not a new 404 on a path that never had
                # one.
                channel = None
            if channel is not None:
                transcode, stream_profile, ffmpeg_stream_profile = (
                    channel_stream_profile_ref(
                        channel, url=new_url, user_agent=user_agent
                    )
                )

        logger.info(
            f"Attempting to change stream for channel {channel_id} to {redact_url(new_url)}"
        )

        # Phase 1 PR 7: the switch is applied by the relay, which is the
        # process that holds the StreamManager. reset_tried carries the
        # tried_stream_ids clear that used to happen here -- PR 4's
        # routing moved this view to the API process, where
        # proxy_server.stream_managers is always empty, so the reset had
        # silently stopped happening.
        result = relay_client.advance(
            channel_id,
            url=new_url,
            user_agent=user_agent,
            stream_id=stream_id,
            m3u_profile_id=m3u_profile_id,
            stream_name=stream_name,
            channel_name=channel_name,
            m3u_profile_name=m3u_profile_name,
            reset_tried=True,
            transcode=transcode,
            stream_profile=stream_profile,
            ffmpeg_stream_profile=ffmpeg_stream_profile,
        )

        if result.get("status") == "error":
            return JsonResponse(
                {
                    "error": result.get("message", "Unknown error"),
                    "diagnostics": result.get("diagnostics", {}),
                },
                status=404,
            )

        if result.get("success") is False:
            error_data = {
                "error": result.get("message", result.get("error", "Stream switch failed")),
                "channel": channel_id,
                "url": new_url,
                "owner": result.get("direct_update", False),
                "worker_id": proxy_server.worker_id,
            }
            if stream_id:
                error_data["stream_id"] = stream_id
            # confirmed=False means owner never responded (504); owner reported failure (502)
            status_code = 504 if result.get("confirmed") is False else 502
            return JsonResponse(error_data, status=status_code)

        # Format response based on whether it was a direct update or event-based
        response_data = {
            "message": "Stream changed successfully",
            "channel": channel_id,
            "url": new_url,
            "owner": result.get("direct_update", False),
            "worker_id": proxy_server.worker_id,
        }

        # Include stream_id in response if it was used
        if stream_id:
            response_data["stream_id"] = stream_id

        return JsonResponse(response_data)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except relay_client.RelayRefused as e:
        logger.error(f"Relay refused the change_stream request with {e.status}")
        return JsonResponse({"error": "Relay refused the request"}, status=502)
    except relay_client.RelayUnavailable as e:
        logger.error(f"Relay not available for change_stream: {e}")
        return JsonResponse({"error": "Relay not available"}, status=503)
    except ImproperlyConfigured as exc:
        # A response body is not the place for validated_base_url()'s
        # message (it already redacted, but redacted still is not
        # nothing) or for the value it blames -- only the fixed string
        # below crosses the wire. The variable responsible goes to the
        # log only.
        logger.error(
            "Relay configuration error for change_stream: %s is misconfigured",
            getattr(exc, "var_name", None) or "the relay base URL",
        )
        return JsonResponse({"error": "Relay configuration error"}, status=500)
    except Exception as e:
        logger.error(f"Failed to change stream: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([IsAdmin])
def channel_status(request, channel_id=None):
    """
    Returns status information about channels with detail level based on request:
    - /status/ returns basic summary of all channels
    - /status/{channel_id} returns detailed info about specific channel

    Phase 1 PR 7: the answer comes from the relay over
    GET /proxy/relay/channels[/<id>] rather than from this process's own
    Redis reads. The URL, the IsAdmin gate and the JSON are unchanged;
    the two new statuses below exist because "the relay did not answer"
    is a thing that can now happen and 500 would say nothing useful.
    """
    # Function-local (D10): this module also hosts stream_ts and
    # stream_xc, which run in the relay process, and relay_client is
    # Django's side of that boundary.
    from apps.proxy import relay_client

    try:
        if channel_id:
            channel_info = relay_client.get_channel(channel_id)
            if channel_info is None:
                return JsonResponse(
                    {"error": f"Channel {channel_id} not found"}, status=404
                )
            return JsonResponse(channel_info)

        live_stats = relay_client.list_channels()

        # Send WebSocket update with the stats
        # Format it the same way the original Celery task did
        send_websocket_update(
            "updates",
            "update",
            {
                "success": True,
                "type": "channel_stats",
                "stats": json.dumps(live_stats),
            }
        )

        return JsonResponse(live_stats)

    except relay_client.RelayRefused as e:
        logger.error(f"Relay refused a status request with {e.status}")
        return JsonResponse({"error": "Relay refused the request"}, status=502)
    except relay_client.RelayUnavailable as e:
        logger.error(f"Relay not available for status: {e}")
        return JsonResponse({"error": "Relay not available"}, status=503)
    except ImproperlyConfigured as exc:
        logger.error(
            "Relay configuration error for channel_status: %s is misconfigured",
            getattr(exc, "var_name", None) or "the relay base URL",
        )
        return JsonResponse({"error": "Relay configuration error"}, status=500)
    except Exception as e:
        logger.error(f"Error in channel_status: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        close_old_connections()


@csrf_exempt
@api_view(["POST", "DELETE"])
@permission_classes([IsAdmin])
def stop_channel(request, channel_id):
    """Stop a channel and release all associated resources using PubSub events"""
    from apps.proxy import relay_client

    try:
        logger.info(f"Request to stop channel {channel_id} received")

        result = relay_client.stop_channel(channel_id)

        if result.get("status") == "error":
            return JsonResponse(
                {"error": result.get("message", "Unknown error")}, status=404
            )

        return JsonResponse(
            {
                "message": "Channel stop request sent",
                "channel_id": channel_id,
                "previous_state": result.get("previous_state"),
            }
        )

    except relay_client.RelayRefused as e:
        logger.error(f"Relay refused the stop request with {e.status}")
        return JsonResponse({"error": "Relay refused the request"}, status=502)
    except relay_client.RelayUnavailable as e:
        logger.error(f"Relay not available for the stop request: {e}")
        return JsonResponse({"error": "Relay not available"}, status=503)
    except ImproperlyConfigured as exc:
        logger.error(
            "Relay configuration error for stop_channel: %s is misconfigured",
            getattr(exc, "var_name", None) or "the relay base URL",
        )
        return JsonResponse({"error": "Relay configuration error"}, status=500)
    except Exception as e:
        logger.error(f"Failed to stop channel: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAdmin])
def stop_client(request, channel_id):
    """Stop a specific client connection using existing client management"""
    from apps.proxy import relay_client

    try:
        # Parse request body to get client ID
        data = json.loads(request.body)
        client_id = data.get("client_id")

        if not client_id:
            return JsonResponse({"error": "No client_id provided"}, status=400)

        result = relay_client.stop_client(channel_id, client_id)

        if result.get("status") == "error":
            return JsonResponse({"error": result.get("message")}, status=404)

        return JsonResponse(
            {
                "message": "Client stop request processed",
                "channel_id": channel_id,
                "client_id": client_id,
                "locally_processed": result.get("locally_processed", False),
            }
        )

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except relay_client.RelayRefused as e:
        logger.error(f"Relay refused the stop request with {e.status}")
        return JsonResponse({"error": "Relay refused the request"}, status=502)
    except relay_client.RelayUnavailable as e:
        logger.error(f"Relay not available for the stop request: {e}")
        return JsonResponse({"error": "Relay not available"}, status=503)
    except ImproperlyConfigured as exc:
        logger.error(
            "Relay configuration error for stop_client: %s is misconfigured",
            getattr(exc, "var_name", None) or "the relay base URL",
        )
        return JsonResponse({"error": "Relay configuration error"}, status=500)
    except Exception as e:
        logger.error(f"Failed to stop client: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@api_view(["POST"])
@permission_classes([IsAdmin])
def next_stream(request, channel_id):
    """Switch to the next available stream for a channel"""
    # Function-local: see change_stream above.
    from apps.proxy.live_proxy.server import ProxyServer

    proxy_server = ProxyServer.get_instance()
    from apps.proxy import relay_client

    try:
        logger.info(
            f"Request to switch to next stream for channel {channel_id} received"
        )

        # Check if the channel exists
        channel = get_stream_object(channel_id)

        # Phase 1 PR 7: what is playing now comes from the relay, which
        # owns the metadata hash. This view runs in the API process after
        # PR 4's routing, so reading live:channel:<id>:metadata here was
        # the control plane reading a relay key -- invisible to the
        # spec's Done grep, which covers apps/channels, apps/m3u, core
        # and dispatcharr, and exactly what this PR removes.
        running = relay_client.get_channel(channel_id)
        current_stream_id = (running or {}).get("stream_id")
        profile_id = (running or {}).get("m3u_profile_id")
        if current_stream_id:
            logger.info(
                f"Found current stream ID {current_stream_id} from the relay for channel {channel_id}"
            )
            if profile_id:
                logger.info(
                    f"Found M3U profile ID {profile_id} from the relay for channel {channel_id}"
                )

        if not current_stream_id:
            # Channel is not running
            return JsonResponse(
                {"error": "No current stream found for channel"}, status=404
            )

        # Get all streams for this channel in their defined order
        streams = list(channel.streams.all().order_by("channelstream__order"))

        if len(streams) <= 1:
            return JsonResponse(
                {
                    "error": "No alternate streams available for this channel",
                    "current_stream_id": current_stream_id,
                },
                status=404,
            )

        # Find the current stream's position in the list
        current_index = None
        for i, stream in enumerate(streams):
            if stream.id == current_stream_id:
                current_index = i
                break

        if current_index is None:
            logger.warning(
                f"Current stream ID {current_stream_id} not found in channel's streams list"
            )
            # Fall back to the first stream that's not the current one
            next_stream = next((s for s in streams if s.id != current_stream_id), None)
            if not next_stream:
                return JsonResponse(
                    {
                        "error": "Could not find current stream in channel list",
                        "current_stream_id": current_stream_id,
                    },
                    status=404,
                )
        else:
            # Get the next stream in the rotation (with wrap-around)
            next_index = (current_index + 1) % len(streams)
            next_stream = streams[next_index]

        next_stream_id = next_stream.id
        logger.info(
            f"Rotating to next stream ID {next_stream_id} for channel {channel_id}"
        )

        # Get full stream info including URL for the next stream. Resolved
        # here, in the API process, where the ORM is; the result is
        # applied on the relay via relay_client.advance() below.
        from apps.proxy.next_source import resolve_source

        answer = resolve_source(channel_id, target_stream_id=next_stream_id, reason="operator")
        stream_info = answer["source"] or {"error": answer["error"]}

        if "error" in stream_info:
            return JsonResponse(
                {
                    "error": stream_info["error"],
                    "current_stream_id": current_stream_id,
                    "next_stream_id": next_stream_id,
                },
                status=404,
            )

        # Now apply the switch on the relay. reset_tried is deliberately
        # absent: next_stream has never cleared tried_stream_ids, and
        # rotating to the next stream is what the exclusion list is for.
        result = relay_client.advance(
            channel_id,
            url=stream_info["url"],
            user_agent=stream_info["user_agent"],
            stream_id=next_stream_id,
            m3u_profile_id=stream_info.get("m3u_profile_id"),
            # Phase 2 PR 2b-1: the Source carries the names now. Before this
            # PR the key did not exist, so this was always None and the relay
            # re-resolved the name by primary key
            # (services/channel_service.py:911).
            stream_name=stream_info.get("stream_name"),
            channel_name=stream_info.get("channel_name"),
            m3u_profile_name=stream_info.get("m3u_profile_name"),
            # Phase 2 PR 2c-8: the Go relay builds no command line, so the
            # profile Django resolved travels with the source.
            transcode=stream_info.get("transcode", False),
            stream_profile=stream_info.get("stream_profile"),
            ffmpeg_stream_profile=stream_info.get("ffmpeg_stream_profile"),
        )

        if result.get("status") == "error":
            return JsonResponse(
                {
                    "error": result.get("message", "Unknown error"),
                    "diagnostics": result.get("diagnostics", {}),
                    "current_stream_id": current_stream_id,
                    "next_stream_id": next_stream_id,
                },
                status=404,
            )

        if result.get("success") is False:
            return JsonResponse(
                {
                    "error": result.get("message", result.get("error", "Stream switch failed")),
                    "current_stream_id": current_stream_id,
                    "next_stream_id": next_stream_id,
                    "owner": result.get("direct_update", False),
                    "worker_id": proxy_server.worker_id,
                },
                status=504 if result.get("confirmed") is False else 502,
            )

        # Format success response
        response_data = {
            "message": "Stream switched to next available",
            "channel": channel_id,
            "previous_stream_id": current_stream_id,
            "new_stream_id": next_stream_id,
            "new_url": stream_info["url"],
            "owner": result.get("direct_update", False),
            "worker_id": proxy_server.worker_id,
        }

        return JsonResponse(response_data)

    except Http404:
        raise
    except relay_client.RelayRefused as e:
        logger.error(f"Relay refused the next_stream request with {e.status}")
        return JsonResponse({"error": "Relay refused the request"}, status=502)
    except relay_client.RelayUnavailable as e:
        logger.error(f"Relay not available for next_stream: {e}")
        return JsonResponse({"error": "Relay not available"}, status=503)
    except ImproperlyConfigured as exc:
        logger.error(
            "Relay configuration error for next_stream: %s is misconfigured",
            getattr(exc, "var_name", None) or "the relay base URL",
        )
        return JsonResponse({"error": "Relay configuration error"}, status=500)
    except Exception as e:
        logger.error(f"Failed to switch to next stream: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)
    finally:
        close_old_connections()
```

### Appendix B.1 — `apps/proxy/ts_admin_urls.py`, whole file

```python
"""The admin Stats UI's five control routes, at /proxy/ts/.

Split out of apps/proxy/live_proxy/urls.py by Phase 2 stage 2d-2 so the
routing leaves the directory stage 2d-4 deletes along with the views it
points at. The five paths and the five `name=` strings are byte-identical
to the ones they replace; apps/proxy/urls.py mounts this module at the same
`ts/` prefix, ahead of the live_proxy include that still carries `stream/`.

The app namespace is this module's own, in apps/proxy/relay_urls.py's
idiom. It is the one thing about these five routes that is not identical
across the move -- `proxy:live_proxy:stop_channel` becomes
`proxy:ts_admin:stop_channel` -- and nothing reverses them: `reverse(` does
not appear anywhere in the tree against any of these six names, and
frontend/src/api.js dials the literal paths (:2465, :2548, :2561, :2617,
:3317, :3334).
"""

from django.urls import path

from apps.proxy import ts_admin_views

app_name = 'ts_admin'

urlpatterns = [
    path('change_stream/<str:channel_id>', ts_admin_views.change_stream, name='change_stream'),
    path('status', ts_admin_views.channel_status, name='channel_status'),
    path('status/<str:channel_id>', ts_admin_views.channel_status, name='channel_status_detail'),
    path('stop/<str:channel_id>', ts_admin_views.stop_channel, name='stop_channel'),
    path('stop_client/<str:channel_id>', ts_admin_views.stop_client, name='stop_client'),
    path('next_stream/<str:channel_id>', ts_admin_views.next_stream, name='next_stream'),
]
```

### Appendix B.2 — the two urlconf edits

```diff
diff --git a/apps/proxy/urls.py b/apps/proxy/urls.py
index d468a808..76891f8f 100644
--- a/apps/proxy/urls.py
+++ b/apps/proxy/urls.py
@@ -7,6 +7,7 @@ app_name = 'proxy'
 urlpatterns = [
     path('stats/', stats_views.combined_stats, name='combined_stats'),
     path('relay/', include('apps.proxy.relay_urls')),
+    path('ts/', include('apps.proxy.ts_admin_urls')),
     path('ts/', include('apps.proxy.live_proxy.urls')),
     path('catchup/', include('apps.timeshift.urls')),
     path('vod/', include('apps.proxy.vod_proxy.urls')),

diff --git a/apps/proxy/live_proxy/urls.py b/apps/proxy/live_proxy/urls.py
index b9aa35f5..e2250d43 100644
--- a/apps/proxy/live_proxy/urls.py
+++ b/apps/proxy/live_proxy/urls.py
@@ -5,10 +5,4 @@ app_name = 'live_proxy'
 
 urlpatterns = [
     path('stream/<str:channel_id>', views.stream_ts, name='stream'),
-    path('change_stream/<str:channel_id>', views.change_stream, name='change_stream'),
-    path('status', views.channel_status, name='channel_status'),
-    path('status/<str:channel_id>', views.channel_status, name='channel_status_detail'),
-    path('stop/<str:channel_id>', views.stop_channel, name='stop_channel'),
-    path('stop_client/<str:channel_id>', views.stop_client, name='stop_client'),
-    path('next_stream/<str:channel_id>', views.next_stream, name='next_stream'),
 ]
```

### Appendix B.3 — `apps/proxy/tests/test_stream_switch.py`

```diff
diff --git a/apps/proxy/tests/test_stream_switch.py b/apps/proxy/tests/test_stream_switch.py
index cf9ebfc5..bc9e8395 100644
--- a/apps/proxy/tests/test_stream_switch.py
+++ b/apps/proxy/tests/test_stream_switch.py
@@ -13,7 +13,7 @@ from apps.proxy.live_proxy.constants import ChannelMetadataField
 from apps.proxy.live_proxy.redis_keys import RedisKeys
 from apps.proxy.live_proxy.services import channel_service as cs_module
 from apps.proxy.live_proxy.services.channel_service import ChannelService
-from apps.proxy.live_proxy.views import change_stream
+from apps.proxy.ts_admin_views import change_stream
 
 
 class FakeRedis:
```

### Appendix C — `apps/proxy/live_proxy/views.py` loses lines 896–1417

A 522-line pure deletion. Rather than reproduce 522 lines of `-`, the mechanical form is exact and checkable:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
python3 - <<'PY'
import pathlib
p = pathlib.Path("apps/proxy/live_proxy/views.py")
L = p.read_text().split("\n")
assert len(L) == 1418, len(L)                       # 1417 lines + the trailing empty
assert L[897].startswith("@csrf_exempt"), L[897]    # 1-based 898
assert L[1416].strip() == "close_old_connections()", L[1416]   # 1-based 1417
assert L[895].strip() == "" and L[896].strip() == ""           # 1-based 896, 897
p.write_text("\n".join(L[:896]).rstrip("\n") + "\n")
print("views.py is now", len(p.read_text().split(chr(10))) - 1, "lines")
PY
```

Expected: `views.py is now 895 lines`. The three assertions are the whole safety of this step — the first fails loudly if 2d-1 (or anything else) moved the file, the second and third fail if the range is off by even one line, and the fourth keeps the two blank separator lines from being left dangling at the end of the file. **No import is removed** (Constraint 5, R3).

### Appendix D — `apps/proxy/live_proxy/tests/zero_orm_allowlist.py`

Generated at `57618a28` and **verified against `d5be64d5`**: `git apply` accepts it with `Hunk #1 succeeded at 257 (offset -20 lines)` and the same −20 on hunks #2 and #3, because 2d-1 deletes a twenty-line `Site` above this block and edits nothing inside it. Task 0 Step 6 checks that, and Task 4 Step 1 re-derives the boundaries from the file itself if a later commit moves them again.

```diff
diff --git a/apps/proxy/live_proxy/tests/zero_orm_allowlist.py b/apps/proxy/live_proxy/tests/zero_orm_allowlist.py
index cde6c037..52820578 100644
--- a/apps/proxy/live_proxy/tests/zero_orm_allowlist.py
+++ b/apps/proxy/live_proxy/tests/zero_orm_allowlist.py
@@ -277,90 +277,18 @@ SITES = (
 )
 
 EDGES = (
-    EdgeEntry(
-        importer="apps/proxy/live_proxy/views.py",
-        module="apps.proxy.next_source",
-        name="channel_stream_profile_ref",
-        hits=7,
-        pr="2c-8",
-        reason=(
-            "Phase 2 PR 2c-8. change_stream can be called with a bare url and "
-            "no stream_id -- reachable only by a hand-crafted admin call, "
-            "never by the UI, whose switchStream always sends stream_id "
-            "(frontend/src/api.js:3314-3322) -- and that path resolves no "
-            "Stream row, so there is no source dict to take a stream_profile "
-            "out of. The Go relay builds no command line (Amendment A4.1), so "
-            "without one it has nothing to spawn. This helper asks the "
-            "CHANNEL for its own effective profile and builds the argv "
-            "against the supplied url, which is the same profile the Python "
-            "relay uses on that path: StreamManager keeps its own across "
-            "update_url (input/manager.py:1462-1540) and rebuilds the command "
-            "from it. "
-            "SEVEN FLAGGED SITES in the reachable subtree, measured rather "
-            "than asserted: Channel.get_stream_profile's "
-            "effective_stream_profile_obj and its CoreSettings default "
-            "lookup, is_proxy() and is_redirect() (which compare self.locked "
-            "and self.name on a loaded instance, core/models.py:127-135 -- "
-            "flagged CALL SITES, not queries), _stream_profile_ref's "
-            "build_command (pure, core/models.py:137-160), and "
-            "_LockedFfmpegProfile.ref reaching _locked_ffmpeg_profile's "
-            "StreamProfile.objects.filter, which IS a query. "
-            "IN THE API PROCESS EITHER WAY: PR 4's routing put change_stream "
-            "on the api role, so this import is not executed in the relay "
-            "process at all -- the same structural reason the six inline "
-            "authorize edges carry."
-        ),
-        closed_by=(
-            "POST /proxy/relay/channels/<id>/advance carrying stream_profile, "
-            "ffmpeg_stream_profile and transcode -- the three fields 2c-8 "
-            "adds to RelayAdvanceRequestSerializer. Django resolves the "
-            "profile in the API process, where the ORM is, and the relay "
-            "spawns the argv it is handed."
-        ),
-    ),
-    EdgeEntry(
-        importer="apps/proxy/live_proxy/views.py",
-        module="apps.proxy.next_source",
-        name="resolve_source",
-        hits=39,
-        pr="2b-3",
-        reason=(
-            "SETTLED HERE, and issue #253 left it open: resolve_source is NOT "
-            "dead in the relay. It is called in-process at views.py:942 "
-            "(change_stream) and views.py:1291 (next_stream) -- the operator "
-            "switch paths, both relay-served. Its reachable subtree is 36 "
-            "ORM sites (measured at 04841a47; the 2b-3 plan's own worked "
-            "example measured 34 at 93900a6f) spanning "
-            "get_stream_info_for_switch's get_object_or_404 chain, "
-            "resolve_initial_source, _source_from_info's "
-            "StreamProfile.objects.get, _resolve_alternates, _commit, "
-            "_with_proxy_settings and _with_output_profiles. #253's "
-            "'looks like API-process or dead code; they were read, not "
-            "executed' is withdrawn. "
-            "2c-1 raised this from 36 to 38: next_source.py's new "
-            "_profile_kind() helper calls is_redirect() and is_proxy(), two "
-            "model-method names the scanner flags, inside resolve_source's "
-            "reachable subtree. Neither issues a query (core/models.py:127-135 "
-            "compares self.locked and self.name on a loaded instance); the count "
-            "moved because two flagged CALL SITES exist, which is the ratchet "
-            "working rather than a number tuned to fit. "
-            "2c-4 raised this from 38 to 39: spec Amendment A4.1 has "
-            "_stream_profile_ref call profile.build_command(url, user_agent, "
-            "pk) to build the argv the Go relay spawns, one flagged CALL SITE "
-            "inside resolve_source's reachable subtree. build_command is pure "
-            "(core/models.py:137-160, shlex.split and string substitution over "
-            "a loaded row's own fields); it issues no query. The count moved "
-            "because one new flagged call site exists, the ratchet working "
-            "exactly as designed."
-        ),
-        closed_by=(
-            "POST /api/relay/channels/<id>/next-source with target_stream_id "
-            "-- already on the contract (apps/proxy/control_plane.py, and "
-            "next_source.resolve_source's own target_stream_id parameter). "
-            "The Go relay makes the operator switch a control-plane round "
-            "trip instead of an import; 2c-8 owns the route."
-        ),
-    ),
+    # Phase 2 stage 2d-2 deleted two entries that stood here, both
+    # importer="apps/proxy/live_proxy/views.py": apps.proxy.next_source
+    # .channel_stream_profile_ref (7 hits, cleared by 2c-8) and
+    # .resolve_source (39 hits, cleared by 2b-3). Neither read went
+    # anywhere -- change_stream and next_stream, the only importers of
+    # either, moved to apps/proxy/ts_admin_views.py, outside
+    # zero_orm_scan.scan_relay_package's scope 1. Both entries' own
+    # reasons already said the reads run "IN THE API PROCESS EITHER
+    # WAY", so this is the file layout catching up with the process
+    # layout rather than a narrowing of what the relay may do; the
+    # runtime half never drove either view. The channel_service.py entry
+    # below is the surviving half of the second one.
     EdgeEntry(
         importer="apps/proxy/live_proxy/services/channel_service.py",
         module="apps.proxy.next_source",
@@ -368,13 +296,16 @@ EDGES = (
         hits=39,
         pr="2b-3",
         reason=(
-            "The same symbol as the views.py edge above, and a SEPARATE "
-            "entry because Ruling R3 allowlists per (importer, module, "
-            "name): channel_service.py:415 calls resolve_source directly "
+            "The last in-package importer of this symbol, and the one "
+            "the 2d-2 note above leaves standing. It was a SEPARATE entry "
+            "from the views.py one because Ruling R3 allowlists per "
+            "(importer, module, name): channel_service.py:415 calls "
+            "resolve_source directly "
             "for the pub/sub-driven operator switch (server.py's switch "
             "listener), a second in-process call site #253 did not "
-            "separately record. Same 39-hit subtree as the views.py edge; "
-            "the count is identical by construction, since scan_edge "
+            "separately record. The 39-hit subtree is the one the deleted "
+            "views.py edge also cleared; the count does not depend on who "
+            "imports the symbol, since scan_edge "
             "depends only on the target module and symbol, never on who "
             "imports it. "
             "2c-1 raised this from 36 to 38: next_source.py's new "
@@ -393,7 +324,7 @@ EDGES = (
             "because one new flagged call site exists, the ratchet working "
             "exactly as designed."
         ),
-        closed_by="As the views.py edge above -- POST .../next-source with target_stream_id.",
+        closed_by="POST .../next-source with target_stream_id.",
     ),
     EdgeEntry(
         importer="apps/proxy/live_proxy/url_utils.py",
```

### Appendix E — `apps/proxy/tests/test_admin_control_views.py`, after the `git mv`

One import line, one appended class. The appended class's two tests were run against the finished shape (`Ran 428 tests ... OK` on `apps.proxy.tests`) and both break-checks BC-1 and BC-2 were run against them.

```diff
diff --git a/apps/proxy/tests/test_admin_control_views.py b/apps/proxy/tests/test_admin_control_views.py
index 4f2658d1..8bde3385 100644
--- a/apps/proxy/tests/test_admin_control_views.py
+++ b/apps/proxy/tests/test_admin_control_views.py
@@ -16,7 +16,7 @@ from apps.accounts.models import User
 from apps.channels.models import Channel, ChannelStream, Stream
 from apps.m3u.models import M3UAccount
 from apps.proxy import relay_client
-from apps.proxy.live_proxy import views
+from apps.proxy import ts_admin_views as views
 from core.models import StreamProfile
 
 
@@ -407,3 +407,44 @@ class AdminControlViewTests(TestCase):
         self.assertEqual(response.status_code, 500)
         self.assertEqual(response.json(), {"error": "Relay configuration error"})
         self.assertIn("DISPATCHARR_RELAY_BASE_URL", "\n".join(caught.output))
+
+
+class AdminControlPermissionTests(TestCase):
+    """PIN, new in 2d-2. The stage's own gate is "URLs, names and
+    permission classes unchanged", and before this class nothing in the
+    tree asserted the last of those: all 23 tests above authenticate as
+    an admin, so a move that dropped @permission_classes([IsAdmin]) from
+    any of the five views would have been green in every label and would
+    have exposed the whole live control surface to any signed-in viewer.
+
+    Measured at the seed, unauthenticated is 401 and an authenticated
+    non-admin is 403, on all six routes.
+    """
+
+    ROUTES = (
+        ("get", "/proxy/ts/status"),
+        ("get", "/proxy/ts/status/abc"),
+        ("post", "/proxy/ts/stop/abc"),
+        ("post", "/proxy/ts/stop_client/abc"),
+        ("post", "/proxy/ts/change_stream/abc"),
+        ("post", "/proxy/ts/next_stream/abc"),
+    )
+
+    def test_every_route_401s_for_an_anonymous_caller(self):
+        client = APIClient()
+        for method, path in self.ROUTES:
+            with self.subTest(route=path):
+                response = getattr(client, method)(path)
+                self.assertEqual(response.status_code, 401)
+
+    def test_every_route_403s_for_a_signed_in_non_admin(self):
+        for level in (User.UserLevel.STREAMER, User.UserLevel.STANDARD):
+            user = User.objects.create_user(
+                username=f"non-admin-{level}", password="p", user_level=level
+            )
+            client = APIClient()
+            client.force_authenticate(user=user)
+            for method, path in self.ROUTES:
+                with self.subTest(route=path, user_level=level):
+                    response = getattr(client, method)(path)
+                    self.assertEqual(response.status_code, 403)
```

### Appendix F — `CLAUDE.md`, two sentences

A replacement script rather than a diff hunk: 2d-1 edits § Test hooks and § Structural constraints in this same file, so line numbers move. Both `OLD` strings were read out of `CLAUDE.md` at `57618a28`, neither sits in a paragraph 2d-1 touched, and both were re-confirmed present exactly once at `d5be64d5`.

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
python3 - <<'PY'
import pathlib

p = pathlib.Path("CLAUDE.md")
s = p.read_text()

# 1. Section "Commands", the relay_client three-way policy sentence.
OLD1 = "the five `live_proxy/views.py` admin views answer with a fixed body"
NEW1 = "the five admin views in `apps/proxy/ts_admin_views.py` answer with a fixed body"
assert s.count(OLD1) == 1, s.count(OLD1)
s = s.replace(OLD1, NEW1, 1)

# 2. Section "Routing". Three things wrong with the old clause after 2d-2 and
#    one wrong before it: the seven routes now live in two urlconfs; `status`
#    (the collection form) has never captured channel_id at all; and
#    channel_status has gone through relay_client rather than Redis since
#    Phase 1 PR 7.
OLD2 = (
    "**Every `live_proxy` endpoint is keyed by the channel's UUID *string*, never its numeric "
    "id** — all seven routes capture `<str:channel_id>` and `channel_status` passes it straight "
    "to Redis with no DB lookup;"
)
NEW2 = (
    "**Every `/proxy/ts/` endpoint is keyed by the channel's UUID *string*, never its numeric "
    "id** — six of the seven routes capture `<str:channel_id>` (the collection form "
    "`/proxy/ts/status` captures nothing) and the identifier reaches the relay unresolved, with "
    "no DB lookup. Since Phase 2 stage 2d-2 the five admin views live in "
    "`apps/proxy/ts_admin_views.py`, registered by `apps/proxy/ts_admin_urls.py`, and "
    "`apps/proxy/live_proxy/urls.py` registers only `stream/`;"
)
assert s.count(OLD2) == 1, s.count(OLD2)
s = s.replace(OLD2, NEW2, 1)

p.write_text(s)
print("CLAUDE.md: 2 replacements")
PY
```

### Appendix G — the spec: Amendment A12, three in-place corrections, the Done-log row

Same form, same reason: 2d-1 inserts Amendment A11 and edits three A10 bullets in this file. The A12 insertion anchors on `## Stage 2d — cutover, and its trap`, which puts it **after** A11 automatically, and the Done-log row anchors on `## Risks`, which puts it after 2d-1's row without this plan needing to know that row's text. Both anchors were verified unique at the seed (`count == 1`).

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-admin-wrappers
python3 - <<'PY'
import pathlib

p = pathlib.Path("docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md")
s = p.read_text()

# ---------------------------------------------------------------- 1. A10.11
OLD = ("(`apps/proxy/live_proxy/views.py:1009`, `:1107`, `:1114`, `:1159`, `:1206`, `:1261`, "
       "`:1343`), channel")
NEW = ("(`apps/proxy/ts_admin_views.py:166`, `:264`, `:271`, `:316`, `:363`, `:421`, `:503` — "
       "`apps/proxy/live_proxy/views.py:1009`, `:1107`, `:1114`, `:1159`, `:1206`, `:1261`, "
       "`:1343` before 2d-2 moved them, A12.1), channel")
assert s.count(OLD) == 1, s.count(OLD)
s = s.replace(OLD, NEW, 1)

# ---------------------------------------------------------------- 2. A10.14
OLD = "- **`apps.proxy.tests`** (4 files): `test_stream_switch.py` (6), `test_boundary_error_arms.py` (3),"
NEW = ("- **`apps.proxy.tests`** (4 files): `test_stream_switch.py` (6, five after 2d-2 re-pointed "
       "its `change_stream` import — A12.6), `test_boundary_error_arms.py` (3),")
assert s.count(OLD) == 1, s.count(OLD)
s = s.replace(OLD, NEW, 1)

# ------------------------------------------------- 3. deletion list, entry 2
OLD = """2. **`migration/phase2d-admin-wrappers`** — move `live_proxy/views.py`'s Django-side `IsAdmin`
   wrappers (`channel_status`, `stop_channel`, `stop_client`, `change_stream`, `next_stream`) to
   `apps/proxy/`, keeping URLs, names and permission classes unchanged so `frontend/src/api.js` never
   notices. Gate: existing frontend Stats/admin-UI tests unchanged and green."""
NEW = """2. **`migration/phase2d-admin-wrappers`** — move `live_proxy/views.py`'s Django-side `IsAdmin`
   wrappers (`channel_status`, `stop_channel`, `stop_client`, `change_stream`, `next_stream`) to
   `apps/proxy/ts_admin_views.py`, keeping URLs, names and permission classes unchanged so
   `frontend/src/api.js` never notices. **Amendment A12 widens this entry in place**: the PR owns
   five things this line named none of. The six URL patterns move too, to a new
   `apps/proxy/ts_admin_urls.py` included from `apps/proxy/urls.py` at the same `ts/` prefix ahead
   of the `live_proxy` include that still carries `stream/`, so the routing leaves the doomed
   directory with the views rather than being re-created from memory at PR 4 (A12.2) — the app
   namespace is the one thing that is not identical across the move, and nothing reverses it.
   Gate 1 loses **two** `EdgeEntry` rows whose only importers were the two views that moved, and a
   surviving entry's prose that cited them is rewritten (A12.5). The five views' test file moves
   with them out of the deleted package and gains the permission pin **nothing in the tree ever
   carried** — a move that dropped `IsAdmin` would have been green in every label, which is this
   entry's own gate (A12.6). `live_proxy/views.py` keeps the five imports the move orphans, because
   removing them shifts six Gate 1 `Site` linenos and stales about twenty prose citations (A12.7).
   Two function-local `ProxyServer` imports are handed to PR 4 (A12.3). Gate: existing frontend
   Stats/admin-UI tests unchanged and green — and `git diff -- frontend/` empty, which is the
   checkable half of "unchanged"; plus `manage.py spectacular` producing a byte-identical OpenAPI
   document before and after, which is the whole of "URLs, names and permission classes unchanged"
   in one command."""
assert s.count(OLD) == 1, s.count(OLD)
s = s.replace(OLD, NEW, 1)

# -------------------------------------------------------- 4. Amendment A12
A12 = """#### Amendment A12 (stage 2d-2) — eight rulings from moving the admin wrappers

**Measured on the merged 2d-1 tree**, with the code move made, run and reverted in a scratch
worktree before any of it was written down. Five of these eight changed when the label was run
rather than read.

**A12.1 — the destination is two modules, `apps/proxy/ts_admin_views.py` and
`apps/proxy/ts_admin_urls.py`**, in `relay_views.py`/`relay_urls.py`'s idiom — the tree's own
spelling for a boundary surface plus its route table. The five view bodies move verbatim; the
seven `relay_client` call sites A10.11 enumerates land at `ts_admin_views.py:166`, `:264`, `:271`,
`:316`, `:363`, `:421`, `:503`, and A10.11 is corrected in place above.

**A12.2 — the app namespace changes, and it is the only thing that does.** The six resolved paths,
the six `name=` strings and the `IsAdmin` permission class are byte-identical; the view module
becomes `apps.proxy.ts_admin_views` and the namespace `proxy:live_proxy:<name>` becomes
`proxy:ts_admin:<name>`. Nothing reverses them — `reverse(` appears nowhere in the tree against any
of the six names, and `frontend/src/api.js` dials literal paths. Preserving the namespace would
mean two resolvers registered under one instance namespace, where the later silently wins the
`namespace_dict` entry and reverse lookups into the earlier one fail: a landmine bought to preserve
a name nothing reads. **The proof that the surface did not move is `manage.py spectacular`**, whose
output is byte-identical before and after; drf-spectacular walks the urlconf, resolves every
callable and reads its permission classes, so an identical schema says in one command what six
hand-written assertions would say less well. Two `path('ts/', include(...))` entries resolve
correctly and **the order between them is a readability choice, not a correctness one** — measured
by swapping them and re-running the label, green either way, because `URLResolver.resolve`
continues past a non-matching include.

**A12.3 — 2d-2 hands PR 4 exactly one thing, and it is not an import that can simply be deleted.**
`change_stream` and `next_stream` open with `ProxyServer.get_instance()` and use it for
`worker_id` alone — `f"{hostname}:{pid}"`, `server.py:96-98` — which appears in four response
bodies. The new module imports it **function-locally** at `:58` and `:402`, in the idiom the file
already uses for `relay_client`, rather than adding a **tenth** module-level
`apps.proxy.live_proxy` import site (A10.3 enumerates nine) to a file whose purpose is surviving
the directory's deletion. Recomputing the string locally was declined: it is equal in the shapes
that matter and only *arguably* equal in a shape where the singleton predates a fork, and this PR's
constraint is no behaviour change rather than no visible difference. **PR 4 must decide what
`worker_id` means once there is no Python relay** — it has been the API worker's id, not the
relay's, since Phase 1 PR 4 routed these views to the api role — and the answer is a contract
decision about four response bodies, not a rehome. One measurement to start that decision from
rather than re-derive: **`grep -rn "worker_id" frontend/src` returns nothing**, so the SPA does not
read the field on any of these four responses, and whatever PR 4 chooses, no frontend change follows
from it.

**A12.4 — the moved code keeps the logger name `live_proxy.views`.** `views.py` builds it through
`live_proxy/utils.py`'s `get_logger()`, which derives `live_proxy.<calling module basename>`. The
new module names it literally, which is `apps/proxy/next_source.py:34-38`'s precedent applied one
level down — that module took `logging.getLogger("live_proxy")` rather than reintroduce the import,
"so every moved line still logs to the stream it logs to today." `live_proxy` is not a configured
logger in `settings.LOGGING`, so both spellings reach the same handler at the same level and the
only difference a rename would make is the `{name}` field. **Renaming it once the directory behind
the name is gone is 2d-6's**, and it is listed there rather than left to be noticed.

**A12.5 — Gate 1 loses two `EdgeEntry` rows, and § Stage 2d and Amendment A10 anticipate none of
it.** `zero_orm_allowlist.py`'s `views.py → apps.proxy.next_source.channel_stream_profile_ref`
(7 hits, cleared by 2c-8) and `views.py → ...resolve_source` (39 hits, cleared by 2b-3) had
`change_stream` and `next_stream` as their only importers, and `import_edges()` walks function-local
imports, so both become "found but not allowed" the moment the views leave the package —
`test_every_in_process_import_edge_is_allowlisted` is a bare `assertEqual` and fails with a set
difference and no message. **This is a narrowing of the static half in the direction of less, and it
is the right narrowing**: both entries' own `reason` text already said the read runs "IN THE API
PROCESS EITHER WAY", so 2d-2 makes the file layout say what the process layout already said. **No
`Site` moves** — all six `Site` entries in that file are inside `stream_ts` or a module-level
helper — and the runtime half is untouched, checked rather than assumed: its five drives are
`/proxy/ts/stream/` tunes and `internal_get` calls on `/proxy/relay/…`, none of which reaches any of
the five views. The surviving `channel_service.py` → `resolve_source` entry cited the deleted one
twice ("the views.py edge above"), and both citations are rewritten rather than left dangling.

**A12.6 — nothing in the tree pinned the permission class, and this entry's own gate is that it did
not change.** All 23 tests in the moved file authenticate as an admin and no test anywhere asserted
a 401 or 403 on any of these six routes, so a move that dropped `IsAdmin` would have been green in
every label. 2d-2 adds `AdminControlPermissionTests`: anonymous **401**, an authenticated
`STREAMER` or `STANDARD` **403**, six routes each, `subTest` so the failure names the route.
**Disclosed, because the obvious break-check does not bite**: deleting the decorator outright leaves
the suite green, since `dispatcharr/settings.py:325-327` makes `IsAdmin` the DRF default. The new
tests pin the effective authorization, not the decorator. The check that reddens is `IsAdmin` →
`AllowAny` — the value on `stream_ts`'s own decorator eleven lines away in the file being copied
from. The moved file also takes `apps.proxy.tests`'s count from 403 to 428 and
`apps.proxy.live_proxy.tests`'s from 429 to 406, and A10.14's list stays at **eleven** files: the
arriving file imports no `live_proxy` name, and `test_stream_switch.py` drops from six imports to
five and stays on the list.

**A12.7 — `live_proxy/views.py` keeps the five imports the move orphans, and the reason is
measured.** `json`, `ImproperlyConfigured`, `csrf_exempt`, `send_websocket_update` and `IsAdmin`
become unused. Removing them deletes five lines **above** line 896, and every `Site.lineno` in
`zero_orm_allowlist.py` is an absolute line number: the label reports all six of that file's SITES
shifted by exactly five (132→127, 152→147, 444→439, 462→457, 468→463, 766→761), and those six
numbers are cited in prose at about twenty further places in the same file. Five inert imports in a
file PR 4 deletes wholesale is the cheaper end of that trade. Four further names in the same import
block (`re`, `UUID`, `permission_classes_by_method`, `permission_classes_by_action`) were **already
unused before this PR**, which is recorded here and fixed nowhere.

**A12.8 — Gate 2's `modules=` does not move and this PR ships no floor edit.** Both new modules are
outside `scripts/coverage_live_path.coveragerc`'s `[report] include` (verified with coverage's own
`prep_patterns` + `GlobMatcher`) and both edited files are still inside it, so the resolved file set
— which is what `modules=` hashes — is unchanged: `digest 8cb5c65dac3e files 38` before and after.
`statements` falls by exactly **216**, the five views' own count measured with `PythonParser`, and
`missing` can only fall with it. The floor is not lowered, for the reason 2d-1's equivalent ruling
gives one PR earlier: `--write-floor` writes one local run's figure where the policy is the worst of
≥12 CI rounds, and a drop bought by removing statements from the denominator is not a coverage
improvement to ratchet on. **2d-5 is where `missing` moves.**

"""
ANCHOR = "\n## Stage 2d — cutover, and its trap\n"
assert s.count(ANCHOR) == 1, s.count(ANCHOR)
s = s.replace(ANCHOR, "\n" + A12 + ANCHOR.lstrip("\n"), 1)

# ---------------------------------------------------------- 5. Done-log row
ROW = ("| 2d-2 -- the admin wrappers relocation (`migration/phase2d-admin-wrappers`). The five "
       "`IsAdmin` control views and the six URL patterns that register them move out of "
       "`apps/proxy/live_proxy/` into `apps/proxy/ts_admin_views.py` and "
       "`apps/proxy/ts_admin_urls.py`, with the resolved paths, the `name=` strings and the "
       "permission class byte-identical and `manage.py spectacular` producing a byte-identical "
       "OpenAPI document as the proof. The app namespace is the one difference and nothing "
       "reverses it. Amendment A12, eight rulings, five of which changed when the label was run "
       "rather than read: Gate 1 loses two `EdgeEntry` rows whose only importers left the package "
       "(and a surviving entry's prose citing them is rewritten, after a first draft deleted three "
       "rows instead of two by taking the range to the wrong boundary); `live_proxy/views.py` keeps "
       "the five imports the move orphans, because removing them shifts all six of that file's Gate "
       "1 `Site` linenos by five and stales about twenty prose citations; nothing in the tree ever "
       "pinned the permission class, so a move that dropped `IsAdmin` would have been green in "
       "every label, closed here by a new `AdminControlPermissionTests` whose own obvious "
       "break-check is disclosed as **not** biting, since `DEFAULT_PERMISSION_CLASSES` is the same "
       "class; two function-local `ProxyServer` imports are handed to 2d-4 with the `worker_id` "
       "contract decision behind them; and the logger keeps the name `live_proxy.views` so no moved "
       "log line changes, with the rename listed for 2d-6. Gate 2's `modules=` unchanged at "
       "`8cb5c65dac3e`/38 with `statements` down 216 and no floor edit. | "
       "`migration/phase2d-admin-wrappers` | pending |")
ANCHOR = "\n\n## Risks\n"
assert s.count(ANCHOR) == 1, s.count(ANCHOR)
s = s.replace(ANCHOR, "\n" + ROW + ANCHOR, 1)

p.write_text(s)
print("spec: 5 edits")
PY
```

---

## Self-review

Every `file:line` this plan cites was re-opened with `sed -n "<n>p" <file>` after the plan was written — first at `57618a28`, then again at `d5be64d5` for everything 2d-1 could have moved — and every count was re-derived. What that found:

**Confirmed, unchanged:** `views.py:898` (`@csrf_exempt`), `:1417` (`close_old_connections()`), `:114` (`_resolve_output_format`), `:136` (`_output_profile_for`), `:1039`/`:1053`/`:1381`/`:1394` (the four `worker_id` response fields — exactly four, no more), `:433`/`:436` (the two `RedisKeys` reads that keep CLAUDE.md § Known defects true); `live_proxy/urls.py:7` (`stream/`); `apps/proxy/urls.py:10` (the `ts/` include); `next_source.py:244` (`def get_stream_object`), `:38` (`logging.getLogger("live_proxy")`); `url_utils.py:24` (the re-export); `live_proxy/utils.py:102` (`def get_logger`); `server.py:96`/`:98` (`os.getpid()`, `worker_id`); `settings.py:326` (`apps.accounts.permissions.IsAdmin` as the DRF default); `nginx.conf:62` (`location = /proxy/ts/status`), `:248` (`location ^~ /proxy/`); `relay_urls.py:14` (`app_name = "relay_control"`) and its 33 lines; `api.js:2465`, `:3317`; `test_stream_switch.py:16`; `test_zero_orm_reads.py:214` (the bare `assertEqual(found, allowed)`); `coveragerc:23` (`include =`); `backend-tests.yml:180` (the three-label coverage matrix); `floor:277-283` (the "`--write-floor` writes the figure from the run it JUST took" paragraph this plan leans on to decline a re-baseline).

**Corrected while writing, each after running rather than reading:**

1. **The first draft removed the five orphaned imports from `views.py`.** Running the label showed all six Gate 1 SITES in that file shifted by exactly five lines. The draft would have shipped a red gate and, fixed naively, about twenty stale prose citations. R3 and Constraint 5 are the result, and the plan now forbids the tidy-up it originally prescribed.
2. **The first draft deleted three `EdgeEntry` rows while intending two** — the range ran to the `EdgeEntry(` of the next entry rather than to the `),` before it, taking `channel_service.py`'s row with it. The label named the casualty exactly (`found but not allowed`). Task 4 Step 1 now asserts on the three boundary lines and R6(iv) records the miss.
3. **The first draft left two dangling cross-references.** With the `views.py` rows gone, the surviving `channel_service.py` entry still read "The same symbol as the views.py edge **above**" and `closed_by="As the views.py edge above"`. Appendix D rewrites both.
4. **The obvious break-check for the new permission tests does not bite.** Deleting `@permission_classes([IsAdmin])` leaves the suite green, because the DRF default is the same class. Rather than quietly substituting a different check, R9 and the break-check table both state it, and BC-2 (`IsAdmin` → `AllowAny`) is the one that reddens.
5. **The include order is not load-bearing**, which the draft asserted without checking. BC-4 swapped the two `ts/` includes and the label stayed green; R2 now says the order is a readability and 2d-4-convenience choice.

**Two verification steps in the plan's own text were wrong and are fixed:** Task 9 Step 2 originally expected `grep "live_proxy/views.py:1009"` to return nothing, but Appendix G deliberately **keeps** the old call-site list as provenance inside A10.11's corrected sentence — so the check is now "exactly one hit, and it carries `before 2d-2 moved them`". The same step expected one hit for `ts_admin_views.py:166`; running Appendix G produced **two** (A10.11 and A12.1). Both expectations were measured by executing Appendices F and G against the seed tree and then reverting it.

**Measured, not asserted, and each with the command in the task that re-runs it:** the byte-identical OpenAPI schema; the seven-line `/proxy/ts/` resolver dump before and after; `views.py`'s 620 statements and the 216 in the moved range; the `8cb5c65dac3e`/38 probe, `7983 → 7767` at `d5be64d5` (`8202 → 7986` at the first seed); coverage's `GlobMatcher` returning `False` for both new modules; the three label counts 403→428, 429→406, 441→441; the four frontend files at 149 tests; anonymous 401 and non-admin 403 on all six routes; zero credential-logging findings; `staticfiles.W004` present before and after.

**What this plan could not settle from the tree**, listed rather than guessed:

- ~~**The post-2d-1 numbers.**~~ **Settled** — 2d-1 merged as `d5be64d5` and this plan was re-seeded against it (see § Re-seeded against 2d-1's merge). The Gate 2 baseline is **7983 → 7767** measured rather than inferred, the three label counts are unchanged at 403/429/441 → 428/406/441, and Appendix D applies at **exactly** the −20 predicted. The one figure that moved and is worth naming: the `EdgeEntry` range Task 4 deletes, `:280`–`:363` → **`:260`–`:343`**, which is why that task derives it from the file rather than quoting it.
- **Whether the E2E suite exercises `stop_channel`, `stop_client` or `next_stream`.** `readChannelStatus` and one `change_stream` POST were found; no Playwright spec was found driving the other three, so the only coverage those three have is the moved Django tests. That is a gap this PR inherits rather than creates, and it is not this PR's to close.
- **Whether `worker_id` in the four response bodies is read by anything.** Half-answered after review: `grep -rn "worker_id" frontend/src` returns **nothing**, so the SPA does not read it and no frontend change follows from whatever 2d-4 decides. That measured fact is now in A12.3. What is still open is whether any non-SPA consumer reads it — a plugin, a Connect webhook payload, or an operator's own script — which cannot be answered from this tree at all, and which is why A12.3 states the decision rather than making it.

### Review round (opus, against `3a9ae0ae`)

Verdict PASS WITH FIXES: 0 blocking, 4 should-fix, 8 notes. The reviewer applied every appendix to the seed and ran it — three labels, the Gate 1 label, the Gate 2 probe, `spectacular` both sides, the resolver dump both sides, all five break-checks plus a sixth variant, the R3 experiment, `GlobMatcher`, `PythonParser`, the frontend four and the label routing — and **every headline number reproduced exactly**. All four should-fixes were wrong **expected outputs in verification steps**, each of which would have stopped a faithful implementer on a mismatch that is not a problem. Each was reproduced here before being applied.

| # | finding | reproduced | disposition |
|---|---|---|---|
| S1 | Task 4 Step 3 expected `grep -c "importer="` = 10; it prints **11**, because Appendix D's own block comment carries the token | yes — 11 unanchored / 10 anchored after, 12 both ways at the seed | **applied**: both Task 0 Step 6 and Task 4 Step 3 anchor on `^        importer=`, and Task 4 Step 3 now asserts **both** counts so a missing block comment is caught too |
| S2 | Task 5 Step 4's `git diff --cached -M --stat -- apps/proxy/tests/` cannot pair the rename — the source path is outside the pathspec | yes — it prints `450 +++` for the moved file | **applied**: both directories in the pathspec, the exact three-line output given, and `450 +++` named as a STOP meaning the file was retyped rather than moved |
| S3 | BC-3's reversion says "deleting both function-local copies" but its expected `failures=2` is the **one-copy** result | yes — both copies gives `FAILED (failures=3, errors=11)`; one copy gives the stated `failures=2` | **applied**: the row narrows to `change_stream`'s copy only, and Task 7 Step 2 records the both-copies figure, why the eleven errors are a connection cascade rather than findings, and that the two copies differ in indentation — which is how the draft came to describe one experiment and quote another |
| S4 | Task 0 Step 4's grep returns **nine** lines, not seven — two are comments naming `relay_client.advance()` | yes | **applied**: the step uses `grep -nE "= relay_client\."` (exactly seven) and names the nine-line trap as the way a re-measurement of A10.11 drifts |
| N1 | the `reverse(` sentence is scoped to `apps/proxy/` but reads tree-wide | yes — 21 hits tree-wide, 2 in `apps/proxy/` | **applied**: both figures given, plus the decisive one — `git grep "live_proxy:"` returns nothing in the tracked tree |
| N2 | Appendix A's second insertion is three lines at `:401-403`, not "one line at `:401-402`" | yes | **applied** |
| N3 | R3's "roughly twenty further places" is generous and several of the cited line numbers are unrelated | yes — **15** prose citations on 15 lines, plus the six `lineno=` assignments | **applied**: the measured 21 edits enumerated, with the observation that `:444` and `:152` carry eleven of the fifteen between them |
| N4 | the "is `worker_id` read by anything" open question is half-answerable in one command | yes — `grep -rn "worker_id" frontend/src` returns nothing | **applied**: folded into A12.3 as a measured fact for 2d-4, and the self-review's open question narrowed to non-SPA consumers |
| N5 | the re-seed table understates 2d-1's footprint in `zero_orm_allowlist.py` (seven edits, not two) | yes — 2d-1's R7 corrects prose at `:439`, `:629`, `:636`, `:639`, `:665`, `:672` besides the `Site` and the `EdgeEntry` | **applied**: all seven named, and Appendix D's three hunk ranges (277-366, 368-380, 393-399) given so the non-overlap is checkable rather than asserted |
| N6 | the moved test file keeps a comment citing a path 2d-4 deletes | — | **declined**, agreeing with the reviewer: inherited, not created, and editing it widens this PR's diff into the doomed package for nothing |
| N7 | Constraint 8 lists A10.3 sites 1, 3, 5, 7, 9 and silently omits site 6, which this PR edits | yes | **applied**: Constraint 8 now names site 6 as touched **by addition only**, with line 10 explicitly still 2d-4's |
| N8 | the 2d-1 branch has moved (`ceea871e` → `7193860c`) | yes | **no edit needed**: this plan pins no 2d-1 SHA, referring to the branch and PR #322 only — which is what makes the re-seed table survive 2d-1 moving. The overlap facts were re-read at `7193860c` and all still hold. |

Appendix G was edited by N4 and was re-run against the seed afterwards (`spec: 5 edits`, all five `count == 1` assertions holding) and reverted; Appendix F and the four diff appendices were re-checked unchanged. No ruling changed in this round.

### Re-seed round (2d-1 merged as `d5be64d5`)

The plan's header promised a re-seed before implementation. This is it, run rather than reasoned: a throwaway worktree at `d5be64d5`, its own container, every appendix re-applied, every figure re-measured, then reverted. **No ruling changed and no appendix was regenerated.** Sixteen figures were checked; three moved, and all three were things the plan had already said would move.

| figure | at `57618a28` | at `d5be64d5` | |
|---|---|---|---|
| Gate 2 probe, before | `8cb5c65dac3e` / 38 / **8202** | `8cb5c65dac3e` / 38 / **7983** | moved — 2d-1's three shims hold 1/25/1 statements where the originals held 85/88/73 |
| Gate 2 probe, after | `8cb5c65dac3e` / 38 / **7986** | `8cb5c65dac3e` / 38 / **7767** | moved with it; the drop is **216** on both trees, because it is the five views' own count |
| the `EdgeEntry` range Task 4 deletes | `:280`–`:363` | **`:260`–`:343`** | moved — the two `views.py` rows are now at `:261` and `:302`, `channel_service.py` at `:345` |
| Appendix D | applies | applies, **offset −20 on all three hunks** | the prediction held to the line |
| Appendices B.2, B.3 | apply | apply | unchanged |
| Appendix E (after `git mv`) | applies | applies | unchanged |
| Appendix C's four assertions | hold, 1417 → 895 lines | hold, 1417 → 895 lines | `views.py` untouched by 2d-1 |
| Appendix F | 2 replacements | **2 replacements**, both `count == 1` | the reason it is a script and not a hunk |
| Appendix G | 5 edits | **5 edits**, all `count == 1` | A12 lands at `:3708` after A11 at `:3588`; the Done-log row at `:4276` after 2d-1's at `:4275` |
| `views.py` shape | 1417 lines, 26 imports, five `def`s | identical | |
| `PythonParser` on `views.py` | 620 / 216 / 404 | identical | |
| Task 0 Step 3 (four relocated names in the moved range) | nothing, exit 1 | nothing, exit 1 | |
| Task 0 Step 4 (`= relay_client.`) | seven, at 1009…1343 | identical | |
| label baselines | 403 / 429 / 441 | identical, all green | |
| labels with the change applied | 428 / 406 / 441 | identical, all green | |
| OpenAPI schema before vs after | `SCHEMA IDENTICAL` | `SCHEMA IDENTICAL` | |
| resolver dump, `manage.py check`, credlint | as stated | identical (`staticfiles.W004` only; `credlint rc=0`) | |
| `git diff --stat 57618a28 d5be64d5 -- frontend/` | — | **empty** | so R14's four files and 149 tests stand without a re-run |

Two things 2d-1 changed that this plan deliberately does **not** follow: `docs/relay-parity-matrix.md` row 9 now cites `apps/proxy/constants.py:40`, and `metrics/curated/catalogue.yml` gained a sentence. Neither is in this PR's scope, and R11's own checks were re-run against the new tree — the parity matrix's four `live_proxy/views.py` citations are still `:162-166`, `:195-206`, `:825` and `:845-851`, all below 896, and `metrics/curated/*.yml` still cites no path this PR moves.

**Round 3 of review caught what this re-seed missed, and the miss has a shape worth naming.** I re-measured everything the re-seed section tabulates and left four `file:line` citations *into the two files 2d-1 edited* on their pre-2d-1 values, under a Seed line that now claims everything was measured at `d5be64d5`. Three were real and are fixed here: R3's twenty-one `zero_orm_allowlist.py` citations, and A10.11's position in the spec (`:3344` → **`:3359`**, cited twice, in R11 and R12). The fourth — R6(iv)'s `EdgeEntry` range — was already corrected in the re-seed commit and is disputed below.

**The R3 correction carries a lesson the first fix would have got wrong.** The obvious repair is to subtract twenty from each citation, because that is the offset `git apply` reported for Appendix D. It produces two wrong numbers: 2d-1's own prose corrections *below* the deleted `Site` changed line counts locally, so thirteen of the fifteen moved up by twenty while `:643`→`:644` and `:742`→`:743` moved **down by one**. R3 now carries the two greps that re-derive the set instead of the arithmetic that approximates it, and says why.

| # | finding | reproduced | disposition |
|---|---|---|---|
| 1 | R3's twenty-one citations are pre-2d-1 | yes — the six `lineno=` are now `:113 :135 :163 :198 :223 :243`, the fifteen prose `:149 :150 :185 :186 :192 :193 :218 :486 :509 :518 :581 :590 :602 :644 :743` | **applied**, plus the two re-derivation greps and the non-uniform-shift warning |
| 2 | R11 and R12 cite A10.11 at `:3344` | yes — it is at **`:3359`**, A11 having been inserted above it | **applied** in both, with the old number kept as provenance in R11 |
| 3 | R6(iv) "the exact range is `:280`–`:363`" | **no** — **disputed.** At the reviewed content (`ad18f1f8`, unchanged at `e36f8cc2`) `plan:169` reads "The exact range **was** `:280`–`:363` at the pre-2d-1 seed and **is `:260`–`:343`** at `d5be64d5`", corrected in the re-seed commit `ad18f1f8`. The re-seed table (`plan:31`), the settled open question and the re-seed round's own table carry `:260`–`:343` as well. Nothing to change; the reviewer appears to have read the pre-re-seed text. The ruling's substance — that Task 4 derives the range from the file rather than quoting either number — is unaffected and is why the staleness would not have bitten an implementer here. |
| 4 | sweep for other stale refs into those two files | done — `grep -noE "zero_orm_allowlist\.py:[0-9-]+"` and the spec-line sweep return **nothing else**. `:3588`/`:3708` (A11/A12 positions) and `:3317`/`:3334` (`api.js`) are post-2d-1 or unrelated; `zero_orm_allowlist.py:111-130` in the re-seed table is deliberate history describing what 2d-1 did | no change |

One rule was corrected rather than re-measured: R13's stopping rule for #259. 2d-1's implementer measured the flake on this host at roughly **eight failures in ten on an unmodified tree**, which makes "three in a row is new" fire on a clean checkout more often than not. The rule is now "re-run and move on; escalate only in CI or on a demonstrably quiescent host." This plan's own six passes across two seeds are recorded beside that as a sample that says nothing either — the same evidence from the other side.
