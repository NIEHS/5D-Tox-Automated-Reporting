"""NIEHS-13's published genomics tables from its own BMDExpress project.

Inputs: the slim extract of the CEBS genomic project for the rat study
(108020004_4D_Genomic_Rats.slim.json.gz — tooling/slim_genomics_extract.py:
the GO BP categories and gene fits ExportGenomics reads from the .bm2, plus
BMDExpress's GO_BP/GENE category analyses; values copied, not recomputed).
The report's own table code (_extract_genomics) runs on it with the default GO
cutoffs.  Oracles: the published Top 10 GO Biological Process Gene Sets and
Top 10 Genes tables for all five tissues, and the Most Potent GO per tissue.

Each published table is identified by its CONTENT (title and "Tissue:"), not
its file name: two ovary files are swapped in the CEBS package —
"…Top_10_Genes_…_Ovary_Rats.pdf" holds the ovary GO table and
"…Top_10_GO_…_Lung_Ovary_Rats.pdf" the ovary genes table.
"""

import asyncio
import gzip
import json
import math
import re
import unicodedata

import pypdf
import pytest

from tests.conftest import REFERENCE_DIR

D = REFERENCE_DIR / "NIEHS-13"
DTXSID = "DTXSID1020431"
TISSUES = ("Heart", "Kidney", "Liver", "Lung", "Ovary")

_NUM = r"([\d.]+|NC)"
_GO_ROW = re.compile(r"(GO:\d{7})\s+.*?\s(\d+)/(\d+)\s+[\d.]+\s+([\d.]+)(?:\s+[a-z])?\s+"
                     + _NUM + r"\s*-\s*" + _NUM + r"\s+(\d+)\s+(\d+)\s*$")
_GO_MEMBERS = re.compile(r"^\s*(GO:\d{7}):\s+(\S+)\s*$")
_GENE_ROW = re.compile(r"^\s*(\S+)\s+(\d+)\s+(\S+)\s+([\d.]+)\s*\(\s*" + _NUM + r"\s*-\s*" + _NUM
                       + r"\s*\)\s+([\d.]+)\s+(UP|DOWN|CONFLICT)\s*$")


def _lines(pdf):
    # NFKC: the PDFs separate gene symbols with U+037E GREEK QUESTION MARK (";").
    for page in pypdf.PdfReader(pdf).pages:
        yield from unicodedata.normalize("NFKC", page.extract_text(extraction_mode="layout")).splitlines()


def _published_top10() -> dict[tuple[str, str], object]:
    """{("GO" | "Genes", tissue): pdf} by the table's own title and tissue."""
    out = {}
    for pdf in sorted(D.glob("108020004_Top_10_*.pdf")):
        head = " ".join(" ".join(ln.split()) for ln in list(_lines(pdf))[:12])
        kind = "GO" if "Top 10 GO Biological Process" in head else "Genes" if "Top 10 Genes" in head else None
        tissue = re.search(r"Tissue:\s*(\w+)", head)
        assert kind and tissue, pdf.name
        assert (kind, tissue.group(1)) not in out, pdf.name
        out[(kind, tissue.group(1))] = pdf
    return out


PUBLISHED = _published_top10()


def _go_table(pdf) -> list[tuple]:
    """[(go id, n with BMD, n genes, BMD, BMDL, BMDU, up, down, members)] in printed order."""
    rows, members = [], {}
    for line in _lines(pdf):
        m = _GO_MEMBERS.match(line)
        if m:
            members.setdefault(m.group(1), m.group(2))
            continue
        m = _GO_ROW.search(line)
        if m:
            rows.append(m.groups())
    return [(*r, members.get(r[0])) for r in rows]


def _genes_table(pdf) -> list[tuple]:
    return [m.groups() for m in map(_GENE_ROW.match, _lines(pdf)) if m]


