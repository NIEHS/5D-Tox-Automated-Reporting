"""Mean ± SE prints at one precision per row — the endpoint's, as the NTP
summaries print it — not per cell by magnitude.

NIEHS-13 printed "97.30 ± 11.70 | 103.4 ± 12.6" in one AST row; the published
summaries (NIEHS-07…13) give every endpoint one precision: AST 2, cholesterol
and SDH 1, platelets 0, organ weights 2, body weight 1.
"""

from tables.display_precision import endpoint_key, recorded_decimals, row_decimals
from tables.table_builder_common import format_row_cell


def test_published_convention_is_per_endpoint_not_magnitude():
    assert row_decimals("Aspartate Aminotransferase") == 2      # ~80 U/L
    assert row_decimals("Cholesterol (mg/dL)") == 1              # ~100 mg/dL
    assert row_decimals("Sorbitol dehydrogenase") == 1           # ~11 IU/L
    assert row_decimals("Platelet count (K/uL)") == 0
    assert row_decimals("Kidney-Left Absolute (g)") == 2         # ~0.6 g
    assert row_decimals("Liver Relative (mg/g)") == 2
    assert row_decimals("Terminal Body Weight (g)") == 1
    assert endpoint_key("Globulin (measured) (g/dL)") == "globulin"


def test_unlisted_endpoint_takes_its_recorded_precision():
    # Reticulocytes print 1 decimal in K/uL but 4 in 10^6/uL (NIEHS-13), so
    # they are not in the table; NIEHS-13 records them to 4 decimals.
    assert recorded_decimals(["0.235", "0.2241", "NA", None, "0.25"]) == 4
    assert row_decimals("Reticulocyte count", 4) == 4
    # Total protein is recorded to 1 decimal but printed to 2 (every PA41).
    assert row_decimals("Total protein", 1) == 2
    assert row_decimals("Creatine kinase", 0) == 1   # at least one decimal
    assert row_decimals("Mystery") is None


def test_cell_formats_from_unrounded_stats_and_keeps_marker():
    assert format_row_cell("103.4 ± 12.6*", 2, stats=[103.4, 12.5712]) == "103.40 ± 12.57*"
    assert format_row_cell("10.21 ± 0.64**", 1, stats=[10.21, 0.6449]) == "10.2 ± 0.6**"
    assert format_row_cell("", 2, values=[0.6, 0.64]) == "0.62 ± 0.02"
    assert format_row_cell("5.0", 1, stats=[5.0, None]) == "5.0"
    assert format_row_cell("as is", None, stats=[1.0, 0.1]) == "as is"


def test_tissue_concentration_prints_three_significant_figures():
    # Published PA48 cells (NIEHS-08/-10/-12): mean and SE rounded independently.
    from tables.table_builder_common import format_mean_se_display, format_mean_se_sig

    nb = " ± "
    assert format_mean_se_sig(33.833, 4.4333) == f"33.8{nb}4.43"
    assert format_mean_se_sig(137.2, 10.64) == f"137{nb}10.6"
    assert format_mean_se_sig(49.997, 19.41) == f"50.0{nb}19.4"
    assert format_mean_se_sig(19473, 700.2) == f"19500{nb}700"
    assert format_mean_se_sig(0.03051, 0.006472) == f"0.0305{nb}0.00647"
    assert format_mean_se_sig(31.9, 3.09) == f"31.9{nb}3.09"
    # The render-time re-round keeps a builder's sig-fig cell as it is.
    assert format_mean_se_display(f"33.8{nb}4.43", None, 3) == f"33.8{nb}4.43"
