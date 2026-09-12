"""The relay reaches the ORM at exactly these sites, for these reasons.

TWO PARTS, AND ONLY ONE OF THEM PROVES ANYTHING (plan 2b-3, Ruling R1).

Part 1 is static. It is a ratchet against a NEW textual ORM site inside
apps/proxy/live_proxy/**, and against a NEW in-process import edge out of
that package. A green part 1 does not establish that the relay makes no
query: it cannot see a property that queries, a getattr dispatch, or an
ORM read more than one import hop away. See zero_orm_scan.py's docstring.

Part 2 is runtime, and it is the one that proves the property. It drives
five real drives through 2a's subprocess harness with every SQL statement
recorded, and holds what the relay executed against the same allowlist.

Both hold against zero_orm_allowlist.py. An empty allowlist is the best
outcome and is NOT the gate (spec line 1659): an honestly-cited entry is
a recorded fact for whoever next touches the file, and deleting a read
this PR is not scoped to remove would be worse.

Narrower, faster relatives that stay as they are:
test_stream_ts_client_registration.py's TrustedTuneQueriesNoUserRowTests
pins one table on the test thread with CaptureQueriesContext, which is
correct there and wrong here (Ruling R5).
"""

from django.test import SimpleTestCase

from . import zero_orm_allowlist as allowlist
from . import zero_orm_scan


class StaticScopeOneTests(SimpleTestCase):
    def test_every_orm_site_in_the_relay_package_is_allowlisted(self):
        found = {(h.path, h.lineno) for h in zero_orm_scan.scan_relay_package()}
        allowed = {(s.path, s.lineno) for s in allowlist.SITES}
        self.assertEqual(
            found,
            allowed,
            "\nunlisted (add to SITES with a reason, or remove the read):\n  "
            + "\n  ".join(sorted(f"{p}:{n}" for p, n in found - allowed))
            + "\nlisted but gone (delete the entry -- the ratchet runs both "
            "ways, and a stale entry is how an allowlist stops meaning "
            "anything):\n  "
            + "\n  ".join(sorted(f"{p}:{n}" for p, n in allowed - found)),
        )

    def test_the_scanner_sees_something(self):
        """Vacuous-pass guard, in 2b-2's idiom.

        assertEqual(set(), set()) passes. If SITES is ever legitimately
        empty AND the scanner is broken, the test above is green and
        proves nothing. This one fails loudly in that state, so an empty
        allowlist has to be argued for rather than arrived at.
        """
        self.assertNotEqual(
            zero_orm_scan.scan_relay_package(),
            [],
            "the scanner found no ORM site anywhere in the relay package. "
            "Either 2c/2d finished the job -- in which case delete this "
            "test in the same diff and say so -- or the scanner is broken.",
        )


class StaticScopeTwoTests(SimpleTestCase):
    def test_every_in_process_import_edge_is_allowlisted(self):
        found = {(e.importer, e.module, e.name) for e in zero_orm_scan.import_edges()
                 if zero_orm_scan.scan_edge(e)}
        allowed = {(e.importer, e.module, e.name) for e in allowlist.EDGES}
        self.assertEqual(found, allowed)

    def test_every_edge_carries_the_hit_count_it_actually_clears(self):
        """The count is the ratchet for a cleared subtree (Ruling R3).

        Per-line entries here would put dozens of lines of a control-plane
        module in the allowlist to say one thing. The count moves only when
        ORM usage inside the subtree changes -- which is exactly when
        someone should look -- unlike Gate 2's `statements` figure, which
        moves on any code edit and is a latent bug for that reason.
        """
        for entry in allowlist.EDGES:
            edge = zero_orm_scan.Edge(entry.importer, entry.module, entry.name)
            self.assertEqual(
                len(zero_orm_scan.scan_edge(edge)),
                entry.hits,
                f"{entry.module}.{entry.name} now holds a different number "
                f"of ORM sites than when it was cleared. Re-read the "
                f"subtree, then update the count and the reason together.",
            )


class AllowlistShapeTests(SimpleTestCase):
    def test_every_entry_states_what_closes_it(self):
        """Spec line 1769 makes 2c-1's precondition depend on this.

        2c-1's description must name, for every entry, either the
        contract field that closes it or the written reason the Go relay
        never asks that question. An entry with an empty `closed_by` is
        an entry 2c-1 cannot honour.
        """
        for entry in list(allowlist.SITES) + list(allowlist.EDGES):
            with self.subTest(entry=entry):
                self.assertTrue(entry.reason.strip())
                self.assertTrue(entry.closed_by.strip())
                self.assertRegex(entry.pr, r"^(Phase 1 PR \d|2[abc]-\d)$")
