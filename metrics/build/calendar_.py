"""Daily resampling and the status rule (spec S6, stage 3 and the status rule).

Module name carries a trailing underscore because `calendar` is a stdlib
module and the test runner puts `metrics/build` first on `sys.path`.
"""

from __future__ import annotations

import datetime as dt

from load import SnapshotRow, pointer

UTC = dt.timezone.utc


def daily_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    """Every date from start to end, inclusive."""
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def snapshot_series(rows: list[SnapshotRow], ptr: str) -> list[tuple[dt.datetime, str, float]]:
    """Per-commit points `(timestamp, sha, value)` for the given JSON-pointer
    metric, skipping rows where the pointer is missing or the value isn't
    numeric (bool is excluded even though it's an int subclass)."""
    out = []
    for r in rows:
        v = pointer(r.metrics, ptr)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append((r.timestamp, r.commit_sha, float(v)))
    return out


def forward_fill(points: list[tuple[dt.datetime, float]], dates: list[dt.date]) -> list[float | None]:
    """The last value at or before each day's end, `None` before the first
    point. `points` need not be pre-sorted. A day is the half-open interval
    `[day 00:00Z, day+1 00:00Z)` rather than closing at `23:59:59` — a
    snapshot timestamp carries microseconds (e.g. `23:59:59.5Z`), and a
    literal `23:59:59` boundary would push such a point into the next day,
    dropping it entirely when that day is outside the requested range."""
    pts = sorted(points, key=lambda p: p[0])
    out: list[float | None] = []
    i = 0
    last: float | None = None
    for day in dates:
        next_day_start = dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min, tzinfo=UTC)
        while i < len(pts) and pts[i][0] < next_day_start:
            last = pts[i][1]
            i += 1
        out.append(last)
    return out


def _at_target(direction: str, target: float | None, value: float) -> bool:
    if direction == "zero":
        return value == 0
    if target is None:
        return False
    return value <= target if direction == "down" else value >= target


def status(direction: str, target: float | None, now: float | None, prev: float | None, stale: bool) -> str:
    """`good` at target or moved toward it since the previous milestone;
    `bad` moved away, or stalled with an unmet target; `neutral` for `info`,
    for a missing current value, or a stall with no target to miss; `stale`
    when the caller says so (`is_stale`/`snapshot_is_stale` upstream) —
    `stale` overrides every other outcome."""
    if stale:
        return "stale"
    if direction == "info" or now is None:
        return "neutral"
    if _at_target(direction, target, now):
        return "good"
    if prev is None:
        return "neutral"
    toward = now < prev if direction in ("down", "zero") else now > prev
    away = now > prev if direction in ("down", "zero") else now < prev
    if toward:
        return "good"
    if away:
        return "bad"
    return "bad" if (target is not None or direction == "zero") else "neutral"


def delta_is_good(direction: str, delta: float) -> bool | None:
    """Whether a change of `delta` is an improvement for `direction`.
    `None` for `info` series (no notion of good/bad) or a zero delta (no
    change to judge). `zero` direction means the implicit target is 0, so a
    negative delta is good just like `down`."""
    if direction == "info" or delta == 0:
        return None
    return delta < 0 if direction in ("down", "zero") else delta > 0


def is_stale(last_real: dt.datetime | None, today: dt.date, max_age_days: int = 2) -> bool:
    """Age-based freshness for event-dump-derived series, and for the
    once-daily `coverage` family (R26/R27): stale when the series' last real
    point is more than `max_age_days` old, or there is no real point at all.
    NOT the rule for the other SNAPSHOT families (code_health, architecture,
    tests) — those are keyed by commit sha, not date, so a quiet week with no
    new commit produces no new row without the pipeline being unhealthy; use
    `snapshot_is_stale` for those instead."""
    if last_real is None:
        return True
    return (today - last_real.date()).days > max_age_days


def snapshot_is_stale(latest_row_sha: str | None, head_sha: str | None) -> bool:
    """Freshness for SNAPSHOT families (R26): a row exists for the current
    first-parent HEAD of main. Snapshot rows are keyed by commit sha, not
    by calendar date, so `is_stale`'s age rule would wrongly flag a healthy
    but quiet pipeline as stale. Fresh iff both `latest_row_sha` and
    `head_sha` are non-empty full 40-character commit SHAs and are exactly
    equal; anything else — no rows at all, no resolvable HEAD, or a mismatch
    — is stale. Guards against `None == None`/`"" == ""` reading as a match
    when either side genuinely has no sha to compare."""
    if not latest_row_sha or not head_sha:
        return True
    return latest_row_sha != head_sha
