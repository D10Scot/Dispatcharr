"""Tests for Channel.get_stream() assignment reuse and stale cleanup."""

from unittest.mock import patch

from django.test import TestCase

from apps.channels.models import Channel, ChannelStream, Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.proxy.constants import ChannelMetadataField, ChannelState
from apps.proxy.redis_keys import RedisKeys


class FakeAssignmentRedis:
    """In-memory Redis for channel_stream assignment tests."""

    def __init__(self):
        self._strings = {}
        self._hashes = {}

    def _decode(self, value):
        if isinstance(value, bytes):
            return value.decode()
        return value

    def get(self, key):
        value = self._strings.get(key)
        if value is None:
            return None
        if isinstance(value, int):
            return str(value).encode()
        return str(value).encode()

    def set(self, key, value):
        self._strings[key] = value

    def delete(self, key):
        self._strings.pop(key, None)
        self._hashes.pop(key, None)

    def exists(self, key):
        return key in self._strings or key in self._hashes

    def hget(self, key, field):
        return self._hashes.get(key, {}).get(field)

    def hdel(self, key, *fields):
        # Added by Phase 2 stage 2d-4 for MetadataOnlyReleaseTests below. Its
        # absence before then was itself one of the three proofs R8 gives that
        # nothing in the tree observed issue #190's five ranges.
        bucket = self._hashes.get(key)
        if not bucket:
            return 0
        removed = 0
        for field in fields:
            if bucket.pop(field, None) is not None:
                removed += 1
        return removed

    def hset(self, key, mapping=None, **kwargs):
        bucket = self._hashes.setdefault(key, {})
        if mapping:
            bucket.update(mapping)
        bucket.update(kwargs)

    def incr(self, key):
        current = int(self._decode(self.get(key)) or 0)
        current += 1
        self._strings[key] = current
        return current

    def decr(self, key):
        current = int(self._decode(self.get(key)) or 0)
        current -= 1
        self._strings[key] = current
        return current


class ChannelGetStreamAssignmentTests(TestCase):
    def setUp(self):
        self.redis = FakeAssignmentRedis()
        self.account = M3UAccount.objects.create(
            name="assignment-test",
            account_type="XC",
            username="user",
            password="pass",
            max_streams=5,
        )
        self.profile = M3UAccountProfile.objects.get(
            m3u_account=self.account, is_default=True
        )
        self.profile.max_streams = 2
        self.profile.save()

        self.stream = Stream.objects.create(
            name="Test Stream",
            url="http://example.com/live/user/pass/1.ts",
            m3u_account=self.account,
        )
        self.channel = Channel.objects.create(channel_number=501, name="Assignment Ch")
        ChannelStream.objects.create(channel=self.channel, stream=self.stream, order=0)

        self.metadata_key = RedisKeys.channel_metadata(str(self.channel.uuid))

    def _seed_assignment(self):
        self.redis.set(f"channel_stream:{self.channel.id}", self.stream.id)
        self.redis.set(f"stream_profile:{self.stream.id}", self.profile.id)

    def _relay_snapshot(self):
        """Answer channel_snapshot from the fake Redis these tests seed.

        Phase 1 PR 7 moved "is the proxy running" off a direct metadata
        read and onto GET /proxy/relay/channels/<uuid>?fields=state. The
        metadata hash is still where the relay reads it and still what
        these tests seed; only who reads it changed. Without this the
        call leaves the process, is refused, and every state-dependent
        assertion below silently becomes an assertion about a relay
        outage instead.
        """
        from apps.proxy import relay_client

        reusable = (
            ChannelState.ACTIVE,
            ChannelState.WAITING_FOR_CLIENTS,
            ChannelState.BUFFERING,
            ChannelState.INITIALIZING,
            ChannelState.CONNECTING,
        )

        def _snapshot(identifier, **kwargs):
            if not self.redis.exists(self.metadata_key):
                return relay_client.ChannelSnapshot(
                    present=False, active=False, reachable=True
                )
            state = self.redis.hget(
                self.metadata_key, ChannelMetadataField.STATE
            )
            return relay_client.ChannelSnapshot(
                present=True, active=state in reusable, reachable=True
            )

        return patch(
            "apps.proxy.relay_client.channel_snapshot", side_effect=_snapshot
        )

    @patch("apps.channels.models.RedisClient.get_client")
    @patch("apps.channels.models.reserve_profile_slot")
    def test_reuses_assignment_when_proxy_active(
        self, mock_reserve, mock_get_client
    ):
        mock_get_client.return_value = self.redis
        self._seed_assignment()
        self.redis.hset(
            self.metadata_key,
            {ChannelMetadataField.STATE: ChannelState.ACTIVE},
        )

        with self._relay_snapshot():
            stream_id, profile_id, error, slot_reserved = self.channel.get_stream()

        self.assertEqual(stream_id, self.stream.id)
        self.assertEqual(profile_id, self.profile.id)
        self.assertIsNone(error)
        self.assertFalse(slot_reserved)
        mock_reserve.assert_not_called()

    @patch("apps.channels.models.RedisClient.get_client")
    @patch("apps.channels.models.reserve_profile_slot")
    def test_reuses_assignment_during_init_before_metadata(
        self, mock_reserve, mock_get_client
    ):
        mock_get_client.return_value = self.redis
        self._seed_assignment()

        with self._relay_snapshot():
            stream_id, profile_id, error, slot_reserved = self.channel.get_stream()

        self.assertEqual(stream_id, self.stream.id)
        self.assertEqual(profile_id, self.profile.id)
        self.assertIsNone(error)
        self.assertFalse(slot_reserved)
        mock_reserve.assert_not_called()

    @patch("apps.channels.models.RedisClient.get_client")
    @patch("apps.channels.models.release_profile_slot")
    @patch("apps.channels.models.reserve_profile_slot")
    def test_releases_stale_assignment_when_proxy_stopped(
        self, mock_reserve, mock_release, mock_get_client
    ):
        mock_get_client.return_value = self.redis
        mock_reserve.return_value = (True, 1, None)
        self._seed_assignment()
        self.redis.hset(
            self.metadata_key,
            {ChannelMetadataField.STATE: ChannelState.STOPPED},
        )

        with self._relay_snapshot():
            stream_id, profile_id, error, slot_reserved = self.channel.get_stream()

        mock_release.assert_called_once_with(self.profile.id, self.redis)
        mock_reserve.assert_called_once()
        self.assertEqual(stream_id, self.stream.id)
        self.assertEqual(profile_id, self.profile.id)
        self.assertTrue(slot_reserved)

    @patch("apps.channels.models.RedisClient.get_client")
    def test_stream_assignment_is_reusable_during_init_pending(self, mock_get_client):
        mock_get_client.return_value = self.redis
        self._seed_assignment()

        with self._relay_snapshot():
            self.assertTrue(
                self.channel._stream_assignment_is_reusable(self.redis, self.stream.id)
            )

    @patch("apps.channels.models.RedisClient.get_client")
    def test_stream_assignment_not_reusable_when_stopped(self, mock_get_client):
        mock_get_client.return_value = self.redis
        self._seed_assignment()
        self.redis.hset(
            self.metadata_key,
            {ChannelMetadataField.STATE: ChannelState.STOPPED},
        )

        with self._relay_snapshot():
            self.assertFalse(
                self.channel._stream_assignment_is_reusable(self.redis, self.stream.id)
            )


