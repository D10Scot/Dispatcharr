import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class RequirementsPinTests(unittest.TestCase):
    def test_pyyaml_pin_matches_uv_lock(self):
        lock = tomllib.load((ROOT / "uv.lock").open("rb"))
        pkg = next(p for p in lock["package"] if p["name"] == "pyyaml")
        text = (ROOT / "metrics" / "requirements.txt").read_text()
        self.assertIn(f"pyyaml=={pkg['version']}", text)
        hashes = set(re.findall(r"--hash=(sha256:[0-9a-f]{64})", text))
        expected = {pkg["sdist"]["hash"]} | {w["hash"] for w in pkg["wheels"]}
        self.assertEqual(hashes, expected)
