"""#7 (dup #6): a concurrent-create race can duplicate a django_celery_beat
schedule row (neither `IntervalSchedule` nor `CrontabSchedule` has any
uniqueness constraint beyond the primary key). Once duplicated, the bare
`get_or_create()` this module used to call raises `MultipleObjectsReturned`
on every later call -- a permanent 500 on M3U/EPG source creation.

`get_or_create_schedule()` takes the oldest matching row instead of `get()`,
so a duplicate is tolerated rather than fatal.
"""

from django_celery_beat.models import CrontabSchedule, IntervalSchedule

from core.models import CoreSettings
from core.scheduling import create_or_update_periodic_task, get_or_create_schedule
from django.test import TestCase


class ScheduleDuplicateRowsTests(TestCase):
    def test_duplicate_interval_rows_no_longer_break_periodic_task_creation(self):
        first = IntervalSchedule.objects.create(every=1, period=IntervalSchedule.HOURS)
        second = IntervalSchedule.objects.create(every=1, period=IntervalSchedule.HOURS)
        lower_id = min(first.id, second.id)

        task = create_or_update_periodic_task(
            "test-duplicate-interval-task",
            "apps.m3u.tasks.some_task",
            interval_hours=1,
        )

        self.assertEqual(task.interval_id, lower_id)
        self.assertEqual(
            IntervalSchedule.objects.filter(every=1, period=IntervalSchedule.HOURS).count(),
            2,
        )

    def test_duplicate_crontab_rows_no_longer_break_periodic_task_creation(self):
        system_tz = CoreSettings.get_system_time_zone()
        first = CrontabSchedule.objects.create(
            minute="0",
            hour="3",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
            timezone=system_tz,
        )
        second = CrontabSchedule.objects.create(
            minute="0",
            hour="3",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
            timezone=system_tz,
        )
        lower_id = min(first.id, second.id)

        task = create_or_update_periodic_task(
            "test-duplicate-crontab-task",
            "apps.m3u.tasks.some_task",
            cron_expression="0 3 * * *",
        )

        self.assertEqual(task.crontab_id, lower_id)
        self.assertEqual(
            CrontabSchedule.objects.filter(
                minute="0",
                hour="3",
                day_of_week="*",
                day_of_month="*",
                month_of_year="*",
                timezone=system_tz,
            ).count(),
            2,
        )

    def test_get_or_create_schedule_creates_the_row_when_none_exists(self):
        # apps/m3u/migrations/0006 and apps/epg/migrations/0007 seed a
        # default every=24 row, so the table is never empty in a migrated
        # test DB; use an interval value no seeded row carries.
        self.assertFalse(
            IntervalSchedule.objects.filter(every=2, period=IntervalSchedule.HOURS).exists()
        )

        created = get_or_create_schedule(
            IntervalSchedule, every=2, period=IntervalSchedule.HOURS
        )

        self.assertEqual(
            IntervalSchedule.objects.filter(every=2, period=IntervalSchedule.HOURS).count(),
            1,
        )
        self.assertEqual(created.every, 2)
