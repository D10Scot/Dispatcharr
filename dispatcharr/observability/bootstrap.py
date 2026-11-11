"""Programmatic, post-fork OpenTelemetry initialisation (spec D10, D12, D13).

``init(service_name, program)`` is called once per process, after any fork,
by the hook each process kind owns (``dispatcharr/wsgi.py``,
``dispatcharr/asgi.py``, ``dispatcharr/celery.py``). It never runs
``opentelemetry-instrument`` and never reads ``OTEL_PYTHON_*`` auto
instrumentation switches.

With ``OTEL_EXPORTER_OTLP_ENDPOINT`` unset nothing is installed, no thread
starts and no connection opens.
"""
import logging
import os
import uuid

from dispatcharr.observability import config, logs

logger = logging.getLogger(__name__)

SERVICE_API = "mino-api"
SERVICE_WORKER = "mino-worker"

# pid -> True once init has reached a decision in that process. Keyed on the
# pid so that a forked child (a new pid) initialises itself.
_initialised_pid = None
_providers = {"tracer": None, "meter": None, "logger": None}


def program_from_supervisor(allowed, default):
    """The supervisord program name when it is one of ``allowed``, else ``default``."""
    name = os.environ.get("SUPERVISOR_PROCESS_NAME", "")
    return name if name in allowed else default


def wsgi_program():
    """``api-uwsgi`` or ``relay-uwsgi``: both load dispatcharr.wsgi."""
    name = program_from_supervisor(("api-uwsgi", "relay-uwsgi"), "")
    if name:
        return name
    try:
        import uwsgi  # type: ignore

        ini = uwsgi.opt.get("ini")
        if isinstance(ini, (list, tuple)):
            ini = ini[0] if ini else None
        if isinstance(ini, bytes):
            ini = ini.decode("utf-8", "replace")
        if ini and "relay" in ini:
            return "relay-uwsgi"
    except Exception:
        pass
    return "api-uwsgi"


def _merge_semconv_opt_in():
    """Make the effective ``OTEL_SEMCONV_STABILITY_OPT_IN`` contain ``http`` (D10).

    Keeps every existing token in order and appends ``http`` unless ``http``
    or ``http/dup`` is already there. ``setdefault`` would not do: an empty
    string or ``database`` would silently remove the stable
    ``http.server.request.duration`` that catalogue row M10 renames.
    """
    key = "OTEL_SEMCONV_STABILITY_OPT_IN"
    tokens = [t.strip() for t in os.environ.get(key, "").split(",")]
    tokens = [t for t in tokens if t]
    if "http" not in tokens and "http/dup" not in tokens:
        tokens.append("http")
    os.environ[key] = ",".join(tokens)


def _service_version():
    try:
        from version import __version__

        return __version__
    except Exception:
        return None


def build_resource(service_name, program):
    """One Resource for all three providers (D13).

    The standard merge: ``OTEL_RESOURCE_ATTRIBUTES`` passes through as the
    trusted operator configuration it is (R-Q18), and our four attributes win
    over a same-named key there and over ``OTEL_SERVICE_NAME``.
    """
    from opentelemetry.sdk.resources import Resource

    attributes = {
        "service.name": service_name,
        "mino.program": program,
        "service.instance.id": str(uuid.uuid4()),
    }
    version = _service_version()
    if version:
        attributes["service.version"] = version
    return Resource.create(attributes)


def _build_tracer_provider(resource):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    from dispatcharr.observability.redaction import RedactingSpanExporter

    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(root=TraceIdRatioBased(config.sampler_ratio())),
    )
    provider.add_span_processor(BatchSpanProcessor(RedactingSpanExporter(OTLPSpanExporter())))
    return provider


def _build_meter_provider(resource):
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics import AlwaysOffExemplarFilter, MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    from dispatcharr.observability.metrics import build_views
    from dispatcharr.observability.redaction import RedactingMetricExporter

    reader = PeriodicExportingMetricReader(RedactingMetricExporter(OTLPMetricExporter()))
    return MeterProvider(
        resource=resource,
        metric_readers=[reader],
        views=build_views(),
        # Exemplars are off (D9): with the default TraceBasedExemplarFilter a
        # histogram recorded inside a sampled span exports View-excluded
        # attributes in the exemplar. The argument beats OTEL_METRICS_EXEMPLAR_FILTER.
        exemplar_filter=AlwaysOffExemplarFilter(),
    )


def _build_logger_provider(resource):
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

    from dispatcharr.observability.redaction import RedactingLogExporter

    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(BatchLogRecordProcessor(RedactingLogExporter(OTLPLogExporter())))
    return provider


def _instrument():
    # In this order (D10). Imported here, after the semconv opt-in is merged.
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor

    DjangoInstrumentor().instrument()
    CeleryInstrumentor().instrument()
    PsycopgInstrumentor().instrument()
    RedisInstrumentor().instrument()
    RequestsInstrumentor().instrument()


def init(service_name, program):
    """Initialise OpenTelemetry in this process. Idempotent per pid; never raises."""
    global _initialised_pid

    logs.set_identity(service_name, program)
    pid = os.getpid()
    if _initialised_pid == pid:
        return
    _initialised_pid = pid
    # A forked child inherits its parent's module state, never its providers.
    for key in _providers:
        _providers[key] = None

    if not config.otlp_enabled():
        return

    try:
        _install(service_name, program)
    except Exception as exc:  # telemetry must never take the process down
        logger.warning("OpenTelemetry initialisation failed (%s); continuing without it", type(exc).__name__)


def _install(service_name, program):
    _merge_semconv_opt_in()

    from opentelemetry import _logs, metrics, trace
    from opentelemetry.propagate import set_global_textmap

    from dispatcharr.observability.propagation import TrustedTraceContextPropagator

    resource = build_resource(service_name, program)

    if config.signal_enabled("traces"):
        _providers["tracer"] = _build_tracer_provider(resource)
        trace.set_tracer_provider(_providers["tracer"])
    if config.signal_enabled("metrics"):
        _providers["meter"] = _build_meter_provider(resource)
        metrics.set_meter_provider(_providers["meter"])
    if config.signal_enabled("logs"):
        _providers["logger"] = _build_logger_provider(resource)
        _logs.set_logger_provider(_providers["logger"])
        from opentelemetry.instrumentation.logging.handler import LoggingHandler

        logs.install_inner_handler(
            LoggingHandler(
                level=logging.NOTSET,
                logger_provider=_providers["logger"],
                log_code_attributes=True,
            )
        )

    set_global_textmap(TrustedTraceContextPropagator())
    _instrument()

    logger.info(
        "OpenTelemetry export enabled for %s (%s) to %s",
        service_name,
        program,
        config.endpoint_for_log(),
    )


def force_flush(timeout_millis=2000):
    """Flush every provider this process installed, bounded (D10)."""
    for provider in _providers.values():
        if provider is None:
            continue
        try:
            provider.force_flush(timeout_millis)
        except Exception:
            pass
