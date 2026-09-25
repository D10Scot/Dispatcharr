"""Property tests for the catch-up pool-matching and preemption predicates.

Written against the contracts PR D-3 (#216) establishes; this module lands after it.

Surfaces (``file:line`` at a54b09a9), all in apps/timeshift/views.py:

- ``_score_pool_fingerprint`` (:1536) and ``_pool_entry_owned_by_user`` (:1705).
- ``_is_timeshift_startup_probe`` (:831) and ``_should_schedule_stats_disconnect_grace`` (:807).
- ``_should_preempt_plain_reconnect`` (:1318), ``_should_displace_busy_pool`` (:1245) and
  ``_should_displace_busy_playback`` (:1336). #216: a mid-file seek on an archive
  of 2 MiB or less was classified as an EOF probe, so it never displaced the busy pool.
- ``_resolve_session_archive_scrub`` (:2001): an in-session timestamp rebuild mapped
  to a TS-packet-aligned byte offset inside the already-open CDN file.
- ``_pool_int_field`` (:1935): Redis hash values in any spelling.

Closes #215's scope and the pool/``_pool_int_field`` scope of #192 (survivor).
"""

from datetime import datetime, timedelta

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.timeshift import views as ts_views

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

WINDOW = ts_views._EOF_PROBE_TAIL_BYTES
MIN_BYTES = ts_views._STATS_GRACE_MIN_YIELDED_BYTES
MIN_SECS = ts_views._STATS_GRACE_MIN_ELAPSED_SECONDS

small_text = st.none() | st.text(max_size=8)
ids = st.none() | st.integers(min_value=0, max_value=50) | st.text(max_size=4)
range_headers = st.none() | st.sampled_from(["", "bytes=0-", "bytes=0-100", "bytes=-500"]) | (
    st.integers(min_value=0, max_value=10**10).map(lambda s: f"bytes={s}-")
) | st.text(max_size=16)


class _FakePoolRedis:
    """Only what _pool_session_exists reads: EXISTS on one pool key."""

    def __init__(self, present_key=None):
        self.present_key = present_key

    def exists(self, key):
        return 1 if key == self.present_key else 0


class FingerprintAndOwnershipProperties(SimpleTestCase):
    @given(entry_ip=small_text, entry_ua=small_text, ip=small_text, ua=small_text)
    def test_fingerprint_score_is_five_per_ip_match_plus_three_per_ua_match(
        self, entry_ip, entry_ua, ip, ua,
    ):
        entry = {"client_ip": entry_ip, "client_user_agent": entry_ua}
        expected = (5 if entry_ip and entry_ip == ip else 0) + (
            3 if entry_ua and entry_ua == ua else 0
        )
        score = ts_views._score_pool_fingerprint(entry, ip, ua)
        self.assertEqual(score, expected)
        self.assertLessEqual(score, ts_views._MATCH_SCORE_THRESHOLD)

    @given(profile_id=ids, owner=ids, user_id=st.integers(min_value=0, max_value=50))
    def test_unclaimed_entries_belong_to_anyone_and_claimed_ones_to_their_owner(
        self, profile_id, owner, user_id,
    ):
        entry = {"profile_id": profile_id, "user_id": owner}
        if not profile_id:
            expected = True
        elif owner is None or owner == "":
            expected = False
        else:
            expected = str(owner) == str(user_id)
        self.assertEqual(ts_views._pool_entry_owned_by_user(entry, user_id), expected)
        self.assertTrue(ts_views._pool_entry_owned_by_user({}, user_id))
        self.assertTrue(ts_views._pool_entry_owned_by_user(None, user_id))


