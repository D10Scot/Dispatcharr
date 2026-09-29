"""dispatcharr_channels 0039: Channel.hls_output_profile (Phase 4a-1d), with its
reverse. A TransactionTestCase for the same reason as
core/tests/test_output_profile_hls_migration.py, and it asserts only after its
own forward migration."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

CHANNELS_BEFORE = [("dispatcharr_channels", "0038_add_catchup_fields")]
CHANNELS_AFTER = [("dispatcharr_channels", "0039_channel_hls_output_profile")]


def _migrate(targets):
    MigrationExecutor(connection).migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def _columns(table):
    with connection.cursor() as cursor:
        return {c.name for c in connection.introspection.get_table_description(cursor, table)}


class ChannelHlsOutputProfileMigrationTests(TransactionTestCase):
    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_the_channels_migration_adds_and_removes_hls_output_profile(self):
        _migrate(CHANNELS_BEFORE)
        self.assertNotIn("hls_output_profile_id", _columns("dispatcharr_channels_channel"))

        apps = _migrate(CHANNELS_AFTER)
        self.assertIn("hls_output_profile_id", _columns("dispatcharr_channels_channel"))
        Channel = apps.get_model("dispatcharr_channels", "Channel")
        Profile = apps.get_model("core", "OutputProfile")
        profile = Profile.objects.create(
            name="hls-migration-test", command="ffmpeg", parameters="x", hls_mode="automatic"
        )
        channel = Channel.objects.create(
            channel_number=9901, name="hls-migration-test", hls_output_profile=profile
        )
        channel.refresh_from_db()
        self.assertEqual(channel.hls_output_profile_id, profile.id)

        # Back: the column is gone, and the channel row survives.
        _migrate(CHANNELS_BEFORE)
        self.assertNotIn("hls_output_profile_id", _columns("dispatcharr_channels_channel"))

        # Forward again: the column exists and the survivor's FK is null.
        apps = _migrate(CHANNELS_AFTER)
        self.assertIn("hls_output_profile_id", _columns("dispatcharr_channels_channel"))
        Channel = apps.get_model("dispatcharr_channels", "Channel")
        self.assertIsNone(Channel.objects.get(name="hls-migration-test").hls_output_profile_id)
