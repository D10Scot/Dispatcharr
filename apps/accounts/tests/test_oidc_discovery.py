"""Discovery and JWKS fetching through the admin ``test`` action (SSO spec 3.5, T20, T20a, T20b).

An in-process ``http.server`` thread on 127.0.0.1 plays the OP, so the class runs with
``OIDC_ALLOW_HTTP`` on. Its JWKS entries carry no ``alg``, like Entra's. SSRF tests patch
``socket.getaddrinfo`` so no test resolves a real name.
"""

import socket
from unittest import mock

import itertools

import requests
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.oidc import discovery
from core.http_security import validate_outbound_http_url

from .oidc_support import (
    PROVIDERS,
    FakeOP,
    FakeResponse,
    admin_client,
    make_entra,
    make_provider,
    set_auth_settings,
)


def _addrinfo(*ips):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]


@override_settings(OIDC_ALLOW_HTTP=True)
class OPTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.op = FakeOP()
        cls.op.start()
        cls.addClassCleanup(cls.op.stop)

    def setUp(self):
        self.op.reset()
        self.client, _ = admin_client()
        set_auth_settings(public_base_url="https://mino.example.com")

    def run_test_action(self, provider):
        response = self.client.post(f"{PROVIDERS}{provider.pk}/test/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()


class TestActionTests(OPTestCase):
    def test_healthy_provider(self):
        self.op.serve_provider("/realms/x")
        provider = make_provider(issuer=self.op.base + "/realms/x")
        result = self.run_test_action(provider)
        self.assertEqual(result["problems"], [])
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["redirect_uri"], "https://mino.example.com/api/accounts/oidc/p1/callback/"
        )

    def test_test_action_writes_nothing(self):
        self.op.serve_provider("/realms/x")
        provider = make_provider(issuer=self.op.base + "/realms/x")
        before = type(provider).objects.filter(pk=provider.pk).values().get()
        from django.core.cache import cache

        keys = (discovery.discovery_cache_key(provider), discovery.jwks_cache_key(provider))
        cache.delete_many(keys)
        self.run_test_action(provider)
        for key in keys:
            self.assertIsNone(cache.get(key), f"the test action wrote {key} to the cache")
        self.assertEqual(type(provider).objects.filter(pk=provider.pk).values().get(), before)
        # The keys are the ones the login flow really fills (spec 3.5), so the assertion
        # above can fail.
        discovery.get_jwks(provider, discovery.get_discovery(provider))
        for key in keys:
            self.assertIsNotNone(cache.get(key), f"the flow's cache does not use {key}")
        cache.delete_many(keys)

    def test_unset_public_base_url_is_reported(self):
        set_auth_settings(public_base_url="")
        self.op.serve_provider("/realms/x")
        provider = make_provider(issuer=self.op.base + "/realms/x")
        result = self.run_test_action(provider)
        self.assertIn("public_base_url_unset", result["problems"])
        self.assertIsNone(result["redirect_uri"])

    def test_unreadable_credential_is_reported(self):
        self.op.serve_provider("/realms/x")
        provider = make_provider(issuer=self.op.base + "/realms/x")
        with override_settings(SECRET_KEY="a-different-secret-key-entirely"):
            result = self.run_test_action(provider)
        self.assertIn("credential_unreadable", result["problems"])

    def test_missing_document_and_bad_json(self):
        provider = make_provider(issuer=self.op.base + "/realms/x")
        self.assertEqual(self.run_test_action(provider)["problems"], ["discovery_http_error"])
        self.op.raw("/realms/x/.well-known/openid-configuration", b"not json")
        self.assertEqual(self.run_test_action(provider)["problems"], ["discovery_invalid"])
        self.op.raw("/realms/x/.well-known/openid-configuration", b"[1, 2]")
        self.assertEqual(self.run_test_action(provider)["problems"], ["discovery_invalid"])

    def test_missing_endpoint_in_the_document(self):
        self.op.json(
            "/realms/x/.well-known/openid-configuration",
            {"issuer": self.op.base + "/realms/x", "token_endpoint": self.op.base + "/t"},
        )
        provider = make_provider(issuer=self.op.base + "/realms/x")
        self.assertEqual(self.run_test_action(provider)["problems"], ["discovery_endpoint_missing"])

    def test_cleartext_endpoint_refused_without_the_switch(self):
        self.op.serve_provider("/realms/x")
        provider = make_provider(issuer=self.op.base + "/realms/x")
        with override_settings(OIDC_ALLOW_HTTP=False):
            result = self.run_test_action(provider)
        self.assertEqual(result["problems"], ["discovery_not_allowed"])
        self.assertEqual(self.op.requests, [], "a cleartext issuer was fetched")

    def test_bad_jwks(self):
        self.op.serve_provider("/realms/x", jwks_keys=[])
        provider = make_provider(issuer=self.op.base + "/realms/x")
        self.assertEqual(self.run_test_action(provider)["problems"], ["jwks_invalid"])
        self.op.raw("/realms/x/jwks", b"{}")
        self.assertEqual(self.run_test_action(provider)["problems"], ["jwks_invalid"])

    def test_malformed_endpoint_urls_answer_a_fixed_code_not_500(self):
        provider = make_provider(issuer=self.op.base + "/realms/x")
        path = "/realms/x/.well-known/openid-configuration"
        good = {
            "issuer": self.op.base + "/realms/x",
            "authorization_endpoint": self.op.base + "/auth",
            "token_endpoint": self.op.base + "/token",
            "jwks_uri": self.op.base + "/jwks",
        }
        for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            self.op.json(path, {**good, field: "https://[oops"})
            response = self.client.post(f"{PROVIDERS}{provider.pk}/test/")
            self.assertEqual(response.status_code, 200, f"{field}: {response.status_code}")
            self.assertEqual(response.json()["problems"], ["discovery_endpoint_invalid"], field)

    def test_parseable_endpoint_with_a_disallowed_scheme_stays_insecure(self):
        provider = make_provider(issuer=self.op.base + "/realms/x")
        path = "/realms/x/.well-known/openid-configuration"
        good = {
            "issuer": self.op.base + "/realms/x",
            "authorization_endpoint": self.op.base + "/auth",
            "token_endpoint": self.op.base + "/token",
            "jwks_uri": self.op.base + "/jwks",
        }
        for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            for bad in ("ftp://idp.example/x", "javascript:alert(1)"):
                self.op.json(path, {**good, field: bad})
                response = self.client.post(f"{PROVIDERS}{provider.pk}/test/")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json()["problems"], ["discovery_endpoint_insecure"], (field, bad)
                )

    def test_deeply_nested_documents_answer_a_fixed_code_not_500(self):
        self.op.serve_provider("/realms/x")
        provider = make_provider(issuer=self.op.base + "/realms/x")
        nested = b"[" * 200_000
        self.op.raw("/realms/x/jwks", nested)
        response = self.client.post(f"{PROVIDERS}{provider.pk}/test/")
        self.assertEqual(response.status_code, 200, "a nested JWKS body made the action fail")
        self.assertEqual(response.json()["problems"], ["jwks_invalid"])
        self.op.raw("/realms/x/.well-known/openid-configuration", nested)
        response = self.client.post(f"{PROVIDERS}{provider.pk}/test/")
        self.assertEqual(response.status_code, 200, "a nested discovery body made the action fail")
        self.assertEqual(response.json()["problems"], ["discovery_invalid"])

    def test_oversized_documents_refused(self):
        self.op.serve_provider("/realms/x")
        provider = make_provider(issuer=self.op.base + "/realms/x")
        self.op.raw("/realms/x/jwks", b" " * (discovery.MAX_BYTES + 1))
        self.assertEqual(self.run_test_action(provider)["problems"], ["jwks_too_large"])
        self.op.raw("/realms/x/.well-known/openid-configuration", b" " * (discovery.MAX_BYTES + 1))
        self.assertEqual(self.run_test_action(provider)["problems"], ["discovery_too_large"])

    def test_redirect_from_jwks_uri_refused(self):
        self.op.serve_provider("/realms/x")
        provider = make_provider(issuer=self.op.base + "/realms/x")
        self.op.raw("/realms/x/jwks", b"", status=302, headers={"Location": "/elsewhere"})
        result = self.run_test_action(provider)
        self.assertEqual(result["problems"], ["jwks_redirect"])
        self.assertNotIn("/elsewhere", self.op.requests, "the redirect was followed")

    def test_redirect_from_discovery_refused(self):
        self.op.raw(
            "/realms/x/.well-known/openid-configuration",
            b"",
            status=302,
            headers={"Location": "/elsewhere"},
        )
        provider = make_provider(issuer=self.op.base + "/realms/x")
        self.assertEqual(self.run_test_action(provider)["problems"], ["discovery_redirect"])

    def test_responses_never_carry_a_resolved_address_or_exception_text(self):
        provider = make_provider(issuer="https://idp.example/realms/x")
        with mock.patch("core.http_security.socket.getaddrinfo", return_value=_addrinfo("10.0.0.5")):
            response = self.client.post(f"{PROVIDERS}{provider.pk}/test/")
        self.assertEqual(response.status_code, 200, "the action failed instead of answering")
        self.assertEqual(response.json()["problems"], ["discovery_not_allowed"])
        self.assertNotIn("10.0.0.5", response.content.decode())


