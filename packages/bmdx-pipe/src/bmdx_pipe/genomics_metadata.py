"""bmdx_pipe.genomics_metadata — reconcile the genomics sidecar's organ/sex with
the project's ExperimentDescription metadata.

ExportGenomics.java parses organ and sex from the experiment NAME, assuming the
`Organ_Chem_Sex_No0` convention (e.g. `Kidney_PFHxSAm_Male_No0`).  Other naming
conventions — e.g. `Triclosan_S1_AA_Kidney_No0` — come out as organ = chemical
name and sex = "Unknown", which also collapses every organ into one section
downstream (sections are keyed organ_sex).  The annotated ExperimentDescription
already carries the correct organ (and sex, when stated), so it is the authority.

Sex inheritance (flagged): when a genomics experiment states no single sex and
every sexed experiment in the study is ONE sex (e.g. all-male apical data), the
genomics experiment inherits that sex.  This is an INFERENCE — the data does not
link transcriptomic samples to animals — so it is recorded in
`_meta.inferred.genomics_sex` (not inside experimentDescription, which is
round-tripped through Java/Jackson into the .bm2) for surfacing and sign-off.
A sample→animal manifest, when one exists, should supersede it.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_SINGLE_SEXES = ("male", "female")


def _single_sex(desc: dict) -> str | None:
    sex = str((desc or {}).get("sex") or "").strip().lower()
    return sex if sex in _SINGLE_SEXES else None


def study_single_sex(experiments: list[dict]) -> str | None:
    """The one sex every sexed experiment shares, or None (mixed, or no sexes)."""
    sexes = {_single_sex(e.get("experimentDescription")) for e in experiments}
    sexes.discard(None)
    return sexes.pop() if len(sexes) == 1 else None


def reconcile_genomics_sidecar(integrated: dict, sidecar_path: str) -> dict:
    """Rewrite the genomics sidecar's per-experiment organ/sex from the project
    metadata, inheriting the study's single sex where genomics states none.

    Mutates `integrated` (genomics experimentDescription.sex for inherited sex,
    plus `_meta.inferred.genomics_sex`) and rewrites the sidecar in place.
    Returns {experiment_name: inherited_sex} for the experiments whose sex was
    inferred (empty when nothing was).  No-op if the sidecar is absent."""
    if not os.path.exists(sidecar_path):
        return {}
    with open(sidecar_path, encoding="utf-8") as f:
        sidecar = json.load(f)

    experiments = integrated.get("doseResponseExperiments", []) or []
    by_name = {e.get("name"): e for e in experiments}
    inherited_sex = study_single_sex(experiments)
    inferred: dict[str, str] = {}
    changed = False

    for sexp in sidecar.get("experiments", []) or []:
        exp = by_name.get(sexp.get("name"))
        if exp is None:
            continue
        desc = exp.setdefault("experimentDescription", {}) or {}
        exp["experimentDescription"] = desc

        organ = str(desc.get("organ") or "").strip()
        if organ and "," not in organ and sexp.get("organ") != organ.title():
            sexp["organ"] = organ.title()
            changed = True

        sex = _single_sex(desc)
        if sex is None and inherited_sex:
            sex = inherited_sex
            desc["sex"] = inherited_sex
            inferred[exp["name"]] = inherited_sex
        if sex and sexp.get("sex") != sex.title():
            sexp["sex"] = sex.title()
            changed = True

    if inferred:
        meta = integrated.setdefault("_meta", {})
        meta.setdefault("inferred", {})["genomics_sex"] = {
            name: {"sex": s, "basis": "study-single-sex"} for name, s in inferred.items()
        }
        logger.info("Genomics sex inferred from the study's single sex: %s", inferred)

    if changed:
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(sidecar, f, indent=2)
    return inferred
