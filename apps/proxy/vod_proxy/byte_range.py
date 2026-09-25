"""Byte-range arithmetic for the VOD proxy (RFC 9110 section 14).

Pure functions, no Django and no Redis, so every rule here is unit-testable
without a session. ``stream_content_with_session`` uses them to decide what
the client is told; the rule they enforce is that the client-facing status,
``Content-Range`` and ``Content-Length`` always describe the bytes actually
sent (#64, #66).
"""

from dataclasses import dataclass
from typing import Iterable, Iterator, Optional, Tuple, Union


class _Unsatisfiable:
    def __repr__(self):
        return "UNSATISFIABLE"


UNSATISFIABLE = _Unsatisfiable()

ResolvedRange = Union[None, _Unsatisfiable, Tuple[int, int]]


def _digits(value: str) -> bool:
    """ASCII digits only. ``str.isdigit()`` is also true for "²" and "³",
    which ``int()`` rejects, and WSGI decodes headers as Latin-1, so a bare
    ``isdigit()`` guard would turn ``Range: bytes=²-`` into a 500."""
    return value.isascii() and value.isdigit()


def parse_length(value) -> Optional[int]:
    """A non-negative integer from a header or stored field, else ``None``."""
    if value is None:
        return None
    text = str(value)
    return int(text) if _digits(text) else None


def resolve_range(range_header: Optional[str], total: int) -> ResolvedRange:
    """Resolve a single ``bytes=`` range against a representation of ``total`` bytes.

    Returns ``(start, end)`` inclusive; ``UNSATISFIABLE`` when the range
    selects no byte of the representation; or ``None`` when the header is
    absent or is not a single byte range this proxy understands, in which
    case the Range is ignored and the whole representation is served (RFC
    9110 section 14.2 permits a server to ignore Range).
    """
    if not range_header or not range_header.startswith("bytes="):
        return None
    spec = range_header[len("bytes="):].strip()
    if "," in spec or "-" not in spec:
        return None
    first, last = spec.split("-", 1)
    if first == "":
        # Suffix form: the final N bytes (#64). bytes=-0 selects nothing.
        if not _digits(last):
            return None
        length = int(last)
        if length == 0 or total <= 0:
            return UNSATISFIABLE
        return max(0, total - length), total - 1
    if not _digits(first):
        return None
    start = int(first)
    if last == "":
        end = total - 1
    elif _digits(last):
        if int(last) < start:
            return UNSATISFIABLE
        end = min(int(last), total - 1)
    else:
        return None
    if start >= total:
        return UNSATISFIABLE
    return start, end


def parse_content_range(value: Optional[str]) -> Optional[Tuple[int, int, Optional[int]]]:
    """Parse ``bytes START-END/TOTAL`` (TOTAL may be ``*``) into a valid triple.

    Returns ``None`` for anything that does not describe a real range:
    missing, the ``bytes */TOTAL`` form, non-numeric, END < START, or
    END >= TOTAL.
    """
    if not value or not value.startswith("bytes "):
        return None
    body = value[len("bytes "):].strip()
    if "/" not in body:
        return None
    span, total_part = body.rsplit("/", 1)
    if "-" not in span:
        return None
    first, last = span.split("-", 1)
    if not (_digits(first) and _digits(last)):
        return None
    if total_part != "*" and not _digits(total_part):
        return None
    start, end = int(first), int(last)
    total = None if total_part == "*" else int(total_part)
    if end < start or (total is not None and end >= total):
        return None
    return start, end, total


@dataclass(frozen=True)
class DownstreamPlan:
    """What the client is told, and how the upstream body is cut to match it."""

    status: int
    content_range: Optional[str] = None
    content_length: Optional[int] = None
    skip: int = 0
    limit: Optional[int] = None
    start: Optional[int] = None
    total: Optional[int] = None
    unsatisfiable: bool = False


def plan_downstream(
    client_range: Optional[str],
    upstream_status: int,
    upstream_content_range: Optional[str],
    upstream_content_length,
    known_total: Optional[int],
) -> DownstreamPlan:
    """Decide the client-facing status and length headers from what the upstream sent.

    - No client Range: 200, the whole representation.
    - Upstream 206 with a valid Content-Range: relay that range verbatim.
    - Upstream 200 to a Range request (Range ignored, #66): cut the body to
      the requested range so the 206 we send is true.
    """
    upstream_length = parse_length(upstream_content_length)
    if not client_range:
        return DownstreamPlan(status=200, content_length=known_total if known_total is not None else upstream_length)

    if upstream_status == 206:
        parsed = parse_content_range(upstream_content_range)
        if parsed is not None:
            start, end, total = parsed
            total = total if total is not None else known_total
            return DownstreamPlan(
                status=206,
                content_range=f"bytes {start}-{end}/{total if total is not None else '*'}",
                content_length=end - start + 1,
                start=start,
                total=total,
            )
        # A 206 with no usable Content-Range: the provider broke the protocol.
        # Describe the range we asked for when the size is known, else say
        # nothing rather than something false.
        resolved = resolve_range(client_range, known_total) if known_total else None
        if isinstance(resolved, tuple):
            start, end = resolved
            return DownstreamPlan(
                status=206,
                content_range=f"bytes {start}-{end}/{known_total}",
                content_length=end - start + 1,
                start=start,
                total=known_total,
            )
        return DownstreamPlan(status=206, content_length=upstream_length)

    if upstream_status == 200:
        total = upstream_length if upstream_length is not None else known_total
        if total is None:
            # Nothing to cut against: pass the whole body through honestly.
            return DownstreamPlan(status=200)
        resolved = resolve_range(client_range, total)
        if resolved is None:
            return DownstreamPlan(status=200, content_length=total)
        if resolved is UNSATISFIABLE:
            return DownstreamPlan(status=416, total=total, unsatisfiable=True)
        start, end = resolved
        return DownstreamPlan(
            status=206,
            content_range=f"bytes {start}-{end}/{total}",
            content_length=end - start + 1,
            skip=start,
            limit=end - start + 1,
            start=start,
            total=total,
        )

    return DownstreamPlan(status=upstream_status, content_length=upstream_length)


def slice_chunks(chunks: Iterable[bytes], skip: int, limit: Optional[int]) -> Iterator[bytes]:
    """Drop the first ``skip`` bytes of ``chunks`` and stop after ``limit`` more."""
    for chunk in chunks:
        if not chunk:
            continue
        if skip:
            if len(chunk) <= skip:
                skip -= len(chunk)
                continue
            chunk = chunk[skip:]
            skip = 0
        if limit is not None:
            if len(chunk) >= limit:
                yield chunk[:limit]
                return
            limit -= len(chunk)
        yield chunk
