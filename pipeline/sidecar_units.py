"""
sidecar_units.py — measurement units onto the per-animal sidecars, at integration.

The derived truth CSVs carry the workbook's Data-sheet headers, which have no
units; the units live in the study workbook's "Key to Column Labels" sheet and
differ between studies (plasma concentration: ng/ml in NIEHS-07 – -09, ug/ml in
NIEHS-10).  A sidecar gets them at ingest from a companion "<csv>.units.json"
(pipeline.pool_fingerprints), or here, when the pool holds the platform's
original study workbook — the source of truth the CSV was derived from
(pipeline.value_validation cross-checks their values).  Where both state a
unit, the workbook's wins.  A unit stated nowhere stays unrecorded; the report
then flags it instead of assuming one.
"""

from __future__ import annotations

import json
import logging

from bmdx_pipe import key_sheet_units

from pipeline.value_validation import study_workbooks
from tables.table_builder_common import find_sidecar_paths, load_sidecar

logger = logging.getLogger(__name__)


def stamp_sidecar_units(fps, session_dir) -> dict[str, int]:
    """Write each study workbook's Key-sheet units into its platform's sidecars
    ("units": {endpoint: unit}, for the endpoints the sidecar records).
    Returns {sidecar path: units written} for the sidecars it changed."""
    changed: dict[str, int] = {}
    for platform, (xlsx_path, _fid) in study_workbooks(fps, session_dir).items():
        units = key_sheet_units(xlsx_path)
        if not units:
            continue
        for sc_path in find_sidecar_paths(str(session_dir), platform).values():
            sidecar = load_sidecar(sc_path)
            endpoints = {o.get("endpoint") for a in sidecar.get("animals", {}).values()
                         for o in a.get("observations", [])}
            stated = {ep: u for ep, u in units.items() if ep in endpoints}
            current = sidecar.get("units") or {}
            for ep, u in stated.items():
                if current.get(ep) not in (None, u):
                    logger.warning("%s: %s unit %r replaced by the study workbook's %r",
                                   platform, ep, current[ep], u)
            merged = {**current, **stated}
            if merged == current:
                continue
            sidecar["units"] = merged
            with open(sc_path, "w") as f:
                json.dump(sidecar, f, indent=2)
            changed[sc_path] = len(stated)
    return changed
