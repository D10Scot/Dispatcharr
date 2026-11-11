"""dispatcharr/wsgi.py must not build telemetry providers in the uWSGI master.

worker_id() == 0 is the master, which only imports the app when lazy-apps is
off; providers built there would be inherited by every forked worker.
"""
import importlib
import logging
import sys
import types
from unittest import mock

from django.test import SimpleTestCase


class WsgiUwsgiMasterTests(SimpleTestCase):
    def _import_wsgi(self, worker_id):
        fake = types.ModuleType("uwsgi")
        fake.worker_id = lambda: worker_id
        import dispatcharr.wsgi as wsgi

        with mock.patch.dict(sys.modules, {"uwsgi": fake}), mock.patch(
            "dispatcharr.observability.bootstrap.init"
        ) as init, self.assertLogs("dispatcharr.wsgi", level="WARNING") as logs:
            logging.getLogger("dispatcharr.wsgi").warning("sentinel")
            importlib.reload(wsgi)
        return init, [r for r in logs.records if r.getMessage() != "sentinel"]

    def test_master_skips_init_and_warns_once(self):
        init, logs = self._import_wsgi(0)
        init.assert_not_called()
        self.assertEqual(len(logs), 1)
        self.assertIn("lazy-apps", logs[0].getMessage())

    def test_worker_initialises(self):
        init, logs = self._import_wsgi(1)
        self.assertEqual(logs, [])
        init.assert_called_once()
        self.assertEqual(init.call_args.args[0], "mino-api")
