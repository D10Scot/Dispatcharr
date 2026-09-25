"""#128: `_validate_tls_cert_paths` (`dispatcharr/settings.py`) exists to turn a
misconfigured TLS certificate path into an actionable `ImproperlyConfigured`
at Django import time. `pathlib.Path.is_file()` re-raises `EACCES` from the
underlying `os.stat()`, as `PermissionError`, instead of returning `False`
when a *parent directory* is not traversable (a root-owned certificate
directory, or a Kubernetes secret mounted with a directory mode that denies
traverse -- the `e2e/COVERAGE.md`-documented `mktemp -d` 0700 case) --
not for a merely-unreadable *file* in an otherwise-traversable directory,
which still reports `is_file() == True` and is unaffected by this fix. The
bare `not Path(file_path).is_file()` check let that `PermissionError` escape
uncaught, so an operator saw a raw traceback instead of the message the
function exists to produce.

This is not specific to Python 3.13 (3.12's `pathlib` swallows the same
narrow set of errors and re-raises the rest identically); 3.13 is simply the
production interpreter (`docker/DispatcharrBase`, `requires-python >=3.13`).
This test patches `pathlib.Path.is_file` directly rather than relying on
interpreter behaviour, so it is interpreter-independent.

A real `chmod 000` cannot reproduce this in the test container, which runs
as root and can read anything regardless of mode -- so the untraversable-
directory case is simulated by patching `Path.is_file` directly.
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
