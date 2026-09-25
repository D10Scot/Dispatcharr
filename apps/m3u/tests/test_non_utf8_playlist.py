"""Guards #217: a non-UTF-8 playlist must decode (as cp1252) instead of
raising UnicodeDecodeError, on every M3U input path -- the ZIP branch the
issue names, and the plain/.gz/.xz paths, which shared the same strict-UTF-8
bug. An unexpected exception during group refresh must still release the
task lock and stop the renewer thread, rather than holding the lock for the
life of the worker process.
"""
import gzip
import io
import lzma
import os
import tempfile
import threading
import zipfile

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from apps.m3u.models import M3UAccount
from apps.m3u.tasks import (
    _open_m3u_text_source,
    fetch_m3u_lines,
    iter_m3u_entries,
    refresh_m3u_groups,
)
from core.utils import acquire_task_lock, release_task_lock

LATIN1_CONTENT = (
    "#EXTM3U\n"
    "#EXTINF:-1,TF1 Séries HD\n"
    "http://example.com/stream1\n"
)


class ZipUploadNonUtf8Tests(SimpleTestCase):
    def test_zip_upload_with_latin1_playlist_does_not_raise(self):
        """The issue's own harness: a ZIP-packaged Latin-1 .m3u member."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("playlist.m3u", LATIN1_CONTENT.encode("latin-1"))

        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(buf.getvalue())
                path = tmp.name

            account = MagicMock()
            account.server_url = None
            account.file_path = path

            with patch("apps.m3u.tasks.send_m3u_update"):
                lines, success = fetch_m3u_lines(account)

            self.assertTrue(success)
            self.assertTrue(any("TF1 Séries HD" in line for line in lines))
        finally:
            if path and os.path.exists(path):
                os.unlink(path)


class StreamedLatin1PlaylistTests(SimpleTestCase):
    def _write(self, suffix, opener):
        path = tempfile.mktemp(suffix=suffix)
        data = LATIN1_CONTENT.encode("latin-1")
        with opener(path, "wb") as f:
            f.write(data)
        return path

    def test_latin1_playlist_parses_on_the_streamed_paths(self):
        cases = (
            (".m3u", open),
            (".m3u.gz", gzip.open),
            (".m3u.xz", lzma.open),
        )
        for suffix, opener in cases:
            with self.subTest(suffix=suffix):
                path = self._write(suffix, opener)
                try:
                    with _open_m3u_text_source(path) as f:
                        entries = list(iter_m3u_entries(f))
                    names = [entry["name"] for entry in entries]
                    self.assertIn("TF1 Séries HD", names)
                finally:
                    os.unlink(path)

    def test_valid_utf8_playlist_is_decoded_unchanged(self):
        """Control: valid UTF-8 is unaffected by the fallback handler."""
        content = "#EXTM3U\n#EXTINF:-1,Valid UTF-8 Café\nhttp://example.com/stream1\n"
        path = tempfile.mktemp(suffix=".m3u")
        with open(path, "wb") as f:
            f.write(content.encode("utf-8"))
        try:
            with _open_m3u_text_source(path) as f:
                entries = list(iter_m3u_entries(f))
            names = [entry["name"] for entry in entries]
            self.assertIn("Valid UTF-8 Café", names)
        finally:
            os.unlink(path)


class GroupRefreshLockReleaseTests(TestCase):
    def test_unexpected_exception_in_group_refresh_releases_the_lock_and_stops_the_renewer(self):
        account = M3UAccount.objects.create(
            name="Lock Release Account",
            server_url="http://example.com/playlist.m3u",
        )
        try:
            with patch(
                "apps.m3u.tasks.fetch_m3u_lines", side_effect=RuntimeError("boom"),
            ):
                with self.assertRaises(RuntimeError):
                    refresh_m3u_groups(account.id)

            self.assertTrue(
                acquire_task_lock("refresh_m3u_account_groups", account.id)
            )
            renewer_thread_name = f"lock-renew-refresh_m3u_account_groups-{account.id}"
            alive_thread_names = {t.name for t in threading.enumerate()}
            self.assertNotIn(renewer_thread_name, alive_thread_names)
        finally:
            release_task_lock("refresh_m3u_account_groups", account.id)
