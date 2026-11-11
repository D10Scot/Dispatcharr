"""T30: the admin-only user activation control (SSO spec D20, section 5.8, PR S0).

Two groups. ``UserActivationTests`` runs on every database: the single-request behaviour.
``UserActivationConcurrencyTests`` is a ``TransactionTestCase`` that needs real PostgreSQL
(advisory locks, ``pg_locks``, ``pg_blocking_pids``) and skips itself elsewhere, as the
tree's other PostgreSQL-only tests do.

The concurrency tests synchronise on ``threading.Event`` objects held inside wrappers around
the production hooks (``admin_floor_lock`` and ``apply_channel_profiles``). No sleep stands in
for a happens-before: where a test waits for another backend to reach a lock it polls
``pg_locks`` / ``pg_blocking_pids`` against a 5 s bound and, on timeout, either fails naming
the state it saw or (the mutex test) goes on to assert the outcome, so a missing lock shows up
as the wrong outcome rather than as a hang. Every wait carries a timeout and every ``finally``
releases every event.
"""

import threading
from unittest import mock, skipUnless

from django.conf import settings
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import api_views as accounts_api_views
from apps.accounts import serializers as accounts_serializers
from apps.accounts.models import User
from apps.channels.models import ChannelProfile

USERS = "/api/accounts/users/"
ME = "/api/accounts/users/me/"
REFRESH = "/api/accounts/token/refresh/"

BOUND = 5  # seconds, for the polls below
JOIN = 10  # seconds, for thread joins


def _make_user(username, level=User.UserLevel.STANDARD, **extra):
    return User.objects.create_user(
        username=username, password="testpass123", user_level=level, **extra
    )


def _bearer(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}


