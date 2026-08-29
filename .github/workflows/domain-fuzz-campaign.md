---
description: Fuzz one application domain per run; contribute permanent property tests and raise typed, prioritized bug issues.
emoji: 🧪
on:
  schedule: every 12 hours
  workflow_dispatch:
    inputs:
      max_rounds:
        description: Maximum fuzzing rounds for this run (1-4)
        required: false
        default: "3"
        type: choice
        options: ["1", "2", "3", "4"]
  stop-after: "+90d"
permissions:
  contents: read
  issues: read
  pull-requests: read
# Kimi K3: gpt-5.6-sol runs were killed mid-turn by OpenAI's cybersecurity
# classifier (HTTP 422, TAC program gate) — security-probing vocabulary is the
# trigger, and retries hit the same verdict. Kimi is on the proxy allowlist
# and has no such filter.
model: kimi-k3
timeout-minutes: 45
features:
  group-concurrency-queue: false
concurrency:
  group: domain-fuzz-campaign
  cancel-in-progress: false
tools:
  github:
    mode: gh-proxy
    toolsets: [default]
  cache-memory: true
network:
  allowed:
    - defaults
    - python
    - node
steps:
  - name: Set up Python 3.13
    uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
    with:
      python-version: "3.13"
  - name: Set up uv
    uses: astral-sh/setup-uv@v10.0.1
    with:
      enable-cache: true
      cache-suffix: domain-fuzz
  - name: Install backend dependencies into .venv
    run: |
      set -euo pipefail
      # Dev group included: Hypothesis (property-based testing) lives there.
      uv sync --locked --no-install-project --python "$(command -v python)"
      # Smoke-check the venv boots Django with the test settings the agent will use.
      DJANGO_SECRET_KEY=fuzz-campaign TEST_USE_SQLITE=1 DJANGO_SETTINGS_MODULE=dispatcharr.settings_test \
        .venv/bin/python -c "import django; django.setup(); print('django', django.get_version(), 'ok')"
      # Tolerant probe: absent until the Hypothesis dep PR lands, present after.
      if .venv/bin/python -c "import hypothesis" 2>/dev/null; then
        echo "HYPOTHESIS_AVAILABLE=1" >> "$GITHUB_ENV"
      else
        echo "HYPOTHESIS_AVAILABLE=0" >> "$GITHUB_ENV"
      fi
  - name: Stage Redis binaries for the agent sandbox
    run: |
      set -euo pipefail
      if ! command -v redis-server >/dev/null 2>&1; then
        sudo apt-get update -qq
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends redis-server redis-tools
      fi
      mkdir -p .fuzz-env/bin
      cp "$(command -v redis-server)" "$(command -v redis-cli)" .fuzz-env/bin/
      .fuzz-env/bin/redis-server --version
  - name: Export runtime environment for the agent
    run: |
      set -euo pipefail
      {
        echo "DJANGO_SECRET_KEY=fuzz-campaign"
        echo "TEST_USE_SQLITE=1"
        echo "DISPATCHARR_LOG_LEVEL=WARNING"
      } >> "$GITHUB_ENV"
pre-agent-steps:
  - name: Select least-recently-fuzzed domain
    id: select_domain
    run: |
      set -euo pipefail
      python3 - <<'PY' >> "$GITHUB_ENV"
      import json, os, datetime, pathlib

      MEM = pathlib.Path("/tmp/gh-aw/cache-memory")
      MEM.mkdir(parents=True, exist_ok=True)
      STATE = MEM / "fuzz-rotation.json"

      # slug -> (description, suggested test labels)
      DOMAINS = {
          "live-relay": ("live stream relay/proxy path (apps/proxy live_proxy + ts_proxy code in apps/channels)",
                          "apps.proxy apps.channels"),
          "timeshift": ("timeshift/catch-up path (apps/timeshift)", "apps.timeshift"),
          "m3u": ("M3U ingestion/sync (apps/m3u)", "apps.m3u"),
          "epg": ("EPG ingestion/matching (apps/epg)", "apps.epg"),
          "output-apis": ("Xtream/HDHR/output API surfaces (apps/output, apps/hdhr, apps/vod)",
                           "apps.output apps.vod"),
      }

      try:
          state = json.loads(STATE.read_text())
          assert isinstance(state, dict)
      except Exception:
          state = {}

      def last_run(slug):
          return state.get(slug, {}).get("last_run", "")

      # Never-fuzzed first (empty string sorts lowest), then oldest; ties break in dict order.
      selected = min(DOMAINS, key=lambda s: (last_run(s), list(DOMAINS).index(s)))

      now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
      entry = state.setdefault(selected, {})
      entry["last_run"] = now
      entry["runs"] = int(entry.get("runs", 0)) + 1
      entry["run_id"] = os.environ.get("GITHUB_RUN_ID", "")
      STATE.write_text(json.dumps(state, indent=2) + "\n")

      desc, labels = DOMAINS[selected]
      print(f"FUZZ_DOMAIN={selected}")
      print(f"FUZZ_DOMAIN_DESC={desc}")
      print(f"FUZZ_TEST_LABELS={labels}")
      PY
      echo "Selected: $(tail -3 "$GITHUB_ENV")"
