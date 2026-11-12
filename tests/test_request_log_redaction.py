"""Xtream credentials never reach the output of Django's own request log records.

Django logs ``Unauthorized: <request.path>`` (and ``Not Found``, ``Bad
Request``, ``Internal Server Error``, ``Not Implemented`` ...) through
``django.request`` for every 4xx/5xx, ``Forbidden (<reason>): <path>`` through
``django.security.csrf``, the exception text of a ``SuspiciousOperation``
through ``django.security.<Name>``, and a request line per request through the
development servers' loggers. The Xtream routes carry the login in the path or
the query string, so before ``core/request_log_redaction.py`` the first line
below was printed verbatim, at WARNING, on the inline (no-nginx) path:

    WARNING django.request Unauthorized: /movie/<username>/<password>/1.mp4

Every test here drives a real request (or, for the two development servers,
their own logging method) and inspects what the PRODUCTION logging
configuration's handlers actually receive: the root logger's ``console``
handler and ``otel`` bridge as ``settings.LOGGING`` builds them (the test
settings import that dict unchanged), Django's own ``DEFAULT_LOGGING`` console
on the ``django`` logger under DEBUG, and the ``django.server`` handler. The
handlers are found by the names ``dictConfig`` gives them and their streams
swapped for buffers; no handler is replaced and no filter is added by a test,
so a test cannot pass on a configuration production does not run.
``RealConfigurationTests`` checks that premise.
"""
import io
import logging
from unittest import mock
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import SuspiciousFileOperation
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver

from core.request_log_redaction import (
    REDACTED_LOGGER_TREES,
    RequestLogCredentialFilter,
    redact_record,
)
from dispatcharr.observability import logs as observability_logs
from dispatcharr.utils import redact_url

# Distinctive, obviously fake, low-entropy values: nothing in a URL, a reason
# phrase or a traceback contains them by accident.
USER = "xcuser-sentinel-one"
PASSWORD = "xcpw-sentinel-two"
WRONG = "wrongpw-sentinel-three"
NONASCII_USER = "xcusér-sentinel-ü1"
NONASCII_PASSWORD = "xcpäss-sentinel-ø2"
SPECIAL_PASSWORD = "re.*+?(sentinel)[x]$^|7"


def _forms(value):
    """Every spelling of ``value`` a log line could carry."""
    return {
        value,
        quote(value, safe=""),
        quote(value),
        value.encode("unicode_escape").decode("ascii"),
    }


class _Capture(logging.Handler):
    """Stands in for the OTel SDK handler behind the bridge (``install_inner_handler``)."""

    def __init__(self):
        super().__init__(level=1)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _handler(logger_name, handler_name):
    for handler in logging.getLogger(logger_name).handlers:
        if handler.get_name() == handler_name:
            return handler
    raise AssertionError(f"logger {logger_name!r} has no handler named {handler_name!r}")


def _django_debug_console():
    # Django's DEFAULT_LOGGING console (re-declared by the fix as
    # "django.console"): the only plain StreamHandler on the django logger.
    for handler in logging.getLogger("django").handlers:
        if type(handler) is logging.StreamHandler:
            return handler
    raise AssertionError("the django logger has no DEFAULT_LOGGING console handler")


class _ProductionSinks:
    """Buffers behind the production handlers, restored on exit."""

    def __init__(self, test):
        self.console = io.StringIO()
        self.debug_console = io.StringIO()
        self.server = io.StringIO()
        self.otel = _Capture()
        for handler, stream in (
            (_handler("", "console"), self.console),
            (_django_debug_console(), self.debug_console),
            (_handler("django.server", "django.server"), self.server),
        ):
            previous = handler.setStream(stream)
            test.addCleanup(handler.setStream, previous)
        observability_logs.install_inner_handler(self.otel)
        test.addCleanup(observability_logs.install_inner_handler, None)

    def otel_text(self):
        parts = []
        for record in self.otel.records:
            parts += [record.getMessage(), repr(record.msg), repr(record.args), repr(vars(record))]
        return "\n".join(parts)

    def everything(self):
        return "\n".join(
            [
                self.console.getvalue(),
                self.debug_console.getvalue(),
                self.server.getvalue(),
                self.otel_text(),
            ]
        )


class _SinkAssertions:
    def assertNoCredential(self, sinks, *values):
        text = sinks.everything()
        for value in values:
            for form in _forms(value):
                self.assertNotIn(
                    form,
                    text,
                    f"credential form {form!r} reached a production log handler:\n{text}",
                )


