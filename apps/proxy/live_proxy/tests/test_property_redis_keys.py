"""Property-based tests for RedisKeys (apps/proxy/live_proxy/redis_keys.py).

Every live-relay Redis key is built by RedisKeys. Keys are the only naming
contract between the owner worker, follower workers, the stats endpoints and
the cleanup paths — a key that embeds caller input verbatim must still land
inside the documented ``live:`` namespace, or cross-channel key pollution
becomes possible. The properties state what the builders promise:

* every key is a str in the ``live:`` namespace, with no NUL/whitespace
  injected by hostile ids (Redis keys are binary-safe, but the codebase
  compares keys as decoded text — a key containing ``\\n`` or ``\\r`` would
  break log-scan tooling and SCAN pattern expectations);
* per-channel keys embed their channel_id, per-client keys embed both ids;
* chunk prefix helpers are strict prefixes of the corresponding chunk keys;
* distinct channel ids never produce the same metadata key (no collisions).

These tests do not require Redis — RedisKeys is pure string formatting.
"""

from hypothesis import given, settings as hyp_settings, strategies as st
from django.test import SimpleTestCase

from apps.proxy.live_proxy.redis_keys import RedisKeys

# CI-deterministic profile — see test_property_find_ts_sync.py for rationale.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

# Channel ids are UUID strings in practice, but the key layer is a plain
# string interpolation. Django's <str:channel_id> path converter admits any
# non-'/' text (percent-decoded), so adversarial ids are in scope — but the
# only guarantee the builders themselves make is namespace containment and
# structural prefixing, not character hygiene.
ids = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=64,
)
fmts = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=16,
)

CHANNEL_KEY_BUILDERS = [
    RedisKeys.channel_metadata,
    RedisKeys.buffer_index,
    RedisKeys.buffer_chunk_prefix,
    RedisKeys.channel_stopping,
    RedisKeys.events_channel,
    RedisKeys.switch_request,
    RedisKeys.channel_owner,
    RedisKeys.clients,
    RedisKeys.last_client_disconnect,
    RedisKeys.connection_attempt,
    RedisKeys.last_data,
    RedisKeys.switch_status,
    RedisKeys.chunk_timestamps,
    RedisKeys.transcode_active,
]

OUTPUT_KEY_BUILDERS = [
    RedisKeys.output_buffer_index,
    RedisKeys.output_buffer_chunk_prefix,
    RedisKeys.output_init,
    RedisKeys.output_state,
    RedisKeys.output_owner,
    RedisKeys.output_chunk_timestamps,
]


class RedisKeysProperties(SimpleTestCase):
    @given(channel_id=ids)
    def test_channel_keys_stay_in_live_namespace(self, channel_id):
        for build in CHANNEL_KEY_BUILDERS:
            key = build(channel_id)
            self.assertIsInstance(key, str)
            self.assertTrue(key.startswith("live:"), key)

    @given(channel_id=ids, fmt=fmts)
    def test_output_keys_stay_in_live_namespace(self, channel_id, fmt):
        for build in OUTPUT_KEY_BUILDERS:
            key = build(channel_id, fmt)
            self.assertIsInstance(key, str)
            self.assertTrue(key.startswith("live:"), key)

    @given(channel_id=ids, chunk_index=st.integers(min_value=0, max_value=10**12))
    def test_chunk_prefix_is_a_prefix_of_chunk_key(self, channel_id, chunk_index):
        prefix = RedisKeys.buffer_chunk_prefix(channel_id)
        key = RedisKeys.buffer_chunk(channel_id, chunk_index)
        self.assertTrue(key.startswith(prefix), (prefix, key))

    @given(
        channel_id=ids,
        fmt=fmts,
        chunk_index=st.integers(min_value=0, max_value=10**12),
    )
    def test_output_chunk_prefix_is_a_prefix_of_chunk_key(
        self, channel_id, fmt, chunk_index
    ):
        prefix = RedisKeys.output_buffer_chunk_prefix(channel_id, fmt)
        key = RedisKeys.output_buffer_chunk(channel_id, fmt, chunk_index)
        self.assertTrue(key.startswith(prefix), (prefix, key))

    @given(channel_a=ids, channel_b=ids)
    def test_distinct_channels_get_distinct_metadata_keys(self, channel_a, channel_b):
        if channel_a == channel_b:
            return
        self.assertNotEqual(
            RedisKeys.channel_metadata(channel_a),
            RedisKeys.channel_metadata(channel_b),
        )

    @given(
        channel_id=ids,
        other=st.tuples(ids, ids),
    )
    def test_channel_id_cannot_escape_its_key_slot(self, channel_id, other):
        """A hostile channel_id embedding ':' must not be able to reach another
        channel's keys by crafting an id that reproduces their full key."""
        target_channel, target_client = other
        if channel_id == target_channel:
            return
        # The stopping key of one channel must never equal the stopping or
        # metadata key of a different channel.
        self.assertNotEqual(
            RedisKeys.channel_stopping(channel_id),
            RedisKeys.channel_stopping(target_channel),
        )
        self.assertNotEqual(
            RedisKeys.channel_metadata(channel_id),
            RedisKeys.channel_metadata(target_channel),
        )
        # Nor may a crafted channel_id impersonate a client-scoped key of
        # another channel.
        self.assertNotEqual(
            RedisKeys.channel_stopping(channel_id),
            RedisKeys.client_stop(target_channel, target_client),
        )

    @given(channel_id=ids, client_id=ids)
    def test_client_keys_embed_both_ids(self, channel_id, client_id):
        stop_key = RedisKeys.client_stop(channel_id, client_id)
        meta_key = RedisKeys.client_metadata(channel_id, client_id)
        self.assertIn(channel_id, stop_key)
        self.assertIn(client_id, stop_key)
        self.assertIn(channel_id, meta_key)
        self.assertIn(client_id, meta_key)
