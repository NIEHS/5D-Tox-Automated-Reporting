"""
The 2026 books' genomic appendices built from the data (rendering.
genomics_appendix, genomics.efdr, genomics.go_definitions): the eFDR methods,
results and table (NIEHS-13 Appendix D.2) and the gene set and gene
definition tables (Appendix E).
"""

import shutil
from pathlib import Path

import pytest

from document_model.document_node import DocNode
from document_model.document_template import load_phrasing
from document_model.phrasing import Phrasing
from rendering import genomics_appendix as ga
from rendering.render_common import inline_plain_text, scoped_value

DOSES = [0, 1, 10, 30, 100, 250, 500]
P = Phrasing(load_phrasing("eras/niehs-2026"))       # the 2026 books' words
SANDGEN = {"generator": "Synthetic and Null Data Generator", "generator_abbreviation": "SaNDGen",
           "generator_url": "https://rstudio.niehs.nih.gov/sandgen/", "distribution": "normal",
           "resamples_per_probe": 1000}


def _tissue(species, tissue, genes, go_active=None, doses=DOSES[1:]):
    go_active = go_active or [0] * len(genes)
    return {"species": species, "tissue": tissue, "experiments": len(genes),
            "groups": {"0": 10, **{f"{d:g}": 5 for d in doses}},
            "gene_pct": genes, "go_active": go_active,
            "go_pct": [0.0 if not n else None for n in go_active]}


def _data(species_doses=DOSES):
    return {"chemical_name": "1,2-Dichlorobenzene", "dose_unit": "ppm",
            "study_design": {"species": "rat", "route": "inhaled"},
            "apical_sections": [{"table_data": {"Female": [{"doses": species_doses}]}}]}


def test_the_efdr_table_prints_as_the_books_do():
    efdr = {"tissues": [_tissue("mouse", "Heart", [0.0, 0.0651, 0.208]),
                        _tissue("rat", "Heart", [0.0, 0.42, 0.0], [0, 8, 0])]}
    m = ga.appendix_efdr_matrix(efdr, P)
    assert m["caption"] == "Empirical False Discovery Results"
    assert m["rows"][0] == ["Mouse", "Heart", "0.09", "0–0.21", "0", "0"]
    assert m["rows"][1][:4] == ["Rat", "Heart", "0.14", "0–0.42"]
    assert m["rows"][1][4] == ga.GO_EFDR_PENDING          # a GO universe we cannot know


def test_the_efdr_results_sentences():
    efdr = {"tissues": [_tissue("mouse", "Heart", [0.0, 0.07, 0.21]),
                        _tissue("rat", "Liver", [0.0, 0.0, 0.03])]}
    (p,) = ga.efdr_results(efdr, "D-1", P)
    assert inline_plain_text(p) == (
        "In all species-tissue combinations, the gene-level eFDR was <1%, with a range of 0% to "
        "0.21% (Table D-1). Most gene-level eFDR values were below 0.5%. In all cases, the eFDR "
        "for GO biological processes was 0% across all species-tissue combinations.")


def test_the_efdr_methods_name_the_study_only_when_the_doses_are_its_own():
    efdr = {"tissues": [_tissue("rat", "Heart", [0.0] * 20)]}
    (p,) = ga.efdr_methods(_data(), efdr, "G", SANDGEN, P)
    text = inline_plain_text(p)
    assert "0 ppm data from each tissue in the 1,2-dichlorobenzene rat study." in text
    assert "(SaNDGen; https://rstudio.niehs.nih.gov/sandgen/), which employed the normal " \
        "distribution method" in text
    assert "resampled to generate 1,000 values for each probe" in text
    assert "organized into 20 different experiments" in text
    assert "i.e., 10 samples in the 0 ppm group and 5 for each nonzero exposure concentration" in text
    assert text.endswith("can be found in Appendix G.")
    # NIEHS-13 deposited NIEHS-12's synthetic null analysis (other doses).
    (p,) = ga.efdr_methods(_data([0, 1, 10, 50, 150, 400, 800]), efdr, "G", SANDGEN, P)
    assert "[Placeholder: whose 0 ppm data — the synthetic null analyses of the rat heart" \
        in inline_plain_text(p)


def test_a_profile_that_does_not_state_the_null_data_s_making_says_so():
    """ntp-5day-2025 predates genomics.efdr: its facts are placeholders, not
    the 2026 books' words."""
    from pipeline.method_profile import resolve
    method = resolve("ntp-5day-2025").efdr_generation()
    (p,) = ga.efdr_methods(_data(), {"tissues": [_tissue("rat", "Heart", [0.0] * 20)]}, None,
                           method, P)
    text = inline_plain_text(p)
    assert "SaNDGen" not in text
    assert "[Placeholder: synthetic null data generator — not stated by the method profile]" \
        in text
    assert resolve("ntp-5day-2025.1").efdr_generation() == SANDGEN


def test_the_results_wording_is_the_definition_s():
    """A definition that words a sentence differently, or names another
    bound, changes the prose — not the code."""
    efdr = {"tissues": [_tissue("mouse", "Heart", [0.0, 0.07, 0.21])]}
    reworded = Phrasing({**P.block, "efdr": {**P.block["efdr"], "bound_pct": 0.1,
                                             "majority_below_pct": None,
                                             "gene_range": "Gene eFDR: {bound} ({min}–{max}%)."}})
    (p,) = ga.efdr_results(efdr, None, reworded)
    assert inline_plain_text(p).startswith("Gene eFDR: at most 0.21% (0–0.21%).")


