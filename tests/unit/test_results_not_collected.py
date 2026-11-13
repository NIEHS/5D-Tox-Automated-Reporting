"""A Results section whose data domains the study did not collect states so
from its document node's gate (requires_platform / not_collected_text in the
template), as the Materials and Methods subsections do — one source for the
wording, the document's; Process no longer writes it."""

from document_model.document_tree import DOCUMENT_TREE, find_node, render_nodes
from rendering.render_common import resolve_narrative_content


def _section(data, node_id):
    tree = render_nodes(data, DOCUMENT_TREE)
    return resolve_narrative_content(find_node(node_id, tree), data)


def test_a_genomics_only_study_says_which_results_were_not_evaluated():
    data = {"collected_platforms": ["gene_expression"], "unified_narratives": {}}
    assert _section(data, "animal-condition").paragraphs == [
        "Body and organ weights were not evaluated in this study."]
    assert _section(data, "clinical-path").paragraphs == [
        "Clinical pathology (clinical chemistry, hematology, and hormone analyses) was not "
        "evaluated in this study."]
    assert _section(data, "internal-dose").paragraphs == [
        "Internal dose was not assessed in this study."]


def test_a_collected_domain_keeps_its_findings_and_a_scaffold_decides_nothing():
    data = {"collected_platforms": ["Clinical Observations", "Hematology"],
            "unified_narratives": {"animal_condition": ["All rats survived."],
                                   "clinical_pathology": ["Findings."]}}
    assert "not evaluated" not in " ".join(_section(data, "animal-condition").paragraphs or [])
    assert "not evaluated" not in " ".join(_section(data, "clinical-path").paragraphs or [])
    scaffold = {"unified_narratives": {}}               # no collected-set signal
    assert _section(scaffold, "internal-dose").kind == "none"
