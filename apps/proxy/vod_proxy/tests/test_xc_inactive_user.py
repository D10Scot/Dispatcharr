"""The XC movie and series roots refuse a deactivated user's credentials.

Inline path (no nginx trust marker): stream_xc_movie/stream_xc_episode call
resolve_authorization, which runs authorize_stream and resolve_xc_user. A
deactivated user's right password must get the wrong password's answer,
byte for byte; reactivating lets the request past authorization (to the
content lookup, which 404s here because no movie or episode exists).
"""

from django.test import Client, TestCase

from apps.accounts.models import User


class XcVodInactiveUserTests(TestCase):
    def setUp(self):
        self.client = Client(REMOTE_ADDR="127.0.0.1")
        self.user = User.objects.create_user(
            username="vod-xc-inactive", password="unused",
            custom_properties={"xc_password": "fake-xc-pass-6"},
        )
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

    def test_movie_and_series_roots_refuse_a_deactivated_user(self):
        for root in ("movie", "series"):
            with self.subTest(root=root):
                wrong = self.client.get(f"/{root}/vod-xc-inactive/not-the-password/987654321.mp4")
                refused = self.client.get(f"/{root}/vod-xc-inactive/fake-xc-pass-6/987654321.mp4")
                ghost = self.client.get(f"/{root}/no-such-xc-user/fake-xc-pass-6/987654321.mp4")
                self.assertEqual(refused.status_code, 401)
                for other in (wrong, ghost):
                    self.assertEqual(refused.status_code, other.status_code)
                    self.assertEqual(refused.content, other.content)

        self.user.is_active = True
        self.user.save(update_fields=["is_active"])
        for root in ("movie", "series"):
            with self.subTest(root=root, reactivated=True):
                response = self.client.get(f"/{root}/vod-xc-inactive/fake-xc-pass-6/987654321.mp4")
                # Past authorization: the content lookup's own 404.
                self.assertEqual(response.status_code, 404)
