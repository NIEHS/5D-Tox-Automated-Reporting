"""
document_tree.py — Declarative NIEHS report document structure.

This module defines the complete structure of an NIEHS 5-day biological
potency report as a tree of nodes.  It is the SINGLE SOURCE OF TRUTH for:

  - Heading hierarchy (level 1, 2, 3)
  - Section ordering
  - Table numbering (auto-assigned by tree-walk position)
  - Figure numbering (auto-assigned by tree-walk position)
  - TOC sidebar navigation (generated from this tree)
  - PDF preview filtering (given a node ID, find its subtree)
  - Typst template rendering (walks this tree to emit content)

Users can override narrative content; everything structural is determined
by position in this tree.

The tree matches the NIEHS Report 10 (NBK589955) Table of Contents exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Node types — determine how the Typst template renders each node
# ---------------------------------------------------------------------------
#
# "cover"            — full-bleed cover page (custom layout, no heading)
# "title-page"       — inner title page (centered, no heading)
# "front-matter"     — front matter section (heading + paragraphs, roman pages)
# "tables-list"      — auto-generated list of tables
# "heading-only"     — structural heading with no own content (children have it)
# "narrative"        — heading + narrative paragraphs (no tables)
# "narrative+tables"  — heading + narrative paragraphs + child tables
# "table"            — a single data table (caption, columns, rows, footnotes)
# "bmd-summary"      — BMD summary table (different structure from dose-response)
# "genomics-section" — gene set or gene BMD section (narrative + tables + descriptions)
# "appendix"         — appendix section


@dataclass
class DocNode:
    """
    One node in the document structure tree.

    Args:
        id:             Unique identifier matching TOC sidebar node IDs.
        title:          Display title for the heading and TOC entry.
        level:          Heading level (0 = no heading, 1 = H1, 2 = H2, 3 = H3).
        node_type:      How the Typst template renders this node (see types above).
        data_key:       Which key in the report data dict holds this node's content.
                        None if the node has no direct content (e.g., heading-only).
        platform:       For table nodes under Results — which platform's data to
                        render (e.g., "Body Weight", "Clinical Chemistry").
        narrative_key:  For narrative+tables nodes — which key in unified_narratives
                        holds the group narrative (e.g., "apical", "clinical_pathology").
        children:       Child nodes (sub-sections, tables within a section).
        table_number:   Auto-assigned by compute_table_numbers().  None until computed.
        figure_number:  Auto-assigned by compute_figure_numbers().  None until computed.
        ready_key:      Alpine store ready flag name (for TOC enable/disable).
                        None if always enabled.
        methods_key:    For M&M subsection nodes — the key in data["methods"]["sections"]
                        that holds this subsection's prose.  Matches SUBSECTION_SKELETON
                        keys in methods_report.py (e.g., "study_design", "clinical_obs").
                        Used by _apply_section_filter() to render only the selected
                        subsection in M&M previews.
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


# ---------------------------------------------------------------------------
# The complete NIEHS report structure
# ---------------------------------------------------------------------------
# Matches NIEHS Report 10 (NBK589955) Table of Contents verbatim.
# Table numbers are auto-assigned by compute_table_numbers() — the
# position in this tree determines the number.

