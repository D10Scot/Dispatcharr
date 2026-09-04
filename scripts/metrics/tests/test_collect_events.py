import json
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


def run(env, out, kinds):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", "o/r", "--out-dir", str(out), "--kinds", kinds, "--no-scorecard"],
        env=env, capture_output=True, text=True, check=False,
    )


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


if __name__ == "__main__":
    unittest.main()
