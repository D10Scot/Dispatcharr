"""The OIDC flow end to end against an in-process fake OP (SSO spec PR S2; section 8 T1-T34).

Every flow here runs through the Django test client: ``start`` (or ``link/start``), the fake
OP's approval, ``callback`` and ``exchange``. The OP requires a valid PKCE verifier and checks
the client credential, its JWKS entries carry no ``alg`` and its discovery document does not
advertise PKCE or RFC 9207 unless a test turns the latter on.
"""

import base64
import datetime
import hashlib
import json
import logging
import threading
import time
import warnings
from unittest import mock
from urllib.parse import parse_qs, unquote_plus, urlsplit

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
import requests
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.db import OperationalError, connection
from django.db.models import F
from django.test import RequestFactory, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import aware_utcnow

from apps.accounts.models import OIDCIdentity, OIDCProvider, User
from apps.accounts.oidc import client_auth, discovery, flow, provisioning
from apps.accounts.oidc import secrets as oidc_secrets
from apps.proxy.authorize import _drf_user
from core.models import NETWORK_ACCESS_KEY, CoreSettings, SystemEvent

from .oidc_flow_support import (
    BASE,
    CLIENT_ID,
    EXCHANGE,
    ME,
    FlowTestCase,
    FlowTransactionTestCase,
    WAIT_TIMEOUT,
    Worker,
    b64url,
    capture_all_logs,
    decode_unverified,
    fragment_code,
    join_all,
    keys,
    make_admin,
    public_jwk,
    query_of,
    sso_error,
)
from .oidc_support import (
    PROVIDERS,
    SECRET_SENTINEL,
    TENANT,
    admin_client,
    make_entra,
)
from .test_oidc_providers import entra_body

FIVE_CLAIMS = ("auth_method", "oidc_provider", "oidc_provider_version", "oidc_level", "oidc_identity")


def bump_mappings(provider, mappings=None, **columns):
    """An admin edit: column-restricted, bumping ``version`` as the providers API does."""
    changes = dict(columns)
    if mappings is not None:
        changes["mappings"] = mappings
    OIDCProvider.update_columns(provider.pk, changes)
    provider.refresh_from_db()
    return provider


def binding_cookies(response):
    return {
        name: morsel
        for name, morsel in response.cookies.items()
        if name.startswith((flow.HTTPS_COOKIE_PREFIX, flow.HTTP_COOKIE_PREFIX))
    }


def redis_client():
    from core.utils import RedisClient

    return RedisClient.get_client(max_retries=1)


# ---- the happy path ------------------------------------------------------------------------


class HappyPathTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_login_end_to_end(self):
        client = APIClient()
        body = self.login(client, self.provider, {"roles": ["staff"], "preferred_username": "alice"})
        self.assertEqual(set(body), {"access", "refresh", "next", "intent"})
        self.assertEqual(body["intent"], "login")
        self.assertEqual(body["next"], "/")
        user = User.objects.get(username="alice")
        self.assertEqual(user.user_level, User.UserLevel.STANDARD)
        self.assertFalse(user.has_usable_password())
        identity = OIDCIdentity.objects.get(user=user)
        self.assertEqual(identity.subject, "subject-1")
        self.assertEqual(identity.mapping_claim_path, "roles")
        self.assertEqual(identity.mapping_claim_values, ["staff"])

        me = APIClient(HTTP_AUTHORIZATION=f"Bearer {body['access']}").get(ME)
        self.assertEqual(me.status_code, 200, me.content)
        self.assertEqual(me.json()["username"], "alice")

        # D2: streaming needs nothing new; the relay's authorizer accepts the same token.
        request = RequestFactory().get("/proxy/ts/stream/x", HTTP_AUTHORIZATION=f"Bearer {body['access']}")
        self.assertEqual(_drf_user(request), user)

    def test_token_claims(self):
        body = self.login(APIClient(), self.provider, {"roles": ["admins"]})
        identity = OIDCIdentity.objects.get()
        for token in (body["access"], body["refresh"]):
            claims = decode_unverified(token)
            self.assertEqual(claims["auth_method"], "oidc")
            self.assertEqual(claims["oidc_provider"], self.provider.pk)
            self.assertEqual(claims["oidc_provider_version"], self.provider.version)
            self.assertEqual(claims["oidc_level"], 10)
            self.assertEqual(claims["oidc_identity"], identity.pk)
            self.assertNotIn("oidc_redirect", claims)

    def test_five_claims_survive_refresh(self):
        body = self.login(APIClient(), self.provider, {"roles": ["admins"]})
        refreshed = self.refresh(body["refresh"])
        self.assertEqual(refreshed.status_code, 200, refreshed.content)
        before = decode_unverified(body["access"])
        after = decode_unverified(refreshed.json()["access"])
        for name in FIVE_CLAIMS:
            self.assertEqual(after.get(name), before[name], name)
        self.assertNotIn("oidc_redirect", after)

    def test_start_parameters(self):
        authorize_url = self.start(APIClient(), self.provider)
        self.assertTrue(authorize_url.startswith(self.op.issuer + "/authorize?"))
        query = query_of(authorize_url)
        self.assertEqual(query["response_type"], "code")
        self.assertEqual(query["client_id"], CLIENT_ID)
        self.assertEqual(query["scope"], self.provider.scopes)
        self.assertEqual(query["code_challenge_method"], "S256")
        self.assertNotIn("prompt", query)
        self.assertEqual(query["redirect_uri"], f"{BASE}/api/accounts/oidc/p1/callback/")
        self.assertEqual(len(query["state"]), 43)
        self.assertEqual(len(query["nonce"]), 43)
        OIDCProvider.objects.filter(pk=self.provider.pk).update(prompt_select_account=True)
        self.assertEqual(query_of(self.start(APIClient(), self.provider))["prompt"], "select_account")

    def test_callback_location_is_fragment_only(self):
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"]})
        location = response["Location"]
        self.assertTrue(location.startswith(f"{BASE}/login/sso#code="), location)
        self.assertNotIn("?code=", location)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    def test_exchange_shape_and_headers(self):
        client = APIClient()
        response = self.sign_in(client, self.provider, {"roles": ["staff"]})
        exchanged = self.exchange(client, response)
        self.assertEqual(exchanged.status_code, 200)
        self.assertEqual(set(exchanged.json()), {"access", "refresh", "next", "intent"})
        self.assertEqual(exchanged["Cache-Control"], "no-store")
        self.assertEqual(exchanged["Pragma"], "no-cache")
        self.assertEqual(exchanged["Referrer-Policy"], "no-referrer")
        deleted = binding_cookies(exchanged)
        self.assertEqual(len(deleted), 1)
        self.assertEqual(next(iter(deleted.values()))["max-age"], 0)

    def test_second_exchange_refused(self):
        client = APIClient()
        response = self.sign_in(client, self.provider, {"roles": ["staff"]})
        self.assertEqual(self.exchange(client, response).status_code, 200)
        again = self.exchange(client, response)
        self.assertEqual(again.status_code, 400)
        self.assertEqual(again.json(), {"code": "handoff_invalid"})

    def test_exchange_after_ttl_refused(self):
        client = APIClient()
        response = self.sign_in(client, self.provider, {"roles": ["staff"]})
        key = flow.HANDOFF_KEY.format(fragment_code(response["Location"]))
        ttl = redis_client().ttl(key)
        self.assertTrue(0 < ttl <= 60, ttl)
        redis_client().delete(key)  # stands for the 60 s expiry
        self.assertEqual(self.exchange(client, response).status_code, 400)

    def test_next_round_trips(self):
        client = APIClient()
        authorize_url = self.start(client, self.provider, next_path="/channels?x=1")
        response = self.callback(client, self.provider, self.op.authorize(authorize_url, {"roles": ["staff"]}))
        self.assertEqual(self.exchange(client, response).json()["next"], "/channels?x=1")

    def test_public_providers_endpoint(self):
        response = APIClient().get("/api/accounts/oidc/providers/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["providers"], [{"slug": "p1", "display_name": "Provider One"}])
        self.assertIs(body["password_login_enabled"], True)
        text = response.content.decode()
        for absent in (self.op.issuer, CLIENT_ID, "client_secret"):
            self.assertNotIn(absent, text)

    def test_disabled_provider_404(self):
        OIDCProvider.update_columns(self.provider.pk, {"enabled": False})
        response = APIClient().get("/api/accounts/oidc/p1/start/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"code": "not_found"})

    def test_no_public_base_url_409(self):
        from .oidc_support import set_auth_settings

        set_auth_settings(public_base_url="")
        response = APIClient().get("/api/accounts/oidc/p1/start/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"code": "sso_not_configured"})


# ---- T1, T2: next and Host ----------------------------------------------------------------


class NextTests(FlowTestCase):
    def test_unsafe_next_becomes_root(self):
        for value in ("//evil", "/\\evil", "https://evil", "%2F%2Fevil", "/ok\x01", "evil", "/%5Cevil"):
            with self.subTest(next=value):
                self.assertEqual(flow.safe_next(value), "/")
        self.assertEqual(flow.safe_next("/channels?a=1#x"), "/channels?a=1#x")
        self.assertEqual(flow.safe_next("/" + "a" * 600), "/")

    def test_unsafe_next_stored_as_root(self):
        provider = self.make_flow_provider()
        client = APIClient()
        authorize_url = self.start(client, provider, next_path="//evil.example/x")
        response = self.callback(client, provider, self.op.authorize(authorize_url, {"roles": ["staff"]}))
        self.assertEqual(self.exchange(client, response).json()["next"], "/")

    def test_host_header_never_used(self):
        provider = self.make_flow_provider()
        client = APIClient(HTTP_HOST="evil.example")
        authorize_url = self.start(client, provider)
        self.assertEqual(query_of(authorize_url)["redirect_uri"], f"{BASE}/api/accounts/oidc/p1/callback/")
        response = self.callback(client, provider, self.op.authorize(authorize_url, {"roles": ["staff"]}))
        self.assertTrue(response["Location"].startswith(BASE + "/"), response["Location"])
        token_form = self.op.token_requests[-1]["form"]
        self.assertEqual(token_form["redirect_uri"], f"{BASE}/api/accounts/oidc/p1/callback/")


# ---- T3, T3b, T3a: the browser binding ------------------------------------------------------


class BindingTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_callback_without_binding_cookie_refused(self):
        client = APIClient()
        authorize_url = self.start(client, self.provider)
        client.cookies.clear()
        response = self.callback(client, self.provider, self.op.authorize(authorize_url, {"roles": ["staff"]}))
        self.assertEqual(
            sso_error(response), "binding_invalid", f"expected binding_invalid, got {response['Location']}"
        )
        self.assertFalse(OIDCIdentity.objects.exists())

    def test_callback_with_wrong_binding_cookie_refused(self):
        client = APIClient()
        authorize_url = self.start(client, self.provider)
        (name,) = [n for n in client.cookies if n.startswith(flow.HTTPS_COOKIE_PREFIX)]
        client.cookies[name] = "not-the-binding"
        response = self.callback(client, self.provider, self.op.authorize(authorize_url, {"roles": ["staff"]}))
        self.assertEqual(sso_error(response), "binding_invalid")

    def test_exchange_from_other_browser_refused(self):
        victim = APIClient()
        response = self.sign_in(victim, self.provider, {"roles": ["staff"]})
        attacker = APIClient()
        stolen = attacker.post(EXCHANGE, {"code": fragment_code(response["Location"])}, format="json")
        self.assertEqual(stolen.status_code, 400)
        self.assertEqual(stolen.json(), {"code": "handoff_invalid"})
        # The handoff was consumed by the failed attempt: a stolen code is worth one try.
        self.assertEqual(self.exchange(victim, response).status_code, 400)


class BindingCookieTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_https_cookie_is_host_prefixed(self):
        response = APIClient().get("/api/accounts/oidc/p1/start/")
        cookies = binding_cookies(response)
        self.assertEqual(len(cookies), 1)
        name, morsel = next(iter(cookies.items()))
        self.assertTrue(name.startswith("__Host-mino_oidc_tx_"), f"cookie name {name!r} is not __Host- prefixed")
        self.assertEqual(len(name), len("__Host-mino_oidc_tx_") + 16)
        self.assertTrue(morsel["secure"])
        self.assertTrue(morsel["httponly"])
        self.assertEqual(morsel["samesite"], "Lax")
        self.assertEqual(morsel["path"], "/")
        self.assertEqual(morsel["domain"], "")
        self.assertEqual(morsel["max-age"], 600)

    def test_http_fallback_cookie_is_unprefixed(self):
        from .oidc_support import set_auth_settings

        set_auth_settings(public_base_url="http://localhost:9191")
        response = APIClient().get("/api/accounts/oidc/p1/start/")
        cookies = binding_cookies(response)
        name, morsel = next(iter(cookies.items()))
        self.assertTrue(name.startswith("mino_oidc_tx_"), name)
        self.assertFalse(morsel["secure"])

    def test_two_transactions_do_not_clobber(self):
        client = APIClient()
        first = self.start(client, self.provider)
        second = self.start(client, self.provider)
        r1 = self.callback(client, self.provider, self.op.authorize(first, {"roles": ["staff"]}))
        self.assertIsNone(sso_error(r1), f"first transaction refused: {r1['Location']}")
        self.assertEqual(self.exchange(client, r1).status_code, 200)
        r2 = self.callback(client, self.provider, self.op.authorize(second, {"roles": ["staff"]}))
        self.assertIsNone(sso_error(r2), f"second transaction refused: {r2['Location']}")
        self.assertEqual(self.exchange(client, r2).status_code, 200)

    def test_cookie_for_other_transaction_refused(self):
        a_client, b_client = APIClient(), APIClient()
        a_url = self.start(a_client, self.provider)
        self.start(b_client, self.provider)
        response = self.callback(b_client, self.provider, self.op.authorize(a_url, {"roles": ["staff"]}))
        self.assertEqual(sso_error(response), "binding_invalid")

    def test_refusal_and_exchange_delete_the_cookie(self):
        client = APIClient()
        url = self.start(client, self.provider)
        name = flow.binding_cookie_name(flow.tx_id(query_of(url)["state"]), BASE)
        client.cookies[name] = "wrong"
        refused = self.callback(client, self.provider, self.op.authorize(url, {"roles": ["staff"]}))
        self.assertEqual(sso_error(refused), "binding_invalid")
        self.assertEqual(refused.cookies[name]["max-age"], 0)

        client = APIClient()
        url = self.start(client, self.provider)
        name = flow.binding_cookie_name(flow.tx_id(query_of(url)["state"]), BASE)
        response = self.callback(client, self.provider, self.op.authorize(url, {"roles": ["staff"]}))
        exchanged = self.exchange(client, response)
        self.assertEqual(exchanged.status_code, 200)
        self.assertEqual(exchanged.cookies[name]["max-age"], 0)

    def test_fifth_stale_cookie_expires_all(self):
        client = APIClient()
        stale = [f"__Host-mino_oidc_tx_{i:016x}" for i in range(5)]
        for name in stale:
            client.cookies[name] = "x"
        response = client.get("/api/accounts/oidc/p1/start/")
        cookies = binding_cookies(response)
        for name in stale:
            self.assertEqual(cookies[name]["max-age"], 0, name)
        fresh = [n for n, m in cookies.items() if m["max-age"] == 600]
        self.assertEqual(len(fresh), 1)

    def test_four_stale_cookies_are_kept(self):
        client = APIClient()
        for i in range(4):
            client.cookies[f"__Host-mino_oidc_tx_{i:016x}"] = "x"
        cookies = binding_cookies(client.get("/api/accounts/oidc/p1/start/"))
        self.assertEqual(len(cookies), 1)


class LinkCsrfTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_forwarded_link_authorize_url_does_not_link(self):
        attacker_client, attacker = admin_client("attacker")
        attacker.user_level = User.UserLevel.STANDARD
        attacker.save(update_fields=["user_level"])
        authorize_url = self.link_start(attacker_client, self.provider)

        victim = APIClient()
        self.start(victim, self.provider)  # the victim holds a binding cookie of its own
        response = self.callback(victim, self.provider, self.op.authorize(authorize_url, {"roles": ["admins"]}))
        self.assertFalse(
            OIDCIdentity.objects.filter(user=attacker).exists(),
            "the victim's IdP identity was linked to the attacker's account",
        )
        self.assertEqual(sso_error(response), "binding_invalid")
        attacker.refresh_from_db()
        self.assertEqual(attacker.user_level, User.UserLevel.STANDARD)

    def test_get_start_never_links(self):
        client = APIClient()
        response = client.get("/api/accounts/oidc/p1/start/", {"intent": "link"})
        state = query_of(response["Location"])["state"]
        tx = json.loads(redis_client().get(flow.TX_KEY.format(state)))
        self.assertEqual(tx["intent"], "login")
        self.assertIsNone(tx["link_user_id"])

    def test_link_attaches_identity_to_caller(self):
        client, user = admin_client("local-admin")
        authorize_url = self.link_start(client, self.provider, next_path="/settings")
        response = self.callback(client, self.provider, self.op.authorize(authorize_url, {"roles": ["admins"]}))
        self.assertIsNone(sso_error(response), response["Location"])
        body = self.exchange(client, response).json()
        self.assertEqual(body["intent"], "link")
        self.assertEqual(body["next"], "/settings")
        self.assertEqual(OIDCIdentity.objects.get().user, user)
        self.assertEqual(User.objects.count(), 1)
        event = SystemEvent.objects.filter(event_type="login_success").latest("id")
        self.assertEqual(event.details["method"], "oidc_link")

    def test_link_start_requires_authentication(self):
        response = APIClient().post("/api/accounts/oidc/p1/link/start/", {}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_link_conflict_with_other_users_identity(self):
        self.login(APIClient(), self.provider, {"roles": ["staff"]})
        client, user = admin_client("other")
        authorize_url = self.link_start(client, self.provider)
        response = self.callback(client, self.provider, self.op.authorize(authorize_url, {"roles": ["admins"]}))
        self.assertEqual(sso_error(response), "link_conflict")
        self.assertFalse(OIDCIdentity.objects.filter(user=user).exists())


# ---- T4, T5, T8: state, PKCE, mix-up --------------------------------------------------------


class StateTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_state_replay_refused(self):
        client = APIClient()
        url = self.start(client, self.provider)
        params = self.op.authorize(url, {"roles": ["staff"]})
        self.assertIsNone(sso_error(self.callback(client, self.provider, params)))
        self.assertEqual(sso_error(self.callback(client, self.provider, params)), "state_invalid")

    def test_unknown_or_malformed_state_refused(self):
        for state in ("", "x", "A" * 43, "!" * 43):
            with self.subTest(state=state):
                response = self.callback(APIClient(), self.provider, {"state": state, "code": "c"})
                self.assertEqual(sso_error(response), "state_invalid")

    def test_idp_error_consumes_state_and_records_fixed_code(self):
        client = APIClient()
        url = self.start(client, self.provider)
        state = query_of(url)["state"]
        response = self.callback(
            client, self.provider, {"state": state, "error": "access_denied", "error_description": "free text"}
        )
        self.assertEqual(sso_error(response), "idp_error")
        self.assertIsNone(redis_client().get(flow.TX_KEY.format(state)))
        event = SystemEvent.objects.filter(event_type="login_failed").latest("id")
        self.assertEqual(event.details["idp_error"], "access_denied")
        self.assertNotIn("free text", json.dumps(event.details))

        response = self.callback(APIClient(), self.provider, {"error": "made_up"})
        event = SystemEvent.objects.filter(event_type="login_failed").latest("id")
        self.assertEqual(event.details["idp_error"], "other")


class PkceTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_verifier_matches_challenge(self):
        client = APIClient()
        url = self.start(client, self.provider)
        challenge = query_of(url)["code_challenge"]
        self.callback(client, self.provider, self.op.authorize(url, {"roles": ["staff"]}))
        form = self.op.token_requests[-1]["form"]
        self.assertEqual(b64url(hashlib.sha256(form["code_verifier"].encode()).digest()), challenge)
        self.assertEqual(form["grant_type"], "authorization_code")
        self.assertNotIn("code_verifier", url)

    def test_op_refuses_wrong_verifier(self):
        client = APIClient()
        url = self.start(client, self.provider)
        state = query_of(url)["state"]
        key = flow.TX_KEY.format(state)
        tx = json.loads(redis_client().get(key))
        tx["code_verifier"] = "wrong-verifier-" + "x" * 40
        redis_client().set(key, json.dumps(tx), ex=600)
        response = self.callback(client, self.provider, self.op.authorize(url, {"roles": ["staff"]}))
        self.assertEqual(sso_error(response), "token_exchange_failed")


class MixUpTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_transaction_from_other_provider_refused(self):
        other = self.make_flow_provider(slug="p2", display_name="Provider Two")
        client = APIClient()
        url = self.start(client, self.provider)
        response = self.callback(client, other, self.op.authorize(url, {"roles": ["staff"]}))
        self.assertEqual(
            sso_error(response), "provider_mismatch", f"expected provider_mismatch, got {response['Location']}"
        )

    def test_provider_version_changed_refused(self):
        client = APIClient()
        url = self.start(client, self.provider)
        OIDCProvider.objects.filter(pk=self.provider.pk).update(version=F("version") + 1)
        response = self.callback(client, self.provider, self.op.authorize(url, {"roles": ["staff"]}))
        self.assertEqual(sso_error(response), "provider_mismatch")

    def test_advertised_iss_param_required(self):
        self.op.discovery_extra = {"authorization_response_iss_parameter_supported": True}
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"]})
        self.assertEqual(sso_error(response), "issuer_mismatch")

    def test_advertised_iss_param_must_match(self):
        self.op.discovery_extra = {"authorization_response_iss_parameter_supported": True}
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"]}, iss_param="https://other")
        self.assertEqual(sso_error(response), "issuer_mismatch")
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"]}, iss_param=self.op.issuer)
        self.assertIsNone(sso_error(response), response["Location"])

    def test_unadvertised_iss_param_absent_succeeds(self):
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"]})
        self.assertIsNone(sso_error(response), response["Location"])

    def test_unadvertised_iss_param_present_must_match(self):
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"]}, iss_param="https://other")
        self.assertEqual(sso_error(response), "issuer_mismatch")


# ---- T6, T7, T9, T20b: the ID token --------------------------------------------------------


class ClaimTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def assertRefused(self, claims=None, **authz):
        response = self.sign_in(APIClient(), self.provider, claims, **authz)
        self.assertEqual(
            sso_error(response), "id_token_invalid", f"expected id_token_invalid, got {response['Location']}"
        )

    def test_wrong_nonce(self):
        self.assertRefused({"roles": ["staff"], "nonce": "not-the-nonce"})

    def test_missing_nonce(self):
        self.assertRefused({"roles": ["staff"]}, drop=("nonce",))

    def test_wrong_aud(self):
        self.assertRefused({"roles": ["staff"], "aud": "someone-else"})

    def test_multi_aud_without_azp(self):
        self.assertRefused({"roles": ["staff"], "aud": [CLIENT_ID, "other"]})

    def test_multi_aud_with_azp_accepted(self):
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"], "aud": [CLIENT_ID, "other"], "azp": CLIENT_ID})
        self.assertIsNone(sso_error(response), response["Location"])

    def test_expired(self):
        now = int(time.time())
        self.assertRefused({"roles": ["staff"], "iat": now - 600, "exp": now - 120})

    def test_iat_in_future(self):
        now = int(time.time())
        self.assertRefused({"roles": ["staff"], "iat": now + 300, "exp": now + 900})

    def test_wrong_iss(self):
        self.assertRefused({"roles": ["staff"], "iss": "https://other.example"})

    def test_missing_sub(self):
        self.assertRefused({"roles": ["staff"]}, drop=("sub",))

    def test_overlong_sub(self):
        self.assertRefused({"roles": ["staff"], "sub": "s" * 256})


class AzpTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def assertRefused(self, claims):
        response = self.sign_in(APIClient(), self.provider, claims)
        self.assertEqual(
            sso_error(response), "id_token_invalid", f"expected id_token_invalid, got {response['Location']}"
        )

    def test_scalar_aud_mismatched_azp_refused(self):
        self.assertRefused({"roles": ["staff"], "aud": CLIENT_ID, "azp": "other-client"})

    def test_single_element_aud_mismatched_azp_refused(self):
        self.assertRefused({"roles": ["staff"], "aud": [CLIENT_ID], "azp": "other-client"})

    def test_non_string_azp_refused(self):
        self.assertRefused({"roles": ["staff"], "azp": 5})


class SignatureTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def assertRefused(self, claims=None, **authz):
        response = self.sign_in(APIClient(), self.provider, claims or {"roles": ["staff"]}, **authz)
        self.assertEqual(
            sso_error(response), "id_token_invalid", f"expected id_token_invalid, got {response['Location']}"
        )

    def test_listed_kid_wrong_key_refused(self):
        self.assertRefused(key=keys()["other_rsa"], kid="rsa1")

    def test_alg_none_refused(self):
        client = APIClient()
        url = self.start(client, self.provider)
        query = query_of(url)
        now = int(time.time())
        payload = {
            "iss": self.op.issuer, "aud": CLIENT_ID, "sub": "s", "iat": now, "exp": now + 300,
            "nonce": query["nonce"], "roles": ["staff"],
        }
        token = jwt.encode(payload, None, algorithm="none", headers={"kid": "rsa1"})
        response = self.callback(client, self.provider, self.op.authorize(url, raw_token=token))
        self.assertEqual(sso_error(response), "id_token_invalid")

    def test_hs256_signed_with_client_secret_refused(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.assertRefused(key=SECRET_SENTINEL, alg="HS256", kid="rsa1")

    def test_jwks_oct_key_refused(self):
        secret = b"oct-key-material-" + b"k" * 32
        self.op.jwks_keys = self.op.jwks_keys + [{"kty": "oct", "kid": "oct1", "k": b64url(secret)}]
        self.assertRefused(key=secret, alg="HS256", kid="oct1")

    def test_wrong_family_key_refused(self):
        # The token names the EC key's kid but the provider is configured for RS256.
        self.assertRefused(key=keys()["ec"], alg="ES256", kid="ec1")

    def test_missing_kid_refused(self):
        self.assertRefused(kid=None)

    def test_unknown_kid_refetches_once(self):
        self.assertRefused(kid="unknown")
        jwks_gets = [p for p in self.op.gets if p.endswith("/jwks")]
        self.assertEqual(len(jwks_gets), 2, "one fetch plus one refetch")
        # Within the cooldown a second unknown kid does not refetch again.
        self.assertRefused(kid="unknown")
        self.assertEqual(len([p for p in self.op.gets if p.endswith("/jwks")]), 2)

    def test_rotated_key_found_by_refetch(self):
        self.login(APIClient(), self.provider, {"roles": ["staff"]})  # JWKS now cached
        self.op.jwks_keys = [public_jwk(keys()["other_rsa"], "rsa2")]
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"]}, key=keys()["other_rsa"], kid="rsa2")
        self.assertIsNone(sso_error(response), response["Location"])

    def test_ec_provider(self):
        provider = bump_mappings(self.provider, id_token_alg="ES256")
        response = self.sign_in(APIClient(), provider, {"roles": ["staff"]}, key=keys()["ec"], alg="ES256", kid="ec1")
        self.assertIsNone(sso_error(response), response["Location"])

    def test_jwk_alg_disagreeing_with_configuration_refused(self):
        jwk = public_jwk(keys()["rsa"], "rsa1")
        jwk["alg"] = "RS512"
        self.op.jwks_keys = [jwk]
        self.assertRefused()


class IssuerSlashTests(FlowTestCase):
    def test_id_token_iss_must_match_stored_issuer_exactly(self):
        issuer = self.op.issuer + "/"
        self.op.issuer_override = issuer
        provider = self.make_flow_provider(issuer=issuer)
        response = self.sign_in(APIClient(), provider, {"roles": ["staff"]})
        self.assertEqual(sso_error(response), "id_token_invalid")
        response = self.sign_in(APIClient(), provider, {"roles": ["staff"], "iss": issuer})
        self.assertIsNone(sso_error(response), response["Location"])


class EntraRuntimeTests(FlowTestCase):
    """Entra's issuer is login.microsoftonline.com, so its discovery document is supplied
    by the fake OP through the cached-discovery seam; JWKS and the token request still go
    to the fake OP over loopback."""

    def setUp(self):
        super().setUp()
        self.provider = make_entra(enabled=True, client_id=CLIENT_ID, mappings=[{"value": "admins", "user_level": 10}, {"value": "staff", "user_level": 1}])
        doc = self.op.discovery_document()
        doc["issuer"] = self.provider.issuer
        patcher = mock.patch.object(discovery, "get_discovery", return_value=doc)
        patcher.start()
        self.addCleanup(patcher.stop)

    def entra_claims(self, **overrides):
        claims = {"iss": self.provider.issuer, "tid": TENANT, "oid": "oid-1", "roles": ["staff"]}
        claims.update(overrides)
        return claims

    def test_matching_tenant_accepted(self):
        response = self.sign_in(APIClient(), self.provider, self.entra_claims())
        self.assertIsNone(sso_error(response), response["Location"])
        identity = OIDCIdentity.objects.get()
        self.assertEqual(identity.extra, {"tid": TENANT, "oid": "oid-1"})

    def test_configured_iss_other_tid_refused(self):
        other = "99999999-8888-7777-6666-555555555555"
        response = self.sign_in(APIClient(), self.provider, self.entra_claims(tid=other))
        self.assertEqual(
            sso_error(response), "id_token_invalid", f"expected id_token_invalid, got {response['Location']}"
        )

    def test_other_tenant_iss_with_configured_tid_refused(self):
        other_iss = "https://login.microsoftonline.com/99999999-8888-7777-6666-555555555555/v2.0"
        response = self.sign_in(APIClient(), self.provider, self.entra_claims(iss=other_iss))
        self.assertEqual(sso_error(response), "id_token_invalid")

    def test_missing_tid_refused(self):
        claims = self.entra_claims()
        del claims["tid"]
        response = self.sign_in(APIClient(), self.provider, claims)
        self.assertEqual(sso_error(response), "id_token_invalid")

    def test_groups_overage_refused(self):
        provider = bump_mappings(self.provider, claim_path="groups")
        response = self.sign_in(
            APIClient(), provider, self.entra_claims(_claim_names={"groups": "src1"}, roles=None)
        )
        self.assertEqual(sso_error(response), "groups_overage")
        self.assertFalse(User.objects.exists())


# ---- T10, T11, T22: identity and level ------------------------------------------------------


class MappingTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_level_recomputed_on_each_login(self):
        make_admin("other-admin")
        self.login(APIClient(), self.provider, {"roles": ["admins"], "preferred_username": "u"})
        self.assertEqual(User.objects.get(username="u").user_level, 10)
        self.login(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": "u"})
        self.assertEqual(User.objects.get(username="u").user_level, 1)
        response = self.sign_in(APIClient(), self.provider, {"roles": ["nothing"], "preferred_username": "u"})
        self.assertEqual(sso_error(response), "no_mapping")
        self.assertEqual(User.objects.get(username="u").user_level, 1)

    def test_highest_mapping_wins(self):
        self.login(APIClient(), self.provider, {"roles": ["viewers", "staff"], "preferred_username": "u"})
        self.assertEqual(User.objects.get(username="u").user_level, 1)

    def test_scalar_claim_value(self):
        self.login(APIClient(), self.provider, {"roles": "staff", "preferred_username": "u"})
        self.assertEqual(User.objects.get(username="u").user_level, 1)

    def test_nested_claim_path(self):
        provider = bump_mappings(self.provider, claim_path="realm_access.roles")
        self.login(APIClient(), provider, {"realm_access": {"roles": ["staff"]}, "preferred_username": "u"})
        self.assertEqual(User.objects.get(username="u").user_level, 1)

    def test_jit_user_fields(self):
        self.login(
            APIClient(), self.provider,
            {"roles": ["staff"], "preferred_username": "jdoe", "email": "jdoe@example.com",
             "given_name": "J", "family_name": "Doe"},
        )
        user = User.objects.get(username="jdoe")
        self.assertEqual((user.email, user.first_name, user.last_name), ("jdoe@example.com", "J", "Doe"))
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertEqual(user.stream_limit, 0)


class DeactivationTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_inactive_linked_user_refused(self):
        self.login(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": "u"})
        User.objects.filter(username="u").update(is_active=False)
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": "u"})
        self.assertEqual(sso_error(response), "inactive")
        self.assertFalse(User.objects.get(username="u").is_active)

    def test_link_target_deactivated_before_callback(self):
        client, user = admin_client("local")
        url = self.link_start(client, self.provider)
        User.objects.filter(pk=user.pk).update(is_active=False)
        response = self.callback(client, self.provider, self.op.authorize(url, {"roles": ["admins"]}))
        self.assertEqual(sso_error(response), "inactive")
        self.assertFalse(OIDCIdentity.objects.exists())

    def test_inactive_user_access_and_refresh_refused(self):
        body = self.login(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": "u"})
        User.objects.filter(username="u").update(is_active=False)
        self.assertEqual(APIClient(HTTP_AUTHORIZATION=f"Bearer {body['access']}").get(ME).status_code, 401)
        self.assertEqual(self.refresh(body["refresh"]).status_code, 401)
        # Even with a changed provider version (the recompute path).
        bump_mappings(self.provider, [{"value": "staff", "user_level": 0}])
        self.assertEqual(self.refresh(body["refresh"]).status_code, 401)


class MeTests(FlowTestCase):
    def test_sso_user_cannot_set_own_password(self):
        provider = self.make_flow_provider()
        body = self.login(APIClient(), provider, {"roles": ["staff"], "preferred_username": "u"})
        client = APIClient(HTTP_AUTHORIZATION=f"Bearer {body['access']}")
        response = client.patch(ME, {"password": "new-password-123"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"code": "password_not_allowed"})
        self.assertFalse(User.objects.get(username="u").has_usable_password())
        # Other fields still update.
        self.assertEqual(client.patch(ME, {"first_name": "U"}, format="json").status_code, 200)

    def test_password_user_can_still_change_password(self):
        user = User.objects.create_user(username="pw", password="old-password-123")
        client = APIClient()
        client.force_authenticate(user)
        self.assertEqual(client.patch(ME, {"password": "new-password-123"}, format="json").status_code, 200)


class SessionTests(FlowTestCase):
    def test_callback_sets_no_session(self):
        provider = self.make_flow_provider()
        client = APIClient()
        response = self.sign_in(client, provider, {"roles": ["admins"]})
        self.assertIsNone(sso_error(response), response["Location"])
        self.assertNotIn("sessionid", response.cookies, "the callback created a Django session")
        exchanged = self.exchange(client, response)
        self.assertNotIn("sessionid", exchanged.cookies)
        for session in Session.objects.all():
            self.assertNotIn("_auth_user_id", session.get_decoded())


class ThrottleTests(FlowTestCase):
    def test_21st_start_in_a_minute_throttled(self):
        self.make_flow_provider()
        client = APIClient()
        for i in range(20):
            self.assertEqual(client.get("/api/accounts/oidc/p1/start/").status_code, 302, i)
        response = client.get("/api/accounts/oidc/p1/start/")
        self.assertEqual(response.status_code, 429)


class UnavailableTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_malformed_discovery_on_start(self):
        self.op.discovery_extra = {"authorization_endpoint": 5}
        response = APIClient().get("/api/accounts/oidc/p1/start/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(sso_error(response), "provider_unavailable")
        self.assertFalse(binding_cookies(response))

    def test_discovery_not_json_on_start(self):
        with mock.patch.object(self.op, "discovery_document", side_effect=lambda: ["not", "an", "object"]):
            response = APIClient().get("/api/accounts/oidc/p1/start/")
        self.assertEqual(sso_error(response), "provider_unavailable")

    def test_malformed_discovery_on_callback(self):
        client = APIClient()
        url = self.start(client, self.provider)
        # Not cache.clear(): django_redis flushes the whole DB, transactions included.
        cache.delete(discovery.discovery_cache_key(self.provider))
        self.op.discovery_extra = {"token_endpoint": None}
        response = self.callback(client, self.provider, self.op.authorize(url, {"roles": ["staff"]}))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(sso_error(response), "provider_unavailable")

    def test_link_start_discovery_failure_502(self):
        client, _ = admin_client()
        self.op.discovery_extra = {"jwks_uri": []}
        response = client.post("/api/accounts/oidc/p1/link/start/", {}, format="json")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"code": "provider_unavailable"})

    def test_redis_down_on_start(self):
        with mock.patch("core.utils.RedisClient.get_client", return_value=None):
            response = APIClient().get("/api/accounts/oidc/p1/start/")
        self.assertEqual(sso_error(response), "sso_unavailable")

    def test_jwks_unreachable_is_id_token_invalid(self):
        client = APIClient()
        url = self.start(client, self.provider)
        with mock.patch.object(discovery, "get_jwks", side_effect=discovery.DiscoveryError("jwks_unreachable")):
            response = self.callback(client, self.provider, self.op.authorize(url, {"roles": ["staff"]}))
        self.assertEqual(sso_error(response), "id_token_invalid")


class CacheTests(FlowTestCase):
    def test_discovery_and_jwks_cached_per_version(self):
        provider = self.make_flow_provider()
        self.login(APIClient(), provider, {"roles": ["staff"]})
        self.assertIsNotNone(cache.get(discovery.discovery_cache_key(provider)))
        self.assertIsNotNone(cache.get(discovery.jwks_cache_key(provider)))
        gets = len(self.op.gets)
        self.login(APIClient(), provider, {"roles": ["staff"]})
        self.assertEqual(len(self.op.gets), gets, "a second login refetched a cached document")
        provider = bump_mappings(provider, scopes="openid profile")
        self.login(APIClient(), provider, {"roles": ["staff"]})
        self.assertGreater(len(self.op.gets), gets, "a version bump did not invalidate the cache")


# ---- T32, T33: client authentication -----------------------------------------------------


def awkward_secret():
    # Built at runtime: a literal secret-shaped string trips the repository's gitleaks scan.
    return "p@ss" + ":w+rd/ " + "%&=" + "é~"


AWKWARD_CLIENT_ID = "client:id+1"


class ClientAuthTests(FlowTestCase):
    def test_basic_credentials_are_form_urlencoded(self):
        provider = self.make_flow_provider(
            client_id=AWKWARD_CLIENT_ID,
            client_auth_method="client_secret_basic",
            client_secret_encrypted=oidc_secrets.encrypt(awkward_secret()),
        )
        self.op.expected_client_id = AWKWARD_CLIENT_ID
        self.op.expected_secret = awkward_secret()
        response = self.sign_in(APIClient(), provider, {"roles": ["staff"], "aud": AWKWARD_CLIENT_ID})
        request = self.op.token_requests[-1]
        auth = request["headers"]["Authorization"]
        self.assertTrue(auth.startswith("Basic "))
        # A conforming client sends only ASCII here; latin-1 decodes whatever arrived so a
        # non-conforming header is shown in the failure rather than raising.
        decoded = base64.b64decode(auth[6:]).decode("latin-1")
        raw_id, _, raw_secret = decoded.partition(":")
        got = (unquote_plus(raw_id), unquote_plus(raw_secret))
        self.assertEqual(
            got, (AWKWARD_CLIENT_ID, awkward_secret()),
            f"form-decoded Basic pair {got!r} != configured {(AWKWARD_CLIENT_ID, awkward_secret())!r}",
        )
        self.assertNotIn(" ", decoded)
        self.assertEqual(decoded.count(":"), 1)
        self.assertNotIn("client_secret", request["form"])
        # The OP accepted the credential and the login completed.
        self.assertIsNone(sso_error(response), response["Location"])

    def test_post_secret_round_trips(self):
        provider = self.make_flow_provider(
            client_id=AWKWARD_CLIENT_ID,
            client_auth_method="client_secret_post",
            client_secret_encrypted=oidc_secrets.encrypt(awkward_secret()),
        )
        self.op.expected_client_id = AWKWARD_CLIENT_ID
        self.op.expected_secret = awkward_secret()
        response = self.sign_in(APIClient(), provider, {"roles": ["staff"], "aud": AWKWARD_CLIENT_ID})
        self.assertIsNone(sso_error(response), response["Location"])
        request = self.op.token_requests[-1]
        self.assertEqual(request["form"]["client_secret"], awkward_secret())
        self.assertEqual(request["form"]["client_id"], AWKWARD_CLIENT_ID)
        self.assertNotIn("Authorization", request["headers"])

    def test_entra_preset_defaults_to_post_and_refuses_basic(self):
        client, _ = admin_client()
        created = client.post(PROVIDERS, entra_body(), format="json")
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()["client_auth_method"], "client_secret_post")
        refused = client.post(PROVIDERS, entra_body(slug="entra2", client_auth_method="client_secret_basic"), format="json")
        self.assertEqual(refused.status_code, 400)
        self.assertIn("client_auth_method", refused.json())

    def test_invalid_client_maps_to_client_auth_failed(self):
        provider = self.make_flow_provider()
        description = "SENTINEL-ERROR-DESCRIPTION-" + b64url(b"desc")
        self.op.token_response = (401, {"error": "invalid_client", "error_description": description})
        with capture_all_logs() as logs:
            response = self.sign_in(APIClient(), provider, {"roles": ["staff"]})
        self.assertEqual(sso_error(response), "client_auth_failed")
        for name, text in logs:
            self.assertNotIn(description, text, f"error_description reached logger {name}")
        for event in SystemEvent.objects.all():
            self.assertNotIn(description, json.dumps(event.details))

    def test_other_token_error_maps_to_token_exchange_failed(self):
        provider = self.make_flow_provider()
        self.op.token_response = (400, {"error": "invalid_grant"})
        self.assertEqual(sso_error(self.sign_in(APIClient(), provider, {"roles": ["staff"]})), "token_exchange_failed")
        self.op.token_response = (200, {"access_token": "only"})
        self.assertEqual(sso_error(self.sign_in(APIClient(), provider, {"roles": ["staff"]})), "token_exchange_failed")

    def test_undecryptable_secret_refused(self):
        provider = self.make_flow_provider(client_secret_encrypted="garbage")
        self.assertEqual(sso_error(self.sign_in(APIClient(), provider, {"roles": ["staff"]})), "token_exchange_failed")


class ClientAssertionTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.admin, _ = admin_client()
        self.provider = self.make_flow_provider(client_auth_method="private_key_jwt", client_secret_encrypted="")
        self.cert_url = f"{PROVIDERS}{self.provider.pk}/certificate/"
        self.active_cert = self.generate_and_activate()
        self.provider.refresh_from_db()

    def generate(self):
        response = self.admin.post(self.cert_url)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def generate_and_activate(self):
        generated = self.generate()
        activated = self.admin.post(
            f"{self.cert_url}activate/", {"thumbprint_sha256": generated["thumbprint_sha256"]}, format="json"
        )
        self.assertEqual(activated.status_code, 200, activated.content)
        return x509.load_pem_x509_certificate(generated["certificate_pem"].encode())

    def assertion(self):
        form = self.op.token_requests[-1]["form"]
        return form["client_assertion"]

    def test_assertion_shape(self):
        self.op.assertion_key = self.active_cert.public_key()
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"]})
        token = self.assertion()  # inspected before the outcome, so a wrong claim is named
        header = jwt.get_unverified_header(token)
        self.assertEqual(header["alg"], "PS256")
        self.assertEqual(header["typ"], "JWT")
        der = self.active_cert.public_bytes(serialization.Encoding.DER)
        self.assertEqual(header["x5t#S256"], b64url(hashlib.sha256(der).digest()))
        self.assertNotIn("x5t", header)
        claims = decode_unverified(token)
        self.assertEqual(claims["iss"], CLIENT_ID)
        self.assertEqual(claims["sub"], CLIENT_ID)
        self.assertEqual(
            claims["aud"], self.op.token_endpoint,
            f"assertion aud {claims['aud']!r}; expected the discovered token_endpoint {self.op.token_endpoint!r}",
        )
        self.assertEqual(claims["exp"] - claims["nbf"], 300)
        self.assertEqual(claims["iat"], claims["nbf"])
        self.assertTrue(claims["jti"])
        self.assertIsNone(sso_error(response), response["Location"])

    def test_assertion_replaces_secret(self):
        self.sign_in(APIClient(), self.provider, {"roles": ["staff"]})
        request = self.op.token_requests[-1]
        self.assertEqual(request["form"]["client_assertion_type"], client_auth.ASSERTION_TYPE)
        self.assertIn("client_assertion", request["form"])
        self.assertNotIn("client_secret", request["form"])
        self.assertNotIn("Authorization", request["headers"])

    def test_jti_is_fresh_per_request(self):
        self.sign_in(APIClient(), self.provider, {"roles": ["staff"]})
        first = decode_unverified(self.assertion())["jti"]
        self.sign_in(APIClient(), self.provider, {"roles": ["staff"]})
        self.assertNotEqual(decode_unverified(self.assertion())["jti"], first)

    def test_signature_verifies_with_active_certificate_only(self):
        pending = x509.load_pem_x509_certificate(self.generate()["certificate_pem"].encode())
        self.provider.refresh_from_db()
        self.sign_in(APIClient(), self.provider, {"roles": ["staff"]})
        token = self.assertion()
        try:
            jwt.decode(token, self.active_cert.public_key(), algorithms=["PS256"], audience=self.op.token_endpoint)
        except jwt.PyJWTError as exc:
            self.fail(f"the assertion does not verify against the ACTIVE certificate: {type(exc).__name__}")
        with self.assertRaises(jwt.InvalidSignatureError):
            jwt.decode(token, pending.public_key(), algorithms=["PS256"], audience=self.op.token_endpoint)

    def test_generic_provider_may_use_rs256(self):
        provider = bump_mappings(self.provider, client_assertion_alg="RS256")
        self.op.assertion_key = self.active_cert.public_key()
        response = self.sign_in(APIClient(), provider, {"roles": ["staff"]})
        self.assertIsNone(sso_error(response), response["Location"])
        self.assertEqual(jwt.get_unverified_header(self.assertion())["alg"], "RS256")

    def test_missing_key_refused(self):
        OIDCProvider.update_columns(self.provider.pk, {"client_key_encrypted": ""})
        self.provider.refresh_from_db()
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"]})
        self.assertEqual(sso_error(response), "token_exchange_failed")
        self.assertEqual(self.op.token_requests, [])


# ---- T34: the session's bound -------------------------------------------------------------


class SessionLifetimeTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_sso_refresh_token_lives_12_hours(self):
        body = self.login(APIClient(), self.provider, {"roles": ["staff"]})
        claims = decode_unverified(body["refresh"])
        self.assertEqual(claims["exp"] - claims["iat"], 43200, "the SSO refresh token does not live 12 hours")
        User.objects.create_user(username="pw", password="testpass123")
        password = APIClient().post("/api/accounts/token/", {"username": "pw", "password": "testpass123"}, format="json")
        self.assertEqual(password.status_code, 200, password.content)
        pclaims = decode_unverified(password.json()["refresh"])
        self.assertEqual(pclaims["exp"] - pclaims["iat"], 86400)

    def test_refresh_refused_after_12_hours(self):
        signed_in = aware_utcnow()
        body = self.login(APIClient(), self.provider, {"roles": ["staff"]})
        target = "rest_framework_simplejwt.tokens.aware_utcnow"
        with mock.patch(target, return_value=signed_in + datetime.timedelta(hours=11, minutes=59)):
            self.assertEqual(self.refresh(body["refresh"]).status_code, 200)
        with mock.patch(target, return_value=signed_in + datetime.timedelta(hours=12, seconds=1)):
            late = self.refresh(body["refresh"])
        self.assertEqual(late.status_code, 401, "an SSO refresh token was honoured past 12 hours")

    def test_refresh_rotation_is_off(self):
        self.assertFalse(
            settings.SIMPLE_JWT["ROTATE_REFRESH_TOKENS"],
            "SSO spec 3.3 step 9: rotation would re-stamp the 12-hour exp with the class lifetime",
        )


# ---- T27, D17: refresh re-evaluation --------------------------------------------------------


class RefreshTests(FlowTestCase):
    """The single-threaded half of D17; the interleavings are in RefreshReevaluationTests."""

    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_disabled_provider_refuses_refresh(self):
        body = self.login(APIClient(), self.provider, {"roles": ["staff"]})
        OIDCProvider.update_columns(self.provider.pk, {"enabled": False})
        response = self.refresh(body["refresh"])
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "token_not_valid")

    def test_deleted_provider_refuses_refresh(self):
        body = self.login(APIClient(), self.provider, {"roles": ["staff"]})
        OIDCIdentity.objects.all().delete()
        OIDCProvider.objects.all().delete()
        self.assertEqual(self.refresh(body["refresh"]).status_code, 401)

    def test_password_refresh_unaffected(self):
        User.objects.create_user(username="pw", password="testpass123")
        token = APIClient().post("/api/accounts/token/", {"username": "pw", "password": "testpass123"}, format="json")
        self.assertEqual(self.refresh(token.json()["refresh"]).status_code, 200)


class RefreshReevaluationTests(FlowTransactionTestCase):
    """D17 (spec 5.4, T27): a changed provider version recomputes the level from the claim
    values stored at the last login. Real commits; the interleavings are event-driven."""

    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def sso_admin(self, username="u", claims=None):
        body = self.login(APIClient(), self.provider, {"roles": ["admins"], "preferred_username": username, **(claims or {})})
        return body, User.objects.get(username=username)

    def level(self, username="u"):
        return User.objects.get(username=username).user_level

    # ---- single-threaded --------------------------------------------------------------

    def test_mapping_change_demotes_on_refresh(self):
        make_admin()
        body, _ = self.sso_admin()
        bump_mappings(self.provider, [{"value": "admins", "user_level": 1}])
        response = self.refresh(body["refresh"])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.level(), 1, "the mapping change did not demote on refresh")

    def test_mapping_removed_refuses_refresh(self):
        make_admin()
        body, _ = self.sso_admin()
        bump_mappings(self.provider, [{"value": "staff", "user_level": 1}])
        self.assertEqual(self.refresh(body["refresh"]).status_code, 401)
        self.assertEqual(self.level(), 10)

    def test_refresh_never_promotes(self):
        body = self.login(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": "u"})
        bump_mappings(self.provider, [{"value": "staff", "user_level": 10}])
        self.assertEqual(self.refresh(body["refresh"]).status_code, 200)
        self.assertEqual(self.level(), 1)

    def test_claim_path_change_refuses_refresh(self):
        make_admin()
        body, _ = self.sso_admin()
        bump_mappings(self.provider, [{"value": "admins", "user_level": 1}], claim_path="groups")
        response = self.refresh(body["refresh"])
        self.assertEqual(response.status_code, 401, "a claim-path change let the stored values be reinterpreted")
        self.assertEqual(self.level(), 10)

    def test_unchanged_version_reads_only_provider(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        User.objects.create_user(username="pw", password="testpass123")
        password = APIClient().post("/api/accounts/token/", {"username": "pw", "password": "testpass123"}, format="json")
        body = self.login(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": "u"})
        with CaptureQueriesContext(connection) as baseline:
            self.assertEqual(self.refresh(password.json()["refresh"]).status_code, 200)
        with CaptureQueriesContext(connection) as sso:
            self.assertEqual(self.refresh(body["refresh"]).status_code, 200)
        extra = len(sso.captured_queries) - len(baseline.captured_queries)
        self.assertEqual(extra, 1, [q["sql"] for q in sso.captured_queries])
        provider_reads = [q for q in sso.captured_queries if "accounts_oidcprovider" in q["sql"]]
        self.assertEqual(len(provider_reads), 1)
        self.assertFalse([q for q in sso.captured_queries if "accounts_oidcidentity" in q["sql"]])

    # ---- interleavings ------------------------------------------------------------------

    def hold_refresh_at_floor_lock(self):
        """Hold the refresh thread in a wrapper around ``admin_floor_lock``, before the helper
        runs. Returns (entered, release)."""
        from apps.accounts.oidc import refresh as refresh_mod

        entered, release = threading.Event(), threading.Event()
        original = refresh_mod.admin_floor_lock

        def wrapper():
            if threading.current_thread().name == "refresh":
                entered.set()
                release.wait(WAIT_TIMEOUT)
            return original()

        patcher = mock.patch.object(refresh_mod, "admin_floor_lock", side_effect=wrapper)
        patcher.start()
        self.addCleanup(patcher.stop)
        return entered, release

    def run_held_refresh(self, token, between):
        entered, release = self.hold_refresh_at_floor_lock()
        worker = Worker(lambda: self.refresh(token), "refresh")
        try:
            worker.start()
            self.assertTrue(entered.wait(WAIT_TIMEOUT), "the refresh never reached admin_floor_lock")
            between()
            release.set()
        finally:
            join_all([worker], [release])
        self.assertIsNone(worker.error, repr(worker.error))
        self.assertFalse(worker.is_alive(), "the refresh thread did not finish")
        return worker.result

    def test_claim_path_changed_between_reads(self):
        self.require_postgresql()
        make_admin()
        with self.subTest(case="a: path edited only"):
            body, user = self.sso_admin()
            bump_mappings(self.provider, [{"value": "admins", "user_level": 1}])
            response = self.run_held_refresh(
                body["refresh"], lambda: bump_mappings(self.provider, claim_path="groups")
            )
            self.assertEqual(
                response.status_code, 401,
                f"refresh answered {response.status_code} after the claim path changed under it",
            )
            self.assertEqual(self.level(), 10)

        with self.subTest(case="b: path edited and identity re-stored"):
            OIDCIdentity.objects.all().delete()
            User.objects.filter(username="u").delete()
            bump_mappings(self.provider, [{"value": "admins", "user_level": 10}], claim_path="roles")
            body, user = self.sso_admin()
            bump_mappings(self.provider, [{"value": "admins", "user_level": 1}])

            def between():
                bump_mappings(
                    self.provider,
                    [{"value": "g-admins", "user_level": 10}, {"value": "admins", "user_level": 1}],
                    claim_path="groups",
                )
                self.login(APIClient(), self.provider, {"groups": ["g-admins"], "preferred_username": "u"})

            response = self.run_held_refresh(body["refresh"], between)
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(self.level(), 10)

    def test_recompute_to_admin_between_reads_is_no_demotion(self):
        self.require_postgresql()
        body, user = self.sso_admin()  # the only active admin
        bump_mappings(self.provider, [{"value": "admins", "user_level": 1}, {"value": "super", "user_level": 10}])

        def between():
            self.login(APIClient(), self.provider, {"roles": ["super"], "preferred_username": "u"})

        response = self.run_held_refresh(body["refresh"], between)
        last_admin = SystemEvent.objects.filter(event_type="login_failed", details__reason="last_admin")
        self.assertEqual(
            response.status_code, 200,
            f"expected 200, got {response.status_code} with {last_admin.count()} last_admin event(s): "
            "the last-admin test ran on a level the re-read no longer gives",
        )
        self.assertEqual(self.level(), 10)
        self.assertFalse(last_admin.exists())

    def test_identity_unlinked_between_reads_refuses(self):
        self.require_postgresql()
        make_admin()
        body, user = self.sso_admin()
        bump_mappings(self.provider, [{"value": "admins", "user_level": 1}])
        response = self.run_held_refresh(body["refresh"], lambda: OIDCIdentity.objects.all().delete())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.level(), 10)

    def test_concurrent_refreshes_never_raise_level(self):
        self.require_postgresql()
        from apps.accounts.oidc import refresh as refresh_mod

        make_admin()
        p0 = self.provider
        p1 = self.make_flow_provider(slug="p2", display_name="Provider Two")
        t0 = self.login(APIClient(), p0, {"roles": ["admins"], "preferred_username": "u"})["refresh"]
        # The same user linked at the second provider.
        client = APIClient()
        client.force_authenticate(User.objects.get(username="u"))
        url = self.link_start(client, p1)
        linked = self.callback(client, p1, self.op.authorize(url, {"roles": ["admins"], "sub": "subject-1b"}))
        self.assertIsNone(sso_error(linked), linked["Location"])
        self.assertEqual(OIDCIdentity.objects.filter(user__username="u").count(), 2)
        t1 = self.login(APIClient(), p1, {"roles": ["admins"], "preferred_username": "u", "sub": "subject-1b"})["refresh"]
        bump_mappings(p0, [{"value": "admins", "user_level": 0}])
        bump_mappings(p1, [{"value": "admins", "user_level": 1}])

        barrier = threading.Barrier(2, timeout=WAIT_TIMEOUT)
        zero_done = threading.Event()
        load_user, demote, floor = refresh_mod.load_user, refresh_mod._demote, refresh_mod.admin_floor_lock

        def load_user_wrapper(user_id):
            loaded = load_user(user_id)
            barrier.wait()  # both have read 10 before either locks
            return loaded

        def demote_wrapper(target, payload):
            try:
                return demote(target, payload)
            finally:
                if threading.current_thread().name == "level0":
                    zero_done.set()

        def floor_wrapper():
            if threading.current_thread().name == "level1":
                zero_done.wait(WAIT_TIMEOUT)
            return floor()

        workers = [Worker(lambda: self.refresh(t0), "level0"), Worker(lambda: self.refresh(t1), "level1")]
        with mock.patch.object(refresh_mod, "load_user", side_effect=load_user_wrapper), \
                mock.patch.object(refresh_mod, "_demote", side_effect=demote_wrapper), \
                mock.patch.object(refresh_mod, "admin_floor_lock", side_effect=floor_wrapper):
            try:
                for worker in workers:
                    worker.start()
            finally:
                join_all(workers, [zero_done])
        for worker in workers:
            self.assertIsNone(worker.error, repr(worker.error))
            self.assertEqual(worker.result.status_code, 200, worker.name)
        self.assertTrue(zero_done.is_set())
        self.assertEqual(
            self.level(), 0,
            f"final level {self.level()}: the level-1 refresh wrote over the committed 0, a promotion",
        )


class HandoffConcurrencyTests(FlowTransactionTestCase):
    def test_concurrent_exchanges_one_wins(self):
        # SQLite's in-memory test database is not visible from a second thread.
        self.require_postgresql("needs a database the worker threads can reach")
        provider = self.make_flow_provider()
        client = APIClient()
        response = self.sign_in(client, provider, {"roles": ["staff"]})
        code = fragment_code(response["Location"])
        cookies = {name: morsel.value for name, morsel in client.cookies.items()}
        barrier = threading.Barrier(2, timeout=WAIT_TIMEOUT)
        original = flow.take

        def take_wrapper(key):
            if key.startswith("oidc:handoff:"):
                barrier.wait()  # both redeem the same code at once
            return original(key)

        def redeem():
            browser = APIClient()
            for name, value in cookies.items():
                browser.cookies[name] = value
            return browser.post(EXCHANGE, {"code": code}, format="json")

        workers = [Worker(redeem, "x"), Worker(redeem, "y")]
        with mock.patch.object(flow, "take", side_effect=take_wrapper):
            try:
                for worker in workers:
                    worker.start()
            finally:
                join_all(workers)
        for worker in workers:
            self.assertIsNone(worker.error, repr(worker.error))
        statuses = sorted(w.result.status_code for w in workers)
        self.assertEqual(statuses, [200, 400], "one handoff code was redeemed twice" if statuses == [200, 200] else statuses)


# ---- fix round 1 ---------------------------------------------------------------------------


class IllNamedCookieTests(FlowTestCase):
    """Only the shape binding_cookie_name produces counts as a stale transaction cookie.

    Django's request parser accepts names http.cookies refuses to write; expiring one made
    set_cookie raise CookieError and start answer 500.
    """

    ILL_NAMED = "; ".join(f"__Host-mino_oidc_tx_({i})=x" for i in range(5))

    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_start_with_five_ill_named_prefixed_cookies(self):
        client = APIClient(raise_request_exception=False)
        response = client.get("/api/accounts/oidc/p1/start/", HTTP_COOKIE=self.ILL_NAMED)
        self.assertEqual(
            response.status_code, 302,
            f"start answered {response.status_code} to five ill-named prefixed cookies",
        )
        self.assertTrue(response["Location"].startswith(self.op.issuer), response["Location"])
        cookies = binding_cookies(response)
        self.assertEqual([n for n, m in cookies.items() if m["max-age"] == 0], [])
        self.assertEqual(len(cookies), 1)

    def test_link_start_with_five_ill_named_prefixed_cookies(self):
        client, _ = admin_client()
        client.raise_request_exception = False
        response = client.post(
            "/api/accounts/oidc/p1/link/start/", {"next": "/users"}, format="json",
            HTTP_COOKIE=self.ILL_NAMED,
        )
        self.assertEqual(
            response.status_code, 200,
            f"link/start answered {response.status_code} to five ill-named prefixed cookies",
        )

    def test_ill_named_cookies_do_not_count_toward_the_cap(self):
        good = "; ".join(f"__Host-mino_oidc_tx_{i:016x}=x" for i in range(4))
        response = APIClient().get(
            "/api/accounts/oidc/p1/start/", HTTP_COOKIE=f"{good}; {self.ILL_NAMED}"
        )
        cookies = binding_cookies(response)
        self.assertEqual(
            [n for n, m in cookies.items() if m["max-age"] == 0], [],
            "four well-formed cookies were expired: the ill-named ones were counted",
        )


class ControlCharacterTests(FlowTestCase):
    """A validated claim carrying a control character never reaches the database as such.

    sub and mapping values are refused (stripping could merge two values); display fields
    are stripped (never compared, and a user may edit them at the IdP).
    """

    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()
        self.client = APIClient(raise_request_exception=False)

    def _sign_in(self, claims):
        return self.sign_in(self.client, self.provider, claims)

    def test_sub_with_a_control_character_refused(self):
        for char in ("\x00", "\x1f", "\x85"):
            with self.subTest(char=hex(ord(char))):
                response = self._sign_in({"sub": f"a{char}b", "roles": ["staff"]})
                self.assertEqual(response.status_code, 302, response.status_code)
                self.assertEqual(
                    sso_error(response), "id_token_invalid",
                    f"a sub carrying {hex(ord(char))} was not refused at validation",
                )
        self.assertFalse(OIDCIdentity.objects.exists())

    def test_mapping_value_with_a_control_character_refused(self):
        users = User.objects.count()
        response = self._sign_in({"roles": ["staff", "x\x00y"]})
        self.assertEqual(response.status_code, 302, response.status_code)
        self.assertEqual(
            sso_error(response), "id_token_invalid",
            "a mapping value carrying NUL was not refused before provisioning",
        )
        self.assertEqual(User.objects.count(), users)

    def test_email_control_characters_stripped(self):
        response = self._sign_in({"roles": ["staff"], "email": "a\x00b@example.com"})
        self.assertEqual(response.status_code, 302, response.status_code)
        self.assertIsNone(
            sso_error(response), f"the email's NUL reached the database: {response['Location']}"
        )
        identity = OIDCIdentity.objects.get()
        self.assertEqual(identity.email_at_last_login, "ab@example.com")
        self.assertEqual(identity.user.email, "ab@example.com")

    def test_name_control_characters_stripped(self):
        response = self._sign_in({"roles": ["staff"], "name": "a\x00b"})
        self.assertEqual(response.status_code, 302, response.status_code)
        self.assertIsNone(
            sso_error(response), f"the name's NUL reached the database: {response['Location']}"
        )
        self.assertEqual(OIDCIdentity.objects.get().display_name, "ab")

    def test_database_error_in_provisioning_is_provisioning_failed(self):
        with mock.patch.object(
            provisioning, "resolve", side_effect=OperationalError("deadlock detected")
        ):
            response = self._sign_in({"roles": ["staff"]})
        self.assertEqual(
            response.status_code, 302,
            f"a DatabaseError from resolve answered {response.status_code}",
        )
        self.assertEqual(sso_error(response), "provisioning_failed")

    # Lone UTF-16 surrogates (category Cs): JSON's "\ud800" escape decodes to one, and no
    # UTF-8 encoder will write it, so before fix round 2 each of these answered 500.

    def test_sub_with_a_lone_surrogate_refused(self):
        for char in ("\ud800", "\udfff"):
            with self.subTest(char=hex(ord(char))):
                response = self._sign_in({"sub": f"a{char}b", "roles": ["staff"]})
                self.assertEqual(
                    response.status_code, 302,
                    f"a sub carrying {hex(ord(char))} answered {response.status_code}",
                )
                self.assertEqual(
                    sso_error(response), "id_token_invalid",
                    f"a sub carrying {hex(ord(char))} was not refused at validation",
                )
        self.assertFalse(OIDCIdentity.objects.exists())

    def test_mapping_value_with_a_lone_surrogate_refused(self):
        users = User.objects.count()
        response = self._sign_in({"roles": ["staff", "x\ud800y"]})
        self.assertEqual(response.status_code, 302, response.status_code)
        self.assertEqual(
            sso_error(response), "id_token_invalid",
            "a mapping value carrying a lone surrogate was not refused before provisioning",
        )
        self.assertEqual(User.objects.count(), users)

    def test_display_field_lone_surrogates_stripped(self):
        response = self._sign_in({
            "roles": ["staff"],
            "email": "a\ud800b@example.com",
            "name": "n\udfffm",
            "preferred_username": "p\ud800u",
            "given_name": "g\ud800n",
            "family_name": "f\udfffn",
        })
        self.assertEqual(
            response.status_code, 302,
            f"display fields carrying lone surrogates answered {response.status_code}",
        )
        self.assertIsNone(sso_error(response), response["Location"])
        identity = OIDCIdentity.objects.get()
        self.assertEqual(identity.email_at_last_login, "ab@example.com")
        self.assertEqual(identity.display_name, "nm")
        self.assertEqual(identity.user.email, "ab@example.com")
        self.assertEqual(identity.user.first_name, "gn")
        self.assertEqual(identity.user.last_name, "fn")
        self.assertNotIn("\ud800", identity.user.username)

    def test_unicode_error_in_provisioning_is_provisioning_failed(self):
        error = UnicodeEncodeError("utf-8", "\ud800", 0, 1, "surrogates not allowed")
        with mock.patch.object(provisioning, "resolve", side_effect=error):
            response = self._sign_in({"roles": ["staff"]})
        self.assertEqual(
            response.status_code, 302,
            f"a UnicodeEncodeError from resolve answered {response.status_code}",
        )
        self.assertEqual(sso_error(response), "provisioning_failed")


class HostileTokenShapeTests(FlowTestCase):
    """Signed ID tokens whose JSON json.dumps cannot produce: each is a refusal, never a 500.

    The token is signed with the fake OP's own key, so every refusal here comes from decoding
    or validation, not from the signature.
    """

    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()
        self.client = APIClient(raise_request_exception=False)

    def _raw_sign_in(self, payload_template, header_json=None):
        url = self.start(self.client, self.provider)
        nonce = query_of(url)["nonce"]
        now = int(time.time())
        payload = payload_template % {
            "iss": json.dumps(self.op.issuer), "aud": json.dumps(CLIENT_ID),
            "nonce": json.dumps(nonce), "iat": now, "exp": now + 300,
        }
        header = header_json or json.dumps({"alg": "RS256", "kid": "rsa1", "typ": "JWT"})
        signing_input = f"{b64url(header.encode())}.{b64url(payload.encode())}"
        rsa = jwt.algorithms.RSAAlgorithm(jwt.algorithms.RSAAlgorithm.SHA256)
        token = f"{signing_input}.{b64url(rsa.sign(signing_input.encode(), keys()['rsa']))}"
        return self.callback(self.client, self.provider, self.op.authorize(url, raw_token=token))

    BASE = (
        '{"iss": %(iss)s, "aud": %(aud)s, "sub": "raw-1", "nonce": %(nonce)s, '
        '"roles": ["staff"], "iat": %(iat)d, "exp": %(exp)d, EXTRA}'
    )

    def assertRefused(self, response, label):
        self.assertEqual(response.status_code, 302, f"{label} answered {response.status_code}")
        self.assertEqual(sso_error(response), "id_token_invalid", f"{label}: {response['Location']}")
        self.assertFalse(OIDCIdentity.objects.exists())

    def test_deep_nesting_in_the_payload_refused(self):
        deep = "[" * 100000 + "]" * 100000
        response = self._raw_sign_in(self.BASE.replace("EXTRA", f'"deep": {deep}'))
        self.assertRefused(response, "a payload nested 100000 deep")

    def test_deep_nesting_in_the_header_refused(self):
        deep = "[" * 100000 + "]" * 100000
        header = '{"alg": "RS256", "kid": "rsa1", "x": %s}' % deep
        response = self._raw_sign_in(self.BASE.replace("EXTRA", '"x": 1'), header_json=header)
        self.assertRefused(response, "a header nested 100000 deep")

    def test_infinite_time_claims_refused(self):
        for claim in ("exp", "iat", "nbf"):
            for value in ("1e999", "-1e999"):
                with self.subTest(claim=claim, value=value):
                    OIDCIdentity.objects.all().delete()
                    cache.clear()  # the start throttle
                    # Duplicate JSON keys: the last value wins, so this one replaces the
                    # template's integer.
                    response = self._raw_sign_in(self.BASE.replace("EXTRA", f'"{claim}": {value}'))
                    self.assertRefused(response, f"{claim}={value}")


class EntraControlCharacterTests(FlowTestCase):
    """Entra's oid is stored in the identity's ``extra``: stripped like a display field."""

    def setUp(self):
        super().setUp()
        self.provider = make_entra(
            enabled=True, client_id=CLIENT_ID, mappings=[{"value": "staff", "user_level": 1}]
        )
        doc = self.op.discovery_document()
        doc["issuer"] = self.provider.issuer
        patcher = mock.patch.object(discovery, "get_discovery", return_value=doc)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_oid_lone_surrogate_stripped(self):
        claims = {"iss": self.provider.issuer, "tid": TENANT, "oid": "o\ud800i", "roles": ["staff"]}
        response = self.sign_in(APIClient(raise_request_exception=False), self.provider, claims)
        self.assertEqual(
            response.status_code, 302, f"an oid carrying a lone surrogate answered {response.status_code}"
        )
        self.assertIsNone(sso_error(response), response["Location"])
        self.assertEqual(OIDCIdentity.objects.get().extra, {"tid": TENANT, "oid": "oi"})


class NetworkAclTests(FlowTestCase):
    """Spec 3.1: the UI network ACL gates providers/, start, callback and exchange."""

    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()
        # The test client's address, 127.0.0.1, is outside this allowlist.
        CoreSettings.objects.update_or_create(
            key=NETWORK_ACCESS_KEY,
            defaults={"name": "Network Access", "value": {"UI": "10.99.0.0/16"}},
        )

    def assertRefused(self, response, path, flow_endpoint=True):
        self.assertEqual(
            response.status_code, 403,
            f"{path} answered {response.status_code} to an address outside the UI ACL",
        )
        if flow_endpoint:
            for name, value in flow.NO_STORE_HEADERS.items():
                self.assertEqual(response.get(name), value, f"{path}: {name}")

    def test_providers(self):
        path = "/api/accounts/oidc/providers/"
        self.assertRefused(APIClient().get(path), path, flow_endpoint=False)

    def test_start(self):
        path = "/api/accounts/oidc/p1/start/"
        self.assertRefused(APIClient().get(path), path)

    def test_callback(self):
        path = "/api/accounts/oidc/p1/callback/"
        self.assertRefused(APIClient().get(path, {"state": "s" * 43, "code": "c"}), path)

    def test_exchange(self):
        self.assertRefused(APIClient().post(EXCHANGE, {"code": "c" * 43}, format="json"), EXCHANGE)

    def test_link_start(self):
        client, _ = admin_client()
        path = "/api/accounts/oidc/p1/link/start/"
        self.assertRefused(client.post(path, {"next": "/users"}, format="json"), path)


class ConnectionReleaseTests(FlowTransactionTestCase):
    """The callback and start hold no database connection across an outbound IdP call.

    What this proves: at the moment of every discovery, token and JWKS request in a whole
    login, Django's handle on this thread's connection is closed and no atomic block is
    open. Under the test backend (plain PostgreSQL) close() really closes the socket. That
    close() hands the connection back to django-db-geventpool's pool rather than closing it
    is read from that backend, not exercised here, and nothing here measures a worker
    under gevent with eight concurrent callbacks.
    """

    def test_no_connection_held_across_outbound_calls(self):
        self.require_postgresql("SQLite ignores close() on its in-memory test database")
        provider = self.make_flow_provider()
        seen = []
        real_fetch = discovery.fetch_outbound_http
        real_post = requests.post

        def note(kind):
            seen.append((kind, connection.connection is None, connection.in_atomic_block))

        def fetch(url, **kwargs):
            note("discovery" if url.endswith(discovery.WELL_KNOWN) else "jwks")
            return real_fetch(url, **kwargs)

        def post(url, **kwargs):
            note("token")
            return real_post(url, **kwargs)

        with mock.patch.object(discovery, "fetch_outbound_http", side_effect=fetch), \
                mock.patch.object(client_auth.requests, "post", side_effect=post):
            self.login(APIClient(), provider, {"roles": ["staff"]})
        self.assertEqual(sorted({kind for kind, _, _ in seen}), ["discovery", "jwks", "token"])
        for kind, released, atomic in seen:
            self.assertFalse(atomic, f"the {kind} request ran inside an atomic block")
            self.assertTrue(released, f"the database connection was held across the {kind} request")


DEAD_CACHE = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://127.0.0.1:1/0",
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}


class RedisOutageTests(FlowTestCase):
    """With Redis really unreachable, the flow answers sso_unavailable, never a 500.

    The cache points at a closed port, so the oidc throttle and the discovery cache meet the
    error django-redis raises in an outage; the transaction store's client is None.
    """

    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def _down(self):
        stack = mock.patch("core.utils.RedisClient.get_client", return_value=None)
        return override_settings(CACHES=DEAD_CACHE), stack

    def test_start(self):
        caches_down, store_down = self._down()
        with caches_down, store_down:
            response = APIClient(raise_request_exception=False).get("/api/accounts/oidc/p1/start/")
        self.assertEqual(
            response.status_code, 302, f"start answered {response.status_code} with Redis down"
        )
        self.assertEqual(sso_error(response), "sso_unavailable")

    def test_callback(self):
        caches_down, store_down = self._down()
        with caches_down, store_down:
            response = APIClient(raise_request_exception=False).get(
                "/api/accounts/oidc/p1/callback/", {"state": "s" * 43, "code": "c"}
            )
        self.assertEqual(
            response.status_code, 302, f"callback answered {response.status_code} with Redis down"
        )
        self.assertEqual(sso_error(response), "sso_unavailable")

    def test_exchange(self):
        caches_down, store_down = self._down()
        with caches_down, store_down:
            response = APIClient(raise_request_exception=False).post(
                EXCHANGE, {"code": "c" * 43}, format="json"
            )
        self.assertEqual(
            response.status_code, 503, f"exchange answered {response.status_code} with Redis down"
        )
        self.assertEqual(response.json(), {"code": "sso_unavailable"})


class DiscoveryCacheIssuerTests(FlowTestCase):
    def test_cached_document_for_another_issuer_is_refetched(self):
        provider = self.make_flow_provider()
        poisoned = {
            **self.op.discovery_document(),
            "issuer": "https://other.example/op",
            "token_endpoint": "https://other.example/op/token",
        }
        cache.set(discovery.discovery_cache_key(provider), poisoned, 60)
        doc = discovery.get_discovery(provider)
        self.assertEqual(
            doc["issuer"], provider.issuer,
            "a cached discovery document for another issuer was served",
        )


class ProviderEditDuringExchangeTests(FlowTestCase):
    def test_mapping_edit_during_token_exchange_refused(self):
        provider = self.make_flow_provider()
        client = APIClient()
        params = self.op.authorize(self.start(client, provider), {"roles": ["admins"]})
        real = client_auth.exchange_code

        def exchange_then_edit(*args, **kwargs):
            id_token = real(*args, **kwargs)
            bump_mappings(OIDCProvider.objects.get(pk=provider.pk), [{"value": "admins", "user_level": 0}])
            return id_token

        users = User.objects.count()
        with mock.patch.object(client_auth, "exchange_code", side_effect=exchange_then_edit):
            response = self.callback(client, provider, params)
        self.assertEqual(
            sso_error(response), "provider_mismatch",
            f"the login applied mappings loaded before the token exchange: {response['Location']}",
        )
        self.assertEqual(User.objects.count(), users)


# ---- fix round 3 ---------------------------------------------------------------------------


def private_jwk(private_key, kid):
    """The JWK of a PRIVATE key, as a broken IdP might publish it (no ``alg``)."""
    if isinstance(private_key, ed25519.Ed25519PrivateKey):
        jwk = json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(private_key))
    elif isinstance(private_key, ec.EllipticCurvePrivateKey):
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private_key))
    else:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key))
    jwk = {k: v for k, v in jwk.items() if k not in ("alg", "key_ops")}
    jwk.update({"kid": kid, "use": "sig"})
    return jwk


