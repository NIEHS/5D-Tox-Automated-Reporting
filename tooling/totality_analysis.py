#!/usr/bin/env python3
"""tooling/totality_analysis.py — experimental "totality analysis" writer.

Writes a single integrated analysis of the WHOLE of one study's experimental
data — every apical platform plus the transcriptomics — and connects the gene
signals back to the apical endpoints. This is the direct gene->apical framing the
team settled on (see memory project_gene_apical_integration.md), grounded in the
knowledge graph and expressed through an ontology roll-up: flat GO gene-sets are
grouped into their anc2vec/UMAP clusters so the genomics reads as interpretable
functional themes rather than a flat term list.

It is EXPLORATORY, not report text (ADR-0022): it reads only integrated-derived
sources (the session's session.duckdb) plus the knowledge base, and never touches
the document tree or a render surface.

Design (see plan): a deterministic "totality brief" guarantees coverage of every
apical platform and both organs x sexes; the brief is handed to the ADR-0022 tool
loop (narrative.chat_agent.run_turn) with an analysis system prompt and a larger
budget, so the model writes the synthesis and can drill into the GO clusters and
the literature (kb_* tools) for specifics and citations.

Usage:
    python -m tooling.totality_analysis --dtxsid DTXSID50469320 \
        --chemical "Perfluorohexanesulfonamide (PFHxSAm)"
    python -m tooling.totality_analysis --dtxsid DTXSID50469320 --brief-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from pathlib import Path

import duckdb

from narrative.chat_agent import run_turn
from narrative.chat_tools import ChatToolbox, SourceRegistry, TOOL_SPECS
from query.session_query import SessionQuerier

DEFAULT_KB_PATH = "bmdx.duckdb"
OUTPUT_DIR = Path("output")
DEFAULT_MODEL = "claude-sonnet-4-6"
WRITER_MAX_TOKENS = 16000
GATHER_MAX_TOKENS = 2500
GATHER_MAX_ROUNDS = 14

# How many rolled-up clusters to surface per organ x sex in the brief / tool.
TOP_CLUSTERS = 12
# Member terms shown per cluster (the rest are summarised as "+N more").
TERMS_PER_CLUSTER = 4


# ---------------------------------------------------------------------------
# GO cluster roll-up — the ontology augmentation
# ---------------------------------------------------------------------------

def _load_go_clusters(kb_path: str) -> dict[str, int]:
    """go_id -> cluster_id from the KB's anc2vec/UMAP clustering."""
    con = duckdb.connect(kb_path, read_only=True)
    try:
        rows = con.execute("SELECT go_id, cluster_id FROM go_terms").fetchall()
    finally:
        con.close()
    return {go_id: cid for go_id, cid in rows}


def _median(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None and v == v]  # drop None / NaN
    return round(statistics.median(clean), 2) if clean else None


def rollup_go_by_cluster(
    gene_set_rows: list[dict],
    go_clusters: dict[str, int],
    *,
    top: int = TOP_CLUSTERS,
) -> list[dict]:
    """Group GO gene-set rows into their anc2vec/UMAP clusters.

    ``gene_set_rows`` come from session.duckdb's ``gene_set`` table (one row per
    tested GO gene-set for one organ x sex): each has ``go_id, go_term, bmd,
    direction, n_genes, fishers_p``. We group by the KB cluster the GO id belongs
    to and rank clusters by median gene-set BMD (ascending = most dose-sensitive
    functional themes first), which is what ties them to the apical BMDs.

    Returns a list of cluster dicts, most-sensitive first, each with a
    representative label (its lowest-BMD member), the member terms, the median
    BMD, the count of enrichment-significant members, and the dominant direction.
    """
    buckets: dict[object, list[dict]] = {}
    for r in gene_set_rows:
        cid = go_clusters.get(r["go_id"], "unclustered")
        if cid == -1:
            cid = "unclustered"
        buckets.setdefault(cid, []).append(r)

    clusters = []
    for cid, members in buckets.items():
        members_sorted = sorted(
            members, key=lambda m: (m["bmd"] is None, m["bmd"] if m["bmd"] is not None else 1e9)
        )
        rep = members_sorted[0]
        dirs = [m["direction"] for m in members if m.get("direction")]
        dominant = max(set(dirs), key=dirs.count) if dirs else ""
        clusters.append({
            "cluster_id": cid,
            "representative": rep["go_term"],
            "n_terms": len(members),
            "median_bmd": _median([m["bmd"] for m in members]),
            "min_bmd": round(rep["bmd"], 2) if rep["bmd"] is not None else None,
            "n_significant": sum(1 for m in members if (m.get("fishers_p") or 1.0) < 0.05),
            "direction": dominant,
            "member_terms": [
                {
                    "go_term": m["go_term"],
                    "bmd": round(m["bmd"], 2) if m["bmd"] is not None else None,
                    "direction": m.get("direction", ""),
                }
                for m in members_sorted[:TERMS_PER_CLUSTER]
            ],
            "more_terms": max(0, len(members) - TERMS_PER_CLUSTER),
        })

    # Most dose-sensitive themes first; a cluster with no numeric BMD sinks.
    clusters.sort(key=lambda c: (c["median_bmd"] is None, c["median_bmd"] if c["median_bmd"] is not None else 1e9))
    named = [c for c in clusters if c["cluster_id"] != "unclustered"]
    return named[:top]


