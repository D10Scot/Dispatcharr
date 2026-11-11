"""The Python rows of the frozen metric catalogue (spec § Metric catalogue, D14).

M10 is the Django instrumentation's own ``http.server.request.duration``
renamed by a View. M11 to M14 are instruments O6 records; this module owns
their names, units, label rules and Views so the redaction boundary and the
SDK agree on one table.

Nothing here imports from ``apps.*`` (the boot trap, spec constraint 6).
"""
from dispatcharr.observability import redaction

SCOPE_NAME = "mino/worker"

M10_NAME = "mino_api_http_server_request_duration"
M11_NAME = "mino_worker_task_duration"
M12_NAME = "mino_worker_queue_depth"
M13_NAME = "mino_worker_provider_slots_in_use"
M14_NAME = "mino_worker_provider_slots_limit"

_TASK_OUTCOMES = frozenset({"SUCCESS", "FAILURE", "RETRY", "REVOKED"})
_QUEUES = frozenset({"celery", "dvr"})

# instrument name -> {attribute key: validator}. A point carrying any other
# key, or a value its validator refuses, is dropped by RedactingMetricExporter.
CATALOGUE = {
    M10_NAME: {
        "http.request.method": redaction.is_method,
        "http.route": redaction.is_route,
        "http.response.status_code": redaction._is_int,
    },
    M11_NAME: {
        "task": redaction.is_dotted,
        "outcome": lambda value: isinstance(value, str) and value in _TASK_OUTCOMES,
    },
    M12_NAME: {"queue": lambda value: isinstance(value, str) and value in _QUEUES},
    M13_NAME: {"m3u_profile_id": redaction.is_digits},
    M14_NAME: {"m3u_profile_id": redaction.is_digits},
}


def build_views():
    """One View per catalogue instrument, then a wildcard that drops the rest."""
    from opentelemetry.sdk.metrics.view import DropAggregation, View

    views = [
        View(
            instrument_name="http.server.request.duration",
            name=M10_NAME,
            attribute_keys=set(CATALOGUE[M10_NAME]),
        )
    ]
    for name in (M11_NAME, M12_NAME, M13_NAME, M14_NAME):
        views.append(View(instrument_name=name, attribute_keys=set(CATALOGUE[name])))
    views.append(View(instrument_name="*", aggregation=DropAggregation()))
    return views


def get_meter():
    """The worker meter. A no-op meter until ``init`` installs an SDK provider."""
    from opentelemetry import metrics

    return metrics.get_meter(SCOPE_NAME)


def task_duration_histogram():
    """M11: seconds per Celery task, labelled ``task`` and ``outcome`` (O6 records it)."""
    return get_meter().create_histogram(M11_NAME, unit="s", description="Celery task duration")
