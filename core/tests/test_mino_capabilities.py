"""The Mino capability document (Phase 4a-1b, spec D19, Decision 15)."""

from django.test import Client, TestCase
from django.urls import reverse

from core.models import NETWORK_ACCESS_KEY, CoreSettings
from version import __version__

BLOCKING_CIDR = "203.0.113.0/24"  # TEST-NET-3: never contains the test client


class MinoCapabilitiesTests(TestCase):
    def setUp(self):
        self.client = Client(REMOTE_ADDR="127.0.0.1")
        self.url = "/api/mino/capabilities/"

    def test_answers_anonymously_with_the_documented_body(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "product": "mino",
                "api_version": 1,
                "server_version": __version__,
                "live_hls": {
                    "available": True,
                    "segment_seconds": 2,
                    "session_leave": True,
                    "rewind_window": {"available": False, "depth_seconds": 0},
                },
            },
        )

    def test_a_stale_bearer_header_is_not_a_401(self):
        # A Mino app build with an expired token must still read a document
        # that needs none: the view runs no authenticators.
        response = self.client.get(self.url, HTTP_AUTHORIZATION="Bearer stale.token.value")
        self.assertEqual(response.status_code, 200)

    def test_the_xc_api_acl_refuses_with_403(self):
        self.addCleanup(CoreSettings.invalidate_group_cache, NETWORK_ACCESS_KEY)
        CoreSettings.objects.update_or_create(
            key=NETWORK_ACCESS_KEY, defaults={"name": "Network Access", "value": {"XC_API": BLOCKING_CIDR}}
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_the_route_is_in_the_schema(self):
        response = self.client.get(reverse("api:schema"), {"format": "json"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("/api/mino/capabilities/", response.json()["paths"])
