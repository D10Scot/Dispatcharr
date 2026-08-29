# Engineering metrics dashboard

Static, no-build-step dashboard published to GitHub Pages, sourced from the
append-only `metrics-data` branch (see its own README for the row schema).

## Layout

- `index.html` / `overview.js` — "now vs baseline" big-number cards with
  sparklines, one per numeric metric across every discovered family.
- `trends.html` / `trends.js` — full time-series per family, one chart per
  numeric metric, with vertical milestone annotations from `milestones.json`.
- `presentation.html` / `presentation.js` — `?from=<sha>&to=<sha>` renders a
  before/after delta table per family, for the migration-story talk.
- `data.js` — shared fetch/parsing helpers used by all three views.
- `milestones.json` — hand-curated phase milestones (checked in, edited by
  hand when a new milestone lands).
- `vendor/uplot/` — vendored chart library (see its README for version,
  source and hashes). No CDN fetches; all supply-chain rules require
  digest/hash-pinned local copies.
- `style.css` — plain CSS, no UI framework.

At publish time (see `.github/workflows/pages.yml`), the JSONL files from
`metrics-data` are copied into `data/` alongside a generated
`data/manifest.json` (a JSON array of family names present at build time).
Views discover families from the manifest rather than hard-coding
`code_health`/`architecture`/`tests`, so new families landing from a
parallel effort (e.g. security/delivery/agentic) appear automatically once
their collector starts writing rows.

## Local development

No build step. To preview against real data:

```bash
mkdir -p /tmp/dashboard-preview/data
cp dashboard/*.html dashboard/*.js dashboard/*.css dashboard/milestones.json /tmp/dashboard-preview/
cp -r dashboard/vendor /tmp/dashboard-preview/
git show origin/metrics-data:code_health.jsonl > /tmp/dashboard-preview/data/code_health.jsonl
git show origin/metrics-data:architecture.jsonl > /tmp/dashboard-preview/data/architecture.jsonl
git show origin/metrics-data:tests.jsonl > /tmp/dashboard-preview/data/tests.jsonl
python3 -c "import json,pathlib; pathlib.Path('/tmp/dashboard-preview/data/manifest.json').write_text(json.dumps(['code_health','architecture','tests']))"
cd /tmp/dashboard-preview && python3 -m http.server 8123
```

Then open `http://localhost:8123/index.html`, `/trends.html`, and
`/presentation.html?from=fd413f0c&to=a6fc2b96`.
