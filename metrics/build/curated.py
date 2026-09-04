"""The three agent-maintained inputs and their validation.

Schemas are documented for humans and agents in docs/agents/metrics.md; this
module is the executable version. Validation returns every error at once so
one edit-run cycle fixes a whole file.
"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import re
from pathlib import Path
from typing import Any, Callable

import yaml

from gitinfo import is_first_parent_on

# A sentence terminator (. ! ?) followed by whitespace or end of string — used
# to enforce the one-sentence milestone summary rule (spec §5.2).
_SENTENCE_TERM_RE = re.compile(r"[.!?](?=\s|$)")


def _is_one_sentence(text: str) -> bool:
    """True when `text` is non-empty and has no sentence terminator other
    than at most one, positioned at the very end."""
    s = (text or "").strip()
    if not s:
        return False
    matches = list(_SENTENCE_TERM_RE.finditer(s))
    if len(matches) > 1:
        return False
    if len(matches) == 1 and matches[0].end() != len(s):
        return False
    return True

DIRECTIONS = {"up", "down", "zero", "info"}
UNITS = {"count", "pct", "seconds", "days", "score", "lines", "ratio"}
GROUPS = {"safety_net", "security", "extraction", "delivery", "agents"}
MILESTONE_KINDS = {"phase-start", "phase-done", "goal", "incident", "release"}
DEFECT_AREAS = {"security", "correctness", "dead-code", "operational"}
DEFECT_SEVERITIES = {"critical", "high", "medium", "low"}
DEFECT_STATUSES = ("open", "pinned", "carried", "fixed")
# Literal until Task 12 lands derive.py and curated.DERIVATIONS becomes a lazy
# lookup into derive.DERIVATIONS (avoids an import cycle: derive imports
# Defect from this module).
DERIVATIONS = {
    "codeql_open_count", "codeql_oldest_open_age_days", "codeql_fixed_per_week",
    "scorecard_score", "scorecard_check", "ci_pass_rate_30d", "ci_median_wall_time_30d",
    "pr_lead_time_30d", "pr_product_ratio_30d", "prs_merged_30d",
    "issues_open_by_label", "issues_time_to_triage_median_30d", "defects_by_status",
}
ALLOWED_TRANSITIONS = {("open", "pinned"), ("open", "carried"), ("open", "fixed"),
                       ("pinned", "fixed"), ("carried", "fixed")}


@dc.dataclass
class Metric:
    id: str
    family: str
    label: str
    unit: str
    direction: str
    group: str
    headline: bool
    since: dt.date
    note: str
    target: float | None = None
    path: str | None = None
    derivation: str | None = None
    params: dict = dc.field(default_factory=dict)


@dc.dataclass
class Phase:
    id: str
    label: str
    summary: str
    headline_ids: list[str]


@dc.dataclass
class Milestone:
    sha: str
    label: str
    kind: str
    phase: str
    summary: str
    pr: int | None = None


@dc.dataclass
class Defect:
    id: str
    title: str
    area: str
    severity: str
    status: str
    first_seen: dt.date
    status_changed: dt.date
    source: str | None = None
    issue: int | None = None
    test: str | None = None
    fixed_in: int | None = None
    carried_as: str | None = None


@dc.dataclass
class Curated:
    catalogue: list[Metric]
    phases: list[Phase]
    milestones: list[Milestone]
    defects: list[Defect]


def _build(cls, raw: dict, where: str, errors: list[str]):
    fields = {f.name for f in dc.fields(cls)}
    unknown = set(raw) - fields
    if unknown:
        errors.append(f"{where}: unknown fields {sorted(unknown)}")
    kwargs = {k: v for k, v in raw.items() if k in fields}
    for f in dc.fields(cls):
        if f.name not in kwargs and f.default is dc.MISSING and f.default_factory is dc.MISSING:
            errors.append(f"{where}: missing required field '{f.name}'")
            kwargs[f.name] = None
    try:
        return cls(**kwargs)
    except TypeError as exc:
        errors.append(f"{where}: {exc}")
        return None


def _read(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_curated(directory: Path) -> Curated:
    """Load the three files; raises ValueError listing structural problems."""
    errors: list[str] = []
    cat_raw = _read(directory / "catalogue.yml") or []
    ms_raw = _read(directory / "milestones.yml") or {}
    def_raw = _read(directory / "defects.yml") or []
    catalogue = [m for i, r in enumerate(cat_raw) if (m := _build(Metric, r, f"catalogue[{i}]", errors))]
    phases = [p for i, r in enumerate(ms_raw.get("phases", [])) if (p := _build(Phase, r, f"phases[{i}]", errors))]
    milestones = [m for i, r in enumerate(ms_raw.get("milestones", [])) if (m := _build(Milestone, r, f"milestones[{i}]", errors))]
    defects = [d for i, r in enumerate(def_raw) if (d := _build(Defect, r, f"defects[{i}]", errors))]
    if errors:
        raise ValueError("curated files are malformed:\n  " + "\n  ".join(errors))
    return Curated(catalogue, phases, milestones, defects)


def validate(
    c: Curated,
    *,
    repo: Path,
    base: str,
    ref: str = "main",
    pr_checker: Callable[[int], bool | None] | None = None,
    known_families: dict[str, set[str]] | None = None,
) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    for m in c.catalogue:
        w = f"catalogue '{m.id}'"
        if m.id in ids:
            errors.append(f"{w}: duplicate id")
        ids.add(m.id)
        if m.direction not in DIRECTIONS:
            errors.append(f"{w}: direction '{m.direction}' not in {sorted(DIRECTIONS)}")
        if m.unit not in UNITS:
            errors.append(f"{w}: unit '{m.unit}' not in {sorted(UNITS)}")
        if m.group not in GROUPS:
            errors.append(f"{w}: group '{m.group}' not in {sorted(GROUPS)}")
        if m.direction == "zero" and m.target not in (None, 0):
            errors.append(f"{w}: direction zero implies target 0")
        if not isinstance(m.since, dt.date):
            errors.append(f"{w}: since must be a date")
        if m.family == "derived":
            if m.derivation not in DERIVATIONS:
                errors.append(f"{w}: unknown derivation '{m.derivation}'")
        else:
            if not m.path or not m.path.startswith("/"):
                errors.append(f"{w}: path must be a JSON pointer starting with '/'")
            elif known_families is not None and m.headline:
                present = known_families.get(m.family)  # None: the family has no row yet (coverage before its first daily run)
                if present is not None and m.path not in present:
                    errors.append(f"{w}: headline path {m.family}{m.path} does not resolve against the latest row")

    phase_ids = {p.id for p in c.phases}
    for p in c.phases:
        missing = [h for h in p.headline_ids if h not in ids]
        if missing:
            errors.append(f"phase '{p.id}': headline_ids {missing} are not catalogue ids")

    for m in c.milestones:
        w = f"milestone '{m.label}'"
        if m.kind not in MILESTONE_KINDS:
            errors.append(f"{w}: kind '{m.kind}' not in {sorted(MILESTONE_KINDS)}")
        if m.phase not in phase_ids:
            errors.append(f"{w}: phase '{m.phase}' is not declared under phases:")
        if len(m.label or "") > 40:
            errors.append(f"{w}: label longer than 40 characters")
        if not isinstance(m.sha, str) or len(m.sha) != 40:
            errors.append(f"{w}: sha must be a full 40-character SHA")
        elif not is_first_parent_on(repo, m.sha, base, ref):
            errors.append(f"{w}: sha {m.sha[:12]} is not a first-parent commit on {ref} since {base[:12]}")
        # None means unverifiable (gh unavailable/timed out/non-JSON — see
        # gitinfo.pr_is_merged), not fatal: only a confirmed False is an
        # error, matching the defect fixed_in check below.
        if m.pr is not None and pr_checker is not None and pr_checker(m.pr) is False:
            errors.append(f"{w}: PR #{m.pr} is not merged")
        if not _is_one_sentence(m.summary):
            errors.append(f"{w}: summary must be one sentence")

    seen: set[str] = set()
    for d in c.defects:
        w = f"defect '{d.id}'"
        if d.id in seen:
            errors.append(f"{w}: duplicate id")
        seen.add(d.id)
        if d.area not in DEFECT_AREAS:
            errors.append(f"{w}: area '{d.area}' not in {sorted(DEFECT_AREAS)}")
        if d.severity not in DEFECT_SEVERITIES:
            errors.append(f"{w}: severity '{d.severity}' not in {sorted(DEFECT_SEVERITIES)}")
        if d.status not in DEFECT_STATUSES:
            errors.append(f"{w}: status '{d.status}' not in {DEFECT_STATUSES}")
        if d.status == "open" and d.issue is None and not d.source:
            errors.append(f"{w}: status open needs issue or source")
        if d.status == "pinned" and (d.issue is None or not d.test):
            errors.append(f"{w}: status pinned needs issue and test")
        if d.status == "fixed" and d.fixed_in is None:
            errors.append(f"{w}: status fixed needs fixed_in")
        if d.status == "carried" and not d.carried_as:
            errors.append(f"{w}: status carried needs carried_as")
        if d.test and not (repo / d.test).exists():
            errors.append(f"{w}: test path {d.test} does not exist")
        if d.fixed_in is not None and pr_checker is not None and pr_checker(d.fixed_in) is False:
            errors.append(f"{w}: fixed_in PR #{d.fixed_in} is not merged")
        for name in ("first_seen", "status_changed"):
            if not isinstance(getattr(d, name), dt.date):
                errors.append(f"{w}: {name} must be a date")
    return errors


def validate_transitions(before: list[Defect], after: list[Defect]) -> list[str]:
    """Status moves only forward (spec §5.3). `before` is the ledger on main."""
    errors = []
    prev = {d.id: d for d in before}
    for d in after:
        old = prev.get(d.id)
        if old and old.status != d.status and (old.status, d.status) not in ALLOWED_TRANSITIONS:
            errors.append(f"defect '{d.id}': status moved backward {old.status} -> {d.status}")
    return errors
