"""
safeguards.inputs — the facts a person states about a study, checked before
anything is written: the study design and the experiment details must use the
controlled vocabularies (bmdx_pipe.VOCABULARIES), and name experiments the
dataset has.

A statement may not contradict what the study workbooks state (ADR-0032):
species, strain, route, duration, an experiment's sex.  Those are the study's
own record; a contradiction is refused (``facts_contradict_workbook``).

A reviewer's decisions on flagged apical BMDs (pipeline.bmd_review) are
checked the same way: each names an endpoint the last Process flagged, is
"unreliable" (UREP) or "reliable", and gives the reviewer's reason
(``bmd_review_invalid``).

A refused statement writes nothing; the refusal (``facts_invalid``) lists
every problem at once, so a person corrects them in one go. The core steps
(workflow.steps.record_study_design, pipeline.metadata_approval) write what
they are given: the notebook states facts unchecked.
"""

from __future__ import annotations

from safeguards.refusals import Refused


def _allowed(vocab) -> list:
    """A vocabulary's values: a list, or a dict of lists (strain: by species)."""
    if isinstance(vocab, dict):
        return [v for vs in vocab.values() for v in vs]
    return list(vocab or [])


def _stated(value) -> bool:
    return value is not None and value != ""


def experiment_metadata_errors(given, integrated: dict | None, vocabularies: dict) -> list[str]:
    """Why ``{experiment name: {field: value}}`` can't be stated: not that
    shape, an experiment the dataset lacks, or a new value outside its
    vocabulary. A value the experiment already carries is not a new statement,
    so it is not checked (the dataset's own inferred values pass through)."""
    if not isinstance(given, dict) or not all(isinstance(v, dict) for v in given.values()):
        return ["expected {experiment name: {field: value}}"]
    experiments = {e.get("name"): (e.get("experimentDescription") or {})
                   for e in (integrated or {}).get("doseResponseExperiments") or []}
    errors = [f"unknown experiment {n!r}" for n in given if n not in experiments]
    for name, fields in given.items():
        current = experiments.get(name) or {}
        for key, value in fields.items():
            allowed = _allowed(vocabularies.get(key))
            if (allowed and _stated(value) and value != current.get(key)
                    and value not in allowed):
                errors.append(f"{name}: {key}={value!r} is not in the vocabulary")
    return errors


def workbook_contradictions(given: dict, integrated: dict | None) -> list[str]:
    """Where ``{experiment name: {field: value}}`` contradicts what the study
    workbooks state for the dataset (pipeline.study_design.workbook_facts)."""
    from pipeline.study_design import workbook_facts

    facts = workbook_facts(integrated)
    out = []
    for name, fields in (given or {}).items():
        for key, value in (fields or {}).items():
            stated = (facts.get(name) or {}).get(key)
            if stated is not None and _stated(value) and value != stated:
                out.append(f"{name}: {key}={value!r}, but the study workbooks state {stated!r}")
    return out


def require_valid_design(dtxsid: str, fields) -> None:
    """The study design's fields and values (pipeline.study_design.DESIGN_FIELDS,
    the vocabularies), and no field the study workbooks state otherwise."""
    from bmdx_pipe import VOCABULARIES
    from pipeline.integrated_io import load_integrated
    from pipeline.study_design import design_field_errors

    errors = design_field_errors(fields, VOCABULARIES)
    if errors:
        raise _invalid(dtxsid, "the study design", errors)
    integrated = load_integrated(dtxsid)
    names = [e.get("name", "") for e in (integrated or {}).get("doseResponseExperiments") or []]
    contradictions = sorted({c.split(": ", 1)[1] for c in workbook_contradictions(
        {n: fields for n in names}, integrated)})
    if contradictions:
        raise _contradicts(dtxsid, "the study design", contradictions)


def require_valid_experiment_metadata(dtxsid: str, given) -> None:
    from bmdx_pipe import VOCABULARIES
    from pipeline.integrated_io import load_integrated

    integrated = load_integrated(dtxsid)
    errors = experiment_metadata_errors(given, integrated, VOCABULARIES)
    if errors:
        raise _invalid(dtxsid, "the experiment details", errors)
    contradictions = workbook_contradictions(given, integrated)
    if contradictions:
        raise _contradicts(dtxsid, "the experiment details", contradictions)


def _contradicts(dtxsid: str, what: str, errors: list[str]) -> Refused:
    return Refused("facts_contradict_workbook",
                   f"{what} for {dtxsid} refused: " + "; ".join(errors),
                   status_code=422, details={"what": what, "errors": errors})


def _invalid(dtxsid: str, what: str, errors: list[str]) -> Refused:
    return Refused("facts_invalid",
                   f"{what} for {dtxsid} refused: " + "; ".join(errors),
                   status_code=422, details={"what": what, "errors": errors})


def bmd_review_errors(decisions, flags: list[dict]) -> list[str]:
    """What is wrong with ``{key: {decision, reason}}`` against the last
    screen's ``flags``: every problem, so a reviewer fixes them in one go."""
    from pipeline.bmd_review import DECISIONS

    if not isinstance(decisions, dict) or not decisions:
        return ["no decisions were given"]
    flagged = {f["key"] for f in flags}
    errors = []
    for key, given in decisions.items():
        if key not in flagged:
            errors.append(f"{key} is not a BMD the last Process flagged")
            continue
        given = given if isinstance(given, dict) else {}
        if given.get("decision") not in DECISIONS:
            errors.append(f"{key}: the decision must be “unreliable” or “reliable”")
        if not str(given.get("reason") or "").strip():
            errors.append(f"{key}: the reviewer's reason is missing")
    return errors


def require_valid_bmd_review(dtxsid: str, decisions, flags: list[dict]) -> None:
    """Refuse (``bmd_review_invalid``) a review with any problem; nothing is written."""
    errors = bmd_review_errors(decisions, flags)
    if errors:
        raise Refused("bmd_review_invalid",
                      f"BMD review for {dtxsid} refused: " + "; ".join(errors),
                      status_code=422, details={"errors": "; ".join(errors)})
