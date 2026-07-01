"""
document_tree.py — Declarative NIEHS report document structure.

This module defines the complete structure of an NIEHS 5-day biological
potency report as a tree of nodes.  It is the SINGLE SOURCE OF TRUTH for:

  - Heading hierarchy (level 1, 2, 3)
  - Section ordering
  - Table numbering (auto-assigned by tree-walk position)
  - Figure numbering (auto-assigned by tree-walk position)
  - Navigation panel (a UI projection of this tree, distinct from the ToC)
  - Preview filtering (given a node ID, find its subtree)
  - Renderers (the HTML preview and the LaTeX/Overleaf export both walk this tree)

Users can override narrative content; everything structural is determined
by position in this tree.

The tree matches the NIEHS Report 10 (NBK589955) Table of Contents exactly.
"""

from __future__ import annotations

from document_node import DocNode  # node shape; re-exported so existing
                                   # `from document_tree import DocNode` keeps working
from document_template import build_tree


# The node SHAPE is defined in document_node.py (DocNode, re-exported above);
# the registry of node TYPES and their capabilities / containment / required
# bindings lives in render_capabilities.COMPONENT_CATALOG.


# ---------------------------------------------------------------------------
# The complete NIEHS report structure
# ---------------------------------------------------------------------------
# Matches NIEHS Report 10 (NBK589955) Table of Contents verbatim.
# Table numbers are auto-assigned by compute_table_numbers() — the
# position in this tree determines the number.

# Built by instantiating the data-driven template
# (templates/niehs-5day-report.yaml) against the component catalog — see
# ADR-0003.  This replaces the former hand-written literal; the golden-tree
# test (tests/unit/test_document_template.py) proves the instantiated tree is
# byte-identical to that original literal.
# NOTE: this reads and parses templates/niehs-5day-report.yaml at IMPORT time.
# A deliberate fail-fast — a missing/malformed template breaks import loudly
# rather than yielding a half-built report — but importing document_tree does
# therefore require the template file to be present and valid.
#
# The active template name — single source for both the document STRUCTURE
# (build_tree below) and the chart config (chart_style/chart_types) loaded by
# the chart pipeline, so structure and chart styling always come from one file.
ACTIVE_TEMPLATE = "niehs-5day-report"
DOCUMENT_TREE: list[DocNode] = build_tree(ACTIVE_TEMPLATE)


# ---------------------------------------------------------------------------
# Front matter vs body
# ---------------------------------------------------------------------------
def first_body_node_id(tree: list[DocNode] | None = None) -> str | None:
    """
    Return the id of the first top-level node whose region == "body" — the
    point where page numbering switches from roman to arabic.  Per NIEHS
    Report 10, front matter is roman-numbered and the body restarts at
    arabic 1 (Background = page 1).  Both renderers (latex_generator,
    html_generator) consume this so the switch lands at the same structural
    point — the boundary lives with the tree, not duplicated in each renderer.

    Pre-ADR-0004-d this looked at node.node_type membership in a frozen
    FRONT_MATTER_NODE_TYPES set; now it reads node.region, which the
    instantiator inherits from the template's region containers.  Same
    result for our template — first body node is "background" — but the
    boundary is now data-driven rather than type-coded.

    Returns None if no top-level node carries region == "body" (a degenerate
    tree, e.g. a bare unit-test scaffold without region containers).
    """
    if tree is None:
        tree = DOCUMENT_TREE
    for node in tree:
        if node.region == "body":
            return node.id
    return None


# ---------------------------------------------------------------------------
# Tree utilities
# ---------------------------------------------------------------------------

