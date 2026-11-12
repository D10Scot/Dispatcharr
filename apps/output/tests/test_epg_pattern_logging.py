"""Custom dummy EPG patterns come from `custom_properties` and are unrestricted
text, so a pattern can contain a login. It must reach no log line, in the
loaded, converted or invalid-regex paths."""

from django.test import SimpleTestCase
from django.utils import timezone

from apps.output import epg
from core.tests.test_credential_logging_url_sites import assert_no_secret, capture


class EpgPatternLoggingTests(SimpleTestCase):
    def call(self, **props):
        base = {"timezone": "UTC"}
        base.update(props)
        return epg.generate_custom_dummy_programs(
            channel_id="1",
            channel_name="News Show",
            now=timezone.now(),
            num_days=1,
            custom_properties=base,
        )

    def test_valid_patterns_are_not_logged(self):
        with capture(epg.logger) as logs:
            self.call(
                title_pattern=r"(?<title>News) Show|fakeuser/fakepass",
                time_pattern=r"(?<hour>x)|fakesecret",
                date_pattern=r"(?<month>y)|fakesecret",
            )
        assert_no_secret(self, logs.records)

    def test_invalid_patterns_are_not_logged(self):
        for field in ("title_pattern", "time_pattern", "date_pattern"):
            with self.subTest(field):
                props = {"title_pattern": r"(?<title>.+)", field: r"(fakeuser/fakepass"}
                with capture(epg.logger) as logs:
                    self.call(**props)
                assert_no_secret(self, logs.records)
