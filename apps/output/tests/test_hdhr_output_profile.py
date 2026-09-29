"""The HDHR output-profile resolver ignores HLS profiles (Phase 4a-1d).

apps/hdhr has no tests of its own; dispatcharr/test_discovery.py routes it to
apps.output and apps.channels."""

from django.test import TestCase

from apps.hdhr.api_views import _resolve_hdhr_output_profile_id
from core.models import CoreSettings, OutputProfile, STREAM_SETTINGS_KEY


class HdhrResolverIgnoresHlsProfilesTests(TestCase):
    def _automatic(self):
        row, _ = OutputProfile.objects.get_or_create(
            name="HLS (Automatic)",
            defaults={
                "hls_mode": "automatic",
                "command": "ffmpeg",
                "parameters": "(built by the relay)",
                "locked": True,
                "is_active": True,
            },
        )
        OutputProfile.objects.filter(id=row.id).update(hls_mode="automatic", is_active=True)
        return row

    def test_the_hdhr_resolver_ignores_an_hls_profile_from_the_url_and_the_default(self):
        row = self._automatic()
        with self.assertLogs("apps.hdhr.api_views", level="WARNING") as logs:
            self.assertIsNone(_resolve_hdhr_output_profile_id(row.id))
        self.assertIn("not found or inactive", logs.output[0])

        settings_row, _ = CoreSettings.objects.get_or_create(
            key=STREAM_SETTINGS_KEY, defaults={"name": "Stream Settings", "value": {}}
        )
        settings_row.value = {**(settings_row.value or {}), "hdhr_output_profile_id": row.id}
        settings_row.save()
        with self.assertLogs("apps.hdhr.api_views", level="WARNING") as logs:
            self.assertIsNone(_resolve_hdhr_output_profile_id(None))
        self.assertIn("not found or inactive", logs.output[0])