class PrivateJwkTests(FlowTestCase):
    """A JWKS entry carrying a private member is refused for every key type (spec 3.4).

    An RSA private key used to answer 500 (PyJWT's verify has no private-key path); EC and
    OKP private keys were accepted and the login succeeded.
    """

    def assertRefused(self, provider, jwk, signing_key, alg, kid):
        self.op.jwks_keys = [jwk]
        client = APIClient(raise_request_exception=False)
        response = self.sign_in(client, provider, {"roles": ["staff"]}, key=signing_key, alg=alg, kid=kid)
        self.assertEqual(
            response.status_code, 302, f"a {alg} private JWK answered {response.status_code}"
        )
        self.assertEqual(
            sso_error(response), "id_token_invalid",
            f"a {alg} JWK carrying a private member was used to verify: {response['Location']}",
        )
        self.assertFalse(OIDCIdentity.objects.exists())

    def test_rsa_private_jwk_refused(self):
        provider = self.make_flow_provider()
        self.assertRefused(provider, private_jwk(keys()["rsa"], "rsa1"), keys()["rsa"], "RS256", "rsa1")

    def test_rsa_public_jwk_with_d_only_refused(self):
        provider = self.make_flow_provider(id_token_alg="PS256")
        full = private_jwk(keys()["rsa"], "rsa1")
        jwk = dict(public_jwk(keys()["rsa"], "rsa1"), d=full["d"])
        self.assertRefused(provider, jwk, keys()["rsa"], "PS256", "rsa1")

    def test_ec_private_jwk_refused(self):
        provider = self.make_flow_provider(id_token_alg="ES256")
        self.assertRefused(provider, private_jwk(keys()["ec"], "ec1"), keys()["ec"], "ES256", "ec1")

    def test_okp_private_jwk_refused(self):
        key = ed25519.Ed25519PrivateKey.generate()
        provider = self.make_flow_provider(id_token_alg="EdDSA")
        self.assertRefused(provider, private_jwk(key, "okp1"), key, "EdDSA", "okp1")

    def test_okp_public_jwk_accepted(self):
        # The control for the OKP case: the same key, published public, signs a login in.
        key = ed25519.Ed25519PrivateKey.generate()
        jwk = {k: v for k, v in private_jwk(key, "okp1").items() if k != "d"}
        provider = self.make_flow_provider(id_token_alg="EdDSA")
        self.op.jwks_keys = [jwk]
        response = self.sign_in(APIClient(), provider, {"roles": ["staff"]}, key=key, alg="EdDSA", kid="okp1")
        self.assertIsNone(sso_error(response), response["Location"])

    def test_test_action_reports_private_jwk(self):
        provider = self.make_flow_provider()
        self.op.jwks_keys = [public_jwk(keys()["rsa"], "rsa1"), private_jwk(keys()["ec"], "ec1")]
        client, _ = admin_client()
        response = client.post(f"{PROVIDERS}{provider.pk}/test/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn(
            "jwks_private_key", response.json()["problems"],
            "the test action called a JWKS carrying a private key fine",
        )
        self.assertFalse(response.json()["ok"])


