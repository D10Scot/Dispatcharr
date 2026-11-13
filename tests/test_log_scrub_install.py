"""Installation of the log scrubber, and the test rig that lets stronger-policy tests bypass it.

Spec: docs/superpowers/specs/2026-11-12-log-scrubber-design.md, T1 (cold child), T2 (no
configuration needed), T3 (chains and plugin discovery), T12 (launchers) and the rig's own
tests (section 9.2). T2, T3 and the rig tests ASSERT that the scrubber is installed and
never repair it, so a factory leaked by a broken test fails them instead of being fixed.
"""
import io
import logging
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from dispatcharr import log_scrub
from tests.log_scrub_rig import FactoryTestCase, unscrubbed_logging
from tests.otel_rig import REPO_ROOT, child_env, run_child

CARRIER = "http://user:pass@example.invalid/get.php"
MASKED = "http://***@example.invalid/get.php"


class ColdImportTests(SimpleTestCase):
    """T1."""

    def test_importing_the_package_installs_the_scrubber(self):
        code = r"""
import io, json, logging
import dispatcharr
marker = bool(getattr(logging.getLogRecordFactory(), "__mino_log_scrubber__", False))
stream = io.StringIO()
handler = logging.StreamHandler(stream)
handler.setFormatter(logging.Formatter("%(message)s"))
log = logging.getLogger("t1.child")
log.propagate = False
log.setLevel(logging.INFO)
log.addHandler(handler)
log.info("fetched %s", "http://user:pass@example.invalid/")
print(json.dumps({"marker": marker, "out": stream.getvalue()}))
"""
        result, payload = run_child(code, child_env())
        self.assertIsNotNone(payload, f"child failed: {result.stderr[-800:]}")
        self.assertTrue(payload["marker"], "scrubber not installed by importing the dispatcharr package")
        self.assertEqual(payload["out"], "fetched http://***@example.invalid/\n")


class NoConfigurationNeededTests(FactoryTestCase):
    """T2."""

    def test_a_handler_added_after_setup_receives_scrubbed_text(self):
        self.assert_scrubber_installed()
        logger, stream = self.capture("t2.fresh")
        logger.info("fetch %s", CARRIER)
        self.assertEqual(stream.getvalue(), f"fetch {MASKED}\n")
        self.assertNotIn("pass@", stream.getvalue(), "unmasked credential reached a fresh handler")

    def test_a_propagated_record_reaches_the_root_logger_scrubbed(self):
        self.assert_scrubber_installed()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        self.addCleanup(root.removeHandler, handler)
        child = logging.getLogger("t2.propagated")
        child.setLevel(logging.INFO)
        child.propagate = True
        child.info("fetch %s", CARRIER)
        self.assertEqual(stream.getvalue(), f"fetch {MASKED}\n")

    def test_a_trace_record_is_scrubbed(self):
        self.assert_scrubber_installed()
        logger, stream = self.capture("t2.trace", level=5)
        logger.trace("fetch %s", CARRIER)
        self.assertEqual(stream.getvalue(), f"fetch {MASKED}\n")

    def test_an_unchanged_record_keeps_the_text_format_byte_identical(self):
        logger, stream = self.capture("t2.unchanged")
        logger.info("%s counted %d channels at 2026/11/12", "A&E / HD", 3)
        self.assertEqual(stream.getvalue(), "A&E / HD counted 3 channels at 2026/11/12\n")


