"""
render_capabilities.py — the document-semantic → rendering-semantic dictionary.

This module is the SINGLE coupling point between the document template
(document_tree.py's node types) and the interactive rendering layer (page
orientation, page breaks, inline text editing).  It answers one question:
"given a node of this semantic type, which rendering operations does it
support?"

Why this exists
---------------
User configuration of the rendered pages — which tables are landscape,
where page breaks go, which prose gets edited — must NOT care when the
document template evolves.  As long as a new section reuses an existing
document semantic (a `table`, a `narrative`, …), the rendering layer
already knows what to do with it: zero code change.  Only when a genuinely
new semantic appears that needs a rendering behaviour we've never built
does code change here.

Decoupling contract
--------------------
  - This module imports NOTHING from document_tree.  It is keyed by
    node_type *strings*, so the dependency points one way (consumers →
    here) and the template never depends on the rendering layer.
  - Consumers: latex_generator and html_generator gate their per-node
    behaviour on these capabilities; background_server annotates the
    serialized tree with them so the frontend reads capabilities instead
    of hardcoding its own copy of the mapping.
  - User choices (orientation/break/edit) are stored separately, keyed by
    node *id*; this module only says what's *possible* per node *type*.

How it fits the larger system
------------------------------
Template (document_tree, niehs.cls)  ← read by ─  Renderer  ─ reads → this
dictionary.  The interaction UI reads capabilities (via the annotated
tree) to decide what to offer, and writes the per-id overlay; the renderer
reads the overlay AND this dictionary to decide what to emit.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NodeCapabilities:
    """
    The rendering operations a document-semantic type supports.

    Each flag answers one yes/no question about what the user may do to a
    node of this type in the interactive preview:

        orientable — its page can be flipped between portrait and landscape
                     (wide data tables, charts, figures).
        breakable  — a user-inserted page break may be placed before/after
                     it (most content; not the fixed front pages).
        editable   — its textual content may be edited in a popup (prose
                     sections; NOT data-driven tables, which come from the
                     integrated dataset).

    Defaults are all False so an unknown/unmapped type is treated as
    "no operations" — the safe, do-nothing fallback.
    """
    orientable: bool = False
    breakable: bool = False
    editable: bool = False

    def to_dict(self) -> dict:
        """Plain-dict form for JSON serialization to the frontend."""
        return {
            "orientable": self.orientable,
            "breakable": self.breakable,
            "editable": self.editable,
        }


# ---------------------------------------------------------------------------
# Constants — the dictionary
# ---------------------------------------------------------------------------

# document semantic (node_type) → rendering semantics (capabilities).
# This is the one place that grows when the template adds a node type.
# Adding a type that reuses an existing capability profile is a one-line
# edit here; only a brand-new capability requires renderer/UI code.
CAPABILITIES_BY_TYPE: dict[str, NodeCapabilities] = {
    # Fixed front pages — auto-laid-out, nothing the user configures.
    "cover":            NodeCapabilities(),
    "title-page":       NodeCapabilities(),
    # Auto-generated list of tables — no user text, but it can start a new
    # page.
    "tables-list":      NodeCapabilities(breakable=True),
    # A heading with no own content (its children carry it) — only
    # meaningful as a place to start a new page.
    "heading-only":     NodeCapabilities(breakable=True),
    # Prose sections — editable text, can break to a new page; never
    # landscape (running body text doesn't rotate).
    "front-matter":     NodeCapabilities(breakable=True, editable=True),
    "narrative":        NodeCapabilities(breakable=True, editable=True),
    "appendix":         NodeCapabilities(breakable=True, editable=True),
    # Prose + child tables — the prose is editable and the section can
    # break; the wide tables are separate child `table` nodes, each
    # orientable on its own (so the prose stays portrait while a table
    # flips landscape).
    "narrative+tables": NodeCapabilities(breakable=True, editable=True),
    # Data tables / charts / figures — orientable and breakable; the data
    # comes from the integrated dataset, so they are not text-editable.
    "table":            NodeCapabilities(orientable=True, breakable=True),
    "incidence-table":  NodeCapabilities(orientable=True, breakable=True),
    "bmd-summary":      NodeCapabilities(orientable=True, breakable=True),
    "genomics-section": NodeCapabilities(orientable=True, breakable=True),
}

# Fallback for a node_type not in the dictionary: no capabilities.  This is
# what lets the template add a type without breaking anything — the new
# type is simply inert until someone gives it an entry above.
_DEFAULT_CAPABILITIES = NodeCapabilities()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def capabilities_for(node_type: str) -> NodeCapabilities:
    """
    Return the capabilities for a document-semantic type, or the safe
    all-False default for an unrecognized type.
    """
    return CAPABILITIES_BY_TYPE.get(node_type, _DEFAULT_CAPABILITIES)


def annotate_capabilities(nodes: list[dict]) -> list[dict]:
    """
    Walk a *serialized* tree (the list-of-dicts from serialize_tree) and add
    a "capabilities" dict to every node, derived from its "type".  Mutates
    in place and also returns the list for convenience.

    background_server calls this once on the serialized tree so the injected
    window.__DOCUMENT_TREE__ and the /api/document-tree response both carry
    capabilities — the frontend then reads node.capabilities directly
    instead of duplicating the type→capability mapping in JavaScript.
    """
    for node in nodes:
        node["capabilities"] = capabilities_for(node.get("type", "")).to_dict()
        children = node.get("children")
        if children:
            annotate_capabilities(children)
    return nodes
