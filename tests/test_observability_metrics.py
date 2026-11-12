"""Observability spec O6 / D16: M11 (task duration) and beat-only M12 to M14."""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.m3u.connection_pool import profile_connections_key
from apps.m3u.models import M3UAccount, M3UAccountProfile
from dispatcharr.observability import metrics, worker_metrics
from tests.otel_rig import SENTINEL, SENTINEL_UUID, Rig


class _RigCase:
    def _install_rig(self):
        self.rig = Rig()
        self.addCleanup(self.rig.teardown)
        meter = self.rig.meter_provider.get_meter(metrics.SCOPE_NAME)
        patcher = patch.object(metrics, "get_meter", return_value=meter)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(worker_metrics, "_histogram", None)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(worker_metrics, "_beat_registered", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _points(self):
        self.rig.flush_metrics()
        return self.rig.metric_sink.points()


class TaskDurationTests(_RigCase, SimpleTestCase):
    def test_one_point_per_task_with_task_and_outcome(self):
        self._install_rig()
        worker_metrics.task_started("t1")
        worker_metrics.task_finished("t1", "apps.m3u.tasks.refresh", "SUCCESS")
        worker_metrics.task_started("t2")
        worker_metrics.task_finished("t2", "apps.m3u.tasks.refresh", "FAILURE")
        points = self._points()[metrics.M11_NAME]
        self.assertCountEqual(
            points,
            [
                {"task": "apps.m3u.tasks.refresh", "outcome": "SUCCESS"},
                {"task": "apps.m3u.tasks.refresh", "outcome": "FAILURE"},
            ],
        )

    def test_the_recorded_value_is_the_elapsed_time_once(self):
        self._install_rig()
        clock = MagicMock()
        clock.monotonic.side_effect = [10.0] + [12.5] * 5
        with patch.object(worker_metrics, "time", clock):
            worker_metrics.task_started("v1")
            worker_metrics.task_finished("v1", "apps.m3u.tasks.refresh", "SUCCESS")
        self.rig.flush_metrics()
        (point,) = [
            p
            for rm in self.rig.metric_sink.exports[-1].resource_metrics
            for sm in rm.scope_metrics
            for m in sm.metrics
            if m.name == metrics.M11_NAME
            for p in m.data.data_points
        ]
        self.assertEqual((point.count, point.sum), (1, 2.5))

    def test_a_state_outside_the_four_outcomes_records_nothing(self):
        self._install_rig()
        for state in ("IGNORED", "REJECTED", None):
            worker_metrics.task_started("s")
            worker_metrics.task_finished("s", "apps.m3u.tasks.refresh", state)
        self.assertNotIn(metrics.M11_NAME, self._points())

    def test_a_task_that_never_started_records_nothing(self):
        self._install_rig()
        worker_metrics.task_finished("never", "apps.m3u.tasks.refresh", "SUCCESS")
        self.assertNotIn(metrics.M11_NAME, self._points())

    def test_the_celery_handlers_drive_it(self):
        self._install_rig()
        from dispatcharr.celery import cleanup_task_memory, reset_db_connection_before_task

        task = MagicMock()
        task.name = "apps.m3u.tasks.refresh"
        with patch("django.db.close_old_connections"):
            reset_db_connection_before_task(task_id="h1", task=task)
            cleanup_task_memory(task_id="h1", task=task, state="RETRY")
        self.assertEqual(
            self._points()[metrics.M11_NAME], [{"task": "apps.m3u.tasks.refresh", "outcome": "RETRY"}]
        )

    def test_a_uuid_or_credential_in_a_task_name_or_outcome_never_exports(self):
        self._install_rig()
        for task_id, name, state in (
            ("u1", f"tasks.{SENTINEL_UUID}", "SUCCESS"),
            ("u2", f"https://user:{SENTINEL}@provider.invalid/x", "SUCCESS"),
            ("u3", "apps.m3u.tasks.refresh", SENTINEL),
        ):
            worker_metrics.task_started(task_id)
            worker_metrics.task_finished(task_id, name, state)
        self.rig.flush_metrics()
        dumped = repr([e for e in self.rig.metric_sink.exports])
        for needle in (SENTINEL, SENTINEL_UUID):
            self.assertIn(needle, repr(self.rig.raw_metric_sink.exports), "control: the raw reader saw it")
            self.assertNotIn(needle, dumped)


class BeatGaugeTests(_RigCase, TestCase):
    def test_queue_depth_reports_llen_per_queue_from_the_broker_client(self):
        self._install_rig()
        depths = {"celery": 7, "dvr": 2}
        with patch.object(worker_metrics, "_queue_depths", return_value=depths), \
             patch.object(worker_metrics, "_slot_observations", return_value=([], [])):
            worker_metrics.register_beat_gauges()
            exported = {p["queue"] for p in self._points()[metrics.M12_NAME]}
            observed = {o.attributes["queue"]: o.value for o in worker_metrics.observe_queue_depth()}
        self.assertEqual(exported, {"celery", "dvr"})
        self.assertEqual(observed, {"celery": 7, "dvr": 2})

    def test_slots_report_in_use_and_limit_per_active_profile_and_close_the_db(self):
        self._install_rig()
        account = M3UAccount.objects.create(name="o6-acct")
        active = M3UAccountProfile.objects.create(m3u_account=account, name="a", max_streams=3, is_active=True)
        M3UAccountProfile.objects.create(m3u_account=account, name="off", max_streams=9, is_active=False)
        redis_client = MagicMock()
        redis_client.mget.return_value = [b"2"] * M3UAccountProfile.objects.filter(is_active=True).count()
        with patch.object(worker_metrics, "_redis_client", return_value=redis_client), \
             patch("django.db.connections.close_all") as close_all:
            observed_in_use = worker_metrics.observe_slots_in_use()
            observed_limit = worker_metrics.observe_slots_limit()
        self.assertTrue(close_all.called, "the callback must close its DB connection")
        self.assertEqual(redis_client.mget.call_count, 1, "M13 and M14 must share one read per collection")
        mine = str(active.id)
        self.assertIn((mine, 2), [(o.attributes["m3u_profile_id"], o.value) for o in observed_in_use])
        self.assertIn((mine, 3), [(o.attributes["m3u_profile_id"], o.value) for o in observed_limit])
        keys = redis_client.mget.call_args_list[0].args[0]
        self.assertIn(profile_connections_key(active.id), keys)
        self.assertTrue(all(o.attributes["m3u_profile_id"].isdigit() for o in observed_in_use))
        redis_client.set.assert_not_called()
        redis_client.incr.assert_not_called()

    def test_a_non_digit_profile_label_never_exports(self):
        self._install_rig()
        from opentelemetry.metrics import Observation

        with patch.object(
            worker_metrics, "_slot_observations",
            return_value=([Observation(1, {"m3u_profile_id": SENTINEL_UUID})], []),
        ):
            worker_metrics.register_beat_gauges()
            points = self._points()
        self.assertNotIn(SENTINEL_UUID, repr(self.rig.metric_sink.exports))
        self.assertIn(SENTINEL_UUID, repr(self.rig.raw_metric_sink.exports), "control")
        self.assertFalse(points.get(metrics.M13_NAME))

    def test_a_broker_failure_is_swallowed(self):
        with patch.object(worker_metrics, "_queue_depths", side_effect=RuntimeError("down")):
            self.assertEqual(worker_metrics.observe_queue_depth(), [])
            self.assertEqual(worker_metrics.observe_queue_depth(), [])


class _FakeConnection:
    """A kombu Connection stand-in that counts opens and releases."""

    opened = 0
    closed = 0

    def __init__(self):
        self.default_channel = MagicMock()
        self.default_channel.client.llen.side_effect = lambda q: {"celery": 4, "dvr": 1}[q]

    def __enter__(self):
        type(self).opened += 1
        return self

    def __exit__(self, *exc):
        type(self).closed += 1


class BrokerConnectionTests(SimpleTestCase):
    def test_repeated_collections_release_every_connection_they_open(self):
        _FakeConnection.opened = _FakeConnection.closed = 0
        from dispatcharr.celery import app

        with patch.object(app, "connection_for_read", side_effect=_FakeConnection):
            for _ in range(3):
                observed = {o.attributes["queue"]: o.value for o in worker_metrics.observe_queue_depth()}
        self.assertEqual(observed, {"celery": 4, "dvr": 1})
        self.assertEqual(_FakeConnection.opened, 3)
        self.assertEqual(
            _FakeConnection.closed, _FakeConnection.opened,
            f"{_FakeConnection.opened - _FakeConnection.closed} broker connection(s) left open",
        )


class WhereTheGaugesAreRegisteredTests(SimpleTestCase):
    def test_beat_registers_them_and_a_worker_does_not(self):
        from dispatcharr import celery as celery_module

        with patch("dispatcharr.observability.worker_metrics.register_beat_gauges") as register, \
             patch("dispatcharr.observability.bootstrap.init"), \
             patch("django.db.connections.close_all"), \
             patch("apps.plugins.loader.PluginManager.get"):
            celery_module.init_worker_process()
            celery_module.init_worker_threads_telemetry(sender=MagicMock(pool_cls="threads"))
            self.assertFalse(register.called, "a worker process registered a beat-only gauge")
            celery_module.init_beat_telemetry()
            register.assert_called_once()
