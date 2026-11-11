"""An in-process fake OpenID provider and flow helpers for the OIDC flow tests (SSO spec PR S2).

The OP is an ``http.server`` thread on 127.0.0.1, so the test classes run with
``OIDC_ALLOW_HTTP`` on. Like Entra, its JWKS entries carry no ``alg`` and its discovery
document has neither ``code_challenge_methods_supported`` nor
``authorization_response_iss_parameter_supported`` unless a test turns the latter on. Its
token endpoint REQUIRES a valid PKCE ``code_verifier`` all the same, and checks the client's
credential.

Key pairs are generated at runtime (once per process); no PEM is committed. ID tokens are
issued with PyJWT by ``FlowOP.authorize``, which stands in for the user approving at the IdP.
"""

import base64
import hashlib
import json
import logging
import secrets
import threading
from contextlib import contextmanager
import time
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote_plus, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User

from .oidc_support import SECRET_SENTINEL, make_provider, set_auth_settings

BASE = "https://mino.example.com"
CLIENT_ID = "mino-client"
EXCHANGE = "/api/accounts/oidc/exchange/"
REFRESH = "/api/accounts/token/refresh/"
ME = "/api/accounts/users/me/"
DEFAULT_MAPPINGS = [
    {"value": "admins", "user_level": 10},
    {"value": "staff", "user_level": 1},
    {"value": "viewers", "user_level": 0},
]
JOIN_TIMEOUT = 10
WAIT_TIMEOUT = 5


@lru_cache(maxsize=None)
def keys():
    """Runtime-generated signing keys: the OP's RSA and EC keys, and an unrelated RSA key."""
    return {
        "rsa": rsa.generate_private_key(public_exponent=65537, key_size=2048),
        "ec": ec.generate_private_key(ec.SECP256R1()),
        "other_rsa": rsa.generate_private_key(public_exponent=65537, key_size=2048),
    }


