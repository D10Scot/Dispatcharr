# Phase 2 PR 2b-3 — the zero-ORM guard, and Gate 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-part guard — static and runtime — that makes "the relay reaches the ORM at exactly these named sites, for these written reasons" a checked fact rather than a claim, record the answer to parity-matrix row 18, and close Gate 1.

**Architecture:** Part 1 is an **AST** scanner, not a grep, because the prescribed grep fails in both directions (issue #253: it misses `channel.get_stream_profile()`, and it counts a docstring that quotes the ORM line it replaced). It scans two scopes — every non-test file under `apps/proxy/live_proxy/`, and every first-party symbol those files import in-process — for three shapes: a `.objects` attribute, a `get_object_or_404`/`get_list_or_404` call, and a call whose attribute name is a method defined on a Django model class anywhere in the tree. Part 2 is a runtime check that patches `django.db.backends.utils.CursorWrapper` at class level (global across threads, which a per-connection `CaptureQueriesContext` is not under `LiveServerTestCase`), attributes each captured query to the relay or to the control plane **by stack frame**, and drives five real requests through 2a's subprocess harness — an owner tune, a follower tune asking for a different Output Profile, an untrusted tune, and the status path read both as-tuned and with the names stripped. Both parts check against one comment-cited allowlist, `apps/proxy/live_proxy/tests/zero_orm_allowlist.py`.

**Tech Stack:** Python `ast`, Django `TestCase`/`LiveServerTestCase`, the 2a relay harness (`apps/proxy/live_proxy/tests/harness/`), real Redis, real Postgres, Playwright only for the parity-matrix guard (`e2e/tests/guards/parity-matrix.spec.ts`, Node-only, no container).

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` — § Stage 2b (lines 1595–1649), the PR table row at line 1659, parity row 18 at line 903, and 2c-1's precondition at line 1769. Supporting: `docs/relay-parity-matrix.md`, [issue #253](https://github.com/D10Scot/Dispatcharr/issues/253), and 2b-2's plan Rulings **R1**, **R1b** and **R3**.

---

## Global Constraints

Every task's requirements implicitly include this section.

1. **A pin that supplies the default pins nothing.** A test must supply a value that could not arise by accident, or it passes with the mechanism deleted. `_output_profile_for` returns `None` before touching the ORM when `decision.output_profile_id` is falsy (`views.py:149-151`), so a tune with `X-Relay-Output: ""` does **not** exercise `views.py:153` — a runtime check that omits the header proves nothing about that site. Every header, every metadata field and every allowlist fixture in this plan must carry a value the broken path could not produce.

2. **The tautological oracle.** A test whose expected value is computed by the code under test cannot fail. The allowlist's SQL signatures and its per-entry counts are **literals typed by a human reading a measurement**, never values the guard computes at run time and compares to itself. Task 2 Step 3 and Task 4 Step 4 each measure first and then write literals; neither may generate the expectation.

3. **A test can go hollow without changing.** Ask of every assertion here: *what edit to production code would make this fail?* If the answer is "none", it is not a test. This binds hardest on a guard, which is exactly the kind of test that can be green and meaningless. Every task below that adds an assertion also carries a **break-check** step: patch in the defect, watch it go red for the right reason, revert. A break-check that does not go red is a finding, not a formality — stop and fix the assertion.

4. **Owner versus follower is a systematic axis.** The relay's organising conditional. `_output_profile_for` is called at `views.py:605` on the owner's init path and at `views.py:712` on every other client; the second client on a running channel makes no `next-source` call at all (2b-2 Ruling R3). Three PRs running have had a defect hiding in one branch. The runtime check drives **both**.

5. **Zero ORM writes is already true and stays true.** Phase 1 PR 6 took non-test `apps/proxy/` to zero ORM writes. This PR must not add one, and the static scanner's shapes include `.save()`/`.delete()` by virtue of the model-method rule, so a regression would be caught.

6. **Never `2>/dev/null` a git query whose emptiness you intend to interpret, and never read `$?` through a pipe.** Use `set -o pipefail`. Brace every ref in a `git show`: `git show "${b}:path"`, never `git show "$b:path"` — zsh eats the path as a history modifier and prints the tip commit's diff instead, exit 0.

7. **Test-hook container.** Writing any `.py` fires `PostToolUse`, which runs the whole `apps.proxy.live_proxy.tests` package plus `apps.channels.tests` in the container named `dispatcharr-testrunner`, flushing shared Redis. That container's bind mount decides which tree is tested, and `DISPATCHARR_TEST_CONTAINER` does **not** reach a hook. Before the first `.py` edit, run `docker inspect dispatcharr-testrunner --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'` and re-point it at this worktree if it names another. Markdown fires no hook.

8. **Coverage Gate 2 is unaffected and must stay so.** Every file this PR creates lives under `apps/proxy/live_proxy/tests/`, which `scripts/coverage_live_path.coveragerc` omits (`omit = */tests/*`, lines 15-16 and 35-36). The floor's `modules=` hash and `statements` therefore do not move. **Do not put the scanner in a non-test module** — that would move the denominator and trip the shape guard.

9. **Stage and commit in separate Bash calls**, and pass the message with `git commit -F <file>` written by the Write tool. The `PreToolUse` gate matches on command text, so one call doing both is blocked, and a heredoc containing the words trips it too.

10. **`--repo D10Scot/Dispatcharr` on every `gh` call.** Without it `gh` resolves to the upstream public tracker.

---

## Rulings

These are decisions this plan makes. Each was reached against the tree at `93900a6f`; an implementer who disagrees should say so with `file:line` evidence rather than quietly diverging.

### R1 — The static half cannot prove zero ORM reads, and says so in its own docstring.

Issue #253 records the shape that defeats it: `channel.get_stream_profile()` performs one-to-several queries (`apps/channels/models.py:467`, plus an FK accessor) behind a call site containing neither `.objects.` nor `get_object_or_404(`. This plan's scanner *does* catch that specific shape — see R2 — but the general class it belongs to is unbounded, and three residuals survive by construction:

- **Descriptor and property access.** `stream.m3u_account`, `channel.effective_stream_profile_obj`: a query with no call syntax at all. The scanner flags calls, not attribute loads, because flagging attribute loads means flagging `.name` and `.id` and drowning the signal.
- **Dynamic dispatch.** `getattr(obj, name)()`, a dict of handlers, anything resolved at run time.
- **Depth.** The scanner follows one import hop out of `live_proxy/**` and is transitive only *within* the module it lands in (R3). An ORM read three first-party modules away is invisible.

So part 1's job is narrowed and stated plainly: **it is a ratchet against new textual ORM sites and new import edges, made accurate enough not to be defeated by a docstring, and it is not evidence that the relay makes no query.** That sentence, and the three residuals above, go verbatim into `zero_orm_scan.py`'s module docstring. Part 2 carries the proof. A green part 1 alone must never be reported as "zero ORM reads".

### R2 — The scanner's third shape is a model-method **name** set, and it is measured, not guessed.

Build the set by AST-parsing every `models.py` in the repo, collecting the non-dunder method names of every class whose bases mention `Model`. Measured at `93900a6f`: **94 names**. A call `x.foo()` where `foo` is in that set is flagged.

This is name-based, not type-based, so it over- and under-counts in known ways:

- It **catches** `get_stream_profile` (all three #253 sites), `get_proxy_settings`, `get_default_output_format`, `release_stream`, `update_stream_profile`, `get_user_agent_string` — every ORM-reaching model method the relay calls, regardless of what the call line looks like. This is the #253 fix.
- It **over-counts** a same-named method on a non-model object. Measured: exactly one such name, `update`, with 8 hits, all `dict.update()`. It goes in a **stoplist**, `_NAMES_TOO_GENERIC`, which must stay short and carry a per-entry comment. `save` and `delete` deliberately stay in the set (Global Constraint 5).
- It **does not** over-count docstrings, because `ast` sees a docstring as `ast.Constant` and never as an `ast.Attribute`. This is the fix for #253's second reported shape, and Task 1 pins it with a synthetic source.

### R3 — Two scopes, two allowlist granularities.

**Scope 1 — `live_proxy/**`, excluding `**/tests/**`.** Per-**line** entries: an exact `file:line`. Precise, and the ratchet bites on any new one. Measured at `93900a6f`: 20 hits, of which 8 are `dict.update()` (stoplist) leaving **12** to account for.

**Scope 2 — the in-process import edges out of scope 1.** Collected by AST from scope 1's `ImportFrom` nodes (module-level and function-local alike), restricted to first-party roots (`apps.`, `core.`, `dispatcharr.`), **excluding any `*/models.py`** — a model module *is* the ORM, and scanning it as "relay code" would flag the entire tree and say nothing. Measured at `93900a6f`, twelve modules import into the relay; after dropping the two `models.py` modules and `core.models`, eight remain, and their imported symbols' reachable subtrees hold **42** hits.

Entries here are per-**edge**, not per-line: one entry per `(importing file, module, symbol)`, clearing that symbol's whole reachable subtree with one reason. Per-line would put 34 lines of `next_source.py` in the file to say one thing.

**The edge entry carries a count, and the count is the ratchet.** An entry records the number of hits in the cleared subtree (`resolve_source: 34`). A change in either direction fails the guard: an ORM read added inside a cleared subtree, or removed by 2c/2d, forces a re-read and a deliberate edit. This is unlike Gate 2's `statements` figure, which CLAUDE.md records as a latent bug precisely because it moves on ordinary code edits; this count moves only when ORM usage changes, which is exactly when someone should look. Say that trade-off in the allowlist's own docstring.

**What edge granularity tolerates, stated honestly:** a new ORM read added inside an already-cleared symbol's subtree is caught by the count but not named. The count says "look"; it does not say where. That is the cost, and it is worth it.

### R4 — Reachability within a module is transitive; reachability across modules is not.

Inside a scope-2 module, follow calls to other names defined in the same module, transitively. That is cheap, exact (same-module name resolution needs no type inference), and it is what makes `resolve_source` → `_source_from_info` → `StreamProfile.objects.get` visible. Across modules, stop. R1's third residual is this rule's cost.

### R5 — The runtime half instruments the cursor class, not a connection.

`CaptureQueriesContext(connection)` binds to `django.db.connections[...]` for the **calling thread**. `RelayHarnessTestCase` is a `LiveServerTestCase`: the relay's code runs on the WSGI server's threads, not the test's. A `CaptureQueriesContext` in the test body would capture nothing from a tune and pass vacuously — the exact failure mode 2b-2 guarded against with its `assertEqual(user_table, "accounts_user")` line, arriving from a different direction.

So: patch `django.db.backends.utils.CursorWrapper.execute` and `.executemany` at **class level**, under a `threading.Lock`, for the duration of the block. That is process-global and sees every thread.

2b-2's two `CaptureQueriesContext` tests (`test_stream_ts_client_registration.py:504-615`) stay exactly as they are — they call `views.stream_ts` directly on the test thread, where a per-connection context is correct, and they are a *unit* pin on one table. They are not generalised; they are cited from this guard's docstring as the narrower, faster check they are.

### R6 — A captured query is attributed to the relay by **stack frame**, and the harness makes this necessary.

The harness runs one process serving both planes: the relay's `stream_ts` calls `control_plane.next_source()`, which makes a real HTTP request back to the same server, where Django's `/api/relay/…` view runs `next_source.resolve_source()` and issues a dozen perfectly legitimate control-plane queries. Counting those as relay ORM reads would make the guard permanently red for the wrong reason.

The HTTP boundary breaks the Python stack, and that is the discriminator. **A query is attributed to the relay iff its stack contains a frame whose file is under `apps/proxy/live_proxy/` and not under a `tests/` directory.** The control-plane view's stack is WSGI handler → view → `next_source`, with no `live_proxy` frame. The relay's in-process call into `next_source.get_stream_object` has `live_proxy/url_utils.py` in its stack. Exact, cheap, and no configuration.

**Consequence the implementer must honour:** the runtime check drives **trusted** tunes only — `X-Dispatcharr-Authorized` plus the `X-Relay-*` headers, as `harness/control.py` documents. An untrusted tune runs `authorize_stream` inline from a `live_proxy` frame, which would be attributed to the relay; in production nginx runs that hop in the API process, so attributing it to the relay would be wrong. Trusted is also the production shape, so this is not a concession.

### R7 — Row 18's answer: **absence is the contract.**

The question the matrix asks is what `stream_name`/`m3u_profile_name` contain when the metadata hash was never written one. The answer, with its evidence:

**The key is absent from the payload entirely — not `null`, not `''`, not the id.** `channel_status.py` only ever assigns `info['stream_name']` inside `if stream_name:` (`:64-70`) or `if stream:` (`:73-76`), and `info['m3u_profile_name']` inside `if stored_name:` (`:90-96`) or `if m3u_profile:` (`:105-110`). `RelayChannelDetailSerializer` declares both `required=False` (`apps/proxy/relay_serializers.py:111`, `:113`) and DRF drops an absent source key rather than emitting a null — which is the same behaviour CLAUDE.md already records for `total_bytes`, `avg_bitrate_kbps` and `stream_id` ("can be **absent entirely** (not null), which the DRF serializer preserves deliberately").

So the ORM fallback is **best-effort enrichment on top of a contract that already permits absence**: it fills the key when the row still exists, and leaves it absent when the row is gone. The Go relay, having no database, always leaves it absent. That is inside the contract, not a divergence from it.

**2c is held to: omit the key. Never substitute `null`, `''` or the numeric id.** That is the sentence that goes in the matrix row.

**And the fallbacks are reachable, so they are allowlisted, not deleted.** The spec was right to refuse the confident deletion. Every name write in the tree is guarded by a truthiness test on a value that arrives from Django (`services/channel_service.py:303-308`, `:364-369`, `:931-939`; `input/manager.py:2175-2178`), and `url_utils.py:31-42`'s `tune_extras` exists precisely to degrade all four names to `None` when the answer comes from a Django that predates 2b-1 — the relay and the control plane are separately deployable processes, so a version-skewed deployment is a supported state, not a bug. 2b-1's own author wrote this down at `apps/proxy/live_proxy/views.py:553-566`: *"a pre-2b-1 Django … or any other cause of a None here writes no STREAM_NAME into the metadata hash at init. Not unrecoverable — `channel_status.py:74`'s ORM-by-stream_id fallback … repairs it on every status poll."* The same holds for `m3u_profile_name`, whose carriers are `required=False` on `RelayAdvanceRequestSerializer` (`:202-211`) and absent from `_CACHED_ALTERNATE_REQUIRED_FIELDS` (`input/manager.py:2016-2019`), so the degraded-failover path can write `M3U_PROFILE` from a stale cache entry with no name beside it.

Under a same-version deployment both fallbacks are dead. That is a property of a deployment, not of the code, and it is not a thing a guard can assert.

**One production path makes the fallback *not* the repair, and it is filed as [#265](https://github.com/D10Scot/Dispatcharr/issues/265).** A degraded failover onto a cached candidate carrying no names writes the new id and leaves the old name standing — `hset(mapping=...)` merges, the id is unconditional and the name is not (`input/manager.py:2160-2178`, and identically `channel_service.py:931-939`), and `_CACHED_ALTERNATE_REQUIRED_FIELDS` (`:2016-2019`) permits a nameless candidate. The key is then **present and wrong**, so no fallback fires and nothing warns. That is a different failure from row 18's — absence is contractual and self-describing, a stale name is a confident wrong answer — and its fix is an `hdel` at the relay's own switch call sites, the relay-internal class D10 keeps out of this stage. 2b-3 cites it and does not fix it.

**Why coverage reads this the wrong way round, measured.** A parallel measurement over 13 rounds at `93900a6f` found `:72-78` (the `Stream` fallback) missing in all 13 and `:103-110` (the `M3UAccountProfile` fallback) covered in all 13, which reads as an asymmetry in the code. It is an artifact of exactly one fixture. `apps/proxy/live_proxy/tests/test_live_db_cleanup.py:322-344` hand-builds a metadata dict with `stream_name` present and `m3u_profile` present with no name beside it, so it skips one branch and enters the other. Worse, that test is about `close_old_connections`: it asserts `info["stream_name"] == "Backup Feed"`, which comes from **Redis**, and `mock_close.assert_called_once()`. `M3UAccountProfile.objects.filter` is **mocked**, and the fallback's own result is **never asserted**. So `:103-110`'s coverage carries no information about production reachability, and `:72-78`'s absence of coverage is a suite gap rather than evidence of anything. **Reachable but untested, and tested without an oracle** — Task 5's fixtures are what close both, against real Postgres through the harness.

**Two things this ruling does not claim.** It does not claim to have enumerated every write path — it names four and the deployment condition that defeats all of them, which is enough to refuse the deletion, and the refusal is the decision. And it does not claim the fallback ever fires in the harness; Task 5 measures that, and R8 says what to do with either answer.

### R8 — A row-18 pin is a fixture, not a hope.

The reachability question above is about deployments; the *behaviour* question is answerable directly and must be pinned by construction: write a metadata hash carrying `stream_id` and no `stream_name`, read the status endpoint, assert what comes back. That test fails if anyone changes the fallback, deletes it, or makes it emit a null — regardless of whether any production path reaches it. It is the row's pin. Task 5 Step 2 writes it.

### R9 — `views.py:153` stays, and the reason is transcribed, not re-derived.

2b-2's Ruling R3 settled this and wrote the reconciliation paragraph for exactly this allowlist entry. Copy it verbatim (it is reproduced in Task 2 Step 4, from `docs/superpowers/plans/2026-09-12-phase2-2b2-output-profile-and-user.md:104` on branch `migration/phase2b-output-profile-and-user`). Do not paraphrase it: spec line 1769 makes 2c-1 restate it, and it is written once.

### R10 — The spec and the matrix are both wrong about one line number, and this PR fixes them.

Both cite `channel_status.py:92` for the `M3UAccountProfile` fallback. At `93900a6f` it is at **`:106`** — 2b-1 inserted a seven-line comment above it. The brief that commissioned this plan already says `:106`. `parity-matrix.spec.ts`'s check 3 only verifies that a cited line *exists* in the file, so `:92` resolves and the drift is silent. Fix the matrix row (Task 6) and leave the spec's prose alone except where Task 6 Step 2 amends it, in the idiom of `2fc5b269`.

---

## File Structure

**Created**

| File | Responsibility |
|---|---|
| `apps/proxy/live_proxy/tests/zero_orm_scan.py` | The AST scanner. Pure Python, no Django import, no I/O beyond reading source files. Exports `model_method_names()`, `scan_relay_package()`, `import_edges()`, `scan_edge()`, and the `Hit` record. Its docstring carries R1's three residuals. |
| `apps/proxy/live_proxy/tests/zero_orm_allowlist.py` | The data. `SITES` (scope-1, per-line) and `EDGES` (scope-2, per-edge with a count), each entry naming the site, the PR that left it, the reason, and per spec line 1769 the contract field that closes it or why the Go relay never asks. Also `SQL_SIGNATURES`, the runtime half's literals. |
| `apps/proxy/live_proxy/tests/harness/queries.py` | `capture_queries()` — the class-level `CursorWrapper` patch, the stack attribution of R6, and `assert_relay_queries_allowlisted()`. |
| `apps/proxy/live_proxy/tests/test_zero_orm_scan.py` | Tests **of the scanner**, against synthetic sources. Where the #253 shapes are pinned. |
| `apps/proxy/live_proxy/tests/test_zero_orm_reads.py` | The guard itself — part 1 (fast, `SimpleTestCase`) and part 2 (harness, `RelayHarnessTestCase`). The spec names this file. |

**Modified**

| File | Change |
|---|---|
| `docs/relay-parity-matrix.md` | Row 18: the `owed: 2b-3` pin becomes the two test references; the `Source` cell's `:92` becomes `:106`; the `Notes` cell records R7's answer. |
| `e2e/tests/guards/parity-matrix.ts` | `GATE_1_CLOSED` `false` → `true`. One line. |
| `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` | An inline bold amendment recording R7 and R1, in `2fc5b269`'s idiom. |
| `CLAUDE.md` | Two sentences: the guard exists, and what it does not prove. |
| `apps/proxy/live_proxy/tests/test_live_db_cleanup.py` | Task 5 Step 3b: fix `MagicMock(name=...)` at `:338-340` and add the assertion whose absence hid it. The only pre-existing test that executes either fallback, and it asserts nothing about them. |

**Not modified, deliberately:** `apps/proxy/live_proxy/channel_status.py`. Nothing is deleted from it (R7); the one production path that defeats its fallback is filed as [#265](https://github.com/D10Scot/Dispatcharr/issues/265) and fixed at the relay's own switch call sites, not here. `apps/proxy/live_proxy/tests/test_stream_ts_client_registration.py`'s two `CaptureQueriesContext` tests (R5).

---

## Task 1: The AST scanner and its own tests

**Files:**
- Create: `apps/proxy/live_proxy/tests/zero_orm_scan.py`
- Test: `apps/proxy/live_proxy/tests/test_zero_orm_scan.py`

**Interfaces:**
- Produces, for Tasks 2 and 4:
  - `Hit = namedtuple("Hit", "path lineno symbol shape")` — `path` repo-relative, `shape` one of `"objects"`, `"shortcut"`, `"model_method"`, `symbol` the model-method name for `"model_method"` and `""` otherwise.
  - `model_method_names() -> dict[str, list[str]]` — name → `["core/models.py:StreamProfile", …]`.
  - `scan_relay_package() -> list[Hit]` — scope 1.
  - `import_edges() -> list[Edge]` where `Edge = namedtuple("Edge", "importer module name")`, `importer` repo-relative.
  - `scan_edge(edge) -> list[Hit]` — scope 2, one edge's reachable subtree.
  - `REPO_ROOT: pathlib.Path`, `_NAMES_TOO_GENERIC: frozenset[str]`.
- Consumes: nothing.

- [ ] **Step 1: Write the failing tests for the two #253 shapes**

These are the whole reason the scanner is an AST scanner. Both use synthetic source so the pin cannot rot when the tree moves.

```python
"""Tests of the zero-ORM scanner itself.

The guard in test_zero_orm_reads.py is only as good as this file. Issue
#253 records that the spec's prescribed grep fails in BOTH directions --
it misses a real read behind a method call, and it counts a docstring
that quotes the ORM line it replaced. Each direction is pinned here on a
synthetic source, so the pin survives the tree moving underneath it.
"""

import textwrap
from django.test import SimpleTestCase

from . import zero_orm_scan


class ScannerShapeTests(SimpleTestCase):
    def _scan(self, source, path="apps/proxy/live_proxy/fake.py"):
        return zero_orm_scan.scan_source(
            textwrap.dedent(source), path, zero_orm_scan.model_method_names()
        )

    def test_a_model_method_call_is_seen_though_its_call_line_names_no_orm(self):
        """Issue #253's under-count: the shape a grep cannot see.

        get_stream_profile is defined on apps/channels/models.py's Channel
        and Stream and reaches StreamProfile.objects.get (models.py:467).
        Its call line contains neither `.objects.` nor `get_object_or_404(`.
        """
        hits = self._scan(
            """
            def tune(channel):
                return channel.get_stream_profile()
            """
        )
        self.assertEqual(
            [(h.lineno, h.shape, h.symbol) for h in hits],
            [(3, "model_method", "get_stream_profile")],
        )

    def test_a_docstring_quoting_an_orm_line_is_not_a_hit(self):
        """Issue #253's over-count, and the more insidious of the two.

        The cheapest way to silence a line-based grep here is to stop
        quoting the old code in the docstring -- making the codebase less
        legible to satisfy a check. `ast` sees a docstring as a Constant
        and never as an Attribute, so the shape simply does not arise.
        """
        hits = self._scan(
            '''
            def resolve(identifier):
                """Phase 1 PR 6 moved this.

                Was: StreamProfile.objects.get(name="ffmpeg", locked=True)
                and get_object_or_404(Stream.objects.all(), pk=identifier).
                """
                return None
            '''
        )
        self.assertEqual(hits, [])

    def test_a_real_objects_attribute_is_a_hit_in_the_same_file(self):
        """The discriminating half of the test above.

        Without this, `test_a_docstring...` passes with a scanner that
        sees nothing at all -- Global Constraint 3.
        """
        hits = self._scan(
            """
            from apps.channels.models import Stream

            def resolve(pk):
                return Stream.objects.filter(id=pk).first()
            """
        )
        self.assertEqual([(h.lineno, h.shape) for h in hits], [(5, "objects")])

    def test_get_object_or_404_is_a_hit(self):
        hits = self._scan(
            """
            def resolve(pk):
                return get_object_or_404(Channel, pk=pk)
            """
        )
        self.assertEqual([(h.lineno, h.shape) for h in hits], [(3, "shortcut")])

    def test_a_stoplisted_name_is_not_a_hit(self):
        """`update` is a StreamProfile method name AND dict.update.

        Measured at 93900a6f: 8 hits in live_proxy, all dict.update().
        The stoplist is how the model-method rule stays usable; this test
        is what stops it growing silently.
        """
        self.assertIn("update", zero_orm_scan.model_method_names())
        hits = self._scan(
            """
            def build(mapping, extra):
                mapping.update(extra)
                return mapping
            """
        )
        self.assertEqual(hits, [])
        self.assertEqual(
            sorted(zero_orm_scan._NAMES_TOO_GENERIC),
            ["update"],
            "the stoplist grew -- every entry costs the guard a shape it "
            "can no longer see, so each needs its own comment and this "
            "assertion updated deliberately",
        )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python manage.py test apps.proxy.live_proxy.tests.test_zero_orm_scan -v 2`
Expected: FAIL — `ImportError` / `ModuleNotFoundError: apps.proxy.live_proxy.tests.zero_orm_scan`.

- [ ] **Step 3: Write the scanner**

```python
"""An AST scan for ORM reads reachable from the relay, in two scopes.

WHAT THIS PROVES, AND WHAT IT DOES NOT (Ruling R1, plan 2b-3).

This is a ratchet against new textual ORM sites and new in-process import
edges out of the relay package. It is NOT evidence that the relay makes
no database query, and a green run must never be reported as one. The
runtime half of the guard (test_zero_orm_reads.py, part 2) carries that
proof.

Three classes are invisible here, by construction:

  1. Descriptor and property access. `stream.m3u_account` and
     `channel.effective_stream_profile_obj` are queries with no call
     syntax. Flagging attribute LOADS would mean flagging `.name` and
     `.id` and drowning the signal, so only CALLS are flagged.
  2. Dynamic dispatch -- getattr(obj, name)(), a handler dict, anything
     resolved at run time.
  3. Depth. One import hop out of live_proxy/**, transitive only WITHIN
     the module landed in (Ruling R4). An ORM read three first-party
     modules away is not seen.

Why AST and not the grep the spec first prescribed: issue #253 records
that the grep fails in both directions. It misses
`channel.get_stream_profile()` -- a real read whose call line names no
ORM -- and it counts a docstring that quotes the ORM line it replaced,
whose cheapest fix is to delete honest documentation. Both are pinned in
test_zero_orm_scan.py.
"""

import ast
import pathlib
from collections import namedtuple

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
RELAY_PACKAGE = REPO_ROOT / "apps" / "proxy" / "live_proxy"

Hit = namedtuple("Hit", "path lineno symbol shape")
Edge = namedtuple("Edge", "importer module name")

_SHORTCUTS = frozenset({"get_object_or_404", "get_list_or_404"})

# Names defined on a Django model that also name a common non-model
# method. Every entry costs the scanner a shape it can no longer see, so
# each needs its own comment and test_zero_orm_scan.py's assertion
# updated deliberately.
_NAMES_TOO_GENERIC = frozenset({
    # StreamProfile.update, and dict.update -- 8 hits in live_proxy at
    # 93900a6f, every one of them a dict.
    "update",
})

# First-party import roots worth following out of the relay package.
_FIRST_PARTY = ("apps.", "core.", "dispatcharr.")


def _is_test_path(path):
    return "tests" in pathlib.Path(path).parts


def model_method_names():
    """name -> ["core/models.py:StreamProfile", ...] for every method
    defined on a class whose bases mention Model. 94 names at 93900a6f."""
    names = {}
    for path in REPO_ROOT.rglob("models.py"):
        rel = str(path.relative_to(REPO_ROOT))
        if rel.startswith((".git", "node_modules")) or "/migrations/" in rel:
            continue
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any("Model" in ast.unparse(b) for b in node.bases):
                continue
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("__"):
                        continue
                    names.setdefault(item.name, []).append(f"{rel}:{node.name}")
    return names


def _hits_in(node, path, methods):
    hits = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr == "objects":
            hits.append(Hit(path, sub.lineno, "", "objects"))
        elif isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name) and func.id in _SHORTCUTS:
                hits.append(Hit(path, sub.lineno, func.id, "shortcut"))
            elif isinstance(func, ast.Attribute):
                name = func.attr
                if name in methods and name not in _NAMES_TOO_GENERIC:
                    hits.append(Hit(path, sub.lineno, name, "model_method"))
    return sorted(set(hits))


def scan_source(source, path, methods):
    return _hits_in(ast.parse(source), path, methods)


def _relay_files():
    return sorted(
        p for p in RELAY_PACKAGE.rglob("*.py")
        if not _is_test_path(p.relative_to(REPO_ROOT))
    )


def scan_relay_package():
    """Scope 1: every non-test file under apps/proxy/live_proxy/."""
    methods = model_method_names()
    hits = []
    for path in _relay_files():
        rel = str(path.relative_to(REPO_ROOT))
        hits.extend(scan_source(path.read_text(), rel, methods))
    return sorted(hits)


def import_edges():
    """Scope 2: every first-party symbol scope 1 imports in-process.

    Module-level and function-local imports alike -- ast.walk sees both,
    and this tree has 602 function-local imports, so restricting to
    module level would miss most of them. `*/models.py` is excluded: a
    model module IS the ORM, and scanning one as relay code would flag
    the whole tree and say nothing (Ruling R3).
    """
    edges = []
    for path in _relay_files():
        rel = str(path.relative_to(REPO_ROOT))
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                continue
            module = node.module
            if not module.startswith(_FIRST_PARTY):
                continue
            if module.startswith("apps.proxy.live_proxy"):
                continue
            if module.endswith(".models"):
                continue
            for alias in node.names:
                edges.append(Edge(rel, module, alias.name))
    return sorted(set(edges))


def scan_edge(edge):
    """Scope 2, one edge: the symbol's reachable subtree in its module.

    Transitive within the module only (Ruling R4): same-module name
    resolution needs no type inference and is exact, and it is what
    makes resolve_source -> _source_from_info ->
    StreamProfile.objects.get visible.
    """
    path = REPO_ROOT / (edge.module.replace(".", "/") + ".py")
    if not path.exists():
        return []
    rel = str(path.relative_to(REPO_ROOT))
    tree = ast.parse(path.read_text())
    defs = {
        n.name: n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    if edge.name not in defs:
        return []
    methods = model_method_names()
    seen, queue = set(), [edge.name]
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        for sub in ast.walk(defs[name]):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            target = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else None
            )
            if target in defs and target not in seen:
                queue.append(target)
    hits = []
    for name in sorted(seen):
        hits.extend(_hits_in(defs[name], rel, methods))
    return sorted(set(hits))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python manage.py test apps.proxy.live_proxy.tests.test_zero_orm_scan -v 2`
Expected: PASS, 5 tests.

- [ ] **Step 5: Break-check the scanner**

Not a formality — a scanner that returns `[]` for everything passes three of the five tests above. In a scratch checkout of the file (`cp`, edit, run, restore; do **not** commit):

1. Change `_hits_in`'s model-method branch to `if False:`. Expected: `test_a_model_method_call_is_seen…` fails; the docstring test still passes, which is exactly why the third test exists.
2. Change `sub.attr == "objects"` to `sub.attr == "nonesuch"`. Expected: `test_a_real_objects_attribute_is_a_hit…` fails.
3. Add `"get_stream_profile"` to `_NAMES_TOO_GENERIC`. Expected: two tests fail — the #253 pin **and** the stoplist assertion, which is the stoplist's whole point.

Restore the file after each. If any of the three does not go red, the assertion is hollow — fix it before continuing.

- [ ] **Step 6: Commit**

```bash
git add apps/proxy/live_proxy/tests/zero_orm_scan.py apps/proxy/live_proxy/tests/test_zero_orm_scan.py
```

Then, in a separate call, with the message written to a file first:

```bash
git commit -F /private/tmp/.../msg-task1.txt
```

Message:

```
test(phase2): an AST scanner for ORM reads reachable from the relay (2b-3 task 1)

The spec prescribed a grep. Issue #253 records that a grep fails in both
directions: it misses channel.get_stream_profile(), whose call line names
no ORM and which reaches StreamProfile.objects.get, and it counts a
docstring that quotes the ORM line it replaced -- whose cheapest fix is
deleting honest documentation. ast sees neither shape the way a line
does. Both are pinned on synthetic sources.

Ruling R1 is in the module docstring: this is a ratchet, not a proof.
Three classes stay invisible -- descriptor access, dynamic dispatch, and
anything more than one import hop out of the package.
```

---

## Task 2: The allowlist, and part 1 of the guard

**Files:**
- Create: `apps/proxy/live_proxy/tests/zero_orm_allowlist.py`
- Create: `apps/proxy/live_proxy/tests/test_zero_orm_reads.py` (part 1 only; Task 4 adds part 2)

**Interfaces:**
- Consumes: everything Task 1 produces.
- Produces, for Task 4: `SITES`, `EDGES`, `SQL_SIGNATURES`, and `Site`/`EdgeEntry`/`Signature` records.

- [ ] **Step 1: Write the failing guard test**

```python
"""The relay reaches the ORM at exactly these sites, for these reasons.

TWO PARTS, AND ONLY ONE OF THEM PROVES ANYTHING (plan 2b-3, Ruling R1).

Part 1 is static. It is a ratchet against a NEW textual ORM site inside
apps/proxy/live_proxy/**, and against a NEW in-process import edge out of
that package. A green part 1 does not establish that the relay makes no
query: it cannot see a property that queries, a getattr dispatch, or an
ORM read more than one import hop away. See zero_orm_scan.py's docstring.

Part 2 is runtime, and it is the one that proves the property. It drives
five real drives through 2a's
subprocess harness with every SQL statement recorded, and holds what the
relay executed against the same allowlist.

Both hold against zero_orm_allowlist.py. An empty allowlist is the best
outcome and is NOT the gate (spec line 1659): an honestly-cited entry is
a recorded fact for whoever next touches the file, and deleting a read
this PR is not scoped to remove would be worse.

Narrower, faster relatives that stay as they are:
test_stream_ts_client_registration.py's TrustedTuneQueriesNoUserRowTests
pins one table on the test thread with CaptureQueriesContext, which is
correct there and wrong here (Ruling R5).
"""

from django.test import SimpleTestCase

from . import zero_orm_allowlist as allowlist
from . import zero_orm_scan


class StaticScopeOneTests(SimpleTestCase):
    def test_every_orm_site_in_the_relay_package_is_allowlisted(self):
        found = {(h.path, h.lineno) for h in zero_orm_scan.scan_relay_package()}
        allowed = {(s.path, s.lineno) for s in allowlist.SITES}
        self.assertEqual(
            found,
            allowed,
            "\nunlisted (add to SITES with a reason, or remove the read):\n  "
            + "\n  ".join(sorted(f"{p}:{n}" for p, n in found - allowed))
            + "\nlisted but gone (delete the entry -- the ratchet runs both "
            "ways, and a stale entry is how an allowlist stops meaning "
            "anything):\n  "
            + "\n  ".join(sorted(f"{p}:{n}" for p, n in allowed - found)),
        )

    def test_the_scanner_sees_something(self):
        """Vacuous-pass guard, in 2b-2's idiom.

        assertEqual(set(), set()) passes. If SITES is ever legitimately
        empty AND the scanner is broken, the test above is green and
        proves nothing. This one fails loudly in that state, so an empty
        allowlist has to be argued for rather than arrived at.
        """
        self.assertNotEqual(
            zero_orm_scan.scan_relay_package(),
            [],
            "the scanner found no ORM site anywhere in the relay package. "
            "Either 2c/2d finished the job -- in which case delete this "
            "test in the same diff and say so -- or the scanner is broken.",
        )


class StaticScopeTwoTests(SimpleTestCase):
    def test_every_in_process_import_edge_is_allowlisted(self):
        found = {(e.importer, e.module, e.name) for e in zero_orm_scan.import_edges()
                 if zero_orm_scan.scan_edge(e)}
        allowed = {(e.importer, e.module, e.name) for e in allowlist.EDGES}
        self.assertEqual(found, allowed)

    def test_every_edge_carries_the_hit_count_it_actually_clears(self):
        """The count is the ratchet for a cleared subtree (Ruling R3).

        Per-line entries here would put 34 lines of next_source.py in the
        allowlist to say one thing. The count moves only when ORM usage
        inside the subtree changes -- which is exactly when someone
        should look -- unlike Gate 2's `statements` figure, which moves
        on any code edit and is a latent bug for that reason.
        """
        for entry in allowlist.EDGES:
            edge = zero_orm_scan.Edge(entry.importer, entry.module, entry.name)
            self.assertEqual(
                len(zero_orm_scan.scan_edge(edge)),
                entry.hits,
                f"{entry.module}.{entry.name} now holds a different number "
                f"of ORM sites than when it was cleared. Re-read the "
                f"subtree, then update the count and the reason together.",
            )


class AllowlistShapeTests(SimpleTestCase):
    def test_every_entry_states_what_closes_it(self):
        """Spec line 1769 makes 2c-1's precondition depend on this.

        2c-1's description must name, for every entry, either the
        contract field that closes it or the written reason the Go relay
        never asks that question. An entry with an empty `closed_by` is
        an entry 2c-1 cannot honour.
        """
        for entry in list(allowlist.SITES) + list(allowlist.EDGES):
            with self.subTest(entry=entry):
                self.assertTrue(entry.reason.strip())
                self.assertTrue(entry.closed_by.strip())
                self.assertRegex(entry.pr, r"^(Phase 1 PR \d|2[abc]-\d)$")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python manage.py test apps.proxy.live_proxy.tests.test_zero_orm_reads -v 2`
Expected: FAIL — `ModuleNotFoundError: … zero_orm_allowlist`.

- [ ] **Step 3: Measure, before writing a single entry**

Global Constraint 2: the allowlist's contents are literals a human types after reading a measurement. Do not generate them.

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/<yours>
python - <<'PY'
from apps.proxy.live_proxy.tests import zero_orm_scan as s
for h in s.scan_relay_package():
    print(f"SITE  {h.path}:{h.lineno}  {h.shape} {h.symbol}")
for e in s.import_edges():
    hits = s.scan_edge(e)
    if hits:
        print(f"EDGE  {e.importer} <- {e.module}.{e.name}  hits={len(hits)}")
PY
```

(Run it with `DJANGO_SETTINGS_MODULE` unset — `zero_orm_scan` imports no Django. If the import machinery objects, run the same body as a standalone script with `sys.path` set to the repo root.)

Measured at `93900a6f`, for comparison — **if your numbers differ, the tree moved and yours are right; re-read before assuming a bug**:

- Scope 1: 12 sites after the stoplist (`channel_status.py:74`, `:106`; `views.py:134`, `:153`, `:434`, `:452`, `:458`, `:750`; `input/manager.py:785`, `:788`, `:791`; `config_helper.py:50`).
- Scope 2: 8 edges with hits, 42 hits total, 34 of them under `next_source.resolve_source`.

- [ ] **Step 4: Write the allowlist**

Each entry's `reason` is the sentence a reviewer needs; each `closed_by` is what spec line 1769 makes 2c-1 restate. Two entries below are transcriptions and must not be paraphrased.

```python
"""Every ORM read reachable from the relay, and exactly why each is here.

An empty allowlist is the target and is NOT the gate (spec line 1659).
A non-empty, comment-cited one passes: the alternative is deleting reads
this PR is not scoped to remove, which is how a guard turns an open
question into a settled-looking answer.

TWO GRANULARITIES, and the reason is in plan 2b-3's Ruling R3.

  SITES  -- scope 1, per line, inside apps/proxy/live_proxy/**. Precise;
            the ratchet bites on any new one, in either direction.
  EDGES  -- scope 2, per in-process import edge out of the package. One
            entry clears a symbol's whole reachable subtree, because
            per-line would put 34 lines of next_source.py here to say
            one thing. The `hits` count is the ratchet in its place: it
            moves only when ORM usage inside the subtree changes.

WHAT EDGE GRANULARITY TOLERATES, said plainly: an ORM read added inside
an already-cleared subtree is caught by the count but not named. The
count says "look"; it does not say where.

`closed_by` is load-bearing beyond this PR. Spec line 1769 makes 2c-1's
precondition "for every entry, name either the contract field that
closes it or the written reason the Go relay never asks that question".
That is this field, and AllowlistShapeTests asserts it is non-empty.
"""

from collections import namedtuple

Site = namedtuple("Site", "path lineno pr reason closed_by")
EdgeEntry = namedtuple("EdgeEntry", "importer module name hits pr reason closed_by")
Signature = namedtuple("Signature", "name sql_fragment table_model exercised_by reason")

SITES = (
    Site(
        path="apps/proxy/live_proxy/channel_status.py",
        lineno=74,
        pr="2b-3",
        reason=(
            "The stream_name fallback, read when the metadata hash carries a "
            "stream_id and no name. NOT deleted: every name write in the tree "
            "is guarded on a value that arrives from Django "
            "(services/channel_service.py:303-308, :364-369, :931-939; "
            "input/manager.py:2175-2178), and url_utils.py:31-42's "
            "tune_extras exists to degrade all four names to None when the "
            "answer comes from a Django that predates 2b-1. The relay and the "
            "control plane are separately deployable, so version skew is a "
            "supported state; 2b-1's author recorded exactly this at "
            "views.py:553-566. Under a same-version deployment the branch is "
            "dead, which is a property of a deployment and not something a "
            "guard can assert. Parity-matrix row 18, plan 2b-3 Ruling R7."
        ),
        closed_by=(
            "Nothing on the contract closes it, and nothing needs to. Row 18's "
            "answer is that ABSENCE is the contract: when Redis has no name, "
            "the key is absent from the status payload entirely -- not null, "
            "not '' -- which RelayChannelDetailSerializer already declares "
            "(relay_serializers.py:111, :113, both required=False). The ORM "
            "fallback is best-effort enrichment on top of that. The Go relay, "
            "having no database, always omits the key, which is inside the "
            "contract rather than a divergence from it. This Python branch is "
            "deleted wholesale in migration/phase2d-delete-live-proxy."
        ),
    ),
    Site(
        path="apps/proxy/live_proxy/channel_status.py",
        lineno=106,
        pr="2b-3",
        reason=(
            "The m3u_profile_name fallback, same shape and same decision as "
            ":74. Its carriers are required=False on "
            "RelayAdvanceRequestSerializer (:202-211) and absent from "
            "input/manager.py:2016-2019's _CACHED_ALTERNATE_REQUIRED_FIELDS, "
            "so a degraded failover can write M3U_PROFILE from a stale cache "
            "entry with no name beside it. Note the spec and the parity "
            "matrix both cite :92 for this read; 2b-1 inserted a seven-line "
            "comment above it and it is at :106 (plan 2b-3 Ruling R10)."
        ),
        closed_by="As :74 -- absence is the contract. Row 18.",
    ),
    Site(
        path="apps/proxy/live_proxy/views.py",
        lineno=153,
        pr="2b-2",
        reason=(
            "OutputProfile.objects.filter(id=..., is_active=True) so "
            "build_command() can be called. Left in place deliberately by "
            "2b-2; its Ruling R3 is transcribed in closed_by below rather "
            "than paraphrased, because spec line 1769 makes 2c-1 restate it "
            "and it is written once."
        ),
        closed_by=(
            # Verbatim from docs/superpowers/plans/
            # 2026-09-12-phase2-2b2-output-profile-and-user.md:104. Do not
            # reword: 2c-1's precondition restates this paragraph.
            "views.py:152 stays. The contract field that closes it is "
            "output_profiles on next-source's response: the Go relay caches "
            "the map at tune and serves every later client from memory. "
            "Python cannot, because _output_profile_for runs per client "
            "(views.py:605 owner-init, :712 everything else) while "
            "next-source runs per channel, and closing it in Python would "
            "need a cache whose staleness semantics nothing has specified."
        ),
    ),
    Site(
        path="apps/proxy/live_proxy/views.py",
        lineno=134,
        pr="2b-3",
        reason=(
            "CoreSettings.get_default_output_format() in _resolve_output_"
            "format. NOT in the spec's Stage 2b table and NOT in issue #253 "
            "-- found by this scanner, which is the first thing in the "
            "programme able to see a classmethod on a model behind a name "
            "that does not look like ORM. Reached only when neither "
            "?output_format= nor the user's custom_properties supplies one. "
            "Since 2b-2 the hop always sets X-Relay-Output-Format, so "
            "force_output_format short-circuits ahead of it on every "
            "nginx-authorized tune; the branch survives for the inline/dev "
            "shape."
        ),
        closed_by=(
            "X-Relay-Output-Format, the sixth relay header 2b-2 added. The Go "
            "relay reads the header and never resolves a default itself; the "
            "dev fallback resolves it in Django, at "
            "POST /_dispatcharr/authorize-internal (2c-8, D5 exception 2)."
        ),
    ),
    Site(
        path="apps/proxy/live_proxy/config_helper.py",
        lineno=50,
        pr="2b-1",
        reason=(
            "TSConfig.get_proxy_settings() -> CoreSettings.get_proxy_settings "
            "(core/models.py:707) through apps/proxy/config.py's 10-second "
            "process-local cache. Issue #253 item 3: 2b-1 put proxy_settings "
            "on next-source's response and deliberately did not wire "
            "StreamManager to prefer it, so the read is still live at the end "
            "of 2b. Same precedent as 2b-1's own 'nothing in the Python relay "
            "consumes this yet, deliberately'."
        ),
        closed_by=(
            "proxy_settings on next-source's response (2b-1). The Go relay "
            "takes channel-start values from the tune answer and never reads "
            "CoreSettings, which also collapses #232's 10-second staleness "
            "window to zero for every value that matters at channel start."
        ),
    ),
    Site(
        path="apps/proxy/live_proxy/views.py",
        lineno=434,
        pr="2b-3",
        reason=(
            "channel.get_stream_profile() -- issue #253's headline finding, "
            "and the shape that made this scanner an AST scan rather than a "
            "grep. apps/channels/models.py:467 falls through to "
            "StreamProfile.objects.get and touches an FK accessor first, so "
            "it is worth one to several queries, not one. Note #253 cites "
            ":430 (verified at ef3d3145); 2b-1 moved it to :434."
        ),
        closed_by=(
            "stream_profile on next-source's response -- already on the "
            "contract since Phase 1 PR 6 (control_plane.next_source's Source "
            "dict, next_source.py:615-624 {id, command, args}). The Go relay "
            "reads the profile it was handed at tune and never resolves one."
        ),
    ),
    Site(
        path="apps/proxy/live_proxy/input/manager.py",
        lineno=785,
        pr="2b-3",
        reason="channel.get_stream_profile(), as views.py:434. #253 cites :741 at ef3d3145.",
        closed_by="stream_profile on next-source's response, as views.py:434.",
    ),
    Site(
        path="apps/proxy/live_proxy/input/manager.py",
        lineno=788,
        pr="2b-3",
        reason="channel.get_stream_profile(), as views.py:434. #253 cites :744 at ef3d3145.",
        closed_by="stream_profile on next-source's response, as views.py:434.",
    ),
    # --- cleared by inspection: a model method that issues no query ---
    Site(
        path="apps/proxy/live_proxy/views.py",
        lineno=750,
        pr="2b-3",
        reason=(
            "resolved_output_profile.build_command(). A model METHOD, so the "
            "scanner flags it, but core/models.py:200-203 is "
            "[self.command] + shlex_split(self.parameters) -- two already-"
            "loaded fields, no query, no descriptor. Kept on the list rather "
            "than stoplisted: build_command is also StreamProfile's "
            "(core/models.py:137-160), and a stoplist entry would blind the "
            "scanner to both on every file."
        ),
        closed_by=(
            "Nothing to close -- no query. The Go relay builds the same argv "
            "from output_profiles on next-source's response (2b-2 Ruling R3)."
        ),
    ),
    Site(
        path="apps/proxy/live_proxy/input/manager.py",
        lineno=791,
        pr="2b-3",
        reason="stream_profile.build_command(...); pure, as views.py:750 (core/models.py:137-160).",
        closed_by="Nothing to close -- no query.",
    ),
    Site(
        path="apps/proxy/live_proxy/views.py",
        lineno=452,
        pr="2b-3",
        reason=(
            "stream_profile.is_redirect(). A model method on an object the "
            "caller already holds; core/models.py compares self.name against "
            "a constant. No query."
        ),
        closed_by="Nothing to close -- no query.",
    ),
    Site(
        path="apps/proxy/live_proxy/views.py",
        lineno=458,
        pr="2b-3",
        reason="stream_profile.is_redirect(), as :452.",
        closed_by="Nothing to close -- no query.",
    ),
)

EDGES = (
    EdgeEntry(
        importer="apps/proxy/live_proxy/views.py",
        module="apps.proxy.next_source",
        name="resolve_source",
        hits=34,
        pr="2b-3",
        reason=(
            "SETTLED HERE, and issue #253 left it open: resolve_source is NOT "
            "dead in the relay. It is called in-process at views.py:924 "
            "(change_stream), views.py:1273 (next_stream) and "
            "services/channel_service.py:415 -- the operator switch paths, "
            "all three relay-served. Its reachable subtree is 34 ORM sites "
            "including get_stream_info_for_switch's get_object_or_404 chain "
            "and _source_from_info's StreamProfile.objects.get. #253's "
            "'looks like API-process or dead code; they were read, not "
            "executed' is withdrawn."
        ),
        closed_by=(
            "POST /api/relay/channels/<id>/next-source with target_stream_id "
            "-- already on the contract (apps/proxy/control_plane.py:152, "
            ":179-180, and next_source.resolve_source's own target_stream_id "
            "parameter at :708). The Go relay makes the operator switch a "
            "control-plane round trip instead of an import; 2c-8 owns the "
            "route."
        ),
    ),
    EdgeEntry(
        importer="apps/proxy/live_proxy/url_utils.py",
        module="apps.proxy.next_source",
        name="get_stream_object",
        hits=3,
        pr="Phase 1 PR 6",
        reason=(
            "Two get_object_or_404 calls and a select_related. Executes in "
            "the relay at views.py:190, views.py:1199 and "
            "input/manager.py:774, and at authorize.py:344 on the inline "
            "authorize path. Issue #253 item 2."
        ),
        closed_by=(
            "next-source's identifier resolution, which 2b-1 extended to "
            "accept a stream_hash as well as a channel uuid (parity row 16). "
            "The Go relay sends whatever identifier arrived in the URL and "
            "Django resolves it, which is what get_stream_object already does."
        ),
    ),
    # The remaining edges follow the same shape. Fill each from the Step 3
    # measurement, with the reason and closed_by written by hand:
    #   apps.proxy.config.TSConfig                    -> proxy_settings on next-source (2b-1)
    #   apps.proxy.authorize.resolve_output_profile   -> the nginx hop; X-Relay-Output
    #   apps.proxy.authorize_views.resolve_authorization -> the nginx hop; the five X-Relay-* headers
    #   ... and any edge the measurement shows that this list does not.
)

SQL_SIGNATURES = ()  # Task 4 fills this, from its own measurement.
```

**The three edges left as a comment are not a placeholder to be skipped** — they are entries whose `hits` count must come from *your* measurement rather than this plan's, because they will have moved if 2b-2's squash changed those modules. Write each one out in full, in the same shape as the two above, before Step 5. The guard fails until you do, which is the point.

One entry deserves its reason stated here so it is not mis-written: `apps.proxy.authorize_views.resolve_authorization` reaches `result_from_headers`'s `User.objects.filter(id=int(user_id)).first()` — at `authorize_views.py:146` on 2b-2's branch; re-measure the line after the squash. **The static scanner flags it and the runtime check clears it**, and the reason is a **surface split, not laziness**: the query sits in the `else` arm of `if surface in (SURFACE_LIVE, SURFACE_LIVE_XC)`, so a live tune never enters it, while `/proxy/vod/`, `/proxy/catchup/` and `/streaming/timeshift.php` keep today's code verbatim. `closed_by` is that split plus `X-Relay-User`, **not** "the field is lazily resolved".

**Do not write the lazy version.** An earlier draft of 2b-2 proposed a lazy `User` proxy and it was withdrawn at `71cd8d31`: `is` cannot be overloaded, and eleven of the field's fourteen consumers test `is None`/`is not None` (`client_manager.py:234`, `:274`; `live_proxy/views.py:174`; `timeshift/views.py:1274`, `:2509`, `:2524`, `:2553`, `:2965`, `:2966`; `vod_proxy/views.py:639`, `:783`), so a stand-in object would be permanently wrong for all eleven — most sharply at `vod_proxy/views.py:783`, where `if user is None` is a *recovery* path that a non-None stand-in would turn into dead code. The two designs imply different blast radii, which is why the reason matters and not just the conclusion: under laziness any consumer touching the field resurrects the query, while under the split only a change to the surface constant or the branch does.

- [ ] **Step 5: Run the guard to verify it passes**

Run: `python manage.py test apps.proxy.live_proxy.tests.test_zero_orm_reads -v 2`
Expected: PASS.

- [ ] **Step 6: Break-check part 1, both directions**

1. Add `from apps.channels.models import Channel` and `Channel.objects.filter(id=1).first()` inside a function in `apps/proxy/live_proxy/client_manager.py`. Expected: `test_every_orm_site_in_the_relay_package_is_allowlisted` fails, naming `client_manager.py:<n>` under "unlisted". Revert.
2. Add `Site(path="apps/proxy/live_proxy/server.py", lineno=1, pr="2b-3", reason="x", closed_by="x")` to `SITES`. Expected: the same test fails, naming it under "listed but gone". Revert.
3. Add a module-level `from core.utils import RedisClient`-shaped import of a symbol with ORM hits — e.g. `from apps.channels.tasks import ...` — into a relay file. Expected: `test_every_in_process_import_edge_is_allowlisted` fails. Revert.
4. Change one `EDGES` entry's `hits` by one. Expected: `test_every_edge_carries_the_hit_count_it_actually_clears` fails, naming the symbol. Revert.

All four must go red. Record in the PR description that they did, with the failure text.

- [ ] **Step 7: Commit**

```bash
git add apps/proxy/live_proxy/tests/zero_orm_allowlist.py apps/proxy/live_proxy/tests/test_zero_orm_reads.py
```

Message file, then commit in a separate call:

```
test(phase2): the zero-ORM allowlist and the static half of the guard (2b-3 task 2)

Twelve sites inside the relay package and eight import edges out of it,
each with the reason it survives and -- per spec line 1769, which 2c-1's
precondition depends on -- either the contract field that closes it or
why the Go relay never asks.

Two findings the spec's Stage 2b table does not have. views.py:134's
CoreSettings.get_default_output_format() is an ORM read on the tune path
that neither the table nor issue #253 records; the scanner found it.
And resolve_source is NOT dead in the relay -- views.py:924,
views.py:1273 and channel_service.py:415 call it on the operator switch
paths, so #253's "read, not executed" caveat is withdrawn and its
34-site subtree is live.
```

---

## Task 3: The runtime capture helper

**Files:**
- Create: `apps/proxy/live_proxy/tests/harness/queries.py`
- Test: `apps/proxy/live_proxy/tests/test_zero_orm_scan.py` (append a class; the helper's unit tests belong with the other tests-of-the-guard)

**Interfaces:**
- Produces: `capture_queries()` — a context manager yielding a list of `Query(sql, relay_frames)`; `relay_queries(captured)`; `RELAY_PREFIX`.
- Consumes: nothing from Tasks 1–2 (deliberately: the helper is mechanism, the allowlist is policy, and Task 4 joins them).

- [ ] **Step 1: Write the failing tests**

```python
class QueryCaptureTests(TestCase):
    """Tests of the capture helper (plan 2b-3, Rulings R5 and R6)."""

    def test_a_query_made_on_another_thread_is_captured(self):
        """The whole reason this is not CaptureQueriesContext.

        CaptureQueriesContext binds to django.db.connections for the
        CALLING thread. RelayHarnessTestCase is a LiveServerTestCase:
        the relay's code runs on the WSGI server's threads. A
        per-connection context in a test body captures nothing from a
        tune and passes vacuously.
        """
        import threading
        from core.models import CoreSettings
        from .harness.queries import capture_queries

        def work():
            list(CoreSettings.objects.all()[:1])

        with capture_queries() as captured:
            thread = threading.Thread(target=work)
            thread.start()
            thread.join()

        self.assertTrue(
            any("core_coresettings" in q.sql for q in captured),
            "the cross-thread query was not captured -- the patch is not "
            "at class level on CursorWrapper",
        )

    def test_a_query_with_no_relay_frame_is_not_attributed_to_the_relay(self):
        """Ruling R6's discriminator, in its negative direction.

        The harness runs one process serving both planes. Django's
        /api/relay/ views issue a dozen legitimate control-plane queries
        per tune; counting those would make the guard permanently red for
        the wrong reason.
        """
        from core.models import CoreSettings
        from .harness.queries import capture_queries, relay_queries

        with capture_queries() as captured:
            list(CoreSettings.objects.all()[:1])

        self.assertEqual(relay_queries(captured), [])

    def test_a_query_with_a_relay_frame_is_attributed_to_the_relay(self):
        """The discriminating half. Without it, the test above passes
        with an attributor that returns [] for everything."""
        from apps.proxy.live_proxy.config_helper import ConfigHelper
        from .harness.queries import capture_queries, relay_queries

        from apps.proxy.config import BaseConfig
        BaseConfig.clear_proxy_settings_cache()

        with capture_queries() as captured:
            ConfigHelper.new_client_behind_seconds()

        self.assertTrue(
            relay_queries(captured),
            "a query issued from apps/proxy/live_proxy/config_helper.py "
            "was not attributed to the relay",
        )

    def test_a_query_from_the_tests_directory_is_not_a_relay_frame(self):
        """tests/ lives under the relay package. Without this exclusion
        every query a test makes is a relay query and the guard is
        unusable."""
        from core.models import CoreSettings
        from .harness.queries import capture_queries, relay_queries

        with capture_queries() as captured:
            list(CoreSettings.objects.filter(key="x"))

        self.assertEqual(relay_queries(captured), [])
```

Note the third test calls `ConfigHelper.new_client_behind_seconds()` (`config_helper.py:44-51`), which is an allowlisted site — it is chosen precisely because it is a *real* relay-frame ORM read, so the positive case is not a synthetic one. `clear_proxy_settings_cache()` first, or the 10-second process-local cache makes the query not happen and the test passes with a broken attributor (Global Constraint 1).

- [ ] **Step 2: Run to verify they fail**

Run: `python manage.py test apps.proxy.live_proxy.tests.test_zero_orm_scan.QueryCaptureTests -v 2`
Expected: FAIL — `ModuleNotFoundError: … harness.queries`.

- [ ] **Step 3: Write the helper**

```python
"""Record every SQL statement the process executes, and say who made it.

WHY NOT CaptureQueriesContext (plan 2b-3, Ruling R5). It binds to
django.db.connections for the CALLING thread. RelayHarnessTestCase is a
LiveServerTestCase, so the relay's code runs on the WSGI server's
threads: a per-connection context in a test body captures nothing from a
tune and passes vacuously -- the same shape as a substring that matches
nothing. Patching CursorWrapper at class level is process-global and
sees every thread.

HOW A QUERY IS ATTRIBUTED (Ruling R6). The harness runs one process
serving both planes: the relay's stream_ts calls control_plane.next_
source(), which makes a real HTTP request back to the same server, where
Django's /api/relay/ view issues a dozen legitimate control-plane
queries. The HTTP boundary breaks the Python stack, and that is the
discriminator -- a query belongs to the relay iff some frame in its
stack is a file under apps/proxy/live_proxy/ that is not under a tests/
directory.

CONSEQUENCE FOR CALLERS: drive TRUSTED tunes only. An untrusted tune
runs authorize_stream inline from a live_proxy frame and would be
attributed to the relay, where production runs that hop in the API
process behind nginx's auth_request.
"""

import threading
import traceback
from collections import namedtuple
from contextlib import contextmanager

from django.db.backends.utils import CursorWrapper

RELAY_PREFIX = "/apps/proxy/live_proxy/"

# params, not just sql: the SQL text carries placeholders, so two
# queries against the same table are byte-identical however different
# the rows they ask for. Task 4's follower drive distinguishes itself
# from the owner drive by the OutputProfile id it asks for, and that id
# is only visible here. Failure messages print sql and never params, so
# a later non-test use of this helper cannot widen what gets logged.
Query = namedtuple("Query", "sql params relay_frames")

_lock = threading.Lock()


def _relay_frames():
    frames = []
    for frame in traceback.extract_stack():
        name = frame.filename.replace("\\", "/")
        if RELAY_PREFIX not in name:
            continue
        tail = name.split(RELAY_PREFIX, 1)[1]
        if tail.startswith("tests/") or "/tests/" in tail:
            continue
        frames.append(f"{tail}:{frame.lineno}")
    return frames


@contextmanager
def capture_queries():
    captured = []
    real_execute = CursorWrapper.execute
    real_executemany = CursorWrapper.executemany

    def record(sql, params):
        with _lock:
            captured.append(Query(str(sql), repr(params), tuple(_relay_frames())))

    def execute(self, sql, params=None):
        record(sql, params)
        return real_execute(self, sql, params)

    def executemany(self, sql, param_list):
        record(sql, param_list)
        return real_executemany(self, sql, param_list)

    CursorWrapper.execute = execute
    CursorWrapper.executemany = executemany
    try:
        yield captured
    finally:
        CursorWrapper.execute = real_execute
        CursorWrapper.executemany = real_executemany


def relay_queries(captured):
    return [q for q in captured if q.relay_frames]
```

- [ ] **Step 4: Run to verify they pass**

Run: `python manage.py test apps.proxy.live_proxy.tests.test_zero_orm_scan.QueryCaptureTests -v 2`
Expected: PASS, 4 tests.

- [ ] **Step 5: Break-check the helper**

1. Replace `_relay_frames`'s body with `return []`. Expected: `test_a_query_with_a_relay_frame…` fails. Revert.
2. Delete the `tests/` exclusion. Expected: `test_a_query_from_the_tests_directory…` fails. Revert.
3. Swap the class-level patch for `CaptureQueriesContext(connection)`. Expected: `test_a_query_made_on_another_thread…` fails — the finding that motivates R5. Revert.

- [ ] **Step 6: Commit**

```bash
git add apps/proxy/live_proxy/tests/harness/queries.py apps/proxy/live_proxy/tests/test_zero_orm_scan.py
```

```
test(phase2): record every query and attribute it by stack frame (2b-3 task 3)

CaptureQueriesContext binds to the calling thread's connection. The
relay harness is a LiveServerTestCase, so the relay's code runs on the
server's threads and a per-connection context captures nothing from a
tune while passing. Patch CursorWrapper at class level instead.

The harness serves both planes in one process, so a tune's own
next-source round trip issues legitimate control-plane queries. The HTTP
boundary breaks the Python stack, which is the discriminator: a query is
the relay's iff some frame is a non-test file under live_proxy/.
```

---

## Task 4: Part 2 — the runtime guard

**Files:**
- Modify: `apps/proxy/live_proxy/tests/test_zero_orm_reads.py` (append `RuntimeGuardTests`)
- Modify: `apps/proxy/live_proxy/tests/zero_orm_allowlist.py` (fill `SQL_SIGNATURES`)

**Interfaces:**
- Consumes: `zero_orm_allowlist.SQL_SIGNATURES`, `harness.queries.capture_queries`, `harness.relay.RelayHarnessTestCase`, `harness.control` for the internal-auth headers.

- [ ] **Step 1: Write the failing test**

**Five drives.** Owner-versus-follower is a systematic axis (Global Constraint 4); the spec is explicit that a tune-only runtime check would never execute the fallback reads under discussion, which are on the **status** path; and each drive must be able to fail for a reason no other drive covers, or it is a copy rather than a drive. The owner and follower ask for *different* Output Profiles, and the status path is read twice — once as tuned, and once with the two names stripped from the hash, which is the only drive in which `channel_status.py`'s fallbacks actually run.

```python
class RuntimeGuardTests(RelayHarnessTestCase):
    """What the relay actually executes, across five drives.

    This is the half that proves the property. Part 1 sees code; this
    sees execution, and the two disagree on purpose in at least one
    place: result_from_headers' User.objects.filter is flagged
    statically and never runs on a live tune, because 2b-2 split
    result_from_headers on the SURFACE (authorize_views.py:146): the
    query sits in the `else` arm and SURFACE_LIVE/SURFACE_LIVE_XC never
    enter it. NOT because the field is lazy -- that design was drafted
    and withdrawn at 71cd8d31, since `is` cannot be overloaded and
    eleven of the field's fourteen consumers test identity.

    Trusted tunes only (Ruling R6): an untrusted tune runs
    authorize_stream inline from a live_proxy frame, where production
    runs that hop in the API process behind nginx's auth_request.
    """

    def _assert_allowlisted(self, captured, phase):
        offenders = []
        for query in relay_queries(captured):
            if not any(sig.sql_fragment in query.sql for sig in allowlist.SQL_SIGNATURES):
                offenders.append((query.sql[:400], query.relay_frames))
        self.assertEqual(
            offenders,
            [],
            f"\n{phase}: the relay executed a query matching no allowlisted "
            f"signature.\n" + "\n".join(f"  {s}\n    via {f}" for s, f in offenders),
        )
        return {
            sig.name for sig in allowlist.SQL_SIGNATURES
            for q in relay_queries(captured) if sig.sql_fragment in q.sql
        }

    def test_the_table_names_in_every_signature_are_real(self):
        """Vacuous-pass guard, 2b-2's idiom generalised.

        A signature that matches nothing satisfies _assert_allowlisted
        for every input while proving nothing, and a renamed db_table
        would make that happen silently.
        """
        from django.apps import apps as django_apps

        for sig in allowlist.SQL_SIGNATURES:
            if not sig.table_model:
                continue
            app_label, model_name = sig.table_model.split(".")
            model = django_apps.get_model(app_label, model_name)
            self.assertIn(
                model._meta.db_table,
                sig.sql_fragment,
                f"{sig.name}'s fragment does not contain "
                f"{model._meta.db_table} -- the table moved and the "
                f"signature now matches nothing",
            )

    def test_a_trusted_tune_a_follower_and_a_status_read_stay_on_the_allowlist(self):
        with self.stand_in():
            profile = stand_in_stream_profile()
            output_profile = OutputProfile.objects.create(
                name="2b3-guard", command="ffmpeg",
                parameters="-i {streamUrl} -f mpegts pipe:1", is_active=True,
            )
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            identifier = str(channel.uuid)

            # Global Constraint 1, twice over.
            #
            # X-Relay-Output must name a REAL active profile, or
            # _output_profile_for returns None at views.py:150 before
            # touching the ORM and views.py:153 is never exercised -- the
            # guard would pass with that site deleted.
            #
            # X-Relay-User must be a DIGIT naming a REAL row, and this is
            # the subtler of the two. 2b-2 split result_from_headers on
            # the surface (authorize_views.py:146): the User query is in
            # the `else` arm, and the live arm is reached first. With an
            # empty header there is no digit to query on, so the `else`
            # arm would not query EITHER -- the guard would stay green
            # with 2b-2's central change backed out. A digit naming a
            # real row is the only input that distinguishes "the surface
            # split holds" from "there was nothing to look up".
            #
            # GUARD_VIEWER_ID is 515151: not 2b-2's own 424242 (so the
            # two tests fail independently), far above any sequence
            # value, and not add_client's "0" fallback.
            viewer = get_user_model()(id=GUARD_VIEWER_ID, username="2b3-guard-viewer")
            viewer.set_password("x")
            viewer.save()

            headers = {
                "X-Dispatcharr-Authorized": relay_trust_token(),
                "X-Relay-Channel": identifier,
                "X-Relay-Client": "client_2b3_owner",
                "X-Relay-User": str(GUARD_VIEWER_ID),
                "X-Relay-Output": str(output_profile.id),
                "X-Relay-Output-Format": "mpegts",
                "X-Relay-Client-IP": "203.0.113.31",
            }

            with capture_queries() as captured:
                owner = requests.get(
                    f"{self.live_server_url}/proxy/ts/stream/{identifier}",
                    headers=headers, stream=True, timeout=20,
                )
                self.addCleanup(owner.close)
                self.assertEqual(owner.status_code, 200)
                next(owner.iter_content(chunk_size=188))
            fired_tune = self._assert_allowlisted(captured, "owner tune")

            # The follower: a second client on a running channel, which
            # makes NO next-source call at all (2b-2 Ruling R3) and takes
            # views.py:712 rather than :605.
            #
            # It asks for a DIFFERENT OutputProfile, and that is what
            # makes it a second drive rather than a second copy of the
            # first. With the same headers as the owner, every assertion
            # below is satisfied by the owner's own queries and the
            # follower drive cannot fail on its own -- the owner/follower
            # axis meeting Global Constraint 1. A distinct id means the
            # `SELECT ... FROM core_outputprofile` carrying THAT id can
            # only have come from this request, so the assertion after
            # the drive fails if the follower path is skipped, short-
            # circuited, or served from the owner's resolved profile.
            other_profile = OutputProfile.objects.create(
                name="2b3-guard-follower", command="ffmpeg",
                parameters="-i {streamUrl} -f mpegts pipe:1", is_active=True,
            )
            follower_headers = dict(headers, **{
                "X-Relay-Client": "client_2b3_follower",
                "X-Relay-Output": str(other_profile.id),
            })
            with capture_queries() as captured:
                follower = requests.get(
                    f"{self.live_server_url}/proxy/ts/stream/{identifier}",
                    headers=follower_headers, stream=True, timeout=20,
                )
                self.addCleanup(follower.close)
                self.assertEqual(follower.status_code, 200)
                next(follower.iter_content(chunk_size=188))
            fired_follower = self._assert_allowlisted(captured, "follower tune")
            # The discriminating assertion, and the mechanical answer to
            # Step 6: only views.py:712 can produce a lookup of THIS id.
            self.assertTrue(
                any(
                    str(other_profile.id) in q.params
                    for q in relay_queries(captured)
                    if "core_outputprofile" in q.sql
                ),
                "no OutputProfile lookup named the follower's own profile "
                f"({other_profile.id}). The second client did not take "
                "views.py:712 -- either it re-ran the owner-init path in "
                "this single-process harness, or the profile came from "
                "the owner's already-resolved one. Report the follower "
                "axis as NOT covered here rather than asserting it.",
            )

            # The status read, WITHOUT ?fields=state -- that is what
            # reaches get_detailed_channel_info and the two fallbacks.
            with capture_queries() as captured:
                status = internal_get(
                    self.live_server_url, f"/proxy/relay/channels/{identifier}"
                )
                self.assertEqual(status.status_code, 200)
            fired_status = self._assert_allowlisted(captured, "status read")

            # A FIFTH drive, and the status path's only discriminating
            # one. The drive above reads a channel this harness tuned
            # against a current Django, so tune_extras supplied every
            # name and the hash has them -- meaning channel_status.py's
            # two fallbacks never fire and that drive would pass with
            # both DELETED. It is an addition detector (break-check 2
            # proves that much) and nothing more; on its own it
            # contributes no exercised_by and cannot fail on a removal.
            #
            # Strip the two names from the hash and read again. Now the
            # fallbacks run, against real Postgres, and the two
            # allowlisted sites become observable -- so their entries can
            # carry exercised_by and their deletion turns this red.
            redis = ProxyServer.get_instance().redis_client
            redis.hdel(
                RedisKeys.channel_metadata(identifier),
                ChannelMetadataField.STREAM_NAME,
                ChannelMetadataField.M3U_PROFILE_NAME,
            )
            with capture_queries() as captured:
                stripped = internal_get(
                    self.live_server_url, f"/proxy/relay/channels/{identifier}"
                )
                self.assertEqual(stripped.status_code, 200)
            fired_stripped = self._assert_allowlisted(captured, "status read, names stripped")
            self.assertTrue(
                fired_stripped - fired_status,
                "stripping the names from the hash changed nothing about "
                "which queries ran, so the two fallbacks did not fire and "
                "this drive proves no more than the one above it",
            )

        fired = fired_tune | fired_follower | fired_status | fired_stripped
        expected = {
            sig.name for sig in allowlist.SQL_SIGNATURES if sig.exercised_by
        }
        self.assertEqual(
            fired & expected,
            expected,
            "an allowlisted signature marked as exercised did not fire. "
            "Either the read is gone -- delete the entry, that is the "
            "ratchet -- or this drive no longer reaches it.",
        )
```

`internal_get` is a small local helper building the two internal headers with `apps.proxy.internal_auth.internal_request_token` the way `apps/proxy/relay_client.py` does; write it in this file rather than adding to `harness/control.py`, which four parallel PRs already contend on.

- [ ] **Step 2: Run to verify it fails**

Run: `python manage.py test apps.proxy.live_proxy.tests.test_zero_orm_reads.RuntimeGuardTests -v 2`
Expected: FAIL — `SQL_SIGNATURES` is empty, so `_assert_allowlisted` reports every relay query as an offender, and the `expected` set is empty so the last assertion passes vacuously. Both are fixed by Step 3.

- [ ] **Step 3: Measure, then write the signatures as literals**

Run the failing test and read the offender list it prints. That list is the measurement. Then type each signature **by hand** into `SQL_SIGNATURES` — never generate them from the captured SQL (Global Constraint 2). Expect roughly:

```python
SQL_SIGNATURES = (
    Signature(
        name="output_profile_for_this_client",
        sql_fragment='FROM "core_outputprofile"',
        table_model="core.OutputProfile",
        exercised_by="owner tune, follower tune",
        reason="views.py:153. See SITES, and 2b-2 Ruling R3 transcribed there.",
    ),
    Signature(
        name="channel_stream_profile",
        sql_fragment='FROM "core_streamprofile"',
        table_model="core.StreamProfile",
        exercised_by="owner tune",
        reason="channel.get_stream_profile() at views.py:434 -- issue #253.",
    ),
    # ... one per offender, each with the file:line its relay_frames name
)
```

**On `exercised_by`, and the flap risk.** A signature marked exercised that fires only sometimes makes the guard flaky, and this programme has already measured three flapping regions in its coverage gate. Mark `exercised_by` only where the drive makes the read deterministic — a fresh tune with an output profile named, for example. Leave it empty where it is not, and say why in `reason`. An empty `exercised_by` means tolerate-only: the entry can rot without the guard noticing, which is a real cost and the honest alternative to a flaky gate.

**On connection-management SQL.** A newly opened connection may emit `SET …` before its first statement. Do not pre-emptively allowlist it: if it appears in the measurement, add one signature named `connection_setup` with the exact observed text quoted in `reason` and no `table_model`. If it does not appear, add nothing.

- [ ] **Step 4: Run to verify it passes**

Run: `python manage.py test apps.proxy.live_proxy.tests.test_zero_orm_reads -v 2`
Expected: PASS.

- [ ] **Step 5: Break-check part 2 — four ways, and each one matters**

1. **A new ORM read on the tune path.** Add `from apps.channels.models import Channel; Channel.objects.filter(uuid=channel_id).first()` inside `stream_ts`, just after the trusted-decision branch. Expected: the offender assertion fails, printing the SQL **and** the `live_proxy/views.py:<n>` frame. Revert.
2. **A new ORM read on the status path only.** Same insertion inside `ChannelStatus.get_detailed_channel_info`. Expected: fails at `status read`, not at `owner tune` — proving the status drive is load-bearing and that a tune-only check (the spec's first draft) would have missed it. Revert.
3. **A read that vanishes.** Delete `views.py:149-155`'s body and `return None`. Expected: the `exercised_by` assertion fails naming `output_profile_for_this_client`. Revert. If it does **not** fail, the `exercised_by` mechanism is hollow — stop and fix it.
4. **The attribution.** Change `RELAY_PREFIX` to something that matches nothing. Expected: the test passes — which is the vacuous state, and is why `test_the_table_names_in_every_signature_are_real` and Task 3's tests exist. Note in the PR description that this is a known unguarded direction of part 2, covered by Task 3's suite rather than by this test. Revert.
5. **2b-2's surface split, backed out.** In `authorize_views.py`'s `result_from_headers`, delete the `if surface in (SURFACE_LIVE, SURFACE_LIVE_XC):` arm so every surface takes the `else` branch. Expected: the owner-tune phase fails with a `SELECT … FROM accounts_user` offender carrying a `live_proxy/views.py:` frame. **If it does not go red, `X-Relay-User` is not naming a real row** and the drive is hollow — that is the whole reason `GUARD_VIEWER_ID` exists. Revert.
6. **The follower's own profile lookup.** In `views.py:712`, replace `_output_profile_for(decision, request, user)` with the owner's already-resolved value (`resolved_output_profile`). Expected: the distinct-profile assertion fails naming the follower's id. **This is the check that the follower drive is a second drive and not a second copy of the first** — with identical headers it would have passed here, which is why the headers differ. Revert.
7. **Both status fallbacks, deleted.** Delete `channel_status.py:72-78` and `:103-110`. Expected: the **names-stripped** drive fails its `fired_stripped - fired_status` assertion; the plain status drive stays green, which is the point — the plain one is an addition detector and cannot see a removal. Revert.

**Which phase can fail, and which are green by construction.** Five green phases are not five proofs, and a reader who is not told which is which will assume they are. Each break-check above must redden the phases named here and leave the rest green; a phase going red that this table says cannot is a finding about the guard, not a pass.

| Break-check | owner | follower | status | status-stripped | untrusted |
|---|---|---|---|---|---|
| 1 — new ORM read inside `stream_ts` | **red** | **red** | — | — | **red** |
| 2 — new ORM read inside `get_detailed_channel_info` | — | — | **red** | **red** | — |
| 5 — 2b-2's surface split backed out | **red** | **red** | — | — | — |
| 6 — follower reuses the owner's resolved profile | — | **red** | — | — | — |
| 7 — both `channel_status.py` fallbacks deleted | — | — | — | **red** | — |
| 5b-2 — `views.py:134`'s `CoreSettings` call deleted | — | — | — | — | **red** |

Two rows in that table are settled facts about the call graph, not guesses, and both were checked rather than assumed:

- **The follower phase *can* fail under break-check 5.** `stream_ts`'s signature is `stream_ts(request, channel_id, user=None, force_output_format=None, decision=None)` and its body opens `if decision is None: decision = resolve_authorization(...)` (`views.py:161-169`). The `decision=` parameter has exactly one caller — `views.py:870`, where `stream_xc` hands its own decision down **inside one request** (parity row 15). Nothing carries a decision *between* requests, so the follower tune is an independent request with `decision=None` and runs `result_from_headers` exactly as the owner does. A follower being served from an already-resolved decision would make this phase green by construction; it is not what the code does.
- **Neither status phase can fail under break-check 5, and that is structural.** `channel_view` is `@authentication_classes([])` + `@permission_classes([IsInternalRelay])` (`relay_views.py:141-144`). It never calls `resolve_authorization`, so `result_from_headers` is not on that path at all. The status phases carry the `get_detailed_channel_info` axis (rows 2 and 7) and nothing about the authorize hop.

So each of the five phases earns its place on at least one row, and no row is carried by more phases than actually run the code it breaks.

- [ ] **Step 5b: The fourth drive — an untrusted tune, characterized not gated**

Steps 1–5 prove a property about **trusted** tunes only, and that is structural (Ruling R6): an untrusted tune runs `authorize_stream` inline from a `live_proxy` frame, so the stack discriminator would attribute the hop's queries to the relay, where production runs that hop in the API process behind nginx's `auth_request`. Widening the attributor to exempt authorize frames would encode a judgment in the mechanism and would mask a genuine relay read that happened to sit in an authorize module; driving untrusted tunes against `SQL_SIGNATURES` would force a dozen hop queries into the policy allowlist with "not really the relay's" reasons, diluting it and making the edge counts noisy.

So drive it against a **separate list**, as a characterization pin rather than a policy gate. This turns an unmeasured hole into a measured one, which is the difference that matters when 2c-1 reads "the guard is green".

```python
    def test_an_untrusted_tune_executes_a_recorded_set_and_no_other(self):
        """The branch the trusted-only rule cannot reach (Ruling R6).

        NOT a policy gate: these queries are the authorize hop's, and in
        production nginx runs that hop in the API process. This is a
        characterization pin -- the set is recorded so a NEW ORM read on
        the inline path is visible, not so the set is required to shrink.

        The sharpest thing it covers is views.py:134's
        CoreSettings.get_default_output_format(). That site is 2b-3's own
        new finding AND the one site the trusted drives structurally
        cannot execute: since 2b-2 the hop always sets
        X-Relay-Output-Format, so force_output_format short-circuits
        ahead of it on every nginx-authorized tune, and since 2b-2 also
        leaves decision.user None on a live tune, views.py:129's
        `if user:` branch is dead there too. No trusted tune can reach
        line 134. This drive is the only thing in the suite that does.
        """
        with self.stand_in():
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=stand_in_stream_profile()
            )
            identifier = str(channel.uuid)
            with capture_queries() as captured:
                # No X-Dispatcharr-Authorized and no X-Relay-* headers:
                # resolve_authorization falls to the inline branch.
                response = requests.get(
                    f"{self.live_server_url}/proxy/ts/stream/{identifier}",
                    stream=True, timeout=20,
                )
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 200)
                next(response.iter_content(chunk_size=188))

        unrecorded = [
            (q.sql[:400], q.relay_frames) for q in relay_queries(captured)
            if not any(s.sql_fragment in q.sql for s in allowlist.INLINE_AUTHORIZE_SIGNATURES)
        ]
        self.assertEqual(
            unrecorded,
            [],
            "\nthe inline authorize path executed a query this list does "
            "not record. That is not automatically wrong -- it is the "
            "hop's work, not the relay's -- but it is new, so record it "
            "with a reason:\n"
            + "\n".join(f"  {s}\n    via {f}" for s, f in unrecorded),
        )
        self.assertIn(
            "core_coresettings",
            " ".join(q.sql for q in relay_queries(captured)),
            "the untrusted tune did not reach CoreSettings at all -- "
            "views.py:134 is the site this drive exists to execute, so "
            "either the drive is no longer untrusted or the site moved",
        )
```

Add `INLINE_AUTHORIZE_SIGNATURES` to `zero_orm_allowlist.py` beside `SQL_SIGNATURES`, with a docstring saying in its first line that it is **characterization, not policy** — it records what the inline hop does, and shrinking it is not a goal.

**Break-check:** add an ORM read to `authorize_stream`'s inline path. Expected: the `unrecorded` assertion fails. Then delete `views.py:134`'s `return CoreSettings.get_default_output_format()` and replace it with `return "mpegts"`. Expected: the second assertion fails — without it, the first passes against a drive that reached nothing. Revert both.

- [ ] **Step 6: Verify the follower branch is genuinely the follower branch**

The distinct-profile assertion added in Step 1 is now the mechanical answer to this — the follower's own `OutputProfile` id can only be looked up by `views.py:712`. So this step is no longer "observe by hand"; it is **read what that assertion did**.

If it **passes**, the follower axis is covered and the PR description says so, citing the assertion.

If it **fails**, do not weaken it. It means the second client re-ran the owner-init path in this single-process harness — `views.py:619-622` short-circuits `initialize_channel` within one process, and `docs/relay-parity-matrix.md`'s row 10 records exactly that defeating a different harness assertion. In that case: keep the drive, convert the assertion to a `self.skipTest` carrying the same message, say in the PR description that the follower axis is **not covered here**, and name `e2e/tests/streaming/shared-upstream.spec.ts` as what does cover it. Do not report a covered axis you did not observe, and do not delete the assertion to make the suite green — a skip that names the reason is evidence; a deletion is not.

- [ ] **Step 7: Commit**

```bash
git add apps/proxy/live_proxy/tests/test_zero_orm_reads.py apps/proxy/live_proxy/tests/zero_orm_allowlist.py
```

```
test(phase2): the runtime half -- five drives, each able to fail alone (2b-3 task 4)

The half that proves the property part 1 only ratchets. Every SQL
statement the process executes is recorded and attributed by stack
frame, so the tune's own next-source round trip -- legitimate
control-plane work in the same process -- does not count against the
relay.

Three drives, not one: the spec's first draft drove only a tune, and the
two fallback reads under discussion are on the STATUS path. A tune-only
check would never have executed them. The status read goes without
?fields=state, which is what reaches get_detailed_channel_info.

X-Relay-Output names a real active profile on purpose: with it empty,
_output_profile_for returns None before touching the ORM and the guard
would pass with views.py:153 deleted.
```

---

## Task 5: Row 18 — the pin, and the answer

**Files:**
- Modify: `apps/proxy/live_proxy/tests/test_zero_orm_reads.py` (append `StatusNameFallbackTests`)
- Modify: `docs/relay-parity-matrix.md` (row 18)
- Modify: `e2e/tests/guards/parity-matrix.ts` (`GATE_1_CLOSED`)

- [ ] **Step 1: Read the write paths yourself before accepting R7**

R7 refuses the deletion on the strength of four write sites and one deployment condition. Confirm each before relying on it; if you find a fifth that writes an id with no name **unconditionally**, R7's conclusion is unchanged but its evidence improves, and the allowlist reason should cite yours.

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/<yours>
grep -rn "STREAM_NAME\|M3U_PROFILE_NAME\|STREAM_ID\|M3U_PROFILE" --include='*.py' apps/ \
  | grep -v "tests/\|test_"
```

Sites R7 rests on: `services/channel_service.py:303-308` and `:364-369` (init), `:931-939` (`_update_channel_metadata`, reached from `change_stream_url` and from `server.py:312`'s pub/sub switch), `input/manager.py:2175-2178` (degraded failover). Every one guards the name on truthiness while writing the id on its own condition. `apps/timeshift/views.py:2985` writes `M3U_PROFILE` with no name beside it but into the `timeshift:` keyspace (`apps/timeshift/redis_keys.py:16`), which `RedisKeys.channel_metadata` (`live:`) never reads — **not** an instance, and worth recording so the next person does not re-find it as one.

- [ ] **Step 2: Write the row-18 pin**

By construction, not by hoping a production path reaches it (R8).

```python
class StatusNameFallbackTests(RelayHarnessTestCase):
    """Parity-matrix row 18: what the status payload carries when the
    metadata hash was never written a name.

    THE ANSWER, which 2c is held to: the key is ABSENT from the payload
    entirely -- not null, not '', not the id. RelayChannelDetailSerializer
    declares both required=False (relay_serializers.py:111, :113), so
    absence is already the contract; channel_status.py's ORM fallback is
    best-effort enrichment on top of it, filling the key when the row
    still exists and leaving it absent when the row is gone. The Go
    relay, having no database, always omits it -- inside the contract,
    not a divergence from it.

    Written as a fixture rather than as a reachability argument: this
    fails if anyone deletes the fallback, changes it, or makes it emit a
    null, whether or not any production path reaches it.
    """

    def test_the_orm_fills_the_name_when_redis_has_none_and_the_row_exists(self):
        with self.stand_in():
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=stand_in_stream_profile()
            )
            identifier = str(channel.uuid)
            stream = Stream.objects.create(name="2b3-row18-stream-name", url="http://x/")
            redis = ProxyServer.get_instance().redis_client
            # A name that could not arise by accident, and NO STREAM_NAME
            # key at all -- writing one empty would test a different branch.
            redis.hset(
                RedisKeys.channel_metadata(identifier),
                mapping={
                    ChannelMetadataField.STATE: "active",
                    ChannelMetadataField.STREAM_ID: str(stream.id),
                },
            )
            body = internal_get(
                self.live_server_url, f"/proxy/relay/channels/{identifier}"
            ).json()
        self.assertEqual(body["stream_name"], "2b3-row18-stream-name")

    def test_the_key_is_absent_when_redis_has_no_name_and_no_row_exists(self):
        """The row-18 answer itself, and the shape 2c must reproduce."""
        with self.stand_in():
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=stand_in_stream_profile()
            )
            identifier = str(channel.uuid)
            absent_stream_id = 987654
            self.assertFalse(Stream.objects.filter(id=absent_stream_id).exists())
            absent_profile_id = 987655
            self.assertFalse(
                M3UAccountProfile.objects.filter(id=absent_profile_id).exists()
            )
            redis = ProxyServer.get_instance().redis_client
            redis.hset(
                RedisKeys.channel_metadata(identifier),
                mapping={
                    ChannelMetadataField.STATE: "active",
                    ChannelMetadataField.STREAM_ID: str(absent_stream_id),
                    ChannelMetadataField.M3U_PROFILE: str(absent_profile_id),
                },
            )
            body = internal_get(
                self.live_server_url, f"/proxy/relay/channels/{identifier}"
            ).json()
        self.assertNotIn("stream_name", body)
        self.assertNotIn("m3u_profile_name", body)
        # The ids ARE present: absence of the NAME is the contract, not
        # absence of the field pair. Without this the test above passes
        # against a payload that dropped everything.
        self.assertEqual(body["stream_id"], absent_stream_id)
        self.assertEqual(body["m3u_profile_id"], absent_profile_id)

    def test_redis_wins_over_the_orm_when_both_have_a_name(self):
        """The fallback is a FALLBACK. Two different names, so the
        assertion distinguishes them -- a test writing the same name in
        both places passes with the precedence inverted."""
        with self.stand_in():
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=stand_in_stream_profile()
            )
            identifier = str(channel.uuid)
            stream = Stream.objects.create(name="2b3-row18-from-the-db", url="http://x/")
            redis = ProxyServer.get_instance().redis_client
            redis.hset(
                RedisKeys.channel_metadata(identifier),
                mapping={
                    ChannelMetadataField.STATE: "active",
                    ChannelMetadataField.STREAM_ID: str(stream.id),
                    ChannelMetadataField.STREAM_NAME: "2b3-row18-from-redis",
                },
            )
            body = internal_get(
                self.live_server_url, f"/proxy/relay/channels/{identifier}"
            ).json()
        self.assertEqual(body["stream_name"], "2b3-row18-from-redis")
```

- [ ] **Step 3: Run, then break-check**

Run: `python manage.py test apps.proxy.live_proxy.tests.test_zero_orm_reads.StatusNameFallbackTests -v 2`
Expected: PASS, 3 tests.

Break-checks:
1. Delete `channel_status.py:73-79`'s fallback block. Expected: test 1 fails; tests 2 and 3 still pass, which is why test 1 exists.
2. Change `info['stream_name'] = stream.name` to `info['stream_name'] = None`. Expected: test 1 fails. (`assertNotIn` in test 2 would **not** catch this, and that asymmetry is the point.)
3. Move the Redis read below the ORM read so the ORM wins. Expected: test 3 fails.

- [ ] **Step 3b: Give the pre-existing test its missing oracle**

`apps/proxy/live_proxy/tests/test_live_db_cleanup.py:338-340` is the only thing that has ever executed `:103-110`, and it executes it with no assertion — and with a mock that does not do what it reads as:

```python
mock_profile_filter.return_value.first.return_value = MagicMock(name="Profile A")
```

`name` is consumed by the `Mock` constructor, so `.name` is a **child mock, not the string**. Verified: `type(MagicMock(name="Profile A").name).__name__` is `MagicMock`, `isinstance(..., str)` is `False`, and its repr is `<MagicMock name='Profile A.name' …>`. The test writes a `MagicMock` into `info['m3u_profile_name']` and nobody has noticed, because the value is never read.

Fix both halves in one edit — the miswiring, and the absence that hid it:

```python
        with patch(
            "apps.m3u.models.M3UAccountProfile.objects.filter"
        ) as mock_profile_filter:
            # configure_mock, not MagicMock(name=...): `name` is consumed
            # by the Mock constructor, so MagicMock(name="Profile A").name
            # is a child mock rather than the string, and the assertion
            # below is what makes that visible instead of silent.
            profile = MagicMock()
            profile.configure_mock(name="Profile A")
            mock_profile_filter.return_value.first.return_value = profile
            info = ChannelStatus.get_detailed_channel_info("channel-uuid")

        self.assertEqual(info["stream_name"], "Backup Feed")
        self.assertEqual(info["m3u_profile_name"], "Profile A")
        mock_close.assert_called_once()
```

Run: `python manage.py test apps.proxy.live_proxy.tests.test_live_db_cleanup -v 2`
Expected: PASS.

Break-check: revert only the `configure_mock` line to `MagicMock(name="Profile A")`. Expected: the new `assertEqual` fails with a `MagicMock` on the left. Restore. That failure is the whole point — it is what has been invisible.

- [ ] **Step 4: Close the matrix row**

Replace row 18's `Pin` cell's `owed: 2b-3` with the two test references, correct `:92` to `:106`, and rewrite the `Notes` cell with the answer. Keep the line canonical: `| ` + cells joined by ` | ` + ` |`, no padding, no trailing whitespace — `parity-matrix.spec.ts` check 2 asserts it.

```
| 18 | What the status payload's `stream_name` and `m3u_profile_name` contain when the channel metadata hash was never written one | `apps/proxy/live_proxy/channel_status.py:74`, `apps/proxy/live_proxy/channel_status.py:106` | `apps/proxy/live_proxy/tests/test_zero_orm_reads.py::StatusNameFallbackTests::test_the_key_is_absent_when_redis_has_no_name_and_no_row_exists`, `apps/proxy/live_proxy/tests/test_zero_orm_reads.py::StatusNameFallbackTests::test_the_orm_fills_the_name_when_redis_has_none_and_the_row_exists` | 2b-3's answer: **absence is the contract.** The key is absent from the payload entirely — not null, not `''`, not the id — because `channel_status.py` only assigns it inside a truthy branch and `RelayChannelDetailSerializer` declares both `required=False` (`relay_serializers.py:111`, `:113`). Python's ORM fallback is best-effort enrichment on top of that: it fills the key when the row still exists and leaves it absent when the row is gone. The Go relay has no database and always omits it, which is inside the contract rather than a divergence from it. 2c: omit the key; never substitute null, `''` or the numeric id. The reads are NOT deleted — every name write in the tree guards the name on a value `url_utils.py:31-42`'s `tune_extras` degrades to `None` for a control plane that predates 2b-1, and the relay and control plane are separately deployable, so both fallbacks are reachable under version skew (`views.py:553-566` records it). They are allowlisted in `zero_orm_allowlist.py` and deleted wholesale in 2d. One production path defeats the repair rather than needing it — a degraded failover writes the new id and leaves the old name standing, so the key is present and wrong ([#265](https://github.com/D10Scot/Dispatcharr/issues/265)); that is a distinct defect from this row, cited not fixed. Coverage reads the two fallbacks as asymmetric (`:72-78` missing in 13/13, `:103-110` covered in 13/13) but that is one fixture's shape — `test_live_db_cleanup.py:322-344` supplies a `stream_name` and not an `m3u_profile_name`, mocks the query, and asserts nothing about either fallback. The spec and this row previously cited `:92`; 2b-1 moved it to `:106` |
```

- [ ] **Step 5: Flip Gate 1**

In `e2e/tests/guards/parity-matrix.ts`, `export const GATE_1_CLOSED = false;` → `true`. The comment above it already says this is 2b-3's job; leave it.

- [ ] **Step 6: Run the guard, both ways**

Run: `cd e2e && npx playwright test tests/guards/parity-matrix.spec.ts --project=guards`
Expected: PASS.

Break-check: set `GATE_1_CLOSED` back to `false` with row 18 closed. Expected: FAIL with "No row is owed any more — you just closed the last one. Flip GATE_1_CLOSED to true in …". Restore. This is the one assertion that makes Gate 1 falsifiable, so watch it fire.

- [ ] **Step 7: Commit**

```bash
git add apps/proxy/live_proxy/tests/test_zero_orm_reads.py apps/proxy/live_proxy/tests/test_live_db_cleanup.py docs/relay-parity-matrix.md e2e/tests/guards/parity-matrix.ts
```

```
relay(phase2): row 18 answered -- absence is the contract -- and Gate 1 closes (2b-3 task 5)

When the metadata hash carries an id and no name, the status payload
omits the key entirely: not null, not '', not the id. The serializer
already declares both required=False, so absence is the contract and the
ORM fallback is enrichment on top of it. The Go relay, with no database,
always omits -- inside the contract, not a divergence from it.

The reads are not deleted. Every name write guards the name on a value
tune_extras degrades to None for a pre-2b-1 control plane, and the two
processes deploy separately, so both fallbacks are reachable under
version skew. 2b-1's author wrote that down at views.py:553-566.
Allowlisted, and deleted wholesale in 2d.

Row 18 was the last owed row, so GATE_1_CLOSED flips here.
```

---

## Task 6: The spec, the tracker, and the PR

**Files:**
- Modify: `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Amend the spec, in `2fc5b269`'s idiom**

Read it first so the voice matches: `git show 2fc5b269 -- docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`. Three inline bold amendments, not footnotes:

a. At the `channel_status.py:74`/`:92` row (line ~1595) — correct `:92` to `:106` and record R7's answer in one sentence, with a pointer to parity row 18.

b. At the two-part guard paragraph (line ~1641) — record that part 1 is an AST scan rather than a grep, that the grep it prescribed fails in **both** directions (#253's two shapes), and R1's sentence: part 1 is a ratchet, not a proof, and three classes stay invisible.

c. At the `#253` paragraph (line ~1645) — record that `resolve_source` is **not** dead in the relay (`views.py:924`, `views.py:1273`, `services/channel_service.py:415`), withdrawing the issue's "read, not executed" caveat; and that `views.py:134`'s `CoreSettings.get_default_output_format()` is a fourth ORM read the Stage 2b table does not name, found by the scanner.

- [ ] **Step 2: Two sentences in `CLAUDE.md`**

In § Testing, after the Gate 2 paragraph:

> **Gate 1 is closed.** `apps/proxy/live_proxy/tests/test_zero_orm_reads.py` holds the relay to `zero_orm_allowlist.py` two ways — an AST scan of the package and its in-process import edges, and a runtime record of every SQL statement five real drives execute, attributed to the relay by stack frame. **The static half is a ratchet, not a proof**: it cannot see a property that queries, a `getattr` dispatch, or an ORM read more than one import hop out of the package, so a green static run is never evidence of zero ORM reads — the runtime half carries that.

- [ ] **Step 3: Close issue #253**

```bash
gh issue comment 253 --repo D10Scot/Dispatcharr --body-file /private/tmp/.../253-close.md
gh issue close 253 --repo D10Scot/Dispatcharr
```

The comment must say, at minimum: shape 1 is caught (the scanner's model-method rule sees `get_stream_profile` at all three sites, whose line numbers have moved from the issue's `ef3d3145` figures to `views.py:434`, `manager.py:785`, `:788`); shape 2 is structurally impossible (`ast` never sees a docstring as an attribute); shape 3 (a pin that supplies the default) is addressed by Global Constraint 1 and by the `X-Relay-Output` choice in Task 4; item 2 is settled the other way — `resolve_source` **does** execute in the relay; item 3 is allowlisted with `proxy_settings` named as what closes it; and a fourth read the issue does not have, `views.py:134`, was found.

- [ ] **Step 4: Run the whole backend package and the guards project**

```bash
python manage.py test apps.proxy.live_proxy.tests
python manage.py test apps.channels.tests
cd e2e && npx playwright test --project=guards
```

Expected: green. If Docker or the test container is down, the hook says so and exits 0 — **then say the tests did not run, and do not describe the work as verified.**

- [ ] **Step 5: Commit and open the PR**

Branch: `migration/phase2b-zero-orm-guard` (the `migration/**` prefix runs every Playwright project plus both bash lifecycle suites).

The PR description must carry, because the 2c-1 precondition and the reviewers depend on it:

1. **The allowlist, entry by entry**, each with its `closed_by` — spec line 1769 makes 2c-1 restate every one, and `views.py:153`'s is 2b-2 Ruling R3's paragraph verbatim.
2. **What the guard cannot see**, R1's three residuals, stated before the claims and not after them.
3. **Every break-check and its failure text** — Task 1 Step 5 (3), Task 2 Step 6 (4), Task 3 Step 5 (3), Task 4 Step 5 (7) and Step 5b (2), Task 5 Step 3 (3) and Step 3b (1). Twenty-three. A break-check that did not go red is a finding; report it as one. Four are load-bearing beyond their own step, and each proves that one drive can fail alone: Step 5's fifth backs out 2b-2's surface split (or `X-Relay-User` names no real row and the owner drive proves nothing); its sixth makes the follower reuse the owner's profile (or the follower drive is a second copy of the first); its seventh deletes both status fallbacks, which must redden the names-stripped drive and must leave the plain status drive green; and Step 5b's second deletes `views.py:134` (or the untrusted drive reached nothing).
4. **Issue [#265](https://github.com/D10Scot/Dispatcharr/issues/265)** — filed during planning, cited in `channel_status.py:106`'s allowlist entry, deliberately not fixed here (relay-internal, D10).
5. **Row 18's answer and its evidence**, and that the reads survive rather than being deleted.
6. **The three findings the spec's table does not have**: `views.py:134`, `resolve_source`'s liveness, and the `:92`→`:106` drift.
7. **Whether the follower axis was actually observed** (Task 4 Step 6), stated either way; that the untrusted path is characterized (Step 5b), not gated; and **Task 4 Step 5's phase table** — which of the five drives each break-check can redden, so five green phases are not read as five proofs.
8. That Gate 1 is closed and Gate 2's floor is untouched (every new file is under `tests/`, which the rcfile omits; 2b-3 moves only `missing`, downward, which the ratchet permits without a floor edit). **Tell 2b-4**: Task 5's fixtures close `:72-78`, so a 2b-4 measurement taken before this lands over-counts by that block.

---

## Self-review

**Spec coverage.** The PR-table row at line 1659 asks for four things. The two-part guard plus `zero_orm_allowlist.py` — Tasks 1–4. Resolving `channel_status.py:74`/`:106` — Task 5, resolved as *allowlist with a cited decision*, which the row explicitly permits ("adds them to the allowlist with a comment citing this decision"). Row 18 closed — Task 5. Gate 1 — Task 5 Step 5. Line 1595's demand that the fallbacks not be deleted without proof is honoured and its reasoning extended (R7). Line 1641's runtime-check spec is honoured with one deviation: it says "monkeypatches the Django DB connection to **raise** on any query", and this plan **records** instead. Raising is incompatible with an allowlist — the first allowlisted read would abort the tune and nothing after it would be observed — and the spec's own § NM2 correction is precisely that the allowlist must make "a read survives" and "the guard passes" compatible. Recorded as a deliberate deviation; it belongs in the PR description.

**Placeholder scan.** One construct in Task 2 Step 4 leaves three `EDGES` entries as a commented list rather than written out. That is deliberate and called out in the step: their `hits` counts cannot be correct in this plan, because 2b-2 squash-merges before this branch exists and may move those modules. The step names each edge, its `closed_by`, and the measurement command that produces the count, and the guard fails until they are written. No other step defers work.

**Type consistency.** `Hit(path, lineno, symbol, shape)` and `Edge(importer, module, name)` are produced in Task 1 and consumed unchanged in Tasks 2 and 4. `Site`/`EdgeEntry`/`Signature` are defined in Task 2 and consumed in Task 4; `EdgeEntry` carries `hits`, which Task 2's `test_every_edge_carries_the_hit_count_it_actually_clears` reads and nothing else writes. `capture_queries()`/`relay_queries()` are defined in Task 3 and used in Tasks 3 and 4. `internal_get` is local to `test_zero_orm_reads.py` and used by Tasks 4 and 5.

**Where this plan does not know.**

- **Whether the harness's second client genuinely takes the follower branch.** Single process, single `ProxyServer`, and `views.py:619-622` short-circuits `initialize_channel` within one process — `docs/relay-parity-matrix.md`'s row 10 notes exactly this defeating a different harness assertion. This is now *asserted* rather than observed: the follower asks for its own `OutputProfile` and only `views.py:712` can look that id up. If the assertion fails, Step 6 says to convert it to a named `skipTest` and report the axis as uncovered — never to delete it.
- **Exactly which queries a tune executes.** The signature list in Task 4 Step 3 is shaped from the static measurement, not from a run; the step is explicitly measure-then-type. What would settle it: running Task 4's test against the tree.
- **Whether `exercised_by` is stable enough to gate on.** Three regions of this relay are known to flap between runs. Task 4 Step 3 restricts the marker to deterministic reads and Step 5's third break-check verifies the mechanism bites at all; if it proves flaky in CI, the honest fix is to drop the marker on the flapping entry and say so, not to add a tolerance.
