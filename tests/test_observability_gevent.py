"""Observability spec D10 / R8: span context survives ``gevent.sleep`` per greenlet.

Under uWSGI's ``gevent-early-monkey-patch`` every request is a greenlet, and
the SDK's context lives in ``contextvars``, which gevent gives each greenlet
its own copy of. This pins that: two greenlets each open a span, yield, open a
child, and each child's parent must be its OWN greenlet's span, never the
other's. It runs the SDK and gevent only, not uWSGI.
"""
import json
import subprocess
import sys

from django.test import SimpleTestCase

from tests.otel_rig import REPO_ROOT

CHILD = r"""
import gevent.monkey
gevent.monkey.patch_all()

import json, sys
import gevent
from opentelemetry import context as otel_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

if sys.argv[1] == "break":
    class _GlobalRuntimeContext(otel_context.contextvars_context.ContextVarsRuntimeContext):
        _current = otel_context.Context()
        def attach(self, ctx):
            token = type(self)._current
            type(self)._current = ctx
            return token
        def get_current(self):
            return type(self)._current
        def detach(self, token):
            type(self)._current = token
    otel_context._RUNTIME_CONTEXT = _GlobalRuntimeContext()

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
tracer = provider.get_tracer("gevent-test")
records = []

def work(name):
    with tracer.start_as_current_span(name) as outer:
        gevent.sleep(0)
        with tracer.start_as_current_span(name + ".child") as child:
            gevent.sleep(0)
            records.append({
                "greenlet": name,
                "own_span_id": outer.get_span_context().span_id,
                "child_parent_span_id": child.parent.span_id if child.parent else None,
            })

gevent.joinall([gevent.spawn(work, "a"), gevent.spawn(work, "b")])
print(json.dumps(records))
"""


def _run(mode):
    result = subprocess.run(
        [sys.executable, "-c", CHILD, mode],
        env={"PATH": __import__("os").environ.get("PATH", ""), "HOME": "/tmp", "LANG": "C.UTF-8", "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    records = json.loads(lines[-1]) if lines else []
    return result, records


def _mismatches(records):
    return [
        r["greenlet"]
        for r in records
        if r["child_parent_span_id"] != r["own_span_id"]
    ]


class GeventContextTests(SimpleTestCase):
    def test_each_greenlets_child_span_has_its_own_greenlets_span_as_parent(self):
        result, records = _run("normal")
        self.assertEqual(len(records), 2, f"expected two records.\n{result.stdout}\n{result.stderr[-2000:]}")
        self.assertEqual(
            _mismatches(records),
            [],
            f"a child span's parent is not its own greenlet's span: {records}",
        )

    def test_the_check_detects_a_process_global_context(self):
        # Self-test of the pin: with the runtime context replaced by one
        # process-global Context, the same check must report a mismatch (or
        # lose a record), otherwise the test above proves nothing.
        result, records = _run("break")
        self.assertTrue(
            len(records) < 2 or _mismatches(records),
            f"a process-global context passed the gevent check: {records}\n{result.stderr[-2000:]}",
        )
