"""The OutputProfile API and HLS profiles (Phase 4a-1d, spec D12).

Seeded rows are never assumed: a TransactionTestCase earlier in the same
process can have flushed the migration's rows under --keepdb, so every test
gets its HLS rows through get_or_create and sets the fields it depends on.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import OutputProfile

User = get_user_model()

REFUSAL = "HLS output profiles are built by the relay and cannot be changed."


def hls_row(name="HLS (Automatic)", mode="automatic"):
    row, _ = OutputProfile.objects.get_or_create(
        name=name,
        defaults={
            "hls_mode": mode,
            "command": "ffmpeg",
            "parameters": "(built by the relay)",
            "locked": True,
            "is_active": True,
        },
    )
    OutputProfile.objects.filter(id=row.id).update(hls_mode=mode, locked=True, is_active=True)
    row.refresh_from_db()
    return row


class OutputProfileHlsApiTests(TestCase):
    def setUp(self):
        admin = User.objects.create_user(username="hls-profile-admin", password="x")
        admin.user_level = 10
        admin.save()
        self.client = APIClient()
        self.client.force_authenticate(user=admin)
        self.url = "/api/core/outputprofiles/"

    def test_hls_mode_is_listed_and_read_only_on_create(self):
        hls_row()
        rows = self.client.get(self.url).json()
        results = rows["results"] if isinstance(rows, dict) else rows
        self.assertTrue(results)
        for row in results:
            self.assertIn("hls_mode", row)

        response = self.client.post(
            self.url,
            {
                "name": "hls-mode-post-test",
                "command": "ffmpeg",
                "parameters": "-i pipe:0 pipe:1",
                "hls_mode": "automatic",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(OutputProfile.objects.get(name="hls-mode-post-test").hls_mode, "")

    def test_an_hls_row_cannot_be_updated(self):
        row = hls_row()
        response = self.client.patch(f"{self.url}{row.id}/", {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json(), {"detail": REFUSAL})
        row.refresh_from_db()
        self.assertTrue(row.is_active)

    def test_an_hls_row_cannot_be_deleted(self):
        row = hls_row()
        response = self.client.delete(f"{self.url}{row.id}/")
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(response.json(), {"detail": REFUSAL})
        self.assertTrue(OutputProfile.objects.filter(id=row.id).exists())

    def test_an_ordinary_row_is_still_editable_and_deletable(self):
        row = OutputProfile.objects.create(
            name="hls-api-ordinary", command="ffmpeg", parameters="-i pipe:0 pipe:1"
        )
        response = self.client.patch(f"{self.url}{row.id}/", {"is_active": False}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        response = self.client.delete(f"{self.url}{row.id}/")
        self.assertEqual(response.status_code, 204, response.content)
