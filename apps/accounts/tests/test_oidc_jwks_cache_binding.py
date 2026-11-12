"""A cached JWKS is served only for the ``jwks_uri`` and issuer it was fetched for.

The cache key is ``oidc:jwks:<pk>:<version>``. A database restored or reset under a Redis
that kept its keys can give this provider the (pk, version) another provider's entry was
written under; served as-is, the login would validate ID tokens against that provider's
signing keys. ``get_jwks`` treats an entry bound to a different ``jwks_uri`` or issuer, or
one in the unbound shape written before the binding, as a miss and refetches.
"""

from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.oidc import discovery

from .oidc_flow_support import FlowTestCase, keys, public_jwk, sso_error

FOREIGN_JWKS = {"keys": [public_jwk(keys()["other_rsa"], "rsa1")]}


class JwksCacheBindingTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()
        self.key = discovery.jwks_cache_key(self.provider)

    def jwks_fetches(self):
        return [path for path in self.op.gets if path.endswith("/jwks")]

    def sign_in_with(self, signing_key, username):
        client = APIClient()
        url = self.start(client, self.provider)
        params = self.op.authorize(
            url, {"roles": ["staff"], "preferred_username": username}, key=signing_key, kid="rsa1"
        )
        return self.callback(client, self.provider, params)

    def test_entry_bound_to_another_jwks_uri_is_refetched(self):
        cache.set(self.key, {
            "jwks_uri": "https://other-idp.example/keys",
            "issuer": self.provider.issuer,
            "jwks": FOREIGN_JWKS,
        }, 3600)
        # A token signed with the foreign key: accepted only if the foreign keys are served.
        forged = self.sign_in_with(keys()["other_rsa"], "forged")
        self.assertEqual(
            sso_error(forged), "id_token_invalid",
            "the login validated against the wrong keys: a JWKS cached for another "
            f"jwks_uri was served (answered {forged['Location']})",
        )
        self.assertFalse(User.objects.filter(username="forged").exists())
        self.assertEqual(len(self.jwks_fetches()), 1, "the mismatched entry was not refetched")
        # The refetched, bound entry now serves the genuine key.
        genuine = self.sign_in_with(None, "genuine")
        self.assertIsNone(sso_error(genuine), genuine["Location"])
        self.assertEqual(len(self.jwks_fetches()), 1)

    def test_entry_bound_to_another_issuer_is_refetched(self):
        cache.set(self.key, {
            "jwks_uri": self.op.issuer + "/jwks",
            "issuer": "https://other-idp.example",
            "jwks": FOREIGN_JWKS,
        }, 3600)
        forged = self.sign_in_with(keys()["other_rsa"], "forged")
        self.assertEqual(
            sso_error(forged), "id_token_invalid",
            "the login validated against the wrong keys: a JWKS cached for another issuer was served",
        )
        self.assertEqual(len(self.jwks_fetches()), 1)

    def test_unbound_old_shape_entry_is_refetched(self):
        cache.set(self.key, FOREIGN_JWKS, 3600)
        genuine = self.sign_in_with(None, "genuine")
        self.assertIsNone(sso_error(genuine), genuine["Location"])
        self.assertEqual(len(self.jwks_fetches()), 1, "the old-shape entry was served, not refetched")
        self.assertEqual(cache.get(self.key)["jwks_uri"], self.op.issuer + "/jwks")

    def test_matching_entry_is_served_with_no_fetch(self):
        genuine_jwks = {"keys": list(self.op.jwks_keys)}
        cache.set(self.key, {
            "jwks_uri": self.op.issuer + "/jwks",
            "issuer": self.provider.issuer,
            "jwks": genuine_jwks,
        }, 3600)
        response = self.sign_in_with(None, "genuine")
        self.assertIsNone(sso_error(response), response["Location"])
        self.assertEqual(self.jwks_fetches(), [], "a matching cached JWKS was refetched")

    def test_fetch_stores_the_binding(self):
        self.sign_in_with(None, "genuine")
        entry = cache.get(self.key)
        self.assertEqual(
            entry,
            {"jwks_uri": self.op.issuer + "/jwks", "issuer": self.provider.issuer,
             "jwks": {"keys": list(self.op.jwks_keys)}},
        )
