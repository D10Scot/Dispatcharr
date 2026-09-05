# Engineering metrics dashboard

Static pages over one `site.json`, published to GitHub Pages by
`.github/workflows/pages.yml`. The pages draw; they never compute. Every
number comes from `python -m metrics.build` (see `docs/agents/metrics.md`
and the design spec it points to).

- `index.html` Overview — phase strip, twenty headline tiles in five groups,
  freshness footer. A tile's background is the daily series in the status
  colour (good / bad / neutral / stale).
- `story.html` — one section per phase: dates, summary, milestones with PR
  links, the headline charts that phase was meant to move, with the phase's
  own date range shaded on each chart.
- `explore.html` — every catalogued metric, per-commit (default) or daily
  (`?mode=daily`); derived metrics have no per-commit points and always
  render daily regardless of the toggle. Milestone lines from
  `metrics/curated/milestones.yml`.
- `compare.html` — two milestones, one delta table per group; `?from=&to=`;
  print-friendly.
- `defects.html` — the known-defect ledger by status.

`app.js` boots the page named in `<main data-page>`; `lib/` holds pure
helpers (format, spark paths, compare rows) and the shared visual pieces;
`pages/` one module per page; `vendor/uplot/` the vendored chart library
(hash-pinned, see its README). No build step, no framework, ES modules.

## Tests and preview

Both blocks run from the repo root.

```bash
(cd frontend && npx vitest --run --config vitest.dashboard.config.js)
```

```bash
# site.json needs a metrics-data checkout; --ref auto (the build step's
# default) prefers origin/main, so fetch that too before building.
git fetch origin main metrics-data
mkdir -p /tmp/md && git archive origin/metrics-data | tar -x -C /tmp/md

# .venv needs pip and PyYAML; create it once if it doesn't already have them:
python3 -m venv .venv && .venv/bin/python -m pip install --require-hashes -r metrics/requirements.txt

.venv/bin/python -m metrics.build --data /tmp/md --curated metrics/curated --out dashboard/site.json
cd dashboard && python3 -m http.server 8123
```

(Plain `python -m metrics.build` works too as long as PyYAML is on that
interpreter.)

`dashboard/site.json` is gitignored and must never be committed: the pages
fetch it relative to themselves, so the preview builds it here, and
`pages.yml` builds the real one into the site artifact at deploy time —
`dashboard/tests/` is stripped from that published artifact, since the
pages never load it.
