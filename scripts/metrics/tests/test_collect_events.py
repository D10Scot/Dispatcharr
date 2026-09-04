import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# `unittest discover -t scripts/metrics` does not put this tests/ dir on
# sys.path, and _fake_gh.py lives alongside this file, not on the package
# path — add it explicitly before importing.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _fake_gh import calls, fake_gh_env

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "collect_events.py"

ALERT = {"number": 7, "state": "open", "created_at": "2026-08-23T16:00:55Z", "fixed_at": None,
         "dismissed_at": None, "dismissed_reason": None,
         "rule": {"id": "py/full-ssrf", "security_severity_level": "critical"},
         "tool": {"name": "CodeQL"}, "most_recent_instance": {"location": {"path": "apps/x.py"}}}
PR = {"number": 5, "title": "G1", "created_at": "2026-08-24T10:00:00Z", "merged_at": "2026-08-25T10:00:00Z",
      "closed_at": "2026-08-25T10:00:00Z", "user": {"login": "d", "type": "User"}, "head": {"ref": "e2e/g1"}}
PR_DETAIL = dict(PR, additions=100, deletions=5, changed_files=3)
PR_FILES = [{"filename": "apps/x.py"}, {"filename": "e2e/a.spec.ts"}, {"filename": "docs/b.md"}]
RUN = {"id": 11, "name": "E2E Tests", "event": "push", "status": "completed", "conclusion": "success",
       "created_at": "2026-08-29T08:00:00Z", "updated_at": "2026-08-29T08:05:00Z",
       "run_started_at": "2026-08-29T08:00:10Z", "head_sha": "abc"}
ISSUE = {"number": 9, "title": "bug", "state": "open", "created_at": "2026-08-27T00:00:00Z", "closed_at": None,
         "updated_at": "2026-08-28T00:00:00Z", "labels": [{"name": "needs-triage"}]}
ISSUE_PR = dict(ISSUE, number=10, pull_request={"url": "x"})
TIMELINE = [{"event": "labeled", "label": {"name": "needs-triage"}, "created_at": "2026-08-27T00:00:01Z"},
            {"event": "unlabeled", "label": {"name": "needs-triage"}, "created_at": "2026-08-28T00:00:00Z"}]


def responses():
    return {
        "/repos/o/r/code-scanning/alerts": {"pages": [[ALERT]]},
        # A bare list here is ONE page (a list of file dicts); wrapping it in
        # another list would make gh_api return [PR_FILES] instead of
        # PR_FILES, breaking project_pr's iteration over file dicts.
        "/repos/o/r/pulls/5/files": PR_FILES,
        "/repos/o/r/pulls/5": PR_DETAIL,
        "/repos/o/r/pulls": {"pages": [[PR]]},
        "/repos/o/r/actions/runs": {"pages": [{"total_count": 1, "workflow_runs": [RUN]}]},
        "/repos/o/r/issues/9/timeline": {"pages": [TIMELINE]},
        "/repos/o/r/issues": {"pages": [[ISSUE, ISSUE_PR]]},
        "/repos/o/r/dependabot/alerts": {"error": "HTTP 403: Resource not accessible by integration"},
        "/repos/o/r/secret-scanning/alerts": {"error": "HTTP 404: Not Found"},
    }


def run(env, out, kinds, extra_args=()):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", "o/r", "--out-dir", str(out), "--kinds", kinds,
         "--no-scorecard", *extra_args],
        env=env, capture_output=True, text=True, check=False,
    )


def windows(runs_since_days: int) -> list[tuple[dt.date, dt.date]]:
    """Mirror fetch_workflow_runs' own window computation so a test can build
    the exact `created=A..B` query keys the fetcher will request, whatever
    day the test happens to run on."""
    since_date = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=runs_since_days)).date()
    today = dt.datetime.now(dt.timezone.utc).date()
    out = []
    start = since_date
    while start <= today:
        end = min(start + dt.timedelta(days=6), today)
        out.append((start, end))
        start = end + dt.timedelta(days=1)
    return out


def runs_query_key(start: dt.date, end: dt.date) -> str:
    return f"/repos/o/r/actions/runs?created={start.isoformat()}..{end.isoformat()}&per_page=100"


def read(out, kind):
    return json.loads((Path(out) / "events" / f"{kind}.json").read_text())


