"""The environment contract (spec D12) and the log-format switch (D8).

Pure functions of a mapping (``os.environ`` by default), so tests can drive
them without touching the process environment. Nothing here imports the OTel
SDK.
"""
import logging
import os

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOL = "http/protobuf"

_PROTOCOL_VARIABLES = (
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
    "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL",
    "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL",
)

SIGNALS = ("traces", "metrics", "logs")

LOG_FORMAT_VARIABLE = "MINO_LOG_FORMAT"


def _env(environ):
    return os.environ if environ is None else environ


def otlp_enabled(environ=None):
    """Whether OTLP is on in this process (D12).

    On if and only if ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set and non-empty,
    ``OTEL_SDK_DISABLED`` is not ``true``, and no protocol variable names
    anything but ``http/protobuf``. A protocol the exporters cannot speak
    turns OTLP off with one WARNING that names the variable and the supported
    value, never the offending value.
    """
    env = _env(environ)
    if not (env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip():
        return False
    if (env.get("OTEL_SDK_DISABLED") or "").strip().lower() == "true":
        return False
    for variable in _PROTOCOL_VARIABLES:
        value = (env.get(variable) or "").strip()
        if value and value != SUPPORTED_PROTOCOL:
            logger.warning(
                "%s is not %s; OpenTelemetry export stays off in this process",
                variable,
                SUPPORTED_PROTOCOL,
            )
            return False
    return True


def signal_enabled(signal, environ=None):
    """False when ``OTEL_<SIGNAL>_EXPORTER`` is ``none``; any other value means OTLP."""
    env = _env(environ)
    value = (env.get(f"OTEL_{signal.upper()}_EXPORTER") or "").strip().lower()
    return value != "none"


def endpoint_for_log(environ=None):
    """The endpoint as ``scheme://host:port`` only: no path, userinfo or query."""
    from urllib.parse import urlsplit

    raw = (_env(environ).get("OTEL_EXPORTER_OTLP_ENDPOINT") or "").strip()
    try:
        parts = urlsplit(raw)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return "(unparseable)"
    if not parts.scheme or not host:
        return "(unparseable)"
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


def sampler_ratio(environ=None):
    """The root sampling ratio from ``OTEL_TRACES_SAMPLER_ARG`` (D11).

    A float in [0, 1]; unset gives 1.0 silently, and an unparseable or
    out-of-range value gives 1.0 with one WARNING that never repeats the value.
    ``OTEL_TRACES_SAMPLER`` is deliberately never read.
    """
    raw = _env(environ).get("OTEL_TRACES_SAMPLER_ARG")
    if raw is None or not raw.strip():
        return 1.0
    try:
        ratio = float(raw)
    except ValueError:
        ratio = None
    if ratio is None or not (0.0 <= ratio <= 1.0):  # NaN fails the comparison too
        logger.warning(
            "OTEL_TRACES_SAMPLER_ARG is not a number in [0, 1]; sampling every trace"
        )
        return 1.0
    return ratio


def log_format(environ=None):
    """``json`` or ``text`` (D8). Anything else is ``text`` with one WARNING.

    The warning names the variable and the value's length, never the value.
    """
    value = _env(environ).get(LOG_FORMAT_VARIABLE)
    if value is None or value == "" or value == "text":
        return "text"
    if value == "json":
        return "json"
    logger.warning(
        "%s is not 'text' or 'json' (value is %d characters long); using text",
        LOG_FORMAT_VARIABLE,
        len(value),
    )
    return "text"
