"""
report_pdf.py — Build a PDF/UA-1 compliant report from approved session data.

Compiles the report.typ Typst template with the provided report data,
producing a tagged PDF with full StructTreeRoot, semantic heading hierarchy
(H1-H6), proper table structure (TH/TD), XMP metadata, and PDF/UA-1
identifier.  The output passes the Matterhorn Protocol machine-checkable
conditions for government 508 compliance.

The Typst compiler is embedded in the `typst` Python package (a pre-built
Rust binary shipped as a wheel — no Rust toolchain needed).  Compilation
is sub-second for typical report sizes.

Usage:
    from report_pdf import build_report_pdf
    pdf_bytes = build_report_pdf(report_data_dict)

    # report_data_dict matches the JSON schema consumed by report.typ.
    # All top-level keys are optional — missing sections are simply
    # omitted from the output.  See the full schema below.
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
from pathlib import Path

import typst


# --- Path to the Typst template ---
# Resolved relative to this file so it works regardless of cwd.
_TEMPLATE_PATH = str(Path(__file__).parent / "report.typ")


def build_report_pdf(data: dict, chart_images: dict | None = None) -> bytes:
    """
    Compile the NIEHS-styled report to PDF/UA-1.

    Serializes `data` to JSON, passes it to the Typst template via
    sys.inputs, and compiles with the ua-1 PDF standard.

    If chart_images is provided (dict with umap_png/cluster_png as
    base64 strings), the PNGs are written to temp files and their
    paths injected into the data dict so the Typst template can
    embed them as figures.

    Args:
        data: Report data dictionary matching the report.typ JSON schema.
              All top-level keys are optional — missing sections are
              simply omitted from the output.
        chart_images: Optional dict with base64-encoded PNG chart images
                      and caption strings.

    Returns:
        The compiled PDF as raw bytes, ready to write to a file or
        return as an HTTP response.

    Raises:
        typst.TypstError: If the template fails to compile (e.g., due
            to missing alt text on figures under PDF/UA-1 strict mode).
    """
    import base64
    import tempfile

    # Ensure required metadata fields have defaults so PDF/UA-1
    # validation doesn't fail on missing title or language.
    data.setdefault("title", "5dToxReport")
    data.setdefault("author", "5dToxReport")

    # Write chart images to temp files so Typst can reference them.
    # The temp files are created in the same directory as the template
    # so Typst's file resolution finds them relative to the root.
    temp_files = []
    if chart_images:
        template_dir = Path(_TEMPLATE_PATH).parent
        chart_data = {}

        for key, filename in [("umap_png", "chart_umap.png"), ("cluster_png", "chart_cluster.png")]:
            b64 = chart_images.get(key)
            if not b64:
                continue
            try:
                png_bytes = base64.b64decode(b64)
                img_path = template_dir / filename
                img_path.write_bytes(png_bytes)
                temp_files.append(img_path)
                chart_data[key.replace("_png", "_path")] = filename
            except Exception:
                pass

        # Pass captions through
        for cap_key in ("umap_caption", "cluster_caption"):
            if chart_images.get(cap_key):
                chart_data[cap_key] = chart_images[cap_key]

        if chart_data:
            data["genomics_charts"] = chart_data

    try:
        pdf_bytes = typst.compile(
            _TEMPLATE_PATH,
            sys_inputs={"data": json.dumps(data, default=str)},
            # PDF/UA-1 (ISO 14289-1) — enforces:
            #   - StructTreeRoot with full tag hierarchy
            #   - /MarkInfo << /Marked true >>
            #   - PDF/UA identifier in XMP metadata
            #   - /Lang in the document catalog
            #   - Compile-time validation of heading order, alt text, etc.
            pdf_standards=["ua-1"],
        )
    finally:
        # Clean up temp chart image files
        for f in temp_files:
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass

    return pdf_bytes


def marshal_export_data(body: dict, section_filter: str | None = None) -> dict:
    """
    Convert the /api/export-pdf request body (same schema as /api/export-docx)
    into the report.typ JSON schema.

    Strategy: start from the full scaffold (which defines every section the
    NIEHS template knows about — boilerplate front matter, heading-only stubs
    for study-specific content) and overlay real data on top.  This ensures
    the exported PDF always shows the complete NIEHS document structure:
    real content where it exists, empty heading stubs everywhere else.

    The web UI sends the same payload to both endpoints for consistency.
    This function reshapes it into the structure the Typst template expects.

    Args:
        body: The request JSON body from the web UI export call.
        section_filter: Optional filter to keep only a specific report
                        section for per-tab PDF previews.  Valid values:
                        "apical" (dose-response tables + narrative),
                        "genomics" (gene set/gene tables + descriptions),
                        "charts" (UMAP + cluster scatter figures).
                        When None, the full report is returned.

    Returns:
        A dict ready to pass to build_report_pdf().
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
    running_header_name = ta["forms"]["running_header"]["text"]
    full_title = (
        f"In Vivo Repeat Dose Biological Potency Study of "
        f"{running_header_name} in Sprague Dawley Rats"
    )
    data["title"] = full_title
    data["running_header"] = full_title
    data["chemical_name"] = chemical_name
    data["casrn"] = body.get("casrn", "")
    data["dtxsid"] = body.get("dtxsid", "")

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

    # References
    references = body.get("references", [])
    if references:
        data["references"] = references

    # Materials and Methods — overlay structured or flat content onto
    # the scaffold's full H2/H3 heading hierarchy.
    methods_data = body.get("methods_data")
    methods_paragraphs = body.get("methods_paragraphs", [])
    if methods_data and methods_data.get("sections"):
        data["methods"] = {"sections": methods_data["sections"]}
    elif methods_paragraphs:
        data["methods"] = {"sections": [], "paragraphs": methods_paragraphs}
    # else: scaffold's heading-only methods structure remains

    # Apical endpoint sections
    apical_sections = body.get("apical_sections", [])
    if apical_sections:
        data["apical_sections"] = []
        for sec in apical_sections:
            footnotes = list(sec.get("footnotes", []))
            dose_unit = sec.get("dose_unit", "mg/kg")

            # Build per-sex missing-animal footnotes from table row data.
            # Each row may have a missing_animals dict mapping dose → count
            # (animals that died before terminal sacrifice).  We store these
            # separately per sex so the Typst template can append the correct
            # footnote to each sex's table independently.
            missing_fn = _build_missing_animal_footnotes(
                sec.get("table_data", {}), dose_unit
            )

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
                "table_data": sec.get("table_data", {}),
                "footnotes": footnotes,
                "missing_animal_footnotes": missing_fn,
                # BMD/BMDL definition line — rendered above the lettered
                # footnotes as an unnumbered paragraph.  Only body weight
                # tables include this (from body_weight_table.py builder).
                "bmd_definition": sec.get("bmd_definition"),
                # Platform identifier — used by _apply_section_filter()
                # to filter sections for per-subsection PDF previews.
                "platform": sec.get("platform", section_title),
            }

            # Table number — derived from the document structure tree.
            # The tree assigns numbers by position (Table 2 = Body Weight,
            # Table 3 = Organ Weight, etc.).  Overrides any user-provided
            # table_number from the UI.
            from document_tree import find_node, DOCUMENT_TREE
            platform = apical_entry["platform"]
            # Search the tree for a table node matching this platform
            def _find_table_number(nodes, plat):
                for n in nodes:
                    if n.platform == plat and n.table_number is not None:
                        return n.table_number
                    if n.children:
                        result = _find_table_number(n.children, plat)
                        if result is not None:
                            return result
                return None
            tree_table_num = _find_table_number(DOCUMENT_TREE, platform)
            if tree_table_num is not None:
                apical_entry["table_number"] = tree_table_num

            data["apical_sections"].append(apical_entry)

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
    bmd_summary = body.get("bmd_summary")
    bmd_endpoints = body.get("bmd_summary_endpoints", [])
    if bmd_summary:
        data["bmd_summary"] = bmd_summary
    elif bmd_endpoints:
        data["bmd_summary"] = {"endpoints": bmd_endpoints}

    # Genomics
    genomics = body.get("genomics_sections", [])
    if genomics:
        data["genomics_sections"] = genomics

    gene_set_narrative = body.get("gene_set_narrative")
    if gene_set_narrative:
        data["gene_set_narrative"] = _ensure_paragraphs(gene_set_narrative)

    gene_narrative = body.get("gene_narrative")
    if gene_narrative:
        data["gene_narrative"] = _ensure_paragraphs(gene_narrative)

    # Summary
    summary_paragraphs = body.get("summary_paragraphs", [])
    if summary_paragraphs:
        data["summary"] = {"paragraphs": summary_paragraphs}

    # Inject the document structure tree so the Typst template can walk
    # it for heading hierarchy, table numbering, and section ordering.
    from document_tree import serialize_tree, find_node, is_leaf_table
    data["document_tree"] = serialize_tree()

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
        A dict ready to pass directly to build_report_pdf().
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
    running_header_name = ta["forms"]["running_header"]["text"]
    full_title = (
        f"In Vivo Repeat Dose Biological Potency Study of "
        f"{running_header_name} in Sprague Dawley Rats"
    )

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
    # Mirrors the exact NIEHS Report 10 section structure.
    # --- Materials and Methods: heading-only scaffold ---
    # Full H2/H3 hierarchy matching NIEHS Report 10 TOC (pages iii-iv).
    # Paragraph content is empty — just the heading structure so the TOC
    # shows the complete expected layout.
    methods_sections = [
        {"level": 2, "heading": "Study Design", "paragraphs": []},
        {"level": 2, "heading": "Dose Selection Rationale", "paragraphs": []},
        {"level": 2, "heading": "Chemistry", "paragraphs": []},
        {"level": 2, "heading": "Clinical Examinations and Sample Collection", "paragraphs": []},
        {"level": 3, "heading": "Clinical Observations", "paragraphs": []},
        {"level": 3, "heading": "Body and Organ Weights", "paragraphs": []},
        {"level": 3, "heading": "Clinical Pathology", "paragraphs": []},
        {"level": 3, "heading": "Internal Dose Assessment", "paragraphs": []},
        {"level": 2, "heading": "Transcriptomics", "paragraphs": []},
        {"level": 3, "heading": "Sample Collection for Transcriptomics", "paragraphs": []},
        {"level": 3, "heading": "RNA Isolation, Library Creation, and Sequencing", "paragraphs": []},
        {"level": 3, "heading": "Sequence Data Processing", "paragraphs": []},
        {"level": 3, "heading": "Sequencing Quality Checks and Outlier Removal", "paragraphs": []},
        {"level": 3, "heading": "Data Normalization", "paragraphs": []},
        {"level": 2, "heading": "Data Analysis", "paragraphs": []},
        {"level": 3, "heading": "Statistical Analysis of Body Weights, Organ Weights, and Clinical Pathology", "paragraphs": []},
        {"level": 3, "heading": "Benchmark Dose Analysis of Body Weights, Organ Weights, and Clinical Pathology", "paragraphs": []},
        {"level": 3, "heading": "Benchmark Dose Analysis of Transcriptomics Data", "paragraphs": []},
        {"level": 3, "heading": "Empirical False Discovery Rate Determination for Genomic Dose-response Modeling", "paragraphs": []},
        {"level": 2, "heading": "Data Accessibility", "paragraphs": []},
    ]

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
    from document_tree import find_node, collect_data_keys, collect_platforms

    # --- Signal the Typst template to skip structural pages ---
    data["section_only"] = True

    # All data keys that can be independently removed
    ALL_BODY = {
        "background", "methods", "apical_sections", "unified_narratives",
        "internal_dose", "bmd_summary", "genomics_sections",
        "gene_set_narrative", "gene_narrative", "genomics_charts",
        "summary", "references",
    }
    ALL_FRONT = {
        "foreword", "about_report", "peer_review", "publication_details",
        "acknowledgments", "abstract", "table_of_contents",
    }

    # --- Look up the node in the document tree ---
    node = find_node(section_filter)

    if node is None:
        # Unknown node ID — strip everything as a safe fallback
        return

    # Front-matter nodes: keep front matter, remove all body
    if node.node_type in ("front-matter", "tables-list", "cover", "title-page"):
        for key in ALL_BODY:
            data.pop(key, None)
        return

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

    for key in ALL_BODY - keep:
        data.pop(key, None)

    # Sub-filter apical_sections by platform
    if platforms and "apical_sections" in data:
        data["apical_sections"] = [
            s for s in data["apical_sections"]
            if s.get("platform") in platforms
        ]


