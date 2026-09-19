# Phase 2 Stage 2d-1 — the boot-trap relocation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the four names surviving code imports out of `apps/proxy/live_proxy/` — `RedisKeys`, `ChannelMetadataField`, `ChannelState` and `ConfigHelper` — into Django-owned modules, so that no file stage 2d KEEPS points at the directory stage 2d-4 deletes, and so the module-level boot trap `apps/channels/models.py:6-7` carries has a home that outlives the relay package.

**Architecture:** Three new modules under `apps/proxy/` (`redis_keys.py`, `constants.py`, `config_helper.py`) take the four names. The three old modules stay in place as re-export shims, so the 25 relay modules and 31 in-package test files that import them need no edit and Gate 2's resolved file set — a set of paths — does not move. Nineteen import statements in ten files outside the package are re-pointed at the new homes. Gate 1's allowlist follows `ConfigHelper` out of scope-1. The boot-check hook arm, which matches by literal path, is re-pointed in the same commit — otherwise it silently stops running in the PR that moves its subject.

**Tech Stack:** Python 3.13 / Django 6; no new dependency, no migration, no Go, no workflow edit, no `docker/` edit. `coverage` 7.16.0 for the Gate 2 measurement; `manage.py check` + `manage.py showmigrations` for the boot path.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` — § Stage 2d's `### Deletion order — one PR each` entry **1**, Amendment **A10.3** (the nine module-level sites and the ruling that widens 2d-1's scope to `ChannelState` and `ConfigHelper`), **A10.4** (Gate 2 — corrected here, see R4), **A10.14** (the thirteen outside test files — corrected here, see R6), **A10.17** (the `models_boot_trap_imports` metric, and #190's five ranges staying put). This PR adds **Amendment A11** and its Done-log row.

**Seed:** `16fbb952942a64115928e8d0ff8dacce3d0eb976` — `relay(httpapi): #318 -- an admin stop cannot interrupt a blocked write (#320)`. Every `file:line`, count, hash and expected output below was measured at that commit. Line numbers drift; if `origin/main` has moved, Task 0 stops.

## Global Constraints

Every task's requirements implicitly include all of these. A conflict with any is a **STOP and report**, not an amendment you make yourself.

1. **Branch: `migration/phase2d-boot-trap-relocation`.** The `migration/**` prefix is load-bearing — it bypasses the E2E path filters and runs every Playwright project plus both bash suites in `lifecycle-tests.yml`.
2. **`apps/proxy/redis_keys.py` and `apps/proxy/constants.py` must have NO imports, at all.** They are loaded by every migration and every management command through `apps/channels/models.py:6-7`. One first-party import in either and Django stops booting for every command in every role. This is not a style rule; Task 5 Step 4's break-check is what it looks like when it is broken.
3. **`apps/proxy/config_helper.py` may import `apps.proxy.config` and nothing else first-party.** `apps/proxy/config.py`'s own module-level imports are `time` and `django.db.connection`; a first-party import added to either file re-creates the trap one level down.
4. **Do not touch the five #190 ranges in `apps/channels/models.py`.** `:516-519`, `:696-702`, `:717-721`, `:747-750`, `:773-778` read and write `RedisKeys.channel_metadata` and `ChannelMetadataField.*`. They are carried along with the relocated import and **not** tidied, deleted, or re-pointed at anything. Amendment A10.17 assigns them to 2d-4. The only thing that changes about them in this PR is which module the names at the top of the file came from.
5. **Do not edit `apps/proxy/live_proxy/**` beyond the three shims and the two Gate 1 test files** named in Tasks 2 and 4. 2d-4 deletes that directory; every other edit there is churn on a corpse.
6. **Do not edit the rcfile, the floor, or the floor companion.** `scripts/coverage_live_path.coveragerc`, `scripts/coverage_live_path.floor` and `scripts/coverage_live_path.floor.modules` are untouched by this PR. R4 is why. If `--gate` fails, that is a **STOP and report**, not a re-baseline.
7. **Do not commit a `metrics/curated/milestones.yml` row.** R10. A milestone row carries the merge SHA and a merge commit cannot name itself.
8. **`scripts/check_credential_logging.py` stays at zero findings** for every `*.py` this PR touches. It runs in the edit hook and in `lint.yml`.
9. **A channel UUID and a provider URL are secrets.** Nothing this PR adds may print either.
10. **Do not use the shared `dispatcharr-testrunner` container.** Start your own, named for this PR, and remove it and its volume when you finish. The `PostToolUse` hook refusing on a mount mismatch is correct behaviour, not a problem to work around: it does **not** see `DISPATCHARR_TEST_CONTAINER`, so it always uses the shared name and always tests whichever worktree that one container is mounted at.
11. **Stage and commit in separate Bash calls.** Write commit messages with the Write tool and commit with `git commit -F <file>`; a single command containing both `git` and `commit` plus a heredoc trips the commit gate, and so does a heredoc whose text merely contains those two words.
12. **`gh` always with `--repo D10Scot/Dispatcharr`.**
13. **Anchor every command with an absolute path or a leading `cd <your worktree> &&`.** The shell cwd is shared or correlated across concurrent agents.
14. **`set -o pipefail` on any pipeline whose emptiness or exit status you intend to read**, and never `2>/dev/null` a git query you plan to interpret.
15. **If the tests did not run, say they did not run.** Never describe unverified work as verified.

---

## Rulings

These are the decisions this plan makes on the questions the spec and Amendment A10 leave open. Each was measured at the seed, with the command that produced it.

### R1 — Three new modules, mirroring the three they came from

`RedisKeys` goes to **`apps/proxy/redis_keys.py`**, `ChannelState` and `ChannelMetadataField` to **`apps/proxy/constants.py`**, `ConfigHelper` to **`apps/proxy/config_helper.py`**. Not one combined module, and not a `relay_`-prefixed name.

Three reasons, in order of weight.

**The leaf guarantee is per-file, and combining would attach an import to the two files that must not have one.** Measured at the seed (`grep -n "^import \|^from " apps/proxy/live_proxy/{redis_keys,constants,config_helper}.py`): `redis_keys.py` and `constants.py` have **no imports at all**; `config_helper.py` has `from apps.proxy.config import TSConfig as Config` at `:5` and a second, function-local one at `:49`. Constraint 2 exists because `apps/channels/models.py:6-7` puts the first two on the migration loader's path. Folding `ConfigHelper` in with them would put `apps.proxy.config` on that path for no gain.

**The same basename makes the diff read as a move** and keeps `git log --follow` working across it. Two of the three files are byte-identical to their originals apart from the module docstring.

**`apps/timeshift/redis_keys.py` already establishes `<app>/redis_keys.py` as this tree's spelling** for exactly this kind of module (it holds `TimeshiftRedisKeys`). `apps/proxy/` has no `constants.py`, `redis_keys.py` or `config_helper.py` at the seed — `ls apps/proxy/*.py` lists 23 files and none of those three — so there is no collision.

**The alternative considered and declined:** `apps/proxy/relay_constants.py` etc., echoing `relay_client.py`/`relay_views.py`/`relay_serializers.py`. Those three names mean "the boundary surface the Go relay calls". These four names are not a surface; they are the vocabulary `apps/channels/models.py` and the catch-up views already speak. A `relay_` prefix would say the wrong thing, and it breaks the read-as-a-move property.

### R2 — `constants.py` is split, not moved whole

`apps/proxy/constants.py` takes **only** `ChannelState` and `ChannelMetadataField`. `REDIS_KEY_PREFIX`, `REDIS_TTL_DEFAULT/SHORT/MEDIUM`, `EventType`, `StreamType`, `TS_PACKET_SIZE`, `TS_SYNC_BYTE`, `NULL_PID_HIGH` and `NULL_PID_LOW` stay in `apps/proxy/live_proxy/constants.py`.

Measured: nothing outside `apps/proxy/live_proxy/` imports any of them. The check is

```bash
grep -rn --include='*.py' -E "\b(TS_PACKET_SIZE|EventType|StreamType|REDIS_TTL_[A-Z]+|REDIS_KEY_PREFIX|TS_SYNC_BYTE|NULL_PID_HIGH|NULL_PID_LOW)\b" \
  apps dispatcharr core scripts | grep -v "^apps/proxy/live_proxy/"
```

