"""Pins the VLC and Streamlink log parsers' branch ladders (Phase 2 PR 2b-4, kind 1).

apps/proxy/live_proxy/tests/test_property_log_parsers.py is a Hypothesis suite
asserting robustness (never raises, stateless across calls) plus round-trips on
generated FFmpeg lines. It does not assert a single VLC or Streamlink field
value. The work here is complementary, not duplicative: literal expected
dicts/tuples for every named branch of VLCLogParser, StreamlinkLogParser and
LogParserFactory.

Pure str -> Optional[dict]: no mocks, no Redis, no DB (log_parsers.py imports
only re/logging/abc/typing), so the only hollow shape that can occur here is
the tautological oracle -- ruled out by every expected value below being a
literal typed by hand, verified against the real module before this file was
written.
"""
from django.test import SimpleTestCase

from apps.proxy.live_proxy.services.log_parsers import (
    LogParserFactory,
    StreamlinkLogParser,
    VLCLogParser,
)


class VLCCanParseTests(SimpleTestCase):
    def test_the_seven_can_parse_outcomes(self):
        parser = VLCLogParser()
        cases = [
            ("main input error: Your input can't be opened: VLC is unable to "
             "open the MRL 'http://x/y.ts'", 'vlc_input_failed'),
            ("ts demux debug: pid 256 type=0x1b video", 'vlc_video'),
            ("ts demux debug: pid 257 type=0x0f audio", 'vlc_audio'),
            ("avcodec decoder debug: AAC channels: 2 samplerate: 48000", 'vlc_audio'),
            ("stream_out_transcode debug: source fps 30/1", 'vlc_video'),
            ("nothing a vlc parser recognises", None),
            # can_parse's decoder guard is 'decoder' in lower and
            # ('channels:' in lower or 'samplerate:' in lower or 'x' in line
            # or 'fps' in lower) -- 'x' in line matches an x ANYWHERE, so a
            # decoder line with no audio marker and any x in it falls to the
            # else and returns 'vlc_video'. Written down because it is
            # exactly the kind of accident a Go port only reproduces if
            # someone recorded it.
            ("avcodec decoder debug: using max resolution 1920x1080", 'vlc_video'),
        ]
        for line, expected in cases:
            with self.subTest(line=line):
                self.assertEqual(parser.can_parse(line), expected)


class VLCParseVideoStreamTests(SimpleTestCase):
    def test_the_ts_demux_codec_map(self):
        """One row of video_codec_map per assertion, dict compared whole.

        The map is four tuples of aliases against four codec names; a Go port
        gets this wrong by transcribing three of the four, which a
        'video_codec' in result assertion would not catch.
        """
        parser = VLCLogParser()
        for line, expected in [
            ("ts demux debug: pid 256 type=0x1b", {"video_codec": "h264"}),
            ("ts demux debug: pid 256 hevc", {"video_codec": "hevc"}),
            ("ts demux debug: pid 256 type=0x02", {"video_codec": "mpeg2video"}),
            ("ts demux debug: pid 256 mpeg-4", {"video_codec": "mpeg4"}),
        ]:
            with self.subTest(line=line):
                self.assertEqual(parser.parse_video_stream(line), expected)

    def test_source_fps_fraction_form(self):
        parser = VLCLogParser()
        result = parser.parse_video_stream(
            "stream_out_transcode debug: source fps 30000/1001"
        )
        self.assertEqual(result["source_fps"], 30000 / 1001)

    def test_source_fps_fraction_with_zero_denominator_is_absent_not_zero(self):
        # The guard is `if denominator > 0` -- absence is what distinguishes
        # this from a division that happened to yield 0.
        parser = VLCLogParser()
        result = parser.parse_video_stream("stream_out_transcode debug: source fps 30/0")
        self.assertIsNone(result)

    def test_source_wxh_form(self):
        parser = VLCLogParser()
        result = parser.parse_video_stream("stream_out_transcode debug: source 1280x720")
        self.assertEqual(
            result,
            {"resolution": "1280x720", "width": 1280, "height": 720},
        )

    def test_source_wxh_bounds(self):
        parser = VLCLogParser()
        # \d{3,4} means a 5-digit number cannot match at all, so the upper
        # bound (<= 10000) is only reachable at exactly 9999.
        result = parser.parse_video_stream("stream_out_transcode debug: source 9999x9999")
        self.assertEqual(result["resolution"], "9999x9999")

        result = parser.parse_video_stream("stream_out_transcode debug: source 0099x0099")
        self.assertIsNone(result)

    def test_generic_resolution_fallback_only_when_source_form_absent(self):
        # NOT prefixed "avcodec" -- that substring's "avc" spuriously matches
        # the video_codec_map's first tuple ('avc', 'h.264', 'type=0x1b'),
        # which would add a video_codec key neither of these two cases
        # expects. Verified against the real module before writing this.
        parser = VLCLogParser()
        result = parser.parse_video_stream("decoder debug: 1920x1080 yuv420p")
        self.assertEqual(
            result,
            {"resolution": "1920x1080", "width": 1920, "height": 1080},
        )

        result = parser.parse_video_stream("decoder debug: 099x099")
        self.assertIsNone(result)

    def test_generic_fps_fallback_and_precedence_over_source_fps(self):
        parser = VLCLogParser()
        result = parser.parse_video_stream("decoder debug: 29.97 fps")
        self.assertEqual(result, {"source_fps": 29.97})

        # The branch a port gets wrong: a line carrying both forms must keep
        # the 'source fps N/D' value, not fall through to the generic fps
        # fallback.
        result = parser.parse_video_stream(
            "stream_out_transcode debug: source fps 30/1 at 25 fps"
        )
        self.assertEqual(result["source_fps"], 30.0)

    def test_empty_result_exit(self):
        parser = VLCLogParser()
        result = parser.parse_video_stream("ts demux debug: pid 256 type=0x99")
        self.assertIsNone(result)


