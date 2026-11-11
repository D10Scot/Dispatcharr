"""Observability spec D10: every uWSGI ini that loads dispatcharr.wsgi sets ``lazy-apps = true``.

``dispatcharr/wsgi.py`` initialises OpenTelemetry at import. With lazy-apps on,
that import happens in each worker after the fork, so no exporter thread is
created in the master and inherited by a child. If an ini turned lazy-apps off,
the import-time call would silently become a pre-fork call.
"""
import re
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

DOCKER_DIR = Path(__file__).resolve().parent.parent / "docker"

_LAZY = re.compile(r"^\s*lazy-apps\s*=\s*true\b", re.MULTILINE)
_NAMES_WSGI = re.compile(r"^\s*module\s*=\s*dispatcharr\.wsgi\b", re.MULTILINE)


def non_lazy_inis(directory):
    """Every ``uwsgi*.ini`` in ``directory`` without ``lazy-apps = true``.

    All of them, not just the ones whose ``module =`` names dispatcharr.wsgi:
    uwsgi.debug.ini loads scripts.debug_wrapper, which imports dispatcharr.wsgi,
    and a new ini could load it by any route.
    """
    return [ini.name for ini in sorted(Path(directory).glob("uwsgi*.ini")) if not _LAZY.search(ini.read_text())]


class UwsgiInisAreLazyTests(SimpleTestCase):
    def test_every_ini_loading_the_wsgi_module_is_lazy(self):
        self.assertEqual(
            non_lazy_inis(DOCKER_DIR),
            [],
            "these uwsgi inis lack `lazy-apps = true`, so OpenTelemetry "
            "would initialise in the master before the fork",
        )

    def test_the_helper_finds_the_inis_it_is_meant_to_police(self):
        loaders = [
            ini.name
            for ini in DOCKER_DIR.glob("uwsgi*.ini")
            if _NAMES_WSGI.search(ini.read_text())
        ]
        self.assertGreaterEqual(len(loaders), 4, loaders)  # uwsgi, modular, relay, dev
        self.assertIn("uwsgi.relay.ini", loaders)
        self.assertIn("uwsgi.debug.ini", [p.name for p in DOCKER_DIR.glob("uwsgi*.ini")])

    def test_the_debug_ini_is_policed_though_it_loads_the_wsgi_module_through_a_wrapper(self):
        debug = (DOCKER_DIR / "uwsgi.debug.ini").read_text()
        self.assertNotIn("dispatcharr.wsgi", debug)
        self.assertIn("lazy-apps = true", debug)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "uwsgi.debug.ini").write_text(_LAZY.sub("; removed", debug))
            self.assertEqual(non_lazy_inis(tmp), ["uwsgi.debug.ini"])

    def test_the_helper_names_a_file_whose_lazy_apps_line_was_removed(self):
        relay = (DOCKER_DIR / "uwsgi.relay.ini").read_text()
        stripped = _LAZY.sub("; lazy-apps removed", relay)
        self.assertNotEqual(relay, stripped)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "uwsgi.relay.ini").write_text(stripped)
            self.assertEqual(non_lazy_inis(tmp), ["uwsgi.relay.ini"])
