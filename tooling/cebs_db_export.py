"""tooling/cebs_db_export.py — the CEBS database-export layout of an Individual
Animal workbook (NIEHS-02 … 05) → the NTP Key/Data rows the truth CSVs carry.

NIEHS-06 onward publish the NTP "Key to Column Labels" + "Data" workbook: one
row per animal (per day), one column per endpoint.  NIEHS-02 … 05 publish the
CEBS database export instead — one sheet ("Body Weights", "NTP Clinical
Chemistry", "Organ Weights", "Hormone", "Clinical Observations"), one row per
animal per MEASUREMENT, upper-case columns (DEPOSITOR_STUDY_NUMBER, DOSE,
ANMLNUM, SEX, SELECTION, OBSDAY, …_MEASUREMENT_NAME/_VALUE, UNIT).  This module
turns it into the Key/Data rows of the same platform (NIEHS-06's columns, plus
Sex, which the export states), so the rest of the ingest is unchanged.

Translation rules — each checked against the published summaries:

* Cohort.  When an export marks a SELECTION ("Original Animals"), unmarked
  rows are another cohort — NIEHS-02/03's second, month-later cohort — and are
  dropped: NIEHS-02's control body weights are 254.6 (SD0) / 272.2 (SD4) from
  the Original Animals alone, as published.  An export that marks no
  SELECTION (NIEHS-04, 05) keeps every animal.  NTP's own Key/Data workbooks
  (NIEHS-06) carry no Selection column either.
* "Exclude" (the carcass weight of an animal found dead or moribund, or a
  value removed from analysis) and "Not Measured" become "NA" — the Key/Data
  spelling — so the row, its day and Terminal Flag (attrition) stay while the
  value counts in no statistic.
* Organ names: "Brain Weight" → "Brain", "Liver Weight" → "Liver",
  "Terminal Bodyweight" → "Terminal Body Weight" (the Key/Data column names).
* Units come from the export's UNIT column ({endpoint: unit}); the organ weight
  export records none.  The dose stays in the export's unit (DOSE_UNIT —
  mMol/kg for these studies, as NIEHS-06's Key sheet also states).
"""

from __future__ import annotations

import re

_NUMBER = re.compile(r"^-?\d*\.?\d+(?:[eE][-+]?\d+)?$")

# Key/Data column for each platform's measurement layout.
#   kind: "single" — one value column (body weight);
#         "wide"   — NAME/VALUE pairs pivoted to one column per name;
#         "obs"    — clinical observations (categorical columns).
_LAYOUTS = {
    "body_weight": {"kind": "single", "value": "WGTVALUE", "column": "Body Weight",
                    "day": "OBSDAY", "day_label": "Observation Day"},
    "clin_chem": {"kind": "wide", "name": "CLINCHEM_MEASUREMENT_NAME",
                  "value": "CLINCHEM_MEASUREMENT_VALUE", "day": "OBSDAY", "day_label": "Observation Day"},
    "hormones": {"kind": "wide", "name": "HORMONE_MEASUREMENT_NAME", "value": "HORMONE_VALUE",
                 "day": "RMVLDAY", "day_label": "Removal Day"},
    "organ_weights": {"kind": "wide", "name": "ORGAN_NAME", "value": "ORGANVALUE",
                      "day": "RMVLDAY", "day_label": "Removal Day"},
    "clinical_obs": {"kind": "obs", "day": "PHASEDAY", "day_label": "Observation Day"},
}

_ORGAN_NAMES = {"Terminal Bodyweight": "Terminal Body Weight"}

_OBS_COLUMNS = [("Observation", "SYMPTOM"), ("Site", "SITE"), ("Modifier", "MODIFIER"),
                ("Severity", "SEVERITY")]


def is_db_export(header: list[str]) -> bool:
    return "DEPOSITOR_STUDY_NUMBER" in header


def _first(I: dict, *names: str) -> str | None:
    return next((n for n in names if n in I), None)


def _value(v) -> str:
    s = "" if v is None else str(v).strip()
    return s if not s or _NUMBER.match(s) else "NA"


def _organ(name: str) -> str:
    return _ORGAN_NAMES.get(name, name[:-len(" Weight")] if name.endswith(" Weight") else name)


def to_key_data(stem: str, header: list[str], rows: list[list]) -> tuple[list[str], list[list[str]], dict, list[str]]:
    """(Key/Data header, rows, {column: unit}, notes) for one export sheet."""
    lay = _LAYOUTS[stem]
    I = {c: i for i, c in enumerate(header)}
    cell = lambda r, c: "" if c is None or r[I[c]] is None else str(r[I[c]]).strip()
    animal = _first(I, "ANMLNUM", "ANMLID", "ANIMALID")
    selection = _first(I, "SELECTION", "SELECTION_NAME")
    notes = []

    marked = {cell(r, selection) for r in rows} - {""} if selection else set()
    if marked:
        kept = [r for r in rows if cell(r, selection)]
        dropped = {cell(r, animal) for r in rows if not cell(r, selection)}
        if dropped:
            notes.append(f"{len(dropped)} animal(s) outside the marked cohort "
                         f"({', '.join(sorted(marked))}) dropped: {', '.join(sorted(dropped, key=_natural))}")
        rows = kept

    base = ["NTP Study Number", "Concentration", "Animal ID", "Sex"]
    study = lambda r: re.sub(r"^X-", "", cell(r, "DEPOSITOR_STUDY_NUMBER"))
    lead = lambda r: [study(r), cell(r, "DOSE"), cell(r, animal), cell(r, "SEX")]
    units: dict[str, str] = {}

    if lay["kind"] == "single":
        out = [lead(r) + [_value(r[I[lay["value"]]]), cell(r, lay["day"]), cell(r, "TERMINAL_FLAG")]
               for r in rows]
        if "UNIT" in I:
            units = {lay["column"]: u for u in {cell(r, "UNIT") for r in rows} - {""}}
        return base + [lay["column"], lay["day_label"], "Terminal Flag"], out, units, notes

    if lay["kind"] == "obs":
        out = [lead(r) + [cell(r, lay["day"])] + [cell(r, src) for _, src in _OBS_COLUMNS] for r in rows]
        return base + [lay["day_label"]] + [c for c, _ in _OBS_COLUMNS], out, units, notes

    # wide: one row per (animal, day), one column per measurement name
    rename = _organ if stem == "organ_weights" else (lambda n: n)
    names: list[str] = []
    by_key: dict[tuple, dict] = {}
    for r in rows:
        name = rename(cell(r, lay["name"]))
        if name not in names:
            names.append(name)
        key = (cell(r, animal), cell(r, lay["day"]))
        rec = by_key.setdefault(key, {"lead": lead(r), "day": key[1], "values": {}})
        rec["values"][name] = _value(r[I[lay["value"]]])
        if "UNIT" in I and cell(r, "UNIT"):
            units.setdefault(name, cell(r, "UNIT"))
    out = [rec["lead"] + [rec["day"]] + [rec["values"].get(n, "") for n in names] for rec in by_key.values()]
    return base + [lay["day_label"]] + names, out, units, notes


def _natural(s: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]
