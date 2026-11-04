"""
knowledge_base/registry.py — the named literature knowledge bases, and which
one a report reads.

A knowledge base is the product of a named crawl (knowledge_base.run_crawl):

    knowledge_bases/<name>/kb.duckdb        the database
    knowledge_bases/<name>/manifest.json    what made it and what it can answer
    knowledge_bases/<name>/crawl/           the crawl's outputs (papers, edges,
                                            extractions, consensus, annotations)

A finished knowledge base is immutable and its name is never reused.  The
manifest records the query it came from (its name, its text and the text's
hash), the stages, whether every stage ran (``complete``), the database's
SHA-256 and its ``capabilities``: what it can answer (papers, claims, genes,
organs, go, pathways — derived from the tables it holds, never declared).

Which one a report reads: its document definition's ``knowledge_base:``
(document_model.document_definition — an era, a study's document.yaml, a
pinned snapshot), else the default named in ``knowledge_bases/DEFAULT``.
Every reader resolves through ``kb_for``; nothing names a database path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from common.paths import REPO_ROOT

# Overridable (tests, a separate workspace), as SESSIONS_DIR is.
KB_ROOT = Path(os.environ.get("KNOWLEDGE_BASES_DIR", REPO_ROOT / "knowledge_bases"))
DEFAULT_FILE = "DEFAULT"
DB_FILE = "kb.duckdb"
MANIFEST_FILE = "manifest.json"
CRAWL_DIR = "crawl"

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# What a table set lets a reader ask: capability -> the tables it needs.
CAPABILITY_TABLES = {
    "papers": ("papers",),
    "claims": ("paper_claims",),
    "genes": ("genes", "paper_genes"),
    "organs": ("paper_organs",),
    "go": ("go_terms", "gene_go_terms"),
    "pathways": ("pathways",),
}
# The genomics interpretation and its references (narrative.genomics_llm,
# narrative.references_builder, knowledge_base.toxkb) ask all of these.
GENOMICS_NEEDS = frozenset({"papers", "claims", "genes", "go", "pathways"})


class KnowledgeBaseError(ValueError):
    """A knowledge base that does not exist, is unfinished, or cannot answer
    what a reader needs."""


def check_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME.match(name):
        raise KnowledgeBaseError(
            f"{name!r} is not a knowledge base name (letters, digits, '.', '_', '-'; "
            "at most 64 characters)")
    return name


def kb_dir(name: str) -> Path:
    return KB_ROOT / check_name(name)


def manifest(name: str) -> dict:
    path = kb_dir(name) / MANIFEST_FILE
    if not path.exists():
        raise KnowledgeBaseError(f"no knowledge base named {name!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_knowledge_bases() -> list[dict]:
    """Every knowledge base's manifest, by name."""
    out = []
    for path in sorted(KB_ROOT.glob(f"*/{MANIFEST_FILE}")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def capabilities_of(db_path: Path) -> list[str]:
    """What a database can answer: each capability whose tables exist and hold
    rows."""
    import duckdb
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = {t for (t,) in con.execute("SHOW TABLES").fetchall()}
        filled = {t for t in tables
                  if con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] > 0}
    finally:
        con.close()
    return sorted(cap for cap, needs in CAPABILITY_TABLES.items()
                  if all(t in filled for t in needs))


def usable(name: str) -> dict:
    """The manifest of a finished knowledge base; refused when it is missing,
    unfinished, or its database is not the one the manifest recorded."""
    m = manifest(name)
    if not m.get("complete"):
        missing = [s["stage"] for s in m.get("stages", []) if s.get("status") != "ran"]
        raise KnowledgeBaseError(
            f"knowledge base {name!r} is unfinished: stage(s) {missing} did not run")
    db = kb_dir(name) / DB_FILE
    if not db.exists():
        raise KnowledgeBaseError(f"knowledge base {name!r} has no database")
    return m


def db_path(name: str) -> Path:
    usable(name)
    return kb_dir(name) / DB_FILE


