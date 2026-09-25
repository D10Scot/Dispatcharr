"""#12: `TokenRefreshView.post` (`apps/accounts/api_views.py`) hands off
straight to `simplejwt`'s `TokenRefreshView.post`, whose
`TokenRefreshSerializer.validate` (simplejwt 5.5.1) looks the refresh
token's user up with a bare `get_user_model().objects.get(...)`. When the
user named by an otherwise-valid, unexpired refresh token has since been
deleted, that lookup raises `User.DoesNotExist`, which escapes uncaught as a
500 -- instead of the 401 `token_not_valid` every other invalid or expired
refresh token already gets, which is the response a client actually knows
how to act on (log in again).
"""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User


class TokenRefreshDeletedUserTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/accounts/token/refresh/"

    def test_refreshing_a_deleted_users_token_is_401_not_500(self):
        user = User.objects.create_user(username="ghost", password="testpass123")
        refresh = RefreshToken.for_user(user)
        refresh_str = str(refresh)
        user.delete()

        response = self.client.post(self.url, {"refresh": refresh_str}, format="json")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json().get("code"), "token_not_valid")

    def test_refreshing_a_live_users_token_still_works(self):
        user = User.objects.create_user(username="alive", password="testpass123")
        refresh = RefreshToken.for_user(user)

        response = self.client.post(
            self.url, {"refresh": str(refresh)}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
