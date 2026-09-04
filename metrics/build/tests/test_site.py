import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
# `unittest discover -t metrics/build` puts only metrics/build on sys.path, so
# `from assemble import ...`/`from curated import ...` below resolve but a
# sibling test helper does not without this (R2).
sys.path.insert(0, str(HERE))

from assemble import build_site  # noqa: E402
from curated import load_curated  # noqa: E402
from _git import git  # noqa: E402  (R2/R10: shared helper, not redefined here)

DATA = HERE / "fixtures" / "data"
CUR = HERE / "fixtures" / "curated" / "valid"
D = dt.date


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

    def test_derived_series_goes_stale_via_age(self):
        # The 2-day age rule (calendar_.is_stale) is still the right check
        # for a DERIVED (event-dump) series: there's no commit sha to compare
        # against HEAD, only a fetch timestamp. codeql_alerts.json's
        # fetched_at is 2026-09-05T06:05:00Z; five days later is well past
        # the 2-day threshold.
        s = self.build(today=D(2026, 9, 10))
        cq = {h["id"]: h for h in s["headline"]}["codeql_open_critical_high"]
        self.assertTrue(cq["stale"]); self.assertEqual(cq["status"], "stale")

    def test_snapshot_family_with_no_rows_at_all_is_stale(self):
        # proxy_loc's family is "code_health", which has no fixture file at
        # all (only tests.jsonl/coverage.jsonl exist under fixtures/data) -
        # no data is not fresh, regardless of HEAD.
        s = self.build()
        proxy = next(m for m in s["groups"]["extraction"] if m["id"] == "proxy_loc")
        self.assertTrue(proxy["stale"]); self.assertIsNone(proxy["now"])

    def test_milestones_sort_by_first_parent_order_not_curated_file_order(self):
        # Two milestones on the SAME calendar day tie on their date string,
        # so sorting by date alone leaves them in whichever order the
        # curated file happened to list them - undefined, and observed
        # backwards on the real data (adjacent compare pairs reporting
        # deltas the wrong way round). Add a same-day-but-git-later commit,
        # and list it BEFORE the earlier same-day milestone in the curated
        # file, to prove the sort uses git chronology, not file order.
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "same-day", "--date", "2026-09-03T21:09:30+00:00")
        third = git(self.repo, "rev-parse", "HEAD")
        # setUp() already substituted the BASE/SECOND placeholders for the
        # real shas, so match on the real `self.second` sha here.
        text = (self.cur / "milestones.yml").read_text()
        text = text.replace(
            f"  - sha: {self.second}",
            f'  - sha: {third}\n    label: Same-day, filed first\n    kind: goal\n    phase: phase0\n'
            f'    pr: null\n    summary: "Listed before SECOND in the YAML on purpose."\n  - sha: {self.second}',
        )
        (self.cur / "milestones.yml").write_text(text)
        curated = load_curated(self.cur)
        s = build_site(self.data, curated, repo=self.repo, base=self.base, today=D(2026, 9, 5))
        self.assertEqual([m["sha"] for m in s["milestones"]], [self.base, self.second, third])
        self.assertIn(f"{self.second}..{third}", s["compare"])
        self.assertNotIn(f"{third}..{self.second}", s["compare"])

    def test_daily_family_uses_age_rule_not_sha_rule(self):
        # R27: "coverage" is populated by a once-daily job, not on every
        # push - its row is keyed to whatever sha HEAD was at 06:15 UTC that
        # morning. Comparing that sha against the CURRENT HEAD (the sha
        # rule used for push-driven snapshot families) would flag it stale
        # on every push since, even right after a healthy run. Add a commit
        # so HEAD moves past the coverage row's sha, and confirm freshness
        # is still judged by age, not by the sha mismatch.
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "third", "--date", "2026-09-04T00:00:00+00:00")
        cat = (self.cur / "catalogue.yml").read_text()
        cat += (
            "\n- id: backend_coverage\n  family: coverage\n  path: /backend_line_pct\n"
            "  label: Backend coverage\n  unit: pct\n  direction: up\n  target: null\n"
            "  group: safety_net\n  headline: false\n  since: 2026-08-19\n"
            '  note: "Daily job."\n'
        )
        (self.cur / "catalogue.yml").write_text(cat)
        row = {"commit_sha": self.base, "family": "coverage", "metrics": {"backend_line_pct": 50.0},
               "timestamp": "2026-09-05T06:15:00+00:00"}
        (self.data / "coverage.jsonl").write_text(json.dumps(row) + "\n")
        curated = load_curated(self.cur)

        # Dated "today" (age 0): fresh, even though its sha (self.base) is
        # not the current HEAD (third).
        s = build_site(self.data, curated, repo=self.repo, base=self.base, today=D(2026, 9, 5))
        cov = next(m for m in s["groups"]["safety_net"] if m["id"] == "backend_coverage")
        self.assertFalse(cov["stale"])

        # Same row, no new one added, but built 3 days later: now stale by age.
        s2 = build_site(self.data, curated, repo=self.repo, base=self.base, today=D(2026, 9, 8))
        cov2 = next(m for m in s2["groups"]["safety_net"] if m["id"] == "backend_coverage")
        self.assertTrue(cov2["stale"])

    def test_phases_and_compare(self):
        s = self.build()
        self.assertEqual([p["id"] for p in s["phases"]], ["investigate", "phase0"])
        self.assertEqual(s["phases"][0]["start"], "2026-08-19")
        key = f"{self.base}..{self.second}"
        self.assertIn(key, s["compare"])
        row = next(r for r in s["compare"][key] if r["id"] == "e2e_scenarios")
        self.assertEqual((row["from"], row["to"], row["delta"], row["good"]), (0, 249, 249, True))

    def test_compare_includes_a_derived_metric_via_forward_filled_daily_value(self):
        # R31: codeql_open_critical_high (family "derived") has no per-sha
        # row to look up - before this fix it was skipped from `compare`
        # entirely (`if not e["commits"]: continue`, and a derived series'
        # `commits` is always None). It must now appear, read at each
        # milestone's own calendar date from the same forward-filled daily
        # series the chart draws. `self.base` (2026-08-19) is before the
        # metric's `since` (2026-08-23), so `from` is a genuine null - not
        # a bug in this test, the gap the chart itself shows (see
        # test_headline_tiles: daily[0] == ["2026-08-19", None]). `to` is
        # the value on `self.second` (2026-09-03): CodeQL alerts 1 (critical,
        # still open) and 9 (high, open, retired from the live API but kept
        # via the history sidecar) are open at that date - 2.
        s = self.build()
        key = f"{self.base}..{self.second}"
        row = next(r for r in s["compare"][key] if r["id"] == "codeql_open_critical_high")
        self.assertEqual((row["from"], row["to"], row["delta"], row["good"]), (None, 2, None, None))

    def test_compare_reads_a_daily_family_metric_via_forward_filled_daily_value(self):
        # R33(2): a DAILY_FAMILIES metric (e.g. "coverage") is keyed to
        # whatever sha the once-daily job happened to see (R27's age rule,
        # not the sha rule) - looking it up by the milestone's own sha in
        # `compare` (the plain snapshot-metric branch) would almost always
        # miss, leaving these headline tiles null in every pair even though
        # the chart itself shows a value. The coverage row below sits at
        # `self.base`'s sha - deliberately NOT `self.second`'s, the pair's
        # `to` side - dated before `self.second` (2026-09-03): only reading
        # the forward-filled daily value on that date (not the row's own
        # sha) can find it.
        cat = (self.cur / "catalogue.yml").read_text()
        cat += (
            "\n- id: backend_coverage\n  family: coverage\n  path: /backend_line_pct\n"
            "  label: Backend coverage\n  unit: pct\n  direction: up\n  target: null\n"
            "  group: safety_net\n  headline: false\n  since: 2026-08-19\n"
            '  note: "Daily job."\n'
        )
        (self.cur / "catalogue.yml").write_text(cat)
        row = {"commit_sha": self.base, "family": "coverage", "metrics": {"backend_line_pct": 50.0},
               "timestamp": "2026-09-01T06:15:00+00:00"}
        (self.data / "coverage.jsonl").write_text(json.dumps(row) + "\n")
        curated = load_curated(self.cur)

        s = build_site(self.data, curated, repo=self.repo, base=self.base, today=D(2026, 9, 5))
        key = f"{self.base}..{self.second}"
        cov = next(r for r in s["compare"][key] if r["id"] == "backend_coverage")
        self.assertEqual(cov["to"], 50.0)

    def test_compare_with_a_latest_sha_absent_from_the_local_repo_builds_without_error(self):
        # R33(1): the synthetic base..latest_sha pair's `latest_sha` comes
        # straight from a data row's commit_sha, not a curated (and
        # therefore validate()-checked) milestone - a checkout whose object
        # store lags the collector by one push (the documented preview
        # recipe used to fetch only metrics-data, not main too) can have a
        # `latest_sha` `git show` has never heard of. Add a fourth,
        # chronologically-latest snapshot row at a sha that plainly doesn't
        # exist anywhere in this test's throwaway repo.
        missing = "c" * 40
        p = self.data / "tests.jsonl"
        row = {"commit_sha": missing, "family": "tests",
               "metrics": {"backend_test_count": 1900, "e2e_scenario_count": 300,
                           "coverage_md_rows": {"done": 150, "known_bug": 10, "todo": 10}},
               "timestamp": "2026-09-05T12:00:00+00:00"}
        p.write_text(p.read_text() + json.dumps(row) + "\n")

        s = self.build()  # must not raise CalledProcessError
        key = f"{self.base}..{missing}"
        self.assertIn(key, s["compare"])
        cq = next(r for r in s["compare"][key] if r["id"] == "codeql_open_critical_high")
        self.assertEqual((cq["from"], cq["to"], cq["delta"], cq["good"]), (None, None, None, None))

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
        # sort_keys=True: object keys inside site.json come out alphabetical
        # (readable diffs), not insertion order.
        self.assertEqual(list(json.loads(out.read_text())["meta"].keys()),
                          sorted(json.loads(out.read_text())["meta"].keys()))

    def test_cli_malformed_today_is_a_one_line_usage_error_not_a_traceback(self):
        out = self.tmp / "site.json"
        r = subprocess.run([sys.executable, "-m", "metrics.build", "--data", str(self.data), "--curated", str(self.cur),
                            "--out", str(out), "--repo", str(self.repo), "--base", self.base, "--today", "not-a-date"],
                           capture_output=True, text=True, cwd=str(HERE.parents[2]))
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("--today", r.stderr)
        self.assertFalse(out.exists())

    def test_cli_today_before_baseline_is_a_one_line_usage_error(self):
        # R32(a): the baseline is self.base, dated 2026-08-19 - a --today
        # before that produces a negative-length (or zero, exclusive) daily
        # series that downstream code was never written to handle.
        out = self.tmp / "site.json"
        r = subprocess.run([sys.executable, "-m", "metrics.build", "--data", str(self.data), "--curated", str(self.cur),
                            "--out", str(out), "--repo", str(self.repo), "--base", self.base, "--today", "2026-08-01"],
                           capture_output=True, text=True, cwd=str(HERE.parents[2]))
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("--today", r.stderr)
        self.assertIn("2026-08-19", r.stderr, "the baseline date should be named in the error")
        self.assertFalse(out.exists())

    def test_cli_missing_out_is_a_usage_error_before_any_data_is_touched(self):
        # --data present, --out missing, and --curated pointed at a
        # nonexistent directory: the missing---out usage check must fire
        # before load_curated() ever runs, or this would fail with a
        # curated-files-not-found error (exit 1) instead of a usage error
        # (exit 2).
        r = subprocess.run([sys.executable, "-m", "metrics.build", "--data", str(self.data),
                            "--curated", str(self.tmp / "does-not-exist"), "--repo", str(self.repo), "--base", self.base],
                           capture_output=True, text=True, cwd=str(HERE.parents[2]))
        self.assertEqual(r.returncode, 2)
        self.assertIn("--out", r.stderr)


if __name__ == "__main__":
    unittest.main()
