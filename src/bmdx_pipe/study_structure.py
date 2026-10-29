"""
study_structure — the study the workbooks describe, and every file checked against it.

The study workbooks (study_workbook) are the study team's own record, one per
platform.  Together they say what the study is: its number and title, the dose
unit, the design the title states (species, strain, route, duration), the dose
groups and sexes, and every animal with its sex, dose and group.  That is the
structure the other files are derived from — the BMDExpress pivots, the
BMDExpress projects (.bm2), the genomic samples — so each is checked against it
(check_against_structure).  A contradiction is an error: the report would be
built on data that does not trace to the study.

The workbooks must agree with each other first.  A second study number, a
second dose unit, a title stating another design, or one animal under two sexes
or doses is listed under ``conflicts``.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import asdict, dataclass, field

# The design facts a title states (study_workbook.title_facts) that hold for
# the whole study; "sex" is per workbook (a study may be single-sex per file).
_DESIGN_FIELDS = ("species", "strain", "articleRoute", "administrationMeans", "studyDuration")

# How many animals an issue names before "…".
_MAX_NAMED = 8

# Endpoints the pool derives from a workbook's own (long_rows_to_pivot), so a
# file may carry them though no workbook column is named so.
_DERIVED = {"Body Weight": {"Body Weight Gain"}}


@dataclass
class StudyStructure:
    study_number: str | None = None
    title: str | None = None
    dose_unit: str | None = None
    # The design facts the titles state, in the metadata vocabulary.
    design: dict[str, str] = field(default_factory=dict)
    sexes: list[str] = field(default_factory=list)
    dose_groups: list[float] = field(default_factory=list)
    # {animal id: {"sex": "Male", "dose": 4.0, "selection": "Core Animals"}}
    animals: dict[str, dict] = field(default_factory=dict)
    # {platform: {"workbook", "endpoints", "units", "days"}}
    platforms: dict[str, dict] = field(default_factory=dict)
    # The study's sample sheet(s): {sample key: {"sample", "animal_id", "tissue"}}
    # (sample_sheet).  Maps a genomic sample to its animal.
    samples: dict[str, dict] = field(default_factory=dict)
    # Where the workbooks disagree: [{"kind", "message", "workbooks"}]
    conflicts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "StudyStructure | None":
        if not d:
            return None
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})

    def roster(self, sex: str | None = None) -> set[str]:
        return {a for a, rec in self.animals.items() if sex is None or rec.get("sex") == sex}


def build_study_structure(workbooks: dict[str, str],
                          sample_sheets: list[str] | None = None) -> StudyStructure:
    """The structure the study workbooks describe.

    Args:
        workbooks:     {path: platform} of the pool's study workbooks.
        sample_sheets: paths of the pool's sample sheets (sample_sheet), which
                       map genomic samples to animals.
    """
    from .sample_sheet import read_sample_sheet
    from .study_workbook import read_study_workbook

    st = StudyStructure()
    for path in sample_sheets or []:
        st.samples.update(read_sample_sheet(path))
    numbers: dict[str, list[str]] = {}
    units: dict[str, list[str]] = {}
    titles: dict[str, list[str]] = {}
    design: dict[str, dict[str, list[str]]] = {f: {} for f in _DESIGN_FIELDS}
    seen: dict[str, tuple[dict, str]] = {}      # animal → (record, workbook)
    clashes: dict[str, set[str]] = {}            # "sex"/"dose" → animals
    clash_books: set[str] = set()
    doses: set[float] = set()
    sexes: set[str] = set()

    for path, platform in sorted(workbooks.items()):
        name = os.path.basename(path)
        wb = read_study_workbook(path)
        for n in ([wb.study_number] if wb.study_number else []) + wb.held_study_numbers:
            numbers.setdefault(n, [])
            if name not in numbers[n]:
                numbers[n].append(name)
        if wb.dose_unit:
            units.setdefault(wb.dose_unit, []).append(name)
        if wb.title:
            titles.setdefault(wb.title, []).append(name)
        for f, v in wb.title_facts.items():
            if f in design:
                design[f].setdefault(v, []).append(name)

        days: set[str] = set()
        for ob in wb.observations():
            if ob.day:
                days.add(ob.day)
            rec = {"sex": ob.sex or None, "dose": ob.dose, "selection": ob.selection or None}
            if ob.sex:
                sexes.add(ob.sex)
            if ob.dose is not None:
                doses.add(ob.dose)
            prior = seen.get(ob.animal_id)
            if prior is None:
                seen[ob.animal_id] = (rec, name)
                continue
            known, where = prior
            for key in ("sex", "dose"):
                if rec[key] is not None and known[key] is not None and rec[key] != known[key]:
                    clashes.setdefault(key, set()).add(ob.animal_id)
                    clash_books.update({where, name})
                elif known[key] is None:
                    known[key] = rec[key]
            if known["selection"] is None:
                known["selection"] = rec["selection"]
        st.platforms[platform] = {
            "workbook": name,
            "endpoints": wb.endpoints,
            "units": wb.units,
            "days": sorted(days),
        }

    st.animals = {a: rec for a, (rec, _) in sorted(seen.items())}
    st.sexes = sorted(sexes)
    st.dose_groups = sorted(doses)

    def one(found: dict[str, list[str]], kind: str, what: str):
        if len(found) > 1:
            st.conflicts.append({
                "kind": kind,
                "message": f"The study workbooks give more than one {what}: "
                           + "; ".join(f"{v!r} ({', '.join(sorted(set(b)))})"
                                       for v, b in sorted(found.items())),
                "workbooks": sorted({b for bs in found.values() for b in bs}),
            })
        return next(iter(found)) if len(found) == 1 else None

    st.study_number = one(numbers, "study_number", "study number")
    st.dose_unit = one(units, "dose_unit", "dose unit")
    st.title = next(iter(titles)) if len(titles) == 1 else None
    for f, found in design.items():
        v = one(found, "design", f)
        if v:
            st.design[f] = v
    for key, animals in sorted(clashes.items()):
        st.conflicts.append({
            "kind": f"animal_{key}",
            "message": f"The study workbooks give {len(animals)} animal(s) more than one "
                       f"{key}: {_named(animals)}",
            "workbooks": sorted(clash_books),
        })
    return st


def _named(ids) -> str:
    ids = sorted(ids, key=lambda a: (len(a), a))
    return ", ".join(ids[:_MAX_NAMED]) + (" …" if len(ids) > _MAX_NAMED else "")


def check_against_structure(fingerprints: dict, st: StudyStructure) -> list:
    """Every file of the pool checked against the study structure.

    Errors: the workbooks contradicting each other (``conflicts``); a file
    naming an animal the study doesn't have, or one under another dose or sex
    than the workbooks give it; a dose group or sex the study doesn't have; an
    endpoint the platform's workbook doesn't record (a study day counts: the
    pivots name body weights by day).
    Animals a file lacks are not a contradiction (biosampling animals, early
    deaths, a platform measured on part of the study): the roster check reports
    them as information.  The workbooks themselves are not checked here.

    Genomic data names samples, not animals: each sample is resolved to its
    animal (sample_sheet.resolve_sample), and must have the animal's dose and
    sex (errors).  Samples that can't be resolved are a warning, per file.
    """
    from .file_integrator import TIER_XLSX, ValidationIssue

    issues: list = []
    by_name = {_get(fp, "filename"): fid for fid, fp in fingerprints.items()}
    for c in st.conflicts:
        issues.append(ValidationIssue(
            severity="error", platform="study", issue_type="workbook_conflict",
            message=c["message"],
            files_involved=[by_name[b] for b in c.get("workbooks", []) if b in by_name],
            details={"kind": c["kind"]},
        ))

    study_doses = list(st.dose_groups)
    for fid, fp in fingerprints.items():
        if _get(fp, "tier") == TIER_XLSX:
            continue
        if _get(fp, "data_type") == "gene_expression":
            issues.extend(_check_samples(fid, fp, st))
            continue
        name = _get(fp, "filename")
        platform = _get(fp, "platform") or "unknown"
        if not (_get(fp, "animal_ids") or _get(fp, "animal_doses") or _get(fp, "endpoint_names")):
            # Nothing of the file's content was read (a .bm2 Java could not
            # export): it can't be checked against the study, so it can't pass.
            issues.append(ValidationIssue(
                severity="error", platform=platform, issue_type="file_not_checked",
                message=f"{name}: its content could not be read, so it was not checked "
                        "against the study workbooks",
                files_involved=[fid],
            ))
            continue
        doses = _get(fp, "animal_doses") or {}
        file_sexes = {s for s in _get(fp, "sexes") or [] if s in ("Male", "Female")}
        one_sex = next(iter(file_sexes)) if len(file_sexes) == 1 else None
        sexes = _get(fp, "animal_sexes") or {}
        animals = set(_get(fp, "animal_ids") or []) | set(doses)

        def add(kind, ids, what, details=None):
            if ids:
                issues.append(ValidationIssue(
                    severity="error", platform=platform, issue_type=kind,
                    message=f"{name}: {what}",
                    files_involved=[fid], details={"animals": sorted(ids), **(details or {})},
                ))

        unknown = {a for a in animals if a not in st.animals}
        add("animal_not_in_study", unknown,
            f"{len(unknown)} animal(s) the study's workbooks do not have: {_named(unknown)}")
        wrong_dose = {a for a, d in doses.items()
                      if d is not None and a in st.animals and st.animals[a].get("dose") is not None
                      and not _same_dose(d, st.animals[a]["dose"])}
        add("animal_dose_mismatch", wrong_dose,
            f"{len(wrong_dose)} animal(s) at another dose than the study's workbooks give: "
            + _named_pairs(wrong_dose, doses, st, "dose"))
        wrong_sex = set()
        for a in animals - unknown:
            sex = sexes.get(a) or one_sex
            known = st.animals[a].get("sex")
            if sex and known and sex != known:
                wrong_sex.add(a)
        add("animal_sex_mismatch", wrong_sex,
            f"{len(wrong_sex)} animal(s) of another sex than the study's workbooks give: "
            f"{_named(wrong_sex)}")
        extra_doses = [d for d in _get(fp, "dose_groups") or []
                       if not any(_same_dose(d, s) for s in study_doses)]
        if extra_doses and study_doses:
            issues.append(ValidationIssue(
                severity="error", platform=platform, issue_type="dose_not_in_study",
                message=f"{name}: dose group(s) {', '.join(f'{d:g}' for d in extra_doses)} "
                        f"are not in the study (its doses: "
                        f"{', '.join(f'{d:g}' for d in study_doses)}"
                        + (f" {st.dose_unit}" if st.dose_unit else "") + ")",
                files_involved=[fid], details={"doses": extra_doses},
            ))
        plat = st.platforms.get(_get(fp, "platform"))
        if plat is not None:
            allowed = set(plat["endpoints"]) | set(plat["days"]) | _DERIVED.get(platform, set())
            extra_eps = [e for e in _get(fp, "endpoint_names") or [] if e not in allowed]
            if extra_eps:
                hints = []
                for e in extra_eps[:_MAX_NAMED]:
                    near = difflib.get_close_matches(e, plat["endpoints"], n=1)
                    hints.append(f"{e!r}" + (f" (the workbook has {near[0]!r})" if near else ""))
                issues.append(ValidationIssue(
                    severity="error", platform=platform, issue_type="endpoint_not_in_study",
                    message=f"{name}: endpoint(s) {plat['workbook']} does not record: "
                            + ", ".join(hints) + (" …" if len(extra_eps) > _MAX_NAMED else ""),
                    files_involved=[fid], details={"endpoints": extra_eps},
                ))
        extra_sexes = file_sexes - set(st.sexes)
        if extra_sexes and st.sexes:
            issues.append(ValidationIssue(
                severity="error", platform=platform, issue_type="sex_not_in_study",
                message=f"{name}: {', '.join(sorted(extra_sexes))} animals, but the study's "
                        f"workbooks have only {', '.join(st.sexes)}",
                files_involved=[fid], details={"sexes": sorted(extra_sexes)},
            ))
    return issues


def _get(fp, key, default=None):
    return fp.get(key, default) if isinstance(fp, dict) else getattr(fp, key, default)


def _same_dose(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)), abs(float(b)))


def _named_pairs(ids, doses, st: StudyStructure, key: str) -> str:
    ids = sorted(ids, key=lambda a: (len(a), a))
    shown = [f"{a} ({doses[a]:g}, not {st.animals[a][key]:g})" for a in ids[:_MAX_NAMED]]
    return ", ".join(shown) + (" …" if len(ids) > _MAX_NAMED else "")


def _check_samples(fid, fp, st: StudyStructure) -> list:
    """A genomic file's samples against the animals they came from."""
    from .file_integrator import ValidationIssue
    from .sample_sheet import resolve_sample

    name = _get(fp, "filename")
    doses = _get(fp, "animal_doses") or {}
    sexes = _get(fp, "animal_sexes") or {}
    file_sexes = {s for s in _get(fp, "sexes") or [] if s in ("Male", "Female")}
    one_sex = next(iter(file_sexes)) if len(file_sexes) == 1 else None
    unresolved, foreign, wrong_dose, wrong_sex = [], [], [], []
    for sample, dose in doses.items():
        hit = resolve_sample(sample, st.samples, st.animals)
        if hit is None:
            unresolved.append(sample)
            continue
        animal = st.animals.get(hit["animal_id"])
        if animal is None:
            foreign.append(f"{sample} (animal {hit['animal_id']})")
            continue
        if dose is not None and animal.get("dose") is not None and not _same_dose(dose, animal["dose"]):
            wrong_dose.append(f"{sample} (animal {hit['animal_id']}: {dose:g}, not {animal['dose']:g})")
        sex = sexes.get(sample) or one_sex
        if sex and animal.get("sex") and sex != animal["sex"]:
            wrong_sex.append(f"{sample} (animal {hit['animal_id']} is {animal['sex']})")

    issues = []

    def add(kind, items, what, severity="error"):
        if items:
            shown = ", ".join(items[:_MAX_NAMED]) + (" …" if len(items) > _MAX_NAMED else "")
            issues.append(ValidationIssue(
                severity=severity, platform="gene_expression", issue_type=kind,
                message=f"{name}: {len(items)} sample(s) {what}: {shown}",
                files_involved=[fid], details={"samples": items},
            ))

    add("sample_not_in_study", foreign, "of animals the study's workbooks do not have")
    add("sample_dose_mismatch", wrong_dose, "at another dose than their animal")
    add("sample_sex_mismatch", wrong_sex, "of another sex than their animal")
    add("samples_unresolved", unresolved,
        "not traced to an animal (no sample sheet names them, and their names "
        "don't end in an animal number)", severity="warning")
    return issues
