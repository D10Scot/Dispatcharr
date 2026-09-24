"""Plugin fetches must validate every redirect hop (SSRF prevention).

#103-#105 - three `requests.get` calls validated only the first URL against
the SSRF rules (core.http_security.validate_outbound_http_url), then let
`requests` follow redirects anywhere with its default `allow_redirects=True`,
including loopback and 169.254.169.254. Each site now goes through
`core.http_security.fetch_outbound_http` (via `apps.plugins.api_views._fetch`),
which re-validates every hop's Location before following it.

The `allow_redirects=False` assertion in each test below is what makes it
real. `http_requests` in `api_views.py` is the same `requests` module object
that `core.http_security` imports, so a site still calling `http_requests.get`
directly also hits the patched mock -- what it does not do is pass
`allow_redirects=False`. A mock follows nothing on its own: it just returns
the canned 302 object, so a naive "was the redirect refused" check can pass
for the wrong reason unless the kwarg itself is asserted.
"""

import json
import socket as _socket_module
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.plugins.api_views import _fetch_manifest
from apps.plugins.models import PluginRepo

User = get_user_model()

# Captured before any test patches core.http_security.socket.getaddrinfo,
# which -- because socket is a single shared module object -- replaces
# getaddrinfo process-wide for the life of the patch, not just for
# core.http_security's own callers. Going through the Django test client (as
# the two view-driving tests below do) reaches django-redis, whose real TCP
# connection to "localhost" also resolves through this same function. The
# side_effect below fakes only the hostnames the test cares about and falls
# back to the real resolver for everything else, so cache lookups keep
# working.
_REAL_GETADDRINFO = _socket_module.getaddrinfo


def _fake_addrinfo(*addrs):
    """Build getaddrinfo-style results for the given IP strings."""
    results = []
    for addr in addrs:
        results.append((None, None, None, None, (addr, 0)))
    return results


def _addrinfo_side_effect(mapping):
    """A getaddrinfo side_effect keyed by hostname, for a multi-hop fetch."""

    def _side_effect(host, *args, **kwargs):
        if host in mapping:
            return _fake_addrinfo(mapping[host])
        return _REAL_GETADDRINFO(host, *args, **kwargs)

    return _side_effect


_ADDR_MAP = {
    "public.example": "93.184.216.34",
    "127.0.0.1": "127.0.0.1",
}


class _FakeResponse:
    """A minimal requests.Response stand-in, context-manager included."""

    def __init__(self, status_code=200, headers=None, json_data=None, content=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_data = json_data if json_data is not None else {}
        self._content = content
        self.closed = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data

    def iter_content(self, chunk_size=8192):
        if self._content:
            yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


def _redirect_to_loopback():
    return _FakeResponse(302, headers={"Location": "http://127.0.0.1:5656/x"})


class PluginFetchRedirectsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="plugin-fetch-admin",
            password="x",
            user_level=User.UserLevel.ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _post_json(self, url_name, payload):
        body = json.dumps(payload).encode()
        return self.client.post(
            reverse(url_name), data=body, content_type="application/json"
        )

    def _assert_every_call_refused_redirects(self, mock_get):
        self.assertTrue(mock_get.call_args_list, "requests.get was never called")
        for call in mock_get.call_args_list:
            self.assertIs(
                call.kwargs.get("allow_redirects"),
                False,
                f"call {call} did not pass allow_redirects=False",
            )

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_fetch_manifest_followed_a_redirect_to_loopback(self, mock_gai, mock_get):
        """#103 - PluginRepoListCreateAPIView / PluginRepoPreviewAPIView / refresh."""
        mock_gai.side_effect = _addrinfo_side_effect(_ADDR_MAP)
        mock_get.return_value = _redirect_to_loopback()

        with self.assertRaises(ValueError):
            _fetch_manifest("http://public.example/m.json")

        self._assert_every_call_refused_redirects(mock_get)

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_repo_manifest_detail_followed_a_redirect_to_loopback(
        self, mock_gai, mock_get
    ):
        """#104 - PluginDetailManifestAPIView."""
        mock_gai.side_effect = _addrinfo_side_effect(_ADDR_MAP)
        mock_get.return_value = _redirect_to_loopback()
        repo = PluginRepo.objects.create(
            name="Test repo", url="http://public.example/manifest.json"
        )

        response = self._post_json(
            "api:plugins:plugin-detail-manifest",
            {"repo_id": repo.id, "manifest_url": "http://public.example/m.json"},
        )

        self._assert_every_call_refused_redirects(mock_get)
        self.assertEqual(response.status_code, 502)

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_plugin_install_followed_a_redirect_to_loopback(self, mock_gai, mock_get):
        """#105 - PluginInstallFromRepoAPIView."""
        mock_gai.side_effect = _addrinfo_side_effect(_ADDR_MAP)
        mock_get.return_value = _redirect_to_loopback()
        repo = PluginRepo.objects.create(
            name="Test repo", url="http://public.example/manifest.json"
        )

        response = self._post_json(
            "api:plugins:repo-install",
            {
                "repo_id": repo.id,
                "slug": "test-plugin",
                "version": "1.0.0",
                "download_url": "http://public.example/plugin.zip",
            },
        )

        self._assert_every_call_refused_redirects(mock_get)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json()["error"],
            "Failed to download plugin. Check the URL and try again.",
        )
