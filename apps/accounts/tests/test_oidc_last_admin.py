"""No SSO login, link or refresh can demote the last active admin (SSO spec 4.4, D21; T31).

The concurrent cases are ``TransactionTestCase``s on real PostgreSQL. Barriers carry a
bounded timeout: where the advisory lock serialises two callers, the first waits out the
barrier alone and goes on, which is the protocol working; ``BrokenBarrierError`` is
swallowed for that reason.
"""

import threading
from unittest import mock

from rest_framework.test import APIClient

from apps.accounts import api_views as accounts_api_views
from apps.accounts.models import OIDCIdentity, OIDCProvider, User
from apps.accounts.oidc import provisioning
from apps.accounts.oidc import refresh as refresh_mod
from core.models import SystemEvent

from .oidc_flow_support import (
    WAIT_TIMEOUT,
    FlowTransactionTestCase,
    Worker,
    join_all,
    make_admin,
    record_resolve_errors,
    sso_error,
)
from .oidc_support import admin_client

BARRIER_TIMEOUT = 2


def thread_name():
    return threading.current_thread().name


def active_admins():
    return list(
        User.objects.filter(is_active=True, user_level__gte=10).order_by("username").values_list("username", flat=True)
    )


def swallow_broken(barrier):
    try:
        barrier.wait()
    except threading.BrokenBarrierError:
        pass


