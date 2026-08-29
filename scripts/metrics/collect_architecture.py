#!/usr/bin/env python3
"""Metric family: architecture (extraction-progress).

Tracks the structural facts that gate the relay extraction:

- cross_app_import_statements: import statements in one ``apps.<x>`` package
  referencing a different ``apps.<y>`` package (non-test files).
- cross_app_import_edges: distinct (from_app, to_app) pairs among those.
- import_cycles: strongly-connected components of size > 1 in the app graph.
- proxy_orm_writes: ORM write calls in non-test ``apps/proxy`` code:
  ``.save()`` on an instance, or manager/queryset write methods
  (``create/update/delete/get_or_create/update_or_create/bulk_*``) called on
  ``X.objects`` or a ``filter()/exclude()/all()`` chain. Bare instance
  ``.delete()`` is deliberately NOT counted: in this codebase it is
  overwhelmingly redis-client ``.delete(key)``, which would swamp the signal.
- reverse_imports_into_proxy: non-test import statements outside apps/proxy
  that import from ``apps.proxy``.
- models_module_level_live_proxy_imports: module-level imports of
  ``apps.proxy.live_proxy`` from ``apps/channels/models.py`` (the boot-cycle
  trap; baseline 2).
"""

from __future__ import annotations

import ast
from pathlib import Path

from _common import emit, is_test_path, iter_files, parse_python, repo_root_arg

ORM_WRITE_MANAGER_METHODS = {
    "create",
    "update",
    "delete",
    "get_or_create",
    "update_or_create",
    "bulk_create",
    "bulk_update",
}
ORM_WRITE_INSTANCE_METHODS = {"save"}


def imported_modules(tree: ast.AST) -> list[str]:
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.append(node.module)
    return mods


def target_app(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) >= 2 and parts[0] == "apps":
        return parts[1]
    return None


def strongly_connected_components(graph: dict[str, set[str]]) -> list[set[str]]:
    """Tarjan's algorithm, iterative-enough for a 14-node graph."""
    index_counter = [0]
    stack: list[str] = []
    lowlink: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: set[str] = set()
    result: list[set[str]] = []

    def strongconnect(v: str) -> None:
        index[v] = lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, ()):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index[w])
        if lowlink[v] == index[v]:
            comp: set[str] = set()
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.add(w)
                if w == v:
                    break
            result.append(comp)

    for v in graph:
        if v not in index:
            strongconnect(v)
    return result


def count_orm_writes(tree: ast.AST) -> int:
    count = 0
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        method = node.func.attr
        receiver = node.func.value
        if method in ORM_WRITE_MANAGER_METHODS:
            # Only when called on something that looks like a manager/queryset:
            # X.objects.create(...), qs.filter(...).update(...)
            if isinstance(receiver, ast.Attribute) and receiver.attr == "objects":
                count += 1
            elif isinstance(receiver, ast.Call) and isinstance(
                receiver.func, ast.Attribute
            ) and receiver.func.attr in {"filter", "exclude", "all", "objects"}:
                count += 1
        elif method in ORM_WRITE_INSTANCE_METHODS:
            # instance.save(); receiver must be a bare name or attribute.
            if isinstance(receiver, (ast.Name, ast.Attribute)):
                count += 1
    return count


def main() -> None:
    root = repo_root_arg(__doc__)
    apps_dir = root / "apps"
    py_files = iter_files(root, (".py",)) if apps_dir.is_dir() else []

    edge_statements: dict[tuple[str, str], int] = {}
    graph: dict[str, set[str]] = {}
    proxy_orm_writes = 0
    reverse_imports_into_proxy = 0

    for path in py_files:
        rel = path.relative_to(root)
        if is_test_path(rel):
            continue
        tree = parse_python(path)
        if tree is None:
            continue

        in_apps = rel.parts[0] == "apps" and len(rel.parts) > 1
        from_app = rel.parts[1] if in_apps else None
        in_proxy = in_apps and from_app == "proxy"

        for module in imported_modules(tree):
            to_app = target_app(module)
            if to_app is None:
                continue
            if in_apps and to_app != from_app:
                edge_statements[(from_app, to_app)] = (
                    edge_statements.get((from_app, to_app), 0) + 1
                )
                graph.setdefault(from_app, set()).add(to_app)
                graph.setdefault(to_app, set())
            if to_app == "proxy" and not in_proxy:
                reverse_imports_into_proxy += 1

        if in_proxy:
            proxy_orm_writes += count_orm_writes(tree)

    cycles = [c for c in strongly_connected_components(graph) if len(c) > 1]

    models_py = root / "apps" / "channels" / "models.py"
    models_live_proxy_imports = 0
    if models_py.is_file():
        tree = parse_python(models_py)
        if tree is not None:
            for node in tree.body:  # module level only, on purpose
                if isinstance(node, ast.ImportFrom) and node.module and (
                    node.module.startswith("apps.proxy.live_proxy")
                ):
                    models_live_proxy_imports += 1
                elif isinstance(node, ast.Import) and any(
                    alias.name.startswith("apps.proxy.live_proxy")
                    for alias in node.names
                ):
                    models_live_proxy_imports += 1

    emit(
        {
            "cross_app_import_statements": sum(edge_statements.values()),
            "cross_app_import_edges": len(edge_statements),
            "import_cycles": len(cycles),
            "import_cycle_members": sorted(sorted(c) for c in cycles),
            "proxy_orm_writes": proxy_orm_writes,
            "reverse_imports_into_proxy": reverse_imports_into_proxy,
            "models_module_level_live_proxy_imports": models_live_proxy_imports,
        }
    )


if __name__ == "__main__":
    main()
