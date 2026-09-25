"""scripts/coverage_live_path_isolated.sh forwarded only its first argument.

The last docker exec built `coverage_live_path.sh ${1:---report} /tmp/combined`,
so `--write-floor --shape-only` arrived as `--write-floor`: a FULL floor write,
which records `missing` from one local round. The floor's rule is that
`missing` comes only from a >=12-round CI census. It was caught only because
the usual containers mount /repo read-only.

docker is stubbed on PATH so no container is needed: the stub records every
call, and the last one is the in-container report/gate/write command.
"""

import os
import pathlib
import subprocess
import tempfile

from django.test import SimpleTestCase

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "coverage_live_path_isolated.sh"
STUB = '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$DOCKER_STUB_LOG"\nexit 0\n'


class IsolatedCoverageForwardsEveryFlagTests(SimpleTestCase):
    def _final_call(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / "bin").mkdir()
            docker = tmp / "bin" / "docker"
            docker.write_text(STUB)
            docker.chmod(0o755)
            log = tmp / "docker.log"
            env = {
                **os.environ,
                "PATH": f"{tmp / 'bin'}:{os.environ['PATH']}",
                "DOCKER_STUB_LOG": str(log),
                "COVERAGE_ISOLATED_OUT": str(tmp / "out"),
                "COVERAGE_ISOLATED_PREFIX": "stub",
            }
            proc = subprocess.run(
                ["bash", str(SCRIPT), *args], env=env,
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return log.read_text().splitlines()[-1]

    def test_isolated_coverage_dropped_every_flag_after_the_first(self):
        self.assertIn(
            "coverage_live_path.sh --write-floor --shape-only /tmp/combined",
            self._final_call("--write-floor", "--shape-only"),
        )

    def test_no_argument_still_means_report(self):
        self.assertIn(
            "coverage_live_path.sh --report /tmp/combined", self._final_call()
        )

    def test_gate_is_forwarded_unchanged(self):
        self.assertIn(
            "coverage_live_path.sh --gate /tmp/combined", self._final_call("--gate")
        )
