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

from apps.output.views import XC_UNAUTHENTICATED_USER
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
                # Byte-for-byte, not just JSON-equal: a client comparing raw
                # bodies or the Content-Type header must see no difference
                # either between an unknown username and a wrong password.
                self.assertEqual(ghost_username.content, wrong_password.content)
                self.assertEqual(
                    ghost_username["Content-Type"], wrong_password["Content-Type"]
                )

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
            # This is the PER-USER network refusal: resolve_xc_user already
            # accepted the password by the time it fires, so the username
            # is real, and #134's whole complaint was that a per-user
            # denial was invisible in the events log -- so it is logged,
            # unlike the (still unresolved) global-block path.
            self.assertEqual(event.details.get("user"), blocked_user.username)
            # The credential must still never leak, resolved user or not.
            for value in event.details.values():
                self.assertNotIn("correct-horse-battery-staple", str(value))

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

        # The GLOBAL pre-check runs before any credential read, so unlike
        # the per-user refusal above it never resolves a user: the event
        # must carry the fixed placeholder, and neither the request's
        # username nor its (here, wrong) password may appear anywhere in
        # it.
        events = SystemEvent.objects.filter(
            event_type="login_failed",
            details__reason="Network access denied (XC API)",
        )
        self.assertEqual(events.count(), 2)
        for event in events:
            self.assertEqual(event.details.get("user"), XC_UNAUTHENTICATED_USER)
            for value in event.details.values():
                self.assertNotIn(self.xc_user.username, str(value))
                self.assertNotIn("wrong-password", str(value))

    def test_wrong_credentials_from_an_allowed_network_still_answer_401(self):
        for url_name in XC_ENDPOINTS:
            with self.subTest(endpoint=url_name):
                response = self._get(url_name, self.xc_user.username, "wrong-password")
                self.assertEqual(response.status_code, 401)

    def test_a_deactivated_user_with_the_right_xc_password_answers_like_a_wrong_one(self):
        """A deactivated user's XC credentials list nothing.

        Same status, same bytes and same Content-Type as a wrong password on
        all four endpoints, so the answer does not reveal whether the
        deactivated account's password was right; reactivating restores 200.
        """
        self.xc_user.is_active = False
        self.xc_user.save(update_fields=["is_active"])
        for url_name in XC_ENDPOINTS:
            with self.subTest(endpoint=url_name):
                wrong_password = self._get(
                    url_name, self.xc_user.username, "wrong-password"
                )
                deactivated = self._get(
                    url_name, self.xc_user.username, "correct-horse-battery-staple"
                )
                # The canonical credential refusal (#84): an unknown
                # username. Comparing against it too means a refusal that
                # names the account's state -- even one given to every
                # password alike -- is caught, not only one that tells the
                # right password from a wrong one.
                ghost_username = self._get(url_name, "no-such-xc-user", "whatever")
                self.assertEqual(deactivated.status_code, 401)
                for other in (wrong_password, ghost_username):
                    self.assertEqual(deactivated.status_code, other.status_code)
                    self.assertEqual(deactivated.content, other.content)
                    self.assertEqual(deactivated["Content-Type"], other["Content-Type"])

        self.xc_user.is_active = True
        self.xc_user.save(update_fields=["is_active"])
        for url_name in XC_ENDPOINTS:
            with self.subTest(endpoint=url_name, reactivated=True):
                response = self._get(
                    url_name, self.xc_user.username, "correct-horse-battery-staple"
                )
                self.assertEqual(response.status_code, 200)

    def test_a_deactivated_network_blocked_user_gets_401_not_403(self):
        """The per-user network refusal fires only after the credentials
        resolve; for a deactivated user they never do, so the right password
        gets the wrong password's 401 and not the 403 that would confirm it.
        """
        blocked_user = User.objects.create_user(
            username="xcauth-inactive-blocked",
            password="not-the-xc-password",
            user_level=10,
            custom_properties={
                "xc_password": "correct-horse-battery-staple",
                "allowed_networks": {"XC_API": BLOCKING_CIDR},
            },
        )
        blocked_user.is_active = False
        blocked_user.save(update_fields=["is_active"])
        for url_name in XC_ENDPOINTS:
            with self.subTest(endpoint=url_name):
                wrong_password = self._get(url_name, blocked_user.username, "wrong-password")
                deactivated = self._get(
                    url_name, blocked_user.username, "correct-horse-battery-staple"
                )
                ghost_username = self._get(url_name, "no-such-xc-user", "whatever")
                self.assertEqual(deactivated.status_code, 401)
                self.assertEqual(deactivated.content, wrong_password.content)
                self.assertEqual(deactivated.content, ghost_username.content)

    def test_a_deactivated_users_right_password_answers_like_an_active_users_wrong_one(self):
        """The comparator is an ACTIVE account's wrong password.

        A refusal that differs by account state -- the same answer for any
        password to a deactivated account, but not the answer an active
        account's wrong password gets -- must redden here.
        """
        deactivated_user = User.objects.create_user(
            username="xcauth-deactivated",
            password="not-the-xc-password",
            user_level=10,
            custom_properties={"xc_password": "fake-xc-pass-8"},
        )
        deactivated_user.is_active = False
        deactivated_user.save(update_fields=["is_active"])
        for url_name in XC_ENDPOINTS:
            with self.subTest(endpoint=url_name):
                active_wrong = self._get(url_name, self.xc_user.username, "wrong-password")
                deactivated = self._get(url_name, deactivated_user.username, "fake-xc-pass-8")
                self.assertEqual(deactivated.status_code, 401)
                self.assertEqual(deactivated.status_code, active_wrong.status_code)
                self.assertEqual(deactivated.content, active_wrong.content)
                self.assertEqual(deactivated["Content-Type"], active_wrong["Content-Type"])
