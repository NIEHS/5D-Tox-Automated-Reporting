"""
pipeline/deposit.py — the study's data deposit: the supplemental files deposited
with the report (CEBS / the Bookshelf package), listed in its Supplemental Data
appendix.

The deposit is recorded once, as a session sidecar (``sessions/<id>/deposit.json``,
like the other sidecars): one entry per file with its size, the study number its
name carries, the KIND of file it is and the species that study used.  The
document then lists the files (ADR-0029): each Supplemental Data section is a
derived ``supplementary-material`` node naming a `deposit_group`, and the 2026
books' per-species sections repeat per deposited species (`repeat:
deposit_species`).  No list is typed by hand.

Kinds (the groups the published books use, NIEHS-02 … 13):

    apical        Apical Benchmark Dose Analysis — model fits, parameters, the
                  BMDS package, the apical summaries, the non-genomic .bm2
    genomic       Genomic Benchmark Dose Analysis — BMDExpress projects and
                  results, expression data, PCA, annotation, QC, software
    study-tables  Study Tables — the NTP summary reports (I04, PA41, R07 …)
    animal-data   Individual Animal Data — Individual_Animal_*
    methods       Materials and Methods (2026)
    inhaled-dose  Theoretical Inhaled Dose (2026)
    software      Analysis Pipeline Evaluation (2026)

The kind is read from the file NAME: deposited files are opaque (PDF, Word, zip),
and their names follow the depositors' convention.  The rules reproduce the
grouping of all 672 files the 11 published deposits list
(tests/unit/test_deposit.py).  A study whose depositors break the convention can
state the kind of a file (`templates/studies/<id>/deposit.yaml`: `kinds:`), as it
can state a file's caption (`captions:`, authored wording such as NIEHS-10's
"Male BMD Apical Endpoints Model Fits"); otherwise the caption is the file name
without its study number, extension and underscores.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import yaml

from common.dtxsid import validate_dtxsid

DEPOSIT_FILE = "deposit.json"
KINDS = ("apical", "genomic", "study-tables", "animal-data", "methods",
         "inhaled-dose", "software")

# The study number a deposited file's name starts with: C20022-01_, C10674_,
# C10866B_, 108020004_.
_STUDY_NUMBER = re.compile(r"^(C\d{5}[A-Z]?(?:-\d\d)?|\d{9})_")
# An NTP summary report's code: I04, I04G, PA41, R07 (the Study Tables).
_TABLE_CODE = re.compile(r"(?:^|[_ –-])(I0\d[A-Z]?|PA\d\d|R0\d)(?:[_ –-]|$)")
# Name fragments of the apical BMD deliverables (lower-cased name, no study number).
_APICAL = ("bmd_apical", "apical_endpoints", "model_recommendation", "model_parameters",
           "appendix_male", "appendix_female", "nongenomic", "bmds")
_APICAL_START = re.compile(r"^(read_?me|parameter_)")
# Name fragments of the genomic deliverables.
_GENOMIC = ("bmdexpress", "top_10", "gene", "go_", "pca", "principal_components", "fastq",
            "fastaq", "microarray", "genomic", "expression", "annotation",
            "batch_correction", "cel_files", "prefilter", "curve_fit", "anova", "efdr",
            "manifest", "transcriptomics", "readcounts", "benchmark_dose_analysis_",
            "software")
# Species named in file names, and how a section titles them.
_SPECIES = {
    "rat": re.compile(r"(?i)(?<![a-z])(rats?|rattus)(?![a-z])|Rat(?=[A-Z_ ]|Study)"),
    "mouse": re.compile(r"(?i)(?<![a-z])(mouse|mice|mus)(?![a-z])|Mouse"),
}
SPECIES_TITLES = {"rat": "Rats", "mouse": "Mice"}

_MIME = {".docx": "docx", ".doc": "msword", ".xlsx": "xlsx", ".pdf": "pdf", ".zip": "zip",
         ".txt": "plain", ".csv": "csv", ".tsv": "tab-separated-values", ".json": "json",
         ".bm2": "octet-stream"}


def study_number(name: str) -> str | None:
    m = _STUDY_NUMBER.match(name)
    return m.group(1) if m else None


def _bare(name: str) -> str:
    """The name without its study number and extension."""
    return _STUDY_NUMBER.sub("", name.rsplit(".", 1)[0] if "." in name else name)


def classify(name: str) -> str:
    """The kind of a deposited file (see the module docstring), from its name."""
    bare = _bare(name)
    low = bare.lower()
    if low.startswith("individual_animal_"):
        return "animal-data"
    if _TABLE_CODE.search(bare) or low.startswith("blood_and_tissue_concentration"):
        return "study-tables"
    if low == "materials_and_methods":
        return "methods"
    if low.startswith("theoretical_inhaled_dose"):
        return "inhaled-dose"
    if "pipeline" in low and ("evaluation" in low or "tbmd" in low):
        return "software"
    if any(t in low for t in _APICAL) or _APICAL_START.match(low):
        return "apical"
    if any(t in low for t in _GENOMIC):
        return "genomic"
    if "summary" in low:
        return "apical"
    return "genomic"


def default_caption(name: str) -> str:
    """"C20022-01_Organ_Weights_Summary.docx" → "Organ Weights Summary"."""
    return " ".join(_bare(name).replace("_", " ").split())


def _species_by_study(names: list[str]) -> dict[str, str]:
    """Each study number's species: the species its files name most often (a
    2026 deposit holds a rat and a mouse study, 108020004 / 108020005)."""
    votes: dict[str, Counter] = {}
    for name in names:
        number = study_number(name)
        if number is None:
            continue
        for species, rx in _SPECIES.items():
            if rx.search(name):
                votes.setdefault(number, Counter())[species] += 1
    return {n: c.most_common(1)[0][0] for n, c in votes.items()}


def build_manifest(files: list[tuple[str, int]], kinds: dict | None = None,
                   captions: dict | None = None) -> dict:
    """The deposit manifest for these (file name, size) pairs: {"files": [...],
    "species": [...]}, files in name order.  `kinds` / `captions` are a study's
    stated kinds and caption wording, by file name."""
    files_in = sorted(files, key=lambda f: f[0].lower())
    species_of = _species_by_study([name for name, _ in files_in])
    files = []
    for name, size in files_in:
        number = study_number(name)
        suffix = Path(name).suffix.lower()
        files.append({
            "file": name,
            "size": size,
            "mime_subtype": _MIME.get(suffix, suffix.lstrip(".")),
            "kind": (kinds or {}).get(name) or classify(name),
            "study": number,
            "species": species_of.get(number) if number else None,
            "caption": (captions or {}).get(name) or default_caption(name),
        })
    seen: list[str] = []
    for f in files:
        if f["species"] and f["species"] not in seen:
            seen.append(f["species"])
    species = [{"key": s, "title": SPECIES_TITLES.get(s, s.title())} for s in seen]
    return {"files": files, "species": species}


# ---------------------------------------------------------------------------
# The session sidecar
# ---------------------------------------------------------------------------

def _study_statements(dtxsid: str) -> dict:
    """The study's stated kinds and captions (templates/studies/<id>/deposit.yaml)."""
    from document_model.document_template import TEMPLATES_DIR
    path = TEMPLATES_DIR / "studies" / validate_dtxsid(dtxsid) / "deposit.yaml"
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    unknown = set(raw) - {"kinds", "captions"}
    if unknown:
        raise ValueError(f"{path}: unknown key(s) {sorted(unknown)} (kinds, captions)")
    bad = {f: k for f, k in (raw.get("kinds") or {}).items() if k not in KINDS}
    if bad:
        raise ValueError(f"{path}: unknown kind(s) {bad}; known {list(KINDS)}")
    return raw


