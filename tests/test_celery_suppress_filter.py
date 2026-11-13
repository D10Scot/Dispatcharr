"""Celery's SuppressFilter only drops INFO and below (spec D10, T11).

The log scrubber rewrites a record's ``msg`` to its rendered text, so a substring test that
used to see only the template now also sees the arguments. Without the level guard an ERROR
whose argument happens to contain ``received`` would be dropped.
"""
import io
import logging
from unittest import mock

from django.test import SimpleTestCase

from dispatcharr import celery as dispatcharr_celery

NOISY = ("celery.app.trace", "celery.beat", "celery.worker.strategy", "celery.beat.Scheduler", "celery.pool")


class SuppressFilterTests(SimpleTestCase):
    def setUp(self):
        self.stream = io.StringIO()
        handler = logging.StreamHandler(self.stream)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        for name in NOISY:
            logger = logging.getLogger(name)
            state = (logger.level, list(logger.filters), logger.propagate, list(logger.handlers))
            self.addCleanup(self._restore, logger, state)
            logger.propagate = False
        with mock.patch.object(dispatcharr_celery, "effective_log_level", "INFO"):
            dispatcharr_celery.setup_celery_logging()
        self.logger = logging.getLogger("celery.app.trace")
        self.logger.addHandler(handler)
        self.addCleanup(self.logger.removeHandler, handler)

    @staticmethod
    def _restore(logger, state):
        logger.setLevel(state[0])
        logger.filters[:] = state[1]
        logger.propagate = state[2]
        logger.handlers[:] = state[3]

    def test_an_error_whose_argument_contains_received_is_emitted_and_masked(self):
        self.logger.error("Task %s raised: %s", "t", "received http://user:pass@example.invalid/x")
        out = self.stream.getvalue()
        self.assertTrue(out, "error record suppressed")
        self.assertIn("http://***@example.invalid/x", out)
        self.assertNotIn("pass@", out)

    def test_an_info_success_line_is_still_suppressed(self):
        self.logger.info("Task %s succeeded in %ss: %s", "t", "0.1", "http://user:pass@example.invalid/x")
        self.assertEqual(self.stream.getvalue(), "")

    def test_an_info_received_line_is_still_suppressed(self):
        self.logger.info("Task %s received", "t")
        self.assertEqual(self.stream.getvalue(), "")
