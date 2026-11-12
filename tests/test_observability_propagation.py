"""Observability spec D11: a client must not be able to choose a trace id.

``TrustedTraceContextPropagator.extract`` honours an incoming ``traceparent``
only when the carrier is not an HTTP request environment (Celery's task
headers, written only by this deployment's own producers) or carries this
deployment's static internal header.
"""
from django.test import SimpleTestCase
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import get_current_span

from dispatcharr.observability.propagation import TrustedTraceContextPropagator, current_traceparent

TRACE_ID = 0x4BF92F3577B34DA6A3CE929D0E0E4736
SPAN_ID = 0x00F067AA0BA902B7
TRACEPARENT = f"00-{TRACE_ID:032x}-{SPAN_ID:016x}-01"


def _extracted(context):
    return get_current_span(context).get_span_context()


class ExtractTrustTests(SimpleTestCase):
    def setUp(self):
        self.propagator = TrustedTraceContextPropagator()

    def _internal(self):
        from apps.proxy.internal_auth import internal_principal_token

        return internal_principal_token()

    def _assert_nothing_extracted(self, context, what):
        ctx = _extracted(context)
        self.assertFalse(
            ctx.is_valid,
            f"{what}: extracted inherited trace id {ctx.trace_id:032x} from an untrusted carrier",
        )

    def test_a_wsgi_environ_with_traceparent_and_no_internal_header_extracts_nothing(self):
        environ = {"REQUEST_METHOD": "GET", "HTTP_TRACEPARENT": TRACEPARENT}
        self._assert_nothing_extracted(self.propagator.extract(environ, getter=_wsgi_getter), "no internal header")

    def test_a_wsgi_environ_with_a_wrong_internal_header_extracts_nothing(self):
        environ = {
            "REQUEST_METHOD": "GET",
            "HTTP_TRACEPARENT": TRACEPARENT,
            "HTTP_X_DISPATCHARR_INTERNAL": "not-the-token",
        }
        self._assert_nothing_extracted(self.propagator.extract(environ, getter=_wsgi_getter), "wrong token")

    def test_a_wsgi_environ_with_the_internal_header_extracts_the_parent(self):
        environ = {
            "REQUEST_METHOD": "GET",
            "HTTP_TRACEPARENT": TRACEPARENT,
            "HTTP_X_DISPATCHARR_INTERNAL": self._internal(),
        }
        ctx = _extracted(self.propagator.extract(environ, getter=_wsgi_getter))
        self.assertEqual((ctx.trace_id, ctx.span_id), (TRACE_ID, SPAN_ID))

    def test_an_asgi_scope_follows_the_same_rule(self):
        untrusted = {"type": "http", "headers": [(b"traceparent", TRACEPARENT.encode())]}
        self._assert_nothing_extracted(self.propagator.extract(untrusted, getter=_asgi_getter), "asgi, no header")
        trusted = {
            "type": "http",
            "headers": [
                (b"traceparent", TRACEPARENT.encode()),
                (b"X-Dispatcharr-Internal", self._internal().encode()),
            ],
        }
        ctx = _extracted(self.propagator.extract(trusted, getter=_asgi_getter))
        self.assertEqual(ctx.trace_id, TRACE_ID)

    def test_a_celery_shaped_carrier_is_extracted(self):
        ctx = _extracted(self.propagator.extract({"traceparent": TRACEPARENT}))
        self.assertEqual((ctx.trace_id, ctx.span_id), (TRACE_ID, SPAN_ID))

    def test_an_untrusted_request_leaves_the_passed_context_unchanged(self):
        from opentelemetry.context import Context, set_value

        base = set_value("marker", "kept", Context())
        environ = {"REQUEST_METHOD": "GET", "HTTP_TRACEPARENT": TRACEPARENT}
        out = self.propagator.extract(environ, base, getter=_wsgi_getter)
        self.assertIs(out, base)


class InjectTests(SimpleTestCase):
    def test_inject_is_the_unchanged_w3c_inject(self):
        tracer = TracerProvider().get_tracer("t")
        carrier = {}
        with tracer.start_as_current_span("s") as span:
            TrustedTraceContextPropagator().inject(carrier)
            ctx = span.get_span_context()
        self.assertTrue(carrier["traceparent"].startswith(f"00-{ctx.trace_id:032x}-{ctx.span_id:016x}-"))

    def test_fields_name_the_w3c_headers(self):
        self.assertEqual(TrustedTraceContextPropagator().fields, {"traceparent", "tracestate"})


class CurrentTraceparentTests(SimpleTestCase):
    def test_none_without_a_valid_span(self):
        self.assertIsNone(current_traceparent())

    def test_names_the_current_span(self):
        tracer = TracerProvider().get_tracer("t")
        with tracer.start_as_current_span("s") as span:
            value = current_traceparent()
            ctx = span.get_span_context()
        self.assertTrue(value.startswith(f"00-{ctx.trace_id:032x}-{ctx.span_id:016x}-"))


class _Getter:
    def get(self, carrier, key):
        raise NotImplementedError

    def keys(self, carrier):
        raise NotImplementedError


class _WsgiGetter(_Getter):
    def get(self, carrier, key):
        value = carrier.get("HTTP_" + key.upper().replace("-", "_"))
        return [value] if value is not None else None

    def keys(self, carrier):
        return [k for k in carrier if k.startswith("HTTP_")]


class _AsgiGetter(_Getter):
    def get(self, carrier, key):
        wanted = key.lower().encode()
        values = [v.decode() for k, v in carrier["headers"] if k.lower() == wanted]
        return values or None

    def keys(self, carrier):
        return [k.decode() for k, _ in carrier["headers"]]


_wsgi_getter = _WsgiGetter()
_asgi_getter = _AsgiGetter()
