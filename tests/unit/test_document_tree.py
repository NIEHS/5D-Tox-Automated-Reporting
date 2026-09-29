"""
test_document_tree.py — Unit tests for the declarative document structure tree.

Verifies that:
  - The tree has the expected top-level sections
  - compute_table_numbers assigns sequential numbers
  - find_node locates nodes by ID
  - serialize_tree produces JSON-friendly dicts with correct keys
  - collect_data_keys and collect_platforms gather correct values
"""

import pytest

from document_model.document_tree import (
    DOCUMENT_TREE,
    DocNode,
    compute_appendix_letters,
    compute_table_numbers,
    find_node,
    first_body_node_id,
    collect_data_keys,
    collect_platforms,
    is_leaf_table,
    serialize_tree,
)


class TestFrontMatterBoundary:
    """The roman->arabic page-numbering boundary lives with the tree."""

    def test_first_body_node_is_background(self):
        # Front matter (cover...abstract) is roman; Background begins the
        # arabic-numbered body — see NIEHS Report 10 (Background = page 1).
        assert first_body_node_id() == "background"

    def test_regions_are_contiguous_runs(self):
        # The switch logic assumes all front-matter nodes come before any
        # body node, and back matter comes after.  Guard that invariant so
        # a future reordering of the template's region containers can't
        # silently interleave them.  (Bare unit-test scaffolds have
        # region=None and shouldn't appear in DOCUMENT_TREE — this is
        # checked separately.)
        regions = [n.region for n in DOCUMENT_TREE]
        assert all(r in ("front", "body", "back") for r in regions), regions
        # The sequence of regions must be a strict front* → body* → back* run.
        order = {"front": 0, "body": 1, "back": 2}
        ranks = [order[r] for r in regions]
        assert ranks == sorted(ranks), (
            f"regions are out of order: {regions}"
        )

    def test_abstract_is_front_matter_background_is_body(self):
        assert find_node("abstract").region == "front"
        assert find_node("background").region == "body"

    def test_region_inherits_to_descendants(self):
        # Children of a region container share the region of the container —
        # nested table nodes under Results are body; appendix children are back.
        assert find_node("table-body-weight").region == "body"
        # mm-stat-apical lives deeply nested under Methods → Data Analysis.
        assert find_node("mm-stat-apical").region == "body"


class TestDocumentTreeStructure:
    """Verify the static DOCUMENT_TREE has expected top-level sections."""

    def test_tree_is_non_empty(self):
        assert len(DOCUMENT_TREE) > 0

    def test_has_title_page_and_no_cover(self):
        # No cover node — the reference DOCX opens directly on the title page.
        ids = [n.id for n in DOCUMENT_TREE]
        assert "title-page" in ids
        assert "cover" not in ids

    def test_has_background(self):
        ids = [n.id for n in DOCUMENT_TREE]
        assert "background" in ids

    def test_has_methods(self):
        ids = [n.id for n in DOCUMENT_TREE]
        assert "methods" in ids

    def test_has_results(self):
        ids = [n.id for n in DOCUMENT_TREE]
        assert "results" in ids

    def test_has_summary(self):
        ids = [n.id for n in DOCUMENT_TREE]
        assert "summary" in ids

    def test_results_has_children(self):
        results = find_node("results")
        assert results is not None
        assert len(results.children) > 0


