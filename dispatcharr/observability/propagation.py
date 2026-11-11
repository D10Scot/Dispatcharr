"""Trace-context propagation (spec D11).

A client must not be able to choose a trace id or force sampling. The
propagator below honours an incoming ``traceparent`` only when the carrier is
not an HTTP request environment, or when it is one and carries this
deployment's static internal header.
"""
from collections.abc import Mapping

from opentelemetry.context import Context
from opentelemetry.propagators.textmap import TextMapPropagator
from opentelemetry.trace import get_current_span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# WSGI's spelling of X-Dispatcharr-Internal (apps/proxy/internal_auth.py
# HEADER_INTERNAL). Spelt out here rather than imported: this package imports
# nothing from apps.* at module level.
_WSGI_INTERNAL_KEY = "HTTP_X_DISPATCHARR_INTERNAL"
_ASGI_INTERNAL_HEADER = b"x-dispatcharr-internal"

_W3C = TraceContextTextMapPropagator()


def _is_wsgi_environ(carrier):
    return isinstance(carrier, Mapping) and "REQUEST_METHOD" in carrier


def _is_asgi_scope(carrier):
    return (
        isinstance(carrier, Mapping)
        and carrier.get("type") in ("http", "websocket")
        and "headers" in carrier
    )


def _internal_header(carrier):
    """The ``X-Dispatcharr-Internal`` value of an HTTP request carrier, or None."""
    if _is_wsgi_environ(carrier):
        return carrier.get(_WSGI_INTERNAL_KEY)
    for name, value in carrier.get("headers") or ():
        if isinstance(name, bytes) and name.lower() == _ASGI_INTERNAL_HEADER:
            try:
                return value.decode("latin-1")
            except AttributeError:
                return None
    return None


def _internal_token_matches(value):
    from apps.proxy.internal_auth import _matches, internal_principal_token

    return _matches(value, internal_principal_token())


class TrustedTraceContextPropagator(TextMapPropagator):
    """W3C TraceContext, extracted only from trusted carriers."""

    def extract(self, carrier, context=None, getter=None):
        http_request = _is_wsgi_environ(carrier) or _is_asgi_scope(carrier)
        if http_request and not _internal_token_matches(_internal_header(carrier)):
            return context if context is not None else Context()
        if getter is None:
            return _W3C.extract(carrier, context)
        return _W3C.extract(carrier, context, getter)

    def inject(self, carrier, context=None, setter=None):
        if setter is None:
            return _W3C.inject(carrier, context)
        return _W3C.inject(carrier, context, setter)

    @property
    def fields(self):
        return _W3C.fields


def current_traceparent():
    """The W3C ``traceparent`` of the current span, or None when it is invalid.

    Always None with OTLP off: the API's non-recording span has an invalid
    context.
    """
    if not get_current_span().get_span_context().is_valid:
        return None
    carrier = {}
    _W3C.inject(carrier)
    return carrier.get("traceparent")
