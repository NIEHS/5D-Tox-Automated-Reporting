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
        table_number:   Auto-assigned by compute_table_numbers().  None until computed.
        figure_number:  Auto-assigned by compute_figure_numbers().  None until computed.
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
    """
    id: str
    title: str
    level: int = 1
    node_type: str = "narrative"
    data_key: str | None = None
    platform: str | None = None
    narrative_key: str | None = None
    children: list[DocNode] = field(default_factory=list)
    table_number: int | None = None
    figure_number: int | None = None
    ready_key: str | None = None
    methods_key: str | None = None
    orientation: str | None = None
    caption: str | None = None
    region: str | None = None