class LastAdminTests(FlowTransactionTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def sso_user(self, username, roles=("admins",), sub=None):
        claims = {"roles": list(roles), "preferred_username": username, "sub": sub or f"sub-{username}"}
        body = self.login(APIClient(), self.provider, claims)
        return body, User.objects.get(username=username)

    def level(self, username):
        return User.objects.get(username=username).user_level

    def last_admin_events(self):
        return SystemEvent.objects.filter(event_type="login_failed", details__reason="last_admin")

    # ---- single-threaded -------------------------------------------------------------------

    def test_login_demoting_last_admin_refused(self):
        _, user = self.sso_user("solo")
        stored = list(OIDCIdentity.objects.get(user=user).mapping_claim_values)
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": "solo", "sub": "sub-solo"})
        self.assertEqual(
            sso_error(response), "last_admin",
            f"expected last_admin; got {response['Location']} and level {self.level('solo')}",
        )
        self.assertEqual(self.level("solo"), 10)
        self.assertEqual(OIDCIdentity.objects.get(user=user).mapping_claim_values, stored)
        self.assertEqual(active_admins(), ["solo"])
        event = self.last_admin_events().get()
        self.assertEqual(event.details["user"], "solo")

    def test_login_demoting_admin_allowed_when_another_remains(self):
        self.sso_user("one")
        make_admin("two")
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": "one", "sub": "sub-one"})
        self.assertIsNone(sso_error(response), response["Location"])
        self.assertEqual(self.level("one"), 1)

    def test_inactive_second_admin_does_not_count(self):
        self.sso_user("one")
        User.objects.filter(pk=make_admin("two").pk).update(is_active=False)
        response = self.sign_in(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": "one", "sub": "sub-one"})
        self.assertEqual(sso_error(response), "last_admin")
        self.assertEqual(self.level("one"), 10)

    def test_link_demoting_last_admin_refused(self):
        client, user = admin_client("local")
        url = self.link_start(client, self.provider)
        response = self.callback(client, self.provider, self.op.authorize(url, {"roles": ["staff"]}))
        self.assertEqual(sso_error(response), "last_admin")
        self.assertFalse(OIDCIdentity.objects.exists())
        self.assertEqual(self.level("local"), 10)

    def test_refresh_demoting_last_admin_refused(self):
        body, _ = self.sso_user("solo")
        OIDCProvider.update_columns(self.provider.pk, {"mappings": [{"value": "admins", "user_level": 1}]})
        response = self.refresh(body["refresh"])
        self.assertEqual(
            response.status_code, 401, f"refresh answered {response.status_code}; level now {self.level('solo')}"
        )
        self.assertEqual(self.level("solo"), 10)
        event = self.last_admin_events().get()
        self.assertEqual(event.details["provider"], "p1")

    # ---- interleavings --------------------------------------------------------------------

    def test_concurrent_demotions_of_two_admins_one_wins(self):
        self.require_postgresql()
        self.sso_user("a")
        self.sso_user("b")
        barrier = threading.Barrier(2, timeout=BARRIER_TIMEOUT)
        original = provisioning.other_active_admin_exists

        def wrapper(target):
            result = original(target)
            swallow_broken(barrier)  # after the admin-set read, before the write
            return result

        workers = []
        for name in ("a", "b"):
            client = APIClient()
            url = self.start(client, self.provider)
            params = self.op.authorize(url, {"roles": ["staff"], "preferred_username": name, "sub": f"sub-{name}"})
            workers.append(Worker(lambda c=client, p=params: self.callback(c, self.provider, p), name))
        with mock.patch.object(provisioning, "other_active_admin_exists", side_effect=wrapper):
            try:
                for worker in workers:
                    worker.start()
            finally:
                join_all(workers)
        for worker in workers:
            self.assertIsNone(worker.error, repr(worker.error))
        outcomes = sorted(str(sso_error(w.result)) for w in workers)
        self.assertEqual(
            outcomes, ["None", "last_admin"],
            f"outcomes {outcomes}; active admins left: {active_admins()}",
        )
        self.assertEqual(len(active_admins()), 1)

    def test_demotion_racing_deactivation_one_wins(self):
        self.require_postgresql()
        b_client = APIClient()
        _, a = self.sso_user("a")
        _, b = self.sso_user("b")
        b_client.force_authenticate(b)
        barrier = threading.Barrier(2, timeout=BARRIER_TIMEOUT)
        sso_check = provisioning.other_active_admin_exists
        floor = accounts_api_views.admin_floor_lock

        def sso_wrapper(target):
            result = sso_check(target)
            swallow_broken(barrier)
            return result

        def floor_wrapper():
            floor()
            swallow_broken(barrier)

        login = APIClient()
        url = self.start(login, self.provider)
        params = self.op.authorize(url, {"roles": ["staff"], "preferred_username": "b", "sub": "sub-b"})
        workers = [
            Worker(lambda: b_client.patch(f"/api/accounts/users/{a.pk}/", {"is_active": False}, format="json"), "deactivate"),
            Worker(lambda: self.callback(login, self.provider, params), "demote"),
        ]
        with mock.patch.object(provisioning, "other_active_admin_exists", side_effect=sso_wrapper), \
                mock.patch.object(accounts_api_views, "admin_floor_lock", side_effect=floor_wrapper):
            try:
                for worker in workers:
                    worker.start()
            finally:
                join_all(workers)
        for worker in workers:
            self.assertIsNone(worker.error, repr(worker.error))
        deactivated = workers[0].result.status_code == 200
        demoted = sso_error(workers[1].result) is None
        self.assertEqual(
            (deactivated, demoted).count(True), 1,
            f"deactivation {workers[0].result.status_code}, demotion {workers[1].result['Location']}; "
            f"active admins left: {active_admins()}",
        )
        self.assertEqual(len(active_admins()), 1, active_admins())

    def test_promoting_and_demoting_callbacks_do_not_deadlock(self):
        self.require_postgresql()
        admin_client_, _ = admin_client("second-admin")
        _, u = self.sso_user("u", roles=("staff",))
        e1, e2, c1_held = threading.Event(), threading.Event(), threading.Event()
        lock_user = provisioning.lock_user
        floor = provisioning.admin_floor_lock

        def lock_user_wrapper(pk):
            if thread_name() == "c1":
                c1_held.set()
                e1.wait(WAIT_TIMEOUT)
            return lock_user(pk)

        def floor_wrapper():
            result = floor()
            if thread_name() == "c2":
                e2.set()
            return result

        def prepared(roles):
            client = APIClient()
            url = self.start(client, self.provider)
            params = self.op.authorize(url, {"roles": roles, "preferred_username": "u", "sub": "sub-u"})
            return lambda: self.callback(client, self.provider, params)

        c1 = Worker(prepared(["admins"]), "c1")
        c2 = Worker(prepared(["staff"]), "c2")
        with mock.patch.object(provisioning, "lock_user", side_effect=lock_user_wrapper), \
                mock.patch.object(provisioning, "admin_floor_lock", side_effect=floor_wrapper), \
                record_resolve_errors() as resolve_errors:
            try:
                c1.start()
                self.assertTrue(c1_held.wait(WAIT_TIMEOUT), "callback 1 never locked the identity")
                promoted = admin_client_.patch(f"/api/accounts/users/{u.pk}/", {"user_level": 10}, format="json")
                self.assertEqual(promoted.status_code, 200, promoted.content)
                c2.start()
                reached = e2.wait(WAIT_TIMEOUT)
                e1.set()
            finally:
                join_all([c1, c2], [e1, e2])
        for worker in (c1, c2):
            text = repr(worker.error) if worker.error else ""
            # A deadlock inside resolve is answered as provisioning_failed, not raised.
            text += " ".join(resolve_errors.get(worker.name, []))
            self.assertNotIn("deadlock detected", text.lower(), f"{worker.name}: {text}")
            self.assertIsNone(worker.error, f"{worker.name} raised {worker.error!r}")
        self.assertTrue(reached, "callback 2 never returned from admin_floor_lock")
        for worker in (c1, c2):
            self.assertIsNone(sso_error(worker.result), f"{worker.name}: {worker.result['Location']}")
        self.assertEqual(self.level("u"), 1)

    def test_refresh_with_stale_user_cannot_demote_last_admin(self):
        self.require_postgresql()
        OIDCProvider.update_columns(
            self.provider.pk,
            {"mappings": [
                {"value": "admins", "user_level": 10},
                {"value": "staff", "user_level": 1},
                {"value": "a-staff", "user_level": 1},
            ]},
        )
        self.provider.refresh_from_db()
        _, a = self.sso_user("a")
        u_body, u = self.sso_user("u", roles=("staff",))
        a_client = APIClient()
        a_client.force_authenticate(a)
        OIDCProvider.update_columns(
            self.provider.pk,
            {"mappings": [
                {"value": "admins", "user_level": 10},
                {"value": "staff", "user_level": 0},
                {"value": "a-staff", "user_level": 1},
            ]},
        )
        self.provider.refresh_from_db()

        entered, release = threading.Event(), threading.Event()
        floor = refresh_mod.admin_floor_lock

        def floor_wrapper():
            if thread_name() == "refresh":
                entered.set()
                release.wait(WAIT_TIMEOUT)
            return floor()

        worker = Worker(lambda: self.refresh(u_body["refresh"]), "refresh")
        with mock.patch.object(refresh_mod, "admin_floor_lock", side_effect=floor_wrapper):
            try:
                worker.start()
                self.assertTrue(entered.wait(WAIT_TIMEOUT), "the refresh never reached admin_floor_lock")
                promoted = a_client.patch(f"/api/accounts/users/{u.pk}/", {"user_level": 10}, format="json")
                self.assertEqual(promoted.status_code, 200, promoted.content)
                demoted = self.sign_in(
                    APIClient(), self.provider, {"roles": ["a-staff"], "preferred_username": "a", "sub": "sub-a"}
                )
                self.assertIsNone(sso_error(demoted), demoted["Location"])
                self.assertEqual(self.level("a"), 1)
                release.set()
            finally:
                join_all([worker], [release])
        self.assertIsNone(worker.error, repr(worker.error))
        self.assertEqual(
            worker.result.status_code, 401,
            f"refresh answered {worker.result.status_code}; U's level {self.level('u')}; "
            f"active admins left: {active_admins()}",
        )
        self.assertEqual(self.level("u"), 10)
        self.assertEqual(active_admins(), ["u"])
        self.assertTrue(self.last_admin_events().filter(details__user="u").exists())
