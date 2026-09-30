"""Replacing an M3U account's uploaded playlist file (#556).

``M3UAccountViewSet.update()`` writes the new upload first and then removes
the account's previous file. The stored path depends only on the uploaded
basename, so a re-upload under the current file's name is the same path, and
removing "the previous file" deleted the file just written: the account was
saved pointing at nothing.
"""
import os
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from apps.m3u.models import M3UAccount
from core.utils import safe_upload_path

User = get_user_model()

OLD_BODY = b"#EXTM3U\n#EXTINF:-1,Old\nhttp://example.invalid/old.ts\n"
NEW_BODY = b"#EXTM3U\n#EXTINF:-1,New\nhttp://example.invalid/new.ts\n"


class M3UFileReuploadTests(TestCase):
    def setUp(self):
        # Resolved, so the paths below compare equal to safe_upload_path's.
        self.upload_dir = os.path.realpath(tempfile.mkdtemp(prefix="m3u-reupload-"))
        self.addCleanup(shutil.rmtree, self.upload_dir, ignore_errors=True)

        # update() hardcodes /data/uploads/m3us in two places. Redirect the
        # path it computes into the temp dir, and make its makedirs() a no-op
        # (the temp dir exists). `apps.m3u.api_views.os` is the os module
        # itself, so the second patch is process-wide for the test's length.
        def _into_tmp(name, _base_dir):
            return safe_upload_path(name, self.upload_dir)

        for target, kwargs in (
            ("apps.m3u.api_views.safe_upload_path", {"side_effect": _into_tmp}),
            ("apps.m3u.api_views.os.makedirs", {}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

        admin = User.objects.create_user(username="m3u_reupload_admin", password="x")
        admin.user_level = 10
        admin.save()
        self.client = APIClient()
        self.client.force_authenticate(user=admin)

    def _account_with_file(self, stored_path):
        with open(os.path.join(self.upload_dir, "playlist.m3u"), "wb") as fh:
            fh.write(OLD_BODY)
        with patch("apps.m3u.signals.refresh_m3u_groups"):
            return M3UAccount.objects.create(name="Uploaded", file_path=stored_path)

    def _upload(self, account, filename):
        return self.client.patch(
            f"/api/m3u/accounts/{account.id}/",
            {"file": SimpleUploadedFile(filename, NEW_BODY)},
            format="multipart",
        )

    def _assert_new_file_kept(self, account, expected_path):
        account.refresh_from_db()
        self.assertEqual(account.file_path, expected_path)
        self.assertTrue(
            os.path.exists(expected_path),
            f"the upload was written to {expected_path} and then deleted by the "
            "old-file cleanup, which removed the same path",
        )
        with open(expected_path, "rb") as fh:
            self.assertEqual(fh.read(), NEW_BODY)

    def test_reupload_under_the_same_name_keeps_the_new_file(self):
        path = os.path.join(self.upload_dir, "playlist.m3u")
        account = self._account_with_file(path)

        response = self._upload(account, "playlist.m3u")

        self.assertEqual(response.status_code, 200, response.content)
        self._assert_new_file_kept(account, path)

    def test_reupload_through_a_symlinked_spelling_of_the_same_path_keeps_the_new_file(self):
        # The stored path and the freshly computed one can spell one file
        # differently (safe_upload_path resolves symlinks; a stored path may
        # not be resolved). Comparing the strings would miss that.
        alias = os.path.join(tempfile.mkdtemp(prefix="m3u-alias-"), "uploads")
        self.addCleanup(shutil.rmtree, os.path.dirname(alias), ignore_errors=True)
        os.symlink(self.upload_dir, alias)
        account = self._account_with_file(os.path.join(alias, "playlist.m3u"))

        response = self._upload(account, "playlist.m3u")

        self.assertEqual(response.status_code, 200, response.content)
        self._assert_new_file_kept(account, os.path.join(self.upload_dir, "playlist.m3u"))

    def test_reupload_under_a_new_name_removes_the_previous_file(self):
        old_path = os.path.join(self.upload_dir, "playlist.m3u")
        account = self._account_with_file(old_path)

        response = self._upload(account, "playlist-v2.m3u")

        self.assertEqual(response.status_code, 200, response.content)
        self._assert_new_file_kept(account, os.path.join(self.upload_dir, "playlist-v2.m3u"))
        self.assertFalse(
            os.path.exists(old_path),
            "a re-upload under a new name must still remove the previous file",
        )
