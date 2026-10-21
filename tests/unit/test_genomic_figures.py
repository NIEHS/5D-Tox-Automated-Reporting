"""
The gene set figures' sections (eras/niehs-proposed; rendering.genomic_figures):
a figure per genomic analysis — a tissue of one sex — repeated by the tree
(``repeat: genomic_analyses``), its image the Process step's chart for that
analysis, and an opening paragraph citing the figures by number.
"""

import base64

import pytest

from document_model.document_template import instantiate
from document_model.document_tree import analysis_key, repeat_items, study_tree
from document_model.phrasing import Phrasing, validate
from rendering.genomic_figures import (
    CLUSTER_INTRO, CLUSTER_KEY, MAP_INTRO, MAP_KEY, STAT_UNRECORDED, attach_genomic_figures,
)
from rendering.render_common import figure_payload, scoped_value

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 32).decode()
DESIGN = {"species": "rat", "route": "gavage", "duration_days": 5, "sexes": ["male", "female"]}
DATA = {"chemical_name": "Triclosan", "study_design": DESIGN, "dose_unit": "mg/kg",
        "genomics_sections": [
            {"type": "gene_set", "organ": "kidney", "sexes": [{"sex": "male"}]},
            {"type": "gene", "organ": "kidney", "sexes": [{"sex": "male"}]},
            {"type": "gene_set", "organ": "liver", "sexes": [{"sex": "male"}, {"sex": "female"}]}]}


def _tree():
    return instantiate([{"region": "body", "children": [
        {"id": "gs", "type": "heading-only", "title": "Gene Sets", "children": [
            {"id": "map", "type": "narrative", "title": "Semantic Map", "data_key": MAP_INTRO,
             "children": [
                 {"id": "fig-map", "type": "figure", "subtype": "chart",
                  "repeat": "genomic_analyses", "title": "Map of ${organ}",
                  "caption": "Map of ${organ}, for ${subject} ${treatment}",
                  "data_key": MAP_KEY}]},
            {"id": "clusters", "type": "narrative", "title": "Clusters",
             "data_key": CLUSTER_INTRO, "children": [
                 {"id": "fig-clusters", "type": "figure", "subtype": "chart",
                  "repeat": "genomic_analyses", "title": "Clusters of ${organ}",
                  "data_key": CLUSTER_KEY}]}]}]}])


def _chart(organ, sex, **extra):
    return {"organ": organ, "sex": sex, "umap_png": PNG, "cluster_png": PNG,
            "types": ["umap", "cluster"], "bmd_stat": "fifth_pct",
            "counts": {"gene_sets": 10, "on_map": 8, "with_bmd": 10, "overlap_clusters": 3},
            **extra}


def _phrasing():
    from document_model.document_template import load_phrasing
    return Phrasing(load_phrasing("eras/niehs-proposed"))


def test_one_copy_per_tissue_and_sex_naming_its_animals():
    items = repeat_items(DATA)["genomic_analyses"]
    assert [(i["key"], i["title"], i["fields"]["subject"]) for i in items] == [
        ("kidney-male", "Kidney", "Male Rats"),
        ("liver-male", "Liver", "Male Rats"),
        ("liver-female", "Liver", "Female Rats")]
    nodes = study_tree(_tree(), None, None, DATA)
    figs = [c for c in nodes[0].children[0].children]
    assert [(f.id, f.scope_analysis) for f in figs] == [
        ("fig-map--kidney-male", "kidney-male"), ("fig-map--liver-male", "liver-male"),
        ("fig-map--liver-female", "liver-female")]
    assert figs[2].caption == ("Map of Liver, for Female Rats Administered Triclosan "
                               "for Five Days")
    assert [f.figure_number for f in figs] == [1, 2, 3]


def test_no_genomic_analyses_no_figures():
    nodes = study_tree(_tree(), None, None, {**DATA, "genomics_sections": []})
    assert nodes[0].children[0].children == []


