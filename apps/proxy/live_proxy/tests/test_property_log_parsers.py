"""Property-based tests for the FFmpeg/VLC/Streamlink log parsers.

apps/proxy/live_proxy/services/log_parsers.py consumes untrusted subprocess
stderr — provider-controlled text — so its core contract is robustness:
``can_parse``/``parse``/``auto_parse`` must never raise, whatever the line
contains. The parsers are stateless module-level singletons, so results for a
valid line must not depend on what garbage was parsed around it. On top of the
no-crash properties, round-trip properties feed generated well-formed FFmpeg
lines and assert the advertised fields parse back out, and the documented
100–10000 resolution bounds are honoured.

Note: the ``speed=`` buffering-detection parsing lives in
StreamManager._parse_ffmpeg_stats (input/manager.py), which is coupled to Redis
and the database; extracting it into this module would make it property-testable
the same way. These tests cover the pure parsing surface that exists today.

Runs without Redis or the database (SimpleTestCase, pure functions).
"""

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.proxy.live_proxy.services.log_parsers import (
    FFmpegLogParser,
    LogParserFactory,
    StreamlinkLogParser,
    VLCLogParser,
)

# CI-deterministic profile — see test_property_ts_realignment.py for rationale.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

PARSERS = [FFmpegLogParser(), VLCLogParser(), StreamlinkLogParser()]

KNOWN_STREAM_TYPES = [
    "input",
    "video",
    "audio",
    "vlc_video",
    "vlc_audio",
    "streamlink",
]

# Arbitrary stderr lines: printable unicode, control chars, nulls, huge runs of
# digits/x/, characters that feed the parser regexes half-valid input.
garbage_lines = st.text(max_size=300) | st.text(
    alphabet="0123456789x., :#()[]/=kbsfpshzHzVideoAudioStream",
    max_size=300,
)

codec_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=2, max_size=12
)


class ParserRobustnessProperties(SimpleTestCase):
    @given(line=garbage_lines)
    def test_auto_parse_never_raises_and_honours_contract(self, line):
        """auto_parse returns None or (stream_type, non-empty dict)."""
        result = LogParserFactory.auto_parse(line)
        if result is not None:
            stream_type, data = result
            self.assertIsInstance(stream_type, str)
            self.assertIsInstance(data, dict)
            self.assertTrue(data)

    @given(
        line=garbage_lines,
        stream_type=st.sampled_from(KNOWN_STREAM_TYPES) | st.text(max_size=20),
    )
    def test_parse_never_raises_for_any_stream_type(self, line, stream_type):
        """parse returns None or a non-empty dict, for known and unknown types."""
        result = LogParserFactory.parse(stream_type, line)
        if result is not None:
            self.assertIsInstance(result, dict)
            self.assertTrue(result)

    @given(line=garbage_lines)
    def test_can_parse_never_raises(self, line):
        for parser in PARSERS:
            result = parser.can_parse(line)
            self.assertTrue(result is None or isinstance(result, str))

    @given(line=garbage_lines, noise=st.lists(garbage_lines, max_size=10))
    def test_parsers_are_stateless_under_garbage_interleaving(self, line, noise):
        """Parsing garbage before/after a line never changes that line's result."""
        before = LogParserFactory.auto_parse(line)
        for junk in noise:
            LogParserFactory.auto_parse(junk)
        after = LogParserFactory.auto_parse(line)
        self.assertEqual(before, after)


class FFmpegRoundTripProperties(SimpleTestCase):
    @given(
        codec=codec_names,
        width=st.integers(100, 9999),
        height=st.integers(100, 9999),
        bitrate_int=st.integers(1, 99999),
        fps_int=st.integers(1, 240),
        fps_frac=st.integers(0, 99),
    )
    def test_video_stream_line_round_trips(
        self, codec, width, height, bitrate_int, fps_int, fps_frac
    ):
        fps_token = f"{fps_int}.{fps_frac:02d}"
        line = (
            f"  Stream #0:0: Video: {codec} (High), yuv420p(progressive), "
            f"{width}x{height} [SAR 1:1 DAR 16:9], {bitrate_int} kb/s, "
            f"{fps_token} fps, 90k tbn"
        )
        self.assertEqual(FFmpegLogParser().can_parse(line), "video")
        result = LogParserFactory.parse("video", line)
        self.assertIsNotNone(result)
        self.assertEqual(result["video_codec"], codec)
        self.assertEqual(result["width"], width)
        self.assertEqual(result["height"], height)
        self.assertEqual(result["resolution"], f"{width}x{height}")
        self.assertEqual(result["source_fps"], float(fps_token))
        self.assertEqual(result["video_bitrate"], float(bitrate_int))

    @given(
        # A codec named exactly "mono"/"stereo"/"quad" would legitimately win
        # the first-match channel regex — a generator artifact, not a bug.
        codec=codec_names.filter(lambda c: c not in {"mono", "stereo", "quad"}),
        sample_rate=st.integers(8000, 384000),
        channels=st.sampled_from(["mono", "stereo", "quad"]),
        bitrate_int=st.integers(1, 99999),
    )
    def test_audio_stream_line_round_trips(
        self, codec, sample_rate, channels, bitrate_int
    ):
        line = (
            f"  Stream #0:1(und): Audio: {codec} (LC), {sample_rate} Hz, "
            f"{channels}, fltp, {bitrate_int} kb/s"
        )
        self.assertEqual(FFmpegLogParser().can_parse(line), "audio")
        result = LogParserFactory.parse("audio", line)
        self.assertIsNotNone(result)
        self.assertEqual(result["audio_codec"], codec)
        self.assertEqual(result["sample_rate"], sample_rate)
        self.assertEqual(result["audio_channels"], channels)
        self.assertEqual(result["audio_bitrate"], float(bitrate_int))

    @given(
        input_number=st.integers(0, 99),
        container=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=2, max_size=12
        ),
    )
    def test_input_format_line_round_trips(self, input_number, container):
        line = f"Input #{input_number}, {container}, from 'http://example.com/stream':"
        self.assertEqual(FFmpegLogParser().can_parse(line), "input")
        result = LogParserFactory.parse("input", line)
        self.assertEqual(result, {"stream_type": container})

    @given(
        width=st.integers(10001, 99999),
        height=st.integers(100, 9999),
    )
    def test_out_of_bounds_resolution_is_rejected(self, width, height):
        """Dimensions outside 100–10000 must not produce a resolution."""
        line = (
            f"  Stream #0:0: Video: h264 (High), yuv420p, {width}x{height}, "
            f"25.00 fps"
        )
        result = LogParserFactory.parse("video", line)
        self.assertIsNotNone(result)  # codec still parses
        self.assertNotIn("resolution", result)
        self.assertNotIn("width", result)
        self.assertNotIn("height", result)
