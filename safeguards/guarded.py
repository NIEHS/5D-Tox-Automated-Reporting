"""
safeguards.guarded — the workflow's acts, guarded: the one entry point for a
front end (the web routes, the command line).

Each function has the name and signature of the core step it guards
(workflow.steps, pipeline.process_integrated, pipeline.pool_state,
pipeline.metadata_approval): it runs the act's checks (safeguards.acts: R6,
the phase, the person's method choice; safeguards.sections: ownership and
reasons), then calls the core step, passing the C2 write policy where the step
writes sections. A refusal is raised before anything is read or written; it
carries a code that safeguards.refusals explains.

The notebook calls the core steps directly: the same workflow, unguarded.
"""

from __future__ import annotations

from safeguards.acts import require
from safeguards.inputs import (
    require_valid_bmd_review, require_valid_design, require_valid_experiment_metadata,
)
from safeguards.sections import ownership_policy, owned, require_reason
from workflow import steps as _steps
from workflow.phases import Action


# --- files ------------------------------------------------------------------

def require_add_files(dtxsid: str, store=None) -> None:
    """Bringing files into a study (R6; ADD_FILES is legal in every phase of
    a study whose data is its own)."""
    require(dtxsid, Action.ADD_FILES, store)


def require_reset(dtxsid: str, store=None) -> None:
    """Clearing a study's files and all derived from them."""
    require(dtxsid, Action.RESET, store)


def remove_pool_file(dtxsid: str, filename: str) -> dict:
    from pipeline.pool_state import remove_pool_file as _remove
    require(dtxsid, Action.REMOVE_FILE)
    return _remove(dtxsid, filename)


def validate_step(dtxsid: str, store) -> dict:
    require(dtxsid, Action.VALIDATE, store)
    return _steps.validate_step(dtxsid, store)


def resolve_step(dtxsid: str, issue_index, chosen_file_id: str, store) -> dict:
    require(dtxsid, Action.RESOLVE, store)
    return _steps.resolve_step(dtxsid, issue_index, chosen_file_id, store)


def confirm_metadata_step(dtxsid: str, confirmed: dict, store) -> dict:
    require(dtxsid, Action.CONFIRM_CLASSIFICATION, store)
    return _steps.confirm_metadata_step(dtxsid, confirmed, store)


# --- the dataset --------------------------------------------------------------

def integrate_step(dtxsid: str, identity: dict | None, store) -> dict:
    require(dtxsid, Action.INTEGRATE, store)
    return _steps.integrate_step(dtxsid, identity, store)


def approve_experiment_metadata(dtxsid: str, metadata_by_name: dict, *, merge: bool = False):
    """Stating the experiment details onto the dataset (STATE_DATASET_FACTS):
    experiments the dataset has, values from the vocabularies."""
    from pipeline.metadata_approval import approve_experiment_metadata as _approve
    require(dtxsid, Action.STATE_DATASET_FACTS)
    require_valid_experiment_metadata(dtxsid, metadata_by_name)
    return _approve(dtxsid, metadata_by_name, merge=merge)


def record_study_design(dtxsid: str, fields: dict, store) -> int:
    """Stating the study design onto the dataset: its fields, from the
    vocabularies."""
    require(dtxsid, Action.STATE_DATASET_FACTS, store)
    require_valid_design(dtxsid, fields)
    return _steps.record_study_design(dtxsid, fields, store)


def review_bmds(dtxsid: str, decisions: dict, store) -> dict:
    """A reviewer's decisions on the apical BMDs the last Process flagged
    (pipeline.bmd_review): each ``{key: {decision, reason}}``, "unreliable"
    (UREP) or "reliable", with the reviewer's reason.  Recorded only; the next
    Process applies them (the publish gate waits for it)."""
    from pipeline.bmd_review import FLAGS_FILE, record_reviews
    require(dtxsid, Action.PROCESS, store)
    flags = (store.read_json(dtxsid, FLAGS_FILE) or {}).get("flags") or []
    require_valid_bmd_review(dtxsid, decisions, flags)
    return record_reviews(store, dtxsid, decisions, flags)


