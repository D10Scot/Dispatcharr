"""Read the metrics-data branch: snapshot rows and event dumps.

Snapshot rows are one JSON object per line in `<family>.jsonl` at the top of
the data directory. Event dumps are a full-state JSON envelope per kind under
`events/<kind>.json`, unioned with a `events/history/<kind>.jsonl` sidecar
that accumulates one line per new-or-changed projection over time (so a
record retired from the live API — an alert that's aged out, a closed PR
past the API's window — is not lost).
"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import json
from pathlib import Path

# security/delivery/agentic were retired before this loader was written;
# their *.jsonl files still exist on the metrics-data branch and must be
# skipped rather than surfaced as unknown families.
RETIRED_FAMILIES = {"security", "delivery", "agentic"}


def _record_key(kind: str, record: dict) -> str:
    # scripts/metrics/collect_events.py's project_* functions always
    # normalize the source-specific identifier (GitHub's issue/PR "number",
    # a workflow run's "id", a Scorecard row's "date") into a single "id"
    # field before a record is written to either the dump or the sidecar —
    # that projection is the source of truth, not this loader. No record on
    # the live metrics-data branch carries a bare "number" field, so keying
    # on anything but "id" here would silently fail to match dump records to
    # their sidecar history. Missing "id" is a bug in the collector's
    # projection, not a shape we should merge around: raise loudly.
    try:
        return str(record["id"])
    except KeyError:
        raise KeyError(f"event '{kind}' record has no 'id': {record!r}") from None


def parse_ts(value: str) -> dt.datetime:
    """Parse an ISO-8601 timestamp with a 'Z' suffix, a numeric UTC offset, or
    no offset at all, returning a UTC-aware datetime. GitHub's API emits 'Z';
    our own 'fetched_at'/'seen_at' emit '+00:00'. A naive value (no offset)
    is treated as already being UTC, not the host's local timezone —
    `datetime.astimezone()` on a naive value assumes local time, which would
    silently shift a naive timestamp by the build host's UTC offset."""
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


@dc.dataclass
class SnapshotRow:
    timestamp: dt.datetime
    commit_sha: str
    family: str
    metrics: dict


@dc.dataclass
class Dump:
    kind: str
    fetched_at: dt.datetime | None
    status: str
    detail: str | None
    records: list[dict]


def load_snapshots(data_dir: Path) -> dict[str, list[SnapshotRow]]:
    """Every `*.jsonl` at the top level of `data_dir`, keyed by family
    (the filename stem), sorted by timestamp. Retired families are dropped."""
    out: dict[str, list[SnapshotRow]] = {}
    for path in sorted(data_dir.glob("*.jsonl")):
        family = path.stem
        if family in RETIRED_FAMILIES:
            continue
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            rows.append(SnapshotRow(
                parse_ts(raw["timestamp"]), raw["commit_sha"], raw.get("family", family), raw["metrics"],
            ))
        rows.sort(key=lambda r: r.timestamp)
        out[family] = rows
    return out


def load_events(data_dir: Path) -> dict[str, Dump]:
    """Union of `events/<kind>.json` (the current full-state dump) and
    `events/history/<kind>.jsonl` (the append-only sidecar), current record
    winning on conflict. A kind with only a sidecar yields status
    "history_only"; a kind with neither is absent from the result. A dump
    with a non-ok status carries no records of its own (the source already
    empties `records` in that case), so the merge naturally falls back to
    "use the sidecar alone" with no special-casing here."""
    events_dir = data_dir / "events"
    history_dir = events_dir / "history"
    kinds = {p.stem for p in events_dir.glob("*.json")} | {p.stem for p in history_dir.glob("*.jsonl")}
    out: dict[str, Dump] = {}
    for kind in sorted(kinds):
        merged: dict[str, dict] = {}
        sidecar = history_dir / f"{kind}.jsonl"
        if sidecar.is_file():
            for line in sidecar.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                # One line per new-or-changed projection; the same id can
                # appear more than once and the LAST line wins, which a plain
                # dict assignment in file order already gives us.
                merged[str(row["id"])] = row["record"]
        current = events_dir / f"{kind}.json"
        if current.is_file():
            env = json.loads(current.read_text(encoding="utf-8"))
            for rec in env.get("records", []):
                merged[_record_key(kind, rec)] = rec
            fetched_at = parse_ts(env["fetched_at"]) if env.get("fetched_at") else None
            out[kind] = Dump(kind, fetched_at, env.get("status", "ok"), env.get("detail"), list(merged.values()))
        else:
            out[kind] = Dump(kind, None, "history_only", None, list(merged.values()))
    return out


def pointer(metrics: dict, ptr: str):
    """JSON-pointer lookup (`/a/b`); `None` if any segment is missing."""
    node = metrics
    for part in ptr.strip("/").split("/"):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node
