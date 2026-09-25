"""Regression tests for #91 (dup #212): xc_get_epg's ?limit= param 500s on
non-numeric or negative input instead of falling back to the default of 4.
"""

from datetime import timedelta
from uuid import uuid4

from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.channels.models import Channel, ChannelGroup
from apps.epg.models import EPGData, ProgramData
from apps.output.views import xc_get_epg


class XcEpgLimitGuardTests(TestCase):
    """Built like XcGetEpgCatchupGateTests (test_views.py:1271)."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username=f"xc-epg-limit-{uuid4().hex[:8]}",
            password="pass",
            user_level=10,
            custom_properties={"xc_password": "xcpass"},
        )
        self.group = ChannelGroup.objects.create(name=f"Group {uuid4().hex[:8]}")
        self.epg = EPGData.objects.create(tvg_id=f"limit-{uuid4().hex[:8]}", name="Limit EPG")
        self.channel = Channel.objects.create(
            name="Limit Guard Ch",
            channel_number=1,
            channel_group=self.group,
            user_level=0,
            epg_data=self.epg,
        )
        now = timezone.now()
        # Six upcoming programmes so a fallback to the default of 4 is
        # observable (a bug that instead returned all six would pass a
        # weaker assertion).
        for i in range(6):
            ProgramData.objects.create(
                epg=self.epg,
                start_time=now + timedelta(minutes=30 * i),
                end_time=now + timedelta(minutes=30 * (i + 1)),
                title=f"Upcoming {i}",
            )

    def tearDown(self):
        from django.core.cache import cache

        cache.clear()

    def _listings(self, *, limit_value):
        params = {
            "action": "get_short_epg",
            "stream_id": str(self.channel.id),
            "limit": limit_value,
        }
        request = self.factory.get("/player_api.php", params)
        return xc_get_epg(request, self.user, short=True)["epg_listings"]

    def test_non_numeric_limit_falls_back_to_default_instead_of_500(self):
        listings = self._listings(limit_value="abc")
        self.assertEqual(len(listings), 4)

    def test_negative_limit_falls_back_to_default_instead_of_500(self):
        listings = self._listings(limit_value="-5")
        self.assertEqual(len(listings), 4)