def require_state_dataset_facts(dtxsid: str, store=None) -> None:
    """Stating a fact onto the dataset (the study design, the experiment
    details): it needs a usable dataset."""
    require(dtxsid, Action.STATE_DATASET_FACTS, store)


def generate_animal_report_step(dtxsid: str, store) -> dict:
    require(dtxsid, Action.APPROVE, store)
    return _steps.generate_animal_report_step(dtxsid, store)


# --- Process --------------------------------------------------------------------

async def run_process(dtxsid: str, params: dict, store) -> dict:
    from pipeline.process_integrated import run_process as _run
    require(dtxsid, Action.PROCESS, store, method=True)
    return await _run(dtxsid, params, store)


async def run_document(dtxsid: str, params: dict, store) -> dict:
    from pipeline.process_integrated import run_document as _run
    require(dtxsid, Action.PROCESS, store, method=True)
    return await _run(dtxsid, params, store)


async def process_step(dtxsid: str, params: dict, store) -> dict:
    require(dtxsid, Action.PROCESS, store, method=True)
    return await _steps.process_step(dtxsid, params, store)


async def document_step(dtxsid: str, params: dict, store) -> dict:
    require(dtxsid, Action.PROCESS, store, method=True)
    return await _steps.document_step(dtxsid, params, store)


def materialize_result_sections(dtxsid: str, store) -> dict:
    require(dtxsid, Action.PROCESS, store)
    return _steps.materialize_result_sections(dtxsid, store, policy=ownership_policy)


def materialize_summary(dtxsid: str, store) -> dict:
    require(dtxsid, Action.PROCESS, store)
    return _steps.materialize_summary(dtxsid, store, policy=ownership_policy)


# --- sections -------------------------------------------------------------------

def write_section(dtxsid: str, key: str, content: dict, store, **kw) -> dict:
    """A write to a section under the C2 policy (a person's or a machine's)."""
    from workflow.section_writes import write_section as _write
    return _write(dtxsid, key, content, store, policy=ownership_policy, **kw)


def accept_section_step(dtxsid: str, section_key: str, store) -> dict:
    return _steps.accept_section_step(dtxsid, section_key, store)


def release_section_step(dtxsid: str, section_key: str, store, *, reason: str = "") -> dict:
    """Reopening an approved section needs a reason (C2 D3)."""
    from workflow import section_writes as sw
    if section_key and sw.validate_section_key(dtxsid, section_key):
        prior = sw.read_prior(dtxsid, section_key, store)
        if prior is not None and prior.get("approved"):
            require_reason(reason, section_key, "reopen")
    return _steps.release_section_step(dtxsid, section_key, store, reason=reason)


def restore_section_step(dtxsid: str, section_key: str, version, store, *,
                         reason: str = "") -> dict:
    """Restoring a past version needs a reason (C2 D3); it never replaces
    content a person owns without one."""
    from workflow import section_writes as sw
    key = sw.validate_section_key(dtxsid, section_key)
    current = sw.read_prior(dtxsid, key, store)
    if current is None or current.get("version") != version:
        require_reason(reason, key, "restore")
    return _steps.restore_section_step(dtxsid, key, version, store, reason=reason,
                                       policy=ownership_policy)


def discard_section_step(dtxsid: str, section_key: str, store, *, reason: str = "") -> dict:
    """An approved section is released before it is discarded; a discard needs
    a reason."""
    from workflow import section_writes as sw
    key = sw.validate_section_key(dtxsid, section_key)
    current = sw.read_prior(dtxsid, key, store)
    if current is None:
        raise sw.not_found(key, "discard")
    if sw.is_locked(current):
        raise owned(key, "discard")
    require_reason(reason, key, "discard")
    return _steps.discard_section_step(dtxsid, key, store, reason=reason)