which returns exactly one line at the seed, `apps/proxy/tests/test_effective_proxy_settings.py:120`, and that is a **comment** mentioning `TS_PACKET_SIZE * 5644`, not an import. (It takes explicit directory arguments rather than `.`, so it needs no `./`-anchored filter and returns the same line under either `grep` on this harness — verified. Re-run **after** Task 1 and it returns three: the two extra are `apps/proxy/constants.py`'s own docstring naming the constants it left behind.) Moving them anyway would deliver dead code into Django-owned space: after 2d-4 the Go relay has its own copies and nothing in Python would read them. The split costs one extra hunk and leaves 2d-4's delete clean.

### R3 — The old modules survive as re-export shims until 2d-4

Each of the three old paths becomes a module docstring plus `from apps.proxy.<module> import <Name>  # noqa: F401`.

**The number that decides this.** Measured at the seed:

```bash
grep -rn --include='*.py' -E "^[[:space:]]*from [A-Za-z_. ]*(redis_keys|constants|config_helper) import .*(RedisKeys|ChannelMetadataField|ChannelState|ConfigHelper)" . | wc -l
```

is **140** import statements. **33** are non-test files inside `apps/proxy/live_proxy/`, **31** are test files inside it, and the rest are outside. Re-pointing all 140 edits 25 modules and 31 test files that 2d-4 deletes wholesale, for no behaviour difference. The shim shape re-points **19** (R5) and leaves 121 alone.

Two further things the shim buys, and the second is the load-bearing one.

- The eleven test files outside the package that A10.14 enumerates keep working with no edit, which is what "2d-1 does not dispose of them but must not break them" means in practice.
- **It is what keeps Gate 2's `modules=` from moving** (R4) — and the mechanism is the **path**, not the statement. The gate hashes `sorted(json["files"].keys())` (`scripts/coverage_live_path.sh:223`, `:235`) with no reference to any statement count, so a file matching `[report] include` stays in the set even at zero statements. The proof is already committed: `apps/proxy/live_proxy/__init__.py` is a **zero-byte** file and is line 6 of `scripts/coverage_live_path.floor.modules`, with `skip_empty = True` set in the rcfile all along — `skip_empty` suppresses such a file from the **text** table only. A shim happens to carry one statement (`coverage.parser.PythonParser`), and nothing depends on that.

### R4 — Gate 2's `modules=` does NOT move, and this PR ships no floor edit at all

**Amendment A10.4 says this PR "trips `modules=` on its first push" and prescribes a `--write-floor --shape-only` re-baseline with `missing` unchanged at 1525. That is wrong for the shim shape, and this plan corrects it in the spec** (Task 8, Appendix H).

A10.4's premise is right: `scripts/coverage_live_path.coveragerc:23-34`'s `[report] include` is `apps/proxy/live_proxy/*` plus ten named files, so a relocated name lands outside the denominator wherever it goes. Its conclusion does not follow, because **no file leaves the set** — the old paths are still there, still matching `apps/proxy/live_proxy/*`, still carrying a statement.

Measured three ways at the seed.

**(a) coverage's own matcher.** Running coverage 7.16.0's `prep_patterns` + `GlobMatcher` over that `include` list returns `False` for `apps/proxy/redis_keys.py`, `apps/proxy/constants.py` and `apps/proxy/config_helper.py`, and `True` for all three `apps/proxy/live_proxy/` paths. The new modules are outside the denominator; the shims are inside it.

**(b) the cheap file-set probe.** `[run] source = apps/proxy` triggers coverage's unexecuted-file walk, so the resolved `files` set does not depend on which tests ran — which means a `coverage run` over a **no-op script** under the same rcfile reproduces the exact set in seconds. Task 7 Step 2 is that probe. Measured:

| tree | digest | files | statements |
|---|---|---|---|
| seed `16fbb952` | `8cb5c65dac3e` | 38 | **8202** |
| this PR's shape | `8cb5c65dac3e` | 38 | **7983** |

`8cb5c65dac3e` / 38 is exactly `scripts/coverage_live_path.floor`'s own `modules=`/`module_count=`. `rcfile=` cannot move either: the rcfile is not edited (Constraint 6).

**(c) a full isolated round.** `scripts/coverage_live_path_isolated.sh --gate` on this PR's shape exited **0**, printing

```
coverage_live_path: denominator: floor 8073 statements  this run 7983 statements (informational -- modules=/rcfile= above are the shape checks)
coverage_live_path: floor missing=1525  this run missing=1505  coverage 81.15%
coverage_live_path: 20 FEWER missed than the floor. The floor is not
coverage_live_path: lowered automatically -- run --write-floor in the PR that earned it.
```

**`statements` is reproducible and `missing` is not, and only the first is quoted as a literal below.** A second round on the same tree, run by this plan's reviewer, drew `statements=7983` again and `missing=**1509**` — "16 FEWER", exit 0. `scripts/coverage_live_path_isolated.sh:9-11` says so in its own header ("the TOTAL determinism it buys is NOT: spread 44 isolated against 47 shared"), and CLAUDE.md § Testing says the same. The pass condition is exit 0 with `modules=`/`rcfile=` matching, not a literal `missing`.

**`missing` cannot rise, and the argument is structural rather than empirical.** The three modules hold **246** statements at the seed (85 + 88 + 73, measured with `PythonParser`) and **27** afterwards (1 + 25 + 1) — a strict removal of 219 statements from the denominator, exactly the 8202 → 7983 the probe measured. Every statement that leaves takes its own missing-or-covered status with it, and the one-statement shims that replace them execute on import in all three labels. So `missing` falls by however many of the 219 were uncovered, and never rises. The other edits this PR makes inside the denominator (`relay_views.py`, `relay_client.py`, `next_source.py`) each change one import statement into a different import statement: same count, still covered.

**And the floor is not lowered either.** `--gate`'s own message invites it ("run `--write-floor` in the PR that earned it"), and this PR declines, for the reason the floor file's own HOW TO MOVE section gives at `scripts/coverage_live_path.floor:277-283`: plain `--write-floor` writes the figure from the run it just took, where this floor's policy is the worst of ≥12 rounds measured **in CI**. One local round is not that. 2d-5 (`migration/phase2d-gate2-recensus`) is the PR where `missing` legitimately moves, on the tree that earns it. A 20-statement drop bought by removing statements from the denominator is not a coverage improvement anybody should ratchet on.

**Note on `statements=8073` in the floor.** It was measured on 2026-09-13 and the seed already draws 8202 — stale by 129 before this PR touches anything, because 2c-8, 2c-9 and #318 added statements to already-included modules. That is precisely why `statements` is recorded provenance and never compared, and it is why this PR does not "fix" it.

### R5 — Nineteen import statements, in ten files

Re-derived at the seed with A10.3's own grep, narrowed to the four names. **`git grep`, not `grep -r .`**, for two reasons found the hard way: `grep -r .` emits a `./` path prefix that some `grep` implementations on this harness's `PATH` do not, so a `grep -v "/apps/proxy/live_proxy/"` filter can silently match nothing; and it walks the filesystem, so a stray `.venv` or build output moves a number this plan uses as a stop condition. `git grep` walks the index and emits bare repo-relative paths under either implementation.

```bash
git grep -nE "^[[:space:]]*from [A-Za-z_. ]*(redis_keys|constants|config_helper) import .*(RedisKeys|ChannelMetadataField|ChannelState|ConfigHelper)" \
  -- '*.py' ':!apps/proxy/live_proxy/*' ':!apps/proxy/tests/*' ':!apps/channels/tests/*' \
  | grep -v 'apps\.timeshift\.redis_keys'
```

The last filter is load-bearing and its absence is what made an earlier draft of this command return 63 instead of 19: **`apps/timeshift/redis_keys.py`'s `TimeshiftRedisKeys` matches the pattern from forty-five sites** — forty of them through the `as RedisKeys` alias, the rest through the class's own name — not the one in `apps/proxy/tests/test_stream_limits.py` an earlier parenthetical claimed. The two `':!apps/*/tests/*'` pathspecs exclude the test files 2d-4 disposes of while keeping `apps/timeshift/tests/`, which R6 re-points here.

| # | site | names | A10.3 site | disposition |
|---|---|---|---|---|
| 1 | `apps/channels/models.py:6` | `RedisKeys` | 2 | re-point |
| 2 | `apps/channels/models.py:7` | `ChannelMetadataField` | 2 | re-point |
| 3 | `apps/proxy/relay_views.py:38` | `ChannelMetadataField` | 3 (part) | re-point |
| 4 | `apps/proxy/relay_views.py:39` | `RedisKeys` | 3 (part) | re-point |
| 5 | `apps/proxy/relay_client.py:61` | `ChannelState` | 4 | re-point |
| 6 | `apps/timeshift/views.py:40` | `ConfigHelper` | 8 | re-point |
| 7 | `apps/timeshift/views.py:41` | `ChannelMetadataField`, `ChannelState` | 8 | re-point |
| 8 | `apps/timeshift/stats.py:13` | `ChannelMetadataField` | 8 | re-point |
| 9 | `apps/proxy/next_source.py:348` | `RedisKeys` | function-local | re-point |
| 10 | `apps/proxy/next_source.py:474` | `RedisKeys` | function-local | re-point |
| 11 | `apps/proxy/next_source.py:1115` | `RedisKeys` | function-local | re-point |
| 12 | `core/utils.py:759` | `RedisKeys` | function-local | re-point |
| 13 | `apps/channels/tasks.py:1125` | `ConfigHelper` | function-local | re-point |
| 14 | `apps/channels/tasks.py:2445` | `ChannelMetadataField` | function-local | re-point |
| 15 | `apps/timeshift/tests/test_stats.py:12` | `ChannelMetadataField`, `ChannelState` | A10.14 | re-point (R6) |
| 16 | `apps/timeshift/tests/test_views.py:3235` | `ChannelMetadataField` | A10.14 | re-point (R6) |
| 17 | `apps/timeshift/tests/test_views.py:3478` | `ChannelMetadataField` | A10.14 | re-point (R6) |
| 18 | `apps/timeshift/tests/test_views.py:3508` | `ChannelMetadataField` | A10.14 | re-point (R6) |
| 19 | `apps/timeshift/tests/test_views.py:3535` | `ChannelMetadataField` | A10.14 | re-point (R6) |

Fourteen non-test statements in eight files, five test statements in two files.

**Not in the list, and each for a stated reason.**

- **`apps/proxy/authorize.py:380`** — `from apps.proxy.live_proxy.url_utils import get_stream_object`. A different module and a different name; A10.3 lists it among the function-local sites 2d-4 owns. Do not touch it even though the file is otherwise in scope for other stages.
- **The 33 non-test and 31 test import statements inside `apps/proxy/live_proxy/`** — the shim serves them (R3), and Constraint 5 forbids editing them.
- **The remaining outside test files** — `apps/proxy/tests/test_stream_switch.py:12`/`:13`, `apps/proxy/tests/test_boundary_error_arms.py:15`, and five under `apps/channels/tests/`. Each of those files imports **other** `live_proxy` symbols too, so re-pointing these particular lines would not take the file off the doomed package; 2d-4 disposes of them as whole files, per A10.14.
- **`apps/proxy/live_proxy/tests/**`** — except the two Gate 1 files R7 names.

### R6 — The two timeshift test files come with the timeshift surface

A10.14 lists thirteen test files outside the package, two of them under `apps.timeshift.tests`, and leaves all thirteen to 2d-4's per-file disposition. **This plan takes those two.**

Measured: all five of their `live_proxy` imports name `constants.ChannelMetadataField`/`ChannelState` — the exact names 2d-1 relocates — and they have no others. `test_stats.py` has one (A10.14 says 1) and `test_views.py` has four (A10.14 says 4), and the totals match. So re-pointing five lines takes the **whole `apps.timeshift.tests` label** off the deleted package, and A10.14's list drops from thirteen files across three labels to **eleven files across two**.

The argument is A10.3's own, one level down: catch-up is the surface stage 2d KEEPS, and A10.3 already rules that `apps/timeshift/views.py` and `stats.py` "cannot be left pointing at a directory scheduled for deletion three PRs later". Their tests are part of that surface. This is a five-line edit that removes an entire label from 2d-4's risk surface, and it is the cheapest thing in this PR.

The eleven that stay are 2d-4's: seven under `apps.channels.tests`, four under `apps.proxy.tests`.

### R7 — Gate 1 moves with `ConfigHelper`, and it narrows by one hop

Nothing in § Stage 2d or Amendment A10 anticipates this, and it is the one part of the PR that is not mechanical. Moving `ConfigHelper` out of `apps/proxy/live_proxy/` changes what the zero-ORM guard sees, in three places. All three were measured by applying the relocation and running the label.

**(i) One SITE is deleted.** `zero_orm_allowlist.py:111-130`'s `Site(path="apps/proxy/live_proxy/config_helper.py", lineno=50, pr="2b-1", …)` names `TSConfig.get_proxy_settings()` in `new_client_behind_seconds`. Scope 1 is `apps/proxy/live_proxy/**` only (`zero_orm_scan.scan_relay_package`), so after the move the scanner does not see it and `test_every_orm_site_in_the_relay_package_is_allowlisted` fails with

```
listed but gone (delete the entry -- the ratchet runs both ways, and a stale entry is how an allowlist stops meaning anything):
  apps/proxy/live_proxy/config_helper.py:50
```

The read has not gone anywhere — it is at **`apps/proxy/config_helper.py:66`**, byte-identical code sitting sixteen lines lower because the new module's docstring is longer than the one it replaced — it has left the scope the SITES list describes. SITES goes **12 → 11**. **The line number matters and is easy to get wrong**: the deleted entry's own coordinates stay `apps/proxy/live_proxy/config_helper.py:50` (that is what the failure message prints, and what the entry recorded), while every statement about where the read *is now* must say `:66`.

**(ii) One EDGE is re-pointed, and its `hits` count drops from 5 to 1.** `import_edges()` walks every first-party `ImportFrom` in the package, so the shim's own `from apps.proxy.config_helper import ConfigHelper` is a new edge and the old `from apps.proxy.config import TSConfig as Config` is gone. Only edges whose subtree reaches the ORM are compared (`test_every_in_process_import_edge_is_allowlisted` filters on `if zero_orm_scan.scan_edge(e)`), which is why the three edges the `redis_keys` and `constants` shims create do not appear: `RedisKeys`, `ChannelState` and `ChannelMetadataField` make no ORM calls. EDGES stays **12**.

The `hits` change is real and must be disclosed rather than absorbed. `scan_edge` is transitive **within the module only** (2b-3's Ruling R4), so where the entry used to clear `TSConfig`'s five same-module classmethods it now clears one call:

```
Hit(path='apps/proxy/config_helper.py', lineno=66, symbol='get_proxy_settings', shape='model_method')
```

The five classmethods are now two hops out and invisible to the static half. **That is a narrowing of Gate 1's static reach, in the direction of less.** It is acceptable here for two reasons and both belong in the entry's `reason` field: the runtime half is unaffected and still catches the read on every drive through `SQL_SIGNATURES`' `proxy_settings_group` (measured — the runtime tests stayed green through the whole relocation); and A10.8 already records that Gate 1's runtime half dies with the package at 2d-4, so this is a one-PR narrowing of something already scheduled for retirement. CLAUDE.md § Testing already says the static half "cannot see … an ORM read more than one import hop out of the package"; this makes one more read fall under that sentence.

**The entry keeps `pr="2b-1"`.** `AllowlistShapeTests.test_every_entry_states_what_closes_it` asserts `entry.pr` matches `^(Phase 1 PR \d|2[abc]-\d)$`, which admits no `2d-1` value. That is not a limitation to route around: the PR that **cleared** this read is still 2b-1, and only the path it travels changed. Widening the regex to record a re-point as a clearance would be the wrong edit, and this plan declines it.

**(iii) One test's driver is replaced.** `test_zero_orm_scan.py:195-229`'s `test_a_query_with_a_relay_frame_is_attributed_to_the_relay` drives `ConfigHelper.new_client_behind_seconds()` *precisely because* the query then carried a frame under `apps/proxy/live_proxy/`. After the move it does not, and the test fails with `AssertionError: [] is not true : a query issued from apps/proxy/live_proxy/config_helper.py was not attributed to the relay` — correctly, since its premise is gone. The replacement is `apps/proxy/live_proxy/views.py`'s `_output_profile_for`, driven with a `SimpleNamespace(trusted=True, output_profile_id=1)`: a module-level function inside the package, needing no Redis and no channel, whose `OutputProfile.objects.filter` at `views.py:152` is itself one of the eleven remaining SITES. Measured green.

**The prose that cites the deleted SITE is updated, not left dangling.** Six places besides the entry being re-pointed — `zero_orm_allowlist.py:439`, `:629`, `:636`, `:639`, `:665` and `:672` — cite "config_helper.py:50" inside comments and `reason` strings. Nothing asserts on them, but a comment citing an entry this PR deleted is exactly the stale-citation shape this programme keeps finding, and two of the six say more than a path: `:439` is another `EdgeEntry`'s `closed_by` pointing at the SITE entry "above" that this PR deletes, and `:636` calls the read "an already-allowlisted SITE", which after this PR it is not. **Appendix E makes all seven corrections** — the re-pointed entry's own `reason` plus those six — and Task 4 Step 3 is the verification, with the per-citation table.

### R8 — The boot-check hook arm takes six literal paths

`.claude/hooks/run-affected-tests.sh:133-146`'s `case` arm matches `apps/proxy/live_proxy/constants.py|apps/proxy/live_proxy/redis_keys.py` **by literal path** and runs `manage.py check`. After the relocation it matches nothing of interest, and the failure mode is silence: no error, no output, the `case` falls through. A10.3 names this and this plan sizes it.

**Six paths, not two, and not three.**

- `apps/proxy/constants.py`, `apps/proxy/redis_keys.py` — the new homes, because that is where a cycle now stops Django booting. **Measured**: adding `from apps.channels.models import Channel` to `apps/proxy/constants.py` makes `manage.py check` exit 1 with `ImportError: cannot import name 'Channel' from partially initialized module 'apps.channels.models' (most likely due to a circular import)`. The trap moved house; it did not go away.
- `apps/proxy/config_helper.py` — although `apps/channels/models.py` does not import it. `apps/timeshift/views.py:40` does, at module level, and `manage.py check` loads the urlconf. It is the same class of file and it costs one alternation.
- The three `apps/proxy/live_proxy/` paths — until 2d-4 deletes them. They are still imported by every relay module, and `apps/proxy/apps.py`'s `ready()` reaches them in every process that is not `manage.py`.

`CLAUDE.md` § Test hooks names the same two paths in prose and § Structural constraints describes the trap in terms of `live_proxy/constants.py`. Both are corrected **in this PR**, not deferred to 2d-6: the per-PR correction convention is what keeps the document from accumulating a backlog of sentences that were true when written, and 2d-6 is a consolidation pass rather than the only place a correction may land.

### R9 — `manage.py check` does not vary by role, and `makemigrations --check` is already dirty at the seed

§ Stage 2d's PR 1 gate says "`manage.py check` green" and the brief for this plan reads it as "green in every role". Measured: **`DISPATCHARR_ROLE` appears in no Python file in the tree.**

```bash
grep -rn "DISPATCHARR_ROLE" --include='*.py' .   # empty at 16fbb952
```

It selects supervisord programs in `docker/`, and every role runs the same Django module graph. So there is one `manage.py check` to run, not four. What a single `check` does **not** exercise is the migration loader, which is the trap's actual victim, so this plan pairs it with `manage.py showmigrations dispatcharr_channels` — a command that imports every migration module in the app whose `models.py` this PR edits.

**And "every backend label green" is five labels, not sixteen.** `scripts/ci_backend_test_labels.py` routes all sixteen paths this PR touches to `apps.channels.tests`, `apps.proxy.live_proxy.tests`, `apps.proxy.tests`, `apps.timeshift.tests` and `core.tests` (Task 0 Step 7 runs the command). Nothing this PR touches sits under `dispatcharr/test_discovery.py`'s `_SHARED_PATH_PREFIXES` — `dispatcharr/`, `pyproject.toml`, `manage.py` and the rest — which is what would force the full sixteen, and CI's own `plan` job derives its labels from the same function. So five is what `Backend result` will run, and it is not a shortfall against the spec's wording.

Separately: **`makemigrations --check` is not clean at the seed, before this PR touches anything.**

```
Migrations for 'core':
  core/migrations/0028_alter_streamprofile_parameters.py
    ~ Alter field parameters on streamprofile
```

exit 1. Verified by running it on a pristine checkout of `16fbb952`. Nothing in CI runs it (CLAUDE.md § Known defects already records that), and the edit hook runs it **per app**, resolving the label through `apps.get_app_configs()`. The honest gate item for this PR is therefore "`makemigrations --check dispatcharr_channels` reports no changes" — measured, `No changes detected in app 'dispatcharr_channels'` — and the pre-existing `core` drift is neither caused nor fixed here. Task 0 Step 4 records it so the implementer does not discover it mid-PR and try to fix it.

### R10 — The catalogue note lands here; the milestone row is a follow-up

`scripts/metrics/collect_architecture.py:159-182` counts module-level `apps.proxy.live_proxy` imports in **`apps/channels/models.py` only**. Measured at the seed it is **2**; on this PR's shape it is **0**. `reverse_imports_into_proxy` is unmoved at **29**, because every re-pointed import still names `apps.proxy`.

§ Stage 2d's PR 1 entry asks this PR for "a milestone line". **It cannot commit one.** A `metrics/curated/milestones.yml` row carries the merge SHA (`# Every sha is a first-parent commit on main`), and a merge commit cannot name itself — 2c-9's Ruling R13, and the precedent of #276 for stage 2b. The row is a one-line PR after this one merges, and Task 9's PR body says so in the follow-ups list so it is not lost.

What this PR **does** commit to `metrics/curated/` is the catalogue note sentence A10.17 assigns to 2d-6. It moves here because the tile reads zero from the moment this PR merges, and `models_boot_trap_imports` carries `headline: true` — four PRs of a headline tile reading zero while eight module-level import sites are still live is the cost of leaving it where A10.17 put it. Amendment A11.5 edits A10.17's bullet in place.

### R11 — `ConfigHelper` is not replaced by direct `TSConfig` calls

The alternative to moving `ConfigHelper` is deleting the dependency: have `apps/timeshift/views.py` and `apps/channels/tasks.py` call `apps.proxy.config.TSConfig` directly — a module that is already outside the doomed package — and let `ConfigHelper` die with the relay at 2d-4. Declined.

Measured, the surviving callers are **six** call sites on five lines, not two: `apps/timeshift/views.py:1490`, `:3081`, `:3082`, `:3165` and `apps/channels/tasks.py:1126` (two calls on that one line), plus a whole test class, `apps/proxy/tests/test_boundary_error_arms.py:18`'s `ConfigHelperDefaultLadderTests`, which tests `ConfigHelper`'s default ladder as its subject. Rewriting six call sites in surviving production code and a test class that would have to be rewritten or deleted is strictly more churn — and more risk, since `ConfigHelper.stream_timeout()` and `TSConfig.STREAM_TIMEOUT` are not the same expression — than moving one 135-line file. A10.3's ruling stands unchanged.

### R12 — One known flake lives on this label, and it is the seed's

`apps.proxy.live_proxy.tests.test_manager_stderr_failover.FfmpegStderrFailoverTests.test_a_buffering_threshold_change_does_not_reach_a_running_channel` fails intermittently with

```
AssertionError: 3 not greater than or equal to 4 : too few distinct speeds after the change to prove records were still being parsed: [...]
```

It is issue **#259**, which `scripts/coverage_live_path_isolated.sh` names in its own failure text ("grep the label's log for 'never observed the lead at all' or 'too few distinct speeds' before investigating coverage"). It fired on **both** attempts at a clean seed coverage round while preparing this plan, and once on a relocated tree that passed on re-run. **Re-run; do not attribute it to this PR, and never lower the asserted count.** If it fires three times in a row on this branch, stop and report — that would be new.

---

## File structure

**Created:**

| Path | Responsibility |
|---|---|
| `apps/proxy/redis_keys.py` | `RedisKeys`. A leaf: no imports at all. Loaded by every migration and management command through `apps/channels/models.py:6`. |
| `apps/proxy/constants.py` | `ChannelState` and `ChannelMetadataField`. A leaf: no imports at all. |
| `apps/proxy/config_helper.py` | `ConfigHelper`. Imports `apps.proxy.config` and nothing else first-party. |

**Modified:**

| Path | Change |
|---|---|
| `apps/proxy/live_proxy/redis_keys.py` | Becomes a one-statement re-export shim. |
| `apps/proxy/live_proxy/config_helper.py` | Becomes a one-statement re-export shim. |
| `apps/proxy/live_proxy/constants.py` | Loses two classes, re-exports them, keeps the other nine names. |
| `apps/channels/models.py` | Two import lines (`:6`, `:7`). **Nothing else** — Constraint 4. |
| `apps/channels/tasks.py` | Two function-local import lines (`:1125`, `:2445`). |
| `apps/proxy/relay_client.py`, `apps/proxy/relay_views.py`, `apps/proxy/next_source.py`, `core/utils.py` | Six import lines between them. |
| `apps/timeshift/views.py`, `apps/timeshift/stats.py` | Three import lines. |
| `apps/timeshift/tests/test_views.py`, `apps/timeshift/tests/test_stats.py` | Five import lines (R6). |
| `apps/proxy/live_proxy/tests/zero_orm_allowlist.py` | One `Site` deleted, one `EdgeEntry` re-pointed (R7). |
| `apps/proxy/live_proxy/tests/test_zero_orm_scan.py` | One test's driver replaced (R7 iii). |
| `.claude/hooks/run-affected-tests.sh` | The boot-check `case` arm: two literal paths become six (R8). |
| `CLAUDE.md` | § Test hooks (two sentences) and § Structural constraints (one bullet). |
| `metrics/curated/catalogue.yml` | One `note:` gains a sentence (R10). |
| `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` | Amendment A11, four in-place corrections to A10 and the deletion list, and the Done-log row. |

**Deliberately not touched, each for a stated reason:** `scripts/coverage_live_path.{sh,coveragerc,floor,floor.modules}` (R4 — the gate must not be able to be re-baselined by this PR); `metrics/curated/milestones.yml` (R10); `apps/channels/models.py`'s five #190 ranges (Constraint 4, A10.17); `apps/proxy/authorize.py` (R5 — its `live_proxy` import is 2d-4's); `dispatcharr/settings.py`, `dispatcharr/urls.py`, `apps/proxy/urls.py`, `apps/proxy/apps.py`, `apps/proxy/tasks.py`, `apps/proxy/relay_urls.py` (A10.3 sites 1, 5, 6, 7, 9 — all 2d-4's); `dispatcharr/test_discovery.py` and `.github/workflows/backend-tests.yml` (their `apps.proxy.live_proxy` label still exists; A10.4 assigns both to 2d-4); `docker/**`, `relay/**`, `e2e/**`, `frontend/**` (nothing here reaches them).

---

## Task 0: Verify the seed

Runs before anything else. Every figure in this plan was measured at `16fbb952`; this task is what confirms the tree still is that one, and records the four numbers later tasks compare against.

**Files:** none modified.

**Interfaces:**
- Consumes: `origin/main` at `16fbb952`.
- Produces: a go/no-go for Tasks 1–9.

- [ ] **Step 1: Create the worktree and branch**

```bash
git -C /Users/dion/git/Dispatcharr fetch origin
git -C /Users/dion/git/Dispatcharr worktree add \
  /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation \
  -b migration/phase2d-boot-trap-relocation origin/main
git -C /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation rev-parse HEAD
```

Expected: `16fbb952942a64115928e8d0ff8dacce3d0eb976`.

**If it is not, `origin/main` has moved, and exactly one move is acceptable.** Check what came in:

```bash
git -C /Users/dion/git/Dispatcharr diff --stat 16fbb952942a64115928e8d0ff8dacce3d0eb976..origin/main
```

If the only changed path is `metrics/curated/milestones.yml`, that is **#321**, the stage-2c milestone row Amendment A10.17 said should land before 2d-1 — measured after this plan was written, `origin/main` at `57618a28ed86820a46012776e65d6b7d8beb356d`, one insertion in that one file. It touches nothing this plan reads, no figure in this plan moves, and the branch proceeds on `origin/main` unchanged. **Any other path in that diff is a stop-and-report**, because every count, hash and line number below was measured at the seed and a change elsewhere may have moved one.

- [ ] **Step 2: Confirm the four modules are shaped as this plan assumes**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
for f in redis_keys constants config_helper; do
  echo "== apps/proxy/live_proxy/$f.py"
  grep -n "^import \|^from " "apps/proxy/live_proxy/$f.py" || echo "  (no module-level imports)"
done
ls apps/proxy/redis_keys.py apps/proxy/constants.py apps/proxy/config_helper.py 2>&1 | head -3
```

Expected, in order: `redis_keys.py` and `constants.py` print `(no module-level imports)`; `config_helper.py` prints `5:from apps.proxy.config import TSConfig as Config` — **`:5` here is the SEED file**, whose docstring is four lines; and the three `ls` targets all report **No such file or directory**. A pre-existing `apps/proxy/constants.py` is a stop-and-report — R1's no-collision claim would be false.

- [ ] **Step 3: Record the four counts this PR moves**

**`git grep`, not `grep -r .`** — see R5 for why; the short version is that `grep -r .` emits a `./` prefix some implementations on this harness's `PATH` do not, which silently turns a `grep -v` path filter into a no-op, and it walks the filesystem rather than the index.

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
set -o pipefail
PAT='^[[:space:]]*from [A-Za-z_. ]*(redis_keys|constants|config_helper) import .*(RedisKeys|ChannelMetadataField|ChannelState|ConfigHelper)'
echo -n "140? all import statements naming the four symbols: "
git grep -nE "$PAT" -- '*.py' | wc -l
echo -n "19? outside the package, minus the files 2d-4 disposes of: "
git grep -nE "$PAT" -- '*.py' ':!apps/proxy/live_proxy/*' ':!apps/proxy/tests/*' ':!apps/channels/tests/*' \
  | grep -v 'apps\.timeshift\.redis_keys' | wc -l
echo -n "33? non-test inside the package: "
git grep -nE "$PAT" -- 'apps/proxy/live_proxy/*.py' 'apps/proxy/live_proxy/**/*.py' ':!apps/proxy/live_proxy/tests/*' | wc -l
echo -n "31? test inside the package: "
git grep -nE "$PAT" -- 'apps/proxy/live_proxy/tests/*' | wc -l
echo -n "2? models_boot_trap_imports: "
python3 scripts/metrics/collect_architecture.py | python3 -c "import sys,json; print(json.load(sys.stdin)['models_module_level_live_proxy_imports'])"
echo -n "29? reverse_imports_into_proxy: "
python3 scripts/metrics/collect_architecture.py | python3 -c "import sys,json; print(json.load(sys.stdin)['reverse_imports_into_proxy'])"
```

Expected: `140`, `19`, `33`, `31`, `2`, `29` — all six measured at the seed. Print the nineteen and diff them against R5's table; they match row for row.

**The `apps.timeshift.redis_keys` filter is not optional.** `apps/timeshift/redis_keys.py` holds a different class, `TimeshiftRedisKeys`, which forty-five sites import — forty of them `as RedisKeys`, which is why they look like hits. Without that filter the second command returns **63**. A different 140 or 19 means R3's and R5's tables need re-deriving before anything is edited — **stop and report** with the actual list.

- [ ] **Step 4: Record the floor's current values and the pre-existing migration drift**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
grep -E '^(shape|statements|missing|percent|measured|runs|modules|module_count|rcfile)=' scripts/coverage_live_path.floor
```

Expected: `shape=per-container/v1-sysmon`, `statements=8073`, `missing=1525`, `percent=81.11`, `measured=2026-09-13`, `runs=12`, `modules=8cb5c65dac3e`, `module_count=38`, `rcfile=3af0a78b9b6f`. These are the values Task 7 compares against and the values this PR leaves **unchanged** (Constraint 6).

- [ ] **Step 5: Start your own test container**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
DISPATCHARR_TEST_CONTAINER=phase2d1 DISPATCHARR_TEST_DB_VOLUME=phase2d1-hookdb \
  CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation \
  .claude/hooks/start-test-container.sh
```

Expected: `==> ready`. Do **not** re-point `dispatcharr-testrunner`; another agent may hold it.

Define this helper once and use it for every `docker exec` below — it is `run-affected-tests.sh:86-93`'s `dexec` verbatim:

```bash
dx() { docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
  phase2d1 /dispatcharrpy/bin/python "$@"; }
```

- [ ] **Step 6: Take the boot-path baseline, and record the pre-existing `makemigrations` drift**

```bash
dx manage.py check 2>&1 | grep -E "System check|Error" | head -3
dx manage.py showmigrations dispatcharr_channels 2>&1 | tail -2
dx manage.py makemigrations --check --dry-run dispatcharr_channels 2>&1 | tail -2
dx manage.py makemigrations --check --dry-run 2>&1 | tail -4
```

Expected: `System check identified 1 issue (0 silenced)` — the pre-existing `staticfiles.W004` warning about a missing `frontend/dist`, not an error; `showmigrations` prints the app's migration list ending at `0038_add_catchup_fields`; `No changes detected in app 'dispatcharr_channels'`; and the **whole-project** run reports `Migrations for 'core': core/migrations/0028_alter_streamprofile_parameters.py`. That last one is R9's pre-existing drift. **Record it and leave it alone.** If it is absent, someone fixed it upstream and R9's caveat can be dropped from the PR body — that is the only thing that changes.

- [ ] **Step 7: Take the five-label baseline**

```bash
for L in core.tests apps.timeshift.tests apps.proxy.tests apps.channels.tests apps.proxy.live_proxy.tests; do
  docker exec phase2d1 redis-cli flushall >/dev/null 2>&1
  echo "##### $L"
  OUT="$(dx manage.py test --keepdb "$L" -v1 2>&1)" || true
  printf '%s\n' "$OUT" | grep -aE '^(Ran [0-9]+ tests|OK|FAILED)' | head -3
  printf '%s\n' "$OUT" | grep -aE '^(FAIL|ERROR): ' | head -10
done
```

Expected on the seed: `core.tests` 105 OK, `apps.timeshift.tests` 349 OK, `apps.proxy.tests` 403 OK, `apps.channels.tests` 441 OK, `apps.proxy.live_proxy.tests` 429 `OK (skipped=1)`. These five are the labels `scripts/ci_backend_test_labels.py` routes this PR's paths to; confirm with

```bash
python3 scripts/ci_backend_test_labels.py apps/proxy/redis_keys.py apps/proxy/constants.py \
  apps/proxy/config_helper.py apps/proxy/live_proxy/redis_keys.py apps/proxy/live_proxy/constants.py \
  apps/proxy/live_proxy/config_helper.py apps/proxy/relay_views.py apps/proxy/relay_client.py \
  apps/proxy/next_source.py apps/channels/models.py apps/channels/tasks.py apps/timeshift/views.py \
  apps/timeshift/stats.py apps/timeshift/tests/test_views.py apps/timeshift/tests/test_stats.py core/utils.py
```

Expected: `["apps.channels.tests", "apps.proxy.live_proxy.tests", "apps.proxy.tests", "apps.timeshift.tests", "core.tests"]`.

If `test_a_buffering_threshold_change_does_not_reach_a_running_channel` fails here, that is R12's flake **on the seed**: re-run the label once and carry on. Record that it fired.

- [ ] **Step 8: Commit nothing.** This task writes no file.

---

## Task 1: The three new modules

**Files:**
- Create: `apps/proxy/redis_keys.py`, `apps/proxy/constants.py`, `apps/proxy/config_helper.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the four names at their new import paths.

- [ ] **Step 1: Apply Appendix A**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
git apply --check --whitespace=error /path/to/appendix-a.diff && git apply /path/to/appendix-a.diff
```

Write the appendix to a file and apply it; do not retype the modules. Appendix A is a unified diff against the seed that `git apply --check --whitespace=error` accepts as-is.

`apps/proxy/redis_keys.py` and `apps/proxy/config_helper.py` are their originals with the module docstring replaced. **`redis_keys.py` alone also loses one byte**: the seed's `apps/proxy/live_proxy/redis_keys.py` ends with a blank line before EOF, which `git apply --whitespace=error` rejects in a newly added file. `apps/proxy/live_proxy/config_helper.py` has no such trailing blank and its copy is byte-identical below the docstring. `apps/proxy/constants.py` carries `ChannelState` and `ChannelMetadataField` verbatim and nothing else (R2).

- [ ] **Step 2: Verify the leaf property mechanically**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
grep -n "^import \|^from " apps/proxy/redis_keys.py apps/proxy/constants.py || echo "both leaves: OK"
grep -n "^import \|^from " apps/proxy/config_helper.py
python3 -c "
from coverage.parser import PythonParser
for f in ['apps/proxy/redis_keys.py','apps/proxy/constants.py','apps/proxy/config_helper.py']:
    p=PythonParser(filename=f); p.parse_source(); print(len(p.statements), f)"
```

Expected: `both leaves: OK`; `config_helper.py` prints exactly one module-level import, **`21:from apps.proxy.config import TSConfig as Config`**; and the statement counts are **85**, **64**, **73**. A different count means the appendix was edited on the way in.

**`:21`, not the seed's `:5`.** The new module's docstring is sixteen lines longer than the one it replaces, so every line in `apps/proxy/config_helper.py` sits sixteen lower than in `apps/proxy/live_proxy/config_helper.py`. The same shift is why the ORM read this module carries is at `:66` and not `:50` (B5's ground, and R7's).

- [ ] **Step 3: Confirm the bodies are unchanged from their originals**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
diff <(sed -n '/^class RedisKeys:/,$p' apps/proxy/redis_keys.py) \
     <(sed -n '/^class RedisKeys:/,$p' apps/proxy/live_proxy/redis_keys.py) \
  && echo "RedisKeys body identical"
diff <(sed -n '/^class ConfigHelper:/,$p' apps/proxy/config_helper.py) \
     <(sed -n '/^class ConfigHelper:/,$p' apps/proxy/live_proxy/config_helper.py) \
  && echo "ConfigHelper body identical"
```

Expected, and the two differ:

```
155a156
> 
RedisKeys body DIFFERS
ConfigHelper body identical
```

The `RedisKeys` comparison exits **1** and reports `155a156 >` — the one trailing blank line Step 1 removes — so its `&& echo "RedisKeys body identical"` does **not** fire. That single added blank line, and the `>` with nothing after it, is the **only** acceptable difference: any line of real content in either `diff` is a **stop**. `ConfigHelper` exits 0 and prints its `identical` line. This is the check that the move is a move.

**Run this step with only Appendix A applied** — that is, before Task 2. Once the shims land, `apps/proxy/live_proxy/redis_keys.py` no longer contains `class RedisKeys:` at all and the comparison degenerates into "the whole class was added", which proves nothing. (An earlier draft of this plan was verified against a fully-applied tree and got exactly that useless output; it is recorded here so the next reader does not repeat it.)

- [ ] **Step 4: Do not commit yet.** The tree is importable but nothing uses the new modules; Tasks 1–4 are one commit.

---

## Task 2: The three shims

**Files:**
- Modify: `apps/proxy/live_proxy/redis_keys.py`, `apps/proxy/live_proxy/config_helper.py`, `apps/proxy/live_proxy/constants.py`

**Interfaces:**
- Consumes: Task 1's three modules.
- Produces: the old import paths, still working, for the 121 statements this PR does not re-point.

- [ ] **Step 1: Apply Appendices B and C**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
git apply --check --whitespace=error /path/to/appendix-b.diff && git apply /path/to/appendix-b.diff
git apply --check --whitespace=error /path/to/appendix-c.diff && git apply /path/to/appendix-c.diff
```

Appendix C is the two whole-file shims; Appendix B is `constants.py`'s split, which keeps the file's own docstring and its nine remaining names and puts the re-export between the `REDIS_TTL_*` block and `EventType`.

- [ ] **Step 2: Verify the shim statement counts**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
python3 -c "
from coverage.parser import PythonParser
t=0
for f in ['apps/proxy/live_proxy/redis_keys.py','apps/proxy/live_proxy/constants.py','apps/proxy/live_proxy/config_helper.py']:
    p=PythonParser(filename=f); p.parse_source(); print(len(p.statements), f); t+=len(p.statements)
print(t, 'in-denominator total (was 246)')"
```

Expected: `1`, `25`, `1`, total **27** — the figure R4's 8202 → 7983 arithmetic rests on (246 − 27 = 219).

**The `1`s are NOT load-bearing, and an earlier draft of this plan said they were.** Gate 2 hashes a set of **paths** and never reads a statement count, so a shim would keep its file in the set at zero statements too — `apps/proxy/live_proxy/__init__.py` is zero bytes, has zero statements, and is line 6 of the committed `scripts/coverage_live_path.floor.modules` with `skip_empty = True` set throughout. `skip_empty` suppresses a file from the **text** table only. What keeps `modules=` stable is that the three old paths still exist (R3, R4).

- [ ] **Step 3: Confirm the package still imports, and that the shims re-export the same objects**

A bare `python -c "import apps.proxy.live_proxy.server"` is **not** the check to use here, and an earlier draft of this plan used it: it raises `django.core.exceptions.AppRegistryNotReady: Apps aren't loaded yet.` on the **seed** as readily as on the finished tree, because that module reaches `core/models.py` at import time. Measured, exit 1 on both. A check that is red before you start cannot tell you anything about what you did. `django.setup()` first:

```bash
docker exec -w /repo -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
  phase2d1 /dispatcharrpy/bin/python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','dispatcharr.settings')
django.setup()
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState, EventType, StreamType, TS_PACKET_SIZE
from apps.proxy.live_proxy.config_helper import ConfigHelper
from apps.proxy.redis_keys import RedisKeys as R2
from apps.proxy.constants import ChannelMetadataField as C2
from apps.proxy.config_helper import ConfigHelper as H2
assert RedisKeys is R2 and ChannelMetadataField is C2 and ConfigHelper is H2
print('shims re-export the same objects: OK')"
```

Expected: **exit 0**, with `shims re-export the same objects: OK` as the **last line**. `django.setup()` first emits stderr noise in this container — a `RuntimeWarning: Accessing the database during app initialization is discouraged` and two `WARNING … relation "core_coresettings"/"core_systemnotification" does not exist` lines — because the hook container migrates only the **test** database and `django.setup()` touches the app one. Measured identical on the seed; it is pre-existing and not a failure. **The exit status and the final line are the assertions.** This is strictly stronger than an import check — it proves the shim is a re-export and not a second definition, and it proves the nine names Appendix B leaves behind are still importable from the old path. Note the command is deliberately **not** piped: Global Constraint 14, and this is the exact step where an earlier draft laundered a real failure into a plausible pass by reading `$?` after a `| tail -3`.

Then the boot path:

```bash
dx manage.py check > /tmp/2d1-check.txt 2>&1; echo "exit=$?"; grep -E "System check|Error" /tmp/2d1-check.txt | head -3
```

Expected: `exit=0` and `System check identified 1 issue (0 silenced)` — the same `staticfiles.W004` as Task 0 Step 6. Anything else is a **stop**.

- [ ] **Step 4: Do not commit yet.**

---

## Task 3: The nineteen re-points

**Files:**
- Modify: the ten files in R5's table.

**Interfaces:**
- Consumes: Task 1's three modules.
- Produces: a tree in which no file stage 2d KEEPS imports these four names from `apps.proxy.live_proxy`.

- [ ] **Step 1: Apply Appendix D**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
git apply --check --whitespace=error /path/to/appendix-d.diff && git apply /path/to/appendix-d.diff
```

Every change is a single line turning `apps.proxy.live_proxy.<module>` into `apps.proxy.<module>`: **nineteen lines, sixteen hunks, ten files** — sixteen rather than nineteen because `models.py:6-7` and `relay_views.py:38-39` are adjacent pairs that `git diff` folds into one hunk each.

- [ ] **Step 2: Verify nothing outside the package still names the four symbols through the old path**

**`git grep` with a pathspec, and no `grep -v` at all** — the same reason Task 0 Step 3 and R5 give: a `grep -v "^./apps/proxy/live_proxy/"` filter over `grep -r .` output is a no-op under any `grep` that does not emit the `./` prefix, and this step's stop rule fires on exactly what then survives. Measured on this PR's own tree: **12** lines with `/usr/bin/grep`, **44** under this harness's wrapped `grep`, **12** with the form below under either.

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
git grep -nE "^[[:space:]]*from apps\.proxy\.live_proxy\.(redis_keys|constants|config_helper) import" \
  -- '*.py' ':!apps/proxy/live_proxy/*'
```

Expected: exactly **seven files, twelve lines** — `apps/proxy/tests/test_stream_switch.py:12` and `:13`, `apps/proxy/tests/test_boundary_error_arms.py:15`, `apps/channels/tests/test_ts_proxy_teardown.py:7` and `:10`, `apps/channels/tests/test_get_stream_assignment.py:9` and `:10`, `apps/channels/tests/test_ts_proxy_initializing.py:14` and `:15`, `apps/channels/tests/test_channel_stream_reuse.py:15`, `apps/channels/tests/test_ts_proxy_ghost_clients.py:15` and `:16`. **Nothing under `apps/timeshift/` and nothing outside `*/tests/`.** A timeshift hit means R6's five lines were missed; a non-test hit means one of R5's nineteen was.

- [ ] **Step 3: Verify the #190 ranges are untouched**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
git diff --stat apps/channels/models.py
git diff apps/channels/models.py | grep -E '^[-+]' | grep -v '^[-+][-+]'
```

Expected: `2 insertions(+), 2 deletions(-)`, and the four printed lines are the two old imports and the two new ones. **Any other line in that diff is a Constraint 4 violation — revert it.** The five ranges at `:516-519`, `:696-702`, `:717-721`, `:747-750` and `:773-778` do not appear.

- [ ] **Step 4: Run the boot path**

```bash
dx manage.py check 2>&1 | grep -E "System check|Error" | head -3
dx manage.py showmigrations dispatcharr_channels 2>&1 | tail -1
dx manage.py makemigrations --check --dry-run dispatcharr_channels 2>&1 | tail -1
```

Expected: `System check identified 1 issue (0 silenced)`; the migration list's last line; `No changes detected in app 'dispatcharr_channels'`.

- [ ] **Step 5: Do not commit yet.** Gate 1 is red until Task 4; a commit here would be blocked by the commit gate, correctly.

---

## Task 4: Gate 1 follows `ConfigHelper` out of scope 1

R7 is the whole argument; this task is its execution. It is in the same commit as Tasks 1–3 because the relocation makes the allowlist wrong the instant it lands.

**Files:**
- Modify: `apps/proxy/live_proxy/tests/zero_orm_allowlist.py`, `apps/proxy/live_proxy/tests/test_zero_orm_scan.py`

**Interfaces:**
- Consumes: Task 1's `apps/proxy/config_helper.py`.
- Produces: `apps.proxy.live_proxy.tests` green again.

- [ ] **Step 1: See it fail first**

```bash
docker exec phase2d1 redis-cli flushall >/dev/null 2>&1
dx manage.py test --keepdb apps.proxy.live_proxy.tests.test_zero_orm_reads -v1 2>&1 \
  | awk '/^(FAIL|ERROR):/{f=1} f' | head -30
```

Expected: **two** failures, and their messages are the specification for this task:

```
FAIL: test_every_orm_site_in_the_relay_package_is_allowlisted
AssertionError: Items in the second set but not the first:
('apps/proxy/live_proxy/config_helper.py', 50) :
...
listed but gone (delete the entry -- the ratchet runs both ways ...):
  apps/proxy/live_proxy/config_helper.py:50

FAIL: test_every_in_process_import_edge_is_allowlisted
AssertionError: Items in the first set but not the second:
('apps/proxy/live_proxy/config_helper.py', 'apps.proxy.config_helper', 'ConfigHelper')
Items in the second set but not the first:
('apps/proxy/live_proxy/config_helper.py', 'apps.proxy.config', 'TSConfig')
```

If a **third** failure appears — in particular an edge naming `apps.proxy.redis_keys` or `apps.proxy.constants` — then one of `RedisKeys`, `ChannelState` or `ChannelMetadataField` has grown an ORM call since the seed, and R7's "only `ConfigHelper` reaches the ORM" no longer holds. **Stop and report.**

Then run `test_zero_orm_scan` and see its one failure:

```bash
dx manage.py test --keepdb apps.proxy.live_proxy.tests.test_zero_orm_scan -v1 2>&1 \
  | awk '/^(FAIL|ERROR):/{f=1} f' | head -20
```

Expected: `AssertionError: [] is not true : a query issued from apps/proxy/live_proxy/config_helper.py was not attributed to the relay`.

- [ ] **Step 2: Apply Appendix E**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
git apply --check --whitespace=error /path/to/appendix-e.diff && git apply /path/to/appendix-e.diff
```

It deletes the `Site` entry, re-points the `EdgeEntry` with `hits=1` and a `reason` that explains the narrowing in place, and replaces the attribution test's driver.

- [ ] **Step 3: Sweep the prose that cites the deleted SITE**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
grep -n "config_helper.py:50" apps/proxy/live_proxy/tests/zero_orm_allowlist.py
```

Expected: **exactly one hit**, at `:437`, inside the re-pointed `EdgeEntry`'s own `reason`:

```
437:            "which was apps/proxy/live_proxy/config_helper.py:50's SITE entry "
```

That one is deliberate and correct — it cites the **deleted entry's own coordinates**, which were and remain `apps/proxy/live_proxy/config_helper.py:50`, fully qualified so it cannot be read as a claim about where the read is now.

**Appendix E makes all seven corrections; this step is the verification, not the work.** An earlier draft of this plan left four of them as a hand-instruction and got both the count and the line number wrong, so the enumeration is recorded here. On the seed there are **six** citations of `config_helper.py:50` besides the entry being re-pointed — `zero_orm_allowlist.py:439`, `:629`, `:636`, `:639`, `:665`, `:672` — and each needed a different fix:

| seed line | what it said | why a path re-qualification was not enough |
|---|---|---|
| `:439` | another `EdgeEntry`'s `closed_by`: "same as config_helper.py:50's SITE entry **above**" | this PR deletes that entry, so the cross-reference dangles whatever the path says |
| `:629` | `# NOT marked exercised: config_helper.py:50's …` | path only |
| `:636` | `# … for an already-allowlisted SITE (config_helper.py:50).` | after this PR the read is **not** an allowlisted SITE — it left scope 1 |
| `:639` | `"config_helper.py:50's TSConfig.get_proxy_settings() reads …"` | path only |
| `:665` | `# … so config_helper.py:50's TSConfig.get_proxy_…` | path only |
| `:672` | `"As SQL_SIGNATURES' proxy_settings_group: config_helper.py:50's …"` | path only |

**And the line number moves with the path.** The read is at `apps/proxy/config_helper.py:`**`66`**, not `:50`: the code is byte-identical and the new module's docstring is sixteen lines longer (the same shift Task 1 Step 2 sees on the import). Writing `apps/proxy/config_helper.py:50` would plant a fresh stale citation — the exact failure shape this sweep exists to prevent.

- [ ] **Step 4: Watch both tests go green**

```bash
docker exec phase2d1 redis-cli flushall >/dev/null 2>&1
dx manage.py test --keepdb apps.proxy.live_proxy.tests.test_zero_orm_reads -v1 2>&1 | grep -aE '^(Ran|OK|FAILED)'
dx manage.py test --keepdb apps.proxy.live_proxy.tests.test_zero_orm_scan -v1 2>&1 | grep -aE '^(Ran|OK|FAILED)'
```

Expected: `Ran 11 tests`, `OK`; `Ran 9 tests`, `OK`.

- [ ] **Step 5: Confirm the SITES and EDGES totals**

```bash
docker exec -w /repo phase2d1 /dispatcharrpy/bin/python -c "
import sys; sys.path.insert(0,'/repo')
from apps.proxy.live_proxy.tests import zero_orm_allowlist as a, zero_orm_scan as z
print('SITES', len(a.SITES), 'EDGES', len(a.EDGES))
print('scanner sites', len(z.scan_relay_package()))
e=z.Edge('apps/proxy/live_proxy/config_helper.py','apps.proxy.config_helper','ConfigHelper')
print('hits', len(z.scan_edge(e)), z.scan_edge(e))"
```

Expected: `SITES 11 EDGES 12`, `scanner sites 11`, and `hits 1` with the single hit

```
Hit(path='apps/proxy/config_helper.py', lineno=66, symbol='get_proxy_settings', shape='model_method')
```

**`lineno=66`, not `50`** — R7 and Task 4 Step 3 both say why. A `50` here would mean the new module's docstring is not the one Appendix A ships.

- [ ] **Step 6: Break-checks**

Each is a reversion applied on top of the finished task, the command that must go red, and the message it prints. Revert each before the next.

| # | reversion | command | must print |
|---|---|---|---|
| 1 | restore the deleted `Site(config_helper.py, 50)` entry | `dx manage.py test --keepdb …test_zero_orm_reads.StaticScopeOneTests` | `listed but gone … apps/proxy/live_proxy/config_helper.py:50` |
| 2 | set the `EdgeEntry` back to `module="apps.proxy.config", name="TSConfig"` | `…test_zero_orm_reads.StaticScopeTwoTests` | both tuples, `Items in the first set but not the second: (…, 'apps.proxy.config_helper', 'ConfigHelper')` |
| 3 | leave the re-pointed `EdgeEntry` but set `hits=5` | `…test_zero_orm_reads.StaticScopeTwoTests` | `apps.proxy.config_helper.ConfigHelper now holds a different number of ORM sites than when it was cleared` |
| 4 | point the attribution test's driver back at `ConfigHelper.new_client_behind_seconds()` | `…test_zero_orm_scan` | `[] is not true : a query issued from …` |

All four were run while writing this plan and produced exactly those messages. **A break-check that stays green is a finding, not a formality** — report it rather than moving on.

- [ ] **Step 7: Run the five labels, then commit Tasks 1–4 together**

```bash
for L in core.tests apps.timeshift.tests apps.proxy.tests apps.channels.tests apps.proxy.live_proxy.tests; do
  docker exec phase2d1 redis-cli flushall >/dev/null 2>&1
  echo "##### $L"
  OUT="$(dx manage.py test --keepdb "$L" -v1 2>&1)" || true
  printf '%s\n' "$OUT" | grep -aE '^(Ran [0-9]+ tests|OK|FAILED)' | head -3
  printf '%s\n' "$OUT" | grep -aE '^(FAIL|ERROR): ' | head -10
done
```

Expected: 105 OK / 349 OK / 403 OK / 441 OK / 429 `OK (skipped=1)` — the same counts as Task 0 Step 7. All five were measured green on this PR's exact shape. If `test_a_buffering_threshold_change_does_not_reach_a_running_channel` fires, that is R12: re-run.

Then stage and commit, in **separate Bash calls** (Constraint 11):

```bash
git -C /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation add \
  apps/proxy/redis_keys.py apps/proxy/constants.py apps/proxy/config_helper.py \
  apps/proxy/live_proxy/redis_keys.py apps/proxy/live_proxy/constants.py apps/proxy/live_proxy/config_helper.py \
  apps/channels/models.py apps/channels/tasks.py apps/proxy/relay_client.py apps/proxy/relay_views.py \
  apps/proxy/next_source.py core/utils.py apps/timeshift/views.py apps/timeshift/stats.py \
  apps/timeshift/tests/test_views.py apps/timeshift/tests/test_stats.py \
  apps/proxy/live_proxy/tests/zero_orm_allowlist.py apps/proxy/live_proxy/tests/test_zero_orm_scan.py
```

then, in a second call, `git commit -F <message file written with the Write tool>`. The commit gate will derive the same five labels and run them.

---

## Task 5: The boot-check hook arm, and CLAUDE.md

R8 is the argument. This is the task that keeps the guard pointing at its subject.

**Files:**
- Modify: `.claude/hooks/run-affected-tests.sh`, `CLAUDE.md`

- [ ] **Step 1: Confirm the arm currently matches nothing this PR moved**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
sed -n '133,146p' .claude/hooks/run-affected-tests.sh
```

Expected: the `# boot check` banner, the two-line comment naming `apps/channels/models.py:6-7`, and `case "$REL" in` / `apps/proxy/live_proxy/constants.py|apps/proxy/live_proxy/redis_keys.py)`.

- [ ] **Step 2: Apply Appendix F**

```bash
git apply --check --whitespace=error /path/to/appendix-f.diff && git apply /path/to/appendix-f.diff
```

It rewrites the arm to six literal paths (a `case` pattern list continued across lines with a trailing `\`, which bash accepts — verified), rewrites the comment above it, generalises the block's failure message from "apps/channels/models.py imports this module" to "apps/channels/models.py or the catch-up surface imports this module", and makes the two `CLAUDE.md` edits R8 names.

- [ ] **Step 3: Verify the arm matches all six and nothing else**

```bash
bash -c '
for REL in apps/proxy/constants.py apps/proxy/redis_keys.py apps/proxy/config_helper.py \
           apps/proxy/live_proxy/constants.py apps/proxy/live_proxy/redis_keys.py \
           apps/proxy/live_proxy/config_helper.py apps/proxy/relay_views.py apps/channels/models.py; do
case "$REL" in
  apps/proxy/constants.py|apps/proxy/redis_keys.py|apps/proxy/config_helper.py|\
  apps/proxy/live_proxy/constants.py|apps/proxy/live_proxy/redis_keys.py|\
  apps/proxy/live_proxy/config_helper.py)
    echo "MATCH $REL" ;;
  *) echo "no    $REL" ;;
esac
done'
bash -n .claude/hooks/run-affected-tests.sh && echo "hook parses"
```

Expected: `MATCH` on the first six, `no` on `relay_views.py` and `models.py`, and `hook parses`. (`models.py` is deliberately not in this arm — it has its own `makemigrations --check` arm earlier in the script.)

- [ ] **Step 4: Break-check — prove the arm still guards something real**

Add a cycling import to the new leaf and confirm the check it triggers actually fails:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
python3 - <<'PY'
import pathlib
p = pathlib.Path("apps/proxy/constants.py")
t = p.read_text()
p.write_text(t.replace('"""\n\n', '"""\n\nfrom apps.channels.models import Channel  # break-check\n\n', 1))
PY
dx manage.py check 2>&1 | grep -iE "ImportError|circular|cannot import" | head -3
```

Must print:

```
ImportError: cannot import name 'Channel' from partially initialized module 'apps.channels.models' (most likely due to a circular import) (/repo/apps/channels/models.py)
```

Measured. Then revert:

```bash
git -C /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation checkout -- apps/proxy/constants.py
dx manage.py check 2>&1 | grep -E "System check" | head -2
```

Expected: back to `System check identified 1 issue (0 silenced)`. **If the break-check does NOT fail, the relocation left the trap behind and R8's premise is wrong — stop and report.**

- [ ] **Step 5: Do not commit yet.** Task 6 shares this commit.

---

## Task 6: The `models_boot_trap_imports` catalogue note

R10 is the argument.

**Files:**
- Modify: `metrics/curated/catalogue.yml`

- [ ] **Step 1: Confirm the metric now reads zero**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
python3 scripts/metrics/collect_architecture.py \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['models_module_level_live_proxy_imports'], d['reverse_imports_into_proxy'])"
```

Expected: `0 29`. The first moved from 2 (Task 0 Step 3); the second did **not** move, because every re-pointed import still names `apps.proxy`.

- [ ] **Step 2: Apply Appendix G**

```bash
git apply --check --whitespace=error /path/to/appendix-g.diff && git apply /path/to/appendix-g.diff
```

One `note:` gains a sentence. The row keeps `headline: true`, `direction: zero` and `target: null`, and **no `milestones.yml` row is added** (Constraint 7).

- [ ] **Step 3: Validate**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
python3 -m metrics.build --validate-only --curated metrics/curated
scripts/run_metrics_tests.sh all 2>&1 | tail -3
```

