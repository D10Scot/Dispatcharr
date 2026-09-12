"""Record every SQL statement the process executes, and say who made it.

WHY NOT CaptureQueriesContext (plan 2b-3, Ruling R5). It binds to
django.db.connections for the CALLING thread. RelayHarnessTestCase is a
LiveServerTestCase, so the relay's code runs on the WSGI server's
threads: a per-connection context in a test body captures nothing from a
tune and passes vacuously -- the same shape as a substring that matches
nothing. Patching CursorWrapper at class level is process-global and
sees every thread.

HOW A QUERY IS ATTRIBUTED (Ruling R6). The harness runs one process
serving both planes: the relay's stream_ts calls control_plane.next_
source(), which makes a real HTTP request back to the same server, where
Django's /api/relay/ view issues a dozen legitimate control-plane
queries. The HTTP boundary breaks the Python stack, and that is the
discriminator -- a query belongs to the relay iff some frame in its
stack is a file under apps/proxy/live_proxy/ that is not under a tests/
directory.

CONSEQUENCE FOR CALLERS: drive TRUSTED tunes only. An untrusted tune
runs authorize_stream inline from a live_proxy frame and would be
attributed to the relay, where production runs that hop in the API
process behind nginx's auth_request.
"""

import threading
import traceback
from collections import namedtuple
from contextlib import contextmanager

from django.db.backends.utils import CursorWrapper

RELAY_PREFIX = "/apps/proxy/live_proxy/"

# params, not just sql: the SQL text carries placeholders, so two
# queries against the same table are byte-identical however different
# the rows they ask for. Task 4's follower drive distinguishes itself
# from the owner drive by the OutputProfile id it asks for, and that id
# is only visible here. Failure messages print sql and never params, so
# a later non-test use of this helper cannot widen what gets logged.
Query = namedtuple("Query", "sql params relay_frames")

_lock = threading.Lock()


def _relay_frames():
    frames = []
    for frame in traceback.extract_stack():
        name = frame.filename.replace("\\", "/")
        if RELAY_PREFIX not in name:
            continue
        tail = name.split(RELAY_PREFIX, 1)[1]
        if tail.startswith("tests/") or "/tests/" in tail:
            continue
        frames.append(f"{tail}:{frame.lineno}")
    return frames


@contextmanager
def capture_queries():
    captured = []
    real_execute = CursorWrapper.execute
    real_executemany = CursorWrapper.executemany

    def record(sql, params):
        with _lock:
            captured.append(Query(str(sql), repr(params), tuple(_relay_frames())))

    def execute(self, sql, params=None):
        record(sql, params)
        return real_execute(self, sql, params)

    def executemany(self, sql, param_list):
        record(sql, param_list)
        return real_executemany(self, sql, param_list)

    CursorWrapper.execute = execute
    CursorWrapper.executemany = executemany
    try:
        yield captured
    finally:
        CursorWrapper.execute = real_execute
        CursorWrapper.executemany = real_executemany


def relay_queries(captured):
    return [q for q in captured if q.relay_frames]
