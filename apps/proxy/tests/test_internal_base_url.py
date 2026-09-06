"""The one D9 resolver, and the two wrappers over it.

D9 asks for "two thin wrappers over one function". PR 6 shipped the
function inside control_plane.py, where relay_client cannot reuse it
without importing a private name across the boundary. These tests pin
the extracted module and, crucially, that BOTH wrappers resolve to an
nginx: the relay's only listener speaks the uwsgi protocol
(docker/uwsgi.relay.ini), so http://relay:5657 is not a thing requests
can dial, and the relay role runs no nginx of its own (D14).
"""

import os
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from apps.proxy import control_plane, internal_base_url, relay_client


def _env(**values):
    return mock.patch.dict(os.environ, values, clear=True)


class ResolveBaseUrlTests(SimpleTestCase):
    def setUp(self):
        internal_base_url._host_validation_warned = False
        self.addCleanup(
            setattr, internal_base_url, "_host_validation_warned", False
        )

    def test_the_explicit_override_wins_and_loses_its_trailing_slash(self):
        with _env(DISPATCHARR_RELAY_BASE_URL="http://front:8443/"):
            self.assertEqual(
                relay_client.get_relay_control_base_url(), "http://front:8443"
            )

    def test_modular_addresses_the_api_role_s_nginx_not_the_relay(self):
        # The ruling that matters: DISPATCHARR_WEB_HOST, not
        # DISPATCHARR_RELAY_HOST. Setting RELAY_HOST must change nothing.
        with _env(DISPATCHARR_ENV="modular", DISPATCHARR_RELAY_HOST="relay"):
            self.assertEqual(
                relay_client.get_relay_control_base_url(), "http://web:9191"
            )
        with _env(
            DISPATCHARR_ENV="modular",
            DISPATCHARR_WEB_HOST="api-1",
            DISPATCHARR_PORT="8080",
        ):
            self.assertEqual(
                relay_client.get_relay_control_base_url(), "http://api-1:8080"
            )

    def test_dev_is_the_single_runserver_process(self):
        with _env(DISPATCHARR_ENV="dev", DISPATCHARR_PORT="9191"):
            self.assertEqual(
                relay_client.get_relay_control_base_url(), "http://127.0.0.1:5656"
            )

    def test_aio_is_loopback_nginx(self):
        with _env():
            self.assertEqual(
                relay_client.get_relay_control_base_url(), "http://127.0.0.1:9191"
            )

    def test_both_directions_share_one_address_and_differ_only_in_override(self):
        with _env(DISPATCHARR_ENV="modular", DISPATCHARR_WEB_HOST="w"):
            self.assertEqual(
                relay_client.get_relay_control_base_url(),
                control_plane.get_control_plane_base_url(),
            )
        with _env(
            DISPATCHARR_ENV="modular",
            DISPATCHARR_WEB_HOST="w",
            DISPATCHARR_RELAY_BASE_URL="http://elsewhere:1",
        ):
            self.assertEqual(
                relay_client.get_relay_control_base_url(), "http://elsewhere:1"
            )
            self.assertEqual(
                control_plane.get_control_plane_base_url(), "http://w:9191"
            )

    def test_a_host_django_would_refuse_fails_at_resolve_time(self):
        # Amendment S10 point 10: an underscore reaches get_host() as a
        # Host header Django rejects before ALLOWED_HOSTS is consulted.
        with _env(DISPATCHARR_ENV="modular", DISPATCHARR_WEB_HOST="bad_host"):
            with self.assertRaises(ImproperlyConfigured) as caught:
                relay_client.get_relay_control_base_url()
        self.assertEqual(caught.exception.var_name, "DISPATCHARR_WEB_HOST")

    def test_a_scheme_less_override_is_named_but_never_echoed(self):
        with _env(DISPATCHARR_RELAY_BASE_URL="user:pw@relay:9191"):
            with self.assertRaises(ImproperlyConfigured) as caught:
                relay_client.get_relay_control_base_url()
        self.assertIn("DISPATCHARR_RELAY_BASE_URL", str(caught.exception))
        self.assertNotIn("pw", str(caught.exception))
