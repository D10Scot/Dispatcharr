"""What the ffmpeg stderr reader decides: parity-matrix rows 1, 4, 5, 6 and 28.

Every stderr line these tests replay is a verbatim capture from ffmpeg 8.1.2
(harness/fixtures/ffmpeg_stderr/, CAPTURE.md). Nothing here writes a progress line, and
nothing here hardcodes a digit read off one: a capture is a timing measurement, so each
test derives what it needs and asserts the SHAPE it needs the capture to have, with a
message telling a future reader to re-derive.

Rows 6 and 28 are DEFECTS, reproduced and not fixed, per spec D5 (strict parity,
defects included). Their tests pin the wrong behaviour on purpose and say so.
"""

from unittest.mock import patch

from apps.proxy.config import TSConfig
from apps.proxy.live_proxy.config_helper import ConfigHelper
from apps.proxy.live_proxy.constants import ChannelState
from core.models import SystemEvent

from .harness.ffmpeg_stderr import progress_lines
from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until
from .manager_support import (
    API_MAX_BUFFERING_SPEED,
    API_MIN_BUFFERING_SPEED,
    FULL_SPEED_RE,
    SPEED_RE,
    add_alternate_stream,
    corpus_elapsed,
    corpus_speeds,
    sample_while,
    set_proxy_settings,
)

# Tasks 2 and 3 add tests to this file and import nothing further: every symbol they
# need is already here.


