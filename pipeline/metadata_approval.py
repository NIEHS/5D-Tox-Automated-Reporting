"""pipeline/metadata_approval.py — record approved experiment metadata.

One implementation for the browser's approval (POST /api/experiment-metadata)
and the headless `generate_report --experiment-metadata`: the descriptions go
onto integrated.json, the genomics sidecar's organ/sex are reconciled with them,
the .bm2 is re-exported, and metadata_approved.json keeps the descriptions so
every later integration re-applies them (workflow.steps.integrate_step).
"""

from __future__ import annotations

import json
import logging

from common.clock import now_iso
from pipeline.integrated_io import load_integrated, save_integrated
from pipeline.session_store import session_dir

logger = logging.getLogger(__name__)

APPROVAL_FILE = "metadata_approved.json"


def approve_experiment_metadata(dtxsid: str, metadata_by_name: dict, *, merge: bool = False) -> dict:
    """Apply ``{experiment name: description}`` and record the approval.

    ``merge`` lays the given fields over each experiment's current description
    (a stated organ or sex); otherwise the given description replaces it, as
    the browser's form sends the whole description.

    Returns {"updated": n, "bm2_exported": bool}.  Raises LookupError when the
    session has no integrated data.
    """
    integrated = load_integrated(dtxsid)
    if integrated is None:
        raise LookupError("No integrated data found")
    sess_path = session_dir(dtxsid)

    updated = 0
    for exp in integrated.get("doseResponseExperiments", []):
        name = exp.get("name", "")
        if name in metadata_by_name:
            given = metadata_by_name[name]
            exp["experimentDescription"] = (
                {**(exp.get("experimentDescription") or {}), **given} if merge else given)
            updated += 1

    # The genomics sidecar was written at integration from the metadata of
    # that moment; carry the approved organ/sex onto it (rewritten only when
    # something changed — its mtime keys the genomics cache).
    from bmdx_pipe.genomics_metadata import reconcile_genomics_sidecar
    from pipeline.processing_helpers import GENOMICS_SIDECAR_NAME
    reconcile_genomics_sidecar(integrated, str(sess_path / GENOMICS_SIDECAR_NAME))

    # Schema-validating writer (ADR-0001): a description that violates the
    # schema fails BEFORE disk is touched.
    save_integrated(dtxsid, integrated)

    bm2_ok = False
    try:
        from bmdx_pipe import export_integrated_bm2
        export_integrated_bm2(str(sess_path / "integrated.json"), str(sess_path / "integrated.bm2"))
        bm2_ok = True
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to re-export .bm2 after metadata edit: %s", e)

    record = {
        "approved_at": now_iso(),
        "experiments_updated": updated,
        # The approved descriptions, re-applied by every later integration.
        "metadata": {
            exp.get("name", ""): exp.get("experimentDescription")
            for exp in integrated.get("doseResponseExperiments", [])
            if exp.get("name", "") in metadata_by_name
        },
    }
    (sess_path / APPROVAL_FILE).write_text(json.dumps(record, indent=2), encoding="utf-8")
    logger.info("Metadata approved for %s: %d experiments updated, bm2=%s",
                dtxsid, updated, "ok" if bm2_ok else "failed")
    return {"updated": updated, "bm2_exported": bm2_ok}
