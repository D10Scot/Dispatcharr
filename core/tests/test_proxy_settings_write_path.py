"""Issue #257: proxy_settings writes go through /api/core/settings/<id>/,
not core/api_views.py's ProxySettingsViewSet.

WHY THIS EXISTS. #257's own analysis and the assessor's retitle were both
wrong about which path the settings UI uses. ProxySettingsViewSet
(core/api_views.py) is never routed -- core/api_urls.py registers no
route for it -- so grepping for it finds only the definition and a
docstring note. The Settings page reads and writes proxy_settings
through the generic CoreSettingsViewSet, at /api/core/settings/<id>/
(frontend/src/api.js's updateSetting), whose CoreSettingsSerializer wrote
`value` verbatim with no validation of any kind. That write path now
merges the incoming value over the stored group and validates the
result through ProxySettingsSerializer before storing it.

LITERAL EXPECTED DICTS, NEVER A SECOND get_proxy_settings() CALL. Per
core/tests/test_core.py's ProxySettingsBackfillsMissingKeysTests
docstring: computing the expected value by calling the same function
under test is the tautological-oracle shape a review already found
(apps/proxy/tests/test_next_source_resolution.py,
test_next_source_api.py) -- reverting the fix entirely still left those
green. Every expectation here is a hand-written literal.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from core.models import CoreSettings, PROXY_SETTINGS_KEY

# The post-migration-0026 shape: every key but new_client_behind_seconds,
# which has no seeding/backfill migration (core/models.py's
# get_proxy_settings docstring). Typed here, not imported, so a key
# silently disappearing from the stored defaults fails this module
# rather than agreeing with it.
SIX_KEY_ROW = {
    "buffering_timeout": 15,
    "buffering_speed": 1.0,
    "redis_chunk_ttl": 60,
    "channel_shutdown_delay": 0,
    "channel_init_grace_period": 60,
    "channel_client_wait_period": 5,
}


class ProxySettingsWritePathTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="proxy_settings_admin",
            password="x",
            user_level=User.UserLevel.ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.row, _ = CoreSettings.objects.get_or_create(
            key=PROXY_SETTINGS_KEY,
            defaults={"name": "Proxy Settings", "value": dict(SIX_KEY_ROW)},
        )
        self.row.value = dict(SIX_KEY_ROW)
        self.row.name = "Proxy Settings"
        self.row.save()
        self.url = f"/api/core/settings/{self.row.pk}/"

    def _refresh_value(self):
        self.row.refresh_from_db()
        return self.row.value

    def test_the_settings_page_put_stores_every_key(self):
        """The reporter's exact path: PUT with {key, name, value}, the
        frontend's own six stored keys plus one changed."""
        body = {
            "key": PROXY_SETTINGS_KEY,
            "name": "Proxy Settings",
            "value": {**SIX_KEY_ROW, "buffering_speed": 2.0},
        }
        response = self.client.put(self.url, body, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            self._refresh_value(),
            {
                "buffering_timeout": 15,
                "buffering_speed": 2.0,
                "redis_chunk_ttl": 60,
                "channel_shutdown_delay": 0,
                "channel_init_grace_period": 60,
                "channel_client_wait_period": 5,
                "new_client_behind_seconds": 5,
            },
        )

    def test_saving_proxy_settings_through_the_settings_api_stores_every_key(self):
        """The other verb that reaches CoreSettingsSerializer.update, sending
        the same six-key-plus-one-changed shape as the PUT test above so
        the two differ only in HTTP method."""
        response = self.client.patch(
            self.url,
            {"value": {**SIX_KEY_ROW, "buffering_speed": 3.5}},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            self._refresh_value(),
            {
                "buffering_timeout": 15,
                "buffering_speed": 3.5,
                "redis_chunk_ttl": 60,
                "channel_shutdown_delay": 0,
                "channel_init_grace_period": 60,
                "channel_client_wait_period": 5,
                "new_client_behind_seconds": 5,
            },
        )

    def test_out_of_range_proxy_settings_are_refused_by_the_settings_api(self):
        """buffering_speed's own max is 10.0 (core/serializers.py's
        ProxySettingsSerializer); 50 is refused, and the stored row is
        untouched."""
        response = self.client.patch(
            self.url, {"value": {"buffering_speed": 50}}, format="json"
        )
        self.assertEqual(
            response.status_code,
            400,
            "An out-of-range proxy_settings value was stored instead of "
            f"refused: got {response.status_code}, body {response.data}",
        )
        self.assertEqual(self._refresh_value(), SIX_KEY_ROW)

    def test_a_partial_proxy_settings_value_keeps_its_siblings(self):
        response = self.client.patch(
            self.url, {"value": {"buffering_speed": 2.0}}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            self._refresh_value(),
            {
                "buffering_timeout": 15,
                "buffering_speed": 2.0,
                "redis_chunk_ttl": 60,
                "channel_shutdown_delay": 0,
                "channel_init_grace_period": 60,
                "channel_client_wait_period": 5,
                "new_client_behind_seconds": 5,
            },
        )
