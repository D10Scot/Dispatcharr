"""core/request_body_spool.py: the API process reads a request body before Django.

The two API inis drop uWSGI's ``post-buffering`` because, under gevent, its
``inc_harakiri()`` turned a zeroed per-worker harakiri deadline into a 1970
timestamp and the master killed the whole worker. This middleware takes over
what post-buffering did for clients: the body is read in full before the app
runs, so a view that answers without reading it does not leave bytes on the
socket. These tests pin the gate, the byte-for-byte hand-over, the bounds,
the cleanup, the wiring in the WSGI module the API ini loads, and the wrapper
behind a real socket (the standard library's ``wsgiref`` server).

What only the manual uWSGI runs show, and no test here: the interleave kill
itself, gevent hub latency during a large spool, and nginx in front.
"""
import hashlib
import io
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from django.core.handlers.wsgi import WSGIRequest
from django.test import SimpleTestCase

from core import request_body_spool
from core.request_body_spool import (
    MEMORY_THRESHOLD,
    SPOOL_ENV,
    SpoolRequestBody,
    wrap,
)


class _Recorder:
    """A WSGI app that records what it saw and reads the body as told."""

    def __init__(self, read=lambda stream: stream.read(), result=None, raise_exc=None):
        self.read = read
        self.result = result
        self.raise_exc = raise_exc
        self.calls = 0
        self.seen = None
        self.stream = None
        self.environ = None

    def __call__(self, environ, start_response):
        self.calls += 1
        self.environ = environ
        self.stream = environ["wsgi.input"]
        self.seen = self.read(self.stream)
        if self.raise_exc is not None:
            raise self.raise_exc
        start_response("200 OK", [("Content-Type", "text/plain")])
        return self.result if self.result is not None else [b"ok"]


class _ClosableResult:
    def __init__(self, items, fail_at=None):
        self.items = items
        self.fail_at = fail_at
        self.closed = False

    def __iter__(self):
        for index, item in enumerate(self.items):
            if index == self.fail_at:
                raise RuntimeError("iteration failed")
            yield item

    def close(self):
        self.closed = True


class _BrokenStream(io.BytesIO):
    """Returns some bytes, then raises as uWSGI's wsgi.input does on a read error."""

    def __init__(self, data, fail_after):
        super().__init__(data)
        self.fail_after = fail_after

    def read(self, size=-1):
        if self.tell() >= self.fail_after:
            raise OSError("error waiting for wsgi.input data")
        return super().read(min(size, self.fail_after - self.tell()))


def _environ(body=b"", content_length=None, stream=None, **extra):
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": "/upload",
        "SERVER_NAME": "testserver",
        "SERVER_PORT": "80",
        "wsgi.input": stream if stream is not None else io.BytesIO(body),
        "wsgi.url_scheme": "http",
        "wsgi.file_wrapper": object(),
    }
    if content_length is not None:
        environ["CONTENT_LENGTH"] = str(content_length)
    environ.update(extra)
    return environ


def _start_response(statuses):
    def start_response(status, headers, exc_info=None):
        statuses.append((status, headers))

    return start_response


def _run(app, environ):
    """Call a WSGI app as uWSGI does: iterate the result, then close it."""
    statuses = []
    result = app(environ, _start_response(statuses))
    try:
        body = b"".join(result)
    finally:
        close = getattr(result, "close", None)
        if close is not None:
            close()
    return statuses, body, result


