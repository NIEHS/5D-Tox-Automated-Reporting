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

The words — sentences, captions, headers, footnotes — are the document
definition's ``phrasing:`` block (document_model.phrasing; eras/niehs-2026);
how the null data were made is the method profile's (genomics.efdr); the
appendix and table cited are the nodes the definition declares ``cited_as``.
A table repeated per tissue or per study takes its own from a ``by_organ`` /
``by_species`` mapping (render_common.scoped_value).  What the data cannot
supply is a visible placeholder, never a blank: the gene definitions (the
books' human UniProt function text, which this pipeline has no source for),
a GO definition without go-basic.obo, a GO eFDR whose universe is unknown.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from document_model.phrasing import Phrasing
from rendering.genomics_results import _Report, _chemical_in_prose, _join, cited, units
from rendering.render_common import (
    _STAT_PHRASE, _bmd_range, _bmr_tag, genomics_table_caption,
)
from tables.table_builder_common import format_display_number

GO_DEFINITION_PENDING = "[Placeholder: GO definition — go-basic.obo not installed]"
GENE_DEFINITION_PENDING = "[Placeholder: gene definition]"
GO_EFDR_PENDING = "[Table data pending: GO eFDR]"


def _method_fact(value, what: str) -> str:
    return str(value) if value is not None else (
        f"[Placeholder: {what} — not stated by the method profile]")


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


def appendix_efdr_matrix(efdr: dict | None, p: Phrasing) -> dict | None:
    if not efdr or not efdr.get("tissues"):
        return None
    rows = []
    for t in efdr["tissues"]:
        gene, go = _summary(t["gene_pct"]), _summary(t["go_pct"])
        rows.append([
            p.word("species", t["species"], default=t["species"].title()), t["tissue"],
            _pct(gene["mean"]), f"{_pct(gene['min'])}–{_pct(gene['max'])}",
            _pct(go["mean"]) if go else GO_EFDR_PENDING,
            (_pct(go["min"]) if go["min"] == go["max"] else f"{_pct(go['min'])}–{_pct(go['max'])}")
            if go else GO_EFDR_PENDING,
        ])
    return {"caption": p.say("efdr.table.caption"), "headers": p.items("efdr.table.headers"),
            "rows": rows, "footnotes": [{"kind": "definition",
                                         "text": p.say("efdr.table.footnote")}]}


def efdr_results(efdr: dict | None, table, p: Phrasing) -> list:
    """The results' sentences: the gene eFDR's bound and range, the majority
    below the definition's percentage, the GO processes active (if any)."""
    if not efdr or not efdr.get("tissues"):
        return []
    tissues = efdr["tissues"]
    values = [v for t in tissues for v in t["gene_pct"]]
    top = max(values)
    limit = p.value("efdr.bound_pct")
    bound = (p.say("efdr.bound_below", limit=_pct(limit)) if limit is not None and top < limit
             else p.say("efdr.bound_at_most", max=_pct(top)))
    sentences = [p.say("efdr.gene_range", bound=bound, min=_pct(min(values)), max=_pct(top),
                       table=p.say("tables.cite", number=table) if table else "")]
    majority = p.value("efdr.majority_below_pct")
    if majority is not None and sum(v < majority for v in values) * 2 > len(values):
        sentences.append(p.say("efdr.gene_majority", limit=_pct(majority)))
    active = [(t, sum(t["go_active"]), sum(1 for n in t["go_active"] if n)) for t in tissues
              if any(t["go_active"])]
    if not active:
        sentences.append(p.say("efdr.go_none"))
    else:
        found = _join([p.say("efdr.go_active_item", species=t["species"],
                             tissue=t["tissue"].lower(), active=n, experiments_with=k,
                             experiments=t["experiments"]) for t, n, k in active])
        sentences.append(p.say("efdr.go_active", found=found))
    return [units(" ".join(sentences))]


def efdr_methods(data: dict, efdr: dict | None, appendix, method: dict,
                 p: Phrasing) -> list:
    """The books' D.2.1 Methods, its facts from the null analyses — the control
    group, the number of experiments, the group sizes, and whose data they
    came from, stated only when the null analyses' doses are this study's —
    and from the method profile (``method``: genomics.efdr, how the null data
    were made)."""
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
        groups = p.say("efdr.methods_groups", control_n=c, control=control, treated_n=treated)
    else:
        groups = "[Placeholder: the synthetic experiments' group sizes differ]"
    report = _Report(data, p)
    own = _own_doses(data, report)
    mismatched = [f"{t['species']} {t['tissue'].lower()}" for t in tissues
                  if own.get(t["species"]) is not None and own[t["species"]] != _null_doses(t)]
    species = sorted({t["species"] for t in tissues})
    if mismatched:
        whose = (f"[Placeholder: whose {control} data — the synthetic null analyses of the "
                 f"{_join(mismatched)} were given other doses than this study's]")
    else:
        whose = p.say("efdr.methods_whose", chemical=_chemical_in_prose(data.get("chemical_name")),
                      species=_join(species), studies=p.noun("study", len(species)))
    resamples = method.get("resamples_per_probe")
    return [units(p.say(
        "efdr.methods", control=control, whose=whose,
        generator=_method_fact(method.get("generator"), "synthetic null data generator"),
        generator_abbreviation=_method_fact(method.get("generator_abbreviation"),
                                            "generator abbreviation"),
        generator_url=_method_fact(method.get("generator_url"), "generator address"),
        distribution=_method_fact(method.get("distribution"), "distribution"),
        resamples=f"{resamples:,}" if resamples is not None else _method_fact(
            None, "values drawn per probe"),
        count=count, groups=groups,
        appendix=p.say("efdr.methods_appendix", appendix=appendix) if appendix else ""))]


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


def _gene_set_definitions(entry: dict, p: Phrasing) -> dict | None:
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
    footnotes = [{"kind": "definition", "text": p.say(
        "gene_set_definitions.go_source",
        release=p.say("gene_set_definitions.go_release", release=version) if version else "")}]
    if d.get("stat") == "fifth_pct":
        footnotes.append({"kind": "definition", "text": p.say("gene_set_definitions.fifth_pct")})
    descriptive = genomics_table_caption({**entry, "table_number": None})
    return {"caption": p.say("gene_set_definitions.caption", table=descriptive),
            "headers": [h.format_map({"tag": tag, "statistic": phrase, "unit": unit})
                        for h in p.items("gene_set_definitions.headers")],
            "rows": rows, "footnotes": footnotes, "breakable": True}


def appendix_gene_set_definitions(data: dict, p: Phrasing) -> dict | None:
    by_organ = {}
    for e in data.get("genomics_sections") or []:
        if e.get("type") == "gene_set":
            built = _gene_set_definitions(e, p)
            if built:
                by_organ[(e.get("organ") or "").strip().lower()] = built
    return {"by_organ": by_organ} if by_organ else None


def appendix_gene_identifiers(data: dict, p: Phrasing) -> dict | None:
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
        out[key] = {"caption": None, "headers": p.items("gene_identifiers.headers"),
                    "rows": rows, "breakable": True,
                    "footnotes": [{"kind": "definition",
                                   "text": p.say("gene_identifiers.footnote")}]}
    return {"by_species": out}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def attach_genomics_appendix(data: dict, tree, efdr: dict | None, phrasing: Phrasing,
                             method: dict | None = None) -> None:
    """Write the genomic appendices' content into ``data`` (module docstring),
    worded by the definition's ``phrasing``; ``method`` is the method
    profile's genomics.efdr (MethodSettings.efdr_generation).  Nothing when the
    definition declares no phrasing (it binds none of these keys)."""
    if not phrasing:
        return
    matrix = appendix_efdr_matrix(efdr, phrasing)
    if matrix:
        data["appendix_efdr_matrix"] = matrix
        data["efdr_methods"] = {"paragraphs": efdr_methods(
            data, efdr, cited(tree, "supplemental-data", "appendix"), method or {}, phrasing)}
        data["efdr_results"] = {"paragraphs": efdr_results(
            efdr, cited(tree, "efdr-table", "table"), phrasing)}
    for key, built in (("appendix_gene_set_definitions", appendix_gene_set_definitions(data, phrasing)),
                       ("appendix_gene_identifiers", appendix_gene_identifiers(data, phrasing))):
        if built:
            data[key] = built
