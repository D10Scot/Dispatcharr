"""A busy catch-up pool entry names the process holding it (#513 constraint 5).

The provider-slot reconciler counts a busy entry only while its worker's
liveness key exists, so the entry must say which worker that is -- at
creation, and again when an idle entry is taken back into use -- and a
streaming response must hold the entry for its whole life.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.proxy.vod_proxy import held_records
from apps.timeshift import views
from apps.timeshift.redis_keys import TimeshiftRedisKeys
from apps.timeshift.tests.test_views import (
    _FakeRedis,
    _fake_upstream,
    _seed_pool_session,
)


class PoolEntryWorkerIdTests(TestCase):
    def test_a_created_entry_records_this_process(self):
        redis = _FakeRedis()
        _seed_pool_session(redis, session_id="s1")
        self.assertEqual(
            redis.hget(TimeshiftRedisKeys.pool("s1"), "worker_id"),
            held_records.current_worker_id(),
        )

    def test_an_idle_entry_taken_back_records_the_process_taking_it(self):
        redis = _FakeRedis()
        _seed_pool_session(redis, session_id="s1", busy="0")
        redis.hset(TimeshiftRedisKeys.pool("s1"), "worker_id", "host-that-died-1")
        profile = MagicMock(id=31)
        with patch.object(views.M3UAccountProfile.objects, "get", return_value=profile), \
                patch.object(views, "reserve_profile_slot", return_value=(True, 1, None)):
            acquired = views._acquire_idle_pool_session(redis, "s1")
        self.assertIsNotNone(acquired)
        self.assertEqual(
            redis.hget(TimeshiftRedisKeys.pool("s1"), "worker_id"),
            held_records.current_worker_id(),
        )


class CatchupStreamHoldsItsPoolEntryTests(TestCase):
    def test_the_pool_entry_is_held_from_the_first_chunk_until_close(self):
        # Imported here, not at module level: a TestCase class in this
        # module's namespace would be collected and run a second time.
        from apps.timeshift.tests.test_views import StreamFromProviderStatusMappingTests

        fixture = StreamFromProviderStatusMappingTests("test_all_candidates_404_returns_404")
        fixture.setUp()
        kwargs = dict(fixture.kwargs, pool_session_id="pool-s1")
        upstream = _fake_upstream(200)
        key = TimeshiftRedisKeys.pool("pool-s1")
        registry = held_records.this_process()
        with patch.object(views, "_open_upstream", return_value=upstream), \
                patch.object(views, "_iter_upstream_with_stop", return_value=iter([b"a", b"b"])), \
                patch.object(views, "RedisClient"), \
                patch.object(views, "_register_stats_client"), \
                patch.object(views, "_unregister_stats_client"):
            response = views._stream_from_provider(**kwargs)
            self.assertEqual(response.status_code, 200)
            chunks = iter(response.streaming_content)
            next(chunks)
            self.assertIn(key, registry.held_keys(), "a streaming catch-up response did not hold its pool entry")
            self.assertIn(
                (key, 600, "busy"), registry.held_entries(),
                "a streaming catch-up response held its pool entry without the busy guard or the busy TTL",
            )
            response.close()
        self.assertNotIn(key, registry.held_keys())
