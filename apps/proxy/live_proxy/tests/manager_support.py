"""Levers the input/manager.py behaviour tests pull, and the corpus readers they use.

Deliberately NOT under harness/: harness/ is 2a-2's deliverable and 2a-3, 2a-5 and
2a-6 are consuming it from this same base commit, so an edit there is a merge conflict
for three PRs. Everything here is specific to input/manager.py's failover behaviour.
`set_proxy_settings` and `sample_while` are the two that plausibly belong to every
stage-2a test; the PR description records the recommendation to move them into
RelayHarnessTestCase once the parallel PRs have landed.
"""

import re
import time

from apps.proxy import relay_client
from apps.proxy.config import TSConfig
from core.models import PROXY_PROFILE_NAME, PROXY_SETTINGS_KEY, CoreSettings, StreamProfile

from .harness.ffmpeg_stderr import progress_lines

# The PRODUCTION regex, copied deliberately rather than imported: these tests assert
# what the shipped parser sees, and importing it would make the assertion move if the
# parser moved (input/manager.py:1065). Same rationale, and the same literal, as
# test_harness_standin.py:20-22.
SPEED_RE = re.compile(r"speed=\s*([0-9.]+)x?")

# The whole field, exponent included -- what the production regex declines to read.
# The gap between the two is parity-matrix row 28 / issue #227.
FULL_SPEED_RE = re.compile(r"speed=\s*([0-9.]+(?:[eE][+-]?[0-9]+)?)x?")

# ffmpeg 8.1.2 appends elapsed= after speed=; CAPTURE.md records it as one of the four
# shapes a hand-written fixture would have got wrong. Nothing in production parses it --
# it is read here only so a test can quote the capture's own wall clock.
ELAPSED_RE = re.compile(r"elapsed=(\d+):(\d\d):(\d\d(?:\.\d+)?)")

# core/serializers.py:96. The API cannot store a buffering_speed outside this range, so
# every threshold these tests set is one an operator could set.
API_MIN_BUFFERING_SPEED = 0.1
API_MAX_BUFFERING_SPEED = 10.0


def corpus_speeds(name):
    """Every progress record's speed=, as the production regex reads it."""
    return [float(SPEED_RE.search(line).group(1)) for line in progress_lines(name)]


def corpus_elapsed(name, index):
    """Record `index`'s elapsed= in seconds -- the real ffmpeg wall clock it took."""
    hours, minutes, seconds = ELAPSED_RE.search(progress_lines(name)[index]).groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _reset_proxy_settings():
    # Deleting the row fires post_delete (core/signals.py:11-13), which invalidates the
    # Redis group cache. It also calls BaseConfig.clear_proxy_settings_cache()
    # (core/models.py:360-361), which is the WRONG class and clears nothing a relay
    # reader will see -- issue #232 -- so the explicit call below is what actually
    # drops the process-local copy.
    CoreSettings.objects.filter(key=PROXY_SETTINGS_KEY).delete()
    TSConfig.clear_proxy_settings_cache()


def set_proxy_settings(test, **overrides):
    """Write proxy_settings the way an operator would, and prove the write landed.

    The explicit TSConfig.clear_proxy_settings_cache() below is REQUIRED, and the
    reason is a production defect this helper's own read-back assertion found
    (issue #232). `get_proxy_settings` is a classmethod that caches on `cls`
    (apps/proxy/config.py:32-51), and every relay reader binds the SUBCLASS --
    `from apps.proxy.config import TSConfig as Config` at config_helper.py:5 and
    input/manager.py:11 -- so the cache lands on `TSConfig` as a shadowing class
    attribute. CoreSettings' post_save receiver clears `BaseConfig`
    (core/models.py:360-361), which never touches that shadow. So saving the row
    does NOT make the new value visible; the 10-second TTL
    (apps/proxy/config.py:24) is the only thing that expires it. Without this line
    rows 1, 5 and 6 fail their own read-back whenever any test tuned a channel in
    the previous ten seconds -- which, in file order, row 28 always has.

    The cleanup is not optional either. TransactionTestCase's teardown TRUNCATEs and
    fires no post_delete, so without it the cached dict keeps this test's thresholds
    into later tests in the same label.

    The read-back assertion is what makes every test using this lever falsifiable: it
    goes through TSConfig.get_proxy_settings(), the exact reader StreamManager.__init__
    uses at input/manager.py:60-61, so a test that later observes "nothing buffered"
    cannot be passing because the setting silently failed to apply. It is also what
    caught #232 rather than letting it pass as a mysterious flake.
    """
    test.addCleanup(_reset_proxy_settings)
    merged = dict(CoreSettings.get_proxy_settings())
    merged.update(overrides)
    CoreSettings.objects.update_or_create(
        key=PROXY_SETTINGS_KEY, defaults={"value": merged}
    )
    # See the docstring: the post_save receiver clears the wrong class (#232).
    TSConfig.clear_proxy_settings_cache()
    live = TSConfig.get_proxy_settings()
    for name, value in overrides.items():
        test.assertEqual(live.get(name), value, f"proxy_settings.{name} did not apply")
    return merged


