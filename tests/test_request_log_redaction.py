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
import copy
import io
import socket
import logging
from unittest import mock
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import SuspiciousFileOperation, TooManyFieldsSent
from django.core.handlers.wsgi import WSGIRequest
import time
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, resolve

from core.request_log_redaction import (
    REDACTED_LOGGER_TREES,
    RequestLogCredentialFilter,
    redact_record,
    redact_text,
    with_request_log_redaction,
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
# Built from the imported module so the file spells the old product name only
# in its imports (scripts/product_name_allowlist.txt).
OTEL_BRIDGE = observability_logs.__name__ + ".OtelBridgeHandler"


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
        handler.request = mock.Mock(spec=socket.socket)  # runserver's is the socket
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
        request = _xc_request(f"/movie/{USER}/{PASSWORD}/1.mp4")
        record = self._record("django.request", "%s: %s", "Unauthorized", request.path, request=request)
        out = RequestLogCredentialFilter().filter(record)
        self.assertIsNot(out, record)
        self.assertEqual(record.args[1], request.path)
        self.assertIs(record.request, request)
        self.assertFalse(hasattr(out, "request"))
        self.assertEqual(out.getMessage(), "Unauthorized: /movie/***/***/1.mp4")
        self.assertEqual(out.args, ())

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


def _xc_request(path, **query):
    """A real HttpRequest for ``path``, resolved the way the handler resolves it."""
    request = RequestFactory().get(path, query)
    request.resolver_match = resolve(request.path_info)
    return request


class ValueScrubTests(SimpleTestCase):
    """The second pass: the values the attached request names as credentials."""

    def _record(self, msg, *args, request=None, name="django.request"):
        record = logging.LogRecord(name, logging.WARNING, __file__, 1, msg, args, None)
        if request is not None:
            record.request = request
        return record

    def test_a_form_the_patterns_miss_is_scrubbed_by_value(self):
        request = _xc_request(f"/movie/{quote(NONASCII_USER)}/{quote(NONASCII_PASSWORD)}/1.mp4")
        self.assertEqual(request.resolver_match.kwargs["password"], NONASCII_PASSWORD)
        record = self._record(
            "lookup failed: user=%s pw=%s raw=%s",
            NONASCII_USER,
            quote(NONASCII_PASSWORD, safe=""),
            f"x{NONASCII_PASSWORD}y",
            request=request,
        )
        # The control: the pattern pass alone leaves all three.
        patterned = copy.copy(record)
        patterned.request = None
        self.assertIn(NONASCII_USER, redact_record(patterned).getMessage())
        message = RequestLogCredentialFilter().filter(record).getMessage()
        for value in (NONASCII_USER, NONASCII_PASSWORD):
            for form in _forms(value):
                self.assertNotIn(form, message)
        self.assertEqual(message, "lookup failed: user=*** pw=*** raw=x***y")

    def test_query_string_values_are_scrubbed_by_value(self):
        request = _xc_request("/player_api.php", username=USER, password=PASSWORD)
        record = self._record("%s: %s (echo %s)", "Unauthorized", "/player_api.php",
                              f"login {USER}:{PASSWORD}", request=request)
        message = RequestLogCredentialFilter().filter(record).getMessage()
        self.assertNotIn(USER, message)
        self.assertNotIn(PASSWORD, message)
        self.assertEqual(message, "Unauthorized: /player_api.php (echo login ***:***)")

    def test_a_one_character_password_does_not_shred_the_message(self):
        request = _xc_request("/movie/u/a/1.mp4")
        self.assertEqual(request.resolver_match.kwargs["password"], "a")
        record = self._record("%s: %s", "Unauthorized", "a banana at a cafe", request=request)
        out = RequestLogCredentialFilter().filter(record)
        self.assertEqual(out.getMessage(), "Unauthorized: a banana at a cafe")
        self.assertEqual(out.args, ("Unauthorized", "a banana at a cafe"))

    def test_a_non_string_argument_is_left_alone(self):
        request = _xc_request(f"/movie/{USER}/{PASSWORD}/1.mp4")
        record = self._record("%s answered %d after %.1fs", "the view", 401, 0.25, request=request)
        out = RequestLogCredentialFilter().filter(record)
        self.assertEqual(out.args, ("the view", 401, 0.25))
        self.assertIs(type(out.args[1]), int)
        self.assertEqual(out.getMessage(), "the view answered 401 after 0.2s")

    def test_a_template_that_cannot_render_is_withheld_not_raised(self):
        request = _xc_request(f"/movie/{USER}/{PASSWORD}/1.mp4")
        record = self._record("%d items for %s", "not-a-number", PASSWORD, request=request)
        out = RequestLogCredentialFilter().filter(record)
        self.assertTrue(out)
        self.assertEqual(out.getMessage(), "[request log record withheld: redaction failed]")
        self.assertNotIn("request", vars(out))


Q_USER = "xcuser-sentinel-q7"
Q_PASS = "xcpw-sentinel-q8"


class RoundOneTests(SimpleTestCase):
    """Review round 1: shapes and records the first pass missed."""

    def _record(self, msg, *args, **extra):
        record = logging.LogRecord("django.request", logging.WARNING, __file__, 1, msg, args, None)
        for key, value in extra.items():
            setattr(record, key, value)
        return record

    def _assert_masked(self, text):
        out = redact_text(text)
        self.assertNotIn(Q_USER, out)
        self.assertNotIn(Q_PASS, out)
        self.assertIn("***", out)

    def test_a_path_starting_with_two_slashes_is_masked(self):
        for text in (
            f"//timeshift/{Q_USER}/{Q_PASS}/60/2026-01-01:10-00/5.ts",
            f"//live/{Q_USER}/{Q_PASS}/abc",
            f"GET //timeshift/{Q_USER}/{Q_PASS}/60/x/5.ts HTTP/1.1",
            f"///series/{Q_USER}/{Q_PASS}/1.mkv",
            f"/live//{Q_USER}//{Q_PASS}/abc",
        ):
            with self.subTest(text=text):
                self._assert_masked(text)

    def test_a_double_slash_path_keeps_its_query_masked(self):
        out = redact_text(f"GET //movie/{Q_USER}/{Q_PASS}/1.mp4?password={Q_PASS} HTTP/1.1")
        self.assertNotIn(Q_PASS, out)
        self.assertNotIn(Q_USER, out)

    def test_percent_encoded_prefix_and_slashes_in_a_request_line(self):
        for text in (
            f"/%6dovie/{Q_USER}/{Q_PASS}/x",
            f"/movie%2F{Q_USER}%2F{Q_PASS}%2F1.mp4",
            f'"GET /%6dovie/{Q_USER}/{Q_PASS}/x HTTP/1.1"',
        ):
            with self.subTest(text=text):
                self._assert_masked(text)

    def test_trailing_punctuation_and_a_key_prefix(self):
        for text in (f"at /{Q_USER}/{Q_PASS}/1.ts.", f"path=/{Q_USER}/{Q_PASS}/1.ts", f"failed: /{Q_USER}/{Q_PASS}/1.ts:"):
            with self.subTest(text=text):
                self._assert_masked(text)

    def test_placeholders_in_credential_positions_still_render(self):
        record = self._record("/movie/%s/%s/1.mp4", Q_USER, Q_PASS)
        out = RequestLogCredentialFilter().filter(record)
        self.assertEqual(out.getMessage(), "/movie/***/***/1.mp4")

    def test_non_string_arguments_are_rendered_then_masked(self):
        class Echo:
            def __str__(self):
                return f"/movie/{Q_USER}/{Q_PASS}/1.mp4"

        for arg in (ValueError(f"bad /movie/{Q_USER}/{Q_PASS}/1.mp4"), Echo()):
            with self.subTest(arg=type(arg).__name__):
                out = RequestLogCredentialFilter().filter(self._record("%s", arg))
                self.assertNotIn(Q_USER, out.getMessage())
                self.assertNotIn(Q_PASS, out.getMessage())

    def test_a_request_whose_query_cannot_be_parsed_still_logs_its_text(self):
        request = RequestFactory().get(f"/movie/{Q_USER}/{Q_PASS}/1.mp4")
        record = self._record("Bad request: %s", request.path, request=request)
        with mock.patch.object(WSGIRequest, "GET", new_callable=mock.PropertyMock, side_effect=TooManyFieldsSent):
            out = RequestLogCredentialFilter().filter(record)
        self.assertEqual(out.getMessage(), "Bad request: /movie/***/***/1.mp4")

    def test_stack_info_is_masked(self):
        record = self._record("x", stack_info=f"Stack at /movie/{Q_USER}/{Q_PASS}/1.mp4")
        out = RequestLogCredentialFilter().filter(record)
        self.assertNotIn(Q_USER, out.stack_info)
        self.assertEqual(record.stack_info, f"Stack at /movie/{Q_USER}/{Q_PASS}/1.mp4")

    def test_a_query_shaped_fragment_is_masked(self):
        for text in (
            f"GET /player_api.php#password={Q_PASS} HTTP/1.1",
            f"GET /x?a=1#username={Q_USER}&password={Q_PASS} HTTP/1.1",
            f"GET //x#password={Q_PASS} HTTP/1.1",
        ):
            with self.subTest(text=text):
                out = redact_text(text)
                self.assertNotIn(Q_PASS, out)
                self.assertNotIn(Q_USER, out)
        self.assertEqual(redact_text("GET /x?a=1#section HTTP/1.1"), "GET /x?a=1#section HTTP/1.1")

    def test_a_bare_root_path_after_a_quoted_key_or_inside_a_url_value(self):
        for text in (
            f'{{"path":"/{Q_USER}/{Q_PASS}/1.ts"}}',
            f'path="/{Q_USER}/{Q_PASS}/1.ts"',
            f"url=http://h/{Q_USER}/{Q_PASS}/1.ts",
        ):
            with self.subTest(text=text):
                self._assert_masked(text)

    def test_cost_grows_linearly_on_hostile_input(self):
        # One shape per code path, so a quadratic edit to any of them reddens
        # at least one shape: the whole-path mask (1, 2), its decode retry (4),
        # redact_url on a token with no leading slash (3, 5), the per-token
        # loop (6), the key prefix (7) and the query/fragment split (8).
        shapes = (
            lambda n: "/" * n,
            lambda n: "/movie/" + "a/" * (n // 2),
            lambda n: "%" * n,
            lambda n: "/" + "%2F" * (n // 3),
            lambda n: "&password=x" * (n // 11),
            lambda n: "a " * (n // 2),
            lambda n: "k" * n + "=/",
            lambda n: "/?" + "#=" * (n // 2),
        )
        # The small run is grown until it takes at least this long, so it is
        # well clear of timer noise and the ratio below means something for
        # every shape (a fixed 20,000 characters ran in under 0.1 ms for some).
        floor_seconds = 0.005
        # The loop stops at the first doubling at or above this, so the
        # small run can reach 5,120,000 characters and the large one
        # 51,200,000 (about 50 MB, briefly).
        max_small = 4_000_000

        def best_of(text, runs=3):
            best = float("inf")
            for _ in range(runs):
                started = time.perf_counter()
                redact_text(text)
                best = min(best, time.perf_counter() - started)
            return best

        for index, shape in enumerate(shapes):
            with self.subTest(shape=index):
                n = 20_000
                while best_of(shape(n), runs=1) < floor_seconds and n < max_small:
                    n *= 2
                small = best_of(shape(n))
                large = best_of(shape(n * 10))
                # 10x the input: linear is ~10x, quadratic ~100x. Allow 40x.
                self.assertLess(large, small * 40, f"n={n}: {small:.4f}s -> {large:.4f}s")


# Review round 3: one literal expectation per input, covering every input the
# three review rounds and the PR body quote. Each expected value is what the
# reviews said is correct, written out, never computed by the code under test.
# Rows marked "over-masked" are the bare-root rule's accepted false positives.
REDACT_TEXT_TABLE = (
    # path forms
    (f"/movie/{Q_USER}/{Q_PASS}/1.mp4", "/movie/***/***/1.mp4"),
    (f"/live/{Q_USER}/{Q_PASS}/1.ts", "/live/***/***/1.ts"),
    (f"/series/{Q_USER}/{Q_PASS}/1.mkv", "/series/***/***/1.mkv"),
    (f"/timeshift/{Q_USER}/{Q_PASS}/60/2026-01-01:10-00/5.ts", "/timeshift/***/***/60/2026-01-01:10-00/5.ts"),
    (f"/{Q_USER}/{Q_PASS}/1.ts", "/***/***/1.ts"),
    (f"/MOVIE/{Q_USER}/{Q_PASS}/1.mp4", "/MOVIE/***/***/1.mp4"),
    (f"/live//{Q_USER}//{Q_PASS}/abc", "/live//***//***/abc"),
    (f"/movie/{Q_USER}/{Q_PASS}", "/movie/***/***"),
    # double-slash forms
    (f"//timeshift/{Q_USER}/{Q_PASS}/60/2026-01-01:10-00/5.ts", "//timeshift/***/***/60/2026-01-01:10-00/5.ts"),
    (f"//live/{Q_USER}/{Q_PASS}/abc", "//live/***/***/abc"),
    (f"GET //timeshift/{Q_USER}/{Q_PASS}/60/x/5.ts HTTP/1.1", "GET //timeshift/***/***/60/x/5.ts HTTP/1.1"),
    (f"//movie/{Q_USER}/{Q_PASS}/1.mp4", "//movie/***/***/1.mp4"),
    (f"///series/{Q_USER}/{Q_PASS}/1.mkv", "///series/***/***/1.mkv"),
    (f"////live//{Q_USER}//{Q_PASS}//abc", "////live//***//***//abc"),
    (f"//{Q_USER}/{Q_PASS}/1.ts", "//***/***/1.ts"),
    (f"GET //movie/{Q_USER}/{Q_PASS}/1.mp4?password={Q_PASS} HTTP/1.1",
     "GET //movie/***/***/1.mp4?password=*** HTTP/1.1"),
    (f"GET //x#password={Q_PASS} HTTP/1.1", "GET //x#password=*** HTTP/1.1"),
    (f"path=//timeshift/{Q_USER}/{Q_PASS}/60/x/5.ts", "path=//timeshift/***/***/60/x/5.ts"),
    (f'"path"://timeshift/{Q_USER}/{Q_PASS}/60/x/5.ts', '"path"://timeshift/***/***/60/x/5.ts'),
    # percent-encoded forms (the server decodes once before routing)
    (f"/%6dovie/{Q_USER}/{Q_PASS}/x", "/movie/***/***/x"),
    (f"/%4DOVIE/{Q_USER}/{Q_PASS}/x", "/MOVIE/***/***/x"),
    (f"/movie%2F{Q_USER}%2F{Q_PASS}%2F1.mp4", "/movie/***/***/1.mp4"),
    (f"/movie%2f{Q_USER}%2f{Q_PASS}%2f1.mp4", "/movie/***/***/1.mp4"),
    (f'"GET /%6dovie/{Q_USER}/{Q_PASS}/x HTTP/1.1"', '"GET /movie/***/***/x HTTP/1.1"'),
    (f"/movie/a/b/%6cive/{Q_USER}/{Q_PASS}/1", "/movie/***/***/live/***/***/1"),
    # double-encoded: not a route (the server decodes once), left alone
    (f"/movie%252F{Q_USER}%252F{Q_PASS}%252F1", f"/movie%252F{Q_USER}%252F{Q_PASS}%252F1"),
    ("/a%20b/c", "/a%20b/c"),
    ("/a%2Fb", "/a%2Fb"),
    ("/x/%41", "/x/%41"),
    ("/a%zz/b%", "/a%zz/b%"),
    # request lines
    (f"GET /movie/{Q_USER}/{Q_PASS}/1.mp4?username={Q_USER}&password={Q_PASS} HTTP/1.1",
     "GET /movie/***/***/1.mp4?username=***&password=*** HTTP/1.1"),
    (f'"GET /movie/{Q_USER}/{Q_PASS}/1.mp4 HTTP/1.1" 401 17', '"GET /movie/***/***/1.mp4 HTTP/1.1" 401 17'),
    (f"HTTP GET /live/{Q_USER}/{Q_PASS}/1.ts 401", "HTTP GET /live/***/***/1.ts 401"),
    # query forms
    (f"/player_api.php?username={Q_USER}&password={Q_PASS}", "/player_api.php?username=***&password=***"),
    (f"/get.php?username={Q_USER}&password={Q_PASS}&type=m3u_plus",
     "/get.php?username=***&password=***&type=m3u_plus"),
    (f"/x?PASSWORD={Q_PASS}", "/x?PASSWORD=***"),
    (f"/x?pass%77ord={Q_PASS}", "/x?pass%77ord=***"),
    (f"/x?password={Q_PASS}&a=1&password={Q_PASS}", "/x?password=***&a=1&password=***"),
    # fragments
    (f"GET /player_api.php#password={Q_PASS} HTTP/1.1", "GET /player_api.php#password=*** HTTP/1.1"),
    (f"GET /x?a=1#username={Q_USER}&password={Q_PASS} HTTP/1.1",
     "GET /x?a=1#username=***&password=*** HTTP/1.1"),
    ("GET /x?a=1#section HTTP/1.1", "GET /x?a=1#section HTTP/1.1"),
    # quoted, bracketed and keyed forms
    (f'{{"path":"/{Q_USER}/{Q_PASS}/1.ts"}}', '{"path":"/***/***/1.ts"}'),
    (f'path="/{Q_USER}/{Q_PASS}/1.ts"', 'path="/***/***/1.ts"'),
    (f"path='/{Q_USER}/{Q_PASS}/1.ts'", "path='/***/***/1.ts'"),
    (f"path=/{Q_USER}/{Q_PASS}/1.ts", "path=/***/***/1.ts"),
    (f"{{'path': '/{Q_USER}/{Q_PASS}/1.ts'}}", "{'path': '/***/***/1.ts'}"),
    (f"url=http://h/{Q_USER}/{Q_PASS}/1.ts", "url=http://h/***/***/1.ts"),
    (f'"url":"http://h/{Q_USER}/{Q_PASS}/1.ts"', '"url":"http://h/***/***/1.ts"'),
    (f"url:http://h/{Q_USER}/{Q_PASS}/1.ts", "url:http://h/***/***/1.ts"),
    (f"url=http://h/movie/{Q_USER}/{Q_PASS}/1", "url=http://h/movie/***/***/1"),
    (f'url="http://{Q_USER}:{Q_PASS}@h/x"', 'url="http://***@h/x"'),
    (f"at /{Q_USER}/{Q_PASS}/1.ts.", "at /***/***/1.ts."),
    (f"failed: /{Q_USER}/{Q_PASS}/1.ts:", "failed: /***/***/1.ts:"),
    (f"error:/{Q_USER}/{Q_PASS}/1.ts", "error:/***/***/1.ts"),
    (f"'/movie/{Q_USER}/{Q_PASS}/1.mp4'", "'/movie/***/***/1.mp4'"),
    (f"(/movie/{Q_USER}/{Q_PASS}/1.mp4)", "(/movie/***/***/1.mp4)"),
    (f"<http://h/{Q_USER}/{Q_PASS}/1.ts>", "<http://h/***/***/1.ts>"),
    # absolute URLs, with and without userinfo and ports (review round 3, E)
    (f"http://h/{Q_USER}/{Q_PASS}/1.ts", "http://h/***/***/1.ts"),
    (f"https://h:8080/{Q_USER}/{Q_PASS}/1.ts", "https://h:8080/***/***/1.ts"),
    (f"GET http://h/{Q_USER}/{Q_PASS}/1.ts HTTP/1.1", "GET http://h/***/***/1.ts HTTP/1.1"),
    (f"http://{Q_USER}:{Q_PASS}@h/x", "http://***@h/x"),
    (f"https://{Q_USER}:{Q_PASS}@h:8080/live/{Q_USER}/{Q_PASS}/1.ts", "https://***@h:8080/live/***/***/1.ts"),
    (f"http://h/movie/{Q_USER}/{Q_PASS}/1.mp4", "http://h/movie/***/***/1.mp4"),
    (f"http://h/player_api.php?username={Q_USER}&password={Q_PASS}",
     "http://h/player_api.php?username=***&password=***"),
    (f"http://h/x#password={Q_PASS}", "http://h/x#password=***"),
    (f'"http://h/{Q_USER}/{Q_PASS}/1.ts"', '"http://h/***/***/1.ts"'),
    (f"http://h/{Q_USER}/{Q_PASS}/1.ts.", "http://h/***/***/1.ts."),
    (f"RuntimeError: fetch http://h/{Q_USER}/{Q_PASS}/1.ts failed",
     "RuntimeError: fetch http://h/***/***/1.ts failed"),
    # non-HTTP schemes
    (f"rtsp://h/{Q_USER}/{Q_PASS}/1", "rtsp://h/***/***/1"),
    (f"ftp://{Q_USER}:{Q_PASS}@h/", "ftp://***@h/"),
    (f"rtmp://h/live/{Q_USER}/{Q_PASS}/1", "rtmp://h/live/***/***/1"),
    # review round 4: an unquoted word, "://", then an Xtream prefix read as
    # a host (masked at 1f7eb88e), and an absolute URL with an encoded path
    (f"path://timeshift/{Q_USER}/{Q_PASS}/60/x/5.ts", "path://timeshift/***/***/60/x/5.ts"),
    (f"error://live/{Q_USER}/{Q_PASS}/abc", "error://live/***/***/abc"),
    (f"Forbidden://live/{Q_USER}/{Q_PASS}/abc", "Forbidden://live/***/***/abc"),
    (f"uri://movie/{Q_USER}/{Q_PASS}/1.mp4", "uri://movie/***/***/1.mp4"),
    (f"http://h/%6dovie/{Q_USER}/{Q_PASS}/1.mp4", "http://h/movie/***/***/1.mp4"),
    (f"http://h/movie%2F{Q_USER}%2F{Q_PASS}%2F1.mp4", "http://h/movie/***/***/1.mp4"),
    # the same with the host percent-encoded (it decodes to a prefix or holds
    # an encoded "/", so it cannot be a host), and with an empty host
    (f"word://movie%2F{Q_USER}%2F{Q_PASS}%2F1.mp4", "word://movie/***/***/1.mp4"),
    (f"word://%2F{Q_USER}%2F{Q_PASS}%2F1.ts", "word:///***/***/1.ts"),
    (f"word:///%6dovie/{Q_USER}/{Q_PASS}/1.mp4", "word:///movie/***/***/1.mp4"),
    # given up (round 4, class c): spelled exactly like http://h/a/5, a URL
    # whose host is the first segment; masked at 1f7eb88e only
    (f"path://{Q_USER}/{Q_PASS}/1.ts", f"path://{Q_USER}/{Q_PASS}/1.ts"),
    # given up (round 4): a host glued to the username; the path is two
    # segments after a real-looking host, as in http://h/a/5
    (f"http://h{Q_USER}/{Q_PASS}/1.ts", f"http://h{Q_USER}/{Q_PASS}/1.ts"),
    # near-misses that stay unchanged
    ("http://h/a/b", "http://h/a/b"),
    ("http://h/a/5", "http://h/a/5"),
    ("url=http://h/a/5", "url=http://h/a/5"),
    ("https://h:8080/a/5", "https://h:8080/a/5"),
    ("http://h", "http://h"),
    ("status: ok", "status: ok"),
    ("time: 12:30:45", "time: 12:30:45"),
    ("key: /api/channels/", "key: /api/channels/"),
    ("key: a/b/c", "key: a/b/c"),
    ('"detail": "/static/x"', '"detail": "/static/x"'),
    ("/api/accounts/users/5/", "/api/accounts/users/5/"),
    ("Unauthorized: /player_api.php", "Unauthorized: /player_api.php"),
    ("the quick brown fox jumps over the lazy dog", "the quick brown fox jumps over the lazy dog"),
    ("ratio 3:1 at 10:00", "ratio 3:1 at 10:00"),
    # over-masked: three segments ending in a stream id look like the bare
    # root route; masked at every earlier head too (stated in the PR body)
    ("/static/js/1.js", "/***/***/1.js"),
    ("/output/m3u/3", "/***/***/3"),
    ('"detail":"/static/js/1.js"', '"detail":"/***/***/1.js"'),
    ("status: /api/channels/5", "status: /***/***/5"),
    ("C:/x/y/1", "C:/***/***/1"),
    # over-masked (round 4): a URL whose host is an Xtream prefix is also
    # read as a path
    ("http://live/a/b", "http://live/***/***"),
    ("http://h/a%2Fb/5", "http://h/***/***/5"),
    # review round 5, B: the userinfo stays masked when the host is read as
    # a path
    (f"http://{Q_USER}:{Q_PASS}@h%2Flive/a/b/c", "http://***@h/live/***/***/c"),
    (f"rtsp://{Q_USER}:{Q_PASS}@cam%2Flive/ch/main/av", "rtsp://***@cam/live/***/***/av"),
    (f"http://{Q_USER}:{Q_PASS}@h%2Fmovie%2Fa%2Fb", "http://***@h/movie/***/***"),
    (f"http://{Q_USER}:{Q_PASS}@%2Flive/a/b", "http://***@/live/***/***"),
    # review round 5, C: a decoded "?" or "#" stays path text (put back
    # encoded since round 6); the real query and fragment are masked as they are
    (f"http://h/%6dovie/a/b/c%3Fd?token={Q_PASS}", "http://h/movie/***/***/c%3Fd?token=***"),
    (f"http://h/%6dovie/a/b/c%3Fd?username={Q_USER}&password={Q_PASS}",
     "http://h/movie/***/***/c%3Fd?username=***&password=***"),
    (f"http://h/%6dovie/a/b/c%23d?password={Q_PASS}", "http://h/movie/***/***/c%23d?password=***"),
    (f"http://h/%6dovie/a/b/c%23d#token={Q_PASS}", "http://h/movie/***/***/c%23d#token=***"),
    (f"http://h/%6cive/a/b/1%3F.ts?password={Q_PASS}", "http://h/live/***/***/1%3F.ts?password=***"),
    # review round 6, D: a whole path with a query keeps its query masks when
    # the path only matches decoded
    (f"/%6cive/a/b/c%3Fd?password={Q_PASS}", "/live/***/***/c%3Fd?password=***"),
    (f"/%6dovie/a/b/c%23d?username={Q_USER}&password={Q_PASS}",
     "/movie/***/***/c%23d?username=***&password=***"),
    (f"/get.php%3Fx/%6cive/a/b/c?username={Q_USER}&password={Q_PASS}",
     "/get.php%3Fx/live/***/***/c?username=***&password=***"),
    # review round 6, E: userinfo in a token that starts "//"
    (f"//{Q_USER}:{Q_PASS}@h/x", "//***@h/x"),
    (f'"//{Q_USER}:{Q_PASS}@cdn.example/app.js"', '"//***@cdn.example/app.js"'),
    (f"//{Q_USER}:{Q_PASS}@h/live/a/b/1.ts", "//***@h/live/***/***/1.ts"),
    (f"url=//{Q_USER}:{Q_PASS}@h/a/b", "url=//***@h/a/b"),
    # review round 6, the accepted-ambiguity class: //<host>/<user>/<pass>/<id>
    (f"//h/{Q_USER}/{Q_PASS}/1.ts", "//h/***/***/1.ts"),
    # review round 6, F(1): a final segment that is only trailing punctuation
    (f"http://h/live/{Q_USER}/.", "http://h/live/***/***"),
    (f"http://h/live/{Q_USER}/...", "http://h/live/***/***"),
)


class RedactTextTableTests(SimpleTestCase):
    """Every row of REDACT_TEXT_TABLE, compared exactly."""

    def test_the_table_is_large_enough_to_mean_something(self):
        self.assertGreaterEqual(len(REDACT_TEXT_TABLE), 60)
        self.assertEqual(len({text for text, _ in REDACT_TEXT_TABLE}), len(REDACT_TEXT_TABLE))

    def test_every_row(self):
        for text, expected in REDACT_TEXT_TABLE:
            with self.subTest(text=text):
                self.assertEqual(redact_text(text), expected)

    def test_an_absolute_url_is_never_split_at_its_scheme(self):
        # Review round 3, finding E: the key prefix took "http:" as a key and
        # masked the URL as a path, so the host became a segment.
        for text, expected in (
            (f"http://h/{Q_USER}/{Q_PASS}/1.ts", "http://h/***/***/1.ts"),
            (f"GET http://h/{Q_USER}/{Q_PASS}/1.ts HTTP/1.1", "GET http://h/***/***/1.ts HTTP/1.1"),
            (f"http://{Q_USER}:{Q_PASS}@h/x", "http://***@h/x"),
            ("http://h/a/5", "http://h/a/5"),
        ):
            with self.subTest(text=text):
                out = redact_text(text)
                self.assertNotIn(Q_USER, out, f"{Q_USER} survived in {out!r}")
                self.assertNotIn(Q_PASS, out, f"{Q_PASS} survived in {out!r}")
                self.assertEqual(out, expected)


_GRID_USERINFOS = (
    ("", ()),
    ("s-ui-user:s-ui-pass@", ("s-ui-user", "s-ui-pass")),
    ("s-ui-user%3Ax:s-ui-pass%40y@", ("s-ui-user", "s-ui-pass")),
)
_GRID_HOSTS = (
    "h", "h.example:8080", "[::1]", "live", "Movie", "timeshift", "%6cive",
    "h%2Flive", "cam%2Fmovie", "%2Flive", "h%2Fx", "",
)
_GRID_PATHS = (
    ("/live/s-p-user/s-p-pass/1.ts", ("s-p-user", "s-p-pass")),
    ("/%6cive/s-p-user/s-p-pass/1.ts", ("s-p-user", "s-p-pass")),
    ("/live%2Fs-p-user%2Fs-p-pass%2F1.ts", ("s-p-user", "s-p-pass")),
    ("/s-p-user/s-p-pass/1.ts", ("s-p-user", "s-p-pass")),
    ("/s-p-user/s-p-pass/%31.ts", ("s-p-user", "s-p-pass")),
    ("/timeshift/s-p-user/s-p-pass/60/x/5.ts", ("s-p-user", "s-p-pass")),
    ("/%6dovie/a/b/c%3Fd", ()),
    ("/%6dovie/a/b/c%23d", ()),
    ("/%6cive/a/b/1%3F.ts", ()),
    ("/%6dovie/a/b/c%40d", ()),
    ("/%6dovie/a/b/c%2F%2Fd", ()),
    ("/get.php%3Fx/%6cive/a/b/c", ()),
    ("/a/b/c", ()),
    ("/a/b/5", ()),
    ("", ()),
)
_GRID_TAILS = (
    ("", ()),
    ("?token=s-q-token", ("s-q-token",)),
    ("?username=s-q-user&password=s-q-pass", ("s-q-user", "s-q-pass")),
    ("?password=s-q-pass#token=s-f-token", ("s-q-pass", "s-f-token")),
    ("#token=s-f-token", ("s-f-token",)),
    ("?a=1", ()),
)
# How a token reaches redact_text: alone, in a request line, after a key, in
# message text. Each is applied to the scheme-less forms.
_GRID_WRAPPERS = (
    ("bare", "{}"),
    ("request line", "GET {} HTTP/1.1"),
    ("key=", "path={}"),
    ("key: ", "path: {}"),
    ("quoted key", '{{"path":"{}"}}'),
    ("message", "Not Found: {}"),
)


def _token_grid():
    """Tokens built from components, each credential a distinct sentinel.

    Yields (text, token, sentinels, form): the text handed to redact_text,
    the token in it that redact_url is asked about, every sentinel the token
    carries (so a survivor can be named), and the token's form. The forms are
    every one redact_text reads differently: ``scheme://...`` URLs, scheme-less
    ``//host/...`` tokens with and without userinfo, and bare ``/path...``
    tokens. The last two are also wrapped in each of _GRID_WRAPPERS. Deterministic.
    """
    for scheme in ("http", "https", "rtsp", "word"):
        for userinfo, ui in _GRID_USERINFOS:
            for host in _GRID_HOSTS:
                for path, ps in _GRID_PATHS:
                    for tail, ts in _GRID_TAILS:
                        token = f"{scheme}://{userinfo}{host}{path}{tail}"
                        yield token, token, ui + ps + ts, "scheme://"
    for userinfo, ui in _GRID_USERINFOS:
        for host in _GRID_HOSTS:
            if not host:
                continue  # "///..." is a bare path, below
            for path, ps in _GRID_PATHS:
                for tail, ts in _GRID_TAILS:
                    token = f"//{userinfo}{host}{path}{tail}"
                    for name, wrapper in _GRID_WRAPPERS:
                        yield wrapper.format(token), token, ui + ps + ts, f"//host, {name}"
    for path, ps in _GRID_PATHS:
        for lead in ("", "/"):
            if not path:
                continue
            for tail, ts in _GRID_TAILS:
                token = f"{lead}{path}{tail}"
                for name, wrapper in _GRID_WRAPPERS:
                    yield wrapper.format(token), token, ps + ts, f"/path, {name}"


class NeverLessThanRedactUrlTests(SimpleTestCase):
    """redact_text never leaves a credential that redact_url masks in the same token.

    The oracle is ``redact_url`` from the project package, applied to the
    token alone, which this PR does not change. The grid covers every form
    redact_text reads differently (``scheme://`` URLs, scheme-less ``//host``
    tokens, bare ``/path`` tokens with a query or fragment), each also inside a
    request line, after a key and in message text. Every extra reading in
    this module may only add masks to redact_url's, never trade one away.
    """

    QUOTED = (
        # review round 5, B and C, verbatim
        f"http://{Q_USER}:{Q_PASS}@h%2Flive/a/b/c",
        f"rtsp://{Q_USER}:{Q_PASS}@cam%2Flive/ch/main/av",
        f"http://{Q_USER}:{Q_PASS}@h%2Fmovie%2Fa%2Fb",
        f"http://{Q_USER}:{Q_PASS}@%2Flive/a/b",
        f"http://h/%6dovie/a/b/c%3Fd?token={Q_PASS}",
        f"http://h/%6dovie/a/b/c%3Fd?username={Q_USER}&password={Q_PASS}",
        f"http://h/%6dovie/a/b/c%23d?password={Q_PASS}",
        f"http://h/%6dovie/a/b/c%23d#token={Q_PASS}",
        f"http://h/%6cive/a/b/1%3F.ts?password={Q_PASS}",
        # review round 6, D and E, verbatim
        f"/%6cive/a/b/c%3Fd?password={Q_PASS}",
        f"/%6dovie/a/b/c%23d?username={Q_USER}&password={Q_PASS}",
        f"/get.php%3Fx/%6cive/a/b/c?username={Q_USER}&password={Q_PASS}",
        f"//{Q_USER}:{Q_PASS}@h/x",
        f"//{Q_USER}:{Q_PASS}@cdn.example/app.js",
        f"//{Q_USER}:{Q_PASS}@h/live/a/b/1.ts",
        f"url=//{Q_USER}:{Q_PASS}@h/a/b",
    )

    # The oracle must keep masking, or the invariant would hold vacuously:
    # the share of the grid's sentinels redact_url itself masks (0.870, 85,532
    # of 98,348, when this was written).
    MIN_ORACLE_MASKED = 0.80

    # The one class where the two readings genuinely differ: a scheme-less
    # "//<host>/<user>/<pass>/<id>" token, which redact_url reads as a host and
    # a bare-root path, and the server (round 1) as a path whose first segment
    # is not a host. It has no exception: both readings' masks are kept, so
    # its count of survivors is asserted to be zero, by name, before the rest.
    AMBIGUOUS_HOST_PATH_SURVIVORS = 0

    def _cases(self):
        cases = list(_token_grid())
        for text in self.QUOTED:
            token = text.split("=", 1)[1] if text.startswith("url=") else text
            cases.append((text, token, (Q_USER, Q_PASS), "quoted"))
        return cases

    def test_no_credential_redact_url_masks_survives(self):
        cases = self._cases()
        forms = {form.split(",")[0] for _, _, _, form in cases}
        self.assertEqual(forms, {"scheme://", "//host", "/path", "quoted"})
        self.assertGreater(len(cases), 20000)
        survivors = []
        sentinels_total = sentinels_masked = 0
        for text, token, sentinels, form in cases:
            baseline = redact_url(token)
            out = redact_text(text)
            for sentinel in sentinels:
                sentinels_total += 1
                if sentinel not in baseline:
                    sentinels_masked += 1
                    if sentinel in out:
                        survivors.append(f"[{form}] {sentinel} in {out!r} (redact_url: {baseline!r})")
        self.assertGreaterEqual(
            sentinels_masked / sentinels_total, self.MIN_ORACLE_MASKED,
            f"the oracle masked only {sentinels_masked} of {sentinels_total} sentinels",
        )
        ambiguous = [
            line for line in survivors
            if line.startswith("[//host") and line[line.index("] ") + 2:].startswith("s-p-")
        ]
        self.assertEqual(
            len(ambiguous), self.AMBIGUOUS_HOST_PATH_SURVIVORS,
            f"//<host>/<user>/<pass>/<id> class: {ambiguous[:3]}",
        )
        by_class = {}
        for line in survivors:
            form = line[1:line.index("]")].split(",")[0]
            kind = line[line.index("] ") + 2:].split(" ")[0]
            by_class.setdefault(f"{form} {kind}", []).append(line)
        self.assertFalse(
            survivors,
            f"{len(survivors)} credential(s) of {len(cases)} inputs survive that redact_url masks; by class: "
            + "; ".join(f"{key}: {len(lines)}, e.g. {lines[0]}" for key, lines in sorted(by_class.items())),
        )


class PlacementTests(_SinkAssertions, SimpleTestCase):
    """The filter sits on HANDLERS, so a child logger and the OTel bridge cannot miss it.

    A filter on a logger applies only to records logged on that exact logger;
    django.security.DisallowedHost (and every other per-exception
    django.security.<Name>) is a descendant, and a record propagating up the
    tree never passes a parent logger's filters. Every handler such a record
    reaches carries the filter instead (RealConfigurationTests checks that
    structurally).
    """

    def setUp(self):
        self.sinks = _ProductionSinks(self)

    def test_a_child_logger_record_reaching_the_otel_bridge(self):
        request = _xc_request("/player_api.php", username=USER, password=PASSWORD)
        logging.getLogger("django.security.DisallowedHost").error(
            "Invalid host for %s", f"/live/{USER}/{PASSWORD}/1.ts", extra={"request": request}
        )
        self.assertNoCredential(self.sinks, USER, PASSWORD)
        self.assertIn(
            "django.security.DisallowedHost Invalid host for /live/***/***/1.ts",
            self.sinks.console.getvalue(),
        )
        [bridged] = [r for r in self.sinks.otel.records if r.name == "django.security.DisallowedHost"]
        self.assertEqual(bridged.getMessage(), "Invalid host for /live/***/***/1.ts")
        self.assertNotIn("request", vars(bridged))

    def test_the_configured_console_filter_drops_the_request(self):
        request = _xc_request("/player_api.php", username=USER, password=PASSWORD)
        self.assertIn(PASSWORD, repr(request))
        record = logging.LogRecord(
            "django.request", logging.WARNING, __file__, 1, "%s: %s",
            ("Unauthorized", "/player_api.php"), None,
        )
        record.request = request
        out = _handler("", "console").filter(record)
        self.assertNotIn("request", vars(out))
        self.assertNotIn(PASSWORD, repr(vars(out)))
        self.assertIs(record.request, request)


class CompositionTests(SimpleTestCase):
    """What with_request_log_redaction adds, pinned exactly.

    tests/test_observability_logs.py pins settings.LOGGING as this function
    applied to the D8 configuration; this pins the function itself, so a
    change to either side reddens one of the two.
    """

    BASE = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"verbose": {"format": "{message}", "style": "{"}},
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "verbose", "level": 5},
            "otel": {"class": OTEL_BRIDGE, "level": 5},
        },
        "loggers": {"apps": {"handlers": ["console", "otel"], "level": 20, "propagate": False}},
        "root": {"handlers": ["console", "otel"], "level": 20},
    }

    EXPECTED = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_log_credentials": {"()": "core.request_log_redaction.RequestLogCredentialFilter"},
            "require_debug_true": {"()": "django.utils.log.RequireDebugTrue"},
            "require_debug_false": {"()": "django.utils.log.RequireDebugFalse"},
        },
        "formatters": {
            "verbose": {"format": "{message}", "style": "{"},
            "django.server": {
                "()": "django.utils.log.ServerFormatter",
                "format": "[{server_time}] {message}",
                "style": "{",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler", "formatter": "verbose", "level": 5,
                "filters": ["request_log_credentials"],
            },
            "otel": {
                "class": OTEL_BRIDGE, "level": 5,
                "filters": ["request_log_credentials"],
            },
            "django.console": {
                "class": "logging.StreamHandler", "level": "INFO",
                "filters": ["require_debug_true", "request_log_credentials"],
            },
            "django.mail_admins": {
                "class": "django.utils.log.AdminEmailHandler", "level": "ERROR",
                "filters": ["require_debug_false", "request_log_credentials"],
            },
            "django.server": {
                "class": "logging.StreamHandler", "formatter": "django.server", "level": "INFO",
                "filters": ["request_log_credentials"],
            },
        },
        "loggers": {
            "apps": {"handlers": ["console", "otel"], "level": 20, "propagate": False},
            "django": {"handlers": ["django.console", "django.mail_admins"], "level": "INFO"},
            "django.server": {"handlers": ["django.server"], "level": "INFO", "propagate": False},
        },
        "root": {"handlers": ["console", "otel"], "level": 20},
    }

    def test_exactly_what_it_adds(self):
        self.assertEqual(with_request_log_redaction(self.BASE), self.EXPECTED)

    def test_the_input_is_not_mutated(self):
        base = copy.deepcopy(self.BASE)
        with_request_log_redaction(base)
        self.assertEqual(base, self.BASE)

    def test_applying_it_twice_adds_nothing_more(self):
        once = with_request_log_redaction(self.BASE)
        self.assertEqual(with_request_log_redaction(once), once)
