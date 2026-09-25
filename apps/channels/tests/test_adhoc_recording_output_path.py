"""Tests for #135: an ad-hoc recording loses its channel subdirectory.

`_build_output_paths` derived `show`/`title` as
`program.get('title') if isinstance(program, dict) else channel.name`
(`apps/channels/tasks.py`). `program` is always a dict (`{}` when there is
no EPG match), so `isinstance(program, dict)` was always True and the
`else channel.name` branch was dead code: an ad-hoc recording with no EPG
match got `show = _safe_name(None) = ""`, and the TV fallback template
`TV_Shows/{show}/{start}.mkv` collapsed the empty segment
(`os.path.normpath`) to `TV_Shows/<start>.mkv` -- no channel subdirectory.
"""
import datetime as dt
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from apps.channels.tasks import _build_output_paths

# Fixed wall time, same shape as test_recording_pipeline.py's
# COLLISION_TEST_START: avoids a counter suffix landing inside the
# %Y%m%d_%H%M%S timestamp by accident.
OUTPUT_PATH_TEST_START = timezone.make_aware(dt.datetime(2026, 1, 15, 10, 30, 0))


def _no_collision_patches():
    """_build_output_paths' collision-avoidance stat and its os.makedirs are
    real filesystem calls; neither is the subject of this test, so both are
    patched out exactly as test_recording_pipeline.py's CollisionAvoidanceTests
    does."""
    def mock_stat(path):
        raise OSError("No such file")

    return patch("os.stat", side_effect=mock_stat), patch("os.makedirs")


class AdhocRecordingOutputPathTests(TestCase):
    def _call(self, program):
        channel = MagicMock(name="ChannelMock")
        channel.name = "My Test Channel"
        now = OUTPUT_PATH_TEST_START
        stat_patch, makedirs_patch = _no_collision_patches()
        with stat_patch, makedirs_patch:
            return _build_output_paths(
                channel, program, now, now + dt.timedelta(hours=1), recording_id=1
            )

    def test_adhoc_recording_path_keeps_the_channel_subdirectory(self):
        """An ad-hoc recording with no EPG match (program == {}) falls back
        to the channel name for the {show} segment, instead of collapsing it."""
        final_path, _hls_dir, _filename = self._call(program={})

        self.assertTrue(
            final_path.startswith("/data/recordings/TV_Shows/My Test Channel/"),
            final_path,
        )

    def test_a_titled_programme_still_names_the_directory(self):
        """Control: a recording with a real EPG title is unaffected — it
        already took the program.get('title') branch before the fix."""
        final_path, _hls_dir, _filename = self._call(program={"title": "My Show"})

        self.assertTrue(
            final_path.startswith("/data/recordings/TV_Shows/My Show/"),
            final_path,
        )
