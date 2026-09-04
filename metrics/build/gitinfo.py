"""Git and GitHub facts the validators need, isolated so tests can inject a
fake `gh` and use a throwaway repo."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    # No timeout catch here: a hung git is a real failure and should propagate
    # subprocess.TimeoutExpired rather than being mistaken for "no answer".
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, timeout=60
    ).stdout.strip()


def first_parent_shas(repo: Path, base: str, ref: str = "main") -> list[str]:
    """Full SHAs of base and every first-parent commit after it up to ref, oldest first."""
    base_full = _git(repo, "rev-parse", f"{base}^{{commit}}")
    later = _git(repo, "rev-list", "--first-parent", "--reverse", f"{base_full}..{ref}").splitlines()
    return [base_full] + [s for s in later if s]


def is_first_parent_on(repo: Path, sha: str, base: str, ref: str = "main") -> bool:
    try:
        full = _git(repo, "rev-parse", f"{sha}^{{commit}}")
    except subprocess.CalledProcessError:
        return False
    return full in first_parent_shas(repo, base, ref)


def commit_date(repo: Path, sha: str) -> dt.datetime:
    iso = _git(repo, "show", "-s", "--format=%aI", sha)
    return dt.datetime.fromisoformat(iso).astimezone(dt.timezone.utc)


def run_gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=60).stdout


def pr_is_merged(repo_slug: str, number: int, gh=run_gh) -> bool | None:
    """True/False from the API; None when gh is unavailable, times out, errors, or
    returns something that isn't a JSON object (unverifiable, not fatal)."""
    try:
        doc = json.loads(gh("api", f"/repos/{repo_slug}/pulls/{number}", "--method", "GET"))
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    return bool(doc.get("merged_at"))