class DiscoveryUrlTests(OPTestCase):
    def test_trailing_slash_issuer_fetches_single_slash_path(self):
        self.op.serve_provider("/realms/x/")
        provider = make_provider(issuer=self.op.base + "/realms/x/")
        self.run_test_action(provider)
        well_known = [p for p in self.op.requests if "well-known" in p]
        self.assertEqual(
            well_known,
            ["/realms/x/.well-known/openid-configuration"],
            f"discovery requests were {well_known}",
        )
        self.assertFalse([p for p in self.op.requests if "//.well-known" in p])
        # The document answers with the slash, as the stored issuer has.
        self.op.json(
            "/realms/x/.well-known/openid-configuration",
            {
                "issuer": self.op.base + "/realms/x/",
                "authorization_endpoint": self.op.base + "/realms/x/auth",
                "token_endpoint": self.op.base + "/realms/x/token",
                "jwks_uri": self.op.base + "/realms/x/jwks",
            },
        )
        self.assertEqual(self.run_test_action(provider)["problems"], [])

    def test_trailing_slash_issuer_compared_exactly(self):
        provider = make_provider(issuer=self.op.base + "/realms/x/")
        self.op.serve_provider("/realms/x/", issuer=self.op.base + "/realms/x")  # no slash
        self.assertEqual(
            self.run_test_action(provider)["problems"], ["discovery_issuer_mismatch"]
        )
        self.op.serve_provider("/realms/x/", issuer=self.op.base + "/realms/x/")
        self.assertEqual(self.run_test_action(provider)["problems"], [])

    def test_discovery_url_function(self):
        self.assertEqual(
            discovery.discovery_url("https://i.example/realms/x/"),
            "https://i.example/realms/x/.well-known/openid-configuration",
        )
        self.assertEqual(
            discovery.discovery_url("https://i.example"),
            "https://i.example/.well-known/openid-configuration",
        )
        # Only ONE terminating slash is stripped.
        self.assertEqual(
            discovery.discovery_url("https://i.example//"),
            "https://i.example//.well-known/openid-configuration",
        )


