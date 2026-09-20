"""Keepalive/DVR-timeout timing invariants -- CONNECTION_TIMEOUT and
KEEPALIVE_INTERVAL, off apps/proxy/config.py, not the deleted relay.

This file used to carry two more halves, seventeen tests total. Phase 2
stage 2d-4 deleted both with apps/proxy/live_proxy/:

  - stream_generator._should_send_keepalive()'s owner and non-owner worker
    paths (the owner branch reads a local StreamManager; the non-owner
    branch reads a Redis last_data timestamp through ProxyServer). Go cover:
    relay/httpapi/keepalive_test.go::TestAnUnhealthyChannelSendsKeepalivesAtTheBufferHeadAndAHealthyOneDoesNot
    (whose header comment cites output/ts/generator.py:387-405, :542-551 by
    line) and ::TestHealthyOnTheListPayloadFollowsTheHealthMonitor. There is
    no Go analogue of the non-owner branch -- there is no non-owner.
  - client_manager._do_stats_update()'s error handling and WebSocket
    dispatch, and client_manager.remove_client()'s non-blocking stats
    update. Go cover for the client-with-no-bytes case:
    relay/httpapi/keepalive_test.go::TestAClientWithNoBytesGetsAnErrorPacketWhenEverySourceFails.
    No Go analogue for the WebSocket fan-out (the Go relay posts to
    /api/relay/events instead; relay/httpapi/events_test.go) or for
    remove_client()'s non-blocking latency assertion.

Recorded in the 2d-4 plan's ruling R7 (file 6) so this is a decision rather
than an oversight.
"""
from django.test import TestCase


class KeepaliveTimingTests(TestCase):
    """Verify that keepalive threshold gives sufficient margin before DVR timeout."""

    def test_keepalive_threshold_less_than_dvr_timeout(self):
        """CONNECTION_TIMEOUT (keepalive trigger) must be < DVR read timeout (15s)."""
        from apps.proxy.config import TSConfig as Config
        connection_timeout = getattr(Config, "CONNECTION_TIMEOUT", 10)
        dvr_read_timeout = 15  # hard-coded in run_recording: timeout=(10, 15)
        self.assertLess(
            connection_timeout,
            dvr_read_timeout,
            f"CONNECTION_TIMEOUT ({connection_timeout}s) must be < DVR timeout ({dvr_read_timeout}s) "
            f"so keepalives fire before DVR times out",
        )

    def test_keepalive_interval_is_short(self):
        """KEEPALIVE_INTERVAL must be short enough to send multiple keepalives in the gap."""
        from apps.proxy.config import TSConfig as Config
        interval = getattr(Config, "KEEPALIVE_INTERVAL", 0.5)
        connection_timeout = getattr(Config, "CONNECTION_TIMEOUT", 10)
        remaining_window = 15 - connection_timeout
        self.assertGreater(
            remaining_window / interval,
            3,
            f"KEEPALIVE_INTERVAL ({interval}s) is too long: only "
            f"{remaining_window/interval:.1f} keepalives would fit in the "
            f"{remaining_window}s window before DVR timeout",
        )