class UserActivationTests(TestCase):
    def setUp(self):
        self.admin = _make_user("admin", User.UserLevel.ADMIN)
        self.other_admin = _make_user("admin2", User.UserLevel.ADMIN)
        self.standard = _make_user("standard")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _patch(self, user, body, client=None):
        return (client or self.client).patch(f"{USERS}{user.pk}/", body, format="json")

    def test_standard_user_cannot_patch_is_active(self):
        client = APIClient()
        client.force_authenticate(self.standard)
        response = self._patch(self.other_admin, {"is_active": False}, client)
        self.assertEqual(response.status_code, 403)
        self.other_admin.refresh_from_db()
        self.assertTrue(self.other_admin.is_active)

    def test_me_cannot_change_is_active(self):
        client = APIClient()
        client.force_authenticate(self.standard)
        response = client.patch(ME, {"is_active": False, "first_name": "Sam"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.standard.refresh_from_db()
        self.assertTrue(self.standard.is_active, "me must not accept is_active")
        self.assertEqual(self.standard.first_name, "Sam")

    def test_admin_cannot_deactivate_self(self):
        response = self._patch(self.admin, {"is_active": False})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"code": "cannot_deactivate_self"})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_last_active_admin_refused(self):
        """A request authenticated before the only other admin went away.

        ``force_authenticate`` stands for a session that passed authentication while its user
        was still active; the target is then the only active admin left.
        """
        self.other_admin.is_active = False
        self.other_admin.save(update_fields=["is_active"])
        response = self._patch(self.admin, {"is_active": False}, self.client)
        # self wins over last-admin when both apply
        self.assertEqual(response.json(), {"code": "cannot_deactivate_self"})

        client = APIClient()
        client.force_authenticate(self.other_admin)  # inactive, but already authenticated
        response = self._patch(self.admin, {"is_active": False}, client)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"code": "last_active_admin"})
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_admin_can_deactivate_another_admin_while_one_remains(self):
        response = self._patch(self.other_admin, {"is_active": False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])
        self.other_admin.refresh_from_db()
        self.assertFalse(self.other_admin.is_active)

    def test_deactivated_user_tokens_refused_and_reactivation_restores_both(self):
        refresh = str(RefreshToken.for_user(self.standard))
        bearer = _bearer(self.standard)
        anon = APIClient()
        self.assertEqual(anon.get(ME, **bearer).status_code, 200)

        self.assertEqual(self._patch(self.standard, {"is_active": False}).status_code, 200)
        self.assertEqual(anon.get(ME, **bearer).status_code, 401)
        self.assertEqual(anon.post(REFRESH, {"refresh": refresh}, format="json").status_code, 401)

        self.assertEqual(self._patch(self.standard, {"is_active": True}).status_code, 200)
        self.assertEqual(anon.get(ME, **bearer).status_code, 200)
        self.assertEqual(anon.post(REFRESH, {"refresh": refresh}, format="json").status_code, 200)

    def test_patch_without_is_active_preserves_deactivation(self):
        self.standard.is_active = False
        self.standard.save(update_fields=["is_active"])
        refresh = str(RefreshToken.for_user(self.standard))
        bearer = _bearer(self.standard)

        response = self._patch(self.standard, {"first_name": "Renamed"})
        self.assertEqual(response.status_code, 200)

        self.standard.refresh_from_db()
        self.assertEqual(self.standard.first_name, "Renamed")
        self.assertFalse(self.standard.is_active, "an edit that omits is_active reactivated the user")
        anon = APIClient()
        self.assertEqual(anon.get(ME, **bearer).status_code, 401)
        self.assertEqual(anon.post(REFRESH, {"refresh": refresh}, format="json").status_code, 401)

    def test_stale_profile_patch_cannot_reactivate(self):
        """The target's own profile PATCH loaded ``request.user`` before an admin deactivated it.

        ``stale`` is that earlier load; ``force_authenticate`` makes it ``request.user`` for the
        later PATCH, which is the state a request that began before the deactivation is in.
        """
        stale = User.objects.get(pk=self.standard.pk)
        self.assertEqual(self._patch(self.standard, {"is_active": False}).status_code, 200)

        client = APIClient()
        client.force_authenticate(stale)
        response = client.patch(ME, {"first_name": "Late"}, format="json")
        self.assertEqual(response.status_code, 200)

        self.standard.refresh_from_db()
        self.assertFalse(
            self.standard.is_active,
            "is_active is True after the stale profile PATCH completed: it re-saved its stale value",
        )
        self.assertEqual(self.standard.first_name, "Late")
        anon = APIClient()
        self.assertEqual(anon.get(ME, **_bearer(self.standard)).status_code, 401)
        self.assertEqual(
            anon.post(REFRESH, {"refresh": str(RefreshToken.for_user(self.standard))}, format="json").status_code,
            401,
        )

    def test_update_saves_only_assigned_columns(self):
        """A save with no assigned scalar writes nothing (guards the update_fields rule)."""
        profile = ChannelProfile.objects.create(name="p1")
        with mock.patch.object(User, "save") as save:
            response = self._patch(self.standard, {"channel_profiles": [profile.pk]})
        self.assertEqual(response.status_code, 200)
        save.assert_not_called()
        self.assertEqual(list(self.standard.channel_profiles.all()), [profile])

    def test_deactivation_with_profile_change_writes_both(self):
        profile = ChannelProfile.objects.create(name="p1")
        self.standard.channel_profiles.add(profile)
        response = self._patch(self.standard, {"is_active": False, "channel_profiles": []})
        self.assertEqual(response.status_code, 200)
        self.standard.refresh_from_db()
        self.assertFalse(self.standard.is_active)
        self.assertEqual(self.standard.channel_profiles.count(), 0)

    def test_deactivation_refused_on_runtime_sqlite(self):
        with override_settings(RUNTIME_SQLITE=True):
            response = self._patch(self.standard, {"is_active": False})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"code": "requires_postgresql"})
            self.standard.refresh_from_db()
            self.assertTrue(self.standard.is_active)

            # Reactivation, and every other edit, still work on SQLite.
            self.standard.is_active = False
            self.standard.save(update_fields=["is_active"])
            self.assertEqual(self._patch(self.standard, {"is_active": True}).status_code, 200)
            self.assertEqual(self._patch(self.standard, {"first_name": "Ok"}).status_code, 200)
        self.standard.refresh_from_db()
        self.assertTrue(self.standard.is_active)

    def test_marker_is_false_under_test(self):
        self.assertIs(settings.RUNTIME_SQLITE, False)


