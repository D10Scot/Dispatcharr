"""The whole OIDC outbound exchange is bounded by ``discovery.TOTAL_DEADLINE`` under gevent.

``discovery.run_bounded`` arms one ``gevent.Timeout`` around discovery, JWKS and the token
POST when gevent has monkey-patched ``socket`` (the uWSGI API workers). Three groups:

- ``RealSocketDeadlineTests`` runs every call site in ONE child interpreter that
  monkey-patches first, as uWSGI's ``gevent-early-monkey-patch`` does, against real socket
  servers in this process that drip the response headers, or a gzip body, a byte at a time
  far inside the per-read timeout, and against a name resolver that takes longer than the
  deadline to answer (the SSRF check resolves the host before the request does). The timer
  interrupts a real blocking read; only the resolver's delay is injected. One child for all
  cases keeps the class to a few seconds: Django's set-up is paid once.
- ``UnpatchedFallbackTests`` runs the same dripped exchange in this process, which is not
  monkey-patched, and shows the fallback that is left there: no whole-exchange bound.
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
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import OIDCProvider
from apps.accounts.oidc import discovery

from .oidc_flow_support import FlowTestCase, capture_all_logs, sso_error
from .oidc_support import PROVIDERS, admin_client

REPO_ROOT = Path(__file__).resolve().parents[3]

DEADLINE = 0.5  # TOTAL_DEADLINE for the dripped exchanges, seconds
DRIP_INTERVAL = 0.05  # one byte per interval: 200 times inside the 10 s read timeout
DRIP_TOTAL = 3.0  # how long the server drips before it closes: six deadlines
RESOLVER_DELAY = 3.0  # how long the slow resolver takes to answer: six deadlines
SLOW_HOST = "slow-resolver.test"  # the one name the child's resolver is slow for
MARGIN = 1.0  # DEADLINE + MARGIN is the most a bounded call may take on a loaded machine
CHILD_TIMEOUT = 120

CHILD = r"""
import gevent.monkey
gevent.monkey.patch_all()

import json, sys, time
import django
django.setup()
from django.conf import settings
settings.OIDC_ALLOW_HTTP = True

from apps.accounts.models import OIDCProvider
from apps.accounts.oidc import client_auth, discovery

import logging
import socket
import gevent

spec = json.loads(sys.argv[1])
discovery.TOTAL_DEADLINE = spec["deadline"]
# The token site's credential is not what is under test: no key material in the child.
client_auth.client_authentication = lambda provider, endpoint: ({"client_id": "c"}, {})

# The order in which a site releases its database connection and first resolves the slow
# name, and every log line the discovery module writes, per case.
events = []
logged = []

_real_release = discovery.release_db_connection


def recording_release():
    events.append("release")
    _real_release()


discovery.release_db_connection = recording_release

# gevent's patched getaddrinfo, wrapped: the slow name answers 127.0.0.1 after a
# cooperative wait, as a resolver that is slow to answer does under gevent. Both the SSRF
# check (core/http_security.py) and urllib3's connect look the function up at call time.
_real_getaddrinfo = socket.getaddrinfo


def slow_getaddrinfo(host, *args, **kwargs):
    if host == spec["slow_host"]:
        events.append("resolve")
        gevent.sleep(spec["resolver_delay"])
        host = "127.0.0.1"
    return _real_getaddrinfo(host, *args, **kwargs)


socket.getaddrinfo = slow_getaddrinfo


class Record(logging.Handler):
    def emit(self, record):
        logged.append(record.getMessage())


discovery.logger.addHandler(Record())
discovery.logger.setLevel(logging.INFO)


def run(site, port, host):
    del events[:]
    del logged[:]
    base = f"http://{host}:{port}/op"
    provider = OIDCProvider(
        issuer=base, client_id="c", client_auth_method="client_secret_post",
        allow_private_network=False,
    )
    outcome = "ok"
    started = time.monotonic()
    try:
        if site == "discovery":
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
    result = {
        "outcome": outcome, "elapsed": time.monotonic() - started, "late": None,
        "events": list(events), "logged": list(logged),
    }
    if outcome == "ok":
        # Sleep past the deadline: an armed timer would fire into this greenlet now.
        try:
            time.sleep(spec["deadline"] * 2)
        except BaseException as exc:
            result["late"] = type(exc).__name__
    return result


