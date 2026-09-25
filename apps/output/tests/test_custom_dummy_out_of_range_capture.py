"""Regression tests for #90 (dup #211): generate_custom_dummy_programs crashed
the streamed /output/epg export when a captured minute, hour, day or year was
out of range. The fix treats an out-of-range capture as "no time"/"no date",
exactly as an unparseable capture already was, instead of letting the
ValueError/OverflowError from datetime construction escape the generator.
"""

from uuid import uuid4

from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.channels.models import ChannelGroup
from apps.epg.models import EPGData, EPGSource
from apps.output.epg import generate_custom_dummy_programs
from apps.output.tests.test_views import OutputEndpointTestMixin, _response_text


class CustomDummyOutOfRangeCaptureTests(SimpleTestCase):
    """Direct calls into generate_custom_dummy_programs; each subTest is one
    counterexample from #90's/#211's table, verified to raise at seed
    (a54b09a9)."""

    def _call(self, channel_name, custom_properties, now=None):
        return generate_custom_dummy_programs(
            channel_id="1",
            channel_name=channel_name,
            now=now or timezone.now(),
            num_days=1,
            custom_properties=custom_properties,
        )

    def test_out_of_range_minute_is_treated_as_no_time_instead_of_raising(self):
        custom_properties = {
            "title_pattern": r"(?<title>.+)",
            "time_pattern": r"(?<hour>\d+):(?<minute>\d+)",
            "timezone": "UTC",
        }
        huge_minute_str = "9" * 20
        cases = [
            ("Team A @ 10:75", 10, 75),
            ("Ch 10:99", 10, 99),
            (f"C 10:{huge_minute_str}", 10, int(huge_minute_str)),
        ]
        for channel_name, hour, minute in cases:
            with self.subTest(channel_name=channel_name):
                with self.assertLogs("apps.output.epg", "WARNING") as cm:
                    programs = self._call(channel_name, custom_properties)
                self.assertIsInstance(programs, list)
                self.assertTrue(
                    any(
                        f"Invalid time values: hour={hour}, minute={minute}" in record
                        for record in cm.output
                    ),
                    cm.output,
                )

    def test_twelve_hour_capture_past_midnight_is_treated_as_no_time(self):
        custom_properties = {
            "title_pattern": r"(?<title>.+)",
            "time_pattern": r"(?<hour>\d+):(?<minute>\d+)(?<ampm>[APap][Mm])",
            "timezone": "UTC",
        }
        channel_name = "X 13:30pm"
        with self.assertLogs("apps.output.epg", "WARNING") as cm:
            programs = self._call(channel_name, custom_properties)
        self.assertIsInstance(programs, list)
        # 13 is not a valid 12-hour value paired with pm, but the existing code
        # has no upper bound on the 12-hour digits; pm adds 12, landing on 25.
        self.assertTrue(
            any(
                "Invalid time values: hour=25, minute=30" in record
                for record in cm.output
            ),
            cm.output,
        )

    def test_impossible_calendar_date_is_treated_as_no_date(self):
        custom_properties = {
            "title_pattern": r"(?<title>.+)",
            "time_pattern": r"@\s*(?<hour>\d+):(?<minute>\d+)",
            "date_pattern": r"(?<month>\d+)/(?<day>\d+)",
            "timezone": "UTC",
        }
        channel_name = "Game 2/31 @ 10:30"
        with self.assertLogs("apps.output.epg", "WARNING") as cm:
            programs = self._call(channel_name, custom_properties)
        self.assertIsInstance(programs, list)
        self.assertTrue(
            any(
                "Invalid date values: month=2, day=31" in record
                for record in cm.output
            ),
            cm.output,
        )

    def test_out_of_range_year_is_treated_as_no_date(self):
        # A time_pattern that also matches is required: date_info alone
        # (without time_info) never reaches the datetime(year, ...)
        # construction that raises at seed — both must be present together.
        custom_properties = {
            "title_pattern": r"(?<title>.+)",
            "time_pattern": r"(?<hour>\d+):(?<minute>\d+)",
            "date_pattern": r"(?<month>\d+)/(?<day>\d+)/(?<year>\d+)",
            "timezone": "UTC",
        }
        cases = [
            ("X 1/2/0 10:30", 0),
            ("X 1/2/99999 10:30", 99999),
        ]
        for channel_name, year in cases:
            with self.subTest(channel_name=channel_name):
                with self.assertLogs("apps.output.epg", "WARNING") as cm:
                    programs = self._call(channel_name, custom_properties)
                self.assertIsInstance(programs, list)
                self.assertTrue(
                    any(
                        f"Invalid date values: month=1, day=2, year={year}" in record
                        for record in cm.output
                    ),
                    cm.output,
                )

    def test_edge_year_one_step_from_datetime_limits_is_treated_as_no_date(self):
        """The category-I planner's prototype found these two channel names
        still raise with the naive 1..9999 year bound; both must pass with
        the plan's 2..9998 bound (see break-check (c))."""
        custom_properties = {
            "title_pattern": r"(?<title>.+)",
            "time_pattern": r"(?<hour>\d+):(?<minute>\d+)",
            "date_pattern": r"(?<month>\d+)/(?<day>\d+)/(?<year>\d+)",
        }
        cases = [
            ("Ch 23:30 12/31/9999", "UTC", 12, 31, 9999),
            ("Ch 0:10 1/1/1", "Asia/Kolkata", 1, 1, 1),
        ]
        for channel_name, tz, month, day, year in cases:
            with self.subTest(channel_name=channel_name):
                props = {**custom_properties, "timezone": tz}
                with self.assertLogs("apps.output.epg", "WARNING") as cm:
                    programs = self._call(channel_name, props)
                self.assertIsInstance(programs, list)
                self.assertTrue(
                    any(
                        f"Invalid date values: month={month}, day={day}, year={year}" in record
                        for record in cm.output
                    ),
                    cm.output,
                )


