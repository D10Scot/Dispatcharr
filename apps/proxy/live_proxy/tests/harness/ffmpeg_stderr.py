"""Access to the captured real-ffmpeg stderr corpus.

The fixtures under fixtures/ffmpeg_stderr/ are verbatim captures from
ffmpeg 8.1.2 -- see that directory's CAPTURE.md and
scripts/capture_ffmpeg_stderr.py. Never hand-edit them: the whole point is
that no line in them was written by us. Where a shape is needed that a real
ffmpeg cannot be made to emit on demand, add it to SYNTHETIC below WITH the
reason, so the exception is visible rather than mixed into the corpus.
"""

import os

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "ffmpeg_stderr")

CORPUS_NAMES: tuple[str, ...] = ("normal", "slow-trickle", "truncation")

# Lines real ffmpeg will not produce to order. Empty today, and every future
# entry needs the "why real ffmpeg cannot" half of its reason, not just a
# description of the shape.
SYNTHETIC: dict[str, tuple[str, str]] = {}


def path(name: str) -> str:
    if name not in CORPUS_NAMES:
        raise ValueError(f"unknown corpus {name!r}; expected one of {', '.join(CORPUS_NAMES)}")
    return os.path.join(FIXTURES, f"{name}.stderr")


def load(name: str) -> bytes:
    """The capture, byte for byte, CR separators included."""
    with open(path(name), "rb") as handle:
        return handle.read()


def split(name: str) -> tuple[bytes, list[bytes]]:
    """(preamble, progress records), split the way the relay itself splits.

    Two things about the real byte stream, both verified against the captures
    rather than assumed, and both of which a naive `split(b"\r")` gets wrong:

    1. ffmpeg **terminates** a progress record with CR, it does not precede one.
       So `capture.split(b"\r")[0]` is the preamble AND record 1 stuck together,
       and every record index after that is off by one.
    2. A capture whose process exited **gracefully** ends its last record with
       LF, not CR -- `truncation.stderr` contains **zero** CR bytes, because its
       one and only record is the final `Lsize=` line. This holds for a SIGTERM
       too, not just a clean end of input: `normal` and `slow-trickle` were both
       SIGTERMed, log "Exiting normally, received signal 15.", and still end LF.
       So CR == records - 1 for every capture here; only a SIGKILL landing
       mid-record could leave CR == records, which this split also handles.
       Anything treating CR as the sole separator finds no records in
       `truncation` at all.

    `input/manager.py`'s `_read_stderr` takes whichever of CR or LF comes first
    as the line terminator, so splitting on both is not a convenience here --
    it is what the code under test does. A record is then any line carrying
    `speed=`, and the preamble is everything before the first one.
    """
    raw = load(name)
    lines = raw.replace(b"\r", b"\n").split(b"\n")

    records = [line for line in lines if b"speed=" in line]
    if not records:
        return raw, []

    first = raw.index(records[0])
    return raw[:first], records


def progress_lines(name: str) -> list[str]:
    """The progress records as text, for assertions about speed=/time=/bitrate=."""
    return [record.decode("utf-8", "replace") for record in split(name)[1]]
