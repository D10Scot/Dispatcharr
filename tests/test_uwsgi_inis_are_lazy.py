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
    """The ``uwsgi*.ini`` files in ``directory`` that load dispatcharr.wsgi without lazy-apps."""
    offenders = []
    for ini in sorted(Path(directory).glob("uwsgi*.ini")):
        text = ini.read_text()
        if _NAMES_WSGI.search(text) and not _LAZY.search(text):
            offenders.append(ini.name)
    return offenders


class UwsgiInisAreLazyTests(SimpleTestCase):
    def test_every_ini_loading_the_wsgi_module_is_lazy(self):
        self.assertEqual(
            non_lazy_inis(DOCKER_DIR),
            [],
            "these uwsgi inis load dispatcharr.wsgi without `lazy-apps = true`, so OpenTelemetry "
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

    def test_the_helper_names_a_file_whose_lazy_apps_line_was_removed(self):
        relay = (DOCKER_DIR / "uwsgi.relay.ini").read_text()
        stripped = _LAZY.sub("; lazy-apps removed", relay)
        self.assertNotEqual(relay, stripped)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "uwsgi.relay.ini").write_text(stripped)
            self.assertEqual(non_lazy_inis(tmp), ["uwsgi.relay.ini"])
