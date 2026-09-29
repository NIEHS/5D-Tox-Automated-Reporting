"""
Catalog ↔ tree consistency guard (ADR-0003 Phase 1, extended in Phase 2.5).

render_capabilities.COMPONENT_CATALOG declares, per node type, facts that make
claims about the real document structure: `headingless` (renders without a
heading?), `allowed_children` (what may nest under it?), and `requires` (which
bindings a node of this type must supply).  These tests pin those claims
against the hand-written DOCUMENT_TREE, so:

  1. the catalog can't silently drift from the tree it describes, and
  2. the level-derivation rule the instantiator relies on —
     `level = 0 if headingless else nesting-depth` — is proven to reproduce
     every level in today's tree.

This is the one place render_capabilities is deliberately coupled to
document_tree (the module itself imports nothing from the tree — see its
decoupling contract).
"""

from dataclasses import fields

from document_model.document_node import DocNode
from document_model.document_tree import DOCUMENT_TREE
from document_model.render_capabilities import (
    COMPONENT_CATALOG,
    CONTENT_KINDS,
    is_allowed_child,
    is_headingless,
    required_bindings_for,
)

# The DocNode binding fields a `requires` entry is allowed to name.
_DOCNODE_FIELDS = {f.name for f in fields(DocNode)}


def _walk_catalog(nodes, depth=1):
    """Yield (node, depth) for every node, top-level nodes at depth 1."""
    for node in nodes:
        yield node, depth
        yield from _walk_catalog(node.children, depth + 1)


def test_every_tree_node_type_is_in_the_catalog():
    """No node in the tree may use a type the catalog doesn't define."""
    for node, _ in _walk_catalog(DOCUMENT_TREE):
        assert node.node_type in COMPONENT_CATALOG, (
            f"node {node.id!r} uses type {node.node_type!r} absent from the catalog"
        )


def test_headingless_flag_matches_tree_levels():
    """A type is headingless iff its nodes carry level 0 in the tree."""
    for node, _ in _walk_catalog(DOCUMENT_TREE):
        assert is_headingless(node.node_type) == (node.level == 0), (
            f"headingless({node.node_type})={is_headingless(node.node_type)} but "
            f"node {node.id!r} has level {node.level}"
        )


def test_level_derivable_from_headingless_and_depth():
    """
    The instantiator derives level instead of authoring it.  Prove the rule
    reproduces every level in today's tree.
    """
    for node, depth in _walk_catalog(DOCUMENT_TREE):
        expected = 0 if is_headingless(node.node_type) else depth
        assert node.level == expected, (
            f"node {node.id!r}: level={node.level} but rule yields {expected} "
            f"(headingless={is_headingless(node.node_type)}, depth={depth})"
        )


def test_tree_nesting_obeys_allowed_children():
    """Every parent→child edge in the tree is permitted by the catalog."""
    for node, _ in _walk_catalog(DOCUMENT_TREE):
        for child in node.children:
            assert is_allowed_child(node.node_type, child.node_type), (
                f"{child.node_type!r} (node {child.id!r}) is not an allowed child "
                f"of {node.node_type!r} (node {node.id!r})"
            )


def test_content_kinds_use_known_vocabulary():
    """Every declared content kind is part of the closed vocabulary."""
    for node_type, spec in COMPONENT_CATALOG.items():
        for kind in spec.content_kinds:
            assert kind in CONTENT_KINDS, (
                f"{node_type!r} declares unknown content kind {kind!r}"
            )


def test_every_type_has_a_profile_role_and_real_bindings():
    """ADR-0025: each preset names a role from the BITS profile and a non-empty
    list of bindings from the closed vocabulary."""
    from document_model.render_capabilities import BINDINGS, ROLE_PROFILE
    for node_type, spec in COMPONENT_CATALOG.items():
        assert spec.role in ROLE_PROFILE, f"{node_type!r} has unknown role {spec.role!r}"
        assert spec.bindings, f"{node_type!r} lists no bindings"
        for b in spec.bindings:
            assert b in BINDINGS, f"{node_type!r} lists unknown binding {b!r}"


def test_role_profile_children_are_roles():
    """The containment grammar is written once, per role, in terms of roles."""
    from document_model.render_capabilities import ROLE_PROFILE
    for role, spec in ROLE_PROFILE.items():
        for child in spec.allowed_children:
            assert child in ROLE_PROFILE, f"role {role!r} allows unknown child role {child!r}"


