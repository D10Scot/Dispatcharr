"""Phase 4a-1b: the Xtream surface advertises and emits the HLS form (R9, D16).

`player_api.php` lists `m3u8` in `allowed_output_formats`; `get.php` with
`output=m3u8|hls` and Xtream credentials emits `/live/<u>/<p>/<id>.m3u8`,
drops `output_format` from the query and keeps `output_profile`.
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from apps.channels.models import Channel

User = get_user_model()


class XCHLSURLTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="xchls-user",
            password="not-the-xc-password",
            user_level=10,
            custom_properties={"xc_password": "xchls-secret"},
        )
        cls.channel = Channel.objects.create(name="xchls", channel_number=9401)

    def setUp(self):
        self.client = Client(REMOTE_ADDR="127.0.0.1")
        self.creds = {"username": "xchls-user", "password": "xchls-secret"}

    def _stream_lines(self, **extra):
        response = self.client.get(reverse("xc_get"), {**self.creds, **extra})
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content) if response.streaming else response.content
        return [line for line in body.decode().splitlines() if "/live/" in line]

    def test_player_api_advertises_m3u8(self):
        response = self.client.get(reverse("xc_player_api"), self.creds)
        self.assertEqual(response.status_code, 200)
        formats = response.json()["user_info"]["allowed_output_formats"]
        self.assertEqual(formats, ["ts", "mp4", "m3u8"])

    def test_get_php_output_m3u8_emits_m3u8_urls(self):
        (line,) = self._stream_lines(output="m3u8")
        self.assertTrue(
            line.endswith(f"/live/xchls-user/xchls-secret/{self.channel.id}.m3u8"),
            line,
        )

    def test_get_php_output_hls_emits_m3u8_urls(self):
        (line,) = self._stream_lines(output="hls")
        self.assertIn(f"/live/xchls-user/xchls-secret/{self.channel.id}.m3u8", line)
        self.assertNotIn("output_format", line)

    def test_the_output_profile_is_kept_and_output_format_dropped(self):
        (line,) = self._stream_lines(output="m3u8", output_profile="3")
        self.assertIn(".m3u8?output_profile=3", line)
        self.assertNotIn("output_format", line)

    def test_output_ts_is_unchanged(self):
        (line,) = self._stream_lines(output="ts")
        self.assertTrue(
            line.endswith(f"/live/xchls-user/xchls-secret/{self.channel.id}?output_format=ts"),
            line,
        )

    def test_a_non_xc_request_keeps_the_query(self):
        # No Xtream credentials: nothing changes, the proxy URL still carries
        # output_format (the relay resolves m3u8 through the hop's aliases).
        response = self.client.get("/output/m3u", {"output_format": "m3u8"})
        self.assertEqual(response.status_code, 200)
        text = response.content.decode()
        self.assertIn("/proxy/ts/stream/", text)
        self.assertIn("output_format=m3u8", text)
