"""The admin-floor lock wait is bounded (``admin_floor.LOCK_WAIT_SECONDS``).

Without the bound a caller queued behind a stalled holder waits in
``pg_advisory_xact_lock`` until uWSGI's 120 s harakiri kills its whole worker. With it,
each caller answers a fixed code within roughly the bound and writes nothing:

- deactivation (``UserViewSet.perform_update``): 503 ``admin_floor_busy``, ``Retry-After: 1``;
- the SSO callback, login and link (``provisioning.resolve``): ``provisioning_failed``, by
  the flow's existing ``DatabaseError`` handler and never by the last resort;
- token refresh (``refresh.check``): 503 ``admin_floor_busy``, ``Retry-After: 1``, never a
  401 that would sign the user out.

PostgreSQL only; the class skips itself elsewhere. A holder thread takes the lock with raw
SQL and keeps it until released. The waiting caller runs on a thread of its own joined with
a timeout, so a build that lost the bound fails naming the unbounded wait instead of
hanging the suite.
"""

import threading
import time
from unittest import mock, skipUnless

from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts import admin_floor
from apps.accounts.admin_floor import ADMIN_FLOOR_LOCK_KEY, AdminFloorBusy, admin_floor_lock
from apps.accounts.models import OIDCIdentity, OIDCProvider, User

from .oidc_flow_support import FlowTransactionTestCase, Worker, capture_all_logs, sso_error
from .oidc_support import admin_client

# The bound the contended tests run with: short, so twenty loops stay cheap. One test runs
# with the shipped constant.
TEST_BOUND = 2
# A generous ceiling for a loaded machine, far below harakiri's 120 s.
CEILING = 30
# How long the holder keeps the lock unless released: longer than CEILING, so a waiter that
# returns before the ceiling did so because of the bound, not because the holder let go.
HOLD = CEILING + 15


class Holder(threading.Thread):
    """Takes the admin-floor lock in its own transaction, writes one row, and keeps both
    until ``release`` is set. ``held`` is set once the lock is granted."""

    def __init__(self, user_pk):
        super().__init__(name="holder", daemon=True)
        self.user_pk = user_pk
        self.held = threading.Event()
        self.release = threading.Event()
        self.error = None

    def run(self):
        from django.db import connection as conn

        try:
            with transaction.atomic():
                with conn.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_xact_lock(%s)", [ADMIN_FLOOR_LOCK_KEY])
                User.objects.filter(pk=self.user_pk).update(first_name="holder-wrote")
                self.held.set()
                self.release.wait(HOLD)
        except BaseException as exc:  # noqa: BLE001 - reported by the test
            self.error = exc
        finally:
            conn.close()


def timed(fn):
    """Wrap ``fn`` so the worker's result is ``(elapsed_seconds, value)``."""

    def run():
        started = time.monotonic()
        value = fn()
        return time.monotonic() - started, value

    return run


