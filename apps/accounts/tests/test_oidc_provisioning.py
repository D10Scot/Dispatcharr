"""Identity resolution, linking and JIT provisioning (SSO spec 4.2, 4.4; T10, T24-T26).

The concurrency cases are ``TransactionTestCase``s on real PostgreSQL, driven by events and
barriers with bounded waits; every thread is joined in ``finally`` and closes its own
connection. They skip themselves under ``TEST_USE_SQLITE=1``.
"""

import re
import threading
import time
from unittest import mock

from django.db import connection
from rest_framework.test import APIClient

from apps.accounts.models import OIDCIdentity, User
from apps.accounts.oidc import provisioning

from .oidc_flow_support import (
    JOIN_TIMEOUT,
    WAIT_TIMEOUT,
    FlowTestCase,
    FlowTransactionTestCase,
    Worker,
    fragment_code,
    join_all,
    make_admin,
    sso_error,
)
from .oidc_support import admin_client

DEADLOCK = "deadlock detected"


def thread_name():
    return threading.current_thread().name


class EmailTakeoverTests(FlowTestCase):
    def test_matching_email_creates_new_user(self):
        admin = User.objects.create_user(
            username="boss", email="boss@example.com", password="testpass123", user_level=10
        )
        make_admin("second-admin")  # so a wrong match is not hidden behind a last_admin refusal
        provider = self.make_flow_provider()
        self.login(
            APIClient(), provider,
            {"roles": ["staff"], "email": "boss@example.com", "preferred_username": "boss"},
        )
        identity = OIDCIdentity.objects.get()
        self.assertNotEqual(
            identity.user_id, admin.pk,
            f"the IdP identity resolved to the existing admin (id {admin.pk}) by email",
        )
        self.assertEqual(identity.user.user_level, User.UserLevel.STANDARD)
        self.assertEqual(identity.user.username, "boss-2")
        admin.refresh_from_db()
        self.assertEqual(admin.user_level, 10)
        self.assertTrue(admin.has_usable_password())


class UsernameTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def test_collision_yields_suffix(self):
        User.objects.create_user(username="alice", password="x-password-123")
        self.login(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": "alice"})
        self.assertTrue(User.objects.filter(username="alice-2", oidc_identities__isnull=False).exists())

    def test_150_character_collision_truncates_per_candidate(self):
        long_name = "n" * 150
        User.objects.create_user(username=long_name, password="x-password-123")
        self.login(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": long_name})
        created = OIDCIdentity.objects.get().user.username
        self.assertEqual(len(created), 150)
        self.assertTrue(created.endswith("-2"), created)

    def test_filtered_out_username_falls_back(self):
        self.login(APIClient(), self.provider, {"roles": ["staff"], "preferred_username": "éé !!"})
        self.assertRegex(OIDCIdentity.objects.get().user.username, r"^sso-[0-9a-f]{8}$")

    def test_email_used_when_no_preferred_username(self):
        self.login(APIClient(), self.provider, {"roles": ["staff"], "email": "e.x+1@example.com"})
        self.assertEqual(OIDCIdentity.objects.get().user.username, "e.x1@example.com")

    def test_username_never_from_sub(self):
        self.login(APIClient(), self.provider, {"roles": ["staff"], "sub": "subject-visible"})
        username = OIDCIdentity.objects.get().user.username
        self.assertNotIn("subject", username)
        self.assertRegex(username, r"^sso-[0-9a-f]{8}$")


class ProvisioningAtomicityTests(FlowTransactionTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()

    def prepare(self, client, claims, *, link=False):
        """start (or link/start) in this thread; return the callback the worker will send."""
        url = self.link_start(client, self.provider) if link else self.start(client, self.provider)
        params = self.op.authorize(url, claims)
        return lambda: self.callback(client, self.provider, params)

    def assertHandoff(self, worker, intent=None):
        self.assertIsNone(worker.error, f"{worker.name} raised {worker.error!r}")
        response = worker.result
        self.assertIsNotNone(response, f"{worker.name} returned nothing (still running?)")
        self.assertIsNone(sso_error(response), f"{worker.name}: {response['Location']}")
        if intent:
            body = worker.client.post(
                "/api/accounts/oidc/exchange/", {"code": fragment_code(response["Location"])}, format="json"
            ).json()
            self.assertEqual(body["intent"], intent)

    def assertNoDeadlock(self, *workers):
        for worker in workers:
            text = repr(worker.error) if worker.error else ""
            self.assertNotIn(DEADLOCK, text.lower(), f"{worker.name} ended in PostgreSQL's deadlock error: {text}")

    # ---- T24 -----------------------------------------------------------------------------

    def test_unmapped_first_login_writes_nothing(self):
        users, identities = User.objects.count(), OIDCIdentity.objects.count()
        response = self.sign_in(APIClient(), self.provider, {"roles": ["nothing"], "preferred_username": "x"})
        self.assertEqual(sso_error(response), "no_mapping")
        self.assertEqual(User.objects.count(), users, f"an unmapped login left a user row: {list(User.objects.values_list('username', flat=True))}")
        self.assertEqual(OIDCIdentity.objects.count(), identities)

    def test_concurrent_first_logins_one_user(self):
        self.require_postgresql()
        barrier = threading.Barrier(2, timeout=WAIT_TIMEOUT)
        original = provisioning.insert_identity

        def wrapper(*args, **kwargs):
            barrier.wait()
            return original(*args, **kwargs)

        workers = []
        for name in ("a", "b"):
            # Distinct usernames, so neither insert waits on the other's username index entry
            # before both reach the identity insert; one subject.
            claims = {"roles": ["admins"], "preferred_username": f"twin-{name}"}
            client = APIClient()
            worker = Worker(self.prepare(client, claims), name)
            worker.client = client
            workers.append(worker)
        with mock.patch.object(provisioning, "insert_identity", side_effect=wrapper):
            try:
                for worker in workers:
                    worker.start()
            finally:
                join_all(workers)
        for worker in workers:
            self.assertHandoff(worker)
        self.assertEqual(OIDCIdentity.objects.count(), 1)
        self.assertEqual(User.objects.count(), 1, list(User.objects.values_list("username", flat=True)))

    def test_losing_identity_insert_leaves_no_orphan_user(self):
        self.require_postgresql()
        ready, committed = threading.Event(), threading.Event()
        original = provisioning.insert_identity

        def wrapper(*args, **kwargs):
            if thread_name() == "loser":
                ready.set()
                committed.wait(WAIT_TIMEOUT)
            return original(*args, **kwargs)

        users_before = User.objects.count()
        client = APIClient()
        worker = Worker(self.prepare(client, {"roles": ["staff"], "preferred_username": "late"}), "loser")
        worker.client = client
        with mock.patch.object(provisioning, "insert_identity", side_effect=wrapper):
            try:
                worker.start()
                self.assertTrue(ready.wait(WAIT_TIMEOUT), "the loser never reached its identity insert")
                winner = User.objects.create_user(username="winner", password="x-password-123")
                OIDCIdentity.objects.create(
                    provider=self.provider, issuer=self.op.issuer, subject="subject-1", user=winner,
                    mapping_claim_path="roles", mapping_claim_values=["staff"],
                )
                committed.set()
            finally:
                join_all([worker], [committed])
        self.assertHandoff(worker)
        self.assertEqual(OIDCIdentity.objects.get().user, winner)
        rose = User.objects.count() - users_before
        orphans = list(User.objects.filter(oidc_identities__isnull=True).values_list("username", flat=True))
        self.assertEqual(rose, 1, f"User count rose by {rose}; users with no OIDCIdentity: {orphans}")

    # ---- T26 -----------------------------------------------------------------------------

    def test_concurrent_links_one_wins(self):
        self.require_postgresql()
        barrier = threading.Barrier(2, timeout=WAIT_TIMEOUT)
        original = provisioning.insert_identity

        def wrapper(*args, **kwargs):
            barrier.wait()
            return original(*args, **kwargs)

        workers, users = [], {}
        for name in ("A", "B"):
            client, user = admin_client(name)
            User.objects.filter(pk=user.pk).update(user_level=1)
            users[name] = user
            worker = Worker(self.prepare(client, {"roles": ["admins"]}, link=True), name)
            worker.client = client
            workers.append(worker)
        with mock.patch.object(provisioning, "insert_identity", side_effect=wrapper):
            try:
                for worker in workers:
                    worker.start()
            finally:
                join_all(workers)
        for worker in workers:
            self.assertIsNone(worker.error, repr(worker.error))
        outcomes = {w.name: sso_error(w.result) for w in workers}
        self.assertEqual(sorted(outcomes.values(), key=str), [None, "link_conflict"], outcomes)
        loser = next(n for n, o in outcomes.items() if o == "link_conflict")
        self.assertEqual(User.objects.get(pk=users[loser].pk).user_level, 1)
        self.assertFalse(OIDCIdentity.objects.filter(user=users[loser]).exists())
        self.assertEqual(OIDCIdentity.objects.count(), 1)

    def test_link_conflict_with_own_identity_does_not_deadlock(self):
        self.require_postgresql()
        e1, e2, e3 = threading.Event(), threading.Event(), threading.Event()
        l_held, c_held = threading.Event(), threading.Event()
        attempt_link, lock_user, after_conflict = (
            provisioning.attempt_link, provisioning.lock_user, provisioning._after_conflict,
        )

        def attempt_link_wrapper(*args, **kwargs):
            if thread_name() == "L":
                l_held.set()
                e1.wait(WAIT_TIMEOUT)
            return attempt_link(*args, **kwargs)

        def lock_user_wrapper(pk):
            if thread_name() == "C":
                c_held.set()
                e2.wait(WAIT_TIMEOUT)
            return lock_user(pk)

        def after_conflict_wrapper(*args, **kwargs):
            if thread_name() == "L":
                e3.set()
            return after_conflict(*args, **kwargs)

        user_client, user = admin_client("U")
        make_admin("other-admin")
        claims = {"roles": ["admins"]}
        l_client = APIClient()
        l_client.force_authenticate(user)
        worker_l = Worker(self.prepare(l_client, claims, link=True), "L")
        worker_l.client = l_client
        c_client = APIClient()
        worker_c = Worker(self.prepare(c_client, claims), "C")
        worker_c.client = c_client
        second_link = self.prepare(user_client, claims, link=True)

        patches = [
            mock.patch.object(provisioning, "attempt_link", side_effect=attempt_link_wrapper),
            mock.patch.object(provisioning, "lock_user", side_effect=lock_user_wrapper),
            mock.patch.object(provisioning, "_after_conflict", side_effect=after_conflict_wrapper),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        try:
            worker_l.start()
            self.assertTrue(l_held.wait(WAIT_TIMEOUT), "L never reached its attempt savepoint")
            linked = second_link()  # the test thread links I to the same U, and commits
            self.assertIsNone(sso_error(linked), linked["Location"])
            worker_c.start()
            self.assertTrue(c_held.wait(WAIT_TIMEOUT), "C never locked the identity")
            e1.set()
            reached = e3.wait(WAIT_TIMEOUT)
            e2.set()
        finally:
            join_all([worker_l, worker_c], [e1, e2, e3])
        self.assertNoDeadlock(worker_l, worker_c)
        self.assertTrue(reached, f"L never entered the conflict handler: {worker_l.error!r} {worker_l.result}")
        self.assertHandoff(worker_c)
        self.assertHandoff(worker_l, intent="link")
        self.assertEqual(OIDCIdentity.objects.count(), 1)

    def test_link_racing_user_delete_answers_409(self):
        self.require_postgresql()
        e1, l_held = threading.Event(), threading.Event()
        original = provisioning.insert_identity
        l_pid = []

        def wrapper(*args, **kwargs):
            identity = original(*args, **kwargs)
            if thread_name() == "L":
                # The backend holding L's transaction now. Worker.pid is the one L started
                # on, and the callback releases its connection before each IdP request, so
                # L reconnects on another backend before it gets here.
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    l_pid.append(cursor.fetchone()[0])
                l_held.set()
                e1.wait(WAIT_TIMEOUT)
            return identity

        u_client, user = admin_client("U")
        b_client, _ = admin_client("B")
        worker_l = Worker(self.prepare(u_client, {"roles": ["admins"]}, link=True), "L")
        worker_b = Worker(lambda: b_client.delete(f"/api/accounts/users/{user.pk}/"), "B")
        state = "not started"
        with mock.patch.object(provisioning, "insert_identity", side_effect=wrapper):
            try:
                worker_l.start()
                self.assertTrue(l_held.wait(WAIT_TIMEOUT), "L never inserted its identity")
                worker_b.start()
                deadline = time.monotonic() + WAIT_TIMEOUT
                blocked = False
                while time.monotonic() < deadline and not blocked:
                    if worker_b.pid is None or not l_pid:
                        state = "pids not recorded"
                        threading.Event().wait(0.02)  # a poll interval, not a synchroniser
                        continue
                    if not worker_b.is_alive():
                        state = f"B finished: {worker_b.result} {worker_b.error!r}"
                        break
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_blocking_pids(%s)", [worker_b.pid])
                        blockers = cursor.fetchone()[0]
                    state = f"B blocked by {blockers}, L is {l_pid[0]}"
                    blocked = l_pid[0] in blockers
                    if not blocked:
                        threading.Event().wait(0.02)
                self.assertTrue(blocked, f"B never waited on L's transaction: {state}")
                e1.set()
            finally:
                join_all([worker_l, worker_b], [e1])
        self.assertIsNone(worker_l.error, repr(worker_l.error))
        self.assertIsNone(sso_error(worker_l.result), worker_l.result["Location"])
        self.assertIsNone(worker_b.error, f"the delete raised instead of answering 409: {worker_b.error!r}")
        self.assertEqual(worker_b.result.status_code, 409, worker_b.result.content)
        self.assertEqual(worker_b.result.json(), {"code": "user_changed_during_delete"})
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertTrue(OIDCIdentity.objects.filter(user=user).exists())