results = {name: run(site, port, host) for name, site, port, host in spec["cases"]}
print(json.dumps({"patched": discovery._gevent_socket_patched(), "results": results}))
"""


class DripServer:
    """A real HTTP server on 127.0.0.1, one thread per connection, answering every request
    the same way.

    ``headers``: the status line and endless header lines, one byte per ``DRIP_INTERVAL``.
    ``gzip``: complete headers, then a gzip body one byte per ``DRIP_INTERVAL``.
    ``fast``: a valid discovery document at once.
    A drip stops after ``DRIP_TOTAL`` and closes the connection.
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
        self.thread.join(5)

    def _serve(self):
        # A short accept timeout: on Linux closing the listening socket does not wake an
        # accept() blocked in another thread, so close() would otherwise wait out its join.
        self.sock.settimeout(0.05)
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            conn.settimeout(None)
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


# (case name, site, server mode, host, the fixed code the bounded call answers). A case on
# SLOW_HOST waits RESOLVER_DELAY for the name before anything connects; its server is never
# reached when the bound holds.
CASES = [
    ("discovery_headers", "discovery", "headers", "127.0.0.1", "discovery_unreachable"),
    ("discovery_gzip", "discovery", "gzip", "127.0.0.1", "discovery_unreachable"),
    ("jwks_headers", "jwks", "headers", "127.0.0.1", "jwks_unreachable"),
    ("token_headers", "token", "headers", "127.0.0.1", "token_exchange_failed"),
    ("token_gzip", "token", "gzip", "127.0.0.1", "token_exchange_failed"),
    ("discovery_slow_dns", "discovery", "fast", SLOW_HOST, "discovery_unreachable"),
    ("jwks_slow_dns", "jwks", "fast", SLOW_HOST, "jwks_unreachable"),
    ("token_slow_dns", "token", "fast", SLOW_HOST, "token_exchange_failed"),
    ("fast", "discovery", "fast", "127.0.0.1", "ok"),
]