def _build_missing_animal_footnotes(
    table_data: dict, dose_unit: str
) -> dict[str, str]:
    """
    Scan table_data rows for missing-animal annotations and produce
    per-sex footnote strings for the Typst template.

    Each row in table_data[sex] may carry a `missing_animals` dict mapping
    dose (as string) to integer count — the number of animals in the xlsx
    study file roster that are absent from that domain's bm2 data (animals
    that died before terminal sacrifice and couldn't have that endpoint
    measured).

    We aggregate per sex, taking the max count at each dose across all
    endpoints (since different endpoints may report slightly different N),
    and produce one footnote per sex, e.g.:

        "5 animals at 333 mg/kg; 5 animals at 1000 mg/kg did not survive
         to terminal sacrifice."

    The result is a dict keyed by sex ("Male", "Female") → footnote string.
    The Typst template appends each sex's footnote to that sex's table,
    keeping Male footnotes under the Male table and vice versa.

    Args:
        table_data: Dict keyed by sex ("Male", "Female"), each value a
                    list of row dicts with optional "missing_animals".
        dose_unit:  Dose unit string (e.g., "mg/kg") for display.

    Returns:
        Dict mapping sex → footnote string.  Empty dict if no missing
        animals in any sex.
    """
    result: dict[str, str] = {}

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
            d_label = str(int(d)) if d == int(d) else str(d)
            parts.append(
                f"{n} animal{'s' if n > 1 else ''} at {d_label} {dose_unit}"
            )

        result[sex] = (
            f"{'; '.join(parts)} did not survive to terminal sacrifice."
        )

    return result
