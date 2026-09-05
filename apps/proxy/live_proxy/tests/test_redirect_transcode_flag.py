"""Redirect is treated like Proxy wherever the transcode flag is derived.

Phase 1 PR 5 re-review (Task 8, commit 10d88607): the view's override forces
transcode=False for the DVR's *initial* tune only. When StreamManager's
dead-air or connect-failure trigger runs _try_next_stream
(apps/proxy/live_proxy/input/manager.py), it re-derives transcode from
get_stream_info_for_switch, which computed True for a Redirect profile —
so the first automatic failover during a recording of a Redirect-profile
channel rebuilt the locked Redirect profile's empty command/parameters and
every reconnect spawned an empty executable. Both derivation points in
apps/proxy/live_proxy/url_utils.py (generate_stream_url's channel-preview
branch, which feeds the initial tune, and get_stream_info_for_switch, which
feeds every later switch) must agree that Redirect means transcode=False,
same as Proxy.
"""

from unittest.mock import patch

from django.test import TestCase

from apps.channels.models import Channel, ChannelStream, Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.proxy.live_proxy.url_utils import (
    generate_stream_url,
    get_stream_info_for_switch,
)
from core.models import StreamProfile


class FakeRedirectRedis:
    """Just enough of a Redis client for Channel.get_stream()'s cold-assignment path."""

    def __init__(self):
        self._data = {}

    def get(self, key):
        value = self._data.get(key)
        return str(value).encode() if value is not None else None

    def set(self, key, value):
        self._data[key] = value

    def delete(self, key):
        self._data.pop(key, None)


class RedirectTranscodeFlagTests(TestCase):
    def setUp(self):
        # A locked "Redirect" profile is normally seeded by
        # core/migrations/0007_create_proxy_and_redirect_stream_profiles.py
        # (command="", parameters=""), but the shared test database this
        # worktree's tests run against does not carry that data (0 rows in
        # StreamProfile despite the migration showing applied) — built fresh
        # here instead, so this test does not depend on that state.
        self.redirect_profile = StreamProfile.objects.create(
            name="Redirect",
            command="",
            parameters="",
            locked=True,
            is_active=True,
        )
        self.account = M3UAccount.objects.create(
            name="redirect-transcode-test",
            account_type="XC",
            username="user",
            password="pass",
            max_streams=5,
        )
        self.m3u_profile = M3UAccountProfile.objects.get(
            m3u_account=self.account, is_default=True
        )
        self.stream = Stream.objects.create(
            name="Redirect Test Stream",
            url="http://example.com/live/user/pass/1.ts",
            m3u_account=self.account,
        )
        self.channel = Channel.objects.create(
            channel_number=9001,
            name="Redirect Test Channel",
            stream_profile=self.redirect_profile,
        )
        ChannelStream.objects.create(channel=self.channel, stream=self.stream, order=0)

    # Both target functions call close_old_connections() in a `finally`
    # block (pre-existing, not part of this fix) with CONN_MAX_AGE=0, which
    # closes the real connection Django's TestCase needs to keep open for
    # its own transaction/savepoint bookkeeping — the same "poisons the
    # connection for subsequent queries" trap CLAUDE.md documents for
    # eager-mode Celery signals. Patched out here so this test can exercise
    # the real ORM-backed derivation without breaking every test that runs
    # after it in the same process.
    @patch("apps.proxy.live_proxy.url_utils.close_old_connections")
    @patch("apps.channels.models.reserve_profile_slot", return_value=(True, 1, None))
    @patch("apps.channels.models.RedisClient.get_client")
    def test_initial_tune_reports_transcode_false(
        self, mock_get_client, _mock_reserve, _mock_close_old_connections
    ):
        """generate_stream_url is what the view's initial tune reads."""
        mock_get_client.return_value = FakeRedirectRedis()

        (
            stream_url,
            user_agent,
            transcode,
            profile_id,
            slot_reserved,
            error,
        ) = generate_stream_url(str(self.channel.uuid))

        self.assertIsNone(error)
        self.assertFalse(transcode)
        self.assertEqual(profile_id, self.redirect_profile.id)

    @patch("apps.proxy.live_proxy.url_utils.close_old_connections")
    @patch("core.utils.RedisClient.get_client")
    @patch("apps.channels.models.reserve_profile_slot", return_value=(True, 1, None))
    @patch("apps.channels.models.RedisClient.get_client")
    def test_switch_path_agrees_transcode_false(
        self,
        mock_get_client,
        _mock_reserve,
        mock_switch_get_client,
        _mock_close_old_connections,
    ):
        """get_stream_info_for_switch is what every later failover/switch reads."""
        mock_get_client.return_value = FakeRedirectRedis()
        mock_switch_get_client.return_value = FakeRedirectRedis()

        info = get_stream_info_for_switch(str(self.channel.uuid))

        self.assertNotIn("error", info)
        self.assertFalse(info["transcode"])
        self.assertEqual(info["stream_profile"], self.redirect_profile.id)