class TestComputeTableNumbers:
    """Verify table numbers are auto-assigned in document order."""

    def test_tables_get_sequential_numbers(self):
        """Table nodes under Results should get sequential numbers starting at 2."""
        # Make a fresh copy so we don't mutate the global tree
        import copy
        tree = copy.deepcopy(DOCUMENT_TREE)
        compute_table_numbers(tree)

        # Find all table nodes under results
        results = None
        for node in tree:
            if node.id == "results":
                results = node
                break
        assert results is not None

        table_numbers = []

        def _collect_results_table_numbers(nodes):
            for n in nodes:
                if n.table_number is not None:
                    table_numbers.append(n.table_number)
                if n.children:
                    _collect_results_table_numbers(n.children)

        _collect_results_table_numbers(results.children)
        assert len(table_numbers) > 0
        # The first RESULTS table is Table 2: Table 1 is the Methods
        # sample-counts-table node, which precedes Results in document order.
        assert table_numbers[0] == 2
        # Should be sequential with no gaps
        for i in range(1, len(table_numbers)):
            assert table_numbers[i] == table_numbers[i - 1] + 1

    def test_sample_counts_table_is_table_one(self):
        """The Methods sample-counts-table node is Table 1 (first numbered node
        in document order), and the first Results table follows at 2 — so
        numbering is fully positional with no reserved-slot hack."""
        import copy
        tree = copy.deepcopy(DOCUMENT_TREE)
        compute_table_numbers(tree)

        sc = find_node("table-sample-counts", tree)
        assert sc is not None and sc.node_type == "sample-counts-table"
        assert sc.table_number == 1
        assert find_node("table-body-weight", tree).table_number == 2

    def test_non_table_nodes_have_no_number(self):
        """Narrative and heading-only nodes should not get table numbers."""
        import copy
        tree = copy.deepcopy(DOCUMENT_TREE)
        compute_table_numbers(tree)

        bg = None
        for node in tree:
            if node.id == "background":
                bg = node
                break
        assert bg is not None
        assert bg.table_number is None

    def test_incidence_table_is_numbered_in_sequence(self):
        """An incidence-table is a numbered table type (it renders through
        niehstable and is xref-able), so it must receive a table_number and not
        leave a gap in the sequence.

        Regression: compute_table_numbers used to allowlist only "table" and
        "bmd-summary", so an incidence-table got None and the surrounding
        numbers jumped, dropping it from the List of Tables and rendering it
        without a "Table N." caption.  Built on a synthetic tree (the active
        niehs-5day template no longer instances an incidence-table node) so the
        numbering contract is pinned independently of the template's node set.
        This synthetic tree has no sample-counts-table node, so numbering starts
        at 1 here; on the real tree Table 1 is the Methods sample-counts node.
        """
        from document_model.document_tree import NUMBERED_TABLE_TYPES, walk_tree

        tree = [
            DocNode(
                id="results", title="Results", level=1, node_type="heading-only",
                children=[
                    DocNode(id="t-bw", title="Body Weights", level=2,
                            node_type="table", platform="Body Weight"),
                    DocNode(id="t-ow", title="Organ Weights", level=2,
                            node_type="table", platform="Organ Weight"),
                    DocNode(id="t-incidence", title="Clinical Observations", level=2,
                            node_type="incidence-table",
                            platform="Clinical Observations"),
                    DocNode(id="t-cc", title="Clinical Chemistry", level=2,
                            node_type="table", platform="Clinical Chemistry"),
                ],
            )
        ]
        compute_table_numbers(tree)

        incidence = find_node("t-incidence", tree)
        assert incidence is not None
        assert incidence.node_type == "incidence-table"
        # It sits third among the numbered tables (t-bw=1, t-ow=2 on this
        # synthetic sample-counts-free tree), so it must be Table 3 — present and
        # gap-free, not None.
        assert incidence.table_number == 3

        # Whole-tree sweep: every numbered-table node has a number and the full
        # run is contiguous starting at 1, with no gaps around the incidence row.
        numbers: list[int] = []

        def _collect(node):
            if node.node_type in NUMBERED_TABLE_TYPES:
                assert node.table_number is not None, (
                    f"{node.id} ({node.node_type}) is a numbered table type but "
                    "got no table_number"
                )
                numbers.append(node.table_number)

        walk_tree(tree, _collect)
        assert numbers == list(range(1, 1 + len(numbers)))


class TestComputeAppendixLetters:
    """Verify appendix letters are auto-assigned A, B, C… in document order."""

    def test_appendices_get_sequential_letters(self):
        import copy
        tree = copy.deepcopy(DOCUMENT_TREE)
        compute_appendix_letters(tree)
        # Appendix a–f in order → A–F.
        expected = {
            "appendix-a": "A", "appendix-b": "B", "appendix-c": "C",
            "appendix-d": "D", "appendix-e": "E", "appendix-f": "F",
        }
        for node_id, letter in expected.items():
            assert find_node(node_id, tree).appendix_letter == letter

    def test_non_appendix_nodes_have_no_letter(self):
        import copy
        tree = copy.deepcopy(DOCUMENT_TREE)
        compute_appendix_letters(tree)
        assert find_node("background", tree).appendix_letter is None
        assert find_node("results", tree).appendix_letter is None

    def test_folded_into_compute_table_numbers(self):
        """compute_table_numbers assigns appendix letters too (folded call site),
        so every caller gets them without a separate call."""
        import copy
        tree = copy.deepcopy(DOCUMENT_TREE)
        compute_table_numbers(tree)
        assert find_node("appendix-a", tree).appendix_letter == "A"
        assert find_node("appendix-f", tree).appendix_letter == "F"


class TestFindNode:
    """Verify find_node locates nodes at any depth."""

    def test_find_top_level(self):
        node = find_node("background")
        assert node is not None
        assert node.title == "Background"

    def test_find_nested_node(self):
        # table-body-weight is nested under results > animal-condition
        node = find_node("table-body-weight")
        assert node is not None
        assert node.platform == "Body Weight"

    def test_find_deeply_nested(self):
        # mm-stat-apical is under methods > mm-data-analysis
        node = find_node("mm-stat-apical")
        assert node is not None

    def test_find_nonexistent_returns_none(self):
        assert find_node("nonexistent-id") is None