# ---------------------------------------------------------------------------
# session.duckdb readers
# ---------------------------------------------------------------------------

def _gene_set_rows(q: SessionQuerier, organ: str, sex: str) -> list[dict]:
    res = q.run_sql(
        "SELECT go_id, go_term, bmd, direction, n_genes, fishers_p "
        f"FROM gene_set WHERE organ = '{organ}' AND sex = '{sex}'"
    )
    cols = res["columns"]
    return [dict(zip(cols, row)) for row in res["rows"]]


def _organ_sex_pairs(q: SessionQuerier) -> list[tuple[str, str]]:
    res = q.run_sql("SELECT DISTINCT organ, sex FROM gene ORDER BY organ, sex")
    return [(r[0], r[1]) for r in res["rows"]]


# ---------------------------------------------------------------------------
# Totality brief — deterministic, guarantees coverage
# ---------------------------------------------------------------------------

def _apical_block(q: SessionQuerier) -> str:
    lines = ["## Apical findings (per platform x sex)\n"]
    study = q.run_sql(
        "SELECT species, strain, duration, route, vehicle, source_file_count FROM study"
    )["rows"]
    if study:
        sp, st, du, ro, ve, nf = study[0]
        lines.append(
            f"Study: {sp or '?'} {st or ''}, {du or '?'} exposure, route={ro or '?'}, "
            f"vehicle={ve or '?'}, {nf or 0} source files.\n"
        )
    measured = q.run_sql("SELECT DISTINCT platform FROM measurement ORDER BY platform")["rows"]
    lines.append("Platforms measured: " + ", ".join(p[0] for p in measured) + "\n")

    res = q.run_sql(
        "SELECT platform, sex, endpoint, bmd_str, bmd_num, bmd_status, direction "
        "FROM apical_result ORDER BY platform, sex, endpoint"
    )
    rows = res["rows"]
    if not rows:
        lines.append("_No modeled apical endpoints in this session._\n")
        return "\n".join(lines)

    current = None
    for platform, sex, endpoint, bmd_str, bmd_num, status, direction in rows:
        key = (platform, sex)
        if key != current:
            lines.append(f"\n**{platform} — {sex}**")
            current = key
        dir_txt = f", {direction}" if direction else ""
        if bmd_num is not None:
            lines.append(f"- {endpoint}: BMD {bmd_str}{dir_txt}")
        else:
            # non-viable model (NVM/UREP/—): report the trend if any
            note = f" ({status})" if status else ""
            lines.append(f"- {endpoint}: no viable BMD{note}{dir_txt}")
    return "\n".join(lines) + "\n"


