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

RULE (added in the post-review fix round, after it was violated once):
no raw `assertIn`/substring check on SQL text anywhere in this file.
Every claim about what ran goes through `_signature_matches` (which
checks `params_fragment` too, not just `sql_fragment`) via
`_assert_allowlisted`, scoped to the drive it is being asked about
(`_signature_phases`) -- never a bare `"table_name" in query.sql` that
bypasses both. Any signature whose SQL text is not unique to one read
(today, only the `core_coresettings` group-key lookup) MUST carry a
`params_fragment`. A hand-rolled `assertIn("core_coresettings", …)` once
shipped here anyway and was satisfied by an unrelated read on the same
drive -- see the review round's Blocking 2 finding.

A KNOWN, ACCEPTED LIMIT (review round Q6): a signature matches by SQL
TEXT, so a NEW read on the SAME drive that happens to reproduce an
already-allowlisted table+WHERE shape (e.g. a second, redundant
`Channel.objects.filter(uuid=...)` added inside stream_ts itself) is
invisible to this runtime half -- phase-scoping closes the WRONG-drive
version of this problem (a read migrating to a phase that never
expected it) but cannot close the SAME-drive version, because both the
old and the new call produce identical SQL on the identical phase. The
STATIC half is what catches this class instead: `scan_relay_package()`
flags every `.objects.`/`get_object_or_404(`/model-method call by
`file:line`, so a genuinely new call site -- even one whose SQL is
indistinguishable from an existing one -- fails
`test_every_orm_site_in_the_relay_package_is_allowlisted` as an
unlisted line. Verified directly: inserting the plan's own literal
break-check text (`Channel.objects.filter(uuid=channel_id).first()`
inside `stream_ts`) leaves this runtime half green and turns the
static half red at the new line.
"""

import time
import uuid as uuid_module

import requests
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase

from core.models import OutputProfile
from apps.proxy.internal_auth import (
    HEADER_AUTHORIZED,
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    HEADER_RELAY_CHANNEL,
    HEADER_RELAY_CLIENT,
    HEADER_RELAY_CLIENT_IP,
    HEADER_RELAY_OUTPUT,
    HEADER_RELAY_OUTPUT_FORMAT,
    HEADER_RELAY_USER,
    build_internal_request_header,
    internal_principal_token,
    relay_trust_token,
)
from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from . import zero_orm_allowlist as allowlist
from . import zero_orm_scan
from .harness.process import stand_in_stream_profile
from .harness.queries import capture_queries, relay_queries
from .harness.relay import RelayHarnessTestCase

# 515151: not 2b-2's own 424242 (test_authenticated_tune_identity.py), so
# the two tests fail independently if either header wiring regresses; far
# above any sequence value; and not add_client's "0" fallback.
GUARD_VIEWER_ID = 515151


def _signature_matches(sig, query):
    """A query matches a Signature iff the SQL text matches, and -- when
    the signature names one -- the bound params also match.

    Django parameterizes CoreSettings' `key` lookup, so two different
    settings groups produce byte-identical SQL text; `sql_fragment`
    alone cannot tell "proxy_settings" from an unrelated group sharing
    the same `WHERE key = %s` shape. See Signature's own docstring in
    zero_orm_allowlist.py -- found via a break-check that passed when it
    should not have.
    """
    if sig.sql_fragment not in query.sql:
        return False
    if sig.params_fragment and sig.params_fragment not in query.params:
        return False
    return True


def _signature_phases(sig):
    """The drive names this signature is eligible on, parsed from
    `exercised_by`, or None for "any phase."

    Review round finding: a signature eligible on every phase (the
    original design) lets a query on drive B satisfy a signature whose
    `exercised_by` names only drive A -- a wrong-drive match the offender
    check cannot tell from a right-drive one, since both are "some
    signature matched." Two concrete failures followed from this: an
    injected Channel-by-uuid read on the STATUS phase passed because
    "channel_by_uuid" (owner/follower only) was still globally eligible,
    and the follower's own OutputProfile lookup going missing entirely
    was invisible to the union-based exercised_by check because the
    OWNER's identically-named signature had already fired on a different
    phase. An EMPTY `exercised_by` stays eligible everywhere on purpose
    -- it marks a cache-dependent read (Task 4 Step 3) that may
    legitimately fire on any drive or none.
    """
    if not sig.exercised_by:
        return None
    return {p.strip() for p in sig.exercised_by.split(",")}


def internal_get(base_url, path):
    """GET an internal /proxy/relay/... route the way relay_client.py does.

    Signed with the same two headers apps/proxy/relay_client.py sends:
    the static X-Dispatcharr-Internal plus the per-request, path-bound
    X-Dispatcharr-Internal-Request. Local to this file, not
    harness/control.py, per the plan: four parallel PRs already contend
    on that module.
    """
    headers = {
        HEADER_INTERNAL: internal_principal_token(),
        HEADER_INTERNAL_REQUEST: build_internal_request_header("GET", path, b""),
    }
    return requests.get(f"{base_url}{path}", headers=headers, timeout=10)


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


class RuntimeGuardTests(RelayHarnessTestCase):
    """What the relay actually executes, across five drives.

    This is the half that proves the property. Part 1 sees code; this
    sees execution, and the two disagree on purpose in at least one
    place: result_from_headers' User.objects.filter is flagged
    statically and never runs on a live tune, because 2b-2 split
    result_from_headers on the SURFACE (authorize_views.py). The query
    sits in the `else` arm and SURFACE_LIVE/SURFACE_LIVE_XC never enter
    it. NOT because the field is lazy -- that design was drafted and
    withdrawn at 71cd8d31, since `is` cannot be overloaded and eleven of
    the field's fourteen consumers test identity.

    Trusted tunes only (Ruling R6): an untrusted tune runs
    authorize_stream inline from a live_proxy frame, where production
    runs that hop in the API process behind nginx's auth_request.
    """

    def _assert_allowlisted(self, captured, phase, signatures=None):
        """Every query in `captured` matches a signature ELIGIBLE ON `phase`.

        `signatures` defaults to SQL_SIGNATURES (the trusted-drive
        policy list); the untrusted drive passes INLINE_AUTHORIZE_
        SIGNATURES instead, so both paths route through one matcher --
        review round Blocking 2's rule, stated in the module docstring:
        no raw SQL-text check anywhere in this file outside this method.

        Eligibility is scoped to `phase` (via _signature_phases), not
        global: a signature named "owner tune, follower tune" cannot
        cover a query that shows up on "status read" instead. Without
        that scoping, a NEW read that happens to reuse an
        already-allowlisted table+WHERE shape on the WRONG drive is
        invisible -- exactly the shape of both Blocking findings in the
        review round.
        """
        if signatures is None:
            signatures = allowlist.SQL_SIGNATURES
        eligible = [
            sig for sig in signatures
            if _signature_phases(sig) is None or phase in _signature_phases(sig)
        ]
        offenders = []
        for query in relay_queries(captured):
            if not any(_signature_matches(sig, query) for sig in eligible):
                offenders.append((query.sql[:400], query.relay_frames))
        self.assertEqual(
            offenders,
            [],
            f"\n{phase}: the relay executed a query matching no signature "
            f"eligible on this drive.\n"
            + "\n".join(f"  {s}\n    via {f}" for s, f in offenders),
        )
        return {
            sig.name for sig in eligible
            for q in relay_queries(captured) if _signature_matches(sig, q)
        }

    def test_the_table_names_in_every_signature_are_real(self):
        """Vacuous-pass guard, 2b-2's idiom generalised.

        A signature that matches nothing satisfies _assert_allowlisted
        for every input while proving nothing, and a renamed db_table
        would make that happen silently.
        """
        for sig in allowlist.SQL_SIGNATURES:
            if not sig.table_model:
                continue
            app_label, model_name = sig.table_model.split(".")
            model = django_apps.get_model(app_label, model_name)
            self.assertIn(
                model._meta.db_table,
                sig.sql_fragment,
                f"{sig.name}'s fragment does not contain "
                f"{model._meta.db_table} -- the table moved and the "
                f"signature now matches nothing",
            )

    def test_a_trusted_tune_a_follower_and_a_status_read_stay_on_the_allowlist(self):
        with self.stand_in():
            profile = stand_in_stream_profile()
            output_profile = OutputProfile.objects.create(
                name="2b3-guard", command="ffmpeg",
                parameters="-i pipe:0 -f mpegts pipe:1", is_active=True,
            )
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            identifier = str(channel.uuid)

            # Global Constraint 1, twice over.
            #
            # X-Relay-Output must name a REAL active profile, or
            # _output_profile_for returns None at views.py's early
            # `if not decision.output_profile_id: return None` before
            # touching the ORM, and the SITE at views.py:152 would never
            # be exercised -- the guard would pass with that site deleted.
            #
            # X-Relay-User must be a DIGIT naming a REAL row, and this is
            # the subtler of the two. 2b-2 split result_from_headers on
            # the surface: the User query is in the `else` arm, and the
            # live arm is reached first. With an empty header there is no
            # digit to query on, so the `else` arm would not query EITHER
            # -- the guard would stay green with 2b-2's central change
            # backed out. A digit naming a real row is the only input
            # that distinguishes "the surface split holds" from "there
            # was nothing to look up".
            User = get_user_model()
            viewer = User(id=GUARD_VIEWER_ID, username="2b3-guard-viewer")
            viewer.set_password("x")
            viewer.save()

            headers = {
                HEADER_AUTHORIZED: relay_trust_token(),
                HEADER_RELAY_CHANNEL: identifier,
                HEADER_RELAY_CLIENT: "client_2b3_owner",
                HEADER_RELAY_USER: str(GUARD_VIEWER_ID),
                HEADER_RELAY_OUTPUT: str(output_profile.id),
                HEADER_RELAY_OUTPUT_FORMAT: "mpegts",
                HEADER_RELAY_CLIENT_IP: "203.0.113.31",
            }

            with capture_queries() as captured:
                owner = requests.get(
                    f"{self.live_server_url}/proxy/ts/stream/{identifier}",
                    headers=headers, stream=True, timeout=20,
                )
                self.addCleanup(owner.close)
                self.assertEqual(owner.status_code, 200)
                next(owner.iter_content(chunk_size=188))
            fired_tune = self._assert_allowlisted(captured, "owner tune")

            # The follower: a second client on a running channel, which
            # (per Redis-visible channel state, not in-process object
            # state -- _channel_setup_needed reads the metadata hash, so
            # this holds even in this single-process harness) makes NO
            # next-source call at all (2b-2 Ruling R3) and takes the
            # `if not output_options_resolved:` branch rather than the
            # owner-init one.
            #
            # It asks for a DIFFERENT OutputProfile, and that is what
            # makes it a second drive rather than a second copy of the
            # first. With the same headers as the owner, every assertion
            # below is satisfied by the owner's own queries and the
            # follower drive cannot fail on its own -- the owner/follower
            # axis meeting Global Constraint 1. A distinct id means the
            # `SELECT ... FROM core_outputprofile` carrying THAT id can
            # only have come from this request, so the assertion after
            # the drive fails if the follower path is skipped, short-
            # circuited, or served from the owner's resolved profile.
            other_profile = OutputProfile.objects.create(
                name="2b3-guard-follower", command="ffmpeg",
                parameters="-i pipe:0 -f mpegts pipe:1", is_active=True,
            )
            follower_headers = dict(headers, **{
                HEADER_RELAY_CLIENT: "client_2b3_follower",
                HEADER_RELAY_OUTPUT: str(other_profile.id),
            })
            with capture_queries() as captured:
                follower = requests.get(
                    f"{self.live_server_url}/proxy/ts/stream/{identifier}",
                    headers=follower_headers, stream=True, timeout=20,
                )
                self.addCleanup(follower.close)
                self.assertEqual(follower.status_code, 200)
                next(follower.iter_content(chunk_size=188))
            fired_follower = self._assert_allowlisted(captured, "follower tune")
            # The discriminating assertion, and the mechanical answer to
            # Step 6: only the follower branch can produce a lookup of
            # THIS id.
            #
            # Review round Blocking 1: this was a recorded skip reason,
            # asserted only after the exercised_by ratchet below, on the
            # theory that a skipTest here would mask that ratchet's own
            # ability to catch the same regression (break-check 3). That
            # reasoning does not survive contact with the evidence: 15+
            # runs here and 14/14 for the round's reviewer never took the
            # "cannot express the follower branch" path, so the
            # conditional was a permanent hedge against a situation that
            # never arose, not an observed limitation -- and Step 6's own
            # rule is that when the assertion is OBSERVED TO HOLD, the PR
            # says so and asserts it. There is no runtime signal that
            # distinguishes "this harness cannot express the follower
            # branch" from "the follower branch regressed", so a
            # conditional here cannot be made sound either way. The
            # honest form is the assertion.
            self.assertTrue(
                any(
                    str(other_profile.id) in q.params
                    for q in relay_queries(captured)
                    if "core_outputprofile" in q.sql
                ),
                "no OutputProfile lookup named the follower's own profile "
                f"({other_profile.id}). The second client did not take the "
                "per-client output-resolution branch -- either it re-ran "
                "the owner-init path in this single-process harness, or "
                "the profile came from the owner's already-resolved one.",
            )

            # The status read, WITHOUT ?fields=state -- that is what
            # reaches get_detailed_channel_info and the two fallbacks.
            with capture_queries() as captured:
                status = internal_get(
                    self.live_server_url, f"/proxy/relay/channels/{identifier}"
                )
                self.assertEqual(status.status_code, 200)
            fired_status = self._assert_allowlisted(captured, "status read")

            # A FIFTH drive, and the status path's only discriminating
            # one. The drive above reads a channel this harness tuned
            # against a current Django, so tune_extras supplied every
            # name and the hash has them -- meaning channel_status.py's
            # two fallbacks never fire and that drive would pass with
            # both DELETED. It is an addition detector (break-check 2
            # proves that much) and nothing more; on its own it
            # contributes no exercised_by and cannot fail on a removal.
            #
            # Strip the two names from the hash and read again. Now the
            # fallbacks run, against real Postgres, and the two
            # allowlisted sites become observable -- so their entries can
            # carry exercised_by and their deletion turns this red.
            redis = ProxyServer.get_instance().redis_client
            redis.hdel(
                RedisKeys.channel_metadata(identifier),
                ChannelMetadataField.STREAM_NAME,
                ChannelMetadataField.M3U_PROFILE_NAME,
            )
            with capture_queries() as captured:
                stripped = internal_get(
                    self.live_server_url, f"/proxy/relay/channels/{identifier}"
                )
                self.assertEqual(stripped.status_code, 200)
            fired_stripped = self._assert_allowlisted(captured, "status read stripped")
            self.assertTrue(
                fired_stripped - fired_status,
                "stripping the names from the hash changed nothing about "
                "which queries ran, so the two fallbacks did not fire and "
                "this drive proves no more than the one above it",
            )

        # Review round SF3: per-drive, not a flat union. A signature
        # marked exercised_by="owner tune" firing only on "status read"
        # is a wrong-drive match the old union+intersection could not
        # see -- it only asked "did the name show up somewhere", never
        # "on the drive it claims". This is what would have caught
        # break-check 6 (follower reuses the owner's profile) on its
        # own, without needing the explicit assertion above: under that
        # defect, "follower tune" fires no core_outputprofile query at
        # all, so output_profile_for_this_client drops out of
        # fired_follower specifically.
        for phase_name, fired in (
            ("owner tune", fired_tune),
            ("follower tune", fired_follower),
            ("status read", fired_status),
            ("status read stripped", fired_stripped),
        ):
            expected_here = {
                sig.name for sig in allowlist.SQL_SIGNATURES
                if _signature_phases(sig) and phase_name in _signature_phases(sig)
            }
            self.assertEqual(
                fired & expected_here,
                expected_here,
                f"{phase_name}: a signature marked exercised_by this drive "
                "did not fire on it. Either the read is gone -- delete the "
                "entry, that is the ratchet -- or this drive no longer "
                "reaches it, or it now fires on a different drive and "
                "exercised_by needs updating to say so.",
            )

    def test_an_untrusted_tune_executes_a_recorded_set_and_no_other(self):
        """The branch the trusted-only rule cannot reach (Ruling R6).

        NOT a policy gate: these queries are the authorize hop's, and in
        production nginx runs that hop in the API process. This is a
        characterization pin -- the set is recorded so a NEW ORM read on
        the inline path is visible, not so the set is required to shrink.

        The sharpest thing it covers is CoreSettings.get_default_output_
        format(), reached here from apps/proxy/authorize.py's
        resolve_output_format -- the EDGE at
        apps.proxy.authorize.resolve_output_format, not the SITE at
        views.py:132. resolve_authorization's inline branch calls
        authorize_stream() rather than result_from_headers(), so
        decision.trusted is False here and _resolve_output_format takes
        its OTHER branch (`return resolve_output_format(...)`), whose own
        last line is this fallback. views.py:132's SITE needs
        decision.trusted True AND decision.output_format falsy at once --
        every trusted drive here sets X-Relay-Output-Format, so that SITE
        stays a defensive branch for a relay talking to a pre-2b-2 hop,
        unreached by anything in this file (see its own `reason` in
        zero_orm_allowlist.py). This drive also reaches a SECOND
        CoreSettings group (network_access, inline_network_access_
        settings below) on the SAME call, so the assertion that pins
        get_default_output_format's own signature by name is what
        distinguishes the two -- a bare "did CoreSettings get queried at
        all" check is satisfied by either and pins neither (review
        round's Blocking 2 finding).
        """
        # get_default_output_format() reads the "stream_settings" group,
        # and network_access_allowed() reads "network_access" -- both
        # Django-cache-backed (Redis) like "proxy_settings" is (Task 3's
        # fix, same shape) -- and unlike Postgres, a write to Redis is
        # not rolled back between test methods. Once anything in this
        # process's test run has warmed either, this drive answers from
        # cache and the corresponding assertion flakes on run order.
        # Cold both explicitly rather than depending on being first.
        # (network_access's own warm-cache flake surfaced only once this
        # signature started being checked for real, in the review
        # round's fix for Blocking 2 -- the old assertIn couldn't
        # distinguish a cache hit from a cache miss because it didn't
        # care which CoreSettings group answered it.)
        from core.models import CoreSettings, NETWORK_ACCESS_KEY, STREAM_SETTINGS_KEY
        CoreSettings.invalidate_group_cache(STREAM_SETTINGS_KEY)
        CoreSettings.invalidate_group_cache(NETWORK_ACCESS_KEY)

        with self.stand_in():
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=stand_in_stream_profile()
            )
            identifier = str(channel.uuid)
            with capture_queries() as captured:
                # No X-Dispatcharr-Authorized and no X-Relay-* headers:
                # resolve_authorization falls to the inline branch.
                response = requests.get(
                    f"{self.live_server_url}/proxy/ts/stream/{identifier}",
                    stream=True, timeout=20,
                )
                self.addCleanup(response.close)
                self.assertEqual(response.status_code, 200)
                next(response.iter_content(chunk_size=188))

        # Review round Blocking 2 / the module docstring's rule: route
        # through _assert_allowlisted (which itself routes through
        # _signature_matches), not a hand-rolled substring check. Reusing
        # the same helper here is deliberate, not incidental: the
        # untrusted drive is a single phase, so phase-scoping is a no-op
        # for it today, but it is the same mechanism this file uses
        # everywhere else, and a future second untrusted-style drive
        # gets the scoping for free rather than needing to reinvent it.
        fired_inline = self._assert_allowlisted(
            captured, "untrusted tune", signatures=allowlist.INLINE_AUTHORIZE_SIGNATURES
        )
        # The discriminating assertion (SF4): pin the SIGNATURE by name,
        # not merely "some query touched this table". A bare
        # `assertIn("core_coresettings", …)` is satisfied by
        # inline_network_access_settings' query alone -- a DIFFERENT
        # settings group, always present on this drive -- and proves
        # nothing about get_default_output_format() specifically. Found
        # by the round's reviewer: replacing authorize.py:259's `return
        # CoreSettings.get_default_output_format()` with a literal
        # `return "mpegts"` left the old assertIn green.
        expected_inline = {
            sig.name for sig in allowlist.INLINE_AUTHORIZE_SIGNATURES if sig.exercised_by
        }
        self.assertEqual(
            fired_inline & expected_inline,
            expected_inline,
            "an INLINE_AUTHORIZE_SIGNATURES entry marked exercised_by did "
            "not fire on the untrusted drive. Either the read is gone -- "
            "delete the entry -- or this drive no longer reaches it.",
        )


class StatusNameFallbackTests(RelayHarnessTestCase):
    """Parity-matrix row 18: what the status payload carries when the
    metadata hash was never written a name.

    THE ANSWER, which 2c is held to: the key is ABSENT from the payload
    entirely -- not null, not '', not the id. RelayChannelDetailSerializer
    declares both required=False, so absence is already the contract;
    channel_status.py's ORM fallback is best-effort enrichment on top of
    it, filling the key when the row still exists and leaving it absent
    when the row is gone. The Go relay, having no database, always omits
    it -- inside the contract, not a divergence from it.

    Written as a fixture rather than as a reachability argument: this
    fails if anyone deletes the fallback, changes it, or makes it emit a
    null, whether or not any production path reaches it.
    """

    def _stream(self, name):
        """A Stream row this fallback can find, with an m3u_account.

        Stream.objects.create() with no m3u_account fires
        apps/channels/signals.py's set_default_m3u_account, which looks
        up a migration-seeded "Custom" M3UAccount -- a row a
        TransactionTestCase-based harness flushes after the first test
        that runs, exactly as RelayHarnessTestCase is. harness/relay.py's
        own make_channel() avoids this the same way, by always supplying
        one.
        """
        from apps.channels.models import Stream
        from apps.m3u.models import M3UAccount

        account = M3UAccount.objects.create(
            name=f"row18-account-{uuid_module.uuid4().hex[:8]}",
            account_type="STD", username="user", password="pass", max_streams=5,
        )
        return Stream.objects.create(name=name, url="http://x/", m3u_account=account)

    def test_the_orm_fills_the_name_when_redis_has_none_and_the_row_exists(self):
        with self.stand_in():
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=stand_in_stream_profile()
            )
            identifier = str(channel.uuid)
            stream = self._stream("2b3-row18-stream-name")
            redis = ProxyServer.get_instance().redis_client
            # A name that could not arise by accident, and NO STREAM_NAME
            # key at all -- writing one empty would test a different branch.
            redis.hset(
                RedisKeys.channel_metadata(identifier),
                mapping={
                    ChannelMetadataField.STATE: "active",
                    ChannelMetadataField.STREAM_ID: str(stream.id),
                },
            )
            body = internal_get(
                self.live_server_url, f"/proxy/relay/channels/{identifier}"
            ).json()
        self.assertEqual(body["stream_name"], "2b3-row18-stream-name")

    def test_the_key_is_absent_when_redis_has_no_name_and_no_row_exists(self):
        """The row-18 answer itself, and the shape 2c must reproduce."""
        from apps.channels.models import Stream
        from apps.m3u.models import M3UAccountProfile

        with self.stand_in():
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=stand_in_stream_profile()
            )
            identifier = str(channel.uuid)
            absent_stream_id = 987654
            self.assertFalse(Stream.objects.filter(id=absent_stream_id).exists())
            absent_profile_id = 987655
            self.assertFalse(
                M3UAccountProfile.objects.filter(id=absent_profile_id).exists()
            )
            redis = ProxyServer.get_instance().redis_client
            redis.hset(
                RedisKeys.channel_metadata(identifier),
                mapping={
                    ChannelMetadataField.STATE: "active",
                    ChannelMetadataField.STREAM_ID: str(absent_stream_id),
                    ChannelMetadataField.M3U_PROFILE: str(absent_profile_id),
                },
            )
            body = internal_get(
                self.live_server_url, f"/proxy/relay/channels/{identifier}"
            ).json()
        self.assertNotIn("stream_name", body)
        self.assertNotIn("m3u_profile_name", body)
        # The ids ARE present: absence of the NAME is the contract, not
        # absence of the field pair. Without this the test above passes
        # against a payload that dropped everything.
        self.assertEqual(body["stream_id"], absent_stream_id)
        self.assertEqual(body["m3u_profile_id"], absent_profile_id)

    def test_redis_wins_over_the_orm_when_both_have_a_name(self):
        """The fallback is a FALLBACK. Two different names, so the
        assertion distinguishes them -- a test writing the same name in
        both places passes with the precedence inverted."""
        with self.stand_in():
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=stand_in_stream_profile()
            )
            identifier = str(channel.uuid)
            stream = self._stream("2b3-row18-from-the-db")
            redis = ProxyServer.get_instance().redis_client
            redis.hset(
                RedisKeys.channel_metadata(identifier),
                mapping={
                    ChannelMetadataField.STATE: "active",
                    ChannelMetadataField.STREAM_ID: str(stream.id),
                    ChannelMetadataField.STREAM_NAME: "2b3-row18-from-redis",
                },
            )
            body = internal_get(
                self.live_server_url, f"/proxy/relay/channels/{identifier}"
            ).json()
        self.assertEqual(body["stream_name"], "2b3-row18-from-redis")
