"""NIEHS-07 … 10 Table 7 (plasma concentrations), every cell, from the
published packages — the rules of method profile ntp-5day-2021.1 as the lab's
PA48 summaries state them:

- a group is BD (below detection) unless over 20% of its values are above the
  limit; otherwise values below the limit count at half the limit (the LOD
  where the data record one, else the LOQ: NIEHS-08 and 10);
- no outlier test (the built-in Dixon test turned three published cells of
  NIEHS-08 and 09 to BD);
- a "No Sample Received" animal is not a sample: NIEHS-07's female 4 mg/kg
  group at 2 hours has two, and the table says so.

Oracle: each package's PA48 summary.  One of its 32 cells is printed with
fewer figures than the rest: NIEHS-08's male 2 mg/kg at 24 hours, "8.1 ± 3.1"
(the same numbers as our "8.10 ± 3.10"), while NIEHS-09 prints an equally exact
0.63 as "0.630".  No rule tells them apart, so that cell is compared by value.
"""

import re

import pypdf
import pytest

from pipeline.method_profile import resolve
from tables.table_builder_common import find_sidecar_paths
from tables.tissue_concentration_table import build_tissue_concentration_table_from_sidecar
from tests.conftest import REFERENCE_DIR

# The one cell PA48 prints short (see the module docstring): (report, sex, hours).
SHORT_PRINT = {("NIEHS-08", "Male", 24)}

STUDIES = {"NIEHS-07": "DTXSID00190950", "NIEHS-08": "DTXSID2029905",
           "NIEHS-09": "DTXSID1022477", "NIEHS-10": "DTXSID50469320"}
NB = " ± "


def _published(report: str) -> dict:
    """{(sex, hours): [cell per dose]} from the package's PA48 summary."""
    [pdf] = (REFERENCE_DIR / report).glob("*PA48*.pdf")
    out, sex = {}, None
    for page in pypdf.PdfReader(pdf).pages:
        for line in page.extract_text().splitlines():
            m = re.match(r"(Male|Female):", line)
            if m:
                sex = m.group(1)
            m = re.search(r"Plasma (\d+) hour .*?\)\s+(.*)$", line)
            if m and sex:
                cells = re.findall(r"BD|([\d.]+)\s*±\s*([\d.]+)\s*\(\d+\)", m.group(2))
                out[(sex, int(m.group(1)))] = [
                    "BD" if not a else f"{a}{NB}{b}"
                    for a, b in (c if isinstance(c, tuple) else (None, None) for c in cells)]
    return out


@pytest.mark.parametrize("report", sorted(STUDIES))
def test_every_table7_cell_matches_the_pa48_summary(reference_session, report):
    published = _published(report)
    assert len(published) == 4                      # 2 sexes × 2 timepoints
    session = reference_session(report, STUDIES[report])
    tc = build_tissue_concentration_table_from_sidecar(
        find_sidecar_paths(str(session), "Tissue Concentration"), compound_name="X",
        method=resolve("ntp-5day-2021.1"))
    got = {}
    for sex, rows in tc["table_data"].items():
        for row in rows:
            if not row.get("is_n_row"):
                hours = int(row["label"].split()[0])
                got[(sex, hours)] = [row["values"][k] for k in sorted(row["values"], key=float)]
    for key in [k for k in published if (report, *k) in SHORT_PRINT]:
        as_numbers = lambda cells: [[float(x) for x in c.split(NB)] if NB in c else c  # noqa: E731
                                    for c in cells]
        assert as_numbers(got.pop(key)) == as_numbers(published.pop(key))
    assert got == published


def test_a_group_short_of_samples_and_the_bd_rule_are_footnoted(reference_session):
    session = reference_session("NIEHS-07", STUDIES["NIEHS-07"])
    tc = build_tissue_concentration_table_from_sidecar(
        find_sidecar_paths(str(session), "Tissue Concentration"), compound_name="X",
        dose_unit="mg/kg", design={"species": "rat"}, method=resolve("ntp-5day-2021.1"))
    texts = [f["text"] for f in tc["footnotes"]]
    assert texts[:2] == [
        "If over 20% of the animals in a group are above the limit of detection, then half the "
        "limit of detection value is substituted for values that are below it.",
        "BD = below detection; group did not have over 20% of its values above the limit of "
        "detection so mean and standard error were not calculated."]
    assert "Only two samples were received for the 4 mg/kg female rats at 2 hours postdose." in texts
    female_2h = tc["table_data"]["Female"][1]
    assert female_2h["label"] == "2 Hours Postdose (ng/mL)"
    assert female_2h["values"]["4"] == "BD" and "4" in female_2h["marker_refs"]
    assert tc["table_data"]["Female"][0]["values"]["4"] == "3"     # n: the animals


def test_the_narrative_says_when_a_timepoint_fell_below_detection(reference_session):
    """NIEHS-07: "At 24 hours postdose, the concentration fell below the limit of
    detection … in both male and female rats, suggesting short plasma
    half-lives" — never a mean of fill-ins."""
    from tables.toxicokinetics import build_internal_dose_narrative, compute_toxicokinetics

    session = reference_session("NIEHS-07", STUDIES["NIEHS-07"])
    tk = compute_toxicokinetics(find_sidecar_paths(str(session), "Tissue Concentration"),
                                resolve("ntp-5day-2021.1"))
    text = " ".join(build_internal_dose_narrative(tk, "6:1 FTOH", "mg/kg", {"species": "rat"}))
    assert ("At 24 hours postdose, plasma concentrations in male and female rats were below "
            "the limit of detection in every dose group, suggesting short plasma half-lives.") in text
    assert "male rats were higher than those in female rats" in text
    assert "24 hours;" not in text and "half-lives (from" not in text   # no ratio or t½ from BD
