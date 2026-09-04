import datetime as dt
import unittest
from pathlib import Path

from load import load_events, load_snapshots, parse_ts, pointer

DATA = Path(__file__).resolve().parent / "fixtures" / "data"


class LoadTests(unittest.TestCase):
    def test_snapshots_sorted_and_retired_families_ignored(self):
        fams = load_snapshots(DATA)
        self.assertEqual(set(fams), {"tests", "coverage"})
        self.assertEqual([r.commit_sha[:1] for r in fams["tests"]], ["a", "b"])
        self.assertEqual(fams["tests"][0].timestamp.tzinfo, dt.timezone.utc)

    def test_pointer(self):
        m = load_snapshots(DATA)["tests"][1].metrics
        self.assertEqual(pointer(m, "/coverage_md_rows/done"), 132)
        self.assertIsNone(pointer(m, "/nope"))
        self.assertIsNone(pointer(m, "/coverage_md_rows/nope"))

    def test_events_union_current_wins(self):
        dumps = load_events(DATA)
        alerts = {r["id"]: r for r in dumps["codeql_alerts"].records}
        self.assertEqual(alerts[1]["severity"], "critical", "current dump overrides the stale history line")
        self.assertIn(9, alerts, "history-only record retained")
        self.assertEqual(dumps["codeql_alerts"].status, "ok")
        self.assertEqual(dumps["dependabot_alerts"].status, "not_permitted")
        self.assertNotIn("secret_scanning", dumps)

    def test_parse_ts(self):
        self.assertEqual(parse_ts("2026-08-23T16:00:00Z").tzinfo, dt.timezone.utc)
        self.assertEqual(parse_ts("2026-08-23T18:00:00+02:00").hour, 16)


if __name__ == "__main__":
    unittest.main()
