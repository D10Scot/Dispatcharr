"""The three agent-maintained inputs and their validation.

Schemas are documented for humans and agents in docs/agents/metrics.md; this
module is the executable version. Validation returns every error at once so
one edit-run cycle fixes a whole file.
"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import re
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import yaml

from gitinfo import is_first_parent_on

# A second sentence start: ". " followed by an uppercase letter — a pragmatic
# proxy for "one sentence" (spec §5.2) that tolerates abbreviations like
# "e.g." and version strings like "v0.29.0" (neither has a space after the
# period, or the following character isn't uppercase).
_SECOND_SENTENCE_RE = re.compile(r"\. [A-Z]")


def _is_one_sentence(text: str) -> bool:
    """True when `text` is non-empty, single-line, and does not start a
    second sentence."""
    s = text or ""
    if not s.strip():
        return False
    if "\n" in s:
        return False
    if _SECOND_SENTENCE_RE.search(s):
        return False
    return True

DIRECTIONS = {"up", "down", "zero", "info"}
UNITS = {"count", "pct", "seconds", "days", "score", "lines", "ratio"}
GROUPS = {"safety_net", "security", "extraction", "delivery", "agents"}
MILESTONE_KINDS = {"phase-start", "phase-done", "goal", "incident", "release"}
DEFECT_AREAS = {"security", "correctness", "dead-code", "operational"}
DEFECT_SEVERITIES = {"critical", "high", "medium", "low"}
DEFECT_STATUSES = ("open", "pinned", "carried", "fixed")
def known_derivations() -> set[str]:
    from derive import DERIVATIONS  # local import: derive imports Defect from this module

    return set(DERIVATIONS)
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


# R32(b): fields that carry a GitHub number (Milestone.pr, Defect.issue,
# Defect.fixed_in) must be an int or null - a bare unquoted YAML scalar like
# `aw_fix_pr` (not a gh-aw run's actual PR number, a placeholder someone
# forgot to fill in) parses to a str, which the dataclass constructor
# accepts silently since dataclasses don't enforce field types at runtime.
_INT_OR_NULL_FIELDS = {"pr", "issue", "fixed_in"}
# Metric.target: a quoted "60" parses to a str, same trap.
_NUMBER_OR_NULL_FIELDS = {"target"}


def _check_types(where: str, kwargs: dict, errors: list[str]) -> None:
    """Type-checks the handful of fields above wherever they appear
    (kwargs is filtered to known fields already, so this runs the same for
    every dataclass `_build` constructs). bool is excluded from both -
    it's an int subclass, but `pr: true` is not a PR number."""
    for name in _INT_OR_NULL_FIELDS:
        if name in kwargs:
            v = kwargs[name]
            if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
                errors.append(f"{where}: {name} must be an int or null, got {v!r}")
    for name in _NUMBER_OR_NULL_FIELDS:
        if name in kwargs:
            v = kwargs[name]
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                errors.append(f"{where}: {name} must be a number or null, got {v!r}")


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
    _check_types(where, kwargs, errors)
    try:
        return cls(**kwargs)
    except TypeError as exc:
        errors.append(f"{where}: {exc}")
        return None


def _read(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _ensure_list(raw: Any, where: str, errors: list[str]) -> list:
    """R33(3): catalogue.yml and defects.yml must each be a YAML sequence
    at the top level. A mapping there (a stray `key: value` where a list
    was meant) used to reach `_build()` by accident - `enumerate()` over a
    dict yields its keys, each a bare string - and crash with
    `AttributeError: 'str' object has no attribute 'items'` deep inside
    `_build`, not a `ValueError`. `__main__.py`'s `_load_committed_defects`
    only catches `ValueError` around `parse_defects`, so that crash broke
    its skip-the-check contract for every other malformed-ledger case
    instead of printing one line and moving on. Caught here as an ordinary
    structural error instead."""
    if isinstance(raw, list):
        return raw
    errors.append(f"{where}: top level must be a list, got {type(raw).__name__}")
    return []


def _ensure_mapping(raw: Any, where: str, errors: list[str]) -> dict:
    """Sibling of `_ensure_list`: milestones.yml must be a YAML mapping
    (its two keys are `phases:` and `milestones:`), not a sequence. Without
    this, a list-shaped milestones.yml reached `ms_raw.get("phases", [])`
    unguarded and raised `AttributeError: 'list' object has no attribute
    'get'` instead of the `ValueError` every other structural problem in
    this module produces."""
    if isinstance(raw, dict):
        return raw
    errors.append(f"{where}: top level must be a mapping with phases: and milestones:, got {type(raw).__name__}")
    return {}


def pointers(obj, prefix=""):
    """Every JSON-pointer path (leaf-only) reachable inside `obj`, e.g.
    `{"a": {"b": 1}}` -> `["/a/b"]`. Used to check a headline catalogue
    metric's `path` resolves against the newest snapshot row for its family
    (R9(d): lives once here, imported by __main__.py and test_real_curated.py
    rather than duplicated)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from pointers(v, f"{prefix}/{k}")
    else:
        yield prefix


def load_curated(directory: Path) -> Curated:
    """Load the three files; raises ValueError listing structural problems."""
    errors: list[str] = []
    cat_raw = _ensure_list(_read(directory / "catalogue.yml") or [], "catalogue.yml", errors)
    ms_raw = _ensure_mapping(_read(directory / "milestones.yml") or {}, "milestones.yml", errors)
    def_raw = _ensure_list(_read(directory / "defects.yml") or [], "defects.yml", errors)
    catalogue = [m for i, r in enumerate(cat_raw) if (m := _build(Metric, r, f"catalogue[{i}]", errors))]
    phases = [p for i, r in enumerate(ms_raw.get("phases", [])) if (p := _build(Phase, r, f"phases[{i}]", errors))]
    milestones = [m for i, r in enumerate(ms_raw.get("milestones", [])) if (m := _build(Milestone, r, f"milestones[{i}]", errors))]
    defects = [d for i, r in enumerate(def_raw) if (d := _build(Defect, r, f"defects[{i}]", errors))]
    if errors:
        raise ValueError("curated files are malformed:\n  " + "\n  ".join(errors))
    return Curated(catalogue, phases, milestones, defects)


def parse_defects(text: str) -> list[Defect]:
    """Parse a raw `defects.yml` document (e.g. from `git show <ref>:...`,
    where there is no file on disk to hand to `load_curated`) into `Defect`
    objects. Raises ValueError on any structural problem, same as
    `load_curated` - used for the forward-only status-transition check
    against a historical revision (__main__.py), which treats any failure
    here as reason to skip the check rather than fail the build on history
    the checkout may not have."""
    errors: list[str] = []
    raw = _ensure_list(yaml.safe_load(text) or [], "defects.yml", errors)
    defects = [d for i, r in enumerate(raw) if (d := _build(Defect, r, f"defects[{i}]", errors))]
    if errors:
        raise ValueError("committed defects.yml is malformed:\n  " + "\n  ".join(errors))
    return defects


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
            if m.derivation not in known_derivations():
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
        if d.test:
            pp = PurePosixPath(d.test)
            if pp.is_absolute() or ".." in pp.parts:
                errors.append(f"{w}: test path {d.test} must stay inside the repo (no absolute path or '..')")
            elif not (repo / d.test).exists():
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
