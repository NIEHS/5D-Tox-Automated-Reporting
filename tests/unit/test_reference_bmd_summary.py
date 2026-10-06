"""NIEHS-13's published apical BMD summary from its own BMDExpress project.

Inputs: the CEBS non-genomic BMDExpress 3.20 project for the rat study
(108020004_4D_NonGenomic_Rats.bm2, read through its JSON export — the .bm2
needs Java).  Oracle: the published "BMD, BMDL, LOEL, and NOEL Summary for
Apical Endpoints" (rat) in the same package.  bmdx_pipe's classification (the
NIEHS defined-category filter, bmd_acceptance) must print every published BMD
and BMDL and reproduce every published NVM.
"""

import json
import re

import pypdf
from bmdx_pipe.apical_report import _build_bmd_result_lookup, format_bmd

from tests.conftest import REFERENCE_DIR

D = REFERENCE_DIR / "NIEHS-13"
EXPERIMENT = "108020004_4D_Rat_BMDExpress_Input_Fnl"


def _published() -> dict[str, tuple[str, str]]:
    """{endpoint label: (BMD, BMDL)} — numbers as printed, or "NVM"."""
    pdf = D / "108020004_BMD,_NOEL_and_LOEL_Summary_for_Apical_Endpoints_Rats.pdf"
    out = {}
    for line in pypdf.PdfReader(pdf).pages[0].extract_text(extraction_mode="layout").splitlines():
        m = re.match(r"\s*([A-Z][A-Za-z -]+?)\s{2,}([\d.]+|NVM)\s+([\d.]+|NVM)\s+\d+\s+\d+\s*$", line)
        if m:
            out[m.group(1).strip()] = (m.group(2), m.group(3))
    return out


def _tokens(label: str) -> frozenset[str]:
    return frozenset(w.rstrip("s") for w in re.findall(r"[a-z]+", label.lower()))


def test_niehs13_rat_bmd_summary_reproduced():
    published = _published()
    assert len(published) == 9

    project = json.loads((D / "108020004_4D_NonGenomic_Rats.bm2.json").read_text())
    ours = {probe: r for (exp, probe), r in _build_bmd_result_lookup(project).items()
            if exp == EXPERIMENT}
    assert len(ours) == 9

    for label, (bmd, bmdl) in published.items():
        # Match by words: "Reticulocytes" -> "Reticulocyte count".
        probe = max(ours, key=lambda p: len(_tokens(label) & _tokens(p)) - len(_tokens(p) - _tokens(label)) / 10)
        r = ours[probe]
        if bmd == "NVM":
            assert r["status"] == "NVM", (label, probe, r)
        else:
            assert r["status"] == "viable", (label, probe, r)
            assert (format_bmd(r["bmd"], 1), format_bmd(r["bmdl"], 1)) == (bmd, bmdl), (label, probe, r)