class CollectEventsTests(unittest.TestCase):
    def test_codeql_dump_keeps_only_declared_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, responses())
            out = Path(tmp) / "data"
            r = run(env, out, "codeql_alerts")
            self.assertEqual(r.returncode, 0, r.stderr)
            dump = read(out, "codeql_alerts")
            self.assertEqual(dump["status"], "ok")
            rec = dump["records"][0]
            self.assertEqual(rec["id"], 7)
            self.assertEqual(rec["severity"], "critical")
            self.assertEqual(rec["rule_id"], "py/full-ssrf")
            self.assertEqual(rec["path"], "apps/x.py")
            self.assertNotIn("most_recent_instance", rec)

    def test_pull_request_dump_fetches_detail_and_files_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, responses(), log=True)
            out = Path(tmp) / "data"
            self.assertEqual(run(env, out, "pull_requests").returncode, 0)
            rec = read(out, "pull_requests")["records"][0]
            self.assertEqual(rec["additions"], 100)
            self.assertEqual(rec["files"], ["apps/x.py", "e2e/a.spec.ts", "docs/b.md"])
            self.assertEqual(rec["author"], "d")
            self.assertEqual(rec["author_type"], "User")
            self.assertEqual(rec["head_ref"], "e2e/g1")
            first = len([c for c in calls(env) if "/pulls/5" in " ".join(c)])
            self.assertEqual(run(env, out, "pull_requests").returncode, 0)
            second = len([c for c in calls(env) if "/pulls/5" in " ".join(c)])
            self.assertEqual(second, first, "merged PR detail must come from the sidecar on the second run")
            # Not just "no re-fetch" — the reused record must still carry the
            # first run's detail/files data, not a regression to
            # project_pr(pr, None, None).
            rec2 = read(out, "pull_requests")["records"][0]
            self.assertEqual(rec2["additions"], 100)
            self.assertEqual(rec2["deletions"], 5)
            self.assertEqual(rec2["changed_files"], 3)
            self.assertEqual(rec2["files"], ["apps/x.py", "e2e/a.spec.ts", "docs/b.md"])

    def test_detail_fetch_failure_does_not_misattribute_kind_status(self):
        # A 403 on a per-record detail call (secondary rate limit, say) is
        # not the same thing as the whole kind being forbidden: it must not
        # come back as "not_permitted" the way a 403 on the listing call
        # does.
        with tempfile.TemporaryDirectory() as tmp:
            resp = responses()
            resp["/repos/o/r/pulls/5/files"] = {"error": "HTTP 403: secondary rate limit"}
            env = fake_gh_env(tmp, resp)
            out = Path(tmp) / "data"
            r = run(env, out, "pull_requests")
            self.assertEqual(r.returncode, 0, r.stderr)
            dump = read(out, "pull_requests")
            self.assertEqual(dump["status"], "error")
            self.assertIn("record 5", dump["detail"])
            self.assertIn("/pulls/5/files", dump["detail"])
            self.assertEqual(dump["records"], [])

    def test_workflow_runs_use_list_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, responses())
            out = Path(tmp) / "data"
            self.assertEqual(run(env, out, "workflow_runs").returncode, 0)
            rec = read(out, "workflow_runs")["records"][0]
            self.assertEqual(rec["id"], 11)
            self.assertEqual(rec["workflow"], "E2E Tests")

    def test_issues_skip_pull_requests_and_carry_label_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, responses())
            out = Path(tmp) / "data"
            self.assertEqual(run(env, out, "issues").returncode, 0)
            recs = read(out, "issues")["records"]
            self.assertEqual([r["id"] for r in recs], [9])
            self.assertEqual(recs[0]["labels"], ["needs-triage"])
            self.assertEqual(recs[0]["label_events"][1], {"event": "unlabeled", "label": "needs-triage", "at": "2026-08-28T00:00:00Z"})

    def test_forbidden_and_disabled_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, responses())
            out = Path(tmp) / "data"
            self.assertEqual(run(env, out, "dependabot_alerts,secret_scanning").returncode, 0)
            self.assertEqual(read(out, "dependabot_alerts")["status"], "not_permitted")
            self.assertEqual(read(out, "secret_scanning")["status"], "disabled")
            self.assertEqual(read(out, "dependabot_alerts")["records"], [])

    def test_history_sidecar_keeps_records_that_leave_the_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "data"
            env = fake_gh_env(tmp, responses())
            self.assertEqual(run(env, out, "workflow_runs").returncode, 0)
            gone = responses(); gone["/repos/o/r/actions/runs"] = {"pages": [{"total_count": 0, "workflow_runs": []}]}
            env = fake_gh_env(tmp, gone)
            self.assertEqual(run(env, out, "workflow_runs").returncode, 0)
            self.assertEqual(read(out, "workflow_runs")["records"], [])
            lines = (out / "events" / "history" / "workflow_runs.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["record"]["id"], 11)

    def test_unchanged_record_is_not_appended_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "data"
            env = fake_gh_env(tmp, responses())
            run(env, out, "codeql_alerts"); run(env, out, "codeql_alerts")
            lines = (out / "events" / "history" / "codeql_alerts.jsonl").read_text().splitlines()
            self.assertEqual(len(lines), 1)

    def test_workflow_runs_windows_union_by_id_later_window_wins(self):
        # --runs-since-days 8 always produces exactly two 7-day-or-shorter
        # windows (see windows()): the fetcher must union both, dedupe the id
        # that appears in both, and keep the later window's copy.
        (w0, w1) = windows(8)
        run_only_in_w0 = {"id": 101, "name": "E2E", "event": "push", "status": "completed",
                           "conclusion": "success", "created_at": "2026-08-20T00:00:00Z",
                           "updated_at": "2026-08-20T00:05:00Z", "run_started_at": "2026-08-20T00:00:10Z",
                           "head_sha": "sha-101"}
        overlap_old = {"id": 202, "name": "Backend", "event": "push", "status": "completed",
                       "conclusion": "failure", "created_at": "2026-08-20T01:00:00Z",
                       "updated_at": "2026-08-20T01:05:00Z", "run_started_at": "2026-08-20T01:00:10Z",
                       "head_sha": "sha-old"}
        overlap_new = dict(overlap_old, conclusion="success", head_sha="sha-new",
                            updated_at="2026-08-27T01:05:00Z")
        run_only_in_w1 = {"id": 303, "name": "Frontend", "event": "push", "status": "completed",
                           "conclusion": "success", "created_at": "2026-08-27T02:00:00Z",
                           "updated_at": "2026-08-27T02:05:00Z", "run_started_at": "2026-08-27T02:00:10Z",
                           "head_sha": "sha-303"}
        with tempfile.TemporaryDirectory() as tmp:
            resp = responses()
            del resp["/repos/o/r/actions/runs"]
            resp[runs_query_key(*w0)] = {"pages": [{"total_count": 2, "workflow_runs": [run_only_in_w0, overlap_old]}]}
            resp[runs_query_key(*w1)] = {"pages": [{"total_count": 2, "workflow_runs": [overlap_new, run_only_in_w1]}]}
            env = fake_gh_env(tmp, resp)
            out = Path(tmp) / "data"
            r = run(env, out, "workflow_runs", extra_args=("--runs-since-days", "8"))
            self.assertEqual(r.returncode, 0, r.stderr)
            dump = read(out, "workflow_runs")
            self.assertEqual(dump["status"], "ok")
            recs = {rec["id"]: rec for rec in dump["records"]}
            self.assertEqual(sorted(recs), [101, 202, 303])
            self.assertEqual(recs[202]["conclusion"], "success", "later window's copy must win the merge")
            self.assertEqual(recs[202]["head_sha"], "sha-new")

    def test_workflow_runs_window_hitting_the_1000_cap_is_reported(self):
        (w0,) = windows(1)  # a 1-day lookback is always a single window
        capped = [
            {"id": i, "name": "E2E", "event": "push", "status": "completed", "conclusion": "success",
             "created_at": "2026-08-20T00:00:00Z", "updated_at": "2026-08-20T00:05:00Z",
             "run_started_at": "2026-08-20T00:00:10Z", "head_sha": f"sha-{i}"}
            for i in range(1000)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            resp = responses()
            del resp["/repos/o/r/actions/runs"]
            resp[runs_query_key(*w0)] = {"pages": [{"total_count": 1000, "workflow_runs": capped}]}
            env = fake_gh_env(tmp, resp)
            out = Path(tmp) / "data"
            r = run(env, out, "workflow_runs", extra_args=("--runs-since-days", "1"))
            self.assertEqual(r.returncode, 0, r.stderr)
            dump = read(out, "workflow_runs")
            self.assertEqual(dump["status"], "ok")
            self.assertEqual(len(dump["records"]), 1000)
            self.assertIn("1000-record listing cap", dump["detail"])
            self.assertIn(f"{w0[0].isoformat()}..{w0[1].isoformat()}", dump["detail"])

    def test_workflow_runs_calls_carry_windowed_created_param(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, responses(), log=True)
            out = Path(tmp) / "data"
            r = run(env, out, "workflow_runs", extra_args=("--runs-since-days", "8"))
            self.assertEqual(r.returncode, 0, r.stderr)
            runs_calls = [c for c in calls(env) if any("/actions/runs" in a for a in c)]
            created_params = []
            for call in runs_calls:
                arg = next(a for a in call if "/actions/runs" in a)
                match = re.search(r"created=(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", arg)
                self.assertIsNotNone(match, f"no created=A..B param in {arg!r}")
                created_params.append(match.group(0))
            self.assertEqual(len(runs_calls), 2, "8-day lookback must produce exactly two windowed calls")
            self.assertEqual(len(set(created_params)), 2, "each window must carry its own distinct created range")


if __name__ == "__main__":
    unittest.main()