class VLCParseAudioStreamTests(SimpleTestCase):
    def test_the_ts_demux_codec_map(self):
        parser = VLCLogParser()
        for line, expected in [
            ("ts demux debug: pid 256 type=0xf", {"audio_codec": "aac"}),
            ("ts demux debug: pid 256 adts", {"audio_codec": "aac"}),
            ("ts demux debug: pid 256 type=0x03", {"audio_codec": "mp3"}),
            ("ts demux debug: pid 256 type=0x06", {"audio_codec": "ac3"}),
        ]:
            with self.subTest(line=line):
                self.assertEqual(parser.parse_audio_stream(line), expected)

    def test_channels_field_maps_named_counts_and_falls_back_to_the_string(self):
        parser = VLCLogParser()
        for channels, expected in [(1, 'mono'), (2, 'stereo'), (6, '5.1'), (8, '7.1')]:
            with self.subTest(channels=channels):
                result = parser.parse_audio_stream(f"decoder debug: channels: {channels}")
                self.assertEqual(result["audio_channels"], expected)
        # Unmapped count: the .get default is the STRING, not the int.
        result = parser.parse_audio_stream("decoder debug: channels: 3")
        self.assertEqual(result["audio_channels"], '3')

    def test_samplerate_field(self):
        parser = VLCLogParser()
        result = parser.parse_audio_stream("decoder debug: samplerate: 48000")
        self.assertEqual(result, {"sample_rate": 48000})

    def test_hz_form_only_when_samplerate_absent(self):
        parser = VLCLogParser()
        result = parser.parse_audio_stream("decoder debug: 44100 hz")
        self.assertEqual(result["sample_rate"], 44100)

        # Precedence: samplerate: wins over a co-occurring Hz form.
        result = parser.parse_audio_stream(
            "decoder debug: samplerate: 48000 at 44100 hz"
        )
        self.assertEqual(result["sample_rate"], 48000)

    def test_word_format_channel_fallback_and_precedence(self):
        parser = VLCLogParser()
        result = parser.parse_audio_stream("decoder debug: mono audio")
        self.assertEqual(result["audio_channels"], 'mono')

        # Precedence: an explicit channels: count wins over a co-occurring
        # word form.
        result = parser.parse_audio_stream("decoder debug: channels: 2 mono")
        self.assertEqual(result["audio_channels"], 'stereo')

    def test_empty_result_exit(self):
        parser = VLCLogParser()
        result = parser.parse_audio_stream("decoder debug: nothing recognisable here")
        self.assertIsNone(result)


