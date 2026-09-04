import datetime as dt
import unittest
from pathlib import Path

from curated import Defect
from derive import DERIVATION_SOURCES, DERIVATIONS, Context
from load import load_events

DATA = Path(__file__).resolve().parent / "fixtures" / "data"
D = dt.date


def ctx():
    defects = [
        Defect(id="a", title="a", area="correctness", severity="high", status="pinned", first_seen=D(2026, 8, 22), status_changed=D(2026, 8, 30), issue=1, test="x"),
        Defect(id="b", title="b", area="security", severity="high", status="fixed", first_seen=D(2026, 8, 22), status_changed=D(2026, 9, 3), fixed_in=154),
        Defect(id="c", title="c", area="security", severity="low", status="open", first_seen=D(2026, 8, 22), status_changed=D(2026, 8, 22), source="s"),
    ]
    return Context(events=load_events(DATA), defects=defects)


class DeriveTests(unittest.TestCase):
    def setUp(self):
        self.c = ctx()

    def d(self, name, day, /, **params):
        # name/day are positional-only so a derivation param also called
        # "name" (scorecard_check's) can still travel through **params.
        return DERIVATIONS[name](self.c, day, params)

    def test_codeql_open_count_as_of_dates(self):
        # ids 1,3,9 open on Aug 24 (2 created Aug 28); id 3 dismissed Aug 30; id 2 fixed Sep 3
        self.assertEqual(self.d("codeql_open_count", D(2026, 8, 22), severities=["critical", "high"]), 0)
        self.assertEqual(self.d("codeql_open_count", D(2026, 8, 24), severities=["critical", "high"]), 3)
        self.assertEqual(self.d("codeql_open_count", D(2026, 8, 29), severities=["critical", "high"]), 4)
        self.assertEqual(self.d("codeql_open_count", D(2026, 8, 31), severities=["critical", "high"]), 3)
        self.assertEqual(self.d("codeql_open_count", D(2026, 9, 4), severities=["critical", "high"]), 2)
        self.assertEqual(self.d("codeql_open_count", D(2026, 9, 4), tools=["Scorecard"]), 1)

    def test_codeql_oldest_open_age(self):
        self.assertEqual(self.d("codeql_oldest_open_age_days", D(2026, 9, 4), severities=["critical", "high"]), 12)
        self.assertIsNone(self.d("codeql_oldest_open_age_days", D(2026, 8, 22), severities=["critical"]))

    def test_codeql_fixed_per_week(self):
        self.assertEqual(self.d("codeql_fixed_per_week", D(2026, 9, 4)), 1)
        self.assertEqual(self.d("codeql_fixed_per_week", D(2026, 9, 12)), 0)

    def test_scorecard(self):
        self.assertEqual(self.d("scorecard_score", D(2026, 9, 4)), 6.9)
        self.assertIsNone(self.d("scorecard_score", D(2026, 9, 1)))
        self.assertEqual(self.d("scorecard_check", D(2026, 9, 4), name="Branch-Protection"), 4)

    def test_ci_pass_rate_ignores_cancelled(self):
        self.assertAlmostEqual(self.d("ci_pass_rate_30d", D(2026, 9, 4), workflows=["E2E Tests"]), 0.5)
        self.assertAlmostEqual(self.d("ci_pass_rate_30d", D(2026, 9, 4), workflows=[]), 1 / 3)
        self.assertIsNone(self.d("ci_pass_rate_30d", D(2026, 8, 20), workflows=["E2E Tests"]))

    def test_ci_median_wall_time(self):
        self.assertEqual(self.d("ci_median_wall_time_30d", D(2026, 9, 4), workflow="E2E Tests"), 480.0)

    def test_pr_lead_time_and_counts(self):
        self.assertEqual(self.d("pr_lead_time_30d", D(2026, 9, 4), quantile=0.5, author_type="all"), (86400 + 7200) / 2)
        self.assertEqual(self.d("pr_lead_time_30d", D(2026, 9, 4), quantile=0.5, author_type="agent"), 7200)
        self.assertEqual(self.d("prs_merged_30d", D(2026, 9, 4), author_type="agent"), 1)
        self.assertEqual(self.d("prs_merged_30d", D(2026, 9, 4), author_type="human"), 1)
        self.assertEqual(self.d("prs_merged_30d", D(2026, 8, 24), author_type="all"), 0)

    def test_pr_product_ratio(self):
        # PR5: 910 lines, 1 of 3 files under apps/ -> 303.3 product lines; PR6: 100 lines all apps/
        self.assertAlmostEqual(self.d("pr_product_ratio_30d", D(2026, 9, 4)), (910 / 3 + 100) / 1010, places=4)

    def test_issue_labels_as_of(self):
        self.assertEqual(self.d("issues_open_by_label", D(2026, 8, 28), label="needs-triage"), 1)
        self.assertEqual(self.d("issues_open_by_label", D(2026, 8, 30), label="needs-triage"), 0)
        self.assertEqual(self.d("issues_open_by_label", D(2026, 9, 4), label="needs-triage"), 1)
        self.assertEqual(self.d("issues_time_to_triage_median_30d", D(2026, 9, 4)), 2 * 86400)

    def test_defects_by_status(self):
        self.assertEqual(self.d("defects_by_status", D(2026, 9, 4), status="fixed"), 1)
        self.assertEqual(self.d("defects_by_status", D(2026, 9, 1), status="fixed"), 0)
        self.assertEqual(self.d("defects_by_status", D(2026, 9, 1), status="open"), 2, "b was open before it was fixed")
        self.assertEqual(self.d("defects_by_status", D(2026, 8, 21), status="open"), 0)

    def test_derivation_sources_covers_every_derivation(self):
        # R9(c): Task 14 keys freshness off this table instead of name-prefix
        # matching, so every registered derivation needs an entry naming the
        # event kinds it reads (empty tuple for ledger-derived series).
        self.assertEqual(set(DERIVATION_SOURCES), set(DERIVATIONS))
        self.assertEqual(DERIVATION_SOURCES["defects_by_status"], ())
        self.assertEqual(DERIVATION_SOURCES["codeql_open_count"], ("codeql_alerts",))
        self.assertEqual(DERIVATION_SOURCES["ci_pass_rate_30d"], ("workflow_runs",))
