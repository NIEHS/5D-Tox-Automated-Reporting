"""
document_node.py — the DocNode dataclass: one node in the report document tree.

Extracted from document_tree.py (ADR-0003 Phase 2.5) so that document_template.py
can construct DocNodes directly without an import cycle.  The import graph is a
clean line: this module depends on nothing in the package; document_template
depends on it; document_tree depends on both.  document_tree re-exports DocNode,
so `from document_tree import DocNode` keeps working for existing callers.

This module defines the node *shape* only.  The registry of node *types* — and
their render capabilities, content kinds, headingless flag, allowed children,
and required bindings — lives in render_capabilities.COMPONENT_CATALOG.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from document_model.content_item import ContentItem


@dataclass
class DocNode:
    """
    One node in the document structure tree.

    Args:
        id:             Unique identifier matching navigation panel node IDs.
        title:          Display title for the heading and TOC entry.
        level:          Heading level (0 = no heading, 1 = H1, 2 = H2, 3 = H3).
                        Derived by the instantiator (0 if the type is headingless,
                        else nesting depth); not authored in templates.
        node_type:      Which catalog component type this is — drives how each
                        renderer renders it (see render_capabilities.COMPONENT_CATALOG).
        data_key:       Which key in the report data dict holds this node's content.
                        None if the node has no direct content (e.g., heading-only).
        platform:       For table nodes under Results — which platform's data to
                        render (e.g., "Body Weight", "Clinical Chemistry").
        narrative_key:  For narrative+tables nodes — which key in unified_narratives
                        holds the group narrative (e.g., "apical", "clinical_pathology").
        children:       Child nodes (sub-sections, tables within a section).
        content_items:  Ordered, sub-addressable ContentItems this component owns
                        (ADR-0003 Part B).  Distinct from children: children are
                        their own tree nodes (headings/sections); content_items
                        are the addressable blocks INSIDE one component (a text /
                        table / chart block), keyed "<node.id>::<item.id>".  Empty
                        for every node until a template authors them.
        table_number:   Auto-assigned by compute_table_numbers().  None until computed.
        figure_number:  Reserved positional figure number for a figure-bearing
                        node.  There is NO DocNode-level figure-numbering pass
                        yet — genomics chart figure numbers are assigned on the
                        chart payloads by genomics_charts.attach_genomics_charts,
                        not here — so this field is currently always None.
        appendix_letter: Positional appendix letter ("A", "B", …) assigned by
                        compute_appendix_letters() to each `appendix` node in
                        document order.  None until computed (and on non-appendix
                        nodes).  The single source of the appendix letter: the
                        renderers compose "Appendix {letter}. {title}" from it
                        (titles no longer carry a literal "Appendix A." prefix),
                        and the docx surface uses it to drive chapter-relative
                        page numbering (pgNumType chapStyle → "A-1, B-1, …").
        ready_key:      Alpine store ready flag name (for navigation panel enable/disable).
                        None if always enabled.
        methods_key:    For M&M subsection nodes — the key in data["methods"]["sections"]
                        that holds this subsection's prose.  Matches SUBSECTION_SKELETON
                        keys in methods_report.py (e.g., "study_design", "clinical_obs").
                        Used by _apply_section_filter() to render only the selected
                        subsection in M&M previews.
        orientation:    Authored page-orientation default ("landscape" /
                        "portrait") for an orientable component (ADR-0003
                        Amendment 1).  None means portrait.  A per-session UI
                        override wins over this; the renderer merges the two via
                        render_capabilities.landscape_requested(default=...).
        caption:        Descriptive paragraph for a captionable component (a
                        table or figure — ADR-0004 amendment a).  Distinct from
                        `title`, which is the short heading/title; this is the
                        BITS <caption><p>...</p></caption> role.  Validated by
                        the instantiator to only appear on captionable types.
                        The renderer prefers this over the data-overlay caption
                        when set; falls back when not, preserving the data-
                        driven path.
        region:         Which book region this node belongs to — "front",
                        "body", or "back" (ADR-0004 amendment d).  Set by the
                        instantiator from the template's region containers and
                        inherited by descendants.  Drives the page-numbering
                        switch and projects directly to BITS <front-matter> /
                        <book-body> / <book-back>.  Not authored on individual
                        nodes — region containers in the template own it.
        content:        For the freeform-page / freeform-block component types:
                        the AUTHORED content source.  Either an inline string (a
                        latex/html fragment) or a dual-source mapping
                        {latex: ..., html: ...} for content that differs per
                        render surface.  None for every pipeline-driven node
                        (which read data[data_key] instead).  See
                        freeform_content.resolve_freeform.
        content_file:   For freeform nodes: a path (relative to templates/) to an
                        external content file read at load time — a .docx for
                        representation "docx", or a .tex/.html fragment.  Mutually
                        exclusive with inline `content`.
        representation: For freeform nodes: "latex" | "html" | "docx" — how to
                        interpret `content`/`content_file`.  Not needed when
                        `content` is a dual-source mapping.
        session_content: For freeform nodes: name of PER-STUDY authored content
                        (`<name>.html` / `<name>.tex`, or a `<name>.json` file
                        list) looked up in the study's own content —
                        sessions/<dtxsid>/authored/, then the version-controlled
                        templates/studies/<dtxsid>/ — never shared across
                        chemicals.  Resolved per request (document_tree.render_nodes).
        requires_platform: Data gate: the node's content applies only when this
                        data domain was collected (e.g. "Tissue Concentration"),
                        or — a list — when ANY of the listed domains was.
        not_collected_text: Shippable statement rendered instead when none of
                        `requires_platform` was collected by the study (default:
                        "<title> was not evaluated in this study.").
        missing_content_text: Shippable statement rendered when the study supplies
                        no `session_content`.  Unset ⇒ a pending placeholder (the
                        content is required and still has to be authored).
        caption_suffix: On a genomics-section: words its per-tissue tables'
                        captions end with, ", for ${subject} ${treatment}" (the
                        2026 books), filled per table from the animals it has
                        rows for (document_tree.assign_genomics_table_numbers).
        deposit_text:   Statement rendered, when the study supplies no
                        `session_content`, if its data deposit has a DOI and files
                        (pipeline.deposit): "{doi}" in it becomes the DOI's link
                        ("The following supplemental files are available at
                        {doi}.").  Before `missing_content_text`.
        resolved_content: COMPUTED at load by the instantiator — the per-surface
                        markup {latex: str|None, html: str|None} produced from the
                        authored source (docx is parsed once here).  Not authored;
                        the renderers read this.  None for non-freeform nodes.
        subtype:        For cover / title-page nodes: which branded cover layout to
                        render (e.g. "niehs-5d-tox").  Looked up in
                        cover_layouts.get_cover_layout by the renderers; None falls
                        back to the default layout.  A pure render concern — not
                        serialized to the frontend.
        appendix_scope: COMPUTED by the numbering pass (ADR-0025 §5): the letter of
                        the enclosing appendix ("B") for every node inside an
                        appendix subtree, None elsewhere.  Tables and figures in a
                        scope are numbered per appendix, not in the body sequence.
        table_label:    COMPUTED display label for a numbered table: "3" in the
                        body, "B-1" inside Appendix B.  The renderers and lists
                        show this; table_number stays the integer (global position
                        in the body, or the appendix-local position in a scope).
        figure_label:   COMPUTED display label for a numbered figure, same rule.
        role:           The document ROLE this node plays (ADR-0025): a key of
                        render_capabilities.ROLE_PROFILE ("sec", "table-wrap",
                        "fig", "app", …).  COMPUTED by the instantiator from the
                        node_type preset; a template entry may state it only to
                        assert it (a mismatch is a load error).  Containment is
                        decided by role, so the tree carries it explicitly.
        binding:        HOW this node's content is produced (ADR-0025): one of
                        render_capabilities.BINDINGS — container / programmatic /
                        llm / authored / derived.  Defaults to the preset's first
                        binding; a template entry may choose another binding the
                        preset lists (e.g. `binding: llm` on the abstract).  The
                        workflow reads this (readiness, approvability) instead of
                        inferring it from the type.
        element:        The BITS element a top-level node projects to (ADR-0028):
                        book-meta | abstract | foreword | front-matter-part |
                        book-part | book-app.  Authored on the template's parts;
                        when omitted the instantiator derives it from type and
                        region (render_capabilities.default_element).  None for
                        nested nodes and for print-only nodes (toc, tables-list,
                        page-break), which have no BITS element.
        book_part_type: The part's BITS @book-part-type (ADR-0028): foreword,
                        authors, contributors, peer-review, acknowledgments,
                        section, appendix.  Top-level parts only; defaulted by the
                        instantiator like `element`.
        parts:          The labeled parts a labeled node is declared to have, in
                        order (ADR-0028 §6) — the abstract's Background / Methods /
                        Results / Summary.  The BITS projection emits each one,
                        with a visible pending paragraph for a part with no text.
        sec_label:      COMPUTED by the numbering pass (ADR-0028 §3): the label of
                        a titled section inside an appendix ("C.1", "C.2.1"); None
                        elsewhere.  Titles never carry it; print surfaces compose
                        "C.1. Title" through render_common.section_heading_text.
        deposit_group:  On a DERIVED supplementary-material node: which kind of the
                        study's deposited files it lists (pipeline.deposit.KINDS:
                        apical, genomic, study-tables, animal-data, …), one entry
                        per file of the session's deposit.json.
        repeat:         On a section or a table: one copy of it per item, expanded
                        by document_tree.study_tree (repeat_items) —
                        `deposit_species`: per species the deposit holds (the
                        2026 books' "G.3 Rats" / "G.4 Mice"); `study_species`:
                        per study of a report over several ("Study Design for
                        Rats"); `genomic_organs`: per tissue of the genomic
                        analyses.  A copy is titled with its item, or fills
                        `${species}` / `${organ}` in its title.  A single study
                        is one unscoped copy; with no deposit species the
                        section's children stand in its place, with no tissues
                        it is left out.
        scope_species:  COMPUTED by that expansion: the species a copy (and every
                        node in it) is about; derived file lists keep to it, and
                        in a report over several studies the copy renders from
                        its study's data (render_common.node_data).
        scope_organ:    COMPUTED likewise: the tissue a `genomic_organs` copy is
                        about; its gene set / gene prose is that tissue's.
    """
    id: str
    title: str
    level: int = 1
    node_type: str = "narrative"
    data_key: str | None = None
    platform: str | None = None
    narrative_key: str | None = None
    children: list[DocNode] = field(default_factory=list)
    content_items: list[ContentItem] = field(default_factory=list)
    table_number: int | None = None
    figure_number: int | None = None
    appendix_letter: str | None = None
    ready_key: str | None = None
    methods_key: str | None = None
    orientation: str | None = None
    caption: str | None = None
    region: str | None = None
    content: str | dict | None = None
    content_file: str | None = None
    representation: str | None = None
    resolved_content: dict | None = None
    session_content: str | None = None
    requires_platform: str | list | None = None
    not_collected_text: str | None = None
    missing_content_text: str | None = None
    deposit_text: str | None = None
    caption_suffix: str | None = None
    subtype: str | None = None
    role: str | None = None
    binding: str | None = None
    appendix_scope: str | None = None
    table_label: str | None = None
    figure_label: str | None = None
    element: str | None = None
    book_part_type: str | None = None
    parts: list | None = None
    sec_label: str | None = None
    deposit_group: str | None = None
    repeat: str | None = None
    scope_species: str | None = None
    scope_organ: str | None = None
