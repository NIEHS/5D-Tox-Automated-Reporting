"""NIEHS-10 Table 7 (plasma concentrations) reproduced from the published data.

Inputs: the CEBS Individual Animal Tissue Concentration workbook, ingested
through the real path (reference_session).  Oracle: the published PA48 summary
in the same package — mean and SE each at 3 significant figures, the unit from
the Key sheet.  The renderer re-rounds every mean ± SE cell, so the check runs
through the shared render plan, not just the builder.
"""

import re

import pypdf

from document_model.document_node import DocNode
from rendering.render_common import apical_table_plan
from rendering.report_data import normalize_apical_section_for_render
from tables.table_builder_common import find_sidecar_paths
from tables.tissue_concentration_table import build_tissue_concentration_table_from_sidecar
from tests.conftest import REFERENCE_DIR

NB = " ± "
PA48 = REFERENCE_DIR / "NIEHS-10" / "C20022-01_PA48_-_Summary_of_Tissue_Concentration.pdf"


def _published_cells() -> dict:
    """{(sex, "<N> h postdose"): [cell per dose]} from the PA48 PDF."""
    out, sex = {}, None
    for page in pypdf.PdfReader(PA48).pages:
        for line in page.extract_text().splitlines():
            m = re.match(r"(Male|Female):", line)
            if m:
                sex = m.group(1)
            m = re.search(r"Plasma (\d+) hour .*?\)\s+(.*)$", line)
            if m and sex:
                cells = re.findall(r"([\d.]+)\s*±\s*([\d.]+)\s*\(\d+\)", m.group(2))
                out[(sex, f"{m.group(1)} h postdose")] = [f"{a}{NB}{b}" for a, b in cells]
    return out


def test_niehs10_table7_cells_match_published(reference_session):
    published = _published_cells()
    assert len(published) == 4  # 2 sexes × 2 timepoints

    session = reference_session("NIEHS-10", "DTXSID50469320")
    paths = find_sidecar_paths(str(session), "Tissue Concentration")
    tc = build_tissue_concentration_table_from_sidecar(paths, compound_name="PFHxSAm")
    section = normalize_apical_section_for_render({
        "platform": "Tissue Concentration", "title": "Tissue Concentration",
        "tables_json": tc["table_data"], "caption": tc["caption"],
    })
    node = DocNode(id="tissue-concentration", title="Tissue Concentration",
                   node_type="table", platform="Tissue Concentration")
    plan = apical_table_plan(node, {"apical_sections": [section]})

    got = {(b.sex_label, r.cells[0]): r.cells[1:3]
           for b in plan.sex_blocks for r in b.rows if not r.is_n_row}
    assert got == published
    # The unit is the Key sheet's (ug/ml), not a literal.
    assert tc["footnotes"][0].endswith("plasma concentration data are presented in µg/mL.")
