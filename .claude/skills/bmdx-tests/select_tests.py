#!/usr/bin/env python3
"""
select_tests.py — import-graph test selector for rlm-bmdx.

Given a list of changed repo-relative paths (argv), build a module-level
import graph of the repo with `ast` and reverse-walk it: a changed module is
"covered" by every test file that transitively imports it. Print the selected
test paths (repo-relative), one per line, on stdout.

The graph is built from textual `import` / `from ... import` statements only.
That captures the real wiring chain that matters here — an integration test
imports `background_server.app`, which imports the route modules — so changing
a route module does select its endpoint tests. It does NOT capture purely
dynamic references (e.g. a monkeypatch target passed as a string); for those
the caller's safety net is the empty-selection -> full fallback.

Exit codes:
  0  -> selection done; stdout lists 0+ repo-relative test files
  3  -> cannot safely select (caller should fall back to the full suite):
        a conftest.py, test-config, or tests/fixtures/ change, or no changed
        path maps to a repo Python module.

stderr carries a human-readable summary (changed modules, selection count);
stdout is pure test paths so the caller can consume it directly.
"""

import ast
import os
import sys
from collections import defaultdict, deque

_SKIP_DIRS = {"node_modules", "__pycache__"}
_CONFIG_FILES = {"pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"}


def build_module_maps(root):
    """Walk the repo and map every .py file <-> its dotted module name."""
    file_to_mod = {}
    mod_to_file = {}
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune hidden dirs (.venv, .git, .claude, ...) and known noise.
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in _SKIP_DIRS
        ]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            parts = rel[:-3].split(os.sep)  # strip ".py"
            if parts[-1] == "__init__":
                parts = parts[:-1]
            mod = ".".join(parts)
            file_to_mod[rel] = mod
            mod_to_file[mod] = rel
    return file_to_mod, mod_to_file


def _longest_prefix(dotted, mod_to_file):
    """Longest existing-module prefix of a dotted name (e.g. a.b.c -> a.b)."""
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        cand = ".".join(parts[:i])
        if cand in mod_to_file:
            return cand
    return None


def _relative_base(mymod, is_pkg, level):
    """Resolve the base package for a relative import of the given level."""
    base_parts = mymod.split(".") if mymod else []
    if not is_pkg:
        base_parts = base_parts[:-1]  # module's own package
    up = level - 1
    if up:
        base_parts = base_parts[:-up] if up <= len(base_parts) else []
    return ".".join(base_parts)


def deps_for_file(rel, root, mod_to_file):
    """Return the set of repo files that `rel` imports (depends on)."""
    full = os.path.join(root, rel)
    try:
        with open(full, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=full)
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        print(f"warn: skipping unparseable {rel}: {exc}", file=sys.stderr)
        return set()

    is_pkg = rel.endswith("__init__.py")
    mymod = ".".join(
        rel[:-3].split(os.sep)[:-1] if is_pkg else rel[:-3].split(os.sep)
    )

    dotted_targets = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                pref = _longest_prefix(alias.name, mod_to_file)
                if pref:
                    dotted_targets.add(pref)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = _relative_base(mymod, is_pkg, node.level)
                modname = (
                    f"{base}.{node.module}" if base and node.module
                    else (node.module or base)
                )
            else:
                modname = node.module
            if not modname:
                continue
            pref = _longest_prefix(modname, mod_to_file)
            if pref:
                dotted_targets.add(pref)
            # `from pkg import sub` where sub is itself a submodule.
            for alias in node.names:
                sub = f"{modname}.{alias.name}"
                if sub in mod_to_file:
                    dotted_targets.add(sub)

    return {mod_to_file[t] for t in dotted_targets}


def is_test_file(rel):
    base = os.path.basename(rel)
    in_tests = rel.split(os.sep)[0] == "tests"
    return in_tests and (base.startswith("test_") or base.endswith("_test.py"))


def main(argv):
    root = os.environ.get("REPO_ROOT") or os.getcwd()
    changed = list(argv)

    # Structural changes whose blast radius the import graph can't bound
    # precisely -> tell the caller to run everything.
    for c in changed:
        base = os.path.basename(c)
        norm = c.replace(os.sep, "/")
        if base == "conftest.py":
            print(f"fallback: {c} (conftest affects its whole subtree)", file=sys.stderr)
            return 3
        if base in _CONFIG_FILES:
            print(f"fallback: {c} (test/build config change)", file=sys.stderr)
            return 3
        if norm.startswith("tests/fixtures/"):
            print(f"fallback: {c} (fixture feeds tests directly)", file=sys.stderr)
            return 3

    file_to_mod, mod_to_file = build_module_maps(root)

    seeds = [c for c in changed if c.endswith(".py") and c in file_to_mod]
    if not seeds:
        print("fallback: no changed path maps to a repo Python module", file=sys.stderr)
        return 3

    # Reverse adjacency: imported_file -> {files that import it}.
    radj = defaultdict(set)
    for rel in file_to_mod:
        for dep in deps_for_file(rel, root, mod_to_file):
            radj[dep].add(rel)

    # BFS outward over importers from each changed file.
    visited = set(seeds)
    queue = deque(seeds)
    while queue:
        f = queue.popleft()
        for importer in radj.get(f, ()):
            if importer not in visited:
                visited.add(importer)
                queue.append(importer)

    tests = sorted(p for p in visited if is_test_file(p))

    print(
        "changed modules: " + ", ".join(file_to_mod[s] for s in seeds),
        file=sys.stderr,
    )
    print(f"selected {len(tests)} test file(s) covering the change", file=sys.stderr)
    for t in tests:
        print(t)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