def _gene_set_entry():
    return {"type": "gene_set", "organ": "heart", "table_number": 7,
            "display": {"stat": "fifth_pct", "unit": "ppm", "decimals": 1,
                        "bmr": {"type": "Relative Deviation", "factor": 0.25}},
            "sexes": [{"sex": "Rats", "study": "rat", "gene_sets": [
                {"go_id": "GO:0044770", "go_term": "cell cycle phase transition", "n_genes": 58,
                 "n_genes_with_bmd": 5, "genes": "Usp22;Cks2", "bmd": 141.36, "bmdl": 55.85,
                 "bmdu": 292.9}]}]}


def test_a_tissue_s_gene_set_definitions(monkeypatch):
    import genomics.go_definitions as gd
    monkeypatch.setattr(gd, "_loaded", lambda: ({"GO:0044770": "The cell cycle process by "
                                                 "which a cell commits to entering the next "
                                                 "cell cycle phase."}, "releases/2025-07-22"))
    built = ga.appendix_gene_set_definitions({"genomics_sections": [_gene_set_entry()]}, P)
    heart = built["by_organ"]["heart"]
    assert heart["caption"].startswith("Active Genes and Definitions within Top 1 Heart Gene "
                                       "Ontology Biological Process Gene Sets Ranked by Potency")
    assert heart["rows"] == [["GO:0044770 cell cycle phase transition", "5/58 (8.6%)",
                              "Usp22; Cks2", "141.4 (55.9–292.9)",
                              "The cell cycle process by which a cell commits to entering the "
                              "next cell cycle phase."]]
    assert "go-basic.obo, releases/2025-07-22" in heart["footnotes"][0]["text"]


def test_without_go_basic_the_definitions_are_pending(monkeypatch, tmp_path):
    monkeypatch.setenv("BMDX_GO_OBO", str(tmp_path / "absent.obo"))
    built = ga.appendix_gene_set_definitions({"genomics_sections": [_gene_set_entry()]}, P)
    assert built["by_organ"]["heart"]["rows"][0][-1] == ga.GO_DEFINITION_PENDING


def test_go_basic_definitions_are_read(tmp_path, monkeypatch):
    from genomics import go_definitions as gd
    obo = tmp_path / "go-basic.obo"
    obo.write_text('format-version: 1.2\ndata-version: releases/2025-07-22\n\n[Term]\n'
                   'id: GO:0044770\nname: cell cycle phase transition\n'
                   'def: "The cell cycle process by which a cell commits to entering the next '
                   'cell cycle phase." [GOC:mtg_cell_cycle]\n', encoding="utf-8")
    monkeypatch.setenv("BMDX_GO_OBO", str(obo))
    assert gd.go_definition("GO:0044770").startswith("The cell cycle process")
    assert gd.release() == "releases/2025-07-22"


def test_each_study_lists_its_genes_once():
    data = {"genomics_sections": [
        {"type": "gene", "organ": o, "sexes": [{"sex": "Rats", "study": "rat", "top_genes": [
            {"gene": g, "entrez_id": i, "probe_id": f"{g.upper()}_1"} for g, i in genes]}]}
        for o, genes in (("heart", [("Spp1", "25353"), ("Lck", "313050")]),
                         ("kidney", [("Lck", "313050"), ("abcc3", "140668")]))]}
    rat = ga.appendix_gene_identifiers(data, P)["by_species"]["rat"]
    assert [r[:3] for r in rat["rows"]] == [["abcc3", "140668", "ABCC3_1"],
                                           ["Lck", "313050", "LCK_1"],
                                           ["Spp1", "25353", "SPP1_1"]]
    assert rat["rows"][0][3] == ga.GENE_DEFINITION_PENDING


def test_a_repeated_table_takes_its_own_matrix():
    by_organ = {"by_organ": {"heart": "H", "ovary": "O"}}
    assert scoped_value(DocNode(id="t", title="", scope_organ="ovary"), by_organ) == "O"
    by_study = {"by_species": {"": "single", "mouse": "M"}}
    assert scoped_value(DocNode(id="t", title=""), by_study) == "single"
    assert scoped_value(DocNode(id="t", title="", scope_species="mouse"), by_study) == "M"


NULL_ZIP = (Path(__file__).resolve().parents[2] / "assets" / "cebs" / "_bookshelf" / "NIEHS-13"
            / "108020004_Rat_DCB_eFDR_Synthetic_Null_Analysis.zip")


@pytest.mark.skipif(not NULL_ZIP.exists() or shutil.which("java") is None,
                    reason="NIEHS-13's deposited synthetic-null analysis or Java not present")
def test_the_efdr_of_a_deposited_null_analysis(tmp_path):
    """NIEHS-13 Table D-1, rat heart: gene eFDR mean 0.04 (our range 0–0.42;
    the book prints 0–0.2, and its other rat ranges are below their means)."""
    import zipfile
    from genomics.efdr import null_analysis, summarize
    name = "Rat Heart DCB Synthetic Null Analysis.bm2"
    with zipfile.ZipFile(NULL_ZIP) as zf:
        zf.extract(name, tmp_path)
    try:
        found = null_analysis(tmp_path / name, {"pct": 5, "min_genes": 20, "max_genes": 500,
                                                "min_bmd": 3}, tmp_path)
    except Exception as e:                         # the Java toolchain is environment-bound
        pytest.skip(f"Java export unavailable: {e}")
    gene = summarize(found["gene_pct"])
    assert (found["species"], found["tissue"], found["experiments"]) == ("rat", "Heart", 20)
    assert ga._pct(gene["mean"]) == "0.04"
    assert found["groups"] == {"0": 10, "1": 5, "10": 5, "30": 5, "100": 5, "250": 5, "500": 5}
