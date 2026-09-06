"""Property-based tests for ``apps.timeshift.stats`` and ``redis_keys``.

Pure-function surfaces only (no Redis, no DB):

* ``parse_stats_channel_id`` splits ``{channel_id}_{session_id}`` — never
  raises, rejects ids without a leading numeric run, and round-trips the
  ids minted by ``stats_channel_id``.
* ``compute_playback_base_from_byte_range`` maps a byte offset into a
  programme position: None for a zero/negative/absent start, otherwise the
  clamped ratio times the duration; never negative, never above the duration.
* ``compute_playback_position_secs`` — the playhead is bounded to
  ``[0, duration_secs]`` when a duration is known, never negative, and a
  paused session ignores wall-clock since the anchor.
* ``resolve_stats_playback_fields`` never raises on arbitrary byte-decorated
  state and never returns a negative base.
* ``stream_stats_to_metadata_fields`` passes through only the mapped keys,
  stringifies values, drops None/empty values, and stamps
  ``STREAM_INFO_UPDATED`` only when at least one field was mapped.
* ``_client_paused`` recognises the three truthy spellings, is
  case/whitespace-insensitive, and treats every other value as not paused.
* ``_decode_hash`` decodes byte keys and values and leaves text untouched.

Runs without Redis or the database (SimpleTestCase, pure functions).
"""

import string

from django.test import SimpleTestCase
from hypothesis import assume, given, settings as hyp_settings, strategies as st

from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.timeshift.redis_keys import parse_stats_channel_id, stats_channel_id
from apps.timeshift.stats import (
    _client_paused,
    _decode_hash,
    compute_playback_base_from_byte_range,
    compute_playback_position_secs,
    resolve_stats_playback_fields,
    stream_stats_to_metadata_fields,
)

# CI-deterministic profile — matches apps/proxy/live_proxy property tests.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

any_text = st.text(max_size=64)

# Redis values in this codebase are written as str(...) and read back as
# UTF-8, so raw bytes handed to the decode helpers are always valid UTF-8.
utf8_binary = st.binary(max_size=32).filter(
    lambda b: _is_valid_utf8(b)
)


def _is_valid_utf8(data):
    try:
        data.decode()
        return True
    except UnicodeDecodeError:
        return False

_STREAM_STATS_FIELDS = {
    "video_codec",
    "resolution",
    "source_fps",
    "pixel_format",
    "video_bitrate",
    "audio_codec",
    "sample_rate",
    "audio_channels",
    "audio_bitrate",
    "stream_type",
}


class StatsChannelIdProperties(SimpleTestCase):
    @given(value=st.one_of(any_text, st.none(), st.integers()))
    def test_never_raises(self, value):
        parse_stats_channel_id(value)

    @given(
        channel_id=st.integers(min_value=0, max_value=10**12),
        session_id=st.text(
            alphabet=string.ascii_letters + string.digits + "-_",
            min_size=1,
            max_size=32,
        ),
    )
    def test_round_trip(self, channel_id, session_id):
        assume("_" not in session_id or session_id.split("_")[0] != "")
        sid = stats_channel_id(channel_id, session_id)
        parsed = parse_stats_channel_id(sid)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["channel_id"], channel_id)
        self.assertEqual(parsed["session_id"], session_id)

    @given(value=any_text)
    def test_rejects_missing_numeric_prefix(self, value):
        parsed = parse_stats_channel_id(value)
        if parsed is not None:
            self.assertRegex(value, r"^\d+_.+$")


class PlaybackBaseFromRangeProperties(SimpleTestCase):
    @given(
        start=st.one_of(st.none(), st.integers(min_value=-10**12, max_value=10**12)),
        length=st.one_of(st.none(), st.integers(min_value=-10**12, max_value=10**12)),
        duration=st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False)),
    )
    def test_never_raises_and_bounds(self, start, length, duration):
        base = compute_playback_base_from_byte_range(start, length, duration)
        if base is None:
            return
        self.assertGreaterEqual(base, 0.0)
        try:
            dur = float(duration)
        except (TypeError, ValueError):
            return
        if dur > 0:
            self.assertLessEqual(base, dur)

    @given(
        ratio=st.floats(min_value=0.0, max_value=1.0),
        length=st.integers(min_value=1, max_value=10**10),
        duration=st.floats(min_value=1.0, max_value=10**6),
    )
    def test_ratio_scaling(self, ratio, length, duration):
        start = int(ratio * length)
        assume(start > 0)  # start <= 0 means "no seek" by contract
        base = compute_playback_base_from_byte_range(start, length, duration)
        self.assertIsNotNone(base)
        expected = min(1.0, max(0.0, start / length)) * duration
        self.assertAlmostEqual(base, expected, places=6)

    @given(start=st.integers(max_value=0))
    def test_nonpositive_start_is_none(self, start):
        self.assertIsNone(
            compute_playback_base_from_byte_range(start, 1000, 60.0)
        )


