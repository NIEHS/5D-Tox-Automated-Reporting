"""Body Weight Gain reproduced from the published data.

NIEHS reports and models the derived endpoint Body Weight Gain: per Core
animal, the last study day's weight minus the first's.  bmdx-pipe writes it
into the body weight pivot at ingest (Core Animals only — NIEHS-10's
Biosampling animals, weighed on SD0 and SD5 too, are excluded), so it gets the
NTP statistics and a BMD like any endpoint; the body weight table prints it as
the 2025 reports do ("Summary of Body Weights and Body Weight Gain").

Oracles — the CEBS Mean Body Weight Summaries:
  * NIEHS-10: C20022-01_Mean_Body_Weight_Summary.docx (both sexes);
  * NIEHS-13: 108020004_Mean_Body_Weight_Summary_Rats.pdf (female rats).
Every published gain cell — mean ± SE and its * / ** marker — must print as
ours.  (Dose groups where every animal died print "N/A" there, "–" here.)
"""

import re
import unicodedata

import docx
import pypdf

from tables.body_weight_table import BODY_WEIGHT_GAIN, build_body_weight_table_from_sidecar
from tables.table_builder_common import find_sidecar_paths
from tests.conftest import REFERENCE_DIR
from tests.unit.test_reference_bmd_summary import _table_rows

NB = " ± "


def _ours(reference_session, report, dtxsid) -> dict[str, list[str]]:
    """{sex: [gain cell per dose]} from our body weight table — printed cells."""
    session = reference_session(report, dtxsid)
    table = build_body_weight_table_from_sidecar(find_sidecar_paths(str(session), "Body Weight"),
                                                 stats_rows=_table_rows(session))
    assert "Body Weight Gain" in table["caption"]
    out = {}
    for sex, rows in table["table_data"].items():
        row = next(r for r in rows if r["label"] == BODY_WEIGHT_GAIN)
        out[sex] = [row["values"][k] for k in sorted(row["values"], key=float)]
    return out


def _cell(text: str) -> str:
    m = re.match(r"(-?[\d.]+)\s*±\s*([\d.]+)\s*(?:\[\d+\])?\s*(\**)$", text.strip())
    return f"{m.group(1)}{NB}{m.group(2)}{m.group(3)}" if m else "–"


def test_niehs10_gain_matches_the_published_summary(reference_session):
    doc = docx.Document(str(REFERENCE_DIR / "NIEHS-10" / "C20022-01_Mean_Body_Weight_Summary.docx"))
    published = {}
    for sex, table in zip(("Male", "Female"), doc.tables):
        row = next(r for r in table.rows if r.cells[0].text.strip().startswith("Body Weight Gain"))
        cells = [c.text.strip() for c in row.cells[1:-2]]          # drop the BMD/BMDL columns
        published[sex] = [_cell(c) if c != "N/A" else "–" for c in cells]
    assert _ours(reference_session, "NIEHS-10", "DTXSID50469320") == published


def test_niehs13_gain_matches_the_published_summary(reference_session):
    pdf = REFERENCE_DIR / "NIEHS-13" / "108020004_Mean_Body_Weight_Summary_Rats.pdf"
    text = unicodedata.normalize("NFKC", pypdf.PdfReader(pdf).pages[0].extract_text(extraction_mode="layout"))
    line = next(ln for ln in text.splitlines() if "Gain" in ln)
    published = [_cell(c) for c in re.findall(r"-?[\d.]+\s*±\s*[\d.]+\[\d+\]\**", line)]
    assert len(published) == 7
    assert _ours(reference_session, "NIEHS-13", "DTXSID1020431") == {"Female": published}