class RealSocketDeadlineTests(SimpleTestCase):
    """A real blocking read on a real socket, interrupted by the real gevent timer."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        servers = {mode: DripServer(mode) for mode in ("headers", "gzip", "fast")}
        try:
            spec = {
                "deadline": DEADLINE,
                "slow_host": SLOW_HOST,
                "resolver_delay": RESOLVER_DELAY,
                "cases": [
                    [name, site, servers[mode].port, host] for name, site, mode, host, _ in CASES
                ],
            }
            env = dict(os.environ)
            env["PYTHONPATH"] = str(REPO_ROOT)
            proc = subprocess.run(
                [sys.executable, "-c", CHILD, json.dumps(spec)],
                cwd=str(REPO_ROOT), env=env, capture_output=True, text=True,
                timeout=CHILD_TIMEOUT, check=False,
            )
        finally:
            for server in servers.values():
                server.close()
        lines = [line for line in proc.stdout.splitlines() if line.startswith("{")]
        cls.child_error = None
        cls.child = None
        if proc.returncode != 0 or not lines:
            cls.child_error = f"child exited {proc.returncode}; stderr tail:\n{proc.stderr[-3000:]}"
        else:
            cls.child = json.loads(lines[-1])

    def result(self, name):
        self.assertIsNone(self.child_error, self.child_error)
        self.assertTrue(self.child["patched"], "the child was not monkey-patched")
        return self.child["results"][name]

    def assert_bounded(self, name):
        _, site, mode, _, code = next(case for case in CASES if case[0] == name)
        out = self.result(name)
        self.assertLess(
            out["elapsed"], DEADLINE + MARGIN,
            f"{site} against a {mode} drip took {out['elapsed']:.2f} s under gevent; "
            f"the whole-exchange deadline is {DEADLINE} s (answered {out['outcome']!r})",
        )
        self.assertGreaterEqual(out["elapsed"], DEADLINE * 0.9, out)
        self.assertEqual(out["outcome"], code, out)

    def test_discovery_dripped_headers(self):
        self.assert_bounded("discovery_headers")

    def test_discovery_dripped_gzip_body(self):
        self.assert_bounded("discovery_gzip")

    def test_jwks_dripped_headers(self):
        self.assert_bounded("jwks_headers")

    def test_token_dripped_headers(self):
        self.assert_bounded("token_headers")

    def test_token_dripped_gzip_body(self):
        self.assert_bounded("token_gzip")

    def assert_resolution_bounded(self, name, label):
        """The site's SSRF check resolves the host inside the timer, after the database
        connection was released, and the deadline (not the check's refusal) answers."""
        _, site, _, _, code = next(case for case in CASES if case[0] == name)
        out = self.result(name)
        self.assertLess(
            out["elapsed"], DEADLINE + MARGIN,
            f"{site} against a resolver that answers after {RESOLVER_DELAY} s took "
            f"{out['elapsed']:.2f} s under gevent; the whole-exchange deadline is {DEADLINE} s, "
            f"so the name resolution ran outside it (answered {out['outcome']!r}, "
            f"events {out['events']})",
        )
        self.assertGreaterEqual(out["elapsed"], DEADLINE * 0.9, out)
        self.assertEqual(out["outcome"], code, out)
        self.assertIn("resolve", out["events"], out)
        self.assertIn("release", out["events"], f"{site} never released its connection: {out}")
        self.assertLess(
            out["events"].index("release"), out["events"].index("resolve"),
            f"{site} resolved the host while still holding its database connection: "
            f"{out['events']}",
        )
        self.assertIn(f"OIDC {label} exchange exceeded its total deadline", out["logged"], out)

    def test_discovery_slow_resolver(self):
        self.assert_resolution_bounded("discovery_slow_dns", "discovery")

    def test_jwks_slow_resolver(self):
        self.assert_resolution_bounded("jwks_slow_dns", "jwks")

    def test_token_slow_resolver(self):
        self.assert_resolution_bounded("token_slow_dns", "token")

    def test_fast_response_unaffected_and_no_timer_left_armed(self):
        out = self.result("fast")
        self.assertEqual(out["outcome"], "ok", out)
        self.assertLess(out["elapsed"], DEADLINE, out)
        self.assertIsNone(out["late"], f"a timer fired after the call returned: {out['late']}")


@override_settings(OIDC_ALLOW_HTTP=True)
class UnpatchedFallbackTests(SimpleTestCase):
    """The documented fallback, in this unpatched process: no whole-exchange bound. If this
    starts failing because the call returned early, the comment at TOTAL_DEADLINE is stale."""

    def test_dripped_headers_are_not_bounded(self):
        self.assertFalse(discovery._gevent_socket_patched(), "the test runner is monkey-patched")
        server = DripServer("headers")
        try:
            provider = OIDCProvider(
                issuer=f"http://127.0.0.1:{server.port}/op", allow_private_network=False
            )
            started = time.monotonic()
            with mock.patch.object(discovery, "TOTAL_DEADLINE", DEADLINE), \
                    self.assertRaises(discovery.DiscoveryError) as caught:
                discovery.fetch_discovery(provider)
            elapsed = time.monotonic() - started
        finally:
            server.close()
        self.assertEqual(caught.exception.code, "discovery_unreachable")
        self.assertGreater(elapsed, DRIP_TOTAL * 0.8, f"returned after {elapsed:.2f} s")


# How long the cooperative hang waits before failing on its own: well past the 0.5 s
# deadline, so a build that loses the bound fails in seconds rather than after a minute.
HANG_CEILING = 3.0


def _cooperative_hang(*args, **kwargs):
    """A request that does not answer, waiting the way a monkey-patched socket read waits."""
    gevent.sleep(HANG_CEILING)
    raise AssertionError(
        f"the deadline never interrupted the request: still waiting after {HANG_CEILING} s, "
        "so run_bounded's whole-exchange timer (TOTAL_DEADLINE) is not armed on this path"
    )


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

    def test_token_endpoint_refusal_answers_its_own_handler_inside_the_bound(self):
        """The SSRF check now runs inside the timer; its refusal still answers by its own
        handler, at once, with no request sent and no deadline involved."""
        self.op.discovery_extra = {"token_endpoint": "http://10.0.0.5/token"}
        provider = self.make_flow_provider()
        client = APIClient()
        url = self.start(client, provider)
        params = self.op.authorize(url, {"roles": ["staff"]})
        posted = []

        def record_post(url, **kwargs):
            posted.append(url)
            raise requests.ConnectionError("the test refuses every POST")

        with mock.patch.object(requests, "post", side_effect=record_post), \
                capture_all_logs() as logs:
            started = time.monotonic()
            response = self.callback(client, provider, params)
            elapsed = time.monotonic() - started
        self.assertEqual(sso_error(response), "token_exchange_failed", response["Location"])
        self.assertEqual(posted, [], "a token request was sent to a private address")
        self.assertEqual(self.op.token_requests, [])
        self.assertNotIn(
            "OIDC token exchange exceeded its total deadline", [text for _, text in logs],
            "the refusal was answered by the deadline, not by the check",
        )
        self.assertLess(elapsed, self.DEADLINE, f"the refusal took {elapsed:.2f} s")

    def test_token_endpoint_check_on_admin_test(self):
        client, _ = admin_client()
        provider = self.make_flow_provider()
        with mock.patch.object(discovery, "validate_outbound_http_url", side_effect=_cooperative_hang), \
                capture_all_logs() as logs:
            result = self.timed(lambda: client.post(f"{PROVIDERS}{provider.pk}/test/").json())
        self.assertEqual(result["problems"], ["token_endpoint_not_allowed"])
        self.assert_deadline_logged(logs, "token endpoint check")


class _HangingRaw:
    """A response body whose first read never answers, waiting cooperatively."""

    def read1(self, *args, **kwargs):
        return _cooperative_hang()


class _HangingResponse:
    """Stands in for a streamed ``requests.Response`` and records whether it was closed."""

    status_code = 200

    def __init__(self):
        self.raw = _HangingRaw()
        self.closed = False

    def close(self):
        self.closed = True


class RunBoundedPropertiesTests(SimpleTestCase):
    """What ``run_bounded`` promises beyond the answer code, with the detection forced on
    and the real gevent timer, in this process."""

    DEADLINE = 0.5

    def setUp(self):
        super().setUp()
        for patcher in (
            mock.patch.object(discovery, "_gevent_socket_patched", return_value=True),
            mock.patch.object(discovery, "TOTAL_DEADLINE", self.DEADLINE),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_broad_except_exception_on_the_path_cannot_swallow_the_deadline(self):
        def call(deadline):
            try:
                gevent.sleep(HANG_CEILING)
            except Exception:  # what a handler between the timer and run_bounded may do
                return "swallowed"
            return "never interrupted"

        with self.assertRaises(discovery.DiscoveryError) as caught:
            value = discovery.run_bounded(
                call, on_expiry=lambda: discovery.DiscoveryError("x_unreachable"), label="x"
            )
            self.fail(
                f"run_bounded returned {value!r}: the timer's exception was caught by an "
                "'except Exception' on the path, so it must not be an Exception subclass"
            )
        self.assertEqual(caught.exception.code, "x_unreachable")

    @override_settings(OIDC_ALLOW_HTTP=True)
    def test_the_response_is_closed_when_the_deadline_interrupts_a_body_read(self):
        resp = _HangingResponse()
        provider = OIDCProvider(issuer="http://127.0.0.1:9/op", allow_private_network=False)
        with mock.patch.object(discovery, "fetch_outbound_http", return_value=resp), \
                self.assertRaises(discovery.DiscoveryError) as caught:
            discovery.fetch_discovery(provider)
        self.assertEqual(caught.exception.code, "discovery_unreachable")
        self.assertTrue(resp.closed, "the discovery response was left open after the deadline")

    @override_settings(OIDC_ALLOW_HTTP=True)
    def test_the_token_response_is_closed_when_the_deadline_interrupts_a_body_read(self):
        from apps.accounts.oidc import client_auth

        resp = _HangingResponse()
        provider = OIDCProvider(
            issuer="http://127.0.0.1:9/op", client_id="c",
            client_auth_method="client_secret_post", allow_private_network=False,
        )
        with mock.patch.object(requests, "post", return_value=resp), \
                mock.patch.object(
                    client_auth, "client_authentication", return_value=({"client_id": "c"}, {})
                ), \
                self.assertRaises(client_auth.TokenExchangeFailed) as caught:
            client_auth.exchange_code(
                provider, {"token_endpoint": "http://127.0.0.1:9/op/token"},
                code="c", redirect_uri="https://mino.example/cb", code_verifier="v",
            )
        self.assertEqual(caught.exception.code, "token_exchange_failed")
        self.assertTrue(resp.closed, "the token response was left open after the deadline")
