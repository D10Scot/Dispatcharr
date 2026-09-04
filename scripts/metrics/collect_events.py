#!/usr/bin/env python3
"""Event dumps: the full current record set of each GitHub-backed source.

Unlike the snapshot collectors, nothing here is a metric. Each kind is written
whole to events/<kind>.json on every run (overwritten), projected down to the
fields the build step needs, with a stable ``id`` per record. Because every
record carries its own timestamps, any "as of date D" number is derived at
build time (metrics/build/derive.py) — which is why these are not appended as
rows and why history reaches back to the data's own start rather than to the
first collection.

Records can fall off an API's retention window (GitHub keeps workflow runs
for 90 days), so each kind also keeps a history sidecar,
events/history/<kind>.jsonl: a record is appended there the first time it is
seen and again whenever its projected form changes. The build step reads the
union, current record winning.

Permission gaps are recorded, never hidden: a 403 writes status
"not_permitted", a 404 writes "disabled", any other GhApiError, OSError or
ValueError writes "error" with the message in ``detail`` and an empty record
list. Any other exception is a bug in a projection or fetcher, not an API
outcome: it propagates out of collect_kind (no file is written for that
kind, avoiding a silent bad-data row) and main() turns it into a nonzero exit
so the run fails visibly instead of being recorded as data.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

from _gh import GhApiError, gh_api

SCORECARD_URL = "https://api.securityscorecards.dev/projects/github.com/{repo}"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------- sidecar ---

class Sidecar:
    """events/history/<kind>.jsonl — last line per id wins."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: dict[str, dict] = {}
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.records[str(row["id"])] = row["record"]

    def get(self, record_id) -> dict | None:
        return self.records.get(str(record_id))

    def absorb(self, records: list[dict], seen_at: str) -> int:
        """Append every record that is new or whose projection changed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        appended = 0
        with self.path.open("a", encoding="utf-8") as f:
            for rec in records:
                key = str(rec["id"])
                if self.records.get(key) == rec:
                    continue
                self.records[key] = rec
                f.write(json.dumps({"id": rec["id"], "seen_at": seen_at, "record": rec}, sort_keys=True) + "\n")
                appended += 1
        return appended


# ---------------------------------------------------------- projections ---

def project_codeql(alert: dict) -> dict:
    rule = alert.get("rule") or {}
    loc = ((alert.get("most_recent_instance") or {}).get("location") or {})
    return {
        "id": alert["number"],
        "state": alert.get("state"),
        "created_at": alert.get("created_at"),
        "fixed_at": alert.get("fixed_at"),
        "dismissed_at": alert.get("dismissed_at"),
        "dismissed_reason": alert.get("dismissed_reason"),
        "rule_id": rule.get("id"),
        "severity": rule.get("security_severity_level"),
        "tool": (alert.get("tool") or {}).get("name"),
        "path": loc.get("path"),
    }


def project_pr(pr: dict, detail: dict | None, files: list[dict] | None) -> dict:
    user = pr.get("user") or {}
    return {
        "id": pr["number"],
        "title": pr.get("title"),
        "created_at": pr.get("created_at"),
        "merged_at": pr.get("merged_at"),
        "closed_at": pr.get("closed_at"),
        "author": user.get("login"),
        "author_type": user.get("type"),
        "head_ref": (pr.get("head") or {}).get("ref"),
        "additions": (detail or {}).get("additions"),
        "deletions": (detail or {}).get("deletions"),
        "changed_files": (detail or {}).get("changed_files"),
        "files": [f.get("filename") for f in (files or [])],
    }


def project_run(run: dict) -> dict:
    return {
        "id": run["id"],
        "workflow": run.get("name"),
        "event": run.get("event"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "run_started_at": run.get("run_started_at"),
        "head_sha": run.get("head_sha"),
    }


def project_issue(issue: dict, timeline: list[dict]) -> dict:
    events = [
        {"event": e["event"], "label": (e.get("label") or {}).get("name"), "at": e.get("created_at")}
        for e in timeline
        if e.get("event") in ("labeled", "unlabeled") and (e.get("label") or {}).get("name")
    ]
    return {
        "id": issue["number"],
        "title": issue.get("title"),
        "state": issue.get("state"),
        "created_at": issue.get("created_at"),
        "closed_at": issue.get("closed_at"),
        "updated_at": issue.get("updated_at"),
        "labels": [l.get("name") for l in (issue.get("labels") or [])],
        "label_events": events,
    }


# -------------------------------------------------------------- fetchers ---
# Each returns the projected record list. They may consult the sidecar to
# skip per-record detail calls for records that cannot change any more.

def fetch_codeql(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    return [project_codeql(a) for a in gh_api(repo, "/code-scanning/alerts", {"state": "all", "per_page": "100"})]


def fetch_dependabot(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    out = []
    for a in gh_api(repo, "/dependabot/alerts", {"state": "all", "per_page": "100"}):
        adv = a.get("security_advisory") or {}
        out.append({
            "id": a["number"], "state": a.get("state"), "created_at": a.get("created_at"),
            "fixed_at": a.get("fixed_at"), "dismissed_at": a.get("dismissed_at"),
            "severity": adv.get("severity"), "package": ((a.get("dependency") or {}).get("package") or {}).get("name"),
        })
    return out


def fetch_secret_scanning(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    return [
        {"id": a["number"], "state": a.get("state"), "created_at": a.get("created_at"),
         "resolved_at": a.get("resolved_at"), "secret_type": a.get("secret_type")}
        for a in gh_api(repo, "/secret-scanning/alerts", {"state": "all", "per_page": "100"})
    ]


def fetch_pull_requests(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    out = []
    for pr in gh_api(repo, "/pulls", {"state": "all", "per_page": "100"}):
        prior = sidecar.get(pr["number"])
        # A merged or closed PR's line counts and file list are final: reuse them.
        if prior and prior.get("closed_at") and prior.get("additions") is not None:
            out.append(project_pr(pr, prior, [{"filename": f} for f in prior.get("files", [])]))
            continue
        detail = gh_api(repo, f"/pulls/{pr['number']}", paginate=False)
        files = gh_api(repo, f"/pulls/{pr['number']}/files", {"per_page": "100"})
        out.append(project_pr(pr, detail, files))
    return out


def fetch_workflow_runs(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=opts.runs_since_days)).strftime("%Y-%m-%d")
    runs = gh_api(repo, "/actions/runs", {"created": f">={since}", "per_page": "100"}, list_key="workflow_runs")
    return [project_run(r) for r in runs]


def fetch_issues(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    out = []
    for issue in gh_api(repo, "/issues", {"state": "all", "per_page": "100"}):
        if "pull_request" in issue:
            continue  # the issues endpoint lists PRs too
        prior = sidecar.get(issue["number"])
        if prior and prior.get("updated_at") == issue.get("updated_at"):
            out.append(dict(prior, labels=[l.get("name") for l in (issue.get("labels") or [])]))
            continue
        timeline = gh_api(repo, f"/issues/{issue['number']}/timeline", {"per_page": "100"})
        out.append(project_issue(issue, timeline))
    return out


def fetch_scorecard(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    with urllib.request.urlopen(SCORECARD_URL.format(repo=repo), timeout=30) as resp:  # noqa: S310 - fixed https host
        doc = json.load(resp)
    return [{
        "id": doc.get("date"),
        "date": doc.get("date"),
        "score": doc.get("score"),
        "commit": (doc.get("repo") or {}).get("commit"),
        "checks": {c["name"]: c.get("score") for c in doc.get("checks", [])},
    }]


KINDS = {
    "codeql_alerts": fetch_codeql,
    "dependabot_alerts": fetch_dependabot,
    "secret_scanning": fetch_secret_scanning,
    "pull_requests": fetch_pull_requests,
    "workflow_runs": fetch_workflow_runs,
    "issues": fetch_issues,
    "scorecard": fetch_scorecard,
}


def collect_kind(kind: str, repo: str, out_dir: Path, opts) -> dict:
    events_dir = out_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    sidecar = Sidecar(events_dir / "history" / f"{kind}.jsonl")
    fetched_at = now_iso()
    envelope = {"kind": kind, "fetched_at": fetched_at, "repo": repo, "status": "ok", "detail": None, "records": []}
    try:
        envelope["records"] = KINDS[kind](repo, sidecar, opts)
    except GhApiError as exc:
        envelope["status"] = {403: "not_permitted", 404: "disabled"}.get(exc.status, "error")
        envelope["detail"] = str(exc).splitlines()[0][:200]
    except (OSError, ValueError) as exc:
        # Scorecard network/timeout errors and JSON decode failures: recorded
        # as a data-collection outcome, not fatal. Anything else (a KeyError
        # or TypeError from a broken projection, say) is a real bug and must
        # not be swallowed into a status row — let it propagate.
        envelope["status"] = "error"
        envelope["detail"] = f"{type(exc).__name__}: {exc}"[:200]
    if envelope["status"] == "ok":
        appended = sidecar.absorb(envelope["records"], fetched_at)
        print(f"{kind}: {len(envelope['records'])} records, {appended} new/changed in history", file=sys.stderr)
    else:
        print(f"{kind}: {envelope['status']} ({envelope['detail']})", file=sys.stderr)
    (events_dir / f"{kind}.json").write_text(json.dumps(envelope, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return envelope


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="D10Scot/Dispatcharr")
    parser.add_argument("--out-dir", type=Path, required=True, help="metrics-data checkout")
    parser.add_argument("--kinds", default=",".join(KINDS), help="comma-separated subset of: " + ", ".join(KINDS))
    parser.add_argument("--runs-since-days", type=int, default=180)
    parser.add_argument("--no-scorecard", action="store_true", help="skip the external Scorecard fetch (tests)")
    opts = parser.parse_args()

    kinds = [k.strip() for k in opts.kinds.split(",") if k.strip()]
    unknown = [k for k in kinds if k not in KINDS]
    if unknown:
        print(f"unknown kinds: {unknown}", file=sys.stderr)
        return 2
    if opts.no_scorecard:
        kinds = [k for k in kinds if k != "scorecard"]
    failures = 0
    for kind in kinds:
        try:
            collect_kind(kind, opts.repo, opts.out_dir, opts)
        except Exception as exc:  # a bug in this script, not an API outcome
            print(f"{kind}: collector crashed: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
