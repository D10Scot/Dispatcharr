"""Observability spec O6 / D11: the authorize hop returns its trace context.

nginx runs ``auth_request`` before the relay sees the request, so the relay can
only be a child of the authorize span if the 200 carries that span's context.
The header is set on the 200 only, and only when the current span is valid
(never with OTLP off).
"""
import re
import uuid
from unittest.mock import patch

import requests
from django.test import Client, TestCase
from opentelemetry import trace
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.trace import SpanKind

from apps.channels.models import Channel
from apps.proxy import relay_client
from apps.proxy.internal_auth import HEADER_RELAY_TRACEPARENT
from tests.otel_rig import SENTINEL_UUID, Rig, reset_semconv

TRACEPARENT_SHAPE = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-0[0-3]$")


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.channel = Channel.objects.create(name="o6-trace", channel_number=9601)
        cls.hidden = Channel.objects.create(name="o6-hidden", channel_number=9602, hidden_from_output=True)

    def _authorize(self, uri):
        return Client().get("/_dispatcharr/authorize", HTTP_X_ORIGINAL_URI=uri)


class AuthorizeTraceparentTests(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        reset_semconv()
        cls.rig = Rig(views=False)
        cls.rig.instrument(DjangoInstrumentor())

    @classmethod
    def tearDownClass(cls):
        cls.rig.teardown()
        super().tearDownClass()

    def setUp(self):
        self.rig.raw.clear()

    def test_the_200_names_the_exported_django_server_span(self):
        response = self._authorize(f"/proxy/ts/stream/{self.channel.uuid}")
        self.assertEqual(response.status_code, 200)
        header = response[HEADER_RELAY_TRACEPARENT]
        self.assertRegex(header, TRACEPARENT_SHAPE)
        servers = [s for s in self.rig.raw_spans() if s.kind is SpanKind.SERVER]
        self.assertEqual(len(servers), 1, "one server span per request")
        ctx = servers[0].get_span_context()
        self.assertEqual(header.split("-")[1:3], [f"{ctx.trace_id:032x}", f"{ctx.span_id:016x}"])
        # The relay's ParentBased sampler keys on this byte: it must be the span's own flags,
        # with the sampled bit set, and one the relay's propagator accepts (version 00: 0 to 3).
        flags = int(header.split("-")[3], 16)
        self.assertEqual(flags, int(servers[0].get_span_context().trace_flags))
        self.assertTrue(flags & 1, "the sampled bit is not set")

    def test_the_header_carries_a_traceparent_and_nothing_of_the_request(self):
        header = self._authorize(f"/proxy/ts/stream/{self.channel.uuid}")[HEADER_RELAY_TRACEPARENT]
        self.assertNotIn(str(self.channel.uuid), header)
        self.assertRegex(header, TRACEPARENT_SHAPE)

    def test_a_403_never_carries_it(self):
        response = self._authorize(f"/proxy/ts/stream/{self.hidden.uuid}")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(HEADER_RELAY_TRACEPARENT, response)

    def test_an_unknown_channel_403_never_carries_it(self):
        response = self._authorize(f"/proxy/ts/stream/{SENTINEL_UUID}")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(HEADER_RELAY_TRACEPARENT, response)


class AuthorizeWithoutSdkTests(_Base):
    def test_with_no_sdk_provider_the_header_is_absent(self):
        self.assertFalse(trace.get_current_span().get_span_context().is_valid)
        response = self._authorize(f"/proxy/ts/stream/{self.channel.uuid}")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(HEADER_RELAY_TRACEPARENT, response)


class SwitchChainDjangoHalfTests(TestCase):
    """D11 test 5: an admin request's outbound ``advance`` carries the client span's context."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        reset_semconv()
        cls.rig = Rig(views=False)
        cls.rig.instrument(RequestsInstrumentor())

    @classmethod
    def tearDownClass(cls):
        cls.rig.teardown()
        super().tearDownClass()

    def _advance_under_server_span(self):
        captured = {}

        def fake_send(adapter, request, **kwargs):
            captured["headers"] = dict(request.headers)
            response = requests.Response()
            response.status_code = 200
            response._content = b"{}"
            response.request = request
            return response

        tracer = self.rig.tracer_provider.get_tracer("test")
        self.rig.raw.clear()
        with tracer.start_as_current_span("admin", kind=SpanKind.SERVER) as server:
            with patch("requests.adapters.HTTPAdapter.send", fake_send):
                try:
                    relay_client.advance(str(uuid.uuid4()), url="http://provider.invalid/x")
                except Exception:
                    pass
        return captured, server

    def test_the_outbound_traceparent_names_the_requests_client_span_whose_parent_is_the_server_span(self):
        captured, server = self._advance_under_server_span()
        header = captured.get("headers", {}).get("traceparent")
        self.assertIsNotNone(header, "the outbound request carried no traceparent")
        clients = [s for s in self.rig.raw_spans() if s.kind is SpanKind.CLIENT]
        self.assertEqual(len(clients), 1)
        client_ctx = clients[0].get_span_context()
        self.assertEqual(header.split("-")[1:3], [f"{client_ctx.trace_id:032x}", f"{client_ctx.span_id:016x}"])
        self.assertEqual(clients[0].parent.span_id, server.get_span_context().span_id)

    def test_the_outbound_traceparent_carries_no_channel_identifier(self):
        captured, _ = self._advance_under_server_span()
        for name, value in captured["headers"].items():
            if name.lower() in ("traceparent", "tracestate", "baggage"):
                self.assertNotRegex(value, r"[0-9a-f]{8}-[0-9a-f]{4}-", f"{name} carries a UUID")
