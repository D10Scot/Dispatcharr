# Plan for #444 — recast the class-body `read_only_fields` guard as a lint

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. The implementer is `sonnet`; a
> stuck implementer escalates to `opus`. The PR is reviewed by `fable` (`opus` when fable credits are
> unavailable) against this plan before it leaves draft. Steps use checkbox (`- [ ]`) syntax.

| | |
|---|---|
| goal | The rule "`read_only_fields` lives in `Meta`, never in a serializer's class body" runs **on the edit that breaks it**: in the `*.py` `PostToolUse` edit hook and in `lint.yml`, independent of backend label routing. The class filter also catches the three shapes #444's comments name. |
| issue | #444 (option (b) of the issue body, plus both comments) |
| seed SHA | **`36e4ce10`** (`main`, 2026-09-25). Every `file:line` below was re-grepped there with `git show "36e4ce10:<path>"`. |
| PRs | **one**, small: one new script, one new test module, one deleted test module, one hook arm, three hook-harness cases, one `lint.yml` job, one ledger field, one CLAUDE.md phrase. |
| branch | `fix/444-read-only-fields-lint` (not `migration/…`: nothing under `docker/` or the relay is touched) |
| backend labels | `tests` only (measured: `printf '%s\n' <the PR's eight paths> \| python3 scripts/ci_backend_test_labels.py` → `["tests"]`) |
| upstreamable | no: `.claude/hooks/`, the fork's `lint.yml` jobs and `metrics/curated/` are fork-only |

**What this plan finds that the issue does not say.** A reviewer should check these first.

1. **The rule has zero findings on the whole tree, not only on the 11 modules the old test scans.** A prototype of the Appendix A script, run over all 614 tracked `*.py` at the seed (`git ls-files -z '*.py' | xargs -0 python3 <script>`), exits 0 with no output in under a second. So `lint.yml` can check **every tracked file**, not only the changed ones as the credential-logging job must (that job's comment at `lint.yml:104-107` says why: its pattern still has a backlog; this rule has none).
2. **Serializers live outside `*serializers.py`.** `apps/proxy/authorize_views.py:80,421,457` and `apps/timeshift/api_views.py:31,53,208` define `serializers.Serializer` subclasses, which the old test's file glob (`tests/test_no_class_body_read_only_fields.py:38-40`) never reads. Scanning any `*.py` the hook or CI hands over covers them with no path filter to maintain. Across the tree the new rule judges 107 classes in 21 files to be serializers (the models' own nested `Meta` makes Django models count too; harmless, since nothing reads `read_only_fields` on a model either).
3. **On today's tree the new class rule and the old one agree exactly**: 72 serializer classes in the 11 old modules under both rules, and no class anywhere that the new rule adds. The three shapes from #444's comments are fixture-only, which is what the issue's reviewer found too. The ten `read_only_fields` assignments in the tree (`apps/channels/serializers.py` ×3, `apps/epg` ×2, `apps/m3u` ×2, `core` ×2, `apps/plugins` ×1) are all inside a `Meta`.
4. **Deleting the old test breaks the metrics validator unless the ledger moves with it.** `metrics/curated/defects.yml:24` (`read-only-fields-misplaced`) carries `test: tests/test_no_class_body_read_only_fields.py`, and `metrics/build/curated.py:320-325` fails on a `test` path that does not exist. Measured on a copy of the seed tree: with the file deleted and the row unchanged, `python3 -m metrics.build --validate-only` prints `defect 'read-only-fields-misplaced': test path tests/test_no_class_body_read_only_fields.py does not exist`. The row's `test` moves to the new module (Task 4). #444 itself is not a ledger row (`git grep -n 444 36e4ce10 -- metrics/curated/` has no defect hit) and gets none: it is a tooling gap, not a product defect.
5. **The script's own unit test would inherit the same routing gap if it were a Django test.** `scripts/check_*.py` routes to **no** backend label (measured: `python3 scripts/ci_backend_test_labels.py scripts/check_read_only_fields.py` → `[]`, as for `scripts/check_credential_logging.py`), and `_PATH_ALIASES` cannot route anything to the root `tests` label: `_resolve_alias_labels` builds `f"{app_name}.tests"` (`dispatcharr/test_discovery.py:186`), so an alias naming `tests` would ask for `tests.tests`. Rather than widen the resolver, the new test module is a **plain `unittest.TestCase` with no Django import**, and the new `lint.yml` job runs it with a bare `python3 -m unittest` on every pull request. Django's runner still collects it under the `tests` label. No `_PATH_ALIASES` entry; `tests/test_ci_test_routing.py` is untouched.
6. **`lint.yml`'s jobs are not required checks.** The Main ruleset requires only `E2E result`, `Lifecycle result`, `Backend result`, `Frontend result`, `agent`, `safe_outputs` and `Go result` (measured with `gh api repos/D10Scot/Dispatcharr/rulesets/21229979`). So the new job, like `credential logging` today, turns a PR red without blocking its merge. That is why the new test module keeps one **live-tree** case under the `tests` label (inside `Backend result`, which is required) as a backstop. Making the new job required is a repo-settings action the user owns (Open question Q1).

---

## Global constraints

Numbered so a step can cite one. A conflict between a constraint and a step is a STOP and report, never a judgement call.

1. **Anchor every command** with an absolute path or a leading `cd <your worktree> &&`. The cwd is correlated across concurrent agents (CLAUDE.md § Repository and direction). Never `cd` into another agent's worktree or into the main checkout. No bare `git stash`.
2. **`set -o pipefail`** on any pipeline whose exit status you read; never `2>/dev/null` a git query whose emptiness you interpret. Brace refs in `git show "${sha}:path"` (the zsh `:s` modifier trap).
3. **Scope is this plan's file list and nothing else.** No other serializer, hook arm, workflow job or doc changes. The hook header's stale "Seven checks" count (`run-affected-tests.sh:4`) stays as it is.
4. **Byte-exact appendices.** Appendices A and B are the full text of the two new files; C, D and E are diff hunks against `36e4ce10` that `git apply --check --whitespace=error` accepted on a fresh `git archive 36e4ce10` tree. Apply them, do not retype them. If a hunk does not apply, STOP and report: the tree moved.
5. **The live hooks are not the edited hooks.** The `PostToolUse` hook that fires on your edits is `${CLAUDE_PROJECT_DIR}/.claude/hooks/run-affected-tests.sh`, from the main checkout, which does **not** carry the new arm until this PR merges. The only evidence for the new arm is invoking your worktree's copy directly (Tasks 6-7), exactly as `.claude/hooks/tests/test_hooks.sh:4-9` says.
6. **The test container must be yours.** Editing `tests/test_read_only_fields_guard.py` makes the live hook run the whole `tests` package in `dispatcharr-testrunner` (`run-affected-tests.sh:354-371`), against whichever worktree that container is bind-mounted at. Before Task 3, check occupancy (`docker ps --filter name=dispatcharr-testrunner`, and `stat -f '%Sm %N'` on files in the tree it is mounted at), then re-point it with `cd <your worktree> && .claude/hooks/start-test-container.sh`. If another agent holds it, STOP and report.
7. **Stage and commit in separate Bash calls**; write the commit message to a file and use `git commit -F`. The commit gate will run the `tests` label and the metrics validator (`pre-commit-tests.sh:217-232`, because `metrics/curated/defects.yml` is staged).
8. **The implementation PR body carries `Closes #444.`** (it is the fix). Nothing else in this programme may: this plan's own docs PR references the issue without a closing keyword.

