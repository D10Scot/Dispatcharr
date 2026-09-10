"""Matrix row 12 / issue #222: the fMP4 generator drops a stalled client, and the
TS generator does not.

THIS TEST PINS A DEFECT. It asserts the behaviour that is WRONG, deliberately,
because spec D5 holds the Go relay to strict parity including known defects: 2c-6
must reproduce this drop, so 2a must be able to tell whether it did. Do not "fix"
this test by making the fMP4 client survive; fixing #222 means changing
output/fmp4/generator.py:339-346 AND this test AND the matrix row together.

What the two generators actually do, which is broader than row 12's original
wording (see the 2a-6 plan's F8): the TS generator returns True only when the
stream manager is unhealthy (output/ts/generator.py:584) and, before it can get
there, sends keepalive packets that refresh last_yield_time and stop _is_timeout()
firing at all -- its own comment at :311-312 says so, capped by
MAX_KEEPALIVE_DURATION (300s). The fMP4 generator has no health check, no
url_switching exemption and no keepalive: elapsed time alone disconnects it.
"""

import shutil
import tempfile
from unittest.mock import patch

from apps.proxy.config import TSConfig

from .harness.asset import TS_PACKET_SIZE
from .harness.relay import RelayHarnessTestCase, wait_until
from .output_support import (
    fragmentable_upstream_payload,
    real_ffmpeg_environment,
    standin_stream_profile,
    tapped,
    wait_for_bytes,
)


class FMP4ClientTimeoutTests(RelayHarnessTestCase):
    # Compressed from 20 + 20 = 40s. Both are plain TSConfig class attributes read
    # through ConfigHelper.get (config_helper.py:30, :104), so patching them is the
    # production lever. 1 + 1 = 2s is short enough that the health monitor has not
    # yet flipped the channel unhealthy (CONNECTION_TIMEOUT is 10s and is NOT
    # compressed here, on purpose: an unhealthy channel would start the TS
    # keepalives and blur which of the two mechanisms held the TS client open).
    TIMEOUT = 1
    GRACE = 1

    def setUp(self):
        super().setUp()
        self.enterContext(real_ffmpeg_environment())
        self.upstream.payload = fragmentable_upstream_payload()
        self.upstream.rate = 2.0
        self.enterContext(patch.object(TSConfig, "BUFFER_CHUNK_SIZE", TS_PACKET_SIZE * 200))
        self.enterContext(patch.object(TSConfig, "STREAM_TIMEOUT", self.TIMEOUT))
        self.enterContext(patch.object(TSConfig, "FAILOVER_GRACE_PERIOD", self.GRACE))

    def test_a_stalled_fmp4_client_is_dropped_while_a_ts_client_is_not(self):
        directory = tempfile.mkdtemp(prefix="dispatcharr-2a6-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        # 2.5 MB at 500 KB/s puts the stall about five seconds into the tune, which
        # leaves room for the remux to produce its init segment and at least one
        # fragment first (measured at 1.69s against a 250 KB/s feed). If the assertion
        # in the middle of this test fires, RAISE this number rather than the deadlines.
        profile = standin_stream_profile(
            directory, name="fmp4-input", extra="--dead-air-after-bytes 2500000"
        )
        channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)

        with tapped(self, channel) as ts_client:
            wait_for_bytes(self, ts_client, 20 * TS_PACKET_SIZE, what="TS bytes")
            with tapped(self, channel, "?output_format=fmp4") as fmp4_client:
                wait_for_bytes(self, fmp4_client, 40_000, timeout=14.0, what="fMP4 bytes")
                self.assertIsNone(
                    fmp4_client.ended_at,
                    "the fMP4 stream ended before the source went quiet -- the stall "
                    "arrived too early; raise --dead-air-after-bytes",
                )

                with self.assertLogs("live_proxy.generator", level="WARNING") as captured:
                    # The source goes quiet: no new fragment reaches either client.
                    wait_until(
                        lambda: fmp4_client.quiet_for() > 1.0,
                        timeout=20.0,
                        what="the fMP4 stream to go quiet",
                    )
                    quiet_since = fmp4_client.last_byte_at

                    # THE DEFECT: elapsed time alone ends the fMP4 response.
                    wait_until(
                        lambda: fmp4_client.ended_at is not None,
                        timeout=self.TIMEOUT + self.GRACE + 5.0,
                        what="the fMP4 client to be disconnected by _is_timeout()",
                    )

                # get_logger() derives its name from the module file, so BOTH
                # generators log under live_proxy.generator -- the message text is
                # what separates them (output/fmp4/generator.py:342-344). This
                # assertion is attribution; the pin is the EOF above it.
                self.assertTrue(
                    any("fMP4 no data for" in line for line in captured.output),
                    "no `fMP4 no data for …s, disconnecting` record: the stream ended "
                    f"for some other reason. Captured: {captured.output}",
                )

                # NOT THE PIN, and a lower bound only. A wall-clock assertion can
                # never be a pin here (see the plan's Global Constraints): this one
                # exists solely to catch a FALSE POSITIVE -- a teardown that ended
                # the response before _is_timeout() could have. It fails in one
                # direction and is silent in the other, which is the only shape a
                # clock is allowed to take in this PR. The pin is the two
                # assertions around it: the fMP4 response ended and the TS response
                # did not.
                self.assertGreaterEqual(
                    fmp4_client.ended_at - quiet_since,
                    self.TIMEOUT + self.GRACE,
                    "the fMP4 client was dropped sooner than "
                    "stream_timeout + failover_grace_period, so this is not _is_timeout()",
                )

                # AND THE CONTRAST, which is the whole content of row 12: the TS
                # client on the same channel, silent for at least as long, is still
                # connected.
                self.assertIsNone(
                    ts_client.ended_at,
                    "the TS client was dropped too -- there is no divergence to pin, "
                    "and either the health monitor fired or a teardown ended both",
                )

                # Stop the channel HERE, before the taps close, not after both `with`
                # blocks exit: output_support.tapped()'s docstring names the cost --
                # response.close() on a partially-consumed streamed response blocks
                # until the SERVER ends it, which for the still-open TS response would
                # otherwise mean paying its own ~20s teardown for nothing this test
                # asserts. Every assertion above has already run, so stopping the
                # channel here changes no window the pin depends on: it only makes the
                # server end both responses immediately, so the tapped() context
                # managers' own response.close() calls (right below, as this method
                # returns) are fast because there is nothing left to wait for.
                self.stop_channel(channel)
