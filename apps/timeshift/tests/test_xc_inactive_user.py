"""The XC catch-up roots refuse a deactivated user's credentials.

Inline path (no nginx trust marker): both /timeshift/... and
/streaming/timeshift.php reach _timeshift_proxy_impl, which calls
resolve_authorization -> authorize_stream -> resolve_xc_user. A deactivated
user's right password must get the wrong password's answer, byte for byte;
reactivating lets the request past the credential check (to the channel
lookup, which answers 404 for a channel id that does not exist).
"""

from unittest.mock import patch

from django.test import Client, TestCase

from apps.accounts.models import User
from apps.timeshift import views

MISSING_CHANNEL_ID = 987654321


class XcCatchupInactiveUserTests(TestCase):
    # The views call close_old_connections() before answering, which closes
    # the TestCase's own connection; the existing timeshift view tests patch
    # it out the same way.
    def setUp(self):
        patcher = patch.object(views, "close_old_connections")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = Client(REMOTE_ADDR="127.0.0.1")
        self.user = User.objects.create_user(
            username="ts-xc-inactive", password="unused",
            custom_properties={"xc_password": "fake-xc-pass-7"},
        )
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

    def _uris(self, password, username="ts-xc-inactive"):
        return [
            f"/timeshift/{username}/{password}/60/2026-06-08:17-00/{MISSING_CHANNEL_ID}.ts",
            (
                f"/streaming/timeshift.php?username={username}"
                f"&password={password}&stream={MISSING_CHANNEL_ID}.ts"
                "&start=2026-06-08:17-00&duration=60"
            ),
        ]

    def test_both_catchup_roots_refuse_a_deactivated_user(self):
        for wrong_uri, right_uri, ghost_uri in zip(
            self._uris("not-the-password"),
            self._uris("fake-xc-pass-7"),
            self._uris("fake-xc-pass-7", username="no-such-xc-user"),
        ):
            with self.subTest(uri=right_uri.split("?")[0]):
                wrong = self.client.get(wrong_uri)
                refused = self.client.get(right_uri)
                ghost = self.client.get(ghost_uri)
                self.assertEqual(refused.status_code, 401)
                for other in (wrong, ghost):
                    self.assertEqual(refused.status_code, other.status_code)
                    self.assertEqual(refused.content, other.content)

        self.user.is_active = True
        self.user.save(update_fields=["is_active"])
        for right_uri in self._uris("fake-xc-pass-7"):
            with self.subTest(uri=right_uri.split("?")[0], reactivated=True):
                response = self.client.get(right_uri)
                # Past the credential check: the channel lookup's own 404.
                self.assertEqual(response.status_code, 404)
