"""
Corpus curation — a versioned, living copy of the literature knowledge base.

The frozen `bmdx.duckdb` (17.5 MB, git-committed, read-only) is the immutable
baseline. Curation is captured per session as an append-only tweak-log
(`corpus_tweaks.jsonl`); the working corpus (`corpus.duckdb`) is a *projection* of
that log onto a copy of the original — so history is the source of truth and the
DB can never drift from it.

First curation op: organ-vocabulary canonicalization. The narrative's organ
signature reads `genes.organs` (a VARCHAR[] column), so the mapping is applied
there; it is also applied to `paper_organs` to keep the corpus consistent.

Materialization mirrors pipeline/session_db.py: build/mutate at a temp path
(DuckDB's create-time fcntl lock blocks on the /workspace mount; a plain file
copy does not), CHECKPOINT to fold the WAL, then shutil.copyfile into place.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import duckdb

from knowledge_base.genefunc_crawl import ORGAN_NORMALIZE, ORGAN_SEARCH_TERMS
from common.clock import now_iso
from workflow.store import DiskPoolStore

# The frozen, read-only baseline corpus at the repo root.
FROZEN_CORPUS = Path(__file__).parent.parent / "bmdx.duckdb"

_TWEAKS_NAME = "corpus_tweaks.jsonl"
_CORPUS_NAME = "corpus.duckdb"
_FINGERPRINT_NAME = ".corpus.fingerprint"


# ---------------------------------------------------------------------------
# Canonical vocabulary (seed suggestions for the UI)
# ---------------------------------------------------------------------------
def canonical_organs() -> list[str]:
    """The hand-made canonical organ whitelist, as map suggestions."""
    return sorted(ORGAN_SEARCH_TERMS.keys())


def seed_organ_map() -> dict[str, str]:
    """A starting noisy→canonical map (the existing ORGAN_NORMALIZE), lowercased."""
    return {k.strip().lower(): v for k, v in ORGAN_NORMALIZE.items()}


# ---------------------------------------------------------------------------
# Per-session paths
# ---------------------------------------------------------------------------
def _store() -> DiskPoolStore:
    return DiskPoolStore()


def tweaks_path(dtxsid: str) -> Path:
    return _store().session_dir(dtxsid) / _TWEAKS_NAME


def corpus_path(dtxsid: str) -> Path:
    return _store().session_dir(dtxsid) / _CORPUS_NAME


def _fingerprint_path(dtxsid: str) -> Path:
    return _store().session_dir(dtxsid) / _FINGERPRINT_NAME


# ---------------------------------------------------------------------------
# Tweak log (append-only)
# ---------------------------------------------------------------------------
def read_tweaks(dtxsid: str) -> list[dict]:
    """The append-only tweak-log as a list, oldest → newest. Empty if none."""
    path = tweaks_path(dtxsid)
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def append_tweak(dtxsid: str, tweak: dict) -> dict:
    """Validate, timestamp, and append one tweak. Returns the stored record.

    Raises ValueError on a malformed tweak (the validate-before-write gate).
    """
    op = tweak.get("op")
    if op != "map_organ":
        raise ValueError(f"unsupported op: {op!r}")
    src = tweak.get("from")
    if not isinstance(src, str) or not src.strip():
        raise ValueError("'from' must be a non-empty string")
    dst = tweak.get("to")
    if dst is not None and (not isinstance(dst, str) or not dst.strip()):
        raise ValueError("'to' must be a non-empty string or null (drop)")
    if isinstance(dst, str) and dst.strip().lower() == src.strip().lower():
        raise ValueError("'from' and 'to' are identical — no-op")

    record = {
        "op": "map_organ",
        "from": src.strip().lower(),
        "to": dst.strip().lower() if isinstance(dst, str) else None,
        "ts": now_iso(),
    }
    path = tweaks_path(dtxsid)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    _fingerprint_path(dtxsid).write_text(str(path.stat().st_size), encoding="utf-8")
    return record


def current_organ_map(dtxsid: str) -> dict[str, str | None]:
    """Fold the log into the net mapping, last-writer-wins per source term.

    Value is the canonical target, or None to drop the term.
    """
    net: dict[str, str | None] = {}
    for t in read_tweaks(dtxsid):
        if t.get("op") == "map_organ" and t.get("from"):
            net[t["from"]] = t.get("to")
    return net


# ---------------------------------------------------------------------------
# Inventory (what the UI displays)
# ---------------------------------------------------------------------------
def organ_inventory(dtxsid: str) -> list[dict]:
    """Distinct organ terms + frequencies from the FROZEN corpus, annotated with
    the current net mapping. genes.organs and paper_organs are unioned; `sources`
    lists which tables a term appears in.
    """
    net = current_organ_map(dtxsid)
    con = duckdb.connect(str(FROZEN_CORPUS), read_only=True)
    try:
        gene_rows = con.execute(
            "SELECT organ, COUNT(*) FROM (SELECT UNNEST(organs) AS organ FROM genes) "
            "GROUP BY organ"
        ).fetchall()
        paper_rows = con.execute(
            "SELECT organ, COUNT(*) FROM paper_organs GROUP BY organ"
        ).fetchall()
    finally:
        con.close()

    agg: dict[str, dict] = {}
    for organ, count in gene_rows:
        if organ is None:
            continue
        e = agg.setdefault(organ, {"organ": organ, "genes_count": 0, "papers_count": 0})
        e["genes_count"] = count
    for organ, count in paper_rows:
        if organ is None:
            continue
        e = agg.setdefault(organ, {"organ": organ, "genes_count": 0, "papers_count": 0})
        e["papers_count"] = count

    inventory = []
    for organ, e in agg.items():
        sources = []
        if e["genes_count"]:
            sources.append("genes")
        if e["papers_count"]:
            sources.append("paper_organs")
        inventory.append({
            "organ": organ,
            "genes_count": e["genes_count"],
            "papers_count": e["papers_count"],
            "total": e["genes_count"] + e["papers_count"],
            "sources": sources,
            "mapped_to": net.get(organ, "__unset__") if organ in net else None,
        })
    inventory.sort(key=lambda r: r["total"], reverse=True)
    return inventory


# ---------------------------------------------------------------------------
# Materialization (project the log onto a copy of the frozen corpus)
# ---------------------------------------------------------------------------
def materialize(dtxsid: str) -> dict:
    """Build the curated corpus.duckdb by applying the net organ map to a copy
    of the frozen original. Returns table counts. Idempotent given the log.
    """
    net = current_organ_map(dtxsid)
    dest = corpus_path(dtxsid)
    dest.parent.mkdir(parents=True, exist_ok=True)

    tmp_root = os.environ.get("BMDX_SESSION_DB_TMPDIR") or None
    tmp_dir = Path(tempfile.mkdtemp(dir=tmp_root))
    tmp_db = tmp_dir / _CORPUS_NAME
    try:
        shutil.copyfile(str(FROZEN_CORPUS), str(tmp_db))
        con = duckdb.connect(str(tmp_db))  # read-write
        try:
            con.execute("CREATE TEMP TABLE organ_map(k VARCHAR, v VARCHAR)")
            if net:
                con.executemany(
                    "INSERT INTO organ_map VALUES (?, ?)",
                    [(k, v) for k, v in net.items()],
                )
                # genes.organs (VARCHAR[]): explode → remap via join → regroup.
                # Set-based (row-by-row UPDATE over 22k rows is far too slow).
                con.execute("""
                    CREATE OR REPLACE TABLE genes AS
                    WITH exploded AS (
                        SELECT g.gene_symbol, g.evidence, g.mention_count,
                               u.organ AS raw_organ
                        FROM genes g
                        LEFT JOIN LATERAL UNNEST(g.organs) AS u(organ) ON TRUE
                    ),
                    remapped AS (
                        SELECT e.gene_symbol, e.evidence, e.mention_count,
                               COALESCE(m.v, e.raw_organ) AS organ,
                               (e.raw_organ IS NOT NULL
                                AND (m.k IS NULL OR m.v IS NOT NULL)) AS keep
                        FROM exploded e
                        LEFT JOIN organ_map m ON e.raw_organ = m.k
                    )
                    SELECT gene_symbol,
                           any_value(evidence) AS evidence,
                           any_value(mention_count) AS mention_count,
                           array_agg(DISTINCT organ)
                             FILTER (WHERE organ IS NOT NULL AND keep) AS organs
                    FROM remapped GROUP BY gene_symbol
                """)
                # paper_organs: drop null-mapped, remap the rest.
                con.execute(
                    "DELETE FROM paper_organs WHERE organ IN "
                    "(SELECT k FROM organ_map WHERE v IS NULL)"
                )
                con.execute(
                    "UPDATE paper_organs SET organ = "
                    "(SELECT v FROM organ_map WHERE k = paper_organs.organ) "
                    "WHERE organ IN (SELECT k FROM organ_map WHERE v IS NOT NULL)"
                )
            con.execute("CHECKPOINT")
            counts = {
                "genes": con.execute("SELECT COUNT(*) FROM genes").fetchone()[0],
                "paper_organs": con.execute(
                    "SELECT COUNT(*) FROM paper_organs"
                ).fetchone()[0],
                "distinct_gene_organs": con.execute(
                    "SELECT COUNT(DISTINCT organ) FROM "
                    "(SELECT UNNEST(organs) AS organ FROM genes)"
                ).fetchone()[0],
            }
        finally:
            con.close()
        shutil.copyfile(str(tmp_db), str(dest))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {"path": str(dest), "counts": counts, "applied_mappings": len(net)}


def is_curated(dtxsid: str) -> bool:
    """True if a materialized curated corpus exists for this session."""
    return corpus_path(dtxsid).exists()


def reset(dtxsid: str) -> dict:
    """Revert to the frozen original: remove log, corpus, and fingerprint."""
    removed = []
    for p in (tweaks_path(dtxsid), corpus_path(dtxsid), _fingerprint_path(dtxsid)):
        if p.exists():
            p.unlink()
            removed.append(p.name)
    return {"removed": removed}
