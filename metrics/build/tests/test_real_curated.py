"""The committed curated files must validate against the committed repo.

Runs offline (no PR checks) so it works in the hook; the Pages build runs the
same validator online.
"""
import json
import subprocess
import unittest
from pathlib import Path

from curated import load_curated, validate
from curated import pointers  # R9(d): the one shared implementation

ROOT = Path(__file__).resolve().parents[3]
BASE = "fd413f0cc4ab3131789a68fb31f1ae622ae7371a"


def latest_family_pointers() -> dict[str, set[str]]:
    """Pointers present in the newest row of each family on origin/metrics-data, if fetched."""
    out: dict[str, set[str]] = {}
    for family in ("code_health", "architecture", "tests", "coverage"):
        r = subprocess.run(["git", "-C", str(ROOT), "show", f"origin/metrics-data:{family}.jsonl"], capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            continue
        row = json.loads(r.stdout.strip().splitlines()[-1])
        out[family] = set(pointers(row["metrics"]))
    return out


class RealCuratedFilesTests(unittest.TestCase):
    def test_committed_files_validate(self):
        c = load_curated(ROOT / "metrics" / "curated")
        has_origin_main = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", "origin/main"], capture_output=True).returncode == 0
        has_main = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "-q", "--verify", "main"], capture_output=True).returncode == 0
        if not (has_origin_main or has_main):
            self.skipTest("neither origin/main nor main is resolvable: real-curated validation needs full main history (fetch-depth 0)")
        ref = "origin/main" if has_origin_main else "main"
        # A shallow clone can resolve `ref` while still lacking the history
        # between BASE and it (e.g. a depth-1 checkout of a PR branch whose
        # local `main` is just the shallow tip). Without full history every
        # milestone's first-parent check fails, not just genuinely bad ones.
        reachable = subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", BASE, ref], capture_output=True
        ).returncode == 0
        if not reachable:
            self.skipTest(f"{BASE[:12]} is not reachable from {ref}: real-curated validation needs full main history (fetch-depth 0)")
        families = latest_family_pointers() or None  # None when the data branch is not fetched: skip resolution checks
        errors = validate(c, repo=ROOT, base=BASE, ref=ref, pr_checker=None, known_families=families)
        self.assertEqual(errors, [], "\n".join(errors))

    def test_exactly_twenty_headlines_four_per_group(self):
        c = load_curated(ROOT / "metrics" / "curated")
        heads = [m for m in c.catalogue if m.headline]
        self.assertEqual(len(heads), 20)
        per_group = {}
        for m in heads:
            per_group[m.group] = per_group.get(m.group, 0) + 1
        self.assertEqual(set(per_group.values()), {4}, per_group)
