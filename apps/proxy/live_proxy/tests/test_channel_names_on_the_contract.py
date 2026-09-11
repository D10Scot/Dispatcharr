"""PINs for Phase 2 PR 2b-1: the names arrive from Django and are stored,
so the relay never re-queries for them.

Spec: docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
§ Stage 2b, the services/channel_service.py:324,331,911 row.
"""

import json
from unittest.mock import MagicMock, patch

from django.http import StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.proxy.live_proxy.constants import ChannelMetadataField
from apps.proxy.live_proxy.server import ProxyServer
from apps.proxy.live_proxy.services.channel_service import ChannelService
from .harness.control import ControlMixin
from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase


def _configure_init_lock_mocks(proxy_server):
    """Wire MagicMock ProxyServer helpers to a real gevent RLock + setup set.

    Copied from test_internal_principal_no_redirect.py's helper of the same
    name rather than imported: that module is SimpleTestCase-only fixture
    plumbing with no shared base, and CLAUDE.md's guidance elsewhere in this
    package is to copy small setup helpers rather than reach across test
    files for them.
    """
    import gevent.lock

    lock = gevent.lock.RLock()
    proxy_server._channels_setting_up = set()
    proxy_server._get_channel_init_lock.return_value = lock
    proxy_server._finish_channel_init_lock.side_effect = (
        lambda _channel_id, held_lock: held_lock.release()
    )
    proxy_server._clear_channel_setting_up.side_effect = (
        lambda channel_id: proxy_server._channels_setting_up.discard(channel_id)
    )
    return lock


