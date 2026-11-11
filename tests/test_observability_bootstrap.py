"""Observability spec D10, D12, D13: what ``init`` installs, and when.

The OTel global providers are set-once per process, so every case that turns
OTLP on runs in a fresh interpreter (``run_child``) with an allowlisted
environment.
"""
import os
from unittest import mock

from django.test import SimpleTestCase

from dispatcharr.observability import bootstrap, config
from tests.otel_rig import child_env, run_child

# OTLP is pointed at a closed port: no span is produced by these cases, and a
# failed export is silent.
ENDPOINT = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:9"}

PRELUDE = """
import json, logging, os, sys, threading

class _Capture(logging.Handler):
    def __init__(self): super().__init__(); self.messages = []
    def emit(self, record): self.messages.append(record.getMessage())

capture = _Capture()
logging.getLogger().addHandler(capture)
logging.getLogger().setLevel(logging.INFO)
from opentelemetry import trace, metrics, _logs
from dispatcharr.observability import bootstrap
"""


def run(body, env):
    result, payload = run_child(PRELUDE + body, child_env(env))
    assert payload is not None, f"child printed no JSON.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr[-3000:]}"
    return payload


class OffByDefaultTests(SimpleTestCase):
    BODY = """
before = threading.active_count()
bootstrap.init("mino-api", "api-uwsgi")
print(json.dumps({
    "tracer": type(trace.get_tracer_provider()).__name__,
    "meter": type(metrics.get_meter_provider()).__name__,
    "logger": type(_logs.get_logger_provider()).__name__,
    "threads_before": before, "threads_after": threading.active_count(),
    "semconv": os.environ.get("OTEL_SEMCONV_STABILITY_OPT_IN"),
    "otel_messages": [m for m in capture.messages if "OpenTelemetry" in m],
}))
"""

    def _assert_off(self, payload):
        self.assertEqual(payload["tracer"], "ProxyTracerProvider")
        self.assertEqual(payload["meter"], "_ProxyMeterProvider")
        self.assertEqual(payload["logger"], "ProxyLoggerProvider")
        self.assertEqual(payload["threads_after"], payload["threads_before"])
        self.assertIsNone(payload["semconv"], "init must not touch the environment when OTLP is off")

    def test_endpoint_unset_installs_nothing(self):
        payload = run(self.BODY, {})
        self._assert_off(payload)
        self.assertEqual(payload["otel_messages"], [])

    def test_sdk_disabled_true_installs_nothing(self):
        self._assert_off(run(self.BODY, {**ENDPOINT, "OTEL_SDK_DISABLED": "true"}))

    def test_a_grpc_protocol_turns_otlp_off_with_one_warning(self):
        payload = run(self.BODY, {**ENDPOINT, "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc"})
        self._assert_off(payload)
        self.assertEqual(len(payload["otel_messages"]), 1, payload["otel_messages"])
        message = payload["otel_messages"][0]
        self.assertIn("OTEL_EXPORTER_OTLP_PROTOCOL", message)
        self.assertIn("http/protobuf", message)
        self.assertNotIn("grpc", message)

    def test_a_per_signal_protocol_variable_also_turns_it_off(self):
        self._assert_off(run(self.BODY, {**ENDPOINT, "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL": "http/json"}))


