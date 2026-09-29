"""core 0029: OutputProfile.hls_mode and the two seeded locked HLS rows
(Phase 4a-1d, spec D12), with its reverse.

A TransactionTestCase, because a migration cannot run inside the atomic block a
TestCase wraps a test in. Each test migrates BACK first and asserts only after
its own forward migration, never on the state it found: a TransactionTestCase
earlier in the same process flushes every table at teardown, which under
--keepdb removes the seeded rows.
"""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

CORE_BEFORE = [("core", "0028_alter_streamprofile_parameters")]
CORE_AFTER = [("core", "0029_outputprofile_hls_mode")]
CHANNELS_BEFORE = [("dispatcharr_channels", "0038_add_catchup_fields")]


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _leaf_targets():
    executor = MigrationExecutor(connection)
    return executor.loader.graph.leaf_nodes()


def _columns(table):
    with connection.cursor() as cursor:
        return {c.name for c in connection.introspection.get_table_description(cursor, table)}


class OutputProfileHlsMigrationTests(TransactionTestCase):
    def tearDown(self):
        # Always leave the database at the leaf, whatever a test did.
        MigrationExecutor(connection).migrate(_leaf_targets())

    def _back(self):
        # channels 0039 depends on core 0029, so it must come off first.
        _migrate(CHANNELS_BEFORE)
        return _migrate(CORE_BEFORE)

    def test_the_core_migration_seeds_two_locked_hls_rows_and_its_reverse_removes_them(self):
        old_apps = self._back()
        OldProfile = old_apps.get_model("core", "OutputProfile")
        self.assertFalse(
            OldProfile.objects.filter(name__in=["HLS (Re-encode)", "HLS (Automatic)"]).exists(),
            "rows named HLS (...) exist after migrating back to core 0028",
        )
        self.assertNotIn("hls_mode", _columns("core_outputprofile"))

        new_apps = _migrate(CORE_AFTER)
        Profile = new_apps.get_model("core", "OutputProfile")
        rows = {
            r.name: r
            for r in Profile.objects.filter(name__in=["HLS (Re-encode)", "HLS (Automatic)"])
        }
        self.assertEqual(sorted(rows), ["HLS (Automatic)", "HLS (Re-encode)"])
        self.assertEqual(rows["HLS (Re-encode)"].hls_mode, "transcode")
        self.assertEqual(rows["HLS (Automatic)"].hls_mode, "automatic")
        for row in rows.values():
            self.assertTrue(row.locked)
            self.assertTrue(row.is_active)
            self.assertEqual(row.command, "ffmpeg")
            self.assertEqual(row.parameters, "(built by the relay)")

        self._back()
        self.assertNotIn("hls_mode", _columns("core_outputprofile"))
        self.assertFalse(
            Profile.objects.filter(name__in=["HLS (Re-encode)", "HLS (Automatic)"]).exists(),
            "rows remain after migrating back to 0028",
        )

    def test_a_pre_existing_row_with_a_seeded_name_is_renamed_not_overwritten(self):
        old_apps = self._back()
        OldProfile = old_apps.get_model("core", "OutputProfile")
        OldProfile.objects.create(
            name="HLS (Automatic)", command="ffmpeg", parameters="-i pipe:0 pipe:1"
        )

        new_apps = _migrate(CORE_AFTER)
        Profile = new_apps.get_model("core", "OutputProfile")
        custom = Profile.objects.get(name="HLS (Automatic) (custom)")
        self.assertEqual(custom.hls_mode, "")
        self.assertEqual(custom.parameters, "-i pipe:0 pipe:1")
        self.assertEqual(Profile.objects.get(name="HLS (Automatic)").hls_mode, "automatic")
