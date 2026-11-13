"""The safeguards are a layer over the workflow core (ADR-0031): front ends go
through them; the core never imports them, and the notebook — the workflow
without the guarding — does not either."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The workflow core: every concern package below the front ends.
CORE = ("common", "workflow", "pipeline", "document_model", "rendering", "tables",
        "narrative", "genomics", "knowledge_base", "styling_export", "roundtrip", "pdf_text")
_IMPORT = re.compile(r"^\s*(?:from|import)\s+safeguards\b", re.M)


def _importers(roots) -> list[str]:
    found = []
    for root in roots:
        for path in (REPO / root).rglob("*.py"):
            if _IMPORT.search(path.read_text(encoding="utf-8", errors="replace")):
                found.append(str(path.relative_to(REPO)))
    return sorted(found)


def test_the_core_never_imports_the_safeguards():
    assert _importers(CORE) == []


def test_the_notebook_drives_the_core_unguarded():
    assert _importers(["notebooks"]) == []


def test_the_safeguards_import_no_front_end():
    front = re.compile(r"^\s*(?:from|import)\s+(?:web_routes|tooling|fastapi)\b", re.M)
    offenders = [str(p.relative_to(REPO)) for p in (REPO / "safeguards").rglob("*.py")
                 if front.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
