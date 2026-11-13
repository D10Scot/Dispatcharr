"""Observability spec D8: JSON logs on request, byte-identical text otherwise."""
import copy
import io
import json
import logging
import os
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase
from opentelemetry.sdk.trace import TracerProvider

from core.request_log_redaction import with_request_log_redaction
from dispatcharr.observability import config, logs

# A literal copy of the seed's LOGGING (dispatcharr/settings.py at 149678aa,
# before this change), with the one environment-dependent value parameterised.
# It is a new pin, not a change to an existing test.


def seed_logging(level):
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "verbose": {
                "format": "{asctime} {levelname} {name} {message}",
                "style": "{",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "verbose",
                "level": 5,
            },
        },
        "loggers": {
            "core.tasks": {"handlers": ["console"], "level": level, "propagate": False},
            "core.utils": {"handlers": ["console"], "level": level, "propagate": False},
            "apps.proxy": {"handlers": ["console"], "level": level, "propagate": False},
            "apps": {"handlers": ["console"], "level": level, "propagate": False},
            "celery": {"handlers": ["console"], "level": level, "propagate": False},
            "celery.task": {"handlers": ["console"], "level": level, "propagate": False},
            "celery.worker": {"handlers": ["console"], "level": level, "propagate": False},
            "celery.beat": {"handlers": ["console"], "level": level, "propagate": False},
            "django.geventpool": {"handlers": ["console"], "level": level, "propagate": False},
        },
        "root": {"handlers": ["console"], "level": level},
    }


def seed_plus_inert_otel_handler(level):
    expected = seed_logging(level)
    expected["handlers"]["otel"] = {
        "class": "dispatcharr.observability.logs.OtelBridgeHandler",
        "level": 5,
    }
    for entry in list(expected["loggers"].values()) + [expected["root"]]:
        entry["handlers"] = ["console", "otel"]
    return expected


class LoggingConfigTests(SimpleTestCase):
    def test_unset_gives_the_seed_dict_plus_the_inert_otel_handler(self):
        out = logs.augment_logging(seed_logging(20), {})
        self.assertEqual(out, seed_plus_inert_otel_handler(20))
        self.assertEqual(out["handlers"]["console"]["formatter"], "verbose")
        self.assertNotIn("json", out["formatters"])

    def test_the_settings_module_applies_it(self):
        if "MINO_LOG_FORMAT" in os.environ:
            self.skipTest("MINO_LOG_FORMAT is set in this environment")
        # settings.py applies the request-log credential filter after D8's
        # change (core/request_log_redaction.py); augment_logging is unchanged.
        self.assertEqual(
            settings.LOGGING,
            with_request_log_redaction(seed_plus_inert_otel_handler(settings.LOG_LEVEL)),
        )

    def test_the_input_dict_is_not_mutated(self):
        original = seed_logging(20)
        snapshot = copy.deepcopy(original)
        logs.augment_logging(original, {"MINO_LOG_FORMAT": "json"})
        self.assertEqual(original, snapshot)

    def test_json_switches_only_the_console_formatter(self):
        out = logs.augment_logging(seed_logging(20), {"MINO_LOG_FORMAT": "json"})
        self.assertEqual(out["handlers"]["console"]["formatter"], "json")
        self.assertEqual(out["formatters"]["json"], {"()": "dispatcharr.observability.logs.JsonFormatter"})
        self.assertEqual(out["formatters"]["verbose"], seed_logging(20)["formatters"]["verbose"])

    def test_explicit_text_is_the_default(self):
        self.assertEqual(
            logs.augment_logging(seed_logging(20), {"MINO_LOG_FORMAT": "text"}),
            logs.augment_logging(seed_logging(20), {}),
        )

    def test_an_unknown_value_is_text_with_one_warning_that_omits_the_value(self):
        value = "S3NT1NEL-pw-9d2f"
        with self.assertLogs("dispatcharr.observability.config", level="WARNING") as captured:
            out = logs.augment_logging(seed_logging(20), {"MINO_LOG_FORMAT": value})
        self.assertEqual(out, seed_plus_inert_otel_handler(20))
        self.assertEqual(len(captured.records), 1)
        message = captured.records[0].getMessage()
        self.assertIn("MINO_LOG_FORMAT", message)
        self.assertIn(str(len(value)), message)
        self.assertNotIn(value, message)

    def test_log_format_reads_only_the_two_values(self):
        self.assertEqual(config.log_format({}), "text")
        self.assertEqual(config.log_format({"MINO_LOG_FORMAT": ""}), "text")
        self.assertEqual(config.log_format({"MINO_LOG_FORMAT": "json"}), "json")


