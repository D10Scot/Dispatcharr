# Project specifics: Dispatcharr (D10Scot/Dispatcharr)

Rewrite this file when porting the skill. `SKILL.md` is generic; this file names this repository.

## Tests, the way CI runs them

- **Python:** labels from `python scripts/ci_backend_test_labels.py` (read its usage). Run in your own container: `DISPATCHARR_TEST_CONTAINER=<name> DISPATCHARR_TEST_DB_VOLUME=<name>-db CLAUDE_HOOK_REPO_ROOT=<worktree> <worktree>/.claude/hooks/start-test-container.sh`, then run labels the way `.claude/hooks/run-affected-tests.sh` does (Redis flushed first, whole package). Run every label once **without** `--keepdb` before pushing: a test on a migration-seeded row passes under keepdb and fails on CI's fresh database. The shared `dispatcharr-testrunner` hook refuses on a mount mismatch; that message is expected in a worktree, and the labels are then run by hand.
- **Gate 2 (Python coverage ratchet):** if the change touches a module listed in `scripts/coverage_live_path.coveragerc`, run `scripts/coverage_live_path_isolated.sh --gate` (read its header). Floor `missing=33`; no tolerance parameter.
- **Go:** the `PostToolUse` hook runs build, vet, lint and `test -race` on every `.go` edit. Before pushing: `cd <worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./... && GOOS=linux golangci-lint run ./...`, then from `<worktree>`: `scripts/check_go_stdlib_only.sh relay` and `scripts/check_go_credential_logging.sh relay`. The Go coverage ratchet has **no headroom** (floor `missing=589`): `scripts/coverage_relay_go.sh --gate` must pass. A draw above the floor is a finding to investigate, and the fix is a re-measurement PR of its own, never a floor bump on the PR that drew it.
- **Frontend:** `cd <worktree>/frontend && npm ci && npm test`.
- **E2E specs:** on every edit under `e2e/**` or `e2e-upstream/**`, comments and strings included: `npx tsc --noEmit` and `npx playwright test --project=guards` (static guards: allowlists, tags, string-literal scans, parity-matrix citations). A full Playwright run only when the plan section requires it, on a private stack with a private image tag (see `worktree-per-change`).
- **Every `.py` edit** runs `scripts/check_credential_logging.py`; keep it clean.
- **Metrics:** `metrics/**` and `scripts/metrics/**` run `scripts/run_metrics_tests.sh` and `python -m metrics.build --validate-only`. Never export `GIT_DIR`/`GIT_WORK_TREE` into that script (#489).

## Commits and PRs

- Stage and commit in separate Bash calls: the commit gate is a `PreToolUse` hook that runs before the command and blocks a call doing both. Write the message to a file (the Write tool, or a heredoc when Write is refused for that path) and commit with `git commit -F <file>`; the gate matches on command text, so a message that names staging and committing together trips it. End every message with the `Co-Authored-By` attribution line the harness supplies for the model that wrote it.
- **The PR opens as a draft and stays a draft until the internal review passes:** `gh pr create --repo D10Scot/Dispatcharr --draft --base main --title "<title>" --body-file <file>`; body from the plan's PR-description draft with placeholders filled, one `Closes #N.` per issue, ending `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. The implementer never marks it ready. Reason: the pr-review bot reviews each PR **once**, on the first non-draft head it sees, and never again unless its review is dismissed; a PR opened ready spends that review on the unreviewed head and every fix round after it lands without a bot pass. Marking ready is `pr-merge-gate`'s first action after the internal PASS, so the bot reviews the head that merges. A `fixed_in: <this PR>` placeholder in `metrics/curated/defects.yml` cannot be committed before the PR number exists: code commit → `gh pr create` → ledger commit.
- The `--repo D10Scot/Dispatcharr` flag on every `gh` call; without it `gh` resolves to the upstream tracker.

## Documents a section may require

`docs/relay-parity-matrix.md` rows for live-path behaviour, `metrics/curated/defects.yml` (validated with `python -m metrics.build --validate-only`), CLAUDE.md figures the change moves, `e2e/COVERAGE.md` in the same PR as new e2e tests.

## Ledger

The orchestrator keeps a ledger in its scratchpad (`impl/ledger.md`): one row per PR with branch, worktree, status, PR number, reviewed SHA, round count, closes list; incidents and follow-ups below it. Escalation reads the round count from here.

## Models available

`sonnet` (implementers only), `opus` (planning, stuck implementers, and reviews when fable is rationed), `fable` (the default reviewer per CLAUDE.md § Delegation). **Current cadence, set by the user for the 2026-09 fix programme to conserve fable credits:** `opus` reviews rounds one and two, `fable` reviews from the third round on, and a security-adjacent change gets `fable` from round one. The D-1 and G-9 reviews on 2026-09-25 each found blockers two opus rounds had missed, which is why the escalation is a rule rather than an option. When fable credits are not rationed, CLAUDE.md's default (fable from round one) applies.
