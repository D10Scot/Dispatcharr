"""Tests for stream switch confirmation and metadata persistence."""

import json
from unittest.mock import MagicMock, patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import User
from apps.proxy import relay_client
from apps.proxy.live_proxy import views as views_module
from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.services import channel_service as cs_module
from apps.proxy.live_proxy.services.channel_service import ChannelService
from apps.proxy.live_proxy.views import change_stream


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


class OwnerPathTests(TestCase):
    def _run(self, manager_url="http://provider.example/stream/296622.ts"):
        redis = FakeRedis()
        proxy = make_proxy_server(redis, owner=True)

        manager = MagicMock()
        manager.url = manager_url
        manager.update_url.return_value = True
        proxy.stream_managers[CHANNEL_ID] = manager

        with patch.object(cs_module.ProxyServer, "get_instance", return_value=proxy), \
             patch("django.db.close_old_connections"):
            result = ChannelService.change_stream_url(
                CHANNEL_ID, NEW_URL, "test-agent",
                target_stream_id=144065, m3u_profile_id=7,
                stream_name="Alt Feed",
            )
        return result, redis, manager

    def test_owner_switch_persists_stream_id_metadata(self):
        result, redis, manager = self._run()

        manager.update_url.assert_called_once_with(NEW_URL, 144065, 7)
        self.assertTrue(result["success"])
        self.assertTrue(result["direct_update"])

        metadata = redis.hashes[RedisKeys.channel_metadata(CHANNEL_ID)]
        self.assertEqual(metadata[ChannelMetadataField.URL], NEW_URL)
        self.assertEqual(metadata[ChannelMetadataField.STREAM_ID], "144065")
        self.assertEqual(metadata[ChannelMetadataField.M3U_PROFILE], "7")
        self.assertEqual(metadata[ChannelMetadataField.STREAM_NAME], "Alt Feed")

    def test_owner_same_url_is_success_and_repairs_metadata(self):
        result, redis, manager = self._run(manager_url=NEW_URL)

        manager.update_url.assert_not_called()
        self.assertTrue(result["success"])

        metadata = redis.hashes[RedisKeys.channel_metadata(CHANNEL_ID)]
        self.assertEqual(metadata[ChannelMetadataField.STREAM_ID], "144065")

    def test_owner_switch_persists_channel_name_and_m3u_profile_name(self):
        """PIN. Phase 2 PR 2b-1, review hop 9. Every other test in this class
        calls change_stream_url with stream_name alone -- channel_name and
        m3u_profile_name default to None, so nothing here could tell a
        threaded value from a dropped one. This one supplies real, distinct
        values for both."""
        redis = FakeRedis()
        proxy = make_proxy_server(redis, owner=True)

        manager = MagicMock()
        manager.url = "http://provider.example/stream/296622.ts"
        manager.update_url.return_value = True
        proxy.stream_managers[CHANNEL_ID] = manager

        with patch.object(cs_module.ProxyServer, "get_instance", return_value=proxy), \
             patch("django.db.close_old_connections"):
            ChannelService.change_stream_url(
                CHANNEL_ID, NEW_URL, "test-agent",
                target_stream_id=144065, m3u_profile_id=7,
                stream_name="Alt Feed",
                channel_name="Real Hop 9 Channel Name",
                m3u_profile_name="Real Hop 9 Profile Name",
            )

        metadata = redis.hashes[RedisKeys.channel_metadata(CHANNEL_ID)]
        self.assertEqual(
            metadata[ChannelMetadataField.CHANNEL_NAME], "Real Hop 9 Channel Name"
        )
        self.assertEqual(
            metadata[ChannelMetadataField.M3U_PROFILE_NAME], "Real Hop 9 Profile Name"
        )


