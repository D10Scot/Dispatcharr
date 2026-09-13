"""ORM-fixture branches in apps/proxy/next_source.py (Phase 2 PR 2b-4, kind 3).

2b-2 edited this file (added output_profiles to the next-source response),
so every line number below was re-derived from a fresh coverage measurement
against 172fb07d rather than carried from an older reading. No relay state
here: ordinary TestCase with model fixtures, reusing NextSourceFixture from
test_next_source_resolution.py rather than writing a third fixture builder.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.channels.models import Channel, ChannelStream, Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.proxy.tests.test_next_source_resolution import (
    FakeControlPlaneRedis,
    NextSourceFixture,
)
from core.models import StreamProfile


class ResolveLiveStreamUrlXcTests(NextSourceFixture, TestCase):
    def test_xc_credentials_build_the_live_url(self):
        from apps.proxy.next_source import _resolve_live_stream_url

        xc_account = M3UAccount.objects.create(
            name="xc-account", account_type=M3UAccount.Types.XC,
            username="user", password="pass", max_streams=5,
        )
        xc_profile = M3UAccountProfile.objects.get(
            m3u_account=xc_account, is_default=True
        )
        xc_stream = Stream.objects.create(
            name="XC Stream", url="http://old.example/should-not-be-used.ts",
            m3u_account=xc_account, stream_id=144065,
            stream_hash="next-source-xc-hash",
        )
        # Fixture credentials, obviously synthetic -- CLAUDE.md's rule
        # against a provider password reaching a log or an assertion.
        with patch(
            "apps.m3u.tasks.get_transformed_credentials",
            return_value=("http://provider.example/", "pw-fixture-user", "pw-fixture-pass"),
        ):
            url = _resolve_live_stream_url(xc_stream, xc_account, xc_profile)

        self.assertEqual(
            url, "http://provider.example/live/pw-fixture-user/pw-fixture-pass/144065.ts"
        )

    def test_xc_without_a_stream_id_falls_back_to_transform_url(self):
        from apps.proxy.next_source import _resolve_live_stream_url

        xc_account = M3UAccount.objects.create(
            name="xc-account-2", account_type=M3UAccount.Types.XC,
            username="user", password="pass", max_streams=5,
        )
        xc_profile = M3UAccountProfile.objects.get(
            m3u_account=xc_account, is_default=True
        )
        # stream_id is None, so the XC branch's own guard
        # (m3u_account.account_type == XC and stream.stream_id) is False --
        # this must fall through to the plain transform_url path rather
        # than the XC credential build.
        plain_stream = Stream.objects.create(
            name="No stream_id", url="http://example.com/plain.ts",
            m3u_account=xc_account, stream_hash="next-source-xc-no-id",
        )
        with patch("apps.m3u.tasks.get_transformed_credentials") as mocked:
            url = _resolve_live_stream_url(plain_stream, xc_account, xc_profile)
        mocked.assert_not_called()
        self.assertEqual(url, "http://example.com/plain.ts")


class TransformUrlNoMatchTests(SimpleTestCase):
    def test_a_pattern_that_does_not_match_falls_back_to_the_original_url(self):
        from apps.proxy.next_source import transform_url

        result = transform_url(
            "http://example.com/stream.ts", r"nomatch-pattern-xyz", r"replacement"
        )
        self.assertEqual(result, "http://example.com/stream.ts")


class OrderAlternatesFromCurrentTests(SimpleTestCase):
    def test_a_current_stream_id_missing_from_ordered_ids_returns_unrotated(self):
        from apps.proxy.next_source import order_alternates_from_current

        alternates = [{"stream_id": 1}, {"stream_id": 2}]
        result = order_alternates_from_current(
            alternates, ordered_stream_ids=[10, 20], current_stream_id=999
        )
        # ordered_stream_ids.index(999) raises ValueError -- the candidate
        # list is returned unrotated, not emptied.
        self.assertEqual(result, alternates)


class GetStreamInfoForSwitchTests(NextSourceFixture, TestCase):
    def test_a_target_stream_with_no_m3u_account_is_refused(self):
        from apps.proxy.next_source import get_stream_info_for_switch

        # Stream.objects.create() with no m3u_account triggers a pre_save
        # signal (apps/channels/signals.py:set_default_m3u_account) that
        # auto-assigns the "custom" M3UAccount -- so the row this test needs
        # (m3u_account genuinely None) can only be reached with .update(),
        # which bypasses signals, after a normal create.
        orphan_stream = Stream.objects.create(
            name="Orphan", url="http://example.com/orphan.ts",
            m3u_account=self.account,
        )
        Stream.objects.filter(pk=orphan_stream.pk).update(m3u_account=None)
        info = get_stream_info_for_switch(
            str(self.channel.uuid), target_stream_id=orphan_stream.id
        )
        self.assertEqual(info, {"error": "Stream has no M3U account"})

    def test_a_target_streams_account_with_no_active_default_profile_is_refused(self):
        from apps.proxy.next_source import get_stream_info_for_switch

        self.m3u_profile.is_active = False
        self.m3u_profile.save()

        info = get_stream_info_for_switch(
            str(self.channel.uuid), target_stream_id=self.stream_a.id
        )
        self.assertEqual(info, {"error": "M3U account has no default profile"})

    def test_no_redis_client_selects_the_default_profile_without_a_capacity_check(self):
        from apps.proxy.next_source import get_stream_info_for_switch

        with patch("core.utils.RedisClient.get_client", return_value=None):
            info = get_stream_info_for_switch(
                str(self.channel.uuid), target_stream_id=self.stream_a.id
            )
        self.assertNotIn("error", info)
        self.assertEqual(info["m3u_profile_id"], self.m3u_profile.id)

    def test_no_profile_has_connection_capacity_is_refused(self):
        from apps.proxy.next_source import get_stream_info_for_switch

        self.m3u_profile.max_streams = 1
        self.m3u_profile.save()
        self.redis.set(f"profile_connections:{self.m3u_profile.id}", 1)

        info = get_stream_info_for_switch(
            str(self.channel.uuid), target_stream_id=self.stream_a.id
        )
        self.assertEqual(
            info, {"error": "No profiles available with connection capacity"}
        )

    def test_no_stream_assigned_to_the_channel_is_refused(self):
        # get_stream_info_for_switch fetches its OWN fresh Channel instance
        # via get_object_or_404(Channel, uuid=...) -- it never touches
        # self.channel -- so the mock must be installed on the class, not
        # the fixture's instance, or it is silently never consulted.
        from apps.proxy.next_source import get_stream_info_for_switch

        with patch.object(
            Channel, "get_stream",
            return_value=(None, None, "no candidates left", False),
        ):
            info = get_stream_info_for_switch(
                str(self.channel.uuid), target_stream_id=None
            )
        self.assertEqual(info, {"error": "no candidates left"})

    def test_no_stream_assigned_falls_back_to_the_default_message(self):
        from apps.proxy.next_source import get_stream_info_for_switch

        with patch.object(
            Channel, "get_stream", return_value=(None, None, None, False)
        ):
            info = get_stream_info_for_switch(
                str(self.channel.uuid), target_stream_id=None
            )
        self.assertEqual(info, {"error": "No stream assigned to channel"})

    def test_a_reserved_slot_is_released_on_a_later_exception(self):
        from apps.proxy.next_source import get_stream_info_for_switch

        # The non-target-stream branch reserves via channel.get_stream()
        # (slot_reserved=True), then the subsequent Stream lookup at
        # pk=stream_id raises because no such Stream exists -- the except
        # block's rollback (release_stream(), only when slot_reserved AND
        # channel is not None) is the product under test, not the get_stream
        # call itself.
        with patch.object(
            Channel, "get_stream",
            return_value=(999999, self.m3u_profile.id, None, True),
        ), patch.object(Channel, "release_stream", return_value=True) as released:
            info = get_stream_info_for_switch(
                str(self.channel.uuid), target_stream_id=None
            )
        self.assertIn("error", info)
        released.assert_called_once()


class GetAlternateStreamsTests(NextSourceFixture, TestCase):
    def test_a_stream_hash_identifier_is_not_a_channel_and_returns_no_alternates(self):
        from apps.proxy.next_source import get_alternate_streams

        result = get_alternate_streams(self.stream_a.stream_hash)
        self.assertEqual(result, [])

    def test_a_stream_with_no_m3u_account_is_skipped_not_excepted(self):
        from apps.proxy.next_source import get_alternate_streams

        orphan = Stream.objects.create(
            name="Orphan", url="http://example.com/o.ts", m3u_account=self.account,
        )
        Stream.objects.filter(pk=orphan.pk).update(m3u_account=None)
        ChannelStream.objects.create(channel=self.channel, stream=orphan, order=2)

        result = get_alternate_streams(str(self.channel.uuid))
        # stream_a and stream_b are still resolvable; orphan contributes
        # nothing but does not abort the rest.
        self.assertEqual(
            {entry["stream_id"] for entry in result},
            {self.stream_a.id, self.stream_b.id},
        )

    def test_an_inactive_m3u_account_is_skipped(self):
        from apps.proxy.next_source import get_alternate_streams

        self.account.is_active = False
        self.account.save()

        result = get_alternate_streams(str(self.channel.uuid))
        self.assertEqual(result, [])

    def test_an_account_with_no_active_default_profile_is_skipped(self):
        from apps.proxy.next_source import get_alternate_streams

        self.m3u_profile.is_active = False
        self.m3u_profile.save()

        result = get_alternate_streams(str(self.channel.uuid))
        self.assertEqual(result, [])

    def test_no_redis_client_selects_the_default_profile_for_every_stream(self):
        from apps.proxy.next_source import get_alternate_streams

        with patch("core.utils.RedisClient.get_client", return_value=None):
            result = get_alternate_streams(str(self.channel.uuid))
        self.assertEqual(
            {entry["stream_id"] for entry in result},
            {self.stream_a.id, self.stream_b.id},
        )

    def test_no_profile_capacity_excludes_that_stream_only(self):
        from apps.proxy.next_source import get_alternate_streams

        self.m3u_profile.max_streams = 1
        self.m3u_profile.save()
        self.redis.set(f"profile_connections:{self.m3u_profile.id}", 1)

        result = get_alternate_streams(str(self.channel.uuid))
        self.assertEqual(result, [])

    def test_a_per_stream_exception_is_isolated_not_fatal(self):
        from apps.proxy.next_source import get_alternate_streams

        # stream_a's m3u_account access raises; stream_b must still resolve.
        # Patched on the CLASS, restored via addCleanup, so only stream_a's
        # instance is affected is not guaranteed -- instead delete stream_a
        # outright, which raises Stream.m3u_account.RelatedObjectDoesNotExist
        # inside the per-stream try when the queryset re-fetches it.
        original_m3u_account_id = self.stream_a.m3u_account_id
        Stream.objects.filter(pk=self.stream_a.pk).update(m3u_account_id=None)
        self.addCleanup(
            lambda: Stream.objects.filter(pk=self.stream_a.pk).update(
                m3u_account_id=original_m3u_account_id
            )
        )

        result = get_alternate_streams(str(self.channel.uuid))
        # stream_a has no m3u_account now -- the "no m3u_account" continue
        # handles it (not the inner except), and stream_b still resolves.
        self.assertEqual([entry["stream_id"] for entry in result], [self.stream_b.id])


class ResolveInitialSourcePreviewTests(NextSourceFixture, TestCase):
    def test_previewing_a_stream_with_no_m3u_account_is_refused(self):
        from apps.proxy.next_source import resolve_initial_source

        orphan = Stream.objects.create(
            name="Orphan", url="http://example.com/o.ts",
            m3u_account=self.account, stream_hash="next-source-orphan-preview",
        )
        Stream.objects.filter(pk=orphan.pk).update(m3u_account=None)
        orphan.refresh_from_db()
        answer = resolve_initial_source(orphan.stream_hash)
        self.assertEqual(
            answer, {"source": None, "error": "Stream has no M3U account"}
        )

    def test_previewing_a_stream_with_no_profile_available_is_refused(self):
        from apps.proxy.next_source import resolve_initial_source

        self.stream_a.get_stream = MagicMock(
            return_value=(None, None, "no capacity", False)
        )
        with patch(
            "apps.channels.models.Stream.objects.select_related"
        ) as select_related, patch(
            "apps.proxy.next_source.get_stream_object", return_value=self.stream_a
        ):
            answer = resolve_initial_source(self.stream_a.stream_hash)
        self.assertEqual(answer, {"source": None, "error": "no capacity"})

    def test_a_preview_exception_releases_a_reserved_slot(self):
        from apps.proxy.next_source import resolve_initial_source

        self.stream_a.get_stream = MagicMock(
            return_value=(self.stream_a.id, 999999, None, True)
        )
        self.stream_a.release_stream = MagicMock(return_value=True)
        with patch(
            "apps.proxy.next_source.get_stream_object", return_value=self.stream_a
        ):
            answer = resolve_initial_source(self.stream_a.stream_hash)
        self.assertIsNone(answer["source"])
        self.assertIsNotNone(answer["error"])
        self.stream_a.release_stream.assert_called_once()

    def test_a_channel_path_exception_releases_a_reserved_slot(self):
        from apps.proxy.next_source import resolve_initial_source

        self.channel.get_stream = MagicMock(
            return_value=(999999, 999999, None, True)
        )
        self.channel.release_stream = MagicMock(return_value=True)
        with patch(
            "apps.proxy.next_source.get_stream_object", return_value=self.channel
        ):
            answer = resolve_initial_source(str(self.channel.uuid))
        self.assertIsNone(answer["source"])
        self.channel.release_stream.assert_called_once()

    def test_a_failed_release_after_a_channel_path_exception_is_logged_not_raised(self):
        from apps.proxy.next_source import resolve_initial_source

        self.channel.get_stream = MagicMock(
            return_value=(999999, 999999, None, True)
        )
        self.channel.release_stream = MagicMock(return_value=False)
        with patch(
            "apps.proxy.next_source.get_stream_object", return_value=self.channel
        ), self.assertLogs("live_proxy", level="WARNING") as logs:
            answer = resolve_initial_source(str(self.channel.uuid))
        self.assertIsNone(answer["source"])
        self.assertTrue(
            any("Failed to release stream" in line for line in logs.output)
        )


class ResolveAlternatesTests(NextSourceFixture, TestCase):
    def test_a_candidate_that_resolves_to_an_error_is_skipped(self):
        from apps.proxy.next_source import _resolve_alternates

        with patch(
            "apps.proxy.next_source.get_alternate_streams",
            return_value=[{"stream_id": self.stream_b.id, "profile_id": self.m3u_profile.id,
                            "name": "Stream B"}],
        ), patch(
            "apps.proxy.next_source.get_stream_info_for_switch",
            return_value={"error": "no capacity"},
        ):
            result = _resolve_alternates(str(self.channel.uuid), self.stream_a.id)
        self.assertEqual(result, [])

    def test_an_unresolved_locked_ffmpeg_profile_is_resolved_once(self):
        from apps.proxy.next_source import _resolve_alternates, _UNRESOLVED_FFMPEG_PROFILE

        with patch(
            "apps.proxy.next_source.get_alternate_streams", return_value=[]
        ), patch(
            "apps.proxy.next_source._locked_ffmpeg_profile", return_value=None
        ) as locked:
            result = _resolve_alternates(
                str(self.channel.uuid), self.stream_a.id,
                locked_ffmpeg_profile=_UNRESOLVED_FFMPEG_PROFILE,
            )
        self.assertEqual(result, [])
        locked.assert_called_once()


class ResolveSourceTargetAndFailoverEdgeTests(NextSourceFixture, TestCase):
    def test_a_target_stream_id_that_resolves_to_an_error_propagates_it(self):
        from apps.proxy.next_source import resolve_source

        with patch(
            "apps.proxy.next_source.get_stream_info_for_switch",
            return_value={"error": "no capacity"},
        ):
            answer = resolve_source(str(self.channel.uuid), target_stream_id=self.stream_a.id)
        self.assertEqual(answer["error"], "no capacity")
        self.assertIsNone(answer["source"])

    def test_a_failover_candidate_with_an_error_or_no_url_is_skipped(self):
        from apps.proxy.next_source import resolve_source

        with patch(
            "apps.proxy.next_source.get_alternate_streams",
            return_value=[
                {"stream_id": self.stream_a.id, "profile_id": self.m3u_profile.id, "name": "A"},
                {"stream_id": self.stream_b.id, "profile_id": self.m3u_profile.id, "name": "B"},
            ],
        ), patch(
            "apps.proxy.next_source.get_stream_info_for_switch",
            side_effect=[
                {"error": "no capacity"},
                {"url": "http://example.com/b.ts", "m3u_profile_id": self.m3u_profile.id,
                 "stream_id": self.stream_b.id, "user_agent": "ua", "transcode": False,
                 "stream_profile": self.stream_profile_obj.id},
            ],
        ), patch("apps.proxy.next_source._commit") as commit:
            commit.return_value = {"stream_id": self.stream_b.id}
            answer = resolve_source(
                str(self.channel.uuid), reason="failover", current_stream_id=self.stream_a.id,
            )
        self.assertEqual(answer["source"], {"stream_id": self.stream_b.id})


class ReleaseSourceEdgeTests(SimpleTestCase):
    @patch("apps.m3u.connection_pool.release_profile_slot")
    @patch("core.utils.RedisClient.get_client")
    @patch("apps.proxy.next_source.Stream.objects.get", side_effect=RuntimeError("db down"))
    @patch("apps.proxy.next_source.Channel.objects.get", side_effect=Channel.DoesNotExist)
    def test_a_stream_lookup_exception_falls_through_to_metadata_release(
        self, mock_channel_get, mock_stream_get, mock_get_client, mock_release_slot
    ):
        from apps.proxy.next_source import release_source

        redis_client = MagicMock()
        mock_get_client.return_value = redis_client

        released = release_source(
            "gone", stream_id=2243070, m3u_profile_id=50, channel_pk=224
        )
        self.assertTrue(released)
        mock_release_slot.assert_called_once_with(50, redis_client)

    @patch("core.utils.RedisClient.get_client", return_value=None)
    @patch("apps.proxy.next_source.Stream.objects.get", side_effect=Stream.DoesNotExist)
    @patch("apps.proxy.next_source.Channel.objects.get", side_effect=Channel.DoesNotExist)
    def test_no_redis_client_at_the_metadata_fallback_returns_false(
        self, mock_channel_get, mock_stream_get, mock_get_client
    ):
        from apps.proxy.next_source import release_source

        released = release_source(
            "gone", stream_id=2243070, m3u_profile_id=50, channel_pk=224
        )
        self.assertFalse(released)
