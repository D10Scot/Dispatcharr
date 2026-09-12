"""An AST scan for ORM reads reachable from the relay, in two scopes.

WHAT THIS PROVES, AND WHAT IT DOES NOT (Ruling R1, plan 2b-3).

This is a ratchet against new textual ORM sites and new in-process import
edges out of the relay package. It is NOT evidence that the relay makes
no database query, and a green run must never be reported as one. The
runtime half of the guard (test_zero_orm_reads.py, part 2) carries that
proof.

Three classes are invisible here, by construction:

  1. Descriptor and property access. `stream.m3u_account` and
     `channel.effective_stream_profile_obj` are queries with no call
     syntax. Flagging attribute LOADS would mean flagging `.name` and
     `.id` and drowning the signal, so only CALLS are flagged.
  2. Dynamic dispatch -- getattr(obj, name)(), a handler dict, anything
     resolved at run time.
  3. Depth. One import hop out of live_proxy/**, transitive only WITHIN
     the module landed in (Ruling R4). An ORM read three first-party
     modules away is not seen.

Why AST and not the grep the spec first prescribed: issue #253 records
that the grep fails in both directions. It misses
`channel.get_stream_profile()` -- a real read whose call line names no
ORM -- and it counts a docstring that quotes the ORM line it replaced,
whose cheapest fix is to delete honest documentation. Both are pinned in
test_zero_orm_scan.py.
"""

import ast
import pathlib
from collections import namedtuple

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
RELAY_PACKAGE = REPO_ROOT / "apps" / "proxy" / "live_proxy"

Hit = namedtuple("Hit", "path lineno symbol shape")
Edge = namedtuple("Edge", "importer module name")

_SHORTCUTS = frozenset({"get_object_or_404", "get_list_or_404"})

# Names defined on a Django model that also name a common non-model
# method. Every entry costs the scanner a shape it can no longer see, so
# each needs its own comment and test_zero_orm_scan.py's assertion
# updated deliberately.
_NAMES_TOO_GENERIC = frozenset({
    # StreamProfile.update, and dict.update -- 8 hits in live_proxy at
    # 93900a6f, every one of them a dict.
    "update",
})

# First-party import roots worth following out of the relay package.
_FIRST_PARTY = ("apps.", "core.", "dispatcharr.")


def _is_test_path(path):
    return "tests" in pathlib.Path(path).parts


def model_method_names():
    """name -> ["core/models.py:StreamProfile", ...] for every method
    defined on a class whose bases mention Model. 94 names at 93900a6f."""
    names = {}
    for path in REPO_ROOT.rglob("models.py"):
        rel = str(path.relative_to(REPO_ROOT))
        if rel.startswith((".git", "node_modules")) or "/migrations/" in rel:
            continue
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any("Model" in ast.unparse(b) for b in node.bases):
                continue
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("__"):
                        continue
                    names.setdefault(item.name, []).append(f"{rel}:{node.name}")
    return names


def _hits_in(node, path, methods):
    hits = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr == "objects":
            hits.append(Hit(path, sub.lineno, "", "objects"))
        elif isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Name) and func.id in _SHORTCUTS:
                hits.append(Hit(path, sub.lineno, func.id, "shortcut"))
            elif isinstance(func, ast.Attribute):
                name = func.attr
                if name in methods and name not in _NAMES_TOO_GENERIC:
                    hits.append(Hit(path, sub.lineno, name, "model_method"))
    return sorted(set(hits))


def scan_source(source, path, methods):
    return _hits_in(ast.parse(source), path, methods)


def _relay_files():
    return sorted(
        p for p in RELAY_PACKAGE.rglob("*.py")
        if not _is_test_path(p.relative_to(REPO_ROOT))
    )


def scan_relay_package():
    """Scope 1: every non-test file under apps/proxy/live_proxy/."""
    methods = model_method_names()
    hits = []
    for path in _relay_files():
        rel = str(path.relative_to(REPO_ROOT))
        hits.extend(scan_source(path.read_text(), rel, methods))
    return sorted(hits)


def import_edges():
    """Scope 2: every first-party symbol scope 1 imports in-process.

    Module-level and function-local imports alike -- ast.walk sees both,
    and this tree has 602 function-local imports, so restricting to
    module level would miss most of them. `*/models.py` is excluded: a
    model module IS the ORM, and scanning one as relay code would flag
    the whole tree and say nothing (Ruling R3).
    """
    edges = []
    for path in _relay_files():
        rel = str(path.relative_to(REPO_ROOT))
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                continue
            module = node.module
            if not module.startswith(_FIRST_PARTY):
                continue
            if module.startswith("apps.proxy.live_proxy"):
                continue
            if module.endswith(".models"):
                continue
            for alias in node.names:
                edges.append(Edge(rel, module, alias.name))
    return sorted(set(edges))


def scan_edge(edge):
    """Scope 2, one edge: the symbol's reachable subtree in its module.

    Transitive within the module only (Ruling R4): same-module name
    resolution needs no type inference and is exact, and it is what
    makes resolve_source -> _source_from_info ->
    StreamProfile.objects.get visible.
    """
    path = REPO_ROOT / (edge.module.replace(".", "/") + ".py")
    if not path.exists():
        return []
    rel = str(path.relative_to(REPO_ROOT))
    tree = ast.parse(path.read_text())
    defs = {
        n.name: n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    if edge.name not in defs:
        return []
    methods = model_method_names()
    seen, queue = set(), [edge.name]
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        for sub in ast.walk(defs[name]):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            target = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else None
            )
            if target in defs and target not in seen:
                queue.append(target)
    hits = []
    for name in sorted(seen):
        hits.extend(_hits_in(defs[name], rel, methods))
    return sorted(set(hits))