safe-outputs:
  create-issue:
    title-prefix: "[domain-fuzz] "
    labels: [bug, fuzzing]
    deduplicate-by-title: true
    allowed-labels:
      - bug
      - fuzzing
      - needs-triage
      - type:crash
      - type:correctness
      - type:performance
      - type:reliability
      - type:security
      - type:test-gap
      - priority:p0
      - priority:p1
      - priority:p2
      - priority:p3
    max: 2
  create-pull-request:
    title-prefix: "[fuzz-hardening] "
    draft: true
    max: 1
    if-no-changes: "ignore"
  noop:
    report-as-issue: false
---

# Domain fuzz campaign

## Environment (already prepared — do not rediscover)

- All backend Python deps are installed in `.venv` (from `uv.lock`). Do not pip/uv install anything.
- `DJANGO_SECRET_KEY`, `TEST_USE_SQLITE=1`, and `DISPATCHARR_LOG_LEVEL=WARNING` are already exported. Tests use SQLite; Postgres is not available.
- Start Redis once before running tests (some tests depend on cache state):
  `./.fuzz-env/bin/redis-server --daemonize yes --port 6379 --save '' --appendonly no && ./.fuzz-env/bin/redis-cli flushall`
- Run tests with: `.venv/bin/python manage.py test <label> [--verbosity 1]` — e.g. `.venv/bin/python manage.py test apps.timeshift.tests.test_catchup_proxy`. Never pass `--settings`.
- If the staged Redis binary fails to run, try `sudo apt-get install -y redis-server`; if Redis still cannot start, treat Redis-dependent checks as **not run** and say so.

## Selected domain

This run's domain was chosen deterministically (least recently fuzzed; rotation state lives in `/tmp/gh-aw/cache-memory/fuzz-rotation.json` — do not edit it):

- Domain: `$FUZZ_DOMAIN` — $FUZZ_DOMAIN_DESC (these are environment variables; `echo` them if needed)
- Suggested test labels: `$FUZZ_TEST_LABELS`

Fuzz only this domain. Do not select a different one.

## Run contract

1. `max_rounds` = `${{ github.event.inputs.max_rounds }}`; if missing/invalid use 3; clamp to 1-4.
2. Execute up to `max_rounds` fuzzing rounds against the selected domain. Stop early if 2 consecutive rounds produce no new signal, or if the run nears timeout — finalize findings already gathered.

## Fuzzing approach

`$HYPOTHESIS_AVAILABLE` tells you whether Hypothesis is installed in `.venv` (`1` = yes).

**Preferred mode (Hypothesis available): contribute permanent property tests.** Pick the domain's parsing/state-transition surfaces (malformed payloads, boundary values, arbitrary byte strings, interleavings) and write Hypothesis property tests that encode invariants the implementation actually promises — read the code first; never invent guarantees. Place them in the domain's existing test package following its `test_*.py` naming, using `SimpleTestCase`/`unittest.TestCase` where the code under test allows, with modest example counts (~200) and a derandomized settings profile so CI stays fast and reproducible. Run them via `manage.py test`.

- **Property holds** → it is permanent fuzzing infrastructure. Collect passing property tests into one draft PR at the end of the run (title: the domain and surfaces covered; body: each invariant and why the implementation promises it). Also run the domain's existing test labels to confirm nothing else broke before creating the PR.
- **Property falsified** → that is a finding. Shrink is automatic; put the minimal counterexample and the property test in the issue (policy below). Do NOT include failing tests in the PR — the PR must be green.
- Both outcomes in one run are normal: PR the survivors, file the failures.

**Fallback mode (`$HYPOTHESIS_AVAILABLE` = 0): probe as before.** Vary inputs, ordering, boundary values, and malformed payloads with throwaway targeted Django tests. File issues for findings; skip the PR entirely.

Either mode, prioritize: parsing edge cases and malformed structures; concurrency/race behavior and state transitions; timeout/retry/failover paths; permission/credential-handling regressions; data-loss or silent-corruption risks. Check what property tests already exist in the domain's test package first and do not duplicate invariants already covered — go deeper (new surfaces) instead.

If infrastructure needed for a check is unavailable, do not claim the check was executed; report only evidence you actually obtained.

## Issue policy

Search open issues before filing; if a finding already exists, mention the matching issue in your `noop` summary instead.

Create an issue only for novel findings backed by concrete evidence from this run. Each issue must include:

- clear title; reproducible steps; expected vs actual behavior; affected domain and impact
- evidence from this run (commands, outputs, file references)
- **likelihood**: one sentence on how probable the trigger is in normal operation (default config, realistic usage)
- **repro artifact**: the complete harness/test code used to demonstrate the finding, inline in a collapsed `<details><summary>Repro harness</summary>` block with a fenced code block and the exact command to run it, so the finding is independently reproducible
- suggested next action

Priority rubric (pick one):

- `priority:p0` — crash, data loss, or security impact in the default configuration
- `priority:p1` — user-visible breakage or corruption under realistic conditions
- `priority:p2` — reliability/performance risk needing an unusual trigger
- `priority:p3` — minor issue or test gap

Labels: one `type:*` (`type:crash`, `type:correctness`, `type:performance`, `type:reliability`, `type:security`, `type:test-gap`), one `priority:*`, plus `bug`, `fuzzing`, `needs-triage`.

## Completion

If no novel findings and no property tests worth contributing, call `noop` with: selected domain, rounds executed, notable scenarios/invariants tested, and why nothing was created. A run that only produces the hardening PR (no issues) is a good run — summarize the invariants added.
