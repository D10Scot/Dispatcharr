"""Redaction at every exporter boundary (spec D9, rulings R7 and R-Q17).

Two standards live here.

1. **Allow by construction**, for everything this package creates: span names,
   span attributes, span status descriptions, span events, metric attributes
   and structured log fields. A value is exported only when its key is on an
   allowlist AND its type and shape satisfy that key's validator. There is no
   scrubbing step a value could slip past: what is not provably safe is
   dropped or replaced by a classification (a status description becomes the
   exception's type).
2. **Best effort, no stronger than stdout**, for log *bodies*: the free text
   of existing log calls. ``redact_text`` removes the pattern classes below
   and is explicitly NOT claimed to make a body safe. An exception message a
   call site interpolates into a body reaches the body as it reaches stdout
   today.

Nothing here imports from ``apps.*``.
"""
import copy
import dataclasses
import logging
import re

from opentelemetry.sdk._logs.export import LogRecordExporter, LogRecordExportResult
from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult
from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter
from opentelemetry.trace import Link, SpanKind
from opentelemetry.trace.status import Status, StatusCode

logger = logging.getLogger(__name__)

REDACTED = "[redacted]"

# ---------------------------------------------------------------------------
# Validators: value -> bool. A value that fails is dropped, never rewritten.
# ---------------------------------------------------------------------------

_HTTP_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH", "_OTHER"}
)
_ROUTE_RE = re.compile(r"^[\w/<>:^$?()\[\]{}|\\+*.,=-]{1,256}$")
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
_DOTTED_RE = re.compile(r"^[A-Za-z0-9_][\w.]{0,127}$")
_IDENT_RE = re.compile(r"^[A-Za-z_]\w{0,63}$")
_UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_UUID_RE = re.compile("^" + _UUID_PATTERN + "$")
_DIGITS_RE = re.compile(r"^\d{1,19}$")
_SQL_OR_REDIS_NAME_RE = re.compile(r"^[A-Z]{2,16}( [A-Z]{2,16})?$")
_RUN_NAME_RE = re.compile(r"^(run|apply_async)/([A-Za-z0-9_][\w.]{0,127})$")
_CODE_PATH_RE = re.compile(r"^[^\n\r]{1,512}$")
_CODE_FUNCTION_RE = re.compile(r"^[\w<>.$-]{1,128}$")
_UUID_ANYWHERE = re.compile(_UUID_PATTERN)
_FRAME_RE = re.compile(r"^[^\n\r]{1,400}:\d+ in [\w<>.$-]{1,128}$")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _fullmatch(pattern):
    return lambda value: isinstance(value, str) and pattern.fullmatch(value) is not None


def _one_of(*members):
    allowed = frozenset(members)
    return lambda value: isinstance(value, str) and value in allowed


is_method = _one_of(*_HTTP_METHODS)
is_route = _fullmatch(_ROUTE_RE)
is_scheme = _one_of("http", "https")
_is_hostname_charset = _fullmatch(_HOSTNAME_RE)


def is_hostname(value):
    # A Host header is the client's own string: a UUID-shaped one is refused
    # (the channel UUID is a capability), as the Go side refuses it under every key.
    return _is_hostname_charset(value) and _UUID_ANYWHERE.search(value) is None
is_dotted = _fullmatch(_DOTTED_RE)
is_identifier = _fullmatch(_IDENT_RE)
is_uuid = _fullmatch(_UUID_RE)
is_digits = _fullmatch(_DIGITS_RE)
is_code_path = _fullmatch(_CODE_PATH_RE)
is_code_function = _fullmatch(_CODE_FUNCTION_RE)


def is_frames(value):
    return (
        isinstance(value, (list, tuple))
        and len(value) <= 256
        and all(isinstance(item, str) and _FRAME_RE.fullmatch(item) for item in value)
    )


def _identifier_or_int(value):
    return _is_int(value) or is_identifier(value)


