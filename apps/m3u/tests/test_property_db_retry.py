"""Property-based tests for ``_db_query_with_retry`` retry semantics.

The helper (apps/m3u/tasks.py) promises:

* ``fn``'s return value is passed through unchanged on success.
* Non-transient exceptions propagate immediately without a connection reset.
* Transient exceptions (OperationalError, InterfaceError, IndexError,
  DatabaseError) are retried up to ``max_retries`` times; the last failure
  propagates.
* A transient failure followed by a success returns the success.

All pure-Python: the DB connection release is mocked, no DB or Redis needed.
"""

from unittest import mock

from django.db import DatabaseError, InterfaceError, OperationalError
from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.m3u import tasks

hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

TRANSIENT = st.sampled_from(
    (
        OperationalError,
        InterfaceError,
        IndexError,
        DatabaseError,
    )
)


class DbQueryWithRetryProperties(SimpleTestCase):
    def _run(self, fn, max_retries=2):
        # Patch the module-local release so no real connection is touched.
        with mock.patch.object(tasks, "_release_task_db_connection") as rel:
            try:
                result = tasks._db_query_with_retry(fn, max_retries=max_retries)
                return ("ok", result, rel.call_count)
            except Exception as exc:  # noqa: BLE001 - we classify, not swallow
                return ("raise", type(exc), rel.call_count)

    @given(value=st.one_of(st.integers(), st.text(), st.none()))
    def test_success_returns_value_verbatim_with_no_reset(self, value):
        status, result, resets = self._run(lambda: value)
        self.assertEqual(status, "ok")
        self.assertEqual(result, value)
        self.assertEqual(resets, 0)

    @given(exc_type=TRANSIENT)
    def test_transient_error_exhausts_retries_then_raises(self, exc_type):
        calls = []

        def fn():
            calls.append(1)
            raise exc_type("boom")

        status, result, resets = self._run(fn, max_retries=2)
        self.assertEqual(status, "raise")
        self.assertIs(result, exc_type)
        # max_retries=2 => fn tried twice, one reset between attempts.
        self.assertEqual(len(calls), 2)
        self.assertEqual(resets, 1)

    @given(exc_type=TRANSIENT, value=st.integers())
    def test_transient_then_success_returns_success(self, exc_type, value):
        state = {"failed": False}

        def fn():
            if not state["failed"]:
                state["failed"] = True
                raise exc_type("transient")
            return value

        status, result, resets = self._run(fn)
        self.assertEqual(status, "ok")
        self.assertEqual(result, value)
        self.assertEqual(resets, 1)

    @given(message=st.text(max_size=20))
    def test_non_transient_error_propagates_immediately(self, message):
        calls = []

        def fn():
            calls.append(1)
            raise ValueError(message)

        status, result, resets = self._run(fn)
        self.assertEqual(status, "raise")
        self.assertIs(result, ValueError)
        # No retry, no reset for a non-transient error.
        self.assertEqual(len(calls), 1)
        self.assertEqual(resets, 0)
