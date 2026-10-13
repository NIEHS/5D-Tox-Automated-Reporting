"""
genomics/go_definitions.py — a Gene Ontology term's definition, as the 2026
books print it beside each gene set (NIEHS-12, 13 Appendix E: "Definitions
of GO terms were adapted from the Gene Ontology Resource"): "The cell cycle
process by which a cell commits to entering the next cell cycle phase."

Read from the GO release file go-basic.obo (its ``def:`` lines), kept at
``resources/go/go-basic.obo`` (or the path in ``BMDX_GO_OBO``) — public
reference data, fetched once (http://purl.obolibrary.org/obo/go/go-basic.obo)
and not committed (it is ~30 MB).  Without the file there are no definitions
and the tables say so; ``release()`` names the file's data-version for the
table's footnote.
"""

from __future__ import annotations

import functools
import os
import re

from common.paths import REPO_ROOT

DEFAULT_PATH = REPO_ROOT / "resources" / "go" / "go-basic.obo"
_DEF = re.compile(r'^def:\s*"((?:[^"\\]|\\.)*)"')


def obo_path():
    from pathlib import Path
    return Path(os.environ.get("BMDX_GO_OBO") or DEFAULT_PATH)


@functools.lru_cache(maxsize=2)
def _load(path: str) -> tuple[dict[str, str], str | None]:
    defs: dict[str, str] = {}
    version = None
    current: str | None = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("data-version:") and version is None:
                version = line.split(":", 1)[1].strip()
            elif line.startswith("[Term]"):
                current = None
            elif line.startswith("id: GO:"):
                current = line[4:].strip()
            elif current and line.startswith("def:"):
                m = _DEF.match(line)
                if m:
                    defs[current] = m.group(1).replace('\\"', '"')
    return defs, version


def _loaded():
    path = obo_path()
    return _load(str(path)) if path.is_file() else ({}, None)


def go_definition(go_id: str) -> str | None:
    """The term's definition, None when the file or the term is missing."""
    return _loaded()[0].get(str(go_id or "").strip())


def release() -> str | None:
    """The loaded file's data-version ("releases/2025-07-22"), or None."""
    return _loaded()[1]
