import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# `unittest discover -t scripts/metrics` only puts scripts/metrics on
# sys.path, not this tests directory, so `_fake_gh` isn't importable without
# this (see task-2 ruling R2).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _fake_gh import fake_gh_env

HERE = Path(__file__).resolve().parent
COLLECTORS = HERE.parent


def run_gh_api(env, code):
    """Run a snippet against _gh.py in a subprocess so PATH (the fake gh) applies."""
    return subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, %r)\n%s" % (str(COLLECTORS), code)],
        env=env, capture_output=True, text=True, check=False,
    )


class GhApiTests(unittest.TestCase):
    def test_multi_page_array_is_flattened(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, {"/repos/o/r/pulls": {"pages": [[{"n": 1}, {"n": 2}], [{"n": 3}]]}})
            r = run_gh_api(env, "from _gh import gh_api; import json; print(json.dumps(gh_api('o/r', '/pulls')))")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), '[{"n": 1}, {"n": 2}, {"n": 3}]')

    def test_multi_page_object_with_list_key_is_flattened(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, {"/repos/o/r/actions/runs": {"pages": [
                {"total_count": 3, "workflow_runs": [{"id": 1}, {"id": 2}]},
                {"total_count": 3, "workflow_runs": [{"id": 3}]},
            ]}})
            r = run_gh_api(env, "from _gh import gh_api; import json; print(json.dumps(gh_api('o/r', '/actions/runs', list_key='workflow_runs')))")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), '[{"id": 1}, {"id": 2}, {"id": 3}]')

    def test_single_object_without_pagination(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, {"/repos/o/r": {"full_name": "o/r"}})
            r = run_gh_api(env, "from _gh import gh_api; import json; print(json.dumps(gh_api('o/r', '', paginate=False)))")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), '{"full_name": "o/r"}')

    def test_http_error_carries_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, {"/repos/o/r/dependabot/alerts": {"error": "HTTP 403: Resource not accessible by integration"}})
            r = run_gh_api(env, "from _gh import gh_api, GhApiError\ntry:\n    gh_api('o/r', '/dependabot/alerts')\nexcept GhApiError as e:\n    print(e.status)")
            self.assertEqual(r.stdout.strip(), "403")

    def test_slurp_flag_is_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = fake_gh_env(tmp, {"/repos/o/r/pulls": [[]]}, log=True)
            run_gh_api(env, "from _gh import gh_api; gh_api('o/r', '/pulls')")
            from _fake_gh import calls
            self.assertIn("--slurp", calls(env)[0])


if __name__ == "__main__":
    unittest.main()
