"""stream_switch's emitted event must never carry a raw provider URL.

Task 10 review, Important finding: input/manager.py's channel_error and
stream_switch payloads truncated self.url / new_url to 100 chars but never
redacted them. For an Xtream-shaped URL the credentials sit inside the first
~60 characters of the path, so a truncated-but-unredacted URL still leaks the
password into the SystemEvent row and every Connect webhook/script fanout,
and now also crosses the relay -> Django HTTP hop as a JSON body. Fixed by
redacting first, then truncating, so the mask is never cut off.
"""
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.proxy.live_proxy.input import manager as manager_module
from apps.proxy.live_proxy.input.manager import StreamManager

CHANNEL_ID = "00000000-0000-0000-0000-000000000151"
XC_PASSWORD = "s3cretpass"
XC_URL = f"http://provider.example.com:8080/live/alice/{XC_PASSWORD}/12345.ts"


def _make_stream_manager():
    sm = StreamManager.__new__(StreamManager)
    sm.channel_id = CHANNEL_ID
    sm.channel_name = "Redaction Channel"
    sm.url = "http://provider.example.com:8080/live/alice/oldpass/1.ts"
    sm.transcode = False
    sm.socket = None
    sm.connected = True
    sm._smoothed_output_bitrate = None
    sm._last_bitrate_db_save_time = 0
    sm._bitrate_warmup_samples = 10
    sm.current_stream_id = None
    sm.tried_stream_ids = set()
    sm.buffer = object()
    return sm


class StreamSwitchEventRedactsUrlTests(SimpleTestCase):
    def test_new_url_is_redacted_before_truncation(self):
        sm = _make_stream_manager()

        with patch.object(manager_module, "emit_event") as mock_emit:
            result = sm.update_url(XC_URL, stream_id=99)

        self.assertTrue(result)
        mock_emit.assert_called_once()
        args, kwargs = mock_emit.call_args
        self.assertEqual(args[0], "stream_switch")
        self.assertIn("***", kwargs["new_url"])
        self.assertNotIn(XC_PASSWORD, kwargs["new_url"])
