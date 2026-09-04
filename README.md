# metrics-data

Append-only engineering-metrics history for D10Scot/Dispatcharr, written by
`.github/workflows/metrics.yml` (weekly + on merge to `main`) using the
deterministic collectors in `scripts/metrics/` on `main`.

One JSONL file per metric family; one row per collection:

```json
{"timestamp": "<ISO-8601>", "commit_sha": "<sha>", "family": "<name>", "metrics": {...}}
```

Rows are keyed by `(commit_sha, family)` and appends are idempotent.
Backfilled rows use the commit's author date as `timestamp`. History starts
at `fd413f0c` (v0.29.0, upstream divergence point).

Families: `code_health`, `architecture`, `tests`, `coverage` — metric
definitions are frozen in each collector's docstring
(`scripts/metrics/collect_<family>.py`).

## Event dumps

`events/<kind>.json` (overwritten daily) and `events/history/<kind>.jsonl`
(append-only sidecars for records that leave an API's window) — see
`events/` and `events/history/`.

## Retired

`security.jsonl`, `delivery.jsonl`, `agentic.jsonl` were frozen on
2026-08-29 and are no longer written.
