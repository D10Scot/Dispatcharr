"""Source resolution, now on the control-plane side of the boundary.

Phase 1 PR 6. These are the properties apps/proxy/live_proxy/url_utils.py
used to hold: pick a stream, reserve its slot, resolve its URL, and treat
a Redirect profile exactly like Proxy on every derivation (the PR 5
re-review's fix, which must survive the move).
"""

from unittest.mock import MagicMock, patch

from django.http import Http404
from django.test import SimpleTestCase, TestCase

from apps.channels.models import Channel, ChannelStream, Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from core.models import StreamProfile


class FakeControlPlaneRedis:
    """In-memory Redis stand-in covering the keys next_source.py touches:
    channel_stream, stream_profile and profile_connections counters."""

    def __init__(self):
        self._strings = {}

    def get(self, key):
        value = self._strings.get(key)
        if value is None:
            return None
        return str(value).encode()

    def set(self, key, value, ex=None):
        self._strings[key] = value

    def delete(self, key):
        self._strings.pop(key, None)

    def exists(self, key):
        return key in self._strings

    def hget(self, key, field):
        # No metadata hash is ever seeded in these tests, so every channel
        # looks "not yet initialized" to _stream_assignment_is_reusable,
        # which is exactly the between-get_stream()-and-initialize_channel()
        # window that reuse branch exists for.
        return None

    def incr(self, key):
        current = int(self._strings.get(key, 0) or 0)
        current += 1
        self._strings[key] = current
        return current

    def decr(self, key):
        current = int(self._strings.get(key, 0) or 0)
        current -= 1
        self._strings[key] = current
        return current

    def pipeline(self):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self._ops = []

    def decr(self, key):
        self._ops.append(("decr", key))
        return self

    def incr(self, key):
        self._ops.append(("incr", key))
        return self

    def set(self, key, value):
        self._ops.append(("set", key, value))
        return self

    def execute(self):
        ops, self._ops = self._ops, []
        for op, *args in ops:
            getattr(self.redis, op)(*args)


class NextSourceFixture:
    """One channel, two streams on one M3U account with one active default
    profile (max_streams large enough not to interfere), except for the
    profile-move case, which is its own class below with a second account.

    A plain mixin, not a TestCase subclass: SourceCarriesNamesTests used to
    inherit NextSourceResolutionTests directly for this fixture, which also
    inherited that class's own 11 test_* methods -- Django's test loader
    discovers inherited test methods same as its own, so every one of them
    ran twice, once under each class name, and any failure in the parent
    would have been reported under both. `(NextSourceFixture, TestCase)` is
    the shape that shares setUp without sharing tests.
    """

    def setUp(self):
        self.redis = FakeControlPlaneRedis()
        self.redis_patcher = patch(
            "core.utils.RedisClient.get_client", return_value=self.redis
        )
        self.redis_patcher.start()
        self.addCleanup(self.redis_patcher.stop)

        # Every moved function closes the DB connection in a `finally` block
        # (pre-existing, not part of this move) with CONN_MAX_AGE=0, which
        # closes the real connection Django's TestCase needs to keep open
        # for its own transaction/savepoint bookkeeping. Patched out here,
        # same as test_redirect_transcode_flag.py, so this test can make
        # more than one resolve_source() call per test.
        self.close_patcher = patch("apps.proxy.next_source.close_old_connections")
        self.close_patcher.start()
        self.addCleanup(self.close_patcher.stop)

        self.stream_profile_obj = StreamProfile.objects.create(
            name="next-source-test-profile",
            command="ffmpeg",
            parameters="-i {streamUrl}",
        )
        self.account = M3UAccount.objects.create(
            name="next-source-account",
            account_type="STD",
            username="user",
            password="pass",
            max_streams=5,
        )
        self.m3u_profile = M3UAccountProfile.objects.get(
            m3u_account=self.account, is_default=True
        )
        self.stream_a = Stream.objects.create(
            name="Stream A",
            url="http://example.com/a.ts",
            m3u_account=self.account,
            stream_profile=self.stream_profile_obj,
            stream_hash="next-source-test-hash-a",
        )
        self.stream_b = Stream.objects.create(
            name="Stream B",
            url="http://example.com/b.ts",
            m3u_account=self.account,
            stream_profile=self.stream_profile_obj,
            stream_hash="next-source-test-hash-b",
        )
        self.channel = Channel.objects.create(
            channel_number=9101,
            name="Next Source Channel",
            stream_profile=self.stream_profile_obj,
        )
        ChannelStream.objects.create(channel=self.channel, stream=self.stream_a, order=0)
        ChannelStream.objects.create(channel=self.channel, stream=self.stream_b, order=1)