def _pattern(size):
    """Bytes whose every position is distinguishable, so a shift or a drop shows."""
    return bytes((i * 7 + i // 251) % 256 for i in range(size))


class GateTests(SimpleTestCase):
    def test_the_gate_off_returns_the_original_callable_untouched(self):
        app = _Recorder()
        for env in ({}, {SPOOL_ENV: ""}, {SPOOL_ENV: "0"}, {SPOOL_ENV: "true"}, {SPOOL_ENV: "yes"}, {SPOOL_ENV: " 1"}):
            with self.subTest(env=env):
                self.assertIs(wrap(app, env), app, f"gate {env!r} must leave the application unwrapped")

    def test_the_gate_on_wraps(self):
        app = _Recorder()
        wrapped = wrap(app, {SPOOL_ENV: "1"})
        self.assertIsInstance(wrapped, SpoolRequestBody)
        self.assertIs(wrapped.application, app)

    def test_the_gate_reads_the_process_environment_by_default(self):
        app = _Recorder()
        previous = os.environ.pop(SPOOL_ENV, None)
        try:
            self.assertIs(wrap(app), app)
            os.environ[SPOOL_ENV] = "1"
            self.assertIsInstance(wrap(app), SpoolRequestBody)
        finally:
            os.environ.pop(SPOOL_ENV, None)
            if previous is not None:
                os.environ[SPOOL_ENV] = previous


class HandOverTests(SimpleTestCase):
    def test_a_small_body_reaches_the_app_byte_for_byte_and_stays_in_memory(self):
        body = b'{"code":"abc","state":"xyz"}'
        app = _Recorder()
        statuses, _, result = _run(SpoolRequestBody(app), _environ(body, len(body)))
        self.assertEqual(app.seen, body)
        self.assertEqual(statuses[0][0], "200 OK")
        self.assertFalse(app.stream._rolled, "a body under the threshold must not touch the disk")

    def test_a_large_body_reaches_the_app_byte_for_byte_through_a_file(self):
        body = _pattern(3 * request_body_spool.READ_CHUNK + 4093)
        app = _Recorder()
        _run(SpoolRequestBody(app), _environ(body, len(body)))
        self.assertEqual(len(app.seen), len(body))
        self.assertEqual(app.seen, body, "the spooled body differs from what the client sent")
        self.assertTrue(app.stream._rolled, f"a body over {MEMORY_THRESHOLD} bytes should roll over to a file")

    def test_every_read_shape_the_app_uses_sees_the_same_bytes(self):
        body = b"line one\nline two\n" + _pattern(9000) + b"\nlast"
        shapes = {
            "read()": lambda s: s.read(),
            "read(n) loop": lambda s: b"".join(iter(lambda: s.read(1000), b"")),
            "readline() loop": lambda s: b"".join(iter(s.readline, b"")),
            "iteration": lambda s: b"".join(s),
        }
        for name, read in shapes.items():
            with self.subTest(shape=name):
                app = _Recorder(read=read)
                _run(SpoolRequestBody(app), _environ(body, len(body)))
                self.assertEqual(app.seen, body, name)

    def test_django_parses_a_large_multipart_upload_from_the_spool(self):
        boundary = "spoolboundary"
        payload = _pattern(3 * 1024 * 1024 + 11)
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="note"\r\n\r\n'
            "hello\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="backup.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
        seen = {}

        def django_view(environ, start_response):
            request = WSGIRequest(environ)
            upload = request.FILES["file"]
            seen["note"] = request.POST["note"]
            seen["file"] = upload.read()
            upload.close()
            start_response("200 OK", [])
            return [b"ok"]

        environ = _environ(
            body,
            len(body),
            CONTENT_TYPE=f"multipart/form-data; boundary={boundary}",
        )
        _run(SpoolRequestBody(django_view), environ)
        self.assertEqual(seen["note"], "hello")
        self.assertEqual(seen["file"], payload, "Django's multipart parser read different bytes from the spool")

    def test_a_view_that_never_reads_still_gets_a_full_body_drained_from_the_socket(self):
        body = _pattern(200_000)
        source = io.BytesIO(body)
        app = _Recorder(read=lambda s: None)
        statuses, _, _ = _run(SpoolRequestBody(app), _environ(stream=source, content_length=len(body)))
        self.assertEqual(statuses[0][0], "200 OK")
        self.assertEqual(source.tell(), len(body), "the body must be consumed from the socket before the app runs")

    def test_a_spooled_request_loses_wsgi_file_wrapper_and_a_passed_through_one_keeps_it(self):
        body = b"x" * 10
        spooled = _Recorder()
        _run(SpoolRequestBody(spooled), _environ(body, len(body)))
        self.assertNotIn("wsgi.file_wrapper", spooled.environ)
        passed = _Recorder()
        _run(SpoolRequestBody(passed), _environ(b""))
        self.assertIn("wsgi.file_wrapper", passed.environ)


class BoundsTests(SimpleTestCase):
    def test_a_content_length_that_is_not_plain_ascii_digits_passes_through(self):
        # int() accepts every one of these; none is a Content-Length.
        for raw in ("5_0", " 50", "50 ", "+50", "\u0665\u0660"):
            with self.subTest(content_length=raw):
                source = io.BytesIO(_pattern(50))
                app = _Recorder(read=lambda s: None)
                _run(SpoolRequestBody(app), _environ(stream=source, CONTENT_LENGTH=raw))
                self.assertIs(app.stream, source, f"{raw!r} is not ASCII digits and must not be spooled")
                self.assertEqual(source.tell(), 0, f"{raw!r}: nothing may be read ahead of the app")

    def test_no_or_unusable_content_length_passes_the_request_through_untouched(self):
        for label, extra in (
            ("absent", {}),
            ("empty", {"CONTENT_LENGTH": ""}),
            ("zero", {"CONTENT_LENGTH": "0"}),
            ("negative", {"CONTENT_LENGTH": "-5"}),
            ("garbage", {"CONTENT_LENGTH": "12abc"}),
            ("chunked", {"HTTP_TRANSFER_ENCODING": "chunked"}),
        ):
            with self.subTest(content_length=label):
                source = io.BytesIO(b"5\r\nhello\r\n0\r\n\r\n")
                app = _Recorder(read=lambda s: None)
                environ = _environ(stream=source, **extra)
                _, _, result = _run(SpoolRequestBody(app), environ)
                self.assertIs(app.stream, source, f"{label}: wsgi.input must be the server's own stream")
                self.assertEqual(source.tell(), 0, f"{label}: nothing may be read ahead of the app")
                self.assertNotIsInstance(result, request_body_spool._ClosingResult)

    def test_only_the_declared_length_is_read_when_the_client_sends_more(self):
        source = io.BytesIO(b"0123456789EXTRA")
        app = _Recorder()
        _run(SpoolRequestBody(app), _environ(stream=source, content_length=10))
        self.assertEqual(app.seen, b"0123456789")
        self.assertEqual(source.read(), b"EXTRA", "bytes past CONTENT_LENGTH must stay unread")

    def test_a_body_shorter_than_declared_is_refused_without_running_the_app(self):
        app = _Recorder()
        statuses, body, result = _run(SpoolRequestBody(app), _environ(b"short", 100))
        self.assertEqual(app.calls, 0, "a truncated body must not reach the application")
        self.assertEqual(statuses, [("400 Bad Request", [("Content-Length", "0")])])
        self.assertEqual(body, b"")

    def test_a_read_error_mid_body_is_refused_without_running_the_app(self):
        app = _Recorder()
        stream = _BrokenStream(_pattern(10_000), fail_after=6_000)
        statuses, _, _ = _run(SpoolRequestBody(app), _environ(stream=stream, content_length=10_000))
        self.assertEqual(app.calls, 0)
        self.assertEqual(statuses[0][0], "400 Bad Request")

    def test_the_truncation_log_line_carries_counts_only(self):
        secret = b"password=hunter2&token=abc"
        with self.assertLogs(request_body_spool.logger.name, level="INFO") as logs:
            _run(SpoolRequestBody(_Recorder()), _environ(secret, 1000, PATH_INFO="/api/x?token=abc"))
        line = "\n".join(logs.output)
        self.assertIn(f"{len(secret)} of 1000", line)
        for leak in ("hunter2", "token", "/api/x"):
            self.assertNotIn(leak, line)


class CleanupTests(SimpleTestCase):
    def _spy_spools(self):
        made = []
        real = request_body_spool.tempfile.SpooledTemporaryFile

        def factory(*args, **kwargs):
            spool = real(*args, **kwargs)
            made.append(spool)
            return spool

        request_body_spool.tempfile.SpooledTemporaryFile = factory
        self.addCleanup(setattr, request_body_spool.tempfile, "SpooledTemporaryFile", real)
        return made

    def test_the_spool_is_closed_when_the_response_is_closed(self):
        made = self._spy_spools()
        inner = _ClosableResult([b"a", b"b"])
        app = _Recorder(result=inner)
        _, body, _ = _run(SpoolRequestBody(app), _environ(_pattern(9000), 9000))
        self.assertEqual(body, b"ab")
        self.assertTrue(inner.closed, "the application's own close() must still be called")
        self.assertEqual(len(made), 1)
        self.assertTrue(made[0].closed, "the spool must be closed when the server closes the response")

    def test_the_spool_is_not_closed_before_the_response_is_closed(self):
        made = self._spy_spools()
        app = _Recorder(read=lambda s: None)
        result = SpoolRequestBody(app)(_environ(b"abc", 3), _start_response([]))
        self.assertFalse(made[0].closed, "a streaming view may still read the body while the response iterates")
        app.stream.seek(0)
        self.assertEqual(app.stream.read(), b"abc")
        result.close()
        self.assertTrue(made[0].closed)

    def test_the_spool_is_closed_when_the_application_raises(self):
        made = self._spy_spools()
        app = _Recorder(raise_exc=ValueError("view blew up"))
        with self.assertRaisesMessage(ValueError, "view blew up"):
            SpoolRequestBody(app)(_environ(_pattern(9000), 9000), _start_response([]))
        self.assertTrue(made[0].closed, "an exception from the application must not leak the spool")

    def test_the_spool_is_closed_when_iteration_fails_and_the_server_closes(self):
        made = self._spy_spools()
        inner = _ClosableResult([b"a", b"b"], fail_at=1)
        app = _Recorder(result=inner)
        with self.assertRaisesMessage(RuntimeError, "iteration failed"):
            _run(SpoolRequestBody(app), _environ(b"abc", 3))
        self.assertTrue(inner.closed)
        self.assertTrue(made[0].closed)

    def test_the_spool_is_closed_when_a_generator_response_is_closed_early(self):
        made = self._spy_spools()
        finished = []

        def generator():
            try:
                yield b"first"
                yield b"second"
            finally:
                finished.append(True)

        app = _Recorder(result=generator())
        result = SpoolRequestBody(app)(_environ(b"abc", 3), _start_response([]))
        iterator = iter(result)
        self.assertEqual(next(iterator), b"first")
        result.close()
        self.assertEqual(finished, [True], "the generator's own cleanup must run")
        self.assertTrue(made[0].closed)

    def test_the_spool_is_closed_when_the_body_is_refused(self):
        made = self._spy_spools()
        _run(SpoolRequestBody(_Recorder()), _environ(b"short", 100))
        self.assertTrue(made[0].closed)

    def test_the_spool_is_closed_when_the_inner_close_raises(self):
        made = self._spy_spools()

        class _BadClose(_ClosableResult):
            def close(self):
                raise RuntimeError("close failed")

        app = _Recorder(result=_BadClose([b"a"]))
        with self.assertRaisesMessage(RuntimeError, "close failed"):
            _run(SpoolRequestBody(app), _environ(b"abc", 3))
        self.assertTrue(made[0].closed)


REPO_ROOT = Path(__file__).resolve().parents[2]
API_INI = REPO_ROOT / "docker" / "uwsgi.ini"

WIRING_CHILD = """
import importlib, json, sys
module, attr = sys.argv[1].split(":")
application = getattr(importlib.import_module(module), attr)
from core.request_body_spool import SpoolRequestBody
print(json.dumps({
    "wrapped": isinstance(application, SpoolRequestBody),
    "inner": type(getattr(application, "application", application)).__name__,
}))
"""


def _ini_value(key, pattern):
    """The value of the first ``key = ...`` line in the API ini matching ``pattern``."""
    for line in API_INI.read_text().splitlines():
        match = re.match(rf"^{re.escape(key)}\s*=\s*(\S+)", line)
        if match and re.search(pattern, match.group(1)):
            return match.group(1)
    raise AssertionError(f"{API_INI.name} has no {key} line matching {pattern!r}")


class WiringTests(SimpleTestCase):
    """The module the API ini loads exports the wrapper exactly when its env line is set.

    Imported in a fresh interpreter, so the Django test process is untouched and
    the import is the same cold one uWSGI's lazy-apps worker performs.
    """

    def _application(self, extra_env):
        env = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "LANG", "DJANGO_SECRET_KEY", "POSTGRES_HOST", "POSTGRES_DB",
                        "POSTGRES_USER", "POSTGRES_PASSWORD", "REDIS_HOST", "REDIS_PORT", "REDIS_DB")
            if key in os.environ
        }
        env.update({"PYTHONPATH": str(REPO_ROOT), "PYTHONDONTWRITEBYTECODE": "1",
                    "DJANGO_SETTINGS_MODULE": os.environ.get("DJANGO_SETTINGS_MODULE", "")})
        env.update(extra_env)
        result = subprocess.run(
            [sys.executable, "-c", WIRING_CHILD, _ini_value("module", ":")],
            env=env, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120, check=False,
        )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, f"child failed:\n{result.stdout}\n{result.stderr[-3000:]}")
        return json.loads(lines[-1])

    def test_the_api_ini_env_line_makes_the_loaded_application_the_spool(self):
        key, value = _ini_value("env", rf"^{SPOOL_ENV}=").split("=", 1)
        seen = self._application({key: value})
        self.assertTrue(
            seen["wrapped"],
            "the WSGI module the API ini loads must apply wrap() to its application: "
            "with the ini's env line set, it did not export a SpoolRequestBody",
        )
        self.assertEqual(seen["inner"], "WSGIHandler", "the spool must wrap Django's own handler")

    def test_without_the_env_line_the_loaded_application_is_django_unwrapped(self):
        seen = self._application({})
        self.assertFalse(seen["wrapped"], "with the switch unset the application must not be wrapped")
        self.assertEqual(seen["inner"], "WSGIHandler")


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass

    def handle(self):
        try:
            super().handle()
        finally:
            self.server.handled.release()


