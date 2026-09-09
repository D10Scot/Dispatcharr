"""Property-based tests for timeshift pool-matching and preemption decisions.

The functions under test in ``apps/timeshift/views.py`` are pure decision
predicates that gate pool reuse, scrub displacement, and stats-grace
scheduling. They run on every catch-up request against a busy/idle pool, and
their invariants are read directly from the implementation:

- ``_score_pool_fingerprint`` scores IP overlap (5) + UA overlap (3), so the
  result is always in ``{0, 3, 5, 8}`` and never negative.
- ``_pool_entry_owned_by_user`` is permissive for unclaimed entries (no
  ``profile_id``) and otherwise compares stringified owner to stringified user.
- ``_is_timeshift_startup_probe`` is the conjunction of two strict thresholds.
- ``_is_full_restart_range`` / ``_should_preempt_plain_reconnect`` /
  ``_should_displace_busy_pool`` compose into the busy-pool preemption
  decision; these properties pin the cases each must accept or reject.
- ``_resolve_session_archive_scrub`` maps an in-window seek onto the open CDN
  archive; its byte offset must stay within ``[0, content_length)`` and be
  188-byte (TS packet) aligned, and a same-timestamp request maps to offset 0.

No Redis or DB: these are pure functions over strings/dicts/ints. Runs under
the derandomized ``dispatcharr-ci`` profile (200 examples, no deadline),
matching the existing ``test_property_*.py`` suites.
"""

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.timeshift import views
from apps.timeshift.stats import EOF_PROBE_TAIL_BYTES

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Reasonable text for IPs, user agents, media ids, session ids.
_short_text = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789.-_: ", max_size=40
)
_ip = st.from_regex(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", fullmatch=True)
_ua = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./() ",
    min_size=1,
    max_size=60,
)
_pos_int = st.integers(min_value=0, max_value=10**12)
_small_pos_int = st.integers(min_value=0, max_value=10**7)


class FingerprintScoreProperties(SimpleTestCase):
    @given(entry_ip=st.one_of(st.none(), _ip), req_ip=st.one_of(st.none(), _ip))
    def test_ip_only_scores_zero_or_five(self, entry_ip, req_ip):
        entry = {}
        if entry_ip is not None:
            entry["client_ip"] = entry_ip
        score = views._score_pool_fingerprint(entry, req_ip, None)
        self.assertIn(score, (0, 5))

    @given(entry_ua=st.one_of(st.none(), _ua), req_ua=st.one_of(st.none(), _ua))
    def test_ua_only_scores_zero_or_three(self, entry_ua, req_ua):
        entry = {}
        if entry_ua is not None:
            entry["client_user_agent"] = entry_ua
        score = views._score_pool_fingerprint(entry, None, req_ua)
        self.assertIn(score, (0, 3))

    @given(
        entry_ip=st.one_of(st.none(), _ip),
        req_ip=st.one_of(st.none(), _ip),
        entry_ua=st.one_of(st.none(), _ua),
        req_ua=st.one_of(st.none(), _ua),
    )
    def test_score_is_bounded_and_matches_threshold_semantics(
        self, entry_ip, req_ip, entry_ua, req_ua
    ):
        entry = {}
        if entry_ip is not None:
            entry["client_ip"] = entry_ip
        if entry_ua is not None:
            entry["client_user_agent"] = entry_ua
        score = views._score_pool_fingerprint(entry, req_ip, req_ua)
        # Max possible is 5 (IP) + 3 (UA) = 8 = _MATCH_SCORE_THRESHOLD.
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, views._MATCH_SCORE_THRESHOLD)
        # Score is exactly the sum of present-and-equal parts.
        expected = 0
        if entry_ip and entry_ip == req_ip:
            expected += 5
        if entry_ua and entry_ua == req_ua:
            expected += 3
        self.assertEqual(score, expected)


class PoolEntryOwnershipProperties(SimpleTestCase):
    @given(user_id=st.integers(min_value=1, max_value=10**9))
    def test_unclaimed_entry_is_owned_by_anyone(self, user_id):
        # No profile_id => unclaimed => True regardless of owner field.
        self.assertTrue(views._pool_entry_owned_by_user({}, user_id))
        self.assertTrue(views._pool_entry_owned_by_user({"user_id": "x"}, user_id))
        self.assertTrue(views._pool_entry_owned_by_user(None, user_id))

    @given(
        owner=st.one_of(st.none(), st.just(""), st.integers(1, 10**9), _short_text),
        user_id=st.integers(min_value=1, max_value=10**9),
    )
    def test_claimed_entry_compares_stringified_owner(self, owner, user_id):
        entry = {"profile_id": "9", "user_id": owner}
        result = views._pool_entry_owned_by_user(entry, user_id)
        if owner is None or owner == "":
            # Claimed (has profile_id) but no owner => not owned.
            self.assertFalse(result)
        else:
            self.assertEqual(result, str(owner) == str(user_id))


