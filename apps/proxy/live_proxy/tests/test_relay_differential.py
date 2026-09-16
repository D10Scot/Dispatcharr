"""The cross-implementation differential: both relays, the same bytes, compared.

Spec Amendment A2.4, owner 2c-9. `relay/internal/relaytest.SyntheticTS(512,
0x100)` and `harness/asset.py`'s `synthetic_ts(packets=512, pid=0x100)` produce
byte-identical output -- 96,256 bytes, SHA-256
e565411f3bbe6d0ab88a4dcd45d9e2a9ca1f65e049846dc5f61a2ec162f57f89, pinned from
the Go side by `relaytest.TestSyntheticTSMatchesThePythonHarness` -- so the two
relays can be driven from ONE upstream serving those bytes and their deliveries
compared by the index each packet carries in its own payload.

WHAT THIS CATCHES THAT NEITHER SIDE'S OWN PINS CAN. Every parity-matrix row is
pinned twice, once per language, and each pin asserts its own implementation
against the row's prose. Two implementations can both satisfy their own tests
and still hand a client different bytes -- a chunk boundary drawn differently, a
realignment that drops a packet on one side and carries it on the other, a join
that lands a chunk apart. That is the class of divergence this file exists for,
and it is the reason the assertion is CONTIGUITY AND OVERLAP rather than a body
digest: the two relays join a channel independently, so the first index each
sees legitimately differs, and a digest of the whole body fails on the join
point alone while saying nothing about the bytes.

IT CITES NO MATRIX ROW, AND NO ROW CITES IT -- deliberately. A differential
failure does not say which side is wrong, so it cannot serve as a row's pin;
rows 7, 8 and 9 keep the per-language pins they already have. This is a
separate, stated artefact that runs after both.

WHERE IT RUNS. `go-tests.yml`'s `differential` job, which is the only job that
builds `relay-go` and boots Postgres and Redis in the same container. Every
other run of this label -- `backend-tests.yml`'s `test` job and its
`coverage-label` job alike -- leaves DISPATCHARR_RELAY_GO_BIN unset and skips,
deterministically in both, which is what keeps Gate 2's Python census
unperturbed by a test that is sometimes present.
"""

import os
import socket
import subprocess
import time
import unittest

import requests
from django.conf import settings

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned, packet_index
from .harness.control import ControlMixin, nginx_headers
from .harness.relay import RelayHarnessTestCase, wait_until
from .manager_support import proxy_stream_profile

# How many whole packets each side is read for. 200 packets is 37,600 bytes --
# comfortably under the 512-packet asset, so neither delivery wraps back to
# index 0 and "ascending and contiguous" is a claim about one pass through the
# asset rather than about the loop point.
PACKETS_READ = 200


def require_relay_go() -> str:
    """The relay-go binary, or skip saying why there is none.

    Skips rather than fails when the variable is UNSET, because whether a Go
    binary has been built is a property of the job, not of the code under test,
    and this module is discovered by every run of this label. It FAILS when the
    variable is set and the path is unusable: a job that went to the trouble of
    naming a binary and then could not run it has a real problem, and a skip
    there is the silence-read-as-pass shape. `relay/channel/
    source_transcode_real_test.go`'s requireFFmpeg makes the same split.
    """
    path = os.environ.get("DISPATCHARR_RELAY_GO_BIN", "")
    if not path:
        raise unittest.SkipTest(
            "DISPATCHARR_RELAY_GO_BIN is unset; the cross-implementation differential "
            "did NOT run. go-tests.yml's `differential` job is what sets it."
        )
    if not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise AssertionError(
            f"DISPATCHARR_RELAY_GO_BIN={path} is not an executable file. It was set "
            "deliberately, so this is a broken job rather than a host without Go."
        )
    return path


