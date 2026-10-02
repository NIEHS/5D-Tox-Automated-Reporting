"""genomics/bmdexpress_categories.py — read BMDExpress's own category analyses
from the integrated project.

A BMDExpress 3 project carries, per gene-expression experiment, the category
analyses its analyst ran:
  * GO_BP — GO Biological Process gene sets (the Top-10 GO table);
  * GENE  — one "category" per Entrez gene, aggregating that gene's probes
    (the Top-10 genes table).

Both carry BMDExpress's filter outcome (``genesThatPassedAllFilters``) and its
direction counts (``genesAdverseUpCount`` / ``genesAdverseDownCount``).  The
published 2025 reports (NIEHS-12/13) build their tables from exactly these: the
Top-10 genes are GENE categories that passed all filters, sorted by BMD median
across the gene's probes (Entrez IDs, multi-probe genes, one probe mapping to
two genes), and the GO table's "Genes with Changed Direction Up/Down" are the
adverse-direction counts.  Reproduced exactly for NIEHS-13 rat liver; see
assets/cebs/NIEHS-13-comparison.md.

Everything here reads the integrated project (CLAUDE.md invariant #1).  A
project without GENE analyses (older analyses) yields nothing, and callers keep
their previous per-probe behaviour.
"""

from __future__ import annotations

import math
import statistics


def _float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _owning_experiment(analysis_name: str, exp_names: list[str]) -> str | None:
    """The experiment an analysis belongs to: its name is the experiment name
    plus BMDExpress pipeline suffixes ("<exp>_curvefitprefilter_..._GENE_...")."""
    for name in sorted(exp_names, key=len, reverse=True):
        if analysis_name == name or analysis_name.startswith(name + "_"):
            return name
    return None


def category_analyses_by_experiment(integrated: dict) -> dict[str, dict[str, list[dict]]]:
    """{experiment name: {"GENE": [result, ...], "GO_BP": [result, ...]}}."""
    exp_names = [e.get("name", "") for e in integrated.get("doseResponseExperiments", []) or []]
    out: dict[str, dict[str, list[dict]]] = {}
    for ca in integrated.get("categoryAnalysisResults", []) or []:
        if not isinstance(ca, dict):
            continue
        name = ca.get("name", "") or ""
        kind = "GENE" if "_GENE_" in name else "GO_BP" if "_GO_BP_" in name else None
        exp = _owning_experiment(name, exp_names) if kind else None
        if exp is None:
            continue
        items = [r for r in ca.get("categoryAnalsyisResults") or [] if isinstance(r, dict)]
        out.setdefault(exp, {}).setdefault(kind, []).extend(items)
    return out


def go_direction_counts(go_items: list[dict]) -> dict[str, tuple[int, int]]:
    """{GO id: (genes up, genes down)} from BMDExpress's adverse-direction counts."""
    out: dict[str, tuple[int, int]] = {}
    for r in go_items:
        ident = r.get("categoryIdentifier") or {}
        go_id = ident.get("id") if isinstance(ident, dict) else None
        if go_id:
            out[go_id] = (int(r.get("genesAdverseUpCount") or 0),
                          int(r.get("genesAdverseDownCount") or 0))
    return out


def _display_symbol(symbol: str, species: str | None) -> str:
    """BMDExpress stores symbols lower-case.  Rodent symbols are written with an
    initial capital (Cyp2b1); human symbols are upper case (CYP2B6)."""
    if (species or "").lower() in ("homo sapiens", "human"):
        return symbol.upper()
    return symbol[:1].upper() + symbol[1:]


def gene_level_top_genes(
    gene_items: list[dict],
    probe_fold_change: dict[str, float],
    species: str | None,
    n: int = 10,
) -> list[dict]:
    """The Top-n genes: GENE categories that passed all BMDExpress filters,
    ranked by BMD median across the gene's probes.

    ``probe_fold_change`` maps probe id → that probe's signed maximum fold
    change; a gene's fold change is the median magnitude over its probes,
    signed by the gene's direction."""
    rows = []
    for r in gene_items:
        if (r.get("genesThatPassedAllFilters") or 0) < 1:
            continue
        bmd = _float(r.get("bmdMedian"))
        if bmd is None:
            continue
        up = int(r.get("genesAdverseUpCount") or 0)
        down = int(r.get("genesAdverseDownCount") or 0)
        direction = "up" if up and not down else "down" if down and not up else "conflict"
        probes = [p for p in str(r.get("probeIds") or "").split(",") if p]
        fcs = [abs(probe_fold_change[p]) for p in probes if _float(probe_fold_change.get(p)) is not None]
        fc = statistics.median(fcs) if fcs else None
        if fc is not None and direction == "down":
            fc = -fc
        rows.append({
            "gene_symbol": _display_symbol(str(r.get("geneSymbolsPrivate") or ""), species),
            "entrez_id": str(r.get("genesIds") or ""),
            "probe_id": ",".join(probes),
            "bmd": bmd,
            "bmdl": _float(r.get("bmdlMedian")),
            "bmdu": _float(r.get("bmduMedian")),
            "direction": direction,
            "fold_change": fc,
        })
    rows.sort(key=lambda x: (x["bmd"], x["gene_symbol"]))
    return [{"rank": i + 1, **x} for i, x in enumerate(rows[:n])]


def genomic_bmr(integrated: dict, exp_name: str) -> dict | None:
    """{"type": "Relative Deviation", "factor": 0.25} recorded by the BMD
    analysis of one experiment (its analysisInfo notes), or None."""
    for b in integrated.get("bMDResult", []) or []:
        if not isinstance(b, dict):
            continue
        name = b.get("name", "") or ""
        if not (name == exp_name or name.startswith(exp_name + "_")):
            continue
        notes = (b.get("analysisInfo") or {}).get("notes") or []
        rec = {}
        for note in notes:
            key, _, value = str(note).partition(":")
            if key.strip() == "BMR Type":
                rec["type"] = value.strip()
            elif key.strip() == "BMR Factor":
                rec["factor"] = _float(value.strip())
        if rec.get("type"):
            return rec
    return None
