"""Tests of the zero-ORM scanner itself.

The guard in test_zero_orm_reads.py is only as good as this file. Issue
#253 records that the spec's prescribed grep fails in BOTH directions --
it misses a real read behind a method call, and it counts a docstring
that quotes the ORM line it replaced. Each direction is pinned here on a
synthetic source, so the pin survives the tree moving underneath it.
"""

import textwrap
from django.test import SimpleTestCase, TransactionTestCase

from . import zero_orm_scan


class ScannerShapeTests(SimpleTestCase):
    def _scan(self, source, path="apps/proxy/live_proxy/fake.py"):
        return zero_orm_scan.scan_source(
            textwrap.dedent(source), path, zero_orm_scan.model_method_names()
        )

    def test_a_model_method_call_is_seen_though_its_call_line_names_no_orm(self):
        """Issue #253's under-count: the shape a grep cannot see.

        get_stream_profile is defined on apps/channels/models.py's Channel
        and Stream and reaches StreamProfile.objects.get (models.py:467).
        Its call line contains neither `.objects.` nor `get_object_or_404(`.
        """
        hits = self._scan(
            """
            def tune(channel):
                return channel.get_stream_profile()
            """
        )
        self.assertEqual(
            [(h.lineno, h.shape, h.symbol) for h in hits],
            [(3, "model_method", "get_stream_profile")],
        )

    def test_a_docstring_quoting_an_orm_line_is_not_a_hit(self):
        """Issue #253's over-count, and the more insidious of the two.

        The cheapest way to silence a line-based grep here is to stop
        quoting the old code in the docstring -- making the codebase less
        legible to satisfy a check. `ast` sees a docstring as a Constant
        and never as an Attribute, so the shape simply does not arise.
        """
        hits = self._scan(
            '''
            def resolve(identifier):
                """Phase 1 PR 6 moved this.

                Was: StreamProfile.objects.get(name="ffmpeg", locked=True)
                and get_object_or_404(Stream.objects.all(), pk=identifier).
                """
                return None
            '''
        )
        self.assertEqual(hits, [])

    def test_a_real_objects_attribute_is_a_hit_in_the_same_file(self):
        """The discriminating half of the test above.

        Without this, `test_a_docstring...` passes with a scanner that
        sees nothing at all -- Global Constraint 3.
        """
        hits = self._scan(
            """
            from apps.channels.models import Stream

            def resolve(pk):
                return Stream.objects.filter(id=pk).first()
            """
        )
        self.assertEqual([(h.lineno, h.shape) for h in hits], [(5, "objects")])

    def test_get_object_or_404_is_a_hit(self):
        hits = self._scan(
            """
            def resolve(pk):
                return get_object_or_404(Channel, pk=pk)
            """
        )
        self.assertEqual([(h.lineno, h.shape) for h in hits], [(3, "shortcut")])

    def test_a_stoplisted_name_is_not_a_hit(self):
        """`update` is a StreamProfile method name AND dict.update.

        Measured at 93900a6f: 8 hits in live_proxy, all dict.update().
        The stoplist is how the model-method rule stays usable; this test
        is what stops it growing silently.
        """
        self.assertIn("update", zero_orm_scan.model_method_names())
        hits = self._scan(
            """
            def build(mapping, extra):
                mapping.update(extra)
                return mapping
            """
        )
        self.assertEqual(hits, [])
        self.assertEqual(
            sorted(zero_orm_scan._NAMES_TOO_GENERIC),
            ["update"],
            "the stoplist grew -- every entry costs the guard a shape it "
            "can no longer see, so each needs its own comment and this "
            "assertion updated deliberately",
        )


