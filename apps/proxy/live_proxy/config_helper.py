"""Moved to ``apps/proxy/config_helper.py`` in Phase 2 stage 2d-1.

Re-exported from here so every importer inside this package -- and
``apps/proxy/tests/test_boundary_error_arms.py`` outside it -- keeps working
until stage 2d-4 deletes the package. Nothing new should import this path.
"""

from apps.proxy.config_helper import ConfigHelper  # noqa: F401
