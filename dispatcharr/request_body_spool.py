"""Read a request body completely before the application runs.

This is uWSGI's ``post-buffering`` done in Python, for the API process only.

Why it exists
-------------
uWSGI 2.0.31 keeps ONE harakiri deadline per worker, shared by every gevent
core on it. Each accept writes ``now + harakiri`` to it
(``plugins/gevent/gevent.c:242-245``) and each request close writes ``0``
(``core/utils.c:1119-1122``). With ``post-buffering`` set, reading a request
body calls ``inc_harakiri()``, which ADDS the interval to whatever is there
(``core/utils.c:45-52``, from ``core/reader.c:485-487`` and ``:558-561``). If a
neighbouring request on the same worker closed while the body-bearing request
waited for its headers, the deadline is 0 and becomes ``0 + 120``: a 1970
timestamp. The master then SIGKILLs the whole worker, and every request on
it, within a second (``core/master_checks.c:199``). So the two API inis drop
``post-buffering``.

Dropping it alone has a cost: a view that answers without reading a large
body (DRF authenticates before it parses, and Django does not drain an unread
body) leaves bytes on the socket, uWSGI closes it, and the client gets a
connection reset instead of the 4xx. Reading the body here first restores
what post-buffering did for the client, without the harakiri arithmetic.

Gate
----
Active only when ``DISPATCHARR_WSGI_SPOOL_REQUEST_BODY`` is exactly ``"1"``,
which only ``docker/uwsgi.ini`` and ``docker/uwsgi.modular.ini`` set (with
``env =``). Anything else, including unset, returns the application callable
unchanged: the relay and dev inis keep uWSGI's own post-buffering, and
``runserver``, Daphne and Celery never see the variable.

Behaviour
---------
* Only a request whose ``CONTENT_LENGTH`` parses as a positive integer is
  spooled, exactly the requests uWSGI's post-buffering acted on. A request
  with no, an empty or an unparseable ``CONTENT_LENGTH`` (a chunked body
  reaching the direct ``http`` listener) is passed through untouched, as
  post-buffering passed it through.
* Exactly ``CONTENT_LENGTH`` bytes are read. Bytes beyond it are never read,
  as before (``wsgi.input`` is bounded by it in uWSGI too).
* A body that ends early or whose read raises ``OSError`` (the client went
  away, or uWSGI's read timed out) is not given to the application: the
  answer is a bodiless ``400``, where uWSGI's post-buffering closed the
  connection without running the app. Nothing about the request is logged
  beyond the two byte counts.
* Up to 4096 bytes stay in memory (post-buffering's own threshold). Above
  that, the body rolls over to an anonymous temporary file in ``tempfile``'s
  directory (``TMPDIR``, else ``/tmp``: the container's writable layer). The
  file is unlinked at creation, so nothing is left on disk even if the worker
  is SIGKILLed; it is closed when the response iterable is closed, or at once
  if the application raises. Its size is the request's declared length, which
  is what uWSGI's own post-buffer file held before: no new bound and no new
  exposure.
* For a spooled request ``wsgi.file_wrapper`` is removed from the environ, so
  Django streams a ``FileResponse`` through its own iterator instead of handing
  uWSGI a sendfile object that the closing wrapper below would hide.
"""

import logging
import os
import tempfile

SPOOL_ENV = "DISPATCHARR_WSGI_SPOOL_REQUEST_BODY"
MEMORY_THRESHOLD = 4096
READ_CHUNK = 65536

logger = logging.getLogger(__name__)


def _declared_length(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        return 0
    return length if length > 0 else 0


def _cooperative_yield():
    """Give other greenlets a turn between chunks when gevent is running."""
    try:
        import gevent
    except ImportError:  # pragma: no cover - gevent is a main dependency
        return
    gevent.sleep(0)


class _ClosingResult:
    """The application's iterable, plus closing the spool when it is closed."""

    def __init__(self, result, spool):
        self._result = result
        self._spool = spool

    def __iter__(self):
        return iter(self._result)

    def close(self):
        try:
            close = getattr(self._result, "close", None)
            if close is not None:
                close()
        finally:
            self._spool.close()


class SpoolRequestBody:
    """WSGI middleware: read the declared body into a spool, then call the app."""

    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        length = _declared_length(environ)
        if not length:
            return self.application(environ, start_response)

        spool = tempfile.SpooledTemporaryFile(max_size=MEMORY_THRESHOLD)
        try:
            received = self._copy(environ["wsgi.input"], spool, length)
            if received < length:
                logger.info(
                    "Request body ended after %d of %d declared bytes; not passed to the application",
                    received,
                    length,
                )
                spool.close()
                start_response("400 Bad Request", [("Content-Length", "0")])
                return []
            spool.seek(0)
            environ["wsgi.input"] = spool
            environ.pop("wsgi.file_wrapper", None)
            result = self.application(environ, start_response)
        except BaseException:
            spool.close()
            raise
        return _ClosingResult(result, spool)

    @staticmethod
    def _copy(source, spool, length):
        received = 0
        while received < length:
            try:
                chunk = source.read(min(READ_CHUNK, length - received))
            except OSError:
                break
            if not chunk:
                break
            spool.write(chunk)
            received += len(chunk)
            _cooperative_yield()
        return received


def wrap(application, environ=None):
    """Return ``application`` spooled when the gate is on, else unchanged."""
    env = os.environ if environ is None else environ
    if env.get(SPOOL_ENV) == "1":
        return SpoolRequestBody(application)
    return application
