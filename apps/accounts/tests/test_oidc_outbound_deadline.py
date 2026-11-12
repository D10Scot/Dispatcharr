"""The whole OIDC outbound exchange is bounded by ``discovery.TOTAL_DEADLINE`` under gevent.

``discovery.run_bounded`` arms one ``gevent.Timeout`` around discovery, JWKS and the token
POST when gevent has monkey-patched ``socket`` (the uWSGI API workers). Two groups:

- ``RealSocketDeadlineTests`` runs each call site in a child interpreter that monkey-patches
  first, as uWSGI's ``gevent-early-monkey-patch`` does, against a real socket server in this
  process that drips the response headers, or a gzip body, a byte at a time inside the
  per-read timeout. The timer interrupts a real blocking read; nothing is mocked. The same
  child run without patching shows the fallback that is left: no whole-exchange bound.
- ``DeadlineMappingTests`` runs in this process through the real views, with the detection
  forced on and the request replaced by a cooperative wait (``gevent.sleep``) that the real
  timer interrupts. It pins that each site answers its existing fixed code, by its own
  handler and never the flow's last resort, and that a fast exchange leaves no timer armed.
"""

import gzip
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest import mock

import gevent
import requests
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.oidc import discovery

from .oidc_flow_support import FlowTestCase, capture_all_logs, sso_error
from .oidc_support import PROVIDERS, admin_client

REPO_ROOT = Path(__file__).resolve().parents[3]

CHILD_DEADLINE = 1.5  # TOTAL_DEADLINE inside the child, seconds
DRIP_INTERVAL = 0.1  # one byte per interval: far inside the 10 s read timeout
DRIP_TOTAL = 8.0  # how long the server keeps dripping before it gives up
MARGIN = 2.0  # deadline + MARGIN is the most a bounded call may take on a loaded machine
CHILD_TIMEOUT = 120

CHILD = r"""
import sys
mode, site, port, deadline = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
if mode == "gevent":
    import gevent.monkey
    gevent.monkey.patch_all()

import json, time
import django
django.setup()
from django.conf import settings
settings.OIDC_ALLOW_HTTP = True

from apps.accounts.models import OIDCProvider
from apps.accounts.oidc import client_auth, discovery

discovery.TOTAL_DEADLINE = deadline
base = f"http://127.0.0.1:{port}/op"
provider = OIDCProvider(
    issuer=base, client_id="c", client_auth_method="client_secret_post", allow_private_network=False
)
# The token site's credential is not what is under test: no key material in the child.
client_auth.client_authentication = lambda provider, endpoint: ({"client_id": "c"}, {})

outcome = "ok"
started = time.monotonic()
try:
    if site in ("discovery", "fast"):
        discovery.fetch_discovery(provider)
    elif site == "jwks":
        discovery.fetch_jwks(provider, {"jwks_uri": base + "/jwks"})
    elif site == "token":
        client_auth.exchange_code(
            provider, {"token_endpoint": base + "/token"},
            code="c", redirect_uri="https://mino.example/cb", code_verifier="v",
        )
except discovery.DiscoveryError as exc:
    outcome = exc.code
except client_auth.TokenExchangeFailed as exc:
    outcome = exc.code
elapsed = time.monotonic() - started
late = None
if site == "fast":
    # Sleep past the deadline: an armed timer would fire into this greenlet now.
    try:
        time.sleep(deadline * 2)
    except BaseException as exc:
        late = type(exc).__name__
print(json.dumps({
    "outcome": outcome, "elapsed": elapsed, "late": late,
    "patched": discovery._gevent_socket_patched(),
}))
"""

