"""RedisKeys carried builders for keys nothing reads or writes.

Phase 2 stage 2d-1 moved apps/proxy/redis_keys.py out of live_proxy/ whole,
and 2d-4 deleted every production reader and writer of 26 of its 28
builders without auditing it (spec Amendment A16.12 item 7). A dead builder is not harmless:
it tells a reader the key is live, and CLAUDE.md had to carry a sentence
explaining that RedisKeys.worker_heartbeat meant nothing.

The surviving set is pinned exactly, so a builder added back needs a caller
and a deliberate edit here.
"""

import ast
import pathlib

from django.test import SimpleTestCase

from apps.proxy.redis_keys import RedisKeys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

SURVIVORS = {"channel_stream", "stream_profile"}

# CLAUDE.md, Structural constraints: apps/channels/models.py imports
# RedisKeys at module level, so one import added to either module can stop
# Django booting. The hook's boot check catches that locally; this is the
# same rule where CI runs it.
LEAF_MODULES = ("apps/proxy/redis_keys.py", "apps/proxy/constants.py")


class RedisKeysDeadBuildersTests(SimpleTestCase):
    def test_redis_keys_carried_builders_for_keys_nothing_reads_or_writes(self):
        builders = {
            name for name, value in vars(RedisKeys).items()
            if isinstance(value, staticmethod)
        }
        self.assertEqual(
            builders, SURVIVORS,
            f"unexpected builders: {sorted(builders - SURVIVORS)}; "
            f"missing: {sorted(SURVIVORS - builders)}",
        )

    def test_the_boot_trap_leaf_modules_import_nothing(self):
        for rel in LEAF_MODULES:
            with self.subTest(module=rel):
                tree = ast.parse((REPO_ROOT / rel).read_text())
                imports = [
                    ast.unparse(node) for node in ast.walk(tree)
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                ]
                self.assertEqual(imports, [], f"{rel} must stay a leaf")
