"""Logging (spec D8): the JSON formatter, the inert OTel bridge and the LOGGING switch.

``settings.py`` imports this module while Django is still loading its
settings, so it must start nothing and import nothing from ``apps.*`` or the
OTel SDK.
"""
import copy
import json
import logging
import traceback
from datetime import datetime, timezone

from dispatcharr.observability import config

# Set by bootstrap.init(); None until a process has said what it is.
_identity = {"service.name": None, "mino.program": None}

# The OpenTelemetry LoggingHandler once init has installed a LoggerProvider.
_inner_handler = None


def set_identity(service_name, program):
    _identity["service.name"] = service_name
    _identity["mino.program"] = program


def get_identity():
    return dict(_identity)


def install_inner_handler(handler):
    global _inner_handler
    _inner_handler = handler


def _exception_type(exc_type):
    from dispatcharr.observability.redaction import redact_exception

    return redact_exception(exc_type)


def _frames(tb):
    return [
        f"{frame.filename}:{frame.lineno} in {frame.name}"
        for frame in traceback.extract_tb(tb, limit=None)
    ]


def _current_span_ids():
    try:
        from opentelemetry.trace import get_current_span

        context = get_current_span().get_span_context()
    except Exception:
        return None, None
    if not context.is_valid:
        return None, None
    return format(context.trace_id, "032x"), format(context.span_id, "016x")


class JsonFormatter(logging.Formatter):
    """One JSON object per line with the keys of the spec's Log record schema."""

    def format(self, record):
        payload = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
            "level": record.levelname,
        }
        from dispatcharr.observability.redaction import redact_text

        payload["msg"] = redact_text(record.getMessage())
        payload["logger"] = record.name
        for key, value in _identity.items():
            if value:
                payload[key] = value
        trace_id, span_id = _current_span_ids()
        if trace_id:
            payload["trace_id"] = trace_id
            payload["span_id"] = span_id
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception.type"] = _exception_type(record.exc_info[0])
            payload["mino.exception.frames"] = _frames(record.exc_info[2])
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class OtelBridgeHandler(logging.Handler):
    """Forwards to the OpenTelemetry LoggingHandler once one is installed.

    Until D10's post-fork ``init`` has installed a LoggerProvider this is a
    no-op, which is what makes it safe to name in ``LOGGING`` at settings
    import, in the Celery parent and in a uWSGI master.
    """

    def emit(self, record):
        inner = _inner_handler
        if inner is None:
            return
        # Never log the exporter's own transport: that is a feedback loop.
        if record.name.startswith(("opentelemetry", "urllib3")):
            return
        try:
            inner.emit(self._structured_copy(record))
        except Exception:
            self.handleError(record)

    @staticmethod
    def _structured_copy(record):
        """A copy whose exception is a type and a frame list, never a message.

        The SDK handler would otherwise attach ``exception.message`` and the
        formatted traceback (source text and exception text) to the record.
        """
        clone = copy.copy(record)
        exc_info = record.exc_info
        clone.exc_info = None
        clone.exc_text = None
        clone.stack_info = None
        if exc_info and exc_info[0] is not None:
            setattr(clone, "exception.type", _exception_type(exc_info[0]))
            setattr(clone, "mino.exception.frames", _frames(exc_info[2]))
        return clone


def augment_logging(logging_config, environ=None):
    """Return ``logging_config`` with D8's changes applied.

    With ``MINO_LOG_FORMAT`` unset the only change is the inert ``otel``
    handler, added to every logger (and the root) that has ``console``. With
    ``json`` the ``console`` handler also takes the JSON formatter.
    """
    cfg = copy.deepcopy(logging_config)
    handlers = cfg.setdefault("handlers", {})
    handlers["otel"] = {
        "class": "dispatcharr.observability.logs.OtelBridgeHandler",
        "level": 5,
    }
    for entry in list(cfg.get("loggers", {}).values()) + [cfg.get("root", {})]:
        names = entry.get("handlers")
        if names and "console" in names and "otel" not in names:
            entry["handlers"] = [*names, "otel"]
    if config.log_format(environ) == "json":
        cfg.setdefault("formatters", {})["json"] = {
            "()": "dispatcharr.observability.logs.JsonFormatter"
        }
        handlers["console"]["formatter"] = "json"
    return cfg
