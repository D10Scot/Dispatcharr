---
description: Fuzz one application domain per run and raise typed, prioritized bug issues.
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
model: gpt-5.6-sol
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
      uv sync --locked --no-install-project --no-dev --python "$(command -v python)"
      # Smoke-check the venv boots Django with the test settings the agent will use.
      DJANGO_SECRET_KEY=fuzz-campaign TEST_USE_SQLITE=1 DJANGO_SETTINGS_MODULE=dispatcharr.settings_test \
        .venv/bin/python -c "import django; django.setup(); print('django', django.get_version(), 'ok')"
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

Each round, vary inputs, ordering, boundary values, and malformed payloads relevant to the domain. Prioritize: parsing edge cases and malformed structures; concurrency/race behavior and state transitions; timeout/retry/failover paths; authorization/secret-handling regressions; data-loss or silent-corruption risks.

Prefer real targeted Django tests (existing tests plus small throwaway test files driven by `manage.py test`) over standalone harness scripts. If infrastructure needed for a check is unavailable, do not claim the check was executed; report only evidence you actually obtained.

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

If no novel findings, call `noop` with: selected domain, rounds executed, notable scenarios tested, and why no issue was created.
