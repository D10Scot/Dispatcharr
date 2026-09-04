import datetime as dt
import json
import shutil
import tempfile
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

    def test_parse_ts_naive_is_treated_as_utc_not_host_local(self):
        # A naive value has no offset to convert from; `.astimezone()` would
        # otherwise assume the build host's local timezone, silently
        # shifting the hour on any host not set to UTC.
        parsed = parse_ts("2026-08-23T16:00:00")
        self.assertEqual(parsed, dt.datetime(2026, 8, 23, 16, 0, 0, tzinfo=dt.timezone.utc))

    def test_event_record_without_id_raises(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            events_dir = tmp / "events"
            events_dir.mkdir()
            (events_dir / "broken_kind.json").write_text(json.dumps({
                "kind": "broken_kind", "fetched_at": "2026-09-05T06:05:00+00:00", "repo": "o/r",
                "status": "ok", "detail": None, "records": [{"not_id": 1}],
            }))
            with self.assertRaises(KeyError):
                load_events(tmp)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
