#!/usr/bin/env python3
"""tooling/cebs_to_pool.py — convert a published CEBS NIEHS data package into
pool inputs rlm-bmdx ingests.

CEBS publishes each study's apical data as NTP "Individual Animal" workbooks
(`Key to Column Labels` + `Data` sheets).  The pool's accepted apical source is
the long-format `*_truth_<sex>.csv` (one row per animal/observation, NTP columns):
the filename sets platform + `tox_study`, and on upload `fingerprint_and_store`
converts it into the wide BMDExpress pivot + per-animal `.sidecar.json`.  The
reference set's truth CSVs are exactly the workbook `Data` sheet split by sex —
`tests/unit/test_cebs_to_pool.py` pins that by regenerating them byte-for-byte
from the reference workbooks.

The `Data` headers carry no units; the Key sheet states them per column, and
they differ by study (plasma ng/ml in NIEHS-07 – -09, ug/ml in NIEHS-10).  Each
CSV gets a companion `<stem>_truth_<sex>.units.json` ({column: unit},
bmdx_pipe.key_sheet_units) that the pool's ingest records in the sidecar.

The 2025 (DTT) workbooks changed the schema: the `Data` sheet has NO `Sex`
column (the studies are single-sex) and says `Study Number` instead of
`NTP Study Number`.  The sex is stated only in the Key sheet's study title
("… in Female Sprague Dawley Rats …").  We fill the `Sex` column from that title
— an inference from the file's own text, reported in the run summary — and
refuse a workbook whose title names both sexes or neither.

Gene expression: the BMDExpress project's experiment names are tissue codes
(`rat_4D_HE_No0`).  The organ is taken from DATA, not the code: each project
experiment's sample IDs are matched against the package's per-tissue expression
files (`…_Expression_Data_<Tissue>_<Species>.txt`), whose sample columns are the
same IDs.  `--metadata-out` writes the resulting per-experiment
ExperimentDescription map ({name: {organ, sex, species, …}}) for the
`/api/experiment-metadata` approval step.

Usage:
    python -m tooling.cebs_to_pool --package assets/cebs/NIEHS-13 \\
        --prefix 108020004 --out sessions/<id>/files \\
        [--genomic-bm2-json assets/cebs/NIEHS-13/_bm2json/108020004_4D_Genomic_Rats.json] \\
        [--metadata-out /tmp/metadata.json]
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
from pathlib import Path

import openpyxl
from bmdx_pipe import key_sheet_units

# Individual-animal workbook → truth-CSV stem (the pool's filename patterns:
# bmdx_pipe.file_integrator._PLATFORM_PATTERNS).  Order matters: "Clinical
# Chemistry" must win over "Clinical Observations" only by its own token.
_WORKBOOK_STEMS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Body_Weight", re.I), "body_weight"),
    (re.compile(r"Organ_Weight", re.I), "organ_weights"),
    (re.compile(r"Clinical_Chemistry", re.I), "clin_chem"),
    (re.compile(r"Clinical_Observations", re.I), "clinical_obs"),
    (re.compile(r"Hematology", re.I), "hematology"),
    (re.compile(r"Hormone", re.I), "hormones"),
    (re.compile(r"Tissue_Concentration", re.I), "tissue_conc"),
]

_SEX_WORDS = re.compile(r"\b(Male|Female)s?\b", re.I)

# Chip species (BMDExpress ChipInfo, Latin) → the metadata vocabulary's common
# name (bmdx_pipe.experiment_metadata).
_CHIP_SPECIES = {"rattus norvegicus": "rat", "mus musculus": "mouse", "homo sapiens": "human"}


def workbook_stem(filename: str) -> str | None:
    """Truth-CSV stem for an Individual Animal workbook, or None (no apical platform)."""
    for pat, stem in _WORKBOOK_STEMS:
        if pat.search(filename):
            return stem
    return None


def _cell(v) -> str:
    """Workbook cell → CSV text, matching how the reference CSVs were written."""
    if v is None:
        return ""
    return str(v)


def key_sheet_sex(wb) -> str | None:
    """The single sex named in the Key sheet's study title, or None.

    Only the title cells of the first row are read — the rest of the Key sheet
    explains column labels (which mention "Sex" generically)."""
    if "Key to Column Labels" not in wb.sheetnames:
        return None
    first = next(wb["Key to Column Labels"].iter_rows(max_row=1, values_only=True), ())
    title = " ".join(str(c) for c in first if c)
    sexes = {m.group(1).title() for m in _SEX_WORDS.finditer(title)}
    return sexes.pop() if len(sexes) == 1 else None


def convert_workbook(path: str, out_dir: str) -> dict:
    """Write one `<stem>_truth_<sex>.csv` per sex.  Returns a summary dict."""
    name = os.path.basename(path)
    stem = workbook_stem(name)
    if stem is None:
        return {"file": name, "status": "skipped", "reason": "no apical platform"}

    wb = openpyxl.load_workbook(path, data_only=True)
    rows = [list(r) for r in wb["Data"].iter_rows(values_only=True)]
    header = [_cell(c) for c in rows[0]]
    body = [r for r in rows[1:] if any(c is not None and str(c).strip() for c in r)]

    notes = []
    if header and header[0] == "Study Number":
        header[0] = "NTP Study Number"
        notes.append("renamed 'Study Number' → 'NTP Study Number'")

    if "Sex" in header:
        sex_idx = header.index("Sex")
        filled = None
    else:
        filled = key_sheet_sex(wb)
        if filled is None:
            return {"file": name, "status": "error",
                    "reason": "no Sex column and the Key title does not name exactly one sex"}
        animal_idx = header.index("Animal ID")
        sex_idx = animal_idx + 1
        header.insert(sex_idx, "Sex")
        body = [r[:sex_idx] + [filled] + r[sex_idx:] for r in body]
        notes.append(f"Sex column absent — filled '{filled}' from the Key sheet title (inferred)")

    by_sex: dict[str, list[list]] = {}
    for r in body:
        by_sex.setdefault(_cell(r[sex_idx]).strip().lower(), []).append(r)

    units = {col: u for col, u in key_sheet_units(path).items() if col in header}

    written = []
    for sex, sex_rows in sorted(by_sex.items()):
        out = os.path.join(out_dir, f"{stem}_truth_{sex}.csv")
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\r\n")  # the reference CSVs are CRLF
            w.writerow(header)
            for r in sex_rows:
                w.writerow([_cell(c) for c in r[:len(header)]])
        written.append(os.path.basename(out))
        if units:
            Path(out).with_suffix(".units.json").write_text(json.dumps(units, indent=2) + "\n")
    return {"file": name, "status": "ok", "written": written, "notes": notes,
            "sex_filled": filled, "units": len(units)}


def genomic_metadata(bm2_json_path: str, package_dir: str, sex: str | None) -> dict:
    """{experiment name: ExperimentDescription-shaped dict} for a genomic project.

    Organ comes from matching each experiment's sample IDs to a per-tissue
    expression file; species from the experiment's chip."""
    project = json.load(open(bm2_json_path))
    tissue_samples: dict[str, set[str]] = {}
    for f in glob.glob(os.path.join(package_dir, "*Expression_Data_*.txt")):
        m = re.search(r"Expression_Data_([A-Za-z]+)", os.path.basename(f))
        if not m:
            continue
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if "\t" in line and not line.startswith("#"):
                    tissue_samples[f] = (m.group(1), set(line.rstrip("\n").split("\t")[1:]))
                    break

    out = {}
    for exp in project.get("doseResponseExperiments", []):
        samples = {t.get("name") for t in exp.get("treatments") or []}
        hits = [(t, len(samples & s)) for t, s in tissue_samples.values() if samples & s]
        hits.sort(key=lambda x: -x[1])
        if not hits or hits[0][1] != len(samples):
            raise ValueError(f"{exp.get('name')}: no expression file holds all of its samples")
        chip = exp.get("chip") if isinstance(exp.get("chip"), dict) else {}
        species = _CHIP_SPECIES.get((chip.get("species") or "").lower())
        # S1500_Plus_Rat → "S1500+_rat" (the vocabulary's platform spelling)
        m = re.fullmatch(r"S1500_Plus_(\w+)", chip.get("name") or "")
        out[exp["name"]] = {
            "organ": hits[0][0].lower(), "sex": sex.lower() if sex else None,
            "species": species, "provider": chip.get("provider"),
            "platform": f"S1500+_{m.group(1).lower()}" if m else chip.get("name"),
            "subjectType": "in vivo", "dataType": "gene_expression",
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--package", required=True, help="CEBS package dir (assets/cebs/<ID>)")
    ap.add_argument("--prefix", default="", help="study-number filename prefix to select one species")
    ap.add_argument("--out", required=True, help="output dir (a session's files/)")
    ap.add_argument("--genomic-bm2-json")
    ap.add_argument("--metadata-out")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    sexes = set()
    for path in sorted(glob.glob(os.path.join(a.package, f"{a.prefix}*Individual_Animal_*.xlsx"))):
        s = convert_workbook(path, a.out)
        print(json.dumps(s))
        if s.get("status") == "ok":
            sexes.update(w.rsplit("_", 1)[1][:-4] for w in s["written"])
    if a.genomic_bm2_json and a.metadata_out:
        study_sex = sexes.pop().title() if len(sexes) == 1 else None
        meta = genomic_metadata(a.genomic_bm2_json, a.package, study_sex)
        Path(a.metadata_out).write_text(json.dumps(meta, indent=2))
        print(json.dumps({"metadata": {k: v["organ"] for k, v in meta.items()}, "sex": study_sex}))


if __name__ == "__main__":
    main()
