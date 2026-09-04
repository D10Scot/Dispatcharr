import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "collect_code_health.py"

# One occurrence each of: a bare `except:`, an `except Exception: pass`
# handler (counts toward both except_exception and except_pass_handlers), a
# function-local import, and an os.environ read. The bare except's body is
# deliberately NOT `pass`, so it doesn't also inflate except_pass_handlers.
MODULE = '''import os


def outer():
    import json
    return json


try:
    risky()
except:
    logged = True

try:
    risky()
except Exception:
    pass

value = os.environ.get("FOO")
'''


def make_repo(tmp: Path) -> None:
    mod_dir = tmp / "apps" / "x"
    mod_dir.mkdir(parents=True)
    (mod_dir / "module.py").write_text(MODULE)


class CollectCodeHealthTests(unittest.TestCase):
    def test_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(Path(tmp))
            r = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", tmp],
                capture_output=True, text=True, check=True,
            )
            m = json.loads(r.stdout)
            self.assertEqual(m["bare_except"], 1)
            self.assertEqual(m["except_exception"], 1)
            self.assertEqual(m["except_pass_handlers"], 1)
            self.assertEqual(m["function_local_imports"], 1)
            self.assertEqual(m["os_environ_reads"], 1)


if __name__ == "__main__":
    unittest.main()
