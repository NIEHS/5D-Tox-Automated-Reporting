"""
report_data.py — Data-assembly helpers for the LaTeX report pipeline.

This module is the data layer behind /api/export-overleaf-bundle and
/api/preview-latex-html.  It takes the web UI's accumulated session
state (the request body) and produces the dict the LaTeX generator
consumes.

Historical context
------------------
This file originally held a `build_report_data` function that compiled
report.typ via the Typst Python wheel to a PDF/UA-1 compliant tagged
PDF.  When the project cut over to LaTeX (2026-05-19 — "no PDFs, no
Typst") the Typst compile step was removed and the rendering tail
became:

    marshal_export_data(body)            ← this file
        → generate_latex(data, …)        ← latex_generator.py
        → build_overleaf_bundle(data, …) ← latex_export.py  (full export)
        → render_html_preview(data, …)   ← latex_html_preview.py  (previews)

The data-assembly logic (`marshal_export_data` and friends) stayed
because it does real work the new path also needs: bm2 reference
resolution, abstract Methods/Results/Summary deterministic paragraphs
from MethodsContext, genomics body narratives, ChemicalIdentity name
forms, deterministic TOC and table entries, and section_filter trimming.

Usage:
    from report_data import marshal_export_data, scaffold_report_data
    data = marshal_export_data(request_body)
    # ... pass to generate_latex / build_overleaf_bundle / render_html_preview ...

    # data dict schema (top-level keys are optional; missing sections
    # render as visible placeholders so the structure stays complete):
    #
    # Front matter:
    #   "foreword":            {"paragraphs": [...]}
    #   "about_report":        {"authors": {"paragraphs": [...]}, "contributors": {"paragraphs": [...]}}
    #   "peer_review":         {"paragraphs": [...]}
    #   "publication_details": {"paragraphs": [...]}
    #   "acknowledgments":     {"paragraphs": [...]}
    #   "abstract":            {"sections": [{"label": str, "text": str}, ...]}
    #
    # Body:
    #   "background":          {"paragraphs": [...]}
    #   "methods":             {"sections": [...]}
    #   "apical_sections":     [...]
    #   "internal_dose":       {"paragraphs": [...], "table": {...}}
    #   "bmd_summary":         {"paragraphs": [...], "endpoints": [...]}
    #   "genomics_sections":   [...]
    #   "summary":             {"paragraphs": [...]}
    #   "references":          [str, ...]
    #
    # Metadata:
    #   "title", "author", "running_header", "chemical_name", "casrn",
    #   "dtxsid", "report_number", "report_date", "issn", "strain",
    #   "report_series"
"""

import json
import logging
from pathlib import Path

from table_builder_common import lettered_footnote, finalize_footnotes


# ---------------------------------------------------------------------------
# Session cache lookup
# ---------------------------------------------------------------------------

