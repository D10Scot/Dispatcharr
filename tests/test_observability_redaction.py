"""Observability spec D9 / R7: redaction at every exporter boundary.

Two standards are tested separately, as the ruling R-Q17 splits them:

* allow by construction (span name/attributes/status/events, metric
  attributes, structured log fields): LEAK assertions say the sentinel is in no
  exported byte, POLICY assertions say what must be absent or present;
* log BODIES (best effort, no stronger than stdout): policy tests only. A bare
  sentinel in a body is NOT asserted absent, because no pattern class targets
  it and the spec says so.

Every case first asserts the export is non-empty and holds the expected item,
then checks the raw (un-redacted) exporter saw the carrier where one exists, so
a call that never carried the sentinel cannot make a test pass.
"""
import logging
import os
import re
import time
import uuid
from unittest import mock, skipUnless

import psycopg
import redis
import requests
from celery import Celery
from django.conf import settings
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import path, resolve
from hypothesis import find, given, settings as hyp_settings, strategies as st
from opentelemetry import trace
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.trace import Link, SpanKind

from dispatcharr.observability import logs
from dispatcharr.observability import redaction
from dispatcharr.observability.metrics import M11_NAME, SCOPE_NAME
from tests.log_scrub_rig import unscrubbed_logging
from tests.otel_rig import SENTINEL, SENTINEL_UUID, Failures, Rig, reset_semconv

HLS_TOKEN = "v1." + "A" * 22 + "." + "B" * 43


def _boom(request):
    raise ValueError(SENTINEL)


urlpatterns = [path("boom/", _boom)]


class SpanBoundaryUnitTests(TestCase):
    """The boundary on hand-built spans: the name rule's own unit cases."""

    def setUp(self):
        self.rig = Rig()
        self.addCleanup(self.rig.teardown)
        self.tracer = self.rig.tracer_provider.get_tracer("unit.scope")

    def test_a_span_named_with_the_sentinel_is_renamed_to_its_scope(self):
        with self.tracer.start_as_current_span(SENTINEL):
            pass
        exported = self.rig.exported_spans()
        self.assertEqual([s.name for s in exported], ["unit.scope"])
        self.assertIn(SENTINEL, self.rig.dump(self.rig.raw_spans()))
        self.assertNotIn(SENTINEL, self.rig.dump(exported))

    def test_permitted_names_are_kept(self):
        names = ["GET", "run/apps.m3u.tasks.refresh", "apply_async/x.y", "SELECT", "SET", "XADD GROUP"]
        for name in names:
            with self.tracer.start_as_current_span(name):
                pass
        self.assertEqual([s.name for s in self.rig.exported_spans()], names)

    def test_method_and_route_name_requires_the_validated_route_attribute(self):
        attrs = {"http.request.method": "GET", "http.route": "^api/"}
        with self.tracer.start_as_current_span("GET ^api/", attributes=attrs):
            pass
        with self.tracer.start_as_current_span("GET ^other/", attributes=attrs):
            pass
        self.assertEqual([s.name for s in self.rig.exported_spans()], ["GET ^api/", "unit.scope"])

    def test_attribute_values_failing_their_rule_are_dropped_not_rewritten(self):
        attrs = {
            "http.route": SENTINEL + " has spaces",
            "http.request.method": "GET",
            "http.response.status_code": True,
            "server.address": f"{SENTINEL}/x",
            "url.full": f"http://u:{SENTINEL}@h/p",
            "celery.task_name": SENTINEL,
            "messaging.message.id": SENTINEL,
        }
        with self.tracer.start_as_current_span("GET", attributes=attrs):
            pass
        (span,) = self.rig.exported_spans()
        self.assertEqual(dict(span.attributes), {"http.request.method": "GET"})

    def test_link_attributes_are_dropped_and_the_link_kept(self):
        with self.tracer.start_as_current_span("root") as root:
            ctx = root.get_span_context()
        with self.tracer.start_as_current_span("GET", links=[Link(ctx, {"secret": SENTINEL})]):
            pass
        span = self.rig.exported_by_name("GET")[0]
        self.assertEqual(len(span.links), 1)
        self.assertEqual(dict(span.links[0].attributes or {}), {})

    def test_an_error_status_description_is_the_exception_type_only(self):
        try:
            with self.tracer.start_as_current_span("GET"):
                raise ValueError(SENTINEL)
        except ValueError:
            pass
        raw = self.rig.raw_spans()[0]
        self.assertIn(SENTINEL, raw.status.description)  # control
        (span,) = self.rig.exported_spans()
        self.assertEqual(span.status.status_code, trace.StatusCode.ERROR)
        self.assertEqual(span.status.description, "ValueError")
        self.assertEqual([e.name for e in span.events], ["exception"])
        self.assertEqual(dict(span.events[0].attributes), {"exception.type": "ValueError"})
        self.assertNotIn(SENTINEL, self.rig.dump(self.rig.exported_spans()))

    def test_a_non_error_status_drops_its_description(self):
        with self.tracer.start_as_current_span("GET") as span:
            span.set_status(trace.Status(trace.StatusCode.OK))
        self.assertEqual(self.rig.exported_spans()[0].status.status_code, trace.StatusCode.OK)