# Span attribute allowlist (D9). O5's recorded sample
# (tests/test_observability_django6_sample.py and its fixture) is what this
# table rests on; a key is added only with a validator of this kind. The sample
# showed the instrumentations emit no db.operation.name (the operation is the
# span name), so that spec-listed key is not here.
SPAN_ATTRIBUTE_RULES = {
    "http.request.method": is_method,
    "http.response.status_code": _is_int,
    "server.port": _is_int,
    "http.route": is_route,
    "url.scheme": is_scheme,
    "server.address": is_hostname,
    "error.type": is_dotted,
    "celery.action": is_dotted,
    "celery.state": is_dotted,
    "celery.task_name": is_dotted,
    "messaging.message.id": is_uuid,
    "db.system": is_identifier,
    "db.name": is_identifier,
    "db.redis.database_index": _identifier_or_int,
}

# Structured log fields (D9). The extras allowlist is EMPTY at O5: no
# non-test call site passes ``extra=`` to a logger, so every ``extra`` key is
# dropped until a key is given a typed rule here.
LOG_FIELD_RULES = {
    "code.file.path": is_code_path,
    "code.function.name": is_code_function,
    "code.line.number": _is_int,
    "exception.type": is_dotted,
    "mino.exception.frames": is_frames,
}
LOG_EXTRA_RULES = {}


def _clean_attributes(attributes, rules):
    if not attributes:
        return {}
    cleaned = {}
    for key, value in dict(attributes).items():
        rule = rules.get(key)
        if rule is not None and rule(value):
            cleaned[key] = value
    return cleaned


# ---------------------------------------------------------------------------
# Log bodies: best effort, no stronger than stdout (R-Q17).
# ---------------------------------------------------------------------------

_UUID_ANYWHERE_RE = re.compile(r"\b" + _UUID_PATTERN + r"\b")
# relay/control/mediasession.go: "v1." + 22-character sid + "." + 43-character MAC.
_HLS_TOKEN_RE = re.compile(r"\bv1\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}\b")
_LONG_HEX_RE = re.compile(r"\b[0-9a-fA-F]{32,}\b")


# The three patterns that used to be regexes here (an absolute URL, a
# key/value assignment, a scheme-less path) were super-linear on crafted log
# text, and this runs inline on the gevent hub. These scanners return exactly
# what those regexes returned: each reproduces the old leftmost-match semantics
# over one structural unit and visits each character a bounded number of times.
# tests/test_observability_redaction.py keeps the old expressions as the oracle.

# A URL match starts at the first ASCII letter of the run of
# scheme characters directly before "://", and runs to the next delimiter.
_SCHEME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+.-")
_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_URL_TAIL_RE = re.compile(r"[^\s\"'<>]+")


def _scrub_urls(text):
    out, pos = [], 0
    k = text.find("://")
    while k != -1:
        start = k
        while start > pos and text[start - 1] in _SCHEME_CHARS:
            start -= 1
        while start < k and text[start] not in _LETTERS:
            start += 1
        tail = _URL_TAIL_RE.match(text, k + 3) if start < k else None
        if tail is None:
            k = text.find("://", k + 1)
            continue
        out.append(text[pos:start])
        out.append(REDACTED)
        pos = tail.end()
        k = text.find("://", pos)
    out.append(text[pos:])
    return "".join(out)


# A key/value match, one maximal [\w.-] run at a time: a run whose
# text from its first word character contains a keyword, followed by the
# separator and a value, is a match; any other run cannot start one.
_RUN_RE = re.compile(r"[\w.-]+")
_WORD_RE = re.compile(r"\w")
_KEYWORD_RE = re.compile(r"(?i)password|passwd|pwd|secret|token|api[_-]?key|credential|auth")
_SEPARATOR_RE = re.compile(r"\s*[=:]\s*")
_BARE_VALUE_RE = re.compile(r"[^\s,;&]+")