class NextSourceResolutionTests(NextSourceFixture, TestCase):
    def test_the_initial_call_reserves_a_slot_once(self):
        from apps.proxy.next_source import resolve_source

        first = resolve_source(str(self.channel.uuid))

        self.assertIsNotNone(first["source"])
        self.assertTrue(first["source"]["slot_reserved"])
        self.assertEqual(first["source"]["stream_id"], self.stream_a.id)

        second = resolve_source(str(self.channel.uuid))

        self.assertIsNotNone(second["source"])
        self.assertFalse(second["source"]["slot_reserved"])
        self.assertEqual(second["source"]["stream_id"], self.stream_a.id)

    def test_a_stream_hash_identifier_resolves_the_stream_surface(self):
        from apps.proxy.next_source import resolve_source

        answer = resolve_source(self.stream_a.stream_hash)

        self.assertIsNotNone(answer["source"])
        self.assertEqual(answer["source"]["stream_id"], self.stream_a.id)

    def test_excluded_streams_are_skipped(self):
        from apps.proxy.next_source import resolve_source

        answer = resolve_source(
            str(self.channel.uuid),
            exclude_stream_ids=[self.stream_a.id],
            reason="failover",
        )

        self.assertIsNotNone(answer["source"])
        self.assertEqual(answer["source"]["stream_id"], self.stream_b.id)

    def test_a_candidate_resolving_to_the_current_url_is_skipped(self):
        from apps.proxy.next_source import resolve_source

        # exclude_stream_ids names an id that isn't a real candidate, purely
        # to make "excluded" non-empty so resolve_source takes the failover
        # traversal branch (the only branch that consults current_url)
        # rather than the no-excludes/no-target initial branch.
        answer = resolve_source(
            str(self.channel.uuid),
            exclude_stream_ids=[999999],
            current_url=self.stream_a.url,
            reason="failover",
        )

        self.assertIsNotNone(answer["source"])
        self.assertEqual(answer["source"]["stream_id"], self.stream_b.id)

    def test_a_failover_with_nothing_tried_yet_still_takes_the_traversal_branch(self):
        from apps.proxy.next_source import resolve_source

        # Establish the live assignment on stream_a, the way the initial
        # tune does -- this is what the failover below is failing away
        # FROM, with no current_stream_id known yet (the relay's own
        # __init__ can fail to load it from Redis -- CLAUDE.md, manager.py's
        # warning about relying on URL comparison).
        first = resolve_source(str(self.channel.uuid))
        self.assertEqual(first["source"]["stream_id"], self.stream_a.id)

        # Review round 1, Important: exclude_stream_ids=[] alone must not
        # route into the reuse-or-reserve branch, or this "failover" would
        # just hand back stream_a's URL again (which update_url then
        # refuses to "switch" to). current_url is what has to force the
        # traversal branch even though nothing has been tried yet.
        answer = resolve_source(
            str(self.channel.uuid),
            exclude_stream_ids=[],
            current_url=self.stream_a.url,
            reason="failover",
        )

        self.assertIsNotNone(answer["source"])
        self.assertEqual(answer["source"]["stream_id"], self.stream_b.id)

    def test_a_failover_reason_alone_avoids_the_reuse_branch(self):
        from apps.proxy.next_source import resolve_source

        first = resolve_source(str(self.channel.uuid))
        self.assertEqual(first["source"]["stream_id"], self.stream_a.id)

        # reason="failover" with no current_url at all (the relay has no
        # URL to compare against) must still route into the traversal
        # branch rather than Channel.get_stream()'s reuse branch -- it just
        # has no way to skip stream_a without current_url, so it lands back
        # on stream_a via the ordered traversal rather than the reuse path.
        # The observable difference from the reuse branch is slot_reserved:
        # the reuse branch reports False for an unchanged live assignment,
        # the traversal branch always reserves (moves the slot) for the
        # candidate it picks, even when that candidate is the same stream.
        answer = resolve_source(
            str(self.channel.uuid),
            exclude_stream_ids=[],
            reason="failover",
        )

        self.assertIsNotNone(answer["source"])
        self.assertEqual(answer["source"]["stream_id"], self.stream_a.id)
        self.assertTrue(answer["source"]["slot_reserved"])

    def test_failover_rotation_starts_after_the_current_stream(self):
        from apps.proxy.next_source import resolve_source

        # A third stream so the rotation order (order_alternates_from_
        # current) is observably different from plain channel order.
        stream_c = Stream.objects.create(
            name="Stream C",
            url="http://example.com/c.ts",
            m3u_account=self.account,
            stream_profile=self.stream_profile_obj,
            stream_hash="next-source-test-hash-c",
        )
        ChannelStream.objects.create(channel=self.channel, stream=stream_c, order=2)

        # Failing over away from B: without current_stream_id threaded
        # through to get_alternate_streams, the traversal falls back to
        # channel order (A first). With it, order_alternates_from_current
        # rotates to start right after B, wrapping, so C is offered first
        # instead — the property apps.proxy.live_proxy.input.manager's
        # _try_next_stream relies on today.
        answer = resolve_source(
            str(self.channel.uuid),
            exclude_stream_ids=[self.stream_b.id],
            current_stream_id=self.stream_b.id,
            reason="failover",
        )

        self.assertIsNotNone(answer["source"])
        self.assertEqual(answer["source"]["stream_id"], stream_c.id)

    def test_no_candidate_left_is_an_error_not_an_exception(self):
        from apps.proxy.next_source import resolve_source

        answer = resolve_source(
            str(self.channel.uuid),
            exclude_stream_ids=[self.stream_a.id, self.stream_b.id],
            reason="failover",
        )

        self.assertIsNone(answer["source"])
        self.assertTrue(answer["error"])

    def test_an_unknown_identifier_raises_http404(self):
        from apps.proxy.next_source import resolve_source

        with self.assertRaises(Http404):
            resolve_source("not-a-channel")

    def test_include_alternates_returns_resolved_candidates_that_reserve_nothing(self):
        from apps.proxy.next_source import resolve_source

        answer = resolve_source(str(self.channel.uuid), include_alternates=True)

        self.assertEqual(len(answer["alternates"]), 1)
        alt = answer["alternates"][0]
        self.assertIn("url", alt)
        self.assertIn("user_agent", alt)
        self.assertIn("transcode", alt)
        self.assertIn("m3u_profile_id", alt)
        self.assertFalse(alt["slot_reserved"])

    def test_resolving_with_alternates_runs_the_locked_ffmpeg_query_once(self):
        """PIN, against the N+1 a review round found: before this,
        include_alternates=True ran _locked_ffmpeg_profile()'s StreamProfile
        query once for the primary source (inside resolve_initial_source)
        plus once per alternate (inside _resolve_alternates ->
        _source_from_info) -- N+1 total. This fixture's one alternate
        (stream_b) already distinguishes "ran once" (this test) from "ran
        twice" (the pre-fix behaviour), which is what matters; a bigger
        fixture would only make the same assertion's margin larger, not
        change what it proves.
        """
        import apps.proxy.next_source as next_source_module
        from apps.proxy.next_source import resolve_source

        wrapped = MagicMock(wraps=next_source_module._locked_ffmpeg_profile)
        with patch.object(next_source_module, "_locked_ffmpeg_profile", wrapped):
            answer = resolve_source(str(self.channel.uuid), include_alternates=True)

        self.assertEqual(len(answer["alternates"]), 1)
        self.assertEqual(wrapped.call_count, 1)

    def test_include_alternates_on_a_previewed_stream_logs_nothing_and_returns_none(self):
        # Minor finding, fix wave B: generate_stream_url always sends
        # include_alternates=True, and a directly previewed Stream has no
        # assigned alternates -- get_alternate_streams() walks
        # Channel.streams, which a bare Stream doesn't have. Before the fix,
        # resolve_source called it anyway on every preview tune and it
        # logged "Stream is not a channel" at ERROR.
        from apps.proxy.next_source import resolve_source

        with self.assertNoLogs("live_proxy", level="ERROR"):
            answer = resolve_source(self.stream_a.stream_hash, include_alternates=True)

        self.assertIsNotNone(answer["source"])
        self.assertEqual(answer["alternates"], [])


