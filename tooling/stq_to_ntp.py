#!/usr/bin/env python3
"""tooling/stq_to_ntp.py — convert raw STQ LIMS body/organ-weight extracts into
the NTP "Individual Animal Data" xlsx format the rlm-bmdx pool ingests.

The Triclosan/BPAF apical weights arrived as raw study-database exports
(`assets/IAD_STQ_{BODYWEIGHTS,ORGANWEIGHTS}_*.xlsx`): DB-native columns, a `SQL`
query sheet, both chemicals combined by `DEPOSITOR_STUDY_NUMBER`, and organ
weights in LONG form (one row per animal×organ). The rlm-bmdx pool keys the
PLATFORM off the filename (`Body_Weight` / `Organ_Weight`) and the DATA_TYPE
(`tox_study`) off the two-sheet `Key to Column Labels` + `Data` structure
(`file_integrator.fingerprint_xlsx`). This rewrites each study into a
per-chemical NTP-format file named like the reference set, so it classifies and
parses identically.

Study→chemical (confirmed by matching each STQ study's dose series to the
session's genomics doses):
  C08002-01  → BPAF      (DTXSID7037717)   doses 0/8/16/31.25/62.5/125/250/500/1000
  C03039C-01 → Triclosan (DTXSID5032498)   doses 0/7.8/15.6/31.25/62.5/125/250/500/1000

Assumptions (all from the delivered data, flagged deliberately):
  * The source is MALE-ONLY (STQ `SEX` is `Male` throughout).
  * `SELECTION` (`None` / `Core Males`) maps to `Core Animals` — no biosampling
    cohort is present in the extract, so every animal is treated as core-study.
  * `DOSE_FACTOR` is empty, so `Concentration = DOSE` (mg/kg) directly.
  * Organ weights are pivoted LONG→WIDE (Kidney-Left / Kidney-Right / Liver /
    Terminal Body Weight); the reference's `Heart` column is absent here and is
    simply not emitted (the studies did not weigh heart).

Usage:
    python -m tooling.stq_to_ntp [--body PATH] [--organ PATH] [--out DIR]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import openpyxl

# NTP study-number pattern the pool's fingerprint extractor accepts.
_STUDY_RE = re.compile(r"^[A-Z]\d+-\d+$")


def _normalize_study(raw: str) -> str:
    """Return a study number the pool extractor recognizes.

    The extract mixes two spellings (`C03039C-01` in the organ file, `C03039-01`
    in the body-weight filename); the latter matches the extractor regex, the
    former (a trailing study-variant letter) does not. Strip that trailing letter
    so both weight files for a chemical share one extractable study number."""
    s = str(raw).strip()
    if _STUDY_RE.match(s):
        return s
    m = re.match(r"^([A-Z]\d+)[A-Z]+(-\d+)$", s)
    return f"{m.group(1)}{m.group(2)}" if m else s


STUDY_TO_CHEM = {
    "C08002-01": ("BPAF", "DTXSID7037717"),
    "C03039C-01": ("Triclosan", "DTXSID5032498"),
}
SELECTION_MAP = {"None": "Core Animals", "Core Males": "Core Animals",
                 "Core Females": "Core Animals"}
# STQ ORGAN_NAME → reference organ-weight column label.
ORGAN_MAP = {
    "Kidney-Left": "Kidney-Left",
    "Kidney-Right": "Kidney-Right",
    "Liver Weight": "Liver",
    "Terminal Bodyweight": "Terminal Body Weight",
}
ORGAN_COLS = ["Kidney-Left", "Kidney-Right", "Liver", "Terminal Body Weight"]


def _read(path: str) -> tuple[list[str], list[list]]:
    """Read the first (data) sheet of an STQ xlsx; return (header, rows).

    read_only is avoided — the STQ files, like NTP xlsx, can carry a bad stored
    dimension that makes read-only mode see one column."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    wb.close()
    header = [str(h) if h is not None else "" for h in rows[0]]
    return header, rows[1:]


def _sel(value) -> str:
    return SELECTION_MAP.get(str(value).strip(), "Core Animals")


def _key_sheet(columns_expl: list[tuple[str, str]], study_number: str) -> list[list]:
    """The `Key to Column Labels` sheet: col A/B = label/explanation, col D = the
    NTP study-metadata block (row 2 study type, row 3 study number, row 4 date)."""
    col_d = ["Evaluation of", "TOX", study_number, ""]
    rows = [["Column Label", "Explanation of Column Label", None, col_d[0]]]
    for i, (label, expl) in enumerate(columns_expl):
        d = col_d[i + 1] if i + 1 < len(col_d) else None
        rows.append([label, expl, None, d])
    return rows


def _write_ntp(out_path: Path, key_rows: list[list], data_header: list[str],
               data_rows: list[list]) -> None:
    wb = openpyxl.Workbook()
    ks = wb.active
    ks.title = "Key to Column Labels"
    for r in key_rows:
        ks.append(r)
    ds = wb.create_sheet("Data")
    ds.append(data_header)
    for r in data_rows:
        ds.append(r)
    wb.save(out_path)