class PlaybackPositionProperties(SimpleTestCase):
    @given(
        base=st.one_of(st.none(), st.floats(min_value=0, max_value=10**6, allow_nan=False)),
        anchor=st.one_of(st.none(), st.floats(min_value=0, max_value=2 * 10**9, allow_nan=False)),
        now=st.floats(min_value=0, max_value=2 * 10**9, allow_nan=False),
        duration=st.one_of(st.none(), st.floats(min_value=1, max_value=10**6, allow_nan=False)),
        paused=st.booleans(),
    )
    def test_bounds_with_byte_base(self, base, anchor, now, duration, paused):
        position = compute_playback_position_secs(
            None,
            None,
            anchor,
            now,
            duration_secs=duration,
            playback_base_secs=base,
            paused=paused,
        )
        if position is None:
            # Only legal when there is neither a base nor a URL/EPG pair.
            self.assertIsNone(base)
            return
        self.assertGreaterEqual(position, 0.0)
        if duration:
            self.assertLessEqual(position, duration)

    @given(
        base=st.floats(min_value=0, max_value=10**6, allow_nan=False),
        anchor=st.floats(min_value=1, max_value=2 * 10**9, allow_nan=False),
        elapsed=st.floats(min_value=0, max_value=10**5, allow_nan=False),
    )
    def test_paused_ignores_wall_clock(self, base, anchor, elapsed):
        now = anchor + elapsed
        paused = compute_playback_position_secs(
            None, None, anchor, now, playback_base_secs=base, paused=True
        )
        running = compute_playback_position_secs(
            None, None, anchor, now, playback_base_secs=base, paused=False
        )
        self.assertAlmostEqual(paused, base, places=6)
        self.assertAlmostEqual(running, base + elapsed, places=6)


class ResolveStatsPlaybackFieldsProperties(SimpleTestCase):
    @given(
        existing_start=st.one_of(st.none(), any_text, utf8_binary),
        existing_anchor=st.one_of(st.none(), any_text, utf8_binary),
        existing_base=st.one_of(st.none(), any_text, utf8_binary),
        range_start=st.one_of(st.none(), st.integers(min_value=-100, max_value=10**9)),
        rep_length=st.one_of(st.none(), st.integers(min_value=-100, max_value=10**9)),
        duration=st.one_of(st.none(), st.floats(min_value=0, max_value=10**6, allow_nan=False), any_text),
        now=st.floats(min_value=0, max_value=2 * 10**9, allow_nan=False),
    )
    def test_never_raises_and_base_sane(
        self,
        existing_start,
        existing_anchor,
        existing_base,
        range_start,
        rep_length,
        duration,
        now,
    ):
        base, anchor = resolve_stats_playback_fields(
            timestamp_utc="2026-05-21T12:55:00",
            existing_programme_start=existing_start,
            existing_position_anchor=existing_anchor,
            existing_playback_base=existing_base,
            range_start=range_start,
            representation_length=rep_length,
            programme_duration_secs=duration,
            now=now,
        )
        if base is not None:
            self.assertGreaterEqual(base, 0.0)


class StreamStatsMappingProperties(SimpleTestCase):
    @given(
        stats=st.dictionaries(
            keys=st.text(max_size=20),
            values=st.one_of(st.none(), any_text, st.integers()),
            max_size=12,
        )
    )
    def test_never_raises_and_only_mapped_keys(self, stats):
        fields = stream_stats_to_metadata_fields(stats)
        known = set(_STREAM_STATS_FIELDS)
        for key in fields:
            self.assertIn(key, known | {ChannelMetadataField.STREAM_INFO_UPDATED})

    @given(
        values=st.dictionaries(
            keys=st.sampled_from(sorted(_STREAM_STATS_FIELDS)),
            values=st.one_of(any_text, st.integers()).filter(
                lambda v: v is not None and v != ""
            ),
            min_size=1,
            max_size=9,
        )
    )
    def test_mapped_values_stringified_and_stamp_added(self, values):
        fields = stream_stats_to_metadata_fields(values)
        self.assertIn(ChannelMetadataField.STREAM_INFO_UPDATED, fields)
        for key, value in fields.items():
            self.assertIsInstance(value, str)
        for src_key in values:
            self.assertIn(src_key, fields)

    def test_empty_and_none_map_to_empty(self):
        self.assertEqual(stream_stats_to_metadata_fields(None), {})
        self.assertEqual(stream_stats_to_metadata_fields({}), {})

    @given(value=any_text)
    def test_unmapped_keys_dropped(self, value):
        assume(value not in _STREAM_STATS_FIELDS)
        fields = stream_stats_to_metadata_fields({value: "x"})
        self.assertNotIn(value, fields)
        self.assertEqual(fields, {})


class ClientPausedProperties(SimpleTestCase):
    @given(value=st.one_of(st.none(), any_text, utf8_binary))
    def test_never_raises(self, value):
        _client_paused(value)

    @given(
        word=st.sampled_from(["1", "true", "yes"]),
        upper=st.booleans(),
        pad=st.text(alphabet=" \t", max_size=3),
    )
    def test_truthy_spellings(self, word, upper, pad):
        if upper:
            word = word.upper()
        self.assertTrue(_client_paused(pad + word + pad))

    @given(value=st.sampled_from(["0", "false", "no", "off", "2", "paused", "y", "t", "tru"]))
    def test_other_values_are_not_paused(self, value):
        self.assertFalse(_client_paused(value))

    def test_empty_and_none_not_paused(self):
        self.assertFalse(_client_paused(None))
        self.assertFalse(_client_paused(""))
        self.assertFalse(_client_paused(b""))


class DecodeHashProperties(SimpleTestCase):
    @given(
        data=st.dictionaries(
            keys=st.one_of(any_text, utf8_binary),
            values=st.one_of(any_text, utf8_binary),
            max_size=8,
        )
    )
    def test_decodes_bytes(self, data):
        decoded = _decode_hash(data)
        # Keys that decode to the same string collapse (e.g. '' and b'').
        unique = {(k.decode() if isinstance(k, bytes) else k) for k in data}
        self.assertEqual(len(decoded), len(unique))
        for key, value in decoded.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(value, str)

    def test_empty(self):
        self.assertEqual(_decode_hash(None), {})
        self.assertEqual(_decode_hash({}), {})
