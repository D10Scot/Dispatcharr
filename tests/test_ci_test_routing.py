"""Pin the CI path-to-label routing in ``dispatcharr/test_discovery.py``.

``labels_for_changed_paths`` decides which backend test packages CI runs for a
change, and the same function backs the local pre-commit gate. It had no tests
at all until this module: every routing defect it carried was invisible to the
suite that the routing itself selects.

These tests call the function the way ``scripts/ci_backend_test_labels.py``
does -- directly, with ``base`` set to the repository root -- so they exercise
the real alias table and the real discovered labels rather than a fixture.
"""

from django.test import SimpleTestCase

from dispatcharr.test_discovery import (
    iter_test_package_labels,
    labels_for_changed_paths,
    repo_root,
)


class ChangedPathRoutingTests(SimpleTestCase):
    def setUp(self):
        self.base = repo_root()
        self.available = set(iter_test_package_labels(base=self.base))

    def _labels(self, *paths):
        return set(labels_for_changed_paths(list(paths), base=self.base))

    def test_vod_change_runs_vod_and_output_tests(self):
        """Pins: the apps/vod/ alias used to name apps.output only.

        An alias replaces prefix matching, so listing only the output app
        meant apps/vod/tests/ never ran for a VOD change -- the tests written
        for the code being edited were the ones being skipped.
        """
        self.assertIn("apps.vod.tests", self.available)
        self.assertIn("apps.output.tests", self.available)

        labels = self._labels("apps/vod/views.py")
        self.assertIn("apps.vod.tests", labels)
        self.assertIn("apps.output.tests", labels)

    def test_live_proxy_change_runs_channels_tests(self):
        """Pins: apps/proxy/live_proxy/ had no alias and matched by prefix only.

        Prefix matching selected apps.proxy.live_proxy.tests alone, skipping
        apps/channels/tests/test_ts_proxy_teardown.py -- the richest proxy
        coverage in the tree, and the only place a real ProxyServer is built.
        """
        self.assertIn("apps.proxy.live_proxy.tests", self.available)
        self.assertIn("apps.channels.tests", self.available)

        labels = self._labels("apps/proxy/live_proxy/server.py")
        self.assertIn("apps.proxy.live_proxy.tests", labels)
        self.assertIn("apps.channels.tests", labels)

    def test_unaliased_app_change_selects_only_its_own_tests(self):
        """Control: no alias means exactly one label, so the fixes stay narrow.

        Guards the opposite failure from the two above -- broadening the alias
        table until every change runs the whole suite would hide a routing
        regression just as effectively as dropping labels does.
        """
        self.assertEqual(self._labels("apps/epg/tasks.py"), {"apps.epg.tests"})

    def test_shared_path_change_still_runs_every_label(self):
        """Pins: _SHARED_PATH_PREFIXES short-circuits before the alias table.

        A change under dispatcharr/ touches the routing and settings that every
        app depends on. If that short-circuit regressed, such a change would
        select a partial label set, and the commit gate -- which reads this
        same function -- would start disagreeing with CI without saying so.
        """
        self.assertEqual(self._labels("dispatcharr/settings.py"), self.available)
