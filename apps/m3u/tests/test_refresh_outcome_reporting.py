"""
Regression tests for M3U refresh outcome reporting (#56, #60, #70).

Bug: ``refresh_m3u_groups`` returned ``(message, None)`` both when it did NOT
run at all (group-refresh lock held by another task, or the account was
deleted/deactivated between the trigger and the group refresh) and when it
DID run and failed. ``_refresh_single_m3u_account_impl`` treated every such
``None`` the same way: it overwrote whatever specific message the failing
step had already recorded with a generic "download failed or other error"
and reported the account as errored -- so a merely-held lock, or a race with
deactivation, read exactly like a real download failure (#56), and a real
failure's HTTP-status-specific message never survived to be shown (#60).
Separately, ``sync_auto_channels`` never raises -- its own ``except`` returns
``{"status": "error", ...}`` -- and the caller rendered that into the
``last_message`` text but still wrote ``Status.SUCCESS`` and sent
``status="success"`` over the WebSocket, so a failed auto channel sync read
as a successful refresh (#70).

Fix: ``refresh_m3u_groups``'s two "did not run" returns now carry a third
tuple element, ``GROUP_REFRESH_SKIPPED``; the caller maps that to
``Status.IDLE`` with a "Refresh skipped: ..." message and sends no error
notification. A real failure's return is treated as already-recorded when
the account's current DB status is already ``ERROR`` (set by the failing
step itself, e.g. ``fetch_m3u_lines``), in which case the caller no longer
overwrites the message. The caller now tracks whether the auto channel sync
failed (either the returned ``status: "error"`` or the caller's own
``except``) and ends the refresh at ``Status.ERROR`` with an "error" WebSocket
update when it did.
"""
from unittest.mock import patch

from django.test import TransactionTestCase

from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import _refresh_single_m3u_account_impl
from core.utils import acquire_task_lock, release_task_lock


class GroupRefreshSkipReportingTests(TransactionTestCase):
    """#56: a group refresh that did NOT run -- the lock was held, or the
    account was gone -- must not be reported as a download failure."""

    def test_group_refresh_lock_contention_is_not_reported_as_a_download_failure(self):
        account = M3UAccount.objects.create(
            name="Lock Contention Account",
            server_url="http://example.com/playlist.m3u",
            is_active=True,
        )
        self.assertTrue(
            acquire_task_lock("refresh_m3u_account_groups", account.id),
            "test setup: could not hold the group-refresh lock",
        )
        try:
            with patch("apps.m3u.tasks.send_m3u_update") as mock_send:
                _refresh_single_m3u_account_impl(account.id)
        finally:
            release_task_lock("refresh_m3u_account_groups", account.id)

        account.refresh_from_db()
        self.assertEqual(account.status, M3UAccount.Status.IDLE)
        self.assertTrue(
            account.last_message.startswith("Refresh skipped"),
            f"expected a 'Refresh skipped' message, got: {account.last_message!r}",
        )
        for call in mock_send.call_args_list:
            self.assertNotEqual(
                call.kwargs.get("status"),
                "error",
                "a held group-refresh lock must not be reported as a download failure",
            )

    def test_an_account_deactivated_mid_refresh_is_not_reported_as_a_download_failure(self):
        account = M3UAccount.objects.create(
            name="Deactivated Mid Refresh Account",
            server_url="http://example.com/playlist.m3u",
            is_active=False,
        )
        # The real refresh_m3u_groups must take its "account missing or
        # inactive" branch, so the row stays inactive; only the object the
        # top-level guard sees is patched to look active, mirroring a
        # deactivation racing the refresh in flight.
        in_memory_active_copy = M3UAccount.objects.get(pk=account.pk)
        in_memory_active_copy.is_active = True

        with patch(
            "apps.m3u.tasks._get_active_m3u_account", return_value=in_memory_active_copy
        ), patch("apps.m3u.tasks.send_m3u_update") as mock_send:
            _refresh_single_m3u_account_impl(account.id)

        account.refresh_from_db()
        self.assertEqual(account.status, M3UAccount.Status.IDLE)
        self.assertTrue(
            account.last_message.startswith("Refresh skipped"),
            f"expected a 'Refresh skipped' message, got: {account.last_message!r}",
        )
        for call in mock_send.call_args_list:
            self.assertNotEqual(
                call.kwargs.get("status"),
                "error",
                "an account deactivated mid-refresh must not be reported as a download failure",
            )