def _scrub_key_values(text):
    out, pos = [], 0
    for run in _RUN_RE.finditer(text):
        a, b = run.span()
        if b <= pos:
            continue
        word = _WORD_RE.search(text, max(a, pos), b)
        if word is None or not _KEYWORD_RE.search(text, word.start(), b):
            continue
        sep = _SEPARATOR_RE.match(text, b)
        if sep is None:
            continue
        v, end = sep.end(), -1
        if v < len(text) and text[v] in "\"'":
            close = text.find(text[v], v + 1)
            if close != -1:
                end = close + 1
        if end == -1:
            bare = _BARE_VALUE_RE.match(text, v)
            if bare is None:
                continue
            end = bare.end()
        out.append(text[pos:v])
        out.append(REDACTED)
        pos = end
    out.append(text[pos:])
    return "".join(out)


# A path match, one maximal run of path characters at a time: it starts at the
# run's first "/" not preceded by [\w/:.-], needs one [A-Za-z0-9_%~-] after it,
# and always ends at the run's end.
_PATH_RUN_RE = re.compile(r"[^\s\"'<>,;)\]]+")
_PATH_NEED_RE = re.compile(r"[A-Za-z0-9_%~-]")
_PATH_BLOCK_RE = re.compile(r"[\w/:.-]")


def _scrub_paths(text):
    out, pos = [], 0
    for run in _PATH_RUN_RE.finditer(text):
        a, b = run.span()
        i = text.find("/", a, b)
        while i > 0 and _PATH_BLOCK_RE.match(text, i - 1):
            i = text.find("/", i + 1, b)
        if i == -1 or not _PATH_NEED_RE.search(text, i + 1, b):
            continue
        out.append(text[pos:i])
        out.append(REDACTED)
        pos = b
    out.append(text[pos:])
    return "".join(out)


def redact_text(text):
    """Remove the pattern classes from a log body. Best effort, not a proof."""
    if not isinstance(text, str) or not text:
        return text
    text = _scrub_urls(text)
    text = _UUID_ANYWHERE_RE.sub(REDACTED, text)
    text = _HLS_TOKEN_RE.sub(REDACTED, text)
    text = _LONG_HEX_RE.sub(REDACTED, text)
    text = _scrub_key_values(text)
    text = _scrub_paths(text)
    return text


def redact_exception(exc):
    """An exception reduced to its qualified type name; its message is never kept."""
    if exc is None:
        return None
    cls = exc if isinstance(exc, type) else type(exc)
    module = getattr(cls, "__module__", "") or ""
    qualname = getattr(cls, "__qualname__", cls.__name__)
    return qualname if module in ("", "builtins") else f"{module}.{qualname}"


# ---------------------------------------------------------------------------
# Spans
# ---------------------------------------------------------------------------


def _exception_type_of(span):
    for event in span.events or ():
        if event.name == "exception":
            value = (event.attributes or {}).get("exception.type")
            if is_dotted(value):
                return value
    return None


def _allowed_name(name, attributes):
    if not isinstance(name, str):
        return False
    method = attributes.get("http.request.method")
    if method is not None:
        if name == method:
            return True
        route = attributes.get("http.route")
        if route is not None and name == f"{method} {route}":
            return True
    if _RUN_NAME_RE.fullmatch(name):
        return True
    return _SQL_OR_REDIS_NAME_RE.fullmatch(name) is not None


