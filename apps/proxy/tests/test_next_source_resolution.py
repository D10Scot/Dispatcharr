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


class NextSourceResolutionTests(TestCase):
    """One channel, two streams on one M3U account with one active default
    profile (max_streams large enough not to interfere), except for the
    profile-move case, which is its own class below with a second account."""

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
    @patch("apps.proxy.next_source.close_old_connections")
    @patch("apps.proxy.next_source.get_stream_object")
    def test_resolve_source_closes_db(self, mock_get_object, mock_close):
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