@override_settings(DEBUG=True)
class XtreamRequestLogTests(_SinkAssertions, TestCase):
    """One real request per Xtream shape and status class.

    DEBUG is on so Django's own ``DEFAULT_LOGGING`` console on the ``django``
    logger writes too: the handler production gets when DEBUG is switched on,
    and the one this configuration does not define.
    """

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        for username, password in (
            (USER, PASSWORD),
            (NONASCII_USER, NONASCII_PASSWORD),
            ("xcuser-special-sentinel", SPECIAL_PASSWORD),
        ):
            user = User.objects.create_user(username=username, password="unused-login-pw")
            user.custom_properties = {"xc_password": password}
            user.save()

    def setUp(self):
        self.sinks = _ProductionSinks(self)
        self.client = Client(raise_request_exception=False)
        # The timeshift views call close_old_connections(), which closes the
        # connection a TestCase's transaction runs on; the next test's first
        # query then fails. apps/timeshift/tests/test_views.py patches it the same way.
        patcher = mock.patch("apps.timeshift.views.close_old_connections")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _get(self, path, expected_status, *credentials):
        response = self.client.get(path)
        self.assertEqual(response.status_code, expected_status, self.sinks.console.getvalue()[-3000:])
        self.assertNoCredential(self.sinks, *credentials)
        return response

    def assertConsoleHas(self, line):
        self.assertIn(line, self.sinks.console.getvalue())
        self.assertIn(line, self.sinks.debug_console.getvalue())
        self.assertIn(line, [r.getMessage() for r in self.sinks.otel.records])

    # -- credentials in the path -------------------------------------------

    def test_movie_401(self):
        self._get(f"/movie/{USER}/{WRONG}/1.mp4", 401, USER, WRONG)
        self.assertConsoleHas("Unauthorized: /movie/***/***/1.mp4")

    def test_movie_404_with_the_right_password(self):
        self._get(f"/movie/{USER}/{PASSWORD}/1.mp4", 404, USER, PASSWORD)
        self.assertConsoleHas("Not Found: /movie/***/***/1.mp4")

    def test_series_401(self):
        self._get(f"/series/{USER}/{WRONG}/1.mkv", 401, USER, WRONG)
        self.assertConsoleHas("Unauthorized: /series/***/***/1.mkv")

    def test_timeshift_path_form(self):
        path = f"/timeshift/{USER}/{WRONG}/60/2026-01-01:10-00/1.ts"
        status = self.client.get(path).status_code
        self.assertGreaterEqual(status, 400, "the case must produce a django.request record")
        self.assertNoCredential(self.sinks, USER, WRONG)
        self.assertIn("/timeshift/***/***/60/2026-01-01:10-00/1.ts", self.sinks.console.getvalue())

    def test_live_prefix_501(self):
        self._get(f"/live/{USER}/{PASSWORD}/1.ts", 501, USER, PASSWORD)
        self.assertConsoleHas("Not Implemented: /live/***/***/1.ts")

    def test_bare_root_501(self):
        self._get(f"/{USER}/{PASSWORD}/1.ts", 501, USER, PASSWORD)
        self.assertConsoleHas("Not Implemented: /***/***/1.ts")

    def test_non_ascii_credentials(self):
        self._get(f"/movie/{quote(NONASCII_USER)}/{quote(NONASCII_PASSWORD)}/1.mp4", 404,
                  NONASCII_USER, NONASCII_PASSWORD)
        self.assertConsoleHas("Not Found: /movie/***/***/1.mp4")

    def test_percent_encoded_and_regex_special_credentials(self):
        path = f"/movie/xcuser-special-sentinel/{quote(SPECIAL_PASSWORD, safe='')}/1.mp4"
        self._get(path, 404, "xcuser-special-sentinel", SPECIAL_PASSWORD)
        self.assertConsoleHas("Not Found: /movie/***/***/1.mp4")

    def test_encoded_space_in_a_credential(self):
        user = "xcuser sentinel-sp3"
        self.client.get(f"/movie/{quote(user)}/{quote(user)}/1.mp4")
        self.assertNoCredential(self.sinks, user, "sentinel-sp3")

    # -- credentials in the query string ------------------------------------

    def test_query_string_endpoints_401(self):
        for path in (
            f"/player_api.php?username={USER}&password={WRONG}",
            f"/get.php?username={USER}&password={WRONG}&type=m3u_plus",
            f"/xmltv.php?username={USER}&password={WRONG}",
            f"/streaming/timeshift.php?username={USER}&password={WRONG}"
            "&stream=1&start=2026-01-01:10-00&duration=60",
        ):
            with self.subTest(path=path.split("?")[0]):
                self._get(path, 401, USER, WRONG)
        self.assertIn("Unauthorized: /player_api.php", self.sinks.console.getvalue())

    # -- the other status classes -------------------------------------------

    def test_403_csrf_on_an_xtream_path(self):
        # A non-numeric id matches no XC route, so the request reaches the SPA
        # catch-all, which (unlike the csrf_exempt XC views) CSRF-checks a POST.
        client = Client(enforce_csrf_checks=True, raise_request_exception=False)
        response = client.post(f"/live/{USER}/{PASSWORD}/abc")
        self.assertEqual(response.status_code, 403)
        self.assertNoCredential(self.sinks, USER, PASSWORD)
        self.assertConsoleHas("Forbidden (CSRF cookie not set.): /live/***/***/abc")

    def test_400_suspicious_operation_from_a_dynamic_security_logger(self):
        path = f"/movie/{USER}/{PASSWORD}/1.mp4"
        with mock.patch(
            "apps.proxy.vod_proxy.views.resolve_authorization",
            side_effect=SuspiciousFileOperation(f"refused {path}"),
        ):
            self._get(path, 400, USER, PASSWORD)
        # Django logs a SuspiciousOperation through the security logger only
        # (no django.request "Bad Request" line), message and traceback.
        console = self.sinks.console.getvalue()
        self.assertIn("django.security.SuspiciousFileOperation refused /movie/***/***/1.mp4", console)
        self.assertIn("SuspiciousFileOperation: refused /movie/***/***/1.mp4", console)

    def test_500_traceback_carrying_the_path(self):
        path = f"/movie/{USER}/{PASSWORD}/1.mp4"
        with mock.patch(
            "apps.proxy.vod_proxy.views.resolve_authorization",
            side_effect=RuntimeError(f"lookup failed for {path} as '{USER}'"),
        ):
            self._get(path, 500, USER, PASSWORD)
        console = self.sinks.console.getvalue()
        self.assertIn("Internal Server Error: /movie/***/***/1.mp4", console)
        self.assertIn("Traceback (most recent call last)", console)
        self.assertIn("RuntimeError: lookup failed for /movie/***/***/1.mp4", console)

    # -- the control --------------------------------------------------------

    def test_an_ordinary_path_is_logged_unchanged(self):
        response = self.client.get("/api/accounts/users/5/")
        self.assertEqual(response.status_code, 401)
        self.assertConsoleHas("Unauthorized: /api/accounts/users/5/")