def deposit_listing(directory: Path, exclude: tuple[str, ...] = ()) -> list[tuple[str, int]]:
    """(name, size) of the files of `directory` (not its sub-directories), less
    the names matching an `exclude` glob."""
    return [(p.name, p.stat().st_size) for p in sorted(Path(directory).iterdir())
            if p.is_file() and not any(p.match(g) for g in exclude)]


def record_deposit(dtxsid: str, directory: Path, exclude: tuple[str, ...] = ()) -> dict:
    """List the files of `directory` as the study's deposit (deposit_listing) and
    save the manifest as the session's deposit.json."""
    from pipeline.session_store import session_path

    directory = Path(directory)
    stated = _study_statements(dtxsid)
    manifest = build_manifest(deposit_listing(directory, exclude), stated.get("kinds"),
                              stated.get("captions"))
    manifest["source"] = str(directory)
    out = session_path(dtxsid) / DEPOSIT_FILE
    out.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def load_deposit(dtxsid: str | None) -> dict | None:
    """The session's deposit manifest, with the study's caption wording applied
    (so a caption edit needs no re-recording); None when none was recorded."""
    if not dtxsid:
        return None
    from pipeline.session_store import session_path
    try:
        path = session_path(dtxsid) / DEPOSIT_FILE
    except ValueError:
        return None
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    captions = _study_statements(dtxsid).get("captions") or {}
    for f in manifest.get("files") or []:
        if f["file"] in captions:
            f["caption"] = captions[f["file"]]
    return manifest


def deposit_files(deposit: dict | None, kind: str, species: str | None = None) -> list[dict]:
    """The deposited files of one kind (and, within a per-species section, of
    that species), in manifest order."""
    return [f for f in (deposit or {}).get("files") or []
            if f.get("kind") == kind and (species is None or f.get("species") == species)]
