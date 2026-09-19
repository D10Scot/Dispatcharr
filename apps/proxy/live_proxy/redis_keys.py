"""Moved to ``apps/proxy/redis_keys.py`` in Phase 2 stage 2d-1.

Re-exported from here so every importer inside this package -- and the six
test files outside it that name this path -- keeps working until stage 2d-4
deletes the package. Nothing new should import this path.
"""

from apps.proxy.redis_keys import RedisKeys  # noqa: F401
