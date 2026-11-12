"""Password login switchable at runtime (SSO spec PR S4).

- ``PasswordLoginGateTests``: every row of spec 5.3, with the gates reading ``auth_settings``
  fresh (5.1).
- ``RefreshGateTests``: D13, a password-issued refresh token stops refreshing.
- ``BreakGlassTests``: ``MINO_PASSWORD_LOGIN_FORCE`` (``settings.PASSWORD_LOGIN_FORCE``) wins
  over the stored value, and nothing reachable over HTTP can set it.
- ``LockoutGuardTests``: spec 5.5's rule, floor and serialization (its fourteen tests and
  T15a's).
- ``RecoveryTests`` and ``PasswordLoginCommandTests``: spec 5.6's command and procedure (T13).

Secrets here are obvious placeholders.
"""

import ast
import io
import threading
from pathlib import Path
from unittest import mock

import jwt
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import OIDCProvider, User
from apps.accounts.oidc import auth_settings, guard
from apps.accounts.oidc import secrets as oidc_secrets
from apps.accounts.oidc.serializers import OIDCProviderSerializer
from core.models import AUTH_SETTINGS_KEY, CoreSettings, SystemEvent

from .oidc_flow_support import (
    JOIN_TIMEOUT,
    ME,
    WAIT_TIMEOUT,
    FlowTestCase,
    FlowTransactionTestCase,
    Worker,
    join_all,
    run_threads,
)
from .oidc_support import (
    PROVIDERS,
    SETTINGS,
    admin_client,
    make_entra,
    make_provider,
    set_auth_settings,
)

TOKEN = "/api/accounts/token/"
LOGIN_ALIAS = "/api/accounts/auth/login/"
REFRESH = "/api/accounts/token/refresh/"
PUBLIC = "/api/accounts/oidc/providers/"
BOOTSTRAP = "/api/accounts/initialize-superuser/"
CORE_SETTINGS = "/api/core/settings/"
PLACEHOLDER_PASSWORD = "placeholder-pw-1"
PLACEHOLDER_SECRET = "placeholder-secret-rotated"
NEW_TENANT = "99999999-8888-7777-6666-555555555555"
REPO_ROOT = Path(__file__).resolve().parents[3]


def stored_enabled():
    return CoreSettings.get_auth_settings()["password_login_enabled"]


def set_password_login(enabled):
    """Write the stored toggle directly, keeping public_base_url."""
    row = CoreSettings.objects.get(key=AUTH_SETTINGS_KEY)
    value = dict(row.value)
    value["password_login_enabled"] = enabled
    CoreSettings.objects.filter(key=AUTH_SETTINGS_KEY).update(value=value)


def password_user(username="pw", level=User.UserLevel.STANDARD):
    return User.objects.create_user(
        username=username, password=PLACEHOLDER_PASSWORD, user_level=level
    )


def obtain(username="pw", password=PLACEHOLDER_PASSWORD, path=TOKEN):
    return APIClient().post(path, {"username": username, "password": password}, format="json")


def bearer(access):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


def events(event_type):
    return [e.details for e in SystemEvent.objects.filter(event_type=event_type).order_by("id")]


