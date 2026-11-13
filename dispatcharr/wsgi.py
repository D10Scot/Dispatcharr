"""
WSGI config for dispatcharr project.
"""
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')

# OpenTelemetry must be initialised BEFORE get_wsgi_application(): the Django
# instrumentation works by inserting its middleware into settings.MIDDLEWARE,
# and a handler built earlier has already loaded its chain (observability spec
# D10, measured: instrumenting afterwards produced no server span at all).
#
# Every docker/uwsgi*.ini sets `lazy-apps = true` (tests/test_uwsgi_inis_are_lazy.py),
# so this module is imported in each worker after the fork. There is
# deliberately no uwsgidecorators.postfork hook: with lazy-apps off this import
# would already have built providers in the master, a worker cannot replace
# the OTel API's set-once global providers, and init() refuses (with a warning)
# to build a second set in a forked child. The lazy-apps test is the protection.
import logging as _logging

from dispatcharr.observability.bootstrap import init as _otel_init, wsgi_program


def _is_uwsgi_master():
    """True when running under uWSGI's master process (worker_id() == 0)."""
    try:
        import uwsgi

        return uwsgi.worker_id() == 0
    except Exception:
        return False


if _is_uwsgi_master():
    # The master imports this module only when lazy-apps is off; building
    # providers here would be inherited by every forked worker.
    _logging.getLogger(__name__).warning(
        "telemetry not initialised in the uWSGI master: lazy-apps must be true"
    )
else:
    _otel_init("mino-api", wsgi_program())

from django.core.wsgi import get_wsgi_application

from dispatcharr.request_body_spool import wrap as _spool_request_body

# Reads the request body before Django runs, in the API process only (the
# DISPATCHARR_WSGI_SPOOL_REQUEST_BODY gate, set by docker/uwsgi.ini and
# docker/uwsgi.modular.ini). It replaces uWSGI's post-buffering there, whose
# harakiri arithmetic killed whole workers: see dispatcharr/request_body_spool.py.
application = _spool_request_body(get_wsgi_application())
