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
SECRETS = ("fakeuser", "fakepass", "faketoken", "fakesecret")


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


def assert_logged(test, records, fragment):
    """The event under test was emitted, so a passing no-secret check is not vacuous."""
    test.assertTrue(
        any(fragment in r.getMessage() for r in records),
        f"no record containing {fragment!r}: {[r.getMessage() for r in records]}",
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
        assert_logged(self, logs.records, "XC API Request: http://prov.example.com/player_api.php")
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
        assert_logged(self, logs.records, "XC API Request failed: requests.exceptions.ConnectionError")
        assert_logged(self, logs.records, "Request details: URL=")
        assert_no_secret(self, logs.records)

    ENDPOINT = "player_api.php?username=fakeuser&password=fakepass"
    CRED_URL = "http://prov.example.com/player_api.php?username=fakeuser&password=fakepass"

    def run_failing(self, expected, event, **session_get):
        client = self.make_client()
        client.session.get = MagicMock(**session_get)
        with capture(xtream_codes.logger) as logs:
            with self.assertRaises(expected):
                client._make_request(self.ENDPOINT, dict(self.PARAMS))
        assert_logged(self, logs.records, event)
        assert_no_secret(self, logs.records)

    def test_request_exception_text_with_the_full_url_is_not_logged(self):
        # requests quotes the full request URL, query string included.
        self.run_failing(
            requests.ConnectionError,
            "XC API Request failed: requests.exceptions.ConnectionError",
            side_effect=requests.ConnectionError(
                f"HTTPConnectionPool: Max retries exceeded with url: {self.CRED_URL}"
            ),
        )

    def test_http_error_text_with_the_full_url_is_not_logged(self):
        response = MagicMock(content=b"x", text="x")
        response.raise_for_status.side_effect = requests.HTTPError(
            f"403 Client Error: Forbidden for url: {self.CRED_URL}"
        )
        self.run_failing(
            requests.HTTPError,
            "XC API Request failed: requests.exceptions.HTTPError",
            return_value=response,
        )

    def test_empty_blocked_and_invalid_json_responses_log_no_url_secret(self):
        empty = MagicMock(content=b"", text="")
        blocked = MagicMock(content=b"blocked", text="blocked")
        bad_json = MagicMock(content=b"<html>", text="<html>")
        bad_json.json.side_effect = requests.exceptions.JSONDecodeError("bad", "<html>", 0)
        for label, response, event in (
            ("empty", empty, "returned empty response from http://prov.example.com/player_api.php"),
            ("blocked", blocked, "request blocked by server from http://prov.example.com/player_api.php"),
            ("json", bad_json, "returned invalid JSON from http://prov.example.com/player_api.php"),
        ):
            with self.subTest(label):
                self.run_failing(ValueError, event, return_value=response)

    def test_unexpected_exception_text_and_traceback_log_no_secret(self):
        self.run_failing(
            KeyError, "XC API Unexpected error: KeyError", side_effect=KeyError(self.CRED_URL)
        )

    def test_the_raised_error_text_is_unchanged(self):
        # Logging only: callers still receive the same message.
        client = self.make_client()
        client.session.get = MagicMock(return_value=MagicMock(content=b"", text=""))
        with self.assertRaises(ValueError) as caught:
            client._make_request("player_api.php", {})
        self.assertEqual(
            str(caught.exception),
            "XC API returned empty response from http://prov.example.com/player_api.php",
        )


class XtreamPublicMethodLoggingTests(SimpleTestCase):
    """Provider bodies and exception text are unstructured: a secret in them
    has no URL shape for any redactor to find. The public methods must log
    fixed events, counts and exception types only, and still raise and return
    exactly what they did."""

    BODY = "fakesecret fakepass fakeuser"

    def make_client(self):
        return xtream_codes.Client("http://prov.example.com", "fakeuser", "fakepass")

    def response(self, payload=None, text=None):
        resp = MagicMock()
        resp.content = b"x"
        resp.text = text if text is not None else self.BODY
        resp.raise_for_status = MagicMock()
        if isinstance(payload, Exception):
            resp.json.side_effect = payload
        else:
            resp.json.return_value = payload
        return resp

    AUTH_OK = {"user_info": {"username": "fakeuser", "auth": 1}, "server_info": {}}

    def authed(self, client):
        client.server_info = dict(self.AUTH_OK)
        return client

    # (method, takes an id, success event, handler event). "{n}" is the count
    # of returned items, "{id}" the provider id as the log shows it.
    FETCHERS = (
        ("get_live_categories", False, "Successfully retrieved {n} live categories",
         "Failed to get live categories: {exc}"),
        ("get_live_category_streams", True, "Successfully retrieved {n} streams for category {id}",
         "Failed to get streams for category {id}: {exc}"),
        ("get_all_live_streams", False, "Successfully retrieved {n} total live streams",
         "Failed to get all live streams: {exc}"),
        ("get_vod_categories", False, "Successfully retrieved {n} VOD categories",
         "Failed to get VOD categories: {exc}"),
        ("get_vod_streams", True, "Successfully retrieved {n} VOD streams for category {id}",
         "Failed to get VOD streams for category {id}: {exc}"),
        ("get_vod_info", True, "Successfully retrieved VOD info for vod_id {id}",
         "Failed to get VOD info for vod_id {id}: {exc}"),
        ("get_series_categories", False, "Successfully retrieved {n} series categories",
         "Failed to get series categories: {exc}"),
        ("get_series", True, "Successfully retrieved {n} series for category {id}",
         "Failed to get series for category {id}: {exc}"),
        ("get_series_info", True, "Successfully retrieved series info for series_id {id}",
         "Failed to get series info for series_id {id}: {exc}"),
    )
    DICT_FETCHERS = ("get_vod_info", "get_series_info")

    def call(self, client, name, takes_id, provider_id):
        return getattr(client, name)(provider_id) if takes_id else getattr(client, name)()

    def test_authenticate_success_logs_no_username_or_response(self):
        client = self.make_client()
        client.session.get = MagicMock(return_value=self.response(dict(self.AUTH_OK)))
        with capture(xtream_codes.logger) as logs:
            info = client.authenticate()
        self.assertEqual(info, self.AUTH_OK)
        assert_logged(self, logs.records, "XC Authentication successful")
        assert_no_secret(self, logs.records)

    def test_authenticate_failures_log_no_response_body(self):
        cases = (
            ("error key", self.response({"error": "fakesecret fakepass"})),
            ("no user_info", self.response({"note": "fakesecret fakepass fakeuser"})),
            (
                "invalid json",
                self.response(
                    requests.exceptions.JSONDecodeError("fakesecret fakepass", "x", 0),
                    text="fakesecret fakepass fakeuser",
                ),
            ),
        )
        for label, response in cases:
            with self.subTest(label):
                client = self.make_client()
                client.session.get = MagicMock(return_value=response)
                with capture(xtream_codes.logger) as logs:
                    with self.assertRaises(ValueError) as caught:
                        client.authenticate()
                self.assertRegex(
                    str(caught.exception),
                    r"^(XC API Error|Authentication failed|XC API returned invalid JSON)",
                )
                assert_logged(self, logs.records, "XC Authentication failed: ValueError")
                assert_no_secret(self, logs.records)

    def test_every_fetcher_logs_no_body_on_an_unexpected_shape(self):
        for name, takes_id, _success, handler in self.FETCHERS:
            with self.subTest(name):
                client = self.authed(self.make_client())
                # a str where a dict or a list is expected
                client.session.get = MagicMock(return_value=self.response(self.BODY))
                if name not in self.DICT_FETCHERS:
                    client.session.get.return_value = self.response({"detail": self.BODY})
                with capture(xtream_codes.logger) as logs:
                    with self.assertRaises(ValueError) as caught:
                        self.call(client, name, takes_id, "5")
                self.assertTrue(str(caught.exception).startswith("Invalid "), caught.exception)
                shown = "str" if name in self.DICT_FETCHERS else "dict"
                assert_logged(self, logs.records, f"unexpected response shape: {shown}")
                assert_logged(self, logs.records, handler.format(id="5", exc="ValueError"))
                assert_no_secret(self, logs.records)

    def test_every_fetcher_logs_no_exception_text_or_traceback_message(self):
        for name, takes_id, _success, handler in self.FETCHERS:
            with self.subTest(name):
                client = self.authed(self.make_client())
                client.session.get = MagicMock(
                    side_effect=requests.ConnectionError(
                        "fakesecret http://prov.example.com/?password=fakepass"
                    )
                )
                with capture(xtream_codes.logger) as logs:
                    with self.assertRaises(requests.ConnectionError):
                        self.call(client, name, takes_id, "5")
                # The fetcher's own handler ran (not only _make_request's).
                assert_logged(self, logs.records, handler.format(id="5", exc="ConnectionError"))
                assert_logged(self, logs.records, "Traceback frames:")
                assert_no_secret(self, logs.records)

    def test_every_fetcher_logs_a_placeholder_for_a_provider_id_and_returns_its_payload(self):
        for name, takes_id, success, _handler in self.FETCHERS:
            if not takes_id:
                continue
            with self.subTest(name):
                client = self.authed(self.make_client())
                payload = {"info": {"k": 1}} if name in self.DICT_FETCHERS else [{"i": 1}, {"i": 2}]
                client.session.get = MagicMock(return_value=self.response(payload))
                with capture(xtream_codes.logger) as logs:
                    result = self.call(client, name, takes_id, "fakesecret-id")
                self.assertEqual(result, payload)
                assert_logged(self, logs.records, success.format(n=2, id="<id>"))
                assert_no_secret(self, logs.records)

    def test_every_fetcher_logs_its_success_count_and_returns_its_payload(self):
        for name, takes_id, success, _handler in self.FETCHERS:
            with self.subTest(name):
                client = self.authed(self.make_client())
                payload = {"info": {"k": 1}} if name in self.DICT_FETCHERS else [{"n": "fakesecret"}, {"n": "x"}]
                client.session.get = MagicMock(return_value=self.response(payload))
                with capture(xtream_codes.logger) as logs:
                    result = self.call(client, name, takes_id, "5")
                self.assertEqual(result, payload)
                assert_logged(self, logs.records, success.format(n=2, id="5"))
                assert_no_secret(self, logs.records)

    def test_traceback_frames_carry_no_source_line_or_chained_message(self):
        # The raising frame's own SOURCE contains a credential-bearing literal;
        # format_tb() would log that line. The chained cause has a message too.
        # Both fixtures are session.get side effects, so they take its arguments.
        def raises_chained(*args, **kwargs):
            try:
                raise ValueError("fakesecret cause")
            except ValueError as cause:
                raise RuntimeError("fakesecret") from cause  # http://prov.example.com/live/fakeuser/fakepass/1.ts

        def raises_with_literal_in_source(*args, **kwargs):
            raise OSError("http://prov.example.com/live/fakeuser/fakepass/1.ts")

        for label, raiser, expected in (
            ("chained", raises_chained, RuntimeError),
            ("literal in the raising line", raises_with_literal_in_source, OSError),
        ):
            with self.subTest(label):
                client = self.authed(self.make_client())
                client.session.get = MagicMock(side_effect=raiser)
                with capture(xtream_codes.logger) as logs:
                    with self.assertRaises(expected) as caught:
                        client.get_live_categories()
                if expected is RuntimeError:
                    self.assertIsInstance(caught.exception.__cause__, ValueError)
                assert_no_secret(self, logs.records)
                frames = [r.getMessage() for r in logs.records if "Traceback frames" in r.getMessage()]
                self.assertTrue(frames, "the frame metadata must still be logged")
                self.assertIn("xtream_codes.py", frames[0])
                self.assertIn(raiser.__name__, frames[0], "the raising frame must be named")

    def test_raised_messages_are_unchanged(self):
        client = self.authed(self.make_client())
        client.session.get = MagicMock(return_value=self.response({"detail": "d"}))
        with self.assertRaises(ValueError) as caught:
            client.get_live_categories()
        self.assertEqual(str(caught.exception), "Invalid categories response: {'detail': 'd'}")
        client = self.make_client()
        client.session.get = MagicMock(return_value=self.response({"error": "boom"}))
        with self.assertRaises(ValueError) as caught:
            client.authenticate()
        self.assertEqual(str(caught.exception), "XC API Error: boom")


class ImageProxyLoggingTests(TestCase):
    URL = "http://fakeuser:fakepass@prov.example.com/logo/1.png"

    def test_blocked_url_is_logged_redacted(self):
        with patch.object(
            image_proxy, "validate_outbound_http_url", side_effect=ValueError(self.URL)
        ):
            with capture(image_proxy.logger) as logs:
                with self.assertRaises(Http404):
                    image_proxy.serve_local_or_remote_image(self.URL, failure_cache={})
        assert_logged(self, logs.records, "Blocked unsafe remote image URL")
        assert_no_secret(self, logs.records)

    def test_rejected_local_path_input_is_not_logged(self):
        # The input starts with /data but is whatever the caller supplied.
        url = "/data/https://prov.example.com/live/fakeuser/fakepass/1.png"
        with patch.object(image_proxy, "resolve_safe_local_data_path", return_value=None):
            with capture(image_proxy.logger) as logs:
                with self.assertRaises(Http404):
                    image_proxy.serve_local_or_remote_image(url, failure_cache={})
        assert_logged(self, logs.records, "file not found or unsafe path")
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
        assert_logged(self, logs.records, "Error fetching remote")
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
        assert_logged(self, logs.records, "clearing cached token and retrying once")
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
        assert_logged(self, logs.records, "Manifest fetch failed")
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
        assert_logged(self, logs.records, "Initial manifest fetch failed")
        assert_no_secret(self, logs.records)