def convert_body_weight(path: str, outdir: Path) -> list[tuple[Path, str, int]]:
    header, rows = _read(path)
    idx = {c: header.index(c) for c in (
        "DEPOSITOR_STUDY_NUMBER", "DOSE", "ANMLNUM", "SEX", "SELECTION",
        "WGTVALUE", "OBSDAY", "TERMINAL_FLAG")}
    by_study: dict[str, list] = {}
    for r in rows:
        by_study.setdefault(r[idx["DEPOSITOR_STUDY_NUMBER"]], []).append(r)

    data_header = ["NTP Study Number", "Concentration", "Animal ID", "Sex",
                   "Selection", "Body Weight", "Observation Day", "Terminal Flag"]
    expl = [("NTP Study Number", "NTP study number"),
            ("Concentration", "Dose in mg/kg"),
            ("Animal ID", "Animal number"),
            ("Sex", "Sex"),
            ("Selection", "Cohort assigned"),
            ("Body Weight", "Body weight measured in grams"),
            ("Observation Day", "Study day body weight was measured (SD = Study Day)"),
            ("Terminal Flag", "Yes indicates that this was a terminal body weight")]
    written = []
    for study, srows in by_study.items():
        chem, _ = STUDY_TO_CHEM.get(study, (study, None))
        study_out = _normalize_study(study)
        drows = []
        for r in srows:
            drows.append([
                study_out, r[idx["DOSE"]], str(r[idx["ANMLNUM"]]), r[idx["SEX"]],
                _sel(r[idx["SELECTION"]]), r[idx["WGTVALUE"]], r[idx["OBSDAY"]],
                "Yes" if str(r[idx["TERMINAL_FLAG"]]).strip() == "Yes" else "",
            ])
        out = outdir / f"{study_out}_Individual_Animal_Body_Weight_Data.xlsx"
        _write_ntp(out, _key_sheet(expl, study_out), data_header, drows)
        written.append((out, chem, len(drows)))
    return written


def convert_organ_weight(path: str, outdir: Path) -> list[tuple[Path, str, int]]:
    header, rows = _read(path)
    idx = {c: header.index(c) for c in (
        "DEPOSITOR_STUDY_NUMBER", "DOSE", "ANMLID", "SEX", "SELECTION",
        "RMVLDAY", "ORGAN_NAME", "ORGANVALUE")}
    # Pivot LONG→WIDE: gather each animal's organ rows into one record.
    animals: dict[tuple, dict] = {}
    order: list[tuple] = []
    for r in rows:
        study, anml = r[idx["DEPOSITOR_STUDY_NUMBER"]], str(r[idx["ANMLID"]])
        key = (study, anml)
        if key not in animals:
            animals[key] = {
                "study": study, "dose": r[idx["DOSE"]], "anml": anml,
                "sex": r[idx["SEX"]], "sel": r[idx["SELECTION"]],
                "rmvl": r[idx["RMVLDAY"]], "organs": {},
            }
            order.append(key)
        col = ORGAN_MAP.get(str(r[idx["ORGAN_NAME"]]).strip())
        if col:
            animals[key]["organs"][col] = r[idx["ORGANVALUE"]]

    by_study: dict[str, list] = {}
    for key in order:
        by_study.setdefault(animals[key]["study"], []).append(animals[key])

    data_header = ["NTP Study Number", "Concentration", "Animal ID", "Sex",
                   "Selection", "Removal Day"] + ORGAN_COLS
    expl = [("NTP Study Number", "NTP study number"),
            ("Concentration", "Dose in mg/kg"),
            ("Animal ID", "Animal number"),
            ("Sex", "Sex"),
            ("Selection", "Cohort assigned"),
            ("Removal Day", "Study day the animal was removed (SD = Study Day)")]
    expl += [(c, f"{c} weight in grams") for c in ORGAN_COLS]
    written = []
    for study, alist in by_study.items():
        chem, _ = STUDY_TO_CHEM.get(study, (study, None))
        study_out = _normalize_study(study)
        drows = []
        for a in alist:
            drows.append(
                [study_out, a["dose"], a["anml"], a["sex"], _sel(a["sel"]), a["rmvl"]]
                + [a["organs"].get(c, "") for c in ORGAN_COLS]
            )
        out = outdir / f"{study_out}_Individual_Animal_Organ_Weight_Data.xlsx"
        _write_ntp(out, _key_sheet(expl, study_out), data_header, drows)
        written.append((out, chem, len(drows)))
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--body", default="assets/IAD_STQ_BODYWEIGHTS_BPAF_Triclosan_C08002-01_C03039-01.xlsx")
    ap.add_argument("--organ", default="assets/IAD_STQ_ORGANWEIGHTS_BPAF_Triclosan_C08002-01_C03039C-01.xlsx")
    ap.add_argument("--out", default="assets/converted")
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"writing NTP-format xlsx to {outdir}/")
    for out, chem, n in convert_body_weight(args.body, outdir):
        print(f"  body   {chem:10} {out.name}  ({n} rows)")
    for out, chem, n in convert_organ_weight(args.organ, outdir):
        print(f"  organ  {chem:10} {out.name}  ({n} animals)")


if __name__ == "__main__":
    main()
