"""Tests for #72: concurrent channel and profile creation can 500 on
`ChannelProfileMembership`'s `unique_together`.

`create_profile_memberships` (`apps/channels/signals.py`, a `ChannelProfile`
`post_save` receiver) and `ChannelViewSet.create`/`from_stream`
(`apps/channels/api_views.py`) each populate `ChannelProfileMembership` from
opposite sides -- one iterates every channel for a new profile, the other
iterates every profile for a new channel. Run together (a profile created
while a channel is being created, or the reverse) they can both try to
insert the same `(channel_profile, channel)` pair, and
`unique_together = ("channel_profile", "channel")` (`apps/channels/models.py`)
turned the loser into an unhandled `IntegrityError` -- a 500 for the request
whose `bulk_create` lost the race, or an unhandled exception out of the
`post_save` receiver.
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_save
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.channels.models import Channel, ChannelProfile, ChannelProfileMembership, Stream
from apps.channels.signals import create_profile_memberships

User = get_user_model()


class ProfileMembershipRaceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="race-admin", password="testpass123")
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_a_profile_created_concurrently_with_a_channel_does_not_raise(self):
        """Re-running the `ChannelProfile` post_save receiver for a profile
        that already has every channel's membership -- simulating a second,
        concurrent `ChannelProfile.save()` that raced the first -- must not
        raise, and must not duplicate the row."""
        channel = Channel.objects.create(channel_number=901, name="Race Channel A")
        profile = ChannelProfile.objects.create(name="Race Profile A")

        self.assertEqual(
            ChannelProfileMembership.objects.filter(
                channel_profile=profile, channel=channel
            ).count(),
            1,
        )

        with transaction.atomic():
            create_profile_memberships(ChannelProfile, profile, created=True)

        self.assertEqual(
            ChannelProfileMembership.objects.filter(
                channel_profile=profile, channel=channel
            ).count(),
            1,
        )

    def test_channel_create_tolerates_a_membership_a_concurrent_profile_create_inserted(self):
        """Deterministic simulation of the reverse race: a `ChannelProfile`
        post_save handler (standing in for a concurrent profile create)
        inserts `(profile, channel)` the instant the channel row is saved --
        before the view's own `bulk_create` runs for the "add to all
        profiles" default. The view must tolerate the pre-existing row
        rather than 500."""
        profile = ChannelProfile.objects.create(name="Race Profile B")

        def _simulate_concurrent_profile_create(sender, instance, created, **kwargs):
            if created:
                ChannelProfileMembership.objects.create(
                    channel_profile=profile, channel=instance
                )

        post_save.connect(
            _simulate_concurrent_profile_create,
            sender=Channel,
            dispatch_uid="test-race-concurrent-profile-create",
        )
        self.addCleanup(
            post_save.disconnect,
            _simulate_concurrent_profile_create,
            sender=Channel,
            dispatch_uid="test-race-concurrent-profile-create",
        )

        with self.subTest("channel create"):
            response = self.client.post(
                "/api/channels/channels/",
                {"channel_number": 902, "name": "Race Channel B"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
            channel_id = response.data["id"]
            self.assertEqual(
                ChannelProfileMembership.objects.filter(
                    channel_profile=profile, channel_id=channel_id
                ).count(),
                1,
            )

        with self.subTest("from-stream"):
            stream = Stream.objects.create(name="Race Stream")
            response = self.client.post(
                "/api/channels/channels/from-stream/",
                {"stream_id": stream.id, "channel_number": 903},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
            channel_id = response.data["id"]
            self.assertEqual(
                ChannelProfileMembership.objects.filter(
                    channel_profile=profile, channel_id=channel_id
                ).count(),
                1,
            )