class StreamTsThreadsRealNamesIntoInitializeChannelTests(SimpleTestCase):
    """PIN. Hop 3 in the review trace: views.py's stream_ts ->
    ChannelService.initialize_channel(channel_name=..., stream_name=...,
    m3u_profile_name=..., ffmpeg_stream_profile=...).

    Every pre-existing stream_ts test that reaches initialize_channel
    supplies an all-None tune_extras dict as generate_stream_url's 7th
    element (test_ghost_session_cleanup.py, test_internal_principal_no_redirect.py,
    test_stream_ts_client_registration.py), and the only one that inspects
    the call reads positional[3] (the transcode flag), never the kwargs.
    That is why this is the priority fix, not a cosmetic one: if
    views.py's initialize_channel call regressed to stream_name=None, every
    existing test stays green, because channel_status.py:74's ORM fallback
    would quietly return the correct name anyway when the status endpoint
    is later polled -- the suite could not see a regression that silently
    reintroduces the very tune-path ORM read this PR exists to remove. This
    test supplies real, distinct values for all four fields specifically so
    that a regression to any of them is visible here, not just eventually
    covered up downstream.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.channel_id = "channel-uuid"

    def _channel(self):
        channel = MagicMock()
        channel.id = 1
        channel.uuid = self.channel_id
        # Deliberately different from tune_extras["channel_name"] below, so
        # a pass cannot come from the `or channel.name` fallback in views.py
        # papering over a broken tune_extras read.
        channel.name = "Channel Row Name (must not appear in the assertion)"
        channel.get_stream_profile.return_value.is_redirect.return_value = False
        return channel

    def _decision(self):
        from apps.proxy.authorize import SURFACE_LIVE, AuthorizeResult

        return AuthorizeResult(
            surface=SURFACE_LIVE,
            channel_uuid=self.channel_id,
            client_id="client_test_1",
            user_id="",
            relay_name="py",
            user=None,
        )

    def _proxy_server(self):
        proxy_server = MagicMock()
        proxy_server.redis_client.exists.return_value = False
        proxy_server.redis_client.hgetall.return_value = {}
        proxy_server.redis_client.get.return_value = None
        proxy_server.check_if_channel_exists.return_value = False
        proxy_server.try_acquire_ownership.return_value = True
        _configure_init_lock_mocks(proxy_server)
        proxy_server.stream_buffers = {self.channel_id: MagicMock()}
        proxy_server.client_managers = {self.channel_id: MagicMock()}
        proxy_server.am_i_owner.return_value = True
        proxy_server.get_buffer.return_value = MagicMock()
        proxy_server.ensure_output_profile.return_value = True
        return proxy_server

    @patch("apps.proxy.live_proxy.views.close_old_connections")
    @patch("apps.proxy.live_proxy.views.create_stream_generator")
    @patch("apps.proxy.live_proxy.views._resolve_output_format", return_value="mpegts")
    @patch("apps.proxy.live_proxy.views._output_profile_for", return_value=None)
    @patch("apps.proxy.live_proxy.views.generate_stream_url")
    @patch("apps.proxy.live_proxy.views.ChannelService")
    @patch("apps.proxy.live_proxy.views.get_stream_object")
    @patch("apps.proxy.live_proxy.views.resolve_authorization")
    @patch("apps.proxy.live_proxy.views.ProxyServer")
    def test_the_supplied_names_reach_initialize_channel_as_kwargs(
        self,
        mock_proxy_cls,
        mock_authorize,
        mock_get_stream_object,
        mock_channel_service,
        mock_generate_url,
        _output_profile,
        _output_format,
        mock_create_generator,
        _mock_close,
    ):
        mock_authorize.return_value = self._decision()
        channel = self._channel()
        mock_get_stream_object.return_value = channel

        mock_channel_service.is_channel_unavailable_for_new_clients.return_value = False
        mock_channel_service.initialize_channel.return_value = True
        mock_generate_url.return_value = (
            "http://upstream/stream.ts", "UA", False, "profile", True, None,
            {
                "channel_name": "Real Channel Name",
                "stream_name": "Real Stream Name",
                "m3u_profile_name": "Real Profile Name",
                "ffmpeg_stream_profile": {"id": 9, "command": "ffmpeg", "args": "-i x"},
            },
        )

        proxy_server = self._proxy_server()
        mock_proxy_cls.get_instance.return_value = proxy_server

        request = self.factory.get(f"/proxy/ts/stream/{self.channel_id}/")

        with patch(
            "apps.proxy.live_proxy.views._channel_setup_needed",
            return_value=(True, None, False),
        ):
            mock_create_generator.return_value = lambda: iter([b"chunk"])
            from apps.proxy.live_proxy.views import stream_ts

            response = stream_ts(request, self.channel_id)

        self.assertIsInstance(response, StreamingHttpResponse)
        mock_channel_service.initialize_channel.assert_called_once()
        kwargs = mock_channel_service.initialize_channel.call_args.kwargs
        self.assertEqual(kwargs["channel_name"], "Real Channel Name")
        self.assertEqual(kwargs["stream_name"], "Real Stream Name")
        self.assertEqual(kwargs["m3u_profile_name"], "Real Profile Name")
        self.assertEqual(
            kwargs["ffmpeg_stream_profile"],
            {"id": 9, "command": "ffmpeg", "args": "-i x"},
        )


class InitializeChannelStoresTheNamesTests(TestCase):
    def _redis(self):
        """A ProxyServer whose redis_client records every hset mapping."""
        from unittest.mock import MagicMock

        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.exists.return_value = False
        proxy_server.initialize_channel.return_value = True
        return proxy_server

    def _written(self, redis_client):
        """Every field any hset wrote, merged."""
        written = {}
        for call in redis_client.hset.call_args_list:
            mapping = call.kwargs.get("mapping")
            if mapping:
                written.update(mapping)
            elif len(call.args) == 3:
                written[call.args[1]] = call.args[2]
        return written

    def test_the_supplied_names_reach_the_metadata_hash(self):
        proxy_server = self._redis()
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer"
        ) as cls:
            cls.get_instance.return_value = proxy_server
            ChannelService.initialize_channel(
                "chan-uuid", "http://u/s.ts", "UA",
                stream_id=7, m3u_profile_id=3,
                channel_name="BBC One", stream_name="BBC One HD",
                m3u_profile_name="Provider A default",
                ffmpeg_stream_profile={"id": 9, "command": "ffmpeg", "args": "-i {streamUrl}"},
            )
        written = self._written(proxy_server.redis_client)
        self.assertEqual(written[ChannelMetadataField.CHANNEL_NAME], "BBC One")
        self.assertEqual(written[ChannelMetadataField.STREAM_NAME], "BBC One HD")
        self.assertEqual(written[ChannelMetadataField.M3U_PROFILE_NAME], "Provider A default")
        self.assertEqual(
            json.loads(written[ChannelMetadataField.FFMPEG_STREAM_PROFILE]),
            {"id": 9, "command": "ffmpeg", "args": "-i {streamUrl}"},
        )

    def test_the_names_land_before_the_stream_manager_starts(self):
        """PIN. StreamManager's own threads read this hash; a field written
        only AFTER proxy_server.initialize_channel() returns is racing them.
        Asserts three of four names -- STREAM_NAME, M3U_PROFILE_NAME and
        FFMPEG_STREAM_PROFILE -- carried by the hash by the time
        initialize_channel was called, not merely by the time the method
        returned. Not CHANNEL_NAME: the real ProxyServer.initialize_channel
        (mocked here) writes that one itself, at server.py:791-797, so this
        test's own capture cannot distinguish this method's CHANNEL_NAME
        write from that one's.

        Exercises the `exists()`-is-False branch (the create path) only --
        see test_the_names_land_before_the_stream_manager_starts_when_metadata_already_exists
        below for the companion `exists()`-is-True case, which a reviewer
        found this test alone could not catch a regression in."""
        proxy_server = self._redis()
        seen = {}

        def capture(*args, **kwargs):
            seen.update(self._written(proxy_server.redis_client))
            return True

        proxy_server.initialize_channel.side_effect = capture
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer"
        ) as cls:
            cls.get_instance.return_value = proxy_server
            ChannelService.initialize_channel(
                "chan-uuid", "http://u/s.ts", "UA",
                stream_id=7, m3u_profile_id=3,
                channel_name="BBC One", stream_name="BBC One HD",
                m3u_profile_name="Provider A default",
                ffmpeg_stream_profile={"id": 9, "command": "ffmpeg", "args": "-i x"},
            )
        self.assertEqual(seen[ChannelMetadataField.STREAM_NAME], "BBC One HD")
        self.assertEqual(seen[ChannelMetadataField.M3U_PROFILE_NAME], "Provider A default")
        self.assertIn(ChannelMetadataField.FFMPEG_STREAM_PROFILE, seen)

    def test_the_names_land_before_the_stream_manager_starts_when_metadata_already_exists(self):
        """PIN. Companion to the test above, for the OTHER branch of
        initialize_channel's `if proxy_server.redis_client.exists(metadata_key):`
        (channel_service.py's pre-init block) -- the "metadata already
        exists" path a re-tune or a follower takes. A reviewer found the
        test above sets exists.return_value = False unconditionally, so it
        exercises only the create branch; dropping `mapping.update(names)`
        from the exists()==True branch left that test green."""
        proxy_server = self._redis()
        proxy_server.redis_client.exists.return_value = True
        seen = {}

        def capture(*args, **kwargs):
            seen.update(self._written(proxy_server.redis_client))
            return True

        proxy_server.initialize_channel.side_effect = capture
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer"
        ) as cls:
            cls.get_instance.return_value = proxy_server
            ChannelService.initialize_channel(
                "chan-uuid", "http://u/s.ts", "UA",
                stream_id=7, m3u_profile_id=3,
                channel_name="BBC One", stream_name="BBC One HD",
                m3u_profile_name="Provider A default",
                ffmpeg_stream_profile={"id": 9, "command": "ffmpeg", "args": "-i x"},
            )
        self.assertEqual(seen[ChannelMetadataField.STREAM_NAME], "BBC One HD")
        self.assertEqual(seen[ChannelMetadataField.M3U_PROFILE_NAME], "Provider A default")
        self.assertIn(ChannelMetadataField.FFMPEG_STREAM_PROFILE, seen)

    def test_initialize_channel_runs_no_query_when_the_names_are_supplied(self):
        """PIN, precisely: this proves initialize_channel makes zero queries
        when called with names supplied -- NOT that supplying names is what
        makes the difference. Task 3 deleted the two ORM fallbacks
        (Channel.objects/Stream.objects) outright rather than gating them
        on missing names, so as of this PR initialize_channel makes zero
        queries regardless of whether names are supplied (confirmed with
        Django's CaptureQueriesContext against channel_name=None,
        stream_name=None, m3u_profile_name=None, ffmpeg_stream_profile=None
        during review: also 0). What this test actually guards against is
        someone re-adding a query unconditionally to this method; it does
        not, and was never able to, demonstrate the conditional relationship
        its previous docstring implied."""
        proxy_server = self._redis()
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer"
        ) as cls:
            cls.get_instance.return_value = proxy_server
            with self.assertNumQueries(0):
                ChannelService.initialize_channel(
                    "chan-uuid", "http://u/s.ts", "UA",
                    stream_id=7, m3u_profile_id=3,
                    channel_name="BBC One", stream_name="BBC One HD",
                    m3u_profile_name="Provider A default",
                    ffmpeg_stream_profile=None,
                )


class SwitchPathsCarryTheNamesTests(TestCase):
    def test_change_stream_url_writes_the_supplied_names_without_a_query(self):
        """PIN. services/channel_service.py:911's Stream.objects fallback is
        what this replaces."""
        from unittest.mock import MagicMock

        proxy_server = MagicMock()
        proxy_server.redis_client = MagicMock()
        proxy_server.redis_client.type.return_value = "hash"
        with patch(
            "apps.proxy.live_proxy.services.channel_service.ProxyServer"
        ) as cls:
            cls.get_instance.return_value = proxy_server
            with self.assertNumQueries(0):
                ChannelService._update_channel_metadata(
                    "chan-uuid", "http://u/new.ts", "UA",
                    stream_id=11, m3u_profile_id=3,
                    stream_name="BBC Two HD",
                    channel_name="BBC Two",
                    m3u_profile_name="Provider A default",
                )
        mapping = proxy_server.redis_client.hset.call_args.kwargs["mapping"]
        self.assertEqual(mapping[ChannelMetadataField.STREAM_NAME], "BBC Two HD")
        self.assertEqual(mapping[ChannelMetadataField.CHANNEL_NAME], "BBC Two")
        self.assertEqual(
            mapping[ChannelMetadataField.M3U_PROFILE_NAME], "Provider A default"
        )


class StatusPrefersTheStoredProfileNameTests(ControlMixin, RelayHarnessTestCase):
    """PIN, end to end through the relay's own HTTP surface.

    The hash is seeded with a name that DIFFERS from the row's, so a pass
    cannot come from the ORM happening to return the same string. That is
    the whole assertion: the status endpoint reads the hash, not the row.
    """

    def test_the_status_payload_reports_the_stored_profile_name(self):
        self.redis = ProxyServer.get_instance().redis_client
        self.assertIsNotNone(self.redis, "the harness needs a real Redis client")
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            with self.tuned(channel):
                self.redis.hset(
                    f"live:channel:{channel.uuid}:metadata",
                    ChannelMetadataField.M3U_PROFILE_NAME,
                    "name-only-in-redis",
                )
                status_code, body = self.status(channel)
            self.assertEqual(status_code, 200)
            self.assertEqual(body["m3u_profile_name"], "name-only-in-redis")
        self.stop_channel(channel)