class OutboundPolicyTests(TestCase):
    """T20a: the repository's SSRF check governs every fetch, including discovered ones."""

    def setUp(self):
        self.client, _ = admin_client()
        set_auth_settings(public_base_url="https://mino.example.com")
        self.requested = []

    def _fake_get(self, documents):
        def get(url, **kwargs):
            self.requested.append(url)
            body = documents.get(url)
            if body is None:
                return FakeResponse(b"{}", status_code=404)
            return FakeResponse(body)

        return get

    def _run(self, provider, resolver, documents):
        with mock.patch("core.http_security.socket.getaddrinfo", side_effect=resolver), \
                mock.patch("requests.get", side_effect=self._fake_get(documents)):
            response = self.client.post(f"{PROVIDERS}{provider.pk}/test/")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_private_issuer_refused_by_default(self):
        provider = make_provider(issuer="https://idp.internal/realms/x")
        result = self._run(provider, lambda host, *a, **k: _addrinfo("10.0.0.5"), {})
        self.assertEqual(self.requested, [], "a request was sent to a private address")
        self.assertEqual(result["problems"], ["discovery_not_allowed"])

    def test_private_issuer_allowed_with_flag(self):
        provider = make_provider(issuer="https://idp.internal/realms/x", allow_private_network=True)
        docs = {
            "https://idp.internal/realms/x/.well-known/openid-configuration": {
                "issuer": "https://idp.internal/realms/x",
                "authorization_endpoint": "https://idp.internal/auth",
                "token_endpoint": "https://idp.internal/token",
                "jwks_uri": "https://idp.internal/jwks",
            },
            "https://idp.internal/jwks": {"keys": [{"kty": "RSA", "kid": "k"}]},
        }
        result = self._run(provider, lambda host, *a, **k: _addrinfo("10.0.0.5"), docs)
        self.assertEqual(result["problems"], [])
        self.assertEqual(len(self.requested), 2)

    def test_metadata_address_refused_even_with_flag(self):
        provider = make_provider(issuer="https://idp.internal/realms/x", allow_private_network=True)
        result = self._run(provider, lambda host, *a, **k: _addrinfo("169.254.169.254"), {})
        self.assertEqual(result["problems"], ["discovery_not_allowed"])
        self.assertEqual(self.requested, [])

    def test_discovered_jwks_uri_checked(self):
        def resolver(host, *args, **kwargs):
            return _addrinfo("10.0.0.5" if host == "10.0.0.5" else "93.184.216.34")

        provider = make_provider(issuer="https://idp.example/realms/x")
        docs = {
            "https://idp.example/realms/x/.well-known/openid-configuration": {
                "issuer": "https://idp.example/realms/x",
                "authorization_endpoint": "https://idp.example/auth",
                "token_endpoint": "https://idp.example/token",
                "jwks_uri": "https://10.0.0.5/jwks",
            }
        }
        result = self._run(provider, resolver, docs)
        self.assertFalse(
            [u for u in self.requested if "10.0.0.5" in u],
            "a request to the private address was attempted",
        )
        self.assertEqual(result["problems"], ["jwks_uri_not_allowed"])

    def test_discovered_token_endpoint_is_checked_too(self):
        def resolver(host, *args, **kwargs):
            return _addrinfo("10.0.0.5" if host == "10.0.0.5" else "93.184.216.34")

        provider = make_provider(issuer="https://idp.example/realms/x")
        docs = {
            "https://idp.example/realms/x/.well-known/openid-configuration": {
                "issuer": "https://idp.example/realms/x",
                "authorization_endpoint": "https://idp.example/auth",
                "token_endpoint": "https://10.0.0.5/token",
                "jwks_uri": "https://idp.example/jwks",
            },
            "https://idp.example/jwks": {"keys": [{"kty": "RSA", "kid": "k"}]},
        }
        result = self._run(provider, resolver, docs)
        self.assertEqual(result["problems"], ["token_endpoint_not_allowed"])

    def test_loopback_needs_env_switch(self):
        op = FakeOP()
        op.start()
        self.addCleanup(op.stop)
        op.serve_provider("/realms/x")
        provider = make_provider(issuer=op.base + "/realms/x", allow_private_network=True)
        # Even the per-provider private flag does not admit loopback or cleartext http.
        with override_settings(OIDC_ALLOW_HTTP=False):
            response = self.client.post(f"{PROVIDERS}{provider.pk}/test/")
        self.assertEqual(response.json()["problems"], ["discovery_not_allowed"])
        self.assertEqual(op.requests, [])
        with override_settings(OIDC_ALLOW_HTTP=True):
            ok = self.client.post(f"{PROVIDERS}{provider.pk}/test/")
        self.assertEqual(ok.json()["problems"], [])

    def test_discovered_token_endpoint_checked_at_callback(self):
        from .oidc_flow_support import FlowOP, query_of

        op = FlowOP()
        op.start()
        self.addCleanup(op.stop)
        op.discovery_extra = {"token_endpoint": "http://10.0.0.5/token"}
        provider = make_provider(
            slug="p1", enabled=True, issuer=op.issuer, client_id="mino-client",
            client_auth_method="client_secret_post",
        )
        posted = []

        def record_post(url, **kwargs):
            posted.append(url)
            raise requests.ConnectionError("the test refuses every POST")

        client = APIClient()
        with override_settings(OIDC_ALLOW_HTTP=True), mock.patch("requests.post", side_effect=record_post):
            start = client.get("/api/accounts/oidc/p1/start/")
            self.assertEqual(start.status_code, 302)
            params = op.authorize(start["Location"], {"roles": ["admins"]})
            response = client.get("/api/accounts/oidc/p1/callback/", params)
        self.assertEqual(query_of(response["Location"]).get("sso_error"), "token_exchange_failed")
        self.assertEqual(posted, [], "a token request was sent to a private address")
        self.assertEqual(op.token_requests, [])

    def test_loopback_needs_env_switch_for_the_flow(self):
        from .oidc_flow_support import FlowOP, query_of

        op = FlowOP()
        op.start()
        self.addCleanup(op.stop)
        make_provider(slug="p1", enabled=True, issuer=op.issuer, allow_private_network=True)
        with override_settings(OIDC_ALLOW_HTTP=False):
            response = APIClient().get("/api/accounts/oidc/p1/start/")
        self.assertEqual(query_of(response["Location"]).get("sso_error"), "provider_unavailable")
        self.assertEqual(op.gets, [])

    def test_entra_provider_cannot_reach_a_private_address(self):
        provider = make_entra()
        self.assertFalse(provider.allow_private_network)
        result = self._run(provider, lambda host, *a, **k: _addrinfo("10.0.0.5"), {})
        self.assertEqual(result["problems"], ["discovery_not_allowed"])

    def test_policy_helper_is_the_shared_one(self):
        with mock.patch("core.http_security.socket.getaddrinfo", return_value=_addrinfo("10.0.0.5")):
            with self.assertRaises(ValueError):
                validate_outbound_http_url("https://x.example/")