class FfmpegStderrFailoverTests(RelayHarnessTestCase):
    def test_a_scientific_notation_speed_is_under_reported_as_its_mantissa(self):
        """PINS A DEFECT: issue #227, parity-matrix row 28. Do not "fix" this.

        input/manager.py:1064-1065's `re.search(r'speed=\\s*([0-9.]+)x?', …)` stops at
        the `e`, so a real ffmpeg line reading `speed=1.41e+03x` -- which ffmpeg 8.1.2
        emits unprompted on a truncated input -- reaches both status surfaces as 1.41, a
        roughly 1000x under-report. D5 is strict parity, defects included: the Go relay
        must under-report the same way, so this test asserts the WRONG value.

        It would fail if someone widened the regex to read the exponent, which is
        exactly the change that must not be made without also changing the Go side and
        this row.
        """
        record = progress_lines("truncation")[0]
        mantissa = float(SPEED_RE.search(record).group(1))
        actual = float(FULL_SPEED_RE.search(record).group(1))
        self.assertGreater(
            actual / mantissa,
            100,
            "the truncation capture no longer carries a scientific-notation speed=; "
            "re-derive this test against the new capture (CAPTURE.md)",
        )

        with self.stand_in(stderr_corpus="truncation", stderr_interval=0.0):
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            with self.tuned(channel) as stream:
                snapshots = sample_while(
                    self,
                    channel,
                    until=lambda info: info.get("ffmpeg_speed") is not None,
                    drain=stream,
                )
            # Stop the channel BEFORE the stand_in context removes its temp directory.
            # The relay's main loop keeps reconnecting after the client leaves, and a
            # respawn from a deleted directory is harmless but fills the log with
            # FileNotFoundError. Every test in this PR that tunes inside a stand_in
            # block does this for the same reason.
            self.stop_channel(channel)

        reported = snapshots[-1]["ffmpeg_speed"]
        self.assertAlmostEqual(reported, round(mantissa, 3), places=3)
        self.assertLess(
            reported,
            actual / 100,
            "the relay reported the true speed; #227 appears to have been fixed, which "
            "makes this row a parity CHANGE, not a pin",
        )

    def test_a_sustained_speed_below_the_threshold_fails_the_channel_over(self):
        """Row 1: speed= below buffering_speed, sustained past buffering_timeout,
        calls _try_next_stream() (input/manager.py:1122-1191).

        The lever is buffering_speed, raised to the API's maximum, exactly as
        CLAUDE.md's failover paragraph describes it ("buffering_speed above 1.0 is the
        lever"). That is what makes this affordable: the slow-trickle capture opens
        above 10.0x and every later record is below it, so the detector arms on record
        two rather than after the ~18 seconds of real ffmpeg wall clock it takes the
        cumulative average to cross 1.0 (that delay is row 4, below).

        buffering_timeout is 1 -- an integer, which is all the API stores
        (core/serializers.py:95) -- so the failover fires only after a full second of
        sustained buffering, and the event's own `duration` field proves it did.
        """
        values = corpus_speeds("slow-trickle")
        self.assertGreater(
            values[0],
            API_MAX_BUFFERING_SPEED,
            "slow-trickle no longer opens above the API's maximum buffering_speed; "
            "re-derive this test against the new capture (CAPTURE.md)",
        )
        self.assertLess(
            max(values[1:]),
            API_MAX_BUFFERING_SPEED,
            "slow-trickle no longer stays below the API's maximum after its first "
            "record; re-derive (CAPTURE.md)",
        )
        # The below-threshold run is every record after the first, replayed at 0.02s
        # apart. It has to outlast the 1-second buffering_timeout with margin: today
        # that is 75 records = 1.5s, and the failover lands around record 53 of 76. The
        # assertion is on the DURATION, not the record count, so a re-capture with a
        # different number of records is fine as long as the run is still long enough.
        self.assertGreater(
            (len(values) - 1) * 0.02,
            1.4,
            "the below-threshold tail no longer outlasts the 1s buffering_timeout this "
            "test sets; lengthen stderr_interval or re-derive (CAPTURE.md)",
        )

        set_proxy_settings(
            self, buffering_speed=API_MAX_BUFFERING_SPEED, buffering_timeout=1
        )
        with self.stand_in(stderr_corpus="slow-trickle", stderr_interval=0.02):
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            alternate = add_alternate_stream(self, channel, self.upstream, order=1)

            with self.tuned(channel) as stream:
                sample_while(
                    self,
                    channel,
                    until=lambda info: info.get("state") == ChannelState.BUFFERING,
                    drain=stream,
                )
                sample_while(
                    self,
                    channel,
                    until=lambda info: info.get("stream_id") == alternate.id,
                    drain=stream,
                )
            self.stop_channel(channel)

        buffering = SystemEvent.objects.filter(
            channel_id=channel.uuid, event_type="channel_buffering"
        )
        self.assertTrue(buffering.exists(), "buffering never armed")

        # Wait for the row, do not assume it. _try_next_stream writes STREAM_ID to the
        # metadata hash at :2125 and RETURNS; the channel_failover emit is back up in
        # _parse_ffmpeg_stats at :1156, after that return, and carries a synchronous
        # HTTP POST plus an ORM write. So the stream_id the loop above waited for lands
        # BEFORE the event row, and a bare .latest() here can raise DoesNotExist --
        # which would read as a flaky pin rather than the ordering fact it is. (Row 2's
        # stream_switch needs no such wait: it is emitted inside update_url at :1480,
        # before the same metadata write. Row 3's channel_error needs none either: it is
        # emitted at :544-551, before the finally block writes the ERROR state that ends
        # the response body the test reads to completion.)
        wait_until(
            lambda: SystemEvent.objects.filter(
                channel_id=channel.uuid, event_type="channel_failover"
            ).exists(),
            timeout=10,
            what="the channel_failover event to reach Django",
        )
        failover = SystemEvent.objects.filter(
            channel_id=channel.uuid, event_type="channel_failover"
        ).latest("timestamp")
        self.assertEqual(failover.details.get("reason"), "buffering_timeout")
        self.assertGreater(
            failover.details.get("duration"),
            ConfigHelper.buffering_timeout(),
            "the failover fired without outlasting buffering_timeout",
        )

    def test_the_captured_cumulative_lead_must_burn_off_before_the_detector_arms(self):
        """Row 4: speed= is ffmpeg's CUMULATIVE average since process start, so a
        front-loaded lead has to burn off before the buffering detector can arm.

        Two halves, and the first is why this row exists at all. The delay is ffmpeg's
        own behaviour and is invisible in the Python: it is visible only in a real
        capture, so the first half reads it off slow-trickle's own elapsed= field --
        the wall clock a real ffmpeg took, against an upstream held to 0.25x real time,
        before its cumulative speed first touched 1.0. That is tens of seconds, which is
        why this row can never be driven by a live ffmpeg inside a test budget.

        The second half replays that same curve at the test's own cadence, at the
        DEFAULT buffering_speed of 1.0, and asserts the invariant the delay produces:
        the relay never labels the channel buffering while the speed it is reporting is
        still at or above the threshold. Sampled, not timed -- ffmpeg_speed is written
        to Redis before the state is (input/manager.py:1206-1230 then :1190), and both
        come out of one hgetall, so a snapshot cannot show a stale pairing.
        """
        values = corpus_speeds("slow-trickle")
        default_speed = ConfigHelper.buffering_speed()
        self.assertEqual(default_speed, 1.0, "proxy_settings defaults have moved")
        crossing = next(
            (i for i, value in enumerate(values) if value < default_speed), None
        )
        self.assertIsNotNone(crossing, "slow-trickle never crosses below 1.0; re-derive")
        self.assertGreater(
            crossing, 0, "slow-trickle starts below 1.0; there is no lead to burn off"
        )
        self.assertGreater(
            corpus_elapsed("slow-trickle", crossing),
            10.0,
            "the capture's own wall clock to the crossing is now under ten seconds; "
            "re-derive -- row 4's claim is that this delay is tens of seconds",
        )
        # The invariant asserted below -- speed >= threshold implies state is not
        # buffering -- is deterministic only while the capture never climbs back over
        # the threshold after crossing it. If it did, _parse_ffmpeg_stats writes the
        # recovered speed (:1206-1230) before it resets the state (:1201), and a
        # snapshot taken in that window would show a high speed with state still
        # buffering. Today's capture is monotone below 1.0 from the crossing on; assert
        # that rather than trust it, the way row 1 asserts its own straddle.
        self.assertLess(
            max(values[crossing:]),
            default_speed,
            "the capture climbs back above the threshold after crossing it; this "
            "test's invariant is no longer race-free -- re-derive (CAPTURE.md)",
        )

        with self.stand_in(stderr_corpus="slow-trickle", stderr_interval=0.02):
            profile = stand_in_stream_profile()
            channel = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            with self.tuned(channel) as stream:
                snapshots = sample_while(
                    self,
                    channel,
                    until=lambda info: info.get("state") == ChannelState.BUFFERING,
                    drain=stream,
                )
            self.stop_channel(channel)

        leading = [
            info
            for info in snapshots
            if info.get("ffmpeg_speed") is not None
            and info["ffmpeg_speed"] >= default_speed
        ]
        self.assertTrue(
            leading, "never observed the lead at all; poll faster or pace the corpus slower"
        )
        for info in leading:
            self.assertNotEqual(
                info["state"],
                ChannelState.BUFFERING,
                f"the detector armed while speed was still {info['ffmpeg_speed']}x",
            )

        # Note that this test leaves buffering_timeout at its default 15, so nothing
        # fails over -- the channel reaches buffering and stays there until the tune
        # closes.

    def test_a_buffering_threshold_change_does_not_reach_a_running_channel(self):
        """Row 5: buffering_speed and buffering_timeout are snapshotted in
        StreamManager.__init__ (input/manager.py:60-61), so a proxy_settings change
        while a channel is running does not reach it.

        The second channel is what makes this falsifiable rather than vacuous. Without
        it the test would pass just as well if the settings write had silently failed,
        or if the relay ignored buffering_speed altogether. Channel B is constructed
        AFTER the change, from the same corpus and the same stand-in, and must buffer
        immediately -- so the only difference between the two channels is when their
        StreamManager was built.
        """
        values = corpus_speeds("normal")
        self.assertGreater(
            min(values),
            API_MIN_BUFFERING_SPEED,
            "normal now dips below the API's minimum buffering_speed; re-derive",
        )
        self.assertGreater(
            values[0],
            API_MAX_BUFFERING_SPEED,
            "normal no longer opens above the API's maximum buffering_speed; re-derive",
        )
        self.assertLess(
            max(values[1:]),
            API_MAX_BUFFERING_SPEED,
            "normal no longer stays below the API's maximum after its first record; "
            "re-derive",
        )

        # Nothing in the corpus can trip 0.1, so channel A must never buffer.
        set_proxy_settings(
            self, buffering_speed=API_MIN_BUFFERING_SPEED, buffering_timeout=300
        )
        with self.stand_in(
            stderr_corpus="normal", stderr_interval=0.02, stderr_loop=True
        ):
            profile = stand_in_stream_profile()
            running = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            with self.tuned(running) as stream:
                sample_while(
                    self,
                    running,
                    until=lambda info: info.get("ffmpeg_speed") is not None,
                    drain=stream,
                )

                # Everything in the corpus now trips the threshold -- for a channel
                # built from here on.
                set_proxy_settings(self, buffering_speed=API_MAX_BUFFERING_SPEED)

                after = sample_while(self, running, chunks=24, drain=stream)

            seen = {
                info["ffmpeg_speed"]
                for info in after
                if info.get("ffmpeg_speed") is not None
            }
            self.assertGreaterEqual(
                len(seen),
                4,
                f"too few distinct speeds after the change to prove records were still "
                f"being parsed: {sorted(seen)}",
            )
            for info in after:
                self.assertNotEqual(
                    info.get("state"),
                    ChannelState.BUFFERING,
                    "the running channel picked up the new threshold",
                )
            self.assertFalse(
                SystemEvent.objects.filter(
                    channel_id=running.uuid, event_type="channel_buffering"
                ).exists()
            )

            # Same corpus, same stand-in, new StreamManager: it snapshots the NEW
            # threshold and buffers at once.
            started_after = self.make_channel(
                upstream_url=self.upstream.url, profile=profile
            )
            with self.tuned(started_after) as stream:
                sample_while(
                    self,
                    started_after,
                    until=lambda info: info.get("state") == ChannelState.BUFFERING,
                    drain=stream,
                )
            self.stop_channel(running)
            self.stop_channel(started_after)

    def test_a_buffering_failover_ignores_max_stream_switches(self):
        """PINS A DEFECT: issue #221, parity-matrix row 6. Do not "fix" this.

        MAX_STREAM_SWITCHES bounds the main loop (input/manager.py:388-402,
        `stream_switch_attempts <= max_stream_switches`). The buffering-timeout path
        calls _try_next_stream() from the stderr reader thread (:1134-1138) and never
        touches that counter, so the bound does not apply to it.

        Set the bound to zero and a buffering failover still happens. That is the whole
        row, and it is falsifiable in the direction that matters: if the stderr path
        were taught to consult the counter -- the natural fix for #221 -- a bound of
        zero would refuse this switch and this test would time out waiting for the
        event. D5 is strict parity, defects included, so the Go relay must ignore the
        bound the same way.

        channel_failover is emitted at exactly one site in the tree
        (input/manager.py:1156-1162), the buffering-timeout branch, so the event alone
        identifies which path made the switch.
        """
        values = corpus_speeds("normal")
        self.assertGreater(values[0], API_MAX_BUFFERING_SPEED, "re-derive; see row 5's test")
        self.assertLess(max(values[1:]), API_MAX_BUFFERING_SPEED, "re-derive")

        set_proxy_settings(
            self, buffering_speed=API_MAX_BUFFERING_SPEED, buffering_timeout=0
        )
        with patch.object(TSConfig, "MAX_STREAM_SWITCHES", 0):
            self.assertEqual(ConfigHelper.max_stream_switches(), 0)
            with self.stand_in(
                stderr_corpus="normal", stderr_interval=0.02, stderr_loop=True
            ):
                profile = stand_in_stream_profile()
                channel = self.make_channel(
                    upstream_url=self.upstream.url, profile=profile
                )
                alternate = add_alternate_stream(self, channel, self.upstream, order=1)

                with self.tuned(channel) as stream:
                    sample_while(
                        self,
                        channel,
                        until=lambda info: info.get("stream_id") == alternate.id,
                        drain=stream,
                    )
                self.stop_channel(channel)

        # Waited for, not assumed -- same ordering fact as row 1's test: the STREAM_ID
        # write at :2125 precedes the emit at :1156.
        wait_until(
            lambda: SystemEvent.objects.filter(
                channel_id=channel.uuid, event_type="channel_failover"
            ).exists(),
            timeout=10,
            what="the channel_failover event to reach Django",
        )
        failover = SystemEvent.objects.filter(
            channel_id=channel.uuid, event_type="channel_failover"
        ).latest("timestamp")
        self.assertEqual(failover.details.get("reason"), "buffering_timeout")
