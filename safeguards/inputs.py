"""
safeguards.inputs — the facts a person states about a study, checked before
anything is written: the study design and the experiment details must use the
controlled vocabularies (bmdx_pipe.VOCABULARIES), and name experiments the
dataset has.

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


def require_valid_design(dtxsid: str, fields) -> None:
    """The study design's fields and values (pipeline.study_design.DESIGN_FIELDS,
    the vocabularies)."""
    from bmdx_pipe import VOCABULARIES
    from pipeline.study_design import design_field_errors

    errors = design_field_errors(fields, VOCABULARIES)
    if errors:
        raise _invalid(dtxsid, "the study design", errors)


def require_valid_experiment_metadata(dtxsid: str, given) -> None:
    from bmdx_pipe import VOCABULARIES
    from pipeline.integrated_io import load_integrated

    errors = experiment_metadata_errors(given, load_integrated(dtxsid), VOCABULARIES)
    if errors:
        raise _invalid(dtxsid, "the experiment details", errors)


def _invalid(dtxsid: str, what: str, errors: list[str]) -> Refused:
    return Refused("facts_invalid",
                   f"{what} for {dtxsid} refused: " + "; ".join(errors),
                   status_code=422, details={"what": what, "errors": errors})
