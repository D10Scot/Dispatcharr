"""Tests for #131: two recordings at an identical start_time.

`schedule_recording_task` (`apps/channels/signals.py`) used to call
`ClockedSchedule.objects.get_or_create(clocked_time=eta)` directly. That
table has no uniqueness beyond the primary key, so two `ClockedSchedule` rows
could exist for the exact same instant -- nothing in the schema stops it --
and a later `get_or_create` at that instant raised `MultipleObjectsReturned`.
The exception landed inside `schedule_task_on_save`'s own blanket
`except Exception` and was `print()`ed, not raised or logged: the `Recording`
still saved with a 201, but `task_id` was left `None` and the recording was
never scheduled, silently and permanently for that clock instant.

The fix (E-1's `core.scheduling.get_or_create_schedule`, applied here in
E-3) takes the oldest matching row instead of calling the bare `get_or_create`,
so a duplicate `clocked_time` no longer breaks scheduling. Failures that
still happen (a different exception, not #131's specific race) now reach
`logger.exception` at ERROR instead of a swallowed `print()`.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from django_celery_beat.models import ClockedSchedule, PeriodicTask

from apps.channels.models import Channel, Recording


class DuplicateClockedScheduleTests(TestCase):
    """A duplicate ClockedSchedule row at the same instant no longer leaves
    a Recording unscheduled."""

    def setUp(self):
        self.channel = Channel.objects.create(
            channel_number=1, name="Duplicate Clocked Channel"
        )

    def tearDown(self):
        PeriodicTask.objects.filter(name__startswith="dvr-recording-").delete()
        ClockedSchedule.objects.all().delete()

    def test_duplicate_clocked_rows_no_longer_leave_a_recording_unscheduled(self):
        eta = timezone.now() + timedelta(hours=2)
        # Two independent ClockedSchedule rows at the exact same instant --
        # the schema allows this; only get_or_create_schedule's own
        # oldest-row rule keeps a later lookup from raising
        # MultipleObjectsReturned.
        first = ClockedSchedule.objects.create(clocked_time=eta)
        ClockedSchedule.objects.create(clocked_time=eta)

        rec = Recording.objects.create(
            channel=self.channel,
            start_time=eta,
            end_time=eta + timedelta(hours=1),
        )

        self.assertEqual(rec.task_id, f"dvr-recording-{rec.id}")
        pt = PeriodicTask.objects.get(name=f"dvr-recording-{rec.id}")
        self.assertEqual(
            pt.clocked_id,
            first.id,
            "PeriodicTask must be bound to the oldest (lowest-id) duplicate "
            "ClockedSchedule row, not create a third or bind to the newer one.",
        )


class RecordingSchedulingFailureLoggingTests(TestCase):
    """A genuine scheduling failure is now logged at ERROR, not printed."""

    def setUp(self):
        self.channel = Channel.objects.create(
            channel_number=2, name="Scheduling Failure Channel"
        )

    def test_a_recording_scheduling_failure_is_logged_at_error_not_printed(self):
        future = timezone.now() + timedelta(hours=1)

        with patch(
            "apps.channels.signals.schedule_recording_task",
            side_effect=Exception("boom"),
        ):
            with self.assertLogs("apps.channels.signals", "ERROR") as cm:
                Recording.objects.create(
                    channel=self.channel,
                    start_time=future,
                    end_time=future + timedelta(hours=1),
                )

        self.assertTrue(
            any("Error in post_save signal" in line for line in cm.output),
            cm.output,
        )