class NextSourceProfileSwitchTests(TestCase):
    """A switch across two M3U accounts, each with its own default profile.

    The single-account fixture above can't exercise this: with only one
    profile, get_stream_info_for_switch computes channel_using_profile=True
    for it and Channel.update_stream_profile() returns True at the "already
    set" guard (apps/channels/models.py:961-963) having moved nothing. Two
    accounts give the switch a real profile to move to.
    """

    def setUp(self):
        self.redis = FakeControlPlaneRedis()
        self.redis_patcher = patch(
            "core.utils.RedisClient.get_client", return_value=self.redis
        )
        self.redis_patcher.start()
        self.addCleanup(self.redis_patcher.stop)

        self.close_patcher = patch("apps.proxy.next_source.close_old_connections")
        self.close_patcher.start()
        self.addCleanup(self.close_patcher.stop)

        self.stream_profile_obj = StreamProfile.objects.create(
            name="next-source-switch-profile",
            command="ffmpeg",
            parameters="-i {streamUrl}",
        )
        self.account_a = M3UAccount.objects.create(
            name="next-source-switch-account-a",
            account_type="STD",
            username="user-a",
            password="pass-a",
            max_streams=5,
        )
        self.account_b = M3UAccount.objects.create(
            name="next-source-switch-account-b",
            account_type="STD",
            username="user-b",
            password="pass-b",
            max_streams=5,
        )
        self.profile_a = M3UAccountProfile.objects.get(
            m3u_account=self.account_a, is_default=True
        )
        self.profile_b = M3UAccountProfile.objects.get(
            m3u_account=self.account_b, is_default=True
        )
        self.stream_a = Stream.objects.create(
            name="Switch Stream A",
            url="http://example.com/switch-a.ts",
            m3u_account=self.account_a,
            stream_profile=self.stream_profile_obj,
        )
        self.stream_b = Stream.objects.create(
            name="Switch Stream B",
            url="http://example.com/switch-b.ts",
            m3u_account=self.account_b,
            stream_profile=self.stream_profile_obj,
        )
        self.channel = Channel.objects.create(
            channel_number=9102,
            name="Next Source Switch Channel",
            stream_profile=self.stream_profile_obj,
        )
        ChannelStream.objects.create(channel=self.channel, stream=self.stream_a, order=0)
        ChannelStream.objects.create(channel=self.channel, stream=self.stream_b, order=1)

    def test_a_switch_moves_the_profile_slot_and_leaves_channel_stream_alone(self):
        from apps.proxy.next_source import resolve_source

        initial = resolve_source(str(self.channel.uuid))
        self.assertEqual(initial["source"]["stream_id"], self.stream_a.id)

        answer = resolve_source(
            str(self.channel.uuid), target_stream_id=self.stream_b.id
        )

        self.assertIsNotNone(answer["source"])

        # The original stream's key now names the new profile.
        self.assertEqual(
            self.redis.get(f"stream_profile:{self.stream_a.id}"),
            str(self.profile_b.id).encode(),
        )
        # Counters moved: P_a down by one, P_b up by one.
        self.assertEqual(
            int(self.redis.get(f"profile_connections:{self.profile_a.id}") or 0),
            0,
        )
        self.assertEqual(
            int(self.redis.get(f"profile_connections:{self.profile_b.id}") or 0),
            1,
        )
        # stream_profile:<streams[1].id> is never created by this path.
        self.assertIsNone(self.redis.get(f"stream_profile:{self.stream_b.id}"))
        # channel_stream still names the ORIGINAL stream, unchanged.
        self.assertEqual(
            self.redis.get(f"channel_stream:{self.channel.id}"),
            str(self.stream_a.id).encode(),
        )


