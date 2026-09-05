"""R30: --ref's "auto" default must resolve to origin/main when the repo has
it, even when a checked-out local main lags behind (a fetch with no
merge/rebase) - see gitinfo.default_ref for the unit-level check. This is
the CLI/build-level proof: a repo where origin/main is ahead of local main
by one commit, and a snapshot row only reachable via that extra commit, must
build as fresh (its row matches HEAD) rather than stale (which is what a
build wrongly pinned to the literal "main" would report, since first-parent
walking "main" would stop one commit short)."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _git import git  # noqa: E402  (R2/R10: shared helper, not redefined here)

CUR = HERE / "fixtures" / "curated" / "valid"
DATA = HERE / "fixtures" / "data"
REPO_ROOT = HERE.parents[2]  # tests -> build -> metrics -> repo root


class RefAutoDefaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_ref_auto_prefers_origin_main_over_a_stale_local_main(self):
        repo = self.tmp / "repo"; repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        (repo / "e2e/tests/seeded").mkdir(parents=True)
        (repo / "e2e/tests/seeded/output-m3u.spec.ts").write_text("")
        git(repo, "commit", "-q", "--allow-empty", "-m", "base", "--date", "2026-08-19T22:13:45+00:00")
        base = git(repo, "rev-parse", "HEAD")
        git(repo, "commit", "-q", "--allow-empty", "-m", "second", "--date", "2026-09-03T21:09:00+00:00")
        second = git(repo, "rev-parse", "HEAD")

        # A third commit exists in the object store but only refs/remotes/
        # origin/main points at it - local `main` (the checked-out branch)
        # stays at `second`, mirroring a real checkout after `git fetch`
        # with no merge or rebase.
        git(repo, "checkout", "-q", "-b", "tmp-ahead", second)
        git(repo, "commit", "-q", "--allow-empty", "-m", "third (origin ahead)", "--date", "2026-09-04T12:00:00+00:00")
        ahead = git(repo, "rev-parse", "HEAD")
        git(repo, "update-ref", "refs/remotes/origin/main", ahead)
        git(repo, "checkout", "-q", "main")
        git(repo, "branch", "-q", "-D", "tmp-ahead")

        cur = self.tmp / "curated"; shutil.copytree(CUR, cur)
        (cur / "milestones.yml").write_text(
            (cur / "milestones.yml").read_text().replace("BASE", base).replace("SECOND", second)
        )
        data = self.tmp / "data"; shutil.copytree(DATA, data)
        # tests.jsonl's rows use aaaa.../bbbb... shas; rewrite to base/second,
        # then append a third row at `ahead` - the commit only origin/main
        # reaches, and the family's chronologically-latest row.
        p = data / "tests.jsonl"
        text = p.read_text().replace("a" * 40, base).replace("b" * 40, second)
        third_row = json.dumps({
            "commit_sha": ahead, "family": "tests",
            "metrics": {"backend_test_count": 1900, "e2e_scenario_count": 260,
                        "coverage_md_rows": {"done": 140, "known_bug": 20, "todo": 20}},
            "timestamp": "2026-09-04T12:05:00+00:00",
        })
        p.write_text(text + third_row + "\n")
        (data / "coverage.jsonl").write_text(
            (data / "coverage.jsonl").read_text().replace("a" * 40, base).replace("b" * 40, second)
        )

        out = self.tmp / "site.json"
        r = subprocess.run(
            [sys.executable, "-m", "metrics.build", "--data", str(data), "--curated", str(cur),
             "--out", str(out), "--repo", str(repo), "--base", base, "--today", "2026-09-05"],
            # Deliberately no --ref: this is exactly what "auto" must handle.
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        site = json.loads(out.read_text())
        e2e = next(m for m in site["groups"]["safety_net"] if m["id"] == "e2e_scenarios")
        # The discriminating signal is `stale`, not `now`: forward_fill reads
        # rows by timestamp regardless of git reachability, so `now` is 260
        # either way. `stale` (calendar_.snapshot_is_stale) compares the
        # family's latest row sha against first_parent_shas(...)[-1] - if
        # --ref's auto default had wrongly stayed the literal "main" (local
        # tip: `second`), head_sha would be `second`, which does not match
        # the latest row's sha (`ahead`) -> stale=True. Only resolving to
        # origin/main (head_sha == ahead) makes this False.
        self.assertEqual(e2e["now"], 260)
        self.assertFalse(e2e["stale"])


if __name__ == "__main__":
    unittest.main()