def _genomics_block(q: SessionQuerier, go_clusters: dict[str, int]) -> str:
    lines = ["## Transcriptomic findings (per organ x sex)\n"]
    for organ, sex in _organ_sex_pairs(q):
        g = q.run_sql(
            "SELECT count(*), round(min(bmd),2), round(median(bmd),2) "
            f"FROM gene WHERE organ='{organ}' AND sex='{sex}' AND bmd IS NOT NULL AND NOT isnan(bmd)"
        )["rows"][0]
        n_genes, gmin, gmed = g
        lines.append(f"\n**{organ} — {sex}**: {n_genes} responsive genes "
                     f"(gene BMD min {gmin}, median {gmed}).")

        # Adverse-outcome signatures (the 5D activation calls)
        sigs = q.run_sql(
            "SELECT title, active, round(bmd,1), direction, fishers_p "
            f"FROM adversity_signature WHERE organ='{organ}' AND sex='{sex}' ORDER BY bmd"
        )["rows"]
        active = [f"{t} (BMD {b}, {d})" for t, a, b, d, p in sigs if a and b is not None]
        if active:
            lines.append("  Active adverse-outcome signatures: " + "; ".join(active) + ".")

        # GO cluster roll-up (the ontology view)
        rows = _gene_set_rows(q, organ, sex)
        clusters = rollup_go_by_cluster(rows, go_clusters)
        lines.append("  GO functional clusters (rolled up from anc2vec/UMAP; "
                     "most dose-sensitive first):")
        for c in clusters:
            terms = ", ".join(
                f"{t['go_term']} (BMD {t['bmd']})" for t in c["member_terms"]
            )
            more = f" +{c['more_terms']} more" if c["more_terms"] else ""
            lines.append(
                f"  - [{c['representative']}] median BMD {c['median_bmd']}, "
                f"{c['n_terms']} terms ({c['n_significant']} p<0.05), {c['direction']}: "
                f"{terms}{more}"
            )
    return "\n".join(lines) + "\n"


def assemble_totality_brief(dtxsid: str, kb_path: str = DEFAULT_KB_PATH) -> str:
    """Deterministic brief covering the totality of the study's data."""
    go_clusters = _load_go_clusters(kb_path)
    with SessionQuerier(dtxsid) as q:
        brief = (
            f"# Totality data brief — {dtxsid}\n\n"
            + _apical_block(q) + "\n"
            + _genomics_block(q, go_clusters)
        )
    return brief


# ---------------------------------------------------------------------------
# Toolbox — chat tools + a GO cluster drill-down
# ---------------------------------------------------------------------------

_GO_CLUSTER_TOOL = {
    "name": "go_cluster_enrichment",
    "description": (
        "GO gene-sets for one organ+sex, rolled up into their anc2vec/UMAP "
        "functional clusters and ranked by median BMD (most dose-sensitive "
        "first). Use to name the transcriptomic response themes and their "
        "dose sensitivity when connecting genomics to apical endpoints."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "organ": {"type": "string", "description": "e.g. liver, kidney"},
            "sex": {"type": "string", "description": "male or female"},
        },
        "required": ["organ", "sex"],
    },
}


class TotalityToolbox(ChatToolbox):
    """ChatToolbox plus a GO-cluster drill-down tool for the totality writer."""

    def __init__(self, *args, kb_path: str = DEFAULT_KB_PATH, **kwargs):
        super().__init__(*args, kb_path=kb_path, **kwargs)
        self._go_clusters = _load_go_clusters(str(self.kb_path))

    def specs(self) -> list[dict]:
        return TOOL_SPECS + [_GO_CLUSTER_TOOL]

    def execute(self, name: str, inputs: dict) -> str:
        if name == "go_cluster_enrichment":
            return self._go_cluster_enrichment(inputs or {})
        return super().execute(name, inputs)

    def _go_cluster_enrichment(self, inputs: dict) -> str:
        organ = str(inputs.get("organ") or "").lower()
        sex = str(inputs.get("sex") or "").lower()
        try:
            with SessionQuerier(self.dtxsid) as q:
                rows = _gene_set_rows(q, organ, sex)
        except Exception as e:  # tool errors are data for the model, not crashes
            out = json.dumps({"error": f"go_cluster_enrichment failed: {e}"})
            self.trace.append({"tool": "go_cluster_enrichment", "input": inputs, "output_chars": len(out)})
            return out
        clusters = rollup_go_by_cluster(rows, self._go_clusters)
        out = json.dumps({"organ": organ, "sex": sex, "clusters": clusters}, ensure_ascii=False)
        self.trace.append({"tool": "go_cluster_enrichment", "input": inputs, "output_chars": len(out)})
        return out


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------