def _latest_session_cache(session_dir: Path, glob_pattern: str):
    """
    Return the NEWEST session cache file matching `glob_pattern`, or None.

    A session accumulates one cache file per content hash (e.g. several
    `_cache_genomics_<hash>.json` as the gene set is re-analysed), so "the
    current one" is the most recently written — not the lexically-first.
    Selecting by modification time matches the convention the session-export
    path uses (latex_export._latest); this is the web/preview path's copy so
    both surfaces resolve the same file from a multi-hash session.

    Returns a pathlib.Path or None when nothing matches.
    """
    candidates = sorted(session_dir.glob(glob_pattern), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


# ---------------------------------------------------------------------------
# Apical section normalizer — canonical input shape for the renderers
# ---------------------------------------------------------------------------
# Both the LaTeX export and the in-app HTML preview consume the same
# data dict.  Their per-row table iteration assumes:
#
#   row["endpoint"]  — the row label
#   row["doses"]     — list of dose values defining column order
#   row["values"]    — list of cell strings parallel to doses
#   row["bmd"], row["bmdl"], row.get("is_n_row")
#
# But the web UI (and the session cache it derives from) ships rows
# with row["label"] for the label and row["values"] as a dict keyed by
# dose-as-string.  Without normalization, the renderers iterate the
# values dict, get the dose strings (its keys) back, and emit the same
# garbage in every row's dose columns — which is exactly the bug
# observed in clinical-endpoint tables on 2026-05-19.
#
# normalize_apical_section_for_render reshapes one apical_sections entry
# into the canonical form.  marshal_export_data invokes it on every
# entry so renderers see consistent input; load_session_data calls it
# too for the CLI path.  Idempotent — already-normalized rows pass
# through unchanged.


def normalize_apical_section_for_render(sec: dict) -> dict:
    """
    Return a shallow-copy of `sec` with apical table rows reshaped to
    the canonical render-input form.

    Source shapes (per-row) we accept and unify:

        {label, doses, values: {dose-string: str}, bmd, bmdl,
         is_n_row?, marker_refs?, ...}        ← web UI body & cache
        {endpoint, doses, values: [str], bmd, bmdl, is_n_row?, ...}
                                              ← already-normalized

    Output shape (per-row):

        {endpoint, doses, values: [str], bmd, bmdl, is_n_row,
         + any other keys carried through}

    Rows whose `values` is already a list are passed through untouched
    (modulo the label→endpoint rename if `endpoint` is absent).  Rows
    with neither `tables_json` nor `table_data` come back unchanged so
    callers can keep using the same dict reference.
    """
    # Resolve which key carries the per-sex row lists.  The web UI
    # forwards apical_sections entries with the data under "table_data"
    # (renamed from the cache's "tables_json" at buildExportPayload
    # time), so handle both.
    src = sec.get("table_data") if isinstance(sec.get("table_data"), dict) else None
    if src is None:
        src = sec.get("tables_json") if isinstance(sec.get("tables_json"), dict) else None
    if not src:
        return sec  # nothing to normalize; pass through unchanged

    table_data: dict[str, list[dict]] = {}
    for sex in ("Male", "Female"):
        rows = src.get(sex, []) or []
        if not rows:
            continue
        normalized_rows: list[dict] = []
        for row in rows:
            doses = row.get("doses", []) or []
            raw_values = row.get("values", [])
            # Flatten dict-by-dose into list-parallel-to-doses when needed.
            # When values is already a list, accept it as-is.
            if isinstance(raw_values, list):
                values_list = [str(v) for v in raw_values]
            elif isinstance(raw_values, dict):
                values_list = []
                for d in doses:
                    # Try the dose's str() form first; for whole-number
                    # floats (e.g. 1.0) also try the int form because the
                    # cache normalizes "1.0" → "1" inconsistently across
                    # platforms.
                    candidates = [str(d)]
                    if isinstance(d, float) and d.is_integer():
                        candidates.append(str(int(d)))
                    if isinstance(d, int):
                        candidates.append(str(float(d)))
                    val = "—"
                    for k in candidates:
                        if k in raw_values:
                            val = str(raw_values[k])
                            break
                    values_list.append(val)
            else:
                values_list = []
            # Preserve every original key (marker_refs, emphasize,
            # day_label, etc.) and overlay the canonical fields.
            normalized = dict(row)
            normalized["endpoint"] = (
                row.get("endpoint") or row.get("label") or row.get("day_label") or ""
            )
            normalized["doses"] = doses
            normalized["values"] = values_list
            normalized["bmd"] = row.get("bmd", "—") or "—"
            normalized["bmdl"] = row.get("bmdl", "—") or "—"
            normalized["is_n_row"] = bool(row.get("is_n_row", False))
            normalized_rows.append(normalized)
        table_data[sex] = normalized_rows

    out = dict(sec)
    out["table_data"] = table_data
    # Drop tables_json from the canonical shape — table_data is now the
    # only authoritative form, and leaving both around invites the next
    # renderer drift.
    out.pop("tables_json", None)
    out["narrative"] = sec.get("narrative", []) or []
    return out


def _build_full_title(ta: dict) -> str:
    """
    Build the report's full title / running header from the test-article forms.

    Fixed NIEHS study-template phrasing ("In Vivo Repeat Dose Biological
    Potency Study of <name> in Sprague Dawley Rats"), using the running_header
    name form (the full, never-abbreviated name).  Single-sourced here because
    marshal_export_data and scaffold_report_data both need the identical title
    and previously derived it with copy-pasted f-strings.
    """
    running_header_name = ta["forms"]["running_header"]["text"]
    return (
        f"In Vivo Repeat Dose Biological Potency Study of "
        f"{running_header_name} in Sprague Dawley Rats"
    )


def marshal_export_data(body: dict, section_filter: str | None = None) -> dict:
    """
    Reshape a web-UI export/preview request body into the render-ready data
    dict that both renderers consume (generate_html for the in-app preview,
    generate_latex for the Overleaf .tex bundle).

    Strategy: start from the full scaffold (which defines every section the
    NIEHS template knows about — boilerplate front matter, heading-only stubs
    for study-specific content) and overlay real content on top.  This ensures
    the rendered report always shows the complete NIEHS document structure:
    real content where it exists, empty heading stubs everywhere else.

    Args:
        body: The request JSON body from the web UI export/preview call.
        section_filter: Optional filter to keep only a specific report section
                        for the per-section preview.  Valid values:
                        "apical" (dose-response tables + narrative),
                        "genomics" (gene set/gene tables + descriptions),
                        "charts" (UMAP + cluster scatter figures).
                        When None, the full report is returned.

    Returns:
        The render-ready data dict (the shape generate_html / generate_latex
        walk).
    """
    chemical_name = body.get("chemical_name", "Chemical")

    # --- Start from the scaffold ---
    # scaffold_report_data() provides the complete NIEHS structure with
    # boilerplate front matter and empty stubs for all body sections.
    # We overlay real content on top, so sections the user hasn't
    # generated yet still appear as headings in the PDF.
    data = scaffold_report_data(
        chemical_name=chemical_name,
        casrn=body.get("casrn", "000-00-0"),
        dtxsid=body.get("dtxsid", "DTXSID0000000"),
    )

    # Rebuild the test article identity with all fields from the web UI,
    # which may include abbreviation, PubChem CID, EC number, etc.
    # The scaffold only uses name/casrn/dtxsid; the web UI captures more.
    ta = build_test_article_forms(
        name=chemical_name,
        abbreviation=body.get("abbreviation", ""),
        casrn=body.get("casrn", ""),
        dtxsid=body.get("dtxsid", ""),
        pubchem_cid=body.get("pubchem_cid", ""),
        ec_number=body.get("ec_number", ""),
    )
    data["test_article"] = ta

    # Recompute the running header and title with the full identity
    full_title = _build_full_title(ta)
    data["title"] = full_title
    data["running_header"] = full_title
    data["chemical_name"] = chemical_name
    data["casrn"] = body.get("casrn", "")
    data["dtxsid"] = body.get("dtxsid", "")

    # Per-node page orientation: {node_id: "landscape"} for nodes the user
    # flipped to landscape (tables / charts / figures).  Both renderers read
    # this from the data dict and wrap those nodes accordingly (pdflscape in
    # LaTeX, an @page landscape block in the HTML preview).  Absent/portrait
    # nodes render normally.
    data["orientations"] = body.get("orientations") or {}

    # --- Report metadata overrides ---
    # These populate the inner title page and publication details.
    # Only override if the web UI provides them (scaffold has placeholders).
    for key in ("report_number", "report_date", "issn", "strain", "report_series"):
        val = body.get(key, "")
        if val:
            data[key] = val

    # --- Front matter overrides ---
    # The scaffold already includes boilerplate for these sections.
    # Only override if the web UI provides custom content.

    foreword = body.get("foreword")
    if foreword:
        data["foreword"] = _ensure_paragraphs(foreword)

    about = body.get("about_report")
    if about:
        data["about_report"] = about

    peer_review = body.get("peer_review")
    if peer_review:
        data["peer_review"] = _ensure_paragraphs(peer_review)

    pub_details = body.get("publication_details")
    if pub_details:
        data["publication_details"] = _ensure_paragraphs(pub_details)

    ack = body.get("acknowledgments")
    if ack:
        data["acknowledgments"] = _ensure_paragraphs(ack)

    abstract = body.get("abstract")
    if abstract:
        data["abstract"] = abstract

    # --- Body section overrides ---
    # Each of these overlays real content onto the scaffold's empty stubs.
    # If the web UI hasn't generated content for a section, the scaffold's
    # empty heading stub remains, keeping it visible in the PDF/TOC.

    # Background
    paragraphs = body.get("paragraphs", [])
    if paragraphs:
        data["background"] = {"paragraphs": paragraphs}

    # References — the narrative-node handler in both renderers reads
    # data["references"]["paragraphs"] (a dict; see _render_front_matter),
    # which is the same shape the session-export path produces from
    # background.json.  The request body carries a flat list of reference
    # strings, so wrap it.  Passing the bare list (the previous behaviour)
    # failed the renderers' isinstance(content, dict) check and silently
    # rendered "[Section pending]" in the HTML preview and the marshal-export
    # LaTeX — assembly drift from the session path that this corrects.
    references = body.get("references", [])
    if references:
        data["references"] = _ensure_paragraphs(references)

    # Materials and Methods — overlay structured or flat content onto
    # the scaffold's full H2/H3 heading hierarchy.
    methods_data = body.get("methods_data")
    methods_paragraphs = body.get("methods_paragraphs", [])
    if methods_data and methods_data.get("sections"):
        data["methods"] = {"sections": methods_data["sections"]}
    elif methods_paragraphs:
        data["methods"] = {"sections": [], "paragraphs": methods_paragraphs}
    # else: scaffold's heading-only methods structure remains

    # Assign positional table numbers on the document tree before any overlay
    # reads them.  _overlay_apical_sections resolves each section's table number
    # via _find_table_number(DOCUMENT_TREE, ...), which reads node.table_number;
    # those fields are None until compute_table_numbers() has run.  Computing
    # here (rather than relying on a later call leaking numbers across requests)
    # makes a fresh process produce correct numbers on the first call.
    from document_tree import compute_table_numbers
    compute_table_numbers()

    _overlay_abstract(data, body)
    _overlay_apical_sections(data, body)
    _overlay_unified_and_bmd(data, body)
    _overlay_genomics(data, body)

    # Summary
    summary_paragraphs = body.get("summary_paragraphs", [])
    if summary_paragraphs:
        data["summary"] = {"paragraphs": summary_paragraphs}

    # Inject the document structure tree so the Typst template can walk
    # it for heading hierarchy, table numbering, and section ordering.
    from document_tree import serialize_tree, find_node, is_leaf_table
    data["document_tree"] = serialize_tree()

    # Build manual TOC entries from the document tree BEFORE the section
    # filter strips content.  This lets the tables-list preview render a
    # complete Table of Contents with ready/placeholder styling, even
    # though the body headings are stripped from the compiled document.
    toc_entries, table_entries = _build_toc_entries(data)
    data["toc_entries"] = toc_entries
    data["table_entries"] = table_entries

    # Apply section filter for PDF previews.
    # Uses the document tree to determine which data keys and platforms
    # belong to the requested TOC node — no hardcoded maps.
    if section_filter:
        _apply_section_filter(data, section_filter)
        # Tell the Typst template whether this is a leaf table preview
        # (no headings, just the table) vs a group/section preview.
        node = find_node(section_filter)
        if node and is_leaf_table(node):
            data["leaf_preview"] = True

    # User-owned content overrides (ADR-0005 round-trip).  The LaTeX export
    # path already loads these (latex_export.build_overleaf_bundle); surface
    # them here too so the HTML preview can mark/render regions a human edited
    # in Overleaf instead of silently showing regenerated content (divergence
    # #2).  Keyed by the same anchor ids the generators emit (node.id /
    # "<node>::<item>").  Empty store → {} → byte-identical to before.
    dtxsid = body.get("dtxsid", "")
    if dtxsid:
        from roundtrip.overrides import load_overrides
        data["overrides"] = load_overrides(dtxsid)

    return data



def overlay_abstract(
    data: dict,
    *,
    abstract_background: str = "",
    bmd_endpoints: list | None = None,
    genomics_cache: dict | None = None,
    dose_groups: list | None = None,
    dose_unit: str = "mg/kg",
    bmd_stat=None,
    methods_context: dict | None = None,
) -> None:
    """
    Assemble data["abstract"]["sections"] (Background / Methods / Results /
    Summary) from EXPLICIT inputs — no request body, no disk reads.

    Both the web path (marshal_export_data, via the _overlay_abstract adapter
    below) and the session export (latex_export.load_session_data) call this
    with the inputs they already have, so the abstract is assembled identically
    from either source.  This is the shared assembler that replaced the
    previous body-and-disk-coupled implementation.

    methods_context (the MethodsContext dict) drives the Methods paragraph and
    the study-purpose sentence; it is absent for a session with no methods
    cache, in which case those parts are simply skipped.  endpoints come from
    data["bmd_summary"] if present, else the explicit bmd_endpoints.  Empty
    sections are left untouched, so a partial abstract is fine.
    """
    abstract_updates: dict[str, str] = {}

    # Abstract → Methods (deterministic from the extracted study facts).
    if methods_context:
        try:
            from methods_report import MethodsContext, build_abstract_methods
            abstract_updates["Methods"] = build_abstract_methods(
                MethodsContext.from_dict(methods_context)
            )
        except Exception:
            pass

    # Deterministic study-purpose sentence appended to the LLM background.
    study_purpose_sentence = ""
    if methods_context:
        try:
            from methods_report import MethodsContext as _MC
            _ctx = _MC.from_dict(methods_context)
            ta = _ctx.chemical_name or "the test article"
            descriptor = "transcriptomic" if _ctx.has_gene_expression else "toxicological"
            study_purpose_sentence = (
                f"A short-term, in vivo {descriptor} study was used to "
                f"assess the biological potency of {ta}."
            )
        except Exception:
            pass

    abstract_bg_text = (abstract_background or "").strip()
    if abstract_bg_text or study_purpose_sentence:
        abstract_updates["Background"] = " ".join(
            p for p in (abstract_bg_text, study_purpose_sentence) if p
        )

    # Apical Results/Summary: prefer endpoints already on `data`, else the arg.
    endpoints = (data.get("bmd_summary") or {}).get("endpoints") or bmd_endpoints or []
    dose_groups = dose_groups or []

    if endpoints or genomics_cache or methods_context:
        try:
            from methods_report import build_abstract_results, build_abstract_summary
            results_text = build_abstract_results(
                apical_bmd_summary=endpoints,
                genomics_sections=genomics_cache,
                dose_groups=dose_groups,
                dose_unit=dose_unit,
                bmd_stat=bmd_stat,
                methods_ctx=methods_context,
            )
            if results_text:
                abstract_updates["Results"] = results_text
            summary_text = build_abstract_summary(
                apical_bmd_summary=endpoints,
                genomics_sections=genomics_cache,
                dose_groups=dose_groups,
                dose_unit=dose_unit,
                bmd_stat=bmd_stat,
            )
            if summary_text:
                abstract_updates["Summary"] = summary_text
        except Exception:
            pass

    # Apply updates to data["abstract"]["sections"], preserving order/labels.
    if abstract_updates:
        existing = data.get("abstract", {"sections": []})
        sections = list(existing.get("sections", []))
        for label, text in abstract_updates.items():
            updated = False
            for sec in sections:
                if sec.get("label", "").lower() == label.lower():
                    sec["text"] = text
                    updated = True
                    break
            if not updated:
                sections.append({"label": label, "text": text})
        data["abstract"] = {"sections": sections}


def _overlay_abstract(data: dict, body: dict) -> None:
    """
    Web-path adapter: pull the abstract inputs out of the request body — and
    read the genomics cache from disk via the body's dtxsid — then delegate to
    the shared overlay_abstract().  Preserves the exact inputs the previous
    body-coupled implementation derived, so the web export is unchanged.
    """
    methods_data = body.get("methods_data")
    methods_context = (
        methods_data["context"]
        if (methods_data and methods_data.get("context"))
        else None
    )

    # Dose groups / unit come from the MethodsContext when present, else the
    # body's dose_unit (default mg/kg).
    dose_groups: list = []
    dose_unit = body.get("dose_unit", "mg/kg")
    if methods_context:
        dose_groups = methods_context.get("dose_groups", []) or []
        dose_unit = methods_context.get("dose_unit", dose_unit)

    # The request body carries genomics as an array, but the abstract builders
    # want the cached organ×sex dict — read it from disk by dtxsid.
    genomics_cache = None
    dtxsid = body.get("dtxsid", "")
    if dtxsid:
        try:
            session_dir = Path("sessions") / dtxsid
            cache = _latest_session_cache(session_dir, "_cache_genomics_*.json")
            if cache is not None:
                import orjson
                genomics_cache = orjson.loads(cache.read_bytes())
        except Exception:
            pass

    overlay_abstract(
        data,
        abstract_background=body.get("abstract_background", "") or "",
        bmd_endpoints=body.get("bmd_summary_endpoints"),
        genomics_cache=genomics_cache,
        dose_groups=dose_groups,
        dose_unit=dose_unit,
        methods_context=methods_context,
    )


def _find_table_number(nodes: list, platform: str):
    """
    Walk the document tree depth-first for a table node whose `platform`
    matches and that has a positional table_number assigned; return that
    number, or None.  Hoisted to module scope so the apical-section loop in
    _overlay_apical_sections doesn't redefine it on every iteration.
    """
    for node in nodes:
        if node.platform == platform and node.table_number is not None:
            return node.table_number
        if node.children:
            result = _find_table_number(node.children, platform)
            if result is not None:
                return result
    return None


def _overlay_apical_sections(data: dict, body: dict) -> None:
    """Overlay the apical endpoint sections: footnotes, tree-derived table numbers, document-order sort, and per-row canonicalization."""
    chemical_name = body.get("chemical_name", "Chemical")
    # Apical endpoint sections
    apical_sections = body.get("apical_sections", [])
    if apical_sections:
        data["apical_sections"] = []
        for sec in apical_sections:
            # The builder already emitted typed footnote records (legend /
            # definition / lettered) with letters assigned.  Copy the list
            # so we don't mutate the cached section.
            footnotes = list(sec.get("footnotes", []))
            dose_unit = sec.get("dose_unit", "mg/kg")
            table_data = sec.get("table_data", {})

            # Build per-sex missing-animal footnotes from table row data.
            # Each row may have a missing_animals dict mapping dose → count
            # (animals that died before terminal sacrifice).  These are typed
            # `lettered` records; append them and re-run finalize_footnotes so
            # the whole list is re-lettered consistently (idempotent — it
            # re-derives row markers from marker_refs each call).
            footnotes.extend(
                _build_missing_animal_footnotes(table_data, dose_unit)
            )
            finalize_footnotes(footnotes, table_data)

            # Determine the first column header based on section type.
            # Body weight tables use "Study Day" (the rows are day 0, day 5);
            # all other apical tables use "Endpoint" (each row is a measured
            # parameter like ALT, albumin, etc.).
            section_title = sec.get("section_title", "Apical Endpoints")
            is_body_weight = "body weight" in section_title.lower()
            first_col = sec.get("first_col_header",
                                "Study Day" if is_body_weight else "Endpoint")

            # Accept caption from either key — the body_weight_table builder
            # outputs "caption" directly, while the frontend uses
            # "table_caption_template".
            caption = (sec.get("caption")
                       or sec.get("table_caption_template", ""))

            apical_entry = {
                "title": section_title,
                "caption": caption,
                "compound": sec.get("compound_name", chemical_name),
                "dose_unit": dose_unit,
                "first_col_header": first_col,
                "narrative": _split_narrative(
                    sec.get("narrative_paragraphs") or sec.get("narrative")
                ),
                "table_data": table_data,
                # Typed footnote list — legend / definition / lettered
                # records, with letters assigned and row markers derived.
                # The old separate missing_animal_footnotes and
                # bmd_definition keys are folded into this list.
                "footnotes": footnotes,
                # Platform identifier — used by _apply_section_filter()
                # to filter sections for per-subsection PDF previews.
                "platform": sec.get("platform", section_title),
            }

            # Table number — derived from the document structure tree.
            # The tree assigns numbers by position (Table 2 = Body Weight,
            # Table 3 = Organ Weight, etc.).  Overrides any user-provided
            # table_number from the UI.  (_find_table_number is a module-level
            # helper so it isn't rebuilt on every loop iteration.)
            from document_tree import DOCUMENT_TREE
            platform = apical_entry["platform"]
            tree_table_num = _find_table_number(DOCUMENT_TREE, platform)
            if tree_table_num is not None:
                apical_entry["table_number"] = tree_table_num

            data["apical_sections"].append(apical_entry)

        # Render in document-tree order (Table 2, 3, 4, ...), not the
        # alphabetical platform order the orchestrator's sections cache
        # happens to produce.  Without this, the full report shows
        # Table 3 (Organ Weight) after Tables 4/5/6 because "Organ
        # Weight" sorts after "Clinical Chemistry" / "Hematology" /
        # "Hormones" alphabetically — even though each per-section PDF
        # preview correctly labels Organ Weight as Table 3.  Sections
        # without a table_number (shouldn't happen for apical, but is
        # possible if the document tree doesn't know the platform) sort
        # to the end; the sort is stable to preserve sibling ordering.
        data["apical_sections"].sort(
            key=lambda s: s.get("table_number") or 10_000,
        )

        # Canonicalize per-row shape so both renderers (LaTeX and HTML)
        # see the same input.  The web UI ships row.values as a dict
        # keyed by dose-as-string; the renderers iterate values as a
        # list — without this step they'd produce the dict's keys (the
        # dose strings) in every row's value columns, identical for
        # every endpoint.  See normalize_apical_section_for_render's
        # docstring for the full reasoning.
        data["apical_sections"] = [
            normalize_apical_section_for_render(s)
            for s in data["apical_sections"]
        ]


def _overlay_unified_and_bmd(data: dict, body: dict) -> None:
    """Overlay unified group narratives, internal dose, and the apical BMD summary table plus its intro/LLE paragraph block."""
    methods_data = body.get("methods_data")
    # Unified narratives — group-level prose spanning multiple platform tables.
    # The NIEHS reference has one narrative for "Animal Condition, Body Weights,
    # and Organ Weights" and one for "Clinical Pathology", rendered before their
    # respective table groups.
    # Unified narratives — map from JS keys (apical, clinical_pathology)
    # to Typst template group keys (animal_condition, clinical_pathology).
    # The JS uses "apical" for the Animal Condition group because that was
    # the original key before the TOC restructure.
    _UNIFIED_KEY_MAP = {
        "apical": "animal_condition",
        "clinical_pathology": "clinical_pathology",
    }
    unified_narr = body.get("unified_narratives", {})
    if unified_narr:
        data["unified_narratives"] = {}
        for key, narr_data in unified_narr.items():
            paras = narr_data.get("paragraphs", []) if isinstance(narr_data, dict) else []
            if isinstance(narr_data, list):
                paras = narr_data
            if paras:
                typst_key = _UNIFIED_KEY_MAP.get(key, key)
                data["unified_narratives"][typst_key] = paras

    # Internal Dose Assessment
    internal_dose = body.get("internal_dose")
    if internal_dose:
        data["internal_dose"] = internal_dose

    # BMD Summary
    # The Apical Endpoint BMD Summary table (Table 8 in NIEHS Report 10)
    # carries a fixed footnote block defining BMD/BMDL/LOEL/NOEL/UREP/NVM
    # — all of these can appear in the table cells, so the legend belongs
    # with every export.
    bmd_summary = body.get("bmd_summary")
    bmd_endpoints = body.get("bmd_summary_endpoints", [])
    _bmd_summary_footnotes = [
        "BMD₁Std = benchmark dose corresponding to a benchmark response set "
        "to one standard deviation from the mean; "
        "BMDL₁Std = benchmark dose lower confidence limit corresponding to a "
        "benchmark response set to one standard deviation from the mean; "
        "LOEL = lowest-observed-effect level; "
        "NOEL = no-observed-effect level; "
        "UREP = unreliable estimate of potency — a label based on review of "
        "BMD modeling results indicating the curve-fit BMD is implausibly far "
        "below the statistically observed effect threshold; "
        "NVM = nonviable model, defined as a modeling result that does not "
        "meet prespecified fit criteria and hence is deemed unreliable.",
    ]
    if bmd_summary:
        data["bmd_summary"] = dict(bmd_summary)
        if not data["bmd_summary"].get("footnotes"):
            data["bmd_summary"]["footnotes"] = _bmd_summary_footnotes
    elif bmd_endpoints:
        data["bmd_summary"] = {
            "endpoints": bmd_endpoints,
            "footnotes": _bmd_summary_footnotes,
        }

    # --- Apical Endpoint BMD Summary paragraphs ---
    # Three-layer paragraph block prepended before Table 8:
    #   1. Boilerplate intro (table reference + LLE explanation) — always present.
    #   2. Descriptive findings (programmatic) — from apical_bmd_narrative if
    #      provided by process-integrated; otherwise omitted.
    #   3. Analytical paragraph (LLM) — from apical_bmd_narrative if present.
    #
    # The intro is generated here from MethodsContext because this path runs
    # during both process-integrated (narrative passed in) and standalone PDF
    # export (narrative may not be present, so we still build the intro).
    if data.get("bmd_summary") and not data["bmd_summary"].get("paragraphs"):
        all_paras: list[str] = []

        # --- Layer 1: boilerplate table-reference intro ---
        _doses_for_lle: list[float] = []
        if methods_data and methods_data.get("context"):
            _doses_for_lle = methods_data["context"].get("dose_groups", []) or []
        _nonzero = [d for d in _doses_for_lle if d and d > 0]
        if _nonzero:
            _lle = min(_nonzero) / 3.0
            _lle_str = f"{_lle:.3f}".rstrip("0").rstrip(".") or "0"
            _dose_unit_str = (
                methods_data["context"].get("dose_unit", "mg/kg")
                if methods_data and methods_data.get("context") else "mg/kg"
            )
            _table_num = None
            try:
                from document_tree import find_node, compute_table_numbers
                compute_table_numbers()
                _bmd_node = find_node("bmd-summary")
                if _bmd_node and _bmd_node.table_number is not None:
                    _table_num = _bmd_node.table_number
            except Exception:
                pass
            _table_ref = f"Table {_table_num}" if _table_num is not None else "the table below"
            all_paras.append(
                f"A summary of the calculated BMDs for each toxicological "
                f"endpoint is provided in {_table_ref}. The endpoint-"
                f"specific LOEL and NOEL are included and could be informative "
                f"for endpoints that lack a calculated BMD either because no "
                f"viable model was available or because the estimated BMD was "
                f"below the lower limit of extrapolation (<{_lle_str} "
                f"{_dose_unit_str})."
            )

        # --- Layers 2 + 3: descriptive + analytical from process-integrated ---
        # apical_bmd_narrative is provided when the PDF is exported immediately
        # after process-integrated (the in-app flow).  On standalone PDF export
        # (export.js → /api/export-pdf) the frontend should include it in the
        # request body if it received it from process-integrated.
        _apical_narr = body.get("apical_bmd_narrative") or {}
        all_paras.extend(_apical_narr.get("paragraphs") or [])

        if all_paras:
            data["bmd_summary"]["paragraphs"] = all_paras


def _overlay_genomics(data: dict, body: dict) -> None:
    """Overlay genomics gene-set/gene sections and auto-populate the gene-set / gene body narratives."""
    methods_data = body.get("methods_data")
    _dtxsid = body.get("dtxsid", "")
    _session_dir_path = Path("sessions") / _dtxsid if _dtxsid else None
    # Genomics
    genomics = body.get("genomics_sections", [])
    if genomics:
        data["genomics_sections"] = genomics
        # Attach genomics chart images (UMAP / cluster-scatter PNGs) to the
        # gene_set entries, exactly as the session-export path does.  The
        # charts live in the session's _cache_charts_*.json (base64 PNG, one
        # entry per organ×sex); the browser does NOT round-trip them through
        # the request body, so we read them server-side here — the behaviour
        # export.js documents ("Chart images are read server-side from
        # _cache_charts_{hash}.json").  Charts hang on entry["charts"], which
        # is what both renderers read; that replaces the old, dead
        # data["genomics_charts"] key (no node type ever consumed it).
        if _session_dir_path and _session_dir_path.exists():
            _charts = _latest_session_cache(_session_dir_path, "_cache_charts_*.json")
            if _charts is not None:
                try:
                    import orjson
                    from genomics_charts import attach_genomics_charts
                    charts_cache = orjson.loads(_charts.read_bytes())
                    if isinstance(charts_cache, list):
                        attach_genomics_charts(genomics, charts_cache)
                except Exception:
                    # A missing/corrupt chart cache must not abort the report;
                    # the genomics sections simply render without figures.
                    logging.exception("Failed to attach genomics charts")

    gene_set_narrative = body.get("gene_set_narrative")
    if gene_set_narrative:
        data["gene_set_narrative"] = _ensure_paragraphs(gene_set_narrative)

    gene_narrative = body.get("gene_narrative")
    if gene_narrative:
        data["gene_narrative"] = _ensure_paragraphs(gene_narrative)

    # --- Auto-populate Gene Set / Gene BMD body narratives ---
    # When the user hasn't supplied their own narrative text with a
    # per-organ `by_organ` map, delegate to the shared assembler so the
    # PDF and the in-app HTML render identical prose.  The cache is
    # read here (not in the shared assembler) because this path is
    # session-specific; `/api/process-integrated` passes the in-memory
    # genomics_sections dict directly instead.
    # _dtxsid / _session_dir_path were resolved once at the top of this
    # function (the charts attach also needs them) — reuse them here.
    _genomics_cache = None
    if _session_dir_path and genomics:
        try:
            _gcache = _latest_session_cache(_session_dir_path, "_cache_genomics_*.json")
            if _gcache is not None:
                import orjson
                _genomics_cache = orjson.loads(_gcache.read_bytes())
        except Exception:
            pass

    if _genomics_cache:
        try:
            from genomics_narratives import build_genomics_body_narratives

            _ctx_dict = (methods_data or {}).get("context") or {}
            _chem_name = (
                _ctx_dict.get("chemical_name")
                or body.get("chemical_name")
                or "the test article"
            )
            narratives = build_genomics_body_narratives(
                genomics_sections=_genomics_cache,
                methods_context=_ctx_dict,
                chemical_name=_chem_name,
            )

            # Overlay each narrative only when the request didn't already
            # carry a `by_organ` map.  The frontend flattens user edits
            # to `paragraphs` (no per-organ awareness), so any session
            # saved before the format upgrade gets a fresh auto-populate
            # on export.  Once the frontend learns to preserve `by_organ`
            # through user edits, those edits win.
            _gs_existing = gene_set_narrative if isinstance(gene_set_narrative, dict) else {}
            if not _gs_existing.get("by_organ") and "gene_set_narrative" in narratives:
                data["gene_set_narrative"] = narratives["gene_set_narrative"]

            _gn_existing = gene_narrative if isinstance(gene_narrative, dict) else {}
            if not _gn_existing.get("by_organ") and "gene_narrative" in narratives:
                data["gene_narrative"] = narratives["gene_narrative"]
        except Exception as e:
            logging.exception("Failed to build genomics body narratives: %s", e)


def build_test_article_forms(
    name: str,
    abbreviation: str = "",
    casrn: str = "",
    dtxsid: str = "",
    pubchem_cid: str = "",
    ec_number: str = "",
) -> dict:
    """
    Build the complete test article identity object with pre-computed name
    forms for every structural position in the NIEHS report template.

    The NIEHS Report 10 (NBK589955) follows strict conventions for how the
    test article is named in different parts of the document.  These are
    not stylistic choices — they reflect a deliberate pattern:

      - Formal positions (titles, captions, headers) always use the full
        IUPAC/common name.  Never abbreviated.
      - Each H1 section re-introduces the abbreviation in its first sentence,
        as if the reader entered via the Table of Contents.
      - The Background section's first mention is the only place that lists
        ALL external identifiers (CASRN, DTXSID, PubChem CID, EC number).
      - After the first-mention introduction, the abbreviation is used
        exclusively for the remainder of that section.
      - "test article" and "the chemical" are used as generic procedural
        nouns only in Methods contexts where the protocol action (not the
        chemical identity) is the focus.

    Each form entry has:
      - "text": the rendered string for that context
      - "placement": list of template positions where this form is used

    The placement tags are consumed by the Typst template to select the
    correct form at each structural position.  They also serve as
    documentation for human readers of the data.

    Args:
        name:         Full chemical name (e.g., "Perfluorohexanesulfonamide")
        abbreviation: Short form used in prose (e.g., "PFHxSAm")
        casrn:        CAS Registry Number (e.g., "41997-13-1")
        dtxsid:       DSSTox Substance Identifier (e.g., "DTXSID50469320")
        pubchem_cid:  PubChem Compound ID (e.g., "11603678")
        ec_number:    European Commission number (e.g., "816-398-1")

    Returns:
        Dict with raw identity fields and a "forms" sub-dict containing
        all pre-computed name forms with placement metadata.
    """
    # --- Compute the form strings ---

    # Title pages: "Perfluorohexanesulfonamide (CASRN 41997-13-1)"
    # Used on cover page and inner title page where the full formal
    # identification is required, but not the working abbreviation.
    title_text = name
    if casrn:
        title_text += f" (CASRN {casrn})"

    # Running header: just the full name, no parentheticals.
    # The NIEHS header is: "In Vivo Repeat Dose Biological Potency Study
    # of Perfluorohexanesulfonamide in Sprague Dawley Rats"
    # The name must fit in a ~270pt centered box, so brevity matters.
    running_header_text = name

    # Section intro: "Perfluorohexanesulfonamide (PFHxSAm)"
    # Re-introduces the abbreviation at the start of each H1 section
    # so readers who jump via TOC get the full-name-to-abbreviation mapping.
    section_intro_text = name
    if abbreviation:
        section_intro_text += f" ({abbreviation})"

    # Background intro: the kitchen-sink first mention with ALL identifiers.
    # "Perfluorohexanesulfonamide (PFHxSAm) (CASRN: 41997-13-1, U.S. EPA
    #  Chemical Dashboard: DTXSID50469320, PubChem CID: 11603678, European
    #  Committee Number: 816-398-1)"
    # This is the only place in the entire report where all IDs appear.
    bg_intro_text = name
    if abbreviation:
        bg_intro_text += f" ({abbreviation})"

    id_parts = []
    if casrn:
        id_parts.append(f"CASRN: {casrn}")
    if dtxsid:
        id_parts.append(
            f"U.S. Environmental Protection Agency [EPA] Chemical "
            f"Dashboard: {dtxsid}"
        )
    if pubchem_cid:
        id_parts.append(f"PubChem CID: {pubchem_cid}")
    if ec_number:
        id_parts.append(f"European Committee Number: {ec_number}")
    if id_parts:
        bg_intro_text += " (" + ", ".join(id_parts) + ")"

    # Prose: abbreviation only (or full name if no abbreviation exists).
    # Used everywhere in body text after the section's first-mention intro.
    prose_text = abbreviation if abbreviation else name

    # Table captions: always the full name, never abbreviated.
    # "Summary of Body Weights of Male Rats Administered
    #  Perfluorohexanesulfonamide for Five Days"
    table_caption_text = name

    # Procedural: "test article" — generic noun used in Methods sections
    # when the focus is on the protocol action, not the chemical identity.
    # Only ~2 uses in the entire NIEHS report.
    procedural_text = "test article"

    # Reference list: full name as it appears in citation titles/URLs.
    reference_text = name

    return {
        # --- Raw identity fields ---
        # Preserved so downstream consumers can recompute forms or use
        # individual fields (e.g., DTXSID for database links).
        "name": name,
        "abbreviation": abbreviation,
        "casrn": casrn,
        "dtxsid": dtxsid,
        "pubchem_cid": pubchem_cid,
        "ec_number": ec_number,

        # --- Pre-computed name forms ---
        # Each form has a "text" string and a "placement" list documenting
        # which template positions consume it.  The Typst template uses
        # these form keys (ta.forms.title, ta.forms.prose, etc.) to select
        # the correct name form at each structural position.
        "forms": {
            "title": {
                "text": title_text,
                "placement": ["cover_page", "inner_title_page"],
            },
            "running_header": {
                "text": running_header_text,
                "placement": ["page_header"],
            },
            "section_intro": {
                "text": section_intro_text,
                "placement": [
                    "abstract_first_sentence",
                    "methods_first_mention",
                    "results_first_mention",
                    "summary_first_sentence",
                ],
            },
            "background_intro": {
                "text": bg_intro_text,
                "placement": ["background_first_sentence"],
            },
            "prose": {
                "text": prose_text,
                "placement": ["body_after_intro"],
            },
            "table_caption": {
                "text": table_caption_text,
                "placement": ["all_table_captions"],
            },
            "procedural": {
                "text": procedural_text,
                "placement": ["methods_procedural_context"],
            },
            "reference": {
                "text": reference_text,
                "placement": ["reference_list_entries"],
            },
        },
    }


def _build_methods_sections_from_tree() -> list[dict]:
    """
    Walk the "methods" node in the document tree and build a flat list
    of {"level": N, "heading": "...", "paragraphs": []} dicts matching
    the format expected by the Typst template's methods rendering.

    This replaces a hardcoded 20-entry list — the tree is the single
    source of truth for the M&M heading hierarchy.  If a section is
    added or reordered in document_tree.py, the scaffold PDF picks
    it up automatically.
    """
    from document_tree import find_node, walk_tree

    methods_node = find_node("methods")
    if not methods_node or not methods_node.children:
        return []

    sections: list[dict] = []

    # Pre-order walk of the methods subtree (excluding the heading-only
    # "methods" parent — we start from its children).  Uses the shared
    # walk_tree primitive (ADR-0006) rather than a local re-implementation.
    def _visit(node) -> None:
        sections.append({
            "level": node.level,
            "heading": node.title,
            # Stable binding the renderer matches on (methods_subsection_content);
            # carry it so a future title reword can't unlink a subsection's prose.
            "key": node.methods_key,
            "paragraphs": [],
        })

    walk_tree(methods_node.children, _visit)
    return sections


def scaffold_report_data(
    chemical_name: str = "Test Article",
    casrn: str = "000-00-0",
    dtxsid: str = "DTXSID0000000",
) -> dict:
    """
    Generate a complete report data dict with placeholder content for every
    section defined in the NIEHS Report 10 template (report.typ).

    Purpose: produce a full-structure scaffold PDF that shows the exact page
    flow of a canonical NIEHS report — title page, roman-numeral front matter,
    TOC, tables list, all body sections with hard page breaks, landscape pages
    for wide dose-response tables, genomics tables with GO/gene descriptions,
    and arabic-numbered body pages.  Every conditional branch in the template
    is exercised so the user can see where content will appear.

    The placeholder text is marked with «angle quotes» to make it visually
    obvious which content is placeholder vs. real.  When real content is
    supplied for a section, it simply replaces the placeholder dict entry.

    Args:
        chemical_name: Chemical name to use in titles and captions.
        casrn: CASRN string for the title page.
        dtxsid: DSSTox substance identifier.

    Returns:
        A dict ready to overlay real content onto via marshal_export_data()
        (or to render as-is for a scaffold-only preview).
    """
    # --- Placeholder helper ---
    # Wraps text so it's clearly identifiable as scaffold content.
    def ph(text: str) -> str:
        return f"\u00ab{text}\u00bb"

    # Build the test article identity with all name forms.
    ta = build_test_article_forms(
        name=chemical_name,
        abbreviation="PFHxSAm" if chemical_name == "Perfluorohexanesulfonamide" else "",
        casrn=casrn,
        dtxsid=dtxsid,
        pubchem_cid="11603678" if dtxsid == "DTXSID50469320" else "",
        ec_number="816-398-1" if casrn == "41997-13-1" else "",
    )

    # Title uses the running_header form (full name, never abbreviated)
    full_title = _build_full_title(ta)

    # --- Shorthand for name forms ---
    # These pull the pre-computed text strings from the test article forms
    # so the scaffold placeholder content uses the correct name form in
    # each structural context, just like the real report would.
    ta_intro = ta["forms"]["section_intro"]["text"]       # "Full Name (Abbrev)"
    ta_bg = ta["forms"]["background_intro"]["text"]       # "Full Name (Abbrev) (CASRN..., DTXSID...)"
    ta_prose = ta["forms"]["prose"]["text"]               # "Abbrev" or full name
    ta_caption = ta["forms"]["table_caption"]["text"]     # "Full Name"

    # --- Results sub-structures: heading-only scaffolds ---
    # These show the H2 headings that will appear in the Results section
    # but with no narrative text and no table data.  When real .bm2 data
    # is uploaded, the apical_sections entries get populated with actual
    # dose-response tables and LLM-generated narrative.

    # Apical sections — H2 headings matching NIEHS Report 10 structure.
    # Empty table_data means no tables render, but the heading appears
    # in the TOC and the section is visible in the document flow.
    apical_sections = [
        {
            "title": "Animal Condition, Body Weights, and Organ Weights",
            "caption": "",
            "compound": chemical_name,
            "dose_unit": "mg/kg",
            "narrative": [],
            "table_data": {},
            "footnotes": [],
        },
        {
            "title": "Clinical Pathology",
            "caption": "",
            "compound": chemical_name,
            "dose_unit": "mg/kg",
            "narrative": [],
            "table_data": {},
            "footnotes": [],
        },
    ]

    # Internal Dose Assessment — heading only, no table.
    internal_dose = {
        "paragraphs": [],
    }

    # BMD Summary — heading only, empty endpoints list.
    # The template checks endpoints.len() > 0, so the heading renders
    # but no table appears.
    bmd_summary = {
        "paragraphs": [],
        "endpoints": [
            # One placeholder row so the heading and table structure appear
            {"sex": "Male", "endpoint": "—", "bmd": None, "bmdl": None, "loel": None, "noel": None, "direction": "—"},
        ],
    }

    # Genomics — section headings for gene set and gene analyses,
    # with organ sub-headings (liver, kidney) but no table data.
    genomics_sections = [
        {"type": "gene_set", "organ": "liver", "sex": "male",
         "caption": "", "gene_sets": [], "go_descriptions": []},
        {"type": "gene_set", "organ": "kidney", "sex": "male",
         "caption": "", "gene_sets": [], "go_descriptions": []},
        {"type": "gene", "organ": "liver", "sex": "male",
         "caption": "", "top_genes": [], "gene_descriptions": []},
        {"type": "gene", "organ": "kidney", "sex": "male",
         "caption": "", "top_genes": [], "gene_descriptions": []},
    ]

    # --- Materials and Methods (structured H2/H3 hierarchy) ---
    # DERIVED FROM THE DOCUMENT TREE — not hardcoded.
    # Walks the "methods" node's children recursively to build the same
    # {"level": N, "heading": "..."} dicts from the tree.  This means
    # adding/removing/reordering M&M subsections in document_tree.py
    # automatically updates the scaffold PDF without touching this file.
    methods_sections = _build_methods_sections_from_tree()

    # ================================================================
    # ASSEMBLE THE COMPLETE SCAFFOLD
    #
    # Content is split into two categories:
    #
    #   BOILERPLATE — text that is identical (or near-identical) across
    #   all NIEHS reports in this series.  Taken verbatim from the
    #   NIEHS Report 10 PDF (NBK589955).  These sections are pre-filled
    #   because they don't depend on study-specific data.
    #
    #   EMPTY — sections whose content is entirely study-specific.
    #   These show the heading (so the full TOC structure is visible)
    #   but contain no body text.  When real content is generated,
    #   it replaces the empty entry.
    # ================================================================

    data = {
        # --- Metadata ---
        "title": full_title,
        "author": "5dToxReport",
        "running_header": full_title,
        "chemical_name": chemical_name,
        "casrn": casrn,
        "dtxsid": dtxsid,
        "report_number": ph("NIEHS Report XX"),
        "report_date": ph("Month Year"),
        "issn": "2768-5632",
        "strain": "(Hsd:Sprague Dawley\u00ae SD\u00ae)",
        "report_series": "NIEHS Report Series",
        # Test article identity with all name forms
        "test_article": ta,

        # ==============================================================
        # FRONT MATTER — BOILERPLATE
        # ==============================================================

        # --- Foreword ---
        # Verbatim from NIEHS Report 10 page ii.  This text is identical
        # across all NIEHS reports — it describes the NIEHS mission and
        # the report series.  No study-specific content.
        "foreword": {"paragraphs": [
            "The National Institute of Environmental Health Sciences (NIEHS) is one of 27 institutes and centers of the National Institutes of Health, which is part of the U.S. Department of Health and Human Services. The NIEHS mission is to discover how the environment affects people in order to promote healthier lives. NIEHS works to accomplish its mission by conducting and funding research on human health effects of environmental exposures; developing the next generation of environmental health scientists; and providing critical research, knowledge, and information to citizens and policymakers who are working to prevent hazardous exposures and reduce the risk of disease and disorders connected to the environment. NIEHS is a foundational leader in environmental health sciences and committed to ensuring that its research is directed toward a healthier environment and healthier lives for all people.",
            "The NIEHS Report series began in 2022. The environmental health sciences research described in this series is conducted primarily by the Division of Translational Toxicology (DTT) at NIEHS. NIEHS/DTT scientists conduct innovative toxicology research that aligns with real-world public health needs and translates scientific evidence into knowledge that can inform individual and public health decision-making.",
            "NIEHS reports are available free of charge on the NIEHS/DTT website and cataloged in PubMed, a free resource developed and maintained by the National Library of Medicine (part of the National Institutes of Health).",
        ]},

        # --- About This Report ---
        # Structure is boilerplate (Authors heading + Contributors heading).
        # Actual names are study-specific → empty.
        "about_report": {
            "authors": {"paragraphs": []},
            "contributors": {"paragraphs": []},
        },

        # --- Peer Review ---
        # Boilerplate template text from NIEHS Report 10 page viii.
        # The report title is inserted dynamically; the rest is verbatim.
        "peer_review": {"paragraphs": [
            f"This report was modeled after the NTP Research Report on In Vivo Repeat Dose Biological Potency Study of Triphenyl Phosphate (CAS No. 115-86-6) in Male Sprague Dawley (Hsd:Sprague Dawley\u00ae SD\u00ae) Rats (Gavage Studies) (https://doi.org/10.22427/NTP-RR-8), which was reviewed internally at the National Institute of Environmental Health Sciences and peer reviewed by external experts. Importantly, these reports employ mathematical model-based approaches to identify and report potency of dose-responsive effects and do not attempt more subjective interpretation (i.e., make calls or reach conclusions on hazard). The peer reviewers of the initial 5-day research report determined that the study design, analysis methods, and results presentation were appropriate. The study design, analysis methods, and results presentation employed for this study are identical to those previously reviewed, approved, and reported; therefore, following internal review, the NIEHS Report on the {full_title} was not subjected to further external peer review.",
        ]},

        # --- Publication Details ---
        # Structure is boilerplate.  DOI and report number are
        # study-specific → shown as placeholders.
        "publication_details": {"paragraphs": [
            "Publisher: National Institute of Environmental Health Sciences",
            "Publishing Location: Research Triangle Park, NC",
            "ISSN: 2768-5632",
            ph("DOI: https://doi.org/10.22427/NIEHS-XX"),
            "Report Series: NIEHS Report Series",
            ph("Report Series Number: XX"),
        ]},

        # --- Acknowledgments ---
        # Boilerplate template.  Contract numbers are study-specific
        # but the structure and lead-in sentence are standard.
        "acknowledgments": {"paragraphs": [
            "This work was supported by the Intramural Research Program at the National Institute of Environmental Health Sciences (NIEHS), National Institutes of Health and performed for NIEHS under contract.",
        ]},

        # --- Abstract ---
        # Structure is boilerplate (Background/Methods/Results/Summary
        # labeled subsections).  Content is study-specific → empty.
        "abstract": {"sections": [
            {"label": "Background", "text": ""},
            {"label": "Methods", "text": ""},
            {"label": "Results", "text": ""},
            {"label": "Summary", "text": ""},
        ]},

        # ==============================================================
        # BODY — EMPTY (study-specific, headings only)
        # ==============================================================

        # --- Background ---
        # Heading shown; content is study-specific.
        "background": {"paragraphs": []},

        # --- Materials and Methods ---
        # Full H2/H3 heading hierarchy shown (matching NIEHS Report 10
        # TOC exactly), but paragraph content is empty.  This ensures
        # the TOC shows the complete expected structure.
        "methods": {"sections": methods_sections},

        # --- Results: Apical Endpoints ---
        # Table structure shown with headings but no data rows.
        # Landscape page breaks still triggered by the 10-dose design.
        "apical_sections": apical_sections,

        # --- Results: Internal Dose Assessment ---
        # Heading + empty table structure.
        "internal_dose": internal_dose,

        # --- Results: BMD Summary ---
        # Heading + empty table structure.
        "bmd_summary": bmd_summary,

        # --- Results: Genomics ---
        # Section headings (Gene Set BMD Analysis, Gene BMD Analysis)
        # with organ sub-headings but no table data.
        "genomics_sections": genomics_sections,
        "gene_set_narrative": {"paragraphs": []},
        "gene_narrative": {"paragraphs": []},

        # --- Summary ---
        # Heading shown; content is study-specific.
        "summary": {"paragraphs": []},

        # --- References ---
        # Empty list — references are study-specific.
        "references": [],
    }

    return data


def _split_narrative(narrative) -> list[str]:
    """
    Normalize narrative input to a list of paragraph strings.

    The narrative may arrive as:
      - A list of strings (one per paragraph) — return as-is
      - A single string with double-newline separators — split
      - None — return empty list
    """
    if narrative is None:
        return []
    if isinstance(narrative, list):
        return narrative
    if isinstance(narrative, str):
        return [p.strip() for p in narrative.split("\n\n") if p.strip()]
    return []


def _ensure_paragraphs(obj) -> dict:
    """
    Normalize a section object to always have a 'paragraphs' key.

    Accepts:
      - A dict with 'paragraphs' key — return as-is
      - A list of strings — wrap in {'paragraphs': [...]}
      - A single string — wrap in {'paragraphs': [str]}

    This lets callers pass either the full dict or just the paragraphs.
    """
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, list):
        return {"paragraphs": obj}
    if isinstance(obj, str):
        return {"paragraphs": [obj]}
    return {"paragraphs": []}


