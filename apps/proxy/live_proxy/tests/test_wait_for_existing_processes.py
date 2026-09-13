"""input/manager.py's _wait_for_existing_processes_to_close (Phase 2 PR 2b-4,
Task 9b, promoted from Task 12's reserve into the plan from the start per the
381-400 band decision).

18 statements, zero in except -- pure polling logic, no subprocess. Built via
StreamManager.__new__ to skip the constructor's subprocess/Redis machinery,
which this method never touches: it reads only self.transcode_process,
self.current_response, self.current_session, self.socket and self.channel_id.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.input.manager import StreamManager


class WaitForExistingProcessesToCloseTests(SimpleTestCase):
    def _manager(self, *, transcode_process=None, current_response=None,
                 current_session=None, socket=None):
        manager = StreamManager.__new__(StreamManager)
        manager.channel_id = "chan-uuid"
        manager.transcode_process = transcode_process
        manager.current_response = current_response
        manager.current_session = current_session
        manager.socket = socket
        return manager

    def test_everything_already_closed_returns_true_immediately(self):
        manager = self._manager()
        with patch("apps.proxy.live_proxy.input.manager.gevent.sleep") as sleep:
            result = manager._wait_for_existing_processes_to_close(timeout=5.0)
        self.assertTrue(result)
        sleep.assert_not_called()

    def test_a_running_transcode_process_is_waited_out(self):
        process = MagicMock()
        process.poll.side_effect = [None, None, 0]  # running, running, exited
        manager = self._manager(transcode_process=process)
        with patch("apps.proxy.live_proxy.input.manager.gevent.sleep") as sleep, \
             patch(
                 "apps.proxy.live_proxy.input.manager.time.time",
                 side_effect=[0.0, 0.0, 0.1, 0.2],
             ):
            result = manager._wait_for_existing_processes_to_close(timeout=5.0)
        self.assertTrue(result)
        self.assertEqual(sleep.call_count, 2)

    def test_an_open_http_response_is_waited_out(self):
        manager = self._manager()
        # current_response starts truthy, then the test clears it as if the
        # response closed between polls -- a plain object placeholder, since
        # only truthiness is read.
        holder = {"response": object()}
        manager.current_response = holder["response"]

        def poll_and_clear(*_a, **_k):
            manager.current_response = None

        with patch(
            "apps.proxy.live_proxy.input.manager.gevent.sleep",
            side_effect=poll_and_clear,
        ) as sleep, patch(
            "apps.proxy.live_proxy.input.manager.time.time",
            side_effect=[0.0, 0.0, 0.1],
        ):
            result = manager._wait_for_existing_processes_to_close(timeout=5.0)
        self.assertTrue(result)
        sleep.assert_called_once()

    def test_an_open_socket_is_waited_out(self):
        manager = self._manager()
        manager.socket = object()

        def poll_and_clear(*_a, **_k):
            manager.socket = None

        with patch(
            "apps.proxy.live_proxy.input.manager.gevent.sleep",
            side_effect=poll_and_clear,
        ) as sleep, patch(
            "apps.proxy.live_proxy.input.manager.time.time",
            side_effect=[0.0, 0.0, 0.1],
        ):
            result = manager._wait_for_existing_processes_to_close(timeout=5.0)
        self.assertTrue(result)
        sleep.assert_called_once()

    def test_a_timeout_with_something_still_open_returns_false_and_warns(self):
        process = MagicMock()
        process.poll.return_value = None  # never exits
        manager = self._manager(transcode_process=process)
        with patch("apps.proxy.live_proxy.input.manager.gevent.sleep"), patch(
            "apps.proxy.live_proxy.input.manager.time.time",
            side_effect=[0.0, 0.0, 5.1],
        ), self.assertLogs("live_proxy.manager", level="WARNING") as logs:
            result = manager._wait_for_existing_processes_to_close(timeout=5.0)
        self.assertFalse(result)
        self.assertIn("Timeout waiting for existing processes to close", logs.output[0])
