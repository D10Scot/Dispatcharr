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
