"""The stand-in is a real child process, spawned by the relay's own spawn helper."""

import os
import re
import select
import signal
import time

from django.test import SimpleTestCase

from apps.proxy.live_proxy.utils import posix_spawn_proc

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned, synthetic_ts
from .harness.ffmpeg_stderr import CORPUS_NAMES, load, progress_lines
from .harness.process import StandInBin
from .harness.upstream import FakeUpstream

# The production regex, copied deliberately rather than imported: these tests
# assert what the shipped parser sees, and importing it would make the
# assertion move if the parser moved (input/manager.py:1065).
SPEED_RE = re.compile(r"speed=\s*([0-9.]+)x?")


def _read_ready(stream, count, deadline):
    """One read that cannot outlive the deadline.

    `stream` is an unbuffered pipe, so a bare `.read()` blocks until data
    arrives -- which means a `while time.monotonic() < deadline` loop around it
    only checks the clock BETWEEN reads and never while one is stuck. A wrong
    literal then hangs the whole label instead of failing it. select() first,
    so the deadline is real.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return b""
    ready, _, _ = select.select([stream.fileno()], [], [], remaining)
    if not ready:
        return b""
    return os.read(stream.fileno(), count)


def _read_exactly(stream, count, timeout=10.0):
    out = b""
    deadline = time.monotonic() + timeout
    while len(out) < count:
        chunk = _read_ready(stream, count - len(out), deadline)
        if not chunk:
            break
        out += chunk
    return out


def _read_until(stream, needle, timeout=10.0):
    """Read until `needle` appears, or the deadline passes. Never blocks past it."""
    out = b""
    deadline = time.monotonic() + timeout
    while needle not in out:
        chunk = _read_ready(stream, 4096, deadline)
        if not chunk:
            break
        out += chunk
    return out


class StandInSpawnTests(SimpleTestCase):
    def test_path_shadowing_makes_which_resolve_the_stand_in(self):
        import shutil

        with StandInBin() as binary:
            self.assertEqual(shutil.which("ffmpeg"), os.path.join(binary.path, "ffmpeg"))

    def test_path_is_restored_on_exit(self):
        before = os.environ["PATH"]
        with StandInBin():
            self.assertNotEqual(os.environ["PATH"], before)
        self.assertEqual(os.environ["PATH"], before)

    def test_the_production_spawn_helper_runs_it_and_copies_ts_bytes(self):
        with FakeUpstream() as upstream, StandInBin():
            proc = posix_spawn_proc(["ffmpeg", "-i", upstream.url])
            try:
                body = _read_exactly(proc.stdout, 8 * TS_PACKET_SIZE)
                self.assertGreater(proc.pid, 0)
                self.assertIsNone(proc.poll())
            finally:
                proc.terminate()
                proc.wait(timeout=5)
        assert_ts_aligned(body)

    def test_the_corpus_is_real_ffmpeg_output(self):
        """Guard: the fixtures must carry a real ffmpeg preamble, not invented lines."""
        for name in CORPUS_NAMES:
            raw = load(name)
            self.assertIn(b"ffmpeg version ", raw, name)
            self.assertIn(b"Input #0, mpegts, from ", raw, name)
            self.assertIn(b"Output #0, mpegts, to 'pipe:1'", raw, name)
            self.assertTrue(progress_lines(name), f"{name}: no progress records")

    def test_a_multi_record_capture_uses_cr_termination(self):
        """CR is how ffmpeg rewrites the status line -- but only between records.

        Asserted on the two multi-record fixtures only. `truncation` has exactly
        one record, LF-terminated, and therefore no CR at all; asserting CR on
        every fixture is false for any capture, not just this one.
        """
        for name in ("normal", "slow-trickle"):
            self.assertIn(b"\r", load(name), f"{name}: no CR; not a real multi-record capture")
        self.assertEqual(len(progress_lines("truncation")), 1)
        self.assertNotIn(b"\r", load("truncation"), "truncation should be a single LF-ended record")

    def test_the_slow_trickle_corpus_actually_falls_below_one(self):
        """Row 4's evidence: a real cumulative speed= that crosses 1.0 and stays.

        Every number here is READ FROM THE CAPTURE. The capture is a timing
        measurement -- record count, the values themselves and the crossing
        index all move between machines and runs -- so this asserts the shape
        the fixture must have, never a digit a previous run happened to produce.
        """
        values = [float(SPEED_RE.search(l).group(1)) for l in progress_lines("slow-trickle")]
        self.assertGreaterEqual(len(values), 20, f"too few records to show a crossing: {len(values)}")
        self.assertGreater(values[0], 5.0, "capture should start with a front-loaded lead")
        self.assertLess(values[-1], 1.0, "capture should end below 1.0")

        below = [i for i, v in enumerate(values) if v < 1.0]
        self.assertTrue(below, "capture never crosses below 1.0")
        # Sustained, not a single dip: from the first index after which every
        # remaining value stays under 1.0, there must be a real tail.
        settled = len(values)
        while settled > 0 and values[settled - 1] < 1.0:
            settled -= 1
        self.assertGreaterEqual(
            len(values) - settled, 5, f"crossing is not sustained; tail = {values[settled:]}"
        )
        self.assertGreater(settled, 0, "capture starts below 1.0; there is no lead to burn off")

    def test_the_truncation_corpus_carries_a_scientific_notation_speed(self):
        """The shape behind #227 -- the exponent, not the mantissa."""
        line = progress_lines("truncation")[0]
        self.assertRegex(line, r"speed=\s*[0-9.]+e[+-][0-9]+x")
        self.assertIn("Error during demuxing", load("truncation").decode("utf-8", "replace"))

    def test_the_stand_in_replays_the_corpus_to_stderr_in_order(self):
        records = progress_lines("slow-trickle")
        first, last = records[0].encode(), records[-1].encode()
        with FakeUpstream() as upstream, StandInBin(
            stderr_corpus="slow-trickle", stderr_interval=0.0
        ):
            proc = posix_spawn_proc(["ffmpeg", "-i", upstream.url])
            try:
                seen = _read_until(proc.stderr, last, timeout=10)
            finally:
                proc.terminate()
                proc.wait(timeout=5)
        self.assertIn(b"ffmpeg version ", seen)
        self.assertIn(first, seen)
        self.assertIn(last, seen)
        self.assertLess(seen.index(first), seen.index(last), "records out of order")

    def test_stderr_interval_paces_the_replay(self):
        """A test buys the corpus's shape at its own cadence, not ffmpeg's 38 seconds."""
        with FakeUpstream() as upstream, StandInBin(
            stderr_corpus="normal", stderr_interval=0.05
        ):
            started = time.monotonic()
            proc = posix_spawn_proc(["ffmpeg", "-i", upstream.url])
            try:
                seen = b""
                deadline = time.monotonic() + 10
                while seen.count(b"speed=") < 3:
                    chunk = _read_ready(proc.stderr, 4096, deadline)
                    if not chunk:
                        break
                    seen += chunk
                elapsed = time.monotonic() - started
            finally:
                proc.terminate()
                proc.wait(timeout=5)
        self.assertGreaterEqual(elapsed, 0.10, "three records arrived faster than 2 intervals")
        self.assertLess(elapsed, 5.0, "replay is not being paced by stderr_interval")

    def test_exit_after_bytes_ends_the_process_with_the_given_code(self):
        with FakeUpstream() as upstream, StandInBin(
            exit_after_bytes=4 * TS_PACKET_SIZE, exit_code=3
        ):
            proc = posix_spawn_proc(["ffmpeg", "-i", upstream.url])
            body = _read_exactly(proc.stdout, 4 * TS_PACKET_SIZE)
            self.assertEqual(proc.wait(timeout=10), 3)
        self.assertEqual(len(body), 4 * TS_PACKET_SIZE)

    def test_dead_air_after_bytes_stops_output_without_exiting(self):
        with FakeUpstream() as upstream, StandInBin(dead_air_after_bytes=2 * TS_PACKET_SIZE):
            proc = posix_spawn_proc(["ffmpeg", "-i", upstream.url])
            try:
                body = _read_exactly(proc.stdout, 2 * TS_PACKET_SIZE)
                self.assertEqual(len(body), 2 * TS_PACKET_SIZE)
                time.sleep(0.5)
                self.assertIsNone(proc.poll(), "stand-in exited; dead air must keep it alive")
            finally:
                proc.terminate()
                proc.wait(timeout=5)

    def test_the_production_parameter_string_works_end_to_end(self):
        """The exact command 2a-4 must drive: -i URL, then flags, then pipe:1.

        This is the regression test for the `-i` branch's position in `_parse`.
        With the generic `startswith("-")` branch first, `-i` is swallowed, the
        URL lands in `positional`, and the fallback picks `positional[-1]` --
        `pipe:1` -- so the child dies on `urlopen("pipe:1")` before writing a
        byte. A bare `["ffmpeg", "-i", url]` cannot catch that, because there
        the last positional IS the url.
        """
        with FakeUpstream() as upstream, StandInBin():
            proc = posix_spawn_proc([
                "ffmpeg", "-i", upstream.url,
                "-c:v", "copy", "-c:a", "copy", "-f", "mpegts", "pipe:1",
            ])
            try:
                body = _read_exactly(proc.stdout, 8 * TS_PACKET_SIZE)
            finally:
                proc.terminate()
                proc.wait(timeout=5)
        self.assertEqual(len(body), 8 * TS_PACKET_SIZE, "child produced no bytes")
        assert_ts_aligned(body)

    def test_pipe_0_reads_stdin(self):
        """`-i pipe:0` copies stdin to stdout -- what the fMP4 and Output
        Profile managers need from their child (2a-6)."""
        payload = synthetic_ts(packets=8)
        with StandInBin():
            proc = posix_spawn_proc([
                "ffmpeg", "-f", "mpegts", "-i", "pipe:0", "-c", "copy", "-f", "mp4", "pipe:1",
            ])
            try:
                proc.stdin.write(payload)
                proc.stdin.flush()
                body = _read_exactly(proc.stdout, len(payload))
            finally:
                proc.terminate()
                proc.wait(timeout=5)
        self.assertEqual(body, payload)

    def test_terminate_reaps_the_child(self):
        with FakeUpstream() as upstream, StandInBin():
            proc = posix_spawn_proc(["ffmpeg", "-i", upstream.url])
            _read_exactly(proc.stdout, TS_PACKET_SIZE)
            pid = proc.pid
            proc.terminate()
            self.assertEqual(proc.wait(timeout=5), -signal.SIGTERM)
        with self.assertRaises(OSError):
            os.kill(pid, 0)
