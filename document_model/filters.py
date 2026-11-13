"""
filters.py — report-level data-selection predicates.

These decide WHICH data appears in a report (which sexes, assays, organs, genes,
gene sets), independent of how any table is built.  They are consumed across the
whole pipeline — pipeline/ (compute-time application), narrative/ (prose that
must match the filtered tables), rendering/ (the export surfaces), and the table
builders — so they belong in the document model beside the filter *config*
(document_template's load_report_* + normalize_filters), NOT under the table
builders.

Historical note: the organ matcher was first written inside body_weight_table.py,
extracted to tables/table_builder_common.py as a "shared table utility", and the
sibling matchers accreted there by proximity.  That location conflated
report-level data selection with table-cell construction; this module is the
honest home.  table_builder_common re-exports these names for backward
compatibility.

The predicate contract is uniform (``filter_allows``) with three deliberately
distinct matching modes — see its docstring.  An EMPTY/None allowlist always
means "no filtering" (every candidate passes), the backward-compatible default.
"""

from __future__ import annotations

import re


# Organ/assay/gene candidates are split into components on whitespace / hyphen /
# dot / slash so one author-friendly token covers the inconsistent spellings
# across the pipeline (e.g. "kidney" must match the apical laterality labels
# "Kidney-Left" / "Kidney-Right" / "R. Kidney" as well as the genomics token
# "kidney").
_COMPONENT_SEP = re.compile(r"[\s.\-/]+")


def _component_match(candidate: str, allowlist: list[str] | None) -> bool:
    """
    Shared COMPONENT-WISE allowlist match — the core of the organ/assay/gene
    matchers.

    An EMPTY/None allowlist means "no filtering" — every candidate passes (the
    pre-feature behaviour).  Otherwise the candidate is case-folded and split on
    whitespace / ``-`` / ``.`` / ``/`` into components, and it passes when a
    listed token equals the whole candidate OR any one component.

    Component matching is what lets one author-friendly token cover the
    inconsistent spellings across the pipeline (e.g. ``"kidney"`` covers the
    clean genomics token AND the split-laterality apical labels
    ``"Kidney-Left"`` / ``"R. Kidney"``; ``"count"`` covers ``"Basophil count"``
    / ``"Leukocyte Count"``).  The allowlist is expected pre-lower-cased by the
    loader, so only the candidate is folded here.
    """
    if not allowlist:
        return True
    folded = (candidate or "").strip().lower()
    if not folded:
        return False
    if folded in allowlist:
        return True
    components = {c for c in _COMPONENT_SEP.split(folded) if c}
    return any(token in components for token in allowlist)


def _exact_match(candidate: str, allowlist: list[str] | None) -> bool:
    """
    EXACT case-insensitive allowlist match (see sex_allowed).  EMPTY/None ⇒ True.
    The allowlist is expected pre-lower-cased; only the candidate is folded.
    """
    if not allowlist:
        return True
    folded = (candidate or "").strip().lower()
    if not folded:
        return False
    return folded in allowlist


def filter_allows(
    candidate: str,
    allowlist: list[str] | None,
    *,
    mode: str = "component",
    alt_id: str | None = None,
) -> bool:
    """
    The single report-level allowlist predicate every filter dimension shares.

    ``mode`` selects the matching contract — the three are deliberately distinct
    and must NOT be collapsed:
      - "component" (organ, assay, gene): component-wise (:func:`_component_match`)
        so one token covers inconsistent spellings across the pipeline.
      - "exact" (sex): exact case-insensitive; a closed binary where a component
        split would wrongly let a partial token cross between male/female.
      - "dual" (gene_set): passes when ``alt_id`` (the GO accession) equals a
        listed token OR ``candidate`` (the human-readable term) component-matches.

    EMPTY/None allowlist ⇒ True (no filtering) in every mode.
    """
    if mode == "exact":
        return _exact_match(candidate, allowlist)
    if mode == "dual":
        if not allowlist:
            return True
        acc = (alt_id or "").strip().lower()
        if acc and acc in allowlist:
            return True
        return _component_match(candidate, allowlist)
    return _component_match(candidate, allowlist)


def organ_allowed(organ: str, allowlist: list[str] | None) -> bool:
    """
    Whether an organ passes a (per-area) report-level allowlist.

    Component-wise match: one token covers the inconsistent organ spellings —
    genomics emits a clean ``"kidney"`` while apical row labels split laterality
    (``"Kidney-Left"``, ``"R. Kidney"``); a non-listed organ shares no component
    and is dropped.  EMPTY/None ⇒ no filtering.  Thin wrapper over
    :func:`filter_allows` (mode="component"); the SINGLE matcher every organ
    choke point shares (genomics post-filter, organ-weight table + narrative).
    """
    return filter_allows(organ, allowlist, mode="component")