class RecordedFetchFailureMessageTests(TransactionTestCase):
    """#60: a real failure's already-recorded, specific message must survive
    the caller, not be overwritten by the generic text."""

    def test_a_recorded_fetch_failure_keeps_its_specific_message(self):
        account = M3UAccount.objects.create(
            name="Specific Failure Account",
            server_url="http://x",
            is_active=True,
        )

        def _record_and_fail(account_arg, use_cache=False):
            # Mirrors what fetch_m3u_lines itself does on every failure
            # return: record the specific message on the account before
            # returning (None, False).
            error_msg = "M3U file not found (404) at URL: http://x"
            account_arg.status = M3UAccount.Status.ERROR
            account_arg.last_message = error_msg
            account_arg.save(update_fields=["status", "last_message"])
            return None, False

        with patch("apps.m3u.tasks.fetch_m3u_lines", side_effect=_record_and_fail):
            _refresh_single_m3u_account_impl(account.id)

        account.refresh_from_db()
        self.assertEqual(account.status, M3UAccount.Status.ERROR)
        self.assertIn("404", account.last_message)


class FailedAutoSyncReportingTests(TransactionTestCase):
    """#70: a failed auto channel sync must not be reported as a successful
    refresh."""

    def _setup_xc_account_with_auto_sync_group(self):
        account = M3UAccount.objects.create(
            name="Auto Sync Failure Account",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        group = ChannelGroup.objects.create(name="Sports")
        ChannelGroupM3UAccount.objects.create(
            m3u_account=account,
            channel_group=group,
            enabled=True,
            auto_channel_sync=True,
            auto_sync_channel_start=100,
            custom_properties={"xc_id": "123"},
        )
        return account, group

    @patch("apps.m3u.tasks.log_system_event")
    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.m3u.tasks.cleanup_stale_group_relationships")
    @patch("apps.m3u.tasks.cleanup_streams", return_value=0)
    @patch("apps.m3u.tasks.process_m3u_batch_direct", return_value="1 created, 0 updated")
    @patch("apps.m3u.tasks.sync_auto_channels")
    @patch("apps.m3u.tasks.refresh_m3u_groups")
    def test_a_failed_auto_sync_is_not_reported_as_success(
        self,
        mock_refresh_groups,
        mock_sync,
        _mock_process,
        _mock_cleanup_streams,
        _mock_cleanup_groups,
        mock_ws,
        _mock_log,
    ):
        account, group = self._setup_xc_account_with_auto_sync_group()
        mock_refresh_groups.return_value = ([], {"Sports": group.id})
        mock_sync.return_value = {"status": "error", "error": "boom"}
        xc_stream = {
            "name": "ESPN",
            "url": "http://example.com/espn.m3u8",
            "attributes": {"group-title": "Sports", "stream_id": "1"},
        }

        with patch("apps.m3u.tasks.collect_xc_streams", return_value=[xc_stream]):
            _refresh_single_m3u_account_impl(account.id)

        account.refresh_from_db()
        self.assertEqual(account.status, M3UAccount.Status.ERROR)
        self.assertIn("Auto-sync error: boom", account.last_message)
        # The last send_m3u_update call is the terminal write; an earlier
        # per-batch progress update (no status kwarg) is unrelated to #70.
        mock_ws.assert_called()
        self.assertEqual(mock_ws.call_args.kwargs.get("status"), "error")
