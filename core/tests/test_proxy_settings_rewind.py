"""Phase 4a-3 (spec D17): the four rewind settings, end to end on the Django
side. LITERAL EXPECTED VALUES, never a second get_proxy_settings() call: the
oracle is written by hand, as core/tests/test_core.py's back-fill tests are."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.proxy.next_source import _with_proxy_settings
from core.models import PROXY_SETTINGS_KEY, CoreSettings

FOUR = (
    "rewind_window_minutes",
    "rewind_linger_seconds",
    "rewind_behind_live_grace_seconds",
    "rewind_disk_cap_gb",
)

# The pre-4a-3 shape: the seven stored keys, none of the four.
SEVEN_KEY_ROW = {
    "buffering_timeout": 15,
    "buffering_speed": 1.0,
    "redis_chunk_ttl": 60,
    "channel_shutdown_delay": 0,
    "channel_init_grace_period": 60,
    "channel_client_wait_period": 5,
    "new_client_behind_seconds": 5,
}


class RewindSettingsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        User = get_user_model()
        admin = User.objects.create_user(
            username="rewind_settings_admin", password="x", user_level=User.UserLevel.ADMIN
        )
        self.api = APIClient()
        self.api.force_authenticate(user=admin)
        self.row, _ = CoreSettings.objects.get_or_create(
            key=PROXY_SETTINGS_KEY, defaults={"name": "Proxy Settings", "value": {}}
        )
        self.row.name = "Proxy Settings"
        self.row.value = dict(SEVEN_KEY_ROW)
        self.row.save()  # post_save invalidates the group cache
        self.url = f"/api/core/settings/{self.row.pk}/"

    def _stored(self):
        self.row.refresh_from_db()
        return self.row.value

    def test_the_four_defaults_are_back_filled(self):
        got = CoreSettings.get_proxy_settings()
        self.assertEqual(
            {key: got[key] for key in FOUR},
            {
                "rewind_window_minutes": 60,
                "rewind_linger_seconds": 300,
                "rewind_behind_live_grace_seconds": 10,
                "rewind_disk_cap_gb": 16,
            },
        )

    def test_each_bound_is_enforced(self):
        # (key, one past the bound, the bound itself)
        cases = (
            ("rewind_window_minutes", 121, 120),
            ("rewind_linger_seconds", 3601, 3600),
            ("rewind_behind_live_grace_seconds", 301, 300),
            ("rewind_disk_cap_gb", 0, 1),
            ("rewind_disk_cap_gb", 10001, 10000),
        )
        for key, refused, accepted in cases:
            with self.subTest(key=key, refused=refused):
                response = self.api.patch(self.url, {"value": {key: refused}}, format="json")
                self.assertEqual(response.status_code, 400, response.data)
                self.assertNotIn(key, self._stored(), "a refused value was stored")
            with self.subTest(key=key, accepted=accepted):
                response = self.api.patch(self.url, {"value": {key: accepted}}, format="json")
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(self._stored()[key], accepted)
                # back to the pre-4a-3 shape for the next case
                self.row.value = dict(SEVEN_KEY_ROW)
                self.row.save()

    def test_the_next_source_answer_carries_the_four_keys(self):
        answer = _with_proxy_settings({})["proxy_settings"]
        self.assertEqual(
            {key: answer[key] for key in FOUR},
            {
                "rewind_window_minutes": 60,
                "rewind_linger_seconds": 300,
                "rewind_behind_live_grace_seconds": 10,
                "rewind_disk_cap_gb": 16,
            },
        )
        response = self.api.patch(
            self.url, {"value": {"rewind_linger_seconds": 45, "rewind_disk_cap_gb": 4}}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        answer = _with_proxy_settings({})["proxy_settings"]
        self.assertEqual(answer["rewind_linger_seconds"], 45)
        self.assertEqual(answer["rewind_disk_cap_gb"], 4)

    def test_the_rewind_settings_are_in_the_schema(self):
        response = self.client.get(reverse("api:schema"), {"format": "json"})
        self.assertEqual(response.status_code, 200)
        properties = response.json()["components"]["schemas"]["RelayProxySettings"]["properties"]
        for key in FOUR:
            self.assertIn(key, properties)
