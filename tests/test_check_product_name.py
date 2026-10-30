"""Tests for scripts/check_product_name.py.

The script is the one place the Mino rename's rule R-1 (decision records keep
the old name) is enforced, so each behaviour is exercised as a subprocess
against a throwaway git repository, the way lint.yml invokes it.

The child environment is built from an allowlist, never by removing variables:
an inherited GIT_DIR, GIT_WORK_TREE or GIT_INDEX_FILE would point `git` at the
real repository, and the check would then ratchet (or --write over) the wrong
tree. Every test asserts the throwaway repo's git-dir before it runs anything.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_product_name.py"
ALLOWLIST = "scripts/product_name_allowlist.txt"


def clean_env(home):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": home,
        "LANG": "C.UTF-8",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    return env


class CheckProductNameTests(SimpleTestCase):
    def setUp(self):
        # The `:latest` image the local hook container runs lacks git; the
        # `:base` image CI runs in has it. Skip only off CI: on CI a missing
        # git is a failure, never a quiet pass.
        if shutil.which("git") is None and not os.environ.get("CI"):
            self.skipTest("git is not installed in this container")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.env = clean_env(str(self.root))
        self.git("init", "-q")
        git_dir = self.git("rev-parse", "--absolute-git-dir").stdout.strip()
        self.assertEqual(Path(git_dir).resolve(), self.root / ".git")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, env=self.env,
            capture_output=True, text=True, check=True,
        )

    def put(self, path, data):
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data if isinstance(data, bytes) else data.encode())
        self.git("add", path)

    def run_check(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], cwd=self.root, env=self.env,
            capture_output=True, text=True,
        )

    def write_allowlist(self):
        result = self.run_check("--write")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_record_path_is_ignored(self):
        self.put("docs/adr/0001-x.md", "dispatcharr " * 5)
        self.put("docs/superpowers/specs/s.md", "Dispatcharr")
        self.put("CHANGELOG.md", "Dispatcharr")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.write_allowlist()
        self.assertEqual((self.root / ALLOWLIST).read_text(), "")

    def test_binary_file_is_ignored(self):
        self.put("logo.bin", b"\0\1dispatcharr\0")
        self.assertEqual(self.run_check().returncode, 0)

    def test_increase_fails(self):
        self.put("a.txt", "dispatcharr\n")
        self.write_allowlist()
        self.put("a.txt", "dispatcharr\ndispatcharr\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("a.txt: count 2, allowed 1", result.stdout)

    def test_unlisted_file_fails(self):
        self.put("a.txt", "dispatcharr\n")
        self.write_allowlist()
        self.put("b.txt", "dispatcharr\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("b.txt: count 1, allowed 0", result.stdout)

    def test_decrease_passes_and_asks_for_write(self):
        self.put("a.txt", "dispatcharr dispatcharr\n")
        self.write_allowlist()
        self.put("a.txt", "dispatcharr\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 0)
        self.assertIn("a.txt: 2 -> 1", result.stdout)
        self.assertIn("--write", result.stdout)

    def test_write_round_trips(self):
        self.put("a.txt", "dispatcharr\n")
        self.put("sub/b.txt", "dispatcharr x dispatcharr\n")
        self.write_allowlist()
        first = (self.root / ALLOWLIST).read_text()
        self.assertEqual(first, "1\ta.txt\n2\tsub/b.txt\n")
        self.assertEqual(self.run_check().returncode, 0)
        self.write_allowlist()
        self.assertEqual((self.root / ALLOWLIST).read_text(), first)

    def test_uppercase_and_lowercase_both_counted(self):
        self.put("a.txt", "Dispatcharr DISPATCHARR dispatcharr\n")
        self.write_allowlist()
        self.assertEqual((self.root / ALLOWLIST).read_text(), "3\ta.txt\n")

    def test_every_record_glob_is_ignored_at_depth(self):
        records = [
            "docs/adr/sub/x.md",
            "docs/superpowers/specs/a/x.md",
            "docs/superpowers/plans/a/b.md",
            "docs/superpowers/analysis/a/b.md",
            "docs/comparisons/run/d.csv",
            "CHANGELOG.md",
        ]
        for path in records:
            self.put(path, "dispatcharr\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.write_allowlist()
        self.assertEqual((self.root / ALLOWLIST).read_text(), "")

    def test_near_miss_record_paths_are_still_counted(self):
        near = ["docs/adr.md", "docs/superpowers/other/x.md", "sub/CHANGELOG.md"]
        for path in near:
            self.put(path, "dispatcharr\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        for path in near:
            self.assertIn(f"{path}: count 1, allowed 0", result.stdout)

    def test_allowlist_does_not_count_against_itself(self):
        self.put("dispatcharr/x.py", "dispatcharr\n")
        self.write_allowlist()
        self.git("add", ALLOWLIST)
        self.assertIn("dispatcharr/x.py", (self.root / ALLOWLIST).read_text())
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn(ALLOWLIST, (self.root / ALLOWLIST).read_text())

    def test_malformed_allowlist_line_exits_1_naming_the_line(self):
        self.put("a.txt", "dispatcharr\n")
        self.put(ALLOWLIST, "1\ta.txt\nnot a valid line\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{ALLOWLIST}:2: expected `<count>\\t<path>`", result.stdout)
