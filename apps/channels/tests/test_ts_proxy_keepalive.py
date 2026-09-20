"""Tests for ts_proxy keepalive and stats-update behavior.

Covers:
  - stream_generator._should_send_keepalive() owner vs non-owner worker paths
  - stream_generator._should_send_keepalive() Redis last_data health check
  - client_manager._do_stats_update() error handling and WebSocket dispatch
  - client_manager.remove_client() non-blocking stats update
  - Keepalive/DVR-timeout timing invariants
"""
import threading
import time
from unittest.mock import MagicMock, patch

from django.test import TestCase


# ---------------------------------------------------------------------------
# _should_send_keepalive: owner worker path
# ---------------------------------------------------------------------------





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
