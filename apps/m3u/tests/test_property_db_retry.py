"""Property tests for ``_db_query_with_retry`` (issue #69).

Surface at seed a54b09a9: ``apps/m3u/tasks.py:80``. A poisoned Celery DB
connection surfaces as a transient error. The helper retries up to
``max_retries`` attempts, resetting the connection between them, and
re-raises the last failure. A non-transient error propagates on the first
attempt, with no reset.

The connection reset is patched out, so no database is touched.
"""

from unittest import mock

from django.db import DatabaseError, InterfaceError, OperationalError
from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.m3u import tasks

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

transient = st.sampled_from((OperationalError, InterfaceError, IndexError, DatabaseError))
non_transient = st.sampled_from((ValueError, KeyError, RuntimeError, TypeError))


class _Flaky:
    """Raises ``errors`` in order, then returns ``value``."""

    def __init__(self, errors, value):
        self.errors = list(errors)
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)("boom")
        return self.value


class DbQueryWithRetryProperties(SimpleTestCase):
    @given(
        max_retries=st.integers(min_value=1, max_value=5),
        errors=st.lists(transient, max_size=6),
        value=st.integers() | st.text(max_size=5) | st.none(),
    )
    def test_transient_failures_are_retried_up_to_max_retries_with_a_reset_between(
        self, max_retries, errors, value
    ):
        fn = _Flaky(errors, value)
        with mock.patch.object(tasks, "_release_task_db_connection") as reset:
            if len(errors) >= max_retries:
                with self.assertRaises(errors[max_retries - 1]):
                    tasks._db_query_with_retry(fn, max_retries=max_retries)
                self.assertEqual(fn.calls, max_retries)
                self.assertEqual(reset.call_count, max_retries - 1)
            else:
                self.assertEqual(tasks._db_query_with_retry(fn, max_retries=max_retries), value)
                self.assertEqual(fn.calls, len(errors) + 1)
                self.assertEqual(reset.call_count, len(errors))

    @given(max_retries=st.integers(min_value=1, max_value=5), error=non_transient)
    def test_a_non_transient_error_propagates_at_once_without_a_reset(self, max_retries, error):
        fn = _Flaky([error], None)
        with mock.patch.object(tasks, "_release_task_db_connection") as reset:
            with self.assertRaises(error):
                tasks._db_query_with_retry(fn, max_retries=max_retries)
        self.assertEqual((fn.calls, reset.call_count), (1, 0))