@skipUnless(connection.vendor == "postgresql", "advisory locks and lock_timeout are PostgreSQL-only")
class AdminFloorBoundedWaitTests(FlowTransactionTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()
        self.marker = User.objects.create_user(username="marker", password="testpass123")
        self.holder = Holder(self.marker.pk)
        self.addCleanup(self._stop_holder)

    def _stop_holder(self):
        self.holder.release.set()
        if self.holder.is_alive():
            self.holder.join(10)

    def contend(self, fn, bound=TEST_BOUND):
        """Run ``fn`` on a thread while the holder keeps the lock; return its elapsed time and
        value. Fails, without hanging, when ``fn`` is still waiting at ``CEILING``."""
        self.holder.start()
        self.assertTrue(self.holder.held.wait(10), f"the holder never took the lock: {self.holder.error!r}")
        waiter = Worker(timed(fn), "waiter")
        with mock.patch.object(admin_floor, "LOCK_WAIT_SECONDS", bound):
            waiter.start()
            waiter.join(CEILING)
            still_waiting = waiter.is_alive()
            # Let go either way, so a broken build's waiter finishes and the test ends.
            self.holder.release.set()
            self.holder.join(10)
            waiter.join(10)
        self.assertFalse(
            still_waiting,
            f"the caller was still waiting for the admin-floor lock after {CEILING} s: "
            "the advisory-lock wait is unbounded",
        )
        self.assertIsNone(waiter.error, f"the caller raised instead of answering: {waiter.error!r}")
        self.assertIsNone(self.holder.error, f"the holder was disturbed: {self.holder.error!r}")
        self.assertEqual(
            User.objects.get(pk=self.marker.pk).first_name, "holder-wrote",
            "the holder's own write did not commit",
        )
        elapsed, value = waiter.result
        self.assertGreaterEqual(
            elapsed, bound * 0.9,
            f"answered in {elapsed:.2f} s, before the {bound} s bound: it never waited for the lock",
        )
        self.assertLess(elapsed, CEILING, f"answered in {elapsed:.2f} s")
        return elapsed, value

    def assert_busy_503(self, response, elapsed):
        self.assertEqual(
            response.status_code, 503,
            f"answered {response.status_code} {getattr(response, 'data', None)!r} after {elapsed:.2f} s",
        )
        self.assertEqual(response.json(), {"code": "admin_floor_busy"})
        self.assertEqual(response["Retry-After"], "1")

    def sso_staff(self, username):
        """A Standard user signed in by SSO (a below-Admin login takes the lock)."""
        body = self.login(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": username})
        return body, User.objects.get(username=username)

    # ---- the four callers -------------------------------------------------------------------

    def test_deactivation_answers_503_within_the_bound(self):
        client, _ = admin_client("deactivator")
        target = User.objects.create_user(username="target", password="testpass123")

        def patch():
            return client.patch(f"/api/accounts/users/{target.pk}/", {"is_active": False}, format="json")

        elapsed, response = self.contend(patch)
        self.assert_busy_503(response, elapsed)
        self.assertTrue(User.objects.get(pk=target.pk).is_active, "the deactivation was written")
        # The next attempt, with the lock free, succeeds.
        self.assertEqual(patch().status_code, 200)
        self.assertFalse(User.objects.get(pk=target.pk).is_active)

    def test_deactivation_with_the_shipped_bound(self):
        self.assertEqual(admin_floor.LOCK_WAIT_SECONDS, 5)
        client, _ = admin_client("deactivator")
        target = User.objects.create_user(username="target", password="testpass123")
        elapsed, response = self.contend(
            lambda: client.patch(f"/api/accounts/users/{target.pk}/", {"is_active": False}, format="json"),
            bound=admin_floor.LOCK_WAIT_SECONDS,
        )
        self.assert_busy_503(response, elapsed)
        self.assertTrue(User.objects.get(pk=target.pk).is_active)

    def test_callback_login_answers_provisioning_failed(self):
        client = APIClient()
        url = self.start(client, self.provider)
        params = self.op.authorize(url, {"roles": ["staff"], "preferred_username": "newcomer"})
        with capture_all_logs() as logs:
            elapsed, response = self.contend(lambda: self.callback(client, self.provider, params))
        self.assertEqual(
            sso_error(response), "provisioning_failed",
            f"callback answered {response['Location']} after {elapsed:.2f} s",
        )
        self.assertFalse(User.objects.filter(username="newcomer").exists(), "a user was provisioned")
        self.assertFalse(OIDCIdentity.objects.exists(), "an identity was written")
        lines = [text for _, text in logs if "OIDC provisioning failed" in text]
        self.assertEqual(lines, ["OIDC provisioning failed: AdminFloorBusy sqlstate=55P03"])
        # forbid_last_resort (FlowMixin.setUp) fails the test if the last resort answered.
        # The next sign-in, with the lock free, succeeds.
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": "newcomer"})
        self.assertIsNone(sso_error(response), response["Location"])
        self.assertTrue(User.objects.filter(username="newcomer").exists())

    def test_callback_link_answers_provisioning_failed(self):
        client, user = admin_client("linker")
        url = self.link_start(client, self.provider)
        params = self.op.authorize(url, {"roles": ["staff"]})
        with capture_all_logs() as logs:
            elapsed, response = self.contend(lambda: self.callback(client, self.provider, params))
        self.assertEqual(
            sso_error(response), "provisioning_failed",
            f"link callback answered {response['Location']} after {elapsed:.2f} s",
        )
        self.assertFalse(OIDCIdentity.objects.exists(), "the link was written")
        self.assertEqual(User.objects.get(pk=user.pk).user_level, User.UserLevel.ADMIN)
        lines = [text for _, text in logs if "OIDC provisioning failed" in text]
        self.assertEqual(lines, ["OIDC provisioning failed: AdminFloorBusy sqlstate=55P03"])
        # A second admin keeps the floor, so the retried link may demote linker to Standard.
        admin_client("other-admin")
        url = self.link_start(client, self.provider)
        response = self.callback(client, self.provider, self.op.authorize(url, {"roles": ["staff"]}))
        self.assertIsNone(sso_error(response), response["Location"])
        self.assertEqual(OIDCIdentity.objects.get().user_id, user.pk)

    def test_refresh_answers_503_not_401(self):
        body, user = self.sso_staff("refresher")
        # Lower the mapping, so the refresh demotes and enters the locked block.
        OIDCProvider.update_columns(self.provider.pk, {"mappings": [{"value": "staff", "user_level": 0}]})
        elapsed, response = self.contend(lambda: self.refresh(body["refresh"]))
        self.assert_busy_503(response, elapsed)
        self.assertEqual(User.objects.get(pk=user.pk).user_level, User.UserLevel.STANDARD, "the demotion was written")
        # The same refresh token, retried with the lock free, succeeds and demotes.
        retried = self.refresh(body["refresh"])
        self.assertEqual(retried.status_code, 200, retried.content)
        self.assertEqual(User.objects.get(pk=user.pk).user_level, 0)

    # ---- the helper ---------------------------------------------------------------------------

    def test_helper_raises_admin_floor_busy_carrying_the_sqlstate(self):
        def take():
            with transaction.atomic():
                admin_floor_lock()

        waiter_result = {}

        def run():
            try:
                take()
            except AdminFloorBusy as exc:
                waiter_result["exc"] = exc
                return "busy"
            return "granted"

        _, outcome = self.contend(run)
        self.assertEqual(outcome, "busy")
        exc = waiter_result["exc"]
        self.assertEqual(getattr(exc.__cause__, "sqlstate", None), "55P03")
        self.assertEqual(str(exc), "admin_floor_busy", "the exception must carry no data")


def _show_lock_timeout():
    with connection.cursor() as cursor:
        cursor.execute("SHOW lock_timeout")
        return cursor.fetchone()[0]


@skipUnless(connection.vendor == "postgresql", "lock_timeout is PostgreSQL-only")
class LockTimeoutRestoredTests(FlowTransactionTestCase):
    """The bound covers the advisory lock only: ``lock_timeout`` is back to its previous value
    the moment the helper returns."""

    def test_previous_value_restored(self):
        with transaction.atomic():
            # A non-default value, so a helper that reset to 0 would be caught too.
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '7s'")
            admin_floor_lock()
            self.assertEqual(_show_lock_timeout(), "7s")

    def test_default_value_restored(self):
        with transaction.atomic():
            before = _show_lock_timeout()
            admin_floor_lock()
            self.assertEqual(_show_lock_timeout(), before)

    def test_uncontended_lock_adds_three_statements(self):
        with transaction.atomic():
            with CaptureQueriesContext(connection) as captured:
                admin_floor_lock()
        self.assertEqual(
            [q["sql"] for q in captured.captured_queries],
            [
                "SELECT current_setting('lock_timeout')",
                "SET LOCAL lock_timeout = '5000ms'",
                f"SELECT pg_advisory_xact_lock({ADMIN_FLOOR_LOCK_KEY})",
                "SELECT set_config('lock_timeout', '0', true)",
            ],
        )

    def test_row_lock_after_the_helper_waits_past_the_bound(self):
        """A row lock taken after the helper waits longer than the advisory bound, and is
        granted rather than refused.

        The row holder lets go only once ``pg_blocking_pids`` shows this backend waiting on
        it, and then after twice the bound, so the wait is longer than the bound by
        construction rather than by a sleep racing the scheduler.
        """
        bound = 1
        user = User.objects.create_user(username="rowlocked", password="testpass123")
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            my_pid = cursor.fetchone()[0]
        locked, seen = threading.Event(), threading.Event()

        def hold_row():
            from django.db import connection as conn

            with transaction.atomic():
                User.objects.select_for_update().get(pk=user.pk)
                with conn.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    holder_pid = cursor.fetchone()[0]
                locked.set()
                deadline = time.monotonic() + CEILING
                while time.monotonic() < deadline:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT pg_blocking_pids(%s)", [my_pid])
                        if holder_pid in (cursor.fetchone()[0] or []):
                            seen.set()
                            break
                    time.sleep(0.05)
                time.sleep(2 * bound)

        row_holder = Worker(hold_row, "row-holder")
        row_holder.start()
        try:
            self.assertTrue(locked.wait(10), f"the row holder never locked: {row_holder.error!r}")
            with mock.patch.object(admin_floor, "LOCK_WAIT_SECONDS", bound):
                with transaction.atomic():
                    admin_floor_lock()
                    started = time.monotonic()
                    User.objects.select_for_update().get(pk=user.pk)
                    waited = time.monotonic() - started
        finally:
            row_holder.join(CEILING + 10)
        self.assertIsNone(row_holder.error, repr(row_holder.error))
        self.assertTrue(seen.is_set(), "this backend was never seen waiting on the row lock")
        self.assertGreater(waited, bound, f"the row lock was granted after {waited:.2f} s, inside the bound")

