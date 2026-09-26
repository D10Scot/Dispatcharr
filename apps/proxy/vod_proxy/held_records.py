"""Which provider-slot records this process holds, and a positive signal that it is alive (#513).

A VOD session hash (vod_persistent_connection:<session>) and a catch-up pool
entry (timeshift:pool:<session>) each stand for one open provider connection,
and each carries the worker that holds it (`worker_id`, hostname-PID). The
provider-slot reconciler (apps/proxy/slot_reconciler.py) counts such a record
as a holder only while that worker's liveness key exists -- NOT while the
record looks recent. Recency is the wrong signal: a paused player stops
reading, its generator sits suspended at a `yield`, no chunk loop runs, and
`last_activity` goes stale while the provider connection stays open and still
occupies the provider's slot (mwcm.py's chunk loop, timeshift/views.py's
post-yield heartbeat).

So each relay-uwsgi process runs one refresher, off the request path, that
every REFRESH_INTERVAL_SECONDS:

- sets `vod:worker:<worker_id>` with a WORKER_KEY_TTL_SECONDS expiry, and
- re-EXPIREs every record this process's generators currently hold, and
  re-stamps the record's `worker_id` with this process, so a pause longer than
  the record's own TTL no longer makes a live holder invisible, and a session
  another worker took over and then lost is claimed back by the one still
  holding it.

It is one Lua script per iteration, so one round trip however many records.

Under gevent the refresher is a greenlet on the one OS thread the process has
(threading is monkey-patched). A hub stall longer than WORKER_KEY_TTL_SECONDS
makes a live worker read as dead; the reconciler drops a holder only after it
has been absent from two consecutive runs, so a stall must outlast the TTL
plus a whole run interval before a count moves. A refresher that died would
be the other failure, so every iteration catches and logs its own exception
and the loop goes on. The greenlet dies with its process, which is the point:
the key then lapses on its own and the reconciler reads that worker as gone.

Tests never start the thread: `SLOT_HOLDER_REFRESHER_ENABLED` is False in
dispatcharr/settings_test.py, and the tests call refresh_once() directly.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time

from django.conf import settings

logger = logging.getLogger(__name__)

WORKER_KEY_PREFIX = "vod:worker:"
WORKER_KEY_TTL_SECONDS = 60
REFRESH_INTERVAL_SECONDS = 10

_REFRESH_SCRIPT = """
-- held_records_refresh
-- KEYS[1]: this worker's liveness key; KEYS[2..]: records this worker holds.
-- ARGV[1]: worker id; ARGV[2]: liveness TTL; then per record a TTL and the
-- name of a field that must read '1' for the record to be refreshed ('' = none).
redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
local refreshed = 0
for i = 2, #KEYS do
  local ttl = tonumber(ARGV[2 * i - 1])
  local busy = ARGV[2 * i]
  if redis.call('EXISTS', KEYS[i]) == 1 then
    if busy == '' or redis.call('HGET', KEYS[i], busy) == '1' then
      redis.call('EXPIRE', KEYS[i], ttl)
      redis.call('HSET', KEYS[i], 'worker_id', ARGV[1])
      refreshed = refreshed + 1
    end
  end
end
return refreshed
"""


def current_worker_id() -> str:
    """This process's holder id: hostname-PID, what VOD hashes always carried."""
    try:
        return f"{socket.gethostname()}-{os.getpid()}"
    except Exception:
        return f"worker-{os.getpid()}"


def worker_key(worker_id: str) -> str:
    return f"{WORKER_KEY_PREFIX}{worker_id}"


class HeldRecords:
    """The records one process's streaming generators hold, and their refresher."""

    def __init__(self, redis_client=None, worker_id=None):
        self._redis_client = redis_client
        self._worker_id = worker_id
        self._held = {}
        self._lock = threading.Lock()
        self._started = False
        self._failing = False

    @property
    def worker_id(self) -> str:
        return self._worker_id or current_worker_id()

    def _client(self):
        if self._redis_client is None:
            from core.utils import RedisClient

            self._redis_client = RedisClient.get_client()
        return self._redis_client

    def hold(self, key: str, *, ttl: int, busy_field: str = "") -> object:
        """Register `key` as held by this process until release(token)."""
        token = object()
        with self._lock:
            self._held[token] = (key, int(ttl), busy_field)
        self._ensure_started()
        return token

    def release(self, token) -> None:
        with self._lock:
            self._held.pop(token, None)

    def held_keys(self):
        with self._lock:
            return sorted({key for key, _ttl, _busy in self._held.values()})

    def held_entries(self):
        """Every (key, ttl, busy_field) held, as the refresher will refresh it."""
        with self._lock:
            return sorted(set(self._held.values()))

    def holding(self, key: str, iterable, *, ttl: int, busy_field: str = ""):
        """Yield from `iterable`, holding `key` from the first item until it ends or closes.

        A generator, so nothing is registered for a response that is never
        iterated; `yield from` hands close() and exceptions to the wrapped
        generator exactly as a direct close would.
        """
        token = self.hold(key, ttl=ttl, busy_field=busy_field)
        try:
            yield from iterable
        finally:
            self.release(token)

    def refresh_once(self) -> int:
        """One refresher iteration. Never raises; returns records refreshed, or -1."""
        try:
            with self._lock:
                records = list(self._held.values())
            by_key = {}
            for key, ttl, busy in records:
                previous = by_key.get(key)
                by_key[key] = (max(ttl, previous[0]) if previous else ttl, busy)
            keys = [worker_key(self.worker_id)] + list(by_key)
            args = [self.worker_id, WORKER_KEY_TTL_SECONDS]
            for ttl, busy in by_key.values():
                args += [ttl, busy]
            client = self._client()
            refreshed = int(client.register_script(_REFRESH_SCRIPT)(keys=keys, args=args))
            if self._failing:
                logger.info("Slot-holder refresher for %s recovered", self.worker_id)
                self._failing = False
            return refreshed
        except Exception as exc:
            if not self._failing:
                logger.warning(
                    "Slot-holder refresher for %s failed; retrying every %ss: %s",
                    self.worker_id, REFRESH_INTERVAL_SECONDS, type(exc).__name__,
                )
                self._failing = True
            return -1

    def _run(self) -> None:
        while True:
            try:
                self.refresh_once()
            except Exception:  # refresh_once already catches; belt and braces
                logger.exception("Slot-holder refresher iteration raised")
            time.sleep(REFRESH_INTERVAL_SECONDS)

    def _ensure_started(self) -> None:
        if self._started or not getattr(settings, "SLOT_HOLDER_REFRESHER_ENABLED", True):
            return
        with self._lock:
            if self._started:
                return
            self._started = True
        thread = threading.Thread(target=self._run, name="slot-holder-refresher", daemon=True)
        thread.start()


_process_records = None
_process_lock = threading.Lock()


def this_process() -> HeldRecords:
    """The one HeldRecords of this process, shared by VOD and catch-up."""
    global _process_records
    if _process_records is None:
        with _process_lock:
            if _process_records is None:
                _process_records = HeldRecords()
    return _process_records
