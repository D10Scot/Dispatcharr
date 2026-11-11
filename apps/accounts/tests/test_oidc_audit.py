"""``auth_config_changed`` audit events (SSO spec D18, section 7, T29 S1 half)."""

import json

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import OIDCProvider
from core.models import SystemEvent

from .oidc_support import (
    PROVIDERS,
    SECRET_SENTINEL,
    SETTINGS,
    admin_client,
    make_provider,
    set_auth_settings,
    standard_client,
)

URL_SENTINEL = "https://sentinel-url-4b2c.example.com"


def _events():
    return list(SystemEvent.objects.filter(event_type="auth_config_changed").order_by("id"))


class AuthConfigAuditTests(TestCase):
    def setUp(self):
        self.client, self.admin = admin_client()
        set_auth_settings()

    def _create(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                PROVIDERS,
                {
                    "slug": "kc",
                    "display_name": "Keycloak",
                    "issuer": "https://idp.example/realms/x",
                    "client_id": "cid",
                    "client_secret": SECRET_SENTINEL,
                },
                format="json",
            )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["id"]

    def test_audit_payload_names_fields_only(self):
        pk = self._create()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(
                f"{PROVIDERS}{pk}/", {"client_secret": "SENTINEL-ROTATED-31d7"}, format="json"
            )
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(SETTINGS, {"public_base_url": URL_SENTINEL}, format="json")

        events = _events()
        self.assertEqual(len(events), 3)
        blob = json.dumps([e.details for e in events])
        for sentinel in (SECRET_SENTINEL, "SENTINEL-ROTATED-31d7", URL_SENTINEL, "sentinel-url-4b2c"):
            self.assertNotIn(sentinel, blob, "an audit payload carries a value")
        created, rotated, settings_event = (e.details for e in events)
        self.assertEqual(created["action"], "provider_created")
        self.assertEqual(created["provider"], "kc")
        self.assertEqual(created["user"], "admin")
        self.assertIn("client_secret", created["fields"])
        self.assertNotIn("client_secret_encrypted", created["fields"])
        self.assertEqual(rotated["action"], "provider_updated")
        self.assertEqual(rotated["fields"], ["client_secret"])
        self.assertEqual(settings_event["action"], "auth_settings_updated")
        self.assertIsNone(settings_event["provider"])
        self.assertEqual(settings_event["fields"], ["public_base_url"])

    def test_fields_are_a_sorted_list_of_changed_names(self):
        pk = self._create()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(
                f"{PROVIDERS}{pk}/",
                {"display_name": "New", "claim_path": "groups", "client_id": "cid"},
                format="json",
            )
        details = _events()[-1].details
        self.assertEqual(details["fields"], ["claim_path", "display_name"])  # client_id unchanged

    def test_no_event_for_a_no_op(self):
        pk = self._create()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(f"{PROVIDERS}{pk}/", {"display_name": "Keycloak"}, format="json")
            self.client.patch(SETTINGS, {"public_base_url": ""}, format="json")
        self.assertEqual(len(_events()), 1)

    def test_delete_event(self):
        provider = make_provider()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(f"{PROVIDERS}{provider.pk}/")
        details = _events()[-1].details
        self.assertEqual(details["action"], "provider_deleted")
        self.assertEqual(details["provider"], "p1")

    def test_certificate_actions_record_field_names(self):
        provider = make_provider(client_auth_method="private_key_jwt", client_secret_encrypted="")
        url = f"{PROVIDERS}{provider.pk}/certificate/"
        with self.captureOnCommitCallbacks(execute=True):
            generated = self.client.post(url).json()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"{url}activate/", {"thumbprint_sha256": generated["thumbprint_sha256"]}, format="json"
            )
        generate_event, activate_event = (e.details for e in _events())
        self.assertEqual(generate_event["fields"], ["pending_client_certificate"])
        self.assertEqual(activate_event["fields"], ["client_auth_method", "client_certificate"])
        self.assertNotIn("PRIVATE KEY", json.dumps([generate_event, activate_event]))

    def test_refused_writes_leave_no_event(self):
        provider = make_provider(client_secret_encrypted="")
        with self.captureOnCommitCallbacks(execute=True):
            refused = [
                self.client.patch(f"{PROVIDERS}{provider.pk}/", {"enabled": True}, format="json"),
                self.client.patch(SETTINGS, {"password_login_enabled": False}, format="json"),
                self.client.patch(SETTINGS, {"public_base_url": "http://nope.example"}, format="json"),
                self.client.post(
                    f"{PROVIDERS}{provider.pk}/certificate/activate/",
                    {"thumbprint_sha256": "0" * 64},
                    format="json",
                ),
            ]
        self.assertEqual([r.status_code for r in refused], [400, 409, 400, 409])
        self.assertEqual(_events(), [])

    def test_a_rolled_back_write_leaves_no_event(self):
        # The event is queued with on_commit, so a transaction that never commits queues none.
        from django.db import transaction

        from apps.accounts.oidc import audit

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            try:
                with transaction.atomic():
                    audit.record_config_change("provider_updated", user="admin", fields=["x"])
                    raise RuntimeError("roll back")
            except RuntimeError:
                pass
        self.assertEqual(callbacks, [])
        self.assertEqual(_events(), [])

    def test_event_type_is_registered(self):
        from apps.connect.models import SUPPORTED_EVENTS

        self.assertIn("auth_config_changed", dict(SystemEvent.EVENT_TYPES))
        self.assertIn("auth_config_changed", SUPPORTED_EVENTS)
        self.assertIsNotNone(OIDCProvider)  # keep the import honest
        self.assertIsNotNone(APIClient)
        self.assertIsNotNone(standard_client)
