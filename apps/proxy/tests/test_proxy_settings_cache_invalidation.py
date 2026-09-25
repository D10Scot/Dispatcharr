"""Issue #232: saving proxy_settings must clear the copy every reader sees,
regardless of which BaseConfig subclass reached get_proxy_settings() first.

ROOT CAUSE. BaseConfig.get_proxy_settings() is a classmethod that writes
`cls._proxy_settings_cache = settings`. Reached as TSConfig.get_proxy_
settings() -- which is how every real caller reaches it, through
TSConfig's own getters (config_helper.py) -- that assignment CREATES a
TSConfig attribute that shadows BaseConfig's. CoreSettings.invalidate_
group_cache() calls BaseConfig.clear_proxy_settings_cache(), which resets
only BaseConfig's copy, so a save through the settings API never clears
the TSConfig-shadowed one a reader is actually using.

connection.close() PATCHED. get_proxy_settings()'s `finally` always closes
the DB connection (apps/proxy/config.py), which is correct in a real
uWSGI worker (avoid holding a connection across the hot path) but poisons
a TestCase's wrapping transaction here ("the connection is closed" on the
next ORM call in the same test). Every test below patches
apps.proxy.config.connection so the close is a no-op instead of skipping
this module's coverage of the bug it was written to catch.
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from apps.proxy.config import BaseConfig, TSConfig
from core.models import CoreSettings, PROXY_SETTINGS_KEY


class ProxySettingsCacheInvalidationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.addCleanup(BaseConfig.clear_proxy_settings_cache)
        self.row, _ = CoreSettings.objects.get_or_create(
            key=PROXY_SETTINGS_KEY, defaults={"name": "Proxy Settings", "value": {}}
        )

    def _save_buffering_speed(self, value):
        self.row.refresh_from_db()
        stored = dict(self.row.value) if isinstance(self.row.value, dict) else {}
        stored["buffering_speed"] = value
        self.row.value = stored
        self.row.save()
        CoreSettings.invalidate_group_cache(PROXY_SETTINGS_KEY)

    @patch("apps.proxy.config.connection")
    def test_saving_proxy_settings_clears_the_copy_tsconfig_reads(self, _connection):
        self._save_buffering_speed(0.5)
        first = TSConfig.get_proxy_settings()["buffering_speed"]
        self.assertEqual(first, 0.5)

        self._save_buffering_speed(9.0)
        second = TSConfig.get_proxy_settings()["buffering_speed"]
        self.assertEqual(
            second,
            9.0,
            "TSConfig.get_proxy_settings() still returned the pre-save value "
            "after CoreSettings.invalidate_group_cache() ran, meaning the "
            "save-time clear reached a different cache copy than the one "
            "TSConfig reads (#232).",
        )

    @patch("apps.proxy.config.connection")
    def test_invalidate_group_cache_clears_a_copy_read_through_any_subclass(
        self, _connection
    ):
        class _AnotherConfig(BaseConfig):
            """A hypothetical future BaseConfig subclass, defined locally
            so this test pins the general shape of #232 -- `cls.` writing
            through ANY subclass shadows BaseConfig's copy -- not just
            TSConfig's specific instance of it."""

        self._save_buffering_speed(1.5)
        first = _AnotherConfig.get_proxy_settings()["buffering_speed"]
        self.assertEqual(first, 1.5)

        self._save_buffering_speed(4.5)
        second = _AnotherConfig.get_proxy_settings()["buffering_speed"]
        self.assertEqual(
            second,
            4.5,
            "A second BaseConfig subclass still read the pre-save value: "
            "the cache is not truly process-local-per-BaseConfig unless "
            "every read and write names BaseConfig explicitly.",
        )