# ---------------------------------------------------------------------------
# TOC entries builder — walks the document tree to build a manual Table of
# Contents for the tables-list preview mode.  The preview strips all body
# content so Typst's outline() has no headings to collect.  Instead, we
# pre-compute the TOC entries here and pass them as data, so the template
# can render a manual TOC with placeholder styling for incomplete sections.
# ---------------------------------------------------------------------------

def _build_toc_entries(data: dict) -> tuple[list[dict], list[dict]]:
    """
    Walk the document tree and build two arrays for the Typst template:

      toc_entries:   [{title, level, ready, id}, ...]
                     Every heading (level 1-3) in the document tree.
                     "ready" is True when the section has real content
                     (not just the scaffold placeholder).

      table_entries: [{title, table_number, ready}, ...]
                     Every numbered table in the Results section.
                     "ready" is True when the table's platform has data
                     in apical_sections or elsewhere.

    "Ready" determination:
      - Front matter sections (foreword, about, peer review, etc.) are
        always ready because the scaffold provides boilerplate.
      - Body sections check whether the corresponding data_key in the
        report data dict has been overlaid with real content.  The
        scaffold sets empty stubs ({paragraphs: []} or empty arrays),
        so we check for non-empty content.
      - Apical table nodes check whether any apical_section entry
        matches the node's platform AND has non-empty table_data.
      - Genomics nodes check genomics_sections for matching entries.

    Args:
        data: The full report data dict (after overlay, before filter).

    Returns:
        (toc_entries, table_entries) — both are lists of dicts.
    """
    from document_tree import DOCUMENT_TREE, compute_table_numbers

    # Ensure table numbers are computed before we walk
    compute_table_numbers()

    toc_entries = []
    table_entries = []

    # --- Readiness checks for each data_key ---
    # Front matter keys are always "ready" (scaffold provides boilerplate).
    _FRONT_KEYS = {
        "foreword", "about_report", "peer_review",
        "publication_details", "acknowledgments", "abstract",
        "table_of_contents",
    }

    def _is_ready(node) -> bool:
        """
        Check whether a node's content is real (not scaffold placeholder).

        Front matter is always ready (boilerplate).  Body sections check
        for non-empty content under their data_key.  Table nodes check
        for platform-matching apical_sections with table_data.  Genomics
        nodes check genomics_sections for matching organ/type entries.
        """
        dk = getattr(node, "data_key", None)

        # Front matter — always ready (boilerplate content)
        if dk in _FRONT_KEYS:
            return True

        # Table nodes — check apical_sections for matching platform data
        if node.node_type == "table" or node.node_type == "incidence-table":
            platform = getattr(node, "platform", None)
            if platform:
                for sec in data.get("apical_sections", []):
                    if sec.get("platform") == platform and sec.get("table_data"):
                        return True
            return False

        # BMD summary — check for non-placeholder endpoints
        if node.node_type == "bmd-summary":
            bmd = data.get("bmd_summary", {})
            endpoints = bmd.get("endpoints", [])
            # Scaffold has one placeholder row with endpoint "—"
            if len(endpoints) > 1:
                return True
            if len(endpoints) == 1 and endpoints[0].get("endpoint") != "—":
                return True
            return False

        # Genomics sections — check for gene_set/gene entries with data
        if node.node_type == "genomics-section":
            gs = data.get("genomics_sections", [])
            nk = getattr(node, "narrative_key", None)
            if nk == "gene_set_narrative":
                return any(s.get("type") == "gene_set" and s.get("gene_sets") for s in gs)
            elif nk == "gene_narrative":
                return any(s.get("type") == "gene" and s.get("top_genes") for s in gs)
            return bool(gs)

        # Narrative / heading-only nodes — check data_key for content
        if dk:
            val = data.get(dk)
            if val is None:
                return False
            if isinstance(val, dict):
                # Check for non-empty paragraphs or sections
                paras = val.get("paragraphs", [])
                secs = val.get("sections", [])
                return bool(paras) or bool(secs)
            if isinstance(val, list):
                return bool(val)
            return bool(val)

        # Heading-only nodes with children — ready if any child is ready
        if node.children:
            return any(_is_ready(c) for c in node.children)

        return False

    # Narrative+tables nodes (animal condition, clinical path) — ready if
    # they have a unified narrative OR any child table has data
    def _is_narrative_tables_ready(node) -> bool:
        """
        Check readiness for narrative+tables nodes (e.g., Animal Condition,
        Clinical Pathology).  Ready if unified narrative exists OR any
        child table node has platform data in apical_sections.
        """
        nk = getattr(node, "narrative_key", None)
        if nk:
            un = data.get("unified_narratives", {})
            if un.get(nk):
                return True
        # Check child tables
        return any(_is_ready(c) for c in node.children)

    # This is a PRUNED walk, deliberately NOT the shared document_tree.walk_tree
    # (ADR-0006): it does not descend into cover / title-page / tables-list /
    # appendix nodes — those are TOC leaves (or excluded), and their subtrees
    # must not contribute entries.  walk_tree always recurses, so it can't
    # express that pruning; the manual recursion below keeps the intent explicit
    # rather than relying on those node types happening to be childless today.
    def _walk_toc(nodes: list):
        """
        Recursively walk tree nodes, emitting toc_entries for headings
        (level >= 1) and table_entries for table nodes with numbers.  Does not
        descend into structural / appendix nodes (see the note above).
        """
        for node in nodes:
            # Skip structural pages (cover, title) — they're not TOC entries
            if node.node_type in ("cover", "title-page"):
                continue

            # Tables list node — skip (it IS the TOC, not an entry in it)
            if node.node_type == "tables-list":
                continue

            # Appendix nodes — always show as placeholders in the TOC
            if node.node_type == "appendix":
                toc_entries.append({
                    "title": node.title,
                    "level": node.level,
                    "ready": False,
                    "id": node.id,
                })
                continue

            # Heading entries (level >= 1) go into the TOC
            if node.level >= 1:
                if node.node_type == "narrative+tables":
                    ready = _is_narrative_tables_ready(node)
                else:
                    ready = _is_ready(node)
                toc_entries.append({
                    "title": node.title,
                    "level": node.level,
                    "ready": ready,
                    "id": node.id,
                })

            # Table entries (numbered tables) go into the Tables list
            if node.table_number is not None:
                ready = _is_ready(node)
                table_entries.append({
                    "title": node.title,
                    "table_number": node.table_number,
                    "ready": ready,
                })

            # Recurse into children
            if node.children:
                _walk_toc(node.children)

    _walk_toc(DOCUMENT_TREE)

    return toc_entries, table_entries


