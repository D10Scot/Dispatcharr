"""M3UAccountSerializer.read_only_fields lives in Meta, not the class body (#15).

`M3UAccountSerializer` declared `read_only_fields = ["locked", "created_at",
"updated_at"]` directly in the class body, a sibling of `class Meta`. DRF's
`ModelSerializer` only reads `Meta.read_only_fields`, so that assignment was
inert: `locked` (which marks the built-in custom account,
`M3UAccount.get_custom_account`) and `updated_at` (documented as "last
successful refresh") were both writable by any admin API client. Reproduced
at seed: a partial PATCH with `locked: true` and a fabricated `updated_at`
persisted both.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.m3u.models import M3UAccount

User = get_user_model()


class M3UAccountReadOnlyFieldsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="m3u-admin", password="testpass123")
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.account = M3UAccount.objects.create(
            name="Read-only fields account",
            server_url="http://example.com/playlist.m3u",
        )
        self.assertFalse(self.account.locked)
        self.assertIsNone(self.account.updated_at)

    def test_m3u_account_locked_and_updated_at_are_not_writable_over_the_api(self):
        response = self.client.patch(
            f"/api/m3u/accounts/{self.account.id}/",
            {"locked": True, "updated_at": "1999-01-02T03:04:05Z"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.account.refresh_from_db()
        self.assertFalse(
            self.account.locked,
            "locked was writable over the API despite being declared read-only",
        )
        self.assertIsNone(
            self.account.updated_at,
            "updated_at was writable over the API despite being declared read-only",
        )
