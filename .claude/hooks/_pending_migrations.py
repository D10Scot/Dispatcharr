"""Exit 1 if the given app module has model changes with no migration.

Takes a module path (``apps.channels``), not a directory name and not a label.
Both matter: ``apps.channels``'s Django label is ``dispatcharr_channels``, and
the plausible-looking ``channels`` is a *different installed app* — the Django
Channels library — which reports "no changes" and exits 0. Guessing the label
therefore fails silently, which is worse than not checking at all.

Exit 0 clean, 1 pending migration, 2 could not resolve the app.
"""
import os
import sys
from pathlib import Path

# Running a script puts its own directory on sys.path, not the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import django  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dispatcharr.settings")
django.setup()

from django.apps import apps  # noqa: E402
from django.core.management import call_command  # noqa: E402

module = sys.argv[1]
label = next((c.label for c in apps.get_app_configs() if c.name == module), None)
if label is None:
    print(f"could not resolve a Django app label for {module!r}", file=sys.stderr)
    raise SystemExit(2)

call_command("makemigrations", label, check=True, dry_run=True, verbosity=1)
