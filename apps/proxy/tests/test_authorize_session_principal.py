"""A Django session stops authorizing streams while password login is off (SSO spec 5.4a, D19, T28).

Every Django session comes from the admin site's password login. The session is established
BEFORE the switch, as an operator's browser would hold it, and the decision is driven through
``authorize_stream`` on the catch-up surface, which requires a principal: a session that no
longer counts leaves the request with none, so the answer is 401 rather than an anonymous tune.
"""

from unittest.mock import patch

from django.contrib.auth import login
from django.contrib.sessions.backends.db import SessionStore
from django.test import override_settings

from apps.proxy import authorize
from apps.proxy.authorize import SURFACE_CATCHUP, AuthorizeDenied, authorize_stream
from core.models import AUTH_SETTINGS_KEY, CoreSettings

from .test_authorize import AuthorizeBase


def _set_password_login(enabled):
    CoreSettings.objects.update_or_create(
        key=AUTH_SETTINGS_KEY,
        defaults={
            "name": "Authentication Settings",
            "value": {"public_base_url": "", "password_login_enabled": enabled},
        },
    )


class SessionPrincipalPasswordOffTests(AuthorizeBase):
    def setUp(self):
        super().setUp()
        _set_password_login(True)
        # The session is made while password login is on, before any switch.
        self.request = self._request()
        self.request.session = SessionStore()
        login(self.request, self.standard, backend="django.contrib.auth.backends.ModelBackend")

    def _authorize(self):
        with patch.object(authorize, "network_access_allowed", return_value=True):
            return authorize_stream(
                self.request, SURFACE_CATCHUP, identifier=str(self.channel.uuid)
            )

    def test_session_principal_resolved_when_password_login_on(self):
        self.assertEqual(self._authorize().user_id, str(self.standard.id))

    def test_session_principal_refused_when_password_login_off(self):
        _set_password_login(False)
        with self.assertRaises(
            AuthorizeDenied,
            msg="a Django session still authorized a stream with password login off (D19)",
        ) as caught:
            self._authorize()
        self.assertEqual(caught.exception.status, 401)

    @override_settings(PASSWORD_LOGIN_FORCE=True)
    def test_session_principal_resolved_under_break_glass(self):
        _set_password_login(False)
        self.assertEqual(self._authorize().user_id, str(self.standard.id))

    def test_the_toggle_is_read_fresh_not_from_the_group_cache(self):
        # Warm the Redis group cache while the row says on, then flip the row with a
        # queryset update, which fires no signal and so leaves the cache stale.
        CoreSettings._get_group(AUTH_SETTINGS_KEY, {})
        CoreSettings.objects.filter(key=AUTH_SETTINGS_KEY).update(
            value={"public_base_url": "", "password_login_enabled": False}
        )
        with self.assertRaises(AuthorizeDenied) as caught:
            self._authorize()
        self.assertEqual(caught.exception.status, 401)

    def test_a_request_without_a_session_reads_no_toggle(self):
        # The check sits after get_user: no session, no logged-in user, no extra query.
        from django.contrib.sessions.backends.db import SessionStore as Store

        anonymous = self._request()
        anonymous.session = Store()
        with self.assertNumQueries(0):
            self.assertIsNone(authorize._session_user(anonymous))
