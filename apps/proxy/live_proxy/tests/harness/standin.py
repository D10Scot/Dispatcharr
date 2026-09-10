"""The stand-in program. Runs as a SEPARATE PROCESS -- imports nothing from this
repository, and must keep it that way.

It is a deliberately dumb pipe: fetch the URL it is given, copy the body to
stdout, and write a scripted sequence of lines to stderr. That is precisely the
contract input/manager.py has with ffmpeg -- stdout is dup2'd onto the pipe the
manager reads as self.socket, stderr is a pipe the stderr-reader thread drains
(input/manager.py:793-803, :904) -- so the relay cannot tell the difference,
while the test gets exact control of what the child says and when it stops.

Everything it writes to stderr is a REAL ffmpeg capture replayed from a corpus
fixture (harness/fixtures/ffmpeg_stderr/, captured by
scripts/capture_ffmpeg_stderr.py). It writes the preamble immediately and then
one progress record per --stderr-interval, so a test buys the corpus's real
shape at its own cadence instead of ffmpeg's wall clock. Nothing here invents a
progress line: see harness/ffmpeg_stderr.SYNTHETIC for the one place an
exception may be declared, and why each one is unavoidable.

The input is the value after `-i`, exactly as ffmpeg reads it, falling back to
the last positional when no `-i` is present. `pipe:0` means "read stdin", which
is how the fMP4 and Output Profile managers feed their child. Every other flag
ffmpeg would take is accepted and ignored, so the PRODUCTION parameter string
(`-i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1`) works unchanged --
which it must, because 2a-4 drives exactly that.

Arguments:

  --stderr-corpus PATH   the captured .stderr file to replay
  --stderr-interval S    seconds between progress records (default 0.05); the
                         preamble is always written immediately
  --stderr-loop          restart the corpus when it runs out, instead of going
                         quiet -- for a test that must outlive the capture
  --exit-after-bytes N   exit after copying N bytes
  --exit-code N          the code to exit with (default 0)
  --dead-air-after-bytes N
                         stop writing after N bytes but stay alive
"""

import os
import sys
import threading
import time
import urllib.request

_COPY_CHUNK = 8192


class _StdinSource:
    """Makes stdin look like the object urlopen returns: .read() and .close()."""

    def read(self, count):
        return os.read(0, count)

    def close(self):
        pass


def _parse(argv):
    options = {
        "input": None,
        "stderr_corpus": None,
        "stderr_interval": 0.05,
        "stderr_loop": False,
        "exit_after_bytes": None,
        "exit_code": 0,
        "dead_air_after_bytes": None,
    }
    positional = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--stderr-corpus":
            options["stderr_corpus"] = argv[i + 1]
            i += 2
        elif arg == "--stderr-interval":
            options["stderr_interval"] = float(argv[i + 1])
            i += 2
        elif arg == "--stderr-loop":
            options["stderr_loop"] = True
            i += 1
        elif arg == "--exit-after-bytes":
            options["exit_after_bytes"] = int(argv[i + 1])
            i += 2
        elif arg == "--exit-code":
            options["exit_code"] = int(argv[i + 1])
            i += 2
        elif arg == "--dead-air-after-bytes":
            options["dead_air_after_bytes"] = int(argv[i + 1])
            i += 2
        elif arg == "-i":
            # ffmpeg's own input flag. The value after it is the input, and this
            # branch MUST stay above the generic `startswith("-")` one below:
            # `-i` starts with a dash, so the generic branch would swallow it,
            # push the URL into `positional`, and leave the fallback to pick
            # `positional[-1]` -- which against the production parameter string
            # (`-i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1`) is
            # `pipe:1`, and `urlopen("pipe:1")` raises
            # `URLError: unknown url type: pipe`. That ordering bug shipped once
            # and passed the smoke test by coincidence, because with a bare
            # `-i URL` the last positional happens to BE the URL; the two tests
            # named in Step 3 exist so it cannot happen again.
            options["input"] = argv[i + 1]
            i += 2
        elif arg.startswith("-"):
            # Anything else -- ffmpeg's own flags, whatever the StreamProfile's
            # parameters carry -- is accepted and ignored, exactly so a test can
            # use a realistic parameter string.
            i += 1
        else:
            positional.append(arg)
            i += 1
    if options["input"] is None and positional:
        options["input"] = positional[-1]
    return options, positional


def _pump_stderr(path, interval, loop):
    """Replay a captured ffmpeg stderr stream: preamble at once, then one
    progress record per `interval`.

    Not a byte-exact replay of what the relay's stderr reader saw from the
    real process -- see the comment at the write site below for what differs
    and why. os.write on fd 2 rather than sys.stderr because the records carry
    no newline and text-mode buffering would hold them.
    """
    with open(path, "rb") as handle:
        raw = handle.read()

    # Same split as harness/ffmpeg_stderr.split(), duplicated because this file
    # runs as a separate process and imports nothing from the repository.
    # Records are CR-TERMINATED, and a capture may end its last one with LF, so
    # both count as terminators -- exactly as input/manager.py's _read_stderr
    # treats them.
    lines = raw.replace(b"\r", b"\n").split(b"\n")
    records = [line for line in lines if b"speed=" in line]
    preamble = raw[: raw.index(records[0])] if records else raw

    os.write(2, preamble)
    while True:
        for record in records:
            if interval:
                time.sleep(interval)
            try:
                # Terminated, not prefixed. Faithful for every record a real
                # ffmpeg writes except its LAST, which a gracefully-exiting
                # ffmpeg terminates with LF and follows with its epilogue
                # ("Exiting normally, received signal 15."). Replaying every
                # record CR-terminated and dropping the epilogue is deliberate:
                # the replay loops, so there is no "last" record, and
                # _read_stderr splits on either terminator anyway. Not
                # byte-exact, and no test asserts that it is.
                os.write(2, record + b"\r")
            except OSError:
                return
        if not loop:
            return


def main(argv=None):
    options, positional = _parse(sys.argv[1:] if argv is None else argv)
    source = options["input"]
    if not source:
        sys.stderr.write("stand-in: no input; expected `-i <url>` or a positional\n")
        return 2

    if options["stderr_corpus"]:
        threading.Thread(
            target=_pump_stderr,
            args=(options["stderr_corpus"], options["stderr_interval"], options["stderr_loop"]),
            daemon=True,
        ).start()

    copied = 0
    dead_air_at = options["dead_air_after_bytes"]
    exit_at = options["exit_after_bytes"]

    if source == "pipe:0":
        # The Output Profile and fMP4 managers feed their child on stdin
        # (output/fmp4/manager.py's FFMPEG_REMUX_CMD is `-f mpegts -i pipe:0`),
        # so the stand-in has to be able to be that child too. 2a-6 needs this.
        response = _StdinSource()
    else:
        response = urllib.request.urlopen(source, timeout=30)
    try:
        while True:
            chunk = response.read(_COPY_CHUNK)
            if not chunk:
                break
            if exit_at is not None and copied + len(chunk) >= exit_at:
                os.write(1, chunk[: exit_at - copied])
                return options["exit_code"]
            if dead_air_at is not None and copied + len(chunk) >= dead_air_at:
                os.write(1, chunk[: dead_air_at - copied])
                # Alive, connected, producing nothing -- what the relay's
                # dead-air watchdog is for.
                while True:
                    time.sleep(1)
            os.write(1, chunk)
            copied += len(chunk)
    except (BrokenPipeError, OSError):
        return options["exit_code"]
    finally:
        response.close()
    return options["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
