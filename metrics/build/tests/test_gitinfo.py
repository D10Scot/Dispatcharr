import sys
import tempfile
import unittest
from datetime import timezone
from pathlib import Path

# `unittest discover -t metrics/build` puts only metrics/build on sys.path, so
# `from gitinfo import ...` below resolves but a sibling test helper does not
# without this (R2).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _git import git  # noqa: E402
from gitinfo import commit_date, default_ref, first_parent_shas, is_first_parent_on, pr_is_merged, ref_exists  # noqa: E402


def make_repo(tmp: Path) -> tuple[Path, list[str]]:
    repo = tmp / "r"; repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    shas = []
    for i in range(3):
        git(repo, "commit", "-q", "--allow-empty", "-m", f"c{i}", "--date", f"2026-08-{20 + i}T10:00:00+00:00")
        shas.append(git(repo, "rev-parse", "HEAD"))
    git(repo, "checkout", "-q", "-b", "side", shas[1])
    git(repo, "commit", "-q", "--allow-empty", "-m", "side")
    side = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    shas.append(git(repo, "rev-parse", "HEAD"))
    return repo, shas + [side]


class GitInfoTests(unittest.TestCase):
    def test_first_parent_walk(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, shas = make_repo(Path(tmp))
            self.assertEqual(first_parent_shas(repo, shas[0]), shas[:4])
            self.assertTrue(is_first_parent_on(repo, shas[3], shas[0]))
            self.assertFalse(is_first_parent_on(repo, shas[4], shas[0]), "a side-branch commit is not first-parent")

    def test_commit_date_is_utc_aware(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, shas = make_repo(Path(tmp))
            d = commit_date(repo, shas[1])
            self.assertEqual(d.tzinfo, timezone.utc)
            self.assertEqual((d.year, d.month, d.day), (2026, 8, 21))

    def test_pr_is_merged_uses_injected_runner(self):
        calls = []
        def fake(*args):
            calls.append(args); return '{"merged_at": "2026-09-01T00:00:00Z"}'
        self.assertTrue(pr_is_merged("o/r", 5, gh=fake))
        self.assertIn("/repos/o/r/pulls/5", calls[0])
        self.assertFalse(pr_is_merged("o/r", 6, gh=lambda *a: '{"merged_at": null}'))
        def broken(*a): raise OSError("no gh")
        self.assertIsNone(pr_is_merged("o/r", 7, gh=broken))

    def test_pr_is_merged_returns_none_for_non_object_json(self):
        # A JSON array (or any non-dict body) has no `merged_at` to read — that
        # is unverifiable, not a confirmed "not merged", so it must not raise.
        self.assertIsNone(pr_is_merged("o/r", 8, gh=lambda *a: "[]"))

    def test_ref_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, shas = make_repo(Path(tmp))
            self.assertTrue(ref_exists(repo, "main"))
            self.assertTrue(ref_exists(repo, shas[0]))
            self.assertFalse(ref_exists(repo, "no-such-ref"))

    def test_default_ref_prefers_origin_main_when_present(self):
        # R30: `origin/main` may be ahead of a stale local `main` (a
        # checkout that fetched but never merged/rebased) - "auto" must
        # prefer it whenever it resolves.
        with tempfile.TemporaryDirectory() as tmp:
            repo, shas = make_repo(Path(tmp))
            git(repo, "update-ref", "refs/remotes/origin/main", shas[0])
            self.assertEqual(default_ref(repo), "origin/main")

    def test_default_ref_falls_back_to_main_when_no_origin_remote(self):
        # A worktree with no `origin` remote at all (this repo's own
        # `.superpowers` worktrees, a fresh `git init`) has no
        # `origin/main` to prefer.
        with tempfile.TemporaryDirectory() as tmp:
            repo, shas = make_repo(Path(tmp))
            self.assertEqual(default_ref(repo), "main")
