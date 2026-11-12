"""Shared helpers for the OIDC tests (SSO spec PR S1).

Secrets here are obvious sentinels. Key pairs are generated at runtime; no PEM is committed.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rest_framework.test import APIClient

from apps.accounts.models import OIDCProvider, User
from apps.accounts.oidc import redirect
from apps.accounts.oidc import secrets as oidc_secrets
from core.models import AUTH_SETTINGS_KEY, CoreSettings

SECRET_SENTINEL = "SENTINEL-CLIENT-SECRET-7f3a"
TENANT = "11111111-2222-3333-4444-555555555555"

PROVIDERS = "/api/accounts/oidc/providers-admin/"
SETTINGS = "/api/accounts/oidc/settings/"
IDENTITIES = "/api/accounts/oidc/identities/"
CORE_SETTINGS = "/api/core/settings/"


def admin_client(username="admin"):
    user = User.objects.create_user(
        username=username, password="testpass123", user_level=User.UserLevel.ADMIN
    )
    client = APIClient()
    client.force_authenticate(user)
    return client, user


def standard_client(username="standard"):
    user = User.objects.create_user(
        username=username, password="testpass123", user_level=User.UserLevel.STANDARD
    )
    client = APIClient()
    client.force_authenticate(user)
    return client, user


def set_auth_settings(**values):
    """Set the auth_settings row explicitly: TransactionTestCase flushes the seeded one."""
    value = {"public_base_url": "", "password_login_enabled": True}
    value.update(values)
    CoreSettings.objects.update_or_create(
        key=AUTH_SETTINGS_KEY, defaults={"name": "Authentication Settings", "value": value}
    )


def make_provider(**overrides):
    fields = dict(
        slug="p1",
        display_name="Provider One",
        kind="generic",
        enabled=False,
        issuer="https://idp.example/realms/x",
        client_id="client-1",
        client_auth_method="client_secret_basic",
        client_secret_encrypted=oidc_secrets.encrypt(SECRET_SENTINEL),
        claim_path="roles",
        mappings=[{"value": "admins", "user_level": 10}],
    )
    fields.update(overrides)
    return OIDCProvider.objects.create(**fields)


def make_entra(**overrides):
    fields = dict(
        slug="entra",
        display_name="Entra",
        kind="entra",
        entra_tenant_id=TENANT,
        issuer=f"https://login.microsoftonline.com/{TENANT}/v2.0",
        client_auth_method="client_secret_post",
        client_assertion_alg="PS256",
    )
    fields.update(overrides)
    return make_provider(**fields)


def base_url_for(target_len, slug):
    """An https base URL that makes ``redirect_uri(base, slug)`` exactly ``target_len`` long."""
    fixed = len(redirect.redirect_uri("https://.example.com", slug))
    pad = target_len - fixed
    assert pad > 0
    base = "https://" + "a" * pad + ".example.com"
    assert len(redirect.redirect_uri(base, slug)) == target_len
    return base


class _FakeRaw:
    """The slice of urllib3's ``HTTPResponse`` the limited reader uses."""

    def __init__(self, body):
        self._body = body
        self._pos = 0

    def read1(self, amt=8192, decode_content=True):
        chunk = self._body[self._pos : self._pos + amt]
        self._pos += len(chunk)
        return chunk


class FakeResponse:
    """Stands in for ``requests.Response`` where the SSRF policy is under test."""

    def __init__(self, body, status_code=200):
        self.status_code = status_code
        self.headers = {}
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.raw = _FakeRaw(self._body)

    def close(self):
        pass


class FakeOP:
    """An in-process OP on 127.0.0.1 serving canned discovery/JWKS documents."""

    def __init__(self):
        self.routes = {}
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.requests.append(self.path)
                status, headers, body = outer.routes.get(self.path, (404, {}, b"{}"))
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def reset(self):
        self.routes.clear()
        self.requests.clear()

    def json(self, path, doc, status=200):
        self.routes[path] = (status, {"Content-Type": "application/json"}, json.dumps(doc).encode())

    def raw(self, path, body, status=200, headers=None):
        self.routes[path] = (status, headers or {}, body)

    def serve_provider(self, issuer_path="/realms/x", *, issuer=None, jwks_keys=None):
        """Serve a well-formed discovery document and a JWKS (entries carry no ``alg``)."""
        stripped = issuer_path[:-1] if issuer_path.endswith("/") else issuer_path
        doc_issuer = issuer if issuer is not None else self.base + issuer_path
        self.json(
            stripped + "/.well-known/openid-configuration",
            {
                "issuer": doc_issuer,
                "authorization_endpoint": self.base + stripped + "/auth",
                "token_endpoint": self.base + stripped + "/token",
                "jwks_uri": self.base + stripped + "/jwks",
            },
        )
        keys = jwks_keys if jwks_keys is not None else [
            {"kty": "RSA", "kid": "k1", "use": "sig", "n": "AQAB", "e": "AQAB"}
        ]
        self.json(stripped + "/jwks", {"keys": keys})
