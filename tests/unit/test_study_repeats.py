"""
Sections repeated per study and per tissue (ADR-0029 §9, document_tree
repeat_items / _expand_repeats) and the data a scoped copy renders from
(render_common.node_data): a report over several studies writes "Study Design
for Rats" / "for Mice", and Heart … Ovary × Rats / Mice under the gene set
analysis, each from its own study's data.
"""

from document_model.document_template import instantiate
from document_model.document_tree import repeat_items, study_tree
from rendering.render_common import node_data, resolve_narrative_content

STUDIES = [{"key": "rat", "title": "Rats", "dtxsid": "R_rat",
            "data": {"methods": {"sections": [{"key": "study_design", "paragraphs": ["Rat design."]}]},
                     "genomics_sections": [{"type": "gene_set", "organ": "heart",
                                            "narrative": ["Rat heart."]}]}},
           {"key": "mouse", "title": "Mice", "dtxsid": "R_mouse",
            "data": {"methods": {"sections": [{"key": "study_design", "paragraphs": ["Mouse design."]}]},
                     "genomics_sections": [{"type": "gene_set", "organ": "heart",
                                            "narrative": ["Mouse heart."]}]}}]
DATA = {"studies": STUDIES, "methods": {"sections": []},
        "genomics_sections": [{"type": "gene_set", "organ": "heart"},
                              {"type": "gene_set", "organ": "ovary"},
                              {"type": "gene", "organ": "heart"}]}


def _tree():
    return instantiate([{"region": "body", "children": [
        {"id": "mm", "type": "heading-only", "title": "Materials and Methods", "children": [
            {"id": "mm-design", "type": "narrative", "title": "Study Design for ${species}",
             "data_key": "methods", "methods_key": "study_design", "repeat": "study_species"}]},
        {"id": "gs", "type": "heading-only", "title": "Gene Sets", "children": [
            {"id": "gs-tissue", "type": "heading-only", "title": "${organ}",
             "repeat": "genomic_organs", "children": [
                 {"id": "gs-tissue-study", "type": "narrative", "title": "${species}",
                  "data_key": "gene_set_narrative", "repeat": "study_species"}]}]}]}])


def _flat(nodes, depth=0):
    out = []
    for n in nodes:
        out.append(("  " * depth) + f"{n.id}: {n.title} [{n.scope_species}/{n.scope_organ}]")
        out += _flat(n.children, depth + 1)
    return out


def test_a_report_over_studies_repeats_per_study_and_tissue():
    nodes = study_tree(_tree(), None, None, DATA)
    assert _flat(nodes) == [
        "mm: Materials and Methods [None/None]",
        "  mm-design--rat: Study Design for Rats [rat/None]",
        "  mm-design--mouse: Study Design for Mice [mouse/None]",
        "gs: Gene Sets [None/None]",
        "  gs-tissue--heart: Heart [None/heart]",
        "    gs-tissue-study--rat--heart: Rats [rat/heart]",
        "    gs-tissue-study--mouse--heart: Mice [mouse/heart]",
        "  gs-tissue--ovary: Ovary [None/ovary]",
        "    gs-tissue-study--rat--ovary: Rats [rat/ovary]",
        "    gs-tissue-study--mouse--ovary: Mice [mouse/ovary]"]


def test_a_single_study_is_one_unscoped_copy_titled_with_its_animals():
    data = {"study_design": {"species": "rat"}}
    assert repeat_items(data)["study_species"] == [{"key": None, "title": "Rats"}]
    (mm, gs) = study_tree(_tree(), None, None, data)
    assert [(n.id, n.title, n.scope_species) for n in mm.children] == [
        ("mm-design", "Study Design for Rats", None)]
    assert gs.children == []                       # no tissues: nothing per tissue
    assert repeat_items({})["study_species"] == [{"key": None, "title": "Animals"}]


def test_a_scoped_copy_renders_from_its_study():
    nodes = study_tree(_tree(), None, None, DATA)
    rat_design, mouse_design = nodes[0].children
    assert resolve_narrative_content(rat_design, node_data(rat_design, DATA)).paragraphs == [
        "Rat design."]
    assert resolve_narrative_content(mouse_design, node_data(mouse_design, DATA)).paragraphs == [
        "Mouse design."]
    mouse_heart = nodes[1].children[0].children[1]
    assert node_data(mouse_heart, DATA)["gene_set_narrative"] == {"paragraphs": ["Mouse heart."]}
    assert node_data(nodes[1], DATA) is DATA      # an unscoped node: the report's data
