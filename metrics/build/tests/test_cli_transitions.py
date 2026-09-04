"""The CLI's forward-only status-transition check: __main__.py's
`_load_committed_defects` reads `metrics/curated/defects.yml` off
`origin/main` (falling back to `main`) via `git show` and hands it to
`curated.validate_transitions` alongside the working-copy ledger. Any
failure to resolve that committed version - no git, no such ref, the file
not present there, or a malformed document - must skip the check with one
printed line rather than fail the build."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CUR = HERE / "fixtures" / "curated" / "valid"
REPO_ROOT = HERE.parents[2]  # tests -> build -> metrics -> repo root


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                           check=True, capture_output=True, text=True).stdout.strip()


def _seed_test_file(repo: Path) -> None:
    # The "valid" fixture's pinned defect (m3u-quote) names this path;
    # validate() checks any non-null `test` field exists in the repo
    # regardless of the entry's status, so every repo used here needs it.
    (repo / "e2e/tests/seeded").mkdir(parents=True, exist_ok=True)
    (repo / "e2e/tests/seeded/output-m3u.spec.ts").write_text("")


def run_cli(curated_dir: Path, repo: Path, base: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "metrics.build", "--validate-only", "--curated", str(curated_dir),
         "--repo", str(repo), "--base", base],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )


class TransitionCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_backward_transition_against_main_fails(self):
        # "main" carries the curated fixture as committed - m3u-quote is
        # `pinned` there.
        repo = self.tmp / "repo"; repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        _seed_test_file(repo)
        (repo / "metrics/curated").mkdir(parents=True)
        for f in ("catalogue.yml", "milestones.yml", "defects.yml"):
            shutil.copy(CUR / f, repo / "metrics/curated" / f)
        git(repo, "add", "-A")
        # milestones.yml still has the BASE/SECOND placeholders at this
        # commit - fine, main's copy is only ever read for defects.yml.
        git(repo, "commit", "-q", "-m", "seed ledger")
        base = git(repo, "rev-parse", "HEAD")

        # The working copy: the same fixture, but m3u-quote moved from
        # `pinned` back to `open` (still valid on its own - it keeps its
        # `issue`), and the milestone placeholders resolved against `base`
        # so validate() has nothing else to complain about.
        working = self.tmp / "working"; shutil.copytree(CUR, working)
        (working / "defects.yml").write_text(
            (working / "defects.yml").read_text().replace("status: pinned", "status: open", 1)
        )
        (working / "milestones.yml").write_text(
            (working / "milestones.yml").read_text().replace("BASE", base).replace("SECOND", base)
        )

        r = run_cli(working, repo, base)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("status moved backward", r.stderr)
        self.assertIn("pinned -> open", r.stderr)

    def test_skip_path_prints_and_exits_zero_when_ledger_absent_on_ref(self):
        # "main" here has no metrics/curated/defects.yml at all - the real
        # state of this repo's own origin/main today.
        repo = self.tmp / "repo"; repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        _seed_test_file(repo)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base, no curated tree")
        base = git(repo, "rev-parse", "HEAD")

        working = self.tmp / "working"; shutil.copytree(CUR, working)
        (working / "milestones.yml").write_text(
            (working / "milestones.yml").read_text().replace("BASE", base).replace("SECOND", base)
        )

        r = run_cli(working, repo, base)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("transition check skipped:", r.stdout)
        self.assertIn("not present on main", r.stdout)


if __name__ == "__main__":
    unittest.main()