class _EndlessRaw:
    """A body that never ends: one KiB per receive."""

    def __init__(self):
        self.reads = 0

    def read1(self, amt=8192, decode_content=True):
        self.reads += 1
        return b" " * 1024


class _EndlessResponse:
    status_code = 200
    headers = {}

    def __init__(self):
        self.raw = _EndlessRaw()

    def close(self):
        pass


class DeadlineTests(TestCase):
    """The limited reader stops at a total monotonic deadline, checked between receives,
    so a server that drips bytes inside the per-read timeout cannot hold a worker."""

    def test_dripping_body_stops_at_the_deadline(self):
        clock = itertools.count(start=1000.0, step=1.0)  # one second per reading
        response = _EndlessResponse()
        with mock.patch.object(discovery, "_now", side_effect=lambda: next(clock)):
            deadline = discovery.deadline_from_now()
            with self.assertRaises(discovery.DiscoveryError) as caught:
                discovery.read_limited(response, deadline, too_large="too_large", failed="unreachable")
        self.assertEqual(
            caught.exception.code, "unreachable",
            f"the endless body ended as {caught.exception.code!r} after {response.raw.reads} reads, "
            "not at the deadline",
        )
        self.assertLessEqual(response.raw.reads, discovery.TOTAL_DEADLINE + 1)

    def test_dripping_discovery_reported_unreachable(self):
        client, _ = admin_client()
        set_auth_settings(public_base_url="https://mino.example.com")
        provider = make_provider(issuer="https://idp.example/realms/x")
        clock = itertools.count(start=1000.0, step=1.0)
        with mock.patch("core.http_security.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")), \
                mock.patch("requests.get", return_value=_EndlessResponse()), \
                mock.patch.object(discovery, "_now", side_effect=lambda: next(clock)):
            result = client.post(f"{PROVIDERS}{provider.pk}/test/").json()
        self.assertEqual(result["problems"], ["discovery_unreachable"])
