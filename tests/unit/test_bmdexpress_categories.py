"""genomics.bmdexpress_categories — tables from BMDExpress's own category analyses.

The 2025 NIEHS reports build the Top-10 genes from the GENE category analysis
(gene level: Entrez gene, median over its probes, only genes that passed every
BMDExpress filter) and print the GO tables' direction counts from the GO_BP
analysis.  For NIEHS-13 rat liver this reproduces the published table exactly
(assets/cebs/NIEHS-13-comparison.md); these tests pin the rules on small inputs.
"""

from genomics.bmdexpress_categories import (
    category_analyses_by_experiment, gene_level_top_genes, genomic_bmr, go_direction_counts,
)


def _gene(sym, entrez, probes, bmd, bmdl, bmdu, up=1, down=0, passed=1):
    return {"geneSymbolsPrivate": sym, "genesIds": entrez, "probeIds": probes,
            "bmdMedian": bmd, "bmdlMedian": bmdl, "bmduMedian": bmdu,
            "genesAdverseUpCount": up, "genesAdverseDownCount": down,
            "genesThatPassedAllFilters": passed}


def test_top_genes_are_gene_level_filtered_and_ranked_by_median():
    items = [
        _gene("cyp2b1", "24300", "CYP2B1_32451,CYP2B2_32473", 69.9, 43.9, 101.5),
        _gene("cyp2b2", "361523", "CYP2B2_32473", 48.4, 25.0, 78.3),
        _gene("scd", "246074", "SCD_1", 4.6, 0.43, 229.7, passed=0),   # failed a filter
        _gene("car3", "54232", "CAR3_8196", 117.8, 41.2, 266.8, up=0, down=1),
    ]
    fc = {"CYP2B1_32451": 303.0, "CYP2B2_32473": 87.1, "CAR3_8196": -2.3}
    top = gene_level_top_genes(items, fc, "Rattus norvegicus")
    assert [g["gene_symbol"] for g in top] == ["Cyp2b2", "Cyp2b1", "Car3"]
    assert top[1]["entrez_id"] == "24300"
    assert top[1]["probe_id"] == "CYP2B1_32451,CYP2B2_32473"
    assert top[1]["fold_change"] == (303.0 + 87.1) / 2      # mean over the gene's probes
    assert top[2]["direction"] == "down" and top[2]["fold_change"] == -2.3
    assert [g["rank"] for g in top] == [1, 2, 3]


def test_human_symbols_stay_upper_case():
    top = gene_level_top_genes([_gene("cyp2b6", "1555", "P_1", 1.0, 0.5, 2.0)], {}, "Homo sapiens")
    assert top[0]["gene_symbol"] == "CYP2B6"


def test_analyses_are_grouped_by_owning_experiment_and_kind():
    integrated = {
        "doseResponseExperiments": [{"name": "rat_LI_No0"}, {"name": "rat_LI_No0_extra"}],
        "categoryAnalysisResults": [
            {"name": "rat_LI_No0_curvefit_BMD_S1500_Plus_Rat_GENE_true_rsquared0.6",
             "categoryAnalsyisResults": [{"x": 1}]},
            {"name": "rat_LI_No0_extra_curvefit_BMD_S1500_Plus_Rat_GO_BP_true",
             "categoryAnalsyisResults": [{"categoryIdentifier": {"id": "GO:1"},
                                         "genesAdverseUpCount": 18, "genesAdverseDownCount": 2}]},
        ],
    }
    by_exp = category_analyses_by_experiment(integrated)
    assert set(by_exp) == {"rat_LI_No0", "rat_LI_No0_extra"}   # longest name wins
    assert by_exp["rat_LI_No0"]["GENE"] == [{"x": 1}]
    assert go_direction_counts(by_exp["rat_LI_No0_extra"]["GO_BP"]) == {"GO:1": (18, 2)}


def test_genomic_bmr_is_read_from_the_bmd_analysis_notes():
    integrated = {"bMDResult": [{"name": "rat_LI_No0_curvefit_BMD", "analysisInfo": {"notes": [
        "BMR Type: Relative Deviation", "BMR Factor: 0.25"]}}]}
    assert genomic_bmr(integrated, "rat_LI_No0") == {"type": "Relative Deviation", "factor": 0.25}
    assert genomic_bmr(integrated, "rat_KI_No0") is None


def test_prefilter_fold_changes_reads_the_williams_result_the_bmd_ran_on():
    """BMDExpress 2.x stat results carry no fold change; the Williams result
    records each probe's (published NIEHS-10 liver: Egr1 −4.218 → 4.2)."""
    from genomics.bmdexpress_categories import prefilter_fold_changes

    probe = {"@ref": 48, "@type": "Probe", "id": "EGR1_8533"}
    integrated = {
        "doseResponseExperiments": [{"@ref": 1, "name": "Liver_PFHxSAm_Male", "probeResponses": [
            {"@ref": 99, "@type": "ProbeResponse", "probe": probe, "responses": [1.0]}]}],
        "williamsTrendResults": [
            {"name": "Liver_PFHxSAm_Male_williams_other", "doseResponseExperiement": 1,
             "williamsTrendResults": [{"probeResponse": 99, "bestFoldChange": 9.9}]},
            {"name": "Liver_PFHxSAm_Male_williams_0.05_NOMTC_foldfilter1.5", "doseResponseExperiement": 1,
             "williamsTrendResults": [{"probeResponse": 99, "bestFoldChange": -4.2182856}]},
        ],
        "bMDResult": [{"analysisInfo": {"notes": [
            "Work Source: Liver_PFHxSAm_Male_williams_0.05_NOMTC_foldfilter1.5"]}}],
    }
    assert prefilter_fold_changes(integrated) == {"Liver_PFHxSAm_Male": {"EGR1_8533": -4.2182856}}


def test_display_symbols_cases_a_go_gene_list():
    from genomics.bmdexpress_categories import display_symbols

    assert display_symbols("zfp36;pik3r1;loc100911814", "Rattus norvegicus") == "Zfp36;Pik3r1;Loc100911814"
    assert display_symbols("cyp2b6;egr1", "Homo sapiens") == "CYP2B6;EGR1"
