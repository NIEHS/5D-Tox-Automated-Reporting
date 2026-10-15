"""
workflow.integration_basis — what an integration was built from (C1 spec §3.2).

Integration pairs the fingerprints with the validation report's coverage matrix
by FILE ID, and file ids are not stable: a cold re-scan mints new ones, and the
converted pivots get new ones at every validation. So "is the dataset still the
one this validation describes?" cannot be asked by id. The **basis** asks it by
file name: a hash over

  * per file, its fingerprint minus the volatile fields (the id and the
    wall-clock stamps, the same set the Methods cache key drops);
  * the coverage matrix, ids mapped to file names;
  * precedence.json, the chosen file id mapped to its name, the time dropped.

`integrate_step` records the basis it integrated from in
``integration_basis.json`` (an input, like a cache key; never a state). The
engine compares it with the basis of the validation now on disk and derives
``artifacts.integration``:

  * ``"current"``      the recorded basis equals today's;
  * ``"out_of_date"``  it differs: the phase reads VALIDATED (integrate again);
  * ``"unrecorded"``   an integrated.json with no basis file (every session from
                       before C1) — counted as current, so none changes phase;
  * ``None``           no integrated.json.

Not in the basis yet: a person's classification correction (CONFIRM). A
re-validation drops those today, so including them would tie the phase to that
loss; C3 makes them durable, and they join the basis then.
"""

from __future__ import annotations

import hashlib
import json

BASIS_FILE = "integration_basis.json"

# Bump when what the basis covers changes (every recorded basis then reads
# out of date, which asks for a re-integration: visible, never silent).
_BASIS_VERSION = 1

# Fingerprint fields that change per scan or per server process, not with the
# data (pipeline.cache_plumbing._METHODS_VOLATILE_FP_FIELDS, kept equal by a test).
VOLATILE_FP_FIELDS = frozenset({"file_id", "ts_added", "ts_filesystem", "ts_internal"})


def _fp_dict(fp) -> dict:
    """A fingerprint as a plain dict (the validation report holds dicts; a
    store's cache may hold FileFingerprint objects)."""
    if isinstance(fp, dict):
        return fp
    from dataclasses import asdict, is_dataclass
    return asdict(fp) if is_dataclass(fp) else {}


def compute_basis(report: dict | None, precedence: list | None) -> str | None:
    """The basis of a validation report and the conflict choices made on it;
    None when there is no report to integrate from."""
    if not isinstance(report, dict):
        return None
    fps = report.get("fingerprints") or {}
    names = {fid: _fp_dict(fp).get("filename") for fid, fp in fps.items()}

    def name(fid):
        return names.get(fid, fid)

    files = {}
    for fp in fps.values():
        d = _fp_dict(fp)
        files[str(d.get("filename"))] = {k: v for k, v in sorted(d.items())
                                         if k not in VOLATILE_FP_FIELDS}
    coverage = {}
    for key, tiers in (report.get("coverage_matrix") or {}).items():
        coverage[key] = {t: (sorted(str(name(i)) for i in v) if isinstance(v, list)
                             else name(v))
                         for t, v in (tiers or {}).items()}
    choices = sorted(
        ({"issue_index": c.get("issue_index"), "chosen": name(c.get("chosen_file_id"))}
         for c in (precedence or []) if isinstance(c, dict)),
        key=lambda c: json.dumps(c, sort_keys=True, default=str))
    blob = json.dumps({"v": _BASIS_VERSION, "files": files, "coverage": coverage,
                       "choices": choices}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def current_basis(dtxsid: str, store) -> str | None:
    """The basis of the validation on disk now (the store's small reads only)."""
    precedence = store.read_json(dtxsid, "precedence.json")
    return compute_basis(store.read_json(dtxsid, "validation_report.json"),
                         precedence if isinstance(precedence, list) else None)


def integration_status(dtxsid: str, store, *, report=None) -> str | None:
    """``current`` / ``out_of_date`` / ``unrecorded`` / None (module docstring).
    `report` saves a second read when the caller already holds it."""
    if not store.artifact_exists(dtxsid, "integrated.json"):
        return None
    recorded = store.read_json(dtxsid, BASIS_FILE)
    if not isinstance(recorded, dict) or not recorded.get("basis"):
        return "unrecorded"
    if report is None:
        report = store.read_json(dtxsid, "validation_report.json")
    precedence = store.read_json(dtxsid, "precedence.json")
    now = compute_basis(report, precedence if isinstance(precedence, list) else None)
    return "current" if now == recorded["basis"] else "out_of_date"


def record_basis(dtxsid: str, store) -> dict:
    """Record the basis an integration was just built from (integrate_step)."""
    from common.clock import now_iso
    doc = {"basis": current_basis(dtxsid, store), "integrated_at": now_iso()}
    store.write_json(dtxsid, BASIS_FILE, doc)
    return doc
