"""CLI: build site.json, or only validate the curated files."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # the package's modules import each other by bare name (tests do too)

from assemble import build_site  # noqa: E402
from curated import _pointers, load_curated, validate  # noqa: E402
from gitinfo import pr_is_merged  # noqa: E402
from load import load_snapshots  # noqa: E402

BASE = "fd413f0cc4ab3131789a68fb31f1ae622ae7371a"
REPO_SLUG = "D10Scot/Dispatcharr"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m metrics.build", description=__doc__)
    p.add_argument("--curated", type=Path, default=Path("metrics/curated"))
    p.add_argument("--data", type=Path, help="metrics-data checkout (omit with --validate-only)")
    p.add_argument("--out", type=Path)
    p.add_argument("--repo", type=Path, default=Path("."))
    p.add_argument("--base", default=BASE)
    p.add_argument("--ref", default="main")
    p.add_argument("--today", default=None, help="YYYY-MM-DD (default: today UTC)")
    p.add_argument("--check-prs", action="store_true", help="verify milestone/fixed_in PRs are merged via gh")
    p.add_argument("--validate-only", action="store_true")
    a = p.parse_args(argv)

    try:
        curated = load_curated(a.curated)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    known = None
    if a.data:
        known = {fam: set(_pointers(rows[-1].metrics)) for fam, rows in load_snapshots(a.data).items() if rows}
    checker = (lambda n: pr_is_merged(REPO_SLUG, n)) if a.check_prs else None
    errors = validate(curated, repo=a.repo, base=a.base, ref=a.ref, pr_checker=checker, known_families=known)
    if errors:
        print("curated files invalid:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    if a.validate_only:
        print(f"ok: {len(curated.catalogue)} metrics, {len(curated.milestones)} milestones, {len(curated.defects)} defects")
        return 0
    if not a.data or not a.out:
        p.error("--data and --out are required unless --validate-only")
    today = dt.date.fromisoformat(a.today) if a.today else dt.datetime.now(dt.timezone.utc).date()
    site = build_site(a.data, curated, repo=a.repo, base=a.base, today=today, ref=a.ref)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(site, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {a.out} ({a.out.stat().st_size // 1024} KB, {len(site['headline'])} headline metrics)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