---

## Overlap with sibling work

Checked at `36e4ce10` with `gh pr list --repo D10Scot/Dispatcharr --state open --json number,title,headRefName,files --limit 100`: four open PRs (#493, #494, #495, #496). None touches any file below.

| file this PR touches | open PR or plan also touching it | resolution |
|---|---|---|
| `.github/workflows/lint.yml` | none open. G-1 (`hook-tests` job) and G-2 (setup-node) are merged into the seed. | new job inserted between `credential-logging` and `lockfile-fresh` |
| `.claude/hooks/run-affected-tests.sh` | none open | new arm directly after the `secrets` arm |
| `.claude/hooks/tests/test_hooks.sh` | none open | cases appended before the summary |
| `scripts/check_credential_logging.py` | none | **not edited**; it is the precedent only |
| `tests/test_no_class_body_read_only_fields.py` | none open (E-6, #436, merged it) | deleted |
| `metrics/curated/defects.yml` | many fix branches edit other rows; none open as a PR | one field on row `:24` only; rebase if a sibling lands first |
| `CLAUDE.md` | none open | one phrase at `:57` |

If an open PR touching any of these appears before this one is opened, rebase onto `main` after it merges and re-run Task 9.

---

## Decisions (the eight questions, answered with evidence)

1. **Hook placement.** A new arm in `.claude/hooks/run-affected-tests.sh`, placed right after the `secrets` arm (`:125-145`), with the same shape: `if [[ "$REL" == *.py ]]`, host `python3` on the **edited file only** (`"$REL"`), **blocking** through `block()`, and a loud `note` when the script or `python3` is missing. It matches the credential arm because the contract is the same: stdlib-only script, no container, zero backlog, so a ratchet on the edited file. It is its own arm, not a second command in the credential arm, so each has its own title and remedy text. `block()` keeps only the first title (`:89`), so if one edit trips both checks the credential finding is reported first; the read-only one surfaces on the next edit. The header's check table (`:15`) and ratchet paragraph (`:17-21`) gain the new row (Appendix C).
2. **Commit gate.** `pre-commit-tests.sh` does **not** run `check_credential_logging.py` on staged files today: its sections are backend (`:129`), frontend (`:173`), go (`:186`), metrics (`:217`) and dashboard (`:234`), and `grep -n credential .claude/hooks/pre-commit-tests.sh` finds nothing. Mirror that: the commit gate is not edited. The deleted test's rule still reaches the commit gate through the new module's live-tree case whenever the `tests` label is selected.
3. **`lint.yml`.** A **new job** `read-only-fields` (name `read_only_fields in Meta`), not a step in `credential-logging`. That job needs `fetch-depth: 0` and a diff base (`:96-134`) because it checks changed files only; this one checks the whole tree and needs neither. Its only `uses:` is the checkout pin copied from the neighbouring jobs, `actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0` with `persist-credentials: false` (`:96-98`). It inherits the workflow's top-level `permissions: contents: read` (`:18-19`). Measured on the prototype: `zizmor 1.30.1` online, "No findings to report", and `actionlint -shellcheck= -pyflakes=` exit 0.
4. **The old test is deleted.** Keeping it would leave two implementations of one rule with different class filters: the old one misses the three shapes, so they would disagree on exactly the cases #444 adds. Its WHY paragraph moves into the new script's docstring. The new `tests/test_read_only_fields_guard.py` follows `tests/test_credential_logging_guard.py`: it runs the script as a subprocess on fixture sources, covering the three missed shapes plus the old test's cases, the I/O contract, and a live-tree case over `apps/**/*.py` and `core/**/*.py`. The real-module break-check (Task 7) moves `EPGSourceSerializer`'s `read_only_fields` out of its `Meta`, the same edit E-6's break-check used.
5. **Scope and interface.** The script checks **every `*.py` path it is given** and has no path filter. The hook passes the edited file. CI passes every tracked file: `git ls-files -z '*.py' | xargs -0 python3 ./scripts/check_read_only_fields.py`. Arguments not ending in `.py` are skipped. The output is `file:line: read_only_fields assigned in the body of serializer class <Name>, where DRF never reads it -- move it into <Name>.Meta`. Exit 0 means no findings (or no files). Exit 1 means at least one finding. Missing, unreadable, non-UTF-8 or unparseable files warn on stderr and do not change the exit. That is `scripts/check_credential_logging.py`'s contract (`:42-50`, `:222-242`, `:279-285`) verbatim. There is **no ignore marker**, because no class-body `read_only_fields` is ever correct.
6. **The class rule.** A class anywhere in the module (nested ones too), other than one named `Meta`, is a serializer when it meets **any** of these tests:
   - (a) it has a nested `class Meta` (kept from the old rule);
   - (b) one of its bases has a trailing identifier ending in `Serializer`, after two steps: unwrap subscripts (`ModelSerializer[int]` → `ModelSerializer`), then resolve a `from X import Y as Z` alias (`Z` → `Y`, whatever `X` is). This covers `serializers.ModelSerializer`, `HyperlinkedModelSerializer`, `ListSerializer`, `serializers.Serializer`, and a serializer imported from another app;
   - (c) one of its bases names a class **defined in the same module** that is itself a serializer, iterated to a fixed point (so `class Y(Middle)`, `class Middle(MyBase)`, `class MyBase(ModelSerializer)` makes `Y` one).

   The finding is a plain or annotated `read_only_fields` assignment directly in the class's own body. A class named `Meta` is never judged, so the correct placement is never reached. The stated limits are these. A base from another module whose name does not end in `Serializer` is not followed. Classes are matched by name. A tuple target, an augmented assignment and `setattr` are not examined. The 11 modules the old test scanned, all measured at zero findings under both rules, are:
   - `apps/accounts/serializers.py`, `apps/channels/serializers.py`, `apps/connect/serializers.py`, `apps/epg/serializers.py`
   - `apps/hdhr/serializers.py`, `apps/m3u/serializers.py`, `apps/plugins/serializers.py`
   - `apps/proxy/relay_serializers.py`, `apps/proxy/serializers.py`, `apps/vod/serializers.py`
   - `core/serializers.py`
7. **Routing.** `scripts/check_read_only_fields.py` → `[]`; `tests/test_read_only_fields_guard.py` → `["tests"]`; `.claude/hooks/…`, `.github/workflows/lint.yml`, `metrics/curated/defects.yml`, `CLAUDE.md` → `[]` (all measured). The PR as a whole selects `["tests"]`. **No `_PATH_ALIASES` entry**, for two reasons: the resolver cannot express "the root `tests` label" (finding 5), and the lint job runs the unit test on every PR anyway. `tests/test_ci_test_routing.py` pins four behaviours (`:30`, `:51`, `:76`, `:85`), none of which this PR touches.
8. **Metrics.** Yes, one field. Row `read-only-fields-misplaced` (`defects.yml:24`) changes `test:` to `tests/test_read_only_fields_guard.py`. Its `status` (`fixed`), `fixed_in` (436) and `status_changed` do not change: the defect's status did not move. No new row. Validate with `python3 -m metrics.build --validate-only`. On the scratch copy, the only errors after the edit were the milestone first-parent checks, which fail there because that copy has no git history. There was no defect error. In a real worktree those checks pass. The plan deliberately does not update CLAUDE.md's "2083 tests" figure: it dates from #332 (only `b6ae174b` carries it, per `git log -S"2083 tests"`), and #436, #455 and #488 have since added tests without moving it, so it is already stale and a bump belongs to a re-measurement, not to this PR.

---

## PR: `fix/444-read-only-fields-lint`

- **Closes** #444 (in the implementation PR body only; constraint 8).
- **Files**
  - `scripts/check_read_only_fields.py` (new, mode 100755 like its sibling)
  - `tests/test_read_only_fields_guard.py` (new)
  - `tests/test_no_class_body_read_only_fields.py` (deleted)
  - `.claude/hooks/run-affected-tests.sh`
  - `.claude/hooks/tests/test_hooks.sh`
  - `.github/workflows/lint.yml`
  - `metrics/curated/defects.yml` (`:24`, one field)
  - `CLAUDE.md` (`:57`, one phrase)
- **Labels** `tests`.

### Tasks

- [ ] **Task 0 — worktree and container.** Create your own worktree and branch off `origin/main` (`git worktree add .worktrees/444-lint -b fix/444-read-only-fields-lint origin/main`, run from the main checkout with an absolute `-C`). Confirm `git -C <wt> rev-parse --short HEAD` is `36e4ce10` or a descendant. If it is a descendant, run `git -C <wt> apply --check --whitespace=error` on Appendices C, D and E (extract each fenced `diff` block to a scratch file) and STOP if any fails. Then handle the container per constraint 6.

- [ ] **Task 1 — the script.** Create `scripts/check_read_only_fields.py` from **Appendix A**, verbatim, then `chmod +x` it. The live hook's credential arm runs on it and must stay silent.
  Verify:
  ```bash
  cd <wt> && set -o pipefail && git ls-files -z '*.py' | xargs -0 python3 ./scripts/check_read_only_fields.py; echo "exit=$?"
  ```
  Expected: no output and `exit=0`. Also run `python3 scripts/check_credential_logging.py scripts/check_read_only_fields.py; echo $?`, expecting `0`.

- [ ] **Task 2 — prove the three shapes against a real class first (red).** Before you write the test module, write the three shapes from #444's comments to a scratch file. Use `ALIASED_BASE`, `SUBSCRIPTED_BASE` and `LOCAL_BASE_TRANSITIVE` from Appendix B. Run the **old** guard's filter on them with this ad hoc one-liner:
  ```bash
  cd <wt> && python3 -c "import ast,sys;t=ast.parse(open(sys.argv[1]).read());bn=lambda b:b.attr if isinstance(b,ast.Attribute) else b.id if isinstance(b,ast.Name) else None;print([n.name for n in ast.walk(t) if isinstance(n,ast.ClassDef) and n.name!='Meta' and (any(isinstance(c,ast.ClassDef) and c.name=='Meta' for c in n.body) or any((bn(b) or '').endswith('Serializer') for b in n.bases))])" <scratch>/shapes.py
  ```
  Expected: the output does **not** include `Z`, `W` or `Y`. It does include `MyBase`, which has a nested `Meta`. Then run `python3 scripts/check_read_only_fields.py <scratch>/shapes.py`, expecting three findings (for `Y`, `Z` and `W`) and exit 1. This proves the new rule catches what the old one missed. Record both outputs for the PR body.

- [ ] **Task 3 — the test module.** Create `tests/test_read_only_fields_guard.py` from **Appendix B**, verbatim. The live hook runs the whole `tests` package in the container, which must pass.
  Verify, host side:
  ```bash
  cd <wt> && python3 -m unittest -v tests.test_read_only_fields_guard 2>&1 | tail -3
  ```
  Expected: `Ran 17 tests` … `OK`.
  **Break-check 1 (the three shapes are pinned, not tautological).** In `scripts/check_read_only_fields.py`, make three edits:
  - delete the line `                or any(name in serializers for name in names)`;
  - delete the two lines `    while isinstance(base, ast.Subscript):` / `        base = base.value`;
  - replace `return aliases.get(base.id, base.id)` with `return base.id`.

  Re-run. Expected (measured): `FAILED (failures=4)`, with the failures being exactly:
  - `test_a_base_imported_under_an_alias_is_resolved`
  - `test_a_subclass_of_a_local_serializer_is_followed_transitively`
  - `test_a_subscripted_base_is_unwrapped`
  - `test_several_files_report_together_and_fail_once`

  Restore with `git -C <wt> checkout -- scripts/check_read_only_fields.py` only if the script is already committed; otherwise re-copy Appendix A. Re-run and confirm `OK`.

- [ ] **Task 4 — the ledger.** In `metrics/curated/defects.yml`, on line `:24` only, replace the literal `test: tests/test_no_class_body_read_only_fields.py` with `test: tests/test_read_only_fields_guard.py` (exactly one occurrence; Appendix F.1). The live hook runs the metrics checks.
  Verify:
  ```bash
  cd <wt> && python3 -m metrics.build --validate-only; echo "exit=$?"
  ```
  Expected: `exit=0`. If `python3` lacks the build's dependency, run the commit gate's own command, exactly as `pre-commit-tests.sh:225-226` has it: `.venv/bin/python -m metrics.build --validate-only --curated metrics/curated`. `scripts/run_metrics_tests.sh build` is only a second, indirect check: it runs the build-step unit tests (`run_metrics_tests.sh:42-44`), which catch a stale `test:` path only through `metrics/build/tests/test_real_curated.py:30-32`.

- [ ] **Task 5 — delete the old test.** Run `git -C <wt> rm tests/test_no_class_body_read_only_fields.py`, then re-run the Task 4 command, expecting `exit=0`. Then check that nothing else references it:
  ```bash
  cd <wt> && git grep -n test_no_class_body_read_only_fields -- . ':!docs/superpowers/plans'
  ```
  Expected: no output. `git grep` exits 1 here, which is correct: an empty result from a query that ran.

- [ ] **Task 6 — the hook arm.** Apply **Appendix C** with `git -C <wt> apply --whitespace=error <scratch>/C.diff`, then run `bash -n <wt>/.claude/hooks/run-affected-tests.sh`, expecting no output.

- [ ] **Task 7 — the hook harness, and the real-module break-check.** Apply **Appendix D** the same way.
  Verify:
  ```bash
  bash <wt>/.claude/hooks/tests/test_hooks.sh | tail -1
  ```
  Expected: `22 passed, 0 failed` (19 existing cases plus 3 new).
  **Break-check 2 (the harness sees the arm).** Build a copy of the hooks whose `run-affected-tests.sh` is the seed's:
  ```bash
  BC=<scratch>/bc && rm -rf "$BC" && mkdir -p "$BC/.claude" && cp -R <wt>/.claude/hooks "$BC/.claude/" && cp -R <wt>/scripts "$BC/scripts" && git -C <wt> show "36e4ce10:.claude/hooks/run-affected-tests.sh" > "$BC/.claude/hooks/run-affected-tests.sh" && HOOK_DIR="$BC/.claude/hooks" bash <wt>/.claude/hooks/tests/test_hooks.sh | grep -E '^FAIL|passed'
  ```
  Expected (measured): `FAIL test_edit_hook_blocks_a_class_body_read_only_fields`, `FAIL test_edit_hook_says_so_when_the_read_only_guard_is_missing`, `20 passed, 2 failed`.
  **Break-check 3 (the real wrong edit, caught by the hook).** In `apps/epg/serializers.py`, move line `:45` (`        read_only_fields = ['created_at', 'updated_at']`, inside `EPGSourceSerializer.Meta`) up into the class body. It goes directly after `:20` (`    cron_expression = …`), dedented to four spaces, so it becomes line 21 above `class Meta:`. Then invoke **your worktree's** hook as the harness does:
  ```bash
  cd <wt> && jq -cn --arg f "$PWD/apps/epg/serializers.py" '{tool_input:{file_path:$f}}' | env -u CLAUDE_HOOK_REPO_ROOT DISPATCHARR_TEST_CONTAINER=hooktest-absent bash .claude/hooks/run-affected-tests.sh; echo "exit=$?"
  ```
  Expected (measured on the prototype), on stderr, then `exit=2`:
  ```
  FAILED: class-body read_only_fields in apps/epg/serializers.py
  Fix this before continuing; do not describe the work as done.

  apps/epg/serializers.py:21: read_only_fields assigned in the body of serializer class EPGSourceSerializer, where DRF never reads it -- move it into EPGSourceSerializer.Meta

  DRF reads read_only_fields from the serializer's Meta only. Move the assignment into that class's 'class Meta:'. A subclass that inherits its parent's Meta declares its own as 'class Meta(Parent.Meta):'.
  ```
  The whole-tree CI command from Task 1 must print the same `apps/epg/serializers.py:21: …` line and exit non-zero. BSD `xargs` (macOS) exits 1 and GNU `xargs` (the CI runner) exits 123; both fail the step. Restore with `git -C <wt> checkout -- apps/epg/serializers.py` and confirm `git -C <wt> status --short apps/epg/` is empty. Note that the live hook (constraint 5) also fires on this edit. It does not carry the new arm, so it will not block; that is expected and is the reason this break-check invokes the worktree copy.

- [ ] **Task 8 — `lint.yml`.** Apply **Appendix E**. The live hook runs zizmor on the file and must report zero findings (CLAUDE.md § Test hooks: a blocking ratchet).
  Also run:
  ```bash
  cd <wt> && actionlint -shellcheck= -pyflakes= .github/workflows/lint.yml; echo "exit=$?"
  ```
  Expected: `exit=0`. Then simulate the job's two steps locally:
  ```bash
  cd <wt> && bash -c 'set -euo pipefail; python3 -m unittest tests.test_read_only_fields_guard 2>&1 | tail -1; git ls-files -z "*.py" | xargs -0 python3 ./scripts/check_read_only_fields.py; echo clean'
  ```
  Expected: `OK` then `clean`.

- [ ] **Task 9 — CLAUDE.md, then the whole-PR checks.** In `CLAUDE.md` line `:57`, replace the literal ``any `*.py` (`scripts/check_credential_logging.py`)`` with ``any `*.py` (`scripts/check_credential_logging.py`, `scripts/check_read_only_fields.py`)``. There is exactly one occurrence (Appendix F.2). Then:
  1. `cd <wt> && set -o pipefail && git diff --name-only --diff-filter=ACMR origin/main -- '*.py' | xargs python3 scripts/check_credential_logging.py; echo $?`, expecting `0`. `--diff-filter=ACMR` leaves out the deleted file, as `lint.yml:134` does.
  2. `cd <wt> && git diff --name-only origin/main | python3 scripts/ci_backend_test_labels.py`, expecting `["tests"]`.
  3. In the container (constraint 6): `docker exec … manage.py test tests --keepdb -v1` (the hook's own `dexec` environment, `run-affected-tests.sh:117-124`). Expected: `OK`. Record the test count: the label loses 1 test and gains 17, so it should be 16 higher than the same label at the seed. Measure the seed count once in the same container before Task 3 if you want the delta exact.
  4. `bash <wt>/.claude/hooks/tests/test_hooks.sh | tail -1`, expecting `22 passed, 0 failed`.

- [ ] **Task 10 — commit, push, PR.** One commit, subject `ci(lint): run the read_only_fields-in-Meta rule on the edit that breaks it (#444)`. Stage and commit in separate calls (constraint 7); the gate runs `tests` and the metrics validator. Push and open a **draft** PR with the body below. Once CI runs, confirm the `Lint` workflow's new `read_only_fields in Meta` job is green **by reading it**: it is not a required check (finding 6), so a red run would not block the merge.

**Tests added:** `tests/test_read_only_fields_guard.py` (17 cases), and three cases in `.claude/hooks/tests/test_hooks.sh`. **Tests removed:** `tests/test_no_class_body_read_only_fields.py` (1 case), superseded as Decision 4 says.

### PR description draft (implementation PR)

> **ci(lint): run the read_only_fields-in-Meta rule on the edit that breaks it (#444)**
>
> The class-body `read_only_fields` guard from #436 was a test under the `tests` label. No serializers module routes to that label, so it never ran on the edit that introduced the mistake; it would have failed on some later, unrelated PR instead. The rule is now `scripts/check_read_only_fields.py`, run like `scripts/check_credential_logging.py`:
> - by the `*.py` `PostToolUse` edit hook on the file just edited (blocking);
> - by a new `lint.yml` job, `read_only_fields in Meta`, over **every tracked `*.py`**. The tree has zero findings, so there is no backlog to exempt.
>
> The same job runs the script's own unit tests with a bare `python3 -m unittest`, because `scripts/` routes to no backend label.
>
> The class filter now also catches the three shapes from #444's comments: a subclass of a same-module serializer with no `Meta` of its own (followed transitively), a base imported under an alias, and a subscripted base. It also reads serializers defined outside `*serializers.py` (`apps/proxy/authorize_views.py`, `apps/timeshift/api_views.py`), which the old test's glob skipped. `tests/test_no_class_body_read_only_fields.py` is deleted, and the defect ledger's `read-only-fields-misplaced` row points at the new test.
>
> Closes #444.
>
> Evidence:
> - Whole tree: <paste Task 1>.
> - The old filter vs the new one on the three shapes: <paste Task 2>.
> - Unit tests: <paste Task 3>. Break-check 1: <paste the 4 failures>.
> - Hook harness: <paste 22/22>. Break-check 2 against the seed hook: <paste 20 passed, 2 failed>.
> - Break-check 3 (EPGSourceSerializer's list moved into the class body, caught by the worktree's hook): <paste>.
> - zizmor / actionlint on `lint.yml`: <paste>.
> - `tests` label: <paste>.
>
> The new job, like `credential logging`, is not a required check; making it one is a ruleset setting.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

---

## Open questions (for the user; none blocks the implementation)

- **Q1.** Should `read_only_fields in Meta` (and `credential logging`, which has the same status) become a required check on the Main ruleset? Today neither is, so both can be merged red. This PR keeps a live-tree case under the required `Backend result` as the backstop, which re-creates the old "fails on a later PR" behaviour only if a red lint job is ignored. Default: leave the settings alone.

## Not verified by the planner

- The new module was run under bare `python3 -m unittest` (17/17 OK, Python 3.13.2), not under Django's runner in the test container: the shared container was not re-pointed at the planner's worktree (constraint 6). Task 9.3 is the first run under `manage.py test tests`.
- zizmor ran online (`GH_TOKEN` from `gh auth token`) at version 1.30.1; the hook's pinned version is checked against `actions-lint.yml` by the hook itself.
- The metrics validator was run on a `git archive` copy with no git history. The defect checks passed there; the milestone first-parent checks can only pass in a real worktree (Task 4).

---

## Appendix A — `scripts/check_read_only_fields.py` (new file, verbatim; mode 100755)

````python
#!/usr/bin/env python3
"""Fail on `read_only_fields` declared where DRF never reads it.

WHY THIS EXISTS (#15, #436, #444). `serializers.ModelSerializer` consults
`Meta.read_only_fields` only. The same name assigned directly in the
serializer's class body -- a sibling of `class Meta`, not a member of it -- is
an ordinary class attribute DRF never looks at, so the fields it names stay
writable over the API. Neither DRF nor any other linter here warns about it,
and the mistake recurred independently at four call sites across three apps
(`M3UAccountSerializer`, `EPGSourceSerializer`, `EPGDataSerializer`,
`StreamSerializer`) before #436 moved them into `Meta`.

WHY A LINT AND NOT A TEST (#444). #436 shipped this rule as
`tests/test_no_class_body_read_only_fields.py`, under the `tests` label. No
serializers module routes to that label, so the guard never ran on the edit
that introduced the mistake and failed instead on some later, unrelated pull
request. As a script it runs where the credential-logging check runs: on the
file just edited (the `*.py` arm of .claude/hooks/run-affected-tests.sh) and
over every tracked `*.py` in CI (lint.yml's `read-only-fields` job),
independent of label routing.

WHAT IS A SERIALIZER CLASS. A class, anywhere in the module (nested ones
included), other than one named `Meta`, is judged a serializer when any of:

  * it has a nested `class Meta`;
  * a base, after unwrapping any subscript (`ModelSerializer[int]` ->
    `ModelSerializer`) and resolving a `from X import Y as Z` alias (`Z` ->
    `Y`), has a trailing identifier ending in `Serializer`
    (`serializers.ModelSerializer`, `ListSerializer`, an imported
    `ChannelSerializer`, `MS` after `import ModelSerializer as MS`);
  * a base is the name of a class defined in the same module that is itself a
    serializer by these rules -- followed transitively, so `class Y(MyBase):`
    counts when `MyBase` does, although `Y` has no `Meta` of its own and
    inherits its parent's.

WHAT COUNTS AS A FINDING. A `read_only_fields = ...` or annotated
`read_only_fields: ... = ...` assignment made directly in such a class's own
body. The identical assignment inside the class's `class Meta:` is correct and
is never reached: a class named `Meta` is never judged.

KNOWN LIMITS.

  * A base defined in ANOTHER module whose name does not end in `Serializer`
    (`from .base import MyBase`) is not followed; only same-module bases are.
  * Classes are matched by name, so two classes of the same name in one
    module (in different functions, say) are judged together: if either is a
    serializer, both are examined.
  * A tuple target (`read_only_fields, x = ...`), an augmented assignment and
    a `setattr()` are not examined. None is a plausible way to write this.

There is no ignore marker: DRF never reads a class-body `read_only_fields`, so
no instance of one is correct and none needs an exemption.

Usage:  scripts/check_read_only_fields.py <file.py> [<file.py> ...]
Exit:   0 = no findings (or no Python files given)
        1 = at least one finding, printed as "file:line: message"

Arguments not ending in `.py` are skipped. Files that do not exist, or that
cannot be read, decoded or parsed, produce a warning on stderr and do not by
themselves change the exit status -- the same contract as
scripts/check_credential_logging.py.
"""

import ast
import sys

SUFFIX = "Serializer"


def _import_aliases(tree):
    """Map each `from X import Y as Z` local name Z to Y (Z != Y only)."""
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.asname and alias.asname != alias.name:
                    aliases[alias.asname] = alias.name
    return aliases


def _base_name(base, aliases):
    """The trailing identifier a base-class expression names, or None.

    `serializers.ModelSerializer` -> `ModelSerializer`; `ModelSerializer[int]`
    -> `ModelSerializer`; `MS` -> `ModelSerializer` when imported under that
    alias.
    """
    while isinstance(base, ast.Subscript):
        base = base.value
    if isinstance(base, ast.Attribute):
        return base.attr
    if isinstance(base, ast.Name):
        return aliases.get(base.id, base.id)
    return None


def _has_nested_meta(node):
    return any(
        isinstance(child, ast.ClassDef) and child.name == "Meta" for child in node.body
    )


def _serializer_class_names(classes, aliases):
    """Names of the module's classes that are serializers, to a fixed point."""
    serializers = set()
    changed = True
    while changed:
        changed = False
        for node in classes:
            if node.name in serializers:
                continue
            names = [_base_name(base, aliases) for base in node.bases]
            if (
                _has_nested_meta(node)
                or any((name or "").endswith(SUFFIX) for name in names)
                or any(name in serializers for name in names)
            ):
                serializers.add(node.name)
                changed = True
    return serializers


def _class_body_read_only_fields(node):
    """Yield the line of each `read_only_fields` assigned in `node`'s own body."""
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
        elif isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "read_only_fields":
                yield stmt.lineno


def check_file(path, out=sys.stdout, err=sys.stderr):
    """Print every class-body `read_only_fields` in `path`. Return the count."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
    except FileNotFoundError:
        print(f"warning: {path}: no such file, not checked", file=err)
        return 0
    except (OSError, ValueError) as exc:
        # UnicodeDecodeError is a ValueError, not an OSError.
        print(f"warning: {path}: could not read ({exc}), not checked", file=err)
        return 0

    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as exc:
        # ValueError as well: ast.parse raises it for a null byte.
        print(f"warning: {path}: could not parse ({exc}), not checked", file=err)
        return 0

    classes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name != "Meta"
    ]
    serializers = _serializer_class_names(classes, _import_aliases(tree))

    findings = []
    for node in classes:
        if node.name not in serializers:
            continue
        for lineno in _class_body_read_only_fields(node):
            findings.append(
                (
                    lineno,
                    f"read_only_fields assigned in the body of serializer class "
                    f"{node.name}, where DRF never reads it -- move it into "
                    f"{node.name}.Meta",
                )
            )

    for lineno, message in sorted(findings):
        print(f"{path}:{lineno}: {message}", file=out)

    return len(findings)


def main(argv):
    total = 0
    for path in argv:
        if not path.endswith(".py"):
            continue
        total += check_file(path)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
````

## Appendix B — `tests/test_read_only_fields_guard.py` (new file, verbatim)

````python
"""Tests for scripts/check_read_only_fields.py.

The script replaced tests/test_no_class_body_read_only_fields.py (#444), which
never ran on the serializers edit it guarded against. These tests pin the
script's contract -- exit codes and the "file:line: message" format -- by
running it as a subprocess, the way the edit hook and lint.yml invoke it, and
pin the three class shapes the old guard's filter missed (#444's comments): a
subclass of a local serializer base with no Meta of its own, a base imported
under an alias, and a subscripted base.

A plain unittest.TestCase with no Django import, so lint.yml's
`read-only-fields` job can run it with a bare `python3 -m unittest` on every
pull request, independent of which backend labels the diff selects.
"""

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "scripts" / "check_read_only_fields.py"

CLASS_BODY = '''
from rest_framework import serializers


class StreamSerializer(serializers.ModelSerializer):
    read_only_fields = ["id"]

    class Meta:
        fields = ["id", "name"]
'''

IN_META = '''
from rest_framework import serializers


class StreamSerializer(serializers.ModelSerializer):
    class Meta:
        fields = ["id", "name"]
        read_only_fields = ["id"]
'''

ANNOTATED = '''
from rest_framework import serializers


class StreamSerializer(serializers.ModelSerializer):
    read_only_fields: list = ["id"]
'''

NESTED_META_ONLY = '''
class Thing:
    read_only_fields = ["id"]

    class Meta:
        fields = ["id"]
'''

# A shared helper meant to be inherited by a Meta: neither a Meta of its own
# nor a serializer base, so it is not a serializer class body.
HELPER_BASE_META = '''
class BaseMeta:
    read_only_fields = ["id"]


class NotASerializer:
    read_only_fields = ["id"]
'''

# #444 comment, shape 1: Y inherits MyBase's Meta and has none of its own.
LOCAL_BASE_TRANSITIVE = '''
from rest_framework import serializers


class MyBase(serializers.ModelSerializer):
    class Meta:
        fields = ["id"]


class Middle(MyBase):
    pass


class Y(Middle):
    read_only_fields = ["id"]
'''

# #444 comment, shape 2.
ALIASED_BASE = '''
from rest_framework.serializers import ModelSerializer as MS


class Z(MS):
    read_only_fields = ["id"]
'''

# #444 comment, shape 3.
SUBSCRIPTED_BASE = '''
from rest_framework import serializers


class W(serializers.ModelSerializer[int]):
    read_only_fields = ["id"]
'''

NESTED_CLASS = '''
from rest_framework import serializers


def build():
    class Inner(serializers.Serializer):
        read_only_fields = ["id"]

    return Inner
'''

BROKEN_SYNTAX = '''
class Broken(:
'''


class ReadOnlyFieldsGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = Path(self._tmp.name)

    def write(self, name, source):
        path = self.tmpdir / name
        path.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
        return path

    def run_guard(self, *paths):
        return subprocess.run(
            [sys.executable, str(GUARD), *[str(p) for p in paths]],
            capture_output=True,
            text=True,
            check=False,
        )

    def assert_one_finding(self, source, lineno, class_name):
        path = self.write("serializers.py", source)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout,
            f"{path}:{lineno}: read_only_fields assigned in the body of "
            f"serializer class {class_name}, where DRF never reads it -- "
            f"move it into {class_name}.Meta\n",
        )

    def assert_clean(self, source):
        path = self.write("serializers.py", source)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_guard_script_exists(self):
        self.assertTrue(GUARD.is_file(), f"{GUARD} is missing")

    def test_class_body_read_only_fields_is_reported(self):
        self.assert_one_finding(CLASS_BODY, 5, "StreamSerializer")

    def test_read_only_fields_in_meta_is_clean(self):
        self.assert_clean(IN_META)

    def test_annotated_assignment_is_reported(self):
        self.assert_one_finding(ANNOTATED, 5, "StreamSerializer")

    def test_a_nested_meta_alone_makes_a_class_a_serializer(self):
        self.assert_one_finding(NESTED_META_ONLY, 2, "Thing")

    def test_a_class_with_neither_trait_is_clean(self):
        self.assert_clean(HELPER_BASE_META)

    def test_a_subclass_of_a_local_serializer_is_followed_transitively(self):
        self.assert_one_finding(LOCAL_BASE_TRANSITIVE, 14, "Y")

    def test_a_base_imported_under_an_alias_is_resolved(self):
        self.assert_one_finding(ALIASED_BASE, 5, "Z")

    def test_a_subscripted_base_is_unwrapped(self):
        self.assert_one_finding(SUBSCRIPTED_BASE, 5, "W")

    def test_a_class_nested_in_a_function_is_examined(self):
        self.assert_one_finding(NESTED_CLASS, 6, "Inner")

    def test_several_files_report_together_and_fail_once(self):
        bad = self.write("bad.py", CLASS_BODY)
        aliased = self.write("aliased.py", ALIASED_BASE)
        clean = self.write("clean.py", IN_META)
        result = self.run_guard(clean, bad, aliased)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 2, result.stdout)
        self.assertIn(f"{bad}:5:", result.stdout)
        self.assertIn(f"{aliased}:5:", result.stdout)
        self.assertNotIn(str(clean), result.stdout)

    def test_non_python_arguments_are_skipped(self):
        path = self.tmpdir / "notes.txt"
        path.write_text(textwrap.dedent(CLASS_BODY), encoding="utf-8")
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")

    def test_missing_file_warns_on_stderr_and_does_not_fail(self):
        missing = self.tmpdir / "gone.py"
        result = self.run_guard(missing)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("no such file", result.stderr)
        self.assertIn(str(missing), result.stderr)

    def test_unparseable_file_warns_on_stderr_and_does_not_fail(self):
        path = self.write("broken.py", BROKEN_SYNTAX)
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("could not parse", result.stderr)

    def test_non_utf8_file_warns_on_stderr_and_does_not_fail(self):
        path = self.tmpdir / "latin1.py"
        path.write_bytes(b"class Caf\xe9Serializer:\n    read_only_fields = []\n")
        result = self.run_guard(path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("could not read", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_no_arguments_is_clean(self):
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_the_app_and_core_trees_are_clean(self):
        # A live ratchet, not a fixture: every module the old test scanned,
        # plus the two that define serializers outside a serializers module
        # (apps/proxy/authorize_views.py, apps/timeshift/api_views.py).
        targets = sorted(REPO.glob("apps/**/*.py")) + sorted(REPO.glob("core/**/*.py"))
        self.assertIn(REPO / "core" / "serializers.py", targets)
        self.assertIn(REPO / "apps" / "timeshift" / "api_views.py", targets)
        result = self.run_guard(*targets)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
````

## Appendix C — `.claude/hooks/run-affected-tests.sh` (against `36e4ce10`)

The header row and ratchet paragraph (`:15-21`), and the new arm directly after the `secrets` arm (`:125-145`).

````diff
--- a/.claude/hooks/run-affected-tests.sh
+++ b/.claude/hooks/run-affected-tests.sh
@@ -13,12 +13,14 @@
 #   lint         frontend/*.js(x)     eslint that file        (advisory)
 #   actions      workflows/action.yml zizmor, whole file      (blocking)
 #   secrets      any *.py             check_credential_logging.py (blocking)
+#   read-only    any *.py             check_read_only_fields.py   (blocking)
 #
-# All but zizmor, typecheck and secrets are deliberately independent of the
-# repo's pre-existing backlog. Those three are ratchets: they hold the whole
-# edited file (or package) clean, because there is nothing to tolerate — the
-# workflow backlog was worked off, both e2e packages typecheck clean, and the
-# five log calls that leaked provider credentials now redact.
+# All but zizmor, typecheck, secrets and read-only are deliberately
+# independent of the repo's pre-existing backlog. Those four are ratchets:
+# they hold the whole edited file (or package) clean, because there is nothing
+# to tolerate — the workflow backlog was worked off, both e2e packages
+# typecheck clean, the five log calls that leaked provider credentials now
+# redact, and #436 moved every class-body read_only_fields into Meta.
 #
 # Backend work happens in a warm local container (see start-test-container.sh).
 # Real PostgreSQL is required: a migration uses the PG-only `~` regex operator,
@@ -144,6 +146,29 @@
   fi
 fi
 
+# -------------------------------------------------------------- read-only ---
+# DRF reads read_only_fields from a serializer's Meta only; the same name
+# assigned in the class body is an ordinary attribute DRF ignores, so the
+# fields it names stay writable (#15). #436 moved the four that existed into
+# Meta and guarded the rule with a test under the `tests` label — which no
+# serializers module routes to, so it never ran on the edit that broke it
+# (#444). This runs it on the edit itself; lint.yml runs the same script over
+# every tracked *.py.
+if [[ "$REL" == *.py ]]; then
+  READ_ONLY_GUARD="scripts/check_read_only_fields.py"
+  if [ ! -f "$READ_ONLY_GUARD" ]; then
+    note "Did NOT check ${REL} for class-body read_only_fields — ${READ_ONLY_GUARD} is missing."
+  elif ! command -v python3 >/dev/null 2>&1; then
+    note "Did NOT check ${REL} for class-body read_only_fields — python3 is not on PATH."
+  else
+    OUT="$(python3 "$READ_ONLY_GUARD" "$REL" 2>&1)"
+    if [ $? -ne 0 ]; then
+      block "class-body read_only_fields in ${REL}" \
+            "$(printf '%s' "$OUT" | head -20)"$'\n\n'"DRF reads read_only_fields from the serializer's Meta only. Move the assignment into that class's 'class Meta:'. A subclass that inherits its parent's Meta declares its own as 'class Meta(Parent.Meta):'."
+    fi
+  fi
+fi
+
 # ------------------------------------------------------------- migrations ---
 if [[ "$REL" == */models.py || "$REL" == models.py ]]; then
   MOD="${REL%/models.py}"; MOD="${MOD//\//.}"
````

## Appendix D — `.claude/hooks/tests/test_hooks.sh` (against `36e4ce10`)

`SCRIPTS_DIR` beside `EDIT` (`:25`); three cases before the summary (`:107`). Repo C gets both check scripts; repo B (no `scripts/`) gives the "missing" case.

````diff
--- a/.claude/hooks/tests/test_hooks.sh
+++ b/.claude/hooks/tests/test_hooks.sh
@@ -23,6 +23,8 @@
 HOOK_DIR="${HOOK_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
 GATE="$HOOK_DIR/pre-commit-tests.sh"
 EDIT="$HOOK_DIR/run-affected-tests.sh"
+# The *.py check scripts beside this copy of the hooks, for the read-only arm.
+SCRIPTS_DIR="$(cd "$HOOK_DIR/../.." && pwd)/scripts"
 
 TMP="$(mktemp -d)"
 trap 'rm -rf "$TMP"' EXIT
@@ -103,6 +105,24 @@
 check "control_edit_hook_is_quiet_under_a_valid_override" 0 EMPTY $st "$out"
 out="$(edit "$TMP/not-in-a-repo.txt")"; st=$?
 check "control_edit_hook_is_quiet_outside_any_repo" 0 NONOTE $st "$out"
+# ---- #444: the read-only arm -----------------------------------------------
+# Repo C carries both *.py check scripts, so an edited *.py there reaches the
+# read-only arm with no "is missing" note from either; repo B carries neither,
+# so the read-only arm's own "is missing" note is what it prints.
+C="$TMP/repo-c"
+git init -q "$C"
+git -C "$C" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
+mkdir -p "$C/scripts" "$C/apps/x"
+cp "$SCRIPTS_DIR/check_credential_logging.py" "$SCRIPTS_DIR/check_read_only_fields.py" "$C/scripts/"
+printf 'class S(ModelSerializer):\n    read_only_fields = ["id"]\n' > "$C/apps/x/bad.py"
+printf 'class S(ModelSerializer):\n    class Meta:\n        read_only_fields = ["id"]\n' > "$C/apps/x/good.py"
+printf 'x = 1\n' > "$B/plain.py"
+out="$(edit "$C/apps/x/bad.py")"; st=$?
+check "test_edit_hook_blocks_a_class_body_read_only_fields" 2 "class-body read_only_fields in apps/x/bad.py" $st "$out"
+out="$(edit "$C/apps/x/good.py")"; st=$?
+check "control_edit_hook_is_quiet_on_read_only_fields_in_meta" 0 EMPTY $st "$out"
+out="$(edit "$B/plain.py")"; st=$?
+check "test_edit_hook_says_so_when_the_read_only_guard_is_missing" 0 "for class-body read_only_fields — scripts/check_read_only_fields.py is missing" $st "$out"
 
 printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
 [ "$FAIL" -eq 0 ]
````

## Appendix E — `.github/workflows/lint.yml` (against `36e4ce10`)

A new job between `credential-logging` (`:92-141`) and `lockfile-fresh` (`:143`). The checkout pin is copied from `:96`.

````diff
--- a/.github/workflows/lint.yml
+++ b/.github/workflows/lint.yml
@@ -140,6 +140,32 @@
           printf '  %s\n' "$@"
           python3 ./scripts/check_credential_logging.py "$@"
 
+  read-only-fields:
+    name: read_only_fields in Meta
+    runs-on: ubuntu-latest
+    steps:
+      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
+        with:
+          persist-credentials: false
+
+      - name: unit tests of the check
+        # Plain unittest with no Django import, so it runs here on every pull
+        # request whatever backend labels the diff selects -- the routing gap
+        # that kept the test this replaced from ever running on the edit it
+        # guarded (#444).
+        run: python3 -m unittest -v tests.test_read_only_fields_guard
+
+      - name: check every tracked Python file
+        # Mirrors the *.py arm of .claude/hooks/run-affected-tests.sh, which
+        # runs the same script on the file just edited. Unlike the
+        # credential-logging job this checks the whole tree rather than the
+        # changed files: the tree has no finding to exempt (#436 moved the
+        # last one into Meta), and a whole-tree run needs no diff base to get
+        # wrong.
+        run: |
+          set -euo pipefail
+          git ls-files -z '*.py' | xargs -0 python3 ./scripts/check_read_only_fields.py
+
   lockfile-fresh:
     name: uv.lock freshness
     runs-on: ubuntu-latest
````

## Appendix F — one-field and one-phrase replacements

Each literal occurs exactly once at `36e4ce10`; replace it with the Edit tool.

**F.1 `metrics/curated/defects.yml:24`**

- old: `test: tests/test_no_class_body_read_only_fields.py`
- new: `test: tests/test_read_only_fields_guard.py`

**F.2 `CLAUDE.md:57`**

- old: ``any `*.py` (`scripts/check_credential_logging.py`)``
- new: ``any `*.py` (`scripts/check_credential_logging.py`, `scripts/check_read_only_fields.py`)``

## Appendix G — how the appendices were verified

On a fresh `git archive 36e4ce10` tree in the planner's scratch directory:
- `git apply --check --whitespace=error` accepted C, D and E together, and they were then applied.
- A and B were copied in, the old test was removed and F.1 was made.
- `bash .claude/hooks/tests/test_hooks.sh` gave `22 passed, 0 failed`.
- `python3 -m unittest tests.test_read_only_fields_guard` gave 17 tests, `OK`.
- Both check scripts run on A and B gave exit 0.
- zizmor 1.30.1 (online) and actionlint ran on the edited `lint.yml` with zero findings.
- The prototype script over all 614 tracked `*.py` of the seed worktree gave exit 0 with no output.
- Break-checks 1, 2 and 3 were measured as quoted in Tasks 3 and 7.
