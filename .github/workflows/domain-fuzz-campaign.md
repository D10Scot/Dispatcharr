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
  copilot-requests: write
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
network:
  allowed:
    - defaults
    - python
    - node
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

## Goal

Choose exactly one domain of this repository each run, perform bounded fuzzy testing to uncover bugs or quality gaps, and open issues for novel findings.

## Run contract

1. Determine `max_rounds` from `${{ github.event.inputs.max_rounds }}`; if missing or invalid, use 3. Clamp to 1-4.
2. Select one domain only for this run. Use risk + recent coverage from repo context and current open issues. Candidate domains include:
   - live stream relay/proxy path
   - timeshift/catch-up path
   - M3U ingestion/sync
   - EPG ingestion/matching
   - Xtream/HDHR/output API surfaces
3. Build a focused fuzzing plan for that single domain, then execute up to `max_rounds` rounds. Stop early if no new signal emerges for 2 consecutive rounds.

## Fuzzing approach

For each round, vary inputs, ordering, boundary values, and malformed payloads relevant to the selected domain. Prioritize:

- parsing edge cases and malformed structures
- concurrency/race behavior and state transitions
- timeout, retry, and failover paths
- authorization/secret-handling regressions
- data-loss or silent-corruption risks

Run targeted existing tests/commands where useful. If runtime infrastructure needed for a check is unavailable in this workflow runtime, do not claim that check was executed; report only evidence you actually obtained.

## Issue policy

Before creating a new issue, search open issues to avoid duplicates. If a finding already exists, call `noop` and include the matching issue reference.

For each novel finding, create an issue only when you have concrete, actionable evidence from this run. Include:

- clear title
- reproducible steps
- expected vs actual behavior
- affected domain and impact
- evidence from this run (commands, outputs, or file references)
- suggested next action

Apply labels by both type and priority:

- **Type (pick one):** `type:crash`, `type:correctness`, `type:performance`, `type:reliability`, `type:security`, or `type:test-gap`
- **Priority (pick one):** `priority:p0`, `priority:p1`, `priority:p2`, or `priority:p3`
- Also include `bug`, `fuzzing`, and `needs-triage`

## Completion behavior

Call `noop` with a concise summary when no novel findings are produced in this run, including:

- selected domain
- rounds executed
- notable scenarios tested
- why no issue was created

Keep enough time for wrap-up and outputs. If the run is approaching timeout, stop fuzzing early and finalize findings already gathered.
