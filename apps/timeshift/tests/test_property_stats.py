"""Property tests for catch-up playback-position math and stats field helpers.

Written against the contracts PR D-3 (#216) establishes; this module lands after it.

Surfaces (``file:line`` at a54b09a9):

- apps/timeshift/stats.py: ``stream_stats_to_metadata_fields`` (:47), ``_decode_hash``
  (:124), ``compute_playback_base_from_byte_range`` (:130),
  ``resolve_stats_playback_fields`` (:146; D-3 routes its tail check through
  ``is_near_eof_offset``, #216), ``compute_playback_position_secs`` (:219),
  ``_client_paused`` (:296).
- apps/timeshift/redis_keys.py: ``stats_channel_id`` (:73) and ``parse_stats_channel_id``
  (:88).

Anchors are realistic epoch seconds. #54 reported "position freezes at 0" and was ruled
invalid: its generator drew ``position_anchor_at=0.0``, which is falsy, and a real epoch
anchor never is.

Closes the stats scope of #192 (survivor), #260 and #55.
"""

import secrets

from django.test import SimpleTestCase
from hypothesis import example, given, settings as hyp_settings, strategies as st

from apps.proxy.constants import ChannelMetadataField
from apps.timeshift import stats as ts_stats
from apps.timeshift.redis_keys import parse_stats_channel_id, stats_channel_id

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

WINDOW = ts_stats.EOF_PROBE_TAIL_BYTES
# The ten Stream.stream_stats keys the stats card shows (stats.py:23-34), spelled out
# here rather than read from the module so a dropped mapping is caught.
MAPPED_SOURCE_KEYS = {
    "video_codec", "resolution", "source_fps", "pixel_format", "video_bitrate",
    "audio_codec", "sample_rate", "audio_channels", "audio_bitrate", "stream_type",
}

# Real epoch seconds: 2001-09-09 .. 2286-11-20 (see #54 in the module docstring).
epochs = st.floats(min_value=1_000_000_000, max_value=9_999_999_999, allow_nan=False)
durations = st.floats(min_value=1, max_value=12 * 3600, allow_nan=False)
stat_values = st.none() | st.just("") | st.text(max_size=8) | st.integers() | st.floats(
    allow_nan=False
)


class MetadataFieldProperties(SimpleTestCase):
    @given(stream_stats=st.none() | st.dictionaries(
        st.sampled_from(sorted(MAPPED_SOURCE_KEYS)) | st.text(max_size=8), stat_values,
        max_size=12,
    ))
    def test_only_mapped_non_empty_values_pass_through_as_text(self, stream_stats):
        out = ts_stats.stream_stats_to_metadata_fields(stream_stats)
        kept = {
            k: v for k, v in (stream_stats or {}).items()
            if k in MAPPED_SOURCE_KEYS and v is not None and v != ""
        }
        updated = ChannelMetadataField.STREAM_INFO_UPDATED
        self.assertEqual(updated in out, bool(kept))
        body = {k: v for k, v in out.items() if k != updated}
        self.assertEqual(len(body), len(kept))
        self.assertEqual(sorted(body.values()), sorted(str(v) for v in kept.values()))

    @given(data=st.none() | st.dictionaries(
        st.text(max_size=6) | st.text(max_size=6).map(str.encode),
        st.text(max_size=6) | st.text(max_size=6).map(str.encode),
        max_size=6,
    ))
    def test_decode_hash_yields_text_and_is_idempotent(self, data):
        decoded = ts_stats._decode_hash(data)
        for key, value in decoded.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(value, str)
        self.assertEqual(ts_stats._decode_hash(decoded), decoded)
        if not data:
            self.assertEqual(decoded, {})

    @given(value=st.none() | st.text(max_size=8) | st.text(max_size=8).map(str.encode),
           spelling=st.sampled_from([None, "1", "TRUE", " yes ", "Yes\n", "true"]))
    def test_paused_is_one_true_or_yes_in_any_case_and_padding(self, value, spelling):
        if spelling is not None:
            value = spelling
        text = value.decode() if isinstance(value, bytes) else value
        expected = text is not None and text.strip().lower() in {"1", "true", "yes"}
        self.assertEqual(ts_stats._client_paused(value), expected)


