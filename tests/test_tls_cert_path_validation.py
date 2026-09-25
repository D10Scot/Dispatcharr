"""#128: `_validate_tls_cert_paths` (`dispatcharr/settings.py`) exists to turn a
misconfigured TLS certificate path into an actionable `ImproperlyConfigured`
at Django import time. On Python 3.13 -- the production image's version,
`docker/DispatcharrBase` -- `pathlib.Path.is_file()` re-raises `EACCES` from
the underlying `os.stat()` instead of returning `False` for a file the
process cannot read (a root-owned certificate, a Kubernetes secret mounted
without group/other read). The bare `not Path(file_path).is_file()` check
lets that `PermissionError` escape uncaught, so an operator sees a raw
traceback instead of the message the function exists to produce.

A real `chmod 000` cannot reproduce this in the test container, which runs
as root and can read anything regardless of mode -- so the unreadable case is
simulated by patching `Path.is_file` directly.
"""

from unittest import mock

from django.test import SimpleTestCase

from dispatcharr.settings import _validate_tls_cert_paths
from django.core.exceptions import ImproperlyConfigured


class TlsCertPathValidationTests(SimpleTestCase):
    def test_unreadable_cert_path_raises_improperly_configured_not_permission_error(self):
        with mock.patch(
            "pathlib.Path.is_file",
            side_effect=PermissionError(13, "Permission denied"),
        ):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                _validate_tls_cert_paths(
                    [("REDIS_SSL_CA_CERT", "/certs/ca.crt")], "Redis"
                )

        message = str(ctx.exception)
        self.assertIn("REDIS_SSL_CA_CERT", message)
        self.assertIn("/certs/ca.crt", message)
        self.assertIn("Permission denied", message)

    def test_missing_cert_path_still_says_file_not_found(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            _validate_tls_cert_paths(
                [("REDIS_SSL_CA_CERT", "/certs/does-not-exist.crt")], "Redis"
            )

        message = str(ctx.exception)
        self.assertIn("REDIS_SSL_CA_CERT", message)
        self.assertIn("file not found", message)