def _f1(x) -> str:
    """A value as printed: one decimal, "NC" when not computable."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return "NC"
    return f"{f:.1f}" if math.isfinite(f) else "NC"


@pytest.fixture(scope="module")
def sections(tmp_path_factory):
    """The report's genomics sections, built by the report's own code from the
    slim extract (the sidecar placed where integration writes it)."""
    from pipeline.processing_helpers import _extract_genomics
    from tests.conftest import _patch_sessions_dir

    slim = json.loads(gzip.open(D / "108020004_4D_Genomic_Rats.slim.json.gz").read())
    root = tmp_path_factory.mktemp("sessions")
    (root / DTXSID).mkdir()
    (root / DTXSID / "genomics.sidecar.json").write_text(json.dumps(slim["genomics_sidecar"]))
    mp = pytest.MonkeyPatch()
    _patch_sessions_dir(mp, root)
    try:
        # The defaults generate_report uses (go_pct 5, 20–500 genes, ≥3 with a BMD).
        return asyncio.run(_extract_genomics(DTXSID, slim["integrated"], ["fifth_pct", "median"],
                                             5, 20, 500, 3))
    finally:
        mp.undo()


def _ours_go(section, n=10):
    return [(r["go_id"], str(r["n_genes_with_bmd"]), str(r["n_genes"]), _f1(r["bmd"]), _f1(r["bmdl"]),
             _f1(r["bmdu"]), str(r["n_up"]), str(r["n_down"]),
             ";".join(sorted(s.lower() for s in (r.get("genes") or "").split(";") if s)))
            for r in section["gene_sets_by_stat"]["fifth_pct"][:n]]


def test_every_tissue_has_both_published_tables():
    assert set(PUBLISHED) == {(k, t) for k in ("GO", "Genes") for t in TISSUES}


@pytest.mark.parametrize("tissue", TISSUES)
def test_top10_go_gene_sets(sections, tissue):
    published = _go_table(PUBLISHED[("GO", tissue)])
    assert len(published) == 10
    pub = [(*r[:8], ";".join(sorted(s.lower() for s in (r[8] or "").split(";") if s))) for r in published]
    assert _ours_go(sections[f"{tissue.lower()}_female"]) == pub


def test_most_potent_go_per_tissue(sections):
    published = {}
    for line in _lines(D / "108020004_Most_Potent_GO_Biological_Process_In_Each_Tissue_Rats.pdf"):
        m = re.match(r"\s*(Heart|Kidney|Liver|Lung|Ovary)\s", line)
        g = _GO_ROW.search(line)
        if m and g:
            published[m.group(1)] = g.groups()
    assert set(published) == set(TISSUES)
    for tissue, row in published.items():
        assert _ours_go(sections[f"{tissue.lower()}_female"], 1)[0][:8] == row, tissue


@pytest.mark.parametrize("tissue", TISSUES)
def test_top10_genes(sections, tissue):
    published = _genes_table(PUBLISHED[("Genes", tissue)])
    assert len(published) == 10
    ours = [(g["gene_symbol"], g["entrez_id"], g["probe_id"], _f1(g["bmd"]), _f1(g["bmdl"]), _f1(g["bmdu"]),
             _f1(abs(g["fold_change"])) if g.get("fold_change") is not None else "NC", g["direction"].upper())
            for g in sections[f"{tissue.lower()}_female"]["top_genes"]]
    assert ours == published


def test_species_resolved_for_every_experiment():
    # The chip (species) is inline on the first experiment only; the others
    # carry its @ref id.  Every tissue must still get the chip's species.
    from genomics.bmdexpress_categories import chip_species_by_experiment
    slim = json.loads(gzip.open(D / "108020004_4D_Genomic_Rats.slim.json.gz").read())
    chips = [e["chip"] for e in slim["integrated"]["doseResponseExperiments"]]
    assert isinstance(chips[0], dict) and all(isinstance(c, int) for c in chips[1:])
    assert set(chip_species_by_experiment(slim["integrated"]).values()) == {"Rattus norvegicus"}
    assert len(chip_species_by_experiment(slim["integrated"])) == 5
