"""A synthetic MPEG-TS asset, and the TS-shape assertions tests make about it.

Synthetic rather than ffmpeg-produced on purpose: nothing on the live path
decodes video. input/buffer.py realigns on the 0x47 sync byte at a 188-byte
stride and the ring buffer carries whatever it is given, so a structurally
valid transport stream is exactly as useful here as a real encode, costs no
ffmpeg, and is byte-for-byte deterministic. Where a REAL remuxer's output is
required -- the fMP4 path, which parses moof/moov boxes -- use
build_real_ts_asset() instead; that is 2a-6's territory.
"""

import os
import shutil
import subprocess
import unittest

TS_PACKET_SIZE = 188
TS_SYNC_BYTE = 0x47


def synthetic_ts(packets: int = 512, pid: int = 0x100) -> bytes:
    """`packets` transport-stream packets on `pid`, with a real continuity counter.

    Each packet is: 0x47, then the 13-bit PID split across two bytes with the
    payload-unit-start flag clear, then 0x10 | (counter % 16) -- adaptation
    field control 01 (payload only) in the high nibble, the continuity counter
    in the low one -- then a 184-byte payload whose first 4 bytes are `i`,
    big-endian, and whose remaining 180 are a repeating, position-derived
    filler pattern.

    The embedded index (read back with packet_index()) is what makes a
    packet's absolute POSITION observable at any distance, not just whether
    it differs from its neighbour: the continuity counter only cycles mod 16,
    and content presence alone repeats too, since the filler is `(i + j) %
    256`. A test asking "how far behind is this packet" needs the index; one
    only asking "did the stream break here" (row 9) needs the continuity
    counter and alignment, both still present and unaffected by this. See
    harness/README.md, "Three traps for the tests that come next", for why a
    position question needed this and elapsed time could not answer it.
    """
    if packets < 1:
        raise ValueError("packets must be >= 1")
    if not 0 <= pid <= 0x1FFF:
        raise ValueError("pid must fit in 13 bits")

    out = bytearray()
    for i in range(packets):
        out.append(TS_SYNC_BYTE)
        out.append((pid >> 8) & 0x1F)
        out.append(pid & 0xFF)
        out.append(0x10 | (i % 16))
        out.extend(i.to_bytes(4, "big"))
        out.extend(bytes((i + j) % 256 for j in range(TS_PACKET_SIZE - 8)))
    return bytes(out)


def packet_index(packet: bytes) -> int:
    """The packet index synthetic_ts() embedded, from a single TS_PACKET_SIZE packet."""
    return int.from_bytes(packet[4:8], "big")


def assert_ts_aligned(data: bytes) -> None:
    """Fail unless `data` is a whole number of packets, each starting with 0x47."""
    if not data:
        raise AssertionError("no bytes at all")
    if len(data) % TS_PACKET_SIZE:
        raise AssertionError(
            f"{len(data)} bytes is not a whole number of {TS_PACKET_SIZE}-byte packets"
        )
    for offset in range(0, len(data), TS_PACKET_SIZE):
        if data[offset] != TS_SYNC_BYTE:
            raise AssertionError(
                f"byte {offset} is {data[offset]:#04x}, not the sync byte {TS_SYNC_BYTE:#04x}"
            )