DOCUMENT_TREE: list[DocNode] = [
    # ── Structural pages (no heading level) ──────────────────────────
    DocNode(
        id="cover",
        title="Cover Page",
        level=0,
        node_type="cover",
    ),
    DocNode(
        id="title-page",
        title="Title Page",
        level=0,
        node_type="title-page",
    ),

    # ── Front matter (roman numeral pages) ───────────────────────────
    DocNode(
        id="foreword",
        title="Foreword",
        level=1,
        node_type="front-matter",
        data_key="foreword",
    ),
    DocNode(
        id="tables-list",
        title="Tables",
        level=1,
        node_type="tables-list",
    ),
    DocNode(
        id="about",
        title="About This Report",
        level=1,
        node_type="front-matter",
        data_key="about_report",
    ),
    DocNode(
        id="peer-review",
        title="Peer Review",
        level=1,
        node_type="front-matter",
        data_key="peer_review",
    ),
    DocNode(
        id="publication",
        title="Publication Details",
        level=1,
        node_type="front-matter",
        data_key="publication_details",
    ),
    DocNode(
        id="acknowledgments",
        title="Acknowledgments",
        level=1,
        node_type="front-matter",
        data_key="acknowledgments",
    ),
    DocNode(
        id="abstract",
        title="Abstract",
        level=1,
        node_type="front-matter",
        data_key="abstract",
    ),

    # ── Body (arabic numeral pages) ──────────────────────────────────

    # Background
    DocNode(
        id="background",
        title="Background",
        level=1,
        node_type="narrative",
        data_key="background",
    ),

    # Materials and Methods
    DocNode(
        id="methods",
        title="Materials and Methods",
        level=1,
        node_type="heading-only",
        data_key="methods",
        children=[
            DocNode(id="mm-study-design", title="Study Design", level=2,
                    node_type="narrative", data_key="methods",
                    methods_key="study_design"),
            DocNode(id="mm-dose-rationale", title="Dose Selection Rationale", level=2,
                    node_type="narrative", data_key="methods",
                    methods_key="dose_selection"),
            DocNode(id="mm-chemistry", title="Chemistry", level=2,
                    node_type="narrative", data_key="methods",
                    methods_key="chemistry"),
            DocNode(
                id="mm-clin-exam",
                title="Clinical Examinations and Sample Collection",
                level=2,
                node_type="heading-only",
                data_key="methods",
                methods_key="clinical_exams",
                children=[
                    DocNode(id="mm-clin-obs", title="Clinical Observations", level=3,
                            node_type="narrative", data_key="methods",
                            methods_key="clinical_obs"),
                    DocNode(id="mm-body-organ-wt", title="Body and Organ Weights", level=3,
                            node_type="narrative", data_key="methods",
                            methods_key="body_organ_weights"),
                    DocNode(id="mm-clin-path", title="Clinical Pathology", level=3,
                            node_type="narrative", data_key="methods",
                            methods_key="clinical_pathology"),
                    DocNode(id="mm-internal-dose", title="Internal Dose Assessment", level=3,
                            node_type="narrative", data_key="methods",
                            methods_key="internal_dose"),
                ],
            ),
            DocNode(
                id="mm-transcriptomics",
                title="Transcriptomics",
                level=2,
                node_type="heading-only",
                data_key="methods",
                methods_key="transcriptomics",
                children=[
                    DocNode(id="mm-tx-sample", title="Sample Collection for Transcriptomics", level=3,
                            node_type="narrative", data_key="methods",
                            methods_key="txomics_sample"),
                    DocNode(id="mm-tx-rna", title="RNA Isolation, Library Creation, and Sequencing", level=3,
                            node_type="narrative", data_key="methods",
                            methods_key="txomics_rna"),
                    DocNode(id="mm-tx-processing", title="Sequence Data Processing", level=3,
                            node_type="narrative", data_key="methods",
                            methods_key="txomics_seq_processing"),
                    DocNode(id="mm-tx-qc", title="Sequencing Quality Checks and Outlier Removal", level=3,
                            node_type="narrative", data_key="methods",
                            methods_key="txomics_qc"),
                    DocNode(id="mm-tx-norm", title="Data Normalization", level=3,
                            node_type="narrative", data_key="methods",
                            methods_key="txomics_normalization"),
                ],
            ),
            DocNode(
                id="mm-data-analysis",
                title="Data Analysis",
                level=2,
                node_type="heading-only",
                data_key="methods",
                methods_key="data_analysis",
                children=[
                    DocNode(id="mm-stat-apical",
                            title="Statistical Analysis of Body Weights, Organ Weights, and Clinical Pathology",
                            level=3, node_type="narrative", data_key="methods",
                            methods_key="stat_analysis"),
                    DocNode(id="mm-bmd-apical",
                            title="Benchmark Dose Analysis of Body Weights, Organ Weights, and Clinical Pathology",
                            level=3, node_type="narrative", data_key="methods",
                            methods_key="bmd_apical"),
                    DocNode(id="mm-bmd-tx",
                            title="Benchmark Dose Analysis of Transcriptomics Data",
                            level=3, node_type="narrative", data_key="methods",
                            methods_key="bmd_genomics"),
                    DocNode(id="mm-fdr",
                            title="Empirical False Discovery Rate Determination for Genomic Dose-response Modeling",
                            level=3, node_type="narrative", data_key="methods",
                            methods_key="efdr"),
                    DocNode(id="mm-data-access", title="Data Accessibility", level=3,
                            node_type="narrative", data_key="methods",
                            methods_key="data_accessibility"),
                ],
            ),
        ],
    ),

    # Results
    DocNode(
        id="results",
        title="Results",
        level=1,
        node_type="heading-only",
        children=[
            # Animal Condition, Body Weights, and Organ Weights
            DocNode(
                id="animal-condition",
                title="Animal Condition, Body Weights, and Organ Weights",
                level=2,
                node_type="narrative+tables",
                narrative_key="animal_condition",
                ready_key="animalCondition",
                children=[
                    DocNode(id="table-body-weight",
                            title="Summary of Body Weights",
                            level=0, node_type="table",
                            platform="Body Weight",
                            ready_key="animalCondition"),
                    DocNode(id="table-organ-weight",
                            title="Summary of Organ Weights",
                            level=0, node_type="table",
                            platform="Organ Weight",
                            ready_key="animalCondition"),
                    DocNode(id="table-clinical-obs",
                            title="Clinical Observations",
                            level=0, node_type="incidence-table",
                            platform="Clinical Observations",
                            ready_key="animalCondition"),
                ],
            ),
            # Clinical Pathology
            DocNode(
                id="clinical-path",
                title="Clinical Pathology",
                level=2,
                node_type="narrative+tables",
                narrative_key="clinical_pathology",
                ready_key="clinicalPath",
                children=[
                    DocNode(id="table-clin-chem",
                            title="Summary of Select Clinical Chemistry Data",
                            level=0, node_type="table",
                            platform="Clinical Chemistry",
                            ready_key="clinicalPath"),
                    DocNode(id="table-hematology",
                            title="Summary of Select Hematology Data",
                            level=0, node_type="table",
                            platform="Hematology",
                            ready_key="clinicalPath"),
                    DocNode(id="table-hormones",
                            title="Summary of Select Hormone Data",
                            level=0, node_type="table",
                            platform="Hormones",
                            ready_key="clinicalPath"),
                ],
            ),
            # Internal Dose Assessment
            DocNode(
                id="internal-dose",
                title="Internal Dose Assessment",
                level=2,
                node_type="narrative+tables",
                ready_key="internalDose",
                children=[
                    DocNode(id="table-tissue-conc",
                            title="Summary of Plasma Concentration Data",
                            level=0, node_type="table",
                            platform="Tissue Concentration",
                            ready_key="internalDose"),
                ],
            ),
            # Apical Endpoint BMD Summary
            DocNode(
                id="bmd-summary",
                title="Apical Endpoint Benchmark Dose Summary",
                level=2,
                node_type="bmd-summary",
                data_key="bmd_summary",
                ready_key="bmdSummary",
            ),
            # Gene Set Benchmark Dose Analysis
            DocNode(
                id="gene-sets",
                title="Gene Set Benchmark Dose Analysis",
                level=2,
                node_type="genomics-section",
                data_key="genomics_sections",
                narrative_key="gene_set_narrative",
                ready_key="geneSets",
            ),
            # Gene Benchmark Dose Analysis
            DocNode(
                id="gene-bmd",
                title="Gene Benchmark Dose Analysis",
                level=2,
                node_type="genomics-section",
                data_key="genomics_sections",
                narrative_key="gene_narrative",
                ready_key="geneBmd",
            ),
            # Note: the former `charts` DocNode was removed when the
            # genomics UMAP + cluster-scatter charts were inlined into
            # each Gene Set per-organ block (see report.typ's gene-set
            # loop + `organ-charts` slots in genomics.js).  The charts
            # are still rendered server-side by genomics_viz.py, just
            # not given a standalone H2 section anymore.
        ],
    ),

    # Summary
    DocNode(
        id="summary",
        title="Summary",
        level=1,
        node_type="narrative",
        data_key="summary",
    ),

    # References
    DocNode(
        id="references",
        title="References",
        level=1,
        node_type="narrative",
        data_key="references",
    ),

    # ── Appendices ───────────────────────────────────────────────────
    DocNode(id="appendix-a", title="Appendix A. Internal Dose Assessment",
            level=1, node_type="appendix"),
    DocNode(id="appendix-b", title="Appendix B. Animal Identifiers",
            level=1, node_type="appendix"),
    DocNode(id="appendix-c", title="Appendix C. Transcriptomic Quality Control and Empirical False Discovery Rate",
            level=1, node_type="appendix"),
    DocNode(id="appendix-d", title="Appendix D. Benchmark Dose Model Recommendation and Selection Methodologies",
            level=1, node_type="appendix"),
    DocNode(id="appendix-e", title="Appendix E. Organ Weight Descriptions",
            level=1, node_type="appendix"),
    DocNode(id="appendix-f", title="Appendix F. Supplemental Data",
            level=1, node_type="appendix"),
]


