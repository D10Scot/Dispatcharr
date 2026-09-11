# Phase 2 PR 2b-1 — Names and Profiles on the Contract: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move five ORM reads out of the relay process by carrying the channel name, stream name, M3U profile name and the locked-ffmpeg `StreamProfile` on the `next-source`/`advance` contract, delete the dead `get_connections_left`, and add `proxy_settings` to the `next-source` response.

**Architecture:** Django already resolves every one of these values while it builds a `next-source` answer — it holds the `Channel`, `Stream`, `M3UAccountProfile` and `StreamProfile` rows in memory at that moment. Today it throws four of them away and the relay re-queries for them later, in its own process, on the byte path. This PR adds them to the `Source` dict (`apps/proxy/next_source.py`), declares them on `SourceSerializer`, carries them through `generate_stream_url` into the channel metadata hash at init and on every switch, and then deletes the relay-side ORM fallbacks that existed only because the values were not being sent. Nothing about *which* stream is chosen changes; this is additive on the wire and subtractive in the relay.

**Tech Stack:** Django 6 + DRF, Redis (channel metadata hash), gevent-patched uWSGI. Tests: `manage.py test` (custom runner, Postgres + Redis required), the stage-2a real-subprocess harness at `apps/proxy/live_proxy/tests/harness/`.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`, § *Stage 2b — complete the contract (Python)* and its PR table (row `2b-1`). The ADR underneath the whole boundary is `docs/adr/0005-the-relay-is-chosen-by-name-once-per-tune.md`. Parity matrix: `docs/relay-parity-matrix.md`.

**Branch:** `migration/phase2b-names-and-profiles`, off `origin/main` at `ef3d3145`.
**Worktree:** `/Users/dion/git/Dispatcharr/.worktrees/phase2-2b1`. Anchor **every** command with an absolute path or a leading `cd` into that worktree — the shell's default cwd is not reliable in a multi-agent run (`CLAUDE.md`).

---

## Global Constraints

- **Read `CLAUDE.md` in full before the first edit.** Everything below assumes it.
- **DRF serializers for every request and response body — never a raw dict** (`CLAUDE.md` § Conventions). Every new wire field is declared on a serializer in the same commit that produces it.
- **Test container.** Use `dispatcharr-testrunner-2b1` for runs **you launch yourself**. The `PostToolUse` hooks run in the harness's environment and **never see `DISPATCHARR_TEST_CONTAINER`** — neither a per-Bash `export` nor a `settings.local.json` `env` block reaches them (`CLAUDE.md` § Test hooks). An edit-triggered run therefore always uses the container literally named `dispatcharr-testrunner`, and whether it tests *your* code depends entirely on which worktree that one container is bind-mounted at. **Before the first edit, check it and re-point it at this worktree if it points elsewhere:**
  ```bash
  docker inspect dispatcharr-testrunner --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'
  ```
  Other agents are active in this session and may re-point it back. **If a hook run's output does not correspond to the code you just wrote, or Docker is down, say the tests did not run — do not describe the work as verified.**
- **Stage and commit in separate `Bash` calls.** The `PreToolUse` commit gate runs before the command, so one call doing both is blocked. A commit message containing the words `git commit` also trips it — write such a message with `Write` and commit with `-F <file>`.
- **Do not edit** `scripts/coverage_live_path.sh`, `scripts/coverage_live_path.floor`, `scripts/coverage_live_path.coveragerc`, or `scripts/coverage_live_path_isolated.sh`. Another agent owns them (2b-0). Do not edit any other worktree.
- **Do not edit `docs/relay-parity-matrix.md`.** Row 18 is `owed: 2b-3` and 2b-3 owns it. Row 16 is already pinned. This PR adds no row and closes none. If you believe a row needs changing, record it in the PR body instead.
- **2b runs fully sequentially** (orchestrator ruling): 2b-1's implementation does not start until 2b-0 has merged, so no two implementers contend for the shared `dispatcharr-testrunner`. The container check below is still correct and still required — other agents in the session may have re-pointed it.
- **Dependency on 2b-0, stated and not depended upon internally.** `scripts/coverage_live_path.floor` carries `statements=7978` as an **equality** check, and this PR adds and removes production statements inside the Gate 2 denominator (`apps/proxy/live_proxy/**`, `apps/proxy/next_source.py`, `apps/proxy/relay_serializers.py`, `apps/proxy/relay_views.py`, `apps/proxy/control_plane.py`). `scripts/coverage_live_path.sh --gate` will therefore refuse with a *shape/statements mismatch*, not a coverage regression. 2b-0 is in flight to fix exactly that. **2b-0 has landed by the time this PR starts (2b is sequential); do not read or rely on how it works.** If `--gate` refuses on the statements equality while this branch is open, record the refusal verbatim in the PR body and continue — it is not this PR's to fix, and it is not a coverage regression.
- `apps/proxy/serializers.py` and `apps/proxy/api_views.py` are **not** in the coverage denominator (`scripts/coverage_live_path.coveragerc` `[report] include`); `apps/proxy/next_source.py` **is**.
- **Credential hygiene:** `scripts/check_credential_logging.py` runs on every `*.py` edit. Never log a URL, path, header or credential except through `redact_url` / `redact_headers`. Names (channel/stream/profile) are not credentials and may be logged plainly, as they already are.
- **`apps/proxy/live_proxy/constants.py` is a leaf module** imported at module level by `apps/channels/models.py:6-7`. Adding a constant to `ChannelMetadataField` is safe; **adding an import to that file stops Django booting.** The edit hook runs `manage.py check` on it for this reason.

---

## What was verified against the tree, and what was not

This section is part of the deliverable. The implementer inherits both halves.

### Spec `file:line` references, re-derived at `ef3d3145`

| Spec citation | State at `ef3d3145` | Verdict |
|---|---|---|
| `input/manager.py:737` — `StreamProfile.objects.get(name='ffmpeg', locked=True)` | `input/manager.py:737` | **exact** |
| `services/channel_service.py:324,331,911` — name fallbacks | `:324` (`Channel.objects.filter(uuid=...)`), `:331` (`Stream.objects.filter(id=...)`), `:911` (`Stream.objects.filter(id=...)`) | **exact** |
| `channel_status.py:74`, `:92` | `:74` (`Stream.objects.filter`), `:92` (`M3UAccountProfile.objects.filter`) | **exact** |
| `url_utils.py:247` — `get_connections_left` | `:247` is the `def` line; the `M3UAccountProfile.objects.get` is at **`:261`**. The spec's prose elsewhere (§ *What the code says*) says "whose body at `:260`" — **off by one**. | **drifted (prose), exact (table)** |
| `views.py:152` — `OutputProfile.objects.filter(...)` | `views.py:152` | **exact** (2b-2's, untouched here) |
| `next_source.py:69-79`'s `get_stream_object` | `:69-79` | **exact** |
| `authorize_views.py:112-141`'s `User.objects.filter` | not re-derived — 2b-2's row, out of scope here | **not checked** |
| `url_utils.py:25` in-process import | `:25`, `from apps.proxy.next_source import get_stream_object, transform_url` | **exact** |
| `views.py:900`, `:1250`, `services/channel_service.py:397` — `resolve_source` in-process imports | `views.py:900`, `views.py:1250`, `channel_service.py:397` | **exact** |

### Three findings the spec's 2b table does not contain

These are **out of scope for this PR** and must be written into the PR body rather than fixed here, **and cited by issue number** — see § *Handing the three out-of-scope ORM findings forward* near the end of this plan. They are recorded because the spec's table is the input to 2c's "a Go relay cannot execute any row in this table" claim, and the table is incomplete.

1. **`get_stream_object(...)` still executes in the relay process on the tune path and on the transcode path** — `views.py:189` (`stream_ts`), `views.py:1178` (`next_stream`, API process), `input/manager.py:731` (`_establish_transcode_connection`), `apps/proxy/authorize.py:344`. It is a `get_object_or_404` pair, i.e. an ORM read, and the spec's table treats it only as *Django's* resolution helper.
2. **`channel.get_stream_profile()` is an ORM read that neither grep can see.** `views.py:430` and `input/manager.py:741`/`:745` call it on a model instance; there is no `.objects.` and no `get_object_or_404(` on those lines. The spec's part-1 static guard is structurally blind to it. **Only 2b-3's runtime check can catch it.** Say so in the PR body so 2b-3's author does not read a green static guard as "zero reads".
3. **`apps/proxy/config.py`'s `BaseConfig.get_proxy_settings()` reaches `CoreSettings`** and is outside `apps/proxy/live_proxy/` and outside `next_source.py`, so it is invisible to the part-1 guard as specified. It is cached (10s process-local on top of a Redis group cache), so it is not a per-request read, but it is not zero either.

### Two items in the 2b-1 scope list that turned out to need no production change

- **`next-source`'s identifier resolution already accepts a `stream_hash`.** `next_source.resolve_source` resolves the identifier through `get_stream_object` (`next_source.py:664`), which tries `Channel.uuid` and falls back to `Stream.stream_hash`; `resolve_initial_source` has a dedicated `isinstance(channel_or_stream, Stream)` preview branch (`:426-480`); and `api_views.next_source_view`'s own comment already says "Neither a Channel by uuid nor a Stream by stream_hash". `apps/proxy/tests/test_next_source_resolution.py::test_a_stream_hash_identifier_resolves_the_stream_surface` covers it **at the function level**. What is missing is a pin **at the HTTP route**, and coverage that the *new* fields this PR adds are present on the preview branch too. Task 2 adds both. **No production change is required for this scope item, and the plan says so rather than inventing one.**
- **`get_connections_left` has no caller.** `grep -rn "get_connections_left"` over the whole worktree (excluding `node_modules` and `.git`) finds: the definition (`url_utils.py:247`), its own test (`test_live_db_cleanup.py:167-175`), and prose in `CHANGELOG.md`, two plans and the spec. No production caller, no frontend caller, no e2e caller. **Delete it** (Task 1), per the spec's "unless a real caller surfaces".

### The measurement, and the ambiguity inside it

The gate is *"2b's own zero-ORM guard test (part 1, static) shows a measured reduction in surviving sites"* — but that guard is built in **2b-3**, not here. This plan therefore performs the census **by hand**, using the shape the spec prescribes for part 1, and records before/after numbers in the PR body. **No script is committed for it**: a throwaway implementation of the same check would be a second, diverging definition for 2b-3 to reconcile.

The spec defines the part-1 site set as two greps:

> (A) `apps/proxy/live_proxy/**` — `.objects.` or `get_object_or_404(`
> (B) *"every function `next_source.py` exports that `live_proxy` still imports in-process"* containing the same patterns.

**Set A is unambiguous. Set B is not, and the ambiguity matters to this PR.** Read literally, Set B is the three imported names (`get_stream_object`, `transform_url`, `resolve_source`) and only `get_stream_object`'s own body matches — **3 lines**. Read transitively (every function those three reach), it is **13 lines** at `ef3d3145`, because `resolve_source` fans out into `resolve_initial_source`, `get_stream_info_for_switch`, `get_alternate_streams` and `_source_from_info`.

The transitive reading has a perverse consequence for *this* PR: folding the locked-ffmpeg `StreamProfile` lookup into Django adds a `StreamProfile.objects.get(...)` inside `resolve_initial_source` / `_source_from_info`, so **moving a read out of the relay makes the transitive count go up**. Both readings are reported below; the headline number is Set A.

**A mechanism claim this plan does not assert:** the transitive expansion presumes `resolve_source` actually *runs* in the relay process. Reading the three in-process import sites (`views.py:900`, `views.py:1250`, `channel_service.py:397`), all three appear to be API-process or dead code — `change_stream` and `next_stream` are `IsAdmin` admin views that PR 4's routing put on the API role, and `channel_service.py:397`'s branch carries a comment saying no caller reaches it. **This was read, not executed.** Do not write "`resolve_source` never runs in the relay" into the PR body. What 2b-3's runtime check can establish, and nothing here can, is which of these actually execute under a real tune and a real status read.

**Baseline census, measured on this worktree at `ef3d3145`:**

```
SET A (apps/proxy/live_proxy/**, non-test, excluding comment-only lines): 8
  apps/proxy/live_proxy/input/manager.py:737              StreamProfile.objects.get(name='ffmpeg', locked=True)
  apps/proxy/live_proxy/channel_status.py:74              Stream.objects.filter(id=stream_id)
  apps/proxy/live_proxy/channel_status.py:92              M3UAccountProfile.objects.filter(id=...)
  apps/proxy/live_proxy/url_utils.py:261                  M3UAccountProfile.objects.get(id=m3u_profile_id)
  apps/proxy/live_proxy/services/channel_service.py:324   Channel.objects.filter(uuid=channel_id)
  apps/proxy/live_proxy/services/channel_service.py:331   Stream.objects.filter(id=stream_id)
  apps/proxy/live_proxy/services/channel_service.py:911   Stream.objects.filter(id=stream_id)
  apps/proxy/live_proxy/views.py:152                      OutputProfile.objects.filter(id=..., is_active=True)
  (plus 2 comment-only grep hits: views.py:919, views.py:1279 — both describe the
   very fallback this PR removes, and both become false statements; Task 4 rewrites them)

SET B literal (bodies of get_stream_object / transform_url / resolve_source):   3
SET B transitive (everything those three reach inside next_source.py):         13
```

**Target at the end of this PR: Set A = 3** (`channel_status.py:74` and `:92`, both deliberately left for 2b-3 to decide; `views.py:152`, 2b-2's). Set B literal unchanged at 3. Set B transitive expected to rise by 1-2 (the locked-ffmpeg lookup); report the exact number rather than predicting it.

The exact census command is in **Task 1, Step 1** and is re-run verbatim in **Task 7**.

---

## File Structure

**Django side (the contract producer)**

- `apps/proxy/next_source.py` — *modify*. `get_stream_info_for_switch` returns two more names; `_source_from_info` and both branches of `resolve_initial_source` emit the four new Source keys; a new module-level helper resolves the locked ffmpeg profile once per call; `resolve_source` attaches `proxy_settings` to the answer.
- `apps/proxy/serializers.py` — *modify*. `SourceSerializer` gains four fields; `NextSourceResponseSerializer` gains `proxy_settings`; a new `ProxySettingsSerializer`. **Not in the coverage denominator.**
- `apps/proxy/api_views.py` — unchanged. **Verify this by reading it, do not edit it.**

**Django→relay side (the switch contract)**

- `apps/proxy/relay_serializers.py` — *modify*. `RelayAdvanceRequestSerializer` gains `channel_name` and `m3u_profile_name`.
- `apps/proxy/relay_client.py` — *modify*. `advance()` gains the two keyword arguments and sends them.
- `apps/proxy/relay_views.py` — *modify*. `channel_advance_view` passes them to `ChannelService.change_stream_url`.

**Relay side (the consumers, and the deletions)**

- `apps/proxy/live_proxy/url_utils.py` — *modify*. `generate_stream_url` returns a 7-tuple; `get_connections_left` and the now-unused `M3UAccountProfile` import are deleted.
- `apps/proxy/live_proxy/views.py` — *modify*. Both `generate_stream_url` unpack sites; `initialize_channel` call gains three arguments; `change_stream` and `next_stream` pass real names into `relay_client.advance`; two stale comments rewritten.
- `apps/proxy/live_proxy/services/channel_service.py` — *modify*. Three ORM fallbacks deleted; `initialize_channel` and `_update_channel_metadata` gain and write the new fields.
- `apps/proxy/live_proxy/input/manager.py` — *modify*. `_establish_transcode_connection` reads the locked-ffmpeg profile from the metadata hash; `_try_next_stream` writes the names on the automatic-failover metadata hset.
- `apps/proxy/live_proxy/channel_status.py` — *modify*. `m3u_profile_name` prefers the hash. **The ORM fallback stays** — 2b-3 decides its fate.
- `apps/proxy/live_proxy/constants.py` — *modify*. Two new `ChannelMetadataField` members. **No new imports.**

**Tests**

- `apps/proxy/tests/test_next_source_api.py` — *modify*. Route-level pins for the new response fields and for a `stream_hash` identifier.
- `apps/proxy/tests/test_next_source_resolution.py` — *modify*. Function-level pins for the four Source keys on all three producer branches.
- `apps/proxy/live_proxy/tests/test_generate_stream_url_control_plane.py` — *modify*. The 7-tuple.
- `apps/proxy/live_proxy/tests/test_live_db_cleanup.py` — *modify*. `UrlUtilsDbCleanupTests` deleted with its subject.
- `apps/proxy/live_proxy/tests/test_ghost_session_cleanup.py`, `test_stream_ts_client_registration.py`, `test_internal_principal_no_redirect.py` — *modify*. Patched `generate_stream_url` return tuples grow by one element.
- `apps/proxy/live_proxy/tests/test_channel_names_on_the_contract.py` — **create**. The new behaviour's own pins, including the end-to-end status read through the stage-2a harness.
- `apps/proxy/live_proxy/tests/test_forced_ffmpeg_profile.py` — **create**. The locked-ffmpeg profile pin.

---

## A note on test claims

Every test below is labelled **PIN** or **REACH**.

- A **PIN** asserts a behaviour that must not change. It is not finished until you have done a **break check**: patch the production line the test is about so the behaviour is wrong, run the test, watch it fail, and do that **three consecutive times with three different plausible breakages** — then revert and watch it pass. Record the three breakages and their failure messages in the PR body. One red is not a break check.
- A **REACH** test executes a branch and asserts something weak (a call completes, a key exists). It is honest coverage, not a guarantee. Say so; do not call it a pin.

---

## Task 1: Baseline census, and delete the dead `get_connections_left`

**Files:**
- Modify: `apps/proxy/live_proxy/url_utils.py` (delete `:247-291`, and the `M3UAccountProfile` import at `:8`)
- Modify: `apps/proxy/live_proxy/tests/test_live_db_cleanup.py` (delete `class UrlUtilsDbCleanupTests`, `:164-176`)

**Interfaces:**
- Consumes: nothing.
- Produces: the recorded baseline numbers (Set A = 8, Set B literal = 3, Set B transitive = 13). Task 7 re-runs the same command and diffs against them.

- [ ] **Step 1: Take the baseline census**

Run this verbatim from the worktree root. It is the by-hand stand-in for 2b-3's part-1 guard.

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1

# SET A: live_proxy's own directory, code lines only.
grep -rn "\.objects\.\|get_object_or_404(" apps/proxy/live_proxy/ --include='*.py' \
  | grep -v "/tests/" \
  | awk -F: '{ l=$0; sub(/^[^:]*:[^:]*:/, "", l); gsub(/^[ \t]+/, "", l);
               printf "%-9s %s:%s\n", (l ~ /^#/ ? "(comment)" : "CODE"), $1, $2 }'

# SET B: next_source.py functions live_proxy imports in-process, literal and transitive.
python3 - <<'PY'
import ast, pathlib, re
root = pathlib.Path(".")
ns = root / "apps/proxy/next_source.py"
src = ns.read_text().splitlines()
tree = ast.parse(ns.read_text())
funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
imported = set()
for p in root.glob("apps/proxy/live_proxy/**/*.py"):
    if "/tests/" in str(p):
        continue
    for m in re.finditer(r"from apps\.proxy\.next_source import ([^\n#]+)", p.read_text()):
        imported.update(n.strip() for n in m.group(1).split(","))