class OnTests(SimpleTestCase):
    BODY = """
bootstrap.init("mino-api", "api-uwsgi")
tp = trace.get_tracer_provider()
first = bootstrap._providers["tracer"]
processors = len(tp._active_span_processor._span_processors)
bootstrap.init("mino-api", "api-uwsgi")
same_provider_after_second_init = bootstrap._providers["tracer"] is first
processors_after_second = len(trace.get_tracer_provider()._active_span_processor._span_processors)
res = tp.resource.attributes
mp = metrics.get_meter_provider()
print(json.dumps({
    "tracer": type(tp).__name__, "meter": type(mp).__name__,
    "logger": type(_logs.get_logger_provider()).__name__,
    "processors": processors, "processors_after_second": processors_after_second,
    "same_provider_after_second_init": same_provider_after_second_init,
    "resource": {k: res.get(k) for k in ("service.name", "mino.program", "service.instance.id",
                                          "service.version", "foo", "telemetry.sdk.language")},
    "exemplar_filter": type(mp._sdk_config.exemplar_filter).__name__,
    "sampler": tp.sampler.get_description(),
    "semconv": os.environ.get("OTEL_SEMCONV_STABILITY_OPT_IN"),
    "info": [m for m in capture.messages if m.startswith("OpenTelemetry export enabled")],
}))
"""

    def test_endpoint_set_installs_sdk_providers_and_a_second_init_is_a_no_op(self):
        p = run(self.BODY, ENDPOINT)
        self.assertEqual((p["tracer"], p["meter"], p["logger"]), ("TracerProvider", "MeterProvider", "LoggerProvider"))
        self.assertEqual(p["processors"], 1)
        self.assertTrue(p["same_provider_after_second_init"], "a second init in the same pid rebuilt the tracer provider")
        self.assertEqual(p["processors_after_second"], 1, "a second init in the same pid added a span processor")
        self.assertEqual(p["semconv"], "http")

    def test_the_resource_carries_our_four_attributes_and_they_win(self):
        env = {
            **ENDPOINT,
            "OTEL_RESOURCE_ATTRIBUTES": "service.name=evil,mino.program=evil,service.instance.id=evil,service.version=evil,foo=bar",
            "OTEL_SERVICE_NAME": "evil2",
        }
        res = run(self.BODY, env)["resource"]
        self.assertEqual(res["service.name"], "mino-api")
        self.assertEqual(res["mino.program"], "api-uwsgi")
        self.assertRegex(res["service.instance.id"], r"^[0-9a-f-]{36}$")
        from version import __version__

        self.assertEqual(res["service.version"], __version__)
        self.assertEqual(res["foo"], "bar", "other OTEL_RESOURCE_ATTRIBUTES keys pass through (R-Q18)")

    def test_exemplars_stay_off_whatever_the_environment_says(self):
        p = run(self.BODY, {**ENDPOINT, "OTEL_METRICS_EXEMPLAR_FILTER": "always_on"})
        self.assertEqual(p["exemplar_filter"], "AlwaysOffExemplarFilter")

    def test_the_sampler_is_parent_based_ratio_and_ignores_otel_traces_sampler(self):
        p = run(self.BODY, {**ENDPOINT, "OTEL_TRACES_SAMPLER_ARG": "0.25", "OTEL_TRACES_SAMPLER": "always_off"})
        self.assertIn("TraceIdRatioBased{0.25}", p["sampler"])
        self.assertTrue(p["sampler"].startswith("ParentBased"))

    def test_an_unparseable_sampler_arg_is_one_and_warns_once_without_the_value(self):
        code = PRELUDE + """
bootstrap.init("mino-api", "api-uwsgi")
print(json.dumps({"sampler": trace.get_tracer_provider().sampler.get_description(),
                  "warnings": [m for m in capture.messages if "SAMPLER_ARG" in m]}))
"""
        _, p = run_child(code, child_env({**ENDPOINT, "OTEL_TRACES_SAMPLER_ARG": "S3NT1NEL-pw-9d2f"}))
        self.assertIn("TraceIdRatioBased{1.0}", p["sampler"])
        self.assertEqual(len(p["warnings"]), 1)
        self.assertNotIn("S3NT1NEL", p["warnings"][0])

    def test_one_signal_can_be_switched_off(self):
        code = PRELUDE + """
bootstrap.init("mino-worker", "celery-beat")
print(json.dumps({"tracer": type(trace.get_tracer_provider()).__name__,
                  "meter": type(metrics.get_meter_provider()).__name__}))
"""
        _, p = run_child(code, child_env({**ENDPOINT, "OTEL_TRACES_EXPORTER": "none"}))
        self.assertEqual(p, {"tracer": "ProxyTracerProvider", "meter": "MeterProvider"})

    def test_the_one_info_line_names_the_endpoint_as_scheme_host_port_only(self):
        env = {"OTEL_EXPORTER_OTLP_ENDPOINT": "https://user:S3NT1NEL-pw-9d2f@collector.example:4318/v1/x?k=S3NT1NEL-pw-9d2f"}
        code = PRELUDE + """
bootstrap.init("mino-api", "daphne")
print(json.dumps({"info": [m for m in capture.messages if m.startswith("OpenTelemetry export enabled")]}))
"""
        _, p = run_child(code, child_env(env))
        self.assertEqual(len(p["info"]), 1)
        self.assertTrue(p["info"][0].endswith("to https://collector.example:4318"), p["info"][0])
        self.assertNotIn("S3NT1NEL", p["info"][0])

    def test_init_in_a_forked_child_builds_nothing_and_warns_once(self):
        # Deviation from D10 ("a forked child initialises itself"): the OTel
        # API's global providers are set-once, so a child cannot replace the
        # parent's. A second set would leave the instrumentors bound to the
        # parent's providers and add threads nothing writes to. The shipped
        # protection is the lazy-apps test.
        code = PRELUDE + """
bootstrap.init("mino-api", "api-uwsgi")
tracer, meter, logger_provider = trace.get_tracer_provider(), metrics.get_meter_provider(), _logs.get_logger_provider()
providers = dict(bootstrap._providers)
threads = threading.active_count()
real = os.getpid()
os.getpid = lambda: real + 1   # a fork: same module state, new pid
bootstrap.init("mino-api", "api-uwsgi")
bootstrap.init("mino-api", "api-uwsgi")
print(json.dumps({
    "global_tracer_unchanged": trace.get_tracer_provider() is tracer,
    "global_meter_unchanged": metrics.get_meter_provider() is meter,
    "global_logger_unchanged": _logs.get_logger_provider() is logger_provider,
    "providers_unchanged": bootstrap._providers == providers,
    "threads_grew": threading.active_count() - threads,
    "warnings": [m for m in capture.messages if "initialised before this process forked" in m],
}))
"""
        _, p = run_child(code, child_env(ENDPOINT))
        self.assertTrue(p["global_tracer_unchanged"] and p["global_meter_unchanged"] and p["global_logger_unchanged"])
        self.assertTrue(p["providers_unchanged"], "init in a forked child built new providers")
        self.assertLessEqual(p["threads_grew"], 0, "init in a forked child started threads")
        self.assertEqual(len(p["warnings"]), 1, p["warnings"])
        self.assertIn("lazy-apps", p["warnings"][0])

    def test_a_fork_after_an_off_init_still_does_nothing_harmful(self):
        code = PRELUDE + """
bootstrap.init("mino-api", "api-uwsgi")
real = os.getpid()
os.getpid = lambda: real + 1
bootstrap.init("mino-api", "api-uwsgi")
print(json.dumps({"tracer": type(trace.get_tracer_provider()).__name__,
                  "warnings": [m for m in capture.messages if "forked" in m]}))
"""
        _, p = run_child(code, child_env({}))
        self.assertEqual(p, {"tracer": "ProxyTracerProvider", "warnings": []})


