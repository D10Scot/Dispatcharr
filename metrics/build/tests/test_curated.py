import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# `unittest discover -t metrics/build` puts only metrics/build on sys.path, so
# `from _git import git` below resolves but a sibling test helper does not
# without this (R2).
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml

from curated import load_curated, validate
from _git import git  # noqa: E402  (R2/R10: shared helper, not redefined here)

FIX = Path(__file__).resolve().parent / "fixtures" / "curated" / "valid"


class CuratedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"; self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "base"); self.base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "second"); self.second = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "e2e" / "tests" / "seeded").mkdir(parents=True)
        (self.repo / "e2e" / "tests" / "seeded" / "output-m3u.spec.ts").write_text("")
        self.curated = self.tmp / "curated"
        shutil.copytree(FIX, self.curated)
        m = (self.curated / "milestones.yml").read_text().replace("BASE", self.base).replace("SECOND", self.second)
        (self.curated / "milestones.yml").write_text(m)
        self.families = {"tests": {"/e2e_scenario_count"}, "code_health": {"/loc_per_app/apps.proxy"}}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _errors(self, pr_checker=lambda n: True):
        c = load_curated(self.curated)
        return validate(c, repo=self.repo, base=self.base, ref="main", pr_checker=pr_checker, known_families=self.families)

    def _mutate(self, name, fn):
        p = self.curated / name
        doc = yaml.safe_load(p.read_text())
        fn(doc)
        p.write_text(yaml.safe_dump(doc, sort_keys=False))

    def test_valid_fixtures_have_no_errors(self):
        self.assertEqual(self._errors(), [])

    def test_catalogue_rejects_unknown_direction_and_group(self):
        self._mutate("catalogue.yml", lambda d: d[0].update(direction="sideways", group="misc"))
        errs = self._errors()
        self.assertTrue(any("direction" in e for e in errs)); self.assertTrue(any("group" in e for e in errs))

    def test_catalogue_headline_must_resolve_against_data(self):
        self._mutate("catalogue.yml", lambda d: d[0].update(path="/does_not_exist"))
        self.assertTrue(any("does not resolve" in e for e in self._errors()))

    def test_catalogue_derived_needs_known_derivation(self):
        self._mutate("catalogue.yml", lambda d: d[1].update(derivation="nope"))
        self.assertTrue(any("derivation" in e for e in self._errors()))

    def test_catalogue_ids_unique(self):
        self._mutate("catalogue.yml", lambda d: d[2].update(id="e2e_scenarios"))
        self.assertTrue(any("duplicate id" in e for e in self._errors()))

    def test_milestone_sha_must_be_first_parent_on_main(self):
        git(self.repo, "checkout", "-q", "-b", "side", self.base)
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "side"); side = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "main")
        self._mutate("milestones.yml", lambda d: d["milestones"][1].update(sha=side))
        self.assertTrue(any("first-parent" in e for e in self._errors()))

    def test_milestone_pr_must_be_merged_when_checker_present(self):
        self.assertTrue(any("not merged" in e for e in self._errors(pr_checker=lambda n: False)))
        self.assertEqual(self._errors(pr_checker=None), [], "hook mode skips PR checks")

    def test_milestone_phase_must_exist_and_label_short(self):
        self._mutate("milestones.yml", lambda d: d["milestones"][1].update(phase="phase9", label="x" * 41))
        errs = self._errors()
        self.assertTrue(any("phase" in e for e in errs)); self.assertTrue(any("label" in e for e in errs))

    def test_phase_headline_ids_must_exist(self):
        self._mutate("milestones.yml", lambda d: d["phases"][0].update(headline_ids=["ghost"]))
        self.assertTrue(any("headline_ids" in e for e in self._errors()))

    def test_defect_status_required_fields(self):
        self._mutate("defects.yml", lambda d: d[1].update(test=None))
        self.assertTrue(any("pinned" in e and "test" in e for e in self._errors()))
        self._mutate("defects.yml", lambda d: d[0].update(source=None))
        self.assertTrue(any("open" in e and "issue" in e for e in self._errors()))

    def test_defect_test_path_must_exist(self):
        self._mutate("defects.yml", lambda d: d[1].update(test="e2e/tests/nope.spec.ts"))
        self.assertTrue(any("does not exist" in e for e in self._errors()))

    def test_defect_status_cannot_move_backwards(self):
        from curated import validate_transitions
        before = load_curated(self.curated)
        self._mutate("defects.yml", lambda d: d[1].update(status="open", test=None, issue=80))
        after = load_curated(self.curated)
        errs = validate_transitions(before.defects, after.defects)
        self.assertTrue(any("backward" in e for e in errs))
        self.assertEqual(validate_transitions(after.defects, before.defects), [])
