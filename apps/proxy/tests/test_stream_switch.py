"""Tests for stream switch confirmation and metadata persistence."""

import json
from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import User
from apps.proxy import relay_client
from apps.proxy.ts_admin_views import change_stream


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.hashes = {}
        self.published = []

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = str(value)

    def setex(self, key, ttl, value):
        self.store[key] = str(value)

    def delete(self, *keys):
        count = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                count += 1
            if self.hashes.pop(key, None) is not None:
                count += 1
        return count

    def keys(self, pattern):
        return []

    def exists(self, key):
        return key in self.store or key in self.hashes

    def type(self, key):
        return "hash" if key in self.hashes else "none"

    def hset(self, key, field=None, value=None, mapping=None):
        hash_value = self.hashes.setdefault(key, {})
        if field is not None and value is not None:
            hash_value[str(field)] = str(value)
        for f, v in (mapping or {}).items():
            hash_value[str(f)] = str(v)

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def publish(self, channel, message):
        self.published.append((channel, message))


CHANNEL_ID = "ad8b11c0-4cd2-4bf5-a95b-153aee7f0671"
NEW_URL = "http://provider.example/stream/144065.ts"


def make_proxy_server(redis, owner):
    proxy = MagicMock()
    proxy.redis_client = redis
    proxy.worker_id = "worker-under-test"
    proxy.check_if_channel_exists.return_value = True
    proxy.am_i_owner.return_value = owner
    proxy.stream_managers = {}
    proxy.stream_buffers = {}
    return proxy






class ChangeStreamViewTests(TestCase):
    """Fix wave B, final-review Blocking finding: the Stats card's Select
    yields a string stream_id, and change_stream used to pass it straight
    through to update_url/tried_stream_ids. Mixed with the int ids Django
    hands back, that crashes the next automatic failover's sorted(exclude)
    call and tears the whole channel down. The view must coerce at the
    boundary: reject a non-integer with 400, and hand the service an int."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create(
            username="change-stream-admin",
            user_level=User.UserLevel.ADMIN,
        )

    def setUp(self):
        self.factory = APIRequestFactory()

    def _post(self, payload):
        request = self.factory.post(
            f"/proxy/ts/change_stream/{CHANNEL_ID}",
            data=json.dumps(payload),
            content_type="application/json",
        )
        force_authenticate(request, user=self.admin)
        return request

    def test_a_non_integer_stream_id_is_rejected_with_400(self):
        # No ProxyServer patch: stage 2d-2 moved change_stream into
        # ts_admin_views, whose ProxyServer import was function-local, and
        # stage 2d-4 removed it outright (worker_id is computed locally now).
        # The patch that stood here already reached a module the view under
        # test did not touch.
        response = change_stream(self._post({"stream_id": "abc"}), CHANNEL_ID)

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content)
        self.assertIn("error", payload)
        # No exception text echoed back to the client.
        self.assertNotIn("abc", payload["error"])
        self.assertNotIn("invalid literal", payload["error"])

    def test_stream_id_is_coerced_to_int_before_reaching_the_service(self):
        resolved_answer = {
            "source": {
                "url": NEW_URL,
                "user_agent": "test-agent",
                "m3u_profile_id": 7,
                "stream_name": "Alt Feed",
            },
            "alternates": [],
            "error": None,
        }

        with patch("apps.proxy.next_source.resolve_source",
                   return_value=resolved_answer) as resolve_source_mock, \
             patch.object(
                 relay_client, "advance",
                 return_value={"status": "success", "success": True, "direct_update": True},
             ) as advance_mock:
            response = change_stream(self._post({"stream_id": "12"}), CHANNEL_ID)

        self.assertEqual(response.status_code, 200)
        resolve_source_mock.assert_called_once_with(
            CHANNEL_ID, target_stream_id=12, reason="operator"
        )
        advance_mock.assert_called_once()
        _args, kwargs = advance_mock.call_args
        self.assertEqual(kwargs["stream_id"], 12)
        self.assertIsInstance(kwargs["stream_id"], int)

        payload = json.loads(response.content)
        self.assertEqual(payload["stream_id"], 12)