# Phase A — gather citations with tools. The numbers already live in the brief;
# the tool-using pass exists only to surface literature [Sn] tokens. (The chat
# model, told to be exhaustive, never volunteers prose — so we keep writing out
# of this phase entirely and do it tool-free in phase B.)
GATHER_SYSTEM_PROMPT = """\
You are gathering literature evidence for an integrated analysis of one NTP 5-day \
genomic dose-response study in Sprague-Dawley rats, on {chemical}. A deterministic \
data brief (with every number) is provided.

Your ONLY job now is to gather citations. Use the knowledge-graph tools — \
kb_gene_evidence, kb_papers_for_genes, kb_pathway_genes (and go_cluster_enrichment \
for cluster detail) — to find papers supporting the most important cross-domain \
gene->apical mechanistic links: the most dose-sensitive sentinel genes and \
enriched functional clusters in liver and kidney (both sexes), and the apical \
endpoints they might explain (thyroid hormones, liver weight, lipids).

Do NOT write the analysis. Do NOT call run_sql — the brief already has the \
numbers. For roughly 8-12 key genes or gene sets, call a knowledge-graph tool to \
pull supporting papers, noting briefly which [Sn] token supports which link. When \
you have enough, stop.
"""

GATHER_INSTRUCTION = (
    "Data brief for the study:\n\n{brief}\n\n"
    "Gather literature citations for the key cross-domain links now."
)

# Phase B — write, tool-free, from the brief + the citations phase A surfaced.
ANALYSIS_SYSTEM_PROMPT = """\
You are a toxicologist writing an integrated analysis of the TOTALITY of one NTP \
5-day genomic dose-response study in Sprague-Dawley rats, on {chemical}. You are \
given a deterministic DATA BRIEF (every apical platform plus the transcriptomics \
for each organ x sex) and a list of AVAILABLE CITATIONS. Write ONE cohesive \
analysis, not a section-by-section dump.

Structure:
1. Study overview.
2. Apical findings by domain (organ weight, clinical chemistry, hematology, \
hormones), with BMDs and direction.
3. Transcriptomic findings per organ x sex: the dose-sensitive GO functional \
clusters (use the rolled-up cluster themes, not a flat term list) and the active \
adverse-outcome signatures.
4. Cross-domain integration — the point: connect gene-level signals to apical \
endpoints. Prefer BMD concordance (do transcriptomic clusters respond at or below \
the apical BMDs?) and direct gene->biomarker links within THIS study. Do NOT \
invoke cross-species (mouse-KO) reasoning as evidence.
5. What the data do NOT support: endpoints where genomics and apical disagree or \
where a link cannot be drawn.

Rules:
- You have NO tools. Every number MUST come from the DATA BRIEF; do not invent \
numbers.
- Support mechanism/literature claims with the [Sn] tokens from the AVAILABLE \
CITATIONS list, cited inline (e.g. "... CAR-mediated induction [S3]"). Use ONLY \
tokens in that list; never invent one. Leaving a claim uncited is fine when no \
provided citation fits.
- Be quantitative and concise; distinguish adaptive from adverse responses; when \
a link is suggestive but not established, say so.
- Output the analysis directly, starting at the "# Integrated Totality Analysis" \
heading — no preamble. Finish every section you start, including any summary table.
"""

WRITE_INSTRUCTION = (
    "DATA BRIEF:\n\n{brief}\n\n"
    "AVAILABLE CITATIONS (cite by token; only these are valid):\n{citations}\n\n"
    "Write the complete integrated totality analysis now."
)


class _NoToolsBox:
    """A run_turn toolbox that exposes no tools, so the model must answer in prose.

    Shares the phase-A SourceRegistry so the [Sn] tokens gathered there still
    validate during citation checking. run_turn only touches ``specs``,
    ``registry`` and ``trace`` when no tool is ever called."""

    def __init__(self, registry: SourceRegistry):
        self.registry = registry
        self.trace: list[dict] = []

    def specs(self) -> list[dict]:
        return []

    def execute(self, name: str, inputs: dict) -> str:  # never reached (no specs)
        return "{}"


