"""Levers the output-side (fMP4, Output Profile) behaviour tests pull.

Deliberately NOT under harness/: harness/ is 2a-2's deliverable and both 2a-3
(PR #239) and 2a-5 (PR #237) sit off the same base with harness/ edits of their
own, so an addition there is a merge conflict for another open PR. 2a-4's
manager_support.py exists for the same reason and this file follows it.

Two child programs appear in this PR and the split is deliberate (harness/README.md
§ The stated rule): the stand-in wherever the subject is the relay's reaction to a
process, real ffmpeg wherever the subject is the bytes a remuxer produces. A dumb
pipe cannot drive the fMP4 path at all -- FMP4RemuxManager parses moof boxes out of
its child's stdout and MPEG-TS carries none.
"""

import contextlib
import functools
import os
import shutil
import stat
import sys
import tempfile
import threading
import time

import requests

from .harness import process as harness_process
from .harness.asset import build_real_ts_asset, ffmpeg_env, require_real_ffmpeg
from .harness.relay import wait_until

# -- ffmpeg environment --------------------------------------------------


@contextlib.contextmanager
def real_ffmpeg_environment():
    """`ffmpeg` on PATH, actually runnable, for the duration.

    require_real_ffmpeg() skips (not fails) when the image links ffmpeg wrongly:
    whether ffmpeg loads is a property of the image, not of the code under test.
    The LD_LIBRARY_PATH export is issue #226's workaround, applied to os.environ
    because live_proxy/utils.py:154 passes os.environ straight to os.posix_spawn --
    harness.asset.ffmpeg_env() only reaches the harness's own subprocess calls.
    """
    from unittest.mock import patch

    require_real_ffmpeg()
    with patch.dict(os.environ, ffmpeg_env()):
        yield


# -- the fragmentable asset -----------------------------------------------

_PAYLOAD_SECONDS = 2.0
_PAYLOAD_GOP = 12


@functools.lru_cache(maxsize=1)
def fragmentable_upstream_payload() -> bytes:
    """A real TS asset the fMP4 remux can turn into more than one fragment per loop.

    gop=12 at 25 fps is a keyframe every ~0.48s, so one 2-second loop carries five
    moof boxes -- measured, against ffmpeg 8.1.2. This is an IMPROVEMENT over the
    default (no -g, one keyframe per 250 frames, ONE moof for the whole asset), not
    a requirement: FakeUpstream loops its payload, so even the one-moof-per-loop
    shape still gets flushed once per loop (the next loop's own moof bounds the
    previous fragment). -g 12 instead gives five smaller fragments per loop
    (~22 KB each, vs. ~95 KB for the whole loop unfragmented), which reaches a
    client's first fragment sooner. See the 2a-6 plan's F3.

    Cached: building it costs about a second of real ffmpeg and every test in this
    PR wants the same bytes.
    """
    return build_real_ts_asset(_PAYLOAD_SECONDS, keyframe_interval=_PAYLOAD_GOP)


# -- the spawn-logging stand-in --------------------------------------------

_STANDIN_SOURCE = os.path.join(
    os.path.dirname(os.path.abspath(harness_process.__file__)), "standin.py"
)