def public_jwk(private_key, kid):
    """A JWK with no ``alg`` member, the way Entra publishes them."""
    if isinstance(private_key, rsa.RSAPrivateKey):
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    else:
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private_key.public_key()))
    jwk = {k: v for k, v in jwk.items() if k not in ("alg", "key_ops")}
    jwk.update({"kid": kid, "use": "sig"})
    return jwk


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class FlowOP:
    """The fake OP. ``authorize`` mints a code; the token endpoint redeems it once."""

    def __init__(self, path="/op"):
        self.path = path
        self.lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status, body):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):  # noqa: N802
                outer.gets.append(self.path)
                if self.path == outer.path + "/.well-known/openid-configuration":
                    return self._send(200, outer.discovery_document())
                if self.path == outer.path + "/jwks":
                    return self._send(200, {"keys": list(outer.jwks_keys)})
                return self._send(404, {})

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8")
                form = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
                status, body = outer.handle_token(dict(self.headers), form, raw)
                self._send(status, body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.reset()

    # ---- lifecycle -------------------------------------------------------------------

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    @property
    def issuer(self):
        return self.base + self.path

    @property
    def token_endpoint(self):
        return self.issuer + "/token"

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def reset(self):
        self.gets = []
        self.token_requests = []
        self.codes = {}
        self.discovery_extra = {}
        self.issuer_override = None
        self.token_response = None
        self.expected_client_id = CLIENT_ID
        self.expected_secret = SECRET_SENTINEL
        self.assertion_key = None
        self.jwks_keys = [public_jwk(keys()["rsa"], "rsa1"), public_jwk(keys()["ec"], "ec1")]

    # ---- documents ---------------------------------------------------------------------

    def discovery_document(self):
        doc = {
            "issuer": self.issuer_override or self.issuer,
            "authorization_endpoint": self.issuer + "/authorize",
            "token_endpoint": self.token_endpoint,
            "jwks_uri": self.issuer + "/jwks",
        }
        doc.update(self.discovery_extra)
        return doc

    # ---- the user approving at the IdP -------------------------------------------------

    def authorize(
        self,
        authorize_url,
        claims=None,
        *,
        drop=(),
        key=None,
        alg="RS256",
        kid="rsa1",
        headers=None,
        iss_param=None,
        raw_token=None,
    ):
        """Return the callback query (``code``, ``state``, optional ``iss``) for this request.

        The ID token carries the request's nonce and the client id as ``aud`` unless a claim
        overrides them.
        """
        query = {k: v[0] for k, v in parse_qs(urlsplit(authorize_url).query).items()}
        now = int(time.time())
        payload = {
            "iss": self.issuer,
            "aud": query["client_id"],
            "sub": "subject-1",
            "iat": now,
            "exp": now + 300,
            "nonce": query["nonce"],
        }
        payload.update(claims or {})
        for name in drop:
            payload.pop(name, None)
        if raw_token is not None:
            id_token = raw_token
        else:
            signing_key = keys()["rsa"] if key is None else key
            hdrs = {"kid": kid} if kid is not None else {}
            hdrs.update(headers or {})
            id_token = jwt.encode(payload, signing_key, algorithm=alg, headers=hdrs)
        code = secrets.token_urlsafe(24)
        with self.lock:
            self.codes[code] = {
                "challenge": query["code_challenge"],
                "method": query.get("code_challenge_method"),
                "id_token": id_token,
            }
        params = {"code": code, "state": query["state"]}
        if iss_param is not None:
            params["iss"] = iss_param
        return params

    # ---- the token endpoint ------------------------------------------------------------

    def _client_ok(self, headers, form):
        auth = headers.get("Authorization")
        if auth and auth.startswith("Basic "):
            # Latin-1 never fails: a client that sent raw non-ASCII is refused, not crashed.
            decoded = base64.b64decode(auth[6:]).decode("latin-1")
            raw_id, _, raw_secret = decoded.partition(":")
            return (
                unquote_plus(raw_id) == self.expected_client_id
                and unquote_plus(raw_secret) == self.expected_secret
            )
        if "client_assertion" in form:
            if self.assertion_key is None:
                return True
            try:
                jwt.decode(
                    form["client_assertion"],
                    self.assertion_key,
                    algorithms=["PS256", "RS256"],
                    audience=self.token_endpoint,
                )
            except jwt.PyJWTError:
                return False
            return form.get("client_id") == self.expected_client_id
        return (
            form.get("client_id") == self.expected_client_id
            and form.get("client_secret") == self.expected_secret
        )

    def handle_token(self, headers, form, raw):
        self.token_requests.append({"headers": headers, "form": form, "raw": raw})
        if self.token_response is not None:
            return self.token_response
        with self.lock:
            entry = self.codes.pop(form.get("code"), None)
        if entry is None:
            return 400, {"error": "invalid_grant"}
        verifier = form.get("code_verifier") or ""
        if entry["method"] != "S256" or b64url(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ) != entry["challenge"]:
            return 400, {"error": "invalid_grant"}
        if not self._client_ok(headers, form):
            return 401, {"error": "invalid_client"}
        return 200, {"id_token": entry["id_token"], "access_token": "at", "token_type": "Bearer"}


def query_of(location):
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


def fragment_code(location):
    fragment = urlsplit(location).fragment
    assert fragment.startswith("code="), location
    return fragment[len("code="):]


def sso_error(response):
    """The ``sso_error`` of a refusal redirect, or None for the handoff redirect."""
    location = response["Location"]
    if "/login/sso#code=" in location:
        return None
    return query_of(location).get("sso_error")


def decode_unverified(token):
    return jwt.decode(token, options={"verify_signature": False})


class FlowMixin:
    """Shared fixtures: one OP per class, a fresh cache and ``auth_settings`` per test."""

    base_url = BASE

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.op = FlowOP()
        cls.op.start()
        cls.addClassCleanup(cls.op.stop)

    def setUp(self):
        super().setUp()
        cache.clear()  # the oidc throttle and the discovery/JWKS caches
        self.op.reset()
        set_auth_settings(public_base_url=self.base_url)

    def make_flow_provider(self, **overrides):
        fields = dict(
            slug="p1",
            enabled=True,
            issuer=self.op.issuer,
            client_id=CLIENT_ID,
            client_auth_method="client_secret_post",
            claim_path="roles",
            mappings=DEFAULT_MAPPINGS,
        )
        fields.update(overrides)
        return make_provider(**fields)

    # ---- the browser half --------------------------------------------------------------

    def start(self, client, provider, next_path=None):
        url = f"/api/accounts/oidc/{provider.slug}/start/"
        response = client.get(url, {"next": next_path} if next_path else {})
        self.assertEqual(response.status_code, 302, getattr(response, "content", b""))
        return response["Location"]

    def link_start(self, client, provider, next_path="/users"):
        response = client.post(
            f"/api/accounts/oidc/{provider.slug}/link/start/", {"next": next_path}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["authorize_url"]

    def callback(self, client, provider, params):
        return client.get(f"/api/accounts/oidc/{provider.slug}/callback/", params)

    def sign_in(self, client, provider, claims=None, **authz):
        """start + IdP approval + callback. Returns the callback response."""
        authorize_url = self.start(client, provider)
        return self.callback(client, provider, self.op.authorize(authorize_url, claims, **authz))

    def exchange(self, client, callback_response):
        code = fragment_code(callback_response["Location"])
        return client.post(EXCHANGE, {"code": code}, format="json")

    def login(self, client, provider, claims=None, **authz):
        """The whole flow; asserts success and returns the exchange body."""
        response = self.sign_in(client, provider, claims, **authz)
        self.assertIsNone(sso_error(response), response["Location"])
        exchanged = self.exchange(client, response)
        self.assertEqual(exchanged.status_code, 200, exchanged.content)
        return exchanged.json()

    def refresh(self, refresh_token, client=None):
        return (client or APIClient()).post(REFRESH, {"refresh": refresh_token}, format="json")


@override_settings(OIDC_ALLOW_HTTP=True)
class FlowTestCase(FlowMixin, TestCase):
    pass


@override_settings(OIDC_ALLOW_HTTP=True)
class FlowTransactionTestCase(FlowMixin, TransactionTestCase):
    """Real commits, for the concurrency tests. Threads are joined in ``finally``."""

    def require_postgresql(self, reason="needs PostgreSQL row and advisory locks"):
        if connection.vendor != "postgresql":
            self.skipTest(reason)


class Worker(threading.Thread):
    """Runs ``fn`` on its own DB connection, captures its result or exception, closes the
    connection when done."""

    def __init__(self, fn, name):
        super().__init__(name=name, daemon=True)
        self.fn = fn
        self.result = None
        self.error = None
        self.pid = None

    def run(self):
        from django.db import connection as conn

        try:
            if conn.vendor == "postgresql":
                with conn.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    self.pid = cursor.fetchone()[0]
            self.result = self.fn()
        except BaseException as exc:  # noqa: BLE001 - reported by the test
            self.error = exc
        finally:
            conn.close()


def run_threads(*workers):
    for worker in workers:
        worker.start()


def join_all(workers, events=()):
    """Join each worker with a bounded wait; only then set every event still unset, so a
    failed test cannot hang, and join again.

    The events are not set first: a worker-set event (one thread signalling another) set
    here early would release the waiting thread before its partner acted, and the
    ordering the test exists to force would be lost.
    """
    for worker in workers:
        worker.join(JOIN_TIMEOUT)
    if any(worker.is_alive() for worker in workers):
        for event in events:
            event.set()
        for worker in workers:
            worker.join(JOIN_TIMEOUT)


@contextmanager
def record_resolve_errors():
    """Record the text of every DatabaseError ``provisioning.resolve`` raises, by thread name.

    The callback answers ``provisioning_failed`` for one rather than letting it escape, so a
    test that must tell PostgreSQL's deadlock error from another refusal reads it here.
    """
    from unittest import mock

    from django.db import DatabaseError

    from apps.accounts.oidc import provisioning

    seen = {}
    real = provisioning.resolve

    def wrapper(*args, **kwargs):
        try:
            return real(*args, **kwargs)
        except DatabaseError as exc:
            seen.setdefault(threading.current_thread().name, []).append(repr(exc))
            raise

    with mock.patch.object(provisioning, "resolve", side_effect=wrapper):
        yield seen


def make_admin(username="admin2"):
    return User.objects.create_user(
        username=username, password="testpass123", user_level=User.UserLevel.ADMIN
    )


CAPTURED_LOGGERS = ("apps", "core", "core.utils", "django", "")


class _Recorder(logging.Handler):
    def __init__(self, sink, name):
        super().__init__(level=logging.DEBUG)
        self.sink = sink
        self.logger_name = name

    def emit(self, record):
        try:
            text = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken record is still evidence
            text = str(record.msg)
        if record.exc_info:
            text += "\n" + logging.Formatter().formatException(record.exc_info)
        self.sink.append((record.name, text))


@contextmanager
def capture_all_logs():
    """A recording handler on each configured logger (spec T16), not the root alone.

    ``apps``, ``core.utils`` and ``apps.proxy`` do not propagate, so a root-only capture
    misses them. Not ``assertLogs``: an empty capture is a pass.
    """
    sink = []
    installed = []
    try:
        for name in CAPTURED_LOGGERS:
            target = logging.getLogger(name)
            handler = _Recorder(sink, name or "root")
            installed.append((target, handler, target.level))
            target.addHandler(handler)
            target.setLevel(logging.DEBUG)
        yield sink
    finally:
        for target, handler, level in installed:
            target.removeHandler(handler)
            target.setLevel(level)