# ---------------------------------------------------------------------------
# Tree utilities
# ---------------------------------------------------------------------------

def compute_table_numbers(tree: list[DocNode] | None = None) -> None:
    """
    Walk the tree in document order and assign table_number to each
    node with node_type == "table" or "bmd-summary".

    Table 1 is always the sample counts table (in Methods), which is
    handled separately.  The apical tables start at Table 2.

    Mutates nodes in place.
    """
    if tree is None:
        tree = DOCUMENT_TREE

    # Table 1 = sample counts (in Methods, not a tree node — it's inline).
    # Apical tables start at 2.
    counter = 2

    def _walk(nodes: list[DocNode]) -> None:
        nonlocal counter
        for node in nodes:
            if node.node_type == "table":
                node.table_number = counter
                counter += 1
            elif node.node_type == "bmd-summary":
                node.table_number = counter
                counter += 1
            if node.children:
                _walk(node.children)

    # Only count tables in the Results section
    for node in tree:
        if node.id == "results":
            _walk(node.children)
            break


def find_node(node_id: str, tree: list[DocNode] | None = None) -> DocNode | None:
    """
    Find a node by its ID anywhere in the tree.

    Returns the node, or None if not found.
    """
    if tree is None:
        tree = DOCUMENT_TREE

    for node in tree:
        if node.id == node_id:
            return node
        if node.children:
            found = find_node(node_id, node.children)
            if found:
                return found
    return None


