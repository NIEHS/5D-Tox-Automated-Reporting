#!/usr/bin/env python3
"""
_refactor_imports.py — rewrite first-party imports after modules move into
concern packages. Safe by construction: driven by an explicit module→package
map, matches whole module tokens only (no substring collisions like
extract / extract_phase2_runner), and handles every import form at any
indentation:

    from <mod> import ...            -> from <pkg>.<mod> import ...
    import <mod>                     -> import <pkg>.<mod> as <mod>
    import <mod> as <alias>          -> import <pkg>.<mod> as <alias>

Only modules present in MODULE_PKG are rewritten; everything else (stdlib,
third-party, already-moved) is left untouched. Idempotent: a module already
qualified (has a dot before it) is skipped.

Usage:
    python _refactor_imports.py --map document_tree=document_model,render_common=rendering [--apply] [files...]
    python _refactor_imports.py --pkg rendering --mods render_common,html_generator [--apply]

Default is DRY-RUN (prints the diff count per file). Pass --apply to write.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build_patterns(module_pkg: dict[str, str]):
    """Return a list of (compiled_regex, repl_func) for each module."""
    pats = []
    for mod, pkg in module_pkg.items():
        qual = f"{pkg}.{mod}"
        m = re.escape(mod)
        # from <mod> import ...   (indent preserved via group 1)
        pats.append((
            re.compile(rf"^(\s*)from {m}(\s+import\b)", re.M),
            rf"\1from {qual}\2",
        ))
        # import <mod> as <alias>   -> import <pkg>.<mod> as <alias>
        pats.append((
            re.compile(rf"^(\s*)import {m}(\s+as\s+\w+)", re.M),
            rf"\1import {qual}\2",
        ))
        # bare import <mod>  (end of statement)  -> import <pkg>.<mod> as <mod>
        pats.append((
            re.compile(rf"^(\s*)import {m}(\s*)$", re.M),
            rf"\1import {qual} as {mod}\2",
        ))
    return pats


def rewrite_text(text: str, pats) -> tuple[str, int]:
    total = 0
    for rx, repl in pats:
        text, n = rx.subn(repl, text)
        total += n
    return text, total


def parse_map(args) -> dict[str, str]:
    mp: dict[str, str] = {}
    if args.map:
        for pair in args.map.split(","):
            mod, pkg = pair.split("=")
            mp[mod.strip()] = pkg.strip()
    if args.pkg and args.mods:
        for mod in args.mods.split(","):
            mp[mod.strip()] = args.pkg.strip()
    return mp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", help="comma list of mod=pkg")
    ap.add_argument("--pkg", help="target package (with --mods)")
    ap.add_argument("--mods", help="comma list of modules (with --pkg)")
    ap.add_argument("--apply", action="store_true", help="write changes (default dry-run)")
    ap.add_argument("files", nargs="*", help="files to scan (default: all .py under root + tests)")
    args = ap.parse_args()

    module_pkg = parse_map(args)
    if not module_pkg:
        sys.exit("no module→package map given (use --map or --pkg/--mods)")
    pats = build_patterns(module_pkg)

    if args.files:
        files = [Path(f) for f in args.files]
    else:
        files = sorted(ROOT.rglob("*.py"))
        files = [f for f in files if ".venv" not in f.parts and f.name != "_refactor_imports.py"]

    changed = 0
    hits = 0
    for f in files:
        try:
            src = f.read_text(encoding="utf-8")
        except Exception:
            continue
        new, n = rewrite_text(src, pats)
        if n:
            hits += n
            changed += 1
            rel = f.relative_to(ROOT) if ROOT in f.parents or f.parent == ROOT else f
            print(f"  {'APPLIED' if args.apply else 'would change'} {rel}: {n} import(s)")
            if args.apply:
                f.write_text(new, encoding="utf-8")

    verb = "rewrote" if args.apply else "would rewrite"
    print(f"{verb} {hits} import(s) across {changed} file(s) for map {module_pkg}")


if __name__ == "__main__":
    main()
