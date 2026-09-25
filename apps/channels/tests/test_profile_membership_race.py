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
        """Deterministic simulation of the reverse race: a `Channel`
        post_save receiver (standing in for a concurrent profile create,
        since the real race is between two unguarded `bulk_create`s and
        there is no `Channel`-side hook to race against otherwise) inserts
        `(profile, channel)` the instant the channel row is saved -- before
        the view's own `bulk_create` runs. The view must tolerate the
        pre-existing row and return 201, on all three of
        `ChannelViewSet.create`/`from_stream`'s `channel_profile_ids`
        branches: omitted (all-profiles, `api_views.py:877`/`:2074`),
        sentinel `[0]` (also all-profiles, `:887`/`:2084`) and a specific id
        list (`:902`/`:2099`) -- three of the plan's seven `ignore_conflicts`
        sites are otherwise never reached by this module, and reverting any
        one of them alone would stay green.

        At base, dropping `ignore_conflicts=True` on the omitted or sentinel
        branches surfaces as an uncaught `IntegrityError` (a 500 in
        production). The specific-ids branch already wraps its `bulk_create`
        in `try/except Exception`, so in production (`ATOMIC_REQUESTS =
        False`, so the view's `with transaction.atomic():` is the outermost
        transaction) it is caught and answered as a 400 that echoes the raw
        `duplicate key value violates unique constraint …` text, silently
        rolling back the channel the client asked for -- not a 500. Under
        this `TestCase`, that same `atomic()` block is a *nested* savepoint,
        so leaving it after the caught error runs `RELEASE SAVEPOINT`
        against a transaction PostgreSQL has already aborted, which raises
        an unhandled `InternalError: current transaction is aborted,
        commands ignored until end of transaction block` instead -- a
        test-harness artefact of the savepoint nesting, not the production
        failure mode, but still a correct red against this test's 201
        expectation.
        """
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

        cases = [
            ("omitted", None),
            ("sentinel [0]", [0]),
            ("specific [profile.id]", [profile.id]),
        ]
        channel_number = 902

        # Each subTest below deletes the channel it created (cascading to
        # its ChannelProfileMembership rows, apps/channels/models.py:875)
        # and, for from-stream, the Stream it created, once its own
        # assertions pass. Without this, iteration 2 and 3 would run against
        # a set the earlier iterations left behind: harmless for the exact
        # `channel_id`-scoped assertions here, but silently order-dependent
        # for any assertion a later change made less specific. A subTest
        # that FAILS needs no matching cleanup: Django's TestCase wraps each
        # subTest in its own savepoint and rolls it back on failure, so a
        # failing case's row (or the row a wrong edit made never exist, per
        # the break-checks below) never survives to the next iteration.
        for label, channel_profile_ids in cases:
            with self.subTest(f"channel create: {label}"):
                payload = {
                    "channel_number": channel_number,
                    "name": f"Race Channel B ({label})",
                }
                if channel_profile_ids is not None:
                    payload["channel_profile_ids"] = channel_profile_ids
                response = self.client.post(
                    "/api/channels/channels/", payload, format="json"
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
                channel_id = response.data["id"]
                self.assertEqual(
                    ChannelProfileMembership.objects.filter(
                        channel_profile=profile, channel_id=channel_id
                    ).count(),
                    1,
                )
                Channel.objects.filter(id=channel_id).delete()
            channel_number += 1

            with self.subTest(f"from-stream: {label}"):
                stream = Stream.objects.create(name=f"Race Stream ({label})")
                payload = {"stream_id": stream.id, "channel_number": channel_number}
                if channel_profile_ids is not None:
                    payload["channel_profile_ids"] = channel_profile_ids
                response = self.client.post(
                    "/api/channels/channels/from-stream/", payload, format="json"
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
                channel_id = response.data["id"]
                self.assertEqual(
                    ChannelProfileMembership.objects.filter(
                        channel_profile=profile, channel_id=channel_id
                    ).count(),
                    1,
                )
                Channel.objects.filter(id=channel_id).delete()
                stream.delete()
            channel_number += 1