def test_allowed_children_are_derived_from_roles():
    """allowed_children_for(type) is exactly the catalog types whose role the
    parent's role admits — nothing per-type."""
    from document_model.render_capabilities import ROLE_PROFILE, allowed_children_for
    for node_type, spec in COMPONENT_CATALOG.items():
        child_roles = ROLE_PROFILE[spec.role].allowed_children
        expected = tuple(n for n, c in COMPONENT_CATALOG.items() if c.role in child_roles)
        assert allowed_children_for(node_type) == expected
        for child in allowed_children_for(node_type):
            assert is_allowed_child(node_type, child)


# Presets whose `caption` belongs to the ONE table-wrap they contain rather than
# to the section itself (ADR-0025 §4: bmd-summary is a <sec> with a single
# table-wrap content item; the caption moves onto that item in migration phase 4).
_CAPTION_ON_INNER_TABLE = {"bmd-summary"}


def test_captionable_implies_table_wrap_or_fig_role():
    """Only BITS <table-wrap> / <fig> carry <caption>; a captionable section
    would be a grammar error (modulo the documented inner-table exception)."""
    for node_type, spec in COMPONENT_CATALOG.items():
        if spec.captionable and node_type not in _CAPTION_ON_INNER_TABLE:
            assert spec.role in ("table-wrap", "fig"), node_type


def test_emits_roles_resolve_in_the_shipped_vocabulary():
    """Every vocabulary role a catalog type `emits` must exist in the shipped
    ntp-report vocabulary — the crosswalk from node_type to paragraph-granular
    semantic roles must not name a role the vocabulary can't resolve (ADR-0010)."""
    import document_model.vocabulary as V

    vocab = V.load_vocabulary("ntp-report")
    for node_type, spec in COMPONENT_CATALOG.items():
        for role in spec.emits:
            assert vocab.get(role) is not None, (
                f"{node_type!r} emits role {role!r} absent from the ntp-report vocabulary"
            )


def test_front_matter_data_key_roles_resolve_in_the_vocabulary():
    """Every (heading, body) role a front-matter data_key derives must resolve in
    the shipped vocabulary — so an Abstract/Foreword/Peer-Review/... section styles
    its head+body by its own NTP role, not the generic pair (ADR-0010)."""
    import document_model.vocabulary as V
    import document_model.render_capabilities as rc

    vocab = V.load_vocabulary("ntp-report")
    for data_key, (head, body) in rc.FRONT_MATTER_ROLES_BY_DATA_KEY.items():
        assert vocab.get(head) is not None, f"{data_key!r} head role {head!r} unresolved"
        assert vocab.get(body) is not None, f"{data_key!r} body role {body!r} unresolved"


def test_front_matter_roles_for_falls_back_to_generic():
    import document_model.render_capabilities as rc
    assert rc.front_matter_roles_for("abstract") == ("abstract_head", "abstract")
    assert rc.front_matter_roles_for("unmapped") == ("section_heading", "body_para")
    assert rc.front_matter_roles_for(None) == ("section_heading", "body_para")


def test_required_bindings_name_real_docnode_fields():
    """A `requires` entry must name an actual DocNode binding field."""
    for node_type, spec in COMPONENT_CATALOG.items():
        for binding in spec.requires:
            assert binding in _DOCNODE_FIELDS, (
                f"{node_type!r} requires {binding!r}, which is not a DocNode field"
            )


def test_landscape_requested_merges_default_and_override():
    """
    Effective orientation = override if present, else template default, gated
    on the type capability (ADR-0003 Amendment 1).
    """
    from document_model.render_capabilities import landscape_requested
    # override wins over the template default, both directions
    assert landscape_requested("table", "n", {"n": "landscape"}, default="portrait") is True
    assert landscape_requested("table", "n", {"n": "portrait"}, default="landscape") is False
    # falls back to the template default when there is no override
    assert landscape_requested("table", "n", {}, default="landscape") is True
    assert landscape_requested("table", "n", {}, default=None) is False
    # capability gate: a non-orientable type is never landscape
    assert landscape_requested("narrative", "n", {"n": "landscape"}, default="landscape") is False


def test_required_bindings_satisfied_by_tree():
    """
    Every node in the real tree supplies the bindings its type requires — so
    the catalog never asserts a requirement the gold-standard tree violates.
    """
    for node, _ in _walk_catalog(DOCUMENT_TREE):
        for binding in required_bindings_for(node.node_type):
            value = getattr(node, binding)
            assert value not in (None, ""), (
                f"node {node.id!r} of type {node.node_type!r} requires {binding!r} "
                f"but it is {value!r}"
            )