Expected: `ok: 46 metrics, 35 milestones, 32 defects`, and the metrics unit tests green. The commit gate runs the first of these for any staged `metrics/` path (`.claude/hooks/pre-commit-tests.sh:185-198`), which is why this PR stages one.

- [ ] **Step 4: Commit Tasks 5 and 6**

Stage `.claude/hooks/run-affected-tests.sh`, `CLAUDE.md` and `metrics/curated/catalogue.yml` in one Bash call, commit with `-F` in the next.

---

## Task 7: Gate 2 — measure, and do not re-baseline

R4 is the argument. This task produces the evidence that the gate is green and the evidence that the floor did not need touching.

**Files:** none modified. **Constraint 6 applies to this whole task.**

- [ ] **Step 1: Confirm the floor is still untouched**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
git diff --stat origin/main -- scripts/coverage_live_path.sh scripts/coverage_live_path.coveragerc \
  scripts/coverage_live_path.floor scripts/coverage_live_path.floor.modules
```

Expected: **empty output**. Anything here is a Constraint 6 violation.

- [ ] **Step 2: The cheap file-set probe**

This is the check that R4 turns on, and it needs no test run at all — `[run] source = apps/proxy` makes coverage walk every file under that tree whether or not anything executed it, so the resolved `files` set is a property of the tree, not of the suite.

```bash
docker exec -e COVERAGE_LIVE_PATH_DATA_DIR=/tmp/cvprobe -w /repo phase2d1 /bin/sh -c '
  rm -rf /tmp/cvprobe && mkdir -p /tmp/cvprobe && printf "pass\n" > /tmp/cvprobe/noop.py &&
  cd /repo &&
  /dispatcharrpy/bin/python -m coverage run --rcfile=scripts/coverage_live_path.coveragerc /tmp/cvprobe/noop.py 2>/dev/null &&
  /dispatcharrpy/bin/python -m coverage combine --rcfile=scripts/coverage_live_path.coveragerc >/dev/null 2>&1 &&
  /dispatcharrpy/bin/python -m coverage json --rcfile=scripts/coverage_live_path.coveragerc -o /tmp/cvprobe/j.json >/dev/null 2>&1 &&
  /dispatcharrpy/bin/python -c "