class NextSourceDbCleanupTests(SimpleTestCase):
    @patch("core.models.OutputProfile.objects.filter")
    @patch("core.models.CoreSettings.get_proxy_settings")
    @patch("apps.proxy.next_source.close_old_connections")
    @patch("apps.proxy.next_source.get_stream_object")
    def test_resolve_source_closes_db(
        self, mock_get_object, mock_close, mock_proxy_settings, mock_output_profiles
    ):
        # Phase 2 PR 2b-1: every resolve_source() answer now carries
        # proxy_settings, which is its own CoreSettings read
        # (_with_proxy_settings). This test is a SimpleTestCase (no DB), so
        # that read is mocked out -- it is not what this test is about.
        # 2b-2 adds a second such read, output_profiles
        # (_with_output_profiles's OutputProfile.objects.filter), mocked
        # for the same reason.
        mock_proxy_settings.return_value = {}
        mock_output_profiles.return_value = []
        channel = MagicMock()
        channel.get_stream.return_value = (None, None, "no streams", False)
        mock_get_object.return_value = channel

        from apps.proxy.next_source import resolve_source

        answer = resolve_source("channel-uuid")

        self.assertIsNone(answer["source"])
        mock_close.assert_called_once()

    @patch("apps.proxy.next_source.close_old_connections")
    @patch("apps.proxy.next_source.get_stream_object")
    def test_get_alternate_streams_closes_db(self, mock_get_object, mock_close):
        channel = MagicMock()
        channel.streams.all.return_value.order_by.return_value.exists.return_value = False
        mock_get_object.return_value = channel

        from apps.proxy.next_source import get_alternate_streams

        self.assertEqual(get_alternate_streams("channel-uuid", current_stream_id=1), [])
        mock_close.assert_called_once()

    @patch("apps.proxy.next_source.close_old_connections")
    @patch("apps.proxy.next_source.get_object_or_404")
    def test_get_stream_info_for_switch_closes_db_on_error(self, mock_get_404, mock_close):
        mock_get_404.side_effect = RuntimeError("db error")

        from apps.proxy.next_source import get_stream_info_for_switch

        result = get_stream_info_for_switch("channel-uuid", target_stream_id=99)

        self.assertIn("error", result)
        mock_close.assert_called_once()