class DevelopmentServerLogTests(_SinkAssertions, SimpleTestCase):
    """The request lines of both development servers, through their own methods."""

    def setUp(self):
        self.sinks = _ProductionSinks(self)

    def test_django_runserver_request_line(self):
        from django.core.servers.basehttp import WSGIRequestHandler

        handler = WSGIRequestHandler.__new__(WSGIRequestHandler)
        handler.request = mock.Mock()
        handler.client_address = ("127.0.0.1", 50000)
        handler.log_message(
            '"%s" %s %s',
            f"GET /movie/{USER}/{PASSWORD}/1.mp4?username={USER}&password={PASSWORD} HTTP/1.1",
            "401",
            "17",
        )
        self.assertNoCredential(self.sinks, USER, PASSWORD)
        self.assertIn(
            '"GET /movie/***/***/1.mp4?username=***&password=*** HTTP/1.1" 401 17',
            self.sinks.server.getvalue(),
        )

    def test_daphne_runserver_request_line(self):
        from daphne.management.commands.runserver import Command

        Command().log_action(
            "http",
            "complete",
            {
                "method": "GET",
                "path": f"/live/{USER}/{PASSWORD}/1.ts",
                "status": 401,
                "time_taken": 0.01,
                "client": "127.0.0.1:50000",
            },
        )
        self.assertNoCredential(self.sinks, USER, PASSWORD)
        self.assertIn("HTTP GET /live/***/***/1.ts 401", self.sinks.console.getvalue())