def free_port() -> int:
    """A port nothing is listening on, released immediately.

    Racy in principle and fine in practice for one process on a CI runner --
    and the alternative, a fixed port, is worse: 5658 is the relay's own
    production port and a developer running this on a host with a dev stack up
    would bind-conflict with it.
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def contiguous_indices(body: bytes) -> list[int]:
    """Every packet's embedded index, asserted to be a strictly ascending run of 1.

    Returns the indices so a caller can compare ranges. Raises AssertionError
    naming the first break, because "the delivery had a gap" is useless without
    where.
    """
    assert_ts_aligned(body)
    indices = [
        packet_index(body[at : at + TS_PACKET_SIZE])
        for at in range(0, len(body), TS_PACKET_SIZE)
    ]
    for position, (left, right) in enumerate(zip(indices, indices[1:])):
        if right != left + 1:
            raise AssertionError(
                f"packet {position + 1} of {len(indices)} carries index {right}, "
                f"after {left}: the delivery is not a contiguous run. "
                f"First ten indices: {indices[:10]}"
            )
    return indices


class RelayDifferentialTests(ControlMixin, RelayHarnessTestCase):
    """Both relays, one upstream, the same asset; the deliveries compared."""

    def start_relay_go(self) -> str:
        """Run relay-go against the live Django in this test, return its base URL.

        Nothing is stubbed: the Go relay resolves its control plane from
        DISPATCHARR_INTERNAL_API_BASE_URL (relay/control/baseurl.go's first
        branch) and calls the REAL `POST /api/relay/channels/<id>/next-source`
        on this test's own LiveServerTestCase, signed with the REAL SECRET_KEY.
        That is the first time in this phase the two halves of the Phase 1
        contract meet across the language boundary.
        """
        binary = require_relay_go()
        port = free_port()
        env = dict(os.environ)
        env.update(
            {
                "DISPATCHARR_RELAY_GO_PORT": str(port),
                # Passed explicitly rather than inherited: how the process this
                # test runs in resolved its SECRET_KEY is not something the
                # child can be assumed to repeat, and a disagreement surfaces
                # as a 403 on every internal call with nothing naming the
                # cause (relay/config/config.go's own note on precedence).
                "DJANGO_SECRET_KEY": settings.SECRET_KEY,
                "DISPATCHARR_RELAY_GO_DEV_ROUTES": "true",
                "DISPATCHARR_INTERNAL_API_BASE_URL": self.live_server_url,
            }
        )
        process = subprocess.Popen(  # noqa: S603 - a path this test resolved itself
            [binary],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        def stop():
            if process.poll() is None:
                # SIGTERM, not SIGKILL: since 2c-8 that raises D6's drain, and
                # letting it run is what keeps this test from leaving a
                # half-torn-down channel behind. The wait is THIRTY seconds
                # against a drain budget of 15 s, not ten: the drain spends a
                # five-second client grace before anything else, so a 10 s
                # wait sat only 5 s above the observed teardown and would
                # escalate to SIGKILL the first time the drain used more of
                # its own budget -- a flake that would read as a hung relay.
                # Measured: the whole test takes ~6.5 s, of which ~5 s is this
                # grace (it was ~2.3 s before 2c-8 added the drain).
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            # Printed on the way out so a failed assertion above is read next
            # to whatever the relay was saying at the time. It redacts its own
            # URLs (relay/redact), so this cannot print a provider credential.
            output = process.stdout.read() if process.stdout else b""
            if output:
                print("relay-go said:\n" + output.decode(errors="replace"))

        self.addCleanup(stop)

        base = f"http://127.0.0.1:{port}"

        def healthy():
            if process.poll() is not None:
                raise AssertionError(
                    f"relay-go exited with {process.returncode} before answering /healthz"
                )
            try:
                return requests.get(f"{base}/healthz", timeout=1).status_code == 200
            except requests.RequestException:
                return False

        wait_until(healthy, timeout=20.0, what="relay-go to answer /healthz")
        return base

    def read_from(self, url: str, channel, client_id: str, count: int) -> bytes:
        """`count` whole packets from a tune at `url`, with nginx's own headers."""
        response = requests.get(
            url,
            stream=True,
            timeout=30.0,
            headers=nginx_headers(channel, client_id),
        )
        self.addCleanup(response.close)
        # NEVER response.text on a 200: a live stream's body does not end, and
        # `timeout` is a socket timeout (harness/relay.py's own note).
        if response.status_code != 200:
            self.fail(f"tune at {url} returned {response.status_code}: {response.text[:200]}")
        wanted = count * TS_PACKET_SIZE
        body = b""
        deadline = time.monotonic() + 30.0
        for chunk in response.raw.stream(8192, decode_content=False):
            body += chunk
            if len(body) >= wanted:
                break
            if time.monotonic() > deadline:
                self.fail(f"only {len(body)} of {wanted} bytes arrived from {url}")
        return body[:wanted]

    def both_deliveries(self, upstream) -> tuple[list[int], bytes, list[int], bytes]:
        """Tune each relay on its OWN channel against `upstream`; return both runs.

        Two channels rather than one, and it is not an evasion. A channel's
        upstream slot is Django's to hand out (`Channel.get_stream()`), so two
        relays tuning ONE channel would contend for the assignment and the test
        would be measuring that contention. Two channels on the same URL get
        the same bytes from the first byte either way -- FakeUpstream serves the
        payload from its start to every connection -- which is the property this
        comparison actually rests on.
        """
        go_base = self.start_relay_go()
        # THIRTY seconds behind, not zero, and the direction is the opposite of
        # the obvious one. A client asking to join at the HEAD lands wherever
        # its own relay's read-ahead had got to when it attached, which is a
        # timing measurement, not a behaviour: measured on this harness, the
        # Python client joined at index 178 while the Go client on an
        # identically-configured channel joined at 0, leaving 22 comparable
        # packets out of 200. Asking to join thirty seconds behind a channel
        # one second old takes BOTH implementations' documented
        # shorter-than-requested fallback -- Python's chunk_timestamps lookup
        # and Go's Ring.Join (pinned by TestJoinFallsBackToTheOldestChunkWhen
        # TheBufferIsShort) -- so both start at the OLDEST resident chunk and
        # the comparison is over the whole read rather than over whatever the
        # scheduler left in common.
        self.set_proxy_setting(new_client_behind_seconds=30)

        profile = proxy_stream_profile()
        py_channel = self.make_channel(upstream_url=upstream.url, profile=profile)
        go_channel = self.make_channel(upstream_url=upstream.url, profile=profile)

        py_body = self.read_from(
            f"{self.live_server_url}/proxy/ts/stream/{py_channel.uuid}",
            py_channel,
            "differential-python",
            PACKETS_READ,
        )
        go_body = self.read_from(
            f"{go_base}/proxy/ts/stream/{go_channel.uuid}",
            go_channel,
            "differential-go",
            PACKETS_READ,
        )
        self.addCleanup(self.stop_channel, py_channel)
        return contiguous_indices(py_body), py_body, contiguous_indices(go_body), go_body

    def assert_overlap_identical(self, py_indices, py_body, go_indices, go_body):
        """The packets both relays delivered are byte-identical, and there are some.

        The emptiness check is the half that matters: without it, two relays
        that delivered disjoint index ranges would compare zero packets and
        pass, which is the strongest possible divergence reported as agreement.
        """
        low = max(py_indices[0], go_indices[0])
        high = min(py_indices[-1], go_indices[-1])
        overlap = high - low + 1
        self.assertGreaterEqual(
            overlap,
            PACKETS_READ // 4,
            f"the two deliveries overlap by {overlap} packets -- python "
            f"{py_indices[0]}..{py_indices[-1]}, go {go_indices[0]}..{go_indices[-1]}. "
            "Too little overlap to compare; the two relays joined the channel at very "
            "different points, which is itself the divergence.",
        )
        for index in range(low, high + 1):
            py_at = (index - py_indices[0]) * TS_PACKET_SIZE
            go_at = (index - go_indices[0]) * TS_PACKET_SIZE
            self.assertEqual(
                py_body[py_at : py_at + TS_PACKET_SIZE],
                go_body[go_at : go_at + TS_PACKET_SIZE],
                f"packet index {index} differs between the two relays. This is a "
                "byte-level divergence on the live path, not a timing difference: "
                "both relays were served the same asset from its start.",
            )

    def test_both_relays_deliver_the_same_packets_from_the_same_upstream(self):
        """One asset in, the same packets out of both implementations."""
        py_indices, py_body, go_indices, go_body = self.both_deliveries(self.upstream)
        self.assert_overlap_identical(py_indices, py_body, go_indices, go_body)