class _Thread:
    """Run one callable on its own thread, with its own DB connection closed afterwards."""

    def __init__(self, fn):
        self.result = None
        self.error = None
        self.done = threading.Event()
        self._fn = fn
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        try:
            self.result = self._fn()
        except BaseException as exc:  # noqa: BLE001 - the test inspects it
            self.error = exc
        finally:
            connections.close_all()
            self.done.set()

    def start(self):
        self._thread.start()
        return self

    def join(self):
        self._thread.join(JOIN)
        assert not self._thread.is_alive(), "worker thread did not finish within the join bound"


def _poll(predicate, bound=BOUND):
    """Poll ``predicate`` for up to ``bound`` seconds; return its last value."""
    stop = threading.Event()
    deadline_hit = threading.Timer(bound, stop.set)
    deadline_hit.start()
    try:
        value = predicate()
        while not value and not stop.is_set():
            stop.wait(0.02)
            value = predicate()
        return value
    finally:
        deadline_hit.cancel()


def _scalar(sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()[0]


@skipUnless(
    connection.vendor == "postgresql",
    "advisory locks, pg_locks and pg_blocking_pids are PostgreSQL-only",
)
class UserActivationConcurrencyTests(TransactionTestCase):
    def _client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def test_concurrent_last_admin_deactivations_one_wins(self):
        """Two admins deactivate each other. The mutex serializes them: exactly one succeeds.

        Each request holds on ``release`` right after it has taken the lock. With the lock,
        the second request cannot reach that point; it waits in PostgreSQL for the advisory
        lock, which ``pg_locks`` shows as a not-granted advisory lock. Without it, both reach
        the hold, each counts the other as an active admin, and both succeed.
        """
        a = _make_user("a", User.UserLevel.ADMIN)
        b = _make_user("b", User.UserLevel.ADMIN)
        release = threading.Event()
        real_lock = accounts_api_views.admin_floor_lock

        def held_lock():
            real_lock()
            release.wait(JOIN)

        def deactivate(requester, target):
            return self._client_for(requester).patch(
                f"{USERS}{target.pk}/", {"is_active": False}, format="json"
            )

        waiting_for_lock = (
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
        )
        try:
            with mock.patch.object(accounts_api_views, "admin_floor_lock", held_lock):
                t1 = _Thread(lambda: deactivate(a, b)).start()
                t2 = _Thread(lambda: deactivate(b, a)).start()
                saw_waiter = _poll(lambda: _scalar(waiting_for_lock) > 0)
                release.set()
                t1.join()
                t2.join()
        finally:
            release.set()

        for t in (t1, t2):
            self.assertIsNone(t.error, f"request raised: {t.error!r}")
        statuses = sorted(t.result.status_code for t in (t1, t2))
        active_admins = User.objects.filter(is_active=True, user_level__gte=10).count()
        self.assertEqual(
            (statuses, active_admins),
            ([200, 400], 1),
            f"statuses={statuses}, active admins left={active_admins}, "
            f"a second backend waiting on the advisory lock was seen: {bool(saw_waiter)}. "
            "Both requests succeeding with no active admin left means the mutex did not serialize them.",
        )
        self.assertTrue(saw_waiter, "the second request never queued on the advisory lock")

    def test_stale_target_cannot_deactivate_last_admin(self):
        """The view loaded T as Standard; before the guard runs T is promoted and X demoted.

        The guards must judge T as the Admin it now is, on the row reloaded under the lock.
        """
        x = _make_user("x", User.UserLevel.ADMIN)
        t = _make_user("t", User.UserLevel.STANDARD)
        held = threading.Event()
        go = threading.Event()
        real_lock = accounts_api_views.admin_floor_lock

        def held_before_lock():
            held.set()
            go.wait(JOIN)
            real_lock()

        def deactivate_t():
            return self._client_for(x).patch(f"{USERS}{t.pk}/", {"is_active": False}, format="json")

        worker = None
        try:
            with mock.patch.object(accounts_api_views, "admin_floor_lock", held_before_lock):
                worker = _Thread(deactivate_t).start()
                self.assertTrue(held.wait(BOUND), "the PATCH never reached the lock")
                # a promotion and a demotion that happen after the view loaded T
                User.objects.filter(pk=t.pk).update(user_level=User.UserLevel.ADMIN)
                User.objects.filter(pk=x.pk).update(user_level=User.UserLevel.STANDARD)
                go.set()
                worker.join()
        finally:
            go.set()

        self.assertIsNone(worker.error, f"request raised: {worker.error!r}")
        t.refresh_from_db()
        active_admins = User.objects.filter(is_active=True, user_level__gte=10).count()
        self.assertEqual(
            (worker.result.status_code, worker.result.json(), t.is_active, active_admins),
            (400, {"code": "last_active_admin"}, True, 1),
            f"status={worker.result.status_code} body={worker.result.content!r} "
            f"T active={t.is_active} active admins left={active_admins}: the guard judged the "
            "target as it was loaded before the lock, not as the row reloaded under it",
        )

    def test_mixed_deactivation_and_profile_change_does_not_deadlock_with_delete(self):
        """``{is_active: false, channel_profiles: []}`` against a concurrent delete of the same user.

        A is held on E1 inside ``apply_channel_profiles``. If that write ran inside A's guarded
        transaction, A would hold U's row there while B's delete holds U's through row and
        waits for U; releasing E1 would then make A wait for B: a deadlock. With the write after
        the commit, B's delete completes while A is held.
        """
        a = _make_user("a", User.UserLevel.ADMIN)
        _make_user("b", User.UserLevel.ADMIN)
        b = User.objects.get(username="b")
        u = _make_user("u")
        profile = ChannelProfile.objects.create(name="p1")
        u.channel_profiles.add(profile)

        e1 = threading.Event()
        a_at_e1 = threading.Event()
        pids = {}
        real_apply = accounts_serializers.apply_channel_profiles

        def held_apply(user, profiles):
            a_at_e1.set()
            e1.wait(JOIN)
            return real_apply(user, profiles)

        def backend_pid():
            return _scalar("SELECT pg_backend_pid()")

        def patch_u():
            pids["a"] = backend_pid()
            return self._client_for(a).patch(
                f"{USERS}{u.pk}/", {"is_active": False, "channel_profiles": []}, format="json"
            )

        def delete_u():
            pids["b"] = backend_pid()
            return self._client_for(b).delete(f"{USERS}{u.pk}/")

        def state():
            if tb.done.is_set():
                return "b finished"
            pid_a, pid_b = pids.get("a"), pids.get("b")
            if pid_a is None or pid_b is None:
                return None
            blocked = _scalar(
                "SELECT %s = ANY(pg_blocking_pids(%s)) AND EXISTS "
                "(SELECT 1 FROM pg_stat_activity WHERE pid = %s AND wait_event_type = 'Lock')",
                [pid_a, pid_b, pid_b],
            )
            return "b blocked on a" if blocked else None

        ta = tb = None
        try:
            with mock.patch.object(accounts_serializers, "apply_channel_profiles", held_apply):
                ta = _Thread(patch_u).start()
                self.assertTrue(a_at_e1.wait(BOUND), "A never reached apply_channel_profiles")
                tb = _Thread(delete_u).start()
                seen = _poll(state)
                self.assertTrue(
                    seen,
                    "neither 'B's delete finished' nor 'B blocked on A' was reached within "
                    f"{BOUND}s: B's thread done={tb.done.is_set()}, pids={pids}",
                )
                state_seen = seen
                e1.set()
                ta.join()
                tb.join()
        finally:
            e1.set()

        for name, t in (("A", ta), ("B", tb)):
            self.assertIsNone(
                t.error,
                f"request {name} raised {t.error!r}. With the profile write inside the guarded "
                f"transaction, A's .set() waits for the through row B's delete holds while B "
                f"waits for A's user row: PostgreSQL's deadlock error. State at E1: {state_seen}",
            )
        self.assertEqual(state_seen, "b finished", "B's delete had to wait for A's user row at E1")
        self.assertEqual(tb.result.status_code, 204)
        self.assertFalse(User.objects.filter(pk=u.pk).exists())