class _QuietServer(WSGIServer):
    def handle_error(self, request, client_address):
        pass  # a client that closed mid-request is the point of one test


class RealSocketTests(SimpleTestCase):
    """The wrapper behind a real socket, served by ``wsgiref``.

    ``wsgiref`` hands the application the socket's own file as ``wsgi.input``
    and closes the connection after each response, which is the shape that
    resets a client whose body was left unread.
    """

    def _serve(self, app):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        previous_tempdir = tempfile.tempdir
        tempfile.tempdir = self.tmp.name
        self.addCleanup(setattr, tempfile, "tempdir", previous_tempdir)

        self.spools = []
        real = request_body_spool.tempfile.SpooledTemporaryFile

        def factory(*args, **kwargs):
            spool = real(*args, **kwargs)
            self.spools.append(spool)
            return spool

        request_body_spool.tempfile.SpooledTemporaryFile = factory
        self.addCleanup(setattr, request_body_spool.tempfile, "SpooledTemporaryFile", real)

        server = make_server("127.0.0.1", 0, app, server_class=_QuietServer, handler_class=_QuietHandler)
        server.handled = threading.Semaphore(0)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.server = server
        return server.server_address[1]

    def _wait_handled(self):
        self.assertTrue(self.server.handled.acquire(timeout=30), "the server never finished the request")

    @staticmethod
    def _request(port, body, declared=None, send=None):
        """Send a POST over a raw socket and return everything the server sent back."""
        declared = len(body) if declared is None else declared
        head = (
            f"POST /upload HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/octet-stream\r\n"
            f"Content-Length: {declared}\r\n\r\n"
        ).encode()
        with socket.create_connection(("127.0.0.1", port), timeout=30) as client:
            client.sendall(head + (body if send is None else body[:send]))
            if send is not None:
                return None
            chunks = []
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)

    def test_a_body_over_the_memory_threshold_reaches_the_app_byte_for_byte(self):
        seen = {}

        def echo(environ, start_response):
            data = environ["wsgi.input"].read()
            seen["rolled_to_disk"] = getattr(environ["wsgi.input"], "_rolled", None)
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [hashlib.sha256(data).hexdigest().encode()]

        port = self._serve(SpoolRequestBody(echo))
        body = _pattern(MEMORY_THRESHOLD * 256 + 13)
        response = self._request(port, body)
        self._wait_handled()
        self.assertTrue(response.startswith(b"HTTP/1.0 200"), response[:200])
        self.assertTrue(response.endswith(hashlib.sha256(body).hexdigest().encode()), "the app must read exactly the bytes sent")
        self.assertTrue(seen["rolled_to_disk"], "a body over the threshold must have rolled over to a file")
        self.assertEqual(len(self.spools), 1)
        self.assertTrue(self.spools[0].closed, "the spool must be closed once the server closed the response")
        self.assertEqual(os.listdir(self.tmp.name), [], "the spool must leave nothing in the temp directory")

    def test_a_view_that_refuses_without_reading_a_large_body_sends_a_complete_response(self):
        calls = []

        def refuse(environ, start_response):
            calls.append(True)
            start_response("403 Forbidden", [("Content-Type", "text/plain"), ("Content-Length", "9")])
            return [b"forbidden"]

        port = self._serve(SpoolRequestBody(refuse))
        body = _pattern(8 * 1024 * 1024)
        try:
            response = self._request(port, body)
        except (ConnectionResetError, BrokenPipeError) as exc:
            self.fail(
                f"the connection was reset ({type(exc).__name__}): a body the view never read was left "
                "on the socket, which is what the spool exists to prevent"
            )
        self._wait_handled()
        self.assertEqual(calls, [True])
        self.assertTrue(response.startswith(b"HTTP/1.0 403"), response[:200])
        self.assertTrue(response.endswith(b"\r\n\r\nforbidden"), "the client must receive the whole 403")

    def test_a_client_that_closes_mid_body_never_reaches_the_app_and_leaves_nothing(self):
        calls = []

        def app(environ, start_response):
            calls.append(True)
            start_response("200 OK", [])
            return [b"ok"]

        port = self._serve(SpoolRequestBody(app))
        body = _pattern(1024 * 1024)
        self._request(port, body, send=100 * 1024)
        self._wait_handled()
        self.assertEqual(calls, [], "a truncated body must not reach the application")
        self.assertEqual(len(self.spools), 1)
        self.assertTrue(self.spools[0].closed, "the spool of a truncated body must be closed")
        self.assertEqual(os.listdir(self.tmp.name), [], "the spool must leave nothing in the temp directory")
