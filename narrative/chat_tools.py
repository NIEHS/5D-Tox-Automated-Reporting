"""
narrative/chat_tools.py — the tools the session chatbot can call, and the
registry of literature sources it may cite.

What this is: the "hands" of the graph-augmented interpretation chat (ADR-0022).
The model does not get the study data stuffed into its prompt; it gets a small
set of TOOLS and decides, per question, what to look up:

  * `list_tables` / `run_sql`        — the per-session DuckDB query substrate
                                       (ADR-0016): read-only SELECT over the
                                       apical results, BMD stats, genes, gene
                                       sets, measurements, dose groups ...
  * `list_report_sections` /
    `read_report_section`            — the generated report content itself
                                       (background, BMD summary, apical and
                                       genomics narratives, references), read
                                       through the same loader the LaTeX
                                       export uses, so the chat sees exactly
                                       what the report says.
  * `kb_gene_evidence` /
    `kb_papers_for_genes` /
    `kb_pathway_genes`               — the toxicogenomics knowledge graph
                                       (bmdx.duckdb): pathways, GO terms,
                                       organs, literature claims and PAPERS.

Every paper a knowledge-graph tool returns is registered in a `SourceRegistry`
and handed to the model as a stable `[Sn]` token. The model may cite ONLY
those tokens; after the answer, `chat_agent` verifies the citations with
narrative/citation_check (the same layer the report narratives use) and
resolves the tokens to full references. That is what makes an answer
"grounded" rather than merely plausible.

Safety properties (each enforced here, not by prompt wording):
  * SQL is read-only and single-statement (query.session_query validates and
    opens the DB read_only); row and character output are capped.
  * The knowledge base is opened read-only; every query is parameterised.
  * Report sections are read from the session's cached artifacts — nothing is
    written, and the session id has already passed validate_dtxsid upstream.

HTTP-free (no FastAPI): usable from the routes, from tests with a fake
session, and from any future front-end.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from query.session_query import QueryError, SessionQuerier, session_db_path

logger = logging.getLogger(__name__)

# Output caps: keep a single tool result small enough that a multi-step turn
# never blows the context window, while still useful (200 rows of a BMD table).
TOOL_MAX_ROWS = 200
TOOL_MAX_CHARS = 12_000
# Path of the knowledge graph, resolved the same way the genomics narrative
# does (relative to the working directory / repo root).
DEFAULT_KB_PATH = "bmdx.duckdb"


# ---------------------------------------------------------------------------
# Source registry — the [Sn] tokens the model may cite
# ---------------------------------------------------------------------------

@dataclass
class SourceRegistry:
    """Citable literature sources surfaced to the model in a thread.

    Each distinct paper gets one stable token `S1`, `S2`, ... the first time any
    tool returns it, and keeps that token for the rest of the thread (the
    registry is persisted with the transcript), so a follow-up question can
    cite a paper an earlier answer surfaced. Tokens are the ONLY things the
    model is allowed to cite; `chat_agent` rejects anything else.
    """
    sources: list[dict] = field(default_factory=list)
    _index: dict[str, str] = field(default_factory=dict, repr=False)

    def register(self, paper: dict) -> str:
        """Register a paper (needs at least a paper_id, doi or title); return
        its token. Registering the same paper twice returns the same token."""
        key = str(paper.get("paper_id") or paper.get("doi") or paper.get("title") or "").strip()
        if not key:
            return ""
        if key in self._index:
            return self._index[key]
        token = f"S{len(self.sources) + 1}"
        self.sources.append({
            "token": token,
            "paper_id": paper.get("paper_id") or "",
            "title": paper.get("title") or "",
            "year": paper.get("year"),
            "venue": paper.get("venue") or "",
            "doi": paper.get("doi") or "",
            "citation_count": paper.get("citation_count") or 0,
            "genes": list(paper.get("genes") or []),
        })
        self._index[key] = token
        return token

    def tokens(self) -> set[str]:
        return {s["token"] for s in self.sources}

    def lookup(self, token: str) -> dict | None:
        for s in self.sources:
            if s["token"] == token:
                return s
        return None

    def to_json(self) -> list[dict]:
        return [dict(s) for s in self.sources]

    @classmethod
    def from_json(cls, sources: list[dict] | None) -> "SourceRegistry":
        reg = cls()
        for s in sources or []:
            reg.sources.append(dict(s))
            key = str(s.get("paper_id") or s.get("doi") or s.get("title") or "")
            if key:
                reg._index[key] = s["token"]
        return reg


# ---------------------------------------------------------------------------
# Tool specifications (Anthropic tool-use JSON schema)
# ---------------------------------------------------------------------------

TOOL_SPECS: list[dict] = [
    {
        "name": "list_tables",
        "description": (
            "List the tables and columns of this study session's read-only "
            "database (apical results, BMD statistics, genes, gene sets, "
            "measurements, dose groups, adversity signatures). Call this before "
            "writing SQL."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_sql",
        "description": (
            "Run ONE read-only SELECT (or WITH ... SELECT) against the session "
            "database and return up to 200 rows. Use it for every number you "
            "report: BMD/BMDL values, LOEL/NOEL, responsive endpoints, gene and "
            "gene-set ranks, dose groups. Filter by organ/sex/platform where "
            "relevant."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single SELECT/WITH statement."}},
            "required": ["sql"],
        },
    },
    {
        "name": "list_report_sections",
        "description": (
            "List the sections of the generated report available to read "
            "(background, BMD summary, apical narratives, genomics narratives, "
            "references, ...), with their type and size."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_report_section",
        "description": (
            "Read one section of the generated report as JSON. For list-valued "
            "sections pass `index` to read one item; for dict-valued sections "
            "pass `subkey`. Large content is truncated — narrow with index/subkey."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string"},
                "index": {"type": "integer", "description": "Item index for list sections."},
                "subkey": {"type": "string", "description": "Key for dict sections."},
            },
            "required": ["section"],
        },
    },
    {
        "name": "kb_gene_evidence",
        "description": (
            "Knowledge-graph evidence for one gene symbol: pathways, GO terms, "
            "organs it is associated with, literature claims, and papers "
            "(returned with [Sn] citation tokens you may cite)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"gene_symbol": {"type": "string"}},
            "required": ["gene_symbol"],
        },
    },
    {
        "name": "kb_papers_for_genes",
        "description": (
            "Papers from the knowledge graph that tie together a SET of genes, "
            "ranked by how many of the genes each covers. Returns [Sn] citation "
            "tokens you may cite. Use for pathway/mechanism claims about a "
            "responsive gene set."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gene_symbols": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "description": "Max papers (default 10)."},
            },
            "required": ["gene_symbols"],
        },
    },
    {
        "name": "kb_pathway_genes",
        "description": "Gene symbols the knowledge graph assigns to a named pathway.",
        "input_schema": {
            "type": "object",
            "properties": {"pathway_name": {"type": "string"}},
            "required": ["pathway_name"],
        },
    },
]


# ---------------------------------------------------------------------------
# Toolbox — executes tool calls for one session
# ---------------------------------------------------------------------------

def _truncate(text: str, limit: int = TOOL_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated — {len(text) - limit} more characters; narrow the request]"


def _jsonable(value: Any) -> Any:
    """Make DuckDB / numpy scalars JSON-serialisable without importing numpy."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