class PasswordLoginGateTests(TestCase):
    """Spec 5.3, row by row: what "password login disabled" disables, and what it leaves."""

    def setUp(self):
        cache.clear()  # the login throttle
        set_auth_settings(password_login_enabled=True)
        self.user = password_user()

    def test_token_refused_when_off(self):
        set_password_login(False)
        response = obtain()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"code": "password_login_disabled"})
        self.assertNotIn("access", response.json())
        failed = events("login_failed")
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["reason"], "password_login_disabled")
        self.assertEqual(failed[0]["user"], "pw")

    def test_login_alias_refused_when_off(self):
        set_password_login(False)
        response = obtain(path=LOGIN_ALIAS)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"code": "password_login_disabled"})

    def test_token_issued_when_on(self):
        response = obtain()
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())
        success = events("login_success")
        self.assertEqual(len(success), 1)
        self.assertNotIn("break_glass", success[0])

    def test_wrong_password_while_off_is_refused_without_checking_it(self):
        # The gate runs before any credential is checked: no password oracle while off.
        # simplejwt binds ``authenticate`` at import (serializers.py, simplejwt 5.5.1), so the
        # patch target is that bound name, not django.contrib.auth's.
        target = "rest_framework_simplejwt.serializers.authenticate"
        # Positive control: with password login on, this patch IS on the login path. It asks
        # only that the patch was reached; how often is the oracle assertion's business.
        with mock.patch(target, return_value=None) as authenticate:
            self.assertEqual(obtain(password="wrong").status_code, 401)
        self.assertGreaterEqual(authenticate.call_count, 1, "the patch is not on the login path")

        set_password_login(False)
        with mock.patch(target) as authenticate:
            response = obtain(password="wrong")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            authenticate.call_count, 0,
            "the password was checked while password login was off (a password oracle)",
        )

    def test_fresh_read_beats_warmed_stale_cache(self):
        # Warm the Redis group cache while the row says enabled, then flip the row with a
        # queryset update: it fires no signal, so the warmed cache stays stale.
        CoreSettings._get_group(AUTH_SETTINGS_KEY, {})
        self.assertTrue(CoreSettings._get_group(AUTH_SETTINGS_KEY, {})["password_login_enabled"])
        set_password_login(False)
        self.assertTrue(
            CoreSettings._get_group(AUTH_SETTINGS_KEY, {})["password_login_enabled"],
            "the precondition failed: the group cache is not stale",
        )
        response = obtain()
        self.assertEqual(
            response.status_code,
            403,
            "the login gate answered from the stale group cache, not a fresh read",
        )
        self.assertEqual(response.json(), {"code": "password_login_disabled"})

    def test_me_password_refused_for_every_user_when_off(self):
        admin = password_user("adm", User.UserLevel.ADMIN)
        set_password_login(False)
        for user in (self.user, admin):
            with self.subTest(user=user.username):
                client = APIClient()
                client.force_authenticate(user)
                response = client.patch(ME, {"password": "new-placeholder-2"}, format="json")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {"code": "password_login_disabled"})
                user.refresh_from_db()
                self.assertTrue(user.check_password(PLACEHOLDER_PASSWORD))

    def test_me_other_fields_still_editable_when_off(self):
        set_password_login(False)
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.patch(ME, {"first_name": "Renamed"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_me_password_allowed_when_on(self):
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.patch(ME, {"password": "new-placeholder-2"}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_api_keys_keep_working_when_off(self):
        self.user.api_key = "placeholder-api-key-value-1"
        self.user.save(update_fields=["api_key"])
        set_password_login(False)
        response = APIClient().get(ME, HTTP_X_API_KEY="placeholder-api-key-value-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "pw")

    def test_existing_access_token_valid_until_expiry(self):
        access = obtain().json()["access"]
        set_password_login(False)
        self.assertEqual(bearer(access).get(ME).status_code, 200)

    def test_bootstrap_not_affected_by_the_toggle(self):
        # Spec 5.3: initialize-superuser is closed by an admin or a provider, never by the toggle.
        set_password_login(False)
        body = APIClient().get(BOOTSTRAP).json()
        self.assertIs(body["superuser_exists"], False)

    def test_bootstrap_post_creates_the_first_admin_while_off(self):
        # The POST half: first-run setup still creates the admin while password login is off.
        set_password_login(False)
        response = APIClient().post(
            BOOTSTRAP, {"username": "first", "password": PLACEHOLDER_PASSWORD}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"superuser_exists": True})
        self.assertEqual(User.objects.get(username="first").user_level, User.UserLevel.ADMIN)

    def test_login_page_config_reports_the_toggle(self):
        self.assertEqual(
            APIClient().get(PUBLIC).json(),
            {"providers": [], "password_login_enabled": True, "password_login_forced": False},
        )
        set_password_login(False)
        self.assertEqual(
            APIClient().get(PUBLIC).json(),
            {"providers": [], "password_login_enabled": False, "password_login_forced": False},
        )


class RefreshGateTests(FlowTestCase):
    """D13: only the access-token tail of a password pair survives the switch."""

    def setUp(self):
        super().setUp()
        password_user()
        self.provider = self.make_flow_provider()

    def test_password_issued_refresh_refused_when_off(self):
        pair = obtain().json()
        self.assertNotIn("auth_method", jwt.decode(pair["refresh"], options={"verify_signature": False}))
        set_password_login(False)
        response = self.refresh(pair["refresh"])
        self.assertEqual(
            response.status_code,
            401,
            "a refresh token with no auth_method claim refreshed while password login was off",
        )
        self.assertEqual(response.json()["code"], "token_not_valid")

    def test_password_issued_refresh_works_when_on(self):
        pair = obtain().json()
        self.assertEqual(self.refresh(pair["refresh"]).status_code, 200)

    def test_sso_refresh_works_when_off(self):
        body = self.login(APIClient(), self.provider, {"roles": ["staff"]})
        set_password_login(False)
        self.assertEqual(self.refresh(body["refresh"]).status_code, 200)

    def test_sso_refresh_refused_when_its_provider_is_disabled(self):
        body = self.login(APIClient(), self.provider, {"roles": ["staff"]})
        set_password_login(False)
        OIDCProvider.update_columns(self.provider.pk, {"enabled": False})
        self.assertEqual(self.refresh(body["refresh"]).status_code, 401)


class BreakGlassTests(TestCase):
    """``MINO_PASSWORD_LOGIN_FORCE=1``: env on means enabled; else the DB value (spec 5.6)."""

    def setUp(self):
        cache.clear()
        set_auth_settings(password_login_enabled=False)
        self.user = password_user()

    @override_settings(PASSWORD_LOGIN_FORCE=True)
    def test_env_force_overrides_db_off(self):
        response = obtain()
        self.assertEqual(
            response.status_code,
            200,
            "the login gate ignored PASSWORD_LOGIN_FORCE and answered from the database",
        )
        success = events("login_success")
        self.assertEqual(len(success), 1)
        self.assertIs(success[0]["break_glass"], True)
        self.assertFalse(stored_enabled(), "break-glass must not write the database")

    @override_settings(PASSWORD_LOGIN_FORCE=True)
    def test_env_force_reenables_refresh_and_me_password(self):
        pair = obtain().json()
        self.assertEqual(
            APIClient().post(REFRESH, {"refresh": pair["refresh"]}, format="json").status_code, 200
        )
        client = APIClient()
        client.force_authenticate(self.user)
        self.assertEqual(
            client.patch(ME, {"password": "new-placeholder-3"}, format="json").status_code, 200
        )

    @override_settings(PASSWORD_LOGIN_FORCE=True)
    def test_login_page_config_reports_the_override(self):
        body = APIClient().get(PUBLIC).json()
        self.assertIs(body["password_login_enabled"], True)
        self.assertIs(body["password_login_forced"], True)

    def test_settings_reports_the_stored_value_not_the_override(self):
        client, _ = admin_client("adm")
        with override_settings(PASSWORD_LOGIN_FORCE=True):
            self.assertIs(client.get(SETTINGS).json()["password_login_enabled"], False)

    def test_no_http_route_changes_the_override(self):
        client, _ = admin_client("adm")
        attempts = [
            client.patch(SETTINGS, {"PASSWORD_LOGIN_FORCE": True, "password_login_forced": True}, format="json"),
            client.patch(SETTINGS, {"password_login_enabled": True}, format="json"),
            client.post(
                CORE_SETTINGS,
                {"key": "password_login_force", "name": "x", "value": {"PASSWORD_LOGIN_FORCE": True}},
                format="json",
            ),
            client.patch(
                f"{CORE_SETTINGS}{CoreSettings.objects.get(key=AUTH_SETTINGS_KEY).pk}/",
                {"value": {"password_login_forced": True}},
                format="json",
            ),
        ]
        self.assertTrue(all(r.status_code < 500 for r in attempts), [r.status_code for r in attempts])
        self.assertIs(settings.PASSWORD_LOGIN_FORCE, False)
        self.assertIs(APIClient().get(PUBLIC).json()["password_login_forced"], False)

    def test_only_settings_assigns_the_override(self):
        # Static: no module other than the settings files assigns PASSWORD_LOGIN_FORCE or
        # reads MINO_PASSWORD_LOGIN_FORCE, and no non-test module invokes the command. So
        # nothing in the web tier can set the override or run the break-glass.
        offenders = []
        for path in sorted((REPO_ROOT / "apps").rglob("*.py")) + sorted(
            (REPO_ROOT / "core").rglob("*.py")
        ) + sorted((REPO_ROOT / "dispatcharr").rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "/tests/" in rel or rel.startswith("dispatcharr/settings"):
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                # Docstrings may name the variable; a call argument or a subscript key is a
                # read (os.environ.get(...), os.getenv(...), os.environ[...]).
                if isinstance(node, ast.Call):
                    for arg in node.args:
                        if getattr(arg, "value", None) == "MINO_PASSWORD_LOGIN_FORCE":
                            offenders.append(f"{rel}:{node.lineno} reads the environment variable")
                if isinstance(node, ast.Subscript):
                    if getattr(node.slice, "value", None) == "MINO_PASSWORD_LOGIN_FORCE":
                        offenders.append(f"{rel}:{node.lineno} reads the environment variable")
                if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        name = getattr(target, "attr", None) or getattr(target, "id", None)
                        if name == "PASSWORD_LOGIN_FORCE":
                            offenders.append(f"{rel}:{node.lineno} assigns it")
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "call_command":
                    if node.args and getattr(node.args[0], "value", None) == "password_login":
                        offenders.append(f"{rel}:{node.lineno} invokes the command")
        self.assertEqual(offenders, [])


class _GuardMixin:
    """Two providers through one fake OP; tokens come from real SSO sign-ins."""

    def make_providers(self, q_enabled=True):
        self.p = self.make_flow_provider(slug="p1")
        self.q = self.make_flow_provider(slug="q1", enabled=q_enabled)

    def sso_pair(self, provider, roles=("admins",), sub="subject-1"):
        return self.login(APIClient(), provider, {"roles": list(roles), "sub": sub, "preferred_username": sub})

    def switch_off(self, client):
        return client.patch(SETTINGS, {"password_login_enabled": False}, format="json")


class LockoutGuardTests(_GuardMixin, FlowTestCase):
    """Spec 5.5: the rule (three reasons), the floor, and what stays allowed while off."""

    def setUp(self):
        super().setUp()
        self.make_providers()

    def test_sso_admin_can_switch_password_login_off(self):
        body = self.sso_pair(self.p)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.switch_off(bearer(body["access"]))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIs(response.json()["password_login_enabled"], False)
        self.assertFalse(stored_enabled())
        audit = events("auth_config_changed")
        self.assertEqual(audit[-1]["fields"], ["password_login_enabled"])
        self.assertEqual(audit[-1]["action"], "auth_settings_updated")
        # And it is enforced at once: no restart, no cache.
        password_user()
        self.assertEqual(obtain().status_code, 403)

    def test_password_session_admin_refused(self):
        password_user("adm", User.UserLevel.ADMIN)
        access = obtain("adm").json()["access"]
        response = self.switch_off(bearer(access))
        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertEqual(body["code"], "lockout_guard")
        self.assertIn(
            "not_sso_session",
            body["reasons"],
            "a password-issued token must be refused as not an SSO session (auth_method)",
        )
        self.assertTrue(stored_enabled())

    def test_rule_accepts_only_an_integer_provider_claim(self):
        # The minted claim is an int. A string or float the database would still coerce to
        # the enabled provider's key is not a proof (guard.evaluate, the type check).
        for value in (str(self.p.pk), float(self.p.pk)):
            with self.subTest(oidc_provider=value):
                reasons = guard.evaluate(
                    password_login_enabled=True,
                    claims={"auth_method": "oidc", "oidc_provider": value, "oidc_level": 10},
                    switching_off=True,
                )
                self.assertEqual(
                    reasons,
                    [guard.PROVIDER_NOT_ENABLED],
                    "a non-integer oidc_provider claim was accepted as the enabled provider",
                )
        self.assertEqual(
            guard.evaluate(
                password_login_enabled=True,
                claims={"auth_method": "oidc", "oidc_provider": self.p.pk, "oidc_level": 10},
                switching_off=True,
            ),
            [],
        )

    @override_settings(PASSWORD_LOGIN_FORCE=True)
    def test_rule_applies_under_the_override(self):
        # Break-glass forces password login on; it does not exempt the switch from the rule.
        # A password admin signed in under the override cannot turn the stored value off.
        password_user("adm", User.UserLevel.ADMIN)
        access = obtain("adm").json()["access"]
        response = self.switch_off(bearer(access))
        self.assertEqual(
            response.status_code, 409, "the lockout rule was skipped under PASSWORD_LOGIN_FORCE"
        )
        self.assertIn("not_sso_session", response.json()["reasons"])
        self.assertTrue(stored_enabled())

    def test_api_key_admin_refused(self):
        admin = password_user("adm", User.UserLevel.ADMIN)
        admin.api_key = "placeholder-api-key-value-2"
        admin.save(update_fields=["api_key"])
        response = APIClient().patch(
            SETTINGS,
            {"password_login_enabled": False},
            format="json",
            HTTP_X_API_KEY="placeholder-api-key-value-2",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["reasons"],
            ["not_sso_session", "provider_not_enabled", "not_admin_at_sign_in"],
        )
        self.assertTrue(stored_enabled())

    def test_standard_at_sign_in_promoted_later_refused(self):
        body = self.sso_pair(self.p, roles=("staff",), sub="promoted")
        user = User.objects.get(username="promoted")
        self.assertEqual(user.user_level, User.UserLevel.STANDARD)
        User.objects.filter(pk=user.pk).update(user_level=User.UserLevel.ADMIN)  # a local promotion
        refreshed = self.refresh(body["refresh"])
        self.assertEqual(refreshed.status_code, 200)
        response = self.switch_off(bearer(refreshed.json()["access"]))
        self.assertEqual(response.status_code, 409, "an admin mapped to Standard at sign-in passed")
        self.assertEqual(
            response.json()["reasons"],
            ["not_admin_at_sign_in"],
            "the refusal must name the sign-in level (oidc_level)",
        )
        self.assertTrue(stored_enabled())

    def test_oidc_level_survives_refresh(self):
        body = self.sso_pair(self.p)
        refreshed = self.refresh(body["refresh"]).json()["access"]
        claims = jwt.decode(refreshed, options={"verify_signature": False})
        self.assertEqual(claims["oidc_level"], 10)
        self.assertEqual(claims["auth_method"], "oidc")
        self.assertEqual(claims["oidc_provider"], self.p.pk)
        self.assertEqual(self.switch_off(bearer(refreshed)).status_code, 200)

    def test_proof_provider_since_disabled_refused(self):
        body = self.sso_pair(self.p)
        admin = APIClient()
        admin.force_authenticate(User.objects.get(username="subject-1"))
        # Disabled while password login is on (allowed: the floor applies only while off).
        self.assertEqual(
            admin.patch(f"{PROVIDERS}{self.p.pk}/", {"enabled": False}, format="json").status_code,
            200,
        )
        response = self.switch_off(bearer(body["access"]))
        self.assertEqual(response.status_code, 409, "a token from a since-disabled provider passed")
        self.assertEqual(response.json()["reasons"], ["provider_not_enabled"])
        self.assertTrue(stored_enabled())

    def test_single_provider_credential_rotation_while_off(self):
        OIDCProvider.objects.filter(pk=self.q.pk).delete()
        set_password_login(False)
        version = OIDCProvider.objects.get(pk=self.p.pk).version
        client, _ = admin_client("adm")
        response = client.patch(
            f"{PROVIDERS}{self.p.pk}/", {"client_secret": PLACEHOLDER_SECRET}, format="json"
        )
        self.assertEqual(
            response.status_code,
            200,
            "a credential rotation on the only provider was refused while password login is off",
        )
        self.assertGreater(OIDCProvider.objects.get(pk=self.p.pk).version, version)
        self.assertFalse(stored_enabled())

    def test_public_base_url_change_while_off_allowed(self):
        set_password_login(False)
        client, _ = admin_client("adm")
        response = client.patch(
            SETTINGS, {"public_base_url": "https://moved.example.com"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["public_base_url"], "https://moved.example.com")
        self.assertFalse(stored_enabled())

    def _only_p_enabled_and_off(self):
        OIDCProvider.update_columns(self.q.pk, {"enabled": False})
        set_password_login(False)

    def test_disable_last_enabled_provider_while_off_refused(self):
        self._only_p_enabled_and_off()
        before = OIDCProvider.objects.get(pk=self.p.pk)
        client, _ = admin_client("adm")
        response = client.patch(f"{PROVIDERS}{self.p.pk}/", {"enabled": False}, format="json")
        self.assertEqual(
            response.status_code, 409, "the last enabled provider was disabled while off"
        )
        self.assertEqual(
            response.json(), {"code": "lockout_guard", "reasons": ["last_enabled_provider"]}
        )
        after = OIDCProvider.objects.get(pk=self.p.pk)
        self.assertTrue(after.enabled)
        self.assertEqual(after.version, before.version)

    def test_delete_last_enabled_provider_while_off_refused(self):
        self._only_p_enabled_and_off()
        client, _ = admin_client("adm")
        response = client.delete(f"{PROVIDERS}{self.p.pk}/")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(), {"code": "lockout_guard", "reasons": ["last_enabled_provider"]}
        )
        self.assertTrue(OIDCProvider.objects.filter(pk=self.p.pk, enabled=True).exists())

    def test_delete_disabled_provider_while_off_allowed(self):
        self._only_p_enabled_and_off()
        client, _ = admin_client("adm")
        self.assertEqual(client.delete(f"{PROVIDERS}{self.q.pk}/").status_code, 204)

    def test_disable_one_of_two_providers_while_off_allowed(self):
        set_password_login(False)
        client, _ = admin_client("adm")
        response = client.patch(f"{PROVIDERS}{self.p.pk}/", {"enabled": False}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(OIDCProvider.objects.get(pk=self.p.pk).enabled)

    def test_disable_last_provider_while_on_allowed(self):
        OIDCProvider.update_columns(self.q.pk, {"enabled": False})
        client, _ = admin_client("adm")
        response = client.patch(f"{PROVIDERS}{self.p.pk}/", {"enabled": False}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(OIDCProvider.objects.filter(enabled=True).exists())

    def test_floor_reads_the_stored_value_not_the_override(self):
        self._only_p_enabled_and_off()
        client, _ = admin_client("adm")
        with override_settings(PASSWORD_LOGIN_FORCE=True):
            response = client.patch(f"{PROVIDERS}{self.p.pk}/", {"enabled": False}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertTrue(OIDCProvider.objects.get(pk=self.p.pk).enabled)

    def test_switching_on_needs_no_proof(self):
        set_password_login(False)
        client, _ = admin_client("adm")
        response = client.patch(SETTINGS, {"password_login_enabled": True}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(stored_enabled())

    def test_refused_switch_writes_no_audit_event(self):
        password_user("adm", User.UserLevel.ADMIN)
        access = obtain("adm").json()["access"]
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.switch_off(bearer(access)).status_code, 409)
        self.assertEqual(events("auth_config_changed"), [])


def barrier_around_evaluate(testcase):
    """Each thread waits on a ``Barrier(2, timeout=2)`` AFTER the guard has read and decided,
    and BEFORE it writes. ``BrokenBarrierError`` is swallowed: with the lock in place the
    second thread is still queued in ``select_for_update`` when the first one's wait times
    out."""
    barrier = threading.Barrier(2, timeout=2)
    real = guard.evaluate

    def wrapper(**kwargs):
        reasons = real(**kwargs)
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return reasons

    patcher = mock.patch.object(guard, "evaluate", side_effect=wrapper)
    patcher.start()
    testcase.addCleanup(patcher.stop)
    return barrier


class LockoutGuardConcurrencyTests(_GuardMixin, FlowTransactionTestCase):
    """The two races the simplified rule still has, serialized by the auth_settings row lock.

    Named in spec 5.5 as members of ``LockoutGuardTests``; they need real commits, so they
    run as a ``TransactionTestCase`` here and ``LockoutGuardTests`` keeps the single-request
    tests.
    """

    def setUp(self):
        super().setUp()
        self.require_postgresql()
        self.make_providers()
        self.admin_client, _ = admin_client("adm")

    def _disable(self, provider):
        client = self.admin_client
        return lambda: client.patch(f"{PROVIDERS}{provider.pk}/", {"enabled": False}, format="json")

    def hold_at_lock(self, thread_name):
        """Hold the named thread just before it takes the auth_settings row lock, after its
        view loaded the provider. Returns (entered, release)."""
        entered, release = threading.Event(), threading.Event()
        real = auth_settings.lock_row

        def held():
            if threading.current_thread().name == thread_name:
                entered.set()
                release.wait(WAIT_TIMEOUT)
            return real()

        patcher = mock.patch.object(auth_settings, "lock_row", side_effect=held)
        patcher.start()
        self.addCleanup(patcher.stop)
        return entered, release

    def test_held_disable_decides_on_the_reloaded_provider(self):
        # The update path's floor decides on the provider reloaded under the lock. Password
        # login off, P enabled and Q disabled. A PATCH {enabled: false} of Q is held after the
        # view loaded Q (enabled=False); Q is enabled; P is disabled (allowed, Q is enabled);
        # the PATCH is released. Q is now the last enabled provider, so it must be refused.
        OIDCProvider.update_columns(self.q.pk, {"enabled": False})
        set_password_login(False)
        entered, release = self.hold_at_lock("held-disable")
        client = self.admin_client
        worker = Worker(self._disable(self.q), "held-disable")
        try:
            run_threads(worker)
            self.assertTrue(entered.wait(WAIT_TIMEOUT), "the PATCH never reached the lock")
            self.assertEqual(
                client.patch(f"{PROVIDERS}{self.q.pk}/", {"enabled": True}, format="json").status_code,
                200,
            )
            self.assertEqual(self._disable(self.p)().status_code, 200)
            release.set()
        finally:
            release.set()
            join_all([worker], [release])
        self.assertIsNone(worker.error, repr(worker.error))
        self.assertTrue(
            OIDCProvider.objects.filter(enabled=True).exists(),
            "forbidden state: a disable decided on the pre-lock instance (enabled=False) and "
            "disabled the last enabled provider while password login is off "
            f"(PATCH {worker.result.status_code})",
        )
        self.assertEqual(worker.result.status_code, 409)
        self.assertEqual(worker.result.json()["reasons"], ["last_enabled_provider"])

    def test_command_disable_racing_disable_of_only_provider_serialized(self):
        # manage.py password_login --disable takes the auth_settings row lock for its floor
        # check and write. Password login on, Q the only enabled provider. The command is held
        # after its floor check, inside its transaction; a PATCH disabling Q starts. With the
        # lock the PATCH waits, then sees password login off and is refused.
        OIDCProvider.update_columns(self.p.pk, {"enabled": False})
        set_password_login(True)
        entered, release = threading.Event(), threading.Event()
        real = CoreSettings._update_group

        def held(*args, **kwargs):
            if threading.current_thread().name == "command":
                entered.set()
                release.wait(WAIT_TIMEOUT)
            return real(*args, **kwargs)

        patcher = mock.patch.object(CoreSettings, "_update_group", side_effect=held)
        patcher.start()
        self.addCleanup(patcher.stop)
        command = Worker(
            lambda: call_command("password_login", "--disable", stdout=io.StringIO()), "command"
        )
        disable = Worker(self._disable(self.q), "disable-q")
        try:
            run_threads(command)
            self.assertTrue(entered.wait(WAIT_TIMEOUT), "the command never reached its write")
            run_threads(disable)
            # Without the lock the PATCH completes here, while the command is held.
            disable.join(2)
            release.set()
        finally:
            release.set()
            join_all([command, disable], [release])
        self.assertIsNone(command.error, repr(command.error))
        self.assertIsNone(disable.error, repr(disable.error))
        off = not stored_enabled()
        enabled = OIDCProvider.objects.filter(enabled=True).count()
        self.assertFalse(
            off and enabled == 0,
            "forbidden state: password login is off and no provider is enabled "
            f"(command --disable committed, PATCH {disable.result.status_code}): "
            "the command's floor check did not hold the auth_settings row lock",
        )
        self.assertEqual(disable.result.status_code, 409)

    def test_locked_patch_does_not_write_back_stale_entra_columns(self):
        # validate() fills entra_tenant_id, issuer and client_assertion_alg from the instance
        # loaded before the lock on every Entra PATCH. A locked PATCH {enabled: false} held
        # after that load, released after another admin changed the tenant, must write only
        # what it sent: the newer tenant and its issuer stay.
        entra = make_entra(slug="entra", enabled=True)
        set_password_login(True)
        entered, release = self.hold_at_lock("held-entra")
        client = self.admin_client
        worker = Worker(self._disable(entra), "held-entra")
        try:
            run_threads(worker)
            self.assertTrue(entered.wait(WAIT_TIMEOUT), "the PATCH never reached the lock")
            response = client.patch(
                f"{PROVIDERS}{entra.pk}/", {"entra_tenant_id": NEW_TENANT}, format="json"
            )
            self.assertEqual(response.status_code, 200, response.content)
            release.set()
        finally:
            release.set()
            join_all([worker], [release])
        self.assertIsNone(worker.error, repr(worker.error))
        self.assertEqual(worker.result.status_code, 200, worker.result.content)
        row = OIDCProvider.objects.get(pk=entra.pk)
        self.assertFalse(row.enabled)
        self.assertEqual(
            (row.entra_tenant_id, row.issuer),
            (NEW_TENANT, f"https://login.microsoftonline.com/{NEW_TENANT}/v2.0"),
            "a locked PATCH wrote back the stale Entra columns validate() filled in",
        )

    def test_held_settings_patch_keeps_a_switch_on_made_meanwhile(self):
        # The settings PATCH reads the auth_settings row under its lock. A PATCH
        # {public_base_url} is held just before the lock while password login is off; another
        # admin switches password login on. Released, the PATCH must write its base URL onto
        # the row as it is now, not onto a copy read before the lock.
        set_password_login(False)
        new_base = "https://mino-held.example.com"
        entered, release = self.hold_at_lock("held-settings")
        client = self.admin_client
        worker = Worker(
            lambda: client.patch(SETTINGS, {"public_base_url": new_base}, format="json"),
            "held-settings",
        )
        try:
            run_threads(worker)
            self.assertTrue(entered.wait(WAIT_TIMEOUT), "the PATCH never reached the lock")
            response = client.patch(SETTINGS, {"password_login_enabled": True}, format="json")
            self.assertEqual(response.status_code, 200, response.content)
            release.set()
        finally:
            release.set()
            join_all([worker], [release])
        self.assertIsNone(worker.error, repr(worker.error))
        self.assertEqual(worker.result.status_code, 200, worker.result.content)
        stored = CoreSettings.objects.get(key=AUTH_SETTINGS_KEY).value
        self.assertEqual(
            (stored.get("public_base_url"), stored.get("password_login_enabled")),
            (new_base, True),
            "a held settings PATCH wrote back a copy of auth_settings read before its lock "
            "and lost the switch-on made meanwhile",
        )

    def test_locked_secret_rotation_clears_an_expiry_set_meanwhile(self):
        # A new secret never inherits the old one's expiry. A locked PATCH {enabled: false,
        # client_secret} is held after its view loaded Q (no expiry, so None is no change
        # against it). Another admin sets an expiry on the old secret. Released, the new
        # secret must be stored with no expiry: a sent client_secret owns the expiry column.
        set_password_login(True)
        entered, release = self.hold_at_lock("held-rotate")
        client = self.admin_client
        worker = Worker(
            lambda: client.patch(
                f"{PROVIDERS}{self.q.pk}/",
                {"enabled": False, "client_secret": PLACEHOLDER_SECRET},
                format="json",
            ),
            "held-rotate",
        )
        try:
            run_threads(worker)
            self.assertTrue(entered.wait(WAIT_TIMEOUT), "the PATCH never reached the lock")
            response = client.patch(
                f"{PROVIDERS}{self.q.pk}/",
                {"client_secret_expires_at": "2030-01-01"},
                format="json",
            )
            self.assertEqual(response.status_code, 200, response.content)
            release.set()
        finally:
            release.set()
            join_all([worker], [release])
        self.assertIsNone(worker.error, repr(worker.error))
        self.assertEqual(worker.result.status_code, 200, worker.result.content)
        row = OIDCProvider.objects.get(pk=self.q.pk)
        self.assertEqual(oidc_secrets.decrypt(row.client_secret_encrypted), PLACEHOLDER_SECRET)
        self.assertIsNone(
            row.client_secret_expires_at,
            "a locked secret rotation kept the expiry another admin set on the old secret",
        )

    def test_locked_patch_of_a_provider_deleted_meanwhile_is_not_found(self):
        # A locked PATCH {enabled: false} of Q is held after its view loaded Q; another admin
        # deletes Q. Released, the reload under the lock finds no row: 404 not_found.
        set_password_login(True)
        entered, release = self.hold_at_lock("held-gone")
        client = self.admin_client
        worker = Worker(self._disable(self.q), "held-gone")
        try:
            run_threads(worker)
            self.assertTrue(entered.wait(WAIT_TIMEOUT), "the PATCH never reached the lock")
            self.assertEqual(client.delete(f"{PROVIDERS}{self.q.pk}/").status_code, 204)
            release.set()
        finally:
            release.set()
            join_all([worker], [release])
        self.assertIsNone(
            worker.error,
            f"a locked PATCH of a provider deleted meanwhile raised: {worker.error!r}",
        )
        self.assertEqual(
            (worker.result.status_code, worker.result.json()),
            (404, {"code": "not_found"}),
            "a locked PATCH of a provider deleted meanwhile was not answered not_found",
        )

    def test_locked_kind_change_to_entra_writes_the_derived_alg(self):
        # A locked PATCH turning a generic provider into Entra is held after its view loaded
        # the provider (alg PS256, so validate()'s PS256 is no change against it). Another
        # admin sets the alg to RS256. Released, the row is Entra and must carry PS256: the
        # derived columns follow the row's final kind, not the stale instance.
        generic = make_provider(slug="gen", client_auth_method="client_secret_post")
        set_password_login(True)
        entered, release = self.hold_at_lock("held-kind")
        client = self.admin_client
        worker = Worker(
            lambda: client.patch(
                f"{PROVIDERS}{generic.pk}/",
                {"kind": "entra", "entra_tenant_id": NEW_TENANT},
                format="json",
            ),
            "held-kind",
        )
        try:
            run_threads(worker)
            self.assertTrue(entered.wait(WAIT_TIMEOUT), "the PATCH never reached the lock")
            response = client.patch(
                f"{PROVIDERS}{generic.pk}/", {"client_assertion_alg": "RS256"}, format="json"
            )
            self.assertEqual(response.status_code, 200, response.content)
            release.set()
        finally:
            release.set()
            join_all([worker], [release])
        self.assertIsNone(worker.error, repr(worker.error))
        self.assertEqual(worker.result.status_code, 200, worker.result.content)
        row = OIDCProvider.objects.get(pk=generic.pk)
        self.assertEqual(
            (row.kind, row.client_assertion_alg),
            ("entra", "PS256"),
            "a locked kind change to Entra left a derived column (client_assertion_alg) "
            "that disagrees with the row's final kind",
        )

    def test_locked_entra_patch_sending_issuer_follows_the_current_tenant(self):
        # A locked PATCH {enabled: false, issuer} on an Entra provider is held after its view
        # loaded the provider. Another admin changes the tenant (and with it the issuer).
        # Released, the issuer it sent (re-derived from the stale tenant by validate()) must
        # not be written: an Entra issuer is derived from the row's tenant, never from the
        # request.
        entra = make_entra(slug="entra", enabled=True)
        stale_issuer = entra.issuer
        set_password_login(True)
        entered, release = self.hold_at_lock("held-issuer")
        client = self.admin_client
        worker = Worker(
            lambda: client.patch(
                f"{PROVIDERS}{entra.pk}/",
                {"enabled": False, "issuer": stale_issuer},
                format="json",
            ),
            "held-issuer",
        )
        try:
            run_threads(worker)
            self.assertTrue(entered.wait(WAIT_TIMEOUT), "the PATCH never reached the lock")
            response = client.patch(
                f"{PROVIDERS}{entra.pk}/", {"entra_tenant_id": NEW_TENANT}, format="json"
            )
            self.assertEqual(response.status_code, 200, response.content)
            release.set()
        finally:
            release.set()
            join_all([worker], [release])
        self.assertIsNone(worker.error, repr(worker.error))
        self.assertEqual(worker.result.status_code, 200, worker.result.content)
        row = OIDCProvider.objects.get(pk=entra.pk)
        self.assertFalse(row.enabled)
        self.assertEqual(
            (row.entra_tenant_id, row.issuer),
            (NEW_TENANT, f"https://login.microsoftonline.com/{NEW_TENANT}/v2.0"),
            "a locked Entra PATCH wrote an issuer derived from the stale tenant over the "
            "row's current tenant",
        )

    def test_concurrent_disables_of_last_two_providers_one_wins(self):
        set_password_login(False)
        barrier_around_evaluate(self)
        a = Worker(self._disable(self.p), "disable-p")
        b = Worker(self._disable(self.q), "disable-q")
        try:
            run_threads(a, b)
        finally:
            join_all([a, b])
        self.assertIsNone(a.error, repr(a.error))
        self.assertIsNone(b.error, repr(b.error))
        codes = sorted([a.result.status_code, b.result.status_code])
        enabled = OIDCProvider.objects.filter(enabled=True).count()
        self.assertGreaterEqual(
            enabled,
            1,
            f"password login off with no enabled provider: both disables committed ({codes})",
        )
        self.assertEqual(codes, [200, 409])
        loser = a.result if a.result.status_code == 409 else b.result
        self.assertEqual(loser.json()["reasons"], ["last_enabled_provider"])

    def test_concurrent_deletes_of_last_two_providers_one_wins(self):
        # The delete path's floor under the same row lock: password login off, P and Q both
        # enabled, both deleted at once. Exactly one DELETE may commit.
        set_password_login(False)
        barrier_around_evaluate(self)
        client = self.admin_client
        a = Worker(lambda: client.delete(f"{PROVIDERS}{self.p.pk}/"), "delete-p")
        b = Worker(lambda: client.delete(f"{PROVIDERS}{self.q.pk}/"), "delete-q")
        try:
            run_threads(a, b)
        finally:
            join_all([a, b])
        self.assertIsNone(a.error, repr(a.error))
        self.assertIsNone(b.error, repr(b.error))
        codes = sorted([a.result.status_code, b.result.status_code])
        self.assertGreaterEqual(
            OIDCProvider.objects.filter(enabled=True).count(),
            1,
            f"password login off with no enabled provider: both deletes committed ({codes})",
        )
        self.assertEqual(codes, [204, 409])

    def test_switch_off_racing_disable_of_only_provider_serialized(self):
        OIDCProvider.update_columns(self.p.pk, {"enabled": False})
        body = self.sso_pair(self.q)
        barrier_around_evaluate(self)
        a = Worker(lambda: self.switch_off(bearer(body["access"])), "switch-off")
        b = Worker(self._disable(self.q), "disable-q")
        try:
            run_threads(a, b)
        finally:
            join_all([a, b])
        self.assertIsNone(a.error, repr(a.error))
        self.assertIsNone(b.error, repr(b.error))
        off = not stored_enabled()
        enabled = OIDCProvider.objects.filter(enabled=True).count()
        self.assertFalse(
            off and enabled == 0,
            "forbidden state: password login is off and no provider is enabled "
            f"(switch-off {a.result.status_code}, disable {b.result.status_code})",
        )
        self.assertEqual(sorted([a.result.status_code, b.result.status_code]), [200, 409])

    def test_unrelated_patch_cannot_empty_the_enabled_set(self):
        # T15a: password login off, P disabled and Q enabled. A credential PATCH for P is
        # held after the view loaded P (enabled=False); P is enabled; Q is disabled (allowed,
        # P is enabled); the held PATCH is released. It must not re-save enabled=False.
        OIDCProvider.update_columns(self.p.pk, {"enabled": False})
        set_password_login(False)
        entered, release = threading.Event(), threading.Event()
        real = OIDCProviderSerializer.update

        def held(serializer, instance, validated_data):
            if threading.current_thread().name == "held":
                entered.set()
                release.wait(WAIT_TIMEOUT)
            return real(serializer, instance, validated_data)

        patcher = mock.patch.object(OIDCProviderSerializer, "update", autospec=True, side_effect=held)
        patcher.start()
        self.addCleanup(patcher.stop)
        client = self.admin_client
        worker = Worker(
            lambda: client.patch(
                f"{PROVIDERS}{self.p.pk}/", {"client_secret": PLACEHOLDER_SECRET}, format="json"
            ),
            "held",
        )
        try:
            run_threads(worker)
            self.assertTrue(entered.wait(WAIT_TIMEOUT), "the credential PATCH never reached update")
            self.assertEqual(
                client.patch(f"{PROVIDERS}{self.p.pk}/", {"enabled": True}, format="json").status_code,
                200,
            )
            self.assertEqual(
                client.patch(f"{PROVIDERS}{self.q.pk}/", {"enabled": False}, format="json").status_code,
                200,
            )
            release.set()
        finally:
            release.set()
            join_all([worker], [release])
        self.assertIsNone(worker.error, repr(worker.error))
        self.assertEqual(worker.result.status_code, 200)
        self.assertTrue(
            OIDCProvider.objects.filter(enabled=True).exists(),
            "a stale credential PATCH re-saved enabled=False and emptied the enabled set",
        )
        self.assertTrue(OIDCProvider.objects.get(pk=self.p.pk).enabled)

    def test_held_delete_decides_on_the_reloaded_provider(self):
        # The delete path's floor (spec 5.5) decides on the provider reloaded under the lock,
        # never on the instance the view loaded before it. Password login off, P disabled and
        # Q enabled. A DELETE of P is held after the view loaded P (enabled=False), before the
        # lock; P is enabled; Q is disabled (allowed, P is enabled); the DELETE is released.
        # P is now the last enabled provider, so the DELETE must be refused.
        OIDCProvider.update_columns(self.p.pk, {"enabled": False})
        set_password_login(False)
        entered, release = self.hold_at_lock("held-delete")
        client = self.admin_client
        worker = Worker(lambda: client.delete(f"{PROVIDERS}{self.p.pk}/"), "held-delete")
        try:
            run_threads(worker)
            self.assertTrue(entered.wait(WAIT_TIMEOUT), "the DELETE never reached the lock")
            self.assertEqual(
                client.patch(f"{PROVIDERS}{self.p.pk}/", {"enabled": True}, format="json").status_code,
                200,
            )
            self.assertEqual(
                client.patch(f"{PROVIDERS}{self.q.pk}/", {"enabled": False}, format="json").status_code,
                200,
            )
            release.set()
        finally:
            release.set()
            join_all([worker], [release])
        self.assertIsNone(worker.error, repr(worker.error))
        self.assertTrue(
            OIDCProvider.objects.filter(enabled=True).exists(),
            "forbidden state: a DELETE decided on the pre-lock instance (enabled=False) and "
            f"removed the last enabled provider while password login is off "
            f"(DELETE {worker.result.status_code})",
        )
        self.assertEqual(worker.result.status_code, 409)
        self.assertEqual(worker.result.json()["reasons"], ["last_enabled_provider"])


class PasswordLoginCommandTests(TestCase):
    """``manage.py password_login``: three verbs and ``--force`` (spec 5.6, 4.4)."""

    def setUp(self):
        set_auth_settings(password_login_enabled=True)

    def run_command(self, *args):
        out = io.StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command("password_login", *args, stdout=out)
        return out.getvalue()

    def test_disable_with_an_enabled_provider(self):
        make_provider(enabled=True)
        output = self.run_command("--disable")
        self.assertIn("Password login disabled.", output)
        self.assertFalse(stored_enabled())
        audit = events("auth_config_changed")
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["user"], "cli")
        self.assertEqual(audit[0]["action"], "auth_settings_updated")
        self.assertEqual(audit[0]["fields"], ["password_login_enabled"])

    def test_disable_with_no_enabled_provider_refused_and_row_unchanged(self):
        make_provider(enabled=False)
        before = CoreSettings.objects.get(key=AUTH_SETTINGS_KEY).value
        with self.assertRaises(CommandError) as caught:
            self.run_command("--disable")
        self.assertIn("last_enabled_provider", str(caught.exception))
        self.assertIn("--force", str(caught.exception))
        self.assertEqual(CoreSettings.objects.get(key=AUTH_SETTINGS_KEY).value, before)
        self.assertEqual(events("auth_config_changed"), [])

    def test_disable_force_writes_with_no_enabled_provider(self):
        output = self.run_command("--disable", "--force")
        self.assertIn("Password login disabled.", output)
        self.assertFalse(stored_enabled())

    @override_settings(RUNTIME_SQLITE=True)
    def test_disable_force_refused_on_runtime_sqlite(self):
        with self.assertRaises(CommandError) as caught:
            self.run_command("--disable", "--force")
        self.assertIn("requires_postgresql", str(caught.exception))
        self.assertTrue(stored_enabled())

    def test_enable_writes_and_is_live_at_once(self):
        set_password_login(False)
        cache.clear()
        password_user()
        self.assertEqual(obtain().status_code, 403)
        output = self.run_command("--enable")
        self.assertIn("Password login enabled.", output)
        self.assertTrue(stored_enabled())
        self.assertEqual(obtain().status_code, 200)
        self.assertEqual(events("auth_config_changed")[-1]["user"], "cli")

    def test_enable_when_already_enabled_writes_nothing(self):
        output = self.run_command("--enable")
        self.assertIn("already enabled", output)
        self.assertEqual(events("auth_config_changed"), [])

    def test_status_reports_db_env_providers_and_admins(self):
        set_password_login(False)
        make_provider(enabled=True, slug="work")
        make_provider(enabled=False, slug="off")
        User.objects.create_user(username="a1", password=PLACEHOLDER_PASSWORD, user_level=10)
        output = self.run_command("--status")
        self.assertIn("Password login (stored): disabled", output)
        self.assertIn("MINO_PASSWORD_LOGIN_FORCE: off", output)
        self.assertIn("Password login now: disabled", output)
        self.assertIn("Enabled providers: 1", output)
        self.assertIn("  work: credential unknown", output)
        self.assertNotIn("  off:", output)
        self.assertIn("Active admins with a usable password: 1", output)
        self.assertFalse(stored_enabled(), "--status wrote the stored value")

    @override_settings(PASSWORD_LOGIN_FORCE=True)
    def test_status_reports_the_override(self):
        set_password_login(False)
        output = self.run_command("--status")
        self.assertIn("MINO_PASSWORD_LOGIN_FORCE: on", output)
        self.assertIn("Password login now: enabled", output)

    def test_a_verb_is_required_and_force_needs_disable(self):
        with self.assertRaises(CommandError):
            self.run_command()
        with self.assertRaises(CommandError):
            self.run_command("--enable", "--force")


class RecoveryTests(TestCase):
    """T13: the recovery procedure of spec 5.6 for an instance whose admins have no password."""

    def setUp(self):
        cache.clear()
        set_auth_settings(password_login_enabled=False)
        make_provider(enabled=True)
        # An SSO-provisioned admin: JIT users get set_unusable_password() (spec 4.2 step 5).
        self.admin = User.objects.create_user(username="sso-admin", user_level=10)
        self.admin.set_unusable_password()
        self.admin.save(update_fields=["password"])

    def run_command(self, *args):
        out = io.StringIO()
        call_command("password_login", *args, stdout=out)
        return out.getvalue()

    def test_enable_reports_no_admin_has_a_password(self):
        output = self.run_command("--enable")
        self.assertIn("Active admins with a usable password: 0", output)
        self.assertIn(
            "changepassword",
            output,
            "--enable must name changepassword when no admin has a password",
        )
        self.assertIn("createsuperuser", output)
        self.assertIn("No admin can sign in with a password yet", output)

    def test_changepassword_then_password_login_recovers(self):
        self.run_command("--enable")
        self.assertEqual(obtain("sso-admin").status_code, 401)
        self.admin.set_password(PLACEHOLDER_PASSWORD)  # what changepassword does
        self.admin.save(update_fields=["password"])
        self.assertEqual(obtain("sso-admin").status_code, 200)
        self.assertIn("Active admins with a usable password: 1", self.run_command("--status"))

    def test_status_lists_expiring_credential(self):
        import datetime

        from django.utils import timezone

        OIDCProvider.objects.all().delete()
        soon = timezone.now().date() + datetime.timedelta(days=10)
        gone = timezone.now().date() - datetime.timedelta(days=2)
        make_provider(enabled=True, slug="soon", client_secret_expires_at=soon)
        make_provider(enabled=True, slug="gone", client_secret_expires_at=gone)
        output = self.run_command("--status")
        self.assertIn(f"  soon: credential expiring, expires {soon.isoformat()} (10 days left)", output)
        self.assertIn(f"  gone: credential expired, expired on {gone.isoformat()}", output)
