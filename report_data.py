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


def _resolve_layout_config(body: dict) -> dict:
    """
    Merge the layout-styles config from its three SOURCES, in increasing
    precedence, into the single ``styles`` mapping the renderers resolve per-node:

        1. global template ``styles:`` block  — the git-tracked default;
        2. per-session ``styles.yaml`` override (keyed by the body's dtxsid);
        3. request-body ``layout_style``       — live UI edits (same channel
           ``orientations`` rides), so an unsaved tweak previews immediately.

    Each source is itself a ``{defaults, types, instances}`` mapping; the merge is
    the generic chart_style.deep_merge, so a later source overrides only the keys
    it names (e.g. a session that re-styles just ``types.narrative`` inherits the
    template's ``defaults``).  The WITHIN-config three-layer precedence
    (defaults ← types ← instances) is resolved later, per-node, at emit time by
    layout_style.resolve_layout_style.  All sources empty ⇒ {} ⇒ no styling.
    """
    from chart_style import deep_merge
    from document_template import load_layout_style
    from document_tree import ACTIVE_TEMPLATE

    template_cfg = load_layout_style(ACTIVE_TEMPLATE)

    session_cfg = None
    dtxsid = body.get("dtxsid", "")
    if dtxsid:
        from document_config import load_session_layout_style
        session_cfg = load_session_layout_style(dtxsid)

    request_cfg = body.get("layout_style")
    if not isinstance(request_cfg, dict):
        request_cfg = None

    return deep_merge(template_cfg, session_cfg, request_cfg)


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


