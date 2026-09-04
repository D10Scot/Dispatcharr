import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "collect_tests.py"


def make_repo(tmp: Path) -> None:
    (tmp / "apps" / "x" / "tests").mkdir(parents=True)
    (tmp / "apps" / "x" / "tests" / "test_a.py").write_text("def test_one():\n    pass\n\ndef test_two():\n    pass\n")
    (tmp / "metrics" / "build" / "tests").mkdir(parents=True)
    (tmp / "metrics" / "build" / "tests" / "test_b.py").write_text("def test_not_counted():\n    pass\n")
    (tmp / "scripts" / "metrics" / "tests").mkdir(parents=True)
    (tmp / "scripts" / "metrics" / "tests" / "test_c.py").write_text("def test_not_counted_either():\n    pass\n")
    (tmp / "e2e").mkdir()
    (tmp / "e2e" / "COVERAGE.md").write_text(
        "| Area | Flow | Goal | Status |\n|---|---|---|---|\n"
        "| A | f1 | G1 | done |\n| A | f2 | G1 | known-bug |\n| B | f3 | G2 | todo |\n| B | f4 | G2 | done |\n"
    )


class CollectTestsTests(unittest.TestCase):
    def test_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(Path(tmp))
            r = subprocess.run([sys.executable, str(SCRIPT), "--repo-root", tmp], capture_output=True, text=True, check=True)
            m = json.loads(r.stdout)
            self.assertEqual(m["backend_test_count"], 2)
            self.assertEqual(m["coverage_md_rows"], {"done": 2, "known_bug": 1, "todo": 1})

    def test_missing_coverage_md_is_zero_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(SCRIPT), "--repo-root", tmp], capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(r.stdout)["coverage_md_rows"], {"done": 0, "known_bug": 0, "todo": 0})