def require(name: str, needs) -> dict:
    """The manifest of ``name``, refused when it cannot answer ``needs``."""
    m = usable(name)
    lacking = sorted(set(needs) - set(m.get("capabilities") or []))
    if lacking:
        raise KnowledgeBaseError(
            f"knowledge base {name!r} cannot answer {lacking} "
            f"(it holds {m.get('capabilities') or []})")
    return m


# ---------------------------------------------------------------------------
# The default
# ---------------------------------------------------------------------------

def default_name() -> str | None:
    path = KB_ROOT / DEFAULT_FILE
    if not path.exists():
        return None
    name = path.read_text(encoding="utf-8").strip()
    return name or None


def set_default(name: str) -> None:
    """Make ``name`` the knowledge base of every report that names none.  It must
    be able to ground the genomics interpretation, as every report's does."""
    require(name, GENOMICS_NEEDS)
    (KB_ROOT / DEFAULT_FILE).write_text(name + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# A report's knowledge base
# ---------------------------------------------------------------------------

def assigned_name(dtxsid: str | None) -> tuple[str | None, str]:
    """(name, source) of the knowledge base a session's report reads: its
    document definition's ``knowledge_base:`` ("definition"), else the default
    ("default"); (None, "none") when neither names one.  An id that names no
    session (not a DTXSID) has no definition of its own."""
    from common.dtxsid import is_valid_dtxsid
    if dtxsid and is_valid_dtxsid(dtxsid):
        from document_model.document_definition import definition_name
        from document_model.document_template import load_knowledge_base
        try:
            named = load_knowledge_base(definition_name(dtxsid))
        except FileNotFoundError:
            named = None
        if named:
            return named, "definition"
    name = default_name()
    return (name, "default") if name else (None, "none")


def kb_for(dtxsid: str | None, needs=GENOMICS_NEEDS) -> dict:
    """The knowledge base a session reads, checked against what the caller
    needs: ``{name, path, sha256, source, capabilities}``.  Raises
    KnowledgeBaseError when none is assigned or the assigned one cannot serve."""
    name, source = assigned_name(dtxsid)
    if not name:
        raise KnowledgeBaseError("no knowledge base is assigned and none is the default")
    m = require(name, needs)
    return {"name": name, "path": kb_dir(name) / DB_FILE, "sha256": m.get("sha256"),
            "source": source, "capabilities": m.get("capabilities") or []}


def kb_or_none(dtxsid: str | None, needs=GENOMICS_NEEDS) -> dict | None:
    """kb_for, or None (logged by the caller) for a reader that degrades without
    a knowledge base (the chat tools, the old upload route)."""
    try:
        return kb_for(dtxsid, needs)
    except KnowledgeBaseError:
        return None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def write_manifest(name: str, fields: dict) -> dict:
    """Write a knowledge base's manifest: ``fields`` plus the facts read off
    its database (sha256, capabilities, table counts)."""
    d = kb_dir(name)
    db = d / DB_FILE
    m = {"name": name, **fields}
    if db.exists():
        import duckdb
        m["sha256"] = sha256_of(db)
        m["capabilities"] = capabilities_of(db)
        con = duckdb.connect(str(db), read_only=True)
        try:
            m["tables"] = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                           for (t,) in con.execute("SHOW TABLES").fetchall()}
        finally:
            con.close()
    (d / MANIFEST_FILE).write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    return m


# ---------------------------------------------------------------------------
# A knowledge base's own spelling of its values
# ---------------------------------------------------------------------------

def field_normalizer(db_path, field: str):
    """The function a knowledge base normalised ``field``'s values with (its
    query's ``normalize`` rules, from the manifest beside the database), so a
    reader spells its own values (a study's gene symbols) the same way.  Values
    are only trimmed when the knowledge base records no rules."""
    import yaml
    from knowledge_base.extract import field_spec, normalizer
    manifest_path = Path(db_path).parent / MANIFEST_FILE
    spec = None
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        text = (m.get("query") or {}).get("text")
        if text:
            spec = field_spec((yaml.safe_load(text) or {}).get("extract") or {}, field)
    return normalizer(spec)