def sex_allowed(sex: str, allowlist: list[str] | None) -> bool:
    """
    Whether a sex passes a (per-area) report-level allowlist.

    EXACT case-insensitive match — NOT component-wise (a component split would
    wrongly let a partial token cross the male/female binary).  Accepts either
    casing; the allowlist is pre-lower-cased by the loader.  EMPTY/None ⇒ no
    filtering.  Thin wrapper over :func:`filter_allows` (mode="exact").
    """
    return filter_allows(sex, allowlist, mode="exact")


def assay_allowed(label: str, allowlist: list[str] | None) -> bool:
    """
    Whether a clinical-pathology endpoint label passes a report-level allowlist.

    Component-wise so one token covers a family of endpoints: ``"count"`` keeps
    ``"Basophil count"`` / ``"Leukocyte Count"``.  EMPTY/None ⇒ no filtering.
    Scoped by the caller to Clinical Chemistry + Hematology; Hormones is
    intentionally never assay-filtered.  Wrapper over :func:`filter_allows`.
    """
    return filter_allows(label, allowlist, mode="component")


def gene_allowed(symbol: str, allowlist: list[str] | None) -> bool:
    """
    Whether a gene symbol passes a report-level allowlist.

    Component-wise (gene symbols are normally a single token, so exact in
    practice, but the shared core keeps the matcher family consistent).
    EMPTY/None ⇒ no filtering.  Wrapper over :func:`filter_allows`.
    """
    return filter_allows(symbol, allowlist, mode="component")


def gene_set_allowed(
    go_id: str, go_term: str, allowlist: list[str] | None
) -> bool:
    """
    Whether a gene set / GO term passes a report-level allowlist.

    A listed token keeps the row when it either EQUALS the GO accession
    (``"GO:0051301"``, case-insensitive) OR is a component of the human-readable
    term (``"cell division"`` → ``"division"``).  EMPTY/None ⇒ no filtering.
    Wrapper over :func:`filter_allows` (mode="dual", alt_id=go_id).
    """
    return filter_allows(go_term, allowlist, mode="dual", alt_id=go_id)


def filter_genomics_sections(
    sections: dict | None,
    *,
    organ: list[str] | None = None,
    sex: list[str] | None = None,
    genes: list[str] | None = None,
    gene_sets: list[str] | None = None,
) -> dict:
    """
    Apply every genomics-area allowlist to a ``{key: entry}`` genomics-sections
    dict, returning a new filtered dict (the input is not mutated).

    The SINGLE genomics choke point shared by both export surfaces (the web
    response in process_integrated and the Overleaf bundle in latex_export), so
    the HTML preview and the .tex always agree:

      1. drop whole entries whose ``organ`` / ``sex`` fail their allowlist;
      2. within each surviving entry, prune ``top_genes`` and ``all_genes`` to
         gene-allowed symbols;
      3. prune every ``gene_sets_by_stat[stat]`` and ``gene_sets_chart_by_stat``
         list to gene-set-allowed rows, re-numbering the kept rows' ``rank``
         1..n (rank is positional display only).

    Any allowlist that is empty/None is a no-op for that axis, so an entirely
    unfiltered call returns the sections unchanged (the pre-feature behaviour).
    """
    if not sections:
        return sections or {}

    out: dict = {}
    for key, entry in sections.items():
        if not isinstance(entry, dict):
            out[key] = entry
            continue
        if not organ_allowed(entry.get("organ", ""), organ):
            continue
        if not sex_allowed(entry.get("sex", ""), sex):
            continue

        new_entry = dict(entry)

        if genes:
            for gk in ("top_genes", "all_genes"):
                rows = new_entry.get(gk)
                if isinstance(rows, list):
                    kept = [
                        g for g in rows
                        if gene_allowed(
                            g.get("gene_symbol") or g.get("gene", ""), genes
                        )
                    ]
                    # Re-number the surviving rows so the displayed rank stays a
                    # gap-free 1..n (rank is positional within the top-20 slice,
                    # not a global potency rank — see _extract_genomics).
                    new_entry[gk] = [
                        {**g, "rank": i + 1} if "rank" in g else g
                        for i, g in enumerate(kept)
                    ]

        if gene_sets:
            def _prune(rows: list) -> list:
                kept = [
                    r for r in rows
                    if gene_set_allowed(
                        r.get("go_id", ""), r.get("go_term", ""), gene_sets
                    )
                ]
                # Re-number the surviving rows so rank stays a gap-free 1..n.
                return [
                    {**r, "rank": i + 1} if "rank" in r else r
                    for i, r in enumerate(kept)
                ]

            for gsk in ("gene_sets_by_stat", "gene_sets_chart_by_stat"):
                by_stat = new_entry.get(gsk)
                if isinstance(by_stat, dict):
                    new_entry[gsk] = {
                        stat: _prune(rows) if isinstance(rows, list) else rows
                        for stat, rows in by_stat.items()
                    }

        out[key] = new_entry
    return out
