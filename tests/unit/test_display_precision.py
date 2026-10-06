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
    assert row_decimals("Total protein", 0) == 1     # at least one decimal
    assert row_decimals("Mystery") is None


def test_cell_formats_from_unrounded_stats_and_keeps_marker():
    assert format_row_cell("103.4 ± 12.6*", 2, stats=[103.4, 12.5712]) == "103.40 ± 12.57*"
    assert format_row_cell("10.21 ± 0.64**", 1, stats=[10.21, 0.6449]) == "10.2 ± 0.6**"
    assert format_row_cell("", 2, values=[0.6, 0.64]) == "0.62 ± 0.02"
    assert format_row_cell("5.0", 1, stats=[5.0, None]) == "5.0"
    assert format_row_cell("as is", None, stats=[1.0, 0.1]) == "as is"
