"""rendering.genomics_summary — the most potent gene set of each tissue, the
table that closes the 2026 books' gene set analysis (NIEHS-12 Table 11,
NIEHS-13 Table 12: "Most Potent Gene Ontology Biological Process Gene Set per
Tissue, Sorted by 5th Percentile Benchmark Dose, for …").

A reduction of the per-tissue gene set tables (data["genomics_sections"]):
for each group of animals (a study, "Rats" / "Mice"; or a sex), each tissue's
gene set with the lowest BMD, the tissues ordered from the most potent.  The
study's lowest is its transcriptional point of departure.  Bound to a
`data-table` node as data["most_potent_gene_sets_matrix"]; a definition places
it (the 2026 era).
"""

from __future__ import annotations

from rendering.render_common import (
    _STAT_PHRASE, _bmd_range, _bmr_tag, _entry_sex_blocks, _finite_or_none,
    _genomics_display,
)
from tables.table_builder_common import format_display_number

DATA_KEY = "most_potent_gene_sets_matrix"


def _bmd(row) -> float | None:
    v = _finite_or_none(row.get("bmd"))
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def most_potent_gene_sets(data: dict) -> dict | None:
    """{caption, headers, rows, footnotes} — each group's tissues, each with its
    lowest-BMD gene set, from the most potent; None without gene sets.  The
    caption names the animals and their treatment, as the books that print
    this table do ("…, for Female Rats and Mice Exposed to … for Five Days")."""
    from document_model.document_tree import caption_values
    entries = [e for e in data.get("genomics_sections") or [] if e.get("type") == "gene_set"]
    groups: dict[str, list[tuple[float, str, dict, dict]]] = {}
    display: dict = {}
    for entry in entries:
        d = _genomics_display(entry) or {}
        display = display or d
        tissue = (entry.get("organ") or "").strip()
        for label, rows in _entry_sex_blocks(entry, "gene_sets"):
            scored = [(b, r) for r in rows if (b := _bmd(r)) is not None]
            if scored:
                bmd, row = min(scored, key=lambda x: x[0])
                groups.setdefault(label, []).append((bmd, tissue[:1].upper() + tissue[1:], row, d))
    if not groups:
        return None
    tag, unit = _bmr_tag(display.get("bmr")), display.get("unit") or "mg/kg"
    phrase = _STAT_PHRASE.get(display.get("stat", "median"), display.get("stat", ""))
    headers = ["Tissue", "Category Name",
               "Input Genes/Platform Genes in Gene Set (% Coverage)",
               f"BMD{tag} {phrase} of Gene Set Transcripts (BMDL{tag}–BMDU{tag}) ({unit})",
               "Genes with Changed Direction Up/Down"]
    out_rows: list[list[str]] = []
    for label, found in groups.items():
        if len(groups) > 1 or label:
            out_rows.append([f"**{label}**"] + [""] * (len(headers) - 1))
        for _, tissue, r, d in sorted(found, key=lambda x: x[0]):
            dec = d.get("decimals", 1)
            n_bmd, n_genes = r.get("n_genes_with_bmd", 0) or 0, r.get("n_genes", 0) or 0
            cover = f"{n_bmd}/{n_genes} ({n_bmd / n_genes * 100:.1f}%)" if n_genes else f"{n_bmd}/—"
            out_rows.append([
                tissue,
                f"{r.get('go_id', '')} {r.get('go_term', '')}".strip(),
                cover,
                f"{format_display_number(r.get('bmd'), dec)} "
                f"({_bmd_range(r.get('bmdl'), r.get('bmdu'), dec, True)})",
                f"{r.get('n_up', '')}/{r.get('n_down', '')}",
            ])
    footnotes = [{"kind": "definition", "text": (
        f"The first gene set of each group is its transcriptional point of departure: "
        f"the lowest Gene Ontology biological process BMD{tag} {phrase.lower()} value.")}]
    if display.get("stat") == "fifth_pct":
        footnotes.append({"kind": "definition", "text":
                          "5th percentile = the value below which 5% of transcript "
                          "benchmark dose values fall."})
    sorted_by = (f"{phrase} Benchmark Dose" if phrase.endswith("Percentile")
                 else f"Benchmark Dose {phrase}")
    fields = caption_values(data)
    animals = f", for {fields['subject']} {fields['treatment']}" if fields else ""
    return {"caption": ("Most Potent Gene Ontology Biological Process Gene Set per Tissue, "
                        f"Sorted by {sorted_by}{animals}"),
            "headers": headers, "rows": out_rows, "footnotes": footnotes, "breakable": True}