def orm_lines(node):
    return [ln for ln in range(node.lineno, node.end_lineno + 1)
            if not src[ln-1].lstrip().startswith("#")
            and (".objects." in src[ln-1] or "get_object_or_404(" in src[ln-1])]
def callees(node):
    return {c.func.id for c in ast.walk(node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
roots = sorted(imported & funcs.keys())
print("imported in-process:", roots)
print("SET B literal:", sum(len(orm_lines(funcs[n])) for n in roots))
seen, stack, hits = set(), list(roots), []
while stack:
    n = stack.pop()
    if n in seen: continue
    seen.add(n)
    hits += [f"next_source.py:{ln} (in {n})" for ln in orm_lines(funcs[n])]
    stack += [c for c in callees(funcs[n]) if c in funcs]
print("SET B transitive:", len(hits))
for h in sorted(hits, key=lambda s: int(s.split(":")[1].split()[0])): print("  ", h)
PY
```

Expected at `ef3d3145`: **Set A = 8 CODE + 2 (comment); Set B literal = 3; Set B transitive = 13.** If any number differs, the tree has moved — record the real numbers and use those as the baseline, and say in the PR body that the plan's baseline was stale.

- [ ] **Step 2: Confirm `get_connections_left` still has no caller**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
grep -rn "get_connections_left" . 2>/dev/null | grep -v node_modules | grep -v "\.git/"
```

Expected: the definition, its own test, and prose in `CHANGELOG.md` / `docs/`. **Nothing else.** If a production caller appears, STOP this task and escalate to the orchestrator — the spec's fallback is "fold its answer into the response instead", which is a different task shape and needs a ruling.

- [ ] **Step 3: Run the test that is about to be deleted, and watch it pass**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test apps.proxy.live_proxy.tests.test_live_db_cleanup.UrlUtilsDbCleanupTests -v2
```

Expected: 1 test, OK. This is the "know what you are deleting" step — if it does not run, find out why before deleting anything.

- [ ] **Step 4: Delete the function, its test, and the now-unused import**

In `apps/proxy/live_proxy/url_utils.py`, delete the whole `get_connections_left` definition (from `def get_connections_left(m3u_profile_id: int) -> int:` through its trailing `finally:` block) and the import at the top:

```python
from apps.m3u.models import M3UAccountProfile
```

Then confirm the name is genuinely unused in that file:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
grep -n "M3UAccountProfile" apps/proxy/live_proxy/url_utils.py
```

Expected: no output.

In `apps/proxy/live_proxy/tests/test_live_db_cleanup.py`, delete the entire `class UrlUtilsDbCleanupTests(SimpleTestCase):` block (its one method included). Leave every other class alone.

- [ ] **Step 5: Run the two affected packages**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test apps.proxy.live_proxy.tests apps.proxy.tests -v1
```

Expected: PASS, with one fewer test than before. If `manage.py check` or an import fails, the `M3UAccountProfile` import removal took something else with it — put it back and re-check.

- [ ] **Step 6: Re-run Set A of the census**

Expected: **Set A = 7 CODE**, `url_utils.py:261` gone.

- [ ] **Step 7: Commit**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
git add apps/proxy/live_proxy/url_utils.py apps/proxy/live_proxy/tests/test_live_db_cleanup.py
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
git commit -m "$(cat <<'EOF'
relay: delete get_connections_left, which had no caller

One M3UAccountProfile.objects.get in the relay process, reachable only
from its own test. Spec § Stage 2b, url_utils.py:247 row: delete unless a
real caller surfaces. None did -- the whole-tree grep finds the
definition, the test, and prose in CHANGELOG.md and two plans.

Surviving ORM sites in apps/proxy/live_proxy/**: 8 -> 7.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
EOF
)"
```

---

## Task 2: Django puts the four names and `proxy_settings` on the contract

**Files:**
- Modify: `apps/proxy/next_source.py`
- Modify: `apps/proxy/serializers.py`
- Test: `apps/proxy/tests/test_next_source_resolution.py`, `apps/proxy/tests/test_next_source_api.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: every `Source` dict gains four keys, and the `next-source` response gains one:

  ```python
  # Source (apps/proxy/next_source.py; SourceSerializer in apps/proxy/serializers.py)
  "channel_name":          str | None   # Channel.name, or Stream.name on the preview branch
  "stream_name":           str | None   # Stream.name
  "m3u_profile_name":      str | None   # M3UAccountProfile.name
  "ffmpeg_stream_profile": dict | None  # {"id": int, "command": str, "args": str} | None

  # next-source response body (NextSourceResponseSerializer)
  "proxy_settings": {
      "buffering_timeout": float, "buffering_speed": float, "redis_chunk_ttl": int,
      "channel_shutdown_delay": float, "channel_init_grace_period": float,
      "channel_client_wait_period": float, "new_client_behind_seconds": float,
  }
  ```

  `ffmpeg_stream_profile` uses the wire spelling `args` for the model's `parameters` field, exactly as `StreamProfileRefSerializer` already does — see that serializer's docstring for why the producer flattens rather than using `source=`.

- [ ] **Step 1: Write the failing function-level tests**

Append to `apps/proxy/tests/test_next_source_resolution.py`. These are **PIN** tests — Django must never again hand the relay a source without these names.

```python
class SourceCarriesNamesTests(NextSourceResolutionTests):
    """PIN. Phase 2 PR 2b-1: every Source carries the names the relay used to
    re-query for (spec § Stage 2b, the channel_service.py:324,331,911 row) and
    the locked ffmpeg profile (the input/manager.py:737 row)."""

    def test_the_initial_tune_source_carries_all_four_names(self):
        answer = resolve_source(self.channel.uuid)
        source = answer["source"]
        self.assertEqual(source["channel_name"], self.channel.name)
        self.assertEqual(source["stream_name"], self.stream_a.name)
        self.assertEqual(source["m3u_profile_name"], self.m3u_profile.name)

    def test_a_switch_source_carries_all_four_names(self):
        answer = resolve_source(
            self.channel.uuid, target_stream_id=self.stream_b.id, reason="operator"
        )
        source = answer["source"]
        self.assertEqual(source["channel_name"], self.channel.name)
        self.assertEqual(source["stream_name"], self.stream_b.name)
        self.assertEqual(source["m3u_profile_name"], self.m3u_profile.name)

    def test_a_previewed_stream_reports_its_own_name_as_the_channel_name(self):
        # stream_ts computes channel_display_name as getattr(channel, "name", None)
        # and a previewed Stream has .name, so this is the value the relay already
        # displays for a hash tune -- carried, not invented.
        answer = resolve_source(self.stream_a.stream_hash)
        source = answer["source"]
        self.assertEqual(source["channel_name"], self.stream_a.name)
        self.assertEqual(source["stream_name"], self.stream_a.name)
        self.assertEqual(source["m3u_profile_name"], self.m3u_profile.name)

    def test_the_locked_ffmpeg_profile_is_carried_when_one_exists(self):
        ffmpeg = StreamProfile.objects.create(
            name="ffmpeg", locked=True, command="ffmpeg", parameters="-i {streamUrl} -c copy -f mpegts pipe:1"
        )
        source = resolve_source(self.channel.uuid)["source"]
        self.assertEqual(
            source["ffmpeg_stream_profile"],
            {"id": ffmpeg.id, "command": "ffmpeg",
             "args": "-i {streamUrl} -c copy -f mpegts pipe:1"},
        )

    def test_no_locked_ffmpeg_profile_is_a_null_key_not_a_missing_one(self):
        StreamProfile.objects.filter(name="ffmpeg", locked=True).delete()
        source = resolve_source(self.channel.uuid)["source"]
        self.assertIn("ffmpeg_stream_profile", source)
        self.assertIsNone(source["ffmpeg_stream_profile"])

    def test_the_answer_carries_proxy_settings_as_resolved_now(self):
        from core.models import CoreSettings

        answer = resolve_source(self.channel.uuid)
        self.assertEqual(answer["proxy_settings"], CoreSettings.get_proxy_settings())
```

`NextSourceResolutionTests` is the existing base class in that file (`:87`). Its `setUp` (`:110-145`) creates `self.stream_profile_obj`, `self.account`, `self.m3u_profile` (fetched, not created — `M3UAccountProfile.objects.get(m3u_account=self.account, is_default=True)`), `self.stream_a` / `self.stream_b` (hashes `next-source-test-hash-a` / `-b`) and `self.channel`, and patches out `apps.proxy.next_source.close_old_connections` so more than one `resolve_source()` call per test is possible. Subclassing it inherits all of that. **Do not refactor that `setUp`** — 2b-2 and 2b-3 both touch this file and a refactor there is a merge conflict for two PRs.

- [ ] **Step 2: Run them and watch every one fail**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test apps.proxy.tests.test_next_source_resolution.SourceCarriesNamesTests -v2
```

Expected: 6 failures, each a `KeyError` on the new key (or an `AssertionError` on `proxy_settings`). A test that *errors* during `setUp` is not a red — fix the fixture first.

- [ ] **Step 3: Implement the producer side**

In `apps/proxy/next_source.py`:

Add the locked-ffmpeg resolver near `_resolve_live_stream_url`:

```python
def _locked_ffmpeg_profile():
    """The locked 'ffmpeg' StreamProfile, flattened, or None.

    input/manager.py:737 used to run this query inside the relay process on
    the force-ffmpeg reconnect path (HLS/RTSP/UDP upstreams detected at
    connect time). Phase 2 PR 2b-1 folds it into every next-source answer
    instead: Django is already holding an open ORM here, and the relay
    cannot be.

    None means "no locked ffmpeg profile is installed", which is what the
    relay's own `except StreamProfile.DoesNotExist` branch already handled
    by falling back to the channel's own profile. The key is always
    present so the relay can tell "not installed" from "old Django".
    """
    profile = StreamProfile.objects.filter(name="ffmpeg", locked=True).first()
    if profile is None:
        return None
    return {"id": profile.id, "command": profile.command, "args": profile.parameters}
```

In `get_stream_info_for_switch`, the returned dict already carries `stream_name`. Add two more keys next to it — both objects are already in hand, so this adds no query:

```python
            'stream_name': stream.name,
            'channel_name': channel.name,
            'm3u_profile_name': m3u_profile.name,
```

In `_source_from_info`, add the four keys to the returned Source (the first three read straight off `info`, with `.get()` so a caller that built an `info` by hand does not `KeyError`):

```python
        "channel_name": info.get("channel_name"),
        "stream_name": info.get("stream_name"),
        "m3u_profile_name": info.get("m3u_profile_name"),
        "ffmpeg_stream_profile": _locked_ffmpeg_profile(),
```

In `resolve_initial_source`, add the same four keys to **both** returned Sources. On the `isinstance(channel_or_stream, Stream)` preview branch:

```python
                        "channel_name": stream.name,
                        "stream_name": stream.name,
                        "m3u_profile_name": m3u_profile.name,
                        "ffmpeg_stream_profile": _locked_ffmpeg_profile(),
```

and on the channel branch:

```python
                    "channel_name": channel.name,
                    "stream_name": stream.name,
                    "m3u_profile_name": m3u_profile.name,
                    "ffmpeg_stream_profile": _locked_ffmpeg_profile(),
```

In `resolve_source`, attach `proxy_settings` to **every** return path — there are five (`answer` from `resolve_initial_source`, the `target_stream_id` success, the failover success, and the two "no candidate" dicts). Do it once, at the end, by wrapping each `return` through a helper rather than repeating the key five times:

```python
def _with_proxy_settings(answer):
    """Channel-start-time proxy settings, on every next-source answer.

    Spec § Stage 2b: "2b moves proxy_settings onto the next-source response
    (channel-start-time values only, matching D5's 'thresholds snapshotted
    at channel start' parity row)". Read through CoreSettings directly, not
    apps/proxy/config.py's TSConfig, so the 10-second process-local cache is
    not in the path. That cache is worse than merely stale: saving
    proxy_settings clears it in NO worker on the proxy path, because
    CoreSettings.invalidate_group_cache calls
    BaseConfig.clear_proxy_settings_cache() while every proxy read goes
    through TSConfig, whose own class attribute shadows the parent's
    (issue #232). The 10-second TTL is what actually ends the staleness.

    Nothing in the PYTHON relay consumes this yet, deliberately -- see this
    plan's § Self-review for the ruling and the reason, and this PR's
    description.
    """
    from core.models import CoreSettings

    answer["proxy_settings"] = CoreSettings.get_proxy_settings()
    return answer
```

and make each `return X` in `resolve_source` a `return _with_proxy_settings(X)`.

- [ ] **Step 4: Declare the new fields on the serializers**

In `apps/proxy/serializers.py`, add to `SourceSerializer`:

```python
    # Phase 2 PR 2b-1. Four values Django holds while it builds this answer
    # and the relay used to re-query for in its own process
    # (services/channel_service.py:324,331,911 and input/manager.py:737 in
    # the spec's § Stage 2b table). Nullable, never absent: a null says
    # "Django looked and there is nothing", which is a different fact from
    # a missing key, and the relay's fallbacks branch on exactly that.
    channel_name = serializers.CharField(allow_null=True)
    stream_name = serializers.CharField(allow_null=True)
    m3u_profile_name = serializers.CharField(allow_null=True)
    ffmpeg_stream_profile = StreamProfileRefSerializer(allow_null=True)
```

Add the settings serializer and the response field:

```python
class ProxySettingsSerializer(serializers.Serializer):
    """CoreSettings.get_proxy_settings()'s seven keys (core/models.py:709-717).

    Declared field by field rather than as a DictField so the contract is
    in the drf-spectacular schema and a Go client can generate against it.
    """

    buffering_timeout = serializers.FloatField()
    buffering_speed = serializers.FloatField()
    redis_chunk_ttl = serializers.IntegerField()
    channel_shutdown_delay = serializers.FloatField()
    channel_init_grace_period = serializers.FloatField()
    channel_client_wait_period = serializers.FloatField()
    new_client_behind_seconds = serializers.FloatField()
```

and on `NextSourceResponseSerializer`:

```python
    proxy_settings = ProxySettingsSerializer()
```

**Order matters:** define `ProxySettingsSerializer` above `NextSourceResponseSerializer` in the file.

- [ ] **Step 5: Run the function-level tests and watch them pass**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test apps.proxy.tests.test_next_source_resolution -v2
```

Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 6: Write the route-level tests**

Append to `class NextSourceRouteTests(RelayApiTestCase)` in `apps/proxy/tests/test_next_source_api.py` (`:199`). The base class `RelayApiTestCase` already provides `self._post(path, payload, *, signed=True)` (`:157`), `self.next_source_path(identifier)` (`:167`), and the same fixture names as `test_next_source_resolution.py`: `self.channel`, `self.stream_a`, `self.stream_b`, `self.m3u_profile`, `self.stream_profile_obj`, plus `self.redis` (a `FakeRelayApiRedis`). **Use them; add no new helper.**

```python
    def test_next_source_returns_the_four_names_and_proxy_settings(self):
        """PIN. Phase 2 PR 2b-1: the wire, not just the resolver."""
        from core.models import CoreSettings

        response = self._post(self.next_source_path(str(self.channel.uuid)), {})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        source = body["source"]
        self.assertEqual(source["channel_name"], self.channel.name)
        self.assertEqual(source["stream_name"], self.stream_a.name)
        self.assertEqual(source["m3u_profile_name"], self.m3u_profile.name)
        self.assertIn("ffmpeg_stream_profile", source)
        self.assertEqual(
            body["proxy_settings"]["buffering_timeout"],
            CoreSettings.get_proxy_settings()["buffering_timeout"],
        )

    def test_next_source_resolves_a_stream_hash_identifier_over_http(self):
        """PIN for parity-matrix row 16's Django half.

        The single-stream admin preview (/proxy/ts/stream/<stream_hash>) has
        no Channel, and the relay sends whatever identifier arrived in the
        URL. next_source.get_stream_object already falls back from
        Channel.uuid to Stream.stream_hash -- this pins that the ROUTE does
        too, which nothing covered before: the existing coverage
        (test_next_source_resolution.py::
        test_a_stream_hash_identifier_resolves_the_stream_surface) calls
        resolve_source directly and would still pass if the view rejected
        the identifier shape.
        """
        response = self._post(self.next_source_path(self.stream_a.stream_hash), {})
        self.assertEqual(response.status_code, 200)
        source = response.json()["source"]
        self.assertEqual(source["stream_id"], self.stream_a.id)
        self.assertEqual(source["channel_name"], self.stream_a.name)
```

- [ ] **Step 7: Run them, watch red then green**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test apps.proxy.tests.test_next_source_api -v2
```

If `test_next_source_resolves_a_stream_hash_identifier_over_http` passes on the *first* run with no production change, that is the expected result and it confirms this plan's finding that the scope item needed no code. Say so in the PR body; do not manufacture a change to make it look like work.

- [ ] **Step 8: Break-check the two PIN groups**

Three breakages, each run separately, each reverted:

1. In `_source_from_info`, change `"stream_name": info.get("stream_name")` to `"stream_name": None`. Expect `SourceCarriesNamesTests::test_a_switch_source_carries_all_four_names` and the route test to fail.
2. In `_locked_ffmpeg_profile`, drop the `locked=True` filter. Expect `test_the_locked_ffmpeg_profile_is_carried_when_one_exists` to still pass but `test_no_locked_ffmpeg_profile_is_a_null_key_not_a_missing_one` to fail **only if an unlocked `ffmpeg` profile exists in the fixture** — if it passes anyway, that is a weakness in the test: add an unlocked `ffmpeg` profile to that test's setup so the `locked=True` filter is genuinely pinned, then re-break.
3. In `resolve_initial_source`'s channel branch, change `"channel_name": channel.name` to `"channel_name": stream.name`. Expect `test_the_initial_tune_source_carries_all_four_names` to fail.

Record all three failure messages for the PR body.

- [ ] **Step 9: Confirm the schema still generates**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py spectacular --file /dev/null 2>&1 | tail -20
```

Expected: no error naming `ProxySettingsSerializer` or `SourceSerializer`. Warnings that already existed before this PR are not this PR's.

- [ ] **Step 10: Commit**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
git add apps/proxy/next_source.py apps/proxy/serializers.py apps/proxy/tests/test_next_source_resolution.py apps/proxy/tests/test_next_source_api.py
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
git commit -F /dev/stdin <<'EOF'
contract: next-source carries the names, the locked ffmpeg profile and proxy_settings

Django holds the Channel, Stream, M3UAccountProfile and StreamProfile rows
while it builds a next-source answer and throws four of them away; the
relay then re-queries for them in its own process, on the byte path. Every
Source now carries channel_name, stream_name, m3u_profile_name and the
locked ffmpeg profile flattened to {id, command, args}, and the answer
carries proxy_settings. Declared on SourceSerializer and a new
ProxySettingsSerializer -- no raw dicts.

Nothing consumes them yet; the relay-side deletions follow in this PR.

Also pins, at the ROUTE rather than the resolver, that next-source resolves
a stream_hash identifier (parity row 16). That already worked -- get_stream_object
falls back from Channel.uuid to Stream.stream_hash and the preview branch
already existed -- so the spec's "extend next-source's identifier resolution"
item needed no production change, only a pin that the view does not reject
the shape.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
EOF
```

---

## Task 3: The tune path consumes the names; two relay ORM reads go

**Files:**
- Modify: `apps/proxy/live_proxy/constants.py` (add two `ChannelMetadataField` members)
- Modify: `apps/proxy/live_proxy/url_utils.py` (`generate_stream_url` → 7-tuple)
- Modify: `apps/proxy/live_proxy/views.py` (two unpack sites, the `initialize_channel` call)
- Modify: `apps/proxy/live_proxy/services/channel_service.py` (delete `:324` and `:331`; write the new fields)
- Test: `apps/proxy/live_proxy/tests/test_generate_stream_url_control_plane.py`, `test_ghost_session_cleanup.py`, `test_stream_ts_client_registration.py`, `test_internal_principal_no_redirect.py`; create `apps/proxy/live_proxy/tests/test_channel_names_on_the_contract.py`

**Interfaces:**
- Consumes: Task 2's four Source keys.
- Produces:
  ```python
  # apps/proxy/live_proxy/url_utils.py
  def generate_stream_url(channel_id) -> tuple:
      """(url, user_agent, transcode, stream_profile_id, slot_reserved, error, tune_extras)"""

  # tune_extras, the 7th element -- always a dict, never None
  {
      "channel_name": str | None,
      "stream_name": str | None,
      "m3u_profile_name": str | None,
      "ffmpeg_stream_profile": dict | None,   # {"id", "command", "args"}
  }

  # apps/proxy/live_proxy/constants.py
  ChannelMetadataField.M3U_PROFILE_NAME = "m3u_profile_name"
  ChannelMetadataField.FFMPEG_STREAM_PROFILE = "ffmpeg_stream_profile"   # JSON-encoded

  # apps/proxy/live_proxy/services/channel_service.py
  ChannelService.initialize_channel(
      channel_id, stream_url, user_agent, transcode=False, stream_profile_value=None,
      stream_id=None, m3u_profile_id=None, channel_name=None, stream_name=None,
      m3u_profile_name=None, ffmpeg_stream_profile=None,   # <- new, both keyword-only in practice
  ) -> bool
  ```

- [ ] **Step 1: Write the failing tests**

Create `apps/proxy/live_proxy/tests/test_channel_names_on_the_contract.py`:

```python
"""PINs for Phase 2 PR 2b-1: the names arrive from Django and are stored,
so the relay never re-queries for them.

Spec: docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
§ Stage 2b, the services/channel_service.py:324,331,911 row.
"""

import json
from unittest.mock import patch

from django.test import TestCase

from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.services.channel_service import ChannelService


class InitializeChannelStoresTheNamesTests(TestCase):
    def _redis(self):
        """A ProxyServer whose redis_client records every hset mapping."""
        from unittest.mock import MagicMock

        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.exists.return_value = False
        proxy_server.initialize_channel.return_value = True
        return proxy_server

    def _written(self, redis_client):
        """Every field any hset wrote, merged."""
        written = {}
        for call in redis_client.hset.call_args_list:
            mapping = call.kwargs.get("mapping")
            if mapping:
                written.update(mapping)
            elif len(call.args) == 3:
                written[call.args[1]] = call.args[2]
        return written

    def test_the_supplied_names_reach_the_metadata_hash(self):
        proxy_server = self._redis()
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer"
        ) as cls:
            cls.get_instance.return_value = proxy_server
            ChannelService.initialize_channel(
                "chan-uuid", "http://u/s.ts", "UA",
                stream_id=7, m3u_profile_id=3,
                channel_name="BBC One", stream_name="BBC One HD",
                m3u_profile_name="Provider A default",
                ffmpeg_stream_profile={"id": 9, "command": "ffmpeg", "args": "-i {streamUrl}"},
            )
        written = self._written(proxy_server.redis_client)
        self.assertEqual(written[ChannelMetadataField.CHANNEL_NAME], "BBC One")
        self.assertEqual(written[ChannelMetadataField.STREAM_NAME], "BBC One HD")
        self.assertEqual(written[ChannelMetadataField.M3U_PROFILE_NAME], "Provider A default")
        self.assertEqual(
            json.loads(written[ChannelMetadataField.FFMPEG_STREAM_PROFILE]),
            {"id": 9, "command": "ffmpeg", "args": "-i {streamUrl}"},
        )

    def test_the_names_land_before_the_stream_manager_starts(self):
        """PIN. StreamManager's own threads read this hash; a field written
        only AFTER proxy_server.initialize_channel() returns is racing them.
        Asserts the hash carried every name by the time initialize_channel
        was called, not merely by the time the method returned."""
        proxy_server = self._redis()
        seen = {}

        def capture(*args, **kwargs):
            seen.update(self._written(proxy_server.redis_client))
            return True

        proxy_server.initialize_channel.side_effect = capture
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer"
        ) as cls:
            cls.get_instance.return_value = proxy_server
            ChannelService.initialize_channel(
                "chan-uuid", "http://u/s.ts", "UA",
                stream_id=7, m3u_profile_id=3,
                channel_name="BBC One", stream_name="BBC One HD",
                m3u_profile_name="Provider A default",
                ffmpeg_stream_profile={"id": 9, "command": "ffmpeg", "args": "-i x"},
            )
        self.assertEqual(seen[ChannelMetadataField.STREAM_NAME], "BBC One HD")
        self.assertEqual(seen[ChannelMetadataField.M3U_PROFILE_NAME], "Provider A default")
        self.assertIn(ChannelMetadataField.FFMPEG_STREAM_PROFILE, seen)

    def test_initialize_channel_runs_no_query_when_the_names_are_supplied(self):
        """PIN. This is the whole point of the PR: with names in hand, the
        relay's init path touches the ORM zero times."""
        proxy_server = self._redis()
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer"
        ) as cls:
            cls.get_instance.return_value = proxy_server
            with self.assertNumQueries(0):
                ChannelService.initialize_channel(
                    "chan-uuid", "http://u/s.ts", "UA",
                    stream_id=7, m3u_profile_id=3,
                    channel_name="BBC One", stream_name="BBC One HD",
                    m3u_profile_name="Provider A default",
                    ffmpeg_stream_profile=None,
                )
```

Also append to `apps/proxy/live_proxy/tests/test_generate_stream_url_control_plane.py`:

```python
    def test_the_seventh_element_carries_the_names_and_the_ffmpeg_profile(self):
        """PIN. generate_stream_url is the only thing between the next-source
        answer and the relay's init call; a name dropped here is a name the
        relay re-queries for."""
        source = make_source()
        source.update(
            channel_name="BBC One",
            stream_name="BBC One HD",
            m3u_profile_name="Provider A default",
            ffmpeg_stream_profile={"id": 9, "command": "ffmpeg", "args": "-i x"},
        )
        answer = {"source": source, "alternates": [], "error": None}
        with patch("apps.proxy.control_plane.next_source", return_value=answer), \
             patch("apps.proxy.live_proxy.url_utils._cache_alternates"):
            result = generate_stream_url("chan-1")
        self.assertEqual(
            result[6],
            {
                "channel_name": "BBC One",
                "stream_name": "BBC One HD",
                "m3u_profile_name": "Provider A default",
                "ffmpeg_stream_profile": {"id": 9, "command": "ffmpeg", "args": "-i x"},
            },
        )

    def test_an_old_django_answering_without_the_names_gives_a_dict_of_nulls(self):
        """PIN. The relay and the control plane are separately deployable
        processes (D5); a next-source answer from a Django that predates this
        PR must not KeyError on the byte path."""
        answer = {"source": make_source(), "alternates": [], "error": None}
        with patch("apps.proxy.control_plane.next_source", return_value=answer), \
             patch("apps.proxy.live_proxy.url_utils._cache_alternates"):
            result = generate_stream_url("chan-1")
        self.assertEqual(
            result[6],
            {"channel_name": None, "stream_name": None,
             "m3u_profile_name": None, "ffmpeg_stream_profile": None},
        )
```

- [ ] **Step 2: Run them, watch them fail**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test \
  apps.proxy.live_proxy.tests.test_channel_names_on_the_contract \
  apps.proxy.live_proxy.tests.test_generate_stream_url_control_plane -v2
```

Expected: the new tests fail (`TypeError: unexpected keyword argument 'm3u_profile_name'`, `IndexError: tuple index out of range`, `AttributeError: M3U_PROFILE_NAME`). The **four pre-existing** `GenerateStreamUrlControlPlaneBodyTests` also still pass at this point — they will break in Step 5, which is expected and handled there.

- [ ] **Step 3: Add the two metadata field names**

In `apps/proxy/live_proxy/constants.py`, inside `class ChannelMetadataField`, under `# Profile fields`:

```python
    M3U_PROFILE_NAME = "m3u_profile_name"
    # The locked ffmpeg StreamProfile, JSON-encoded {"id", "command", "args"},
    # written from the next-source answer so input/manager.py's force-ffmpeg
    # path (HLS/RTSP/UDP upstreams) needs no StreamProfile query in the relay
    # process. Phase 2 PR 2b-1.
    FFMPEG_STREAM_PROFILE = "ffmpeg_stream_profile"
```

**Add no import to this file.** The edit hook runs `manage.py check`; if it fails, you added one.

- [ ] **Step 4: Make `generate_stream_url` return the 7th element**

In `apps/proxy/live_proxy/url_utils.py`, add the extractor and widen every return:

```python
_TUNE_EXTRA_KEYS = (
    "channel_name", "stream_name", "m3u_profile_name", "ffmpeg_stream_profile",
)


def _tune_extras(source):
    """The four values Phase 2 PR 2b-1 added to the Source, defaulted to None.

    Always a dict with all four keys, so callers index rather than probe --
    and a next-source answer from a Django that predates 2b-1 degrades to
    the pre-2b-1 behaviour (the relay's own fallbacks) instead of raising on
    the byte path. The relay and the control plane are separately deployable
    processes; a KeyError here would be a tune failure, not a missing name.
    """
    return {key: (source or {}).get(key) for key in _TUNE_EXTRA_KEYS}
```

Then change the docstring's "Same 6-tuple every caller already reads" to name seven, and widen all four returns:

```python
        return None, None, False, None, False, "Control plane refused this channel", _tune_extras(None)
        ...
        return None, None, False, None, False, "Control plane unreachable", _tune_extras(None)
        ...
        return None, None, False, None, False, answer.get("error"), _tune_extras(None)
        ...
    return (
        source["url"],
        source["user_agent"],
        source["transcode"],
        source["stream_profile"]["id"],
        source["slot_reserved"],
        None,
        _tune_extras(source),
    )
```

- [ ] **Step 5: Fix every unpack site and every patched return value**

Find them all:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
grep -rn "generate_stream_url" apps/ | grep -v "url_utils.py"
```

Two production unpack sites, both in `stream_ts`:

- `apps/proxy/live_proxy/views.py:327` and `:376` — add `tune_extras,` as the last name in each tuple. Initialise `tune_extras = _tune_extras(None)` alongside the other pre-loop initialisers (`stream_url = None`, `profile_value = None`, …) so the `stream_url is None` bail-out path never references an unbound name; import `_tune_extras` from `.url_utils` next to the existing `generate_stream_url` import.

Five test files, each with a literal 6-tuple to widen by one element (`{}` is fine where the test does not care):

- `apps/proxy/live_proxy/tests/test_ghost_session_cleanup.py` — `:289`, `:500`, and every other `return_value = (` under a `@patch(".../generate_stream_url")` (grep the file; there are five patch decorators).
- `apps/proxy/live_proxy/tests/test_stream_ts_client_registration.py` — `:308`.
- `apps/proxy/live_proxy/tests/test_internal_principal_no_redirect.py` — the two patch sites at `:96` and `:157`.
- `apps/proxy/live_proxy/tests/test_generate_stream_url_control_plane.py` — the four `assertEqual(result, (...))` assertions at `:47`, `:62`, `:72`, `:82`. Rename `test_success_returns_the_6_tuple_and_caches_alternates` to `test_success_returns_the_7_tuple_and_caches_alternates` and add the seventh element to all four expected tuples.
- `apps/proxy/tests/test_redirect_transcode_flag.py` — read it; its docstring mentions the 6-tuple. If it unpacks, widen it; if it only mentions it in prose, fix the prose.

- [ ] **Step 6: Thread the names into `initialize_channel`**

In `apps/proxy/live_proxy/views.py`, at the `ChannelService.initialize_channel(...)` call (`~:551`):

```python
                    success = ChannelService.initialize_channel(
                        channel_id,
                        stream_url,
                        stream_user_agent,
                        transcode,
                        profile_value,
                        stream_id,
                        m3u_profile_id,
                        channel_name=tune_extras["channel_name"] or channel.name,
                        stream_name=tune_extras["stream_name"],
                        m3u_profile_name=tune_extras["m3u_profile_name"],
                        ffmpeg_stream_profile=tune_extras["ffmpeg_stream_profile"],
                    )
```

`or channel.name` is deliberate and is **not** a new ORM read: `channel` is already in hand from `get_stream_object` at `:189` for `channel.id` and `channel.get_stream_profile()`, neither of which this PR removes (see § *Three findings* above). It is the pre-2b-1-Django degradation path.

- [ ] **Step 7: Write the fields in `channel_service.initialize_channel`, and delete the two fallbacks**

In `apps/proxy/live_proxy/services/channel_service.py`:

Widen the signature:

```python
    def initialize_channel(channel_id, stream_url, user_agent, transcode=False,
                           stream_profile_value=None, stream_id=None, m3u_profile_id=None,
                           channel_name=None, stream_name=None,
                           m3u_profile_name=None, ffmpeg_stream_profile=None):
```

and document the two new arguments in the docstring's `Args:` block, matching the existing "(avoids DB lookup if already known)" phrasing.

Build the names once, above the existing pre-init block, and write them in **both** arms of it (the `exists` arm and the create arm) — `StreamManager`'s threads start inside `proxy_server.initialize_channel(...)` below and read this hash, so a field written only afterwards is racing them:

```python
            import json

            names = {}
            if channel_name:
                names[ChannelMetadataField.CHANNEL_NAME] = channel_name
            if stream_name:
                names[ChannelMetadataField.STREAM_NAME] = stream_name
            if m3u_profile_name:
                names[ChannelMetadataField.M3U_PROFILE_NAME] = m3u_profile_name
            if ffmpeg_stream_profile:
                names[ChannelMetadataField.FFMPEG_STREAM_PROFILE] = json.dumps(
                    ffmpeg_stream_profile
                )
```

In the `if proxy_server.redis_client.exists(metadata_key):` arm, change the single-field `hset` to a mapping that includes `names`; in the `else` arm, merge `names` into `initial_metadata`. **If `stream_id` is falsy the whole pre-init block is skipped today** — leave that structure alone; the post-init `update_data` block below still writes the names, and a tune with no `stream_id` has no manager to race.

Delete the two ORM fallbacks (`:322-333` in the current file — the `if not channel_name:` and `if not stream_name and stream_id:` blocks and their `try/except`), and delete the now-unused `Channel` / `Stream` imports **only if nothing else in the file uses them** — check with `grep -n "Channel\b\|Stream\b" apps/proxy/live_proxy/services/channel_service.py` before removing an import.

In the post-init `update_data` block, add the two new fields next to the existing `channel_name` / `stream_name` writes:

```python
                if m3u_profile_name:
                    update_data[ChannelMetadataField.M3U_PROFILE_NAME] = m3u_profile_name
                if ffmpeg_stream_profile:
                    update_data[ChannelMetadataField.FFMPEG_STREAM_PROFILE] = json.dumps(
                        ffmpeg_stream_profile
                    )
```

- [ ] **Step 8: Run the two packages**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test apps.proxy.live_proxy.tests apps.proxy.tests apps.channels.tests -v1
```

Expected: PASS. `apps.channels.tests` is in the list because `_PATH_ALIASES` routes `apps/proxy/live_proxy/` to it as well (`CLAUDE.md` § Testing) — the commit gate will run it anyway.

- [ ] **Step 9: Break-check the three PINs in `test_channel_names_on_the_contract.py`**

1. Move the `names` write from the pre-init block to the post-init `update_data` block only. Expect `test_the_names_land_before_the_stream_manager_starts` to fail and `test_the_supplied_names_reach_the_metadata_hash` to still pass — which is exactly the pair of tests doing its job.
2. Re-add `if not stream_name and stream_id: stream_name = Stream.objects.filter(...)`. Expect `test_initialize_channel_runs_no_query_when_the_names_are_supplied` to fail **only if the fallback fires** — it will not, because `stream_name` is supplied. Change the test's `stream_name=` to `None` in a scratch edit to confirm the `assertNumQueries(0)` has teeth, then revert both. **If it has no teeth, say so in the PR body and downgrade that test to REACH** rather than leaving a PIN claim you could not substantiate.
3. Drop `ChannelMetadataField.M3U_PROFILE_NAME` from the `names` dict. Expect `test_the_supplied_names_reach_the_metadata_hash` and `test_the_names_land_before_the_stream_manager_starts` to fail.

- [ ] **Step 10: Re-run Set A of the census**

Expected: **Set A = 5 CODE** (`channel_service.py:324` and `:331` gone).

- [ ] **Step 11: Commit**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
git add apps/proxy/live_proxy/constants.py apps/proxy/live_proxy/url_utils.py apps/proxy/live_proxy/views.py apps/proxy/live_proxy/services/channel_service.py apps/proxy/live_proxy/tests/
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
git commit -F /dev/stdin <<'EOF'
relay: the tune path takes its names from the contract, not from the ORM

generate_stream_url returns a seventh element carrying the four values
2b-1 added to the Source, and stream_ts passes them to
ChannelService.initialize_channel, which writes them into the metadata hash
BEFORE proxy_server.initialize_channel starts the StreamManager -- the
manager's own threads read that hash, so a field written afterwards is
racing them.

Deletes the Channel.objects and Stream.objects name fallbacks
(services/channel_service.py:324,331 in the spec's Stage 2b table). A
next-source answer with no names degrades to a dict of Nones rather than
raising, because the relay and the control plane are separately deployable
processes.

Surviving ORM sites in apps/proxy/live_proxy/**: 7 -> 5.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
EOF
```

---

## Task 4: The switch paths carry the names; the third relay ORM read goes

**Files:**
- Modify: `apps/proxy/relay_serializers.py` (`RelayAdvanceRequestSerializer`)
- Modify: `apps/proxy/relay_client.py` (`advance`)
- Modify: `apps/proxy/relay_views.py` (`channel_advance_view`)
- Modify: `apps/proxy/live_proxy/views.py` (`change_stream` ~`:900-930`, `next_stream` ~`:1250-1290`; the two stale comments at `:919` and `:1279`)
- Modify: `apps/proxy/live_proxy/services/channel_service.py` (`change_stream_url`, `_update_channel_metadata`; delete `:911`)
- Modify: `apps/proxy/live_proxy/input/manager.py` (`_try_next_stream`'s metadata `hset`)
- Test: `apps/proxy/live_proxy/tests/test_channel_names_on_the_contract.py`, `apps/proxy/tests/test_relay_control_api.py`

**Interfaces:**
- Consumes: Task 2's Source keys, Task 3's `ChannelMetadataField.M3U_PROFILE_NAME`.
- Produces:
  ```python
  # apps/proxy/relay_client.py
  def advance(identifier, *, url, user_agent=None, stream_id=None, m3u_profile_id=None,
              stream_name=None, channel_name=None, m3u_profile_name=None,
              reset_tried=False) -> dict

  # apps/proxy/live_proxy/services/channel_service.py
  ChannelService.change_stream_url(channel_id, new_url=None, user_agent=None,
      target_stream_id=None, m3u_profile_id=None, stream_name=None,
      channel_name=None, m3u_profile_name=None) -> dict
  ChannelService._update_channel_metadata(channel_id, url, user_agent=None,
      stream_id=None, m3u_profile_id=None, stream_name=None,
      channel_name=None, m3u_profile_name=None) -> bool
  ```

**Context the implementer needs, because it is not obvious from the files:**
`apps/proxy/live_proxy/views.py:919` and `:1279` are comments asserting that `stream_name` is "Always None: the Source contract … carries seven fields and stream_name is not one of them", and that the relay resolves it by primary key instead. **Both statements stop being true in this PR.** Rewriting them is part of the work, not a tidy-up.

**A behaviour change, flagged:** `input/manager.py`'s `_try_next_stream` writes the post-switch metadata hash directly (`~:2115-2128`) and **never writes `STREAM_NAME`**. After an automatic failover today, the hash keeps the *previous* stream's name, and `GET /proxy/ts/status/<uuid>` reports it. That is a stale value, not a missing one, so `channel_status.py:74`'s "no name in Redis" fallback never fires for it. Writing the name here fixes a real defect and changes an externally-observable field. It is in scope because the whole point of carrying `stream_name` is that the relay stops guessing — but **it is a behaviour change and must be called out in the PR body**, and it is adjacent to parity-matrix row 18 (`owed: 2b-3`). **Do not edit the matrix.**

- [ ] **Step 1: Write the failing tests**

Append to `apps/proxy/live_proxy/tests/test_channel_names_on_the_contract.py`:

```python
class SwitchPathsCarryTheNamesTests(TestCase):
    def test_change_stream_url_writes_the_supplied_names_without_a_query(self):
        """PIN. services/channel_service.py:911's Stream.objects fallback is
        what this replaces."""
        from unittest.mock import MagicMock

        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.type.return_value = "hash"
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer"
        ) as cls:
            cls.get_instance.return_value = proxy_server
            with self.assertNumQueries(0):
                ChannelService._update_channel_metadata(
                    "chan-uuid", "http://u/new.ts", "UA",
                    stream_id=11, m3u_profile_id=3,
                    stream_name="BBC Two HD",
                    channel_name="BBC Two",
                    m3u_profile_name="Provider A default",
                )
        mapping = proxy_server.redis_client.hset.call_args.kwargs["mapping"]
        self.assertEqual(mapping[ChannelMetadataField.STREAM_NAME], "BBC Two HD")
        self.assertEqual(mapping[ChannelMetadataField.CHANNEL_NAME], "BBC Two")
        self.assertEqual(
            mapping[ChannelMetadataField.M3U_PROFILE_NAME], "Provider A default"
        )
```

And, for the automatic-failover path, add to `apps/proxy/live_proxy/tests/test_try_next_stream.py` (the file that already drives `_try_next_stream`; read its existing setup and reuse it rather than building a new one):

```python
    def test_an_automatic_failover_writes_the_new_stream_name(self):
        """PIN. Before Phase 2 PR 2b-1 this hset carried no STREAM_NAME, so
        the status payload kept reporting the PREVIOUS stream's name after a
        failover -- a stale value, not a missing one, so channel_status.py's
        "no name in Redis" fallback never fired for it."""
        # ... drive one failover with a next-source answer whose source carries
        # stream_name="BBC Two HD" and m3u_profile_name="Provider A default",
        # then assert on the mapping passed to redis_client.hset.
```

Fill that body in against the file's existing idiom — the assertion is on the `mapping=` kwarg of the `hset` call `_try_next_stream` makes, exactly as the test above does.

- [ ] **Step 2: Run them, watch them fail**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test \
  apps.proxy.live_proxy.tests.test_channel_names_on_the_contract \
  apps.proxy.live_proxy.tests.test_try_next_stream -v2
```

Expected: `TypeError: unexpected keyword argument 'channel_name'` and a `KeyError`/`AssertionError` on `stream_name`.

- [ ] **Step 3: Widen the Django→relay advance contract**

`apps/proxy/relay_serializers.py`, on `RelayAdvanceRequestSerializer`, next to the existing `stream_name`:

```python
    # Phase 2 PR 2b-1: Django resolved these while it chose the source, so the
    # relay writes them into its metadata hash instead of re-querying
    # (services/channel_service.py:911 in the spec's § Stage 2b table).
    channel_name = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=None
    )
    m3u_profile_name = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=None
    )
```

`apps/proxy/relay_client.py`, `advance()`: add `channel_name=None, m3u_profile_name=None` to the keyword-only signature and to the `payload` dict.

`apps/proxy/relay_views.py`, `channel_advance_view`: pass both through:

```python
        stream_name=source["stream_name"],
        channel_name=source["channel_name"],
        m3u_profile_name=source["m3u_profile_name"],
```

- [ ] **Step 4: Make the two admin views send real names**

In `apps/proxy/live_proxy/views.py`'s `change_stream`, replace the `stream_name = stream_info.get("stream_name")` line and its six-line comment with:

```python
            # Phase 2 PR 2b-1: the Source carries the names now. Before this
            # PR the key did not exist, so this was always None and the relay
            # re-resolved the name by primary key
            # (services/channel_service.py:911).
            stream_name = stream_info.get("stream_name")
            channel_name = stream_info.get("channel_name")
            m3u_profile_name = stream_info.get("m3u_profile_name")
```

and pass `channel_name=channel_name, m3u_profile_name=m3u_profile_name` on the `relay_client.advance(...)` call below. Do the same in `next_stream` (`~:1275-1290`), replacing its identical stale comment.

- [ ] **Step 5: Consume them in the relay and delete `:911`**

In `apps/proxy/live_proxy/services/channel_service.py`:

- `change_stream_url`: add `channel_name=None, m3u_profile_name=None` to the signature; document them; pass them on to `_update_channel_metadata` at `:488`. The dead `if not new_url and target_stream_id:` branch (which calls `resolve_source`) can also take them from `stream_info` — do that, one line each, so the branch stays consistent if it is ever reached again. **Do not delete that branch**; its comment explains why it is kept.
- `_update_channel_metadata`: add `channel_name=None, m3u_profile_name=None` to the signature; **delete** the `if not stream_name: try: Stream.objects.filter(...)` fallback and the function-local `from apps.channels.models import Stream` inside it; write the three names into the `metadata` dict when truthy:

```python
            if stream_name:
                metadata[ChannelMetadataField.STREAM_NAME] = stream_name
            if channel_name:
                metadata[ChannelMetadataField.CHANNEL_NAME] = channel_name
            if m3u_profile_name:
                metadata[ChannelMetadataField.M3U_PROFILE_NAME] = m3u_profile_name
```

Note that `stream_name` is currently written **inside** the `if stream_id:` block. Keep that nesting for `stream_name` (a name without an id is meaningless on this hash) but put `channel_name` and `m3u_profile_name` at the top level.

- [ ] **Step 6: Write the names on the automatic-failover path**

In `apps/proxy/live_proxy/input/manager.py`'s `_try_next_stream`, the `hset` mapping (`~:2117`): add the two names from the source, guarded, so a degraded-fallback source from the cached list (which may predate 2b-1) does not write `"None"`:

```python
                    mapping = {
                        ChannelMetadataField.URL: source["url"],
                        ...
                        ChannelMetadataField.STREAM_SWITCH_REASON: "max_retries_exceeded",
                    }
                    # Phase 2 PR 2b-1: before this, the hash kept the PREVIOUS
                    # stream's name after an automatic failover -- a stale
                    # value, which is why channel_status.py:74's "no name in
                    # Redis" fallback never fired for it.
                    if source.get("stream_name"):
                        mapping[ChannelMetadataField.STREAM_NAME] = source["stream_name"]
                    if source.get("m3u_profile_name"):
                        mapping[ChannelMetadataField.M3U_PROFILE_NAME] = source["m3u_profile_name"]
                    self.buffer.redis_client.hset(
                        RedisKeys.channel_metadata(self.channel_id), mapping=mapping
                    )
```

**Do not** add `stream_name` to `_CACHED_ALTERNATE_REQUIRED_FIELDS` — a cached alternate written before this PR has no such key, and requiring it would make the degraded-failover path reject every stale cache entry and refuse to fail over during a Django outage. That is the opposite of what the degraded path is for.

- [ ] **Step 7: Run the packages**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test apps.proxy.live_proxy.tests apps.proxy.tests apps.channels.tests -v1
```

Expected: PASS. If `apps.proxy.tests.test_relay_control_api` fails on the advance request shape, its fixture is sending a body the widened serializer now validates differently — read the failure before changing the serializer.

- [ ] **Step 8: Break-check**

1. Drop `channel_name` from `_update_channel_metadata`'s mapping — expect `test_change_stream_url_writes_the_supplied_names_without_a_query` to fail.
2. In `relay_views.channel_advance_view`, pass `m3u_profile_name=None` — expect the same test to pass (it calls `_update_channel_metadata` directly) and the round-trip test in `test_relay_control_api.py` to fail. **If nothing fails**, there is no route-level pin on the new advance fields: add one to `test_relay_control_api.py` before proceeding.
3. Remove the `STREAM_NAME` line from `_try_next_stream`'s mapping — expect `test_an_automatic_failover_writes_the_new_stream_name` to fail.

- [ ] **Step 9: Re-run Set A of the census**

Expected: **Set A = 4 CODE** (`channel_service.py:911` gone).

- [ ] **Step 10: Commit**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
git add apps/proxy/relay_serializers.py apps/proxy/relay_client.py apps/proxy/relay_views.py apps/proxy/live_proxy/views.py apps/proxy/live_proxy/services/channel_service.py apps/proxy/live_proxy/input/manager.py apps/proxy/live_proxy/tests/ apps/proxy/tests/
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
git commit -F /dev/stdin <<'EOF'
relay: the switch paths carry the names too

change_stream and next_stream resolve the source in the API process and
then sent stream_name=None, because the Source contract had no such key --
their own comments said so. It does now, so they send it, along with
channel_name and m3u_profile_name, through relay_client.advance and the
advance request serializer into the metadata hash. Deletes
_update_channel_metadata's Stream.objects fallback
(services/channel_service.py:911).

Behaviour change, deliberate: _try_next_stream's post-failover metadata
write carried no STREAM_NAME at all, so after an automatic failover the
status payload kept reporting the PREVIOUS stream's name. It writes the new
one now. Adjacent to parity-matrix row 18, which 2b-3 owns; the matrix is
not touched here.

Surviving ORM sites in apps/proxy/live_proxy/**: 5 -> 4.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
EOF
```

---

## Task 5: The status endpoint prefers the stored M3U profile name

**Files:**
- Modify: `apps/proxy/live_proxy/channel_status.py` (`~:85-100`)
- Test: `apps/proxy/live_proxy/tests/test_channel_names_on_the_contract.py`

**Interfaces:**
- Consumes: `ChannelMetadataField.M3U_PROFILE_NAME` (Task 3), written at init (Task 3) and on every switch (Task 4).
- Produces: nothing new. **The ORM read at `:92` stays.** 2b-3 decides whether it is provably unreachable; this task only makes it *possible* for it to be.

Today `m3u_profile_name` has **no Redis path at all** — unlike `stream_name`, which prefers the hash, the profile name is resolved from the ORM on **every** detailed status read. This task gives it the same shape `stream_name` already has.

- [ ] **Step 1: Write the failing test**

Append to `apps/proxy/live_proxy/tests/test_channel_names_on_the_contract.py`:

```python
class StatusPrefersTheStoredProfileNameTests(RelayHarnessTestCase):
    """PIN, end to end through the relay's own HTTP surface.

    The hash is seeded with a name that DIFFERS from the row's, so a pass
    cannot come from the ORM happening to return the same string. That is
    the whole assertion: the status endpoint reads the hash, not the row.
    """

    def test_the_status_payload_reports_the_stored_profile_name(self):
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            with self.tuned(channel):
                self.redis.hset(
                    f"live:channel:{channel.uuid}:metadata",
                    ChannelMetadataField.M3U_PROFILE_NAME,
                    "name-only-in-redis",
                )
                status_code, body = self.status(channel)
            self.assertEqual(status_code, 200)
            self.assertEqual(body["m3u_profile_name"], "name-only-in-redis")
        self.stop_channel(channel)
```

Read `apps/proxy/live_proxy/tests/harness/README.md` and `harness/relay.py` before writing this — `self.redis`, `self.status`, `self.stand_in`, `self.tuned`, `self.make_channel` and `self.stop_channel` are the harness's own names and the exact spelling may differ. **Do not** import `e2e/fixtures/greybox/redis.ts`-style helpers; this is the Python harness.

If `self.status(channel)` returns the *basic* payload rather than the detailed one, use the detailed route — `GET /proxy/relay/channels/<uuid>` **without** `?fields=state` is what reaches `get_detailed_channel_info` and the two fallback reads (spec § Stage 2b, the corrected part-2 guard). Confirm which builder answers before asserting.

- [ ] **Step 2: Run it, watch it fail**

Expected failure: `m3u_profile_name` is the *database row's* name, not `"name-only-in-redis"` — because nothing reads the hash yet.

- [ ] **Step 3: Prefer the hash**

In `apps/proxy/live_proxy/channel_status.py`, inside the `if m3u_profile_id_bytes:` block, before the ORM lookup:

```python
                    stored_name = metadata.get(ChannelMetadataField.M3U_PROFILE_NAME)
                    if stored_name:
                        info['m3u_profile_name'] = (
                            stored_name.decode()
                            if isinstance(stored_name, bytes)
                            else stored_name
                        )
                    else:
                        # Phase 2 PR 2b-1 writes M3U_PROFILE_NAME at channel
                        # init and on every switch, so this branch is now a
                        # defensive read for whatever path does not (yet,
                        # provably) write one. Deliberately NOT deleted here:
                        # 2b-3 owns the question of whether it is reachable,
                        # and parity-matrix row 18 is where the answer goes.
                        try:
                            from apps.m3u.models import M3UAccountProfile
                            m3u_profile = M3UAccountProfile.objects.filter(
                                id=m3u_profile_id
                            ).first()
                            if m3u_profile:
                                info['m3u_profile_name'] = m3u_profile.name
                        except (ImportError, DatabaseError) as e:
                            logger.warning(
                                f"Failed to get M3U profile name for ID {m3u_profile_id}: {e}"
                            )
```

This mirrors the `stream_name` block immediately above it, byte-decode and all. Do not change that block.

- [ ] **Step 4: Run it, watch it pass**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test apps.proxy.live_proxy.tests.test_channel_names_on_the_contract -v2
```

- [ ] **Step 5: Break-check**

1. Delete the `if stored_name:` branch — expect the new test to fail with the row's name.
2. Change `stored_name.decode()` to `stored_name` unconditionally — expect a failure on a `b'...'` repr **if the harness's Redis returns bytes**. If it returns `str` and nothing fails, the decode is untested: say so rather than claiming it is pinned.
3. Seed the hash with an empty string instead of a name — expect the ORM branch to take over and the test to fail with the row's name, confirming the truthiness guard is load-bearing.

- [ ] **Step 6: Run the full three packages, then commit**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test apps.proxy.live_proxy.tests apps.proxy.tests apps.channels.tests -v1
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
git add apps/proxy/live_proxy/channel_status.py apps/proxy/live_proxy/tests/test_channel_names_on_the_contract.py
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
git commit -F /dev/stdin <<'EOF'
status: prefer the stored M3U profile name over the row

Unlike stream_name, m3u_profile_name had no Redis path at all -- the
detailed status payload resolved it from the ORM on every read. It now
reads the field 2b-1 writes at init and on every switch, with the existing
ORM lookup kept as the fallback.

The ORM read is deliberately NOT deleted: 2b-3 owns whether
channel_status.py:74 and :92 are provably unreachable, and parity-matrix
row 18 is where that answer goes.

Pinned end to end through the relay's HTTP surface, with a name seeded into
Redis that differs from the row's, so a pass cannot come from the two
happening to agree.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
EOF
```

---

## Task 6: The force-ffmpeg path reads the profile from the hash

**Files:**
- Modify: `apps/proxy/live_proxy/input/manager.py` (`_establish_transcode_connection`, `:730-746`)
- Test: create `apps/proxy/live_proxy/tests/test_forced_ffmpeg_profile.py`

**Interfaces:**
- Consumes: `ChannelMetadataField.FFMPEG_STREAM_PROFILE` (Tasks 3 and 4).
- Produces: nothing downstream.

**The narrow scope, stated:** this task removes **one** line — `StreamProfile.objects.get(name='ffmpeg', locked=True)`. The three ORM reads on the same seventeen lines (`get_stream_object(self.channel_id)` at `:731`, `channel.get_stream_profile()` at `:741` and `:745`) are **not** in the spec's Stage 2b table and are **not** removed here. Record that in the PR body; do not quietly fix or quietly ignore it.

- [ ] **Step 1: Write the failing test**

Create `apps/proxy/live_proxy/tests/test_forced_ffmpeg_profile.py`:

```python
"""PIN for Phase 2 PR 2b-1: the force-ffmpeg reconnect path takes its
StreamProfile from the channel metadata hash, not from a query.

Spec § Stage 2b, the input/manager.py:737 row. force_ffmpeg is set in
_run's main loop when detect_stream_type() sees an HLS, RTSP/RTP or UDP
upstream on a non-transcoding profile (input/manager.py:442-450), which is
why this test sets the flag directly rather than driving a real HLS tune:
the subject is which PROFILE the branch picks, not how the flag gets set.
"""
```

Write two tests in it:

1. **PIN** — with the hash carrying `{"id": 9, "command": "ffmpeg", "args": "-i {streamUrl} -c copy -f mpegts pipe:1"}` and `force_ffmpeg = True`, the built `transcode_cmd` starts with `ffmpeg` and contains the substituted stream URL, and `self.stream_command == "ffmpeg"`. Assert the profile came from the hash by making the hash's `command` a value that could not come from the DB (e.g. `"ffmpeg"` with `args` containing a marker token like `-metadata from_the_hash=1`) and asserting the marker is in the command.
2. **PIN** — with the hash field **absent** and `force_ffmpeg = True`, the code falls back to today's behaviour (`channel.get_stream_profile()`), i.e. a deployment mid-upgrade does not lose its forced remux.

Build the `StreamManager` the way `apps/proxy/live_proxy/tests/test_manager_connection_failover.py` and `manager_support.py` already do — read both before writing, and reuse their construction helper rather than adding a new one.

- [ ] **Step 2: Run them, watch them fail**

Expected: the first fails because the hash is ignored and the DB's profile is used (no marker in the command).

- [ ] **Step 3: Implement**

In `_establish_transcode_connection`, replace the `if hasattr(self, 'force_ffmpeg') and self.force_ffmpeg:` block:

```python
                if hasattr(self, 'force_ffmpeg') and self.force_ffmpeg:
                    stream_profile = self._stored_ffmpeg_profile()
                    if stream_profile is not None:
                        logger.info("Using FFmpeg stream profile for unsupported proxy content (HLS/RTSP/UDP)")
                    else:
                        # Pre-2b-1 Django, or no locked ffmpeg profile installed.
                        # Same fallback the StreamProfile.DoesNotExist branch used
                        # to take.
                        stream_profile = channel.get_stream_profile()
                        logger.warning(f"FFmpeg profile not found, using channel default profile for channel: {self.channel_id}")
                else:
                    stream_profile = channel.get_stream_profile()
```

and add the reader as a method on `StreamManager`:

```python
    def _stored_ffmpeg_profile(self):
        """The locked ffmpeg StreamProfile, from the metadata hash.

        Phase 2 PR 2b-1. Django resolved it while answering next-source
        (apps/proxy/next_source.py's _locked_ffmpeg_profile) and wrote it
        here; the relay no longer runs
        StreamProfile.objects.get(name='ffmpeg', locked=True) in its own
        process on the force-ffmpeg reconnect path.

        Returns an UNSAVED StreamProfile so build_command() -- which is
        model behaviour, not data -- still runs. name and locked are set so
        is_proxy()/is_redirect() answer False, which is what they answer for
        a real locked 'ffmpeg' row. It is never saved; nothing here writes.
        """
        redis_client = getattr(self.buffer, "redis_client", None)
        if not redis_client:
            return None
        try:
            raw = redis_client.hget(
                RedisKeys.channel_metadata(self.channel_id),
                ChannelMetadataField.FFMPEG_STREAM_PROFILE,
            )
            if not raw:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode()
            stored = json.loads(raw)
            from core.models import StreamProfile

            return StreamProfile(
                id=stored["id"],
                name="ffmpeg",
                locked=True,
                command=stored["command"],
                parameters=stored["args"],
            )
        except Exception as exc:
            logger.warning(
                f"Could not read the stored ffmpeg profile for channel "
                f"{self.channel_id}: {exc}"
            )
            return None
```

`RedisKeys` (`:15`) and `ChannelMetadataField` (`:16`) are already imported at the top of `input/manager.py`. **`json` is not** — add `import json` to the stdlib import block at the top (`:3-9`). Confirm before and after with `grep -n "^import json" apps/proxy/live_proxy/input/manager.py`.

- [ ] **Step 4: Run them, watch them pass**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test apps.proxy.live_proxy.tests.test_forced_ffmpeg_profile -v2
```

- [ ] **Step 5: Break-check**

1. Make `_stored_ffmpeg_profile` return `None` unconditionally — expect the marker test to fail and the fallback test to pass.
2. Set `locked=False` on the constructed profile — expect no failure (it only affects `is_proxy`/`is_redirect`, both False either way). **That is a real gap**: add a third test asserting `build_command()` returns a non-empty list for the stored profile, so a future edit that lets a Proxy/Redirect shape through this path is caught, then re-break.
3. Change `parameters=stored["args"]` to `parameters=""` — expect the marker test to fail.

- [ ] **Step 6: Run the three packages, re-run the census, commit**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test apps.proxy.live_proxy.tests apps.proxy.tests apps.channels.tests -v1
```

Expected census: **Set A = 3 CODE** (`channel_status.py:74`, `channel_status.py:92`, `views.py:152`).

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
git add apps/proxy/live_proxy/input/manager.py apps/proxy/live_proxy/tests/test_forced_ffmpeg_profile.py
```

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
git commit -F /dev/stdin <<'EOF'
relay: the force-ffmpeg path reads its profile from the hash

input/manager.py:737 ran StreamProfile.objects.get(name='ffmpeg',
locked=True) inside the relay process on the reconnect path for HLS, RTSP
and UDP upstreams. Django resolves it once per tune now and writes it into
the metadata hash; the relay rebuilds an unsaved StreamProfile from it so
build_command() -- model behaviour, not data -- still runs, and falls back
to channel.get_stream_profile() when the field is absent, which is what the
StreamProfile.DoesNotExist branch did.

NOT removed, and not in the spec's Stage 2b table: get_stream_object() at
:731 and channel.get_stream_profile() at :741/:745 are ORM reads on the
same path. The second has no `.objects.` on its line, so the static guard
2b-3 builds cannot see it at all -- only the runtime check can.

Surviving ORM sites in apps/proxy/live_proxy/**: 4 -> 3.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Pr6xFBkeJHvguMJ6PweBMu
EOF
```

---

## Task 7: Final census, the gate evidence, and the PR

**Files:**
- No production files. This task produces the PR body and verifies the whole branch.

- [ ] **Step 1: Run the final census, both sets**

Run Task 1 Step 1's command verbatim. Expected:

```
SET A: 3 CODE  (channel_status.py:74, channel_status.py:92, views.py:152)
SET B literal: 3   (unchanged)
SET B transitive: report the measured number, do not predict it
```

**Set A: 8 → 3, a measured reduction of 5.** That is this PR's gate evidence.

If Set B transitive went **up**, that is expected and is explained in § *The measurement, and the ambiguity inside it*: folding a read into `_locked_ffmpeg_profile` adds a line inside a function `resolve_source` transitively reaches. Report the number and the explanation together. Do not hide it, and do not restructure production code to flatter the metric.

- [ ] **Step 2: Run the whole backend suite the way CI does**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test -v1
```

Note (`CLAUDE.md` § Testing) that **a green full in-process run is not what CI runs** and a red one may be an order-dependence artefact. If something fails, re-run that label alone before believing it:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
python manage.py test <the.failing.label> -v2
```

- [ ] **Step 3: Check the parity-matrix guard still passes, without editing the matrix**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1/e2e
npx playwright test --project=guards 2>&1 | tail -30
```

Expected: pass. Rows 16 and 18 are untouched by this PR; row 16's pin (`test_a_stream_hash_tune_applies_no_channel_check`) must still resolve. **If the guard fails, do not fix it by editing the matrix** — find what this PR renamed or moved and put it back.

- [ ] **Step 4: Attempt the coverage gate, and record whatever it says**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
scripts/coverage_live_path.sh --gate 2>&1 | tail -25
```

Three possible outcomes, all legitimate to report:
- **Passes** — 2b-0 landed and the statement count is no longer an equality check. Record the number.
- **Refuses on `statements=` or `shape=`** — expected if 2b-0 has not landed. Record the refusal verbatim. **This is not a coverage regression and this PR does not fix it.**
- **Fails on `missing=`** — a genuine coverage regression from this PR's new production lines. Add tests for the uncovered branches (the `except` in `_stored_ffmpeg_profile`, the `_tune_extras(None)` error returns) until it passes.

- [ ] **Step 5: Write the PR body**

Write it to a file and open the PR from the file (a body containing `git commit` would trip the commit gate if pasted into a commit message; use `-F` habits here too). It must contain, at minimum:

1. **The gate evidence.** Set A 8 → 3, itemised by which task removed which line. Set B literal 3 → 3. Set B transitive, before and after, with the explanation.
2. **The spec drift**, from § *Spec `file:line` references* above — specifically that `url_utils.py:247` is the `def`, the ORM call is at `:261`, and the spec's prose § *What the code says* says `:260`.
3. **The three findings the spec's 2b table does not contain** (`get_stream_object`, `channel.get_stream_profile()`, `apps/proxy/config.py`), verbatim from this plan, addressed to 2b-3's author — because a green static guard with those three live would be a false "zero ORM reads".
4. **The two scope items that needed no production change** (`stream_hash` already accepted; `get_connections_left` had no caller), with the evidence for each.
5. **The behaviour change**: `_try_next_stream` now writes `STREAM_NAME` after an automatic failover, where before it left the previous stream's name in the hash. Name parity row 18 and say the matrix was not touched.
6. **Every break check**: which production line was broken, which test went red, and the failure message — three per PIN group.
7. **Any test that was downgraded from PIN to REACH** because its break check showed it had no teeth (Task 3 Step 9 item 2, Task 5 Step 5 item 2).
8. **The coverage-gate outcome** from Step 4, verbatim.
9. **What `proxy_settings` does not do yet**: it is on the response and in the schema, and **nothing in the Python relay reads it**. The consumer is the Go relay in 2c. Wiring `StreamManager.__init__` to prefer it would collapse the 10-second staleness window in the Python relay mid-phase — a behaviour change no 2b gate asks for, and a perturbation of the timing of the very system whose coverage measurement 2b-4 still has to close. Orchestrator ruling; see § Self-review.
10. **The advance-request ruling**, one line: the spec's "advance's responses" means the advance **request** body (`apps/proxy/relay_serializers.py:187-192`, `:202`), and the spec's wording is being corrected separately.
11. **The issue number** covering the three out-of-scope ORM findings, from § Handing the three out-of-scope ORM findings forward.

- [ ] **Step 6: Push the branch**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
git push -u origin migration/phase2b-names-and-profiles
```

The branch name starts with `migration/`, so **every** Playwright project and both bash lifecycle suites run on it (`CLAUDE.md` § Full E2E runs). Expect a long CI cycle and budget for it.

- [ ] **Step 7: Open the PR as a draft, then request review**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2-2b1
gh pr create --repo D10Scot/Dispatcharr --draft --base main \
  --title "contract(phase2): 2b-1 — names and profiles on next-source and advance" \
  --body-file <the file from Step 5>
```

**Always `--repo D10Scot/Dispatcharr`** — `gh` otherwise resolves to the upstream public tracker.

---

## Self-review against the spec

**Spec coverage, row `2b-1` of the Stage 2b PR table, item by item:**

| Spec item | Task |
|---|---|
| `channel_name`/`stream_name`/`m3u_profile_name` on `next-source`'s response | Task 2 |
| …and on `advance`'s | Task 4 (the `/proxy/relay/.../advance` **request** body — see below) |
| The locked-ffmpeg `StreamProfile` folded into `next-source` as a second key | Tasks 2 (produce) and 6 (consume) |
| `get_connections_left` deleted unless a caller surfaces | Task 1 |
| `next-source`'s identifier resolution accepts a `stream_hash` (parity row 16) | Task 2 — **already true; pinned at the route rather than changed** |
| `proxy_settings` on `next-source`'s response, channel-start-time values only | Task 2 |
| Gate: a measured reduction in surviving sites | Tasks 1 and 7 (8 → 3) |

**The spec's "advance's responses" is a slip in the spec, and the orchestrator has ruled on it — do not re-litigate this.** The spec says "Add `channel_name`/`stream_name` as non-optional fields on **both response bodies**". There are two things called "advance" and **neither response points at the relay**: `/proxy/relay/channels/<id>/advance` is a **Django→relay** call whose *request* carries the resolved source and whose *response* is the relay's own switch result, read back by Django. Putting names on that response would send them in the direction that already has an open ORM.

**Ruling: "advance" means the advance REQUEST body.** The evidence, verified against this tree at `ef3d3145`:

- `apps/proxy/relay_serializers.py:187` — `class RelayAdvanceRequestSerializer(serializers.Serializer)`.
- `apps/proxy/relay_serializers.py:188-192` — its docstring: *"`url` is required: Django resolves the candidate in the API process, where the ORM is, and the relay applies it."* That is the Django→relay direction stated by the contract itself.
- `apps/proxy/relay_serializers.py:202` — `stream_name` is **already** a field on that request serializer. The key exists; what does not exist is a producer that fills it, because the `Source` contract had no `stream_name` to fill it from.

That request body is the only direction that can close `services/channel_service.py:911`, which is the row the spec's own table assigns to this change. **The spec's wording is wrong and will be corrected separately** — do not edit the spec from this branch.

**`proxy_settings` is deliberately not consumed by the Python relay — ruled, with the reason, not just the decision.** Task 2 puts it on the response, on `ProxySettingsSerializer` and in the drf-spectacular schema, and stops there. Wiring `StreamManager.__init__` to prefer it would collapse the 10-second staleness window *in the Python relay, mid-phase*, and that is a behaviour change **no 2b gate asks for**. It is also the wrong system to change now: Gate 2's coverage measurement over these same modules is already timing-sensitive — the floor file records four regions that flap between runs, and the shape rules exist because a `gevent.sleep()` boundary decides whether a statement is counted — so altering when a running channel picks up a settings change perturbs the very measurement 2b-4 has to close. The spec's stated purpose for this field is that **the Go relay** never reads `CoreSettings`, and the Go relay is 2c's.

**Type consistency check:** `tune_extras` is spelled identically in Tasks 3, 4 and 6 and has exactly four keys in all of them. `ffmpeg_stream_profile` uses `args` (not `parameters`) on the wire in Task 2, in the hash in Task 3, and when reconstructing the model in Task 6. `ChannelMetadataField.M3U_PROFILE_NAME` and `.FFMPEG_STREAM_PROFILE` are defined once (Task 3) and referenced by those exact names in Tasks 4, 5 and 6.

---

## Handing the three out-of-scope ORM findings forward

§ *Three findings the spec's 2b table does not contain* (above) records three ORM reads that survive in the relay and that **no 2b PR removes**. The orchestrator has filed them as an issue on `D10Scot/Dispatcharr` so they cannot be lost. **Task 7's PR body must cite that issue by number.** Find it:

```bash
gh issue list --repo D10Scot/Dispatcharr --state open --search "get_stream_profile static guard blind"
```

Always with an explicit `--repo` — `gh` otherwise resolves to the upstream public tracker.

The one that matters most, and the sentence to put in the PR body verbatim:

> `channel.get_stream_profile()` at `apps/proxy/live_proxy/views.py:430` and `apps/proxy/live_proxy/input/manager.py:741`/`:745` is an ORM read with **no `.objects.` and no `get_object_or_404(` on its line**. 2b-3's part-1 static guard is structurally blind to it, so a green part-1 with this read live would be a false "zero ORM reads" — the same class of failure the spec already corrected the naive `grep -rn "\.objects\." apps/proxy/live_proxy/` for once, arriving by a different route. Only 2b-3's part-2 runtime check can see it.

If 2b-3's author reads a green static guard as "done", that is the failure this paragraph exists to prevent. Say it in the PR body; do not leave it in this plan alone.

## Adjacent claims this plan did NOT verify

Named here, deliberately, before anyone builds on them.

1. **That `resolve_source` never executes in the relay process.** Three in-process import sites were *read* (`views.py:900`, `views.py:1250`, `channel_service.py:397`) and all three look like API-process or dead code. Not executed, not instrumented. 2b-3's runtime check is what can settle it.
2. **That `channel_status.py:74`'s `stream_name` fallback is now unreachable.** Task 4 makes the automatic-failover path write a name, and Task 3 makes the init path write one, but no audit of *every* write path to the metadata hash was done — which is precisely the audit the spec refused to assert without, and this plan does not assert it either. 2b-3 owns it.
3. **That `apps/proxy/config.py`'s `get_proxy_settings` is the only remaining `CoreSettings` read on the relay's path.** Only `apps/proxy/live_proxy/**` and `next_source.py` were swept. `apps/proxy/authorize.py`, `authorize_views.py`, `utils.py` and `relay_client.py` were not.
4. **That `authorize_views.py:112-141`'s `User` read is where the spec says it is.** Not checked — 2b-2's row, deliberately left alone.
5. **That adding `_locked_ffmpeg_profile()` to every Source costs one query per tune and not more.** It is an unfiltered `.first()` on a tiny table called once per `_source_from_info` / `resolve_initial_source` — but `_resolve_alternates` calls `_source_from_info` **once per alternate**, so a channel with ten alternates and `include_alternates=True` runs it eleven times. No query count was measured. **Task 2's implementer should add `assertNumQueries` around an `include_alternates=True` resolve and report the number**; if it is unacceptable, the fix is a per-call memo on `resolve_source`, not a change to the contract.
6. **That the stage-2a harness exposes `self.redis` and a detailed-status helper under those names.** Task 5's test is written from `harness/README.md`'s examples, not from `harness/relay.py`'s source. Read the source before writing the test.
7. **That `NextSourceResolutionTests` is subclassable from a second module.** Its `setUp` was read and every fixture name confirmed (`self.stream_profile_obj`, `self.account`, `self.m3u_profile`, `self.stream_a`, `self.stream_b`, `self.channel`), but no subclass of it exists in the tree today, so "subclassing inherits all of that" is read from the source, not demonstrated. If it does not subclass cleanly, copy the `setUp` rather than refactoring it.
8. **That `scripts/coverage_live_path.sh --gate` can be run from this worktree at all.** The floor file's own instructions say to run `--gate` from the ordinary read-only test-hook container — which is shared, and which other agents may be re-pointing. Task 7 Step 4 assumes it runs; if it cannot, record that rather than a number.
9. **That the frontend consumes none of these fields.** No frontend sweep was done. `m3u_profile_name` and `stream_name` already appear on the status payload, so nothing there changes shape — but the failover-name behaviour change (Task 4) is visible in the UI, and nobody checked whether anything asserts on it.
