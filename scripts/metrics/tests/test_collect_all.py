import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
COLLECT_ALL = SCRIPTS / "collect_all.py"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def make_git_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
    return repo


class CollectAllTests(unittest.TestCase):
    def test_external_family_written_only_from_extra_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            extra = Path(tmp) / "cov.json"
            extra.write_text(json.dumps({"backend_line_pct": 45.6}))
            out = Path(tmp) / "out"
            r = subprocess.run([sys.executable, str(COLLECT_ALL), "--repo-root", str(repo), "--out-dir", str(out),
                                "--only", "coverage", "--extra-metrics", f"coverage={extra}"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            row = json.loads((out / "coverage.jsonl").read_text().splitlines()[0])
            self.assertEqual(row["family"], "coverage")
            self.assertEqual(row["metrics"]["backend_line_pct"], 45.6)

    def test_external_family_without_extra_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            out = Path(tmp) / "out"
            r = subprocess.run([sys.executable, str(COLLECT_ALL), "--repo-root", str(repo), "--out-dir", str(out), "--only", "coverage"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertFalse((out / "coverage.jsonl").exists())

    def test_one_failing_family_does_not_stop_the_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_git_repo(Path(tmp))
            out = Path(tmp) / "out"
            # A repo root that is a git repo but has no apps/ makes every checkout
            # collector emit zeros rather than fail, so force a failure by pointing
            # one family's script at a missing file via the override env used only
            # by this test.
            env = dict(__import__("os").environ, METRICS_COLLECTOR_OVERRIDE="architecture=/nonexistent.py")
            r = subprocess.run([sys.executable, str(COLLECT_ALL), "--repo-root", str(repo), "--out-dir", str(out),
                                "--only", "code_health,architecture,tests"], capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 1)
            self.assertTrue((out / "code_health.jsonl").exists())
            self.assertTrue((out / "tests.jsonl").exists())
            self.assertFalse((out / "architecture.jsonl").exists())
            self.assertIn("architecture", r.stderr)
