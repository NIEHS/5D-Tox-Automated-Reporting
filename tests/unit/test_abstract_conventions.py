"""
The abstract's Summary and gene sentences follow the published books:

- a study of one sex names no sex ("Taken together, the most sensitive …",
  NIEHS-02 … 06); one of both sexes names each ("in male rats", NIEHS-10);
- the 2026 books (the definition's ``abstract_genes: false``) name no
  individual gene: "the most sensitive gene set and apical endpoint BMD
  (BMDL) values … occurred at …" (NIEHS-12, 13);
- a report over several studies states each under its animals: "Taken
  together, in rats, …  In mice, …".
"""

from narrative.abstract_genomics import build_abstract_results_genomics
from narrative.abstract_summary import build_abstract_summary
from rendering.report_compose import _merge_abstract

DOSES = [0, 1, 10, 50]
RATS = {"species": "rat", "route": "inhaled", "duration_days": 5}


def _genomics(sex: str) -> dict:
    return {f"liver_{sex}": {
        "gene_sets_by_stat": {"fifth_pct": [{"go_term": "xenobiotic metabolic process",
                                             "bmd": 8.76, "bmdl": 5.96}]},
        "top_genes": [{"gene_symbol": "Cyp2b1", "bmd": 4.84, "bmdl": 2.50, "direction": "up"}]}}


def _apical(sex: str) -> list[dict]:
    return [{"endpoint": "Liver Weight", "sex": sex, "bmd": "19.1", "bmdl": "12.8",
             "bmd_status": "viable", "direction": "increase"}]


def test_a_single_sex_summary_names_no_sex():
    text = build_abstract_summary(_apical("Male"), _genomics("male"), DOSES, "mg/kg",
                                  "fifth_pct", sexes=["Male"], bmd_decimals=1, design=RATS)
    assert text.startswith("Taken together, the most sensitive gene set BMD (BMDL)")
    assert "male" not in text


def test_both_sexes_are_each_named():
    genomics = {**_genomics("male"), **_genomics("female")}
    text = build_abstract_summary(_apical("Male") + _apical("Female"), genomics, DOSES,
                                  "mg/kg", "fifth_pct", sexes=["Male", "Female"],
                                  bmd_decimals=1, design=RATS)
    assert text.startswith("Taken together, in male rats,") and " In female rats," in text


def test_without_genes_the_summary_names_gene_sets_and_apical_endpoints():
    text = build_abstract_summary(_apical("Female"), _genomics("female"), DOSES, "ppm",
                                  "fifth_pct", sexes=["Female"], bmd_decimals=1, design=RATS,
                                  genes=False)
    assert text == ("Taken together, the most sensitive gene set and apical endpoint BMD "
                    "(BMDL) values that could be reliably determined occurred at 8.8 (6.0) "
                    "and 19.1 (12.8) ppm, respectively.")


def test_without_genes_the_results_name_gene_sets_only():
    with_genes = build_abstract_results_genomics(_genomics("female"), DOSES, "ppm", "fifth_pct",
                                                 sexes=["Female"], bmd_decimals=1, design=RATS)
    without = build_abstract_results_genomics(_genomics("female"), DOSES, "ppm", "fifth_pct",
                                              sexes=["Female"], bmd_decimals=1, design=RATS,
                                              genes=False)
    assert "Cyp2b1" in with_genes and "Cyp2b1" not in without
    assert "no Gene Ontology biological process had BMD values below" in without
    assert "xenobiotic metabolic process" in without


def test_a_report_over_studies_states_each_summary_under_its_animals():
    summary = ("Taken together, the most sensitive gene set and apical endpoint BMD (BMDL) "
               "values that could be reliably determined occurred at {} ppm, respectively.")
    studies = [{"title": "Rats", "abstract": {"sections": [
                   {"label": "Summary", "text": summary.format("87.6 (59.6) and 191.4 (127.6)")}]}},
               {"title": "Mice", "abstract": {"sections": [
                   {"label": "Summary", "text": summary.format("1.4 (0.5) and 15.1 (2.2)")}]}}]
    data = {"abstract": {"sections": [{"label": "Background", "text": "B."}]}}
    _merge_abstract(data, studies)
    text = data["abstract"]["sections"][-1]["text"]
    assert text.startswith("Taken together, in rats, the most sensitive gene set")
    assert " In mice, the most sensitive gene set and apical endpoint" in text


def test_an_apical_only_summary_still_names_the_most_sensitive():
    """NIEHS-05: "Taken together, the most sensitive apical endpoint BMD (BMDL)
    value that could be reliably determined occurred at 51.3 (27.0) mg/kg." """
    text = build_abstract_summary(_apical("Male"), {}, DOSES, "mg/kg", "median",
                                  sexes=["Male"], bmd_decimals=1, design=RATS)
    assert text == ("Taken together, the most sensitive apical endpoint BMD (BMDL) value "
                    "that could be reliably determined occurred at 19.1 (12.8) mg/kg.")