class ChainTests(FactoryTestCase):
    """T3."""

    def foreign(self, capture_previous):
        """A plugin's factory: optionally calls what was current, and replaces it."""
        previous = logging.getLogRecordFactory() if capture_previous else logging.LogRecord
        calls = []

        def foreign_factory(*args, **kwargs):
            calls.append(1)
            return previous(*args, **kwargs)

        logging.setLogRecordFactory(foreign_factory)
        return foreign_factory, calls

    def test_a_replaced_factory_is_wrapped_with_one_warning_and_then_left_alone(self):
        self.assert_scrubber_installed()
        foreign_factory, calls = self.foreign(capture_previous=False)
        with self.assertLogs("dispatcharr.log_scrub", level="WARNING") as captured:
            self.assertTrue(log_scrub.ensure_installed())
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(
            captured.records[0].getMessage(),
            "the log record factory was replaced; the log scrubber has been re-installed around it",
        )
        self.assertTrue(calls, "the foreign factory no longer runs")  # the WARNING's own record went through it
        outer = logging.getLogRecordFactory()
        self.assertIs(outer.__mino_log_scrubber_previous__, foreign_factory)
        with self.assertNoLogs("dispatcharr.log_scrub", level="WARNING"):
            self.assertFalse(log_scrub.ensure_installed())
        self.assertIs(logging.getLogRecordFactory(), outer, "a second call added a layer")
        logger, stream = self.capture("t3.wrapped")
        before = len(calls)
        logger.info("fetch %s", CARRIER)
        self.assertEqual(stream.getvalue(), f"fetch {MASKED}\n")
        self.assertEqual(len(calls) - before, 1)

    def test_a_cooperative_chain_scrubs_twice_without_recursion(self):
        self.assert_scrubber_installed()
        logger, stream = self.capture("t3.single")
        logger.info("fetch %s", CARRIER)
        single = stream.getvalue()

        foreign_factory, calls = self.foreign(capture_previous=True)  # G captured F1 and calls it
        with self.assertLogs("dispatcharr.log_scrub", level="WARNING"):
            log_scrub.ensure_installed()  # F2 -> G -> F1
        logger2, stream2 = self.capture("t3.chain")
        calls.clear()
        with mock.patch.object(log_scrub, "_scrub_record", wraps=log_scrub._scrub_record) as scrub:
            logger2.info("fetch %s", CARRIER)
        self.assertEqual(stream2.getvalue(), single)
        self.assertEqual(len(calls), 1, "G did not run exactly once")
        self.assertEqual(scrub.call_count, 2, "the scrubber should run twice through the chain")

    def test_repeated_replacement_builds_a_finite_chain(self):
        self.assert_scrubber_installed()
        logger, stream = self.capture("t3.single2")
        logger.info("fetch %s", CARRIER)
        single = stream.getvalue()
        for _ in range(3):
            self.foreign(capture_previous=True)
            with self.assertLogs("dispatcharr.log_scrub", level="WARNING"):
                log_scrub.ensure_installed()
        logger2, stream2 = self.capture("t3.rounds")
        logger2.info("fetch %s", CARRIER)  # terminates: no RecursionError
        self.assertEqual(stream2.getvalue(), single)

    def test_each_wrapper_holds_the_factory_that_was_current_at_its_creation(self):
        foreign_factory, _ = self.foreign(capture_previous=False)
        with self.assertLogs("dispatcharr.log_scrub", level="WARNING"):
            log_scrub.ensure_installed()
        wrapper = logging.getLogRecordFactory()
        self.assertIs(wrapper.__mino_log_scrubber_previous__, foreign_factory)
        self.assertIs(wrapper.__kwdefaults__["_previous"], foreign_factory)
        # There is no module-global predecessor that a later installation could reassign.
        self.assertEqual([name for name in vars(log_scrub) if "previous" in name.lower()], [])
        later, _ = self.foreign(capture_previous=True)
        with self.assertLogs("dispatcharr.log_scrub", level="WARNING"):
            log_scrub.ensure_installed()
        self.assertIs(wrapper.__mino_log_scrubber_previous__, foreign_factory)
        self.assertIs(logging.getLogRecordFactory().__mino_log_scrubber_previous__, later)


