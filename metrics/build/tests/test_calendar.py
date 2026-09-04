import datetime as dt
import unittest

from calendar_ import daily_dates, delta_is_good, forward_fill, is_stale, snapshot_is_stale, snapshot_series, status
from load import SnapshotRow

UTC = dt.timezone.utc
D = dt.date


def ts(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=UTC)


class CalendarTests(unittest.TestCase):
    def test_daily_dates_inclusive(self):
        self.assertEqual(len(daily_dates(D(2026, 8, 30), D(2026, 9, 2))), 4)

    def test_daily_dates_single_day(self):
        self.assertEqual(daily_dates(D(2026, 9, 4), D(2026, 9, 4)), [D(2026, 9, 4)])

    def test_snapshot_series_skips_missing(self):
        rows = [SnapshotRow(ts("2026-08-19T10:00"), "a" * 40, "tests", {"n": 1}),
                SnapshotRow(ts("2026-08-20T10:00"), "b" * 40, "tests", {"m": 2}),
                SnapshotRow(ts("2026-08-21T10:00"), "c" * 40, "tests", {"n": 3})]
        self.assertEqual([(s, v) for _, s, v in snapshot_series(rows, "/n")], [("a" * 40, 1), ("c" * 40, 3)])

    def test_snapshot_series_skips_non_numeric(self):
        rows = [SnapshotRow(ts("2026-08-19T10:00"), "a" * 40, "tests", {"n": "not a number"}),
                SnapshotRow(ts("2026-08-20T10:00"), "b" * 40, "tests", {"n": True}),
                SnapshotRow(ts("2026-08-21T10:00"), "c" * 40, "tests", {"n": 3})]
        self.assertEqual([(s, v) for _, s, v in snapshot_series(rows, "/n")], [("c" * 40, 3)])

    def test_forward_fill(self):
        pts = [(ts("2026-08-20T10:00"), 1.0), (ts("2026-08-22T23:00"), 2.0)]
        self.assertEqual(forward_fill(pts, daily_dates(D(2026, 8, 19), D(2026, 8, 23))), [None, 1.0, 1.0, 2.0, 2.0])

    def test_forward_fill_unsorted_input(self):
        pts = [(ts("2026-08-22T23:00"), 2.0), (ts("2026-08-20T10:00"), 1.0)]
        self.assertEqual(forward_fill(pts, daily_dates(D(2026, 8, 19), D(2026, 8, 23))), [None, 1.0, 1.0, 2.0, 2.0])

    def test_forward_fill_last_moment_of_day_counts_for_that_day(self):
        # A point at 23:59:59.5Z (snapshot timestamps carry microseconds) is
        # still within that calendar day, not pushed into the next one — the
        # day boundary is half-open [day 00:00Z, day+1 00:00Z).
        pts = [(dt.datetime(2026, 8, 20, 23, 59, 59, 500000, tzinfo=UTC), 5.0)]
        self.assertEqual(forward_fill(pts, daily_dates(D(2026, 8, 19), D(2026, 8, 20))), [None, 5.0])

    def test_status_rule(self):
        self.assertEqual(status("down", 0, 0, 3, False), "good")        # at target
        self.assertEqual(status("down", 0, 2, 3, False), "good")        # moving toward
        self.assertEqual(status("down", 0, 4, 3, False), "bad")         # moving away
        self.assertEqual(status("down", 0, 3, 3, False), "bad")         # stalled, target unmet
        self.assertEqual(status("down", None, 3, 3, False), "neutral")  # stalled, no target
        self.assertEqual(status("up", 60, 45, 40, False), "good")
        self.assertEqual(status("up", 60, 61, 40, False), "good")
        self.assertEqual(status("zero", None, 1, 1, False), "bad")
        self.assertEqual(status("zero", None, 0, 1, False), "good")
        self.assertEqual(status("info", None, 5, 1, False), "neutral")
        self.assertEqual(status("down", 0, 2, None, False), "neutral")  # no previous point
        self.assertEqual(status("down", 0, 2, 3, True), "stale")
        self.assertEqual(status("down", 0, None, 3, False), "neutral")  # no current value

    def test_delta_is_good(self):
        self.assertTrue(delta_is_good("down", -2))
        self.assertFalse(delta_is_good("down", 2))
        self.assertTrue(delta_is_good("up", 2))
        self.assertTrue(delta_is_good("zero", -1))
        self.assertIsNone(delta_is_good("info", 2))
        self.assertIsNone(delta_is_good("up", 0))

    def test_is_stale(self):
        self.assertFalse(is_stale(ts("2026-09-03T06:00"), D(2026, 9, 4)))
        self.assertTrue(is_stale(ts("2026-09-01T06:00"), D(2026, 9, 4)))
        self.assertTrue(is_stale(None, D(2026, 9, 4)))

    def test_snapshot_is_stale_matches_head(self):
        self.assertFalse(snapshot_is_stale("a" * 40, "a" * 40))

    def test_snapshot_is_stale_mismatch(self):
        self.assertTrue(snapshot_is_stale("a" * 40, "b" * 40))

    def test_snapshot_is_stale_no_rows(self):
        self.assertTrue(snapshot_is_stale(None, "a" * 40))

    def test_snapshot_is_stale_both_none_is_stale(self):
        # Neither a row nor a resolvable HEAD sha exists to compare — must
        # not fall through to `None == None` and read as "fresh".
        self.assertTrue(snapshot_is_stale(None, None))

    def test_snapshot_is_stale_empty_head_is_stale(self):
        self.assertTrue(snapshot_is_stale("a" * 40, ""))


if __name__ == "__main__":
    unittest.main()
