"""Our statistics and printed cells against the summary tables NIEHS published.

Each reference fixture (tests/fixtures/reference/<report>/) is a subset of a
published CEBS package: the Individual Animal workbooks and the PA06/PA41/PA43
summaries NTP computed from them.  tooling.ntp_stats_conformance converts the
workbooks, matches each published row to our data by VALUE (every dose group's
N and mean at the published precision) and compares the * / ** markers and the
printed "mean ± SE" (at the precision our table builders use).

A RATCHET in both directions: a new disagreement fails, and so does a known one
that starts agreeing (then shrink the list).  Every known disagreement is a
p-value within ~0.001 of 0.01 or 0.05 (assets/cebs/NTP-STATS-CONFORMANCE.md).
Unmatched rows are rows our data cannot reproduce — NTP's outlier removals and
derived endpoints we do not compute.

Printed cells: across NIEHS-07 – -13, 3594 of 3598 published cells print
exactly as ours.  The 4 that do not are SEs on an exact decimal half that NTP
rounds sometimes up, sometimes down (no single rounding rule — half-up on the
decimal value or on the binary float — reproduces all of them).
"""

import pytest

from tests.conftest import REFERENCE_DIR
from tooling.ntp_stats_conformance import compare_package

# report -> ({(table, sex, label, dose, column): (published, ours)}, {unmatched (table, sex, label)})
KNOWN = {
    # NIEHS-02 publishes the CEBS database-export layout (tooling.cebs_db_export).
    "NIEHS-02": (
        {("PA06", "Male", "Brain Relative", 2.7, "pairwise"): ("**", "*")},  # Williams p = 0.0133
        {("PA41", "Male", "Globulin"), ("PA41", "Male", "A/G Ratio")},       # derived; not computed
    ),
    "NIEHS-10": (
        {("PA41", "Male", "Cholesterol", 0.0, "trend"): ("**", "*"),       # J p = 0.0105
         ("PA41", "Male", "Cholesterol", 111.0, "pairwise"): ("**", "*")},  # Dunn p = 0.0486
        {("PA41", "Male", "A/G Ratio"), ("PA41", "Female", "A/G Ratio")},   # derived; not computed
    ),
    "NIEHS-13": (
        {},
        {("PA41", "Female", "A/G Ratio"),                                   # derived; not computed
         # NTP removed outliers (published N below the data's): heart 150 ppm
         # (animal 403), AST and creatine kinase controls.
         ("PA06", "Female", "Heart Absolute"), ("PA06", "Female", "Heart Relative"),
         ("PA41", "Female", "Aspartate Aminotransferase"), ("PA41", "Female", "Creatine Kinase")},
    ),
}
COMPARED = {"NIEHS-02": 102, "NIEHS-10": 640, "NIEHS-13": 252}

# report -> {(sex, endpoint, dose): (published cell, ours)} — the known printed-cell edges
KNOWN_CELLS = {
    "NIEHS-02": {},
    "NIEHS-10": {("Male", "Monocyte count", 0.15): ("0.24 ± 0.09", "0.24 ± 0.10")},  # SE 0.095 (n = 2)
    "NIEHS-13": {},
}


@pytest.mark.parametrize("report", sorted(KNOWN))
def test_published_significance_markers(report, tmp_path):
    cells = compare_package(str(REFERENCE_DIR / report), str(tmp_path))
    compared = [c for c in cells if c["status"] == "compared"]
    disagree = {(c["table"], c["sex"], c["label"], c["dose"], c["column"]): (c["published"], c["ours"])
                for c in compared if c["published"] != c["ours"]}
    unmatched = {(c["table"], c["sex"], c["label"]) for c in cells if c["status"] == "unmatched"}

    known_disagree, known_unmatched = KNOWN[report]
    assert len(compared) == COMPARED[report]
    assert disagree == known_disagree
    assert unmatched == known_unmatched


@pytest.mark.parametrize("report", sorted(KNOWN_CELLS))
def test_published_cells_print_as_ours(report, tmp_path):
    cells = [c for c in compare_package(str(REFERENCE_DIR / report), str(tmp_path))
             if c["status"] == "compared" and c["published_cell"]]
    differ = {(c["sex"], c["endpoint"], c["dose"]): (c["published_cell"], c["ours_cell"])
              for c in cells if c["published_cell"] != c["ours_cell"]}
    assert differ == KNOWN_CELLS[report]
