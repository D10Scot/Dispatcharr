"""``auth_settings`` may be written only through its own endpoint (SSO spec 5.1, T14, T12a S1 half).

Two writers are closed here: ``CoreSettingsViewSet`` (refused in every direction, before the
serializer validates) and Django admin's ``CoreSettingsAdmin`` (view-only for that row).
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from rest_framework.test import APIClient

from core.models import AUTH_SETTINGS_KEY, CoreSettings

USE_AUTH_ENDPOINT = {"code": "use_auth_settings_endpoint"}
SETTINGS = "/api/core/settings/"
ORIGINAL = {"public_base_url": "https://mino.example.com", "password_login_enabled": True}


def _seed():
    row, _ = CoreSettings.objects.update_or_create(
        key=AUTH_SETTINGS_KEY, defaults={"name": "Authentication Settings", "value": dict(ORIGINAL)}
    )
    return row


class AuthSettingsGenericEndpointTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="admin", password="x", user_level=10)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.row = _seed()
        self.other = CoreSettings.objects.create(key="other_group", name="Other", value={"a": 1})
        self.url = f"{SETTINGS}{self.row.pk}/"

    def _assert_refused(self, response):
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json(), USE_AUTH_ENDPOINT)

    def _assert_unchanged(self):
        self.row.refresh_from_db()
        self.assertEqual(self.row.key, AUTH_SETTINGS_KEY)
        self.assertEqual(self.row.value, ORIGINAL)
        self.other.refresh_from_db()
        self.assertEqual((self.other.key, self.other.value), ("other_group", {"a": 1}))

    def test_patch_refused(self):
        body = {"value": {"public_base_url": "", "password_login_enabled": False}}
        self._assert_refused(self.client.patch(self.url, body, format="json"))
        self._assert_unchanged()

    def test_put_refused(self):
        body = {"key": AUTH_SETTINGS_KEY, "name": "x", "value": {"password_login_enabled": False}}
        self._assert_refused(self.client.put(self.url, body, format="json"))
        self._assert_unchanged()

    def test_delete_refused(self):
        self._assert_refused(self.client.delete(self.url))
        self._assert_unchanged()

    def test_post_with_the_key_refused(self):
        body = {"key": AUTH_SETTINGS_KEY, "name": "dup", "value": {}}
        self._assert_refused(self.client.post(SETTINGS, body, format="json"))
        self._assert_unchanged()
        self.assertEqual(CoreSettings.objects.filter(key=AUTH_SETTINGS_KEY).count(), 1)

    def test_rename_auth_settings_to_another_key_refused(self):
        self._assert_refused(self.client.patch(self.url, {"key": "renamed"}, format="json"))
        self._assert_unchanged()

    def test_rename_other_row_into_auth_settings_refused(self):
        # With the row present, the serializer's uniqueness error would also answer 400, so
        # the body is what tells the refusal from the accident.
        response = self.client.patch(
            f"{SETTINGS}{self.other.pk}/", {"key": AUTH_SETTINGS_KEY}, format="json"
        )
        self._assert_refused(response)
        self._assert_unchanged()

    def test_rename_into_auth_settings_refused_when_the_row_is_absent(self):
        self.row.delete()
        response = self.client.patch(
            f"{SETTINGS}{self.other.pk}/", {"key": AUTH_SETTINGS_KEY}, format="json"
        )
        self._assert_refused(response)
        self.assertFalse(CoreSettings.objects.filter(key=AUTH_SETTINGS_KEY).exists())

    def test_reads_stay_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        keys = [r["key"] for r in self.client.get(SETTINGS).json()]
        self.assertIn(AUTH_SETTINGS_KEY, keys)

    def test_other_groups_are_unaffected(self):
        response = self.client.patch(
            f"{SETTINGS}{self.other.pk}/", {"value": {"a": 2}}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.other.refresh_from_db()
        self.assertEqual(self.other.value, {"a": 2})
        self.assertEqual(self.client.delete(f"{SETTINGS}{self.other.pk}/").status_code, 204)


class AuthSettingsDjangoAdminTests(TestCase):
    """The admin site is a second writer; a superuser is logged in BEFORE each change."""

    def setUp(self):
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="root", password="x", email="root@example.com"
        )
        self.row = _seed()
        self.other = CoreSettings.objects.create(key="other_group", name="Other", value={"a": 1})
        self.client = Client()
        self.client.force_login(self.superuser)
        self.change_url = f"/admin/core/coresettings/{self.row.pk}/change/"

    def _row_state(self):
        return list(CoreSettings.objects.order_by("key").values_list("key", "name", "value"))

    def test_change_form_post_leaves_row_unchanged(self):
        before = self._row_state()
        response = self.client.post(
            self.change_url,
            {"key": AUTH_SETTINGS_KEY, "name": "Authentication Settings", "value": '{"password_login_enabled": false}'},
        )
        self.assertIn(response.status_code, (302, 403, 200))
        self.assertEqual(self._row_state(), before)
        self.row.refresh_from_db()
        self.assertEqual(self.row.value, ORIGINAL)

    def test_change_view_is_view_only(self):
        response = self.client.get(self.change_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="_save"')
        self.assertNotContains(response, "deletelink")

    def test_delete_view_refused(self):
        url = f"/admin/core/coresettings/{self.row.pk}/delete/"
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 403)
        self.assertTrue(CoreSettings.objects.filter(key=AUTH_SETTINGS_KEY).exists())

    def test_bulk_delete_action_refused(self):
        response = self.client.post(
            "/admin/core/coresettings/",
            {
                "action": "delete_selected",
                "_selected_action": [self.row.pk, self.other.pk],
                "post": "yes",
            },
        )
        # Django's delete_selected needs delete permission on every selected object.
        self.assertEqual(response.status_code, 403)
        self.assertTrue(CoreSettings.objects.filter(key=AUTH_SETTINGS_KEY).exists())
        self.assertTrue(CoreSettings.objects.filter(key="other_group").exists())

    def test_delete_queryset_itself_refuses_the_row(self):
        """Defence in depth: the hook that actually deletes also refuses."""
        from unittest import mock

        from django.contrib import admin
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory

        request = RequestFactory().post("/admin/core/coresettings/")
        request.user = self.superuser
        request.session = {}
        request._messages = FallbackStorage(request)
        model_admin = admin.site._registry[CoreSettings]
        model_admin.delete_queryset(request, CoreSettings.objects.all())
        self.assertTrue(CoreSettings.objects.filter(key=AUTH_SETTINGS_KEY).exists())
        self.assertTrue(CoreSettings.objects.filter(key="other_group").exists())
        self.assertIn("cannot be deleted", str(list(request._messages)[0]))
        # Without the row, the queryset deletes normally.
        model_admin.delete_queryset(request, CoreSettings.objects.filter(key="other_group"))
        self.assertFalse(CoreSettings.objects.filter(key="other_group").exists())
        self.assertIsNotNone(mock)

    def test_bulk_delete_of_other_rows_still_works(self):
        self.client.post(
            "/admin/core/coresettings/",
            {"action": "delete_selected", "_selected_action": [self.other.pk], "post": "yes"},
        )
        self.assertFalse(CoreSettings.objects.filter(key="other_group").exists())

    def test_add_auth_settings_refused(self):
        self.row.delete()
        response = self.client.post(
            "/admin/core/coresettings/add/",
            {"key": AUTH_SETTINGS_KEY, "name": "x", "value": "{}"},
        )
        self.assertEqual(response.status_code, 200)  # the form re-renders with an error
        self.assertFalse(CoreSettings.objects.filter(key=AUTH_SETTINGS_KEY).exists())

    def test_rename_another_row_into_auth_settings_refused(self):
        self.row.delete()
        response = self.client.post(
            f"/admin/core/coresettings/{self.other.pk}/change/",
            {"key": AUTH_SETTINGS_KEY, "name": "Other", "value": "{}"},
        )
        self.assertEqual(response.status_code, 200)
        self.other.refresh_from_db()
        self.assertEqual(self.other.key, "other_group")

    def test_other_rows_remain_editable(self):
        response = self.client.post(
            f"/admin/core/coresettings/{self.other.pk}/change/",
            {"key": "other_group", "name": "Renamed", "value": '{"a": 3}'},
        )
        self.assertEqual(response.status_code, 302)
        self.other.refresh_from_db()
        self.assertEqual((self.other.name, self.other.value), ("Renamed", {"a": 3}))
