#!/usr/bin/env python3
"""Metric family: security.

GitHub-API-backed alert counts. Unlike the M1 collectors these need network
access and a `gh`-authenticated token; they cannot run against a bare
historical checkout, so they are NOT run by `backfill.py` — the series starts
at first collection (see `_notes` on the emitted row).

- codeql_open_by_severity: open code-scanning alert count keyed by
  ``rule.security_severity_level`` (``critical``/``high``/``medium``/``low``);
  alerts with no severity level reported fall under ``"unknown"``.
- codeql_open_by_language: open code-scanning alert count keyed by the
  CodeQL language pack, read from the alert's
  ``most_recent_instance.environment`` JSON string (``{"language": "..."}"),
  falling back to parsing ``.../language:xxx`` out of
  ``most_recent_instance.category`` when ``environment`` is absent.
- dependabot_open_by_severity: open Dependabot alert count keyed by
  ``security_advisory.severity``, or ``null`` if the endpoint is
  forbidden/not-enabled for this repo (403/404) — see ``_notes``.
- secret_scanning_open_count: open secret-scanning alert count, or ``null``
  when the feature is disabled for the repo (404) or inaccessible (403).

Every count is "open alerts right now", not a delta — the JSONL history is
what makes the trend visible.
"""

from __future__ import annotations

import json
import re

from _gh import GhApiError, gh_api, repo_arg

LANGUAGE_CATEGORY_RE = re.compile(r"language:([\w-]+)")


def _alert_language(alert: dict) -> str:
    instance = alert.get("most_recent_instance") or {}
    env_raw = instance.get("environment")
    if env_raw:
        try:
            env = json.loads(env_raw)
            lang = env.get("language")
            if lang:
                return lang
        except (json.JSONDecodeError, AttributeError):
            pass
    category = instance.get("category") or ""
    match = LANGUAGE_CATEGORY_RE.search(category)
    if match:
        return match.group(1)
    return "unknown"


def codeql_counts(repo: str) -> tuple[dict[str, int], dict[str, int]]:
    alerts = gh_api(repo, "/code-scanning/alerts", params={"state": "open"})
    by_severity: dict[str, int] = {}
    by_language: dict[str, int] = {}
    for alert in alerts:
        severity = (alert.get("rule") or {}).get("security_severity_level") or "unknown"
        by_severity[severity] = by_severity.get(severity, 0) + 1
        language = _alert_language(alert)
        by_language[language] = by_language.get(language, 0) + 1
    return by_severity, by_language


def dependabot_counts(repo: str) -> dict[str, int] | None:
    alerts = gh_api(repo, "/dependabot/alerts", params={"state": "open"})
    by_severity: dict[str, int] = {}
    for alert in alerts:
        severity = (alert.get("security_advisory") or {}).get("severity") or "unknown"
        by_severity[severity] = by_severity.get(severity, 0) + 1
    return by_severity


def secret_scanning_count(repo: str) -> int:
    alerts = gh_api(repo, "/secret-scanning/alerts", params={"state": "open"})
    return len(alerts)


def main() -> None:
    from _common import emit

    repo = repo_arg(__doc__)
    notes: list[str] = [
        "not backfillable: series starts at first collection (live API state, "
        "no historical snapshot exists per commit)."
    ]

    codeql_by_severity, codeql_by_language = codeql_counts(repo)

    try:
        dependabot_by_severity = dependabot_counts(repo)
    except GhApiError as exc:
        dependabot_by_severity = None
        notes.append(f"dependabot_open_by_severity: null ({exc.status or 'error'}: {exc})")

    try:
        secret_scanning = secret_scanning_count(repo)
    except GhApiError as exc:
        secret_scanning = None
        notes.append(f"secret_scanning_open_count: null ({exc.status or 'error'}: {exc})")

    emit(
        {
            "codeql_open_by_severity": codeql_by_severity,
            "codeql_open_by_language": codeql_by_language,
            "dependabot_open_by_severity": dependabot_by_severity,
            "secret_scanning_open_count": secret_scanning,
            "_notes": " | ".join(notes),
        }
    )


if __name__ == "__main__":
    main()
