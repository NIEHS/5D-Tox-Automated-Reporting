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

from document_tree import (
    DOCUMENT_TREE,
    DocNode,
    compute_table_numbers,
    find_node,
    collect_data_keys,
    collect_platforms,
    is_leaf_table,
    serialize_tree,
)


class TestDocumentTreeStructure:
    """Verify the static DOCUMENT_TREE has expected top-level sections."""

    def test_tree_is_non_empty(self):
        assert len(DOCUMENT_TREE) > 0

    def test_has_cover_and_title(self):
        ids = [n.id for n in DOCUMENT_TREE]
        assert "cover" in ids
        assert "title-page" in ids

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

        def _collect(nodes):
            for n in nodes:
                if n.table_number is not None:
                    table_numbers.append(n.table_number)
                if n.children:
                    _collect(n.children)

        _collect(results.children)
        assert len(table_numbers) > 0
        # Table numbers should start at 2 (Table 1 = sample counts, inline)
        assert table_numbers[0] == 2
        # Should be sequential with no gaps
        for i in range(1, len(table_numbers)):
            assert table_numbers[i] == table_numbers[i - 1] + 1

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
        """Clinical Observations platform should also include 'Clinical'."""
        node = find_node("table-clinical-obs")
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
