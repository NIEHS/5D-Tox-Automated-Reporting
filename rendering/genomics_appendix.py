"""
rendering/genomics_appendix.py — the 2026 books' genomic appendices, built from
the report's data (NIEHS-12, 13 Appendices D.2 and E):

  efdr_methods / efdr_results / appendix_efdr_matrix
      D.2 Empirical False Discovery Rate: how the synthetic null data were made
      and analysed, the summary sentences, and "Empirical False Discovery
      Results" (each species and tissue's gene and GO biological process eFDR,
      mean and range) — from the study's synthetic-null analysis
      (genomics.efdr, the session's efdr.json).
  appendix_gene_set_definitions
      "Active Genes and Definitions within Top 10 <Tissue> Gene Ontology
      Biological Process Gene Sets …": one table per tissue, its top gene sets
      with their active genes, BMD and the GO term's definition
      (genomics.go_definitions, go-basic.obo).
  appendix_gene_identifiers
      "Gene Identifiers and Definitions for <animals> …": one table per study,
      the genes of its top-gene tables with their Entrez ids and probes.

A table repeated per tissue or per study takes its own from a ``by_organ`` /
``by_species`` mapping (render_common.scoped_value).  What the data cannot
supply is a visible placeholder, never a blank: the gene definitions (the
books' human UniProt function text, which this pipeline has no source for),
a GO definition without go-basic.obo, a GO eFDR whose universe is unknown.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from rendering.genomics_results import _Report, _chemical_in_prose, _join, units
from rendering.render_common import (
    _STAT_PHRASE, _bmd_range, _bmr_tag, genomics_table_caption,
)
from tables.table_builder_common import format_display_number

GO_DEFINITION_PENDING = "[Placeholder: GO definition — go-basic.obo not installed]"
GENE_DEFINITION_PENDING = "[Placeholder: gene definition]"
GO_EFDR_PENDING = "[Table data pending: GO eFDR]"
_SPECIES_TITLE = {"rat": "Rat", "mouse": "Mouse"}


def _pct(v: float) -> str:
    """An eFDR percentage as the books print it: two decimals, trailing zeros
    dropped ("0.07", "0.2", "0")."""
    q = Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = format(q.normalize(), "f")
    return "0" if s in ("0", "-0") else s


# ---------------------------------------------------------------------------
# D.2 Empirical False Discovery Rate
# ---------------------------------------------------------------------------

def _summary(values):
    from genomics.efdr import summarize
    return summarize(values)


def appendix_efdr_matrix(efdr: dict | None) -> dict | None:
    if not efdr or not efdr.get("tissues"):
        return None
    rows = []
    for t in efdr["tissues"]:
        gene, go = _summary(t["gene_pct"]), _summary(t["go_pct"])
        rows.append([
            _SPECIES_TITLE.get(t["species"], t["species"].title()), t["tissue"],
            _pct(gene["mean"]), f"{_pct(gene['min'])}–{_pct(gene['max'])}",
            _pct(go["mean"]) if go else GO_EFDR_PENDING,
            (_pct(go["min"]) if go["min"] == go["max"] else f"{_pct(go['min'])}–{_pct(go['max'])}")
            if go else GO_EFDR_PENDING,
        ])
    return {"caption": "Empirical False Discovery Results",
            "headers": ["Species", "Tissue", "Gene eFDR (%) Mean", "Gene eFDR (%) Range",
                        "GO Biological Process eFDR (%) Mean",
                        "GO Biological Process eFDR (%) Range"],
            "rows": rows, "footnotes": [{"kind": "definition", "text":
                "eFDR = empirical false discovery rate; GO = Gene Ontology."}]}


def efdr_results(efdr: dict | None, table: str | None) -> list:
    if not efdr or not efdr.get("tissues"):
        return []
    tissues = efdr["tissues"]
    values = [v for t in tissues for v in t["gene_pct"]]
    top = max(values)
    ref = f" (Table {table})" if table else ""
    bound = "<1%" if top < 1 else f"at most {_pct(top)}%"
    sentences = [f"In all species-tissue combinations, the gene-level eFDR was {bound}, with "
                 f"a range of {_pct(min(values))}% to {_pct(top)}%{ref}."]
    if sum(v < 0.5 for v in values) * 2 > len(values):
        sentences.append("Most gene-level eFDR values were below 0.5%.")
    active = [(t, sum(t["go_active"]), sum(1 for n in t["go_active"] if n)) for t in tissues
              if any(t["go_active"])]
    if not active:
        sentences.append("In all cases, the eFDR for GO biological processes was 0% across all "
                         "species-tissue combinations.")
    else:
        found = _join([f"the {t['species']} {t['tissue'].lower()} ({n} in {k} of "
                       f"{t['experiments']} synthetic null experiments)" for t, n, k in active])
        sentences.append(f"GO biological processes were active in the synthetic null data of "
                         f"{found}; in all other species-tissue combinations the eFDR for GO "
                         f"biological processes was 0%.")
    return [units(" ".join(sentences))]


def efdr_methods(data: dict, efdr: dict | None, appendix: str | None) -> list:
    """The books' D.2.1 Methods, its facts from the null analyses: the control
    group, the number of experiments, the group sizes — and whose data they
    came from, stated only when the null analyses' doses are this study's."""
    if not efdr or not efdr.get("tissues"):
        return []
    tissues = efdr["tissues"]
    unit = data.get("dose_unit") or "mg/kg"
    control = f"0 {unit}"
    n = {t["experiments"] for t in tissues}
    count = str(n.pop()) if len(n) == 1 else "[Placeholder: number of synthetic null experiments]"
    sizes = {(t["groups"].get("0"), tuple(sorted({v for d, v in t["groups"].items()
                                                  if d != "0"}))) for t in tissues}
    if len(sizes) == 1 and len(next(iter(sizes))[1]) == 1:
        c, (treated,) = next(iter(sizes))
        groups = (f"i.e., {c} samples in the {control} group and {treated} for each nonzero "
                  f"exposure concentration")
    else:
        groups = "[Placeholder: the synthetic experiments' group sizes differ]"
    report = _Report(data)
    own = _own_doses(data, report)
    mismatched = [f"{t['species']} {t['tissue'].lower()}" for t in tissues
                  if own.get(t["species"]) is not None and own[t["species"]] != _null_doses(t)]
    species = _join(sorted({t["species"] for t in tissues}))
    if mismatched:
        whose = (f"[Placeholder: whose {control} data — the synthetic null analyses of the "
                 f"{_join(mismatched)} were given other doses than this study's]")
    else:
        studies = "studies" if len({t["species"] for t in tissues}) > 1 else "study"
        whose = f"the {_chemical_in_prose(data.get('chemical_name'))} {species} {studies}"
    appendix_ref = (f" The associated bm2 analysis files that are the basis of the empirical "
                    f"false discovery rate can be found in Appendix {appendix}." if appendix else "")
    return [units(
        f"Synthetic null data were generated using the probe-filtered (i.e., “no 0”) {control} "
        f"data from each tissue in {whose}. The synthetic null data were generated using the "
        f"Synthetic and Null Data Generator (SaNDGen; https://rstudio.niehs.nih.gov/sandgen/), "
        f"which employed the normal distribution method previously described for generating "
        f"synthetic data. In short, for each set of tissue/species, {control} data were used to "
        f"generate a distribution for each probe. This distribution was resampled to generate "
        f"1,000 values for each probe. These values were distributed into synthetic samples, "
        f"which were then organized into {count} different experiments paralleling the "
        f"distribution of samples in the experimental study, {groups}. Each of the {count} "
        f"synthetic null experiments was processed through BMDExpress using the identical "
        f"parameters used to analyze the experimental data. The resultant data were then used "
        f"to determine the empirical false discovery rates (eFDR), which are reported as "
        f"percentages of possible genes and Gene Ontology (GO) biological processes."
        f"{appendix_ref}")]


def _null_doses(t: dict) -> list[float]:
    return sorted(float(d) for d in t["groups"] if float(d) > 0)


def _own_doses(data: dict, report: _Report) -> dict:
    """{species: the study's non-zero doses} from its apical tables."""
    from pipeline.study_design import design_or_standard
    out = {}
    for key, _, sdata in report.studies:
        species = key or design_or_standard(data.get("study_design") or {}).get("species")
        for sec in sdata.get("apical_sections") or []:
            for rows in (sec.get("table_data") or {}).values():
                for row in rows or []:
                    if row.get("doses") and species not in out:
                        out[species] = sorted(float(d) for d in row["doses"] if float(d) > 0)
    return out


# ---------------------------------------------------------------------------
# E Gene Set and Gene Definitions
# ---------------------------------------------------------------------------

def _groups(entry: dict, rows_key: str) -> list[tuple[str, list]]:
    return [(str(b.get("sex") or ""), b.get(rows_key) or []) for b in entry.get("sexes") or []
            if b.get(rows_key)]


def _gene_set_definitions(entry: dict) -> dict | None:
    from genomics.go_definitions import go_definition, release
    groups = _groups(entry, "gene_sets")
    if not groups:
        return None
    d = entry.get("display") if isinstance(entry.get("display"), dict) else {}
    dec, unit = d.get("decimals", 3), d.get("unit") or "mg/kg"
    tag = _bmr_tag(d.get("bmr"))
    phrase = _STAT_PHRASE.get(d.get("stat", "median"), d.get("stat", ""))
    rows: list[list[str]] = []
    for label, sets in groups:
        if len(groups) > 1:
            rows.append([f"**{label}**", "", "", "", ""])
        for r in sets:
            n_bmd, n_genes = r.get("n_genes_with_bmd", 0) or 0, r.get("n_genes", 0) or 0
            cover = f"{n_bmd}/{n_genes} ({n_bmd / n_genes * 100:.1f}%)" if n_genes else f"{n_bmd}/—"
            rows.append([
                f"{r.get('go_id', '')} {r.get('go_term', '')}".strip(), cover,
                str(r.get("genes", "") or "").replace(";", "; "),
                f"{format_display_number(r.get('bmd'), dec)} "
                f"({_bmd_range(r.get('bmdl'), r.get('bmdu'), dec, True)})",
                go_definition(r.get("go_id")) or GO_DEFINITION_PENDING,
            ])
    version = release()
    source = (f"Definitions of GO terms are the Gene Ontology Resource's (go-basic.obo, "
              f"{version})." if version else
              "Definitions of GO terms are the Gene Ontology Resource's (go-basic.obo).")
    footnotes = [{"kind": "definition", "text": source}]
    if d.get("stat") == "fifth_pct":
        footnotes.append({"kind": "definition", "text": "5th percentile = the value below which "
                                                        "5% of transcript benchmark dose values fall."})
    descriptive = genomics_table_caption({**entry, "table_number": None})
    return {"caption": f"Active Genes and Definitions within {descriptive}",
            "headers": ["Category Name", "Input Genes/Platform Genes in Gene Set (% Coverage)",
                        "Active Genes",
                        f"BMD{tag} {phrase} of Gene Set Transcripts (BMDL{tag}–BMDU{tag}) ({unit})",
                        "Definition"],
            "rows": rows, "footnotes": footnotes, "breakable": True}


def appendix_gene_set_definitions(data: dict) -> dict | None:
    by_organ = {}
    for e in data.get("genomics_sections") or []:
        if e.get("type") == "gene_set":
            built = _gene_set_definitions(e)
            if built:
                by_organ[(e.get("organ") or "").strip().lower()] = built
    return {"by_organ": by_organ} if by_organ else None


def appendix_gene_identifiers(data: dict) -> dict | None:
    """Per study: the genes of its top-gene tables, alphabetically."""
    by_study: dict[str, dict] = {}
    for e in data.get("genomics_sections") or []:
        if e.get("type") != "gene":
            continue
        for b in e.get("sexes") or []:
            genes = by_study.setdefault(b.get("study") or "", {})
            for g in b.get("top_genes") or []:
                symbol = str(g.get("gene") or g.get("gene_symbol") or "")
                if symbol and symbol not in genes:
                    genes[symbol] = g
    if not by_study:
        return None
    out = {}
    for key, genes in by_study.items():
        rows = [[s, str(g.get("entrez_id") or "—"),
                 str(g.get("probe_id") or "").replace(",", ", "), GENE_DEFINITION_PENDING]
                for s, g in sorted(genes.items(), key=lambda kv: kv[0].lower())]
        out[key] = {"caption": None,
                    "headers": ["Gene Symbol", "Entrez Gene IDs", "Probe IDs", "Definition"],
                    "rows": rows, "breakable": True,
                    "footnotes": [{"kind": "definition", "text":
                                   "In some cases, a probe may map to more than one gene, "
                                   "resulting in duplicate reporting of that probe mapped to "
                                   "different genes."}]}
    return {"by_species": out}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

EFDR_TABLE = "table-c-efdr"
SUPPLEMENTAL_APPENDIX = "appendix-f"


def attach_genomics_appendix(data: dict, tree, efdr: dict | None) -> None:
    """Write the genomic appendices' content into ``data`` (module docstring)."""
    from document_model.document_tree import find_node
    appendix = getattr(find_node(SUPPLEMENTAL_APPENDIX, tree) if tree else None,
                       "appendix_letter", None)
    table_node = find_node(EFDR_TABLE, tree) if tree else None
    table = getattr(table_node, "table_label", None) or getattr(table_node, "table_number", None)
    matrix = appendix_efdr_matrix(efdr)
    if matrix:
        data["appendix_efdr_matrix"] = matrix
        data["efdr_methods"] = {"paragraphs": efdr_methods(data, efdr, appendix)}
        data["efdr_results"] = {"paragraphs": efdr_results(efdr, table)}
    for key, built in (("appendix_gene_set_definitions", appendix_gene_set_definitions(data)),
                       ("appendix_gene_identifiers", appendix_gene_identifiers(data))):
        if built:
            data[key] = built
