"""Observability spec D10: where each Celery process kind initialises OpenTelemetry.

``worker_process_init`` is sent by the prefork and solo pools only. The thread
pool (the ``dvr`` worker) forks nothing and sends nothing, so it initialises in
``worker_init``, and only when the configured pool is the thread pool. The
tests drive Celery's own startup path: ``app.WorkController(pool=...)`` sends
``worker_init`` from its constructor with the pool still named, unresolved.
"""
from unittest import mock

from django.test import SimpleTestCase

from dispatcharr.celery import app


def _controller(pool):
    return app.WorkController(pool=pool, hostname=f"otel-test-{pool}@host")


class CeleryOtelInitTests(SimpleTestCase):
    def test_the_threads_pool_runs_init_once_through_worker_init(self):
        with mock.patch("dispatcharr.observability.bootstrap.init") as init:
            _controller("threads")
        init.assert_called_once_with("mino-worker", "celery-dvr")

    def test_the_prefork_pool_does_not_run_init_in_the_parent(self):
        with mock.patch("dispatcharr.observability.bootstrap.init") as init:
            _controller("prefork")
        init.assert_not_called()

    def test_worker_process_init_runs_init_in_each_prefork_child(self):
        from celery.signals import worker_process_init

        with mock.patch("dispatcharr.observability.bootstrap.init") as init, mock.patch(
            "apps.plugins.loader.PluginManager.get"
        ), mock.patch("django.db.connections.close_all"):
            worker_process_init.send(sender=None)
        init.assert_called_once_with("mino-worker", "celery-default")

    def test_beat_init_names_the_beat_program(self):
        from celery.signals import beat_init

        with mock.patch("dispatcharr.observability.bootstrap.init") as init:
            beat_init.send(sender=None)
        init.assert_called_once_with("mino-worker", "celery-beat")

    def test_the_thread_pool_check_accepts_the_name_and_the_class_only(self):
        from celery.concurrency.thread import TaskPool as ThreadPool
        from celery.concurrency.prefork import TaskPool as PreforkPool

        from dispatcharr.celery import _is_thread_pool

        self.assertTrue(_is_thread_pool("threads"))
        self.assertTrue(_is_thread_pool(ThreadPool))
        self.assertFalse(_is_thread_pool("prefork"))
        self.assertFalse(_is_thread_pool(PreforkPool))
        self.assertFalse(_is_thread_pool(None))
