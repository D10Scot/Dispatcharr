"""Property-based tests for StreamManager._parse_ffmpeg_stats.

The FFmpeg buffering detector consumes provider-controlled stderr lines and
drives a state transition (active <-> buffering) plus a failover trigger on a
sustained timeout. The promised invariants, from the code:

* never raises on any stats line, whatever junk ffmpeg (or a proxy standing
  in for it) emits;
* a reported speed at or above the configured buffering threshold never sets
  the buffering flag, and clears it if set;
* a reported speed strictly below the threshold sets the buffering flag and
  starts the buffering clock, but does not fail over until the timeout has
  elapsed;
* an unparseable / speed-less line never changes the buffering state.

The manager is built without __init__ and given only the attributes the parse
path reads; ConfigHelper thresholds are patched so no DB is reached. Runs
under SimpleTestCase.
"""

import time
from unittest import mock

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.proxy.live_proxy.input.manager import StreamManager

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

THRESHOLD = 1.0  # the buffering_speed we patch in


def make_manager():
    """A bare StreamManager with just the attributes _parse_ffmpeg_stats touches."""
    mgr = StreamManager.__new__(StreamManager)
    mgr.channel_id = "ch"
    mgr.channel_name = "ch"
    mgr.buffering = False
    mgr.buffering_start_time = None
    mgr.buffering_timeout = 10**9  # never fires within a test
    mgr.buffering_speed = THRESHOLD
    mgr.current_stream_id = None  # skip the DB-EMA branch
    mgr._bitrate_warmup_samples = 0
    mgr._smoothed_output_bitrate = None
    mgr._last_bitrate_db_save_time = 0
    mgr._bitrate_db_save_interval = 30
    # A buffer whose redis_client is None -> the hset calls are skipped.
    mgr.buffer = mock.Mock()
    mgr.buffer.redis_client = None
    return mgr


# A free-form stats line: arbitrary text plus ffmpeg-flavoured tokens.
stats_lines = st.text(max_size=200) | st.text(
    alphabet="0123456789.abcdefgmkbits/pfq= :\x00x-_", max_size=200
)


class ParseFfmpegStatsRobustness(SimpleTestCase):
    @given(line=stats_lines)
    def test_never_raises_on_any_line(self, line):
        mgr = make_manager()
        mgr._parse_ffmpeg_stats(line)  # must not raise

    @given(line=stats_lines, noise=st.lists(stats_lines, max_size=8))
    def test_garbage_never_changes_buffering_state(self, line, noise):
        """Lines with no speed token leave the buffering flag untouched."""
        mgr = make_manager()
        # Assume: if the line has no parseable speed, state is unchanged.
        import re

        has_speed = re.search(r"speed=\s*([0-9.]+)x?", line) is not None
        for junk in noise:
            mgr._parse_ffmpeg_stats(junk)
        before = mgr.buffering
        mgr._parse_ffmpeg_stats(line)
        if not has_speed:
            self.assertEqual(mgr.buffering, before)


class ParseFfmpegStatsSpeedThreshold(SimpleTestCase):
    def _line(self, speed):
        return (
            "frame= 100 fps= 25 q=28.0 size= 2048kB time=00:00:04.00 "
            f"bitrate= 406.1kbits/s speed={speed}x"
        )

    @given(speed=st.floats(min_value=THRESHOLD, max_value=100, allow_nan=False))
    def test_speed_at_or_above_threshold_never_sets_buffering(self, speed):
        mgr = make_manager()
        mgr._parse_ffmpeg_stats(self._line(speed))
        self.assertFalse(mgr.buffering)

    @given(speed=st.floats(min_value=THRESHOLD, max_value=100, allow_nan=False))
    def test_speed_at_or_above_threshold_clears_buffering(self, speed):
        mgr = make_manager()
        mgr.buffering = True
        mgr.buffering_start_time = time.time()
        mgr._parse_ffmpeg_stats(self._line(speed))
        self.assertFalse(mgr.buffering)
        self.assertIsNone(mgr.buffering_start_time)

    @given(
        speed=st.floats(
            min_value=0.01, max_value=THRESHOLD - 0.001, allow_nan=False
        ).filter(lambda s: s > 0)
    )
    def test_speed_below_threshold_sets_buffering(self, speed):
        mgr = make_manager()
        mgr._parse_ffmpeg_stats(self._line(speed))
        self.assertTrue(mgr.buffering)
        self.assertIsNotNone(mgr.buffering_start_time)

    @given(speed=st.floats(min_value=0.01, max_value=0.5, allow_nan=False))
    def test_no_failover_before_timeout(self, speed):
        """A slow speed within the timeout window never triggers _try_next_stream."""
        mgr = make_manager()
        mgr.buffering_timeout = 10**9  # far future
        with mock.patch.object(
            StreamManager, "_try_next_stream", return_value=False
        ) as mock_switch:
            mgr._parse_ffmpeg_stats(self._line(speed))
        mock_switch.assert_not_called()
