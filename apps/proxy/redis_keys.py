"""Redis key builders Django still uses.

apps/channels/models.py imports RedisKeys at module level (Channel.get_stream,
release_stream, update_stream_profile and _release_stale_stream_assignment),
and so do core/utils.py and apps/proxy/next_source.py function-locally.

THIS MODULE MUST STAY A LEAF -- no imports, at all. It is loaded by every
migration and every management command through that models.py import, so a
cycle added here is not a failing test, it is a container that does not
start. ``.claude/hooks/run-affected-tests.sh``'s boot-check ``case`` arm
names this file for exactly that reason, and
apps/proxy/tests/test_redis_keys_dead_builders.py asserts it.

Phase 2 stage 2d-1 moved this module here from the live relay's package, and
it then held 28 builders for the Python relay's channel state. The Go relay
opens no Redis connection, so fix plan J-2 deleted the 26 whose keys nothing
in production reads or writes.
"""

class RedisKeys:
    # Written only by apps/channels/models.py — Channel.get_stream(),
    # release_stream(), update_stream_profile() — and reached only through
    # apps/proxy/next_source.py since Phase 1 PR 6. They were hand-rolled
    # f-strings on both sides of the boundary, which is what made them
    # split-brain; naming them here is what makes a second writer visible.
    @staticmethod
    def channel_stream(channel_pk):
        """Stream id currently assigned to this channel (numeric channel pk)."""
        return f"channel_stream:{channel_pk}"

    @staticmethod
    def stream_profile(stream_id):
        """M3U account profile id serving this stream."""
        return f"stream_profile:{stream_id}"