class PlaybackBaseProperties(SimpleTestCase):
    @given(range_start=st.none() | st.integers(min_value=-10, max_value=10**11),
           content_length=st.integers(min_value=-10, max_value=10**11),
           duration=st.floats(min_value=-10, max_value=12 * 3600, allow_nan=False))
    def test_byte_offset_maps_linearly_into_the_programme_or_none(
        self, range_start, content_length, duration,
    ):
        base = ts_stats.compute_playback_base_from_byte_range(
            range_start, content_length, duration,
        )
        if range_start is None or range_start <= 0 or content_length <= 0 or duration <= 0:
            self.assertIsNone(base)
            return
        expected = min(1.0, range_start / content_length) * duration
        self.assertAlmostEqual(base, expected, places=6)
        self.assertGreaterEqual(base, 0.0)
        self.assertLessEqual(base, duration)

    @given(total=st.integers(min_value=1, max_value=WINDOW), data=st.data(),
           duration=durations, previous_base=st.floats(0, 3600, allow_nan=False),
           previous_anchor=epochs, now=epochs)
    # #216: on a 1.5 MiB archive a mid-file seek kept the previous stats base.
    @example(total=1_572_864, data=None, duration=3600.0, previous_base=120.0,
             previous_anchor=1_700_000_000.0, now=1_700_000_100.0)
    def test_a_seek_into_an_archive_no_larger_than_the_window_reanchors(
        self, total, data, duration, previous_base, previous_anchor, now,
    ):
        if data is None:
            start = 512_000
        elif total > 1:
            start = data.draw(st.integers(min_value=1, max_value=total - 1))
        else:
            return
        base, anchor = ts_stats.resolve_stats_playback_fields(
            timestamp_utc="2026-03-01:20-00", existing_programme_start="2026-03-01:20-00",
            existing_position_anchor=str(previous_anchor),
            existing_playback_base=str(previous_base), range_start=start,
            representation_length=total, programme_duration_secs=duration, now=now,
        )
        self.assertEqual(anchor, now)
        self.assertAlmostEqual(base, min(1.0, start / total) * duration, places=6)

    @given(total=st.integers(min_value=WINDOW + 1, max_value=10**11), data=st.data(),
           previous_base=st.floats(0, 3600, allow_nan=False), previous_anchor=epochs,
           now=epochs)
    def test_a_tail_probe_on_a_larger_archive_keeps_the_previous_anchor(
        self, total, data, previous_base, previous_anchor, now,
    ):
        start = data.draw(st.integers(min_value=total - WINDOW, max_value=total - 1))
        base, anchor = ts_stats.resolve_stats_playback_fields(
            timestamp_utc="2026-03-01:20-00", existing_programme_start=b"2026-03-01:20-00",
            existing_position_anchor=str(previous_anchor).encode(),
            existing_playback_base=str(previous_base).encode(), range_start=start,
            representation_length=total, programme_duration_secs=3600, now=now,
        )
        self.assertEqual((base, anchor), (previous_base, str(previous_anchor)))

    @given(range_start=st.none() | st.integers(min_value=0, max_value=10**11),
           total=st.none() | st.integers(min_value=0, max_value=10**11),
           existing_start=st.none() | st.text(max_size=16),
           previous_base=st.none() | st.text(max_size=6) | st.floats(0, 1e5, allow_nan=False).map(str),
           now=epochs)
    def test_resolve_never_raises_and_a_programme_change_always_reanchors_at_url_time(
        self, range_start, total, existing_start, previous_base, now,
    ):
        base, anchor = ts_stats.resolve_stats_playback_fields(
            timestamp_utc="2026-03-01:20-00", existing_programme_start=existing_start,
            existing_position_anchor=None, existing_playback_base=previous_base,
            range_start=range_start, representation_length=total,
            programme_duration_secs=3600, now=now,
        )
        if base is not None:
            self.assertGreaterEqual(base, 0.0)
        if existing_start is not None and existing_start != "2026-03-01:20-00":
            self.assertEqual((base, anchor), (None, now))


