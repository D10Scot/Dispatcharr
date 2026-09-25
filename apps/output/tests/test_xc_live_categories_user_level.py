"""Regression test for #85: xc_get_live_categories' has-profiles branch
filtered `channels__user_level` exactly (`== 0`) where the no-profile
branch, the admin branch, and xc_get_live_streams all use `__lte`. A
level-1 user with at least one Channel Profile could list a level-1
channel via get_live_streams, but the channel's category never appeared
in get_live_categories.
"""

from uuid import uuid4

from django.test import RequestFactory, TestCase

from apps.accounts.models import User
from apps.channels.models import (
    Channel,
    ChannelGroup,
    ChannelProfile,
    ChannelProfileMembership,
)
from apps.output.views import xc_get_live_categories, xc_get_live_streams


class XcLiveCategoriesUserLevelTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.request = self.factory.get("/player_api.php")
        self.profile = ChannelProfile.objects.create(
            name=f"cat-profile-{uuid4().hex[:8]}"
        )
        # New profiles auto-include every existing channel via a post_save
        # signal; none exist yet at this point, but clear defensively so
        # only the memberships this test creates below are in play.
        ChannelProfileMembership.objects.filter(channel_profile=self.profile).delete()
        self.user = User.objects.create_user(
            username=f"xc-cat-{uuid4().hex[:8]}",
            password="pass",
            user_level=1,
        )
        self.user.channel_profiles.add(self.profile)

    def _channel_in_profile(self, group, user_level):
        channel = Channel.objects.create(
            channel_group=group,
            name=f"Ch {uuid4().hex[:8]}",
            channel_number=1.0,
            user_level=user_level,
        )
        ChannelProfileMembership.objects.create(
            channel_profile=self.profile,
            channel=channel,
            enabled=True,
        )
        return channel

    def test_profiled_user_sees_the_category_of_every_channel_it_can_list(self):
        group = ChannelGroup.objects.create(name=f"Group {uuid4().hex[:8]}")
        channel = self._channel_in_profile(group, user_level=1)

        # Premise: the channel really is visible to this user via
        # get_live_streams, which already uses __lte everywhere. Without
        # this, a missing category could equally mean the channel was
        # filtered out for an unrelated reason.
        streams = xc_get_live_streams(self.request, self.user)
        self.assertIn(
            channel.id,
            [s["stream_id"] for s in streams],
            "premise: the level-1 channel must be listed by get_live_streams",
        )

        categories = xc_get_live_categories(self.user)
        self.assertIn(
            str(group.id),
            [c["category_id"] for c in categories],
            "a channel visible in get_live_streams must have a category",
        )

    def test_profiled_user_does_not_see_a_category_above_its_level(self):
        group = ChannelGroup.objects.create(name=f"Group {uuid4().hex[:8]}")
        self._channel_in_profile(group, user_level=2)

        categories = xc_get_live_categories(self.user)
        self.assertNotIn(
            str(group.id),
            [c["category_id"] for c in categories],
            "a level-1 user must not see a category whose only channel is level 2",
        )
