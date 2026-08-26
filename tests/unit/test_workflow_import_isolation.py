"""
Import-graph guard for the workflow/ package (ADR-0014).

The whole point of the engine is that the arrow points AWAY from the UI:
workflow/ may depend on pipeline/ and document_model/, but must NEVER import
web_routes/ (or the web-only pool_orchestrator shim). If it did, a TUI or a
headless caller could not use the engine without dragging FastAPI in, and the
decoupling would be a fiction.

This is a static source scan (not an import-time check) so it catches a
forbidden import even if that module isn't imported during a given test run.
"""

import ast
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parent.parent.parent / "workflow"

FORBIDDEN_PREFIXES = ("web_routes", "pipeline.pool_orchestrator")


def _imported_modules(py_file: Path):
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            # Only module-absolute imports matter here; level>0 is a relative
            # import within workflow/, which is fine.
            if node.module and node.level == 0:
                yield node.module, node.lineno


def test_workflow_never_imports_web_routes():
    offenders = []
    for py_file in sorted(WORKFLOW_DIR.rglob("*.py")):
        for module, lineno in _imported_modules(py_file):
            if any(module == p or module.startswith(p + ".") for p in FORBIDDEN_PREFIXES):
                offenders.append(f"{py_file.name}:{lineno} imports {module}")
    assert not offenders, (
        "workflow/ must not import the UI layer (arrow points away from web_routes):\n"
        + "\n".join(offenders)
    )
