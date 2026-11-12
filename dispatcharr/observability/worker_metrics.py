"""Recording side of the Python worker metrics M11 to M14 (spec D14, D16).

M11 is recorded in every Celery process that runs tasks. M12 to M14 are
observable gauges registered only by the beat process (one per deployment, not
forked), so a gauge cannot be reported stale by each of N children. A gauge
callback only reads: it never writes a provider-slot counter (#513).

Attribute values here are closed sets or digits: a task name, one of four
outcomes, one of two queue names, a numeric profile id. Nothing derived from a
URL, a channel UUID or a user reaches an instrument. Nothing under ``apps.*``
is imported at module level (the boot trap, spec constraint 6).
"""
import logging
import time

logger = logging.getLogger(__name__)

_QUEUES = ("celery", "dvr")
_OUTCOMES = frozenset({"SUCCESS", "FAILURE", "RETRY", "REVOKED"})
_MAX_STARTED = 10000  # a task whose task_postrun never fires must not grow this forever
_started = {}
_histogram = None
_beat_registered = False
_pending_limit = None  # M14's observations, computed by M13's callback in the same collection
_failing = set()  # callbacks whose last run failed: log the first failure of a streak only


def _warn_once(what, exc):
    if what not in _failing:
        _failing.add(what)
        logger.warning("%s could not be read (%s)", what, type(exc).__name__)


def _task_histogram():
    global _histogram
    if _histogram is None:
        from . import metrics

        _histogram = metrics.task_duration_histogram()
    return _histogram


def task_started(task_id):
    if len(_started) >= _MAX_STARTED:
        _started.pop(next(iter(_started)), None)
    _started[task_id] = time.monotonic()


def task_finished(task_id, task_name, state):
    """Record one M11 point. Never raises: a metric must not fail a task."""
    began = _started.pop(task_id, None)
    # Celery also sends IGNORED and REJECTED; the catalogue's outcome set is closed.
    if began is None or not task_name or state not in _OUTCOMES:
        return
    try:
        _task_histogram().record(
            time.monotonic() - began, {"task": task_name, "outcome": state}
        )
    except Exception:
        logger.debug("recording the task duration failed", exc_info=True)


def _queue_depths():
    """{queue: LLEN}, on a broker connection that is released before returning."""
    from dispatcharr.celery import app

    with app.connection_for_read() as connection:
        client = connection.default_channel.client
        return {queue: int(client.llen(queue) or 0) for queue in _QUEUES}


def _redis_client():
    from core.utils import RedisClient

    return RedisClient.get_client()


def observe_queue_depth(_options=None):
    from opentelemetry.metrics import Observation

    try:
        depths = _queue_depths()
    except Exception as exc:
        _warn_once("queue depth", exc)
        return []
    _failing.discard("queue depth")
    return [Observation(depth, {"queue": queue}) for queue, depth in depths.items()]


def _active_profiles():
    from django.db import connections

    from apps.m3u.models import M3UAccountProfile

    try:
        return list(
            M3UAccountProfile.objects.filter(is_active=True).values_list("id", "max_streams")
        )
    finally:
        connections.close_all()


def _slot_observations():
    """(in_use, limit) lists of Observations, one read of the rows and one MGET."""
    from opentelemetry.metrics import Observation

    from apps.m3u.connection_pool import profile_connections_key

    rows = _active_profiles()
    if not rows:
        return [], []
    values = _redis_client().mget([profile_connections_key(pk) for pk, _ in rows])
    in_use, limit = [], []
    for (pk, max_streams), raw in zip(rows, values):
        attrs = {"m3u_profile_id": str(pk)}
        in_use.append(Observation(int(raw or 0), attrs))
        limit.append(Observation(int(max_streams or 0), attrs))
    return in_use, limit


def observe_slots_in_use(_options=None):
    """M13. Also computes M14's observations, so one collection reads rows and Redis once."""
    global _pending_limit
    _pending_limit = None
    try:
        in_use, limit = _slot_observations()
    except Exception as exc:
        _warn_once("provider slots", exc)
        return []
    _failing.discard("provider slots")
    _pending_limit = limit
    return in_use


def observe_slots_limit(_options=None):
    global _pending_limit
    limit, _pending_limit = _pending_limit, None
    if limit is not None:
        return limit
    try:
        return _slot_observations()[1]
    except Exception as exc:
        _warn_once("provider slots", exc)
        return []


def register_beat_gauges():
    """Register M12 to M14 on the worker meter. Called from ``beat_init`` only."""
    global _beat_registered
    if _beat_registered:
        return
    _beat_registered = True
    from . import metrics

    meter = metrics.get_meter()
    meter.create_observable_gauge(
        metrics.M12_NAME, callbacks=[observe_queue_depth], unit="{message}",
        description="Messages waiting in a Celery queue",
    )
    meter.create_observable_gauge(
        metrics.M13_NAME, callbacks=[observe_slots_in_use], unit="{slot}",
        description="Provider slots in use per M3U profile",
    )
    meter.create_observable_gauge(
        metrics.M14_NAME, callbacks=[observe_slots_limit], unit="{slot}",
        description="Provider slot limit per M3U profile (0 is unlimited)",
    )
