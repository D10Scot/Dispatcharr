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

Permission gaps are recorded, never hidden: a 403 from the *listing* call
writes status "not_permitted", a 404 writes "disabled", any other GhApiError,
OSError or ValueError writes "error" with the message in ``detail`` and an
empty record list. A failure on a *per-record* detail call (PR detail, PR
files, issue timeline) is a different thing: it says nothing about whether
the whole kind is permitted, so fetchers wrap it in DetailFetchError, which
collect_kind always maps to "error" (never "not_permitted"/"disabled") with
the record id and path named in ``detail``. Any other exception is a bug in a
projection or fetcher, not an API outcome: it propagates out of collect_kind
(no file is written for that kind, avoiding a silent bad-data row) and
main() turns it into a nonzero exit so the run fails visibly instead of
being recorded as data.

A third, non-fatal case: ``workflow_runs`` paginates GitHub's `/actions/runs`
listing in 7-day windows because the endpoint truncates at a 1,000-record
ceiling per query. If a single window itself hits that ceiling, the kind is
still "ok" (every other window's records did arrive) but ``detail`` names the
window, so the gap is visible in the dump rather than silently dropped.
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


class DetailFetchError(Exception):
    """A per-record detail call failed — not a listing-endpoint outcome.

    The 403→not_permitted / 404→disabled mapping in collect_kind describes
    the *whole kind* being gated (e.g. Dependabot alerts off for this repo).
    A single record's detail call failing — a secondary rate limit hit while
    backfilling PR file lists, say — means something else entirely and must
    never be recorded as if the kind itself were forbidden or absent.
    Fetchers raise this for a failed detail/files/timeline call; collect_kind
    always maps it to status "error" with the record named in ``detail``.
    """

    def __init__(self, kind: str, record_id, path: str, message: str) -> None:
        self.kind = kind
        self.record_id = record_id
        self.path = path
        self.message = message
        super().__init__(f"{kind} record {record_id} ({path}): {message}")


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
        detail_path = f"/pulls/{pr['number']}"
        try:
            detail = gh_api(repo, detail_path, paginate=False)
        except GhApiError as exc:
            raise DetailFetchError("pull_requests", pr["number"], detail_path, str(exc)) from exc
        files_path = f"/pulls/{pr['number']}/files"
        try:
            files = gh_api(repo, files_path, {"per_page": "100"})
        except GhApiError as exc:
            raise DetailFetchError("pull_requests", pr["number"], files_path, str(exc)) from exc
        out.append(project_pr(pr, detail, files))
    return out


def fetch_workflow_runs(repo: str, sidecar: Sidecar, opts) -> tuple[list[dict], str | None]:
    """`/actions/runs` listing (with `created=>=since`) silently truncates at
    GitHub's 1,000-record ceiling — this repo already has 1,178 runs, so a
    single unwindowed call loses the oldest ~15% with no signal. Fetch in
    7-day `created=A..B` windows instead, from `since` up to today inclusive
    (UTC dates), and union the results by id — a later window's copy of a
    record wins the merge. If any single window itself returns exactly 1000
    records (still possible on a very busy week), that window's cap is
    reported back to the caller as ``detail`` rather than silently dropped.
    """
    since_date = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=opts.runs_since_days)).date()
    today = dt.datetime.now(dt.timezone.utc).date()
    by_id: dict[int, dict] = {}
    cap_detail: str | None = None
    window_start = since_date
    while window_start <= today:
        window_end = min(window_start + dt.timedelta(days=6), today)
        created = f"{window_start.isoformat()}..{window_end.isoformat()}"
        runs = gh_api(repo, "/actions/runs", {"created": created, "per_page": "100"}, list_key="workflow_runs")
        if len(runs) == 1000:
            cap_detail = f"window {window_start.isoformat()}..{window_end.isoformat()} hit the 1000-record listing cap"
        for run in runs:
            by_id[run["id"]] = run
        window_start = window_end + dt.timedelta(days=1)
    return [project_run(r) for r in by_id.values()], cap_detail


def fetch_issues(repo: str, sidecar: Sidecar, opts) -> list[dict]:
    out = []
    for issue in gh_api(repo, "/issues", {"state": "all", "per_page": "100"}):
        if "pull_request" in issue:
            continue  # the issues endpoint lists PRs too
        prior = sidecar.get(issue["number"])
        if prior and prior.get("updated_at") == issue.get("updated_at"):
            out.append(dict(prior, labels=[l.get("name") for l in (issue.get("labels") or [])]))
            continue
        timeline_path = f"/issues/{issue['number']}/timeline"
        try:
            timeline = gh_api(repo, timeline_path, {"per_page": "100"})
        except GhApiError as exc:
            raise DetailFetchError("issues", issue["number"], timeline_path, str(exc)) from exc
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
    # A fetcher normally returns just the record list. One (workflow_runs)
    # also needs to report a non-fatal condition (a per-window listing cap)
    # alongside a still-"ok" status, so it may return (records, detail)
    # instead — collect_kind accepts either shape without every other
    # fetcher having to change.
    fetch_detail: str | None = None
    try:
        result = KINDS[kind](repo, sidecar, opts)
        if isinstance(result, tuple):
            envelope["records"], fetch_detail = result
        else:
            envelope["records"] = result
    except DetailFetchError as exc:
        # A per-record detail call failed, not the listing call: never
        # not_permitted/disabled — those describe the whole kind being
        # gated, which this isn't.
        envelope["status"] = "error"
        envelope["detail"] = str(exc)[:200]
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
        if fetch_detail:
            envelope["detail"] = fetch_detail
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