class ReleaseSourceMetadataFallbackTests(SimpleTestCase):
    """Phase 1 PR 6, Task 9: the half of the release pin that moved to
    Django. A channel deleted mid-playback (neither a Channel nor a Stream
    row exists) still frees channel_stream:*/stream_profile:* and the
    provider slot, using only the ids the relay read out of its own
    metadata hash and passed as arguments."""

    @patch("apps.m3u.connection_pool.release_profile_slot")
    @patch("core.utils.RedisClient.get_client")
    @patch("apps.proxy.next_source.Stream.objects.get", side_effect=Stream.DoesNotExist)
    @patch("apps.proxy.next_source.Channel.objects.get", side_effect=Channel.DoesNotExist)
    def test_release_source_falls_back_to_metadata_when_channel_gone(
        self, mock_channel_get, mock_stream_get, mock_get_client, mock_release_slot
    ):
        redis_client = MagicMock()
        mock_get_client.return_value = redis_client

        from apps.proxy.next_source import release_source

        released = release_source(
            "gone", stream_id=2243070, m3u_profile_id=50, channel_pk=224
        )

        self.assertTrue(released)
        redis_client.delete.assert_any_call("channel_stream:224")
        redis_client.delete.assert_any_call("stream_profile:2243070")
        mock_release_slot.assert_called_once_with(50, redis_client)


