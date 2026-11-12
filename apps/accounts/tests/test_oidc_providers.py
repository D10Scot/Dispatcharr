"""OIDC provider admin API (SSO spec PR S1): storage, secrets, certificates, Entra preset.

Concurrency tests are ``TransactionTestCase``s that need real PostgreSQL (row locks) and skip
themselves elsewhere. They synchronise on ``threading.Event``/``Barrier`` objects held inside
wrappers around production functions; every wait is bounded and every ``finally`` releases
every event. No sleep stands in for a happens-before.
"""

import datetime
import threading
from unittest import mock, skipUnless

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from django.db import IntegrityError, connection, connections, transaction
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import OIDCIdentity, OIDCProvider, User
from apps.accounts.oidc import certificates, expiry, redirect
from apps.accounts.oidc import secrets as oidc_secrets
from apps.accounts.oidc.serializers import OIDCProviderSerializer
from core.models import AUTH_SETTINGS_KEY, CoreSettings

from .oidc_support import (
    CORE_SETTINGS,
    PROVIDERS,
    SECRET_SENTINEL,
    SETTINGS,
    TENANT,
    admin_client,
    base_url_for,
    make_entra,
    make_provider,
    set_auth_settings,
    standard_client,
)

JOIN = 10
PG_ONLY = skipUnless(connection.vendor == "postgresql", "needs PostgreSQL row locks")


def generic_body(**overrides):
    body = {
        "slug": "kc",
        "display_name": "Keycloak",
        "kind": "generic",
        "issuer": "https://idp.example/realms/x",
        "client_id": "client-1",
        "client_secret": SECRET_SENTINEL,
        "claim_path": "realm_access.roles",
        "mappings": [{"value": "admins", "user_level": 10}],
    }
    body.update(overrides)
    return body


def entra_body(**overrides):
    body = {
        "slug": "entra",
        "display_name": "Entra",
        "kind": "entra",
        "entra_tenant_id": TENANT,
        "client_id": "client-e",
        "client_secret": SECRET_SENTINEL,
    }
    body.update(overrides)
    return body