class PluginDiscoveryTests(FactoryTestCase):
    """T3 case 5: discover_plugins restores the wrapper on each of its three exits."""

    def make_manager(self):
        from apps.plugins.loader import PluginManager

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.dict("os.environ", {"DISPATCHARR_PLUGINS_DIR": tmp.name}):
            manager = PluginManager()
        self.addCleanup(lambda: tmp.name in __import__("sys").path and __import__("sys").path.remove(tmp.name))
        return manager

    def replace_factory(self):
        def foreign_factory(*args, **kwargs):
            return logging.LogRecord(*args, **kwargs)

        logging.setLogRecordFactory(foreign_factory)
        return foreign_factory

    def assert_wrapped_around(self, foreign_factory, where):
        current = logging.getLogRecordFactory()
        self.assertTrue(
            getattr(current, "__mino_log_scrubber__", False),
            f"foreign factory not wrapped after {where}",
        )
        self.assertIs(current.__mino_log_scrubber_previous__, foreign_factory)

    def test_the_normal_return(self):
        manager = self.make_manager()
        foreign_factory = self.replace_factory()
        manager.discover_plugins(sync_db=False, release_connections=False)
        self.assert_wrapped_around(foreign_factory, "normal discovery")

    def test_the_cached_early_return(self):
        manager = self.make_manager()
        manager.discover_plugins(sync_db=False, release_connections=False)
        manager._discovery_completed = True
        manager._last_reload_token = manager._get_reload_token()
        foreign_factory = self.replace_factory()
        with mock.patch.object(manager, "_discover_plugins_impl") as impl:
            manager.discover_plugins(sync_db=False, use_cache=True, release_connections=False)
        impl.assert_not_called()  # it really was the cached exit
        self.assert_wrapped_around(foreign_factory, "cached discovery")

    def test_an_exception_from_discovery(self):
        manager = self.make_manager()
        foreign_factory = self.replace_factory()
        with mock.patch.object(manager, "_discover_plugins_impl", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                manager.discover_plugins(sync_db=False, release_connections=False)
        self.assert_wrapped_around(foreign_factory, "a failed discovery")


class RigTests(FactoryTestCase):
    """The D11 rig's own contract."""

    def test_during_the_block_records_are_not_scrubbed_and_after_it_they_are(self):
        self.assert_scrubber_installed()
        logger, stream = self.capture("rig.during")
        with unscrubbed_logging():
            logger.info("fetch %s", CARRIER)
        logger.info("fetch %s", CARRIER)
        self.assertEqual(stream.getvalue(), f"fetch {CARRIER}\nfetch {MASKED}\n")

    def test_the_exact_entry_factory_is_restored_after_an_exception(self):
        self.assert_scrubber_installed()
        entry = logging.getLogRecordFactory()
        with self.assertRaises(ZeroDivisionError):
            with unscrubbed_logging():
                self.assertIs(logging.getLogRecordFactory(), logging.LogRecord)
                1 / 0
        self.assertIs(logging.getLogRecordFactory(), entry)
        with unscrubbed_logging():  # the active flag was cleared too
            pass

    def test_nesting_is_refused_and_the_outer_state_is_intact(self):
        self.assert_scrubber_installed()
        entry = logging.getLogRecordFactory()
        with unscrubbed_logging():
            with self.assertRaisesRegex(RuntimeError, "not re-entrant"):
                with unscrubbed_logging():
                    self.fail("the nested block must not run")
            self.assertIs(logging.getLogRecordFactory(), logging.LogRecord)  # still the outer's
        self.assertIs(logging.getLogRecordFactory(), entry)

    def test_entering_with_no_scrubber_installed_raises(self):
        logging.setLogRecordFactory(logging.LogRecord)
        with self.assertRaisesRegex(AssertionError, "scrubber not installed at entry"):
            with unscrubbed_logging():
                self.fail("must not run")
        self.assertIs(logging.getLogRecordFactory(), logging.LogRecord)

    def test_a_cooperative_chain_is_rejected_and_left_as_it_was(self):
        self.assert_scrubber_installed()
        previous = logging.getLogRecordFactory()

        def foreign_factory(*args, **kwargs):
            return previous(*args, **kwargs)

        logging.setLogRecordFactory(foreign_factory)
        with self.assertLogs("dispatcharr.log_scrub", level="WARNING"):
            log_scrub.ensure_installed()  # F2 -> G -> F1
        outer = logging.getLogRecordFactory()
        with self.assertRaisesRegex(AssertionError, "predecessor is not the bare logging.LogRecord"):
            with unscrubbed_logging():
                self.fail("must not run")
        self.assertIs(logging.getLogRecordFactory(), outer)


class LauncherTests(SimpleTestCase):
    """T12: every launcher imports the dispatcharr package before application code."""

    def test_celery_programs_start_celery_dash_a_dispatcharr(self):
        for name in ("celery-default.conf", "celery-dvr.conf", "celery-beat.conf"):
            text = (REPO_ROOT / "docker" / "supervisord.d" / name).read_text()
            self.assertIn("celery -A dispatcharr ", text, f"launcher does not import the dispatcharr package: {name}")

    def test_daphne_loads_the_dispatcharr_asgi_application(self):
        text = (REPO_ROOT / "docker" / "supervisord.d" / "daphne.conf").read_text()
        self.assertIn("dispatcharr.asgi", text, "launcher does not import the dispatcharr package: daphne.conf")

    def test_every_uwsgi_ini_imports_or_serves_a_dispatcharr_module(self):
        inis = sorted((REPO_ROOT / "docker").glob("uwsgi*.ini"))
        self.assertGreaterEqual(len(inis), 4)
        for path in inis:
            lines = [line.replace(" ", "") for line in path.read_text().splitlines()]
            ok = any(
                line.startswith(("import=dispatcharr.", "module=dispatcharr.", "wsgi-file=dispatcharr"))
                for line in lines
            )
            self.assertTrue(ok, f"launcher does not import the dispatcharr package: {path.name}")

    def test_manage_py_imports_dispatcharr_settings(self):
        self.assertIn("dispatcharr.settings", (Path(REPO_ROOT) / "manage.py").read_text())