import json,hashlib
d=json.load(open(\"/tmp/cvprobe/j.json\"))
files=sorted(d[\"files\"].keys())
print(\"digest\", hashlib.sha256(\"\n\".join(files).encode()).hexdigest()[:12], \"files\", len(files), \"statements\", d[\"totals\"][\"num_statements\"])
"'
```

Expected: `digest 8cb5c65dac3e files 38 statements 7983`.

The digest and the file count are the floor's own `modules=`/`module_count=`: **unchanged**, which is R4's claim and A10.4's correction. The statement count moved from the seed's **8202** to **7983** — the 219 statements the relocation removed from the denominator, exactly (246 → 27, Task 2 Step 2). The floor's recorded `statements=8073` is 2026-09-13's figure and was already stale at the seed; it is provenance and is never compared.

**If the digest is not `8cb5c65dac3e`, stop.** There are exactly two causes, and neither has anything to do with statement counts: a **file added** under `apps/proxy/live_proxy/` (or matching one of the rcfile's ten named paths), or one of the **three old paths deleted** rather than left as a shim. The set is a set of paths; a shim that somehow ended up with zero statements would still be in it — `apps/proxy/live_proxy/__init__.py` is zero bytes and is line 6 of the companion list. Do not re-baseline; diff the printed file list against `scripts/coverage_live_path.floor.modules`, which is what the companion is committed for.

- [ ] **Step 3: The full isolated round**

Three containers, one per label, the shape CI's `coverage-label` matrix uses:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
for s in proxy liveproxy channels; do
  DISPATCHARR_TEST_CONTAINER=phase2d1-iso-$s DISPATCHARR_TEST_DB_VOLUME=phase2d1-iso-$s-hookdb \
    CLAUDE_HOOK_REPO_ROOT=/Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation \
    .claude/hooks/start-test-container.sh
done
COVERAGE_ISOLATED_PREFIX=phase2d1-iso COVERAGE_ISOLATED_OUT=/tmp/phase2d1-cov \
  bash scripts/coverage_live_path_isolated.sh --gate
```

**Expected: exit 0**, `this run 7983 statements`, and `this run missing=` a value comfortably under the floor's **1525**. Two rounds on this exact shape drew **1505** ("20 FEWER") and **1509** ("16 FEWER"), both green:

```
coverage_live_path: denominator: floor 8073 statements  this run 7983 statements (informational -- modules=/rcfile= above are the shape checks)
coverage_live_path: floor missing=1525  this run missing=1505  coverage 81.15%
coverage_live_path: 20 FEWER missed than the floor. The floor is not
coverage_live_path: lowered automatically -- run --write-floor in the PR that earned it.
```

**Do not compare that block literally.** `statements` is reproducible; `missing` is bimodal by design — `scripts/coverage_live_path_isolated.sh:9-11`'s own header says the per-container shape buys block-level determinism and **not** total determinism (spread 44). The assertions are the exit status and the `modules=`/`rcfile=` shape checks; the number is informational as long as it is below the floor. **Do not act on that last line.** R4 says why: `--write-floor` writes one local run's figure where the policy is the worst of ≥12 CI rounds, and a drop bought by removing statements from the denominator is not a coverage improvement to ratchet on. 2d-5 is where `missing` moves.

Two things that can go wrong, and what each means.

- **`refusing --gate on an incomplete round`** with `liveproxy=1`: grep the log for `too few distinct speeds`. That is R12's flake (#259) and the round is discarded, not investigated. Re-run. It fired on both attempts at a clean **seed** round while this plan was written, so it is not this PR's.
- **`the module list moved`**: stop. See Step 2.

- [ ] **Step 4: Remove the three extra containers**

```bash
for s in proxy liveproxy channels; do
  docker rm -f phase2d1-iso-$s >/dev/null 2>&1
  docker volume rm phase2d1-iso-$s-hookdb >/dev/null 2>&1
done
```

- [ ] **Step 5: Commit nothing.** This task writes no file. Its output goes in the PR body.

---

## Task 8: Amendment A11, the four in-place spec corrections, and the Done-log row

Four of this plan's rulings refine or contradict the spec, and the spec must never carry both an old sentence and a contradicting new one. Each is edited **in place** and the amendment says so.

**Files:**
- Modify: `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`

- [ ] **Step 1: Apply Appendix H**

```bash
git apply --check --whitespace=error /path/to/appendix-h.diff && git apply /path/to/appendix-h.diff
```

It carries seven things:

1. **Amendment A11**, eight items, inserted immediately before `## Stage 2d — cutover, and its trap`.
2. **A10.4's "2d-1 trips the gate" paragraph, rewritten in place** — R4. The old text ordered a `--shape-only` re-baseline this PR does not ship.
3. **The deletion list's PR 1 entry**, same correction, so the list and the amendment cannot disagree.
4. **A10.14's `apps.timeshift.tests` bullet**, gaining the sentence that makes those two files 2d-1's and the list eleven — R6.
5. **A10.17's `models_boot_trap_imports` bullet**, gaining the sentence that moves the catalogue note here from 2d-6 — R10.
6. **The deletion list's entry 1 milestone clause**, which still asked 2d-1 for "a milestone line" that R10 declines. Without this hunk the spec carries A11.5's ruling and the instruction it overrules, three paragraphs apart.
7. **The deletion list's entry 4 `(g)`**, which still said "thirteen test files … `apps.timeshift.tests` (2)". A11.4 and the edited A10.14 bullet both say eleven across two labels, and 2d-4's planner reads the deletion list.

Plus the **Done-log row** for 2d-1, appended after the A10 row.

- [ ] **Step 2: Verify the spec has no contradictory pair left**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation
SPEC=docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
grep -c "shape-only" "$SPEC"
grep -n "a milestone line for" "$SPEC" || echo "(entry 1's milestone clause: gone)"
grep -n "thirteen test files" "$SPEC"
grep -c "^#### Amendment A11" "$SPEC"
```

Expected, in order: **`9`**, the "gone" line, **two** `thirteen test files` hits, and **`1`**.

**The nine `shape-only` hits**: seven attribute the re-baseline to 2d-4 or describe the floor's own procedure; the other two are the `| Amendment A10 --` **Done-log row**, which says 2d-1 ships one, and A11.2's sentence explaining why that row is left alone. **A Done-log row records what its own PR shipped and is history, not a live instruction** — A10's row accurately records what A10 claimed, the claim is corrected in A10.4's own text and in both deletion-list entries, and rewriting merged rows is not this programme's convention. A tenth hit, or any live instruction assigning a re-baseline to 2d-1, is a **stop**.

**The two surviving `thirteen test files` hits are both correct and both must be there**: A10.14's own heading, which now carries the parenthetical saying eleven across two by the time 2d-4 runs, and 2d-1's Done-log row, which says "A10.14's thirteen test files become eleven". A **third** hit means the deletion-list entry-4 hunk did not apply. Deletion-list entry 1's "a milestone line for" clause must be **absent**; if it is still there, so is a live instruction A11.5 overrules.

- [ ] **Step 3: Commit Task 8**

Docs only. The commit gate routes `docs/` to no backend label, so nothing runs; that is correct.

---

## Task 9: Open the PR

- [ ] **Step 1: Push and open a draft PR**

```bash
git -C /Users/dion/git/Dispatcharr/.worktrees/phase2d-boot-trap-relocation push -u origin migration/phase2d-boot-trap-relocation
gh pr create --repo D10Scot/Dispatcharr --draft \
  --title "relay(phase2): 2d-1 — the boot-trap relocation" \
  --body-file <the file written from the template below>
```

- [ ] **Step 2: Watch the required checks**

`E2E result`, `Lifecycle result`, `Backend result`, `Frontend result`, `agent`, `safe_outputs`. `Backend result` is the one that matters here: it carries both the five-label matrix and `coverage-gate`. The `migration/**` prefix means the full E2E and lifecycle matrices run — expect a long wall time and nothing else.

`Go result` is not a required check and this PR touches no Go; it is A10.1's precondition for **2d-3**, not this PR's business.

- [ ] **Step 3: Mark ready for review once green.**

### PR body template

```markdown
## What

Moves the four names surviving code imports out of `apps/proxy/live_proxy/`:
`RedisKeys` and `ChannelMetadataField` (the known boot trap, `apps/channels/models.py:6-7`)
and — per spec Amendment A10.3, which this spec previously assigned to nobody —
`ChannelState` and `ConfigHelper`, which `apps/proxy/relay_client.py` and the whole
catch-up surface import at module level.

Three new modules: `apps/proxy/redis_keys.py` and `apps/proxy/constants.py` (leaves, no
imports at all) and `apps/proxy/config_helper.py` (imports only `apps.proxy.config`).
`constants.py` is **split**, not moved whole: `EventType`, `StreamType`, `REDIS_TTL_*` and
the TS packet constants stay behind and die with the package at 2d-4, because nothing
outside it imports them.

The three old paths stay as re-export shims. That is what keeps the diff to
**19 import statements in 10 files** out of the 140 in the tree that name these symbols,
and what keeps Gate 2's resolved file set byte-identical — the gate hashes a set of paths,
so a path that still exists cannot leave the set whatever its statement count.

## The trap moved house; it did not go away

Adding `from apps.channels.models import Channel` to the new `apps/proxy/constants.py`
still breaks `manage.py check`:

    ImportError: cannot import name 'Channel' from partially initialized module
    'apps.channels.models' (most likely due to a circular import)

`.claude/hooks/run-affected-tests.sh`'s boot-check `case` arm matched the two old paths
**by literal path** and would have silently stopped running in the PR that moved its
subject — no error, no output. It now takes six: the three new homes and the three shims,
the latter until 2d-4 deletes them. `CLAUDE.md` § Test hooks and § Structural constraints
are corrected in the same commit.

## Gate 2: spec Amendment A10.4 was wrong, and this PR corrects it in place

A10.4 said this PR trips `modules=` on its first push and must ship a `--shape-only`
re-baseline with `missing` unchanged at 1525. It does not, and it does not.

The relocated statements leave the denominator but **no file leaves the set**, because the
old paths remain as shims. The mechanism is the path, not the statement: the gate hashes
`sorted(json["files"].keys())` (`scripts/coverage_live_path.sh:223`) and never reads a
statement count, so a file matching `[report] include` stays in the set even at zero
statements — `apps/proxy/live_proxy/__init__.py` is zero bytes, has zero statements, and is
line 6 of the committed `scripts/coverage_live_path.floor.modules`, with `skip_empty = True`
set all along (it suppresses a file from the **text** table only). Measured at the seed and
on this branch with a no-op `coverage run` under the same rcfile (`source =` triggers coverage's unexecuted-file walk, so the set does not
depend on which tests ran):

| tree | digest | files | statements |
|---|---|---|---|
| seed `16fbb952` | `8cb5c65dac3e` | 38 | 8202 |
| this PR | `8cb5c65dac3e` | 38 | 7983 |

`8cb5c65dac3e`/38 is the floor's own `modules=`/`module_count=`. A full
`scripts/coverage_live_path_isolated.sh --gate` round exits 0 at `missing=1505` against
the floor's 1525 — and a second round, taken independently, at 1509. The total is bimodal
by design (the script's own header says the per-container shape buys block determinism and
not total determinism), so the assertions are exit 0 and the shape fields, never the number.

**No floor edit ships** — not a `--shape-only` re-baseline, not a lowered `missing`. The
20-statement drop is bought by removing statements from the denominator, not by covering
more code, and plain `--write-floor` would write one local run where this floor's policy
is the worst of ≥12 CI rounds. 2d-5 is where that number moves. The `--shape-only`
re-baseline A10.4 ordered is 2d-4's alone.

## Gate 1 moves with `ConfigHelper`, and it narrows by one hop

Nothing in the spec anticipated this. `zero_orm_allowlist.py` needs two edits: the
`Site(config_helper.py, 50)` entry is **deleted** (the read is still there, at
`apps/proxy/config_helper.py:66` — byte-identical code sixteen lines lower, because the
new module's docstring is longer — but scope 1 is the package only, so the ratchet reports
it "listed but gone"), and the `EdgeEntry` becomes
`(apps.proxy.config_helper, ConfigHelper, hits=1)` from
`(apps.proxy.config, TSConfig, hits=5)`.

**The `hits` drop is a real narrowing and is disclosed rather than absorbed.** `scan_edge`
is transitive within the module only, so the five `TSConfig` classmethods it used to clear
are now two hops out and invisible to the static half. The runtime half is unaffected and
still catches the read through `SQL_SIGNATURES`' `proxy_settings_group`. SITES 12 → 11,
EDGES 12 → 12. The entry keeps `pr="2b-1"`: the PR that cleared the read is unchanged, and
`AllowlistShapeTests`' own regex admits no `2d-1` value.

A third file moves with them: `test_zero_orm_scan.py`'s attribution test drove
`ConfigHelper.new_client_behind_seconds()` *because* the query carried a frame inside the
package, which after the move it does not. The replacement driver is `views.py`'s
`_output_profile_for`, whose `OutputProfile.objects.filter` at `views.py:152` is itself one
of the remaining SITES.

## A10.14's thirteen become eleven

All five `live_proxy` imports in `apps/timeshift/tests/{test_views,test_stats}.py` name the
relocated constants and nothing else, so re-pointing them here takes the whole
`apps.timeshift.tests` label — catch-up, the surface 2d KEEPS — off the deleted package.
2d-4's per-file disposition list is now eleven files across two labels.

## What this PR does NOT do

Everything below is stage 2d-4's, named here so none of it is attempted:

- The other eight module-level import sites of A10.3 — `dispatcharr/settings.py:107`'s
  `INSTALLED_APPS` entry (the boot-fatal one), `apps/proxy/relay_views.py:34-41`'s other
  three imports, `dispatcharr/urls.py:9`, `apps/proxy/urls.py:10`, `apps/proxy/tasks.py:6`,
  `apps/proxy/apps.py:9-15`'s `ready()` and its two `getattr` consumers.
- The function-local sites naming other symbols: `apps/proxy/authorize.py:380`
  (`get_stream_object`), `apps/m3u/connection_pool.py:81` and `dispatcharr/consumers.py:120`
  (`transform_url`).
- **#190's five metadata-hash ranges in `apps/channels/models.py`** (`:516-519`, `:696-702`,
  `:717-721`, `:747-750`, `:773-778`). Carried along with the relocated import and
  deliberately untouched, per A10.17. This PR's `models.py` diff is exactly four lines.
- The eleven remaining test files of A10.14, the parity matrix's Python column, the
  `apps.proxy.live_proxy` label in `backend-tests.yml:180` and `test_discovery.py:58`, and
  the Gate 2 `--shape-only` re-baseline.
- The `milestones.yml` row for `models_boot_trap_imports` reaching zero: a milestone row
  carries the merge SHA and a merge commit cannot name itself, so it is a one-line
  follow-up PR after this merges (2c-9 R13; #276's precedent for stage 2b). The catalogue
  **note** is here, because the tile reads zero from this merge.

## The gate, and what it does and does not prove

- `manage.py check` green, and `manage.py showmigrations dispatcharr_channels` green —
  the second because `check` alone does not drive the migration loader, which is the trap's
  actual victim. `DISPATCHARR_ROLE` appears in **no** Python file in the tree, so there is
  one check to run rather than one per role.
- All five routed backend labels green: 105 / 349 / 403 / 441 / 429 (+1 skip). Five, not sixteen,
  is correct: `scripts/ci_backend_test_labels.py` routes all sixteen touched paths to exactly those
  five, nothing here is under `_SHARED_PATH_PREFIXES`, and CI's `plan` job uses the same function.
- `Backend result` green, including `coverage-gate`.
- `makemigrations --check dispatcharr_channels`: no changes. The **whole-project** run is
  dirty at the seed (`core/0028_alter_streamprofile_parameters`), pre-existing, nothing in
  CI runs it, and this PR neither causes nor fixes it.
- `scripts/check_credential_logging.py`: zero findings on every touched `*.py`.
- `python -m metrics.build --validate-only`: green.

**`manage.py check` passing proves this relocation did not break boot and proves nothing
about the eight remaining module-level sites.** The check that would catch those is
deleting the directory, which is 2d-4's; A10.3's enumeration is the substitute, and it is
the reason that enumeration exists.

## Known flake seen while preparing this

`test_a_buffering_threshold_change_does_not_reach_a_running_channel` (#259, "too few
distinct speeds") fired on both attempts at a clean **seed** coverage round and once on a
relocated tree that passed on re-run. It is pre-existing and not this PR's; re-run rather
than lowering the asserted count.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
```

---

## Appendices

Every appendix is a unified diff against the seed `16fbb952942a64115928e8d0ff8dacce3d0eb976`. Each one was generated by `git diff` from a tree built at that commit and each was verified with

```bash
git apply --check --whitespace=error <appendix>.diff
```

against a pristine checkout of the seed, individually, and then all eight were applied in order (A, B, C, D, E, F, G, H) to one tree with no conflict. **Write each to a file and `git apply` it; do not retype a hunk.** The predecessor lesson this follows is the one about an appendix written as prose or as a paragraph replacement going stale and being spliced wrong.

Appendices A–C are Tasks 1 and 2 (the modules and the shims), D is Task 3 (the re-points), E is Task 4 (Gate 1), F is Task 5 (the hook and CLAUDE.md), G is Task 6 (the catalogue), H is Task 8 (the spec).

### Appendix A — the three new modules

```diff
diff --git a/apps/proxy/config_helper.py b/apps/proxy/config_helper.py
new file mode 100644
index 00000000..06694089
--- /dev/null
+++ b/apps/proxy/config_helper.py
@@ -0,0 +1,151 @@
+"""Helper module to access configuration values with proper defaults.
+
+Moved here from ``apps/proxy/live_proxy/config_helper.py`` in Phase 2 stage
+2d-1 (spec Amendment A10.3). Two surfaces stage 2d KEEPS call it --
+catch-up (``apps/timeshift/views.py``, four call sites, imported at module
+level) and the DVR retry window (``apps/channels/tasks.py:1125``) -- so it
+cannot stay in a directory stage 2d-4 deletes.
+
+Unlike ``apps/proxy/redis_keys.py`` and ``apps/proxy/constants.py`` this
+module is NOT a leaf: it imports ``apps.proxy.config``, whose own
+module-level imports are ``time`` and ``django.db.connection`` and nothing
+first-party. That is boot-safe, and it is safe only for that reason --
+``apps/channels/models.py`` does not import this module, so it is not on
+the migration-loader path, but the same "no first-party import" discipline
+applies to anything added here.
+
+``apps/proxy/live_proxy/config_helper.py`` re-exports ``ConfigHelper`` from
+here until stage 2d-4 deletes the package.
+"""
+
+from apps.proxy.config import TSConfig as Config
+
+class ConfigHelper:
+    """
+    Helper class for accessing configuration values with sensible defaults.
+    This simplifies code and ensures consistent defaults across the application.
+    """
+
+    @staticmethod
+    def get(name, default=None):
+        """Get a configuration value with a default fallback"""
+        return getattr(Config, name, default)
+
+    # Commonly used configuration values
+    @staticmethod
+    def connection_timeout():
+        """Get connection timeout in seconds"""
+        return ConfigHelper.get('CONNECTION_TIMEOUT', 10)
+
+    @staticmethod
+    def client_wait_timeout():
+        """Get client wait timeout in seconds"""
+        return ConfigHelper.get('CLIENT_WAIT_TIMEOUT', 30)
+
+    @staticmethod
+    def stream_timeout():
+        """Get stream timeout in seconds"""
+        return ConfigHelper.get('STREAM_TIMEOUT', 60)
+
+    @staticmethod
+    def channel_shutdown_delay():
+        """Get channel shutdown delay in seconds"""
+        return Config.get_channel_shutdown_delay()
+
+    @staticmethod
+    def initial_behind_chunks():
+        """Get number of chunks to start behind"""
+        return ConfigHelper.get('INITIAL_BEHIND_CHUNKS', 4)
+
+    @staticmethod
+    def new_client_behind_seconds():
+        """Get number of seconds behind live to start new clients.
+        0 means start at live (buffer head).
+        Loaded from DB proxy_settings so users can change it at runtime."""
+        from apps.proxy.config import TSConfig
+        settings = TSConfig.get_proxy_settings()
+        return settings.get('new_client_behind_seconds', 5)
+
+    @staticmethod
+    def keepalive_interval():
+        """Get keepalive interval in seconds"""
+        return ConfigHelper.get('KEEPALIVE_INTERVAL', 0.5)
+
+    @staticmethod
+    def cleanup_check_interval():
+        """Get cleanup check interval in seconds"""
+        return ConfigHelper.get('CLEANUP_CHECK_INTERVAL', 3)
+
+    @staticmethod
+    def redis_chunk_ttl():
+        """Get Redis chunk TTL in seconds"""
+        return Config.get_redis_chunk_ttl()
+
+    @staticmethod
+    def chunk_size():
+        """Get chunk size in bytes"""
+        return ConfigHelper.get('CHUNK_SIZE', 8192)
+
+    @staticmethod
+    def max_retries():
+        """Get maximum retry attempts"""
+        return ConfigHelper.get('MAX_RETRIES', 3)
+
+    @staticmethod
+    def retry_window_seconds():
+        """Reset the retry counter after this many seconds without a failure."""
+        return ConfigHelper.get('RETRY_WINDOW_SECONDS', 1800)
+
+    @staticmethod
+    def stable_connection_threshold():
+        """Seconds of stable playback before switch rotation state resets."""
+        return ConfigHelper.get('STABLE_CONNECTION_THRESHOLD', 30)
+
+    @staticmethod
+    def max_stream_switches():
+        """Get maximum number of stream switch attempts"""
+        return ConfigHelper.get('MAX_STREAM_SWITCHES', 10)
+
+    @staticmethod
+    def retry_wait_interval():
+        """Get wait interval between connection retries in seconds"""
+        return ConfigHelper.get('RETRY_WAIT_INTERVAL', 0.5)  # Default to 0.5 second
+
+    @staticmethod
+    def url_switch_timeout():
+        """Get URL switch timeout in seconds (max time allowed for a stream switch operation)"""
+        return ConfigHelper.get('URL_SWITCH_TIMEOUT', 20)  # Default to 20 seconds
+
+    @staticmethod
+    def failover_grace_period():
+        """Get extra time (in seconds) to allow for stream switching before disconnecting clients"""
+        return ConfigHelper.get('FAILOVER_GRACE_PERIOD', 20)  # Default to 20 seconds
+
+    @staticmethod
+    def buffering_timeout():
+        """Get buffering timeout in seconds"""
+        return Config.get_buffering_timeout()
+
+    @staticmethod
+    def buffering_speed():
+        """Get buffering speed threshold"""
+        return Config.get_buffering_speed()
+
+    @staticmethod
+    def channel_init_grace_period():
+        """Max seconds to wait for initial buffer fill during channel startup."""
+        return Config.get_channel_init_grace_period()
+
+    @staticmethod
+    def channel_client_wait_period():
+        """Seconds to keep a ready channel alive waiting for the first client to connect."""
+        return Config.get_channel_client_wait_period()
+
+    @staticmethod
+    def chunk_timeout():
+        """
+        Get chunk timeout in seconds (used for both socket and HTTP read timeouts).
+        This controls how long we wait for each chunk before timing out.
+        Set this higher (e.g., 30s) for slow providers that may have intermittent delays.
+        """
+        return ConfigHelper.get('CHUNK_TIMEOUT', 5)  # Default 5 seconds
diff --git a/apps/proxy/constants.py b/apps/proxy/constants.py
new file mode 100644
index 00000000..3cdb99dc
--- /dev/null
+++ b/apps/proxy/constants.py
@@ -0,0 +1,113 @@
+"""Channel state and metadata-field names shared by Django and the relay.
+
+Moved here from ``apps/proxy/live_proxy/constants.py`` in Phase 2 stage 2d-1
+(spec Amendment A10.3). ``apps/channels/models.py`` imports
+``ChannelMetadataField`` at module level, and the catch-up surface --
+``apps/timeshift/views.py`` and ``apps/timeshift/stats.py``, which stage 2d
+KEEPS -- imports both names; neither may be left pointing at a directory
+stage 2d-4 deletes.
+
+THIS MODULE MUST STAY A LEAF -- no imports, at all, for the reason
+``apps/proxy/redis_keys.py``'s docstring gives.
+
+Only the two names surviving code needs are here. ``EventType``,
+``StreamType``, ``REDIS_TTL_*``, ``REDIS_KEY_PREFIX`` and the TS packet
+constants stay in ``apps/proxy/live_proxy/constants.py``: nothing outside
+that package imports them, and 2d-4 deletes them with it.
+"""
+
+# Channel states
+class ChannelState:
+    INITIALIZING = "initializing"
+    CONNECTING = "connecting"
+    WAITING_FOR_CLIENTS = "waiting_for_clients"
+    ACTIVE = "active"
+    ERROR = "error"
+    STOPPING = "stopping"
+    STOPPED = "stopped"
+    BUFFERING = "buffering"
+
+    # States before a channel is fully active. Used by the stream manager
+    # finally block to decide whether a failed stream can write ERROR.
+    PRE_ACTIVE = frozenset([INITIALIZING, CONNECTING, BUFFERING, WAITING_FOR_CLIENTS])
+
+
+# Channel metadata field names stored in Redis
+class ChannelMetadataField:
+    # Basic fields
+    URL = "url"
+    USER_AGENT = "user_agent"
+    STATE = "state"
+    OWNER = "owner"
+    STREAM_ID = "stream_id"
+    CHANNEL_NAME = "channel_name"
+    STREAM_NAME = "stream_name"
+    CHANNEL_ID = "channel_id"
+    CHANNEL_UUID = "channel_uuid"
+    LOGO_ID = "logo_id"
+
+    # Profile fields
+    STREAM_PROFILE = "stream_profile"
+    M3U_PROFILE = "m3u_profile"
+    M3U_PROFILE_NAME = "m3u_profile_name"
+    # The locked ffmpeg StreamProfile, JSON-encoded {"id", "command", "args"},
+    # written from the next-source answer so input/manager.py's force-ffmpeg
+    # path (HLS/RTSP/UDP upstreams) needs no StreamProfile query in the relay
+    # process. Phase 2 PR 2b-1.
+    FFMPEG_STREAM_PROFILE = "ffmpeg_stream_profile"
+
+    # Status and error fields
+    ERROR_MESSAGE = "error_message"
+    ERROR_TIME = "error_time"
+    STATE_CHANGED_AT = "state_changed_at"
+    INIT_TIME = "init_time"
+    CONNECTION_READY_TIME = "connection_ready_time"
+
+    # Buffer and data tracking
+    BUFFER_CHUNKS = "buffer_chunks"
+    TOTAL_BYTES = "total_bytes"
+
+    # Stream switching
+    STREAM_SWITCH_TIME = "stream_switch_time"
+    STREAM_SWITCH_REASON = "stream_switch_reason"
+
+    # FFmpeg performance metrics
+    FFMPEG_SPEED = "ffmpeg_speed"
+    FFMPEG_FPS = "ffmpeg_fps"
+    ACTUAL_FPS = "actual_fps"
+    FFMPEG_OUTPUT_BITRATE = "ffmpeg_output_bitrate"
+    FFMPEG_BITRATE = "ffmpeg_bitrate"
+    FFMPEG_STATS_UPDATED = "ffmpeg_stats_updated"
+
+    # Video stream info
+    VIDEO_CODEC = "video_codec"
+    RESOLUTION = "resolution"
+    WIDTH = "width"
+    HEIGHT = "height"
+    SOURCE_FPS = "source_fps"
+    PIXEL_FORMAT = "pixel_format"
+    VIDEO_BITRATE = "video_bitrate"
+    SOURCE_BITRATE = "source_bitrate"
+
+    # Audio stream info
+    AUDIO_CODEC = "audio_codec"
+    SAMPLE_RATE = "sample_rate"
+    AUDIO_CHANNELS = "audio_channels"
+    AUDIO_BITRATE = "audio_bitrate"
+
+    # Stream format info
+    STREAM_TYPE = "stream_type"
+    # Stream info timestamp
+    STREAM_INFO_UPDATED = "stream_info_updated"
+
+    # Client metadata fields
+    CONNECTED_AT = "connected_at"
+    LAST_ACTIVE = "last_active"
+    OUTPUT_FORMAT = "output_format"
+    BYTES_SENT = "bytes_sent"
+    AVG_RATE_KBPS = "avg_rate_KBps"
+    CURRENT_RATE_KBPS = "current_rate_KBps"
+    IP_ADDRESS = "ip_address"
+    WORKER_ID = "worker_id"
+    CHUNKS_SENT = "chunks_sent"
+    STATS_UPDATED_AT = "stats_updated_at"
diff --git a/apps/proxy/redis_keys.py b/apps/proxy/redis_keys.py
new file mode 100644
index 00000000..bcd3de82
--- /dev/null
+++ b/apps/proxy/redis_keys.py
@@ -0,0 +1,172 @@
+"""Redis key patterns for the live relay's channel state.
+
+Moved here from ``apps/proxy/live_proxy/redis_keys.py`` in Phase 2 stage
+2d-1 (spec Amendment A10.3), because ``apps/channels/models.py`` imports
+``RedisKeys`` at module level and must not point at a directory stage 2d-4
+deletes.
+
+THIS MODULE MUST STAY A LEAF -- no imports, at all. It is loaded by every
+migration and every management command through that models.py import, so a
+cycle added here is not a failing test, it is a container that does not
+start. ``.claude/hooks/run-affected-tests.sh``'s boot-check ``case`` arm
+names this file for exactly that reason.
+
+``apps/proxy/live_proxy/redis_keys.py`` re-exports ``RedisKeys`` from here
+until stage 2d-4 deletes the package.
+"""
+
+class RedisKeys:
+    @staticmethod
+    def channel_metadata(channel_id):
+        """Key for channel metadata hash"""
+        return f"live:channel:{channel_id}:metadata"
+
+    @staticmethod
+    def buffer_index(channel_id):
+        """Key for tracking input buffer index"""
+        return f"live:channel:{channel_id}:input:buffer:index"
+
+    @staticmethod
+    def buffer_chunk(channel_id, chunk_index):
+        """Key for specific input buffer chunk"""
+        return f"live:channel:{channel_id}:input:buffer:chunk:{chunk_index}"
+
+    @staticmethod
+    def buffer_chunk_prefix(channel_id):
+        """Prefix for input buffer chunks"""
+        return f"live:channel:{channel_id}:input:buffer:chunk:"
+
+    @staticmethod
+    def channel_stopping(channel_id):
+        """Key indicating channel is stopping"""
+        return f"live:channel:{channel_id}:stopping"
+
+    @staticmethod
+    def client_stop(channel_id, client_id):
+        """Key requesting client stop"""
+        return f"live:channel:{channel_id}:client:{client_id}:stop"
+
+    @staticmethod
+    def events_channel(channel_id):
+        """PubSub channel for events"""
+        return f"live:events:{channel_id}"
+
+    @staticmethod
+    def switch_request(channel_id):
+        """Key for stream switch request"""
+        return f"live:channel:{channel_id}:switch_request"
+
+    @staticmethod
+    def channel_owner(channel_id):
+        """Key for storing channel owner worker ID"""
+        return f"live:channel:{channel_id}:owner"
+
+    @staticmethod
+    def clients(channel_id):
+        """Key for set of client IDs"""
+        return f"live:channel:{channel_id}:clients"
+
+    @staticmethod
+    def last_client_disconnect(channel_id):
+        """Key for last client disconnect timestamp"""
+        return f"live:channel:{channel_id}:last_client_disconnect_time"
+
+    @staticmethod
+    def connection_attempt(channel_id):
+        """Key for connection attempt timestamp"""
+        return f"live:channel:{channel_id}:connection_attempt_time"
+
+    @staticmethod
+    def last_data(channel_id):
+        """Key for last data timestamp"""
+        return f"live:channel:{channel_id}:last_data"
+
+    @staticmethod
+    def switch_status(channel_id):
+        """Key for stream switch status"""
+        return f"live:channel:{channel_id}:switch_status"
+
+    @staticmethod
+    def worker_heartbeat(worker_id):
+        """Key for worker heartbeat"""
+        return f"live:worker:{worker_id}:heartbeat"
+
+    @staticmethod
+    def chunk_timestamps(channel_id):
+        """Sorted set mapping chunk receive-timestamps (score) to chunk indices (member).
+        Used for time-based client positioning."""
+        return f"live:channel:{channel_id}:input:buffer:chunk_timestamps"
+
+    @staticmethod
+    def transcode_active(channel_id):
+        """Key indicating active transcode process"""
+        return f"live:channel:{channel_id}:transcode_active"
+
+    @staticmethod
+    def client_metadata(channel_id, client_id):
+        """Key for client metadata hash"""
+        return f"live:channel:{channel_id}:clients:{client_id}"
+
+    # Output format buffer keys - parameterized by format name (e.g. 'fmp4').
+    # Adding a new output format only requires a new manager; the key structure
+    # is shared so no new key methods are needed.
+    @staticmethod
+    def output_buffer_index(channel_id, fmt):
+        return f"live:channel:{channel_id}:output:{fmt}:buffer:index"
+
+    @staticmethod
+    def output_buffer_chunk(channel_id, fmt, chunk_index):
+        return f"live:channel:{channel_id}:output:{fmt}:buffer:chunk:{chunk_index}"
+
+    @staticmethod
+    def output_buffer_chunk_prefix(channel_id, fmt):
+        return f"live:channel:{channel_id}:output:{fmt}:buffer:chunk:"
+
+    @staticmethod
+    def output_init(channel_id, fmt):
+        """Binary init segment for formats that require one (e.g. fMP4 ftyp+moov)."""
+        return f"live:channel:{channel_id}:output:{fmt}:init"
+
+    @staticmethod
+    def output_state(channel_id, fmt):
+        """Remux/transcode manager state for this output format."""
+        return f"live:channel:{channel_id}:output:{fmt}:state"
+
+    @staticmethod
+    def output_owner(channel_id, fmt):
+        """Worker ID owning the output format manager."""
+        return f"live:channel:{channel_id}:output:{fmt}:owner"
+
+    @staticmethod
+    def output_chunk_timestamps(channel_id, fmt):
+        """Sorted set mapping fragment receive-timestamps to fragment indices."""
+        return f"live:channel:{channel_id}:output:{fmt}:buffer:chunk_timestamps"
+
+    @staticmethod
+    def channel_source_cache(channel_id):
+        """Resolved failover candidates, cached at channel start.
+
+        Read by two callers, neither of which reserves anything or moves
+        the provider slot: views.py's stream_ts, trying the next candidate
+        when a Redirect profile's primary URL fails validation at tune
+        time (unconditionally, not just on an outage); and
+        input/manager.py's _try_next_stream degraded fallback, only when
+        the control plane is unreachable at failover time (Phase 1 PR 6).
+        Both treat the list as stale and unenforced.
+        """
+        return f"live:channel:{channel_id}:source_cache"
+
+    # Written only by apps/channels/models.py — Channel.get_stream(),
+    # release_stream(), update_stream_profile() — and reached only through
+    # apps/proxy/next_source.py since Phase 1 PR 6. They were hand-rolled
+    # f-strings on both sides of the boundary, which is what made them
+    # split-brain; naming them here is what makes a second writer visible.
+    @staticmethod
+    def channel_stream(channel_pk):
+        """Stream id currently assigned to this channel (numeric channel pk)."""
+        return f"channel_stream:{channel_pk}"
+
+    @staticmethod
+    def stream_profile(stream_id):
+        """M3U account profile id serving this stream."""
+        return f"stream_profile:{stream_id}"
```

### Appendix B — `apps/proxy/live_proxy/constants.py`, split

```diff
diff --git a/apps/proxy/live_proxy/constants.py b/apps/proxy/live_proxy/constants.py
index ffc439bb..2f1e01ea 100644
--- a/apps/proxy/live_proxy/constants.py
+++ b/apps/proxy/live_proxy/constants.py
@@ -9,20 +9,12 @@ REDIS_TTL_DEFAULT = 3600  # 1 hour
 REDIS_TTL_SHORT = 60      # 1 minute
 REDIS_TTL_MEDIUM = 300    # 5 minutes
 
-# Channel states
-class ChannelState:
-    INITIALIZING = "initializing"
-    CONNECTING = "connecting"
-    WAITING_FOR_CLIENTS = "waiting_for_clients"
-    ACTIVE = "active"
-    ERROR = "error"
-    STOPPING = "stopping"
-    STOPPED = "stopped"
-    BUFFERING = "buffering"
-
-    # States before a channel is fully active. Used by the stream manager
-    # finally block to decide whether a failed stream can write ERROR.
-    PRE_ACTIVE = frozenset([INITIALIZING, CONNECTING, BUFFERING, WAITING_FOR_CLIENTS])
+# ChannelState and ChannelMetadataField moved to apps/proxy/constants.py in
+# Phase 2 stage 2d-1 and are re-exported here so every importer inside this
+# package -- and the five test files outside it that name this path -- keeps
+# working until stage 2d-4 deletes the package. Nothing new should import
+# them from here.
+from apps.proxy.constants import ChannelMetadataField, ChannelState  # noqa: F401
 
 # Event types
 class EventType:
@@ -44,86 +36,6 @@ class StreamType:
     TS = "ts"
     UNKNOWN = "unknown"
 
-# Channel metadata field names stored in Redis
-class ChannelMetadataField:
-    # Basic fields
-    URL = "url"
-    USER_AGENT = "user_agent"
-    STATE = "state"
-    OWNER = "owner"
-    STREAM_ID = "stream_id"
-    CHANNEL_NAME = "channel_name"
-    STREAM_NAME = "stream_name"
-    CHANNEL_ID = "channel_id"
-    CHANNEL_UUID = "channel_uuid"
-    LOGO_ID = "logo_id"
-
-    # Profile fields
-    STREAM_PROFILE = "stream_profile"
-    M3U_PROFILE = "m3u_profile"
-    M3U_PROFILE_NAME = "m3u_profile_name"
-    # The locked ffmpeg StreamProfile, JSON-encoded {"id", "command", "args"},
-    # written from the next-source answer so input/manager.py's force-ffmpeg
-    # path (HLS/RTSP/UDP upstreams) needs no StreamProfile query in the relay
-    # process. Phase 2 PR 2b-1.
-    FFMPEG_STREAM_PROFILE = "ffmpeg_stream_profile"
-
-    # Status and error fields
-    ERROR_MESSAGE = "error_message"
-    ERROR_TIME = "error_time"
-    STATE_CHANGED_AT = "state_changed_at"
-    INIT_TIME = "init_time"
-    CONNECTION_READY_TIME = "connection_ready_time"
-
-    # Buffer and data tracking
-    BUFFER_CHUNKS = "buffer_chunks"
-    TOTAL_BYTES = "total_bytes"
-
-    # Stream switching
-    STREAM_SWITCH_TIME = "stream_switch_time"
-    STREAM_SWITCH_REASON = "stream_switch_reason"
-
-    # FFmpeg performance metrics
-    FFMPEG_SPEED = "ffmpeg_speed"
-    FFMPEG_FPS = "ffmpeg_fps"
-    ACTUAL_FPS = "actual_fps"
-    FFMPEG_OUTPUT_BITRATE = "ffmpeg_output_bitrate"
-    FFMPEG_BITRATE = "ffmpeg_bitrate"
-    FFMPEG_STATS_UPDATED = "ffmpeg_stats_updated"
-
-    # Video stream info
-    VIDEO_CODEC = "video_codec"
-    RESOLUTION = "resolution"
-    WIDTH = "width"
-    HEIGHT = "height"
-    SOURCE_FPS = "source_fps"
-    PIXEL_FORMAT = "pixel_format"
-    VIDEO_BITRATE = "video_bitrate"
-    SOURCE_BITRATE = "source_bitrate"
-
-    # Audio stream info
-    AUDIO_CODEC = "audio_codec"
-    SAMPLE_RATE = "sample_rate"
-    AUDIO_CHANNELS = "audio_channels"
-    AUDIO_BITRATE = "audio_bitrate"
-
-    # Stream format info
-    STREAM_TYPE = "stream_type"
-    # Stream info timestamp
-    STREAM_INFO_UPDATED = "stream_info_updated"
-
-    # Client metadata fields
-    CONNECTED_AT = "connected_at"
-    LAST_ACTIVE = "last_active"
-    OUTPUT_FORMAT = "output_format"
-    BYTES_SENT = "bytes_sent"
-    AVG_RATE_KBPS = "avg_rate_KBps"
-    CURRENT_RATE_KBPS = "current_rate_KBps"
-    IP_ADDRESS = "ip_address"
-    WORKER_ID = "worker_id"
-    CHUNKS_SENT = "chunks_sent"
-    STATS_UPDATED_AT = "stats_updated_at"
-
 # TS packet constants
 TS_PACKET_SIZE = 188
 TS_SYNC_BYTE = 0x47
```

### Appendix C — the two whole-file shims

```diff
diff --git a/apps/proxy/live_proxy/config_helper.py b/apps/proxy/live_proxy/config_helper.py
index c3af3966..2cee4d62 100644
--- a/apps/proxy/live_proxy/config_helper.py
+++ b/apps/proxy/live_proxy/config_helper.py
@@ -1,135 +1,8 @@
-"""
-Helper module to access configuration values with proper defaults.
-"""
-
-from apps.proxy.config import TSConfig as Config
-
-class ConfigHelper:
-    """
-    Helper class for accessing configuration values with sensible defaults.
-    This simplifies code and ensures consistent defaults across the application.
-    """
-
-    @staticmethod
-    def get(name, default=None):
-        """Get a configuration value with a default fallback"""
-        return getattr(Config, name, default)
-
-    # Commonly used configuration values
-    @staticmethod
-    def connection_timeout():
-        """Get connection timeout in seconds"""
-        return ConfigHelper.get('CONNECTION_TIMEOUT', 10)
-
-    @staticmethod
-    def client_wait_timeout():
-        """Get client wait timeout in seconds"""
-        return ConfigHelper.get('CLIENT_WAIT_TIMEOUT', 30)
-
-    @staticmethod
-    def stream_timeout():
-        """Get stream timeout in seconds"""
-        return ConfigHelper.get('STREAM_TIMEOUT', 60)
-
-    @staticmethod
-    def channel_shutdown_delay():
-        """Get channel shutdown delay in seconds"""
-        return Config.get_channel_shutdown_delay()
-
-    @staticmethod
-    def initial_behind_chunks():
-        """Get number of chunks to start behind"""
-        return ConfigHelper.get('INITIAL_BEHIND_CHUNKS', 4)
-
-    @staticmethod
-    def new_client_behind_seconds():
-        """Get number of seconds behind live to start new clients.
-        0 means start at live (buffer head).
-        Loaded from DB proxy_settings so users can change it at runtime."""
-        from apps.proxy.config import TSConfig
-        settings = TSConfig.get_proxy_settings()
-        return settings.get('new_client_behind_seconds', 5)
-
-    @staticmethod
-    def keepalive_interval():
-        """Get keepalive interval in seconds"""
-        return ConfigHelper.get('KEEPALIVE_INTERVAL', 0.5)
-
-    @staticmethod
-    def cleanup_check_interval():
-        """Get cleanup check interval in seconds"""
-        return ConfigHelper.get('CLEANUP_CHECK_INTERVAL', 3)
+"""Moved to ``apps/proxy/config_helper.py`` in Phase 2 stage 2d-1.
 
-    @staticmethod
-    def redis_chunk_ttl():
-        """Get Redis chunk TTL in seconds"""
-        return Config.get_redis_chunk_ttl()
-
-    @staticmethod
-    def chunk_size():
-        """Get chunk size in bytes"""
-        return ConfigHelper.get('CHUNK_SIZE', 8192)
-
-    @staticmethod
-    def max_retries():
-        """Get maximum retry attempts"""
-        return ConfigHelper.get('MAX_RETRIES', 3)
-
-    @staticmethod
-    def retry_window_seconds():
-        """Reset the retry counter after this many seconds without a failure."""
-        return ConfigHelper.get('RETRY_WINDOW_SECONDS', 1800)
-
-    @staticmethod
-    def stable_connection_threshold():
-        """Seconds of stable playback before switch rotation state resets."""
-        return ConfigHelper.get('STABLE_CONNECTION_THRESHOLD', 30)
-
-    @staticmethod
-    def max_stream_switches():
-        """Get maximum number of stream switch attempts"""
-        return ConfigHelper.get('MAX_STREAM_SWITCHES', 10)
-
-    @staticmethod
-    def retry_wait_interval():
-        """Get wait interval between connection retries in seconds"""
-        return ConfigHelper.get('RETRY_WAIT_INTERVAL', 0.5)  # Default to 0.5 second
-
-    @staticmethod
-    def url_switch_timeout():
-        """Get URL switch timeout in seconds (max time allowed for a stream switch operation)"""
-        return ConfigHelper.get('URL_SWITCH_TIMEOUT', 20)  # Default to 20 seconds
-
-    @staticmethod
-    def failover_grace_period():
-        """Get extra time (in seconds) to allow for stream switching before disconnecting clients"""
-        return ConfigHelper.get('FAILOVER_GRACE_PERIOD', 20)  # Default to 20 seconds
-
-    @staticmethod
-    def buffering_timeout():
-        """Get buffering timeout in seconds"""
-        return Config.get_buffering_timeout()
-
-    @staticmethod
-    def buffering_speed():
-        """Get buffering speed threshold"""
-        return Config.get_buffering_speed()
-
-    @staticmethod
-    def channel_init_grace_period():
-        """Max seconds to wait for initial buffer fill during channel startup."""
-        return Config.get_channel_init_grace_period()
-
-    @staticmethod
-    def channel_client_wait_period():
-        """Seconds to keep a ready channel alive waiting for the first client to connect."""
-        return Config.get_channel_client_wait_period()
+Re-exported from here so every importer inside this package -- and
+``apps/proxy/tests/test_boundary_error_arms.py`` outside it -- keeps working
+until stage 2d-4 deletes the package. Nothing new should import this path.
+"""
 
-    @staticmethod
-    def chunk_timeout():
-        """
-        Get chunk timeout in seconds (used for both socket and HTTP read timeouts).
-        This controls how long we wait for each chunk before timing out.
-        Set this higher (e.g., 30s) for slow providers that may have intermittent delays.
-        """
-        return ConfigHelper.get('CHUNK_TIMEOUT', 5)  # Default 5 seconds
+from apps.proxy.config_helper import ConfigHelper  # noqa: F401
diff --git a/apps/proxy/live_proxy/redis_keys.py b/apps/proxy/live_proxy/redis_keys.py
index 46f87fdf..c1d732af 100644
--- a/apps/proxy/live_proxy/redis_keys.py
+++ b/apps/proxy/live_proxy/redis_keys.py
@@ -1,161 +1,8 @@
-"""
-Defines Redis key patterns used throughout the TS proxy service.
-Centralizing these key patterns makes it easier to maintain and change them if needed.
-"""
-
-class RedisKeys:
-    @staticmethod
-    def channel_metadata(channel_id):
-        """Key for channel metadata hash"""
-        return f"live:channel:{channel_id}:metadata"
-
-    @staticmethod
-    def buffer_index(channel_id):
-        """Key for tracking input buffer index"""
-        return f"live:channel:{channel_id}:input:buffer:index"
-
-    @staticmethod
-    def buffer_chunk(channel_id, chunk_index):
-        """Key for specific input buffer chunk"""
-        return f"live:channel:{channel_id}:input:buffer:chunk:{chunk_index}"
-
-    @staticmethod
-    def buffer_chunk_prefix(channel_id):
-        """Prefix for input buffer chunks"""
-        return f"live:channel:{channel_id}:input:buffer:chunk:"
-
-    @staticmethod
-    def channel_stopping(channel_id):
-        """Key indicating channel is stopping"""
-        return f"live:channel:{channel_id}:stopping"
-
-    @staticmethod
-    def client_stop(channel_id, client_id):
-        """Key requesting client stop"""
-        return f"live:channel:{channel_id}:client:{client_id}:stop"
-
-    @staticmethod
-    def events_channel(channel_id):
-        """PubSub channel for events"""
-        return f"live:events:{channel_id}"
-
-    @staticmethod
-    def switch_request(channel_id):
-        """Key for stream switch request"""
-        return f"live:channel:{channel_id}:switch_request"
-
-    @staticmethod
-    def channel_owner(channel_id):
-        """Key for storing channel owner worker ID"""
-        return f"live:channel:{channel_id}:owner"
-
-    @staticmethod
-    def clients(channel_id):
-        """Key for set of client IDs"""
-        return f"live:channel:{channel_id}:clients"
-
-    @staticmethod
-    def last_client_disconnect(channel_id):
-        """Key for last client disconnect timestamp"""
-        return f"live:channel:{channel_id}:last_client_disconnect_time"
-
-    @staticmethod
-    def connection_attempt(channel_id):
-        """Key for connection attempt timestamp"""
-        return f"live:channel:{channel_id}:connection_attempt_time"
-
-    @staticmethod
-    def last_data(channel_id):
-        """Key for last data timestamp"""
-        return f"live:channel:{channel_id}:last_data"
-
-    @staticmethod
-    def switch_status(channel_id):
-        """Key for stream switch status"""
-        return f"live:channel:{channel_id}:switch_status"
+"""Moved to ``apps/proxy/redis_keys.py`` in Phase 2 stage 2d-1.
 
-    @staticmethod
-    def worker_heartbeat(worker_id):
-        """Key for worker heartbeat"""
-        return f"live:worker:{worker_id}:heartbeat"
-
-    @staticmethod
-    def chunk_timestamps(channel_id):
-        """Sorted set mapping chunk receive-timestamps (score) to chunk indices (member).
-        Used for time-based client positioning."""
-        return f"live:channel:{channel_id}:input:buffer:chunk_timestamps"
-
-    @staticmethod
-    def transcode_active(channel_id):
-        """Key indicating active transcode process"""
-        return f"live:channel:{channel_id}:transcode_active"
-
-    @staticmethod
-    def client_metadata(channel_id, client_id):
-        """Key for client metadata hash"""
-        return f"live:channel:{channel_id}:clients:{client_id}"
-
-    # Output format buffer keys - parameterized by format name (e.g. 'fmp4').
-    # Adding a new output format only requires a new manager; the key structure
-    # is shared so no new key methods are needed.
-    @staticmethod
-    def output_buffer_index(channel_id, fmt):
-        return f"live:channel:{channel_id}:output:{fmt}:buffer:index"
-
-    @staticmethod
-    def output_buffer_chunk(channel_id, fmt, chunk_index):
-        return f"live:channel:{channel_id}:output:{fmt}:buffer:chunk:{chunk_index}"
-
-    @staticmethod
-    def output_buffer_chunk_prefix(channel_id, fmt):
-        return f"live:channel:{channel_id}:output:{fmt}:buffer:chunk:"
-
-    @staticmethod
-    def output_init(channel_id, fmt):
-        """Binary init segment for formats that require one (e.g. fMP4 ftyp+moov)."""
-        return f"live:channel:{channel_id}:output:{fmt}:init"
-
-    @staticmethod
-    def output_state(channel_id, fmt):
-        """Remux/transcode manager state for this output format."""
-        return f"live:channel:{channel_id}:output:{fmt}:state"
-
-    @staticmethod
-    def output_owner(channel_id, fmt):
-        """Worker ID owning the output format manager."""
-        return f"live:channel:{channel_id}:output:{fmt}:owner"
-
-    @staticmethod
-    def output_chunk_timestamps(channel_id, fmt):
-        """Sorted set mapping fragment receive-timestamps to fragment indices."""
-        return f"live:channel:{channel_id}:output:{fmt}:buffer:chunk_timestamps"
-
-    @staticmethod
-    def channel_source_cache(channel_id):
-        """Resolved failover candidates, cached at channel start.
-
-        Read by two callers, neither of which reserves anything or moves
-        the provider slot: views.py's stream_ts, trying the next candidate
-        when a Redirect profile's primary URL fails validation at tune
-        time (unconditionally, not just on an outage); and
-        input/manager.py's _try_next_stream degraded fallback, only when
-        the control plane is unreachable at failover time (Phase 1 PR 6).
-        Both treat the list as stale and unenforced.
-        """
-        return f"live:channel:{channel_id}:source_cache"
-
-    # Written only by apps/channels/models.py — Channel.get_stream(),
-    # release_stream(), update_stream_profile() — and reached only through
-    # apps/proxy/next_source.py since Phase 1 PR 6. They were hand-rolled
-    # f-strings on both sides of the boundary, which is what made them
-    # split-brain; naming them here is what makes a second writer visible.
-    @staticmethod
-    def channel_stream(channel_pk):
-        """Stream id currently assigned to this channel (numeric channel pk)."""
-        return f"channel_stream:{channel_pk}"
-
-    @staticmethod
-    def stream_profile(stream_id):
-        """M3U account profile id serving this stream."""
-        return f"stream_profile:{stream_id}"
+Re-exported from here so every importer inside this package -- and the six
+test files outside it that name this path -- keeps working until stage 2d-4
+deletes the package. Nothing new should import this path.
+"""
 
+from apps.proxy.redis_keys import RedisKeys  # noqa: F401
```

### Appendix D — the nineteen re-points

```diff
diff --git a/apps/channels/models.py b/apps/channels/models.py
index 0bcb2fd3..28b61969 100644
--- a/apps/channels/models.py
+++ b/apps/channels/models.py
@@ -3,8 +3,8 @@ from django.core.exceptions import ValidationError
 from django.conf import settings
 from core.models import StreamProfile, CoreSettings
 from core.utils import RedisClient, custom_properties_as_dict
-from apps.proxy.live_proxy.redis_keys import RedisKeys
-from apps.proxy.live_proxy.constants import ChannelMetadataField
+from apps.proxy.redis_keys import RedisKeys
+from apps.proxy.constants import ChannelMetadataField
 import logging
 import uuid
 from django.utils import timezone
diff --git a/apps/channels/tasks.py b/apps/channels/tasks.py
index e4021b10..edff0e8c 100755
--- a/apps/channels/tasks.py
+++ b/apps/channels/tasks.py
@@ -1122,7 +1122,7 @@ def _dvr_ffmpeg_retry_window_seconds():
     """Max continuous outage duration before giving up on FFmpeg restarts.
     """
     try:
-        from apps.proxy.live_proxy.config_helper import ConfigHelper
+        from apps.proxy.config_helper import ConfigHelper
         return ConfigHelper.stream_timeout() + ConfigHelper.failover_grace_period()
     except Exception:
         return 80.0
@@ -2442,7 +2442,7 @@ def run_recording(recording_id, channel_id, start_time_str, end_time_str):
         # Try to get stream stats from the relay's status payload
         try:
             from apps.proxy import relay_client
-            from apps.proxy.live_proxy.constants import ChannelMetadataField
+            from apps.proxy.constants import ChannelMetadataField
 
             # Phase 1 PR 7: this runs in the dvr Celery worker, which has
             # no business reading the channel's metadata hash directly.
diff --git a/apps/proxy/next_source.py b/apps/proxy/next_source.py
index 0cf12f12..95286ed1 100644
--- a/apps/proxy/next_source.py
+++ b/apps/proxy/next_source.py
@@ -345,7 +345,7 @@ def get_stream_info_for_switch(channel_id: str, target_stream_id: Optional[int]
     channel = None
     try:
         from core.utils import RedisClient
-        from apps.proxy.live_proxy.redis_keys import RedisKeys
+        from apps.proxy.redis_keys import RedisKeys
 
         channel = get_object_or_404(Channel, uuid=channel_id)
         redis_client = RedisClient.get_client()
@@ -471,7 +471,7 @@ def get_alternate_streams(channel_id: str, current_stream_id: Optional[int] = No
     """
     try:
         from core.utils import RedisClient
-        from apps.proxy.live_proxy.redis_keys import RedisKeys
+        from apps.proxy.redis_keys import RedisKeys
 
         # Get channel object
         channel = get_stream_object(channel_id)
@@ -1112,7 +1112,7 @@ def release_source(identifier, *, stream_id=None, m3u_profile_id=None, channel_p
 
     from core.utils import RedisClient
     from apps.m3u.connection_pool import release_profile_slot
-    from apps.proxy.live_proxy.redis_keys import RedisKeys
+    from apps.proxy.redis_keys import RedisKeys
 
     redis_client = RedisClient.get_client()
     if not redis_client:
diff --git a/apps/proxy/relay_client.py b/apps/proxy/relay_client.py
index 44b5805c..175b5dc1 100644
--- a/apps/proxy/relay_client.py
+++ b/apps/proxy/relay_client.py
@@ -58,7 +58,7 @@ from apps.proxy.internal_auth import (
     internal_principal_token,
 )
 from apps.proxy.internal_base_url import resolve_base_url
-from apps.proxy.live_proxy.constants import ChannelState
+from apps.proxy.constants import ChannelState
 
 logger = logging.getLogger(__name__)
 
diff --git a/apps/proxy/relay_views.py b/apps/proxy/relay_views.py
index 3badb437..1632f698 100644
--- a/apps/proxy/relay_views.py
+++ b/apps/proxy/relay_views.py
@@ -35,8 +35,8 @@ from apps.proxy.live_proxy.channel_status import (
     ChannelStatus,
     build_live_channel_stats_data,
 )
-from apps.proxy.live_proxy.constants import ChannelMetadataField
-from apps.proxy.live_proxy.redis_keys import RedisKeys
+from apps.proxy.constants import ChannelMetadataField
+from apps.proxy.redis_keys import RedisKeys
 from apps.proxy.live_proxy.server import ProxyServer
 from apps.proxy.live_proxy.services.channel_service import ChannelService
 from apps.proxy.permissions import IsInternalRelay
diff --git a/apps/timeshift/stats.py b/apps/timeshift/stats.py
index ebc54249..caa74009 100644
--- a/apps/timeshift/stats.py
+++ b/apps/timeshift/stats.py
@@ -10,7 +10,7 @@ from datetime import timezone as dt_timezone
 
 from apps.channels.models import Channel
 from apps.m3u.models import M3UAccountProfile
-from apps.proxy.live_proxy.constants import ChannelMetadataField
+from apps.proxy.constants import ChannelMetadataField
 from apps.timeshift.redis_keys import TimeshiftRedisKeys, parse_stats_channel_id
 from apps.timeshift.helpers import parse_catchup_timestamp
 from core.utils import RedisClient
diff --git a/apps/timeshift/tests/test_stats.py b/apps/timeshift/tests/test_stats.py
index db2b30b6..663ea7a5 100644
--- a/apps/timeshift/tests/test_stats.py
+++ b/apps/timeshift/tests/test_stats.py
@@ -9,7 +9,7 @@ from django.test import TestCase
 from rest_framework.test import APIRequestFactory, force_authenticate
 
 from apps.accounts.models import User
-from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
+from apps.proxy.constants import ChannelMetadataField, ChannelState
 from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, parse_stats_channel_id
 from apps.timeshift import stats_views
 from apps.timeshift.helpers import get_programme_info
diff --git a/apps/timeshift/tests/test_views.py b/apps/timeshift/tests/test_views.py
index e641a0b1..21fa3489 100644
--- a/apps/timeshift/tests/test_views.py
+++ b/apps/timeshift/tests/test_views.py
@@ -3232,7 +3232,7 @@ class TimeshiftStatsClientTests(TestCase):
         self.user = MagicMock(id=5, username="viewer")
 
     def test_register_stats_preserves_connected_at_on_reregister(self):
-        from apps.proxy.live_proxy.constants import ChannelMetadataField
+        from apps.proxy.constants import ChannelMetadataField
         from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys
 
         client_key = RedisKeys.client_metadata(self.stats_channel_id, self.client_id)
@@ -3475,7 +3475,7 @@ class TimeshiftStatsClientTests(TestCase):
         self.assertNotEqual(self.redis.hget(client_key, "position_anchor_at"), "1000.0")
 
     def test_register_stats_seeds_stream_stats_from_memory(self):
-        from apps.proxy.live_proxy.constants import ChannelMetadataField
+        from apps.proxy.constants import ChannelMetadataField
         from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys
 
         metadata_key = RedisKeys.channel_metadata(self.stats_channel_id)
@@ -3505,7 +3505,7 @@ class TimeshiftStatsClientTests(TestCase):
         self.assertEqual(self.redis.hget(metadata_key, ChannelMetadataField.STREAM_ID), "42")
 
     def test_register_stats_skips_stream_stats_when_stream_unchanged(self):
-        from apps.proxy.live_proxy.constants import ChannelMetadataField
+        from apps.proxy.constants import ChannelMetadataField
         from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys
 
         metadata_key = RedisKeys.channel_metadata(self.stats_channel_id)
@@ -3532,7 +3532,7 @@ class TimeshiftStatsClientTests(TestCase):
         self.assertEqual(self.redis.hget(metadata_key, ChannelMetadataField.RESOLUTION), "1280x720")
 
     def test_register_stats_updates_stream_stats_on_failover_stream_change(self):
-        from apps.proxy.live_proxy.constants import ChannelMetadataField
+        from apps.proxy.constants import ChannelMetadataField
         from apps.timeshift.redis_keys import TimeshiftRedisKeys as RedisKeys, TimeshiftRedisKeys
 
         metadata_key = RedisKeys.channel_metadata(self.stats_channel_id)
diff --git a/apps/timeshift/views.py b/apps/timeshift/views.py
index 9b2f3040..7562e95c 100644
--- a/apps/timeshift/views.py
+++ b/apps/timeshift/views.py
@@ -37,8 +37,8 @@ from apps.m3u.connection_pool import (
 )
 from apps.m3u.models import M3UAccount, M3UAccountProfile
 from apps.m3u.tasks import get_transformed_credentials
-from apps.proxy.live_proxy.config_helper import ConfigHelper
-from apps.proxy.live_proxy.constants import ChannelMetadataField, ChannelState
+from apps.proxy.config_helper import ConfigHelper
+from apps.proxy.constants import ChannelMetadataField, ChannelState
 from apps.timeshift.redis_keys import (
     TimeshiftRedisKeys,
     mint_session_id,
diff --git a/core/utils.py b/core/utils.py
index ce5c74c9..00c928d1 100644
--- a/core/utils.py
+++ b/core/utils.py
@@ -756,7 +756,7 @@ def dispatch_event_system(event_type, channel_id=None, channel_name=None, **deta
         from apps.channels.models import Channel, Stream
         from core.models import StreamProfile
         from core.utils import RedisClient
-        from apps.proxy.live_proxy.redis_keys import RedisKeys
+        from apps.proxy.redis_keys import RedisKeys
 
         payload = dict(details)
 
```

### Appendix E — Gate 1: the allowlist and the attribution test

```diff
diff --git a/apps/proxy/live_proxy/tests/test_zero_orm_scan.py b/apps/proxy/live_proxy/tests/test_zero_orm_scan.py
index 59a4d3ad..074d70f6 100644
--- a/apps/proxy/live_proxy/tests/test_zero_orm_scan.py
+++ b/apps/proxy/live_proxy/tests/test_zero_orm_scan.py
@@ -194,37 +194,31 @@ class QueryCaptureTests(TransactionTestCase):
 
     def test_a_query_with_a_relay_frame_is_attributed_to_the_relay(self):
         """The discriminating half. Without it, the test above passes
-        with an attributor that returns [] for everything."""
-        from apps.proxy.live_proxy.config_helper import ConfigHelper
+        with an attributor that returns [] for everything.
+
+        The driver was ConfigHelper.new_client_behind_seconds() until
+        Phase 2 stage 2d-1 moved ConfigHelper to
+        apps/proxy/config_helper.py: the read still fires, but no frame
+        in its stack is under apps/proxy/live_proxy/ any more, so it
+        stopped being an example of what this test is about. views.py's
+        _output_profile_for is the replacement -- a module-level
+        function in the package, reached with a stub decision and no
+        Redis, whose OutputProfile.objects.filter at views.py:152 is
+        itself one of zero_orm_allowlist.py's SITES.
+        """
+        from types import SimpleNamespace
+
+        from apps.proxy.live_proxy.views import _output_profile_for
         from .harness.queries import capture_queries, relay_queries
 
-        # Two caches sit in front of the query this test wants to see fire,
-        # and both must be cold or the ORM read never happens at all --
-        # Global Constraint 1 applied to a fixture, not just a header.
-        #
-        # 1. CoreSettings.get_proxy_settings() is itself backed by a
-        #    Django-cache (Redis) group ("proxy_settings"), so a warm Redis
-        #    entry answers without ever reaching Postgres.
-        # 2. TSConfig.get_proxy_settings() (config_helper.py:50 calls it)
-        #    additionally keeps a 10-second process-local copy. Clearing it
-        #    via BaseConfig.clear_proxy_settings_cache() -- what
-        #    CoreSettings.invalidate_group_cache() itself calls -- is the
-        #    documented #232 trap: `cls._proxy_settings_cache = ...` inside
-        #    the classmethod means the first fetch made *through TSConfig*
-        #    creates a TSConfig-owned attribute that shadows BaseConfig's,
-        #    and clearing BaseConfig's copy leaves that shadow warm. Clear
-        #    TSConfig's own directly.
-        from core.models import CoreSettings, PROXY_SETTINGS_KEY
-        from apps.proxy.config import TSConfig
-        CoreSettings.invalidate_group_cache(PROXY_SETTINGS_KEY)
-        TSConfig.clear_proxy_settings_cache()
+        decision = SimpleNamespace(trusted=True, output_profile_id=1)
 
         with capture_queries() as captured:
-            ConfigHelper.new_client_behind_seconds()
+            _output_profile_for(decision, None, None)
 
         self.assertTrue(
             relay_queries(captured),
-            "a query issued from apps/proxy/live_proxy/config_helper.py "
+            "a query issued from apps/proxy/live_proxy/views.py "
             "was not attributed to the relay",
         )
 
diff --git a/apps/proxy/live_proxy/tests/zero_orm_allowlist.py b/apps/proxy/live_proxy/tests/zero_orm_allowlist.py
index cde6c037..0910fbff 100644
--- a/apps/proxy/live_proxy/tests/zero_orm_allowlist.py
+++ b/apps/proxy/live_proxy/tests/zero_orm_allowlist.py
@@ -108,26 +108,6 @@ SITES = (
         ),
         closed_by="As :74 -- absence is the contract. Row 18.",
     ),
-    Site(
-        path="apps/proxy/live_proxy/config_helper.py",
-        lineno=50,
-        pr="2b-1",
-        reason=(
-            "TSConfig.get_proxy_settings() -> CoreSettings.get_proxy_settings "
-            "(core/models.py) through apps/proxy/config.py's 10-second "
-            "process-local cache. Issue #253 item 3: 2b-1 put proxy_settings "
-            "on next-source's response and deliberately did not wire "
-            "StreamManager to prefer it, so the read is still live at the end "
-            "of 2b. Same precedent as 2b-1's own 'nothing in the Python relay "
-            "consumes this yet, deliberately'."
-        ),
-        closed_by=(
-            "proxy_settings on next-source's response (2b-1). The Go relay "
-            "takes channel-start values from the tune answer and never reads "
-            "CoreSettings, which also collapses #232's 10-second staleness "
-            "window to zero for every value that matters at channel start."
-        ),
-    ),
     Site(
         path="apps/proxy/live_proxy/views.py",
         lineno=132,
@@ -435,19 +415,38 @@ EDGES = (
             "per importer, and TSConfig is imported into five relay files."
         ),
         closed_by=(
-            "proxy_settings on next-source's response (2b-1), same as "
-            "config_helper.py:50's SITE entry above. The Go relay takes "
-            "channel-start values from the tune answer and never reads "
-            "CoreSettings."
+            "proxy_settings on next-source's response (2b-1). That read had its "
+            "own SITE entry here until stage 2d-1 moved ConfigHelper to "
+            "apps/proxy/config_helper.py:66 and out of scope 1, which "
+            "deleted the entry; the runtime half still covers the read. "
+            "The Go relay takes channel-start values from the tune answer "
+            "and never reads CoreSettings."
         ),
     ),
     EdgeEntry(
         importer="apps/proxy/live_proxy/config_helper.py",
-        module="apps.proxy.config",
-        name="TSConfig",
-        hits=5,
+        module="apps.proxy.config_helper",
+        name="ConfigHelper",
+        hits=1,
         pr="2b-1",
-        reason="As the client_manager.py entry above -- same symbol, same 5-hit subtree, a second importer.",
+        reason=(
+            "Was (apps.proxy.config, TSConfig, 5 hits) until stage 2d-1 moved "
+            "ConfigHelper to apps/proxy/config_helper.py and left this file a "
+            "re-export shim. The SAME read is still reached -- "
+            "apps/proxy/config_helper.py:66's TSConfig.get_proxy_settings(), "
+            "which was apps/proxy/live_proxy/config_helper.py:50's SITE entry "
+            "before the move (the code is byte-identical; the read sits sixteen "
+            "lines lower because the new module's docstring is longer) -- but "
+            "scan_edge() is transitive WITHIN THE MODULE "
+            "ONLY (Ruling R4), so it now sees one hit where it saw TSConfig's "
+            "five same-module classmethods. That is a real one-hop narrowing of "
+            "the static half, disclosed rather than absorbed: the five classmethods "
+            "are now two hops out and invisible to it. The runtime half is "
+            "unaffected and still catches the read -- SQL_SIGNATURES' "
+            "proxy_settings_group matches it on every drive. `pr` stays 2b-1: the "
+            "PR that CLEARED this read is unchanged, only the path it travels is, "
+            "and AllowlistShapeTests' own regex admits no 2d value."
+        ),
         closed_by="As the client_manager.py entry above.",
     ),
     EdgeEntry(
@@ -626,17 +625,19 @@ SQL_SIGNATURES = (
         # should not have).
         params_fragment="'proxy_settings'",
         table_model="core.CoreSettings",
-        # NOT marked exercised: config_helper.py:50's TSConfig.get_proxy_
+        # NOT marked exercised: apps/proxy/config_helper.py:66's TSConfig.get_proxy_
         # settings sits behind a 10-second process-local cache whose
         # warm/cold state depends on what ran earlier in the same test
         # process -- this programme has already measured flapping regions
         # from exactly this kind of state and Task 4 Step 3 says mark
         # exercised_by only where a drive makes the read deterministic.
         # Present so a cache-cold run does not fail with "no allowlisted
-        # signature" for an already-allowlisted SITE (config_helper.py:50).
+        # signature" for a read that left scope 1 at stage 2d-1
+        # (apps/proxy/config_helper.py:66) and is now covered by the
+        # runtime half alone.
         exercised_by="",
         reason=(
-            "config_helper.py:50's TSConfig.get_proxy_settings() reads "
+            "apps/proxy/config_helper.py:66's TSConfig.get_proxy_settings() reads "
             "this group through a 10-second process-local cache; whether "
             "it fires on a given run depends on cache state this guard "
             "does not control, so it is recorded but not required. "
@@ -662,14 +663,14 @@ INLINE_AUTHORIZE_SIGNATURES = (
         # Q5 (review round): SQL_SIGNATURES' proxy_settings_group is not
         # eligible on this list -- the untrusted drive also tunes (it
         # runs channel.get_stream_profile() etc. exactly as a trusted
-        # tune does), so config_helper.py:50's TSConfig.get_proxy_
+        # tune does), so apps/proxy/config_helper.py:66's TSConfig.get_proxy_
         # settings() could equally fire here on a cache-cold run. Not
         # marked exercised for the same reason as the SQL_SIGNATURES
         # entry: whether it fires depends on cache state this guard does
         # not control.
         exercised_by="",
         reason=(
-            "As SQL_SIGNATURES' proxy_settings_group: config_helper.py:50's "
+            "As SQL_SIGNATURES' proxy_settings_group: apps/proxy/config_helper.py:66's "
             "TSConfig.get_proxy_settings() reads this group through a "
             "10-second process-local cache, reachable from the untrusted "
             "tune's own channel-setup path exactly as from a trusted one."
```

### Appendix F — the boot-check hook arm and CLAUDE.md

```diff
diff --git a/.claude/hooks/run-affected-tests.sh b/.claude/hooks/run-affected-tests.sh
index 5eab5f99..01772aaf 100755
--- a/.claude/hooks/run-affected-tests.sh
+++ b/.claude/hooks/run-affected-tests.sh
@@ -131,14 +131,26 @@ if [[ "$REL" == */models.py || "$REL" == models.py ]]; then
 fi
 
 # -------------------------------------------------------------- boot check ---
-# apps/channels/models.py:6-7 imports these two leaf modules at module level, so
-# one added import here stops Django booting for every migration and command.
+# apps/channels/models.py:6-7 imports apps/proxy/redis_keys.py and
+# apps/proxy/constants.py at module level, so one added import in either stops
+# Django booting for every migration and command. Phase 2 stage 2d-1 moved those
+# two names out of apps/proxy/live_proxy/ (spec Amendment A10.3) along with
+# ConfigHelper, which the catch-up surface imports at module level -- the trap
+# moved house, it did not go away, and this arm moved with it.
+#
+# The three apps/proxy/live_proxy/ paths stay until stage 2d-4 deletes the
+# package: they are re-export shims every relay module still imports, and
+# apps/proxy/apps.py's ready() reaches them in every process that is not
+# manage.py. THIS ARM MATCHES BY LITERAL PATH -- a file renamed out of it stops
+# being checked with no error and no output, which is how it would be lost.
 case "$REL" in
-  apps/proxy/live_proxy/constants.py|apps/proxy/live_proxy/redis_keys.py)
+  apps/proxy/constants.py|apps/proxy/redis_keys.py|apps/proxy/config_helper.py|\
+  apps/proxy/live_proxy/constants.py|apps/proxy/live_proxy/redis_keys.py|\
+  apps/proxy/live_proxy/config_helper.py)
     if container_ok; then
       OUT="$(dexec manage.py check)"; [ $? -eq 0 ] ||
         block "django check failed after editing ${REL}" \
-              "$(printf '%s' "$OUT" | grep -E 'Error|error:' | head -12)"$'\n\n'"apps/channels/models.py imports this module at module level; a cycle here breaks every management command."
+              "$(printf '%s' "$OUT" | grep -E 'Error|error:' | head -12)"$'\n\n'"apps/channels/models.py or the catch-up surface imports this module at module level; a cycle here breaks every management command."
     elif [ -z "$_container_mismatched" ]; then
       note "Did NOT run 'manage.py check' after editing ${REL} — container '${CONTAINER}' is not running."
     fi
diff --git a/CLAUDE.md b/CLAUDE.md
index 38fe622f..7eb158c4 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -53,10 +53,10 @@ scripts/check_go_stdlib_only.sh relay           # the module must stay stdlib-on
 
 ## Test hooks (this fork only)
 
-`.claude/settings.json` registers `PostToolUse` on `Write|Edit`, each check scoped to the edited file. Blocking: `*tests/test_*.py` (whole package), `frontend/**/*.test.jsx` (vitest), `*/models.py` (`makemigrations --check`), `live_proxy/{constants,redis_keys}.py` (`manage.py check`), `.github/workflows/*.yml` + `action.yml` + `dependabot.yml` (zizmor), `e2e/**/*.ts` + `e2e-upstream/**/*.ts` (`tsc --noEmit` for that package — blocking, unlike eslint: both packages typecheck clean, so it's a ratchet, and the only automated check those trees have; a full Playwright run is far too slow for a hook), any `*.py` (`scripts/check_credential_logging.py`), `metrics/**` + `scripts/metrics/**` (`scripts/run_metrics_tests.sh`, plain unittest, no container, plus `python -m metrics.build --validate-only`), `dashboard/*.{js,html}` (vitest with `frontend/vitest.dashboard.config.js`). Advisory: eslint on `frontend/**/*.jsx` (so pre-existing errors don't punish touching legacy code).
+`.claude/settings.json` registers `PostToolUse` on `Write|Edit`, each check scoped to the edited file. Blocking: `*tests/test_*.py` (whole package), `frontend/**/*.test.jsx` (vitest), `*/models.py` (`makemigrations --check`), `apps/proxy/{constants,redis_keys,config_helper}.py` and their three `live_proxy/` re-export shims (`manage.py check`), `.github/workflows/*.yml` + `action.yml` + `dependabot.yml` (zizmor), `e2e/**/*.ts` + `e2e-upstream/**/*.ts` (`tsc --noEmit` for that package — blocking, unlike eslint: both packages typecheck clean, so it's a ratchet, and the only automated check those trees have; a full Playwright run is far too slow for a hook), any `*.py` (`scripts/check_credential_logging.py`), `metrics/**` + `scripts/metrics/**` (`scripts/run_metrics_tests.sh`, plain unittest, no container, plus `python -m metrics.build --validate-only`), `dashboard/*.{js,html}` (vitest with `frontend/vitest.dashboard.config.js`). Advisory: eslint on `frontend/**/*.jsx` (so pre-existing errors don't punish touching legacy code).
 
 - The migration check resolves the app label via `apps.get_app_configs()`, never the directory name: `apps.channels` has label `dispatcharr_channels`, and the guess `channels` hits the *Django Channels library*, which reports "no changes" and exits 0 — guessing fails silently.
-- The boot check exists because `apps/channels/models.py:6–7` imports two `live_proxy` leaf modules at module level; a cycle there breaks `manage.py check` for every command.
+- The boot check exists because `apps/channels/models.py:6–7` imports two leaf modules at module level; a cycle there breaks `manage.py check` for every command. Phase 2 stage 2d-1 moved those two out of `live_proxy/` into `apps/proxy/redis_keys.py` and `apps/proxy/constants.py` — **the arm moved with them, and the three old paths stay in it until 2d-4 deletes the package**, because they are still re-export shims every relay module imports. The arm matches **by literal path**: a file renamed out of it stops being checked with no error and no output, which is exactly how this guard would be lost in the PR that moves its subject.
 - zizmor blocks on **every** finding in the edited file, legacy included. Workflows are at **zero findings** — a ratchet; keep it there. Same zizmor version pinned in `.github/workflows/actions-lint.yml`; the hook warns on version drift — bump both together. **Deliberately no `.github/zizmor.yml`** (defaults already enforce hash-pinning, `persist-credentials`, least-privilege permissions); suppress a considered exception with a trailing `# zizmor: ignore[audit-name]`. Online audits are **on** (`impostor-commit` catches SHAs from the wrong repo — invisible offline); token from `$GH_TOKEN` / `$GITHUB_TOKEN` / `gh auth token`, degrades loudly to offline without one. Opt out with `ZIZMOR_HOOK_OFFLINE=1` — **not** zizmor's own `ZIZMOR_OFFLINE`, a `true`/`false` flag that `=1` breaks.
 - Go gets its own `PostToolUse` hook, `.claude/hooks/run-go-checks.sh`, on any `*.go` file: `go build ./...`, `go vet ./...` and `golangci-lint run` over the whole module plus `go test -race` for the edited file's package, all blocking, with zero lint findings as a ratchet in zizmor's idiom (the pinned version is checked against `go-tests.yml`'s, and a mismatch warns). `-race` is not optional and has no per-package exemption: this phase moves the relay off gevent's single OS thread, so a data race becomes possible for the first time. The commit gate runs `go build`, `go vet` and `go test -race ./...` over the whole module for any staged `*.go`. **Both anchor on the edited or staged file's own path, following #258's rule, and both then walk up for a `go.mod` rather than calling `hook_repo_root`** — that helper returns the *repo* root, and `go build ./...` needs the *module* root, which is `relay/` and is defined by where `go.mod` sits, not `.git`. They do borrow `hook_canon_path`, so a symlinked spelling of the same tree compares equal. **The `PostToolUse` hook does NOT honour `CLAUDE_HOOK_REPO_ROOT`**, unlike `hook_repo_root()` itself — a review found that pinning the go.mod walk to the *repo* root breaks it silently: the repo root carries no `go.mod` (`relay/` does), so the walk climbs to `/`, the module root comes back empty, and the script exits 0 with no output at all on a real compile error. The commit gate's Go section still respects the variable, harmlessly: it reaches `pre-commit-tests.sh`'s own `$REPO_ROOT` (already correctly resolved via `hook_repo_root`, which the variable is meant to pin) and only then walks up *per staged path* for `go.mod`, so pinning the repo root there doesn't touch the module-root computation the way it did in the `PostToolUse` hook. `hook_container_mismatch` is deliberately unused: the Go checks run on the host with no container, so it has nothing to judge. Note that `relay/` paths map to **no** backend test label (`scripts/ci_backend_test_labels.py` returns `[]` for them), so for a Go-only commit the Go section of the gate is the only thing that runs.
 - The Go hook and `go-tests.yml` also run `scripts/check_go_credential_logging.sh` (`relay/internal/credlint`, a `go/types`-aware checker built with `go run` from stdlib only): every error-typed argument to a formatting or logging call in `relay/` — `fmt.Errorf` and its `Sprint`/`Fprint`/`Print` family, package `log`'s `Print`/`Fatal`/`Panic` family, `log/slog`'s level functions and `*Logger` methods, and `slog.Any` — must pass through `redact.Error`, or the call must carry `// credential-logging: ok - <reason>` on a line it spans or the line above; a bare marker with no reason clears nothing. Zero findings is a ratchet, run from the module root so the hook and CI cannot disagree. `relay/internal/credlint/check.go`'s header states the rule's three known gaps: a composite literal storing an error in a field (`control.Unavailable{Err: err}`) is not a call and is not seen — the leak surfaces one hop later at the type's `Error()` method, which is where 2c-4 found and fixed one; `errors.Join` and a hand-formatted `%v` of an error field are invisible unless they go through a listed sink; and an error stringified by hand (`err.Error()` passed as a string) is invisible by the same string-blindness the Python check shares. `go-tests.yml`'s `build` job runs inside this repository's own base image (`ghcr.io/<owner>/<repo>:base`, the same one `backend-tests.yml` uses), not a bare runner, so parity-matrix row 4's real-ffmpeg pin (`relay/channel/source_transcode_real_test.go`) runs against the production ffmpeg (8.1.2, `docker/DispatcharrBase`) rather than a distro package — ffmpeg 6.1.1 (ubuntu-latest's own apt) omits `frame=` from stream-copy progress lines, so the verbatim-ported `IsProgressLine` gate never passes and the pin fails rather than skips when `CI` is set (CI fix round, 2026-09-14; spec Amendment A4).
@@ -101,7 +101,7 @@ VOD is deliberately different: no ring buffer (`iter_content(8192)` passthrough)
 ## Structural constraints on refactoring
 
 - **The apps are a mesh, not a stack**: 367 cross-app imports over 50 edges, four cycles centred on `channels`. Extracting the relay pulls in `channels` → `m3u`/`epg` → back. There is no clean seam.
-- `apps/channels/models.py:6–7` imports `RedisKeys` and `ChannelMetadataField` from `apps.proxy.live_proxy` at **module level** — loaded by every migration and management command. It survives only because those are leaf modules: **one import added to `live_proxy/constants.py` and Django stops booting.** Hence 602 function-local imports. Phase 1 PR 7 audited whether either could go and the answer is no. `RedisKeys` could only go by relocating PR 6's two four-line key helpers to a Django-owned module: PR 6 moved `channel_stream:*` and `stream_profile:*` into that class, and this module is their owner and only writer, reaching them through it at twenty-six sites — so the import is now the legitimate accessor for keys this module owns, not an incidental leak. Doing that relocation would not remove the trap anyway, because `ChannelMetadataField` stays: `Channel.release_stream()` writes to the relay's metadata hash on every successful release, plus two fallback-path reads (`release_stream()`'s recovery branch and `_release_stale_stream_assignment()`) — the relay-key access PR 7 left in the control plane (see § Known defects, and issue #190). PR 7 did drop the third name, `ChannelState`, with the reuse check that used it. Two module-level imports remain, and the trap with them.
+- `apps/channels/models.py:6–7` imports `RedisKeys` and `ChannelMetadataField` at **module level** — loaded by every migration and management command. Since Phase 2 stage 2d-1 they come from `apps/proxy/redis_keys.py` and `apps/proxy/constants.py`, Django-owned leaf modules, and no longer from `apps.proxy.live_proxy`; `ChannelState` and `ConfigHelper` moved out with them (`apps/proxy/constants.py`, `apps/proxy/config_helper.py`) because `apps/proxy/relay_client.py` and the whole catch-up surface import those at module level too and stage 2d-4 deletes the package. **The relocation moved the trap's address, not the trap.** It survives only because those are leaf modules: **one import added to `apps/proxy/constants.py` and Django stops booting** — measured on the 2d-1 branch as `ImportError: cannot import name 'Channel' from partially initialized module 'apps.channels.models'`. Hence 602 function-local imports. The three old paths stay as re-export shims until 2d-4, so every module inside the package and the seven test files outside it that name one of them keep working unedited. `RedisKeys` is the legitimate accessor for keys this module owns rather than an incidental leak: PR 6 moved `channel_stream:*` and `stream_profile:*` into that class, and this module is their owner and only writer, reaching them through it at twenty-six sites. `ChannelMetadataField` is here for #190's reason: `Channel.release_stream()` writes to the relay's metadata hash on every successful release, plus two fallback-path reads (`release_stream()`'s recovery branch and `_release_stale_stream_assignment()`) — the relay-key access PR 7 left in the control plane (see § Known defects, and issue #190), which 2d-1 carried along unchanged and 2d-4 deletes. `metrics/curated/`'s `models_boot_trap_imports` reads **0** from 2d-1, and it counts this one file: eight other module-level `live_proxy` import sites are live until 2d-4 (spec Amendment A10.3), so the zero is not “the trap is gone”.
 - Good news: non-test `apps/proxy/` contains **zero ORM writes as of Phase 1 PR 6** — the `stream.save()` in `services/channel_service.py` and all thirteen `log_system_event()` calls (`server.py` ×2, `input/manager.py` ×7, `output/ts/generator.py` ×2, `output/fmp4/generator.py` ×1, `vod_proxy/multi_worker_connection_manager.py` ×1) now post to `POST /api/relay/events`, and Django performs the write in `core/relay_events.py`. The obstacle is **29 reverse-import sites** (`scripts/metrics/collect_architecture.py`'s `reverse_imports_into_proxy`, which counts non-test import statements outside `apps/proxy/` that import from it — Phase 1 raised the number on purpose, by giving the control plane one `relay_client` to import instead of a Redis key to read) and reads of 14 model classes, not transactional coupling.
 - Complexity is concentrated: 111 functions hold 43% of function lines — `fetch_schedules_direct()` (1,323 lines), `run_recording()` (1,139, 47 `try` blocks), `sync_auto_channels()` (1,010).
 
```

### Appendix G — the catalogue note

```diff
diff --git a/metrics/curated/catalogue.yml b/metrics/curated/catalogue.yml
index db4e7df9..e70d363f 100644
--- a/metrics/curated/catalogue.yml
+++ b/metrics/curated/catalogue.yml
@@ -35,7 +35,7 @@
 - {id: import_cycles, family: architecture, path: /import_cycles, label: Import cycles, unit: count, direction: down, target: 0, group: extraction, headline: true, since: 2026-08-19,
    note: "Strongly connected components of size > 1 in the cross-app import graph."}
 - {id: models_boot_trap_imports, family: architecture, path: /models_module_level_live_proxy_imports, label: models.py boot-trap imports, unit: count, direction: zero, target: null, group: extraction, headline: true, since: 2026-08-19,
-   note: "Module-level imports of apps.proxy.live_proxy in apps/channels/models.py; one more import there stops Django booting."}
+   note: "Module-level imports of apps.proxy.live_proxy in apps/channels/models.py; one more import there stops Django booting. It counts that ONE file: it reaches zero at Phase 2 stage 2d-1, which relocated both imports to apps/proxy/redis_keys.py and apps/proxy/constants.py, while eight other module-level import sites into the package stay live until 2d-4 deletes it (spec Amendment A10.3) -- a zero here is not 'the boot trap is gone'."}
 - {id: proxy_orm_writes, family: architecture, path: /proxy_orm_writes, label: apps/proxy ORM writes, unit: count, direction: down, target: 0, group: extraction, headline: true, since: 2026-08-19,
    note: "ORM write calls in non-test apps/proxy code. Exactly one at baseline."}
 - {id: cross_app_edges, family: architecture, path: /cross_app_import_edges, label: Cross-app import edges, unit: count, direction: down, target: null, group: extraction, headline: false, since: 2026-08-19, note: "Distinct (from_app, to_app) pairs."}
```

### Appendix H — Amendment A11, four in-place corrections, and the Done-log row

```diff
diff --git a/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md b/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
index 08c861ef..c2c0238a 100644
--- a/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
+++ b/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
@@ -2996,18 +2996,33 @@ census that makes the survivor gate real cannot be taken until after the delete.
 `internal_base_url.py`, `next_source.py`, `permissions.py`, `relay_client.py`, `relay_serializers.py`,
 `relay_views.py` — the Phase 1 boundary, i.e. the control plane the Go relay calls.
 
-**2d-1 trips the gate.** `constants.py` and `redis_keys.py` are lines 11 and 25 of that list, and
-`scripts/coverage_live_path.coveragerc:23-34`'s `[report] include` is `apps/proxy/live_proxy/*` plus
-ten **named** files — so a relocated `RedisKeys`/`ChannelMetadataField` lands outside the denominator
-wherever it goes, the resolved `files` set changes, and `modules=8cb5c65dac3e`
-(`scripts/coverage_live_path.floor:319`) stops matching. That check is an **equality**, not a
-ratchet, so it fails green-to-red on the first push regardless of how coverage moves. The floor's own
-procedure already has the right answer for this shape: `scripts/coverage_live_path.floor:244-258`
-distinguishes a `missing` move (which needs the ≥12-round CI census) from a shape-only re-baseline
-(module list or rcfile changed deliberately, `missing` unchanged), and prescribes **one** clean run
-plus `--write-floor --shape-only` for the latter. **Ruling: 2d-1 ships a `--shape-only`
-re-baseline, `missing` unchanged at 1525, and says so in one line.** No census. Nothing about #312
-changes this: #312 is a claim about the *spread* of a number this move does not claim.
+**2d-1 does NOT trip the gate, and this paragraph's first draft said it did** — corrected in place
+by Amendment A11.2, which carries the measurement. The half that is right: the relocated names land
+outside the denominator wherever they go, because `scripts/coverage_live_path.coveragerc:23-34`'s
+`[report] include` is `apps/proxy/live_proxy/*` plus ten **named** files and
+`apps/proxy/redis_keys.py` matches neither. The half that is wrong: that the resolved `files` set
+therefore changes. 2d-1 leaves the OLD PATHS in place as re-export shims, and the resolved set is a set
+of **paths**: `scripts/coverage_live_path.sh:223` hashes `sorted(json["files"].keys())` with no reference
+to any statement count, and a file matching `[report] include` stays in it even at zero statements — the
+proof is already committed, since `apps/proxy/live_proxy/__init__.py` is a zero-byte file and is line 6
+of `scripts/coverage_live_path.floor.modules`. (`skip_empty = True` suppresses such a file from the TEXT
+table only; the JSON the gate reads keeps it.) So the 38-file set is unchanged — measured at `16fbb952` by running
+`coverage run` over a no-op script under the same rcfile (`source =` triggers coverage's
+unexecuted-file walk, so the set does not depend on which tests ran): `8cb5c65dac3e`, 38 files, with
+and without the three new modules present, matching the floor's own `modules=`. `rcfile=` is
+untouched because the rcfile is not edited. **Ruling: 2d-1 ships NO floor edit at all** — neither a
+`--shape-only` re-baseline nor a `missing` bump. `missing` can only fall, since the move strictly
+removes statements from the denominator and the shims that replace them execute on
+import; measured on the 2d-1 shape through `scripts/coverage_live_path_isolated.sh --gate`, **1505
+against the floor's 1525**, green, printing "20 FEWER missed than the floor". Lowering it is declined
+too: plain `--write-floor` writes the figure from the run it just took, where this floor's policy is
+the worst of ≥12 **CI** rounds, and 2d-5's re-census is where that number legitimately moves. **The
+`--shape-only` re-baseline this paragraph ordered belongs to 2d-4 alone**, where deleting 28 modules
+moves the set for real. Nothing about #312 changes any of this: #312 is a claim about the *spread* of
+a number no move here claims. **The Done-log row for this amendment is left as written**: a Done-log row
+records what its own PR shipped, and A10's row saying 2d-1 ships a `--shape-only` re-baseline is an
+accurate record of what A10 claimed at the time. It is history, not a live instruction, and the
+instruction it recorded is corrected here and in the deletion list.
 
 **2d-4 is the harder half, and it needs a PR of its own.** Deleting 28 modules moves `modules=` again and
 drops the real draw by most of its value, so a `--shape-only` re-baseline there leaves a floor of
@@ -3415,7 +3430,9 @@ under. It is cheap and it is worth doing first for one reason: 2d-4 is the large
 the phase, and a flake that reddens its CI is a flake that gets attributed to the deletion.
 
 **A10.14 — thirteen test files OUTSIDE the deleted package import it, across three surviving labels,
-and each errors at import and fails its whole label.** Re-derived at this SHA by counting
+and each errors at import and fails its whole label.** (**Eleven across two labels by the time 2d-4
+runs — Amendment A11.4**, which moves the two `apps.timeshift.tests` files to 2d-1; the enumeration
+below is the one measured at `1326de3e` and is left as measured.) Re-derived at this SHA by counting
 `from apps.proxy.live_proxy` / `import apps.proxy.live_proxy` per file outside the package:
 
 - **`apps.channels.tests`** (7 files): `test_ts_proxy_teardown.py` (9 imports),
@@ -3424,7 +3441,12 @@ and each errors at import and fails its whole label.** Re-derived at this SHA by
   `test_ts_proxy_keepalive_duration.py` (1), `test_channel_stream_reuse.py` (1).
 - **`apps.proxy.tests`** (4 files): `test_stream_switch.py` (6), `test_boundary_error_arms.py` (3),
   `test_relay_status_shape.py` (2), `test_combined_stats.py` (1).
-- **`apps.timeshift.tests`** (2 files): `test_views.py` (4), `test_stats.py` (1).
+- **`apps.timeshift.tests`** (2 files): `test_views.py` (4), `test_stats.py` (1). **Amendment
+  A11.4: these two are 2d-1's, not 2d-4's, and the list is eleven files by the time 2d-4 runs.**
+  All five of their imports name `live_proxy.constants.ChannelMetadataField`/`ChannelState` — the
+  names 2d-1 relocates — so re-pointing them there costs five lines and takes the whole catch-up
+  label, the surface 2d KEEPS, off the deleted package by the same argument this amendment already
+  makes for `apps/timeshift/views.py` and `stats.py` in A10.3 site 8.
 
 A Python import error is not a test failure that can be tolerated per-test: it fails collection for
 the module and therefore the label. **Two of those three labels — `apps.proxy.tests` and
@@ -3538,7 +3560,10 @@ planner can decline them by citation rather than by judgement.
   `models_boot_trap_imports` metric reads `/models_module_level_live_proxy_imports`, which
   `scripts/metrics/collect_architecture.py:159-182` computes over **`apps/channels/models.py` only**
   — so it reaches zero at **2d-1** and deserves a milestone line there, and it will read zero while
-  eight other module-level sites are still live (A10.3). **It carries `headline: true`, exactly like
+  eight other module-level sites are still live (A10.3). **Amendment A11.5: the note sentence lands in 2d-1, not here** — the metric reads zero
+  from the moment 2d-1 merges, so a docs PR four PRs later is four PRs of a headline tile saying
+  something it does not mean. The milestone ROW stays a post-merge follow-up, for A9.9's reason.
+  **It carries `headline: true`, exactly like
   its neighbours at `:35` and `:39`** — this amendment's fix round first recorded the opposite, from
   a `cut -c1-200` that truncated a 235-character line three characters before the flag, which is the
   same read-a-truncation-as-an-absence mistake `CLAUDE.md` warns about for a discarded stderr. So it
@@ -3560,6 +3585,126 @@ planner can decline them by citation rather than by judgement.
   reads the marginal-coverage arithmetic before it adds them, and a draw above the floor is a finding
   to investigate per package and then per block, never a floor bump on the PR that drew it.
 
+#### Amendment A11 (2d-1) — eight rulings from the boot-trap relocation
+
+**Verified at `16fbb952`**, the merged tree 2d-1 branches from (`#320`, the #318 fix). Every figure
+below was measured there, and where an item contradicts a sentence in Amendment A10 or in § Stage
+2d's deletion list, that sentence is **edited in place** and the item says so.
+
+**A11.1 — the four names get three modules, mirroring the three they came from, and `constants.py`
+is SPLIT rather than moved whole.** `apps/proxy/redis_keys.py` takes `RedisKeys` entire (the seed
+file has no imports at all); `apps/proxy/config_helper.py` takes `ConfigHelper` entire; and
+`apps/proxy/constants.py` takes **only** `ChannelState` and `ChannelMetadataField`, leaving
+`REDIS_KEY_PREFIX`, `REDIS_TTL_*`, `EventType`, `StreamType` and the four TS packet constants in
+`apps/proxy/live_proxy/constants.py`, where nothing outside the package imports them and 2d-4 deletes
+them with the rest. Three reasons for the three-module shape rather than one combined module. The
+same basename makes the diff read as a move and keeps `git log --follow` working.
+`apps/timeshift/redis_keys.py` already establishes `<app>/redis_keys.py` as this tree's spelling.
+And the leaf guarantee is per-file: `redis_keys.py` and `constants.py` import **nothing**, while
+`config_helper.py` imports `apps.proxy.config` — whose own module-level imports are `time` and
+`django.db.connection` and nothing first-party — so folding them into one module would attach an
+import to the two files `apps/channels/models.py` loads on the migration path. The relocation moves
+the trap's address and not the trap: measured on the 2d-1 branch, adding `from apps.channels.models
+import Channel` to `apps/proxy/constants.py` makes `manage.py check` exit 1 with `ImportError: cannot
+import name 'Channel' from partially initialized module 'apps.channels.models' (most likely due to a
+circular import)`.
+
+**A11.2 — Gate 2's `modules=` does not move, A10.4 said it would, and A10.4 is corrected in
+place.** See the edited paragraph. The mechanism is the shim (A11.3): the relocated statements leave
+the denominator, but no FILE leaves the resolved set. Measured two ways at `16fbb952`: coverage
+7.16.0's own `GlobMatcher` over `[report] include` returns `False` for `apps/proxy/redis_keys.py`,
+`apps/proxy/constants.py` and `apps/proxy/config_helper.py` and `True` for all three
+`live_proxy/` paths; and a `coverage run` over a no-op script under the same rcfile prints
+`8cb5c65dac3e 38` with and without the three new modules on disk, which is the floor's own
+`modules=`/`module_count=`. A full `scripts/coverage_live_path_isolated.sh --gate` round on the 2d-1
+shape then drew `statements=7983` (floor 8073, informational) and `missing=1505` (floor 1525), exit
+0. **2d-1 ships no floor edit.** The cheap probe is worth keeping: it answers "did the file set move"
+in seconds without running a single test, and it is the only half of the gate a shape change can
+break.
+
+**A11.3 — the old modules survive as re-export shims until 2d-4, and that is what makes 2d-1
+small.** Measured at `16fbb952`: **140** import statements in the tree name one of the four symbols
+through one of the three modules — 33 non-test and 31 test inside `apps/proxy/live_proxy/`, the rest
+outside. 2d-1 re-points **19 of them, in 10 files** (A11.4) and leaves every other one on a shim. The
+alternative, re-pointing all 140, edits 25 modules and 31 test files that 2d-4 deletes wholesale, for
+no behaviour difference and at the cost of the `modules=` stability A11.2 depends on. Each shim is a
+module docstring plus one `from … import X  # noqa: F401`. What keeps `modules=` stable is that the
+three old **paths** still exist, not that they still carry a statement: the gate hashes a set of paths
+(`scripts/coverage_live_path.sh:223`), and a zero-statement file matching `[report] include` stays in
+that set — `apps/proxy/live_proxy/__init__.py` is zero bytes and is line 6 of the committed
+`scripts/coverage_live_path.floor.modules`.
+
+**A11.4 — the nineteen re-pointed import statements, and why the two timeshift TEST files are among
+them.** Non-test, fourteen statements in eight files: `apps/channels/models.py:6` and `:7`,
+`apps/channels/tasks.py:1125` and `:2445`, `apps/proxy/relay_client.py:61`,
+`apps/proxy/relay_views.py:38` and `:39`, `apps/proxy/next_source.py:348`, `:474` and `:1115`,
+`core/utils.py:759`, `apps/timeshift/views.py:40` and `:41`, `apps/timeshift/stats.py:13`. Test, five
+statements in two files: `apps/timeshift/tests/test_stats.py:12` and
+`apps/timeshift/tests/test_views.py:3235`, `:3478`, `:3508`, `:3535`. Those five are every
+`live_proxy` import those two files have, so re-pointing them takes `apps.timeshift.tests` — the
+catch-up label, the surface 2d KEEPS — off the deleted package entirely and reduces A10.14's thirteen
+files to **eleven**, edited in place there. `apps/proxy/authorize.py:380` is NOT in this list: it
+imports `url_utils.get_stream_object`, which is 2d-4's.
+
+**A11.5 — the `models_boot_trap_imports` milestone is a post-merge follow-up and the catalogue note
+is not.** `scripts/metrics/collect_architecture.py:159-182` counts module-level
+`apps.proxy.live_proxy` imports in `apps/channels/models.py` alone; measured at `16fbb952` it is
+**2**, and it is **0** on the 2d-1 shape. A milestone row carries the merge SHA and a merge commit
+cannot name itself (2c-9's Ruling R13, #276's precedent), so 2d-1 commits **no** `milestones.yml`
+row; the row is a one-line PR after merge. The catalogue NOTE that says the metric counts one file —
+which A10.17 assigned to 2d-6 — moves to 2d-1, because the tile reads zero from the moment 2d-1
+merges and a headline tile saying something it does not mean for four PRs is the cost of leaving it.
+A10.17's bullet is edited in place. `reverse_imports_into_proxy` is unmoved at **29**: every
+re-pointed import still names `apps.proxy`.
+
+**A11.6 — Gate 1 moves with `ConfigHelper`, which nothing in § Stage 2d or A10 anticipates, and it
+narrows by one hop.** `apps/proxy/live_proxy/tests/zero_orm_allowlist.py` needs exactly two edits,
+both measured: the `Site(config_helper.py, 50)` entry is **deleted** (the read is still there, at
+`apps/proxy/config_helper.py:66` — the code is byte-identical and sits sixteen lines lower because the
+new module's docstring is longer — but scope 1 is `apps/proxy/live_proxy/**` only, so the scanner
+reports it "listed but gone" — the ratchet runs both ways); and the
+`EdgeEntry(config_helper.py, apps.proxy.config, TSConfig, hits=5)` becomes
+`(config_helper.py, apps.proxy.config_helper, ConfigHelper, hits=1)`. The `hits` drop is real and is
+disclosed rather than absorbed: `scan_edge` is transitive **within the module only** (2b-3's Ruling
+R4), so where it used to see `TSConfig`'s five same-module classmethods it now sees one call, and the
+five are two hops out and invisible to it. The runtime half is unaffected and still catches the read
+through `SQL_SIGNATURES`' `proxy_settings_group`. The entry keeps `pr="2b-1"`: the PR that cleared
+the read is unchanged, and `AllowlistShapeTests.test_every_entry_states_what_closes_it` asserts
+`^(Phase 1 PR \d|2[abc]-\d)$`, which admits no `2d-1` — widening that regex to record a re-point
+rather than a clearance would be the wrong edit. A third file moves with them:
+`test_zero_orm_scan.py`'s `test_a_query_with_a_relay_frame_is_attributed_to_the_relay` drove
+`ConfigHelper.new_client_behind_seconds()` precisely because it issued a query from inside the
+package, which after the move it does not; the replacement driver is `views.py`'s
+`_output_profile_for` with a stub decision, whose `OutputProfile.objects.filter` at `views.py:152` is
+itself one of the remaining SITES. SITES goes 12 → 11; EDGES stays 12.
+
+**A11.7 — the boot-check hook arm takes six literal paths, not two.** The three new homes, because
+that is where a cycle now stops Django booting; and the three `live_proxy/` shims, until 2d-4 deletes
+them, because `apps/proxy/apps.py`'s `ready()` still reaches them in every process that is not
+`manage.py`. `apps/proxy/config_helper.py` is in the arm although `apps/channels/models.py` does not
+import it: `apps/timeshift/views.py:40` does, at module level, and the urlconf is loaded by
+`manage.py check`. `CLAUDE.md` § Test hooks and § Structural constraints are corrected in the same
+commit, per this programme's per-PR correction convention rather than being left to 2d-6.
+
+**A11.8 — two gate items in § Stage 2d's PR 1 entry need restating, because neither means what it
+says.** (i) "`manage.py check` green in every role" is one check, not four:
+`DISPATCHARR_ROLE` appears in **no** Python file in the tree (`grep -rn DISPATCHARR_ROLE --include=
+'*.py'` is empty at `16fbb952`) — it selects supervisord programs, and every role runs the same
+Django module graph. The pair that actually covers the boot path is `manage.py check` plus a command
+that drives the migration loader (`manage.py showmigrations dispatcharr_channels`), since the trap's
+victim is the loader. (ii) `makemigrations --check` is **not clean at the seed**: `16fbb952` reports
+`Migrations for 'core': core/migrations/0028_alter_streamprofile_parameters.py ~ Alter field
+parameters on streamprofile` and exits 1, before 2d-1 touches anything. Nothing in CI runs it
+(§ Known defects already says so) and the edit hook runs it per **app**, resolved through
+`apps.get_app_configs()`, so the honest gate item for a PR editing `apps/channels/models.py` is "no
+pending migration for `dispatcharr_channels`", and the pre-existing `core` drift is neither caused
+nor fixed here. (iii) "every backend label green" is **five** labels, not sixteen, and that is not a
+shortfall: `scripts/ci_backend_test_labels.py` routes all sixteen paths 2d-1 touches to
+`apps.channels.tests`, `apps.proxy.live_proxy.tests`, `apps.proxy.tests`, `apps.timeshift.tests` and
+`core.tests`; nothing this PR touches is under `dispatcharr/test_discovery.py`'s
+`_SHARED_PATH_PREFIXES`, and CI's own `plan` job derives its labels from the same function, so the
+five are exactly what `Backend result` will run.
+
 ## Stage 2d — cutover, and its trap
 
 **The historical bug this stage exists to not repeat.** Every live-bound nginx location today carries
@@ -3781,12 +3926,16 @@ share a PR with the delete that makes it measurable).
    must not be left pointing at a directory PR 4 deletes); re-pointing
    `.claude/hooks/run-affected-tests.sh:136-145`'s boot-check `case` arm, which matches the two old
    paths **by literal path** and silently stops running otherwise, plus the same two path names in
-   `CLAUDE.md` § Test hooks; and a milestone line for `metrics/curated/`'s
-   `models_boot_trap_imports`, which reaches zero here (A10.17). Everything else is PR 4's, named
-   there. **Amendment A10.4: this PR moves two files out of Gate 2's denominator and therefore trips
-   `modules=` on its first push** — it ships a
-   `scripts/coverage_live_path.sh --write-floor --shape-only` re-baseline, `missing` unchanged at
-   1525, and says which kind of move it is in one line, per the floor's own procedure. Gate:
+   `CLAUDE.md` § Test hooks; and, for `metrics/curated/`'s `models_boot_trap_imports`, which reaches
+   zero here (A10.17), **the catalogue NOTE saying the metric counts `apps/channels/models.py` alone —
+   not a `milestones.yml` row. Amendment A11.5 corrects this entry's original "a milestone line":** a
+   milestone row carries the merge SHA and a merge commit cannot name itself (A9.9), so the row is a
+   one-line PR after 2d-1 merges. Everything else is PR 4's, named
+   there. **Amendment A11.2 corrects A10.4 here: this PR does NOT trip `modules=` and ships no floor
+   edit at all.** The relocated names leave the denominator, but the old PATHS stay as
+   re-export shims, and coverage's resolved `files` set is a set of paths, so it is byte-identical — `8cb5c65dac3e`, 38 files,
+   measured both ways — and `missing` can only fall (measured 1505 against the floor's 1525). The
+   `--shape-only` re-baseline A10.4 ordered is 2d-4's. Gate:
    `manage.py check` green, every backend label green, `Backend result` green including the
    coverage gate — noting that `manage.py check` passes today with the directory present, so it
    proves this relocation did not break boot and proves nothing about the other eight sites.
@@ -3861,9 +4010,11 @@ share a PR with the delete that makes it measurable).
    metadata-hash ranges in `apps/channels/models.py` (three reads at `:516-519`, `:696-702` and
    `:747-750`; two `hdel`s at `:717-721` and `:773-778`),
    which PR 1's relocation otherwise carries along unchanged and which read and write a key the Go
-   relay never writes. (g) A10.14 — **thirteen test files outside the deleted package import it**,
-   across `apps.channels.tests` (7 files), `apps.proxy.tests` (4) and `apps.timeshift.tests` (2);
-   each errors at import and fails its whole label, and two of those labels are in
+   relay never writes. (g) A10.14 — **eleven test files outside the deleted package import it**,
+   across `apps.channels.tests` (7 files) and `apps.proxy.tests` (4); **Amendment A11.4 corrects the
+   thirteen this entry originally named**, because 2d-1 re-points the two `apps.timeshift.tests` files,
+   whose five `live_proxy` imports all name the constants it relocates. Each errors at import and fails
+   its whole label, and BOTH surviving labels are in
    `.github/workflows/backend-tests.yml:180`'s coverage matrix, so `coverage-gate` fails with them.
    **This PR's plan gives a per-file disposition** — delete, rewrite against the Go relay, or keep by
    dropping the import — rather than discovering them from a red run. (h) A10.15 — re-point the three
@@ -4004,6 +4155,7 @@ Filled in as PRs merge; this spec lands as its own PR 0.
 | 2c-8 -- the Go relay's control routes and drain (`migration/phase2c-control-drain`). The four remaining `/proxy/relay/…` routes (the single-channel `GET` with its `?fields=state` form, the channel `DELETE`, the client `DELETE` and `advance`), the detail endpoint with its five extra client fields and row 14's `owner` asymmetry, the XC live roots (Ruling R1: spec D1 scopes them and no PR owned them), the four events the tune and stop paths raise, the dev-only `POST /_dispatcharr/authorize-internal` fallback and the Go half that calls it, and D6's SIGTERM drain with a real `/readyz` and a role-aware Docker `HEALTHCHECK`. Thirteen parity-matrix rows get a Go pin, taking the matrix to 28 of 28 pinnable rows, and the ten authorize-matrix rows among them gain a Notes clause saying the Go pin covers the relay's ask-and-obey share and not the decision, which stays Django's. Amendment A8. Four defects found and fixed, three in code this PR did not write: `RequireInternal` verifying the bound signature against an empty body (A8.3), `Manager.publish` bypassing `addClient` for the first client of every channel (A8.4), `control.Emitter` panicking on a send after `Close` and on a second `Close` (A8.5), and -- in this PR's own first draft, found by a Gate 2 coverage test -- the `x-api-key` body field that never arrived, because DRF reads input by a field's NAME and `source=` maps only the output (A8.9). Two Python-side findings reproduced and filed rather than fixed: `source_bitrate` and `ffmpeg_bitrate` are read by `channel_status.py` and written by nothing, the second because the reader and the writer name two different constants ([#314](https://github.com/D10Scot/Dispatcharr/issues/314)). Four break-checks stayed green on a first attempt and each produced a better test or deleted unreachable code. Five plan-text corrections found and made in-tree, none changing the shipped code: Task 0 Step 2's expected `c.clients[` grep count on the merged 2c-7 tree said four hits including `StopClient`'s lookup, but `StopClient` does not exist until this PR's own Task 1 -- the measured count on the tree Task 0 actually ran against is three (one write, two reads); Appendix U's request-count fix, written for Task 4 Step 5, was applied at Task 1 instead so Task 1's own commit would not land with `./httpapi` red under Constraint 33, and both steps now say so; Tasks 2, 3 and 4 landed in one commit rather than three, plus Ruling R10's `Emitter` guards and Task 8's self-contained Docker/entrypoint/healthcheck pieces, because building each task in isolation surfaced a three-link build/test dependency chain the plan's task boundaries did not show; `authorize_test.go` (Task 6) defines `runningIDs` and `containsString`, and `xc_test.go` (Task 7) calls rather than redefines them, the reverse of where the plan first placed them; and `server.go`'s `/healthz`/`/readyz` doc comment was rewritten as one coherent paragraph rather than applied as Appendix J's original hunk, which would have left a stale 2c-1 sentence ("this PR adds no Docker HEALTHCHECK") sitting directly above the paragraph describing the HEALTHCHECK this PR adds -- Appendix J's hunk text is regenerated to match. | `migration/phase2c-control-drain` | pending |
 | 2c-9 -- the Go coverage gate and stage 2c's close-out (`migration/phase2c-go-coverage-gate`). `scripts/coverage_relay_go.sh` measures the ten packages the shipped binary LINKS (not `./...`: `internal/relaytest` and `internal/credlint` are out by the same rule the Python rcfile applies, worth 73.74% vs 84.12% on one run at `a635190c`) under `go test -count=1 -race -covermode=atomic`, and gates on `missing` against a floor whose number is the worst of a 12-round CI census (sequence 589 589 588 588 589 589 589 588 588 588 588 589; max set at round 1, unchanged through round 12), with `shape=`/`packages=`/`gomod=` as equality checks and `statements` recorded but never compared. `go-tests.yml` gains `coverage` and `differential` jobs, both in `Go result`'s needs; `codeql.yml` gains a Go job of its own with `build-mode: manual`, verified live via a manual `workflow_dispatch` since it carries no `pull_request` trigger. The parity matrix's Go half becomes mechanical: an eighth guard check plus `GO_PARITY_CLOSED`, with rows 26 and 27 exempt by construction rather than by an exemption list; on this tree 28 of 28 pinned rows already carry a Go reference. Amendment A2.4's cross-implementation differential lands as one harness test that starts `relay-go` against the test's own `LiveServerTestCase` Django, green on the first attempt (Ran 1 test in 6.5s); a second differential (row 9's realignment) was built, run and dropped because `FakeUpstream`'s looping payload cannot express a mid-packet start without re-breaking every loop. [#309](https://github.com/D10Scot/Dispatcharr/issues/309) fixed by widening the dead-air bound by a tenth of a check interval, the asserted count of three unchanged -- the stamp move first proposed for it was measured not to reduce the failure rate (2 sub-400 ms gaps in 60 loaded runs against 1 in 60 unmodified, independently reproduced on a third host at 1-in-30 for both shapes) and the margin turned out to be the health monitor's ticker drift, about a millisecond, rather than the 50 ms interval the floor looks like. 2c-8's `relay/drain/drain_test.go` stops restating `docker/supervisord.d/relay-go.conf`'s `stopwaitsecs` as a Go constant and reads it, through a newly exported `relaytest.RepoRoot()`, failing rather than defaulting when the key is gone -- five break-checks, the load-bearing one being `stopwaitsecs=60` staying green so the assertion is a bound and not an equality. Amendment A9, twelve rulings including A9.12: a plan-text defect found and fixed in this PR, where Task 3 Step 1's example `gh api` command carried a `--repo` flag that tool does not have (and would have been semantically wrong regardless, since the endpoint's own path already names the target repository); corrected in the plan document as committed, and the four resolved action pins matched Appendix C's existing ones exactly, confirming no drift; a second, smaller miscount in the same plan ("seven" break-check failure modes against a table and later text both saying eight, in Task 2 Step 5's heading and Task 10 Step 1's PR-description instruction) found and corrected alongside it. One commit-sequencing self-correction, disclosed rather than silently fixed: Appendix C's `go-tests.yml` diff is written as one hunk spanning both the `coverage` and `differential` jobs, but Tasks 3 and 4 describe them as separate commits; the whole appendix was applied and committed together on the first pass, then split into the two intended commits via `git reset --soft` before anything was pushed. Three handoffs declined with reasons (the matrix line-number refresh, the `fmp4.go` split and its `"remux stderr"` rename, the milestone row). | `migration/phase2c-go-coverage-gate` | pending |
 | Amendment A10 -- what stage 2d inherits from stage 2c (`docs/phase2d-inputs-amendment`). Seventeen findings verified against the merged 2c tree at `1326de3e`, the first tree on which all nine 2c PRs exist together, and seven in-place corrections to § Stage 2d's deletion list, which grows from five PRs to six. The load-bearing ones: `Go result` is not a required check on the Main ruleset (ruleset `21229979` requires six contexts and not that one), so 2d-3 has a precondition no commit can satisfy; every route beyond `/healthz` and `/readyz` is behind `DISPATCHARR_RELAY_GO_DEV_ROUTES` (`relay/config/config.go:146-155`, `relay/httpapi/server.go:62-89`), which `relay-go.conf` does not set, so pointing nginx at 5658 today 404s every tune; the module-level boot trap is NINE sites, the boot-fatal one being `dispatcharr/settings.py:107`'s `INSTALLED_APPS` entry and four more sitting inside `apps/proxy/` itself, the sharpest of those being `apps/proxy/relay_views.py:34-41` -- a surviving Gate 2 boundary module that is Django's implementation of the five routes the Go relay takes over; Gate 2's Python gate loses 28 of its 38 modules and is tripped by 2d-1 on its first push, so 2d-1 ships a `--shape-only` re-baseline and a new 2d-5 carries the post-delete CI census (the docs PR becomes 2d-6); the parity matrix's Python column replacement moves from the docs PR to 2d-4 because `parity-matrix.ts:369` and `:476` both fail on a deleted path (measured: 53 of 86 Source citations and all 38 Python pins are inside the directory), with rows 26 and 27 left to the 2d-4 plan since they are `white-box-only` behaviours with no Go source to re-point at and the guard has no retired form; the Go suite opens the Python harness's ffmpeg corpus in place (`relay/internal/relaytest/corpus.go:56-57`, `:65`) and 44 further Go citations into `live_proxy/` dangle -- a floor, not a budget, since 694 further lines under `relay/` cite the deleted files by bare name and none is fixed in 2d; deleting the differential test breaks `Go result` unless `go-tests.yml:472` and its `:496-501` success loop are edited in the same commit, and nothing replaces the only CI job that DRIVES the Go binary against a real Django (every E2E container already RUNS it beside real stores). Three findings of the amendment's own, not on the brief: the four extra boot-trap sites; `relay-go.conf:21-23`'s comment promising a `nice` level "in 2c-2" that nine PRs later is still absent, which makes the byte-carrying process the lowest-priority of three for any operator who took the documented `UWSGI_NICE_LEVEL=-5`; and [#190](https://github.com/D10Scot/Dispatcharr/issues/190) NOT closing by deletion, since all five of its metadata-hash ranges (one of them previously unrecorded, `apps/channels/models.py:747-750`) are in a file 2d does not delete. Two corrections to § Stage 2d's own text: there is no "multi-client sharing" greybox spec and nothing in `e2e/` ever imported relay internals, so one greybox spec is rewritten rather than two. **Opus review fix round (four blocking, nine should-fix, all reproduced before applying).** The boot-trap enumeration was incomplete in the way that matters and went from five sites to NINE: it missed `dispatcharr/settings.py:107`'s `INSTALLED_APPS` entry (boot-fatal in every role, and the mechanism behind the 16-to-15 label count the spec already asserted without naming), `apps/proxy/tasks.py:6` (a Celery-autodiscovered module whose `channel_stats` emission scans Redis keys the Go relay never writes -- a capability decision, not a rehome), `apps/timeshift/views.py:40-41` and `stats.py:13` (catch-up, the surface 2d KEEPS, and the source of `ChannelState`/`ConfigHelper` having no assigned home in this spec at all -- now 2d-1's), `apps/proxy/apps.py:9-15` plus its two `getattr(proxy_app, 'live_proxy')` consumers that no import grep finds, and five further function-local imports. The greybox Redis rewrite and its `allowlist.ts`/`COVERAGE.md` twins were scheduled at the DELETE while breaking at the FLIP, so PR 3 could not have passed its own `E2E result` gate: moved to PR 3, with a table saying which PR OWNS each E2E edit rather than only which event breaks it. Thirteen test files outside the deleted package import it -- seven in `apps.channels.tests`, four in `apps.proxy.tests`, two in `apps.timeshift.tests` -- each failing its whole label at import, two of those labels inside the coverage matrix; enumerated as A10.14, with per-file dispositions required of the 2d-4 plan and 2d-5's census tied to them. Three `metrics/curated/defects.yml` rows cite test files 2d-4 deletes and `metrics/build/curated.py:320-325` fails on a missing path, first surfacing on `main` after merge because the commit gate runs the validator only for staged `metrics/` paths: moved into PR 4 with `--validate-only` added to its gate (A10.15). One inherited factual error corrected in two places: the Python relay DOES read `X-Relay-Client-IP` (`authorize_views.py:185`, `live_proxy/views.py:202-206`, pinned by `test_client_ip_provenance.py:103`), so row 17's field is production-proven before the cutover rather than first at it -- and the sentence at spec line 1621 that said otherwise, which contradicted row 17 inside this same document, is fixed in place. Also: a sixteenth `relay_client` call site in dead code (`core/tasks.py:428-436`); `DISPATCHARR_RELAY_GO_PORT` honoured by the binary and the healthcheck but baked as a literal in the cutover's own sed, a 502 on every tune for an operator who sets it (A10.16); the dangling-citation count restated as a floor rather than a budget (694 `.py` lines under `relay/` cite deleted files by bare name, none fixed in 2d); and re-measured call-site counts (13 in-process, 11 `CorpusPath(`) against the first draft's 16 and 12. | `docs/phase2d-inputs-amendment` | pending |
+| 2d-1 -- the boot-trap relocation (`migration/phase2d-boot-trap-relocation`). `RedisKeys`, `ChannelMetadataField`, `ChannelState` and `ConfigHelper` move out of `apps/proxy/live_proxy/` into three Django-owned modules -- `apps/proxy/redis_keys.py` and `apps/proxy/constants.py`, both leaves with no imports at all, and `apps/proxy/config_helper.py`, which imports only `apps.proxy.config` -- with `constants.py` SPLIT rather than moved whole so `EventType`, `StreamType`, `REDIS_TTL_*` and the TS packet constants die with the package at 2d-4. The three old PATHS stay as re-export shims, which is what keeps the diff to 19 import statements in 10 files out of the 140 in the tree that name these symbols, and what keeps Gate 2's `modules=` byte-identical -- the gate hashes a set of paths, so a path that still exists cannot leave the set whatever its statement count. Amendment A11, eight rulings, four of which correct A10 or § Stage 2d in place: **A10.4 was wrong that this PR trips `modules=`** (measured `8cb5c65dac3e`/38 files with and without the new modules, and two full isolated rounds at `missing=1505` and `1509` against the floor's 1525, both green -- the total is bimodal by design, which is why only the exit status and the shape fields are assertions) so **no floor edit ships at all** and the `--shape-only` re-baseline becomes 2d-4's alone; A10.14's thirteen test files become **eleven**, because all five `live_proxy` imports in `apps/timeshift/tests/{test_views,test_stats}.py` name the relocated constants and re-pointing them takes the catch-up label off the deleted package; A10.17's `models_boot_trap_imports` catalogue note moves here from 2d-6 since the tile reads 0 from this merge (the milestone ROW stays a post-merge one-liner, A9.9's reason); and two gate items are restated -- `DISPATCHARR_ROLE` appears in no Python file, so "green in every role" is one `manage.py check` plus a migration-loader command, and `makemigrations --check` is already dirty at the seed (`core/0028_alter_streamprofile_parameters`), pre-existing and neither caused nor fixed here. Gate 1 moves with `ConfigHelper` and nothing in the spec anticipated it: one SITE deleted (12 -> 11), one EDGE re-pointed with `hits` 5 -> 1 -- a real one-hop narrowing of the static half, since `scan_edge` is transitive within the module only -- and `test_zero_orm_scan.py`'s attribution driver replaced with `views.py`'s `_output_profile_for`, whose own ORM read is already an allowlisted SITE. The boot-check hook arm and `CLAUDE.md`'s two prose copies of it take six literal paths instead of two; the trap moved house rather than away, measured as `ImportError: cannot import name 'Channel' from partially initialized module` when a cycling import is added to the new `apps/proxy/constants.py`. #190's five ranges in `apps/channels/models.py` are carried along unchanged, as A10.17 rules. | `migration/phase2d-boot-trap-relocation` | pending |
 
 ## Risks
 