class StreamlinkParserTests(SimpleTestCase):
    def test_can_parse(self):
        parser = StreamlinkLogParser()
        self.assertEqual(
            parser.can_parse("[cli][info] Opening stream: 720p (hls)"), 'streamlink'
        )
        self.assertEqual(
            parser.can_parse("[cli][info] Available streams: 480p, 720p"), 'streamlink'
        )
        self.assertIsNone(parser.can_parse("[cli][info] Found matching plugin"))

    def test_parse_video_stream_named_qualities(self):
        parser = StreamlinkLogParser()
        table = [
            ('2160p', "3840x2160", 3840, 2160),
            ('1080p', "1920x1080", 1920, 1080),
            ('720p', "1280x720", 1280, 720),
            ('480p', "854x480", 854, 480),
            ('360p', "640x360", 640, 360),
        ]
        for quality, resolution, width, height in table:
            with self.subTest(quality=quality):
                result = parser.parse_video_stream(
                    f"[cli][info] Opening stream: {quality} (hls)"
                )
                self.assertEqual(
                    result,
                    {"video_codec": "h264", "resolution": resolution,
                     "width": width, "height": height, "pixel_format": "yuv420p"},
                )

    def test_parse_video_stream_wxh_form(self):
        parser = StreamlinkLogParser()
        result = parser.parse_video_stream("[cli][info] Opening stream: 1600x900")
        self.assertEqual(
            result,
            {"video_codec": "h264", "resolution": "1600x900",
             "width": 1600, "height": 900, "pixel_format": "yuv420p"},
        )

    def test_parse_video_stream_unmapped_quality_falls_back_to_1080p(self):
        # A surprising default -- exactly why it needs a literal pin.
        parser = StreamlinkLogParser()
        result = parser.parse_video_stream("[cli][info] Opening stream: 144p")
        self.assertEqual(
            result,
            {"video_codec": "h264", "resolution": "1920x1080",
             "width": 1920, "height": 1080, "pixel_format": "yuv420p"},
        )

    def test_parse_video_stream_no_match(self):
        parser = StreamlinkLogParser()
        self.assertIsNone(
            parser.parse_video_stream("[cli][info] Found matching plugin")
        )

    def test_parse_input_format_and_parse_audio_stream_are_unconditionally_none(self):
        parser = StreamlinkLogParser()
        self.assertIsNone(parser.parse_input_format("anything"))
        self.assertIsNone(parser.parse_audio_stream("anything"))


class LogParserFactoryTests(SimpleTestCase):
    def test_get_parser_and_method_no_match(self):
        self.assertIsNone(LogParserFactory.parse("not_a_stream_type", "x"))

    def test_parse_dispatches_vlc_and_streamlink(self):
        self.assertEqual(
            LogParserFactory.parse("vlc_video", "ts demux debug: pid 256 type=0x1b"),
            {"video_codec": "h264"},
        )
        self.assertEqual(
            LogParserFactory.parse(
                "streamlink", "[cli][info] Opening stream: 720p (hls)"
            ),
            {"video_codec": "h264", "resolution": "1280x720",
             "width": 1280, "height": 720, "pixel_format": "yuv420p"},
        )

    def test_auto_parse_dispatches_finds_nothing_and_the_claimed_but_empty_case(self):
        self.assertEqual(
            LogParserFactory.auto_parse(
                "ts demux debug: pid 256 type=0x1b video"
            ),
            ('vlc_video', {"video_codec": "h264"}),
        )
        self.assertIsNone(
            LogParserFactory.auto_parse("nothing any parser recognises")
        )
        # The branch a port misses: a line a parser CLAIMS but parses to
        # nothing must return None, not a tuple with an empty dict. This line
        # is claimed as 'vlc_video' by can_parse (ts demux debug + type= +
        # video) but parse_video_stream finds no codec/fps/resolution match
        # for it.
        self.assertIsNone(
            LogParserFactory.auto_parse("ts demux debug: pid 256 type=0x99 video")
        )
