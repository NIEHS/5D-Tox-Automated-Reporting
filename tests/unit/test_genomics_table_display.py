"""Genomics table labels follow the analysis, not the NIEHS-10 constants.

An entry without `display` (legacy) keeps the reference headers verbatim; a
2025-method entry (5th-percentile ranking, 25% relative-deviation BMR, ppm)
is labelled accordingly, prints Entrez IDs, and shows a non-convergent upper
bound as "NC".
"""

from rendering.render_common import (
    GENE_SET_TABLE_HEADERS, GENE_TABLE_HEADERS, gene_set_table_headers, gene_table_headers,
    gene_table_rows, gene_set_table_rows, genomics_table_caption,
)

DISPLAY = {"stat": "fifth_pct", "bmr": {"type": "Relative Deviation", "factor": 0.25},
           "unit": "ppm", "decimals": 1}


def test_legacy_entry_keeps_reference_headers():
    assert gene_set_table_headers({}) == GENE_SET_TABLE_HEADERS
    assert gene_table_headers({}) == GENE_TABLE_HEADERS


def test_2025_entry_is_labelled_by_stat_bmr_and_unit():
    e = {"type": "gene_set", "organ": "liver", "display": DISPLAY}
    h = gene_set_table_headers(e)
    assert h[4] == "BMDrd25 5th Percentile of Gene Set Transcripts (ppm)"
    assert h[5] == "5th Percentile BMDLrd25–BMDUrd25 (ppm)"
    assert gene_table_headers(e)[3] == "BMDrd25 (BMDLrd25–BMDUrd25) in ppm"
    # As NIEHS-12 and 13 print it (a median reads "Benchmark Dose Median").
    assert genomics_table_caption(e).endswith("Sorted by 5th Percentile Benchmark Dose")


def test_2025_rows_use_entrez_ids_one_decimal_and_nc():
    e = {"type": "gene", "organ": "liver", "display": DISPLAY, "sexes": [{"sex": "Female", "top_genes": [
        {"gene": "Cyp2b1", "entrez_id": "24300", "probe_id": "CYP2B1_32451,CYP2B2_32473",
         "bmd": 69.87, "bmdl": 43.91, "bmdu": None, "fold_change": 195.04, "direction": "up"}]}]}
    row = gene_table_rows(e)[1]
    assert row[:4] == ["Cyp2b1", "24300", "CYP2B1_32451, CYP2B2_32473", "69.9 (43.9–NC)"]
    gs = {"type": "gene_set", "display": DISPLAY, "sexes": [{"sex": "Female", "gene_sets": [
        {"go_id": "GO:1", "go_term": "t", "n_genes": 59, "n_genes_with_bmd": 20,
         "bmd": 87.62, "bmdl": 59.57, "bmdu": 136.71, "n_up": 18, "n_down": 2}]}]}
    assert gene_set_table_rows(gs)[1][4:] == ["87.6", "59.6–136.7", "18", "2"]
