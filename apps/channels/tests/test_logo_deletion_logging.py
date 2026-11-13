"""Logo deletion logs a logo id and an exception type, never a path, a
filename or exception text.

A logo's `url` is an unrestricted text field and uploaded filenames are kept,
so a name such as `/data/logos/token=faketoken.png` is attacker- or
provider-shaped text that can carry a credential. The three deletion
endpoints used to log `os.path.basename(logo.url)` and `str(e)`.
"""

import logging
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.channels import api_views
from apps.channels.models import Logo
from core.tests.test_credential_logging_url_sites import assert_no_secret, capture

LOGO_URL = "/data/logos/token=faketoken.png"


class LogoDeletionLoggingTests(TestCase):
    def setUp(self):
        admin = User.objects.create_user(username="logo-log-admin", password="x")
        admin.user_level = 10
        admin.save()
        self.client = APIClient()
        self.client.force_authenticate(user=admin)
        self.logo = Logo.objects.create(name="l", url=LOGO_URL)

    def request(self, which):
        self.logo, _ = Logo.objects.get_or_create(name="l", url=LOGO_URL)
        if which == "bulk":
            return self.client.delete(
                "/api/channels/logos/bulk-delete/",
                {"logo_ids": [self.logo.id], "delete_files": True},
                format="json",
            )
        if which == "cleanup":
            return self.client.post(
                "/api/channels/logos/cleanup/", {"delete_files": True}, format="json"
            )
        return self.client.delete(f"/api/channels/logos/{self.logo.id}/?delete_file=true")

    def test_success_logs_no_filename(self):
        for which in ("bulk", "cleanup", "single"):
            with self.subTest(which):
                with patch.object(api_views.os.path, "exists", return_value=True), patch.object(
                    api_views.os, "remove"
                ) as remove:
                    with capture(api_views.logger) as logs:
                        response = self.request(which)
                self.assertLess(response.status_code, 300, response.content)
                remove.assert_called_with(LOGO_URL)
                assert_no_secret(self, logs.records)
                self.assertTrue(
                    any("Deleted local file of logo" in r.getMessage() for r in logs.records)
                )

    def test_failure_logs_no_filename_or_exception_text_and_keeps_the_response(self):
        for which in ("bulk", "cleanup", "single"):
            with self.subTest(which):
                with patch.object(api_views.os.path, "exists", return_value=True), patch.object(
                    api_views.os, "remove", side_effect=OSError(f"cannot remove {LOGO_URL}")
                ):
                    with capture(api_views.logger) as logs:
                        response = self.request(which)
                # Behaviour is unchanged: still a 500 carrying the same text.
                self.assertEqual(response.status_code, 500, response.content)
                assert_no_secret(self, logs.records)
                self.assertTrue(
                    any(
                        "Failed to delete local file of logo" in r.getMessage()
                        for r in logs.records
                    )
                )