def collect_data_keys(node: DocNode) -> set[str]:
    """
    Collect all data_key values from a node and its descendants.

    Used by the preview filter to determine which report data keys
    to keep when rendering a specific subtree.
    """
    # Genomics narrative keys (gene_set_narrative, gene_narrative) are
    # top-level report data keys, not sub-keys of unified_narratives.
    # We must add them directly so _apply_section_filter() keeps them.
    _TOP_LEVEL_NARRATIVE_KEYS = {"gene_set_narrative", "gene_narrative"}

    keys: set[str] = set()
    if node.data_key:
        keys.add(node.data_key)
    if node.narrative_key:
        if node.narrative_key in _TOP_LEVEL_NARRATIVE_KEYS:
            keys.add(node.narrative_key)
        else:
            keys.add("unified_narratives")
    for child in node.children:
        keys.update(collect_data_keys(child))
    return keys


def collect_platforms(node: DocNode) -> set[str]:
    """
    Collect all platform values from a node and its descendants.

    Used by the preview filter to sub-filter apical_sections
    to only the platforms in the requested subtree.
    """
    platforms: set[str] = set()
    if node.platform:
        platforms.add(node.platform)
        # Legacy compat: "Clinical Observations" also matches "Clinical"
        if node.platform == "Clinical Observations":
            platforms.add("Clinical")
    for child in node.children:
        platforms.update(collect_platforms(child))
    return platforms


def collect_methods_keys(node: DocNode) -> set[str]:
    """
    Collect all methods_key values from a node and its descendants.

    Used by the preview filter to restrict data.methods.sections to
    only the subsections belonging to the selected M&M node.  A parent
    node like "Clinical Examinations and Sample Collection" yields its
    own key plus all its children's keys.
    """
    keys: set[str] = set()
    if node.methods_key:
        keys.add(node.methods_key)
    for child in node.children:
        keys.update(collect_methods_keys(child))
    return keys


def is_leaf_table(node: DocNode) -> bool:
    """True if this node is a single table with no children."""
    return node.node_type == "table" and not node.children


def serialize_tree(tree: list[DocNode] | None = None) -> list[dict]:
    """
    Serialize the tree to JSON-friendly dicts for the Typst template
    and the frontend TOC sidebar.

    Each node becomes a dict with all fields + serialized children.
    """
    if tree is None:
        tree = DOCUMENT_TREE

    def _to_dict(node: DocNode) -> dict:
        d = {
            "id": node.id,
            "title": node.title,
            "level": node.level,
            "type": node.node_type,
        }
        if node.data_key:
            d["data_key"] = node.data_key
        if node.platform:
            d["platform"] = node.platform
        if node.narrative_key:
            d["narrative_key"] = node.narrative_key
        if node.table_number is not None:
            d["table_number"] = node.table_number
        if node.figure_number is not None:
            d["figure_number"] = node.figure_number
        if node.ready_key:
            d["ready_key"] = node.ready_key
        if node.children:
            d["children"] = [_to_dict(c) for c in node.children]
        return d

    return [_to_dict(n) for n in tree]


# ---------------------------------------------------------------------------
# Initialize table numbers on module load
# ---------------------------------------------------------------------------
compute_table_numbers()
