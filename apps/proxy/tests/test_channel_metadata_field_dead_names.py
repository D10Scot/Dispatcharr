"""ChannelMetadataField carried names for a Redis hash field nothing reads.

Issue #461, the same shape as #407's RedisKeys audit: a dead name is not
harmless -- it tells a reader a live field exists when nothing writes or
reads it any more. #314 was exactly that confusion (a status endpoint field
nobody ever wrote). apps/proxy/constants.py is a boot-trap leaf
(apps/channels/models.py imports apps/proxy/redis_keys.py at module level,
and apps/timeshift/views.py imports apps/proxy/config_helper.py and this
module -- apps/proxy/constants.py -- at module level, so a cycle in either
breaks every management command; timeshift/views.py's third module-level
import, apps.timeshift.redis_keys, is a different module and not part of
this trap); the leaf-import assertion itself already lives in
apps/proxy/tests/test_redis_keys_dead_builders.py's LEAF_MODULES, which
covers this file too, so it is not repeated here.

Criterion, identical to #407's: a name is dead when no
`ChannelMetadataField.<NAME>` reference exists IN CODE anywhere in the tree
outside apps/proxy/constants.py itself (docs/ and CHANGELOG.md excluded as
historical, and so is a comment -- a fix round found STATE_CHANGED_AT named
only in relay/channel/channel.go comments, with no reader anywhere). The
surviving set is pinned exactly, so a name added back needs a real non-test
reader and a deliberate edit here.
"""

from django.test import SimpleTestCase

from apps.proxy.constants import ChannelMetadataField

SURVIVORS = {
    "URL",
    "STATE",
    "STREAM_ID",
    "CHANNEL_NAME",
    "STREAM_NAME",
    "CHANNEL_ID",
    "CHANNEL_UUID",
    "LOGO_ID",
    "M3U_PROFILE",
    "INIT_TIME",
    "TOTAL_BYTES",
    "VIDEO_CODEC",
    "RESOLUTION",
    "WIDTH",
    "HEIGHT",
    "SOURCE_FPS",
    "PIXEL_FORMAT",
    "VIDEO_BITRATE",
    "AUDIO_CODEC",
    "SAMPLE_RATE",
    "AUDIO_CHANNELS",
    "AUDIO_BITRATE",
    "STREAM_TYPE",
    "STREAM_INFO_UPDATED",
}


class ChannelMetadataFieldDeadNamesTests(SimpleTestCase):
    def test_channel_metadata_field_carries_only_names_with_a_reader(self):
        names = {
            name for name, value in vars(ChannelMetadataField).items()
            if isinstance(value, str) and not name.startswith("_")
        }
        self.assertEqual(
            names, SURVIVORS,
            f"unexpected names: {sorted(names - SURVIVORS)}; "
            f"missing: {sorted(SURVIVORS - names)}",
        )