class TestNodeIndex:
    """Verify the id->node index backs find_node and enforces uniqueness."""

    def test_duplicate_id_at_top_level_raises(self):
        # Two sibling nodes sharing an id must be rejected at build time:
        # without the index, find_node would silently return the first one for
        # every caller (pre-order shadowing) with no warning.
        from document_model.document_tree import build_node_index

        dup = [
            DocNode(id="dup", title="First"),
            DocNode(id="dup", title="Second"),
        ]
        with pytest.raises(ValueError, match="duplicate node id 'dup'"):
            build_node_index(dup)

    def test_duplicate_id_nested_raises(self):
        # A duplicate hidden one level down must also be caught — the walk is
        # whole-tree, not just top-level siblings.
        from document_model.document_tree import build_node_index

        nested = [
            DocNode(
                id="parent",
                title="Parent",
                children=[DocNode(id="parent", title="Shadow child")],
            ),
        ]
        with pytest.raises(ValueError, match="duplicate node id 'parent'"):
            build_node_index(nested)

    def test_unique_tree_builds_index_of_every_node(self):
        from document_model.document_tree import build_node_index, walk_tree

        tree = [
            DocNode(
                id="root",
                title="Root",
                children=[
                    DocNode(id="a", title="A"),
                    DocNode(id="b", title="B"),
                ],
            ),
        ]
        index = build_node_index(tree)
        ids = []
        walk_tree(tree, lambda n: ids.append(n.id))
        assert set(index) == set(ids)
        # The index holds the live node objects, not copies.
        assert index["a"].title == "A"

    def test_document_tree_has_no_duplicate_ids(self):
        # The live default tree must satisfy the uniqueness invariant — if this
        # fails, the template grew a duplicate id and import itself would now
        # raise (this is just a friendlier assertion of the same fact).
        from document_model.document_tree import DOCUMENT_TREE, build_node_index, walk_tree

        all_ids = []
        walk_tree(DOCUMENT_TREE, lambda n: all_ids.append(n.id))
        # No exception, and the index spans every node exactly once.
        index = build_node_index(DOCUMENT_TREE)
        assert len(index) == len(all_ids)

    def test_find_node_default_returns_live_index_object(self):
        # find_node() with no explicit tree must return the SAME object the
        # index holds (the O(1) path), not a fresh walk result.
        from document_model.document_tree import DOCUMENT_TREE, build_node_index

        index = build_node_index(DOCUMENT_TREE)
        assert find_node("background") is index["background"]


class TestCollectDataKeys:
    """Verify collect_data_keys gathers keys from a subtree."""

    def test_single_node(self):
        node = find_node("background")
        keys = collect_data_keys(node)
        assert "background" in keys

    def test_parent_with_children(self):
        results = find_node("results")
        keys = collect_data_keys(results)
        # Should include bmd_summary, genomics_sections, etc.
        assert "bmd_summary" in keys
        assert "genomics_sections" in keys


class TestCollectPlatforms:
    """Verify collect_platforms gathers platform values from a subtree."""

    def test_table_node_has_platform(self):
        node = find_node("table-body-weight")
        platforms = collect_platforms(node)
        assert "Body Weight" in platforms

    def test_parent_collects_child_platforms(self):
        animal_condition = find_node("animal-condition")
        platforms = collect_platforms(animal_condition)
        assert "Body Weight" in platforms
        assert "Organ Weight" in platforms

    def test_clinical_obs_has_legacy_compat(self):
        """The "Clinical Observations" platform should also expose the legacy
        "Clinical" alias.  Built on a synthetic node (the active template no
        longer instances a clinical-obs table) so the alias contract is pinned
        independently of the template's node set."""
        node = DocNode(id="t-clin-obs", title="Clinical Observations", level=2,
                       node_type="incidence-table", platform="Clinical Observations")
        platforms = collect_platforms(node)
        assert "Clinical Observations" in platforms
        assert "Clinical" in platforms


class TestSerializeTree:
    """Verify serialize_tree produces JSON-friendly output."""

    def test_returns_list(self):
        result = serialize_tree()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_node_has_required_keys(self):
        result = serialize_tree()
        first = result[0]
        assert "id" in first
        assert "title" in first
        assert "level" in first
        assert "type" in first

    def test_children_serialized_recursively(self):
        result = serialize_tree()
        # Find the results node
        results_dict = None
        for d in result:
            if d["id"] == "results":
                results_dict = d
                break
        assert results_dict is not None
        assert "children" in results_dict
        assert len(results_dict["children"]) > 0

    def test_platform_included_when_present(self):
        """Table nodes should have 'platform' in their serialized form."""
        result = serialize_tree()
        # Walk to find a table node
        results_dict = next(d for d in result if d["id"] == "results")

        def _find_platform(nodes):
            for n in nodes:
                if "platform" in n:
                    return n
                if "children" in n:
                    found = _find_platform(n["children"])
                    if found:
                        return found
            return None

        found = _find_platform(results_dict["children"])
        assert found is not None
        assert found["platform"] in ("Body Weight", "Organ Weight", "Clinical Chemistry")


class TestIsLeafTable:
    """Verify is_leaf_table correctly identifies table leaves."""

    def test_table_without_children_is_leaf(self):
        node = find_node("table-body-weight")
        assert is_leaf_table(node)

    def test_heading_node_is_not_leaf(self):
        node = find_node("results")
        assert not is_leaf_table(node)

    def test_narrative_node_is_not_leaf(self):
        node = find_node("background")
        assert not is_leaf_table(node)