class CustomDummyExportSurvivesBadChannelNameTests(OutputEndpointTestMixin, TestCase):
    """One dummy source configured with #90's patterns, two channels: the
    out-of-range channel must not abort the streamed XMLTV export for the
    well-formed one."""

    def setUp(self):
        super().setUp()
        self.group = ChannelGroup.objects.create(name=f"Dummy Group {uuid4().hex[:8]}")
        self.profile = self._create_isolated_profile("dummy-epg-c1")

        self.epg_source = EPGSource.objects.create(
            name="Dummy #90 patterns",
            source_type="dummy",
            custom_properties={
                "title_pattern": r"(?<title>.+)",
                "time_pattern": r"(?<hour>\d+):(?<minute>\d+)",
                "timezone": "UTC",
            },
        )
        self.epg_data = EPGData.objects.create(
            tvg_id=f"dummy-c1-{uuid4().hex[:8]}",
            name="Dummy EPG",
            epg_source=self.epg_source,
        )

        self.bad_channel = self._add_channel_to_profile(
            self.profile,
            self.group,
            name="Team A @ 10:75",
            channel_number=1.0,
            tvg_id="BadChannel",
            epg_data=self.epg_data,
        )
        self.good_channel = self._add_channel_to_profile(
            self.profile,
            self.group,
            name="Team B @ 10:30",
            channel_number=2.0,
            tvg_id="GoodChannel",
            epg_data=self.epg_data,
        )

    def _epg_url(self, query="tvg_id_source=tvg_id&days=0&prev_days=0"):
        base = reverse("output:epg_endpoint", kwargs={"profile_name": self.profile.name})
        return f"{base}?{query}"

    def test_one_out_of_range_channel_name_does_not_abort_the_xmltv_export(self):
        client = Client()
        response = client.get(self._epg_url())

        self.assertEqual(response.status_code, 200)
        content = _response_text(response)

        self.assertTrue(
            content.rstrip().endswith("</tv>"),
            "the bad channel's crash must not truncate the streamed body",
        )
        self.assertRegex(
            content,
            r'<programme[^>]*channel="GoodChannel"',
            "the well-formed channel's programme must still be exported",
        )
