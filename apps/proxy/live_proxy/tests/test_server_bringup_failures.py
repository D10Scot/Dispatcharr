"""A tune whose source cannot be resolved releases its ownership.

stream_ts stops retrying as soon as the failure is not a connection limit
(views.py:336-343) and its own finally block releases ownership at
views.py:612-615. That release is the whole subject.

NOT _cleanup_failed_init. The tune is by channel uuid, so
resolve_initial_source takes the Channel branch and Channel.get_stream()
skips the unresolvable stream; initialize_channel is never entered, and
_cleanup_failed_init's only callers (server.py:719 and :874) are inside it.
This test's server.py yield is ZERO. It earns its place on views.py.

NOT a matrix row -- the ownership lease is D2-deleted machinery. What ports
is the observable: a tune that cannot be served answers an error and leaves
nothing claiming the channel.

Cheap on purpose: nothing spawns, because the failure happens before any
subprocess is reached.
"""

import requests

from apps.channels.models import Stream
from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from .harness.process import stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase, wait_until


class BringUpFailureTests(RelayHarnessTestCase):
    def test_a_tune_whose_source_cannot_be_resolved_leaves_nothing_behind(self):
        server = ProxyServer.get_instance()
        profile = stand_in_stream_profile()
        channel = self.make_channel(
            upstream_url=self.upstream.url, profile=profile
        )
        identifier = str(channel.uuid)

        # queryset.update(), never instance.save(): Stream has a pre_save
        # receiver (apps/channels/signals.py:52-65) that raises when it
        # cannot find the migration-seeded custom M3UAccount, which the
        # flush has already removed.
        Stream.objects.filter(id=channel.streams.first().id).update(
            m3u_account=None
        )

        response = requests.get(
            f"{self.live_server_url}/proxy/ts/stream/{identifier}",
            stream=True,
            timeout=20,
        )
        self.addCleanup(response.close)
        self.assertNotEqual(
            response.status_code, 200, "an unresolvable source must not stream"
        )

        # Nothing is left claiming the channel: no ownership key, no
        # metadata hash, and no local manager.
        wait_until(
            lambda: not server.redis_client.exists(
                RedisKeys.channel_owner(identifier)
            ),
            timeout=10,
            what="the failed init to release ownership",
        )
        self.assertFalse(
            server.redis_client.exists(RedisKeys.channel_metadata(identifier))
        )
        # The one place in this PR a test reads ProxyServer's own dicts: the
        # claim is precisely "no local state survived", which has no wire
        # representation. Not extended beyond this.
        self.assertNotIn(identifier, server.stream_managers)
        self.assertNotIn(identifier, server.stream_buffers)
