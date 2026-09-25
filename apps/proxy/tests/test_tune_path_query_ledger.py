"""Every query the tune path runs, per drive, from a cold cache.

WHY THIS EXISTS. Phase 2 stage 2d-4 deleted Gate 1's static ORM scanner with
apps/proxy/live_proxy/. Its scope-2 walk was the only ratchet over the
Django modules the Go relay and nginx call on every tune -- next_source,
authorize, authorize_views, config and config_helper (spec A10.8, A16.12
item 3). Those modules now run in the API process and read the ORM by
design, so relocating the scanner's line-keyed allowlist would be a list
of 62 expected reads that goes red when lines move. What is worth pinning
is what a tune COSTS: this module records the exact multiset of queries
each per-tune hop runs, and fails naming the table when one is added,
removed or repeated.

THE SIGNATURE. (verb, table), plus the settings-group key for
core_coresettings, because two settings groups produce identical SQL text
and differ only in the bound key (the deleted allowlist's params_fragment
lesson). Counts are exact, so a second redundant query of an existing
shape changes a count; the deleted runtime half could not see that.

COLD, ALWAYS. Every drive clears Django's cache and the process-local
proxy_settings cache first. A warm cache hides the CoreSettings reads
(memory: warm state hides a query), and CLAUDE.md records that TSConfig's
cache attribute shadows BaseConfig's, so both are reset.

CHANGING A LEDGER ENTRY is a behaviour change to the tune path and follows
the repo's test-modification rule: the PR lists the entry before and after
and says why the query moved.
"""

import ast
import pathlib
import re
from collections import Counter
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from apps.proxy import relay_client
from apps.proxy.config import BaseConfig, TSConfig
from apps.proxy.tests.test_next_source_api import RelayApiTestCase

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

_STATEMENT = re.compile(
    r'^\s*(SELECT|INSERT|UPDATE|DELETE)\b.*?(?:FROM|INTO|UPDATE)\s+"([a-z0-9_]+)"',
    re.S | re.I,
)
_SETTINGS_KEY = re.compile(r"'([a-z_]+)'")

S = "SELECT"

# Measured at 6319768f (the tree this PR is based on), typed by hand (Task 1).
LEDGER = {
    # nginx auth_request, once per tune: STREAMS ACL, stream settings, the channel.
    "authorize_live_uuid": {
        (S, "core_coresettings", "network_access"): 1,
        (S, "core_coresettings", "stream_settings"): 1,
        (S, "dispatcharr_channels_channel"): 1,
    },
    # POST /api/relay/channels/<uuid>/next-source, first tune of the channel.
    "next_source_first_tune": {
        (S, "core_coresettings", "proxy_settings"): 1,
        (S, "core_coresettings", "stream_settings"): 1,
        (S, "core_outputprofile"): 1,
        (S, "core_streamprofile"): 2,
        (S, "core_useragent"): 1,
        (S, "dispatcharr_channels_channel"): 2,
        (S, "dispatcharr_channels_channeloverride"): 1,
        (S, "dispatcharr_channels_channelstream"): 1,
        (S, "dispatcharr_channels_stream"): 2,
        (S, "m3u_m3uaccount"): 1,
        (S, "m3u_m3uaccountprofile"): 2,
    },
    # The same call again: the assignment-reuse branch skips three reads.
    "next_source_reuse": {
        (S, "core_coresettings", "proxy_settings"): 1,
        (S, "core_coresettings", "stream_settings"): 1,
        (S, "core_outputprofile"): 1,
        (S, "core_streamprofile"): 2,
        (S, "core_useragent"): 1,
        (S, "dispatcharr_channels_channel"): 2,
        (S, "dispatcharr_channels_channeloverride"): 1,
        (S, "dispatcharr_channels_channelstream"): 1,
        (S, "dispatcharr_channels_stream"): 1,
        (S, "m3u_m3uaccountprofile"): 1,
    },
    # POST /api/relay/channels/<uuid>/release, once per channel stop.
    "release": {
        (S, "dispatcharr_channels_channel"): 1,
    },
}


def _signature(query):
    match = _STATEMENT.match(query["sql"])
    if not match:
        return (query["sql"].split()[0].upper(), "?")
    verb, table = match.group(1).upper(), match.group(2)
    if table == "core_coresettings":
        key = _SETTINGS_KEY.search(query["sql"])
        return (verb, table, key.group(1) if key else "?")
    return (verb, table)


def _cold():
    cache.clear()
    for klass in (BaseConfig, TSConfig):
        klass._proxy_settings_cache = None
        klass._proxy_settings_cache_time = 0


