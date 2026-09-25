"""#138: a recurring rule materialises one Recording (and one ClockedSchedule/PeriodicTask
pair) per matching day up to its own end_date, synchronously, inside the request. The
serializer caps end_date so the request stays bounded; sync_recurring_rule_impl is unchanged.

The clock is frozen for the whole class: the serializer computes "today" at request time and
these tests compute it in setUp, so a real midnight between the two would make an over-cap
end_date land exactly on the cap and pass on correct code.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django_celery_beat.models import PeriodicTask
from rest_framework.test import APIClient

from apps.channels.models import Channel, Recording, RecurringRecordingRule
# The cap is pinned here as a number, deliberately not imported from the serializer.
from core.models import CoreSettings

RULES_URL = "/api/channels/recurring-rules/"
CAP_DAYS = 365
CAP_MESSAGE = f"End date must be no more than {CAP_DAYS} days from today"
# Noon UTC: the same calendar date in UTC (Django's TIME_ZONE in the test settings) and in
# every zone west of UTC+12, a different one in UTC+13/+14, which the last test relies on.
FROZEN_NOW = datetime(2026, 9, 24, 12, 0, tzinfo=dt_timezone.utc)


class RecurringRuleEndDateCapTests(TestCase):
    def setUp(self):
        patcher = mock.patch("django.utils.timezone.now", return_value=FROZEN_NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        User = get_user_model()
        self.admin = User.objects.create_user(username="cap_admin", password="pass")
        self.admin.user_level = 10
        self.admin.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.channel = Channel.objects.create(channel_number=1, name="Cap Channel")
        # The same "today" sync_recurring_rule_impl walks from (apps/channels/tasks.py).
        tz = ZoneInfo(CoreSettings.get_system_time_zone())
        self.today = FROZEN_NOW.astimezone(tz).date()

    def _payload(self, **overrides):
        payload = {
            "channel": self.channel.id,
            "days_of_week": [0, 1, 2, 3, 4, 5, 6],
            "start_time": "12:00:00",
            "end_time": "13:00:00",
            "start_date": (self.today - timedelta(days=2)).isoformat(),
            "end_date": (self.today + timedelta(days=14)).isoformat(),
            "name": "cap",
        }
        payload.update(overrides)
        return payload

    def _rows_for(self, rule_id):
        return Recording.objects.filter(custom_properties__rule__id=rule_id).count()

    def test_a_rule_past_the_cap_is_refused_before_it_materialises_anything(self):
        over = (self.today + timedelta(days=CAP_DAYS + 1)).isoformat()
        resp = self.client.post(RULES_URL, self._payload(end_date=over), format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn(CAP_MESSAGE, " ".join(resp.json().get("end_date", [])))
        self.assertEqual(RecurringRecordingRule.objects.count(), 0)
        self.assertEqual(Recording.objects.count(), 0)
        self.assertEqual(PeriodicTask.objects.filter(name__startswith="dvr-recording-").count(), 0)

    def test_a_rule_exactly_at_the_cap_is_accepted(self):
        at = (self.today + timedelta(days=CAP_DAYS)).isoformat()
        resp = self.client.post(RULES_URL, self._payload(end_date=at), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertGreaterEqual(self._rows_for(resp.json()["id"]), CAP_DAYS)

    def test_a_create_with_no_end_date_is_still_refused_as_required(self):
        payload = self._payload()
        del payload["end_date"]
        resp = self.client.post(RULES_URL, payload, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn("End date is required", resp.content.decode())
        self.assertEqual(RecurringRecordingRule.objects.count(), 0)

    def test_a_patch_that_leaves_end_date_alone_is_not_re_capped(self):
        # A row from before the cap, with an end_date the cap would now refuse.
        rule = RecurringRecordingRule.objects.create(
            channel=self.channel,
            days_of_week=[0, 1, 2, 3, 4, 5, 6],
            start_time="12:00:00",
            end_time="13:00:00",
            start_date=self.today,
            end_date=self.today + timedelta(days=CAP_DAYS + 30),
        )
        resp = self.client.patch(f"{RULES_URL}{rule.id}/", {"enabled": False}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        rule.refresh_from_db()
        self.assertFalse(rule.enabled)
        self.assertEqual(rule.end_date, self.today + timedelta(days=CAP_DAYS + 30))

    def test_a_patch_that_extends_end_date_past_the_cap_is_refused_and_changes_nothing(self):
        resp = self.client.post(RULES_URL, self._payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        rule_id = resp.json()["id"]
        before = self._rows_for(rule_id)
        self.assertGreaterEqual(before, 13)
        over = (self.today + timedelta(days=CAP_DAYS + 1)).isoformat()
        resp = self.client.patch(f"{RULES_URL}{rule_id}/", {"end_date": over}, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn(CAP_MESSAGE, " ".join(resp.json().get("end_date", [])))
        rule = RecurringRecordingRule.objects.get(pk=rule_id)
        self.assertEqual(rule.end_date, self.today + timedelta(days=14))
        self.assertEqual(self._rows_for(rule_id), before)

    def test_the_cap_counts_from_today_in_the_system_time_zone_not_django_s(self):
        # In UTC+14 the frozen instant is already the next calendar day, so the latest
        # accepted end_date is one day later than a Django-TIME_ZONE (UTC) "today" would allow.
        # The settings group is cached in Redis, which the transaction rollback does not
        # touch, so the zone is restored explicitly (the cleanup runs before the rollback).
        self.addCleanup(CoreSettings.set_system_time_zone, CoreSettings.get_system_time_zone())
        CoreSettings.set_system_time_zone("Pacific/Kiritimati")
        self.assertEqual(CoreSettings.get_system_time_zone(), "Pacific/Kiritimati")
        local_today = FROZEN_NOW.astimezone(ZoneInfo("Pacific/Kiritimati")).date()
        self.assertEqual(local_today, FROZEN_NOW.date() + timedelta(days=1))
        at = (local_today + timedelta(days=CAP_DAYS)).isoformat()
        resp = self.client.post(RULES_URL, self._payload(end_date=at, days_of_week=[0]), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