class MetadataOnlyReleaseTests(TestCase):
    """Issue #190's five ranges are gone, and this is what that changed.

    Phase 2 stage 2d-4 deleted every read of and write to
    live:channel:<uuid>:metadata from apps/channels/models.py. Before it,
    release_stream()'s recovery branch (:694-721) could rebuild a stream_id and
    a profile_id from that hash when the Django-owned channel_stream: key was
    already gone, release the provider slot and report success. After it, the
    branch is gone and release_stream() reports failure instead.

    NOTHING ELSE IN THE TREE OBSERVES THAT CHANGE. Every other caller of
    release_stream() seeds the primary Django-owned keys, which is exactly the
    branch that skipped all four fallback reads; no test ever asserted the
    hdel; and two of the fakes had no hget or hdel at all -- the 2d-4 plan's
    ruling R8 records the audit. The delete was test-invisible in BOTH
    directions, which is why this test exists rather than a green suite being
    taken as evidence.

    The reversion that makes it bite is therefore the :694-721 recovery branch,
    NOT the :745-750 read: with no channel_stream: key seeded, release_stream()
    takes the first branch and never reaches :745-750 at all.
    """

    def setUp(self):
        self.account = M3UAccount.objects.create(name="meta-only", max_streams=1)
        self.profile = M3UAccountProfile.objects.create(
            m3u_account=self.account, name="p", max_streams=1,
            search_pattern="", replace_pattern="",
        )
        self.stream = Stream.objects.create(
            name="s", url="http://e/s", m3u_account=self.account
        )
        self.channel = Channel.objects.create(name="c", channel_number=1)
        ChannelStream.objects.create(channel=self.channel, stream=self.stream, order=0)
        self.redis = FakeAssignmentRedis()
        self.metadata_key = RedisKeys.channel_metadata(str(self.channel.uuid))
        # ONLY the relay's metadata hash: no channel_stream:, no stream_profile:.
        # This is precisely the shape the deleted recovery branch existed for.
        self.redis.hset(
            self.metadata_key,
            {
                ChannelMetadataField.STREAM_ID: str(self.stream.id),
                ChannelMetadataField.M3U_PROFILE: str(self.profile.id),
            },
        )

    @patch("apps.channels.models.release_profile_slot")
    @patch("apps.channels.models.RedisClient.get_client")
    def test_a_metadata_only_assignment_is_no_longer_recoverable(
        self, mock_get_client, mock_release
    ):
        mock_get_client.return_value = self.redis

        self.assertIs(self.channel.release_stream(), False)

        # And the slot is NOT released, which is the consequence that matters:
        # the deleted branch called release_profile_slot() on the id it had
        # recovered from the hash.
        mock_release.assert_not_called()

    @patch("apps.channels.models.release_profile_slot")
    @patch("apps.channels.models.RedisClient.get_client")
    def test_the_metadata_hash_is_left_exactly_as_it_was_found(
        self, mock_get_client, mock_release
    ):
        # The other half of the delete: both hdel calls are gone, so a release
        # no longer reaches into a key the Go relay owns and never writes. The
        # fake's hdel (above) is what makes this observable at all.
        mock_get_client.return_value = self.redis
        before = dict(self.redis._hashes[self.metadata_key])

        self.channel.release_stream()

        self.assertEqual(self.redis._hashes[self.metadata_key], before)
