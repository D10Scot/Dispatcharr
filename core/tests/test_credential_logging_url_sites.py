"""Log calls the widened credential-logging check found leaking a URL or a
login: they must log through `redact_url` or a non-sensitive fact instead.

THE DEFECT CLASS. `scripts/check_credential_logging.py` matched `_url` but not a
bare `url`, so these calls were invisible to it:

- `core/xtream_codes.py` `Client._make_request` logged the request URL and the
  whole params dict (`username`, `password`) at DEBUG, and again at ERROR when
  the request failed;
- `core/image_proxy.py` logged the remote image URL (M3U `tvg-logo` values can
  carry a login) and `requests`' exception text, which embeds the URL, at
  WARNING;
- `apps/epg/sd_utils.py` `sd_authorized_request` logged its request URL at
  WARNING when a token was rejected;
- `apps/plugins/api_views.py` logged a plugin repository URL (a private
  repository can carry a token in it) and, for the refresh path, a traceback
  whose exception text repeats it.

Each test calls the real function with obviously fake secrets, captures every
record at TRACE (level 5) and fails naming the leaked value.
"""

import logging
from unittest.mock import MagicMock, patch

import requests
from django.http import Http404
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.epg import sd_utils
from apps.plugins import api_views as plugin_api_views
from apps.plugins.models import PluginRepo
from core import image_proxy, xtream_codes

TRACE = 5
SECRETS = ("fakeuser", "fakepass", "faketoken")


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(level=TRACE)
        self.records = []

    def emit(self, record):
        self.records.append(record)


class capture:
    """Collect every record from the given loggers at TRACE; fail if none."""

    def __init__(self, *loggers):
        self.loggers = loggers
        self.handler = _Records()
        self.saved = []

    def __enter__(self):
        for lg in self.loggers:
            self.saved.append((lg, lg.level, lg.propagate))
            lg.setLevel(TRACE)
            lg.addHandler(self.handler)
        return self.handler

    def __exit__(self, exc_type, exc, tb):
        for lg, level, propagate in self.saved:
            lg.removeHandler(self.handler)
            lg.setLevel(level)
        if exc_type is None:
            assert self.handler.records, "no log record captured: the capture is vacuous"
        return False


def assert_no_secret(test, records):
    for rec in records:
        text = " | ".join(
            [rec.getMessage(), repr(rec.args), rec.exc_text or ""]
        )
        if rec.exc_info:
            text += " | " + repr(rec.exc_info[1])
        for secret in SECRETS:
            test.assertNotIn(
                secret, text, f"{rec.name} {rec.levelname} leaked {secret!r}: {text}"
            )


class XtreamClientLoggingTests(SimpleTestCase):
    def make_client(self):
        return xtream_codes.Client("http://prov.example.com", "fakeuser", "fakepass")

    PARAMS = {"username": "fakeuser", "password": "fakepass", "action": "get_live"}

    def test_request_line_names_no_url_secret_or_param_value(self):
        client = self.make_client()
        response = MagicMock(content=b"[]", text="[]")
        response.json.return_value = []
        client.session.get = MagicMock(return_value=response)
        with capture(xtream_codes.logger) as logs:
            result = client._make_request(
                "player_api.php?username=fakeuser&password=fakepass", dict(self.PARAMS)
            )
        self.assertEqual(result, [])
        assert_no_secret(self, logs.records)

    def test_failure_details_name_no_url_secret_or_param_value(self):
        client = self.make_client()
        client.session.get = MagicMock(
            side_effect=requests.ConnectionError("connection refused")
        )
        with capture(xtream_codes.logger) as logs:
            with self.assertRaises(requests.ConnectionError):
                client._make_request(
                    "player_api.php?username=fakeuser&password=fakepass", dict(self.PARAMS)
                )
        assert_no_secret(self, logs.records)


class ImageProxyLoggingTests(TestCase):
    URL = "http://fakeuser:fakepass@prov.example.com/logo/1.png"

    def test_blocked_url_is_logged_redacted(self):
        with patch.object(
            image_proxy, "validate_outbound_http_url", side_effect=ValueError(self.URL)
        ):
            with capture(image_proxy.logger) as logs:
                with self.assertRaises(Http404):
                    image_proxy.serve_local_or_remote_image(self.URL, failure_cache={})
        assert_no_secret(self, logs.records)

    def test_fetch_failure_logs_neither_url_nor_exception_text(self):
        with patch.object(image_proxy, "validate_outbound_http_url"), patch.object(
            image_proxy.requests,
            "get",
            side_effect=requests.ConnectionError(f"failed to reach {self.URL}"),
        ):
            with capture(image_proxy.logger) as logs:
                with self.assertRaises(Http404):
                    image_proxy.serve_local_or_remote_image(self.URL, failure_cache={})
        assert_no_secret(self, logs.records)


class SdRequestLoggingTests(TestCase):
    def test_token_rejected_warning_logs_redacted_url(self):
        from apps.epg.models import EPGSource

        source = EPGSource.objects.create(name="sd", source_type="schedules_direct")
        url = "https://sd.example.com/20141201/lineups?password=fakepass"
        rejected = MagicMock(status_code=401)
        with patch.object(sd_utils.requests, "get", return_value=rejected), patch.object(
            sd_utils, "sd_obtain_token", return_value=MagicMock(ok=False, token=None)
        ), patch.object(sd_utils, "sd_parse_response_payload", return_value=(None, None)):
            with capture(sd_utils.logger) as logs:
                sd_utils.sd_authorized_request(
                    "GET", url, source=source, token="stale"
                )
        assert_no_secret(self, logs.records)


class PluginRepoLoggingTests(TestCase):
    URL = "https://prov.example.com/manifest.json?token=faketoken"

    def setUp(self):
        admin = User.objects.create_user(username="plugin-log-admin", password="x")
        admin.user_level = 10
        admin.save()
        self.client = APIClient()
        self.client.force_authenticate(user=admin)

    def test_refresh_failure_logs_no_repo_url_secret_or_traceback_text(self):
        repo = PluginRepo.objects.create(name="r", url=self.URL)
        with patch.object(
            plugin_api_views, "_fetch_manifest", side_effect=RuntimeError(self.URL)
        ):
            with capture(plugin_api_views.logger) as logs:
                response = self.client.post(f"/api/plugins/repos/{repo.pk}/refresh/")
        self.assertEqual(response.status_code, 502)
        assert_no_secret(self, logs.records)

    def test_create_failure_logs_no_repo_url_secret(self):
        with patch.object(
            plugin_api_views, "_fetch_manifest", side_effect=RuntimeError(self.URL)
        ):
            with capture(plugin_api_views.logger) as logs:
                response = self.client.post(
                    "/api/plugins/repos/", {"url": self.URL}, format="json"
                )
        self.assertGreaterEqual(response.status_code, 400)
        assert_no_secret(self, logs.records)
