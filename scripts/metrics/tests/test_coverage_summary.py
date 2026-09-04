import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "coverage_summary.py"

BACKEND = {
    "totals": {"percent_covered": 45.678},
    "files": {
        "apps/proxy/a.py": {"summary": {"covered_lines": 10, "num_statements": 40}},
        "apps/proxy/b.py": {"summary": {"covered_lines": 30, "num_statements": 40}},
        "core/c.py": {"summary": {"covered_lines": 9, "num_statements": 10}},
        "dispatcharr/d.py": {"summary": {"covered_lines": 0, "num_statements": 10}},
    },
}
STATUS = {"labels": ["apps.proxy.tests", "core.tests"], "failed_labels": ["core.tests"]}
FRONTEND = {"total": {"lines": {"pct": 71.94}}}


def run(args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


class CoverageSummaryTests(unittest.TestCase):
    def test_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            (t / "b.json").write_text(json.dumps(BACKEND)); (t / "s.json").write_text(json.dumps(STATUS)); (t / "f.json").write_text(json.dumps(FRONTEND))
            r = run(["--backend", str(t / "b.json"), "--backend-status", str(t / "s.json"), "--frontend", str(t / "f.json"), "--out", str(t / "row.json")])
            self.assertEqual(r.returncode, 0, r.stderr)
            row = json.loads((t / "row.json").read_text())
            self.assertEqual(row["backend_line_pct"], 45.68)
            self.assertEqual(row["backend_by_app"], {"apps.proxy": 50.0, "core": 90.0, "dispatcharr": 0.0})
            self.assertEqual(row["backend_status"], "failed")
            self.assertEqual(row["backend_failed_labels"], ["core.tests"])
            self.assertEqual(row["frontend_line_pct"], 71.94)
            self.assertEqual(row["frontend_status"], "ok")

    def test_missing_inputs_are_failed_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            r = run(["--backend", str(t / "nope.json"), "--backend-status", str(t / "nope2.json"), "--frontend", str(t / "nope3.json"), "--out", str(t / "row.json")])
            self.assertEqual(r.returncode, 0, r.stderr)
            row = json.loads((t / "row.json").read_text())
            self.assertIsNone(row["backend_line_pct"]); self.assertEqual(row["backend_status"], "failed")
            self.assertIsNone(row["frontend_line_pct"]); self.assertEqual(row["frontend_status"], "failed")
