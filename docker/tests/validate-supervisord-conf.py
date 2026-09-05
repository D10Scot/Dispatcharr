#!/usr/bin/env python
"""Parse every docker/supervisord/*.conf rung with supervisor's own parser.

supervisord has no config-test flag (its -t is --strip_ansi), so this is
the config test: it drives ServerOptions.realize(), which is exactly what
a real boot does minus spawning anything. Catches a bad datatype, an
unset %(ENV_x)s, an [include] that resolves to nothing it should have
matched, and a priority or stopsignal that does not mean what was
intended.

Off-image, /app and /run do not exist, so the conf files are copied to a
temporary tree with those two prefixes rewritten. The environment is a
representative one, not the real one; POSTGRES_USER is the invoking user
because supervisord resolves `user=` against the local passwd database at
parse time.

Usage: uv run --no-project --with supervisor==4.3.0 python docker/tests/validate-supervisord-conf.py [repo_root]
"""

from __future__ import annotations

import getpass
import os
import re
import shutil
import sys
import tempfile

from supervisor.options import ServerOptions

EXPECTED = {
    "all.conf": [
        "postgres", "redis", "api-uwsgi", "relay-uwsgi", "daphne",
        "celery-default", "celery-dvr", "celery-beat", "nginx",
    ],
    "all-dev.conf": [
        "postgres", "redis-dev", "api-uwsgi", "relay-uwsgi", "daphne",
        "celery-default", "celery-dvr", "celery-beat", "vite",
    ],
    "api.conf": ["api-uwsgi", "daphne", "nginx"],
    "worker.conf": ["celery-default", "celery-dvr", "celery-beat"],
    # relay.conf's [include] is a glob (relay-*.conf); PR 4 is what
    # first populates it, with relay-uwsgi (D14 — the relay role runs
    # no nginx, so this program is and stays the only one this rung
    # includes).
    "relay.conf": ["relay-uwsgi"],
}

FAKE_ENV = {
    "PG_BINDIR": "/usr/lib/postgresql/17/bin",
    "POSTGRES_DIR": "/data/db",
    "POSTGRES_PORT": "5432",
    "POSTGRES_USER": getpass.getuser(),
    "DISPATCHARR_HOME": os.path.expanduser("~"),
    "DISPATCHARR_CELERY_USER": getpass.getuser(),
    "DISPATCHARR_CELERY_HOME": os.path.expanduser("~"),
    "CELERY_LOG_LEVEL": "warning",
    # Negative on purpose: the point of setpriv-after-nice is that a
    # negative value is expressible at all.
    "UWSGI_NICE_LEVEL": "-5",
    "CELERY_NICE_LEVEL": "5",
    "VIRTUAL_ENV": "/dispatcharrpy",
    "DISPATCHARR_UWSGI_INI": "/app/docker/uwsgi.ini",
    "DISPATCHARR_UWSGI_EXTRA_ARGS": "--disable-logging",
}

RUNTIME_PATH_KEYS = r"logfile|pidfile|childlogdir|file|serverurl"


def stage(repo_root: str) -> tuple[str, str]:
    """Copy the two conf directories to a temp tree, rewriting /app and /run."""
    tmp = tempfile.mkdtemp(prefix="supervisord-validate-")
    app = os.path.join(tmp, "app", "docker")
    run = os.path.join(tmp, "run")
    os.makedirs(app)
    os.makedirs(run)
    for name in ("supervisord", "supervisord.d"):
        shutil.copytree(os.path.join(repo_root, "docker", name),
                        os.path.join(app, name))
    for name in ("supervisord", "supervisord.d"):
        directory = os.path.join(app, name)
        for entry in sorted(os.listdir(directory)):
            if not entry.endswith(".conf"):
                continue
            path = os.path.join(directory, entry)
            with open(path) as handle:
                text = handle.read()
            text = text.replace("/app/docker/", app + "/")
            text = re.sub(
                r"(?m)^(\s*(?:%s)\s*=\s*(?:unix://)?)/run" % RUNTIME_PATH_KEYS,
                r"\1" + run,
                text,
            )
            with open(path, "w") as handle:
                handle.write(text)
    return app, run


def main() -> int:
    repo_root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    os.environ.update(FAKE_ENV)
    try:
        app, _run = stage(repo_root)
    except FileNotFoundError as exc:
        # Before the rung files exist this is the expected failing state,
        # and a traceback is a worse way to say so than a FAIL line.
        print("FAIL: %s missing (%s)" % (
            os.path.relpath(exc.filename or "docker/supervisord", repo_root),
            exc.strerror))
        return 1
    rung_dir = os.path.join(app, "supervisord")

    failures = 0
    seen = set()
    for rung in sorted(os.listdir(rung_dir)):
        if not rung.endswith(".conf") or rung == "supervisorctl.conf":
            continue
        seen.add(rung)
        options = ServerOptions()
        try:
            options.realize(["-c", os.path.join(rung_dir, rung)], doc=__doc__)
        except SystemExit as exc:
            print("FAIL %s: supervisor rejected the config (exit %s)" % (rung, exc))
            failures += 1
            continue
        names = [group.name for group in
                 sorted(options.process_group_configs, key=lambda g: g.priority)]
        expected = EXPECTED.get(rung)
        if expected is None:
            print("FAIL %s: unknown rung, add it to EXPECTED" % rung)
            failures += 1
            continue
        if names != expected:
            print("FAIL %s: programs %s, expected %s" % (rung, names, expected))
            failures += 1
            continue
        print("OK   %s: %s" % (rung, ", ".join(names) or "(no programs yet)"))
        for warning in options.parse_warnings:
            print("       warn: %s" % warning)

    missing = set(EXPECTED) - seen
    if missing:
        print("FAIL missing rung files: %s" % ", ".join(sorted(missing)))
        failures += 1

    print("%d rung(s) checked, %d failure(s)" % (len(seen), failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
