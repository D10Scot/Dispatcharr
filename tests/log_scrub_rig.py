"""Test rig for the central log scrubber (spec D11, section 9.2).

The test process runs with the scrubber installed, exactly as production does,
so a test that captures log records and asserts that a credential-shaped value
is absent would pass even if its call site regressed: the record factory has
already removed the value before the capture sees it. A test whose policy is
stronger than the scrubber ("the call site never logs it at all") captures
inside ``unscrubbed_logging()`` instead, and so observes the raw call site.

Contract (one context manager, no re-entry):

* on entry the current factory must carry ``__mino_log_scrubber__`` and its
  captured predecessor must BE ``logging.LogRecord``. A missing marker on the
  immediate predecessor proves nothing about the layers below it (in
  ``F2 -> G -> F1`` the foreign ``G`` carries no marker yet still calls ``F1``),
  so anything but the bare stdlib factory is refused;
* nesting is refused, not supported;
* during the block the factory is a MARKED pass-through to that predecessor
  (``__mino_log_scrubber_test_bypass__``). the scrubber module's ``install()``
  recognises the marker and leaves it alone, because code under test can reach
  ``PluginManager.discover_plugins`` (``log_system_event`` -> ``trigger_event``),
  whose ``finally: ensure_installed()`` would otherwise re-install a scrubber and
  silently hollow the rest of the block;
* on normal exit the rig asserts that its pass-through is STILL the current
  factory and fails the test loudly if anything replaced it;
* on every exit, an exception inside the block included, the exact object
  found on entry is put back.

The marker is TEST-ONLY: nothing outside ``tests/`` may set it.

It changes a process-global: use it only in the test's own thread, never around
code that starts threads or greenlets that log.
"""
import contextlib
import io
import logging

from django.test import SimpleTestCase

_active = False


@contextlib.contextmanager
def unscrubbed_logging():
    global _active
    if _active:
        raise RuntimeError("unscrubbed_logging is not re-entrant")
    entry = logging.getLogRecordFactory()
    if not getattr(entry, "__mino_log_scrubber__", False):
        raise AssertionError("scrubber not installed at entry")
    predecessor = getattr(entry, "__mino_log_scrubber_previous__", None)
    if predecessor is not logging.LogRecord:
        raise AssertionError("predecessor is not the bare logging.LogRecord")
    _active = True

    def bypass(*args, **kwargs):
        return predecessor(*args, **kwargs)

    bypass.__mino_log_scrubber_test_bypass__ = True
    replaced = None
    try:
        logging.setLogRecordFactory(bypass)
        yield
        replaced = logging.getLogRecordFactory() is not bypass  # normal exit only
    finally:
        logging.setLogRecordFactory(entry)
        _active = False
    if replaced:
        raise AssertionError(
            "the log record factory was replaced inside unscrubbed_logging(): "
            "the rest of the block ran through a different factory"
        )


class FactoryTestCase(SimpleTestCase):
    """Records the exact factory object at entry and restores it, whatever the test did."""

    def setUp(self):
        self.entry_factory = logging.getLogRecordFactory()
        self.addCleanup(logging.setLogRecordFactory, self.entry_factory)

    def assert_scrubber_installed(self):
        self.assertTrue(
            getattr(logging.getLogRecordFactory(), "__mino_log_scrubber__", False),
            "scrubber not installed",
        )

    def capture(self, name, level=logging.INFO):
        """A fresh logger with a bare StreamHandler, no configuration at all."""
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger = logging.getLogger(name)
        logger.propagate = False
        logger.setLevel(level)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        return logger, stream
