"""XC VOD credential failures must return 401/403, not crash with a 500.

Regression tests for https://github.com/D10Scot/Dispatcharr/issues/100:
``stream_xc_movie`` and ``stream_xc_episode`` built
``rest_framework.response.Response`` on their credential/ACL early-return
branches without ever importing it, so every one of those branches raised
``NameError`` and the client got an unhandled 500.
"""

from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import User


class XcVodCredentialStatusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="xcuser",
            password="irrelevant",
            custom_properties={"xc_password": "correct-password"},
        )

    def test_wrong_password_movie_is_401(self):
        response = self.client.get("/movie/xcuser/wrong-password/123.mp4")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "Invalid credentials"})

    def test_missing_xc_password_movie_is_401(self):
        self.user.custom_properties = {}
        self.user.save()
        response = self.client.get("/movie/xcuser/any-password/123.mp4")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "Invalid credentials"})

    def test_wrong_password_episode_is_401(self):
        response = self.client.get("/series/xcuser/wrong-password/456.mp4")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "Invalid credentials"})

    def test_missing_xc_password_episode_is_401(self):
        self.user.custom_properties = {}
        self.user.save()
        response = self.client.get("/series/xcuser/any-password/456.mp4")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"error": "Invalid credentials"})

    def test_acl_denied_movie_is_403(self):
        with patch(
            "apps.proxy.vod_proxy.views.network_access_allowed",
            return_value=False,
        ):
            response = self.client.get("/movie/xcuser/correct-password/123.mp4")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "Forbidden"})

    def test_acl_denied_episode_is_403(self):
        with patch(
            "apps.proxy.vod_proxy.views.network_access_allowed",
            return_value=False,
        ):
            response = self.client.get("/series/xcuser/correct-password/456.mp4")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "Forbidden"})