class DripServer:
    """A one-thread HTTP server on 127.0.0.1 that answers every request the same way.

    ``headers``: the status line and endless header lines, one byte per ``DRIP_INTERVAL``.
    ``gzip``: complete headers, then a gzip body one byte per ``DRIP_INTERVAL``.
    ``fast``: a valid discovery document at once.
    Either drip stops after ``DRIP_TOTAL`` and closes the connection.
    """

    def __init__(self, mode):
        self.mode = mode
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        try:
            self.sock.close()
        except OSError:
            pass
        self.thread.join(DRIP_TOTAL + 5)

    def _serve(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    @staticmethod
    def _read_request(conn):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        length = 0
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1])
        while len(rest) < length:
            chunk = conn.recv(4096)
            if not chunk:
                return
            rest += chunk

    def _drip(self, conn, payload):
        ends = time.monotonic() + DRIP_TOTAL
        for byte in payload:
            if self.stop.is_set() or time.monotonic() > ends:
                return
            conn.sendall(bytes([byte]))
            time.sleep(DRIP_INTERVAL)

    def _handle(self, conn):
        try:
            conn.settimeout(DRIP_TOTAL + 5)
            self._read_request(conn)
            if self.mode == "fast":
                issuer = f"http://127.0.0.1:{self.port}/op"
                body = json.dumps({
                    "issuer": issuer,
                    "authorization_endpoint": issuer + "/authorize",
                    "token_endpoint": issuer + "/token",
                    "jwks_uri": issuer + "/jwks",
                }).encode()
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                    + body
                )
            elif self.mode == "headers":
                self._drip(conn, b"HTTP/1.1 200 OK\r\n" + b"X-Pad: aaaaaaaaaaaaaaaa\r\n" * 1000)
            elif self.mode == "gzip":
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    b"Content-Encoding: gzip\r\nConnection: close\r\n\r\n"
                )
                body = gzip.compress(json.dumps({"pad": os.urandom(4096).hex()}).encode())
                self._drip(conn, body)
        except OSError:
            pass  # the client went away: the bounded case
        finally:
            conn.close()


def run_child(mode, site, server_mode):
    server = DripServer(server_mode)
    try:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
        result = subprocess.run(
            [sys.executable, "-c", CHILD, mode, site, str(server.port), str(CHILD_DEADLINE)],
            cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
            timeout=CHILD_TIMEOUT, check=False,
        )
    finally:
        server.close()
    lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    if result.returncode != 0 or not lines:
        raise AssertionError(
            f"child {mode}/{site} exited {result.returncode}; stderr tail:\n{result.stderr[-3000:]}"
        )
    return json.loads(lines[-1])


class RealSocketDeadlineTests(FlowTestCase):
    """A real blocking read on a real socket, interrupted by the real gevent timer."""

    def assert_bounded(self, site, server_mode, code):
        out = run_child("gevent", site, server_mode)
        self.assertTrue(out["patched"], "the child was not monkey-patched")
        self.assertLess(
            out["elapsed"], CHILD_DEADLINE + MARGIN,
            f"{site} against a {server_mode} drip took {out['elapsed']:.2f} s under gevent; "
            f"the whole-exchange deadline is {CHILD_DEADLINE} s (answered {out['outcome']!r})",
        )
        self.assertGreaterEqual(out["elapsed"], CHILD_DEADLINE * 0.9, out)
        self.assertEqual(out["outcome"], code, out)

    def test_discovery_dripped_headers(self):
        self.assert_bounded("discovery", "headers", "discovery_unreachable")

    def test_discovery_dripped_gzip_body(self):
        self.assert_bounded("discovery", "gzip", "discovery_unreachable")

    def test_jwks_dripped_headers(self):
        self.assert_bounded("jwks", "headers", "jwks_unreachable")

    def test_token_dripped_headers(self):
        self.assert_bounded("token", "headers", "token_exchange_failed")

    def test_token_dripped_gzip_body(self):
        self.assert_bounded("token", "gzip", "token_exchange_failed")

    def test_without_gevent_dripped_headers_are_not_bounded(self):
        """The documented fallback: no whole-exchange bound outside gevent. If this starts
        failing because the call returned early, the comment at TOTAL_DEADLINE is stale."""
        out = run_child("plain", "discovery", "headers")
        self.assertFalse(out["patched"])
        self.assertGreater(out["elapsed"], DRIP_TOTAL * 0.8, out)

    def test_fast_response_unaffected_and_no_timer_left_armed(self):
        out = run_child("gevent", "fast", "fast")
        self.assertEqual(out["outcome"], "ok", out)
        self.assertLess(out["elapsed"], CHILD_DEADLINE, out)
        self.assertIsNone(out["late"], f"a timer fired after the call returned: {out['late']}")


