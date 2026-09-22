"""
test_section_catalog.py — the tree-derived workflow catalog.

`workflow.section_catalog.catalog_for_tree` walks a DocNode forest and yields the
workflow view of it (one SectionSpec per singleton content section, per programmatic
group narrative, and per instance FAMILY). This pins:

  - the global template yields exactly the expected workflow units, including the
    three programmatic group narratives (`animal_condition`, `clinical_pathology`,
    `internal_dose`) that had NO workflow row before the catalog;
  - each spec's derived kind / approvable / unlock / instance_of;
  - instance families (`bm2`, `genomics`) are emitted ONCE (concrete instances stay
    disk-discovered);
  - removing a section from a tree drops it from the catalog (the seam that lets the
    per-session configurator change the workflow, not just rendering).
"""

from document_model.document_node import DocNode
from document_model.document_tree import DOCUMENT_TREE
from workflow.section_catalog import catalog_for_tree


def _by_key(tree):
    return {s.key: s for s in catalog_for_tree(tree)}


def test_global_tree_yields_expected_workflow_units():
    specs = _by_key(DOCUMENT_TREE)
    # The four singletons + three group narratives + two families.
    assert set(specs) == {
        "background",
        "methods",
        "summary",
        "bmd_summary",
        "animal_condition",
        "clinical_pathology",
        "internal_dose",
        "bm2",
        "genomics",
    }


def test_internal_dose_is_a_display_only_row():
    # The headline case: internal_dose exists in the template and renders, but is a
    # programmatic narrative with no approvable section_key. It must surface as a
    # non-approvable display row.
    spec = _by_key(DOCUMENT_TREE)["internal_dose"]
    assert spec.kind == "programmatic"
    assert spec.approvable is False
    assert spec.instance_of is None
    assert spec.unlock == ()


def test_singleton_kinds_and_approvability():
    specs = _by_key(DOCUMENT_TREE)
    assert specs["background"].kind == "llm"
    assert specs["background"].approvable is True
    assert specs["methods"].kind == "llm"
    assert specs["methods"].unlock == ("processed",)
    assert specs["summary"].kind == "llm"
    assert specs["summary"].unlock == ("background", "results")
    # bmd_summary is auto-derived (a deterministic reduction carrying an LLM
    # paragraph) but still approvable.
    assert specs["bmd_summary"].kind == "derived"
    assert specs["bmd_summary"].approvable is True


def test_families_collapse_and_declare_metadata():
    specs = _by_key(DOCUMENT_TREE)
    bm2 = specs["bm2"]
    assert bm2.instance_of == "bm2"
    assert bm2.kind == "programmatic"
    assert bm2.approvable is True
    assert bm2.store == "bm2_{slug}.json"
    # The six platform table nodes collapse into ONE family spec.
    assert len(bm2.node_ids) >= 2

    genomics = specs["genomics"]
    assert genomics.instance_of == "genomics"
    assert genomics.kind == "llm"
    assert genomics.approvable is False
    assert genomics.unlock == ("knowledge_base",)
    assert genomics.store == "genomics_{organ}_{sex}.json"


def test_group_narratives_have_no_standalone_store():
    specs = _by_key(DOCUMENT_TREE)
    for key in ("animal_condition", "clinical_pathology", "internal_dose"):
        assert specs[key].store == ""  # rendered from the process overlay


def test_removing_a_section_drops_it_from_the_catalog():
    # A per-session tree with the background node removed must not yield a background
    # spec — the seam that makes the configurator's structure edits reach the workflow.
    full = [
        DocNode(id="background", title="Background", level=1,
                node_type="narrative", data_key="background"),
        DocNode(id="summary", title="Summary", level=1,
                node_type="narrative", data_key="summary"),
    ]
    assert set(_by_key(full)) == {"background", "summary"}

    trimmed = [
        DocNode(id="summary", title="Summary", level=1,
                node_type="narrative", data_key="summary"),
    ]
    assert set(_by_key(trimmed)) == {"summary"}


def test_front_matter_and_generated_lists_are_not_workflow_units():
    # front-matter parts, abstract, references, and the sample-counts table carry
    # data_keys but are NOT authorable workflow sections — they must not appear.
    tree = [
        DocNode(id="foreword", title="Foreword", level=1,
                node_type="front-matter", data_key="foreword"),
        DocNode(id="abstract", title="Abstract", level=1,
                node_type="front-matter", data_key="abstract"),
        DocNode(id="references", title="References", level=1,
                node_type="narrative", data_key="references"),
        DocNode(id="table-sample-counts", title="Sample Counts", level=1,
                node_type="sample-counts-table", data_key="sample_counts"),
    ]
    assert _by_key(tree) == {}


def test_catalog_preserves_document_order():
    keys = [s.key for s in catalog_for_tree(DOCUMENT_TREE)]
    # background precedes methods precedes summary (front-to-back document order).
    assert keys.index("background") < keys.index("methods") < keys.index("summary")