class TunePathQueryLedgerTests(RelayApiTestCase):
    """RelayApiTestCase supplies the channel, two streams, the fake Redis
    and the internal-header signing the Go relay's own client uses."""

    def _observe(self, call):
        _cold()
        # The reuse check asks the relay whether the channel runs. Nothing
        # listens in a test, so pin the answer instead of dialling :5658.
        absent = relay_client.ChannelSnapshot(present=False, active=False, reachable=True)
        with patch.object(relay_client, "channel_snapshot", return_value=absent):
            with CaptureQueriesContext(connection) as ctx:
                response = call()
        self.assertEqual(response.status_code, 200, response.content[:300])
        return dict(Counter(_signature(q) for q in ctx.captured_queries))

    def _assert_ledger(self, drive, observed):
        self.assertEqual(
            observed, LEDGER[drive],
            f"{drive}: the tune path's queries moved.\n"
            f"  added or more: {sorted((Counter(observed) - Counter(LEDGER[drive])).items())}\n"
            f"  removed or fewer: {sorted((Counter(LEDGER[drive]) - Counter(observed)).items())}\n"
            f"  observed: {sorted(observed.items())}",
        )

    def _authorize(self):
        return self.client.get(
            "/_dispatcharr/authorize",
            HTTP_X_ORIGINAL_URI=f"/proxy/ts/stream/{self.channel.uuid}",
        )

    def _next_source(self):
        return self._post(self.next_source_path(str(self.channel.uuid)), {})

    def test_the_authorize_hop_runs_no_query_outside_its_ledger(self):
        self._assert_ledger("authorize_live_uuid", self._observe(self._authorize))

    def test_a_first_tune_next_source_runs_no_query_outside_its_ledger(self):
        self._assert_ledger("next_source_first_tune", self._observe(self._next_source))

    def test_a_reused_assignment_next_source_runs_no_query_outside_its_ledger(self):
        self._observe(self._next_source)
        self._assert_ledger("next_source_reuse", self._observe(self._next_source))

    def test_release_runs_no_query_outside_its_ledger(self):
        self._observe(self._next_source)
        path = self.release_path(str(self.channel.uuid))
        self._assert_ledger("release", self._observe(lambda: self._post(path, {})))


# The static half: every ORM site in the five modules Gate 1's scope-2 walk
# covered (spec A16.12 item 3), keyed by enclosing qualname and counted per
# module, never by line. The ledger above sees only the four drives it runs;
# this sees every branch -- XC and catch-up in authorize.py, failover and
# release in next_source.py, the non-live paths of authorize_views.py -- and
# does not move when lines move. What it cannot see: a new read made through
# an instance method or a related-object descriptor (channel.get_stream(),
# stream.m3u_account). The ledger sees those on the mainline drives only.
# Typed by hand from a measurement at 6319768f (Task 1 Step 4).
BOUNDARY_MODULES = {
    "apps/proxy/next_source.py": {
        "model_imports": {
            ("", "apps.channels.models", "Channel"),
            ("", "apps.channels.models", "Stream"),
            ("", "apps.m3u.models", "M3UAccount"),
            ("", "apps.m3u.models", "M3UAccountProfile"),
            ("", "core.models", "StreamProfile"),
            ("_with_output_profiles", "core.models", "OutputProfile"),
            ("_with_proxy_settings", "core.models", "CoreSettings"),
        },
        "objects": 11,
        "get_object_or_404": 6,
        "model_class_calls": {"CoreSettings.get_proxy_settings": 1},
    },
    "apps/proxy/authorize.py": {
        "model_imports": {
            ("", "apps.accounts.models", "User"),
            ("_resolve_channel", "apps.channels.models", "Channel"),
            ("resolve_output_format", "core.models", "CoreSettings"),
            ("resolve_output_profile", "core.models", "OutputProfile"),
        },
        "objects": 6,
        "get_object_or_404": 0,
        "model_class_calls": {"CoreSettings.get_default_output_format": 1},
    },
    "apps/proxy/authorize_views.py": {
        "model_imports": {("", "apps.accounts.models", "User")},
        "objects": 1,
        "get_object_or_404": 0,
        "model_class_calls": {},
    },
    "apps/proxy/config.py": {
        "model_imports": {("BaseConfig.get_proxy_settings", "core.models", "CoreSettings")},
        "objects": 0,
        "get_object_or_404": 0,
        "model_class_calls": {"CoreSettings.get_proxy_settings": 1},
    },
    "apps/proxy/config_helper.py": {
        "model_imports": set(),
        "objects": 0,
        "get_object_or_404": 0,
        "model_class_calls": {},
    },
}


def _orm_sites(rel):
    tree = ast.parse((REPO_ROOT / rel).read_text())
    imports, bound_names = set(), set()

    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, scope + [child.name])
                continue
            if isinstance(child, ast.ImportFrom) and child.module and (
                child.module.endswith(".models") or child.module == "django.db.models"
            ):
                for alias in child.names:
                    imports.add((".".join(scope), child.module, alias.name))
                    bound_names.add(alias.asname or alias.name)
            visit(child, scope)

    visit(tree, [])
    objects = get_404 = 0
    class_calls = Counter()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "objects":
            objects += 1
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "get_object_or_404":
                get_404 += 1
            elif (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in bound_names
            ):
                class_calls[f"{func.value.id}.{func.attr}"] += 1
    return {
        "model_imports": imports,
        "objects": objects,
        "get_object_or_404": get_404,
        "model_class_calls": dict(class_calls),
    }


class BoundaryModulesOrmSitesTests(SimpleTestCase):
    def test_the_boundary_modules_gained_no_orm_read_after_gate_1_was_retired(self):
        for rel, expected in BOUNDARY_MODULES.items():
            with self.subTest(module=rel):
                self.assertEqual(_orm_sites(rel), expected)
