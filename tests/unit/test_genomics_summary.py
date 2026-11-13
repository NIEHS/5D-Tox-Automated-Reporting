"""The most potent gene set of each tissue (NIEHS-12 Table 11, NIEHS-13
Table 12): each group's tissues with their lowest-BMD gene set, from the most
potent, the caption naming the animals."""

from rendering.genomics_summary import most_potent_gene_sets

DISPLAY = {"stat": "fifth_pct", "bmr": {"type": "Relative Deviation", "factor": 0.25},
           "unit": "ppm", "decimals": 1}


def _gs(go, term, bmd, bmdl, bmdu, n, total, up, down):
    return {"go_id": go, "go_term": term, "bmd": bmd, "bmdl": bmdl, "bmdu": bmdu,
            "n_genes_with_bmd": n, "n_genes": total, "n_up": up, "n_down": down}


def test_each_tissue_s_most_potent_gene_set_from_the_most_potent():
    genomics = [
        {"type": "gene_set", "organ": "heart", "display": DISPLAY, "sexes": [
            {"sex": "Rats", "gene_sets": [_gs("GO:0044770", "cell cycle phase transition",
                                              141.37, 55.85, 292.88, 5, 58, 0, 5)]},
            {"sex": "Mice", "gene_sets": []}]},
        {"type": "gene_set", "organ": "liver", "display": DISPLAY, "sexes": [
            {"sex": "Rats", "gene_sets": [
                _gs("GO:0001676", "long-chain fatty acid metabolic process", 92.8, 52.7, 150, 5, 50, 5, 0),
                _gs("GO:0006805", "xenobiotic metabolic process", 87.6, 59.6, 136.7, 20, 59, 18, 2)]}]},
        {"type": "gene", "organ": "liver", "sexes": []}]
    data = {"genomics_sections": genomics, "chemical_name": "1,4-Dichlorobenzene",
            "study_design": {"species": "rat", "route": "inhaled", "duration_days": 5,
                             "sexes": ["female"]}}
    table = most_potent_gene_sets(data)
    assert table["caption"] == (
        "Most Potent Gene Ontology Biological Process Gene Set per Tissue, Sorted by 5th "
        "Percentile Benchmark Dose, for Female Rats Exposed to 1,4-Dichlorobenzene for Five Days")
    assert table["headers"][3] == ("BMDrd25 5th Percentile of Gene Set Transcripts "
                                   "(BMDLrd25–BMDUrd25) (ppm)")
    assert table["rows"] == [
        ["**Rats**", "", "", "", ""],
        ["Liver", "GO:0006805 xenobiotic metabolic process", "20/59 (33.9%)",
         "87.6 (59.6–136.7)", "18/2"],
        ["Heart", "GO:0044770 cell cycle phase transition", "5/58 (8.6%)",
         "141.4 (55.9–292.9)", "0/5"]]
    assert most_potent_gene_sets({"genomics_sections": []}) is None
