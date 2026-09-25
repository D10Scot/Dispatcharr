"""StreamSerializer.read_only_fields lives in Meta, not the class body (#15).

`StreamSerializer` declared `read_only_fields = ["is_custom", "m3u_account",
"stream_hash", "stream_id", "stream_chno"]` directly in the class body, a
sibling of `class Meta`, where `ModelSerializer` never reads it.

`get_fields()` already marks a *different* set of fields (`id`, `name`,
`url`, `m3u_account`, `tvg_id`, `channel_group`) read-only, but only when
`self.instance` is an M3U-derived (non-custom) stream -- see
`apps/channels/serializers.py`. It does not cover the five system fields
here, and does not run at all for a fresh (instance-less) serializer, which
is exactly the state DRF evaluates when deciding what a POST/PATCH may set.
Custom streams (`is_custom=True`, no `m3u_account` set by the client) never
hit that instance-based branch, so the misplaced `read_only_fields` was the
only thing standing between a client and forging `is_custom`, `m3u_account`,
`stream_hash`, `stream_id` or `stream_chno` on one.
"""

from django.test import TestCase

from apps.channels.serializers import StreamSerializer
from apps.m3u.models import M3UAccount


class StreamSerializerReadOnlyFieldsTests(TestCase):
    def test_stream_system_fields_are_read_only(self):
        serializer = StreamSerializer()
        for field_name in [
            "is_custom",
            "m3u_account",
            "stream_hash",
            "stream_id",
            "stream_chno",
        ]:
            self.assertTrue(
                serializer.fields[field_name].read_only,
                f"StreamSerializer.{field_name} is not read-only",
            )

    def test_creating_a_custom_stream_still_works(self):
        """Control: a custom stream's is_custom/m3u_account/stream_hash are
        set by the set_default_m3u_account/generate_custom_stream_hash
        signal receivers (apps/channels/signals.py), never by the client, so
        moving read_only_fields into Meta must not block stream creation.

        The built-in "custom" M3UAccount is seeded by a data migration
        (apps/m3u/migrations/0003_create_custom_account.py), not created
        here -- but a TransactionTestCase elsewhere in the suite (e.g.
        apps.m3u.tests.test_sync_correctness) flushes it under --keepdb,
        since Django's flush does not replay data migrations. get_or_create
        it explicitly so this test doesn't depend on migration-seeded state
        surviving whatever ran before it (memory: keepdb hides seeded-row
        drift)."""
        M3UAccount.objects.get_or_create(
            name="custom", locked=True, defaults={"max_streams": 0, "is_active": True}
        )

        serializer = StreamSerializer(data={"name": "My Custom Stream", "url": "http://example.com/s.ts"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        stream = serializer.save()

        self.assertTrue(stream.is_custom)
        self.assertIsNotNone(stream.m3u_account)
        self.assertTrue(stream.stream_hash)
