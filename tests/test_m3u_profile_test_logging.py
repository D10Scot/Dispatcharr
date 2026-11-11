"""The WebSocket `m3u_profile_test` preview must not log a pattern's error text.

In Xtream "simple" profile mode the search and replace patterns are the
provider login, so an exception raised while previewing them can quote
credentials. Drives the real `receive` path as
tests/test_websocket_consumer_filter.py does.
"""

import json
from unittest.mock import AsyncMock, patch

import regex
from asgiref.sync import async_to_sync
from django.test import SimpleTestCase

from apps.accounts.models import User
from apps.proxy import next_source
from apps.proxy.tests.test_profile_pattern_logging import NoPatternInLogs, capture
from dispatcharr import consumers
from dispatcharr.consumers import MyWebSocketConsumer
from tests.test_websocket_consumer_filter import _user

_real_sub = regex.sub


class ConsumerPreviewPatternLoggingTests(NoPatternInLogs, SimpleTestCase):
    def test_preview_error_logs_type_only(self):
        consumer = MyWebSocketConsumer()
        consumer.scope = {"user": _user(user_level=User.UserLevel.ADMIN)}
        consumer.send = AsyncMock()
        url = "http://prov.example.com/live/olduser/oldpass/1.ts"
        payload = {
            "type": "m3u_profile_test",
            "url": url,
            "search": "olduser/oldpass",
            "replace": "newuser/newpass",
        }
        err = ValueError("bad group name 'olduser/oldpass' at position 4")

        def sub(*args, **kwargs):
            # Only the preview call passes a timeout; transform_url's own
            # backreference conversion must keep working.
            if "timeout" in kwargs:
                raise err
            return _real_sub(*args, **kwargs)

        with patch("dispatcharr.consumers.regex.sub", side_effect=sub):
            with capture(consumers.logger, next_source.logger) as logs:
                async_to_sync(consumer.receive)(json.dumps(payload))

        consumer.send.assert_awaited_once()
        sent = json.loads(consumer.send.await_args.kwargs["text_data"])
        self.assertEqual(sent["data"]["search_preview"], url)
        self.assertEqual(
            sent["data"]["result"], "http://prov.example.com/live/newuser/newpass/1.ts"
        )
        self.assert_no_leak(logs)
        self.assertTrue(any("ValueError" in r.getMessage() for r in logs.records))
