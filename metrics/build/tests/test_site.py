import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from assemble import build_site
from curated import load_curated

HERE = Path(__file__).resolve().parent
DATA = HERE / "fixtures" / "data"
CUR = HERE / "fixtures" / "curated" / "valid"
D = dt.date


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"; self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "base", "--date", "2026-08-19T22:13:45+00:00"); self.base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "second", "--date", "2026-09-03T21:09:00+00:00"); self.second = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "e2e/tests/seeded").mkdir(parents=True); (self.repo / "e2e/tests/seeded/output-m3u.spec.ts").write_text("")
        self.cur = self.tmp / "curated"; shutil.copytree(CUR, self.cur)
        (self.cur / "milestones.yml").write_text((self.cur / "milestones.yml").read_text().replace("BASE", self.base).replace("SECOND", self.second))
        # The fixture data rows use aaaa.../bbbb... SHAs; rewrite them to the repo's so milestones line up.
        self.data = self.tmp / "data"; shutil.copytree(DATA, self.data)
        for f in ("tests.jsonl", "coverage.jsonl"):
            p = self.data / f
            p.write_text(p.read_text().replace("a" * 40, self.base).replace("b" * 40, self.second))
        self.curated = load_curated(self.cur)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def build(self, today=D(2026, 9, 5)):
        return build_site(self.data, self.curated, repo=self.repo, base=self.base, today=today)

    def test_meta_and_freshness(self):
        s = self.build()
        self.assertEqual(s["meta"]["baseline"]["sha"], self.base)
        self.assertEqual(s["meta"]["baseline"]["date"], "2026-08-19")
        self.assertIn("tests", s["meta"]["freshness"])
        self.assertTrue(any("dependabot" in n for n in s["meta"]["source_notes"]))

    def test_headline_tiles(self):
        s = self.build()
        by_id = {h["id"]: h for h in s["headline"]}
        e2e = by_id["e2e_scenarios"]
        self.assertEqual(e2e["now"], 249); self.assertEqual(e2e["at_baseline"], 0)
        # R9(a): the fixture's date range (base 2026-08-19 .. today 2026-09-05)
        # is 18 days, shorter than SPARK_POINTS=30 - spark is bounded by
        # however many days actually exist, not padded out to 30.
        self.assertEqual(len(e2e["spark"]), min(30, len(s["groups"]["safety_net"][0]["daily"])))
        self.assertEqual(e2e["status"], "good")
        cq = by_id["codeql_open_critical_high"]
        self.assertEqual(cq["now"], 2)
        self.assertEqual(cq["daily"][0], ["2026-08-19", None], "before `since` the series is a gap")
        self.assertEqual(cq["daily"][4], ["2026-08-23", 2], "ids 1 and 3 were created on Aug 23")
        self.assertNotIn("proxy_loc", by_id, "headline: false stays off the front page")

    def test_groups_have_every_catalogue_metric_with_commit_series_for_snapshots(self):
        s = self.build()
        ids = {m["id"] for g in s["groups"].values() for m in g}
        self.assertEqual(ids, {"e2e_scenarios", "codeql_open_critical_high", "proxy_loc"})
        e2e = next(m for m in s["groups"]["safety_net"] if m["id"] == "e2e_scenarios")
        self.assertEqual([c[2] for c in e2e["commits"]], [0, 249])
        cq = next(m for m in s["groups"]["security"] if m["id"] == "codeql_open_critical_high")
        self.assertIsNone(cq["commits"])

    def test_stale_series_is_flagged(self):
        # R26: a snapshot-family series (e2e_scenarios, family "tests") goes
        # stale when its family's latest row is behind the repo's current
        # first-parent HEAD - NOT via calendar age (calendar_.is_stale is for
        # derived/event-dump series only; a snapshot family with no new
        # commits in a while is a quiet week, not an unhealthy pipeline).
        # Add a third commit with no corresponding snapshot row so HEAD
        # moves past the family's last row.
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "third", "--date", "2026-09-04T12:00:00+00:00")
        s = self.build()
        e2e = {h["id"]: h for h in s["headline"]}["e2e_scenarios"]
        self.assertTrue(e2e["stale"]); self.assertEqual(e2e["status"], "stale")

    def test_phases_and_compare(self):
        s = self.build()
        self.assertEqual([p["id"] for p in s["phases"]], ["investigate", "phase0"])
        self.assertEqual(s["phases"][0]["start"], "2026-08-19")
        key = f"{self.base}..{self.second}"
        self.assertIn(key, s["compare"])
        row = next(r for r in s["compare"][key] if r["id"] == "e2e_scenarios")
        self.assertEqual((row["from"], row["to"], row["delta"], row["good"]), (0, 249, 249, True))

    def test_defects_section(self):
        s = self.build()
        self.assertEqual(len(s["defects"]["entries"]), 2)
        last_day = s["defects"]["by_status_daily"][-1]
        self.assertEqual(last_day[1]["pinned"], 1)

    def test_cli_builds_and_validates(self):
        out = self.tmp / "site.json"
        # R9(b): cwd is the repo root (HERE.parents[2]: tests -> build -> metrics -> repo root),
        # not parents[3].
        r = subprocess.run([sys.executable, "-m", "metrics.build", "--data", str(self.data), "--curated", str(self.cur),
                            "--out", str(out), "--repo", str(self.repo), "--base", self.base, "--today", "2026-09-05"],
                           capture_output=True, text=True, cwd=str(HERE.parents[2]))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("headline", json.loads(out.read_text()))
        r = subprocess.run([sys.executable, "-m", "metrics.build", "--validate-only", "--curated", str(self.cur),
                            "--repo", str(self.repo), "--base", self.base], capture_output=True, text=True, cwd=str(HERE.parents[2]))
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
