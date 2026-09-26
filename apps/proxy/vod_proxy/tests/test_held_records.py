"""The slot-holder registry and refresher (#513 constraints 4 and 5).

A VOD session hash or a busy catch-up pool entry counts toward the provider
slot only while the worker holding it is alive, and "alive" is a key the
worker's own refresher keeps setting -- never the record's recency, which a
paused player lets go stale while its provider connection stays open. These
run against the live Redis the suite already uses; without it they skip,
except under CI, where they fail.
"""

from __future__ import annotations

import os
import threading
import uuid
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.proxy.vod_proxy import held_records
from apps.proxy.vod_proxy.held_records import (
    REFRESH_INTERVAL_SECONDS,
    WORKER_KEY_TTL_SECONDS,
    HeldRecords,
    worker_key,
)


def _live_redis():
    from core.utils import RedisClient

    try:
        client = RedisClient.get_client(max_retries=1, retry_interval=0)
        if client is not None and client.ping():
            return client
    except Exception:
        pass
    return None


class HeldRecordsRealRedisTests(SimpleTestCase):
    redis = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.redis = _live_redis()

    def setUp(self):
        if self.redis is None:
            if os.environ.get("CI"):
                self.fail("Redis is not reachable under CI: these tests must run, not skip")
            self.skipTest("Redis not available")
        tag = uuid.uuid4().hex[:12]
        self.worker = f"test-host-{tag}"
        self.vod_key = f"vod_persistent_connection:held-{tag}"
        self.pool_key = f"timeshift:pool:held-{tag}"
        self.records = HeldRecords(self.redis, self.worker)

    def tearDown(self):
        if self.redis is not None:
            self.redis.delete(self.vod_key, self.pool_key, worker_key(self.worker))

    def test_refresh_sets_the_worker_liveness_key_with_a_short_ttl(self):
        self.assertEqual(self.records.refresh_once(), 0)
        self.assertEqual(self.redis.get(worker_key(self.worker)), self.worker)
        ttl = self.redis.ttl(worker_key(self.worker))
        self.assertTrue(0 < ttl <= WORKER_KEY_TTL_SECONDS, ttl)
        # Several refresh periods fit inside one TTL, so one missed beat is not a death.
        self.assertGreaterEqual(WORKER_KEY_TTL_SECONDS, 3 * REFRESH_INTERVAL_SECONDS)

    def test_a_held_vod_session_outlives_its_own_ttl_while_held(self):
        # The paused viewer: the hash is about to expire and nothing in the
        # chunk loop will refresh it, because the loop is not running.
        self.redis.hset(self.vod_key, mapping={"active_streams": "1", "worker_id": "someone-else"})
        self.redis.expire(self.vod_key, 5)
        token = self.records.hold(self.vod_key, ttl=3600)
        self.assertEqual(self.records.refresh_once(), 1)
        self.assertGreater(self.redis.ttl(self.vod_key), 3000)
        # ...and the record now names the worker that actually holds it.
        self.assertEqual(self.redis.hget(self.vod_key, "worker_id"), self.worker)
        self.records.release(token)
        self.redis.expire(self.vod_key, 5)
        self.assertEqual(self.records.refresh_once(), 0)
        self.assertLessEqual(self.redis.ttl(self.vod_key), 5)

    def test_a_catch_up_entry_is_refreshed_only_while_busy(self):
        self.redis.hset(self.pool_key, mapping={"busy": "1", "profile_id": "7"})
        self.redis.expire(self.pool_key, 5)
        self.records.hold(self.pool_key, ttl=600, busy_field="busy")
        self.assertEqual(self.records.refresh_once(), 1)
        self.assertGreater(self.redis.ttl(self.pool_key), 500)
        # Released to idle (busy=0, the 60 s idle TTL): the refresher must not
        # stretch an idle entry back to the busy TTL.
        self.redis.hset(self.pool_key, "busy", "0")
        self.redis.expire(self.pool_key, 60)
        self.assertEqual(
            self.records.refresh_once(), 0,
            "an idle catch-up entry was refreshed to the busy TTL",
        )
        self.assertLessEqual(self.redis.ttl(self.pool_key), 60)

    def test_a_record_already_gone_is_not_recreated(self):
        self.records.hold(self.vod_key, ttl=3600)
        self.assertEqual(self.records.refresh_once(), 0)
        self.assertEqual(self.redis.exists(self.vod_key), 0)

    def test_holding_registers_from_the_first_item_until_the_end_or_close(self):
        def gen():
            yield b"a"
            yield b"b"

        wrapped = self.records.holding(self.vod_key, gen(), ttl=3600)
        self.assertEqual(self.records.held_keys(), [])  # nothing until iterated
        self.assertEqual(next(wrapped), b"a")
        self.assertEqual(self.records.held_keys(), [self.vod_key])
        self.assertEqual(list(wrapped), [b"b"])
        self.assertEqual(self.records.held_keys(), [])

        closed = []

        def gen2():
            try:
                yield b"a"
                yield b"b"
            finally:
                closed.append(True)

        wrapped = self.records.holding(self.vod_key, gen2(), ttl=3600)
        next(wrapped)
        wrapped.close()
        self.assertEqual(closed, [True], "close() did not reach the wrapped generator")
        self.assertEqual(self.records.held_keys(), [])


