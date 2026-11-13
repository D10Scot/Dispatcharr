# dispatcharr/__init__.py

# The log scrubber goes in first, before Celery or anything else in the package can
# log: every process here imports this package before application code runs. The
# relative import keeps this file's product-name count unchanged.
from .log_scrub import install as _install_log_scrub

_install_log_scrub()

# For Celery: import eagerly so @shared_task binds to the configured app.
# Lazy-loading via __getattr__ left the default Celery app unconfigured in
# production (no CELERY_BROKER_URL in env), so .delay() fell back to AMQP
# localhost and failed with ConnectionRefusedError.
from .celery import app as celery_app

__all__ = ("celery_app",)