class ChatToolbox:
    """Executes the chat tools for one session.

    Args:
        dtxsid:        the session id (already validated by the route).
        registry:      the thread's SourceRegistry (citation tokens persist
                       across turns).
        chemical_name / casrn: passed to the report-data loader so the report
                       sections read as they render.
        kb_path:       path to bmdx.duckdb; missing ⇒ knowledge tools report
                       "unavailable" rather than failing the turn.
    """

    def __init__(
        self,
        dtxsid: str,
        registry: SourceRegistry,
        *,
        chemical_name: str = "the test article",
        casrn: str = "",
        kb_path: str | Path = DEFAULT_KB_PATH,
    ):
        self.dtxsid = dtxsid
        self.registry = registry
        self.chemical_name = chemical_name
        self.casrn = casrn
        self.kb_path = Path(kb_path)
        self._report_data: dict | None = None
        # Every executed call, for the transcript's tool trace.
        self.trace: list[dict] = []

    # -- public -------------------------------------------------------------

    def specs(self) -> list[dict]:
        return TOOL_SPECS

    def execute(self, name: str, inputs: dict) -> str:
        """Run one tool; ALWAYS returns a string (JSON text or an error
        message the model can act on). Never raises into the agent loop."""
        handler = {
            "list_tables": self._list_tables,
            "run_sql": self._run_sql,
            "list_report_sections": self._list_report_sections,
            "read_report_section": self._read_report_section,
            "kb_gene_evidence": self._kb_gene_evidence,
            "kb_papers_for_genes": self._kb_papers_for_genes,
            "kb_pathway_genes": self._kb_pathway_genes,
        }.get(name)
        if handler is None:
            out = json.dumps({"error": f"unknown tool {name!r}"})
        else:
            try:
                out = _truncate(json.dumps(_jsonable(handler(inputs or {})), ensure_ascii=False))
            except QueryError as e:
                out = json.dumps({"error": f"query rejected: {e}"})
            except Exception as e:  # tool errors are data for the model, not crashes
                logger.warning("chat tool %s failed: %s", name, e, exc_info=True)
                out = json.dumps({"error": f"{name} failed: {e}"})
        self.trace.append({"tool": name, "input": inputs, "output_chars": len(out)})
        return out

    # -- session database ---------------------------------------------------

    def _querier(self) -> SessionQuerier:
        if not session_db_path(self.dtxsid).exists():
            raise QueryError(
                "this session has no query database yet — run Process first"
            )
        return SessionQuerier(self.dtxsid)

    def _list_tables(self, _: dict) -> dict:
        with self._querier() as q:
            return q.schema()

    def _run_sql(self, inputs: dict) -> dict:
        sql = str(inputs.get("sql") or "")
        with self._querier() as q:
            return q.run_sql(sql, max_rows=TOOL_MAX_ROWS)

    # -- generated report content ------------------------------------------

    def _report(self) -> dict:
        if self._report_data is None:
            from rendering.latex_export import load_session_data
            self._report_data = load_session_data(
                self.dtxsid, chemical_name=self.chemical_name, casrn=self.casrn or "000-00-0",
            )
        return self._report_data

    def _list_report_sections(self, _: dict) -> dict:
        data = self._report()
        out = []
        for key, val in data.items():
            if val in (None, "", [], {}):
                continue
            kind = "list" if isinstance(val, list) else "dict" if isinstance(val, dict) else "text"
            size = len(val) if isinstance(val, (list, dict, str)) else 1
            out.append({"section": key, "type": kind, "size": size})
        return {"sections": out}

    def _read_report_section(self, inputs: dict) -> Any:
        data = self._report()
        key = str(inputs.get("section") or "")
        if key not in data:
            return {"error": f"no section {key!r}; call list_report_sections"}
        val = data[key]
        if inputs.get("index") is not None and isinstance(val, list):
            i = int(inputs["index"])
            if not 0 <= i < len(val):
                return {"error": f"index {i} out of range 0..{len(val) - 1}"}
            return val[i]
        if inputs.get("subkey") and isinstance(val, dict):
            sub = str(inputs["subkey"])
            if sub not in val:
                return {"error": f"no subkey {sub!r}; available: {sorted(val)[:50]}"}
            return val[sub]
        return val

    # -- knowledge graph ---------------------------------------------------

    def _kb(self):
        if not self.kb_path.exists():
            raise RuntimeError(f"knowledge base unavailable ({self.kb_path} not found)")
        from knowledge_base.toxkb import ToxKBQuerier
        return ToxKBQuerier(str(self.kb_path))

    def _register_papers(self, papers: list[dict]) -> list[dict]:
        out = []
        for p in papers:
            tok = self.registry.register(p)
            if tok:
                entry = {"cite": f"[{tok}]", "title": p.get("title"), "year": p.get("year")}
                if p.get("venue"):
                    entry["venue"] = p["venue"]
                if p.get("genes"):
                    entry["genes"] = p["genes"]
                out.append(entry)
        return out

    def _kb_gene_evidence(self, inputs: dict) -> dict:
        gene = str(inputs.get("gene_symbol") or "").strip().upper()
        if not gene:
            return {"error": "gene_symbol is required"}
        with self._kb() as kb:
            papers = kb.gene_papers(gene)
            meta = kb.papers_metadata([p["paper_id"] for p in papers])
            for p in papers:
                p.update({k: v for k, v in meta.get(p["paper_id"], {}).items() if k in ("venue", "doi")})
            papers.sort(key=lambda p: (-(p.get("citation_count") or 0), p["paper_id"]))
            return {
                "gene": gene,
                "evidence": kb.gene_evidence(gene),
                "organs": kb.gene_organs(gene),
                "pathways": kb.gene_pathways(gene)[:40],
                "go_terms": kb.gene_go_terms(gene)[:40],
                "claims": kb.gene_claims(gene)[:20],
                "papers": self._register_papers(papers[:15]),
            }

    def _kb_papers_for_genes(self, inputs: dict) -> dict:
        genes = [str(g).strip().upper() for g in (inputs.get("gene_symbols") or []) if str(g).strip()]
        if not genes:
            return {"error": "gene_symbols is required"}
        limit = max(1, min(int(inputs.get("limit") or 10), 25))
        if not self.kb_path.exists():
            raise RuntimeError(f"knowledge base unavailable ({self.kb_path} not found)")
        from narrative.references_builder import build_reference_pool_for_genes
        pool = build_reference_pool_for_genes(genes, str(self.kb_path), pool_size=limit)
        return {"genes": genes, "papers": self._register_papers(pool)}

    def _kb_pathway_genes(self, inputs: dict) -> dict:
        name = str(inputs.get("pathway_name") or "").strip()
        if not name:
            return {"error": "pathway_name is required"}
        with self._kb() as kb:
            return {"pathway": name, "genes": kb.pathway_genes(name)}