class StatsGraceProperties(SimpleTestCase):
    @given(total=st.integers(min_value=0, max_value=10**8),
           elapsed=st.floats(min_value=0, max_value=3600, allow_nan=False))
    def test_startup_probe_is_the_conjunction_of_both_thresholds(self, total, elapsed):
        self.assertEqual(
            ts_views._is_timeshift_startup_probe(total, elapsed),
            total < MIN_BYTES and elapsed < MIN_SECS,
        )

    @given(total=st.integers(min_value=0, max_value=10**8),
           elapsed=st.floats(min_value=0, max_value=3600, allow_nan=False),
           stopped_for_reuse=st.booleans(), pool_exists=st.booleans(),
           client_id=st.none() | st.sampled_from(["", "sess-1"]))
    def test_grace_is_skipped_for_reuse_probes_and_an_early_retry_on_a_live_pool(
        self, total, elapsed, stopped_for_reuse, pool_exists, client_id,
    ):
        redis_client = _FakePoolRedis(
            ts_views._pool_key(client_id) if (pool_exists and client_id) else None
        )
        expected = not (
            stopped_for_reuse
            or (total < MIN_BYTES and elapsed < MIN_SECS)
            or (elapsed < MIN_SECS and bool(client_id) and pool_exists)
        )
        self.assertEqual(
            ts_views._should_schedule_stats_disconnect_grace(
                total, elapsed, stopped_for_reuse=stopped_for_reuse,
                redis_client=redis_client, client_id=client_id,
            ),
            expected,
        )


class PreemptionProperties(SimpleTestCase):
    @given(header=range_headers, pool_exists=st.booleans(), pool_busy=st.booleans(),
           pool_media_id=ids, media_id=ids)
    def test_plain_reconnect_preempts_exactly_a_full_restart_of_the_same_busy_media(
        self, header, pool_exists, pool_busy, pool_media_id, media_id,
    ):
        same_media = pool_media_id is None or str(pool_media_id) == str(media_id)
        expected = (
            ts_views._is_full_restart_range(header) and pool_exists and pool_busy and same_media
        )
        self.assertEqual(
            ts_views._should_preempt_plain_reconnect(
                header, pool_exists=pool_exists, pool_busy=pool_busy,
                pool_media_id=pool_media_id, media_id=media_id,
            ),
            expected,
        )

    @given(header=range_headers,
           content_length=st.none() | st.integers(min_value=1, max_value=10**10),
           busy_serving_range=st.none() | st.sampled_from(["none", "start", "range"]),
           pool_media_id=ids, media_id=ids)
    def test_a_programme_hop_never_displaces_and_same_media_defers_to_the_playback_rule(
        self, header, content_length, busy_serving_range, pool_media_id, media_id,
    ):
        result = ts_views._should_displace_busy_pool(
            header, content_length, busy_serving_range,
            pool_media_id=pool_media_id, media_id=media_id,
        )
        if pool_media_id is not None and str(pool_media_id) != str(media_id):
            self.assertFalse(result)
        else:
            self.assertEqual(
                result,
                ts_views._should_displace_busy_playback(
                    header, content_length, busy_serving_range,
                ),
            )

    @given(total=st.integers(min_value=1, max_value=10**11), data=st.data(),
           busy_serving_range=st.none() | st.sampled_from(["none", "start", "range"]))
    # #216: on a 1.5 MiB archive every mid-file seek was an "EOF probe" and never displaced.
    @example(total=1_572_864, data=None, busy_serving_range="start")
    def test_a_mid_file_seek_outside_the_tail_displaces_whatever_the_archive_size(
        self, total, data, busy_serving_range,
    ):
        if data is None:
            start = 512_000
        else:
            upper = total - WINDOW - 1 if total > WINDOW else total - 1
            if upper < 1:
                return
            start = data.draw(st.integers(min_value=1, max_value=upper))
        self.assertTrue(
            ts_views._should_displace_busy_playback(
                f"bytes={start}-", total, busy_serving_range,
            )
        )

    @given(content_length=st.none() | st.integers(min_value=1, max_value=10**10),
           busy_serving_range=st.none() | st.sampled_from(["none", "start", "range"]))
    def test_a_byte_zero_seek_displaces_only_a_known_full_file_stream(
        self, content_length, busy_serving_range,
    ):
        self.assertEqual(
            ts_views._should_displace_busy_playback("bytes=0-", content_length, busy_serving_range),
            busy_serving_range == "none"
            and not ts_views._is_near_eof_probe("bytes=0-", content_length),
        )
        self.assertFalse(
            ts_views._should_displace_busy_playback(None, content_length, busy_serving_range)
        )


