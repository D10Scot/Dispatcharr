"""Redirect is treated like Proxy wherever the transcode flag is derived.

Phase 1 PR 5 re-review (Task 8, commit 10d88607): the view's override forces
transcode=False for the DVR's *initial* tune only. When StreamManager's
dead-air or connect-failure trigger runs _try_next_stream
(apps/proxy/live_proxy/input/manager.py), it re-derives transcode from
get_stream_info_for_switch, which computed True for a Redirect profile —
so the first automatic failover during a recording of a Redirect-profile
channel rebuilt the locked Redirect profile's empty command/parameters and
every reconnect spawned an empty executable. Both derivation points in
apps/proxy/next_source.py (resolve_initial_source's channel-preview branch,
which feeds the initial tune, and get_stream_info_for_switch, which feeds
every later switch) must agree that Redirect means transcode=False, same
as Proxy.

Phase 1 PR 6: moved here whole from
apps/proxy/live_proxy/tests/test_redirect_transcode_flag.py when the
derivation it pins moved to apps/proxy/next_source.py. Only the import,
the patch targets and the first test's assertions (a Source dict instead
of the 6-tuple, because generate_stream_url becomes an HTTP call in Task 7
and this pin must keep testing the derivation, not the transport) changed.
"""

from unittest.mock import patch

from django.test import TestCase

from apps.channels.models import Channel, ChannelStream, Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.proxy.next_source import get_stream_info_for_switch, resolve_initial_source
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
        self.proxy_profile = StreamProfile.objects.create(
            name="Proxy", command="", parameters="", locked=True, is_active=True,
        )
        # Not locked, and not one of the two reserved names: the ordinary
        # case, which must report "transcode" however it is spelled.
        self.ffmpeg_profile = StreamProfile.objects.create(
            name="custom-remux",
            command="ffmpeg",
            parameters="-i {streamUrl} -c copy -f mpegts pipe:1",
            locked=False,
            is_active=True,
        )

    # Both target functions call close_old_connections() in a `finally`
    # block (pre-existing, not part of this fix) with CONN_MAX_AGE=0, which
    # closes the real connection Django's TestCase needs to keep open for
    # its own transaction/savepoint bookkeeping — the same "poisons the
    # connection for subsequent queries" trap CLAUDE.md documents for
    # eager-mode Celery signals. Patched out here so this test can exercise
    # the real ORM-backed derivation without breaking every test that runs
    # after it in the same process.
    @patch("apps.proxy.next_source.close_old_connections")
    @patch("apps.channels.models.reserve_profile_slot", return_value=(True, 1, None))
    @patch("apps.channels.models.RedisClient.get_client")
    def test_initial_tune_reports_transcode_false(
        self, mock_get_client, _mock_reserve, _mock_close_old_connections
    ):
        """resolve_initial_source is what the view's initial tune reads."""
        mock_get_client.return_value = FakeRedirectRedis()

        answer = resolve_initial_source(str(self.channel.uuid))

        self.assertIsNone(answer["error"])
        self.assertFalse(answer["source"]["transcode"])
        self.assertEqual(answer["source"]["stream_profile"]["id"], self.redirect_profile.id)

    @patch("apps.proxy.next_source.close_old_connections")
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

    def test_profile_kind_names_all_three_architectures(self):
        """The one derivation, over the three shapes it must separate.

        The literals are typed here, not read back from the module: a
        test comparing _profile_kind(x) against a constant the module
        also defines would pass with every name spelled wrong
        together.
        """
        from apps.proxy.next_source import _profile_kind

        self.assertEqual(_profile_kind(self.redirect_profile), "redirect")
        self.assertEqual(_profile_kind(self.proxy_profile), "proxy")
        self.assertEqual(_profile_kind(self.ffmpeg_profile), "transcode")

    def test_an_unlocked_profile_named_redirect_is_not_redirect(self):
        """is_redirect() is `locked AND name == "Redirect"`, both halves.

        A user may name their own profile "Redirect"; it is an
        ordinary transcoding profile and must not make the relay
        answer 302 to a provider URL it never validated.
        """
        from apps.proxy.next_source import _profile_kind

        impostor = StreamProfile.objects.create(
            name="Redirect", command="ffmpeg", parameters="-i {streamUrl}",
            locked=False, is_active=True,
        )
        self.assertEqual(_profile_kind(impostor), "transcode")

    @patch("apps.proxy.next_source.close_old_connections")
    @patch("apps.channels.models.reserve_profile_slot", return_value=(True, 1, None))
    @patch("apps.channels.models.RedisClient.get_client")
    def test_initial_tune_reports_kind_redirect_and_leaves_transcode_alone(
        self, mock_get_client, _mock_reserve, _mock_close_old_connections
    ):
        mock_get_client.return_value = FakeRedirectRedis()

        answer = resolve_initial_source(str(self.channel.uuid))

        self.assertIsNone(answer["error"])
        self.assertEqual(answer["source"]["stream_profile"]["kind"], "redirect")
        # transcode is unchanged by this PR. Asserted beside kind, in the
        # same payload, because "the new field is right" and "the old
        # field did not move" are two claims and D5 requires both.
        self.assertFalse(answer["source"]["transcode"])

    @patch("apps.proxy.next_source.close_old_connections")
    @patch("apps.channels.models.reserve_profile_slot", return_value=(True, 1, None))
    @patch("apps.channels.models.RedisClient.get_client")
    def test_the_locked_ffmpeg_profile_carries_a_kind_too(
        self, mock_get_client, _mock_reserve, _mock_close_old_connections
    ):
        """ffmpeg_stream_profile is rendered by the SAME serializer.

        The fourth dict the ruling did not name. Without it, a
        required `kind` on StreamProfileRefSerializer makes every
        next-source answer that carries a locked ffmpeg profile fail
        serialization -- a 500 on every tune, and one no test touching
        only the three `source` sites would catch.
        """
        StreamProfile.objects.create(
            name="ffmpeg", command="ffmpeg", parameters="-i {streamUrl}",
            locked=True, is_active=True,
        )
        mock_get_client.return_value = FakeRedirectRedis()

        answer = resolve_initial_source(str(self.channel.uuid))

        self.assertEqual(answer["source"]["ffmpeg_stream_profile"]["kind"], "transcode")

    def test_the_serializer_renders_kind(self):
        """A required field DRF does not declare is silently dropped."""
        from apps.proxy.serializers import StreamProfileRefSerializer

        rendered = StreamProfileRefSerializer(
            {"id": 7, "command": "", "args": "", "kind": "redirect"}
        ).data
        self.assertEqual(rendered["kind"], "redirect")
