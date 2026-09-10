"""An in-process HTTP upstream for backend tests.

Not a reuse of the e2e-upstream Docker image on purpose: the backend test runner
is itself a container, and a sibling container per test is a poor trade for
something that has to start in milliseconds. This serves one looping TS payload
on one path, with the eight live-TS faults harness.faults ports.

Threading, not gevent: manage.py test does not monkey-patch (the patch is
applied only by dispatcharr/gevent_patch.py, imported from the uWSGI ini files),
so ThreadingHTTPServer's real OS threads are the right primitive and are the
same primitive the relay's own workers use under test.
"""

import http.server
import threading
import time

from .asset import TS_PACKET_SIZE, synthetic_ts
from .faults import FaultStore

_HTML_ERROR_PAGE = (
    b"<html><head><title>502 Bad Gateway</title></head>"
    b"<body><h1>502 Bad Gateway</h1></body></html>"
)

# What "rate 1.0" means, in bytes per second: 2 Mbit/s, the bitrate
# e2e-upstream/scripts/make-asset.sh builds its own asset at. slow-trickle's
# rate multiplies this.
NOMINAL_BYTE_RATE = 2_000_000 // 8

_WRITE_CHUNK = TS_PACKET_SIZE * 50  # 9,400 bytes


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # Silence BaseHTTPRequestHandler's stderr access log; a test that wants to
    # know what was requested reads server.request_count.
    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802 - the stdlib's name
        upstream = self.server.upstream
        faults = upstream.faults
        with upstream._lock:
            upstream.request_count += 1
            hop = upstream._redirect_hops

        if faults.is_active("not-found"):
            self._send_short(404, b'{"error": "fault: not-found"}', "application/json")
            return
        if faults.is_active("auth-failure"):
            self._send_short(401, b'{"error": "fault: auth-failure"}', "application/json")
            return
        if faults.is_active("connection-limit"):
            self._send_short(429, b'{"error": "fault: connection-limit"}', "application/json")
            return

        if faults.is_active("redirect-chain"):
            depth = faults.config_of("redirect-chain")["depth"]
            if hop < depth:
                with upstream._lock:
                    upstream._redirect_hops += 1
                self.send_response(302)
                self.send_header("Location", upstream.url)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            # Chain exhausted: this request serves the stream, and the next
            # connection starts a fresh chain.
            with upstream._lock:
                upstream._redirect_hops = 0

        if faults.is_active("non-ts-bytes"):
            self._send_short(200, _HTML_ERROR_PAGE, "text/html")
            return

        self.send_response(200)
        self.send_header("Content-Type", "video/mp2t")
        self.send_header("Connection", "close")
        self.end_headers()

        if faults.is_active("dead-air"):
            # Headers sent, nothing else, socket held open -- exactly what a
            # provider that stops producing looks like from the relay's side.
            deadline = time.monotonic() + upstream.dead_air_hold_seconds
            while time.monotonic() < deadline and not upstream._stopping.is_set():
                time.sleep(0.05)
            return

        self._stream(upstream)

    def _send_short(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _stream(self, upstream):
        payload = upstream.payload
        faults = upstream.faults

        rate = None
        if faults.is_active("slow-trickle"):
            rate = faults.config_of("slow-trickle")["rate"] * NOMINAL_BYTE_RATE
        elif upstream.rate is not None:
            rate = upstream.rate * NOMINAL_BYTE_RATE

        stop_after = None
        clean = True
        if faults.is_active("disconnect"):
            config = faults.config_of("disconnect")
            stop_after = config["after_bytes"]
            clean = config["clean"]

        sent = 0
        at = 0
        started = time.monotonic()
        try:
            while not upstream._stopping.is_set():
                if stop_after is not None and sent >= stop_after:
                    if not clean:
                        # Abrupt: drop the socket without a clean shutdown, so
                        # the reader sees a connection reset rather than EOF.
                        self.close_connection = True
                        try:
                            self.connection.close()
                        except OSError:
                            pass
                    return
                chunk = _WRITE_CHUNK
                if stop_after is not None:
                    chunk = min(chunk, stop_after - sent)
                piece = bytearray()
                while len(piece) < chunk:
                    take = min(chunk - len(piece), len(payload) - at)
                    piece += payload[at : at + take]
                    at = (at + take) % len(payload)
                self.wfile.write(bytes(piece))
                sent += len(piece)
                if rate is not None:
                    due = started + sent / rate
                    now = time.monotonic()
                    if due > now:
                        time.sleep(min(due - now, 0.25))
        except (BrokenPipeError, ConnectionResetError, OSError):
            # The relay closed its side -- an ordinary end to a tune.
            return


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # A tune ending, or the `disconnect` fault firing, closes a socket
        # mid-response. socketserver's default handle_error prints a full
        # traceback to stderr for each one, which would bury every real test
        # failure in noise. Swallowed here deliberately: nothing about this
        # server's own errors is under test, and a test that cares asserts on
        # what the client received.
        pass


class FakeUpstream:
    """A looping TS upstream on 127.0.0.1, with injectable faults.

    `payload` defaults to 512 synthetic packets (~96 KB). `rate` paces every
    response at that multiple of NOMINAL_BYTE_RATE even with no slow-trickle
    fault armed, and **defaults to 1.0 rather than None on purpose**: at
    loopback speed this server pushes about 34 MB/s into the ring buffer, which
    was measured filling Redis to 2.17 GB across 8,863 chunk keys in ~50
    seconds of a single held-open tune. Redis runs with `maxmemory 0` and DB 0
    is shared with the Celery broker and the Django cache, so an unpaced tune
    held open for a dead-air cycle or a buffering window -- which is precisely
    what 2a-3 … 2a-6 will do -- takes the whole test process down with it.
    `rate=None` restores the unpaced behaviour and is a deliberate,
    short-tune-only choice.
    """

    dead_air_hold_seconds = 30.0

    def __init__(self, payload: bytes | None = None, rate: float | None = 1.0) -> None:
        self.payload = payload if payload is not None else synthetic_ts(packets=512)
        if not self.payload:
            raise ValueError("payload must not be empty")
        self.rate = rate
        self.faults = FaultStore()
        self.request_count = 0
        self._redirect_hops = 0
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self.url = ""

    def start(self) -> "FakeUpstream":
        if self._server is not None:
            raise RuntimeError("already started")
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.upstream = self
        host, port = self._server.server_address[:2]
        self.url = f"http://{host}:{port}/live.ts"
        # poll_interval, not the 0.5s default: serve_forever() sleeps that long
        # between checks of its shutdown flag and shutdown() waits one out, so
        # the default costs every single upstream test half a second of pure
        # teardown -- measured at ~0.5s per test across the whole label.
        self._thread = threading.Thread(
            target=self._server.serve_forever, args=(0.01,), name="fake-upstream", daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stopping.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> "FakeUpstream":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
