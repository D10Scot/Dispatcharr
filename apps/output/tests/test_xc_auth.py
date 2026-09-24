"""xc_authenticate: one answer for bad credentials, 403 for a refused network.

#84 - player_api.php (and panel_api.php, get.php, xmltv.php) used to answer
404 for an unknown username and 401 for a wrong password, making the
handshake endpoint an account-enumeration oracle. xc_authenticate delegates
to apps.proxy.authorize.resolve_xc_user, the constant-time check every
streaming surface already uses, so all four endpoints now answer 401 for
either case, with identical bodies.

#134 - a user refused by the per-user or global XC_API network ACL used to
get the same 401 as a wrong password. xc_authenticate distinguishes the two
outcomes (401 credentials, 403 network), and player_api.php/panel_api.php
gain the same network pre-check get.php/xmltv.php already had, logging a
login_failed event for the refusal.
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core.models import NETWORK_ACCESS_KEY, CoreSettings, SystemEvent

User = get_user_model()

# 203.0.113.0/24 is TEST-NET-3 (RFC 5737): documentation-only, guaranteed to
# never contain a real client -- including the loopback peer the Django test
# client connects from.
BLOCKING_CIDR = "203.0.113.0/24"

XC_ENDPOINTS = ["xc_player_api", "xc_panel_api", "xc_get", "xc_xmltv"]


class XCAuthTests(TestCase):
    def setUp(self):
        self.client = Client(REMOTE_ADDR="127.0.0.1")
        self.xc_user = User.objects.create_user(
            username="xcauth-user",
            password="not-the-xc-password",
            user_level=10,
            custom_properties={"xc_password": "correct-horse-battery-staple"},
        )
        self.no_password_user = User.objects.create_user(
            username="xcauth-no-xc-password",
            password="not-the-xc-password",
            user_level=10,
        )

    def _get(self, url_name, username, password):
        return self.client.get(
            reverse(url_name), {"username": username, "password": password}
        )

    def test_an_unknown_xc_username_answered_404_where_a_wrong_password_answered_401(self):
        """An unknown username and a wrong password must be indistinguishable.

        Also folds in a user that exists but carries no xc_password at all
        (self.no_password_user): resolve_xc_user treats a missing key the
        same as a wrong one, so all three cases must answer 401 with the
        same body.
        """
        for url_name in XC_ENDPOINTS:
            with self.subTest(endpoint=url_name):
                ghost_username = self._get(url_name, "no-such-xc-user", "whatever")
                wrong_password = self._get(
                    url_name, self.xc_user.username, "wrong-password"
                )
                no_xc_password = self._get(
                    url_name, self.no_password_user.username, "whatever"
                )

                self.assertEqual(ghost_username.status_code, 401)
                self.assertEqual(wrong_password.status_code, 401)
                self.assertEqual(no_xc_password.status_code, 401)
                self.assertEqual(ghost_username.json(), wrong_password.json())
                self.assertEqual(ghost_username.json(), no_xc_password.json())

    def test_a_non_ascii_xc_password_is_refused_not_500(self):
        response = self._get("xc_player_api", self.xc_user.username, "café☕")
        self.assertEqual(response.status_code, 401)

    def test_valid_xc_credentials_still_answer_200_on_all_four_endpoints(self):
        for url_name in XC_ENDPOINTS:
            with self.subTest(endpoint=url_name):
                response = self._get(
                    url_name, self.xc_user.username, "correct-horse-battery-staple"
                )
                self.assertEqual(response.status_code, 200)

    def test_a_network_blocked_xc_user_got_401_as_if_the_password_were_wrong(self):
        blocked_user = User.objects.create_user(
            username="xcauth-network-blocked",
            password="not-the-xc-password",
            user_level=10,
            custom_properties={
                "xc_password": "correct-horse-battery-staple",
                "allowed_networks": {"XC_API": BLOCKING_CIDR},
            },
        )
        for url_name in XC_ENDPOINTS:
            with self.subTest(endpoint=url_name):
                response = self._get(
                    url_name, blocked_user.username, "correct-horse-battery-staple"
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"error": "Forbidden"})

    def test_player_api_and_panel_api_logged_no_event_for_a_network_refusal(self):
        blocked_user = User.objects.create_user(
            username="xcauth-network-blocked-events",
            password="not-the-xc-password",
            user_level=10,
            custom_properties={
                "xc_password": "correct-horse-battery-staple",
                "allowed_networks": {"XC_API": BLOCKING_CIDR},
            },
        )
        self._get(
            "xc_player_api", blocked_user.username, "correct-horse-battery-staple"
        )
        self._get(
            "xc_panel_api", blocked_user.username, "correct-horse-battery-staple"
        )

        events = SystemEvent.objects.filter(
            event_type="login_failed",
            details__reason="Network access denied (XC API)",
        )
        self.assertEqual(events.count(), 2)
        endpoints = {event.details.get("endpoint") for event in events}
        self.assertEqual(endpoints, {"player_api", "panel_api"})
        for event in events:
            self.assertEqual(event.details.get("user"), blocked_user.username)

    def test_a_global_xc_api_block_answered_401_on_player_api(self):
        # TestCase wraps each test in a transaction that is rolled back at
        # the end, but CoreSettings' group cache lives in Redis, not
        # Postgres -- the post_save signal's cache invalidation is not part
        # of that rollback. Without this cleanup, the narrowed value here
        # would stay warm and leak into later tests (memory: warm state
        # hides a query).
        self.addCleanup(CoreSettings.invalidate_group_cache, NETWORK_ACCESS_KEY)
        CoreSettings.objects.update_or_create(
            key=NETWORK_ACCESS_KEY,
            defaults={"name": "Network Access", "value": {"XC_API": BLOCKING_CIDR}},
        )

        for url_name in ("xc_player_api", "xc_panel_api"):
            with self.subTest(endpoint=url_name):
                response = self._get(url_name, self.xc_user.username, "wrong-password")
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json(), {"error": "Forbidden"})

    def test_wrong_credentials_from_an_allowed_network_still_answer_401(self):
        for url_name in XC_ENDPOINTS:
            with self.subTest(endpoint=url_name):
                response = self._get(url_name, self.xc_user.username, "wrong-password")
                self.assertEqual(response.status_code, 401)