class UrlconfCoverageTests(SimpleTestCase):
    """Every urlconf route that captures a username and a password is redacted.

    The shapes are defined once, in the project package's ``utils.redact_url``;
    this walks the live urlconf so a new credential-in-path route that the
    definition does not cover fails here, without anyone listing it.
    """

    SAMPLES = {"username": USER, "password": PASSWORD}

    def _credential_routes(self, patterns, prefix=""):
        for entry in patterns:
            if isinstance(entry, URLResolver):
                yield from self._credential_routes(entry.url_patterns, prefix + str(entry.pattern))
            elif isinstance(entry, URLPattern):
                groups = set(entry.pattern.regex.groupindex)
                if {"username", "password"} <= groups:
                    yield entry, prefix

    def _sample_path(self, entry, prefix):
        from django.urls import reverse

        kwargs = {name: self.SAMPLES.get(name, "1") for name in entry.pattern.regex.groupindex}
        self.assertEqual(prefix, "", "credential routes are mounted at the site root")
        return reverse(entry.name, kwargs=kwargs)

    def test_every_credential_route_is_covered(self):
        routes = list(self._credential_routes(get_resolver().url_patterns))
        names = {entry.name for entry, _ in routes}
        # The walk must actually find the routes, or this test passes empty.
        self.assertLessEqual(
            {
                "xc_live_stream_endpoint",
                "xc_stream_endpoint",
                "timeshift_proxy",
                "stream_xc_movie",
                "stream_xc_episode",
            },
            names,
        )
        for entry, prefix in routes:
            path = self._sample_path(entry, prefix)
            with self.subTest(route=entry.name, path=path):
                out = redact_url(path)
                self.assertNotIn(USER, out)
                self.assertNotIn(PASSWORD, out)


class RealConfigurationTests(SimpleTestCase):
    """The premise of the tests above, and the property the fix rests on."""

    def test_the_handlers_are_the_ones_settings_logging_defines(self):
        self.assertIn("console", settings.LOGGING["handlers"])
        self.assertIn("otel", settings.LOGGING["handlers"])
        root = logging.getLogger()
        self.assertIn(_handler("", "console"), root.handlers)
        self.assertIn(_handler("", "otel"), root.handlers)
        self.assertEqual(type(_handler("", "otel")).__name__, "OtelBridgeHandler")

    def test_every_handler_a_request_record_can_reach_carries_the_filter(self):
        # A handler added later on any of these paths, by anyone, fails here.
        names = [
            "django.request",
            "django.security.csrf",
            "django.security.SomeFutureSuspiciousOperation",
            "django.server",
            "django.channels.server",
        ]
        for name in names:
            logger = logging.getLogger(name)
            reached = []
            while logger is not None:
                reached += logger.handlers
                logger = logger.parent if logger.propagate else None
            self.assertTrue(reached, name)
            for handler in reached:
                with self.subTest(logger=name, handler=handler.get_name()):
                    self.assertTrue(
                        any(isinstance(f, RequestLogCredentialFilter) for f in handler.filters),
                        f"{name} reaches handler {handler.get_name()!r} ({type(handler).__name__}) "
                        "without the credential filter",
                    )


class FilterUnitTests(SimpleTestCase):
    def _record(self, name, msg, *args, **extra):
        record = logging.LogRecord(name, logging.WARNING, __file__, 1, msg, args, None)
        for key, value in extra.items():
            setattr(record, key, value)
        return record

    def test_out_of_scope_records_pass_through_as_the_same_object(self):
        record = self._record("apps.proxy", "%s", f"/movie/{USER}/{PASSWORD}/1.mp4")
        self.assertIs(redact_record(record), record)

    def test_every_tree_is_in_scope_including_descendants(self):
        for tree in REDACTED_LOGGER_TREES:
            for name in (tree, tree + ".Child"):
                with self.subTest(name=name):
                    record = self._record(name, "%s", f"/movie/{USER}/{PASSWORD}/1.mp4")
                    self.assertEqual(redact_record(record).getMessage(), "/movie/***/***/1.mp4")

    def test_the_original_record_is_never_mutated_and_the_request_is_dropped(self):
        request = mock.Mock(path=f"/movie/{USER}/{PASSWORD}/1.mp4")
        record = self._record("django.request", "%s: %s", "Unauthorized", request.path, request=request)
        out = RequestLogCredentialFilter().filter(record)
        self.assertIsNot(out, record)
        self.assertEqual(record.args[1], request.path)
        self.assertIs(record.request, request)
        self.assertFalse(hasattr(out, "request"))
        self.assertEqual(out.args, ("Unauthorized", "/movie/***/***/1.mp4"))

    def test_mapping_args(self):
        record = self._record("django.channels.server", "%(path)s", {"path": f"/{USER}/{PASSWORD}/1.ts"})
        self.assertEqual(redact_record(record).getMessage(), "/***/***/1.ts")

    def test_a_failure_withholds_the_content_but_not_the_record(self):
        record = self._record("django.request", "%s", f"/movie/{USER}/{PASSWORD}/1.mp4")
        with mock.patch("core.request_log_redaction.redact_record", side_effect=ValueError):
            out = RequestLogCredentialFilter().filter(record)
        self.assertTrue(out)
        self.assertNotIn(PASSWORD, out.getMessage())
        self.assertEqual(out.name, "django.request")
        self.assertEqual(out.levelno, logging.WARNING)
