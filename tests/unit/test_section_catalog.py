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
    # The four singletons + three group narratives + two families + the six
    # authored/boilerplate front-matter content sections (display-only rows so the
    # workflow surfaces an unauthored About This Report as pending).
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
        "foreword",
        "about_report",
        "peer_review",
        "publication_details",
        "acknowledgments",
        "abstract",
    }


def test_front_matter_content_sections_are_display_only_front_region():
    specs = _by_key(DOCUMENT_TREE)
    for key in (
        "foreword", "about_report", "peer_review",
        "publication_details", "acknowledgments", "abstract",
    ):
        spec = specs[key]
        assert spec.kind == "authored", key
        assert spec.approvable is False, key   # the app is not an editor (ADR-0018)
        assert spec.instance_of is None, key
        assert spec.region == "front", key
        assert spec.store == "", key           # rendered from scaffold/overlay, no file


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


def test_front_matter_content_is_a_workflow_unit_but_generated_lists_are_not():
    # Front-matter CONTENT (foreword, abstract, …) IS a display-only workflow unit —
    # the workflow must surface an unauthored front-matter section as pending. But the
    # auto-generated LIST nodes (references, sample-counts) are produced entirely by a
    # tree walk and carry no workflow row.
    tree = [
        DocNode(id="foreword", title="Foreword", level=1,
                node_type="front-matter", data_key="foreword", region="front"),
        DocNode(id="abstract", title="Abstract", level=1,
                node_type="front-matter", data_key="abstract", region="front"),
        DocNode(id="references", title="References", level=1,
                node_type="narrative", data_key="references"),
        DocNode(id="table-sample-counts", title="Sample Counts", level=1,
                node_type="sample-counts-table", data_key="sample_counts"),
    ]
    specs = _by_key(tree)
    assert set(specs) == {"foreword", "abstract"}
    assert all(specs[k].region == "front" and not specs[k].approvable
               for k in specs)


def test_catalog_preserves_document_order():
    keys = [s.key for s in catalog_for_tree(DOCUMENT_TREE)]
    # background precedes methods precedes summary (front-to-back document order).
    assert keys.index("background") < keys.index("methods") < keys.index("summary")


# --- Write-side helpers (Phase 2, R2–R5) -------------------------------------
#
# These pin the catalog-derived write vocabulary against the literals the write
# routes used to hardcode, so the R2–R5 rewire is provably behavior-preserving.


def test_approvable_section_types_match_historical_literal():
    from workflow.section_catalog import approvable_section_types

    # The exact set web_routes.session_routes.api_session_approve hardcoded.
    assert approvable_section_types() == frozenset(
        {"background", "bm2", "methods", "bmd_summary", "genomics", "summary"}
    )


def test_singleton_section_files_match_historical_reads():
    from workflow.section_catalog import singleton_section_files

    # The four singleton files the session payload (R4) read by name.
    assert set(singleton_section_files()) == {
        "background.json",
        "methods.json",
        "bmd_summary.json",
        "summary.json",
    }


def test_resolve_section_key_matches_historical_branches():
    from workflow.section_catalog import resolve_section_key

    assert resolve_section_key({"section_type": "background"}) == ("background", None)
    assert resolve_section_key({"section_type": "methods"}) == ("methods", None)
    assert resolve_section_key({"section_type": "bmd_summary"}) == ("bmd_summary", None)
    assert resolve_section_key({"section_type": "summary"}) == ("summary", None)
    # bm2 needs a slug; genomics needs organ+sex (with the same normalization).
    assert resolve_section_key({"section_type": "bm2", "bm2_slug": "liver"}) == ("bm2_liver", None)
    assert resolve_section_key({"section_type": "bm2"})[0] is None
    assert resolve_section_key(
        {"section_type": "genomics", "organ": "Liver", "sex": "Male"}
    ) == ("genomics_liver_male", None)
    assert resolve_section_key({"section_type": "genomics", "organ": "liver"})[0] is None
    assert resolve_section_key({"section_type": "nope"})[0] is None
