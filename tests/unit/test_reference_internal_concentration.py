"""The internal concentration tables of NIEHS-12 and -13 reproduce from the
lab's results workbook (Bookshelf bundle) through the real ingest path.

Published: NIEHS-12 Tables 18 (rats) and 19 (mice), NIEHS-13 Tables 19 (rats)
and 20 (mice) — tests/fixtures/reference/NIEHS-1x/bookshelf_Table_*.json
(tooling.bookshelf_breakdown).  Each table's study-day, matrix and n rows,
every concentration cell (mean ± SE, BD, significance markers — including the
groups NTP left an outlier out of) and the ppm-normalized rows are compared.

Not compared: the rows normalized by the theoretical inhaled dose
(mg/kg/day), which the data do not record.  Known differences: NIEHS-12
Table 19 prints three SEs at two significant figures ("0.80", "0.12",
"0.0067") where its own convention, and every other cell, has three.
"""

import json
import re

import pytest

from pipeline.method_profile import resolve
from tables.table_builder_common import find_sidecar_paths
from tables.tissue_concentration_table import build_tissue_concentration_table_from_sidecar
from tests.conftest import REFERENCE_DIR

CASES = [
    # report, study (its lab workbook holds both species), species, published table
    ("NIEHS-13", "108020004", "rat", "bookshelf_Table_19.json"),
    ("NIEHS-13", "108020004", "mouse", "bookshelf_Table_20.json"),
    ("NIEHS-12", "108020006", "rat", "bookshelf_Table_18.json"),
    ("NIEHS-12", "108020006", "mouse", "bookshelf_Table_19.json"),
]

# (table, row label, dose) → published cell, where the publication departs
# from its own printed precision.
KNOWN = {
    ("bookshelf_Table_19.json", "Liver concentration (ng/g)", "1"): "12.9 ± 0.80",
    ("bookshelf_Table_19.json", "Normalized liver concentration [(ng/g)/ppm]", "1"): "12.9 ± 0.80",
    ("bookshelf_Table_19.json", "Lung concentration (ng/g)", "1"): "7.86 ± 0.12",
    ("bookshelf_Table_19.json", "Normalized lung concentration [(ng/g)/ppm]", "1"): "7.86 ± 0.12",
    ("bookshelf_Table_19.json", "Normalized lung concentration [(ng/g)/ppm]", "250"): "0.0300 ± 0.0067",
}


def _clean(cell: str) -> str:
    cell = re.sub(r"<sup>.*?</sup>", "", cell)
    return cell.replace(",", "").replace("\\*", "*").replace(" ", " ").strip()


@pytest.mark.parametrize("report,study,species,table", CASES)
def test_concentration_table_matches_published(reference_session, report, study, species, table):
    session = reference_session(report, "DTXSID_REF", study=study)
    if species == "mouse":
        # The lab workbook holds both species; convert its mouse sheet.
        from bmdx_pipe import tox_study_csv_to_pivot_txt
        from tooling.cebs_to_pool import convert_workbook

        files = session / "files"
        for f in files.glob("tissue_conc_truth_*"):
            f.unlink()
        xlsx = next((REFERENCE_DIR / report).glob(f"{study}_*Concentration_Data.xlsx"))
        assert convert_workbook(str(xlsx), str(files), "mouse")["status"] == "ok"
        csv = files / "tissue_conc_truth_female.csv"
        tox_study_csv_to_pivot_txt(str(csv), str(files), "Tissue Concentration", "tox_study",
                                   units=json.loads(csv.with_suffix(".units.json").read_text()))

    built = build_tissue_concentration_table_from_sidecar(
        find_sidecar_paths(str(session), "Tissue Concentration"), "X", "ppm",
        {"species": species}, method=resolve("ntp-5day-2025"))
    rows = built["table_data"]["Female"]
    published = json.loads((REFERENCE_DIR / report / table).read_text())
    doses = [h.split()[0] for h in published["header"][0][1:]]
    pub_rows = [r for r in published["rows"] if "mg/kg" not in r[0]]

    assert [_clean(r["label"]).lower() for r in rows] == [_clean(r[0]).lower() for r in pub_rows]
    differ = {}
    for ours, pub in zip(rows, pub_rows):
        if ours.get("is_heading"):
            continue
        for dose, cell in zip(doses, pub[1:]):
            mine = ours["values"].get(dose, "").replace(" ", " ")
            if mine != _clean(cell):
                differ[(table, ours["label"], dose)] = _clean(cell)
    expected = {k: v for k, v in KNOWN.items() if k[0] == table} if report == "NIEHS-12" else {}
    assert differ == expected


def test_converter_reads_the_detection_limits_and_sampling():
    """The LOD comes from the sheet's own footnote; an early death is unsampled."""
    import openpyxl

    from tooling import cebs_lab_concentration as lab

    xlsx = next((REFERENCE_DIR / "NIEHS-13").glob("*Concentration_Data.xlsx"))
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    sheets = {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}
    assert lab.species_sheet(sheets, "rat") == "Rat Sample Results"
    header, body, units, _ = lab.to_key_data(sheets["Rat Sample Results"], "108020004")
    assert header[6:8] == ["Blood 1,4-DCB Concentration", "Blood 1,4-DCB LOD"]
    assert units["Lung 1,4-DCB Concentration"] == "ng/g"
    by_id = {(r[2], r[5]): r for r in body}
    assert by_id[("106", "4")][6:8] == ["173", "0.0960"]       # Subject ID 2F106
    assert by_id[("608", "4")][6:] == [""] * 6                  # early death, no samples
    mouse = lab.to_key_data(sheets["Mouse Sample Results"], "108020005")[1]
    assert {(r[2], r[5]): r for r in mouse}[("11", "4")][6:8] == ["BLOD", "0.0960"]