def _format_citations(registry: SourceRegistry) -> str:
    if not registry.sources:
        return "(none gathered)"
    lines = []
    for s in registry.sources:
        genes = ", ".join(s.get("genes") or [])
        gtxt = f" — genes: {genes}" if genes else ""
        lines.append(f"[{s['token']}] {s.get('title', '')} ({s.get('year') or ''}){gtxt}")
    return "\n".join(lines)


def _render_markdown(dtxsid: str, chemical: str, result: dict) -> str:
    parts = [
        f"# Totality analysis — {chemical} ({dtxsid})\n",
        f"*Experimental, exploratory (ADR-0022) — not report text. "
        f"Model: {result.get('model_used')}, {result.get('rounds')} tool rounds.*\n",
        result["answer"].strip(),
    ]
    refs = result.get("references") or []
    if refs:
        parts.append("\n## References\n")
        for r in refs:
            bits = [b for b in (r.get("title"), str(r.get("year") or ""), r.get("venue"), r.get("doi")) if b]
            parts.append(f"- {r['token']}: " + ". ".join(bits))
    unresolved = result.get("unresolved_citations")
    if unresolved:
        parts.append(f"\n> Note: {len(unresolved)} unresolved citation(s) flagged by verification.")
    return "\n".join(parts) + "\n"


async def write_totality_analysis(
    dtxsid: str,
    *,
    chemical: str,
    model: str = DEFAULT_MODEL,
    kb_path: str = DEFAULT_KB_PATH,
) -> Path:
    brief = assemble_totality_brief(dtxsid, kb_path=kb_path)
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / f"{dtxsid}-totality-brief.md").write_text(brief)

    registry = SourceRegistry()

    # Phase A — gather citations with the knowledge-graph tools.
    gather_box = TotalityToolbox(dtxsid, registry, chemical_name=chemical, kb_path=kb_path)
    await run_turn(
        history=[],
        user_message=GATHER_INSTRUCTION.format(brief=brief),
        toolbox=gather_box,
        chemical_name=chemical,
        model=model,
        system_prompt=GATHER_SYSTEM_PROMPT.format(chemical=chemical),
        max_tokens=GATHER_MAX_TOKENS,
        max_rounds=GATHER_MAX_ROUNDS,
    )
    citations = _format_citations(registry)

    # Phase B — write in a clean, tool-free context (guaranteed prose); the shared
    # registry lets the [Sn] tokens gathered in phase A pass citation checking.
    result = await run_turn(
        history=[],
        user_message=WRITE_INSTRUCTION.format(brief=brief, citations=citations),
        toolbox=_NoToolsBox(registry),
        chemical_name=chemical,
        model=model,
        system_prompt=ANALYSIS_SYSTEM_PROMPT.format(chemical=chemical),
        max_tokens=WRITER_MAX_TOKENS,
        max_rounds=1,
    )
    result["citations_gathered"] = len(registry.sources)
    out = OUTPUT_DIR / f"{dtxsid}-totality-analysis.md"
    out.write_text(_render_markdown(dtxsid, chemical, result))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Experimental totality-analysis writer.")
    ap.add_argument("--dtxsid", default="DTXSID50469320")
    ap.add_argument("--chemical", default="", help="Friendly compound name for the prose.")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--kb", default=DEFAULT_KB_PATH, help="Path to bmdx.duckdb")
    ap.add_argument("--brief-only", action="store_true",
                    help="Assemble and print the deterministic brief; no LLM call.")
    args = ap.parse_args()

    chemical = args.chemical or args.dtxsid

    if args.brief_only:
        brief = assemble_totality_brief(args.dtxsid, kb_path=args.kb)
        OUTPUT_DIR.mkdir(exist_ok=True)
        p = OUTPUT_DIR / f"{args.dtxsid}-totality-brief.md"
        p.write_text(brief)
        print(brief)
        print(f"\n[wrote {p}]")
        return

    out = asyncio.run(write_totality_analysis(
        args.dtxsid, chemical=chemical, model=args.model, kb_path=args.kb
    ))
    print(f"[wrote {out}]")


if __name__ == "__main__":
    main()
