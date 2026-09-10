"""What the socket decides: parity-matrix rows 2 and 3, plus the raw-HTTP Proxy path.

No corpus here: these tests are about bytes stopping, not about what ffmpeg said. The
stand-in runs SILENT (stderr_corpus=None) wherever one is needed at all, so nothing the
child writes can reach the buffering detector and confuse the trigger under test.
"""

from unittest.mock import patch

import requests

from apps.proxy.config import TSConfig
from apps.proxy.live_proxy.config_helper import ConfigHelper
from core.models import SystemEvent

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned
from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until
from .manager_support import (
    API_MAX_BUFFERING_SPEED,
    add_alternate_stream,
    proxy_stream_profile,
    read_until_end,
    sample_while,
    set_proxy_settings,
)


class ConnectionFailoverTests(RelayHarnessTestCase):
    def test_dead_air_on_a_young_connection_switches_streams(self):
        """Row 2: no data for longer than the inactivity threshold, seen on three
        consecutive health checks, switches streams
        (input/manager.py:1503-1507, :1509-1560, :414-439).

        The stand-in copies a few chunks and then stays alive producing nothing
        (--dead-air-after-bytes), which is a provider that has stopped, not one that has
        disconnected -- an EOF would take the connect-failure path instead (row 3).
        Enough bytes go through first that the buffer index is non-zero, which is what
        makes _health_inactivity_threshold return CONNECTION_TIMEOUT rather than the
        60-second channel_init_grace_period (input/manager.py:1503-1507).

        HALF OF ROW 2 IS DELIBERATELY NOT PINNED. A connection stable for >= 30 seconds
        reconnects in place before it switches; `stable_time >= 30` is a bare literal at
        input/manager.py:1536 and connection_start_time is set inside
        _establish_transcode_connection, so reaching that branch costs 30 seconds of
        wall clock in a label that runs in 7 -- or reaching into the manager, which the
        composition rule forbids. Note what would fix that: apps/proxy/config.py:119
        already defines MIN_STABLE_TIME_BEFORE_RECONNECT = 30 and NOTHING READS IT
        (CLAUDE.md lists it as dead), so wiring the literal to the constant already
        named for it would make this branch patchable like every other threshold, and
        would unlock _attempt_reconnect and _wait_for_existing_processes_to_close with
        it. That is a production change and is not this PR's to make. This test drives
        the unstable branch, which is the reachable one; the matrix row's Notes cell
        says the same.
        """
        # Three unhealthy checks at 0.05s each, after 0.3s of silence. All three are
        # plain class attributes read through getattr(Config, …) / ConfigHelper.get
        # (input/manager.py:77, :1507, :1774), which is the production read path, not
        # a seam.
        #
        # CHUNK_TIMEOUT is the one that dominates, and the reason is not obvious:
        # _process_stream_data re-checks needs_stream_switch only BETWEEN fetch_chunk
        # calls, and a fetch_chunk on a dead-air pipe blocks in select() for the whole
        # chunk_timeout (:1774, :1799). At the shipped 5s the health monitor raises the
        # flag in ~0.45s and the main loop then waits out a full select before noticing
        # -- measured at 5.47s for this one test. Dropping it to 0.2 brings the test to
        # ~1.3s and changes nothing else: chunk_timeout is re-read on every fetch_chunk
        # call, not snapshotted.
        with patch.object(TSConfig, "HEALTH_CHECK_INTERVAL", 0.05), patch.object(
            TSConfig, "CONNECTION_TIMEOUT", 0.3
        ), patch.object(TSConfig, "CHUNK_TIMEOUT", 0.2):
            with self.stand_in(
                stderr_corpus=None, dead_air_after_bytes=60 * TS_PACKET_SIZE
            ):
                profile = stand_in_stream_profile()
                channel = self.make_channel(
                    upstream_url=self.upstream.url, profile=profile
                )
                alternate = add_alternate_stream(self, channel, self.upstream, order=1)

                with self.tuned(channel) as stream:
                    served = stream.read(20 * TS_PACKET_SIZE)
                    assert_ts_aligned(served)

                    # No drain: the point of this test is that no more bytes arrive.
                    sample_while(
                        self,
                        channel,
                        until=lambda info: info.get("stream_id") == alternate.id,
                        timeout=20.0,
                    )
                self.stop_channel(channel)

        self.assertTrue(
            SystemEvent.objects.filter(
                channel_id=channel.uuid, event_type="stream_switch"
            ).exists(),
            "the stream_id moved without a stream_switch event",
        )

    def test_three_connect_failures_exhaust_the_source(self):
        """Row 3: MAX_RETRIES (3) consecutive connection failures exhaust the source
        (input/manager.py:50-52, :182-192, :533-538, apps/proxy/config.py:9-10).

        Driven on the PROXY stream profile, which is the same accounting on a cheaper
        path: _establish_http_connection hands back a pipe immediately, HTTPStreamReader
        gets the upstream's 404 and closes the write end, and fetch_chunk's EOF branch
        ends the attempt exactly as a dead child would (input/manager.py:1826-1831).
        Three attempts, the exponential backoff between them, then url_failed, the
        channel_error event, and -- with no alternate stream -- the ERROR state, which
        the client sees as an `Error:` TS packet rather than a hang
        (output/ts/generator.py:229, utils.py:96-98).

        The window-reset half of this row -- the counter resetting once a gap exceeds
        RETRY_WINDOW_SECONDS -- is already pinned by
        test_failover_retry_window.py::test_counter_resets_after_idle_period, which the
        matrix row cites alongside this test. Reproducing it here would mean compressing
        the window below the backoff so the channel could never exhaust at all, i.e.
        asserting that a loop does not terminate.

        MAX_RETRIES is patchable, and is deliberately NOT patched: the row names the
        value 3, so the test pays the 0.75s of backoff rather than change the number
        under test.
        """
        self.assertEqual(ConfigHelper.max_retries(), 3)
        self.upstream.faults.arm("not-found")

        channel = self.make_channel(
            upstream_url=self.upstream.url, profile=proxy_stream_profile()
        )
        response = requests.get(
            f"{self.live_server_url}/proxy/ts/stream/{channel.uuid}",
            stream=True,
            timeout=30,
        )
        self.assertEqual(response.status_code, 200)
        body = read_until_end(response, timeout=20.0)

        self.assertIn(b"Error:", body, "the client was not told why the tune failed")
        self.assertGreaterEqual(
            self.upstream.request_count,
            3,
            "fewer than MAX_RETRIES connection attempts reached the upstream",
        )

        error = SystemEvent.objects.filter(
            channel_id=channel.uuid, event_type="channel_error"
        ).latest("timestamp")
        self.assertEqual(error.details.get("error_type"), "connection_failed")
        self.assertEqual(error.details.get("attempts"), ConfigHelper.max_retries())

    def test_the_proxy_profile_streams_with_no_ffmpeg_and_no_stats(self):
        """The raw-HTTP Proxy path end to end -- no subprocess anywhere.

        Pins matrix row 29 (added by 2a-7), and is here for two reasons. It is the only test in stage
        2a that exercises input/http_streamer.py at all (101 statements, 0% on this
        branch), together with _establish_http_connection and _close_socket's HTTP
        branch -- roughly 143 statements of input/manager.py the spec's 2a-4 row calls
        out as needing "only a socket".

        And the negative it asserts is real, externally-visible parity: the buffering
        detector is ffmpeg-exclusive. A Proxy-profile channel has no stderr, so
        _parse_ffmpeg_stats never runs, ffmpeg_speed never appears on the status, and
        buffering_speed/buffering_timeout are silently inert -- which is exactly what
        CLAUDE.md's failover paragraph records and what nothing in the UI says. The
        threshold is set to the API maximum here so the assertion is a real negative:
        on the ffmpeg profile that same setting buffers on the second record (Task 3's
        row-6 test), and here it does nothing at all.

        The window is measured in ring-buffer chunks read, not in seconds, so it cannot
        become a fixed sleep.
        """
        set_proxy_settings(
            self, buffering_speed=API_MAX_BUFFERING_SPEED, buffering_timeout=0
        )
        channel = self.make_channel(
            upstream_url=self.upstream.url, profile=proxy_stream_profile()
        )
        with self.tuned(channel) as stream:
            served = stream.read(20 * TS_PACKET_SIZE)
            assert_ts_aligned(served)
            snapshots = sample_while(self, channel, chunks=40, drain=stream)

        self.assertTrue(snapshots)
        for info in snapshots:
            self.assertNotIn(
                "ffmpeg_speed",
                info,
                "the Proxy profile reported an ffmpeg speed; there is no ffmpeg",
            )
            self.assertNotEqual(info.get("state"), "buffering")
        self.assertFalse(
            SystemEvent.objects.filter(
                channel_id=channel.uuid, event_type="channel_buffering"
            ).exists()
        )
