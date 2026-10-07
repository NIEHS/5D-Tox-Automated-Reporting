"""The body weight table shows the study days the published tables show.

Rows: the first and last study day, and every day between whose NTP
statistics are responsive (significant trend AND pairwise).  NIEHS-12 prints
rats' day 4 and mice's days 2–4 — not the days with a trend alone (rats 1–3,
mouse 1); NIEHS-13 and the earlier reports have no responsive intermediate day.
Each cell carries its own * / ** from that day's statistics.

Oracles — the CEBS Mean Body Weight Summaries ("mean ± SEM [N]" + markers):
NIEHS-12 rats and mice (tests/fixtures/reference/NIEHS-12), NIEHS-13 rats.
"""

import re
import unicodedata

import pypdf
import pytest

from tables.body_weight_table import build_body_weight_table_from_sidecar
from tables.table_builder_common import find_sidecar_paths
from tests.conftest import REFERENCE_DIR
from tests.unit.test_reference_bmd_summary import _table_rows

NB = "\u00a0±\u00a0"   # our cells use no-break spaces

# Cells the published data cannot reproduce: {(study, row, dose index): published}.
# NIEHS-12 mouse SD4, 0 ppm — the workbook's weights (recorded to 0.1 g) average
# to exactly 20.55, which rounds half up to 20.6; NIEHS printed 20.5, from its
# unrounded weights.  Our cell is checked to be the half-up reading.
_UNREPRODUCIBLE = {("108020007", "4", 0): (f"20.5{NB}0.4**", f"20.6{NB}0.4**")}
_CELL = re.compile(r"(-?[\d.]+)\s*±\s*([\d.]+)\s*\[\s*\d+\]\s*(\**)")


def _published(pdf) -> dict[str, list[str]]:
    """{row label as we print it: [cell per dose]} from a Mean Body Weight Summary."""
    text = unicodedata.normalize("NFKC", pypdf.PdfReader(pdf).pages[0].extract_text(extraction_mode="layout"))
    out = {}
    for line in text.splitlines():
        flat = re.sub(r"\s+", "", line)
        m = re.match(r"SD(\d+)\(g\)", flat)
        label = m.group(1) if m else ("Body Weight Gain" if flat.startswith("BodyWeightGain") else None)
        if label is not None:
            out[label] = [f"{a}{NB}{b}{mk}" for a, b, mk in _CELL.findall(line)]
    return out


def _ours(session) -> dict[str, list[str]]:
    table = build_body_weight_table_from_sidecar(find_sidecar_paths(str(session), "Body Weight"),
                                                 stats_rows=_table_rows(session))
    [rows] = table["table_data"].values()
    return {r["label"]: [r["values"][k] for k in sorted(r["values"], key=float)]
            for r in rows if not r.get("is_n_row")}


@pytest.mark.parametrize("report,study,pdf,days", [
    ("NIEHS-12", "108020006", "108020006_Mean_Body_Weight_Summary_Rats.pdf", ["0", "4", "5"]),
    ("NIEHS-12", "108020007", "108020007_Mean_Body_Weight_Summary_Mice.pdf", ["0", "2", "3", "4", "5"]),
    ("NIEHS-13", "108020004", "108020004_Mean_Body_Weight_Summary_Rats.pdf", ["0", "5"]),
])
def test_rows_and_cells_match_the_published_summary(reference_session, report, study, pdf, days):
    published = _published(REFERENCE_DIR / report / pdf)
    assert list(published) == days + ["Body Weight Gain"]
    session = reference_session(report, "DTXSID6020430" if report == "NIEHS-12" else "DTXSID1020431",
                                study=study)
    ours = _ours(session)
    for (s, row, i), (theirs, mine) in _UNREPRODUCIBLE.items():
        if s == study:
            assert (published[row][i], ours[row][i]) == (theirs, mine)
            published[row][i] = mine
    assert ours == published


def test_niehs02_database_export_body_weights(reference_session):
    """NIEHS-02 publishes the CEBS database-export layout: only the "Original
    Animals" count (the second, month-later cohort is dropped), and an animal
    found dead keeps its row with no value.  Oracle: the I04 summary, cells
    "mean ± SE [*]" per dose across its pages."""
    pdf = REFERENCE_DIR / "NIEHS-02" / "C10674_I04_Mean_Body_Weight_Summary.pdf"
    published: dict[str, list[str]] = {}
    for page in pypdf.PdfReader(pdf).pages:
        for line in unicodedata.normalize("NFKC", page.extract_text(extraction_mode="layout")).splitlines():
            m = re.match(r"\s*SD(\d+)\s", line)
            if m:
                published.setdefault(m.group(1), []).extend(
                    f"{a}{NB}{b}{mk}" for a, b, mk in re.findall(r"([\d.]+)\s*±\s*([\d.]+)\s*(\**)", line))
    assert {k: len(v) for k, v in published.items()} == {"0": 6, "4": 6}
    session = reference_session("NIEHS-02", "DTXSID9000002")
    ours = _ours(session)
    assert {day: ours[day] for day in published} == published