def marshal_export_data(
    body: dict,
    section_filter: str | None = None,
    tree: "list | None" = None,
) -> dict:
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
        tree: Optional per-session document tree (a list[DocNode]).  When None
              (the default), the global DOCUMENT_TREE is used, so every existing
              caller is byte-identical.  A per-session structure override
              (document_config.build_session_tree) is passed here so the report
              re-renders with a different structure against the SAME data — no
              re-integration (the render path never touches integrated.json).

    Returns:
        The render-ready data dict (the shape generate_html / generate_latex
        walk).
    """
    from document_tree import DOCUMENT_TREE
    # Resolve once: `active_tree` is a concrete list for the walks that need one;
    # the raw `tree` param (possibly None) is passed to find_node so the default
    # path keeps its O(1) index lookup (an explicit tree forces a linear scan).
    active_tree = tree if tree is not None else DOCUMENT_TREE

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

    # Per-content-type layout styling (fonts + page flow).  A single ``styles``
    # config, resolved per-node by layout_style.resolve_layout_style, that BOTH
    # renderers consume identically (LaTeX wraps each chunk, HTML emits CSS —
    # ADR-0006 no-drift).  Three SOURCES merged in increasing precedence:
    # global template block ← per-session override ← live request body.  Empty
    # everywhere ⇒ {} ⇒ each surface emits its built-in look (no-op).
    data["layout_style"] = _resolve_layout_config(body)

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

    # Table 1: Final Sample Counts (the sample-counts-table tree node).  Built
    # from the posted MethodsContext, which already carries
    # genomics_sample_counts on the web path (no session_dir here, so the
    # fingerprint fallback is a no-op).  None ⇒ node shows its pending stub.
    if methods_data and methods_data.get("context"):
        from methods_table1 import build_sample_counts_from_context
        sample_counts = build_sample_counts_from_context(methods_data["context"])
        if sample_counts:
            data["sample_counts"] = sample_counts

    # Assign positional table numbers on the document tree before any overlay
    # reads them.  _overlay_apical_sections resolves each section's table number
    # via _find_table_number(DOCUMENT_TREE, ...), which reads node.table_number;
    # those fields are None until compute_table_numbers() has run.  Computing
    # here (rather than relying on a later call leaking numbers across requests)
    # makes a fresh process produce correct numbers on the first call.
    from document_tree import compute_table_numbers
    compute_table_numbers(active_tree)

    from report_data_overlays import (
        _overlay_abstract,
        _overlay_apical_sections,
        _overlay_unified_and_bmd,
        _overlay_genomics,
    )
    _overlay_abstract(data, body)
    _overlay_apical_sections(data, body, tree=active_tree)
    _overlay_unified_and_bmd(data, body)
    _overlay_genomics(data, body)

    # Positional table numbers for the data-driven genomics tables — continues
    # the tree sequence (Table 8 → 9, 10, ...) now that genomics_sections is
    # finalized.  Same helper the LaTeX session path calls, so both surfaces
    # number identically; runs before _build_toc_entries so the Tables list
    # picks the numbers up.  A no-op when there are no genomics sections.
    from document_tree import assign_genomics_table_numbers
    assign_genomics_table_numbers(active_tree, data.get("genomics_sections"))

    # Summary
    summary_paragraphs = body.get("summary_paragraphs", [])
    if summary_paragraphs:
        data["summary"] = {"paragraphs": summary_paragraphs}

    # Inject the document structure tree so the Typst template can walk
    # it for heading hierarchy, table numbering, and section ordering.
    from document_tree import serialize_tree, find_node, is_leaf_table
    data["document_tree"] = serialize_tree(active_tree)

    # Build manual TOC entries from the document tree BEFORE the section
    # filter strips content.  This lets the tables-list preview render a
    # complete Table of Contents with ready/placeholder styling, even
    # though the body headings are stripped from the compiled document.
    from report_data_toc import _build_toc_entries, _apply_section_filter
    toc_entries, table_entries = _build_toc_entries(data, tree=active_tree)
    data["toc_entries"] = toc_entries
    data["table_entries"] = table_entries

    # Apply section filter for PDF previews.
    # Uses the document tree to determine which data keys and platforms
    # belong to the requested TOC node — no hardcoded maps.
    if section_filter:
        _apply_section_filter(data, section_filter, tree=tree)
        # Tell the Typst template whether this is a leaf table preview
        # (no headings, just the table) vs a group/section preview.
        node = find_node(section_filter, tree)
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
    # Only prose subsections (heading-bearing narrative/heading-only nodes)
    # become methods "sections"; a data table nested under Methods (e.g. the
    # headingless sample-counts-table) renders through its own dispatch and must
    # NOT masquerade as an empty prose section.
    _PROSE_TYPES = {"narrative", "heading-only"}

    def _visit(node) -> None:
        if node.node_type not in _PROSE_TYPES:
            return
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
        # Foreword — fixed NIEHS boilerplate.  Each paragraph is an INLINE-CONTENT
        # list (render_common inline model): plain-string runs interleaved with
        # {"type": "ext-link", ...} units carrying the reference's embedded
        # hyperlinks (NIEHS, DTT, the report website, PubMed).  All three surfaces
        # render these as real links (docx w:hyperlink / LaTeX \href / HTML <a>).
        "foreword": {"paragraphs": [
            [
                "The ",
                {"type": "ext-link",
                 "text": "National Institute of Environmental Health Sciences (NIEHS)",
                 "href": "https://www.niehs.nih.gov/"},
                " is one of 27 institutes and centers of the National Institutes of Health, which is part of the U.S. Department of Health and Human Services. The NIEHS mission is to discover how the environment affects people in order to promote healthier lives. NIEHS works to accomplish its mission by conducting and funding research on human health effects of environmental exposures; developing the next generation of environmental health scientists; and providing critical research, knowledge, and information to citizens and policymakers who are working to prevent hazardous exposures and reduce the risk of disease and disorders connected to the environment. NIEHS is a foundational leader in environmental health sciences and committed to ensuring that its research is directed toward a healthier environment and healthier lives for all people.",
            ],
            [
                "The NIEHS Report series began in 2022. The environmental health sciences research described in this series is conducted primarily by the ",
                {"type": "ext-link",
                 "text": "Division of Translational Toxicology (DTT)",
                 "href": "https://www.niehs.nih.gov/research/atniehs/dtt/index.cfm"},
                " at NIEHS. NIEHS/DTT scientists conduct innovative toxicology research that aligns with real-world public health needs and translates scientific evidence into knowledge that can inform individual and public health decision-making.",
            ],
            [
                "NIEHS reports are available free of charge on the ",
                {"type": "ext-link",
                 "text": "NIEHS/DTT website",
                 "href": "https://www.niehs.nih.gov/research/atniehs/dtt/assoc/reports/niehs-reports/index.cfm"},
                " and cataloged in ",
                {"type": "ext-link", "text": "PubMed",
                 "href": "https://pubmed.ncbi.nlm.nih.gov/"},
                ", a free resource developed and maintained by the National Library of Medicine (part of the National Institutes of Health).",
            ],
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
        # DOI and Report Series Number are assigned by NIEHS only at
        # publication, so they are genuinely unknown pre-publication.  Render
        # them as plain "to be assigned" text rather than ph()-wrapped scaffold:
        # the guillemets ph() adds ("«...»") are non-ASCII and rendered as
        # mojibake ("Â¿") in the compiled PDF, and a placeholder marker should
        # never ship in a deliverable regardless.  The other four lines are
        # real, known values.
        "publication_details": {"paragraphs": [
            "Publisher: National Institute of Environmental Health Sciences",
            "Publishing Location: Research Triangle Park, NC",
            "ISSN: 2768-5632",
            "DOI: to be assigned upon publication",
            "Report Series: NIEHS Report Series",
            "Report Series Number: to be assigned upon publication",
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

def _build_toc_entries(data: dict, tree: "list | None" = None) -> tuple[list[dict], list[dict]]:
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

    nodes = tree if tree is not None else DOCUMENT_TREE
    # Ensure table numbers are computed before we walk
    compute_table_numbers(nodes)

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

        # Sample-counts table (Table 1) — ready iff its built matrix has rows.
        if node.node_type == "sample-counts-table":
            built = data.get(dk) if dk else None
            return bool(isinstance(built, dict) and built.get("rows"))

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

    _walk_toc(nodes)

    # Genomics tables are DATA-DRIVEN (not tree nodes), so the walk above misses
    # them.  They were numbered by assign_genomics_table_numbers before this ran;
    # append them to the Tables list in table_number order so the front-matter
    # list continues Table 8 → 9, 10, ...  Title/readiness come from the same
    # shared caption + row presence the renderers use, so all three agree.
    from render_common import genomics_table_caption
    genomics_tables = [
        {
            "title": genomics_table_caption(entry).split(". ", 1)[-1],
            "table_number": entry["table_number"],
            "ready": bool(
                entry.get("gene_sets") if entry.get("type") == "gene_set"
                else entry.get("top_genes")
            ),
        }
        for entry in (data.get("genomics_sections") or [])
        if entry.get("table_number") is not None
    ]
    genomics_tables.sort(key=lambda e: e["table_number"])
    table_entries.extend(genomics_tables)

    return toc_entries, table_entries


def _apply_section_filter(data: dict, section_filter: str, tree: "list | None" = None) -> None:
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
        "background", "methods", "sample_counts", "apical_sections",
        "unified_narratives", "internal_dose", "bmd_summary",
        "genomics_sections", "gene_set_narrative", "gene_narrative",
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
                if find_node(section_filter, tree) is None and candidate_organ:
                    organ_qualifier = candidate_organ.lower()
                    section_filter = parent_id
                break

    # --- Look up the node in the document tree ---
    node = find_node(section_filter, tree)

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