ANCHOR = datetime(2026, 3, 1, 20, 0, 0)


def _descriptor(content_length, duration_secs, anchor=ANCHOR):
    return {
        "final_url": b"https://cdn.example/archive.ts",
        "content_length": str(content_length),
        "archive_duration_secs": str(duration_secs),
        "archive_anchor_ts": anchor.strftime("%Y-%m-%d:%H-%M-%S").encode(),
    }


class ArchiveScrubProperties(SimpleTestCase):
    @given(content_length=st.integers(min_value=1, max_value=10**11),
           duration_secs=st.integers(min_value=60, max_value=8 * 3600),
           offset_secs=st.integers(min_value=-4 * 3600, max_value=10 * 3600))
    def test_scrub_is_same_in_window_aligned_or_none(
        self, content_length, duration_secs, offset_secs,
    ):
        requested = (ANCHOR + timedelta(seconds=offset_secs)).strftime("%Y-%m-%d:%H-%M-%S")
        result = ts_views._resolve_session_archive_scrub(
            _descriptor(content_length, duration_secs), requested,
        )
        if offset_secs == 0:
            self.assertEqual(
                result, {"kind": "same", "byte_offset": 0, "remaining": content_length},
            )
        elif offset_secs < 0 or offset_secs >= duration_secs:
            self.assertIsNone(result)
        elif result is not None:
            self.assertEqual(result["kind"], "scrub")
            offset = result["byte_offset"]
            self.assertEqual(offset % 188, 0)
            self.assertGreaterEqual(offset, 0)
            self.assertLess(offset, content_length)
            self.assertEqual(result["remaining"], content_length - offset)
            expected = (int(offset_secs / duration_secs * content_length) // 188) * 188
            self.assertEqual(offset, expected)

    @given(requested=st.text(max_size=24),
           descriptor=st.fixed_dictionaries({}, optional={
               # Pool hashes hold what Dispatcharr wrote: UTF-8 text, as str or as bytes.
               "final_url": st.none() | st.text(max_size=8)
               | st.text(max_size=8).map(str.encode),
               "content_length": st.none() | st.text(max_size=6) | st.integers(-5, 10**9),
               "archive_duration_secs": st.none() | st.text(max_size=6) | st.integers(-5, 10**5),
               "archive_anchor_ts": st.none() | st.text(max_size=20),
           }))
    def test_scrub_never_raises_on_arbitrary_pool_state(self, requested, descriptor):
        result = ts_views._resolve_session_archive_scrub(descriptor, requested)
        self.assertTrue(result is None or result["kind"] in {"same", "scrub"})


class PoolIntFieldProperties(SimpleTestCase):
    @given(n=st.integers(min_value=-(10**15), max_value=10**15),
           spelling=st.sampled_from(["int", "str", "bytes", "padded"]))
    def test_integer_spellings_round_trip(self, n, spelling):
        value = {
            "int": n, "str": str(n), "bytes": str(n).encode(), "padded": f" {n} ",
        }[spelling]
        self.assertEqual(ts_views._pool_int_field(value), n)

    # Redis-shaped values only: a hash field is None, str, bytes or (from a caller's own
    # dict) int. A float never reaches it; _pool_int_field(float("inf")) would raise.
    @given(value=st.none() | st.text(max_size=10) | st.binary(max_size=10)
           | st.integers())
    @example(value=b"\xff")
    @example(value="²")
    def test_anything_else_is_none_or_an_int_and_never_raises(self, value):
        result = ts_views._pool_int_field(value)
        self.assertTrue(result is None or isinstance(result, int))
