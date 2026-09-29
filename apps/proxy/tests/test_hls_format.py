"""The HLS output as a resolved format (Phase 4a-1b, spec D2).

`hls` and its alias `m3u8` resolve ONLY from the request. A stored user or
deployment default of either is not honoured: without that guard a user row
holding `hls` (which answered 501 before this PR) would turn every one of that
user's byte-stream tunes into a playlist.
"""

from unittest.mock import patch

from django.test import Client, RequestFactory, TestCase

from apps.accounts.models import User
from apps.channels.models import Channel
from apps.proxy import authorize
from core.models import CoreSettings


class ResolveOutputFormatHLSTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.channel = Channel.objects.create(name="hls-format", channel_number=9301)
        cls.user = User.objects.create_user(username="hls-format-user", password="x")

    def setUp(self):
        self.factory = RequestFactory()

    def _resolve(self, query="", user=None):
        request = self.factory.get(f"/proxy/ts/stream/x{query}")
        return authorize.resolve_output_format(request, user)

    def test_hls_and_m3u8_resolve_to_hls(self):
        self.assertEqual(self._resolve("?output_format=hls"), "hls")
        self.assertEqual(self._resolve("?output_format=m3u8"), "hls")
        self.assertEqual(self._resolve("?output=m3u8"), "hls")
        self.assertEqual(self._resolve("?output=hls"), "hls")

    def test_the_hop_answers_hls_for_an_hls_tune(self):
        response = Client().get(
            "/_dispatcharr/authorize",
            HTTP_X_ORIGINAL_URI=f"/proxy/ts/stream/{self.channel.uuid}?output_format=hls",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Relay-Output-Format"], "hls")

    def test_a_user_default_of_hls_is_not_honoured(self):
        for stored in ("hls", "m3u8"):
            with self.subTest(stored=stored):
                self.user.custom_properties = {"output_format": stored}
                self.assertEqual(self._resolve(user=self.user), "mpegts")
        # The guard skips only the HLS spellings: any other stored value is
        # still returned as it always was.
        self.user.custom_properties = {"output_format": "fmp4"}
        self.assertEqual(self._resolve(user=self.user), "fmp4")

    def test_a_deployment_default_of_hls_reads_as_mpegts(self):
        for stored in ("hls", "m3u8"):
            with self.subTest(stored=stored):
                with patch.object(CoreSettings, "get_default_output_format", return_value=stored):
                    self.assertEqual(self._resolve(), "mpegts")
        with patch.object(CoreSettings, "get_default_output_format", return_value="fmp4"):
            self.assertEqual(self._resolve(), "fmp4")
