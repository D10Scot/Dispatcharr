import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "collect_architecture.py"

# apps/channels -> apps/proxy is a cross-app import edge and, since the
# importer is outside apps/proxy, also a reverse import into proxy.
CHANNELS_MODULE = "from apps.proxy import live_proxy\n"

# A bare `X.objects.create(...)` call under apps/proxy, with no import of its
# own, so it exercises proxy_orm_writes without also creating a second
# (proxy -> channels) edge that would form a cycle and complicate the count.
PROXY_MODULE = '''def do_write():
    Channel.objects.create(name="x")
'''


def make_repo(tmp: Path) -> None:
    channels_dir = tmp / "apps" / "channels"
    channels_dir.mkdir(parents=True)
    (channels_dir / "service.py").write_text(CHANNELS_MODULE)
    proxy_dir = tmp / "apps" / "proxy" / "x"
    proxy_dir.mkdir(parents=True)
    (proxy_dir / "writer.py").write_text(PROXY_MODULE)


class CollectArchitectureTests(unittest.TestCase):
    def test_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(Path(tmp))
            r = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo-root", tmp],
                capture_output=True, text=True, check=True,
            )
            m = json.loads(r.stdout)
            self.assertEqual(m["cross_app_import_statements"], 1)
            self.assertEqual(m["cross_app_import_edges"], 1)
            self.assertEqual(m["reverse_imports_into_proxy"], 1)
            self.assertEqual(m["proxy_orm_writes"], 1)
            self.assertEqual(m["import_cycles"], 0)
            self.assertEqual(m["models_module_level_live_proxy_imports"], 0)


if __name__ == "__main__":
    unittest.main()