def walk_tree(nodes: list[DocNode], visit) -> None:
    """
    Pre-order depth-first walk of a DocNode forest.

    Calls ``visit(node)`` on every node in document order — a node is visited
    BEFORE its children, and siblings are visited in list order.  This is the
    one canonical traversal of the document tree (ADR-0006): the renderers,
    the data gatherer, and the export marshaller each used to re-derive "look
    at this node, then recurse into ``node.children``" by hand, which let the
    traversals drift apart.  Centralising it here makes the tree
    (Architectural Invariant #2) own its own iteration order.

    The walk is intentionally side-effect-only: it returns nothing and does
    not collect results.  Callers that need to accumulate output (e.g. a
    renderer building a list of markup chunks) close over their own
    accumulator inside ``visit`` and append to it — see html_generator._walk_html
    and latex_generator._walk_latex.  Keeping accumulation out of the primitive is
    what lets one walk serve callers that produce wildly different outputs.

    Args:
        nodes: the forest to walk — a list of top-level DocNodes.  Pass a
            single node as a one-element list (``walk_tree([node], visit)``)
            to walk one subtree.
        visit: a callable invoked once per node as ``visit(node)``.  Its
            return value is ignored; any output it produces is its own
            responsibility (typically by mutating a closed-over accumulator).

    Returns:
        None.  This primitive exists for its traversal order, not a value.
    """
    for node in nodes:
        # Pre-order: the node itself is handled before we descend.  Renderers
        # rely on this so a section's heading/intro chunk lands ahead of its
        # children's chunks, preserving document order in the flat output.
        visit(node)
        walk_tree(node.children, visit)


# Node types that render through niehstable, emit \label{tab:<id>}, and so
# must receive a positional table_number.  This is the single producer-side
# source of truth; cross_references._TABLE_TYPES is the consumer-side mirror and
# must stay equal to it (see the assertion in cross_references.py).
NUMBERED_TABLE_TYPES = frozenset(
    {"sample-counts-table", "table", "incidence-table", "bmd-summary"}
)


def compute_table_numbers(tree: list[DocNode] | None = None) -> None:
    """
    Walk the whole tree in document order and assign table_number to every
    node whose node_type is in NUMBERED_TABLE_TYPES.

    Numbering is fully positional and starts at Table 1: the first numbered
    node in document order is the Methods sample-counts table (a
    `sample-counts-table` node under Transcriptomics), so it earns Table 1 by
    position; the Results tables follow (2, 3, ...).  Numbering is not scoped to
    a section id, so re-parenting or renaming a section can't silently drop a
    number.

    Mutates nodes in place.
    """
    if tree is None:
        tree = DOCUMENT_TREE

    # Positional from 1: the sample-counts-table node in Methods is the first
    # numbered node in document order, so it becomes Table 1; Results tables
    # follow.  (Previously Table 1 was reserved for a DOCX-only inline table
    # that no tree node carried — that hack is gone now the table is a node.)
    counter = 1

    def visit(node: DocNode) -> None:
        nonlocal counter
        if node.node_type in NUMBERED_TABLE_TYPES:
            node.table_number = counter
            counter += 1

    walk_tree(tree, visit)


# The two genomics-section nodes carry their role in `narrative_key`; the flat
# data["genomics_sections"] entries carry the SAME role in `type`.  Mapping one
# to the other lets us number the data-driven genomics tables in the exact order
# the renderers emit them, without importing render_common (which would cycle).
_GENOMICS_NARRATIVE_TO_TYPE = {
    "gene_set_narrative": "gene_set",
    "gene_narrative": "gene",
}


def assign_genomics_table_numbers(
    tree: list[DocNode] | None,
    genomics_sections: list[dict] | None,
) -> None:
    """
    Assign positional ``table_number`` to each genomics-section entry, continuing
    the sequence the tree's numbered tables established (Table 8 → 9, 10, ...).

    Genomics tables are DATA-DRIVEN, not tree nodes: the tree holds two
    ``genomics-section`` nodes (gene-sets, gene-bmd) that each expand at render
    time into one table per matching entry in ``genomics_sections``.  So
    compute_table_numbers() — a pure tree walk — can't see them; this is the
    data-side companion that numbers them, called by BOTH render paths after
    ``data["genomics_sections"]`` is finalized (single source of truth: same
    function, same inputs → identical numbers on both surfaces).

    Ordering is load-bearing: the numbers MUST match the printed order.  The
    renderers walk the TREE — the gene-sets node emits ALL ``type=="gene_set"``
    entries first, then gene-bmd emits ALL ``type=="gene"`` — NOT the interleaved
    order of the raw list.  So we walk the genomics-section nodes in tree order,
    and for each, number its role's entries in list order.  Deriving the role
    sequence from the tree (via each node's ``narrative_key``) keeps this
    template-driven rather than hardcoding ("gene_set", "gene").

    Mutates each entry dict in place (sets ``entry["table_number"]``); entries
    whose role has no genomics-section node are left unnumbered.  Idempotent.
    """
    if tree is None:
        tree = DOCUMENT_TREE
    if not genomics_sections:
        return

    # Continue from the highest number the tree already assigned (Table 8 here).
    tree_max = 1
    def _max(node: DocNode) -> None:
        nonlocal tree_max
        if node.table_number is not None:
            tree_max = max(tree_max, node.table_number)
    walk_tree(tree, _max)

    # Role sequence in tree order, from the genomics-section nodes themselves.
    role_order: list[str] = []
    def _roles(node: DocNode) -> None:
        if node.node_type == "genomics-section":
            role = _GENOMICS_NARRATIVE_TO_TYPE.get(
                getattr(node, "narrative_key", None) or ""
            )
            if role and role not in role_order:
                role_order.append(role)
    walk_tree(tree, _roles)

    counter = tree_max + 1
    for role in role_order:
        for entry in genomics_sections:
            if entry.get("type") == role:
                entry["table_number"] = counter
                counter += 1


