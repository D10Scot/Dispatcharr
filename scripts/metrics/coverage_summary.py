#!/usr/bin/env python3
"""Fold `coverage json` output and vitest's coverage-summary.json into the
`coverage` family's metrics dict (one row per daily run, never backfilled).

Per-app backend percentages are computed from file summaries, grouped by the
same keys code_health uses for loc_per_app (``apps.<name>``, ``core``,
``dispatcharr``). A missing or unreadable input reports ``null`` and status
"failed" rather than crashing: a red day must be a visible point.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load(path: Path | None):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError) as exc:
        print(f"warning: could not read {path}: {exc}", file=sys.stderr)
        return None


def app_key(rel: str) -> str:
    parts = rel.split("/")
    if parts[0] == "apps" and len(parts) > 1:
        return f"apps.{parts[1]}"
    return parts[0]


def backend_metrics(cov: dict | None, status: dict | None) -> dict:
    if not cov:
        return {"backend_line_pct": None, "backend_by_app": {}, "backend_status": "failed",
                "backend_failed_labels": (status or {}).get("failed_labels", [])}
    covered: dict[str, int] = {}
    total: dict[str, int] = {}
    for rel, info in cov.get("files", {}).items():
        s = info.get("summary", {})
        k = app_key(rel)
        covered[k] = covered.get(k, 0) + s.get("covered_lines", 0)
        total[k] = total.get(k, 0) + s.get("num_statements", 0)
    by_app = {k: round(100.0 * covered[k] / total[k], 2) for k in sorted(total) if total[k]}
    failed = (status or {}).get("failed_labels", [])
    return {
        "backend_line_pct": round(cov.get("totals", {}).get("percent_covered", 0.0), 2),
        "backend_by_app": by_app,
        "backend_status": "failed" if failed or status is None else "ok",
        "backend_failed_labels": failed,
    }


def frontend_metrics(summary: dict | None) -> dict:
    pct = (((summary or {}).get("total") or {}).get("lines") or {}).get("pct")
    return {"frontend_line_pct": round(pct, 2) if isinstance(pct, (int, float)) else None,
            "frontend_status": "ok" if isinstance(pct, (int, float)) else "failed"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backend", type=Path)
    p.add_argument("--backend-status", type=Path)
    p.add_argument("--frontend", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    row = {}
    row.update(backend_metrics(load(a.backend), load(a.backend_status)))
    row.update(frontend_metrics(load(a.frontend)))
    a.out.write_text(json.dumps(row, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(row), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
