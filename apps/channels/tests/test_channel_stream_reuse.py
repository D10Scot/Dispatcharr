"""Channel.get_stream()'s reuse check asks the relay, not Redis.

live:channel:<uuid>:metadata is relay-owned. channel_stream:<pk> and
stream_profile:<id> are Django-owned (PR 6) and stay a direct read --
the fallback branch below is reading Django's own key, which is why it
is still Redis here.
"""

from unittest import mock

from django.test import TestCase

from apps.channels.models import Channel
from apps.proxy import relay_client
from apps.proxy.live_proxy.redis_keys import RedisKeys


class _Redis:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key):
        return self._values.get(key)


class StreamAssignmentReuseTests(TestCase):
    def setUp(self):
        self.channel = Channel.objects.create(name="One", channel_number=1)

    def _snapshot(self, **kwargs):
        defaults = {"present": False, "active": False, "reachable": True}
        defaults.update(kwargs)
        return relay_client.ChannelSnapshot(**defaults)

    def test_a_running_channel_keeps_its_assignment(self):
        with mock.patch.object(
            relay_client, "channel_snapshot",
            return_value=self._snapshot(present=True, active=True),
        ):
            self.assertTrue(
                self.channel._stream_assignment_is_reusable(_Redis(), 7)
            )

    def test_metadata_not_written_yet_falls_back_to_the_django_owned_key(self):
        # Between get_stream() reserving and initialize_channel() starting,
        # the relay holds nothing and stream_profile:<id> is what says the
        # assignment is real.
        redis = _Redis({RedisKeys.stream_profile(7): "3"})
        with mock.patch.object(
            relay_client, "channel_snapshot", return_value=self._snapshot()
        ):
            self.assertTrue(
                self.channel._stream_assignment_is_reusable(redis, 7)
            )
        with mock.patch.object(
            relay_client, "channel_snapshot", return_value=self._snapshot()
        ):
            self.assertFalse(
                self.channel._stream_assignment_is_reusable(_Redis(), 7)
            )

    def test_metadata_present_but_inactive_is_a_stale_assignment(self):
        redis = _Redis({RedisKeys.stream_profile(7): "3"})
        with mock.patch.object(
            relay_client, "channel_snapshot",
            return_value=self._snapshot(present=True, active=False),
        ):
            self.assertFalse(
                self.channel._stream_assignment_is_reusable(redis, 7)
            )

    def test_the_relay_is_asked_once_not_twice(self):
        with mock.patch.object(
            relay_client, "channel_snapshot",
            return_value=self._snapshot(present=True, active=True),
        ) as asked:
            self.channel._stream_assignment_is_reusable(_Redis(), 7)
        self.assertEqual(asked.call_count, 1)

    def test_an_unreachable_relay_reuses_rather_than_re_reserving(self):
        # A snapshot with reachable=False reports present=False, which
        # sends this to the Django-owned fallback. Reusing cannot leak a
        # provider slot; re-reserving could.
        redis = _Redis({RedisKeys.stream_profile(7): "3"})
        with mock.patch.object(
            relay_client, "channel_snapshot",
            return_value=self._snapshot(reachable=False),
        ):
            self.assertTrue(
                self.channel._stream_assignment_is_reusable(redis, 7)
            )


class PreemptionIsGoneTests(TestCase):
    def test_the_preemption_corpse_is_deleted(self):
        # It never returned a channel: models.py imports no `time`, the
        # index key it prefers is written nowhere, and the scan fallback
        # int()s a UUID. Deleting it removes code, not a feature -- there
        # was never a feature.
        self.assertFalse(hasattr(Channel, "_pick_channel_to_preempt"))
        self.assertFalse(hasattr(Channel, "_channel_proxy_is_active"))