def test_a_copy_takes_its_analysis_payload():
    nodes = study_tree(_tree(), None, None, DATA)
    fig = nodes[0].children[0].children[1]
    value = {"by_analysis": {"liver-male": {"png_b64": PNG}}}
    assert scoped_value(fig, value) == {"png_b64": PNG}
    assert figure_payload(fig, {MAP_KEY: value}) == {"png_b64": PNG}
    assert figure_payload(nodes[0].children[0].children[0], {MAP_KEY: value}) is None
    assert analysis_key("Liver", "Male") == "liver-male"


def test_figures_and_their_prose_from_the_charts():
    data = dict(DATA)
    tree = study_tree(_tree(), None, None, data)
    charts = [_chart("kidney", "male"), _chart("liver", "male"),
              _chart("liver", "female", counts={"gene_sets": 5, "on_map": 5, "with_bmd": 5,
                                                "overlap_clusters": 2})]
    attach_genomic_figures(data, tree, _phrasing(), charts)
    maps = data[MAP_KEY]["by_analysis"]
    assert sorted(maps) == ["kidney-male", "liver-female", "liver-male"]
    assert maps["kidney-male"]["filename"] == "gene-set-map-kidney-male.png"
    assert maps["kidney-male"]["notes"] == [
        "8 of the 10 active gene sets are on the map; the other 2 are GO terms the map "
        "does not hold and are not shown."]
    assert maps["liver-female"]["notes"] == ["All 5 active gene sets are on the map."]
    assert data[CLUSTER_KEY]["by_analysis"]["liver-male"]["notes"] == [
        "10 gene sets in 3 clusters, each at its BMD 5th percentile."]
    (intro,) = data[MAP_INTRO]["paragraphs"]
    assert "(Figure 1 to Figure 3)" in intro and "2,840 GO biological process terms" in intro
    (intro,) = data[CLUSTER_INTRO]["paragraphs"]
    assert "(Figure 4 to Figure 6)" in intro and "BMD 5th percentile (mg/kg, log scale)" in intro


def test_charts_that_do_not_record_their_statistic_say_so():
    data = dict(DATA)
    tree = study_tree(_tree(), None, None, data)
    charts = [{k: v for k, v in _chart("kidney", "male").items() if k != "bmd_stat"}]
    attach_genomic_figures(data, tree, _phrasing(), charts)
    assert STAT_UNRECORDED in data[CLUSTER_INTRO]["paragraphs"][0]
    # Only the figures with an image are cited.
    assert "(Figure 4)" in data[CLUSTER_INTRO]["paragraphs"][0]


def test_nothing_without_figures_placed():
    data = dict(DATA)
    tree = instantiate([{"region": "body", "children": [
        {"id": "gs", "type": "heading-only", "title": "Gene Sets"}]}])
    attach_genomic_figures(data, tree, _phrasing(), [_chart("kidney", "male")])
    assert MAP_KEY not in data and MAP_INTRO not in data


def test_the_proposed_definition():
    from document_model.document_definition import DEFAULT_DEFINITION, load_definition
    from document_model.document_template import load_phrasing
    assert DEFAULT_DEFINITION == "eras/niehs-proposed"
    validate(load_phrasing("eras/niehs-proposed"))
    ids = set()

    def walk(entries):
        for e in entries:
            ids.add(e.get("id"))
            walk(e.get("children") or [])
    walk(load_definition("eras/niehs-proposed")["document"])
    assert {"gene-set-map", "figure-gene-set-map", "gene-set-clusters",
            "figure-gene-set-clusters", "figures-list"} <= ids


@pytest.mark.parametrize("study", ["DTXSID1020431", "DTXSID6020430"])
def test_the_published_2026_books_have_no_proposed_sections(study):
    from document_model.document_definition import load_definition
    ids = set()

    def walk(entries):
        for e in entries:
            ids.add(e.get("id"))
            walk(e.get("children") or [])
    walk(load_definition(f"studies/{study}/document")["document"])
    assert not {"gene-set-map", "gene-set-clusters", "figures-list"} & ids


def test_only_a_section_a_table_or_a_figure_repeats():
    with pytest.raises(ValueError, match="only a section, a table or a figure"):
        instantiate([{"region": "body", "children": [
            {"id": "c", "type": "cover", "title": "C", "repeat": "genomic_analyses"}]}])
