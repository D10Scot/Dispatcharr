"""Observability spec D10: ``dispatcharr/wsgi.py`` initialises OpenTelemetry before the handler is built.

The Django instrumentation works by inserting its middleware into
``settings.MIDDLEWARE``; a handler built earlier has already loaded its chain
and never runs it. This imports the REAL ``dispatcharr.wsgi`` in a cold
interpreter (nothing instrumented beforehand), calls ``application`` with a
WSGI environ and decodes what a stdlib OTLP receiver captured.

Measured at the spec: instrumenting after ``get_wsgi_application()`` produced no
server span at all.
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from django.test import SimpleTestCase
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.trace.v1.trace_pb2 import Span

from tests.otel_rig import child_env, run_child

CHILD = """
import json, sys
from wsgiref.util import setup_testing_defaults
import dispatcharr.wsgi as w
from opentelemetry import trace, metrics

environ = {}
setup_testing_defaults(environ)
environ.update({"REQUEST_METHOD": "GET", "PATH_INFO": "/api/no/such/path", "SERVER_NAME": "localhost"})
status = []
body = b"".join(w.application(environ, lambda s, h, exc=None: status.append(s)))
trace.get_tracer_provider().force_flush()
metrics.get_meter_provider().force_flush()
print(json.dumps({"status": status[0] if status else None}))
"""


class _Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.server.captured.append((self.path, self.rfile.read(length)))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


class WsgiColdImportTests(SimpleTestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Receiver)
        self.server.captured = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()

    def _run(self, extra_env=None):
        env = {"OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{self.server.server_address[1]}"}
        env.update(extra_env or {})
        result, payload = run_child(CHILD, child_env(env))
        self.assertIsNotNone(payload, f"child failed:\n{result.stdout}\n{result.stderr[-3000:]}")
        return payload

    def _decoded(self):
        spans, points, service_names = [], [], set()
        for path, body in self.server.captured:
            if path == "/v1/traces":
                request = ExportTraceServiceRequest.FromString(body)
                for rs in request.resource_spans:
                    service_names |= {
                        a.value.string_value for a in rs.resource.attributes if a.key == "service.name"
                    }
                    for ss in rs.scope_spans:
                        spans.extend(ss.spans)
            elif path == "/v1/metrics":
                request = ExportMetricsServiceRequest.FromString(body)
                for rm in request.resource_metrics:
                    for sm in rm.scope_metrics:
                        for metric in sm.metrics:
                            # cumulative: a later export repeats the same point, so
                            # record the request count each carries, not the number of exports
                            points.extend((metric.name, dp.count) for dp in metric.histogram.data_points)
        return spans, points, service_names

    def _assert_one_request_exported(self):
        spans, points, service_names = self._decoded()
        server_spans = [s for s in spans if s.kind == Span.SPAN_KIND_SERVER]
        self.assertEqual(len(server_spans), 1, f"no server span recorded; got {[s.name for s in spans]}")
        counts = {count for name, count in points if name == "mino_api_http_server_request_duration"}
        self.assertEqual(counts, {1}, f"no mino_api_http_server_request_duration point for one request; got {points}")
        self.assertIn("mino-api", service_names)

    def test_init_precedes_the_handler(self):
        self._run()
        self._assert_one_request_exported()

    def test_an_empty_semconv_opt_in_still_yields_the_stable_duration(self):
        self._run({"OTEL_SEMCONV_STABILITY_OPT_IN": ""})
        self._assert_one_request_exported()

    def test_a_database_only_opt_in_is_merged_with_http(self):
        self._run({"OTEL_SEMCONV_STABILITY_OPT_IN": "database"})
        self._assert_one_request_exported()