class SourceCarriesNamesTests(NextSourceFixture, TestCase):
    """PIN. Phase 2 PR 2b-1: every Source carries the names the relay used to
    re-query for (spec § Stage 2b, the channel_service.py:324,331,911 row) and
    the locked ffmpeg profile (the input/manager.py:737 row).

    Shares NextSourceResolutionTests' fixture via NextSourceFixture, not by
    inheriting that class -- inheriting it would have re-run its 11 test_*
    methods under this class's name too (a reviewer finding; see the
    mixin's own docstring above)."""

    def test_the_initial_tune_source_carries_all_four_names(self):
        from apps.proxy.next_source import resolve_source

        answer = resolve_source(self.channel.uuid)
        source = answer["source"]
        self.assertEqual(source["channel_name"], self.channel.name)
        self.assertEqual(source["stream_name"], self.stream_a.name)
        self.assertEqual(source["m3u_profile_name"], self.m3u_profile.name)

    def test_a_switch_source_carries_all_four_names(self):
        from apps.proxy.next_source import resolve_source

        answer = resolve_source(
            self.channel.uuid, target_stream_id=self.stream_b.id, reason="operator"
        )
        source = answer["source"]
        self.assertEqual(source["channel_name"], self.channel.name)
        self.assertEqual(source["stream_name"], self.stream_b.name)
        self.assertEqual(source["m3u_profile_name"], self.m3u_profile.name)

    def test_a_previewed_stream_reports_its_own_name_as_the_channel_name(self):
        # stream_ts computes channel_display_name as getattr(channel, "name", None)
        # and a previewed Stream has .name, so this is the value the relay already
        # displays for a hash tune -- carried, not invented.
        from apps.proxy.next_source import resolve_source

        answer = resolve_source(self.stream_a.stream_hash)
        source = answer["source"]
        self.assertEqual(source["channel_name"], self.stream_a.name)
        self.assertEqual(source["stream_name"], self.stream_a.name)
        self.assertEqual(source["m3u_profile_name"], self.m3u_profile.name)

    def test_the_locked_ffmpeg_profile_is_carried_when_one_exists(self):
        # core/migrations/0006 and 0007 seed a locked 'ffmpeg' profile, but a
        # TransactionTestCase run earlier in the SAME process can have
        # flushed it away already (manager_support.py:105's "Created rather
        # than fetched" comment documents exactly this hazard). get_or_create
        # is robust to both orderings: if the seeded row survived, this finds
        # it (name+locked is not DB-unique, so a get() alone risks a second
        # match if one ever collides; a filter().first() ordered by pk is
        # what _locked_ffmpeg_profile() itself uses); if it was flushed away,
        # this recreates it with the same shape a real deployment has.
        from apps.proxy.next_source import resolve_source

        ffmpeg, _ = StreamProfile.objects.get_or_create(
            name="ffmpeg", locked=True,
            defaults={
                "command": "ffmpeg",
                "parameters": "-i {streamUrl} -c copy -f mpegts pipe:1",
            },
        )
        source = resolve_source(self.channel.uuid)["source"]
        self.assertEqual(
            source["ffmpeg_stream_profile"],
            {"id": ffmpeg.id, "command": ffmpeg.command, "args": ffmpeg.parameters},
        )

    def test_no_locked_ffmpeg_profile_is_a_null_key_not_a_missing_one(self):
        from apps.proxy.next_source import resolve_source

        # core/signals.py's prevent_deletion_if_locked blocks .delete() on a
        # locked profile (pre_delete signal). QuerySet.update() sends no
        # signals, so flipping locked=False is the way to make "no locked
        # ffmpeg profile" true in a test DB without violating that guard.
        StreamProfile.objects.filter(name="ffmpeg", locked=True).update(locked=False)
        source = resolve_source(self.channel.uuid)["source"]
        self.assertIn("ffmpeg_stream_profile", source)
        self.assertIsNone(source["ffmpeg_stream_profile"])

    def test_the_answer_carries_proxy_settings_as_resolved_now(self):
        from core.models import CoreSettings
        from apps.proxy.next_source import resolve_source

        answer = resolve_source(self.channel.uuid)
        self.assertEqual(answer["proxy_settings"], CoreSettings.get_proxy_settings())