def _apply_section_filter(data: dict, section_filter: str) -> None:
    """
    Strip all report sections except the requested one for PDF preview.

    Uses the document structure tree (document_tree.py) to determine which
    data keys and platforms belong to the requested TOC node.  This replaces
    all hardcoded filter maps with a single tree-driven lookup.

    Modifies `data` in place: sets section_only=True (tells the Typst
    template to skip structural pages), removes front matter for body
    previews, removes body sections not referenced by the requested node,
    and sub-filters apical_sections by platform.

    Args:
        data: The full report data dict (modified in place).
        section_filter: Any TOC node ID (e.g., "animal-condition",
                        "table-body-weight", "background", "foreword").
    """
    from document_tree import (
        find_node, collect_data_keys, collect_platforms, collect_methods_keys,
    )

    # All data keys that can be independently removed
    ALL_BODY = {
        "background", "methods", "apical_sections", "unified_narratives",
        "internal_dose", "bmd_summary", "genomics_sections",
        "gene_set_narrative", "gene_narrative",
        "summary", "references",
    }
    ALL_FRONT = {
        "foreword", "about_report", "peer_review", "publication_details",
        "acknowledgments", "abstract", "table_of_contents",
    }

    # --- Resolve dynamic per-organ subnode IDs ---
    # The frontend sidebar generates per-organ subnodes for the genomics
    # parents — IDs like "gene-set-liver" or "gene-bmd-kidney" — that
    # don't exist in the static DOCUMENT_TREE.  Map them to the parent
    # node ("gene-sets" / "gene-bmd") and remember the organ qualifier
    # so we can sub-filter genomics_sections to just that organ below.
    organ_qualifier: str | None = None
    if section_filter and section_filter not in (None, ""):
        for prefix, parent_id in (
            ("gene-set-", "gene-sets"),
            ("gene-bmd-", "gene-bmd"),
        ):
            if section_filter.startswith(prefix):
                candidate_organ = section_filter[len(prefix):]
                # Only treat as a per-organ subnode when the suffix
                # isn't itself an existing static node ID.
                if find_node(section_filter) is None and candidate_organ:
                    organ_qualifier = candidate_organ.lower()
                    section_filter = parent_id
                break

    # --- Look up the node in the document tree ---
    node = find_node(section_filter)

    if node is None:
        # Unknown node ID — strip everything as a safe fallback
        data["section_only"] = True
        return

    # --- Signal the Typst template which preview mode to use ---
    # Front-matter nodes strip all body content and set preview_mode so
    # the Typst template renders only the appropriate structural pages.
    #
    # Three sub-modes:
    #   "cover"        — render only the cover page (full-bleed green)
    #   "title-page"   — render only the inner title page (centered text)
    #   "front-matter" — render inner title + one front matter section
    #
    # For individual front-matter sections (foreword, peer-review, etc.),
    # we strip all OTHER front matter keys so only the selected section
    # renders — otherwise every front matter page shows up.
    if node.node_type in ("front-matter", "tables-list", "cover", "title-page"):
        for key in ALL_BODY:
            data.pop(key, None)

        if node.node_type == "cover":
            data["preview_mode"] = "cover"
        elif node.node_type == "title-page":
            data["preview_mode"] = "title-page"
        elif node.node_type == "tables-list":
            # TOC/tables-list preview: strip all front matter content
            # sections but keep body data so the TOC outline has entries.
            data["preview_mode"] = "tables-list"
            for key in ALL_FRONT:
                data.pop(key, None)
            # Restore body keys so outline() can enumerate headings
            # (they were already stripped above — re-marshal from scaffold)
        else:
            data["preview_mode"] = "front-matter"
            # Keep only the selected front-matter section's data key.
            keep_key = getattr(node, "data_key", None)
            if keep_key:
                for key in ALL_FRONT:
                    if key != keep_key:
                        data.pop(key, None)
        return

    # Body content: skip front matter and structural pages
    data["section_only"] = True

    # Body content: remove front matter, keep only data keys referenced
    # by this node's subtree
    for key in ALL_FRONT:
        data.pop(key, None)

    keep = collect_data_keys(node)
    # For nodes under Results that reference apical_sections, also keep
    # the sections array itself
    platforms = collect_platforms(node)
    if platforms:
        keep.add("apical_sections")

    # Charts are rendered inline within the gene-set per-organ blocks, and
    # their PNG payload now travels INSIDE each genomics_sections entry (as
    # entry["charts"], attached by genomics_charts.attach_genomics_charts).
    # So keeping "genomics_sections" automatically keeps the charts — there is
    # no separate top-level chart key to preserve any more.
    for key in ALL_BODY - keep:
        data.pop(key, None)

    # Sub-filter apical_sections by platform
    if platforms and "apical_sections" in data:
        data["apical_sections"] = [
            s for s in data["apical_sections"]
            if s.get("platform") in platforms
        ]

    # Sub-filter methods.sections by selected M&M subsection.
    # Each M&M subnode (mm-study-design, mm-clin-exam, etc.) has a methods_key
    # that maps to a key in data.methods.sections.  For heading-only parents
    # (mm-clin-exam, mm-transcriptomics, mm-data-analysis), we collect the
    # parent's key plus all children's keys so the preview shows the whole
    # subtree under that parent heading.  The root "methods" node has no
    # methods_key of its own but its subtree covers every section.
    methods_keys = collect_methods_keys(node)
    if methods_keys and "methods" in data:
        methods_data = data["methods"]
        sections = methods_data.get("sections", [])
        filtered = [s for s in sections if s.get("key") in methods_keys]
        if filtered:
            data["methods"] = {**methods_data, "sections": filtered}

    # Sub-filter genomics_sections by type for the gene-sets / gene-bmd
    # node previews.  Both nodes share data_key="genomics_sections" but each
    # represents a different slice — gene-sets renders type="gene_set"
    # entries, gene-bmd renders type="gene" entries.  Without this filter,
    # the gene-sets preview would also show gene tables and vice versa.
    # The narrative_key on the node uniquely identifies which slice to keep.
    nk = getattr(node, "narrative_key", None)
    if nk in ("gene_set_narrative", "gene_narrative") and "genomics_sections" in data:
        wanted_type = "gene_set" if nk == "gene_set_narrative" else "gene"
        data["genomics_sections"] = [
            s for s in data["genomics_sections"]
            if s.get("type") == wanted_type
        ]

    # Per-organ subnode filter — when the requested TOC id was e.g.
    # "gene-set-liver", drop sections for other organs so the preview
    # renders only the Liver table (and its narrative, via the Typst
    # `by_organ` lookup).  The narrative dict stays intact because its
    # per-organ placement is keyed by organ name in the template.
    if organ_qualifier and "genomics_sections" in data:
        data["genomics_sections"] = [
            s for s in data["genomics_sections"]
            if str(s.get("organ", "")).lower() == organ_qualifier
        ]


