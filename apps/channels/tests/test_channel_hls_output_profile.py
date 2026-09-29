"""Channel.hls_output_profile through the API (Phase 4a-1d, spec D12)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.channels.models import Channel
from core.models import OutputProfile

User = get_user_model()


def automatic_row():
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
    OutputProfile.objects.filter(id=row.id).update(
        hls_mode="automatic", locked=True, is_active=True
    )
    return row


class ChannelHlsOutputProfileTests(TestCase):
    def setUp(self):
        admin = User.objects.create_user(username="hls-channel-admin", password="x")
        admin.user_level = 10
        admin.save()
        self.client = APIClient()
        self.client.force_authenticate(user=admin)
        self.channel = Channel.objects.create(channel_number=9911, name="hls-output-profile")
        self.url = f"/api/channels/channels/{self.channel.id}/"

    def test_a_channel_accepts_an_hls_output_profile_and_refuses_an_ordinary_one(self):
        row = automatic_row()
        response = self.client.patch(self.url, {"hls_output_profile_id": row.id}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["hls_output_profile_id"], row.id)

        ordinary = OutputProfile.objects.create(
            name="hls-channel-ordinary", command="ffmpeg", parameters="-i pipe:0 pipe:1"
        )
        response = self.client.patch(
            self.url, {"hls_output_profile_id": ordinary.id}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("hls_output_profile_id", response.json())

        response = self.client.patch(self.url, {"hls_output_profile_id": None}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["hls_output_profile_id"])

    def test_deleting_the_profile_nulls_the_channel(self):
        row = automatic_row()
        Channel.objects.filter(id=self.channel.id).update(hls_output_profile=row)
        OutputProfile.objects.filter(hls_mode="automatic").delete()
        self.channel.refresh_from_db()
        self.assertIsNone(self.channel.hls_output_profile_id)
