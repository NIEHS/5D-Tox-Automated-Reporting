"""Our statistics against the significance markers NIEHS published.

Each reference fixture (tests/fixtures/reference/<report>/) is a subset of a
published CEBS package: the Individual Animal workbooks and the PA06/PA41/PA43
summaries NTP computed from them.  tooling.ntp_stats_conformance converts the
workbooks, matches each published row to our data by VALUE (every dose group's
N and mean at the published precision) and compares the * / ** markers.

A RATCHET in both directions: a new disagreement fails, and so does a known one
that starts agreeing (then shrink the list).  Every known disagreement is a
p-value within ~0.001 of 0.01 or 0.05 (assets/cebs/NTP-STATS-CONFORMANCE.md).
Unmatched rows are rows our data cannot reproduce — NTP's outlier removals and
derived endpoints we do not compute.
"""

import pytest

from tests.conftest import REFERENCE_DIR
from tooling.ntp_stats_conformance import compare_package

# report -> ({(table, sex, label, dose, column): (published, ours)}, {unmatched (table, sex, label)})
KNOWN = {
    "NIEHS-10": (
        {("PA41", "Male", "Cholesterol", 0.0, "trend"): ("**", "*"),       # J p = 0.0105
         ("PA41", "Male", "Cholesterol", 111.0, "pairwise"): ("**", "*")},  # Dunn p = 0.0486
        {("PA41", "Male", "A/G Ratio"), ("PA41", "Female", "A/G Ratio")},   # derived; not computed
    ),
}
COMPARED = {"NIEHS-10": 640}


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
