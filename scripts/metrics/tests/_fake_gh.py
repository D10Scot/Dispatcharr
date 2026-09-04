"""A stand-in `gh` for collector tests.

Tests write a JSON responses file and put a `gh` shim on PATH that answers
`gh api [--paginate] [--slurp] <path>` from it. Everything else `gh` can do is
out of scope: the shim exits 64 on any other invocation so a test that reaches
a real `gh` subcommand fails loudly rather than hitting the network.

responses: { "<path-prefix>": <one page> | {"pages": [<page>, ...]} | {"error": "HTTP 403: nope"} }
The longest matching prefix wins. A request for a path with no match exits 64.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

SHIM = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if not args or args[0] != "api":
    sys.stderr.write("fake gh: unsupported invocation: %r\\n" % (args,))
    sys.exit(64)
paginate = "--paginate" in args
slurp = "--slurp" in args
path = next((a for a in args[1:] if a.startswith("/") or a.startswith("http")), None)
responses = json.load(open(os.environ["FAKE_GH_RESPONSES"]))
log = os.environ.get("FAKE_GH_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps(args) + "\\n")
match = max((k for k in responses if path is not None and path.split("?")[0].startswith(k)), key=len, default=None)
if match is None:
    sys.stderr.write("fake gh: no response for %s\\n" % path)
    sys.exit(64)
resp = responses[match]
if isinstance(resp, dict) and "error" in resp:
    sys.stderr.write("gh: %s (%s)\\n" % (resp["error"], resp["error"].split(":")[0]))
    sys.exit(1)
pages = resp["pages"] if isinstance(resp, dict) and "pages" in resp else [resp]
if paginate and slurp:
    print(json.dumps(pages))
elif paginate:
    for p in pages:
        print(json.dumps(p))
else:
    print(json.dumps(pages[0]))
"""


def fake_gh_env(tmp_dir: str | os.PathLike, responses: dict, log: bool = False) -> dict[str, str]:
    tmp = Path(tmp_dir)
    bin_dir = tmp / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "gh"
    shim.write_text(SHIM, encoding="utf-8")
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    responses_path = tmp / "responses.json"
    responses_path.write_text(json.dumps(responses), encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["FAKE_GH_RESPONSES"] = str(responses_path)
    if log:
        env["FAKE_GH_LOG"] = str(tmp / "calls.log")
    return env


def calls(env: dict[str, str]) -> list[list[str]]:
    path = env.get("FAKE_GH_LOG")
    if not path or not Path(path).exists():
        return []
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]
