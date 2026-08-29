"""Shared `gh` CLI helpers for the M2 API-based collectors.

Unlike the M1 collectors (AST/grep over a checkout, no network), these talk to
the GitHub API via the `gh` CLI subprocess (already authenticated in CI via
the job's ``GITHUB_TOKEN``/``GH_TOKEN`` env, and locally via `gh auth login`).
Always pass ``--repo`` explicitly — never rely on `gh` inferring the repo from
cwd (CLAUDE.md: "gh commands use explicit --repo").

Collectors must never hard-fail on a permission gap: some endpoints
(Dependabot alerts, secret-scanning alerts) are 403/404 depending on repo
settings the collector doesn't control. Callers catch ``GhApiError`` and emit
``null`` + an explanatory ``_notes`` entry instead of raising.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import urllib.parse


class GhApiError(Exception):
    """A `gh api`/`gh` invocation failed; carries the HTTP status if known."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _extract_status(stderr: str) -> int | None:
    # gh api's error text includes "HTTP 404" / "HTTP 403" etc.
    for line in stderr.splitlines():
        if "HTTP " in line:
            tail = line.split("HTTP ", 1)[1].strip()
            digits = "".join(ch for ch in tail.split()[0] if ch.isdigit())
            if digits:
                return int(digits)
    return None


def run_gh(*args: str) -> str:
    """Run an arbitrary `gh` subcommand, returning stdout. Raises GhApiError."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GhApiError(result.stderr.strip() or "gh command failed", _extract_status(result.stderr))
    return result.stdout


def gh_api(repo: str, path: str, params: dict[str, str] | None = None, paginate: bool = True):
    """Call `gh api /repos/<repo><path>`, returning parsed JSON.

    Always paginates by default (safe for both list and object endpoints:
    `gh api --paginate` on a non-array response just returns the single
    object). Raises GhApiError with `.status` set when the HTTP call fails,
    so callers can special-case 403 ("no access")/404 ("feature disabled").
    """
    full_path = f"/repos/{repo}{path}"
    if params:
        full_path += "?" + urllib.parse.urlencode(params)
    args = ["api", full_path, "--method", "GET"]
    if paginate:
        args.append("--paginate")
    stdout = run_gh(*args)
    if not stdout.strip():
        return []
    # `gh api --paginate` merges all pages into a single JSON array (or
    # returns the lone object for non-list endpoints), so one json.loads
    # is correct regardless of how many pages were fetched.
    return json.loads(stdout)


def repo_arg(description: str) -> str:
    """Parse the standard `--repo` flag shared by all API collectors."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--repo",
        default="D10Scot/Dispatcharr",
        help="owner/repo to query (default: D10Scot/Dispatcharr)",
    )
    args = parser.parse_args()
    return args.repo
