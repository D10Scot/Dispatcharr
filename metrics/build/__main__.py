"""CLI: build site.json, or only validate the curated files.

Exit codes: 0 success; 1 curated files invalid (structurally malformed, or
`validate()` reported errors); 2 usage error - missing required arguments or
a malformed --today (raised via argparse's own `p.error()`, which prints
usage plus a one-line message to stderr rather than a traceback)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # the package's modules import each other by bare name (tests do too)

from assemble import build_site  # noqa: E402
from curated import Defect, load_curated, parse_defects, pointers, validate, validate_transitions  # noqa: E402
from gitinfo import pr_is_merged  # noqa: E402
from load import load_snapshots  # noqa: E402

BASE = "fd413f0cc4ab3131789a68fb31f1ae622ae7371a"
REPO_SLUG = "D10Scot/Dispatcharr"
LEDGER_PATH = "metrics/curated/defects.yml"


def _load_committed_defects(repo: Path) -> tuple[list[Defect] | None, str | None]:
    """The defect ledger as committed on the mainline, for the forward-only
    status-transition check (curated.validate_transitions). Never fatal: no
    git, neither `origin/main` nor `main` resolvable, the ledger not present
    on that ref, or a malformed document there all return `(None, reason)`
    so the caller prints one line and skips the check rather than failing a
    build over history the local checkout may not have - a shallow clone, a
    worktree with no `origin` remote, or (true on this branch today) a
    curated tree that predates this file on `main`."""
    ref = None
    for candidate in ("origin/main", "main"):
        try:
            rr = subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify", candidate],
                                 capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"git rev-parse failed: {exc}"
        if rr.returncode == 0:
            ref = candidate
            break
    if ref is None:
        return None, "neither origin/main nor main is resolvable"
    try:
        r = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{LEDGER_PATH}"],
                            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"git show failed: {exc}"
    if r.returncode != 0:
        return None, f"{LEDGER_PATH} not present on {ref}"
    try:
        return parse_defects(r.stdout), None
    except ValueError as exc:
        return None, f"committed {LEDGER_PATH} on {ref} is malformed: {exc}"


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

    # Required-argument and format checks first, before touching the
    # filesystem, running the (possibly network-calling, via --check-prs)
    # validator, or building anything - a usage mistake should fail fast
    # and cheap, not after a curated-file load and a round of `gh api` calls.
    if not a.validate_only and (not a.data or not a.out):
        p.error("--data and --out are required unless --validate-only")
    today = None
    if not a.validate_only:
        if a.today:
            try:
                today = dt.date.fromisoformat(a.today)
            except ValueError:
                p.error(f"--today: invalid date {a.today!r}, expected YYYY-MM-DD")
        else:
            today = dt.datetime.now(dt.timezone.utc).date()

    try:
        curated = load_curated(a.curated)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    known = None
    if a.data:
        known = {fam: set(pointers(rows[-1].metrics)) for fam, rows in load_snapshots(a.data).items() if rows}
    checker = (lambda n: pr_is_merged(REPO_SLUG, n)) if a.check_prs else None
    errors = validate(curated, repo=a.repo, base=a.base, ref=a.ref, pr_checker=checker, known_families=known)
    committed_defects, skip_reason = _load_committed_defects(a.repo)
    if skip_reason:
        print(f"transition check skipped: {skip_reason}")
    else:
        errors += validate_transitions(committed_defects, curated.defects)
    if errors:
        print("curated files invalid:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    if a.validate_only:
        print(f"ok: {len(curated.catalogue)} metrics, {len(curated.milestones)} milestones, {len(curated.defects)} defects")
        return 0
    site = build_site(a.data, curated, repo=a.repo, base=a.base, today=today, ref=a.ref)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(site, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {a.out} ({a.out.stat().st_size // 1024} KB, {len(site['headline'])} headline metrics)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