def _redact_span(span):
    attributes = _clean_attributes(span.attributes, SPAN_ATTRIBUTE_RULES)

    name = span.name
    if not _allowed_name(name, attributes):
        scope = span.instrumentation_scope
        name = (scope.name if scope is not None and scope.name else None) or "unknown"

    status = span.status
    if status is not None and status.status_code is StatusCode.ERROR:
        status = Status(StatusCode.ERROR, _exception_type_of(span))
    elif status is not None:
        status = Status(status.status_code)

    events = []
    for event in span.events or ():
        if event.name != "exception":
            continue
        exception_type = (event.attributes or {}).get("exception.type")
        kept = {"exception.type": exception_type} if is_dotted(exception_type) else {}
        events.append(Event(name="exception", attributes=kept, timestamp=event.timestamp))

    links = [Link(link.context) for link in span.links or ()]

    return ReadableSpan(
        name=name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=attributes,
        events=events,
        links=links,
        kind=span.kind if isinstance(span.kind, SpanKind) else SpanKind.INTERNAL,
        instrumentation_info=None,
        status=status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class RedactingSpanExporter(SpanExporter):
    """Rebuilds every span through the allowlists before ``inner`` sees it."""

    def __init__(self, inner):
        self._inner = inner

    def export(self, spans):
        return self._inner.export([_redact_span(span) for span in spans])

    def shutdown(self):
        return self._inner.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self._inner.force_flush(timeout_millis)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

_dropped_logged = set()


def _log_dropped_once(instrument):
    if instrument in _dropped_logged:
        return
    _dropped_logged.add(instrument)
    logger.warning(
        "dropped a metric point of %s whose attributes failed validation", instrument
    )


class RedactingMetricExporter(MetricExporter):
    """Validates each point's attribute values against the catalogue (D9).

    A metric not in the catalogue is dropped whole; a point whose attribute
    key is not catalogued for its instrument, or whose value fails that key's
    validator, is dropped and the drop is logged once per instrument.
    """

    def __init__(self, inner, catalogue=None):
        self._inner = inner
        self._catalogue = catalogue
        super().__init__(
            preferred_temporality=getattr(inner, "_preferred_temporality", None),
            preferred_aggregation=getattr(inner, "_preferred_aggregation", None),
        )

    def _rules(self):
        if self._catalogue is None:
            from dispatcharr.observability.metrics import CATALOGUE

            self._catalogue = CATALOGUE
        return self._catalogue

    def _clean_metric(self, metric):
        rules = self._rules().get(metric.name)
        if rules is None:
            return None
        kept = []
        for point in metric.data.data_points:
            attributes = dict(point.attributes or {})
            if all(key in rules and rules[key](value) for key, value in attributes.items()):
                changes = {}
                if hasattr(point, "exemplars"):
                    changes["exemplars"] = ()
                kept.append(dataclasses.replace(point, **changes))
            else:
                _log_dropped_once(metric.name)
        if not kept:
            return None
        return dataclasses.replace(metric, data=dataclasses.replace(metric.data, data_points=kept))

    def export(self, metrics_data, timeout_millis=10000, **kwargs):
        resource_metrics = []
        for resource_metric in metrics_data.resource_metrics:
            scopes = []
            for scope_metric in resource_metric.scope_metrics:
                metrics = [m for m in map(self._clean_metric, scope_metric.metrics) if m is not None]
                if metrics:
                    scopes.append(dataclasses.replace(scope_metric, metrics=metrics))
            if scopes:
                resource_metrics.append(dataclasses.replace(resource_metric, scope_metrics=scopes))
        if not resource_metrics:
            return MetricExportResult.SUCCESS
        return self._inner.export(
            dataclasses.replace(metrics_data, resource_metrics=resource_metrics),
            timeout_millis,
            **kwargs,
        )

    def force_flush(self, timeout_millis=10000):
        return self._inner.force_flush(timeout_millis)

    def shutdown(self, timeout_millis=30000, **kwargs):
        return self._inner.shutdown(timeout_millis=timeout_millis, **kwargs)


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


def _redact_log_record(readable):
    record = readable.log_record
    rules = {**LOG_EXTRA_RULES, **LOG_FIELD_RULES}
    attributes = _clean_attributes(record.attributes, rules)
    body = redact_text(record.body) if isinstance(record.body, str) else None
    # event_name is cleared too: the SDK handler promotes ``otel.event.name`` to
    # it, and nothing of ours sets one.
    clean = copy.copy(record)
    clean.attributes = attributes
    clean.body = body
    clean.event_name = None
    return dataclasses.replace(readable, log_record=clean)



class RedactingLogExporter(LogRecordExporter):
    """Allowlists structured fields and scrubs (best effort) the body."""

    def __init__(self, inner):
        self._inner = inner

    def export(self, batch):
        result = self._inner.export([_redact_log_record(item) for item in batch])
        return result if result is not None else LogRecordExportResult.SUCCESS

    def shutdown(self):
        return self._inner.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self._inner.force_flush(timeout_millis)
