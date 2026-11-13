"""The log scrubber runs upstream of the JSON formatter and the OTLP exporter (spec T9).

``redact_text`` does NOT remove ``get.php?username=<sentinel>``: it has no leading slash and
``username`` is not among its key-value keywords. So a sentinel in either sink's body can
only be absent because the scrubber removed it first.
"""
import io
import json
import logging

from opentelemetry.instrumentation.logging.handler import LoggingHandler

from dispatcharr.observability import logs
from tests.log_scrub_rig import FactoryTestCase
from tests.otel_rig import SENTINEL, Rig


class SinkTests(FactoryTestCase):
    def setUp(self):
        super().setUp()
        self.assert_scrubber_installed()  # asserts; never repairs
        self.rig = Rig()
        self.addCleanup(self.rig.teardown)
        logs.install_inner_handler(
            LoggingHandler(logger_provider=self.rig.logger_provider, log_code_attributes=True)
        )
        self.addCleanup(logs.install_inner_handler, None)
        self.log = logging.getLogger("tests.log_scrub.sinks")
        self.log.propagate = False
        self.log.setLevel(logging.DEBUG)
        self.bridge = logs.OtelBridgeHandler()
        self.stream = io.StringIO()
        self.json_handler = logging.StreamHandler(self.stream)
        self.json_handler.setFormatter(logs.JsonFormatter())
        for handler in (self.bridge, self.json_handler):
            self.log.addHandler(handler)
            self.addCleanup(self.log.removeHandler, handler)

    def test_neither_sink_receives_the_credential(self):
        self.log.info("fetched get.php?username=%s&x=1", SENTINEL)

        raw = [r.log_record for r in self.rig.raw_logs.get_finished_logs()]
        exported = [r.log_record for r in self.rig.redacted_logs.get_finished_logs()]
        self.assertEqual(len(raw), 1, "the OTLP sink did not receive the record")
        self.assertEqual(len(exported), 1)
        for record in (raw[0], exported[0]):
            self.assertIn("username=***", str(record.body))
            self.assertNotIn(SENTINEL, str(record.body), "credential reached the OTLP body")
            self.assertNotIn(SENTINEL, repr(dict(record.attributes)))

        (line,) = self.stream.getvalue().splitlines()
        payload = json.loads(line)
        self.assertIn("username=***", payload["msg"])
        self.assertNotIn(SENTINEL, line, "credential reached the JSON sink")
