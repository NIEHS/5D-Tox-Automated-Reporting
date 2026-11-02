"""
A table's footnote letters are printed where the published books print them
(NIEHS-07 … 13): the notes on the whole table on the first-column header
("Endpoint^a,b"), the plasma table's on its caption, a cell's on the cell
("4^c", "6^c,d", "Relative (mg/g)^e"). The builders bind notes to places
(tables.table_builder_common: marker_refs, finalize_footnotes);
rendering.render_common.apical_table_plan gives the letters as superscripts,
and every surface prints them.
"""

from document_model.document_node import DocNode
from rendering.render_common import apical_table_plan, make_sup
from tables.table_builder_common import add_marker_ref, finalize_footnotes, lettered_footnote

SUP = "sup"


def _section():
    n_row = {"label": "n", "doses": [0.0, 4.0], "values": {"0": "10", "4": "6"}, "is_n_row": True}
    rel = {"label": "Liver Relative (mg/g)", "doses": [0.0, 4.0],
           "values": {"0": "36.0 ± 0.7", "4": "BD"}, "bmd": "0.48", "bmdl": "0.22"}
    add_marker_ref(n_row, "4", "short")
    add_marker_ref(n_row, "4", "clot")
    add_marker_ref(rel, "label", "relative")
    add_marker_ref(rel, "bmd", "urep")
    footnotes = [
        lettered_footnote("Data are displayed as mean ± SE.", "data_format", target="header"),
        lettered_footnote("Statistics.", "stat", target="header"),
        lettered_footnote("Caption note.", "cap", target="caption"),
        lettered_footnote("Not received.", "short", target="cells"),
        lettered_footnote("Clotted.", "clot", target="cells"),
        lettered_footnote("Relative weights.", "relative", target="cells"),
        lettered_footnote("UREP.", "urep", target="cells"),
        lettered_footnote("Listed only.", "plain"),
    ]
    table = {"Male": [n_row, rel]}
    finalize_footnotes(footnotes, table)
    return {"platform": "Organ Weight", "dose_unit": "mg/kg", "caption": "Organ Weights",
            "first_col_header": "Endpoint", "table_data": table, "footnotes": footnotes}


def _plan():
    from rendering.report_data import normalize_apical_section_for_render

    node = DocNode(id="t", title="T", node_type="table", platform="Organ Weight")
    node.table_number = 3
    section = normalize_apical_section_for_render(_section())
    return apical_table_plan(node, {"apical_sections": [section]})


def test_finalize_letters_a_cell_with_two_notes():
    table = _section()["table_data"]
    assert table["Male"][0]["markers"] == {"4": "d,e"}
    assert table["Male"][1]["markers"] == {"label": "f", "bmd": "g"}


def test_the_plan_marks_header_caption_and_cells():
    plan = _plan()
    assert plan.first_col == ["Endpoint", make_sup("a,b")]
    assert plan.caption_units == ["Table 3. ", "Organ Weights", make_sup("c")]
    n_row, rel = plan.sex_blocks[0].rows
    assert n_row.cells[1] == "10"
    assert n_row.cells[2] == ["6", make_sup("d,e")]
    assert rel.cells[0] == ["Liver Relative (mg/g)", make_sup("f")]
    assert rel.cells[3] == ["0.48", make_sup("g")]
    assert rel.cells[4] == "0.22"


