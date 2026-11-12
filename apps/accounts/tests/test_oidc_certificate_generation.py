"""Client key generation stays off the gevent hub (SSO follow-up to PR S1).

RSA key generation is CPU-bound. Inline in a monkey-patched uWSGI worker it would stall every
other request greenlet on that worker until it finished, so ``certificates.generate_pair`` runs
it on the hub's native threadpool when gevent's patching is active and inline everywhere else.

The gevent half runs in a child process: patching this test process would change every other
test in the label.
"""

import json
import subprocess
import sys
import threading
from pathlib import Path
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from django.conf import settings
from django.test import SimpleTestCase

from apps.accounts.oidc import certificates

# Generations run back to back with no yield of their own, so inline under gevent the ticker
# greenlet cannot run at all until the last one returns and its longest gap is the whole run.
GENERATIONS = 10
# The child is killed after this long, so a regression that hangs fails instead.
CHILD_TIMEOUT = 120

CHILD = r"""
from gevent import monkey

monkey.patch_all()

import json
import sys
import threading
import time

import gevent

from apps.accounts.oidc import certificates

GENERATIONS = int(sys.argv[1])

gaps = []
stop = []


def ticker():
    last = time.perf_counter()
    while not stop:
        gevent.sleep(0.001)
        now = time.perf_counter()
        gaps.append(now - last)
        last = now


threads = []
real = certificates._generate_pair


def recording(slug):
    threads.append(threading.get_ident())
    return real(slug)


certificates._generate_pair = recording
tick = gevent.spawn(ticker)
gevent.sleep(0.02)
started = time.perf_counter()
pairs = [certificates.generate_pair("child") for _ in range(GENERATIONS)]
total = time.perf_counter() - started
stop.append(True)
tick.join()

def boom(slug):
    raise ValueError("generation failed")

certificates._generate_pair = boom
try:
    certificates.generate_pair("child")
    raised = None
except ValueError as exc:
    raised = str(exc)

print(json.dumps({
    "total": total,
    "max_gap": max(gaps),
    "ticks": len(gaps),
    "hub_thread": threading.get_ident(),
    "threads": threads,
    "pair": pairs[0],
    "raised": raised,
}))
"""


def _run_child():
    result = subprocess.run(
        [sys.executable, "-c", CHILD, str(GENERATIONS)],
        cwd=str(Path(settings.BASE_DIR)),
        capture_output=True,
        text=True,
        timeout=CHILD_TIMEOUT,
    )
    if result.returncode != 0:
        raise AssertionError(f"gevent child failed ({result.returncode}): {result.stderr[-2000:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def _assert_pair(case, key_pem, cert_pem):
    key = serialization.load_pem_private_key(key_pem.encode("ascii"), password=None)
    cert = x509.load_pem_x509_certificate(cert_pem.encode("ascii"))
    case.assertEqual(key.key_size, certificates.KEY_SIZE)
    case.assertEqual(
        cert.public_key().public_numbers(), key.public_key().public_numbers()
    )


class GeventKeyGenerationTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.child = _run_child()

    def test_concurrent_greenlet_keeps_running_during_generation(self):
        child = self.child
        # Inline, the ticker is starved for the whole run (max_gap ~= total). Off the hub it
        # wakes every few milliseconds; half the run is a bound no loaded runner reaches,
        # because load slows the generations and the ticker together.
        self.assertLess(
            child["max_gap"],
            0.5 * child["total"],
            f"a greenlet was starved for {child['max_gap'] * 1000:.1f} ms of a "
            f"{child['total'] * 1000:.1f} ms run of {GENERATIONS} key generations "
            f"({child['ticks']} ticks): RSA key generation ran on the gevent hub thread",
        )

    def test_generation_runs_on_a_threadpool_thread(self):
        self.assertEqual(len(self.child["threads"]), GENERATIONS)
        self.assertNotIn(self.child["hub_thread"], self.child["threads"])

    def test_returns_a_matching_pair(self):
        key_pem, cert_pem = self.child["pair"]
        _assert_pair(self, key_pem, cert_pem)

    def test_exception_reraises_in_the_caller(self):
        self.assertEqual(self.child["raised"], "generation failed")


class InlineKeyGenerationTests(SimpleTestCase):
    """Without gevent's patching (this process, Celery, Daphne, management commands)."""

    def test_generates_inline_without_the_threadpool(self):
        caller = threading.get_ident()
        seen = []
        real = certificates._generate_pair

        def recording(slug):
            seen.append(threading.get_ident())
            return real(slug)

        with (
            mock.patch.object(certificates, "_generate_pair", recording),
            mock.patch(
                "gevent.get_hub",
                side_effect=AssertionError(
                    "generate_pair used the gevent threadpool in a process gevent has not patched"
                ),
            ) as get_hub,
        ):
            key_pem, cert_pem = certificates.generate_pair("inline")
        self.assertEqual(seen, [caller])
        get_hub.assert_not_called()
        _assert_pair(self, key_pem, cert_pem)
