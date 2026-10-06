"""Tissue concentrations print at 3 significant figures, as NIEHS-10 Table 7 does.

The per-animal plasma values are NIEHS-10's (CEBS C20022-01 Individual Animal
Tissue Concentration Data); the expected cells are the published Table 7 /
PA48.  The renderer re-rounds every mean ± SE cell, so the check runs through
the shared render plan, not just the builder.
"""

import json

from document_model.document_node import DocNode
from rendering.render_common import apical_table_plan
from rendering.report_data import normalize_apical_section_for_render
from tables.tissue_concentration_table import build_tissue_concentration_table_from_sidecar

CHEM = "Perfluorohexanesulfonamide"
# sex -> dose -> (2 h values on SD4, 24 h values on SD5), one per animal
PLASMA = {
    "Male": {4.0: ([31.5, 27.6, 42.4], [23.8, 16.9, 28.7]),
             37.0: ([141, 117, 153], [46.4, 18.4, 85.3])},
    "Female": {4.0: ([39.7, 58.2, 41], [31.5, 42.5, 40.3]),
               37.0: ([190, 182, 180], [105, 104, 95.3])},
}
NB = " ± "
PUBLISHED = {  # (sex, row label) -> [4 mg/kg, 37 mg/kg]
    ("Male", "2 h postdose"): [f"33.8{NB}4.43", f"137{NB}10.6"],
    ("Male", "24 h postdose"): [f"23.1{NB}3.42", f"50.0{NB}19.4"],
    ("Female", "2 h postdose"): [f"46.3{NB}5.96", f"184{NB}3.06"],
    ("Female", "24 h postdose"): [f"38.1{NB}3.36", f"101{NB}3.08"],
}


def _sidecar(by_dose: dict) -> dict:
    animals, aid = {}, 0
    for dose, (two_h, day_after) in by_dose.items():
        for early, late in zip(two_h, day_after):
            aid += 1
            animals[str(aid)] = {"dose": dose, "selection": "Biosampling Animals", "observations": [
                {"day": "SD4", "endpoint": f"Plasma 2 Hour {CHEM} Concentration", "value": str(early)},
                {"day": "SD4", "endpoint": f"Plasma 2 Hour {CHEM} LOQ", "value": "1"},
                {"day": "SD5", "endpoint": f"Plasma 24 Hour {CHEM} Concentration", "value": str(late)},
                {"day": "SD5", "endpoint": f"Plasma 24 Hour {CHEM} LOQ", "value": "1"},
            ]}
    return {"animals": animals}


def test_niehs10_table7_cells_match_published(tmp_path):
    paths = {}
    for sex, by_dose in PLASMA.items():
        p = tmp_path / f"{sex}.sidecar.json"
        p.write_text(json.dumps(_sidecar(by_dose)))
        paths[sex] = str(p)
    tc = build_tissue_concentration_table_from_sidecar(paths, compound_name=CHEM)

    section = normalize_apical_section_for_render({
        "platform": "Tissue Concentration", "title": "Tissue Concentration",
        "tables_json": tc["table_data"], "caption": tc["caption"],
    })
    node = DocNode(id="tissue-concentration", title="Tissue Concentration",
                   node_type="table", platform="Tissue Concentration")
    plan = apical_table_plan(node, {"apical_sections": [section]})

    got = {(b.sex_label, r.cells[0]): r.cells[1:3]
           for b in plan.sex_blocks for r in b.rows if not r.is_n_row}
    assert got == PUBLISHED
