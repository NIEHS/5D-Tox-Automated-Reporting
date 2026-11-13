"""The 2018-era genomic reporting rules (ntp-5day-2018; NIEHS-02 … 06), and the
lower limit of extrapolation every era prints ("<20.3 (NR)")."""

from genomics.bmdexpress_categories import (
    category_analyses_by_experiment, gene_level_top_genes, lower_limits_of_extrapolation,
    reported_go_ids,
)
from rendering.render_common import below_lle, gene_set_table_rows, gene_table_rows, lle_text

EXP = "EDHP mg_kg"
STEM = f"{EXP}_williams_0.05_NOMTC_foldfilter1.5_BMD_GPL1355_"


def _go(gid):
    return {"categoryIdentifier": {"id": gid, "title": gid}}


def _gene(title, bmd, probes, up=1, down=0):
    return {"categoryIdentifier": {"id": title, "title": title}, "geneSymbolsPrivate": "",
            "genesThatPassedAllFilters": 1, "bmdMedian": bmd, "bmdlMedian": bmd / 2,
            "bmduMedian": bmd * 2, "probeIds": ",".join(probes), "genesIds": "1",
            "genesAdverseUpCount": up, "genesAdverseDownCount": down}


def _project():
    return {"doseResponseExperiments": [{"name": EXP, "treatments": [
        {"dose": 0.0}, {"dose": 61.2}, {"dose": 122.5}]}],
        "categoryAnalysisResults": [
            {"name": STEM + "GO_BP_true_true_pval0.1_ratio40_conf0.5",
             "categoryAnalsyisResults": [_go("GO:1"), _go("GO:2")]},
            {"name": STEM + "GO_BP_true_true_pval0.1_ratio40_conf0.5_deduplicate",
             "categoryAnalsyisResults": [_go("GO:1")]},
            {"name": STEM + "DEFINED-Category_File_Rat_Individual_Gene_Category_File_true_true",
             "categoryAnalsyisResults": [_gene("ddit4", 5e-13, ["p1"])]},
        ]}


def test_the_individual_gene_analysis_is_gene_level_and_go_terms_come_deduplicated():
    cats = category_analyses_by_experiment(_project())[EXP]
    assert [g["categoryIdentifier"]["title"] for g in cats["GENE"]] == ["ddit4"]
    assert len(cats["GO_BP"]) == 3
    assert reported_go_ids(cats) == {"GO:1"}
    assert reported_go_ids({"GO_BP": cats["GO_BP"]}) is None
    assert lower_limits_of_extrapolation(_project()) == {EXP: 61.2 / 3}


def test_genes_below_the_fold_change_floor_are_not_reported():
    genes = [_gene("ddit4", 1.0, ["p1"]), _gene("trib3", 2.0, ["p2"]),
             _gene("slc6a6", 3.0, ["p3", "p4"], up=0, down=1)]
    fc = {"p1": 3.4, "p2": 1.9, "p3": -13.0, "p4": -1.5}
    kept = gene_level_top_genes(genes, fc, "Rattus norvegicus", min_fold_change=2)
    assert [g["gene_symbol"] for g in kept] == ["Ddit4", "Slc6a6"]   # median |fc| 7.25
    assert len(gene_level_top_genes(genes, fc, "Rattus norvegicus")) == 3


def test_a_bmd_below_the_limit_prints_lt_limit_nr_as_the_books_do():
    assert [lle_text(x, d) for x, d in ((61 / 3, 1), (1 / 3, 1), (0.15 / 3, 3), (0.07 / 3, 3))] \
        == ["20.3", "0.333", "0.050", "0.023"]
    d = {"lle": 61 / 3, "decimals": 1}
    assert below_lle(5e-13, d) == "<20.3" and below_lle(23.8, d) is None
    assert below_lle(5e-13, {"decimals": 1}) is None
    entry = {"display": d, "sexes": [{"sex": "Male", "top_genes": [
        {"gene_symbol": "Ddit4", "probe_id": "p1", "bmd": 5e-13, "bmdl": 1e-13, "bmdu": 9e-13,
         "fold_change": 3.4, "direction": "up"}],
        "gene_sets": [{"go_id": "GO:1", "go_term": "x", "n_genes": 18, "n_genes_with_bmd": 5,
                       "genes": "a;b", "bmd": 1e-12, "bmdl": 1e-13, "bmdu": 1e-11,
                       "n_up": 5, "n_down": 0}]}]}
    assert gene_table_rows(entry)[1][3] == "<20.3 (NR)"
    assert gene_set_table_rows(entry)[1][4:6] == ["<20.3", "NR"]
