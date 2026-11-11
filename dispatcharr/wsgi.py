"""
WSGI config for dispatcharr project.
"""
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')

# OpenTelemetry must be initialised BEFORE get_wsgi_application(): the Django
# instrumentation works by inserting its middleware into settings.MIDDLEWARE,
# and a handler built earlier has already loaded its chain (observability spec
# D10, measured: instrumenting afterwards produced no server span at all).
# Every uwsgi ini that loads this module sets `lazy-apps = true`
# (tests/test_uwsgi_inis_are_lazy.py), so this runs in each worker after the
# fork. The postfork hook covers a configuration that turns lazy-apps off; the
# pid guard in init() makes the two calls one.
from dispatcharr.observability.bootstrap import init as _otel_init, wsgi_program

_otel_init("mino-api", wsgi_program())

try:
    import uwsgidecorators

    @uwsgidecorators.postfork
    def _otel_postfork():
        _otel_init("mino-api", wsgi_program())
except ImportError:
    pass

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