class DiscoveryEndpointCharacterTests(FlowTestCase):
    """Every endpoint the discovery document names is printable ASCII, checked before caching."""

    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_start_refuses_surrogate_in_authorization_endpoint(self):
        self.op.discovery_extra = {"authorization_endpoint": self.op.issuer + "/authorize\ud800"}
        response = APIClient(raise_request_exception=False).get(f"/api/accounts/oidc/{self.provider.slug}/start/")
        self.assertEqual(
            response.status_code, 302,
            f"start answered {response.status_code} to a surrogate in authorization_endpoint",
        )
        self.assertEqual(sso_error(response), "provider_unavailable", response["Location"])
        self.assertIsNone(
            cache.get(discovery.discovery_cache_key(self.provider)),
            "a discovery document with an unencodable endpoint was cached",
        )

    def test_link_start_refuses_surrogate_in_authorization_endpoint(self):
        self.op.discovery_extra = {"authorization_endpoint": self.op.issuer + "/authorize?x=\ud800"}
        client, _ = admin_client()
        client.raise_request_exception = False
        response = client.post(
            f"/api/accounts/oidc/{self.provider.slug}/link/start/", {"next": "/users"}, format="json"
        )
        self.assertEqual(
            response.status_code, 502,
            f"link/start answered {response.status_code} to a surrogate in authorization_endpoint",
        )
        self.assertEqual(response.json()["code"], "provider_unavailable")

    def test_every_endpoint_must_be_printable_ascii(self):
        cases = {
            "authorization_endpoint": ["/authorize\r\nX: y", "/author ize", "/authorize\x00", "/authorizé"],
            "token_endpoint": ["/token\ud800", "/to ken"],
            "jwks_uri": ["/jwks\x7f", "/jwks "],
        }
        for field, suffixes in cases.items():
            for suffix in suffixes:
                with self.subTest(field=field, value=ascii(suffix)):
                    self.op.discovery_extra = {field: self.op.issuer + suffix}
                    with self.assertRaises(discovery.DiscoveryError) as caught:
                        discovery.fetch_discovery(self.provider)
                    self.assertEqual(caught.exception.code, "discovery_endpoint_invalid")

    def test_test_action_reports_invalid_endpoint(self):
        self.op.discovery_extra = {"authorization_endpoint": self.op.issuer + "/authorize\ud800"}
        client, _ = admin_client()
        response = client.post(f"{PROVIDERS}{self.provider.pk}/test/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["problems"], ["discovery_endpoint_invalid"])


UNEXPECTED_TEXT = "unexpected-" + "c0ffee5eed"


def explode(*args, **kwargs):
    """Stands in for any step raising an exception type nobody enumerated."""
    raise KeyError(UNEXPECTED_TEXT)


class LastResortTests(FlowTestCase):
    """Each entry point answers its fixed refusal for an unenumerated exception, and says so
    at ERROR with the class and the innermost frame only."""

    FRAME = f"{__name__}:explode:"

    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def assertLoggedLoudly(self, logs, captured, stage):
        lines = [r.getMessage() for r in logs.records if r.levelno == logging.ERROR]
        self.assertEqual(len(lines), 1, logs.output)
        line = lines[0]
        self.assertIn(flow.UNEXPECTED_MARKER, line)
        self.assertIn(f"OIDC {stage} ", line)
        self.assertIn("KeyError", line)
        self.assertIn(self.FRAME, line, f"the innermost frame is not named: {line}")
        for record in logs.records:
            self.assertIsNone(record.exc_info, "a traceback was logged")
        everything = " ".join(logs.output) + " ".join(text for _, text in captured)
        self.assertNotIn(UNEXPECTED_TEXT, everything, "the exception's message reached a log")

    def test_callback(self):
        client = APIClient(raise_request_exception=False)
        url = self.start(client, self.provider)
        params = self.op.authorize(url, {"roles": ["staff"]})
        with self.assertLogs("apps.accounts.oidc.flow", "DEBUG") as logs, capture_all_logs() as captured:
            with mock.patch.object(flow.validate, "validate_id_token", side_effect=explode):
                response = self.callback(client, self.provider, params)
        self.assertEqual(
            response.status_code, 302, f"an unenumerated exception answered {response.status_code}"
        )
        self.assertEqual(sso_error(response), "provider_unavailable", response["Location"])
        self.assertLoggedLoudly(logs, captured, "callback")
        event = SystemEvent.objects.filter(event_type="login_failed").latest("id")
        self.assertEqual(event.details.get("unexpected"), flow.UNEXPECTED_MARKER)

    def test_start(self):
        client = APIClient(raise_request_exception=False)
        with self.assertLogs("apps.accounts.oidc.flow", "DEBUG") as logs, capture_all_logs() as captured:
            with mock.patch.object(flow, "safe_next", side_effect=explode):
                response = client.get(f"/api/accounts/oidc/{self.provider.slug}/start/")
        self.assertEqual(
            response.status_code, 302, f"an unenumerated exception answered {response.status_code}"
        )
        self.assertEqual(sso_error(response), "provider_unavailable", response["Location"])
        self.assertLoggedLoudly(logs, captured, "start")

    def test_link_start(self):
        client, _ = admin_client()
        client.raise_request_exception = False
        with self.assertLogs("apps.accounts.oidc.flow", "DEBUG") as logs, capture_all_logs() as captured:
            with mock.patch.object(flow, "safe_next", side_effect=explode):
                response = client.post(
                    f"/api/accounts/oidc/{self.provider.slug}/link/start/", {"next": "/users"}, format="json"
                )
        self.assertEqual(
            response.status_code, 502, f"an unenumerated exception answered {response.status_code}"
        )
        self.assertEqual(response.json()["code"], "provider_unavailable")
        self.assertLoggedLoudly(logs, captured, "link_start")


class ProvisioningSqlstateTests(FlowTestCase):
    def test_provisioning_failed_logs_the_sqlstate(self):
        import psycopg

        def deadlock(*args, **kwargs):
            try:
                raise psycopg.errors.DeadlockDetected("detail " + UNEXPECTED_TEXT)
            except psycopg.Error as exc:
                raise OperationalError("deadlock " + UNEXPECTED_TEXT) from exc

        provider = self.make_flow_provider()
        with self.assertLogs("apps.accounts.oidc.flow", "WARNING") as logs:
            with mock.patch.object(provisioning, "resolve", side_effect=deadlock):
                response = self.sign_in(APIClient(raise_request_exception=False), provider, {"roles": ["staff"]})
        self.assertEqual(sso_error(response), "provisioning_failed")
        text = " ".join(logs.output)
        self.assertIn("OperationalError sqlstate=40P01", text, f"no SQLSTATE in: {text}")
        self.assertNotIn(UNEXPECTED_TEXT, text)

    def test_sqlstate_refuses_anything_but_a_five_character_code(self):
        class Fake(Exception):
            pass

        for value, expected in (("40P01", "40P01"), ("4OP01x", None), ("40 01", None), (None, None), (5, None)):
            cause = Fake()
            cause.sqlstate = value
            exc = OperationalError("x")
            exc.__cause__ = cause
            with self.subTest(value=value):
                self.assertEqual(flow.sqlstate(exc), expected)


class RefreshOwnerTests(FlowTestCase):
    """Spec 5.4: an identity that now belongs to another user refuses the refresh."""

    def test_identity_of_another_user_refuses_refresh(self):
        provider = self.make_flow_provider()
        body = self.login(APIClient(), provider, {"roles": ["staff"], "preferred_username": "u"})
        other = User.objects.create_user(username="other", user_level=1)
        OIDCIdentity.objects.update(user=other)
        # A version bump so refresh re-evaluates; the mapping still grants u's level.
        bump_mappings(provider, [{"value": "staff", "user_level": 1}])
        response = self.refresh(body["refresh"])
        self.assertEqual(
            response.status_code, 401,
            f"a refresh was re-evaluated against an identity owned by another user: {response.status_code}",
        )