def _build_missing_animal_footnotes(
    table_data: dict, dose_unit: str
) -> list[dict]:
    """
    Scan table_data rows for missing-animal annotations and produce typed
    footnote records for the apical footnote list.

    Each row in table_data[sex] may carry a `missing_animals` dict mapping
    dose (as string) to integer count — the number of animals in the xlsx
    study file roster that are absent from that domain's bm2 data (animals
    that died before terminal sacrifice and couldn't have that endpoint
    measured).

    We aggregate per sex, taking the max count at each dose across all
    endpoints (since different endpoints may report slightly different N),
    and produce one lettered footnote per sex, e.g.:

        "5 animals at 333 mg/kg; 5 animals at 1,000 mg/kg did not survive
         to terminal sacrifice."

    These are typed `lettered` records with `target="none"` — the dose
    groups are named inline in the text, so no in-table cell marker is
    needed.  The caller merges them into the section's footnote list and
    re-runs finalize_footnotes so they pick up the next letters after the
    builder's own footnotes.

    Args:
        table_data: Dict keyed by sex ("Male", "Female"), each value a
                    list of row dicts with optional "missing_animals".
        dose_unit:  Dose unit string (e.g., "mg/kg") for display.

    Returns:
        List of typed `lettered` footnote records (one per sex with
        missing animals).  Empty list if no missing animals in any sex.
    """
    records: list[dict] = []

    for sex in ("Male", "Female"):
        rows = table_data.get(sex, [])
        if not rows:
            continue

        # Aggregate: for each dose, take the max missing count across rows
        missing_by_dose: dict[float, int] = {}
        for row in rows:
            ma = row.get("missing_animals")
            if not ma:
                continue
            for dose_key, count in ma.items():
                dose = float(dose_key)
                if dose not in missing_by_dose or count > missing_by_dose[dose]:
                    missing_by_dose[dose] = count

        if not missing_by_dose:
            continue

        # Sort by dose for consistent display order
        sorted_doses = sorted(missing_by_dose.keys())
        parts = []
        for d in sorted_doses:
            n = missing_by_dose[d]
            # Format dose: drop decimal for whole numbers (333 not 333.0)
            d_label = f"{int(d):,}" if d == int(d) else str(d)
            parts.append(
                f"{n} animal{'s' if n > 1 else ''} at {d_label} {dose_unit}"
            )

        text = f"{'; '.join(parts)} did not survive to terminal sacrifice."
        records.append(lettered_footnote(
            text, f"missing_animal_{sex}", target="none",
        ))

    return records