class InstrumentationLeakTests(TestCase):
    """Each real instrumentation, on Django 6 and the real urlconf, through the boundary."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._env = mock.patch.dict(
            os.environ,
            {"OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST": ".*"},
        )
        cls._env.start()
        reset_semconv()
        cls.rig = Rig()
        cls.rig.instrument(
            DjangoInstrumentor(),
            CeleryInstrumentor(),
            PsycopgInstrumentor(),
            RedisInstrumentor(),
            RequestsInstrumentor(),
        )

    @classmethod
    def tearDownClass(cls):
        cls.rig.teardown()
        cls._env.stop()
        super().tearDownClass()

    def setUp(self):
        self.rig.raw.clear()
        self.rig.redacted.clear()
        self.failures = Failures()

    def _server_spans(self, exporter):
        return [s for s in exporter.get_finished_spans() if s.kind is SpanKind.SERVER]

    # ---- django -----------------------------------------------------------

    def test_django_routes_through_the_real_urlconf(self):
        from apps.proxy import stream_routes

        xc_regexes = [p.pattern.regex.pattern for p in stream_routes.xc_urlpatterns]
        client = Client(raise_request_exception=False)
        requests_made = [
            f"/live/user1/{SENTINEL}/42?password={SENTINEL}",
            f"/{SENTINEL}/{SENTINEL}/42",
            f"/proxy/ts/stream/{SENTINEL_UUID}",
            f"/hls/{HLS_TOKEN}/x.m3u8",
            f"/api/no/such/{SENTINEL}",
        ]
        for url in requests_made:
            client.get(url, HTTP_X_SENTINEL=SENTINEL)

        exported = self._server_spans(self.rig.redacted)
        f = self.failures
        f.check(len(exported) == len(requests_made), f"expected {len(requests_made)} server spans, got {len(exported)}")
        for secret in (SENTINEL, SENTINEL_UUID, HLS_TOKEN):
            f.leak_spans(exported, secret, "django server spans")
        for span in exported:
            for key in span.attributes:
                f.check(not key.startswith("http.request.header"), f"POLICY key {key} on {span.name!r}")
                f.check(key not in ("url.full", "http.url", "http.target", "url.path", "url.query"), f"POLICY key {key} on {span.name!r}")
        # An XC tune span carries the exact re_path regex as its route and in its name.
        names = {s.name for s in exported}
        for regex in xc_regexes:
            f.check(f"GET {regex}" in names, f"no XC span named for route {regex!r}; have {sorted(names)}")
        by_route = {s.attributes.get("http.route") for s in exported}
        f.check(xc_regexes[0] in by_route, "the /live/ XC route is missing from http.route")
        f.check(xc_regexes[1] in by_route, "the bare XC route is missing from http.route")
        # Control: the raw spans did carry the captured header, so the policy
        # assertion above is not vacuous.
        raw_dump = self.rig.dump(self._server_spans(self.rig.raw))
        f.check(SENTINEL in raw_dump, "control: header capture did not put the sentinel on the raw span")
        f.raise_if_any(self)

    def test_the_route_attribute_is_the_resolver_route_for_the_real_urlconf(self):
        match = resolve(f"/live/user1/{SENTINEL}/42")
        client = Client(raise_request_exception=False)
        client.get(f"/live/user1/{SENTINEL}/42")
        (span,) = self._server_spans(self.rig.redacted)
        self.assertEqual(span.attributes["http.route"], match.route)
        self.assertEqual(span.name, f"GET {match.route}")

    @override_settings(ROOT_URLCONF="tests.test_observability_redaction")
    def test_a_genuine_resolver404_is_named_get_with_no_route_and_no_raw_path_fallback(self):
        # The real urlconf has no genuinely unrouted path (an SPA catch-all
        # takes everything outside the API prefixes), so this uses the module's
        # own small urlconf: a Resolver404 for a path no pattern matches.
        response = Client(raise_request_exception=False).get(f"/no/such/{SENTINEL}?password={SENTINEL}")
        self.assertEqual(response.status_code, 404)
        exported = self._server_spans(self.rig.redacted)
        self.assertEqual([s.name for s in exported], ["GET"])
        self.assertNotIn("http.route", exported[0].attributes)
        self.assertNotIn(SENTINEL, self.rig.dump(exported))

    @override_settings(ROOT_URLCONF="tests.test_observability_redaction")
    def test_a_view_raising_a_bare_sentinel_exports_its_type_only(self):
        Client(raise_request_exception=False).get("/boom/")
        raw = self._server_spans(self.rig.raw)
        exported = self._server_spans(self.rig.redacted)
        f = self.failures
        f.check(len(exported) == 1, f"expected one server span, got {len(exported)}")
        f.check(any(SENTINEL in (s.status.description or "") for s in raw), "control: raw status did not carry the sentinel")
        f.leak_spans(exported, SENTINEL, "django exception span")
        if exported:
            f.check(exported[0].status.description == "ValueError", f"status description {exported[0].status.description!r}")
            f.check(
                [dict(e.attributes) for e in exported[0].events] == [{"exception.type": "ValueError"}],
                "exception event is not the type only",
            )
        f.raise_if_any(self)

    # ---- requests ---------------------------------------------------------

    def test_requests_failing_in_the_transport(self):
        class Failing(requests.adapters.HTTPAdapter):
            def send(self, request, **kwargs):
                raise requests.exceptions.ConnectionError(
                    f"HTTPConnectionPool(host='h', port=80): Max retries exceeded with url: "
                    f"/live/u/{SENTINEL}/1?password={SENTINEL}"
                )

        session = requests.Session()
        session.mount("http://", Failing())
        with self.assertRaises(requests.exceptions.ConnectionError):
            session.get(f"http://user:{SENTINEL}@h/live/u/{SENTINEL}/1?password={SENTINEL}")
        raw = [s for s in self.rig.raw.get_finished_spans() if s.kind is SpanKind.CLIENT]
        exported = [s for s in self.rig.redacted.get_finished_spans() if s.kind is SpanKind.CLIENT]
        f = self.failures
        f.check(len(exported) == 1, f"expected one client span, got {len(exported)}")
        raw_dump = self.rig.dump(raw)
        f.check(SENTINEL in raw_dump, "control: raw client span did not carry the sentinel")
        f.check("url.full" in raw[0].attributes, "control: raw span has no url.full")
        f.leak_spans(exported, SENTINEL, "requests client span")
        for key in ("url.full", "user_agent.original", "network.peer.address", "network.peer.port"):
            f.check(key not in exported[0].attributes, f"POLICY key {key} on {exported[0].name!r}")
        f.check(exported[0].name == "GET", f"span name {exported[0].name!r}")
        f.check(exported[0].attributes.get("error.type") == "ConnectionError", "error.type was not kept")
        f.raise_if_any(self)

    def test_relay_client_advance_injects_the_requests_client_span_context(self):
        from apps.proxy import relay_client

        captured = {}

        def send(adapter, request, **kwargs):
            captured["traceparent"] = request.headers.get("traceparent")
            raise requests.exceptions.ConnectionError(f"Max retries exceeded with url: {request.path_url}")

        tracer = self.rig.tracer_provider.get_tracer("test")
        with mock.patch.object(requests.adapters.HTTPAdapter, "send", send):
            with tracer.start_as_current_span("admin request", kind=SpanKind.SERVER):
                with self.assertRaises(relay_client.RelayUnavailable):
                    relay_client.advance(str(uuid.uuid4()), url=f"http://p/{SENTINEL}")
        client_spans = [s for s in self.rig.raw.get_finished_spans() if s.kind is SpanKind.CLIENT]
        f = self.failures
        f.check(len(client_spans) == 1, f"expected one client span, got {len(client_spans)}")
        f.check(bool(captured.get("traceparent")), "no traceparent was injected into the outgoing request")
        if client_spans and captured.get("traceparent"):
            ctx = client_spans[0].context
            f.check(
                captured["traceparent"].startswith(f"00-{ctx.trace_id:032x}-{ctx.span_id:016x}-"),
                f"traceparent {captured['traceparent']!r} does not name the requests client span",
            )
        f.leak_spans(self.rig.exported_spans(), SENTINEL, "relay_client.advance spans")
        f.raise_if_any(self)

    # ---- psycopg ----------------------------------------------------------

    @skipUnless(connection.vendor == "postgresql", "opens a raw PostgreSQL connection with psycopg")
    def test_psycopg_syntax_error_echoing_a_literal(self):
        conn = psycopg.connect(**connection.get_connection_params())
        self.addCleanup(conn.close)
        with self.assertRaises(psycopg.Error):
            conn.cursor().execute(f"SELECT '{SENTINEL}' FROM")
        raw = [s for s in self.rig.raw.get_finished_spans() if s.instrumentation_scope.name.endswith("psycopg")]
        exported = [s for s in self.rig.redacted.get_finished_spans() if s.instrumentation_scope.name.endswith("psycopg")]
        f = self.failures
        f.check(bool(exported), "no psycopg span was exported")
        f.check(SENTINEL in self.rig.dump(raw), "control: raw psycopg span did not carry the sentinel")
        f.leak_spans(exported, SENTINEL, "psycopg spans")
        for span in exported:
            for key in ("db.statement", "db.user", "db.query.text"):
                f.check(key not in span.attributes, f"POLICY key {key} on {span.name!r}")
        f.raise_if_any(self)

    # ---- redis ------------------------------------------------------------

    def _redis(self):
        return redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=int(settings.REDIS_DB))

    def test_redis_error_echoing_an_argument_and_a_set_of_a_uuid(self):
        client = self._redis()
        with self.assertRaises(redis.ResponseError):
            client.execute_command("NOSUCHCMD", SENTINEL)
        client.set(SENTINEL_UUID, SENTINEL)
        client.delete(SENTINEL_UUID)
        raw = [s for s in self.rig.raw.get_finished_spans() if s.instrumentation_scope.name.endswith("redis")]
        exported = [s for s in self.rig.redacted.get_finished_spans() if s.instrumentation_scope.name.endswith("redis")]
        f = self.failures
        f.check(len(exported) >= 3, f"expected the redis commands to export, got {len(exported)}")
        f.check(SENTINEL in self.rig.dump(raw), "control: raw redis span did not carry the sentinel")
        f.leak_spans(exported, SENTINEL, "redis spans")
        f.leak_spans(exported, SENTINEL_UUID, "redis spans")
        f.check("NOSUCHCMD" in {s.name for s in exported}, "the NOSUCHCMD span name was not kept")
        for span in exported:
            f.check("db.statement" not in span.attributes, f"POLICY key db.statement on {span.name!r}")
        f.raise_if_any(self)

    # ---- celery -----------------------------------------------------------

    def test_celery_task_raising_with_a_bare_argument(self):
        app = Celery("observability-test")
        app.conf.task_always_eager = False

        @app.task(name="tests.observability.raises")
        def raises(arg, k=None):
            raise ValueError(f"bare {arg}")

        result = raises.apply(args=[SENTINEL], kwargs={"k": SENTINEL})
        self.assertEqual(result.state, "FAILURE")
        raw = [s for s in self.rig.raw.get_finished_spans() if s.instrumentation_scope.name.endswith("celery")]
        exported = [s for s in self.rig.redacted.get_finished_spans() if s.instrumentation_scope.name.endswith("celery")]
        f = self.failures
        f.check(any(s.name == "run/tests.observability.raises" for s in exported), f"no run span; have {[s.name for s in exported]}")
        f.check(SENTINEL in self.rig.dump(raw), "control: raw celery span did not carry the sentinel")
        f.leak_spans(exported, SENTINEL, "celery spans")
        for span in exported:
            for key in ("celery.delivery_info", "celery.hostname"):
                f.check(key not in span.attributes, f"POLICY key {key} on {span.name!r}")
        f.raise_if_any(self)

    def test_celery_task_that_retries_with_the_sentinel_in_its_exception(self):
        app = Celery("observability-test-retry")

        @app.task(name="tests.observability.retries", bind=True, max_retries=1)
        def retries(self):
            raise self.retry(exc=ValueError(SENTINEL), countdown=0)

        retries.apply()
        raw = [s for s in self.rig.raw.get_finished_spans() if s.instrumentation_scope.name.endswith("celery")]
        exported = [s for s in self.rig.redacted.get_finished_spans() if s.instrumentation_scope.name.endswith("celery")]
        f = self.failures
        f.check(bool(exported), "no celery span was exported")
        f.check(SENTINEL in self.rig.dump(raw), "control: raw celery span did not carry the sentinel")
        f.leak_spans(exported, SENTINEL, "celery retry spans")
        f.raise_if_any(self)


class LogFieldAndBodyTests(TestCase):
    """Structured fields are allow-by-construction; bodies are policy-tested only."""

    def setUp(self):
        self.rig = Rig()
        self.addCleanup(self.rig.teardown)
        logs.install_inner_handler(
            LoggingHandler(logger_provider=self.rig.logger_provider, log_code_attributes=True)
        )
        self.addCleanup(logs.install_inner_handler, None)
        self.log = logging.getLogger("tests.observability.logs")
        self.log.propagate = False
        self.log.setLevel(logging.DEBUG)
        self.handler = logs.OtelBridgeHandler()
        self.log.addHandler(self.handler)
        self.addCleanup(self.log.removeHandler, self.handler)

    def _exported(self):
        return [r.log_record for r in self.rig.redacted_logs.get_finished_logs()]

    def _raw(self):
        return [r.log_record for r in self.rig.raw_logs.get_finished_logs()]

    def test_extra_fields_never_leave_the_bridge(self):
        self.log.info("hello", extra={"secret": SENTINEL, "count": 3})
        (raw,) = self._raw()
        (record,) = self._exported()
        self.assertEqual(redaction.LOG_EXTRA_RULES, {})  # POLICY: empty allowlist
        for attrs in (raw.attributes, record.attributes):
            self.assertNotIn("secret", attrs)
            self.assertNotIn("count", attrs)
            self.assertNotIn(SENTINEL, repr(dict(attrs)))

    def test_a_typed_rule_keeps_its_key_and_still_drops_the_other(self):
        # The exporter's typed extras allowlist, reached by a record that did not
        # come through the bridge (the bridge forwards no extras at all).
        from opentelemetry._logs import LogRecord

        logger = self.rig.logger_provider.get_logger("direct")
        with mock.patch.dict(redaction.LOG_EXTRA_RULES, {"count": redaction._is_int}):
            logger.emit(LogRecord(body="hello", attributes={"secret": SENTINEL, "count": 3}))
        (record,) = self._exported()
        self.assertEqual(record.attributes.get("count"), 3)  # POLICY
        self.assertNotIn("secret", record.attributes)
        self.assertNotIn(SENTINEL, repr(dict(record.attributes)))  # LEAK

    def test_an_exception_log_carries_a_type_and_frames_without_locals_or_message(self):
        def inner():
            local_secret = SENTINEL  # noqa: F841 - must not appear in the export
            raise ValueError(f"message {SENTINEL}")

        try:
            inner()
        except ValueError:
            self.log.exception("failed")
        (record,) = self._exported()
        attrs = dict(record.attributes)
        self.assertEqual(attrs["exception.type"], "ValueError")
        frames = attrs["mino.exception.frames"]
        self.assertTrue(frames)
        self.assertRegex(frames[-1], r"test_observability_redaction\.py:\d+ in inner$")
        self.assertNotIn(SENTINEL, repr(attrs))
        self.assertNotIn("exception.message", attrs)
        self.assertNotIn("exception.stacktrace", attrs)
        # The bridge never hands the SDK a message either.
        self.assertNotIn("exception.message", self._raw()[0].attributes)

    def test_hostile_extras_never_reach_the_encoded_otlp_bytes(self):
        """Each mechanism by which an ``extra=`` key could become wire data, on the ENCODED bytes."""
        from opentelemetry.exporter.otlp.proto.common._log_encoder import encode_logs

        hostile = [
            # promoted by the SDK handler to the record's first-class event name
            {"otel.event.name": SENTINEL},
            {"event.name": SENTINEL_UUID},
            # spoofing each structured field (the legacy spellings are not allowlisted at all)
            {"code.filepath": SENTINEL, "code.function": SENTINEL, "code.lineno": 7},
            {"code.file.path": SENTINEL, "code.function.name": SENTINEL, "code.line.number": 7},
            {"exception.type": SENTINEL},
            {"mino.exception.frames": [f"/live/user/{SENTINEL}/1:1 in f"]},
        ]
        for extra in hostile:
            with self.subTest(keys=sorted(extra)):
                self.rig.raw_logs.clear()
                self.rig.redacted_logs.clear()
                self.log.info("hello", extra=extra)
                raw = self.rig.raw_logs.get_finished_logs()
                exported = self.rig.redacted_logs.get_finished_logs()
                self.assertEqual(len(exported), 1)
                encoded = encode_logs(exported).SerializeToString()
                self.assertNotIn(SENTINEL.encode(), encoded, f"the sentinel reached the OTLP bytes via {sorted(extra)}")
                self.assertNotIn(SENTINEL_UUID.encode(), encoded)
                # POLICY: the structured fields are the code's, not the caller's
                attrs = dict(exported[0].log_record.attributes)
                self.assertEqual(attrs["code.function.name"], "test_hostile_extras_never_reach_the_encoded_otlp_bytes")
                self.assertNotEqual(attrs["code.line.number"], 7)
                self.assertNotIn("exception.type", attrs)
                self.assertNotIn("mino.exception.frames", attrs)
                self.assertIsNone(exported[0].log_record.event_name)
                # The bridge itself already forwards nothing from extra (the exporter is the second line).
                self.assertEqual(len(raw), 1)
                self.assertNotIn(SENTINEL, repr(dict(raw[0].log_record.attributes)))
                self.assertIsNone(raw[0].log_record.event_name)

    def test_the_exporter_alone_clears_event_name_and_spoofed_fields(self):
        # The bridge is bypassed here: a record reaching the logger provider by
        # any other route still leaves clean.
        from opentelemetry.exporter.otlp.proto.common._log_encoder import encode_logs
        from opentelemetry._logs import LogRecord

        logger = self.rig.logger_provider.get_logger("direct")
        logger.emit(
            LogRecord(
                body="direct",
                attributes={"code.filepath": SENTINEL, "exception.type": "x y", "mino.exception.frames": ["bad"]},
                event_name=SENTINEL,
            )
        )
        (exported,) = self.rig.redacted_logs.get_finished_logs()
        self.assertEqual(dict(self.rig.raw_logs.get_finished_logs()[0].log_record.attributes)["code.filepath"], SENTINEL)  # control
        self.assertNotIn(SENTINEL.encode(), encode_logs([exported]).SerializeToString())
        self.assertIsNone(exported.log_record.event_name)

    def test_a_retry_log_body_loses_its_url_uuid_and_token_classes(self):
        # R-Q17: the bare sentinel in an exception text is NOT asserted absent.
        body = (
            f"Task tests.observability.retries[{SENTINEL_UUID}] retry: Retry in 1s: "
            f"ConnectionError('http://u:pw@prov.tv/live/a/b/1 {HLS_TOKEN}')"
        )
        # The D9 layer alone must remove these classes: the central log scrubber would already have
        # masked the userinfo, so capture the raw body (spec 9.2).
        with unscrubbed_logging():
            self.log.warning(body)
        (record,) = self._exported()
        for secret in ("pw@prov.tv", SENTINEL_UUID, HLS_TOKEN):
            self.assertNotIn(secret, record.body)

    def test_body_policy_one_case_per_pattern_class(self):
        # POLICY TESTS ONLY (R-Q17). Each pattern class is shown removed from a
        # body that contains it. A bare sentinel in a body is deliberately NOT
        # asserted absent: no class targets it, and the body is no stronger
        # than stdout.
        cases = {
            "url": ("fetching http://prov.tv:8080/live/user/pw123/1.ts?token=abc now", ["pw123", "prov.tv", "abc"]),
            "scheme-less path": ("opened /live/someuser/somepass/42 for client", ["someuser", "somepass"]),
            "uuid": (f"channel {SENTINEL_UUID} started", [SENTINEL_UUID]),
            "hls token": (f"session {HLS_TOKEN} left", [HLS_TOKEN]),
            "long hex": ("digest " + "ab12" * 10 + " ok", ["ab12" * 10]),
            "key=value": ("login failed password=hunter2 for x", ["hunter2"]),
        }
        for label, (body, secrets) in cases.items():
            with self.subTest(label):
                out = redaction.redact_text(body)
                self.assertNotEqual(out, body)
                for secret in secrets:
                    self.assertNotIn(secret, out)
                with unscrubbed_logging():  # the D9 layer alone, not the central scrubber (spec 9.2)
                    self.log.info(body)
        exported = [r.body for r in self._exported()]
        self.assertEqual(len(exported), len(cases))
        for body, (_, secrets) in zip(exported, cases.values()):
            for secret in secrets:
                self.assertNotIn(secret, body)

    def test_a_body_without_a_pattern_class_is_unchanged(self):
        self.assertEqual(redaction.redact_text("Started 3 clients on channel 7"), "Started 3 clients on channel 7")


class ValidatorTests(TestCase):
    def test_a_trailing_newline_is_refused(self):
        for validator, good in (
            (redaction.is_dotted, "abc"),
            (redaction.is_route, "^api/"),
            (redaction.is_uuid, SENTINEL_UUID),
            (redaction.is_identifier, "postgresql"),
            (redaction.is_hostname, "example.com"),
            (redaction.is_digits, "12"),
        ):
            with self.subTest(validator=validator):
                self.assertTrue(validator(good))
                self.assertFalse(validator(good + "\n"))

    def test_a_uuid_shaped_server_address_is_refused(self):
        self.assertFalse(redaction.is_hostname(SENTINEL_UUID))
        self.assertFalse(redaction.is_hostname(f"{SENTINEL_UUID}.example.com"))
        self.assertTrue(redaction.is_hostname("web"))

    def test_a_frame_with_a_trailing_newline_is_refused(self):
        self.assertTrue(redaction.is_frames(["a.py:1 in f"]))
        self.assertFalse(redaction.is_frames(["a.py:1 in f\n"]))


class MetricBoundaryTests(TestCase):
    def setUp(self):
        self.rig = Rig()
        self.addCleanup(self.rig.teardown)
        self.meter = self.rig.meter_provider.get_meter(SCOPE_NAME)
        self.tracer = self.rig.tracer_provider.get_tracer("test")

    def _points(self):
        self.rig.flush_metrics()
        return self.rig.metric_sink.points(), self.rig.raw_metric_sink.points()

    def test_an_excluded_attribute_recorded_in_a_sampled_span_exports_nowhere(self):
        histogram = self.meter.create_histogram(M11_NAME, unit="s")
        with self.tracer.start_as_current_span("recording"):
            histogram.record(1.5, {"task": "apps.x.tasks.run", "outcome": "SUCCESS", "secret": SENTINEL})
        exported, raw = self._points()
        self.assertEqual(exported.get(M11_NAME), [{"task": "apps.x.tasks.run", "outcome": "SUCCESS"}])
        self.assertNotIn(SENTINEL, repr(exported))
        # The View cut the key before the exporter; exemplars are off, so the
        # secret is not in an exemplar's filtered attributes either.
        for data in self.rig.raw_metric_sink.exports:
            for rm in data.resource_metrics:
                for sm in rm.scope_metrics:
                    for metric in sm.metrics:
                        for point in metric.data.data_points:
                            self.assertEqual(list(getattr(point, "exemplars", ())), [])
        self.assertNotIn(SENTINEL, repr(raw))

    def test_an_uncatalogued_counter_exports_nothing(self):
        counter = self.meter.create_counter("uncatalogued_total")
        counter.add(1, {"k": "v"})
        exported, raw = self._points()
        self.assertNotIn("uncatalogued_total", exported)
        self.assertNotIn("uncatalogued_total", raw)  # the wildcard view dropped it first

    def test_the_exporter_itself_drops_an_uncatalogued_metric_the_views_did_not(self):
        # No Views here: the boundary must not depend on them.
        rig = Rig(views=False)
        self.addCleanup(rig.teardown)
        meter = rig.meter_provider.get_meter(SCOPE_NAME)
        meter.create_counter("uncatalogued_total").add(1)  # no attributes: only the name can condemn it
        meter.create_histogram(M11_NAME, unit="s").record(1.0, {"task": "apps.x.tasks.ok", "outcome": "SUCCESS", "extra": SENTINEL})
        rig.flush_metrics()
        self.assertIn("uncatalogued_total", rig.raw_metric_sink.points())  # control
        exported = rig.metric_sink.points()
        self.assertNotIn("uncatalogued_total", exported)
        self.assertNotIn(M11_NAME, exported)  # an unlisted key fails the point
        self.assertNotIn(SENTINEL, repr(exported))

    def test_a_catalogue_point_whose_task_is_a_url_is_dropped(self):
        histogram = self.meter.create_histogram(M11_NAME, unit="s")
        histogram.record(1.0, {"task": f"http://u:{SENTINEL}@h/x", "outcome": "SUCCESS"})
        histogram.record(1.0, {"task": "apps.x.tasks.ok", "outcome": "SUCCESS"})
        exported, raw = self._points()
        self.assertIn(SENTINEL, repr(raw))  # control: the View kept the key
        self.assertEqual(exported.get(M11_NAME), [{"task": "apps.x.tasks.ok", "outcome": "SUCCESS"}])
        self.assertNotIn(SENTINEL, repr(exported))

    def test_an_outcome_outside_the_closed_set_is_dropped(self):
        histogram = self.meter.create_histogram(M11_NAME, unit="s")
        histogram.record(1.0, {"task": "apps.x.tasks.ok", "outcome": SENTINEL})
        exported, _ = self._points()
        self.assertNotIn(M11_NAME, exported)


# ---------------------------------------------------------------------------
# LS-2 / spec T8: redact_text scans in linear time, byte-identical to the
# regexes it replaced. The three old expressions live here and nowhere else.
# ---------------------------------------------------------------------------

# Same registration as tests/test_redaction.py (byte-identical profile).
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

_OLD_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s\"'<>]+")
_OLD_KEY_VALUE_RE = re.compile(
    r"(?i)\b([\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|credential|auth)[\w.-]*)"
    r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
)
_OLD_PATH_RE = re.compile(r"(?<![\w/:.-])/[^\s\"'<>,;)\]]*[A-Za-z0-9_%~-][^\s\"'<>,;)\]]*")


def _old_urls(text):
    return _OLD_URL_RE.sub(redaction.REDACTED, text)


def _old_key_values(text):
    return _OLD_KEY_VALUE_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{redaction.REDACTED}", text
    )


def _old_paths(text):
    return _OLD_PATH_RE.sub(redaction.REDACTED, text)


def _old_redact_text(text):
    """The pre-LS-2 composition, in the pre-LS-2 order."""
    if not isinstance(text, str) or not text:
        return text
    text = _old_urls(text)
    text = redaction._UUID_ANYWHERE_RE.sub(redaction.REDACTED, text)
    text = redaction._HLS_TOKEN_RE.sub(redaction.REDACTED, text)
    text = redaction._LONG_HEX_RE.sub(redaction.REDACTED, text)
    text = _old_key_values(text)
    return _old_paths(text)


_T8_FRAGMENTS = [
    '"', "'", "=", ":", "/", "(", '"<>,;)]', " ", "\t", "\n", ".", "-", "_", "&", "?",
    "token", "AUTH", "PassWord", "api-key", "api_key", "apikey", "ſecret", "Secret",
    "credential", "pwd", "passwd", "x", "a", "1", "://", "http", "https", "ftp",
    "1http", "x=", "é", "ß", "²",
    # trigger-dense compounds, so 200 derandomized examples reach the edge cases
    "1https://", "-ftp://", "9http://x", "token=", "x=token=", "/a/(", "(/",
]
_T8_STRINGS = (
    st.lists(st.sampled_from(_T8_FRAGMENTS), min_size=1, max_size=16)
    .map("".join)
    .filter(lambda s: len(s) <= 64)
)

_T8_FIXED = [
    "1https://example.invalid/x",
    "x=token=pass",
    'token="one two";x=token=three',
    "token='auth=x'auth=y",
    '.-AUTH.key: "v"',
    "ſecret=x",
    "éhttps://x",
    "a/b(/c)",
    "/é",
    "/éa",
    "https://u:p@h.invalid/a/b?token=abc&x=1 see /var/log/x.log",
    'password="a b" /live/u/p/1.ts',
    # one 64-character string per scanner
    "a" * 60 + "://x",
    "auth." * 10 + "k=v;" + "x" * 10,
    "/(" * 32,
    # a quoted value followed by the OTHER quote kind; a non-ASCII letter before a path
    "token=\"a\" 'b",
    "é/a",
]

_T8_SCANNERS = (
    ("_scrub_urls", _old_urls),
    ("_scrub_key_values", _old_key_values),
    ("_scrub_paths", _old_paths),
)


def _t8_differences(text):
    """Every way the new code disagrees with the oracle on ``text``."""
    found = []
    for name, old in _T8_SCANNERS:
        new = getattr(redaction, name)(text)
        if new != old(text):
            found.append(f"{name}({text!r}) = {new!r}, oracle {old(text)!r}")
    new = redaction.redact_text(text)
    if new != _old_redact_text(text):
        found.append(f"redact_text({text!r}) = {new!r}, oracle {_old_redact_text(text)!r}")
    return found


def _round_one_wrong_scrub_urls(text):
    """The round-1 rewrite: a scheme must follow a non-scheme character."""
    return re.sub(
        r"(?<![A-Za-z0-9+.\-])[A-Za-z][A-Za-z0-9+.\-]*://[^\s\"'<>]+",
        redaction.REDACTED,
        text,
    )


class RedactTextLinearTests(SimpleTestCase):
    """T8: the linear scanners equal the old regexes; long hostile input is fast."""

    def test_fixed_examples_match_the_oracle(self):
        for text in _T8_FIXED:
            with self.subTest(text=text):
                self.assertEqual(_t8_differences(text), [])

    def test_the_named_examples_keep_their_known_output(self):
        # Exact values, so an oracle and a scanner that drift together still fail.
        R = redaction.REDACTED
        self.assertEqual(redaction.redact_text("1https://example.invalid/x"), f"1{R}")
        self.assertEqual(redaction._scrub_key_values("x=token=pass"), f"x=token={R}")

    @given(_T8_STRINGS)
    def test_bounded_differential(self, text):
        self.assertEqual(_t8_differences(text), [])

    def test_the_differential_can_fail(self):
        # Positive control: the round-1 wrong rewrite must be caught, by the
        # fixed example and by the generator.
        with mock.patch.object(redaction, "_scrub_urls", _round_one_wrong_scrub_urls):
            self.assertNotEqual(_t8_differences("1https://example.invalid/x"), [])
            hit = find(
                _T8_STRINGS,
                lambda s: bool(_t8_differences(s)),
                settings=hyp_settings(max_examples=5000, derandomize=True, deadline=None),
            )
            self.assertNotEqual(_t8_differences(hit), [])

    def test_long_hostile_input_is_scanned_in_linear_time(self):
        # Scanner-only: the oracle never sees these. The bound is the spec's
        # 50 ms; the scanners measure 0.1 to 4 ms at these sizes and the old
        # expressions take 0.2 s to 18 s, so the bound is >10x above linear and
        # >4x below the cheapest quadratic. The best of three runs is used so a
        # single GC pause or scheduler hiccup on a loaded runner cannot redden it.
        hostile = {
            # exercises _scrub_urls only because the long-hex pattern masks it first
            "a * 32000": "a" * 32000,
            "a. * 16000": "a." * 16000,
            "auth * 8000": "auth" * 8000,
            "token=\" * 4500": 'token="' * 4500,
            "/( * 16000": "/(" * 16000,
        }
        for label, text in hostile.items():
            best = None
            for _ in range(3):
                started = time.perf_counter()
                redaction.redact_text(text)
                elapsed = time.perf_counter() - started
                best = elapsed if best is None else min(best, elapsed)
            with self.subTest(shape=label):
                self.assertLess(
                    best,
                    0.050,
                    f"redact_text took {best * 1000:.1f} ms on {label}: "
                    "a pattern is super-linear again",
                )