class InProcessTests(SimpleTestCase):
    def test_semconv_opt_in_is_merged_not_defaulted(self):
        cases = {None: "http", "": "http", "database": "database,http", "http": "http", "http/dup": "http/dup",
                 " database , http/dup ": "database,http/dup", "database,messaging": "database,messaging,http"}
        for preset, expected in cases.items():
            with self.subTest(preset=preset), mock.patch.dict(os.environ):
                os.environ.pop("OTEL_SEMCONV_STABILITY_OPT_IN", None)
                if preset is not None:
                    os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = preset
                bootstrap._merge_semconv_opt_in()
                self.assertEqual(os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"], expected)

    def test_init_records_the_identity_for_logs_even_when_otlp_is_off(self):
        from dispatcharr.observability import logs

        with mock.patch.object(bootstrap, "_initialised_pid", None), mock.patch.dict(os.environ, clear=False):
            os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
            bootstrap.init("mino-worker", "celery-dvr")
        self.assertEqual(logs.get_identity(), {"service.name": "mino-worker", "mino.program": "celery-dvr"})
        logs.set_identity(None, None)

    def test_init_never_raises_when_installation_fails(self):
        with mock.patch.object(bootstrap, "_initialised_pid", None), mock.patch.dict(
            os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:9"}
        ), mock.patch.object(bootstrap, "_install", side_effect=RuntimeError("S3NT1NEL-pw-9d2f")):
            with self.assertLogs("dispatcharr.observability.bootstrap", level="WARNING") as captured:
                bootstrap.init("mino-api", "api-uwsgi")
        self.assertIn("RuntimeError", captured.output[0])
        self.assertNotIn("S3NT1NEL", captured.output[0])

    def test_wsgi_program_follows_supervisor_and_defaults_to_api(self):
        with mock.patch.dict(os.environ, {"SUPERVISOR_PROCESS_NAME": "relay-uwsgi"}):
            self.assertEqual(bootstrap.wsgi_program(), "relay-uwsgi")
        with mock.patch.dict(os.environ, {"SUPERVISOR_PROCESS_NAME": "something-else"}):
            self.assertEqual(bootstrap.wsgi_program(), "api-uwsgi")

    def test_endpoint_for_log_drops_userinfo_path_and_query(self):
        self.assertEqual(config.endpoint_for_log({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://u:p@h:4318/x?y=z"}), "http://h:4318")
        self.assertEqual(config.endpoint_for_log({"OTEL_EXPORTER_OTLP_ENDPOINT": "not a url"}), "(unparseable)")
