"""next-source's `capacity` object (Phase 4a-1c, spec § Slot reclaim, step 1).

The all-profiles-full refusal names the profiles that blocked the tune, so the
relay can take back a channel nobody is watching on one of them and ask once
more. It is read-only and advisory: the reservation is still the slot script's.
"""

from unittest.mock import patch

from apps.channels.models import Channel, ChannelStream, Stream
from apps.m3u.connection_pool import (
    ALL_PROFILES_FULL,
    get_profile_credential_fingerprint,
    profile_connections_key,
    server_group_connections_key,
)
from apps.m3u.models import M3UAccount, M3UAccountProfile, ServerGroup
from apps.proxy.tests.test_next_source_api import RelayApiTestCase


def _cap_profile(profile, max_streams):
    M3UAccountProfile.objects.filter(pk=profile.pk).update(max_streams=max_streams)
    profile.refresh_from_db()


class NextSourceCapacityTests(RelayApiTestCase):
    def _fill(self, profile, count=1):
        self.redis._strings[profile_connections_key(profile.id)] = count

    def _blocked_answer(self, identifier=None):
        response = self._post(
            self.next_source_path(identifier or str(self.channel.uuid)), {}
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _pooled_channel(self, *, number):
        """Two XC accounts sharing one login in one ServerGroup, the channel's
        stream on account 1. Returns (channel, profile 1, profile 2, group)."""
        group = ServerGroup.objects.create(name=f"capacity-pool-{number}")
        profiles = []
        for index in (1, 2):
            account = M3UAccount.objects.create(
                name=f"capacity-xc-{number}-{index}",
                account_type="XC",
                username="user",
                password="pass",
                server_url="http://xc.example.com",
                server_group=group,
                max_streams=5,
            )
            profile = M3UAccountProfile.objects.get(
                m3u_account=account, is_default=True
            )
            _cap_profile(profile, 1)
            profiles.append(profile)
        stream = Stream.objects.create(
            name=f"Capacity Pooled Stream {number}",
            url=f"http://example.com/live/user/pass/{number}.ts",
            m3u_account=profiles[0].m3u_account,
            stream_profile=self.stream_profile_obj,
            stream_hash=f"capacity-pooled-hash-{number}",
        )
        channel = Channel.objects.create(
            channel_number=9300 + number,
            name=f"Capacity Pooled Channel {number}",
            stream_profile=self.stream_profile_obj,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
        return channel, profiles[0], profiles[1], group

    def _credential_key(self, profile, group):
        return server_group_connections_key(
            group.id, get_profile_credential_fingerprint(profile)
        )

    def test_a_blocked_channel_names_its_full_profile(self):
        _cap_profile(self.m3u_profile, 1)
        self._fill(self.m3u_profile)

        calls = []
        real_walk = Channel.blocking_profile_ids
        before = {}

        def recording_walk(channel):
            before.update(self.redis._strings)
            result = real_walk(channel)
            calls.append(result)
            return result

        with patch.object(Channel, "blocking_profile_ids", recording_walk):
            body = self._blocked_answer()

        self.assertIsNone(body["source"])
        self.assertEqual(body["error"], ALL_PROFILES_FULL)
        self.assertEqual(
            body["capacity"],
            {"blocked": True, "profile_ids": [self.m3u_profile.id]},
        )
        # The blocking walk is read-only: the keyspace (slot_version:* keys
        # included) the refusal left is exactly the keyspace after the walk.
        self.assertEqual(len(calls), 1)
        self.assertEqual(before, self.redis._strings)

    def test_credential_siblings_are_named(self):
        channel, one, two, group = self._pooled_channel(number=1)
        # Account 2's profile holds the login's one credential slot; account
        # 1's own counter has room.
        self.redis._strings[self._credential_key(one, group)] = 1
        body = self._blocked_answer(str(channel.uuid))
        self.assertEqual(
            body["capacity"],
            {"blocked": True, "profile_ids": sorted([one.id, two.id])},
        )

    def test_a_full_profile_whose_login_has_room_names_no_sibling(self):
        channel, one, two, group = self._pooled_channel(number=2)
        # R64: full on its own counter, the credential counter below its cap.
        self.redis._strings[profile_connections_key(one.id)] = 1
        self.redis._strings[self._credential_key(one, group)] = 0
        body = self._blocked_answer(str(channel.uuid))
        self.assertEqual(
            body["capacity"], {"blocked": True, "profile_ids": [one.id]}
        )

    def test_a_profile_full_on_both_counters_names_no_sibling(self):
        channel, one, two, group = self._pooled_channel(number=3)
        # R72: full on its own counter AND the shared credential counter at
        # its cap. The slot script answers profile_full first, and stopping a
        # sibling's channel cannot unblock this profile.
        self.redis._strings[profile_connections_key(one.id)] = 1
        self.redis._strings[self._credential_key(one, group)] = 1
        body = self._blocked_answer(str(channel.uuid))
        self.assertEqual(
            body["capacity"], {"blocked": True, "profile_ids": [one.id]}
        )

    def test_a_blocked_stream_preview_names_its_full_profile(self):
        _cap_profile(self.m3u_profile, 1)
        self._fill(self.m3u_profile)
        body = self._blocked_answer(self.stream_a.stream_hash)
        self.assertIsNone(body["source"])
        self.assertEqual(body["error"], ALL_PROFILES_FULL)
        self.assertEqual(
            body["capacity"],
            {"blocked": True, "profile_ids": [self.m3u_profile.id]},
        )

    def test_an_answered_tune_carries_null_capacity(self):
        body = self._blocked_answer()
        self.assertIsNotNone(body["source"])
        self.assertIn("capacity", body)
        self.assertIsNone(body["capacity"])

    def test_a_refusal_that_is_not_maxed_out_carries_null_capacity(self):
        empty = Channel.objects.create(
            channel_number=9399,
            name="Capacity No Streams",
            stream_profile=self.stream_profile_obj,
        )
        body = self._blocked_answer(str(empty.uuid))
        self.assertIsNone(body["source"])
        self.assertEqual(body["error"], "No streams assigned to channel")
        self.assertIn("capacity", body)
        self.assertIsNone(body["capacity"])

    def test_the_capacity_field_is_in_the_schema(self):
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(request=None, public=True)
        components = schema["components"]["schemas"]
        self.assertEqual(
            sorted(components["NextSourceCapacity"]["properties"]),
            ["blocked", "profile_ids"],
        )
        self.assertIn("capacity", components["NextSourceResponse"]["properties"])

    def test_blocking_profiles_walk_the_profiles_get_stream_tries(self):
        # Decision 1's drift guard. Five streams, one per skip get_stream()
        # makes, so a blocking walk that stopped skipping (or started skipping
        # something else) names a different set than get_stream() examined.
        channel = Channel.objects.create(
            channel_number=9398,
            name="Capacity Walk Channel",
            stream_profile=self.stream_profile_obj,
        )
        every_profile = []

        def stream_on(account, order, tag):
            stream = Stream.objects.create(
                name=f"Capacity Walk {tag}",
                url=f"http://example.com/walk-{tag}.ts",
                m3u_account=account,
                stream_profile=self.stream_profile_obj,
                stream_hash=f"capacity-walk-{tag}",
            )
            ChannelStream.objects.create(channel=channel, stream=stream, order=order)
            return stream

        # 1. An active account: default profile plus one more active profile
        #    and one INACTIVE non-default profile (the is_active filter).
        active = M3UAccount.objects.create(
            name="capacity-walk-active", account_type="STD", max_streams=1
        )
        default = M3UAccountProfile.objects.get(m3u_account=active, is_default=True)
        extra = M3UAccountProfile.objects.create(
            m3u_account=active, name="extra", max_streams=1, is_active=True,
            search_pattern="", replace_pattern="",
        )
        inactive_profile = M3UAccountProfile.objects.create(
            m3u_account=active, name="inactive", max_streams=1, is_active=False,
            search_pattern="", replace_pattern="",
        )
        _cap_profile(default, 1)
        every_profile += [default, extra, inactive_profile]
        stream_on(active, 0, "active")

        # 2. An inactive account.
        dead = M3UAccount.objects.create(
            name="capacity-walk-dead", account_type="STD", max_streams=1, is_active=False
        )
        dead_default = M3UAccountProfile.objects.get(m3u_account=dead, is_default=True)
        _cap_profile(dead_default, 1)
        every_profile.append(dead_default)
        stream_on(dead, 1, "dead")

        # 3. An account whose default profile is inactive.
        nodefault = M3UAccount.objects.create(
            name="capacity-walk-nodefault", account_type="STD", max_streams=1
        )
        nd_default = M3UAccountProfile.objects.get(
            m3u_account=nodefault, is_default=True
        )
        _cap_profile(nd_default, 1)
        M3UAccountProfile.objects.filter(pk=nd_default.pk).update(is_active=False)
        nd_extra = M3UAccountProfile.objects.create(
            m3u_account=nodefault, name="nd-extra", max_streams=1, is_active=True,
            search_pattern="", replace_pattern="",
        )
        every_profile += [nd_default, nd_extra]
        stream_on(nodefault, 2, "nodefault")

        # 4. A stream with no account.
        orphan = stream_on(active, 3, "orphan")
        Stream.objects.filter(pk=orphan.pk).update(m3u_account=None)

        # Every profile in the fixture, the skipped ones included, at its cap.
        for profile in every_profile:
            self.redis._strings[profile_connections_key(profile.id)] = 1

        recorded = []

        def refuse(profile, redis_client):
            recorded.append(profile.id)
            return False, 1, "profile_full"

        with patch("apps.channels.models.reserve_profile_slot", refuse):
            channel_stream_id, _profile_id, reason, _reserved = channel.get_stream()
        self.assertIsNone(channel_stream_id)
        self.assertEqual(reason, ALL_PROFILES_FULL)

        self.assertEqual(sorted(set(recorded)), channel.blocking_profile_ids())
        # And the skips are real: the walk examined the two active profiles of
        # the active account, and none of the inactive or orphaned ones.
        self.assertIn(default.id, recorded)
        self.assertIn(extra.id, recorded)
        self.assertNotIn(inactive_profile.id, recorded)
        self.assertNotIn(dead_default.id, recorded)
        self.assertNotIn(nd_default.id, recorded)