class StartupProbeProperties(SimpleTestCase):
    @given(
        yielded=st.integers(min_value=0, max_value=10**9),
        elapsed=st.floats(min_value=0.0, max_value=1000.0),
    )
    def test_probe_is_conjunction_of_strict_thresholds(self, yielded, elapsed):
        result = views._is_timeshift_startup_probe(yielded, elapsed)
        expected = (
            yielded < views._STATS_GRACE_MIN_YIELDED_BYTES
            and elapsed < views._STATS_GRACE_MIN_ELAPSED_SECONDS
        )
        self.assertEqual(result, expected)

    @given(
        yielded=st.integers(
            min_value=views._STATS_GRACE_MIN_YIELDED_BYTES, max_value=10**9
        ),
        elapsed=st.floats(
            min_value=views._STATS_GRACE_MIN_ELAPSED_SECONDS, max_value=1000.0
        ),
    )
    def test_at_or_above_both_thresholds_is_never_a_probe(self, yielded, elapsed):
        self.assertFalse(views._is_timeshift_startup_probe(yielded, elapsed))


class GraceSchedulingProperties(SimpleTestCase):
    @given(
        yielded=st.integers(min_value=0, max_value=10**9),
        elapsed=st.floats(min_value=0.0, max_value=1000.0),
    )
    def test_stopped_for_reuse_never_schedules(self, yielded, elapsed):
        self.assertFalse(
            views._should_schedule_stats_disconnect_grace(
                yielded, elapsed, stopped_for_reuse=True
            )
        )

    @given(
        yielded=st.integers(
            min_value=0, max_value=views._STATS_GRACE_MIN_YIELDED_BYTES - 1
        ),
        elapsed=st.floats(
            min_value=0.0,
            max_value=views._STATS_GRACE_MIN_ELAPSED_SECONDS - 0.001,
        ),
    )
    def test_startup_probe_never_schedules(self, yielded, elapsed):
        self.assertFalse(
            views._should_schedule_stats_disconnect_grace(
                yielded, elapsed, stopped_for_reuse=False
            )
        )


class PreemptPlainReconnectProperties(SimpleTestCase):
    @given(
        range_header=st.one_of(st.none(), st.just("bytes=0-"), _short_text),
        pool_exists=st.booleans(),
        pool_busy=st.booleans(),
        same_media=st.booleans(),
    )
    def test_preempt_requires_full_restart_and_busy_same_media(
        self, range_header, pool_exists, pool_busy, same_media
    ):
        media_id = "5_2026-07-09:14-00"
        pool_media_id = media_id if same_media else "9_2026-07-10:00-00"
        result = views._should_preempt_plain_reconnect(
            range_header,
            pool_exists=pool_exists,
            pool_busy=pool_busy,
            pool_media_id=pool_media_id,
            media_id=media_id,
        )
        is_full_restart = views._is_full_restart_range(range_header)
        expected = (
            is_full_restart and pool_exists and pool_busy and same_media
        )
        self.assertEqual(result, expected)

    @given(range_header=st.one_of(st.none(), _short_text))
    def test_no_full_restart_no_preempt(self, range_header):
        assume(not views._is_full_restart_range(range_header))
        self.assertFalse(
            views._should_preempt_plain_reconnect(
                range_header,
                pool_exists=True,
                pool_busy=True,
                pool_media_id="m",
                media_id="m",
            )
        )


