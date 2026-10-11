"""
tables/units.py — measurement units as the data records them, written for print.

Units come from the study workbook's Key sheet, carried in each sidecar's
"units" map ({endpoint: unit}; bmdx_pipe.key_sheet_units).  They are written
as the lab system types them ("ug/ml", "K/uL"); NIEHS reports print SI
spelling ("µg/mL", "K/µL").  Nothing here supplies a unit the data does not
state: an unrecorded unit is None, and the caller flags it.
"""

from __future__ import annotations

import re

# Lab-system spelling -> printed spelling, per "/"-separated unit token.
_TOKENS = {"ml": "mL", "dl": "dL", "ul": "µL", "l": "L", "ug": "µg", "mcg": "µg"}

# The visible marker a table prints when its data record no unit
# (render_common.scan_pending_markers blocks a strict build on it).
UNIT_NOT_RECORDED = "[Placeholder: {what} unit not recorded in the data]"


def display_unit(unit: str) -> str:
    """"ug/ml" -> "µg/mL", "ng/ml" -> "ng/mL", "K/uL" -> "K/µL"; others as written."""
    return "/".join(_TOKENS.get(t.lower(), t) for t in re.split(r"/", unit.strip()))


def recorded_units(sidecars, endpoint_filter) -> dict[str, str]:
    """{endpoint: printed unit} across sidecars, for endpoints `endpoint_filter`
    accepts."""
    out: dict[str, str] = {}
    for sc in sidecars:
        for ep, unit in ((sc or {}).get("units") or {}).items():
            if unit and endpoint_filter(ep):
                out[ep] = display_unit(unit)
    return out
