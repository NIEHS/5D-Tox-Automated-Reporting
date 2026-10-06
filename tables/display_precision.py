"""
tables/display_precision.py — how many decimals an apical table row prints.

NTP summary tables print every mean ± SE in a row at ONE precision, and that
precision belongs to the endpoint, not to the value's magnitude: aspartate
aminotransferase (~80 U/L) prints "82.20 ± 1.88" while cholesterol (~100
mg/dL) and sorbitol dehydrogenase (~11 IU/L) print "103.3 ± 4.4" and
"11.9 ± 0.9"; platelets print whole numbers.  A per-cell magnitude rule
mixed precisions within a row ("97.30 ± 11.70 | 103.4 ± 12.6").

``PUBLISHED_DECIMALS`` is that convention as the CEBS summary tables of
NIEHS-07, -08, -09, -10, -12 and -13 print it (PA06/PA41/PA43/hormone
summaries; every endpoint listed prints at the same precision in every
report).  An endpoint it does not list takes the precision its individual
values are recorded with (at least 1 decimal) — e.g. reticulocytes, which
print 1 decimal in K/uL (NIEHS-07–09) but 4 in 10^6/uL (NIEHS-13), and are
recorded to 4 decimals in the latter.
"""

from __future__ import annotations

import re

# Endpoint (lower-case, units and other parentheticals removed) -> decimals.
PUBLISHED_DECIMALS: dict[str, int] = {
    # Clinical chemistry
    "a/g ratio": 2,
    "alanine aminotransferase": 1,
    "albumin": 2,
    "alkaline phosphatase": 1,
    "aspartate aminotransferase": 2,
    "bile salts/acids": 1,
    "cholesterol": 1,
    "creatinine": 2,
    "globulin": 2,
    "glucose": 1,
    "sorbitol dehydrogenase": 1,
    "triglycerides": 1,
    "urea nitrogen": 1,
    # Hematology
    "basophil count": 2,
    "eosinophil count": 2,
    "erythrocyte count": 2,
    "hematocrit": 1,
    "hemoglobin": 1,
    "large unstained cell count": 2,
    "leukocyte count": 2,
    "manual hematocrit": 1,
    "mean cell hemoglobin": 1,
    "mean cell hgb concentration": 1,
    "monocyte count": 2,
    "neutrophil count": 2,
    "platelet count": 0,
    # Hormones
    "free thyroxine": 3,
    "thyroid stimulating hormone": 3,
    "total thyroxine": 2,
    "triiodothyronine": 3,
    "total triiodothyronine": 3,
    # Weights
    "body weight": 1,
    "body weight gain": 1,
    "terminal body weight": 1,
}

# Organ weights (absolute g, relative mg/g) print 2 decimals in every report.
ORGAN_WEIGHT_DECIMALS = 2


def endpoint_key(label: str) -> str:
    """"Globulin (measured) (g/dL)" -> "globulin"."""
    return re.sub(r"\s+", " ", re.sub(r"\([^)]*\)", " ", str(label or ""))).strip().lower()


def row_decimals(label: str, recorded: int | None = None) -> int | None:
    """The precision one table row prints at: the published convention for a
    known endpoint, 2 for an organ weight, else the recorded precision of the
    endpoint's individual values (at least 1).  None when none of these
    applies (the caller then keeps one precision across the row itself)."""
    key = endpoint_key(label)
    if key in PUBLISHED_DECIMALS:
        return PUBLISHED_DECIMALS[key]
    if re.search(r"\b(absolute|relative)\b", key):
        return ORGAN_WEIGHT_DECIMALS
    if recorded is not None:
        return max(1, recorded)
    return None


def recorded_decimals(values) -> int | None:
    """The most decimals any of the individual values is recorded with
    ("0.2350" -> 4, "11" -> 0); None when there are no numeric values.  Takes
    the maximum because exports drop trailing zeros ("0.235" for 0.2350)."""
    best: int | None = None
    for v in values:
        s = str(v).strip() if v is not None else ""
        try:
            float(s)
        except ValueError:
            continue
        d = len(s.split(".", 1)[1]) if "." in s else 0
        best = d if best is None else max(best, d)
    return best
