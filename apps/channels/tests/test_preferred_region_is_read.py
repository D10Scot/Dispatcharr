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

from apps.channels.epg_matching import (
    build_epg_tvg_id_index,
    get_preferred_region_code,
    normalize_name,
)
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

    def test_the_preferred_region_changes_which_epg_row_a_tied_channel_matches(self):
        """End-to-end: the region bonus must reach `_compute_fuzzy_score` and
        change which EPG row wins, not just reach `match_channels_to_epg`'s
        argument list. Only `build_epg_matching_catalog` and
        `apply_matched_epg_to_channels` are patched here -- `match_channels_to_epg`,
        `fuzzy_scan_epg_list` and `_compute_fuzzy_score` all run for real.

        Two synthetic EPG rows both named "BBC One" tie on plain fuzzy score
        (both normalize to "bbc one", `fuzz.ratio` 100) and differ only by a
        region suffix on `tvg_id`: `bbcone.us` (id 10, listed first) and
        `bbcone.uk` (id 11). With no region set, the scan's tie-break keeps
        whichever row it saw first (`_fuzzy_scan_core`: a later row must
        strictly beat the current best score to replace it), so both channels
        land on the `.us` row. With `preferred_region` set to "uk",
        `_compute_fuzzy_score`'s region bonus is +15 for `.uk` and -15 for
        `.us` (`apps/channels/epg_matching.py:211-224`), so the `.uk` row wins
        outright (115 vs 85) -- both comfortably clear the bulk "no ML needed"
        threshold (`FUZZY_HIGH_CONFIDENCE=90`), so this never touches the ML
        band.
        """
        us_row = {
            "id": 10,
            "tvg_id": "bbcone.us",
            "original_tvg_id": "bbcone.us",
            "name": "BBC One",
            "epg_source_id": 1,
            "epg_source_priority": 0,
            "norm_name": normalize_name("BBC One"),
        }
        uk_row = {
            "id": 11,
            "tvg_id": "bbcone.uk",
            "original_tvg_id": "bbcone.uk",
            "name": "BBC One",
            "epg_source_id": 1,
            "epg_source_priority": 0,
            "norm_name": normalize_name("BBC One"),
        }
        epg_data = [us_row, uk_row]
        tvg_id_index = build_epg_tvg_id_index(epg_data)

        channel_a = Channel.objects.create(channel_number=1, name="BBC One")
        channel_b = Channel.objects.create(channel_number=2, name="BBC One")

        with self.subTest("no preferred region: ties keep the first-seen row"):
            with patch(
                "apps.channels.tasks.build_epg_matching_catalog",
                return_value=(epg_data, tvg_id_index),
            ), patch(
                "apps.channels.tasks.apply_matched_epg_to_channels",
                return_value=[],
            ) as mock_apply:
                match_epg_channels()
            matched = mock_apply.call_args.args[0]
            won_ids = sorted({chan["epg_data_id"] for chan in matched})
            self.assertEqual(won_ids, [us_row["id"]])

        with self.subTest("preferred region uk: the .uk row wins outright"):
            self._set_preferred_region("UK")
            with patch(
                "apps.channels.tasks.build_epg_matching_catalog",
                return_value=(epg_data, tvg_id_index),
            ), patch(
                "apps.channels.tasks.apply_matched_epg_to_channels",
                return_value=[],
            ) as mock_apply:
                match_epg_channels()
            matched = mock_apply.call_args.args[0]
            won_ids = sorted({chan["epg_data_id"] for chan in matched})
            self.assertEqual(won_ids, [uk_row["id"]])