def build_node_index(tree: list[DocNode]) -> dict[str, DocNode]:
    """
    Build an ``{id: node}`` lookup over a forest, enforcing id uniqueness.

    Walks the tree in document order and raises ValueError on the first
    duplicate id.  Node ids must be globally unique: find_node — and every
    other id-keyed lookup (xref-token resolution, readiness checks, the
    renderers' section filter) — keys on id alone, so a duplicate would
    silently shadow, with the first pre-order match winning for all callers
    and no warning.  Failing here, at build time, turns that latent template
    authoring bug into a loud error, consistent with this module's fail-fast
    template loading (see the import-time note on DOCUMENT_TREE).
    """
    index: dict[str, DocNode] = {}

    def visit(node: DocNode) -> None:
        if node.id in index:
            raise ValueError(
                f"duplicate node id {node.id!r} in document tree — node ids "
                "must be unique (find_node and every id-keyed lookup would "
                "otherwise silently shadow to the first pre-order match)"
            )
        index[node.id] = node

    walk_tree(tree, visit)
    return index


def find_node(node_id: str, tree: list[DocNode] | None = None) -> DocNode | None:
    """
    Find a node by its ID anywhere in the tree.

    Returns the node, or None if not found.

    For the default tree (DOCUMENT_TREE) this is an O(1) lookup against a
    prebuilt id->node index (_DOCUMENT_INDEX), not a linear scan.  The index is
    built once at import and never goes stale: the tree's shape is frozen after
    build_tree() — nothing in prod mutates node.children — and
    compute_table_numbers() only sets table_number, not ids.  When an explicit
    non-default ``tree`` is passed (unit tests, or any future sub-forest), fall
    back to a linear pre-order walk, since those callers don't share the cache.
    """
    if tree is None:
        return _DOCUMENT_INDEX.get(node_id)

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
    Serialize the tree to JSON-friendly dicts for the renderers
    and the frontend navigation panel.

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
        if node.orientation:
            d["orientation"] = node.orientation
        if node.caption:
            d["caption"] = node.caption
        # ADR-0004 amendment d: every node carries its book region.  Only
        # serialize it when set (descendants of region containers; bare
        # test-scaffold nodes still serialize without it) so the JSON stays
        # noise-free for the legacy unit-test cases.
        if node.region:
            d["region"] = node.region
        if node.children:
            d["children"] = [_to_dict(c) for c in node.children]
        return d

    return [_to_dict(n) for n in tree]


# ---------------------------------------------------------------------------
# Initialize table numbers and the id->node index on module load
# ---------------------------------------------------------------------------
compute_table_numbers()

# O(1) id->node lookup for the default tree, used by find_node().  Built once
# here (eagerly, so a duplicate id fails import like a malformed template) and
# never invalidated: prod never mutates the tree's shape after build_tree(), so
# the index can't go stale.  Tests passing an explicit sub-forest bypass this
# and walk linearly instead.
_DOCUMENT_INDEX: dict[str, DocNode] = build_node_index(DOCUMENT_TREE)