def proxy_stream_profile():
    """The locked built-in Proxy profile: raw HTTP into the ring buffer, no subprocess.

    Created rather than fetched: TransactionTestCase's flush wipes the rows
    core/migrations/0003_preload_stream_profiles.py seeds. `locked=True` is what makes
    is_proxy() true (core/models.py:127-130), and StreamProfile.save's protected-field
    guard only runs when self.pk is set (core/models.py:78-80), so creating one is fine.
    """
    profile, _ = StreamProfile.objects.get_or_create(
        name=PROXY_PROFILE_NAME,
        defaults={"command": "", "parameters": "", "locked": True},
    )
    return profile


def add_alternate_stream(test, channel, upstream, *, order):
    """A further Stream on `channel`, on a DIFFERENT URL, so a failover can pick it.

    The different URL is load-bearing, not cosmetic: next_source's failover traversal
    rejects any candidate resolving to the URL already playing
    (apps/proxy/next_source.py:621-633), so two ChannelStreams sharing one FakeUpstream
    path make every failover answer "no alternate stream" and the test then passes or
    fails for the wrong reason. FakeUpstream's handler never inspects the request path
    (harness/upstream.py's _Handler.do_GET), so a different path on the same server is a
    genuinely different URL serving the same bytes -- and still ends in .ts, which keeps
    detect_stream_type on the 'ts' branch (utils.py:31-66) instead of forcing ffmpeg.
    """
    from apps.channels.models import ChannelStream, Stream

    first = channel.streams.order_by("channelstream__order").first()
    test.assertIsNotNone(first, "channel has no stream to copy an account from")
    base = upstream.url.rsplit("/", 1)[0]
    stream = Stream.objects.create(
        name=f"{channel.name}-alt-{order}",
        url=f"{base}/alt-{order}.ts",
        m3u_account=first.m3u_account,
        stream_profile=first.stream_profile,
        stream_hash=f"{channel.uuid}-alt-{order}",
    )
    ChannelStream.objects.create(channel=channel, stream=stream, order=order)
    return stream


def status(channel):
    """GET /proxy/relay/channels/<uuid>, through Django's own client for it.

    relay_client mints the two internal headers and dials
    DISPATCHARR_RELAY_BASE_URL, which RelayHarnessTestCase.setUp already points at the
    live server (harness/relay.py:87). None means the relay holds no metadata for the
    channel (a 404, which relay_client.get_channel:240-242 turns into None).

    The payload is built from ONE hgetall (channel_status.py:30), so state,
    ffmpeg_speed and stream_id inside one snapshot are mutually consistent -- which is
    what lets these tests assert invariants over samples instead of values at instants.
    """
    return relay_client.get_channel(str(channel.uuid))


def sample_while(test, channel, *, until=None, chunks=None, drain=None, timeout=15.0):
    """Poll the relay's own status, returning every snapshot taken, newest last.

    Exactly one stopping condition:
      until=<predicate over the snapshot dict>  stop as soon as it holds
      chunks=<int>                              stop after that many ring-buffer chunks
                                                have been read (requires drain)

    `drain` is the open _TunedStream. Reading is not incidental. The relay keeps
    producing while the test polls, and a client that never reads fills its socket
    buffer and stalls the generator thread serving it; draining also paces the loop to
    roughly real time without a fixed sleep, which is what keeps these tests off the
    clock (2a-2's plan, Keeping the suite fast).
    """
    if (until is None) == (chunks is None):
        raise ValueError("pass exactly one of until= or chunks=")
    if chunks is not None and drain is None:
        raise ValueError("chunks= counts bytes read, so it needs drain=")

    # The harness patches this down to TS_PACKET_SIZE * 10 in setUp; read it rather
    # than hardcode it, so a change there does not silently change what a test observes.
    chunk_size = TSConfig.BUFFER_CHUNK_SIZE
    snapshots = []
    read = 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        info = status(channel)
        if info is not None:
            snapshots.append(info)
            if until is not None and until(info):
                return snapshots
        if drain is not None:
            drain.read(chunk_size)
            read += 1
            if chunks is not None and read >= chunks:
                return snapshots
        else:
            time.sleep(0.02)
    if until is not None:
        test.fail(
            f"timed out after {timeout}s; last snapshot: "
            f"{snapshots[-1] if snapshots else 'none'}"
        )
    test.fail(f"read {read} of {chunks} chunks before the {timeout}s deadline")


def read_until_end(response, *, timeout=15.0):
    """Every byte of a streaming response that is expected to END, with a deadline.

    RelayHarnessTestCase.tuned() is the wrong tool for a tune that fails: _TunedStream
    raises when the body ends early, and that ending is exactly what a connect-failure
    test is asserting. Deadline-bounded so a body that does NOT end fails the test
    rather than hanging the label -- `timeout` on the request is a socket timeout, not a
    wall-clock one.
    """
    body = b""
    deadline = time.monotonic() + timeout
    try:
        for chunk in response.iter_content(chunk_size=8192):
            body += chunk
            if time.monotonic() > deadline:
                raise AssertionError(f"response did not end within {timeout}s")
    finally:
        response.close()
    return body