def _json_logger(stream):
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logs.JsonFormatter())
    log = logging.getLogger("tests.observability.jsonlogs")
    log.handlers = [handler]
    log.propagate = False
    log.setLevel(1)
    return log


class JsonFormatterTests(SimpleTestCase):
    def setUp(self):
        self.stream = io.StringIO()
        self.log = _json_logger(self.stream)
        logs.set_identity("mino-api", "api-uwsgi")
        self.addCleanup(logs.set_identity, None, None)

    def _lines(self):
        return [json.loads(line) for line in self.stream.getvalue().splitlines()]

    def test_one_json_object_per_line_with_the_schema_keys(self):
        self.log.warning("started %d clients", 3)
        self.log.log(5, "trace level")
        first, second = self._lines()
        self.assertEqual(
            set(first),
            {"time", "level", "msg", "logger", "service.name", "mino.program"},
        )
        self.assertEqual(first["level"], "WARNING")
        self.assertEqual(first["msg"], "started 3 clients")
        self.assertEqual(first["logger"], "tests.observability.jsonlogs")
        self.assertEqual(first["service.name"], "mino-api")
        self.assertEqual(first["mino.program"], "api-uwsgi")
        self.assertRegex(first["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")
        self.assertEqual(second["level"], logging.getLevelName(5))
        self.assertNotIn("trace_id", first)  # absent, never empty, without a span

    def test_trace_and_span_ids_appear_inside_a_span(self):
        tracer = TracerProvider().get_tracer("t")
        with tracer.start_as_current_span("s") as span:
            self.log.info("inside")
            ctx = span.get_span_context()
        self.log.info("outside")
        inside, outside = self._lines()
        self.assertEqual(inside["trace_id"], f"{ctx.trace_id:032x}")
        self.assertEqual(inside["span_id"], f"{ctx.span_id:016x}")
        self.assertNotIn("trace_id", outside)
        self.assertNotIn("span_id", outside)

    def test_an_exception_is_a_type_and_frames_never_a_message(self):
        secret = "S3NT1NEL-pw-9d2f"
        try:
            raise ValueError(secret)
        except ValueError:
            self.log.exception("failed")
        (line,) = self._lines()
        self.assertEqual(line["exception.type"], "ValueError")
        self.assertRegex(line["mino.exception.frames"][-1], r"test_observability_logs\.py:\d+ in test_an_exception")
        self.assertNotIn(secret, json.dumps(line))

    def test_the_body_is_scrubbed_and_extras_are_not_serialised(self):
        self.log.info("fetched http://u:pw@prov.tv/live/a/b/1.ts", extra={"secret": "S3NT1NEL-pw-9d2f"})
        (line,) = self._lines()
        self.assertNotIn("prov.tv", line["msg"])
        self.assertNotIn("secret", line)
        self.assertNotIn("S3NT1NEL-pw-9d2f", json.dumps(line))

    def test_absent_identity_is_absent_not_null(self):
        logs.set_identity(None, None)
        self.log.info("x")
        (line,) = self._lines()
        self.assertNotIn("service.name", line)
        self.assertNotIn("mino.program", line)


class OtelBridgeHandlerTests(SimpleTestCase):
    def test_it_is_a_no_op_until_a_handler_is_installed(self):
        logs.install_inner_handler(None)
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "m", (), None)
        logs.OtelBridgeHandler().emit(record)  # must not raise or start anything

    def test_it_never_forwards_the_exporters_own_transport_logs(self):
        inner = mock.Mock()
        logs.install_inner_handler(inner)
        self.addCleanup(logs.install_inner_handler, None)
        for name in ("urllib3.connectionpool", "opentelemetry.sdk.x"):
            logs.OtelBridgeHandler().emit(logging.LogRecord(name, logging.DEBUG, __file__, 1, "m", (), None))
        inner.emit.assert_not_called()
        logs.OtelBridgeHandler().emit(logging.LogRecord("apps.x", logging.INFO, __file__, 1, "m", (), None))
        inner.emit.assert_called_once()