class DisplaceBusyPoolProperties(SimpleTestCase):
    @given(
        range_header=st.one_of(st.none(), _short_text),
        content_length=st.one_of(st.none(), _small_pos_int),
        serving_range=st.one_of(st.none(), st.just("none"), _short_text),
    )
    def test_programme_hop_never_displaces(
        self, range_header, content_length, serving_range
    ):
        # Different media ids route to programme-change preemption, never
        # to busy displacement.
        self.assertFalse(
            views._should_displace_busy_pool(
                range_header,
                content_length,
                serving_range,
                pool_media_id="1_A",
                media_id="2_B",
            )
        )

    @given(content_length=st.integers(min_value=10**8, max_value=10**12))
    def test_mid_file_scrub_on_large_archive_displaces(self, content_length):
        # A seek to a point comfortably before the EOF tail on a large archive
        # is a scrub, not a probe, and must displace busy playback.
        start = max(1, content_length - EOF_PROBE_TAIL_BYTES - 1000)
        range_header = f"bytes={start}-"
        self.assertTrue(
            views._should_displace_busy_playback(
                range_header, content_length, "bytes=0-"
            )
        )

    @given(start=st.integers(min_value=1, max_value=10**7))
    def test_nonzero_start_with_unknown_length_displaces(self, start):
        # content_length None => not a near-EOF probe (needs a huge start),
        # so a mid-file seek displaces.
        self.assertTrue(
            views._should_displace_busy_playback(
                f"bytes={start}-", None, "bytes=0-"
            )
        )


class ArchiveScrubProperties(SimpleTestCase):
    def _descriptor(self, content_length, duration_secs, anchor_ts):
        return {
            "final_url": "http://provider/x.ts",
            "content_length": str(content_length),
            "archive_duration_secs": str(duration_secs),
            "archive_anchor_ts": anchor_ts,
        }

    @given(
        content_length=st.integers(min_value=188, max_value=10**9),
        duration_secs=st.integers(min_value=60, max_value=10**5),
    )
    def test_same_timestamp_maps_to_offset_zero(self, content_length, duration_secs):
        d = self._descriptor(content_length, duration_secs, "2026-07-09:14-00")
        result = views._resolve_session_archive_scrub(d, "2026-07-09:14-00")
        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], "same")
        self.assertEqual(result["byte_offset"], 0)
        self.assertEqual(result["remaining"], content_length)

    @given(
        content_length=st.integers(min_value=376, max_value=10**9),
        duration_secs=st.integers(min_value=120, max_value=10**5),
        offset_secs=st.integers(min_value=1, max_value=59),
    )
    def test_in_window_scrub_offset_is_bounded_and_ts_aligned(
        self, content_length, duration_secs, offset_secs
    ):
        # Anchor with seconds precision so sub-minute offsets land in-window.
        d = self._descriptor(content_length, duration_secs, "2026-07-09:14-00-00")
        requested = f"2026-07-09:14-00-{offset_secs:02d}"
        result = views._resolve_session_archive_scrub(d, requested)
        # offset_secs < 60 <= duration_secs, and >= 1.0s so not "same".
        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], "scrub")
        self.assertGreaterEqual(result["byte_offset"], 0)
        self.assertLess(result["byte_offset"], content_length)
        # TS-packet (188-byte) aligned.
        self.assertEqual(result["byte_offset"] % 188, 0)
        self.assertEqual(result["remaining"], content_length - result["byte_offset"])

    @given(
        content_length=st.integers(min_value=188, max_value=10**9),
        duration_secs=st.integers(min_value=60, max_value=10**5),
    )
    def test_reverse_seek_returns_none(self, content_length, duration_secs):
        d = self._descriptor(content_length, duration_secs, "2026-07-09:14-05")
        # Request an earlier time than the anchor => content not on this URL.
        result = views._resolve_session_archive_scrub(d, "2026-07-09:14-00")
        self.assertIsNone(result)

    @given(
        content_length=st.integers(min_value=188, max_value=10**9),
        duration_secs=st.integers(min_value=60, max_value=3600),
    )
    def test_seek_past_window_returns_none(self, content_length, duration_secs):
        # offset >= duration_secs is outside the opened window.
        d = self._descriptor(content_length, duration_secs, "2026-07-09:14-00-00")
        # duration_secs capped at 3600; request start 2 hours later.
        result = views._resolve_session_archive_scrub(d, "2026-07-09:16-00-00")
        self.assertIsNone(result)

    @given(garbage=_short_text)
    def test_unparseable_descriptor_or_timestamp_returns_none(self, garbage):
        assume("final_url" not in garbage)
        d = {
            "final_url": "http://provider/x.ts",
            "content_length": "1000",
            "archive_duration_secs": "60",
            "archive_anchor_ts": "2026-07-09:14-00",
        }
        # Garbage requested timestamp cannot be parsed => None.
        result = views._resolve_session_archive_scrub(d, garbage)
        self.assertIsNone(result)
