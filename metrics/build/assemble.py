"""Assemble site.json from snapshots, event dumps and the curated files."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from calendar_ import daily_dates, delta_is_good, forward_fill, is_stale, snapshot_is_stale, snapshot_series, status
from curated import Curated, Metric
from derive import DERIVATION_SOURCES, DERIVATIONS, Context
from gitinfo import commit_date, first_parent_shas
from load import load_events, load_snapshots

SPARK_POINTS = 30


def _iso(d: dt.date) -> str:
    return d.isoformat()


def _series_for(m: Metric, snapshots, ctx: Context, dates: list[dt.date], today: dt.date):
    """Return (daily values, commit points or None, last_real datetime or None)."""
    if m.family == "derived":
        fn = DERIVATIONS[m.derivation]
        daily = [fn(ctx, d, m.params) if d >= m.since else None for d in dates]
        # R9(c): freshness comes from DERIVATION_SOURCES, keyed by derivation
        # name to the event kinds it actually reads - NOT name-prefix
        # matching, which drifts the moment a new derivation is added.
        kinds = DERIVATION_SOURCES.get(m.derivation, ())
        if not kinds:
            # Ledger-derived (defects_by_status): no event dump backs it, it
            # reads the curated defect ledger that is part of every build's
            # own inputs, so it is always fresh as of "today".
            last_real = dt.datetime.combine(today, dt.time.min, tzinfo=dt.timezone.utc)
        else:
            fetched = [ctx.events[k].fetched_at for k in kinds if k in ctx.events and ctx.events[k].fetched_at]
            last_real = max(fetched) if fetched else None
        return daily, None, last_real
    rows = snapshots.get(m.family, [])
    points = snapshot_series(rows, m.path)
    daily = forward_fill([(t, v) for t, _, v in points], dates)
    daily = [v if d >= m.since else None for d, v in zip(dates, daily)]
    commits = [[sha, t.isoformat(), v] for t, sha, v in points]
    last_real = points[-1][0] if points else None
    return daily, commits, last_real


def _value_at(daily: list, dates: list[dt.date], day: dt.date):
    if day < dates[0]:
        return None
    idx = min((day - dates[0]).days, len(dates) - 1)
    return daily[idx]


def build_site(data_dir: Path, curated: Curated, *, repo: Path, base: str, today: dt.date, ref: str = "main") -> dict:
    snapshots = load_snapshots(data_dir)
    events = load_events(data_dir)
    ctx = Context(events=events, defects=curated.defects)
    base_date = commit_date(repo, base).date()
    dates = daily_dates(base_date, today)
    # R26: SNAPSHOT-family freshness is "does the family have a row for the
    # repo's current first-parent HEAD", not a calendar-age check - a quiet
    # week with no new commits is a healthy pipeline, not a stale one.
    head_sha = first_parent_shas(repo, base, ref)[-1]

    milestones = []
    for m in curated.milestones:
        d = commit_date(repo, m.sha)
        milestones.append({"sha": m.sha, "date": _iso(d.date()), "label": m.label, "kind": m.kind,
                           "phase": m.phase, "pr": m.pr, "summary": m.summary})
    milestones.sort(key=lambda x: x["date"])
    milestone_days = [dt.date.fromisoformat(x["date"]) for x in milestones]

    groups: dict[str, list[dict]] = {}
    series_by_id: dict[str, dict] = {}
    for m in curated.catalogue:
        daily, commits, last_real = _series_for(m, snapshots, ctx, dates, today)
        if m.since > today:
            # Nothing is expected yet - don't flag a series that hasn't
            # started as stale.
            stale = False
        elif m.family == "derived":
            stale = is_stale(last_real, today)
        else:
            rows = snapshots.get(m.family, [])
            latest_row_sha = rows[-1].commit_sha if rows else None
            stale = snapshot_is_stale(latest_row_sha, head_sha)
        now = daily[-1]
        # "Previous milestone" is per metric: the last milestone strictly before this
        # series' newest real point, so a milestone that landed with the latest data
        # does not make every metric read as stalled.
        cutoff = last_real.date() if last_real else today
        prev_day = max((d for d in milestone_days if d < cutoff), default=None)
        prev = _value_at(daily, dates, prev_day) if prev_day else None
        entry = {
            "id": m.id, "label": m.label, "unit": m.unit, "direction": m.direction, "target": m.target,
            "group": m.group, "headline": m.headline, "note": m.note,
            "daily": [[_iso(d), v] for d, v in zip(dates, daily)],
            "commits": commits,
            "last_real": last_real.isoformat() if last_real else None,
            "stale": stale,
            "status": status(m.direction, m.target, now, prev, stale),
            "now": now,
            "at_baseline": next((v for v in daily if v is not None), None),
            "at_prev_milestone": prev,
        }
        groups.setdefault(m.group, []).append(entry)
        series_by_id[m.id] = entry

    headline = [dict(e, spark=[v for _, v in e["daily"][-SPARK_POINTS:]]) for e in series_by_id.values() if e["headline"]]

    phases = []
    for p in curated.phases:
        own = [x for x in milestones if x["phase"] == p.id]
        starts = [x["date"] for x in own if x["kind"] == "phase-start"] or [x["date"] for x in own]
        ends = [x["date"] for x in own if x["kind"] == "phase-done"]
        phases.append({"id": p.id, "label": p.label, "summary": p.summary, "headline_ids": p.headline_ids,
                       "start": min(starts) if starts else None, "end": max(ends) if ends else None, "milestones": own})

    def compare(sha_a: str, sha_b: str) -> list[dict]:
        rows = []
        for e in series_by_id.values():
            if not e["commits"]:
                continue
            by_sha = {c[0]: c[2] for c in e["commits"]}
            if sha_a not in by_sha or sha_b not in by_sha:
                continue
            delta = by_sha[sha_b] - by_sha[sha_a]
            rows.append({"id": e["id"], "group": e["group"], "label": e["label"], "unit": e["unit"], "direction": e["direction"],
                         "from": by_sha[sha_a], "to": by_sha[sha_b], "delta": delta, "good": delta_is_good(e["direction"], delta)})
        return rows

    compare_pairs = [(a["sha"], b["sha"]) for a, b in zip(milestones, milestones[1:])]
    latest_sha = None
    latest_ts = None
    for rows in snapshots.values():
        if rows and (latest_sha is None or rows[-1].timestamp > latest_ts):
            latest_sha, latest_ts = rows[-1].commit_sha, rows[-1].timestamp
    if latest_sha and milestones and (milestones[0]["sha"], latest_sha) not in compare_pairs:
        compare_pairs.append((milestones[0]["sha"], latest_sha))
    compare_section = {f"{a}..{b}": compare(a, b) for a, b in compare_pairs}

    by_status_daily = [[_iso(d), {s: DERIVATIONS["defects_by_status"](ctx, d, {"status": s}) for s in ("open", "pinned", "carried", "fixed")}] for d in dates]
    defects = {"entries": [vars(d) | {"first_seen": _iso(d.first_seen), "status_changed": _iso(d.status_changed)} for d in curated.defects],
               "by_status_daily": by_status_daily}

    freshness = {fam: rows[-1].timestamp.isoformat() for fam, rows in snapshots.items() if rows}
    freshness.update({k: v.fetched_at.isoformat() for k, v in events.items() if v.fetched_at})
    notes = [f"{k}: {v.status}" + (f" ({v.detail})" if v.detail else "") for k, v in events.items() if v.status != "ok"]

    return {
        "meta": {"built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "today": _iso(today),
                 "baseline": {"sha": base, "date": _iso(base_date)}, "freshness": freshness, "source_notes": notes,
                 "commit_count": sum(1 for _ in snapshots.get("tests", []))},
        "headline": headline,
        "groups": groups,
        "phases": phases,
        "milestones": milestones,
        "defects": defects,
        "compare": compare_section,
    }
