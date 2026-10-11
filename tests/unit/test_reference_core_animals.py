"""Body weight values feed statistics and BMD modeling with Core animals only.

Every published NIEHS body weight table counts the Core cohort: its n equals
the Core count per dose (NIEHS-07 … 13, the Bookshelf reports' "Summary of
Body Weights" tables), and the internal-dose animals ("Biosampling"/"Biosample
Animals", weighed too) are left out.  bmdx-pipe keeps them out of the pivot —
the BMDExpress input the statistics and BMD modeling read — while the sidecar
keeps every animal.

Oracles — the CEBS Mean Body Weight Summaries:
  * NIEHS-10: C20022-01_Mean_Body_Weight_Summary.docx — "N = …" per dose
    (the animals weighed at SD5; 0 where every Core animal died);
  * NIEHS-13: 108020004_Mean_Body_Weight_Summary_Rats.pdf — "[n]" per cell.
"""

import re
import unicodedata
from collections import Counter

import docx
import pypdf

from tests.conftest import REFERENCE_DIR


def _pivot_counts(session, sex: str) -> dict[str, list[int]]:
    """{row: [animals with a value, per dose ascending]} of the body weight pivot."""
    lines = [ln.split("\t") for ln in (session / "files" / f"body_weight_truth_{sex}.txt")
             .read_text().splitlines() if not ln.startswith("#")]
    doses = [float(d) for d in lines[1][1:]]
    out = {}
    for row in lines[2:]:
        n = Counter(d for d, v in zip(doses, row[1:]) if v != "NaN")
        out[row[0]] = [n.get(d, 0) for d in sorted(set(doses))]
    return out


def test_niehs10_pivot_counts_the_published_n(reference_session):
    session = reference_session("NIEHS-10", "DTXSID50469320")
    doc = docx.Document(str(REFERENCE_DIR / "NIEHS-10" / "C20022-01_Mean_Body_Weight_Summary.docx"))
    for sex, table in zip(("male", "female"), doc.tables):
        published = [int(m.group(1)) for c in table.rows[0].cells[1:]
                     if (m := re.search(r"N\s*=\s*(\d+)", c.text))]
        assert len(published) == 10
        # 3 Biosampling animals at each of two doses were weighed on SD5 as well.
        assert _pivot_counts(session, sex)["SD5"] == published


def test_niehs13_pivot_counts_the_published_n(reference_session):
    session = reference_session("NIEHS-13", "DTXSID1020431")
    pdf = REFERENCE_DIR / "NIEHS-13" / "108020004_Mean_Body_Weight_Summary_Rats.pdf"
    text = unicodedata.normalize("NFKC", pypdf.PdfReader(pdf).pages[0].extract_text(extraction_mode="layout"))
    counts = _pivot_counts(session, "female")
    for label, row in (("SD0(", "SD0"), ("SD5(", "SD5"), ("Gain", "Body Weight Gain")):
        line = next(ln for ln in text.splitlines() if label in ln and "[" in ln)
        published = [int(n) for n in re.findall(r"\[(\d+)\]", line)]
        assert len(published) == 7
        # 3 Biosample animals per group, weighed SD0–SD4, are not counted.
        assert counts[row] == published, label