def test_every_surface_prints_the_marks():
    from rendering import docx_generator, html_generator, jats_generator, latex_generator

    node = DocNode(id="t", title="T", node_type="table", platform="Organ Weight")
    node.table_number = 3
    from rendering.report_data import normalize_apical_section_for_render
    data = {"apical_sections": [normalize_apical_section_for_render(_section())]}

    html = html_generator._render_apical_table(node, data)
    assert "Endpoint<sup>a,b</sup>" in html and "6<sup>d,e</sup>" in html
    assert "Organ Weights<sup>c</sup>" in html

    tex = latex_generator._render_apical_table(node, data)
    assert r"Endpoint\textsuperscript{a,b}" in tex and r"6\textsuperscript{d,e}" in tex
    assert r"Organ Weights\textsuperscript{c}" in tex

    from lxml import etree
    xml = etree.tostring(jats_generator._emit_apical_table(node, data)[0], encoding="unicode")
    assert "<th>Endpoint<sup>a,b</sup></th>" in xml and "<td>6<sup>d,e</sup></td>" in xml
    assert "<title>Organ Weights<sup>c</sup></title>" in xml

    from docx import Document
    doc = Document()
    docx_generator._render_apical_table(doc, node, data)
    runs = [(r.text, r.font.superscript) for t in doc.tables for row in t.rows
            for c in row.cells for p in c.paragraphs for r in p.runs]
    assert ("a,b", True) in runs and ("d,e", True) in runs
    caption_runs = [(r.text, r.font.superscript) for p in doc.paragraphs for r in p.runs]
    assert ("c", True) in caption_runs


def _bw_table(tmp_path, animals):
    import json
    from tables.body_weight_table import build_body_weight_table_from_sidecar

    def days(last):
        return [{"day": f"SD{d}", "endpoint": "Body Weight", "value": str(300 + d),
                 "terminal": d == last} for d in range(last + 1)]
    path = tmp_path / "bw.sidecar.json"
    path.write_text(json.dumps({"animals": {
        str(i): {"dose": dose, "selection": "Core Animals", "observations": days(last)}
        for i, (dose, last) in enumerate(animals)}}))
    return build_body_weight_table_from_sidecar({"Male": str(path)}, dose_unit="mg/kg")


def test_a_removal_after_the_first_weighing_marks_the_later_cells(tmp_path):
    # NIEHS-07 Table 2: one of 1,000 mg/kg's five rats left on day 1 and three on
    # day 4; the day-5 cell of the survivor carries one note naming both, and
    # a group of one prints no SE ("295.8^c").
    out = _bw_table(tmp_path, [(0.0, 5), (0.0, 5), (1000.0, 1), (1000.0, 4), (1000.0, 4),
                               (1000.0, 4), (1000.0, 5)])
    rows = {r["label"]: r for r in out["table_data"]["Male"]}
    fn = next(f for f in out["footnotes"] if f.get("id", "").startswith("indiv_removal"))
    assert fn["text"] == ("One male rat was found dead on study day 1 and three male rats "
                          "were found dead on study day 4.")
    assert rows["5"]["markers"] == {"1000": fn["letter"]}
    assert rows["5"]["values"]["1000"] == "305.0"
    assert "markers" not in rows["n"] and "markers" not in rows["0"]


def test_a_removal_by_the_first_weighing_marks_the_n(tmp_path):
    # NIEHS-10 Table 2: a rat found dead on day 0 is not in the table ("4^c").
    out = _bw_table(tmp_path, [(0.0, 5), (0.0, 5), (1000.0, 0), (1000.0, 5), (1000.0, 5)])
    rows = {r["label"]: r for r in out["table_data"]["Male"]}
    fn = next(f for f in out["footnotes"] if f.get("id", "").startswith("indiv_removal"))
    assert fn["text"] == "One male rat was found dead on study day 0."
    assert rows["n"]["markers"] == {"1000": fn["letter"]}
    assert "markers" not in rows["5"]


def test_a_group_short_of_samples_names_its_matrices_once():
    from tables.blood_tissue_concentration_table import _short_note

    assert _short_note([("liver", 2, 0), ("lung", 2, 0)], 3) == (
        "n = 2 for liver and lung. No samples were received for one animal.")
    assert _short_note([("blood", 2, 1), ("lung", 2, 1)], 3) == (
        "n = 2 for blood and lung. One animal for blood and one animal for lung were "
        "identified as outliers and thus excluded from analysis.")
    assert _short_note([("lung", 2, 1)], 3) == (
        "n = 2 for lung. One animal was identified as an outlier and thus excluded from "
        "analysis.")
