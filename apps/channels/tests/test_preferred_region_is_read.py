"""Tests for #140: EPG regional weighting is permanently inert.

`get_preferred_region_code()` (`apps/channels/epg_matching.py`) used to read a
flat `CoreSettings` row keyed `"preferred-region"`. `core/migrations/0020`
deleted that row, so the lookup always raised `CoreSettings.DoesNotExist` and
the helper always returned `None` -- even when an operator had chosen a
region through the UI, which lives in `system_settings.preferred_region`
(`CoreSettings.get_preferred_region()`, `core/models.py:581-582`). The two
bulk EPG matching tasks (`apps/channels/tasks.py`) carried the same dead
inline lookup rather than calling the helper.
"""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase

from apps.channels.epg_matching import get_preferred_region_code
from apps.channels.models import Channel
from apps.channels.tasks import match_epg_channels, match_selected_channels_epg
from core.models import CoreSettings, SYSTEM_SETTINGS_KEY


class PreferredRegionSettingsMixin:
    def setUp(self):
        cache.clear()
        CoreSettings.objects.filter(key=SYSTEM_SETTINGS_KEY).delete()

    def tearDown(self):
        cache.clear()

    def _set_preferred_region(self, value):
        CoreSettings.objects.create(
            key=SYSTEM_SETTINGS_KEY,
            name="System Settings",
            value={"preferred_region": value},
        )


class PreferredRegionHelperTests(PreferredRegionSettingsMixin, TestCase):
    def test_preferred_region_helper_reads_system_settings(self):
        self._set_preferred_region("UK")
        self.assertEqual(get_preferred_region_code(), "uk")

    def test_a_non_string_preferred_region_is_ignored(self):
        self._set_preferred_region(5)
        self.assertIsNone(get_preferred_region_code())

    def test_no_preferred_region_means_no_bonus(self):
        # Control: no system_settings row at all (setUp deleted it).
        self.assertIsNone(get_preferred_region_code())


class BulkEpgMatchingRegionTests(PreferredRegionSettingsMixin, TestCase):
    """`match_epg_channels` and `match_selected_channels_epg` pass
    `region_code` positionally as the third argument to
    `match_channels_to_epg` (`apps/channels/tasks.py:232-330`, `:336-440`).
    Both functions are patched, along with `build_epg_matching_catalog` and
    `apply_matched_epg_to_channels`, which are the only other calls each task
    makes into `apps.channels.epg_matching` -- confirmed by reading both
    function bodies line by line. Patching all three lets each task run to
    completion (including its `finally: cleanup_after_matching()`) without
    touching the ML matching pipeline or the database rows it would
    otherwise write.
    """

    def test_bulk_epg_matching_passes_the_preferred_region(self):
        self._set_preferred_region("UK")
        channel = Channel.objects.create(channel_number=1, name="Test Channel")

        with self.subTest("match_epg_channels"):
            with patch(
                "apps.channels.tasks.build_epg_matching_catalog",
                return_value=([], {}),
            ), patch(
                "apps.channels.tasks.match_channels_to_epg",
                return_value={
                    "channels_to_update": [],
                    "matched_channels": [],
                    "unchanged_channels": [],
                },
            ) as mock_match, patch(
                "apps.channels.tasks.apply_matched_epg_to_channels",
                return_value=[],
            ):
                match_epg_channels()
            self.assertEqual(mock_match.call_args.args[2], "uk")

        with self.subTest("match_selected_channels_epg"):
            with patch(
                "apps.channels.tasks.build_epg_matching_catalog",
                return_value=([], {}),
            ), patch(
                "apps.channels.tasks.match_channels_to_epg",
                return_value={
                    "channels_to_update": [],
                    "matched_channels": [],
                    "unchanged_channels": [],
                },
            ) as mock_match, patch(
                "apps.channels.tasks.apply_matched_epg_to_channels",
                return_value=[],
            ):
                match_selected_channels_epg([channel.id])
            self.assertEqual(mock_match.call_args.args[2], "uk")
