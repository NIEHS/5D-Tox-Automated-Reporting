"""
ADR-0025 acceptance tests: the document grammar is a BITS profile with an
orthogonal `binding` axis.

Two INSTANCES must validate through the real instantiator and stay green:
the shipped template (byte-for-byte compatible through the presets) and the
reference report's faithful structure (docs/reference/…faithful.yaml, derived
from the NIEHS-10 docx).  The difference between them is a difference in
bindings, never in what the grammar can express.  The remaining tests pin the
resolution rules: type-or-(role, binding), role assertion, binding choice, the
file-only bindings, and the tree carrying both axes.
"""

from pathlib import Path

import pytest
import yaml

from document_model.document_config import _tree_from_document_list, load_template, ACTIVE_TEMPLATE
from document_model.document_template import instantiate
from document_model.document_tree import walk_tree
from document_model.render_capabilities import (
    BINDINGS, COMPONENT_CATALOG, ROLE_PROFILE, preset_for, role_for,
)

REPO = Path(__file__).resolve().parents[2]
REFERENCE_YAML = REPO / "docs" / "reference" / "niehs-10-structure.faithful.yaml"


def _nodes(tree):
    out = []
    walk_tree(tree, out.append)
    return out


# ---------------------------------------------------------------------------
# The two acceptance instances
# ---------------------------------------------------------------------------

def test_shipped_template_is_an_instance_of_the_profile():
    tree = _tree_from_document_list(load_template(ACTIVE_TEMPLATE))
    for node in _nodes(tree):
        assert node.role in ROLE_PROFILE, node.id
        assert node.binding in BINDINGS, node.id


def test_reference_report_is_an_instance_of_the_profile():
    """The NIEHS-10 structure (nested front matter, structured appendices with
    sub-sections two deep, data + authored tables, figures, per-appendix lists,
    55 supplementary files) validates unchanged."""
    document = yaml.safe_load(REFERENCE_YAML.read_text(encoding="utf-8"))["document"]
    tree = _tree_from_document_list(document)
    nodes = _nodes(tree)
    types = {n.node_type for n in nodes}
    # The constructs that used to be violations are all present.
    assert {"appendix", "figure", "data-table", "authored-table", "figures-list",
            "supplementary-material", "freeform-block"} <= types
    about = next(n for n in nodes if n.id == "about-this-report")
    assert [c.title for c in about.children] == ["Authors", "Contributors"]
    c22 = next(n for n in nodes if n.id == "c-2-2")
    assert c22.level == 3 and {c.node_type for c in c22.children} == {"figure", "data-table"}
    assert sum(1 for n in nodes if n.node_type == "supplementary-material") == 55
    # Honest bindings.
    by_id = {n.id: n for n in nodes}
    assert by_id["abstract"].binding == "llm"
    assert by_id["references"].binding == "derived"
    assert by_id["table-d-1"].binding == "authored"
    assert by_id["table-b-1"].binding == "programmatic"
    assert by_id["appendix-a"].binding == "container" and by_id["appendix-a"].role == "app"


# ---------------------------------------------------------------------------
# Resolution rules
# ---------------------------------------------------------------------------

def test_tree_carries_role_and_default_binding():
    tree = instantiate([{"id": "s", "type": "heading-only", "title": "S", "children": [
        {"id": "t", "type": "table", "title": "T", "platform": "Body Weight"}]}])
    assert (tree[0].role, tree[0].binding) == ("sec", "container")
    assert (tree[0].children[0].role, tree[0].children[0].binding) == ("table-wrap", "programmatic")


def test_explicit_role_and_binding_resolve_to_a_preset_without_type():
    tree = instantiate([{"id": "a", "role": "app", "binding": "container", "title": "A"}])
    assert tree[0].node_type == "appendix"
    assert preset_for("table-wrap", "authored") == "authored-table"


def test_explicit_pair_without_a_preset_is_rejected():
    with pytest.raises(ValueError, match="no catalog preset renders role 'toc' with binding 'llm'"):
        instantiate([{"id": "x", "role": "toc", "binding": "llm", "title": "X"}])


def test_role_must_match_the_preset():
    with pytest.raises(ValueError, match="role 'fig' does not match type 'table'"):
        instantiate([{"id": "t", "type": "table", "role": "fig", "title": "T", "platform": "P"}])


def test_binding_must_be_one_the_preset_admits():
    with pytest.raises(ValueError, match="binding 'llm' is not one type 'table' admits"):
        instantiate([{"id": "t", "type": "table", "binding": "llm", "title": "T", "platform": "P"}])


def test_binding_choice_is_kept_on_the_node():
    tree = instantiate([{"id": "r", "type": "narrative", "title": "R", "data_key": "references",
                         "binding": "derived"}])
    assert tree[0].binding == "derived"


def test_containment_is_by_role_not_type():
    # A figure inside a freeform (authored) section inside an appendix: legal
    # because sec → fig and app → sec, with no per-type rule anywhere.
    tree = instantiate([{"id": "a", "type": "appendix", "title": "A", "children": [
        {"id": "s", "type": "freeform-block", "title": "S", "content": {"html": "<p>x</p>"},
         "children": [{"id": "f", "type": "figure", "title": "F", "subtype": "chart", "data_key": "k"}]}]}])
    assert tree[0].children[0].children[0].role == "fig"
    assert role_for("appendix") == "app"


def test_supplementary_material_requires_a_file_and_nothing_else():
    ok = instantiate([{"id": "s", "type": "supplementary-material", "title": "S", "content_file": "a.xlsx"}])
    assert ok[0].binding == "authored" and ok[0].level == 0
    with pytest.raises(ValueError, match="requires `content_file`"):
        instantiate([{"id": "s", "type": "supplementary-material", "title": "S"}])
    with pytest.raises(ValueError, match="only `content_file` applies"):
        instantiate([{"id": "s", "type": "supplementary-material", "title": "S",
                      "content_file": "a.xlsx", "representation": "html"}])


def test_authored_figure_subtypes_name_their_image_file():
    ok = instantiate([{"id": "f", "type": "figure", "title": "F", "subtype": "diagram",
                       "content_file": "reference/flow.png"}])
    assert ok[0].content_file == "reference/flow.png"
    with pytest.raises(ValueError, match="requires `content_file`"):
        instantiate([{"id": "f", "type": "figure", "title": "F", "subtype": "diagram"}])
    with pytest.raises(ValueError, match="figure subtype 'sketch' is not one of"):
        instantiate([{"id": "f", "type": "figure", "title": "F", "subtype": "sketch"}])


def test_every_preset_pair_round_trips_through_preset_for():
    """The canonical preset for (role, default binding) is a type with that
    role admitting that binding — the reverse map is total over the catalog."""
    for name, comp in COMPONENT_CATALOG.items():
        canonical = preset_for(comp.role, comp.bindings[0])
        assert canonical is not None
        c = COMPONENT_CATALOG[canonical]
        assert c.role == comp.role and comp.bindings[0] in c.bindings