class PlaybackPositionProperties(SimpleTestCase):
    @given(base=st.floats(min_value=0, max_value=12 * 3600, allow_nan=False),
           anchor=epochs, elapsed=st.floats(min_value=-600, max_value=12 * 3600, allow_nan=False),
           duration=st.none() | durations, paused=st.booleans())
    def test_byte_seek_position_is_base_plus_unpaused_elapsed_clamped_to_the_programme(
        self, base, anchor, elapsed, duration, paused,
    ):
        position = ts_stats.compute_playback_position_secs(
            None, None, anchor, anchor + elapsed, duration_secs=duration,
            playback_base_secs=base, paused=paused,
        )
        expected = base + (0.0 if paused else max(0.0, elapsed))
        if duration:
            expected = min(expected, duration)
        self.assertAlmostEqual(position, expected, delta=1e-6 * max(1.0, expected))

    @given(url_offset_secs=st.integers(min_value=-3600, max_value=6 * 3600),
           anchor=epochs, elapsed=st.floats(min_value=0, max_value=6 * 3600, allow_nan=False),
           duration=durations, paused=st.booleans())
    def test_url_seek_position_is_offset_from_epg_start_plus_elapsed_never_negative(
        self, url_offset_secs, anchor, elapsed, duration, paused,
    ):
        from datetime import datetime, timedelta

        epg_start = datetime(2026, 3, 1, 20, 0, 0)
        url = (epg_start + timedelta(seconds=url_offset_secs)).strftime("%Y-%m-%d:%H-%M-%S")
        position = ts_stats.compute_playback_position_secs(
            url, epg_start.isoformat() + "+00:00", anchor, anchor + elapsed,
            duration_secs=duration, paused=paused,
        )
        expected = min(max(0.0, url_offset_secs + (0.0 if paused else elapsed)), duration)
        self.assertAlmostEqual(position, expected, delta=1e-6 * max(1.0, expected))

    @given(anchor=epochs, later=st.floats(min_value=0, max_value=86400, allow_nan=False),
           base=st.floats(min_value=0, max_value=3600, allow_nan=False))
    def test_paused_position_does_not_advance_with_the_wall_clock(self, anchor, later, base):
        first = ts_stats.compute_playback_position_secs(
            None, None, anchor, anchor, playback_base_secs=base, paused=True,
        )
        second = ts_stats.compute_playback_position_secs(
            None, None, anchor, anchor + later, playback_base_secs=base, paused=True,
        )
        self.assertEqual(first, second)


session_ids = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_",
    min_size=1, max_size=32,
)


class StatsChannelIdProperties(SimpleTestCase):
    @given(channel_id=st.integers(min_value=0, max_value=10**9), session_id=session_ids)
    def test_minted_stats_channel_ids_round_trip(self, channel_id, session_id):
        self.assertEqual(
            parse_stats_channel_id(stats_channel_id(channel_id, session_id)),
            {"channel_id": channel_id, "session_id": session_id},
        )

    def test_a_real_minted_session_id_round_trips(self):
        session_id = secrets.token_urlsafe(16)
        self.assertEqual(
            parse_stats_channel_id(stats_channel_id(7, session_id))["session_id"], session_id,
        )

    @given(value=st.none() | st.text(max_size=24) | st.integers())
    def test_parse_is_none_or_a_numeric_channel_and_a_session(self, value):
        parsed = parse_stats_channel_id(value)
        if parsed is not None:
            self.assertIsInstance(parsed["channel_id"], int)
            self.assertTrue(parsed["session_id"])

    @given(prefix=st.text(alphabet="abc-_ ", min_size=1, max_size=6), session_id=session_ids)
    def test_an_id_without_a_numeric_prefix_is_rejected(self, prefix, session_id):
        self.assertIsNone(parse_stats_channel_id(f"{prefix}_{session_id}"))
