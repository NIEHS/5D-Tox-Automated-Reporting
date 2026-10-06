"""The published apical BMD/BMDL/LOEL/NOEL summaries, reproduced.

Oracle: the published "BMD, BMDL, LOEL, and NOEL Summary for Apical Endpoints"
(rat, 108020004) in the CEBS package.

- BMD/BMDL: from the CEBS non-genomic BMDExpress 3.20 project
  (108020004_4D_NonGenomic_Rats.bm2, read through its JSON export — the .bm2
  needs Java) through bmdx_pipe's classification (the NIEHS defined-category
  filter, bmd_acceptance): every published value printed, every NVM reproduced.
- LOEL/NOEL: from the Individual Animal workbooks, ingested through the real
  path (reference_session) and run through bmdx_pipe.build_table_data — the NTP
  pairwise tests (Williams/Dunnett for weights, Shirley/Dunn for clinical
  pathology) and the NIEHS LOEL/NOEL rule.  The integrated project
  build_table_data reads is assembled from the session's pivot files by
  _read_pivot, standing in for Java's IntegrateProject import; checked against
  the Java-built integrated.json of the NIEHS-13 session (same experiment
  names, platforms, doses, endpoints and responses on all four platforms).
- NIEHS-10 LOEL/NOEL, the same way, against its published summary (CEBS
  C20022-01 …LOEL_and_NOEL_Summary….docx, both sexes, hormones included).  Its
  BMDs came from modified BMDS 2.7 (not in the fixture), so only LOEL/NOEL.

LOEL/NOEL are compared as the report prints them (render_common._dose_cell):
"ND" — not determined — when there is no LOEL, or no tested dose below it.
"""

import json
import math
import re
from pathlib import Path

import docx
import pypdf
from bmdx_pipe.apical_report import _build_bmd_result_lookup, build_table_data, format_bmd

from rendering.render_common import _dose_cell
from tests.conftest import REFERENCE_DIR

D = REFERENCE_DIR / "NIEHS-13"
EXPERIMENT = "108020004_4D_Rat_BMDExpress_Input_Fnl"


def _published() -> dict[str, tuple[str, str, str, str]]:
    """{endpoint label: (BMD, BMDL, LOEL, NOEL)} — as printed ("NVM" for no model)."""
    pdf = D / "108020004_BMD,_NOEL_and_LOEL_Summary_for_Apical_Endpoints_Rats.pdf"
    out = {}
    for line in pypdf.PdfReader(pdf).pages[0].extract_text(extraction_mode="layout").splitlines():
        m = re.match(r"\s*([A-Z][A-Za-z -]+?)\s{2,}([\d.]+|NVM)\s+([\d.]+|NVM)\s+(\d+)\s+(\d+)\s*$", line)
        if m:
            out[m.group(1).strip()] = m.groups()[1:]
    return out


def _key(label: str) -> frozenset[str]:
    """Words that identify an endpoint across naming styles: "Liver Weight
    Absolute" == "Liver", "Reticulocytes" == "Reticulocyte count"."""
    words = {w.rstrip("s") for w in re.findall(r"[a-z]+", label.lower())}
    return frozenset(words - {"weight", "absolute", "count"})


def _match(label: str, candidates) -> str:
    hits = [c for c in candidates if _key(c) == _key(label)]
    assert len(hits) == 1, (label, hits)
    return hits[0]


def _read_pivot(path: Path) -> dict:
    """A pool pivot file (the BMDExpress import format) as an integrated-project
    experiment — what Java's IntegrateProject builds from it."""
    platform, rows = None, []
    for line in path.read_text().splitlines():
        if line.startswith("#"):
            if line.startswith("# Platform:"):
                platform = line.split(":", 1)[1].strip()
            continue
        rows.append(line.split("\t"))
    doses = [float(x) for x in rows[1][1:]]
    return {
        "name": path.stem,
        "experimentDescription": {"platform": platform},
        "treatments": [{"name": a, "dose": d} for a, d in zip(rows[0][1:], doses)],
        "probeResponses": [
            {"probe": {"id": r[0]},
             "responses": [float(v) if v not in ("", "NaN") else math.nan for v in r[1:]]}
            for r in rows[2:]
        ],
    }


def test_niehs13_rat_bmd_and_bmdl_reproduced():
    published = _published()
    assert len(published) == 9

    project = json.loads((D / "108020004_4D_NonGenomic_Rats.bm2.json").read_text())
    ours = {probe: r for (exp, probe), r in _build_bmd_result_lookup(project).items()
            if exp == EXPERIMENT}
    assert len(ours) == 9

    for label, (bmd, bmdl, _loel, _noel) in published.items():
        r = ours[_match(label, ours)]
        if bmd == "NVM":
            assert r["status"] == "NVM", (label, r)
        else:
            assert r["status"] == "viable", (label, r)
            assert (format_bmd(r["bmd"], 1), format_bmd(r["bmdl"], 1)) == (bmd, bmdl), (label, r)


def _table_rows(session) -> dict:
    """{sex: {endpoint: TableRow}} from build_table_data over the session's pivots."""
    project = {"doseResponseExperiments": [_read_pivot(p) for p in sorted((session / "files").glob("*.txt"))],
               "bMDResult": []}
    return {sex: {row.label: row for row in rows} for sex, rows in build_table_data(project, {}).items()}


def _printed(value: str) -> str:
    """A published LOEL/NOEL cell ("111.0", "0.15", "ND") as our report prints it."""
    return value if value == "ND" else _dose_cell(float(value))


def test_niehs13_rat_loel_and_noel_reproduced(reference_session):
    rows = _table_rows(reference_session("NIEHS-13", "DTXSID1020431"))["Female"]
    published = _published()
    got = {}
    for label in published:
        row = rows[_match(label, rows)]
        got[label] = (_dose_cell(row.loel), _dose_cell(row.noel))
    assert got == {label: (_printed(loel), _printed(noel)) for label, (_, _, loel, noel) in published.items()}


def _niehs10_published() -> dict[tuple[str, str], tuple[str, str]]:
    """{(sex, endpoint): (LOEL, NOEL)} from the published summary table."""
    doc = docx.Document(next((REFERENCE_DIR / "NIEHS-10").glob("*LOEL_and_NOEL_Summary*.docx")))
    out, sex = {}, None
    for row in doc.tables[0].rows[1:]:
        cells = [c.text.strip() for c in row.cells]
        if cells[0] in ("Male", "Female"):
            sex = cells[0]
            continue
        out[(sex, cells[0])] = (cells[3], cells[4])
    return out


def test_niehs10_loel_and_noel_reproduced(reference_session):
    rows = _table_rows(reference_session("NIEHS-10", "DTXSID50469320"))
    published = _niehs10_published()
    assert len(published) == 23
    got, expected = {}, {}
    for (sex, label), (loel, noel) in published.items():
        row = rows[sex][_match(label, rows[sex])]
        got[(sex, label)] = (_dose_cell(row.loel), _dose_cell(row.noel))
        expected[(sex, label)] = (_printed(loel), _printed(noel))
    assert got == expected