# The relay's own production environment sets this (docker/entrypoint.sh:102).
# Neither test context runs that entrypoint -- the hook container starts with
# `--entrypoint sleep` and backend-tests.yml with `options: --entrypoint ""` --
# and the image carries two librist (/usr/local/lib/librist.so.4.11.0, what
# ffmpeg was linked against, and the distro's 4.3.1 that `vlc` pulls in), with
# ld.so.conf putting the multiarch directory first. So an unqualified `ffmpeg`
# in a test resolves 4.3.1 and dies with
#   symbol lookup error: undefined symbol: rist_peer_config_defaults_set_versioned
# Verified in dispatcharr-testrunner on 2026-09-10.
#
# Set here, in the CHILD's environment, rather than in
# scripts/ci_bootstrap_backend.sh: this is test-local, works identically in the
# hook container, in backend-tests.yml and on a developer's machine, and needs
# no production-adjacent edit. It is a WORKAROUND, not the fix -- the root cause
# is an image defect, tracked as D10Scot/Dispatcharr#226, whose own suggested
# fixes are ordered image-first with exporting this variable in the two test
# bootstraps as the last resort. If #226 lands, this whole helper becomes a
# plain shutil.which plus a version probe.
_FFMPEG_ENV = {"LD_LIBRARY_PATH": "/usr/local/lib"}


def ffmpeg_env() -> dict:
    """`os.environ` plus whatever a spawned ffmpeg needs to actually load."""
    return {**os.environ, **_FFMPEG_ENV}


def require_real_ffmpeg() -> str:
    """The path to a WORKING ffmpeg, or skip the test saying why there isn't one.

    Skips rather than fails: whether ffmpeg links correctly is a property of the
    image the suite happens to run in, not of the code under test, and a red
    suite on an image that links differently teaches nobody anything.
    """
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise unittest.SkipTest("no ffmpeg on PATH")
    try:
        completed = subprocess.run(
            [executable, "-hide_banner", "-version"],
            capture_output=True,
            env=ffmpeg_env(),
            timeout=30,
        )
    except OSError as exc:
        raise unittest.SkipTest(f"ffmpeg at {executable} could not be run: {exc}") from exc
    if completed.returncode != 0:
        raise unittest.SkipTest(
            f"ffmpeg at {executable} exits {completed.returncode}: "
            f"{completed.stderr.decode(errors='replace')[:200]}"
        )
    return executable


def build_real_ts_asset(seconds: float = 2.0, *, keyframe_interval: int | None = None) -> bytes:
    """A short, genuinely encoded MPEG-TS, for the tests that need a real remux.

    Mirrors e2e-upstream/scripts/make-asset.sh, trimmed: no burned-in frame
    counter (nothing here decodes video) and a much shorter duration. Nothing
    downstream may hardcode the packet count -- an ffmpeg version drift is
    expected to change it.

    `keyframe_interval` is `-g`: with libx264's default (250 frames) a 2-second asset
    has one keyframe, so `-movflags frag_keyframe` produces a single `moof` for the
    whole asset. That is NOT unusable through the fMP4 remux by itself -- a caller that
    loops the payload (harness.upstream.FakeUpstream does) still gets more than one
    fragment, because the next loop's own `moof` bounds the previous one, and
    `FMP4RemuxManager._flush_complete_fragments` flushes on exactly that boundary.
    Passing a value well below `seconds x rate` here is an IMPROVEMENT, not a
    requirement: it trades one large fragment per loop (~95 KB at the defaults) for
    several smaller ones (`-g 12` gives five per loop, ~22 KB each), which reaches
    a client's first fragment sooner and exercises `_flush_complete_fragments` more
    than once per loop. Measured against a real remux, both shapes work; see the
    2a-6 plan's F3 for the numbers and the correction to an earlier draft of this
    docstring, which overstated the case as an impossibility.
    """
    executable = require_real_ffmpeg()
    encoder_args = ["-c:v", "libx264", "-preset", "ultrafast"]
    if keyframe_interval is not None:
        encoder_args += ["-g", str(keyframe_interval)]
    encoder_args += ["-b:v", "400k"]
    completed = subprocess.run(
        [
            executable, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=25:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            *encoder_args, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "64k",
            "-f", "mpegts", "pipe:1",
        ],
        capture_output=True,
        env=ffmpeg_env(),
        timeout=120,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "ffmpeg failed to build the asset: "
            + completed.stderr.decode(errors="replace")[:400]
        )
    data = completed.stdout
    assert_ts_aligned(data)
    return data