```

---

## Self-review

### Round-2 fix, after the review of `ec8d394f`

One blocking finding and three notes, all four reproduced here and all four correct.

**NEW-1 was a miss of exactly the kind the round-1 fix was about.** B1 and S6 converted Task 0 Step 3 and R5 to `git grep` and wrote the reason into both; **Task 3 Step 2 carries the same `grep -r . | grep -v "^./apps/proxy/live_proxy/"` shape and was not converted with them.** Measured on this PR's tree: **12** lines under `/usr/bin/grep`, **44** under this harness's wrapped `grep` — and the thirty-two extra are every non-test file in the package, against a stop rule reading "a non-test hit means one of R5's nineteen was [missed]". Converted to `git grep -nE … -- '*.py' ':!apps/proxy/live_proxy/*'`, which returns the twelve under either implementation with no `grep -v` at all. The reviewer swept the rest and this was the only survivor; R2's (`:62`, explicit directory args), R3's (`:75`, no path filter) and R9's (`:220`, expects empty) are all safe under both, and I re-confirmed that.

**NEW-2**: three places still read as though the shim's statement count were what keeps the file set stable — the Architecture paragraph, the PR body, and Appendix H's deletion-list entry 1 sentence — four hundred lines from A11.3's "not that they still carry a statement". None was false; all three now say "paths". The purely descriptive "Becomes a one-statement re-export shim" in the File-structure table stays.

**NEW-3**: "forty-five sites import `as RedisKeys`" conflates two numbers. Measured: **45** lines name `apps.timeshift.redis_keys` (that is what the filter removes), of which **40** carry the `as RedisKeys` alias; the other five match through `TimeshiftRedisKeys` itself. Both figures now stated.

**NEW-4**: Task 2 Step 3's `django.setup()` check emits `RuntimeWarning: Accessing the database during app initialization` and two `relation … does not exist` warnings on stderr, because the hook container migrates only the **test** database. Measured identical on the seed. The step is a stop-on-anything-else check, so it now names them as pre-existing and states that the exit status and the final line are the assertions.

### Fix round, after the opus review of `ceea871e`

The review verdict was FAIL: six blocking and eight should-fix findings, **every one of them a defect in the document rather than in the engineering** — both contested rulings, R4's refutation of A10.4 and R7's Gate 1 changes, were independently re-measured and confirmed, including all four break-checks and a second full isolated round (exit 0, `missing=1509`). Fourteen findings were reproduced here before being applied, on two throwaway worktrees at the seed — one pristine, one with the appendices applied — plus a third carrying **only Appendix A**, which is where two of them actually live. Every one was a genuine defect; none was disputed. What they were, and the pattern behind them:

**Five were an expected output that cannot be produced, which is a halt for an implementer following the document literally.**

- **Task 0 Step 3's `19?` check returned 63.** The parenthetical explaining the `test_stream_limits.py` exclusion was simply false: `apps/timeshift/redis_keys.py`'s `TimeshiftRedisKeys as RedisKeys` alias matches the pattern from **forty-five** sites, not one. The command now uses `git grep` with pathspecs plus an explicit `apps.timeshift.redis_keys` filter, returns 19, and prints four more counts (140/33/31 and the two metrics) so the whole of R3 and R5 is checkable in one step. `git grep` also closes a second hole the reviewer found: `grep -r .` emits a `./` prefix that some `grep` implementations on this harness's `PATH` do not, which silently turns a `grep -v "/apps/proxy/live_proxy/"` filter into a no-op and returns 140 instead. R5's own command had the same defect (S6) and got the same fix — a ruling whose stated command does not reproduce its number is an unsourced number.
- **Task 1 Step 2 expected `5:` for an import that is at `:21`.** The new `config_helper.py` docstring is sixteen lines longer than the one it replaces.
- **Task 4 Step 5 expected `lineno=50` for a read that is at `:66`** — the same sixteen-line shift, and the worst of the six because **Task 4 Step 3 instructed writing `:50` into four citations**, on the stated grounds that "the read did not move lines, only files". It moved both. Following that instruction would have planted a fresh stale citation, which is the exact failure shape the sweep exists to prevent. `:66` now appears in all six places, including Appendix E's `reason` and the spec's A11.6, and Step 3's justification is rewritten to say why.
- **Task 2 Step 3's `import apps.proxy.live_proxy.server` fails identically on the seed** with `AppRegistryNotReady`, so it could never have distinguished a working shim from a broken one. Measured exit 1 on both trees. Replaced with a `django.setup()` check that is strictly stronger — it asserts the shims re-export the **same objects** (`RedisKeys is R2`), which the old check never did — and un-piped, since reading `$?` after `| tail -3` is exactly how that unconditional failure would have been laundered into a plausible pass (S8, and Global Constraint 14 which the step itself was breaking).
- **Task 1 Step 3's `diff` reports `155a156 >`, a content difference by the step's own criterion**, so `&& echo "RedisKeys body identical"` never fires. The underlying fact was also half wrong: only `redis_keys.py` had a trailing blank line at the seed; `config_helper.py` did not, and its copy is byte-identical below the docstring. **And my first attempt to verify the correction was itself wrong** — I ran it on a fully-applied tree, where `live_proxy/redis_keys.py` is a shim with no `class RedisKeys:` at all, and got `1,155d0`, a useless "the whole class was added". The step now says to run it with only Appendix A applied, and that is where the `155a156` expectation was re-measured. The portable-`sed` alternative I first offered for it was **BSD-sed-incompatible** (`extra characters at the end of d command`); it is deleted rather than fixed.

**Four were a claim that would have entered the phase spec as a measured fact.**

- **The `skip_empty` mechanism was wrong in six places, including two spec amendments.** The plan said a shim's single statement is what keeps its file in Gate 2's resolved set. It is not: the gate hashes `sorted(json["files"].keys())`, a set of **paths**, with no reference to any statement count. The proof was already committed and I walked past it while writing R4 — `apps/proxy/live_proxy/__init__.py` is a **zero-byte** file with zero statements and is line 6 of `scripts/coverage_live_path.floor.modules`, with `skip_empty = True` set in the rcfile the whole time; `skip_empty` suppresses a file from the **text** table only. R4's conclusion is unaffected and is in fact **more** robust than claimed; the mechanism is corrected in R3, Task 2 Step 2, Task 7 Step 2's troubleshooting, the PR body, and spec A11.2 and A11.3. Task 7 Step 2's failure mode is rewritten to the real one: a file added under `apps/proxy/live_proxy/`, or one of the three old paths deleted.
- **Appendix H left two contradicting sentences standing in the spec**, against Task 8's own stated premise. Deletion-list entry 1 still asked 2d-1 for "a milestone line" that R10 declines, and entry 4's `(g)` still said "thirteen test files … `apps.timeshift.tests` (2)" against A11.4's eleven. Two more hunks now correct both. **A third contradiction surfaced only when I ran Task 8 Step 2's own grep against the corrected tree**: A10.14's *heading* still said "thirteen … across three surviving labels", which the bullet beneath it no longer does. It now carries the parenthetical, and the enumeration under it is left as measured at `1326de3e`.
- **Task 8 Step 2's expected output was not met by its own appendix.** A seventh `shape-only` hit exists — the `| Amendment A10 --` Done-log row, which assigns a re-baseline to 2d-1. Ruling: a Done-log row records what its own PR shipped and is history, not a live instruction; A10's row accurately records what A10 claimed, the claim is corrected in A10.4's text and in both deletion-list entries, and rewriting merged rows is not this programme's convention. A11.2 now says so in the spec, and the step expects **nine** hits with the two exceptions named, plus three further greps with their expected results.
- **Task 7 Step 3 quoted an exact `missing` for a number the tree documents as bimodal.** The reviewer's independent round drew **1509** against this plan's 1505, both green; `scripts/coverage_live_path_isolated.sh:9-11`'s own header says the per-container shape buys block-level determinism and not total determinism. The step now states the pass condition — exit 0, `statements=7983`, `missing` comfortably under 1525 — and says plainly that only the exit status and the shape fields are assertions. R4, the PR body and the Done-log row carry both figures.

**Three were arithmetic.** Task 3 Step 2 said "seven files, **eight** lines" and then listed twelve, excusing it with a parenthetical instead of correcting it (it is twelve). Appendix D's description said nineteen hunks where there are **sixteen** carrying nineteen lines, because two adjacent import pairs fold. R11 said "seven call sites" and listed **six** on five lines.

**One was a halt with no way past it.** Task 0 Step 1 expects `origin/main` at the seed and says stop otherwise; `origin/main` had moved to `57618a28` — **#321**, the stage-2c milestone row A10.17 itself said should land before 2d-1, one insertion in `metrics/curated/milestones.yml`. The step now names that exact delta as the one acceptable move and stops on anything else.

**One was a note worth taking.** "Every backend label green" is five labels, not sixteen, and that is not a shortfall — nothing this PR touches is under `_SHARED_PATH_PREFIXES`, and CI's `plan` job derives its labels from the same function the plan calls. Said in R9 and in spec A11.8 so it does not read as one.

Everything re-verified after the fixes: all eight appendices re-extracted from the corrected document apply individually and in sequence with `--whitespace=error`; the tree they produce is byte-identical to the one the corrections were authored on; Gate 1 is green (20 tests); `apps.proxy.tests` 403 OK and `apps.proxy.live_proxy.tests` 429 `OK (skipped=1)` — the latter on a re-run, after R12's #259 flake fired once more, exactly as the plan says to expect; `metrics.build --validate-only` and `check_credential_logging.py` green.

### Original review pass

Every `file:line` this plan cites was re-opened at the seed `16fbb952` and confirmed. What that pass found:

**Corrected before this plan was written.**

1. **"Fifteen non-test import statements in eight files" → fourteen.** An early count of R5's table double-counted; the actual non-test figure is 14 statements in 8 files, and the total with R6's five test statements is **19 in 10 files**, which is what the table, the appendix and the PR body all say. The `git apply` of Appendix D moves exactly nineteen lines, which is the check that settles it.
2. **A10.4's `modules=` claim, refuted rather than restated.** The first draft of this plan carried A10.4's prescription verbatim (ship a `--shape-only` re-baseline, `missing` unchanged at 1525) because the amendment is the authority. Measuring it — coverage's own `GlobMatcher`, then the no-op probe, then a full isolated round — showed the premise holds and the conclusion does not, because the amendment did not account for the shim. R4 and Amendment A11.2 are the result, and the spec is edited in place rather than left carrying both sentences.
3. **The seed's denominator is 8202, not the floor's 8073.** The first attempt to explain the measured 7983 arithmetically came out 129 short, which looked like a modelling error in R4. It was not: the floor's `statements` was measured on 2026-09-13 and 2c-8, 2c-9 and #318 have added to already-included modules since. Measured directly with the probe on a pristine seed: 8202. 8202 − 219 = 7983, exactly the static arithmetic (246 → 27). That stale-by-129 figure is itself the clearest possible illustration of why `statements` is provenance and not a check, and R4 says so.
4. **Gate 1's three consequences, none of them in the spec.** The first pass at this plan had Tasks 1–3 and a five-label run. Running that tree found two `test_zero_orm_reads` failures and one `test_zero_orm_scan` failure. All three are now R7 and Task 4, with the exact assertion text each produces. Had the plan shipped without them, the implementer would have met a red `apps.proxy.live_proxy.tests` at commit time with no guidance, and the tempting fix — widening `AllowlistShapeTests`' `pr` regex to admit `2d-1` — is the wrong one.
5. **`hits` 5 → 1 is a narrowing, not a neutral re-point.** The first draft of the allowlist edit carried `hits=5` forward on the assumption that re-pointing a module path does not change what an entry clears. The break-check in Task 4 Step 6 row 3 is what would have caught it; measuring `scan_edge` directly is what did. The `reason` field now carries the disclosure, because an allowlist whose entries do not say what they stopped covering is the failure mode the allowlist exists to prevent one level up.
6. **`makemigrations --check` is dirty at the seed.** The brief's non-negotiables list "`makemigrations --check` clean" as a gate item. Run on a pristine `16fbb952` it exits 1 on `core/0028_alter_streamprofile_parameters`. R9 restates the gate item as the per-app check the edit hook actually runs, and Task 0 Step 6 records the pre-existing drift so it is not discovered mid-PR and "fixed".
7. **"Green in every role" is one check.** `grep -rn DISPATCHARR_ROLE --include='*.py'` is empty at the seed. R9.
8. **A9.13 → A9.9.** The in-place correction to A10.17 first cited "A9.13's reason" for the milestone-row deferral. Amendment A9 has twelve rulings and the relevant one is A9.9, which A10.17 itself already cites. Corrected in Appendix H.
9. **The appendix diffs' trailing blank lines.** `apps/proxy/live_proxy/redis_keys.py` and `config_helper.py` end with a blank line before EOF at the seed. A byte-faithful copy inherits it and `git apply --whitespace=error` rejects it in a newly added file. The three new modules are trimmed to a single trailing newline, which is the one byte in which they are not byte-identical to their originals — Task 1 Step 3's `diff` check is written to expect it.
10. **Appendix D originally overlapped Appendix B.** The first generation put all three shims in one diff, which then conflicted with the `constants.py` hunk applied separately. The eight appendices are now disjoint by path and were verified applying in sequence to one tree.

**Confirmed as cited, and worth naming because each is load-bearing.**

- `apps/proxy/live_proxy/redis_keys.py` and `constants.py` have **no** module-level imports; `config_helper.py` has one, `apps.proxy.config`, at `:5` — and `apps/proxy/config.py`'s own module-level imports are `time` and `django.db.connection`, nothing first-party. Constraints 2 and 3.
- `.claude/hooks/run-affected-tests.sh:133-146` is the boot-check block and `:137` is the two-path `case` pattern. `CLAUDE.md:56` names the same two paths in prose and `:59` explains why; `:104` is § Structural constraints' bullet.
- `scripts/coverage_live_path.coveragerc:23-34` is the `[report] include` block; `scripts/coverage_live_path.floor:242-312` is the HOW TO MOVE THIS FLOOR procedure and `:313-321` are the fields.
- `scripts/metrics/collect_architecture.py:159-182` computes the metric over `apps/channels/models.py` alone; `metrics/curated/catalogue.yml:37-38` is the row, and it does carry `headline: true`.
- `.claude/hooks/pre-commit-tests.sh:185-198` is the metrics section of the commit gate, and it fires only for a staged `metrics/`, `scripts/metrics/` or `scripts/run_metrics_tests.sh` path.
- `apps/proxy/live_proxy/tests/zero_orm_allowlist.py:111-130` is the `Site` this PR deletes; `:444-452` is the `EdgeEntry` it re-points. `test_zero_orm_reads.py:249` is the `pr` regex; `:211-212` is the `if zero_orm_scan.scan_edge(e)` filter that explains why only one of the four new shim edges appears.
- `apps/proxy/live_proxy/views.py:136-155` is `_output_profile_for`, and its `OutputProfile.objects.filter` at `:152` is in the SITES list.

**Two things this plan states but could not settle from the tree.**

- **A clean seed coverage round.** Two attempts to measure the seed's own `missing` were discarded by #259's flake (`too few distinct speeds`, same test both times). The seed's **denominator** is measured (8202, by the probe, which runs no tests), and this PR's full round is measured (`missing=1505`, exit 0). What is not measured is the seed's own `missing`, so the "20 fewer" is against the floor's 1525 rather than against a same-day seed draw. That is what the gate compares anyway, so nothing in this plan depends on the missing figure — but a reviewer asking "20 fewer than what, exactly" deserves the honest answer.
- **Whether `manage.py check` would catch a cycle added to one of the three `live_proxy/` shims.** R8 keeps them in the arm on the strength of `apps/proxy/apps.py`'s `ready()` reaching them in every process that is not `manage.py` — which is A10.3's reading of that file, not a measurement, and `manage.py check` is precisely the process `ready()` skips. The arm is kept for them regardless: it costs one alternation, and 2d-4 removes all three. The new homes, which are the ones that matter, are measured (Task 5 Step 4).