class NonOwnerPathTests(TestCase):
    def _run(self, owner_outcome):
        redis = FakeRedis()
        proxy = make_proxy_server(redis, owner=False)
        status_key = RedisKeys.switch_status(CHANNEL_ID)

        if owner_outcome is not None:
            original_publish = redis.publish

            def publish_and_confirm(channel, message):
                original_publish(channel, message)
                redis.store[status_key] = owner_outcome

            redis.publish = publish_and_confirm

        with patch.object(cs_module.ProxyServer, "get_instance", return_value=proxy), \
             patch.object(cs_module, "STREAM_SWITCH_CONFIRM_TIMEOUT", 0.3), \
             patch.object(cs_module, "STREAM_SWITCH_POLL_INTERVAL", 0.05):
            result = ChannelService.change_stream_url(
                CHANNEL_ID, NEW_URL, "test-agent",
                target_stream_id=144065, m3u_profile_id=7,
                stream_name="Alt Feed",
            )
        return result, redis

    def test_pubsub_event_carries_stream_id(self):
        result, redis = self._run(owner_outcome="switched")

        self.assertEqual(len(redis.published), 1)
        payload = json.loads(redis.published[0][1])
        self.assertEqual(payload["stream_id"], 144065)
        self.assertEqual(payload["m3u_profile_id"], 7)
        self.assertEqual(payload["stream_name"], "Alt Feed")
        self.assertEqual(payload["url"], NEW_URL)

    def test_pubsub_event_carries_channel_name_and_m3u_profile_name(self):
        """PIN. pr-review bot finding, verified and confirmed blocking: the
        follower branch of change_stream_url published stream_name alone --
        _publish_stream_switch_event had no parameters for channel_name/
        m3u_profile_name at all, so an operator-initiated change_stream or
        next_stream issued against a follower worker reached the owner with
        both names unset. The owner's event handler then called
        _update_channel_metadata with them None, leaving the pre-switch
        m3u_profile_name in the hash -- the same stale-name shape fixed for
        the automatic-failover path at input/manager.py:2162, reintroduced
        here, and worse than before this PR because the ORM fallback that
        used to paper over it (channel_service.py:343) is gone. Every other
        test in this class calls change_stream_url with stream_name alone,
        so none of them could catch a dropped channel_name/m3u_profile_name;
        this one supplies real, distinct values for both."""
        redis = FakeRedis()
        proxy = make_proxy_server(redis, owner=False)
        status_key = RedisKeys.switch_status(CHANNEL_ID)

        original_publish = redis.publish

        def publish_and_confirm(channel, message):
            original_publish(channel, message)
            redis.store[status_key] = "switched"

        redis.publish = publish_and_confirm

        with patch.object(cs_module.ProxyServer, "get_instance", return_value=proxy), \
             patch.object(cs_module, "STREAM_SWITCH_CONFIRM_TIMEOUT", 0.3), \
             patch.object(cs_module, "STREAM_SWITCH_POLL_INTERVAL", 0.05):
            ChannelService.change_stream_url(
                CHANNEL_ID, NEW_URL, "test-agent",
                target_stream_id=144065, m3u_profile_id=7,
                stream_name="Alt Feed",
                channel_name="Real Follower Channel Name",
                m3u_profile_name="Real Follower Profile Name",
            )

        self.assertEqual(len(redis.published), 1)
        payload = json.loads(redis.published[0][1])
        self.assertEqual(payload["channel_name"], "Real Follower Channel Name")
        self.assertEqual(payload["m3u_profile_name"], "Real Follower Profile Name")

    def test_switch_confirmed_by_owner_reports_success(self):
        result, _ = self._run(owner_outcome="switched")

        self.assertTrue(result["success"])
        self.assertFalse(result["direct_update"])
        self.assertTrue(result["event_published"])

    def test_switch_failed_by_owner_reports_failure(self):
        result, _ = self._run(owner_outcome="failed")

        self.assertFalse(result["success"])
        self.assertIn("failed", result["message"].lower())

    def test_no_confirmation_times_out_and_reports_failure(self):
        result, _ = self._run(owner_outcome=None)

        self.assertFalse(result["success"])
        self.assertIs(result["confirmed"], False)
        self.assertIn("not confirmed", result["message"])

    def test_stale_status_key_is_cleared_before_publishing(self):
        redis = FakeRedis()
        proxy = make_proxy_server(redis, owner=False)
        status_key = RedisKeys.switch_status(CHANNEL_ID)
        redis.store[status_key] = "switched"

        deleted_before_publish = []
        original_publish = redis.publish

        def tracking_publish(channel, message):
            deleted_before_publish.append(status_key not in redis.store)
            original_publish(channel, message)

        redis.publish = tracking_publish

        with patch.object(cs_module.ProxyServer, "get_instance", return_value=proxy), \
             patch.object(cs_module, "STREAM_SWITCH_CONFIRM_TIMEOUT", 0.2), \
             patch.object(cs_module, "STREAM_SWITCH_POLL_INTERVAL", 0.05):
            result = ChannelService.change_stream_url(
                CHANNEL_ID, NEW_URL, "test-agent", target_stream_id=144065,
            )

        self.assertEqual(deleted_before_publish, [True])
        self.assertFalse(result["success"])


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
        proxy = make_proxy_server(FakeRedis(), owner=True)

        with patch.object(views_module.ProxyServer, "get_instance", return_value=proxy):
            response = change_stream(self._post({"stream_id": "abc"}), CHANNEL_ID)

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content)
        self.assertIn("error", payload)
        # No exception text echoed back to the client.
        self.assertNotIn("abc", payload["error"])
        self.assertNotIn("invalid literal", payload["error"])

    def test_stream_id_is_coerced_to_int_before_reaching_the_service(self):
        proxy = make_proxy_server(FakeRedis(), owner=True)
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

        with patch.object(views_module.ProxyServer, "get_instance", return_value=proxy), \
             patch("apps.proxy.next_source.resolve_source",
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
