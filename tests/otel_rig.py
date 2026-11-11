"""Shared fixtures for the observability tests (spec O5).

``Rig`` stands up SDK providers that are NOT installed as the process globals
(the globals are set-once per process, so a test that set them would poison
every later test). Each instrumentor is handed the rig's providers directly.

Every span goes to two exporters: ``raw`` sees what the instrumentation
emitted, and ``redacted`` sees what survived ``RedactingSpanExporter``. A leak
test asserts ``raw`` holds the sentinel (the control: a call that never
carried it cannot make the test pass) and ``redacted`` does not.
"""
import os

from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import AlwaysOffExemplarFilter, MeterProvider
from opentelemetry.sdk.metrics.export import (
    MetricExporter,
    MetricExportResult,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from dispatcharr.observability.metrics import build_views
from dispatcharr.observability.redaction import (
    RedactingLogExporter,
    RedactingMetricExporter,
    RedactingSpanExporter,
)

SENTINEL = "S3NT1NEL-pw-9d2f"
SENTINEL_UUID = "5e171e10-0000-4000-8000-00000000d2f0"


def reset_semconv():
    """Make the Django/requests instrumentations read the opt-in afresh, with ``http`` in it."""
    from opentelemetry.instrumentation._semconv import _OpenTelemetrySemanticConventionStability as S

    from dispatcharr.observability.bootstrap import _merge_semconv_opt_in

    _merge_semconv_opt_in()
    S._initialized = False
    S._OTEL_SEMCONV_STABILITY_SIGNAL_MAPPING = {}


class CollectingMetricExporter(MetricExporter):
    def __init__(self):
        super().__init__()
        self.exports = []

    def export(self, metrics_data, timeout_millis=10000, **kwargs):
        self.exports.append(metrics_data)
        return MetricExportResult.SUCCESS

    def force_flush(self, timeout_millis=10000):
        return True

    def shutdown(self, timeout_millis=30000, **kwargs):
        pass

    def points(self):
        """{metric name: [attribute dict, ...]} over everything exported."""
        found = {}
        for data in self.exports:
            for rm in data.resource_metrics:
                for sm in rm.scope_metrics:
                    for metric in sm.metrics:
                        found.setdefault(metric.name, []).extend(
                            dict(p.attributes) for p in metric.data.data_points
                        )
        return found


class Rig:
    def __init__(self, catalogue=None, views=True):
        self.raw = InMemorySpanExporter()
        self.redacted = InMemorySpanExporter()
        self.tracer_provider = TracerProvider()
        self.tracer_provider.add_span_processor(SimpleSpanProcessor(self.raw))
        self.tracer_provider.add_span_processor(SimpleSpanProcessor(RedactingSpanExporter(self.redacted)))

        self.metric_sink = CollectingMetricExporter()
        self.raw_metric_sink = CollectingMetricExporter()
        self.meter_provider = MeterProvider(
            metric_readers=[
                PeriodicExportingMetricReader(
                    RedactingMetricExporter(self.metric_sink, catalogue), export_interval_millis=3_600_000
                ),
                PeriodicExportingMetricReader(self.raw_metric_sink, export_interval_millis=3_600_000),
            ],
            views=build_views() if views else [],
            exemplar_filter=AlwaysOffExemplarFilter(),
        )

        self.raw_logs = InMemoryLogRecordExporter()
        self.redacted_logs = InMemoryLogRecordExporter()
        self.logger_provider = LoggerProvider()
        self.logger_provider.add_log_record_processor(SimpleLogRecordProcessor(self.raw_logs))
        self.logger_provider.add_log_record_processor(
            SimpleLogRecordProcessor(RedactingLogExporter(self.redacted_logs))
        )
        self._instrumentors = []

    def instrument(self, *instrumentors):
        for instrumentor in instrumentors:
            instrumentor.instrument(
                tracer_provider=self.tracer_provider, meter_provider=self.meter_provider
            )
            self._instrumentors.append(instrumentor)

    def teardown(self):
        for instrumentor in reversed(self._instrumentors):
            instrumentor.uninstrument()
        self._instrumentors = []
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
        self.logger_provider.shutdown()

    def flush_metrics(self):
        self.meter_provider.force_flush()

    @staticmethod
    def dump(spans):
        """Every byte the spans would put on the wire, as one string."""
        return "\n".join(span.to_json() for span in spans)

    def raw_spans(self):
        return self.raw.get_finished_spans()

    def exported_spans(self):
        return self.redacted.get_finished_spans()

    def exported_by_name(self, name):
        return [s for s in self.exported_spans() if s.name == name]


def span_leak_fields(span, needle):
    found = []
    if needle in str(span.name):
        found.append("name")
    if any(needle in str(k) or needle in str(v) for k, v in (span.attributes or {}).items()):
        found.append("attr")
    if span.status is not None and needle in str(span.status.description or ""):
        found.append("status")
    if any(
        needle in str(e.name) or any(needle in str(v) for v in (e.attributes or {}).values())
        for e in span.events or ()
    ):
        found.append("event")
    if any(needle in str(v) for link in span.links or () for v in (link.attributes or {}).values()):
        found.append("link")
    return found


class Failures:
    """Collects assertion failures so a test reports every one, not just the first."""

    def __init__(self):
        self.items = []

    def check(self, condition, message):
        if not condition:
            self.items.append(message)

    def leak(self, haystack, needle, where):
        self.check(needle not in haystack, f"LEAK in {where}: {needle!r} reached the exporter")

    def leak_spans(self, spans, needle, where):
        """Report each span and the field (name/attr/status/event/link) that carries ``needle``."""
        for span in spans:
            fields = span_leak_fields(span, needle)
            self.check(not fields, f"LEAK in {where}, span {span.name!r}: {', '.join(fields)} carries {needle!r}")

    def raise_if_any(self, test):
        if self.items:
            test.fail("\n".join(self.items))


# --- subprocess helpers ------------------------------------------------------

import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

# What a child that imports Django settings needs from the parent, and nothing
# else: a child built by removing known-bad variables would inherit every
# OTEL_* the developer's shell happens to export.
_SETTINGS_PASSTHROUGH = (
    "POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_PORT",
    "REDIS_HOST", "REDIS_PORT", "REDIS_DB", "DJANGO_SECRET_KEY", "TEST_USE_SQLITE",
    "DISPATCHARR_ENV", "DISPATCHARR_LOG_LEVEL",
)


def child_env(extra=None, django=True):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONPATH": str(REPO_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if django:
        env["DJANGO_SETTINGS_MODULE"] = "dispatcharr.settings_test"
        for key in _SETTINGS_PASSTHROUGH:
            if key in os.environ:
                env[key] = os.environ[key]
    env.update(extra or {})
    return env


def run_child(code, env, timeout=120):
    """Run ``code`` in a fresh interpreter. Its last stdout line must be JSON."""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    payload = None
    if lines:
        try:
            payload = json.loads(lines[-1])
        except ValueError:
            payload = None
    return result, payload
