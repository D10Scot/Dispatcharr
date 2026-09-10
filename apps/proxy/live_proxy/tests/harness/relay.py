"""Bring the relay up in a backend test, against real Redis and a real control plane.

LiveServerTestCase for two reasons, both required (see the plan's Task 5):
committed rows, because the relay reads the database from its own OS threads
with their own connections; and a real HTTP control plane, because since Phase 1
PR 6 the relay asks Django for its source over HTTP and posts its events there.

The ProxyServer singleton is process-wide and is NEVER torn down: its cleanup
thread (server.py:2192) and event listener (server.py:467) are `while True`
loops with no stop flag. Tests isolate by unique channel UUID and by deleting
that channel's Redis keys, not by rebuilding the server.
"""

import contextlib
import itertools
import os
import time
import uuid as uuid_module

import requests
from django.test import LiveServerTestCase
from unittest.mock import patch

from apps.proxy.live_proxy.redis_keys import RedisKeys
from apps.proxy.live_proxy.server import ProxyServer

from .process import StandInBin
from .upstream import FakeUpstream


def wait_until(predicate, *, timeout: float = 10.0, interval: float = 0.05, what: str = "") -> None:
    """Poll `predicate` until it is true, or fail naming what was being waited for.

    Deadline polling, never a fixed sleep: a harness test must cost what the
    behaviour costs and no more (the plan's Keeping the suite fast).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s waiting for {what or 'a condition'}")


# Module-level, not per class: Channel.channel_number is a FloatField whose
# uniqueness is enforced only inside clean() and only within a channel_group
# (apps/channels/models.py:311, :411-417), so a collision would not raise -- it
# would quietly give two tests the same number and make a failure confusing.
_channel_numbers = itertools.count(9500)


class _TunedStream:
    """Exactly-`count` reads from an open streaming response, with a deadline."""

    def __init__(self, response, *, timeout: float) -> None:
        self._iterator = response.iter_content(chunk_size=4096)
        self._buffer = b""
        self._timeout = timeout

    def read(self, count: int) -> bytes:
        deadline = time.monotonic() + self._timeout
        while len(self._buffer) < count:
            if time.monotonic() > deadline:
                raise AssertionError(
                    f"read {len(self._buffer)} of {count} bytes before the {self._timeout}s deadline"
                )
            chunk = next(self._iterator, None)
            if chunk is None:
                raise AssertionError(
                    f"upstream ended after {len(self._buffer)} of {count} bytes"
                )
            self._buffer += chunk
        out, self._buffer = self._buffer[:count], self._buffer[count:]
        return out


class RelayHarnessTestCase(LiveServerTestCase):
    """Base class for every stage-2a relay test."""

    # Do NOT set `available_apps` here to narrow TransactionTestCase's
    # per-test table flush -- it was tried and measured to do nothing: the
    # 0.7-1.1s a harness test costs is the test BODY (a real subprocess spawn,
    # a real HTTP round trip through LiveServerTestCase, wait_until polling
    # for real Redis-mediated state), not the between-test flush
    # `available_apps` targets. Django's TransactionTestCase._pre_setup fires
    # emit_post_migrate_signal on every test when `available_apps` is set (it
    # must, since teardown then inhibits post_migrate to avoid re-seeding the
    # full app set), and that per-test cost cancels the saving. The minimal
    # correct set is eight apps, not three, because authorize_stream's
    # anonymous-tune path calls get_user_model(), which needs apps.accounts
    # registered -- anything narrower 500s. Worse than merely unhelpful:
    # restricting the app registry stops those apps' tables being FLUSHED,
    # not being WRITTEN TO through an already-imported model class, so a row
    # written to an app outside the set would silently persist across every
    # later test instead of being cleaned up -- a hazard with no offsetting
    # benefit. See the plan's "Keeping the suite fast" section for the
    # measurements.

    def setUp(self):
        super().setUp()
        self._env_backup = {
            name: os.environ.get(name)
            for name in ("DISPATCHARR_INTERNAL_API_BASE_URL", "DISPATCHARR_RELAY_BASE_URL")
        }
        os.environ["DISPATCHARR_INTERNAL_API_BASE_URL"] = self.live_server_url
        os.environ["DISPATCHARR_RELAY_BASE_URL"] = self.live_server_url

        # A paced upstream (rate=1.0) plus a small chunk keeps two things true
        # at once: Redis never takes 34 MB/s (see FakeUpstream's docstring), and
        # a client still sees bytes in milliseconds rather than waiting out a
        # ~256 KB chunk at 250 KB/s. TSConfig.BUFFER_CHUNK_SIZE is a plain class
        # attribute read through ConfigHelper.get, so patching it is the
        # production lever, not a mock.
        from apps.proxy.config import TSConfig
        from .asset import TS_PACKET_SIZE

        patcher = patch.object(TSConfig, "BUFFER_CHUNK_SIZE", TS_PACKET_SIZE * 10)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.upstream = FakeUpstream().start()
        self.addCleanup(self.upstream.stop)
        self.addCleanup(self._restore_env)
        self._channels = []
        self.addCleanup(self._cleanup_channels)

    def _restore_env(self):
        for name, value in self._env_backup.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    # -- fixtures ------------------------------------------------------

    def make_channel(self, *, upstream_url: str, profile):
        """A Channel with one Stream on it, wired the way a real tune expects.

        The M3UAccount/M3UAccountProfile/Stream/ChannelStream shape is copied
        from apps/proxy/tests/test_next_source_resolution.py:110-144, which is
        the recipe next_source.resolve_source() is already known to accept.
        """
        from apps.channels.models import Channel, ChannelStream, Stream
        from apps.m3u.models import M3UAccount, M3UAccountProfile

        suffix = uuid_module.uuid4().hex[:8]
        account = M3UAccount.objects.create(
            name=f"harness-account-{suffix}",
            account_type="STD",
            username="user",
            password="pass",
            max_streams=5,
        )
        # Created by M3UAccount's own post_save; fetched, not made.
        M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        stream = Stream.objects.create(
            name=f"harness-stream-{suffix}",
            url=upstream_url,
            m3u_account=account,
            stream_profile=profile,
            stream_hash=f"harness-hash-{suffix}",
        )
        channel = Channel.objects.create(
            channel_number=next(_channel_numbers),
            name=f"harness-channel-{suffix}",
            stream_profile=profile,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)
        self._channels.append(channel)
        return channel

    def stand_in(self, **kwargs) -> StandInBin:
        """A StandInBin whose default stderr pacing cannot race this class's tests.

        input/manager.py's bitrate EMA (`_bitrate_warmup_samples = 10`, gating
        the branch at :1096-1112 and the final-bitrate flush in `stop()` at
        :1407-1415) is entered only on the stderr reader's 11th progress
        record. The "normal" corpus -- StandInBin's own default -- has exactly
        11 records, so at StandInBin's default pacing (stderr_interval=0.05)
        that 11th record lands ~0.55s after spawn: close enough to a short
        harness tune's own lifetime that whether record 11 is parsed before
        the test calls stop_channel is a coin flip. Measured: four
        back-to-back runs of the Task 7 gate gave `missing` a 27-statement
        spread with this method absent. `stderr_interval=0.0` here writes the
        whole corpus within microseconds of spawn -- so far ahead of the
        network round-trip a `tuned()`/`tune()` call already costs that the
        EMA branch is deterministically reached on every run, in the
        "reached" direction, before any short tune ends. A test that wants
        the corpus genuinely paced (matrix rows 1/4, the buffering detector)
        passes stderr_interval explicitly and gets it -- this default only
        protects a test that has no opinion on stderr timing, which is what
        every test in this file is.
        """
        kwargs.setdefault("stderr_interval", 0.0)
        return StandInBin(**kwargs)

    # -- driving the relay ---------------------------------------------

    @contextlib.contextmanager
    def tuned(self, channel, *, timeout: float = 20.0):
        """GET /proxy/ts/stream/<uuid> over real HTTP; yield a reader, response open.

        Real HTTP rather than the Django test client, because the spec's
        composition rule is to drive the relay through its HTTP surface.

        The response stays open for the body of the `with`, which is what makes
        anything asserted inside it safe: channel_shutdown_delay defaults to 0
        (apps/proxy/config.py:54), so the moment the last client disconnects the
        channel may start tearing down, and a status read or a pid lookup after
        that point is racing the teardown rather than observing the stream.
        """
        url = f"{self.live_server_url}/proxy/ts/stream/{channel.uuid}"
        response = requests.get(url, stream=True, timeout=timeout)
        try:
            # NEVER build this message eagerly. `Response.text` reads the whole
            # body, and on a live streaming 200 the body does not end -- the
            # `timeout` above is a socket timeout, not a wall-clock one, so
            # bytes keep arriving and the read never returns. Formatting it as
            # an assertEqual message hangs every passing tune forever, which
            # under the commit hook pins the container rather than failing a
            # test. Only a non-200 has a body worth reading.
            if response.status_code != 200:
                self.fail(f"tune returned {response.status_code}: {response.text[:200]}")
            yield _TunedStream(response, timeout=timeout)
        finally:
            response.close()

    def tune(self, channel, *, read_bytes: int = 3760, timeout: float = 20.0) -> bytes:
        """Open a tune, read `read_bytes`, close. For tests that only want bytes."""
        with self.tuned(channel, timeout=timeout) as stream:
            return stream.read(read_bytes)

    def stop_channel(self, channel) -> None:
        ProxyServer.get_instance().stop_channel(str(channel.uuid))

    # -- harness-only introspection (see test_harness_smoke.py's docstring) --

    def spawned_pid(self, channel) -> int:
        manager = ProxyServer.get_instance().stream_managers.get(str(channel.uuid))
        self.assertIsNotNone(manager, "no StreamManager for the channel")
        process = getattr(manager, "transcode_process", None)
        self.assertIsNotNone(process, "the StreamManager spawned no process")
        return process.pid

    @staticmethod
    def process_is_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    # -- cleanup -------------------------------------------------------

    def _cleanup_channels(self):
        server = ProxyServer.get_instance()
        for channel in self._channels:
            channel_id = str(channel.uuid)
            try:
                server.stop_channel(channel_id)
            except Exception:
                pass
            client = server.redis_client
            if client is None:
                continue
            for pattern in (
                f"{RedisKeys.channel_metadata(channel_id)}",
                f"{RedisKeys.buffer_chunk_prefix(channel_id)}*",
                f"live:channel:{channel_id}:*",
            ):
                for key in client.scan_iter(match=pattern, count=500):
                    client.delete(key)
        self._channels = []
