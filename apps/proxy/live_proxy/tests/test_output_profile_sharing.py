"""Matrix row 11: one transcode process per active (channel, profile) pair.

Re-pins the row that e2e/tests/streaming-greybox/output-profile-sharing.spec.ts
already covers. Both stand: the e2e spec proves it through nginx in a real
container by counting `pgrep -x ffmpeg`; this proves it in-process by counting
SPAWNS of the profile's own command, which is unambiguous without a container-wide
pre-flight and which 2c-7 can reproduce unchanged in Go.

The channel's input is the locked Proxy stream profile, which spawns no subprocess
at all, so every line in the spawn log is an Output Profile transcode.
"""

import os
import shutil
import tempfile

from core.models import OutputProfile

from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned
from .harness.relay import RelayHarnessTestCase
from .manager_support import proxy_stream_profile
from .output_support import spawn_count, spawn_logging_standin, tapped, wait_for_bytes


class OutputProfileSharingTests(RelayHarnessTestCase):
    def test_two_clients_on_one_output_profile_share_a_single_transcode(self):
        directory = tempfile.mkdtemp(prefix="dispatcharr-2a6-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        log = os.path.join(directory, "spawns.log")
        executable = spawn_logging_standin(directory, log)

        output = OutputProfile.objects.create(
            name="harness-output-profile",
            command=executable,
            parameters="-i pipe:0 -f mpegts pipe:1",
            is_active=True,
        )
        channel = self.make_channel(
            upstream_url=self.upstream.url, profile=proxy_stream_profile()
        )
        query = f"?output_profile={output.id}"

        with tapped(self, channel, query) as first:
            wait_for_bytes(self, first, 20 * TS_PACKET_SIZE, what="bytes for the first client")
            with tapped(self, channel, query) as second:
                wait_for_bytes(self, second, 20 * TS_PACKET_SIZE, what="bytes for the second client")

                assert_ts_aligned(first.snapshot()[: 20 * TS_PACKET_SIZE])
                assert_ts_aligned(second.snapshot()[: 20 * TS_PACKET_SIZE])

                self.assertEqual(
                    spawn_count(log), 1,
                    "two clients on one output profile spawned "
                    f"{spawn_count(log)} transcodes, expected exactly 1",
                )

                # Complementary, not redundant: the e2e spec's own second assertion,
                # and its key name is more useful in a failure message than a bare
                # count. Built through RedisKeys rather than hardcoded, which trades
                # "a key rename is caught" for "a key rename does not fail this test
                # for the wrong reason".
                owner_key = RedisKeys.output_owner(
                    str(channel.uuid), f"mpegts:p{output.id}"
                )
                self.assertTrue(
                    ProxyServer.get_instance().redis_client.exists(owner_key),
                    f"no owner lock at {owner_key}; the transcode never claimed the pair",
                )
        self.stop_channel(channel)