def _cooperative_hang(*args, **kwargs):
    """A request that never answers, waiting the way a monkey-patched socket read waits."""
    gevent.sleep(60)
    raise AssertionError("the deadline never interrupted the request")


@override_settings(OIDC_ALLOW_HTTP=True)
class DeadlineMappingTests(FlowTestCase):
    """Each site answers its existing fixed code when the whole-exchange timer fires."""

    DEADLINE = 0.5

    def setUp(self):
        super().setUp()
        p1 = mock.patch.object(discovery, "_gevent_socket_patched", return_value=True)
        p2 = mock.patch.object(discovery, "TOTAL_DEADLINE", self.DEADLINE)
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def hang_fetch(self, which):
        """``fetch_outbound_http`` that hangs for URLs ending in ``which``, real otherwise."""
        real = discovery.fetch_outbound_http

        def fetch(url, **kwargs):
            if url.endswith(which):
                return _cooperative_hang()
            return real(url, **kwargs)

        return mock.patch.object(discovery, "fetch_outbound_http", side_effect=fetch)

    def assert_deadline_logged(self, logs, label):
        expected = f"OIDC {label} exchange exceeded its total deadline"
        self.assertIn(
            expected, [text for _, text in logs],
            f"the deadline handler did not answer; logged: {[t for _, t in logs if 'OIDC' in t]}",
        )

    def timed(self, fn):
        started = time.monotonic()
        value = fn()
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, self.DEADLINE + 5, f"took {elapsed:.2f} s")
        return value

    def test_discovery_on_start(self):
        provider = self.make_flow_provider()
        with self.hang_fetch("/openid-configuration"), capture_all_logs() as logs:
            response = self.timed(lambda: APIClient().get(f"/api/accounts/oidc/{provider.slug}/start/"))
        self.assertEqual(sso_error(response), "provider_unavailable", response["Location"])
        self.assert_deadline_logged(logs, "discovery")

    def test_discovery_on_admin_test(self):
        client, _ = admin_client()
        provider = self.make_flow_provider()
        with self.hang_fetch("/openid-configuration"), capture_all_logs() as logs:
            result = self.timed(lambda: client.post(f"{PROVIDERS}{provider.pk}/test/").json())
        self.assertEqual(result["problems"], ["discovery_unreachable"])
        self.assert_deadline_logged(logs, "discovery")

    def test_jwks_on_admin_test(self):
        client, _ = admin_client()
        provider = self.make_flow_provider()
        with self.hang_fetch("/jwks"), capture_all_logs() as logs:
            result = self.timed(lambda: client.post(f"{PROVIDERS}{provider.pk}/test/").json())
        self.assertEqual(result["problems"], ["jwks_unreachable"])
        self.assert_deadline_logged(logs, "jwks")

    def test_jwks_on_callback(self):
        provider = self.make_flow_provider()
        client = APIClient()
        url = self.start(client, provider)
        params = self.op.authorize(url, {"roles": ["staff"]})
        with self.hang_fetch("/jwks"), capture_all_logs() as logs:
            response = self.timed(lambda: self.callback(client, provider, params))
        self.assertEqual(sso_error(response), "id_token_invalid", response["Location"])
        self.assert_deadline_logged(logs, "jwks")

    def test_token_on_callback(self):
        provider = self.make_flow_provider()
        client = APIClient()
        url = self.start(client, provider)
        params = self.op.authorize(url, {"roles": ["staff"]})
        with mock.patch.object(requests, "post", side_effect=_cooperative_hang), \
                capture_all_logs() as logs:
            response = self.timed(lambda: self.callback(client, provider, params))
        self.assertEqual(sso_error(response), "token_exchange_failed", response["Location"])
        self.assert_deadline_logged(logs, "token")

    def test_fast_exchange_leaves_no_timer(self):
        client, _ = admin_client()
        provider = self.make_flow_provider()
        result = client.post(f"{PROVIDERS}{provider.pk}/test/").json()
        self.assertEqual(result["problems"], [])
        # Any timer left armed would fire into this greenlet during the sleep.
        gevent.sleep(self.DEADLINE * 3)