class HeldRecordsLoopTests(SimpleTestCase):
    """The refresher never dies of an exception and starts only when enabled."""

    def test_refresh_once_swallows_a_redis_failure_and_logs_once(self):
        broken = mock.MagicMock()
        broken.register_script.side_effect = ConnectionError("redis went away")
        records = HeldRecords(broken, "w1")
        with self.assertLogs(held_records.logger, "WARNING") as logs:
            self.assertEqual(records.refresh_once(), -1)
            self.assertEqual(records.refresh_once(), -1)
        self.assertEqual(len(logs.records), 1, "a failure streak should log once, not every beat")

    def test_recovery_after_a_failure_streak_logs_once(self):
        client = mock.MagicMock()
        script = mock.MagicMock()
        script.side_effect = [ConnectionError("redis went away"), 0, 0]
        client.register_script.return_value = script
        records = HeldRecords(client, "w1")
        with self.assertLogs(held_records.logger, "WARNING"):
            self.assertEqual(records.refresh_once(), -1)
        with self.assertLogs(held_records.logger, "INFO") as logs:
            self.assertEqual(records.refresh_once(), 0)
        self.assertEqual(len(logs.records), 1, "a recovery should log once, not every beat")
        self.assertIn("recovered", logs.records[0].getMessage())
        # "not every beat" is the claim above: a second success beat, still
        # inside the same non-failing run, must log nothing at INFO. Without
        # this, deleting the `self._failing = False` reset would still pass
        # the two assertions above (only the FIRST success logs regardless),
        # leaving the "once" half of the claim unpinned.
        with self.assertNoLogs(held_records.logger, "INFO"):
            self.assertEqual(records.refresh_once(), 0)

    def test_the_loop_keeps_going_after_an_iteration_raises(self):
        records = HeldRecords(mock.MagicMock(), "w1")
        calls = []

        class Stop(BaseException):
            pass

        def refresh():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("an iteration blew up")
            return 0

        def sleep(_seconds):
            if len(calls) >= 3:
                raise Stop

        with mock.patch.object(records, "refresh_once", side_effect=refresh), \
                mock.patch.object(held_records.time, "sleep", side_effect=sleep), \
                self.assertLogs(held_records.logger, "ERROR"):
            with self.assertRaises(Stop):
                records._run()
        self.assertEqual(len(calls), 3, "the refresher stopped after an iteration raised")

    @override_settings(SLOT_HOLDER_REFRESHER_ENABLED=True)
    def test_the_first_hold_starts_one_refresher_thread(self):
        records = HeldRecords(mock.MagicMock(), "w1")
        with mock.patch.object(held_records.threading, "Thread") as thread:
            records.hold("k1", ttl=10)
            records.hold("k2", ttl=10)
        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["name"], "slot-holder-refresher")
        self.assertTrue(thread.call_args.kwargs["daemon"])
        thread.return_value.start.assert_called_once_with()

    def test_no_refresher_thread_in_tests(self):
        records = HeldRecords(mock.MagicMock(), "w1")
        with mock.patch.object(held_records.threading, "Thread") as thread:
            records.hold("k1", ttl=10)
        thread.assert_not_called()

    def test_this_process_is_one_registry_shared_by_every_caller(self):
        self.assertIs(held_records.this_process(), held_records.this_process())

    def test_the_vod_manager_and_catch_up_record_the_same_worker_id(self):
        from apps.proxy.vod_proxy.multi_worker_connection_manager import (
            MultiWorkerVODConnectionManager,
        )

        manager = MultiWorkerVODConnectionManager.__new__(MultiWorkerVODConnectionManager)
        self.assertEqual(manager._get_worker_id(), held_records.current_worker_id())
        self.assertEqual(held_records.current_worker_id(), f"{__import__('socket').gethostname()}-{os.getpid()}")


class VodStreamHoldsItsSessionTests(SimpleTestCase):
    """stream_content_with_session's response holds the session hash while it streams."""

    def test_the_session_is_held_from_the_first_chunk_until_the_stream_ends(self):
        from apps.proxy.vod_proxy.tests.test_vod_range_responses import VodRangeResponseTests

        case = VodRangeResponseTests("test_a_provider_416_on_a_first_request_was_a_500")
        case.setUp()
        response = None
        try:
            response = case._get(None)
            self.assertEqual(response.status_code, 200)
            key = f"vod_persistent_connection:{case.SESSION}"
            registry = held_records.this_process()
            self.assertNotIn(key, registry.held_keys())
            chunks = iter(response.streaming_content)
            next(chunks)
            self.assertIn(key, registry.held_keys(), "a streaming VOD response did not hold its session")
            self.assertIn(
                (key, 3600, ""), registry.held_entries(),
                "a streaming VOD response held its session with the wrong TTL or a busy guard",
            )
            list(chunks)
            self.assertNotIn(key, registry.held_keys())
        finally:
            # On a failing assertion above, the generator is otherwise never
            # consumed or closed here: it only finalises on garbage
            # collection, after doCleanups() has already undone the
            # harness's Redis/upstream patches, and that late finalisation
            # logs a stray "Unknown VOD script" ERROR (round 1 nit 2).
            # Closing it explicitly, before doCleanups(), keeps the failure
            # path from leaking either the log line or the held key.
            if response is not None:
                response.close()
            case.doCleanups()