def spawn_logging_standin(directory, log_path, *, name="output-standin"):
    """An executable that appends its pid to `log_path`, then runs harness/standin.py.

    Why a log rather than a process count: the claim matrix row 11 makes is about
    how many transcodes are STARTED for one (channel, profile) pair, and a log of
    spawns says that directly. A count of surviving processes says it only
    indirectly, needs /proc or pgrep, and -- as the e2e spec this re-pins has to
    document at length -- is ambiguous about processes from elsewhere.

    Copied into `directory` for the same reason StandInBin copies it: the repository
    is bind-mounted read-only in the test container, so nothing in the tree can be
    given an exec bit at test time.
    """
    shutil.copyfile(_STANDIN_SOURCE, os.path.join(directory, "standin.py"))
    wrapper = os.path.join(directory, name)
    body = (
        f"#!{sys.executable}\n"
        "import os, runpy, sys\n"
        f"open({log_path!r}, 'a').write(str(os.getpid()) + chr(10))\n"
        "sys.argv[0] = 'ffmpeg'\n"
        f"runpy.run_path(os.path.join({directory!r}, 'standin.py'), run_name='__main__')\n"
    )
    with open(wrapper, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.chmod(wrapper, os.stat(wrapper).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return wrapper


def spawn_count(log_path) -> int:
    """How many times the logging stand-in has been spawned. 0 if never."""
    try:
        with open(log_path, encoding="utf-8") as handle:
            return len([line for line in handle if line.strip()])
    except FileNotFoundError:
        return 0


def standin_stream_profile(directory, *, name, extra=""):
    """An input StreamProfile that spawns the stand-in WITHOUT shadowing `ffmpeg`.

    StandInBin puts its wrapper first on PATH, which also captures
    output/fmp4/manager.py:32's FFMPEG_REMUX_CMD -- and a dumb pipe cannot produce
    an fMP4 init segment (this plan's F1). Naming the executable in the profile row
    reaches input/manager.py's spawn (build_command at core/models.py:200) and
    leaves PATH alone.

    `extra` carries stand-in flags, e.g. "--dead-air-after-bytes 2500000".
    """
    from core.models import StreamProfile

    log = os.path.join(directory, f"{name}-spawns.log")
    executable = spawn_logging_standin(directory, log, name=name)
    profile = StreamProfile.objects.create(
        name=f"harness-{name}",
        command=executable,
        parameters=f"-i {{streamUrl}} {extra}".strip(),
    )
    return profile


# -- draining a live tune in the background ---------------------------------


class StreamTap(threading.Thread):
    """Drains a streaming response in the background, recording when it went quiet
    and when (if ever) it ended.

    A real thread, not a greenlet: manage.py test is not monkey-patched
    (harness/README.md), so this is the same primitive FakeUpstream already uses.
    """

    def __init__(self, response):
        super().__init__(daemon=True, name="stream-tap")
        self._response = response
        self._lock = threading.Lock()
        self._buffer = bytearray()
        self._started_at = time.monotonic()
        self.bytes_read = 0
        self.last_byte_at = None
        self.ended_at = None
        self.error = None

    def start(self):
        self._started_at = time.monotonic()
        super().start()

    def run(self):
        try:
            for chunk in self._response.iter_content(chunk_size=4096):
                if not chunk:
                    continue
                with self._lock:
                    self._buffer += chunk
                    self.bytes_read += len(chunk)
                    self.last_byte_at = time.monotonic()
        except Exception as exc:          # the response being closed is an ordinary end
            self.error = exc
        finally:
            with self._lock:
                self.ended_at = time.monotonic()

    def snapshot(self) -> bytes:
        with self._lock:
            return bytes(self._buffer)

    def quiet_for(self) -> float:
        """Seconds since the last byte, or since the tap started if none arrived."""
        with self._lock:
            return time.monotonic() - (self.last_byte_at or self._started_at)


@contextlib.contextmanager
def tapped(test, channel, query=""):
    """GET /proxy/ts/stream/<uuid><query> over real HTTP, drained in the background.

    NEVER format response.text into an assertion message on a 200: the body of a
    live tune does not end and the read never returns (harness/relay.py's `tuned`
    carries the same warning, for the same reason).

    COST TRAP, found measuring 2a-6's row-12 test: `finally: response.close()` below
    does not return promptly if the response body was only partially consumed (which
    every caller here does -- StreamTap reads it in a background thread via
    `iter_content`, and a test rarely waits for it to end on its own).

    The mechanism (corrected on review -- an earlier draft of this note blamed the
    connection-pool release path waiting for EOF; that is not it): the background
    StreamTap thread's `iter_content()` call is blocked inside an in-flight read,
    holding whatever `requests`/`urllib3` uses to serialize access to that response's
    buffered reader. The main thread's `response.close()` cannot proceed until that
    read call returns and releases it -- which happens on the arrival of ANY new byte
    on the connection, not specifically EOF. Demonstrated independently against a
    quiet HTTP server that sent one chunk then six seconds of silence: `close()` took
    5.50s, and the background reader then received the *second* chunk right after.
    In the row-12 test the releasing byte is the TS client's own keepalive packet,
    sent once the health monitor flips the channel unhealthy -- which is also why the
    cost tracks the health monitor's own timing rather than any timeout `close()`
    carries of its own.

    Net effect unchanged from the first draft of this note: exiting a `with
    tapped(...)` block pays whatever it costs for the underlying connection to
    produce one more byte -- the server's own timeout, teardown, or keepalive
    cadence -- whether or not the test asserts anything about that response ever
    ending. Measured: closing a TS-format tap whose channel had gone unhealthy cost
    ~13.5s here, independent of and much larger than the ~7s the test's own pinned
    wait cost -- confirmed by instrumentation, not the `stop_channel()` call at the
    end of the test, which cost 0.14s on its own.

    The fix that worked in practice, once found, was NOT inside this function: stop
    the channel explicitly, while still inside the `with tapped(...)` block and after
    every assertion that needed the response open has already run. That makes the
    SERVER end the response immediately, so the `finally: response.close()` below has
    nothing left to wait for when the block exits. See
    `test_fmp4_client_timeout.py`'s `self.stop_channel(channel)` placement for the
    worked example (21.5s to 8.5s on that test). There is still no way to make an
    *unmodified* caller's `with tapped(...)` exit fast without that caller doing the
    stopping itself -- `tapped()` cannot know when a test no longer needs the
    response open, so this function still can't fix the trap generically, only
    document it and the pattern that avoids it.
    """
    url = f"{test.live_server_url}/proxy/ts/stream/{channel.uuid}{query}"
    response = requests.get(url, stream=True, timeout=20)
    if response.status_code != 200:
        body = response.text[:200]
        response.close()
        test.fail(f"tune returned {response.status_code}: {body}")
    tap = StreamTap(response)
    tap.start()
    try:
        yield tap
    finally:
        response.close()


def wait_for_bytes(test, tap, count, *, timeout=10.0, what="bytes"):
    wait_until(
        lambda: tap.bytes_read >= count,
        timeout=timeout,
        what=f"{count} {what} (got {tap.bytes_read} so far)",
    )


# -- MP4 shape assertions ----------------------------------------------------


def mp4_boxes(data: bytes):
    """[(offset, size, type)] walking the top-level MP4 box chain, stopping at the
    first malformed length. Deliberately a re-implementation of the walk rather
    than an import of _find_moof_offset: a test that parses with the code under
    test proves the code agrees with itself, not that the code is right."""
    boxes = []
    offset = 0
    while offset + 8 <= len(data):
        size = int.from_bytes(data[offset:offset + 4], "big")
        box_type = data[offset + 4:offset + 8]
        if size < 8:
            break
        boxes.append((offset, size, box_type))
        offset += size
    return boxes


def assert_fmp4_init_then_fragment(test, data: bytes):
    """Fail unless `data` is ftyp, then moov, then at least one moof followed by an
    mdat -- the shape output/fmp4/manager.py splits at and the shape a player needs."""
    boxes = mp4_boxes(data)
    types = [box_type for _, _, box_type in boxes]
    if not types or types[0] != b"ftyp":
        test.fail(f"fMP4 stream does not start with ftyp: got {types[:5]!r} from {data[:32]!r}")
    if b"moov" not in types:
        test.fail(f"no moov box in the fMP4 stream: got {types!r}")
    if b"moof" not in types:
        test.fail(f"no moof (fragment) box in the fMP4 stream: got {types!r}")
    moof_index = types.index(b"moof")
    if moof_index + 1 >= len(types) or types[moof_index + 1] != b"mdat":
        test.fail(
            f"moof at box index {moof_index} is not followed by mdat: got {types!r}"
        )