class ProviderModelTests(TestCase):
    def test_slug_is_unique(self):
        make_provider(slug="a")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_provider(slug="a")

    def test_identity_unique_per_provider_issuer_subject(self):
        provider = make_provider()
        user = User.objects.create_user(username="u1", password="x")
        other = User.objects.create_user(username="u2", password="x")
        OIDCIdentity.objects.create(
            user=user, provider=provider, issuer=provider.issuer, subject="sub-1"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            OIDCIdentity.objects.create(
                user=other, provider=provider, issuer=provider.issuer, subject="sub-1"
            )
        # A different subject, or the same subject at another provider, is fine.
        OIDCIdentity.objects.create(
            user=other, provider=provider, issuer=provider.issuer, subject="sub-2"
        )

    def test_provider_with_identities_cannot_be_deleted(self):
        provider = make_provider()
        user = User.objects.create_user(username="u1", password="x")
        OIDCIdentity.objects.create(
            user=user, provider=provider, issuer=provider.issuer, subject="s"
        )
        with self.assertRaises(ProtectedError):
            provider.delete()

    def test_deleting_the_user_cascades_to_the_identity(self):
        provider = make_provider()
        user = User.objects.create_user(username="u1", password="x")
        OIDCIdentity.objects.create(
            user=user, provider=provider, issuer=provider.issuer, subject="s"
        )
        user.delete()
        self.assertEqual(OIDCIdentity.objects.count(), 0)


class SecretsTests(TestCase):
    def test_round_trip_and_ciphertext_differs(self):
        token = oidc_secrets.encrypt(SECRET_SENTINEL)
        self.assertNotIn(SECRET_SENTINEL, token)
        self.assertEqual(oidc_secrets.decrypt(token), SECRET_SENTINEL)

    def test_each_kind_uses_its_own_key(self):
        token = oidc_secrets.encrypt("value", oidc_secrets.CLIENT_SECRET)
        with self.assertRaises(oidc_secrets.CredentialUnreadable):
            oidc_secrets.decrypt(token, oidc_secrets.CLIENT_KEY)

    def test_unreadable_after_secret_key_change(self):
        token = oidc_secrets.encrypt(SECRET_SENTINEL)
        with override_settings(SECRET_KEY="a-different-secret-key-entirely"):
            with self.assertRaises(oidc_secrets.CredentialUnreadable):
                oidc_secrets.decrypt(token)
            self.assertFalse(oidc_secrets.is_readable(token))
        self.assertTrue(oidc_secrets.is_readable(token))

    def test_provider_reports_credential_unreadable_after_key_change(self):
        client, _ = admin_client()
        provider = make_provider()
        url = f"{PROVIDERS}{provider.pk}/"
        self.assertFalse(client.get(url).json()["credential_unreadable"])
        with override_settings(SECRET_KEY="a-different-secret-key-entirely"):
            self.assertTrue(client.get(url).json()["credential_unreadable"])
            self.assertTrue(client.get(PROVIDERS).json()[0]["credential_unreadable"])

    def test_unreadable_key_is_reported_too(self):
        client, _ = admin_client()
        provider = make_provider()
        _, cert = certificates.generate_pair("p1")
        OIDCProvider.objects.filter(pk=provider.pk).update(
            client_key_encrypted=oidc_secrets.encrypt("not-a-real-key", oidc_secrets.CLIENT_KEY),
            client_cert_pem=cert,
        )
        with override_settings(SECRET_KEY="a-different-secret-key-entirely"):
            body = client.get(f"{PROVIDERS}{provider.pk}/").json()
        self.assertTrue(body["credential_unreadable"])


class ProviderSecretTests(TestCase):
    def setUp(self):
        self.client, self.admin = admin_client()
        set_auth_settings()

    def test_secret_never_in_responses(self):
        created = self.client.post(PROVIDERS, generic_body(), format="json")
        self.assertEqual(created.status_code, 201, created.content)
        pk = created.json()["id"]
        ciphertext = OIDCProvider.objects.get(pk=pk).client_secret_encrypted
        self.assertTrue(ciphertext)
        self.assertNotEqual(ciphertext, SECRET_SENTINEL)

        responses = {
            "create": created,
            "list": self.client.get(PROVIDERS),
            "detail": self.client.get(f"{PROVIDERS}{pk}/"),
            "update": self.client.patch(
                f"{PROVIDERS}{pk}/", {"display_name": "Renamed"}, format="json"
            ),
        }
        rotated = oidc_secrets.encrypt("SENTINEL-ROTATED-9c1d")
        self.assertNotEqual(rotated, ciphertext)
        responses["secret update"] = self.client.patch(
            f"{PROVIDERS}{pk}/", {"client_secret": "SENTINEL-ROTATED-9c1d"}, format="json"
        )
        for name, response in responses.items():
            text = response.content.decode()
            self.assertEqual(response.status_code // 100, 2, f"{name}: {text}")
            self.assertNotIn(SECRET_SENTINEL, text, f"{name} response leaks the secret")
            self.assertNotIn("SENTINEL-ROTATED-9c1d", text, f"{name} response leaks the secret")
            self.assertNotIn(
                ciphertext, text, f"{name} response carries the stored ciphertext"
            )
            self.assertNotIn("client_secret_encrypted", text)
        self.assertTrue(created.json()["client_secret_set"])

    def test_standard_user_core_settings_listing_has_no_secret(self):
        self.client.post(PROVIDERS, generic_body(), format="json")
        standard, _ = standard_client()
        response = standard.get(CORE_SETTINGS)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SECRET_SENTINEL, response.content.decode())
        self.assertNotIn("client_secret", response.content.decode())

    def test_database_column_is_not_plaintext_and_decrypts(self):
        pk = self.client.post(PROVIDERS, generic_body(), format="json").json()["id"]
        stored = OIDCProvider.objects.get(pk=pk).client_secret_encrypted
        self.assertNotIn(SECRET_SENTINEL, stored)
        self.assertEqual(oidc_secrets.decrypt(stored), SECRET_SENTINEL)

    def test_patch_without_secret_keeps_the_stored_value(self):
        pk = self.client.post(PROVIDERS, generic_body(), format="json").json()["id"]
        before = OIDCProvider.objects.get(pk=pk).client_secret_encrypted
        self.client.patch(f"{PROVIDERS}{pk}/", {"display_name": "x"}, format="json")
        self.assertEqual(OIDCProvider.objects.get(pk=pk).client_secret_encrypted, before)

    def test_empty_secret_is_refused_not_a_clear(self):
        pk = self.client.post(PROVIDERS, generic_body(), format="json").json()["id"]
        before = OIDCProvider.objects.get(pk=pk).client_secret_encrypted
        response = self.client.patch(f"{PROVIDERS}{pk}/", {"client_secret": ""}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(OIDCProvider.objects.get(pk=pk).client_secret_encrypted, before)

    def test_non_admin_cannot_use_the_provider_api(self):
        standard, _ = standard_client()
        self.assertEqual(standard.get(PROVIDERS).status_code, 403)
        self.assertEqual(standard.post(PROVIDERS, generic_body(), format="json").status_code, 403)


class ProviderCrudTests(TestCase):
    def setUp(self):
        self.client, self.admin = admin_client()
        set_auth_settings()

    def test_create_defaults_and_redirect_uri(self):
        set_auth_settings(public_base_url="https://mino.example.com")
        body = self.client.post(PROVIDERS, generic_body(), format="json").json()
        self.assertEqual(body["version"], 1)
        self.assertFalse(body["enabled"])
        self.assertEqual(body["client_auth_method"], "client_secret_basic")
        self.assertEqual(
            body["redirect_uri"], "https://mino.example.com/api/accounts/oidc/kc/callback/"
        )

    def test_delete_with_identities_is_409_and_keeps_the_row(self):
        provider = make_provider()
        user = User.objects.create_user(username="u1", password="x")
        OIDCIdentity.objects.create(
            user=user, provider=provider, issuer=provider.issuer, subject="s"
        )
        response = self.client.delete(f"{PROVIDERS}{provider.pk}/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"code": "provider_has_identities"})
        self.assertTrue(OIDCProvider.objects.filter(pk=provider.pk).exists())

    def test_delete_without_identities(self):
        provider = make_provider()
        self.assertEqual(self.client.delete(f"{PROVIDERS}{provider.pk}/").status_code, 204)
        self.assertFalse(OIDCProvider.objects.filter(pk=provider.pk).exists())

    def test_generic_issuer_must_be_https(self):
        response = self.client.post(
            PROVIDERS, generic_body(issuer="http://idp.example/realms/x"), format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("issuer", response.json())
        with override_settings(OIDC_ALLOW_HTTP=True):
            ok = self.client.post(
                PROVIDERS, generic_body(issuer="http://127.0.0.1:9/realms/x"), format="json"
            )
        self.assertEqual(ok.status_code, 201, ok.content)

    def test_generic_issuer_is_required_and_stored_unnormalised(self):
        body = generic_body()
        del body["issuer"]
        self.assertEqual(self.client.post(PROVIDERS, body, format="json").status_code, 400)
        ok = self.client.post(
            PROVIDERS, generic_body(issuer="https://idp.example/realms/x/"), format="json"
        )
        self.assertEqual(ok.json()["issuer"], "https://idp.example/realms/x/")

    def test_scopes_must_contain_openid(self):
        response = self.client.post(PROVIDERS, generic_body(scopes="profile email"), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("scopes", response.json())

    def test_id_token_alg_restricted(self):
        for bad in ("none", "HS256", "HS512", "RS1"):
            response = self.client.post(PROVIDERS, generic_body(id_token_alg=bad), format="json")
            self.assertEqual(response.status_code, 400, bad)
        self.assertEqual(
            self.client.post(
                PROVIDERS, generic_body(id_token_alg="ES256"), format="json"
            ).status_code,
            201,
        )

    def test_slug_shape(self):
        for bad in ("Upper", "has space", "a" * 41, "under_score"):
            response = self.client.post(PROVIDERS, generic_body(slug=bad), format="json")
            self.assertEqual(response.status_code, 400, bad)

    def test_reserved_slugs_refused(self):
        # Every literal path segment under /api/accounts/oidc/ in the spec's section 3.1
        # table: providers, providers-admin, settings, identities, exchange (first
        # segments), and link, start, callback (second segments).
        for reserved in (
            "providers", "providers-admin", "settings", "identities", "exchange",
            "link", "start", "callback",
        ):
            response = self.client.post(PROVIDERS, generic_body(slug=reserved), format="json")
            self.assertEqual(response.status_code, 400, reserved)
            self.assertIn("slug", response.json(), reserved)
        self.assertEqual(OIDCProvider.objects.count(), 0)
        provider = make_provider(slug="ok-one")
        renamed = self.client.patch(
            f"{PROVIDERS}{provider.pk}/", {"slug": "identities"}, format="json"
        )
        self.assertEqual(renamed.status_code, 400)
        self.assertEqual(
            self.client.post(PROVIDERS, generic_body(slug="settings-2"), format="json").status_code,
            201,
        )

    def test_put_is_not_allowed(self):
        provider = make_provider()
        response = self.client.put(
            f"{PROVIDERS}{provider.pk}/", generic_body(slug="p1"), format="json"
        )
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.patch(
            f"{PROVIDERS}{provider.pk}/", {"display_name": "x"}, format="json"
        ).status_code, 200)

    def test_claim_path_shape(self):
        for bad in ("a..b", ".a", "a.", "a b"):
            response = self.client.post(PROVIDERS, generic_body(claim_path=bad), format="json")
            self.assertEqual(response.status_code, 400, bad)

    def test_mapping_validation(self):
        bad_mappings = [
            "not a list",
            [{"value": "a"}],
            [{"value": "", "user_level": 1}],
            [{"value": "a", "user_level": 5}],
            [{"value": "a", "user_level": True}],
            [{"value": "a", "user_level": 10.0}],
            [{"value": "a", "user_level": 1.0}],
            [{"value": "a", "user_level": "1"}],
            [{"value": " ", "user_level": 1}],
            [{"value": "\t\n", "user_level": 1}],
            [{"value": "a", "user_level": 1}, {"value": "a", "user_level": 0}],
            [{"value": "x" * 257, "user_level": 1}],
            [{"value": f"v{i}", "user_level": 1} for i in range(51)],
            [{"value": "a", "user_level": 1, "extra": 1}],
        ]
        for mappings in bad_mappings:
            response = self.client.post(
                PROVIDERS, generic_body(mappings=mappings), format="json"
            )
            self.assertEqual(response.status_code, 400, mappings)
            self.assertIn("mappings", response.json())
        good = [{"value": f"v{i}", "user_level": [0, 1, 10][i % 3]} for i in range(50)]
        self.assertEqual(
            self.client.post(PROVIDERS, generic_body(mappings=good), format="json").status_code,
            201,
        )


class EnablingNeedsACredentialTests(TestCase):
    def setUp(self):
        self.client, _ = admin_client()
        set_auth_settings()

    def test_enable_without_secret_refused(self):
        provider = make_provider(client_secret_encrypted="")
        response = self.client.patch(
            f"{PROVIDERS}{provider.pk}/", {"enabled": True}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"code": "credential_missing"})
        provider.refresh_from_db()
        self.assertFalse(provider.enabled)

    def test_create_enabled_without_credential_refused(self):
        body = generic_body(enabled=True)
        del body["client_secret"]
        response = self.client.post(PROVIDERS, body, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"code": "credential_missing"})
        self.assertEqual(OIDCProvider.objects.count(), 0)

    def test_enable_with_secret_in_same_request(self):
        provider = make_provider(client_secret_encrypted="")
        response = self.client.patch(
            f"{PROVIDERS}{provider.pk}/",
            {"enabled": True, "client_secret": SECRET_SENTINEL},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_private_key_jwt_needs_an_active_pair_not_a_secret(self):
        provider = make_provider(client_auth_method="private_key_jwt")
        response = self.client.patch(
            f"{PROVIDERS}{provider.pk}/", {"enabled": True}, format="json"
        )
        self.assertEqual(response.json(), {"code": "credential_missing"})

    def test_certificate_path_create_disabled_generate_activate_enable(self):
        body = generic_body(client_auth_method="private_key_jwt")
        del body["client_secret"]
        created = self.client.post(PROVIDERS, body, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        pk = created.json()["id"]
        generated = self.client.post(f"{PROVIDERS}{pk}/certificate/").json()
        activated = self.client.post(
            f"{PROVIDERS}{pk}/certificate/activate/",
            {"thumbprint_sha256": generated["thumbprint_sha256"]},
            format="json",
        )
        self.assertEqual(activated.status_code, 200, activated.content)
        enabled = self.client.patch(f"{PROVIDERS}{pk}/", {"enabled": True}, format="json")
        self.assertEqual(enabled.status_code, 200, enabled.content)


class EntraPresetTests(TestCase):
    def setUp(self):
        self.client, _ = admin_client()
        set_auth_settings()

    def test_multi_tenant_aliases_refused(self):
        for alias in ("common", "organizations", "consumers", "contoso.onmicrosoft.com", ""):
            response = self.client.post(
                PROVIDERS, entra_body(entra_tenant_id=alias), format="json"
            )
            self.assertEqual(response.status_code, 400, f"{alias!r}: {response.content}")
            self.assertEqual(
                response.json(),
                {"entra_tenant_id": ["must be a tenant GUID"]},
                alias,
            )
        self.assertEqual(OIDCProvider.objects.count(), 0)

    def test_issuer_is_derived_and_input_issuer_ignored(self):
        response = self.client.post(
            PROVIDERS,
            entra_body(entra_tenant_id=TENANT.upper(), issuer="https://evil.example/"),
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["issuer"], f"https://login.microsoftonline.com/{TENANT}/v2.0")
        self.assertEqual(body["entra_tenant_id"], TENANT)

    def test_defaults_to_post_claim_roles_and_ps256(self):
        body = self.client.post(PROVIDERS, entra_body(), format="json").json()
        self.assertEqual(body["client_auth_method"], "client_secret_post")
        self.assertEqual(body["claim_path"], "roles")
        self.assertEqual(body["client_assertion_alg"], "PS256")
        self.assertFalse(body["allow_private_network"])

    def test_refuses_basic_auth_method(self):
        response = self.client.post(
            PROVIDERS, entra_body(client_auth_method="client_secret_basic"), format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("client_auth_method", response.json())

    def test_private_key_jwt_is_offered(self):
        body = entra_body(client_auth_method="private_key_jwt")
        del body["client_secret"]
        self.assertEqual(self.client.post(PROVIDERS, body, format="json").status_code, 201)

    def test_entra_preset_refuses_private_flag(self):
        response = self.client.post(
            PROVIDERS, entra_body(allow_private_network=True), format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("allow_private_network", response.json())
        provider = make_entra()
        patched = self.client.patch(
            f"{PROVIDERS}{provider.pk}/", {"allow_private_network": True}, format="json"
        )
        self.assertEqual(patched.status_code, 400)

    def test_generic_provider_may_set_private_flag(self):
        response = self.client.post(
            PROVIDERS, generic_body(allow_private_network=True), format="json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["allow_private_network"])

    def test_switching_a_generic_provider_to_entra_validates_the_preset(self):
        provider = make_provider()
        response = self.client.patch(
            f"{PROVIDERS}{provider.pk}/", {"kind": "entra"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("entra_tenant_id", response.json())

    def test_redirect_uri_over_256_refused(self):
        slug_ok, slug_long = "tenant-x", "tenant-xy"
        base256 = base_url_for(256, slug_ok)
        set_auth_settings(public_base_url=base256)
        ok = self.client.post(PROVIDERS, entra_body(slug=slug_ok), format="json")
        self.assertEqual(ok.status_code, 201, ok.content)
        self.assertEqual(len(ok.json()["redirect_uri"]), 256)

        # One character more through the slug.
        long = self.client.post(PROVIDERS, entra_body(slug=slug_long), format="json")
        self.assertEqual(
            long.status_code, 400, "a 257-character Entra redirect URI was accepted"
        )
        self.assertEqual(long.json(), {"code": "redirect_uri_too_long"})
        self.assertFalse(OIDCProvider.objects.filter(slug=slug_long).exists())

        # The same through a slug edit of the existing provider.
        pk = ok.json()["id"]
        edit = self.client.patch(f"{PROVIDERS}{pk}/", {"slug": slug_long}, format="json")
        self.assertEqual(edit.status_code, 400)
        self.assertEqual(edit.json(), {"code": "redirect_uri_too_long"})

        # And through a public_base_url change that pushes an existing provider past 256.
        longer_base = base_url_for(257, slug_ok)
        patched = self.client.patch(SETTINGS, {"public_base_url": longer_base}, format="json")
        self.assertEqual(patched.status_code, 400)
        self.assertEqual(patched.json(), {"code": "redirect_uri_too_long"})
        self.assertEqual(CoreSettings.get_auth_settings()["public_base_url"], base256)

    def test_generic_provider_has_no_length_limit(self):
        set_auth_settings(public_base_url=base_url_for(300, "kc"))
        self.assertEqual(self.client.post(PROVIDERS, generic_body(), format="json").status_code, 201)

    def test_kind_edit_to_entra_is_length_checked(self):
        provider = make_provider(slug="kc", client_auth_method="client_secret_post")
        set_auth_settings(public_base_url=base_url_for(300, "kc"))
        response = self.client.patch(
            f"{PROVIDERS}{provider.pk}/",
            {"kind": "entra", "entra_tenant_id": TENANT},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"code": "redirect_uri_too_long"})


@PG_ONLY
class EntraRedirectRaceTests(TransactionTestCase):
    def test_slug_edit_racing_base_url_edit_cannot_exceed_256(self):
        slug = "s" * 20
        longer_slug = "s" * 30
        base = base_url_for(240, slug)
        # Lengthen the base by exactly 10 characters.
        longer_base = base.replace(".example.com", "a" * 10 + ".example.com")
        self.assertEqual(len(longer_base), len(base) + 10)

        admin = User.objects.create_user(
            username="admin", password="x", user_level=User.UserLevel.ADMIN
        )
        set_auth_settings(public_base_url=base)
        provider = make_entra(slug=slug)

        barrier = threading.Barrier(2, timeout=2)
        original = redirect.ensure_entra_redirect_fits

        def wrapped(*args, **kwargs):
            original(*args, **kwargs)  # validate against what was just read
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass

        results = {}

        def send(name, call):
            try:
                client = APIClient()
                client.force_authenticate(admin)
                results[name] = call(client)
            finally:
                connections.close_all()

        threads = [
            threading.Thread(
                target=send,
                args=(
                    "slug",
                    lambda c: c.patch(
                        f"{PROVIDERS}{provider.pk}/", {"slug": longer_slug}, format="json"
                    ),
                ),
            ),
            threading.Thread(
                target=send,
                args=(
                    "base",
                    lambda c: c.patch(SETTINGS, {"public_base_url": longer_base}, format="json"),
                ),
            ),
        ]
        with mock.patch.object(redirect, "ensure_entra_redirect_fits", wrapped):
            for t in threads:
                t.start()
            for t in threads:
                t.join(JOIN)
        self.assertFalse(any(t.is_alive() for t in threads), "a request hung")

        statuses = sorted(r.status_code for r in results.values())
        committed = len(
            redirect.redirect_uri(
                CoreSettings.get_auth_settings()["public_base_url"],
                OIDCProvider.objects.get(pk=provider.pk).slug,
            )
        )
        self.assertEqual(
            statuses,
            [200, 400],
            f"exactly one edit may win; got {statuses} and a committed redirect URI of "
            f"{committed} characters (Entra accepts 256)",
        )
        self.assertEqual(committed, 250)


class ProviderImmutabilityTests(TestCase):
    def setUp(self):
        self.client, _ = admin_client()
        set_auth_settings()
        self.entra = make_entra()
        user = User.objects.create_user(username="linked", password="x")
        OIDCIdentity.objects.create(
            user=user, provider=self.entra, issuer=self.entra.issuer, subject="sub-1"
        )

    def _patch(self, provider, body):
        return self.client.patch(f"{PROVIDERS}{provider.pk}/", body, format="json")

    def test_client_id_change_refused_with_identities(self):
        before = self.entra.client_id
        response = self._patch(self.entra, {"client_id": "another-app"})
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("client_id", response.json())
        self.entra.refresh_from_db()
        self.assertEqual(self.entra.client_id, before)

    def test_tenant_change_refused_with_identities(self):
        other = "99999999-8888-7777-6666-555555555555"
        response = self._patch(self.entra, {"entra_tenant_id": other})
        self.assertEqual(response.status_code, 400)
        self.entra.refresh_from_db()
        self.assertEqual(self.entra.entra_tenant_id, TENANT)

    def test_generic_issuer_change_refused_with_identities(self):
        generic = make_provider(slug="g")
        user = User.objects.create_user(username="linked2", password="x")
        OIDCIdentity.objects.create(
            user=user, provider=generic, issuer=generic.issuer, subject="s"
        )
        response = self._patch(generic, {"issuer": "https://other.example/realms/x"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("issuer", response.json())

    def test_unchanged_value_and_other_fields_are_allowed(self):
        self.assertEqual(self._patch(self.entra, {"client_id": self.entra.client_id}).status_code, 200)
        self.assertEqual(self._patch(self.entra, {"display_name": "New"}).status_code, 200)

    def test_changes_are_allowed_without_identities(self):
        free = make_provider(slug="free")
        self.assertEqual(self._patch(free, {"client_id": "new-id"}).status_code, 200)


class ProviderVersionTests(TestCase):
    def setUp(self):
        self.client, _ = admin_client()
        set_auth_settings()
        self.provider = make_provider()

    def _version(self):
        return OIDCProvider.objects.get(pk=self.provider.pk).version

    def _patch(self, body):
        response = self.client.patch(f"{PROVIDERS}{self.provider.pk}/", body, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def test_security_relevant_edits_bump_version(self):
        start = self._version()
        self._patch({"mappings": [{"value": "x", "user_level": 1}]})
        self.assertEqual(self._version(), start + 1)
        self._patch({"claim_path": "groups"})
        self.assertEqual(self._version(), start + 2)
        self._patch({"client_secret": "SENTINEL-NEW-SECRET"})
        self.assertEqual(self._version(), start + 3)
        self._patch({"slug": "renamed"})
        self.assertEqual(self._version(), start + 4)
        self._patch({"scopes": "openid email"})
        self.assertEqual(self._version(), start + 5)

    def test_cosmetic_edits_do_not_bump_version(self):
        start = self._version()
        self._patch({"display_name": "Cosmetic"})
        self._patch({"client_secret_expires_at": "2030-01-01"})
        self._patch({"prompt_select_account": True})
        self.assertEqual(self._version(), start)

    def test_a_no_op_patch_changes_nothing(self):
        start = self._version()
        self._patch({"claim_path": self.provider.claim_path})
        self.assertEqual(self._version(), start)


class CredentialExpiryTests(TestCase):
    def setUp(self):
        self.client, _ = admin_client()
        set_auth_settings()
        self.today = timezone.now().date()

    def _expiry(self, provider):
        return self.client.get(f"{PROVIDERS}{provider.pk}/").json()["credential_expiry"]

    def _with_cert(self, provider):
        key, cert = certificates.generate_pair(provider.slug)
        OIDCProvider.objects.filter(pk=provider.pk).update(
            client_key_encrypted=oidc_secrets.encrypt(key, oidc_secrets.CLIENT_KEY),
            client_cert_pem=cert,
        )
        return certificates.not_after(cert).date()

    def test_states_at_the_boundaries(self):
        provider = make_provider()
        cases = [
            (None, "unknown", None),
            (self.today + datetime.timedelta(days=31), "ok", 31),
            (self.today + datetime.timedelta(days=30), "expiring", 30),
            (self.today, "expiring", 0),
            (self.today - datetime.timedelta(days=1), "expired", -1),
        ]
        for date, state, days in cases:
            provider.client_secret_expires_at = date
            info = expiry.credential_expiry(provider, today=self.today)
            self.assertEqual((info["state"], info["days_left"]), (state, days), date)

    def test_api_reports_expiry(self):
        provider = make_provider(
            client_secret_expires_at=self.today + datetime.timedelta(days=30)
        )
        info = self._expiry(provider)
        self.assertEqual(info["state"], "expiring")
        self.assertEqual(info["days_left"], 30)
        self.assertEqual(info["expires_at"], provider.client_secret_expires_at.isoformat())

    def test_credential_warnings_list_enabled_expiring_providers_only(self):
        make_provider(
            slug="soon",
            enabled=True,
            client_secret_expires_at=self.today + datetime.timedelta(days=5),
        )
        make_provider(
            slug="gone",
            enabled=True,
            client_secret_expires_at=self.today - datetime.timedelta(days=2),
        )
        make_provider(
            slug="off",
            enabled=False,
            client_secret_expires_at=self.today - datetime.timedelta(days=2),
        )
        make_provider(
            slug="fine",
            enabled=True,
            client_secret_expires_at=self.today + datetime.timedelta(days=200),
        )
        warnings = self.client.get(SETTINGS).json()["credential_warnings"]
        self.assertEqual(
            {w["slug"]: w["state"] for w in warnings}, {"soon": "expiring", "gone": "expired"}
        )

    def test_warnings_are_for_admins_only(self):
        make_provider(
            enabled=True, client_secret_expires_at=self.today - datetime.timedelta(days=1)
        )
        standard, _ = standard_client()
        body = standard.get(SETTINGS).json()
        self.assertNotIn("credential_warnings", body)
        self.assertEqual(set(body), {"public_base_url", "password_login_enabled"})

    def test_switch_back_to_secret_reports_the_secrets_own_expiry(self):
        provider = make_provider(client_secret_expires_at=self.today - datetime.timedelta(days=1))
        not_after = self._with_cert(provider)
        OIDCProvider.objects.filter(pk=provider.pk).update(client_auth_method="private_key_jwt")
        info = self._expiry(provider)
        self.assertEqual(info["state"], "ok")
        self.assertEqual(info["expires_at"], not_after.isoformat())
        self.client.patch(
            f"{PROVIDERS}{provider.pk}/", {"client_auth_method": "client_secret_post"}, format="json"
        )
        info = self._expiry(provider)
        self.assertEqual(
            info["state"],
            "expired",
            "after switching back to the secret, the certificate's notAfter was still reported",
        )
        self.assertEqual(
            info["expires_at"], (self.today - datetime.timedelta(days=1)).isoformat()
        )

    def test_secret_with_no_date_is_unknown_after_switch_back(self):
        provider = make_provider(client_secret_expires_at=None)
        self._with_cert(provider)
        OIDCProvider.objects.filter(pk=provider.pk).update(client_auth_method="private_key_jwt")
        self.assertEqual(self._expiry(provider)["state"], "ok")
        self.client.patch(
            f"{PROVIDERS}{provider.pk}/", {"client_auth_method": "client_secret_post"}, format="json"
        )
        info = self._expiry(provider)
        self.assertEqual(info["state"], "unknown")
        self.assertIsNone(info["expires_at"])

    def test_new_secret_without_date_resets_expiry(self):
        provider = make_provider(client_secret_expires_at=self.today + datetime.timedelta(days=90))
        response = self.client.patch(
            f"{PROVIDERS}{provider.pk}/", {"client_secret": "SENTINEL-NEW"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        provider.refresh_from_db()
        self.assertIsNone(provider.client_secret_expires_at)

    def test_new_secret_with_a_date_keeps_that_date(self):
        provider = make_provider()
        self.client.patch(
            f"{PROVIDERS}{provider.pk}/",
            {"client_secret": "SENTINEL-NEW", "client_secret_expires_at": "2031-02-03"},
            format="json",
        )
        provider.refresh_from_db()
        self.assertEqual(provider.client_secret_expires_at, datetime.date(2031, 2, 3))


class ProviderCertificateTests(TestCase):
    def setUp(self):
        self.client, _ = admin_client()
        set_auth_settings()
        self.provider = make_provider(
            client_auth_method="private_key_jwt", client_secret_encrypted=""
        )
        self.url = f"{PROVIDERS}{self.provider.pk}/certificate/"

    def _generate(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def _activate(self, thumbprint=None):
        body = {} if thumbprint is None else {"thumbprint_sha256": thumbprint}
        return self.client.post(f"{self.url}activate/", body, format="json")

    def test_private_key_never_in_any_response(self):
        generated = self._generate()
        thumb = generated.json()["thumbprint_sha256"]
        activated = self._activate(thumb)
        self.assertEqual(activated.status_code, 200, activated.content)
        bodies = {
            "generate": generated,
            "activate": activated,
            "download": self.client.get(f"{self.url}?slot=active"),
            "list": self.client.get(PROVIDERS),
            "detail": self.client.get(f"{PROVIDERS}{self.provider.pk}/"),
        }
        for name, response in bodies.items():
            text = response.content.decode()
            self.assertNotIn("PRIVATE KEY", text, f"{name} response carries a private key")
        provider = OIDCProvider.objects.get(pk=self.provider.pk)
        self.assertNotIn("PRIVATE KEY", provider.client_key_encrypted)
        # ... while the stored ciphertext really is a key.
        self.assertIn(
            "PRIVATE KEY",
            oidc_secrets.decrypt(provider.client_key_encrypted, oidc_secrets.CLIENT_KEY),
        )

    def test_download_is_the_public_certificate(self):
        self._generate()
        response = self.client.get(f"{self.url}?slot=pending")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/x-pem-file")
        cert = x509.load_pem_x509_certificate(response.content)
        provider = OIDCProvider.objects.get(pk=self.provider.pk)
        key = serialization.load_pem_private_key(
            oidc_secrets.decrypt(
                provider.pending_client_key_encrypted, oidc_secrets.CLIENT_KEY
            ).encode(),
            password=None,
        )
        self.assertEqual(
            cert.public_key().public_numbers(), key.public_key().public_numbers()
        )
        self.assertEqual(cert.subject.rfc4514_string(), "CN=mino-oidc-p1")
        span = cert.not_valid_after_utc - cert.not_valid_before_utc
        self.assertAlmostEqual(span.days, 730, delta=1)

    def test_download_of_an_empty_slot_is_404(self):
        self.assertEqual(self.client.get(f"{self.url}?slot=pending").status_code, 404)
        self.assertEqual(self.client.get(f"{self.url}?slot=active").status_code, 404)
        self.assertEqual(self.client.get(f"{self.url}?slot=bogus").status_code, 400)

    def test_generate_fills_pending_and_leaves_active(self):
        first = self._generate().json()
        self._activate(first["thumbprint_sha256"])
        active_before = OIDCProvider.objects.get(pk=self.provider.pk).client_cert_pem
        second = self._generate().json()
        provider = OIDCProvider.objects.get(pk=self.provider.pk)
        self.assertEqual(provider.client_cert_pem, active_before, "active slot was overwritten")
        self.assertEqual(
            certificates.thumbprint_sha256(provider.client_cert_pem), first["thumbprint_sha256"]
        )
        self.assertEqual(
            certificates.thumbprint_sha256(provider.pending_client_cert_pem),
            second["thumbprint_sha256"],
        )
        self.assertNotEqual(first["thumbprint_sha256"], second["thumbprint_sha256"])

    def test_generating_does_not_bump_version(self):
        start = OIDCProvider.objects.get(pk=self.provider.pk).version
        self._generate()
        self.assertEqual(OIDCProvider.objects.get(pk=self.provider.pk).version, start)

    def test_activate_promotes_the_named_certificate(self):
        OIDCProvider.objects.filter(pk=self.provider.pk).update(
            client_auth_method="client_secret_post"
        )
        start = OIDCProvider.objects.get(pk=self.provider.pk).version
        generated = self._generate().json()
        response = self._activate(generated["thumbprint_sha256"])
        self.assertEqual(response.status_code, 200, response.content)
        provider = OIDCProvider.objects.get(pk=self.provider.pk)
        self.assertEqual(
            certificates.thumbprint_sha256(provider.client_cert_pem),
            generated["thumbprint_sha256"],
        )
        self.assertEqual(provider.pending_client_cert_pem, "")
        self.assertEqual(provider.pending_client_key_encrypted, "")
        self.assertEqual(provider.client_auth_method, "private_key_jwt")
        self.assertEqual(provider.version, start + 1)
        info = response.json()["credential_expiry"]
        self.assertEqual(
            info["expires_at"], certificates.not_after(provider.client_cert_pem).date().isoformat()
        )
        self.assertEqual(
            response.json()["client_certificate"]["active"]["thumbprint_sha256"],
            generated["thumbprint_sha256"],
        )

    def test_activation_keeps_the_stored_secret(self):
        provider = make_provider(slug="both")
        url = f"{PROVIDERS}{provider.pk}/certificate/"
        generated = self.client.post(url).json()
        self.client.post(
            f"{url}activate/", {"thumbprint_sha256": generated["thumbprint_sha256"]}, format="json"
        )
        provider.refresh_from_db()
        self.assertTrue(provider.client_secret_encrypted)

    def test_stale_activation_refused(self):
        a = self._generate().json()
        self._generate()  # certificate B replaces A in the pending slot
        provider_before = OIDCProvider.objects.get(pk=self.provider.pk)
        b_thumb = certificates.thumbprint_sha256(provider_before.pending_client_cert_pem)
        self.assertNotEqual(a["thumbprint_sha256"], b_thumb)

        response = self._activate(a["thumbprint_sha256"])
        self.assertEqual(
            response.status_code,
            409,
            "activation promoted a pending certificate other than the one named",
        )
        self.assertEqual(response.json(), {"code": "pending_certificate_changed"})
        provider = OIDCProvider.objects.get(pk=self.provider.pk)
        self.assertEqual(provider.client_cert_pem, "", "the active pair changed")
        self.assertEqual(provider.client_auth_method, "private_key_jwt")
        self.assertEqual(provider.version, provider_before.version)
        self.assertEqual(
            certificates.thumbprint_sha256(provider.pending_client_cert_pem), b_thumb
        )

    def test_activation_without_a_body_or_a_pending_slot_is_409(self):
        self._generate()
        response = self._activate()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"code": "pending_certificate_changed"})
        # Nothing pending at all.
        OIDCProvider.objects.filter(pk=self.provider.pk).update(
            pending_client_cert_pem="", pending_client_key_encrypted=""
        )
        self.assertEqual(self._activate("0" * 64).status_code, 409)

    def test_malformed_thumbprints_answer_409_and_write_nothing(self):
        self._generate()
        before = OIDCProvider.objects.get(pk=self.provider.pk)
        bad = ["é" * 64, "é", "zz" * 32, "g" * 64, "abc", " ", "0" * 63, "0" * 65, "\u0661" * 64]
        for thumbprint in bad:
            response = self._activate(thumbprint)
            self.assertEqual(response.status_code, 409, f"{thumbprint!r}: {response.content}")
            self.assertEqual(response.json(), {"code": "pending_certificate_changed"})
        after = OIDCProvider.objects.get(pk=self.provider.pk)
        self.assertEqual(after.client_cert_pem, "")
        self.assertEqual(after.pending_client_cert_pem, before.pending_client_cert_pem)
        self.assertEqual(after.version, before.version)

    def test_uppercase_hex_thumbprint_is_accepted(self):
        generated = self._generate().json()
        response = self._activate(generated["thumbprint_sha256"].upper())
        self.assertEqual(response.status_code, 200, response.content)

    def test_non_numeric_ids_answer_404_on_every_certificate_route(self):
        for suffix, method in (
            ("certificate/", "post"),
            ("certificate/", "get"),
            ("certificate/activate/", "post"),
            ("test/", "post"),
        ):
            response = getattr(self.client, method)(f"{PROVIDERS}abc/{suffix}")
            self.assertEqual(response.status_code, 404, f"{method} {suffix}")

    def test_non_admin_cannot_generate_or_download(self):
        standard, _ = standard_client()
        self.assertEqual(standard.post(self.url).status_code, 403)
        self.assertEqual(standard.get(f"{self.url}?slot=active").status_code, 403)

    def test_certificate_actions_404_for_a_missing_provider(self):
        self.assertEqual(self.client.post(f"{PROVIDERS}99999/certificate/").status_code, 404)
        self.assertEqual(
            self.client.post(
                f"{PROVIDERS}99999/certificate/activate/", {"thumbprint_sha256": "a"}, format="json"
            ).status_code,
            404,
        )


@PG_ONLY
class ProviderPartialWriteTests(TransactionTestCase):
    """T15a: a provider write never re-saves a stale column."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin", password="x", user_level=User.UserLevel.ADMIN
        )
        set_auth_settings()
        self.provider = make_provider()
        self.url = f"{PROVIDERS}{self.provider.pk}/"
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _held(self, target_owner, target_name, request_call):
        """Run ``request_call`` on a thread, held inside the first call to ``target``.

        Returns ``(entered, release, thread, result)``. The hold is placed after the view has
        loaded its instance, so the request carries a stale copy of the row.
        """
        entered, release = threading.Event(), threading.Event()
        result = {}
        original = getattr(target_owner, target_name)
        first = []

        def held(*args, **kwargs):
            if not first:
                first.append(True)
                entered.set()
                release.wait(JOIN)
            return original(*args, **kwargs)

        def run():
            try:
                client = APIClient()
                client.force_authenticate(self.admin)
                result["response"] = request_call(client)
            finally:
                connections.close_all()

        return entered, release, threading.Thread(target=run), result, held

    def test_stale_patch_does_not_resave_enabled(self):
        entered, release, thread, result, held = self._held(
            OIDCProviderSerializer,
            "update",
            lambda c: c.patch(self.url, {"display_name": "Held rename"}, format="json"),
        )
        try:
            with mock.patch.object(OIDCProviderSerializer, "update", held):
                thread.start()
                self.assertTrue(entered.wait(JOIN), "the held PATCH never reached update()")
                enabled = self.client.patch(self.url, {"enabled": True}, format="json")
                self.assertEqual(enabled.status_code, 200, enabled.content)
                release.set()
                thread.join(JOIN)
        finally:
            release.set()
            if thread.ident is not None:
                thread.join(JOIN)
        self.assertEqual(result["response"].status_code, 200, result["response"].content)
        provider = OIDCProvider.objects.get(pk=self.provider.pk)
        self.assertTrue(
            provider.enabled,
            "a stale PATCH wrote enabled=False back over a committed enable "
            "(full-row save instead of a column-restricted update)",
        )
        self.assertEqual(provider.display_name, "Held rename")

    def test_stale_certificate_action_does_not_resave_enabled(self):
        entered, release, thread, result, held = self._held(
            certificates,
            "generate_pair",
            lambda c: c.post(f"{self.url}certificate/"),
        )
        try:
            with mock.patch.object(certificates, "generate_pair", held):
                thread.start()
                self.assertTrue(entered.wait(JOIN), "certificate generation never started")
                enabled = self.client.patch(self.url, {"enabled": True}, format="json")
                self.assertEqual(enabled.status_code, 200, enabled.content)
                release.set()
                thread.join(JOIN)
        finally:
            release.set()
            if thread.ident is not None:
                thread.join(JOIN)
        self.assertEqual(result["response"].status_code, 200, result["response"].content)
        provider = OIDCProvider.objects.get(pk=self.provider.pk)
        self.assertTrue(provider.enabled, "certificate generation wrote a stale enabled back")
        self.assertTrue(provider.pending_client_cert_pem)

    def test_concurrent_security_edits_both_bump_version(self):
        start = OIDCProvider.objects.get(pk=self.provider.pk).version
        entered, release, thread, result, held = self._held(
            OIDCProviderSerializer,
            "update",
            lambda c: c.patch(self.url, {"claim_path": "groups"}, format="json"),
        )
        try:
            with mock.patch.object(OIDCProviderSerializer, "update", held):
                thread.start()
                self.assertTrue(entered.wait(JOIN))
                second = self.client.patch(self.url, {"scopes": "openid email"}, format="json")
                self.assertEqual(second.status_code, 200, second.content)
                release.set()
                thread.join(JOIN)
        finally:
            release.set()
            if thread.ident is not None:
                thread.join(JOIN)
        self.assertEqual(result["response"].status_code, 200, result["response"].content)
        provider = OIDCProvider.objects.get(pk=self.provider.pk)
        self.assertEqual(provider.version, start + 2, "a version bump was lost")
        self.assertEqual(provider.claim_path, "groups")
        self.assertEqual(provider.scopes, "openid email")


class RuntimeSqliteTests(TestCase):
    def test_provider_create_refused_on_runtime_sqlite(self):
        client, _ = admin_client()
        set_auth_settings()
        with override_settings(RUNTIME_SQLITE=True):
            response = client.post(PROVIDERS, generic_body(), format="json")
        self.assertEqual(
            response.status_code, 400, "a provider was created on a runtime SQLite instance"
        )
        self.assertEqual(response.json(), {"code": "requires_postgresql"})
        self.assertEqual(OIDCProvider.objects.count(), 0)

    def test_updates_and_deletes_still_work_on_runtime_sqlite(self):
        client, _ = admin_client()
        set_auth_settings()
        provider = make_provider()
        with override_settings(RUNTIME_SQLITE=True):
            self.assertEqual(
                client.patch(
                    f"{PROVIDERS}{provider.pk}/", {"display_name": "x"}, format="json"
                ).status_code,
                200,
            )
            self.assertEqual(client.delete(f"{PROVIDERS}{provider.pk}/").status_code, 204)


class SettingsEndpointTests(TestCase):
    def setUp(self):
        self.client, _ = admin_client()
        set_auth_settings()

    def test_seed_migration_creates_the_group(self):
        import importlib

        from django.apps import apps

        migration = importlib.import_module("core.migrations.0030_seed_auth_settings")
        CoreSettings.objects.filter(key=AUTH_SETTINGS_KEY).delete()
        migration.seed_auth_settings(apps, None)
        row = CoreSettings.objects.get(key=AUTH_SETTINGS_KEY)
        self.assertEqual(row.value, {"public_base_url": "", "password_login_enabled": True})
        # Re-running keeps an existing row's value.
        CoreSettings.objects.filter(key=AUTH_SETTINGS_KEY).update(
            value={"public_base_url": "https://kept.example", "password_login_enabled": True}
        )
        migration.seed_auth_settings(apps, None)
        self.assertEqual(
            CoreSettings.objects.get(key=AUTH_SETTINGS_KEY).value["public_base_url"],
            "https://kept.example",
        )

    def test_get_auth_settings_defaults_when_the_row_is_missing(self):
        CoreSettings.objects.filter(key=AUTH_SETTINGS_KEY).delete()
        self.assertEqual(
            CoreSettings.get_auth_settings(),
            {"public_base_url": "", "password_login_enabled": True},
        )

    def test_get_auth_settings_bypasses_the_cache(self):
        CoreSettings._get_group(AUTH_SETTINGS_KEY, {})  # warm the group cache
        CoreSettings.objects.filter(key=AUTH_SETTINGS_KEY).update(
            value={"public_base_url": "https://direct.example", "password_login_enabled": True}
        )  # a queryset update fires no signal, so the cache stays stale
        self.assertEqual(
            CoreSettings.get_auth_settings()["public_base_url"], "https://direct.example"
        )

    def test_patch_works_when_the_row_is_missing(self):
        CoreSettings.objects.filter(key=AUTH_SETTINGS_KEY).delete()
        response = self.client.patch(
            SETTINGS, {"public_base_url": "https://mino.example.com/"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["public_base_url"], "https://mino.example.com")

    def test_password_toggle_off_without_an_sso_session_is_refused_by_the_guard(self):
        # S4 replaced S1's unconditional refusal with the lockout guard (spec 5.5). An admin
        # with no SSO token, with a provider and with a valid URL in the same request, is
        # refused on every condition of the rule, and nothing is written.
        make_provider(enabled=True)
        for body in (
            {"password_login_enabled": False},
            {"password_login_enabled": False, "public_base_url": "https://mino.example.com"},
        ):
            response = self.client.patch(SETTINGS, body, format="json")
            self.assertEqual(response.status_code, 409)
            self.assertEqual(
                response.json(),
                {
                    "code": "lockout_guard",
                    "reasons": ["not_sso_session", "provider_not_enabled", "not_admin_at_sign_in"],
                },
            )
        values = CoreSettings.get_auth_settings()
        self.assertTrue(values["password_login_enabled"])
        self.assertEqual(values["public_base_url"], "", "the refused request still wrote a URL")

    def test_password_toggle_on_is_accepted(self):
        response = self.client.patch(SETTINGS, {"password_login_enabled": True}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_get_is_open_to_standard_users_and_patch_is_not(self):
        standard, _ = standard_client()
        self.assertEqual(standard.get(SETTINGS).status_code, 200)
        self.assertEqual(
            standard.patch(SETTINGS, {"public_base_url": "https://x.example"}, format="json").status_code,
            403,
        )
        self.assertEqual(APIClient().get(SETTINGS).status_code, 401)

    def test_public_base_url_cleartext_refused(self):
        response = self.client.patch(
            SETTINGS, {"public_base_url": "http://mino.example"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"code": "public_base_url_insecure"})
        self.assertEqual(CoreSettings.get_auth_settings()["public_base_url"], "")

    def test_public_base_url_loopback_http_accepted(self):
        for url in ("http://localhost:9191", "http://127.0.0.1:9191", "http://[::1]:9191"):
            response = self.client.patch(SETTINGS, {"public_base_url": url}, format="json")
            self.assertEqual(response.status_code, 200, f"{url}: {response.content}")
        self.assertEqual(
            CoreSettings.get_auth_settings()["public_base_url"], "http://[::1]:9191"
        )

    def test_public_base_url_http_allowed_by_deployment_switch(self):
        with override_settings(OIDC_ALLOW_HTTP=True):
            response = self.client.patch(
                SETTINGS, {"public_base_url": "http://mino.example"}, format="json"
            )
        self.assertEqual(response.status_code, 200, response.content)

    def test_public_base_url_shape(self):
        for bad in (
            "mino.example",
            "ftp://mino.example",
            "https://user@mino.example",
            "https://mino.example/sub",
            "https://mino.example/?q=1",
            "https://mino.example/#frag",
            "https://",
        ):
            response = self.client.patch(SETTINGS, {"public_base_url": bad}, format="json")
            self.assertEqual(response.status_code, 400, bad)
        self.assertEqual(CoreSettings.get_auth_settings()["public_base_url"], "")

    def test_public_base_url_normalised_and_clearable(self):
        self.client.patch(SETTINGS, {"public_base_url": "HTTPS://Mino.Example:8443/"}, format="json")
        self.assertEqual(
            CoreSettings.get_auth_settings()["public_base_url"], "https://mino.example:8443"
        )
        self.client.patch(SETTINGS, {"public_base_url": ""}, format="json")
        self.assertEqual(CoreSettings.get_auth_settings()["public_base_url"], "")


class IdentityEndpointTests(TestCase):
    def setUp(self):
        self.client, self.admin = admin_client()
        self.provider = make_provider()
        self.user = User.objects.create_user(username="linked", password="x")
        self.other = User.objects.create_user(username="other", password="x")
        self.identity = OIDCIdentity.objects.create(
            user=self.user,
            provider=self.provider,
            issuer=self.provider.issuer,
            subject="sub-A-SENTINEL",
            mapping_claim_path="roles",
            mapping_claim_values=["admins"],
        )
        OIDCIdentity.objects.create(
            user=self.other, provider=self.provider, issuer=self.provider.issuer, subject="sub-B"
        )

    def test_list_and_filter_by_user(self):
        from .oidc_support import IDENTITIES

        self.assertEqual(len(self.client.get(IDENTITIES).json()), 2)
        filtered = self.client.get(f"{IDENTITIES}?user={self.user.pk}").json()
        self.assertEqual([i["id"] for i in filtered], [self.identity.pk])
        self.assertEqual(self.client.get(f"{IDENTITIES}?user=abc").status_code, 400)

    def test_claim_values_only_in_the_detail(self):
        from .oidc_support import IDENTITIES

        listed = self.client.get(IDENTITIES).json()[0]
        self.assertNotIn("mapping_claim_values", listed)
        detail = self.client.get(f"{IDENTITIES}{self.identity.pk}/").json()
        self.assertEqual(detail["mapping_claim_values"], ["admins"])

    def test_unlink_deletes_only_the_identity(self):
        from .oidc_support import IDENTITIES

        response = self.client.delete(f"{IDENTITIES}{self.identity.pk}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(OIDCIdentity.objects.filter(pk=self.identity.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_unlink_writes_an_event_with_the_admin_and_no_subject(self):
        from core.models import SystemEvent

        from .oidc_support import IDENTITIES

        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(f"{IDENTITIES}{self.identity.pk}/")
        event = SystemEvent.objects.get(event_type="login_success")
        self.assertEqual(event.details["method"], "oidc_unlink")
        self.assertEqual(event.details["admin"], "admin")
        self.assertEqual(event.details["user"], "linked")
        self.assertNotIn("sub-A-SENTINEL", str(event.details))

    def test_non_admin_refused(self):
        from .oidc_support import IDENTITIES

        standard, _ = standard_client()
        self.assertEqual(standard.get(IDENTITIES).status_code, 403)
        self.assertEqual(standard.delete(f"{IDENTITIES}{self.identity.pk}/").status_code, 403)
