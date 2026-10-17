"""A missing measurement must reach BMDExpress as a missing value, never make
the whole table unreadable.

BMDExpress's ExperimentFileUtil rejects an empty cell as non-numeric and drops
the table; it reads "NaN" as a missing value it skips during modeling.  The CSV
converter wrote NaN; the workbook converter wrote "", so every workbook table
with a missing value was dropped from the combined dataset (NIEHS-10's clinical
chemistry, hematology, hormones, organ weights and tissue concentrations) while
the integration reported success.  IntegrateProject now fails instead of
skipping a table it can't read, so the same fault can't be silent again.
"""

import openpyxl

from bmdx_pipe.pool_integrator import xlsx_to_pivot_txt


def _pivot(path) -> dict[str, list[str]]:
    lines = [ln.split("\t") for ln in open(path).read().splitlines() if not ln.startswith("#")]
    return {r[0]: r[1:] for r in lines[2:]}


def test_a_missing_workbook_value_is_written_as_nan(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["NTP Study Number", "Concentration", "Animal ID", "Sex", "Liver", "Heart"])
    ws.append(["S", 0, "1", "Male", 10.1, 1.2])
    ws.append(["S", 4, "2", "Male", 11.2, None])   # heart not weighed
    path = tmp_path / "organ.xlsx"
    wb.save(path)
    [out] = xlsx_to_pivot_txt(str(path), str(tmp_path), "Organ Weight", "tox_study")
    rows = _pivot(out)
    assert rows["Heart"] == ["1.2", "NaN"]
    assert rows["Liver"] == ["10.1", "11.2"]
    assert all(v != "" for vals in rows.values() for v in vals)


def test_integrate_project_fails_on_a_table_it_cannot_read():
    from pathlib import Path
    src = (Path(__file__).parent.parent / "src/bmdx_pipe/java/IntegrateProject.java").read_text()
    # the skip that hid the loss is gone; an unreadable table stops the run
    assert "— skipping" not in src
    assert "System.exit(3)" in src