class QueryCaptureTests(TransactionTestCase):
    """Tests of the capture helper (plan 2b-3, Rulings R5 and R6).

    TransactionTestCase, not TestCase: apps/proxy/config.py's
    BaseConfig.get_proxy_settings() ends with `finally: connection.close()`
    -- deliberate production behaviour, so a WSGI worker does not hold an
    idle connection between settings reads -- and closing the physical
    connection object out from under a plain TestCase's atomic/savepoint
    wrapping corrupts it for every later test in the class ("the
    connection is closed" surfacing in an unrelated, later test was this
    exact side effect). TransactionTestCase does not hold an outer
    transaction across a test, so the same close-and-lazily-reconnect
    behaviour that is harmless in production is harmless here too.
    """

    def test_a_query_made_on_another_thread_is_captured(self):
        """The whole reason this is not CaptureQueriesContext.

        CaptureQueriesContext binds to django.db.connections for the
        CALLING thread. RelayHarnessTestCase is a LiveServerTestCase:
        the relay's code runs on the WSGI server's threads. A
        per-connection context in a test body captures nothing from a
        tune and passes vacuously.
        """
        import threading
        from core.models import CoreSettings
        from .harness.queries import capture_queries

        def work():
            from django.db import connections
            try:
                list(CoreSettings.objects.all()[:1])
            finally:
                # Django's own recommendation for a thread that touches
                # the ORM: it gets its own connection lazily and nothing
                # closes it automatically once the thread ends. Left
                # open, it leaks into later tests in this class (a
                # subsequent test in this module intermittently saw
                # "the connection is closed" from an unrelated query,
                # which is this leak's signature, not a bug in the
                # helper being tested here).
                connections.close_all()

        with capture_queries() as captured:
            thread = threading.Thread(target=work)
            thread.start()
            thread.join()

        self.assertTrue(
            any("core_coresettings" in q.sql for q in captured),
            "the cross-thread query was not captured -- the patch is not "
            "at class level on CursorWrapper",
        )

    def test_a_query_with_no_relay_frame_is_not_attributed_to_the_relay(self):
        """Ruling R6's discriminator, in its negative direction.

        The harness runs one process serving both planes. Django's
        /api/relay/ views issue a dozen legitimate control-plane queries
        per tune; counting those would make the guard permanently red for
        the wrong reason.
        """
        from core.models import CoreSettings
        from .harness.queries import capture_queries, relay_queries

        with capture_queries() as captured:
            list(CoreSettings.objects.all()[:1])

        self.assertEqual(relay_queries(captured), [])

    def test_a_query_with_a_relay_frame_is_attributed_to_the_relay(self):
        """The discriminating half. Without it, the test above passes
        with an attributor that returns [] for everything."""
        from apps.proxy.live_proxy.config_helper import ConfigHelper
        from .harness.queries import capture_queries, relay_queries

        # Two caches sit in front of the query this test wants to see fire,
        # and both must be cold or the ORM read never happens at all --
        # Global Constraint 1 applied to a fixture, not just a header.
        #
        # 1. CoreSettings.get_proxy_settings() is itself backed by a
        #    Django-cache (Redis) group ("proxy_settings"), so a warm Redis
        #    entry answers without ever reaching Postgres.
        # 2. TSConfig.get_proxy_settings() (config_helper.py:50 calls it)
        #    additionally keeps a 10-second process-local copy. Clearing it
        #    via BaseConfig.clear_proxy_settings_cache() -- what
        #    CoreSettings.invalidate_group_cache() itself calls -- is the
        #    documented #232 trap: `cls._proxy_settings_cache = ...` inside
        #    the classmethod means the first fetch made *through TSConfig*
        #    creates a TSConfig-owned attribute that shadows BaseConfig's,
        #    and clearing BaseConfig's copy leaves that shadow warm. Clear
        #    TSConfig's own directly.
        from core.models import CoreSettings, PROXY_SETTINGS_KEY
        from apps.proxy.config import TSConfig
        CoreSettings.invalidate_group_cache(PROXY_SETTINGS_KEY)
        TSConfig.clear_proxy_settings_cache()

        with capture_queries() as captured:
            ConfigHelper.new_client_behind_seconds()

        self.assertTrue(
            relay_queries(captured),
            "a query issued from apps/proxy/live_proxy/config_helper.py "
            "was not attributed to the relay",
        )

    def test_a_query_from_the_tests_directory_is_not_a_relay_frame(self):
        """tests/ lives under the relay package. Without this exclusion
        every query a test makes is a relay query and the guard is
        unusable."""
        from core.models import CoreSettings
        from .harness.queries import capture_queries, relay_queries

        with capture_queries() as captured:
            list(CoreSettings.objects.filter(key="x"))

        self.assertEqual(relay_queries(captured), [])
