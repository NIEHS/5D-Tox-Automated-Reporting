"""tooling/cebs_lab_concentration.py — the analytical lab's blood and tissue
concentration workbook (NIEHS-12, -13: "Individual Animal Blood and Tissue
Concentration Data", bundle-only) → the Key/Data rows of a Tissue
Concentration truth CSV.

The workbook is the lab's results report, not an NTP Key/Data workbook: one
sheet per species ("Rat Sample Results", "Mouse Sample Results"), six title
lines, then one row per animal —

    Strain/Species | Sex | Matrix | Subject ID | Group # |
    Exposure Concentration (ppm) | Study Day | Sampling Time Relative to Dosing |
    Blood\\n 1,4-DCB Concentration (ng/mL) | Lung … (ng/g) | Liver … (ng/g) | Comments

and footnotes below the data.  Translation rules:

* One sheet: the one whose Strain/Species column names the species the caller
  gives (the package's study prefix is single-species; its sibling workbooks
  say which).
* Subject ID "2F106" is group 2, Female, animal 106 — the Animal ID the
  study's other workbooks use.  The group/sex prefix is checked against the
  row's own Group # and Sex before it is dropped.
* Columns: "Phase" "SD" + "Day" from "Day 4" (the Tissue Concentration day
  columns, as NIEHS-07 … 10 record them); each matrix becomes
  "<Matrix> <analyte> Concentration" with its unit from the header, plus a
  "<Matrix> <analyte> LOD" column holding the limit of detection.
* The LOD is read from the sheet's own footnote ("The limit of detection (LOD)
  for 1,4-DCB in blood samples is 0.0960 ng/mL.  For tissue samples, the LOD
  is 3 times the blood LOD, 0.288 ng/g.") — blood for the blood column, the
  tissue LOD for every other matrix.  A sheet without it is refused.
* "BLOD" (below the LOD) stays as written, with the LOD beside it.  Anything
  else non-numeric ("---", "no sample(s)" — no sample received) becomes an
  empty value with no LOD: the animal was not sampled for that matrix.
* No Selection column: the lab does not say which cohort an animal belongs to.
"""

from __future__ import annotations

import re

_SHEET_SUFFIX = "Sample Results"
_HEADER_FIRST = "Strain/Species"
_SPECIES_WORDS = {"rat": ("rat",), "mouse": ("mouse", "mice")}
_NUMBER = re.compile(r"^-?\d*\.?\d+(?:[eE][-+]?\d+)?$")
_MATRIX_HEADER = re.compile(r"^(?P<matrix>\w+)\s+(?P<analyte>.+?)\s+Concentration\s*\((?P<unit>[^)]+)\)$")
_BLOOD_LOD = re.compile(r"limit of detection \(LOD\) for .+? in blood samples is\s+(\d+(?:\.\d+)?)", re.I)
_TISSUE_LOD = re.compile(r"For tissue samples, the LOD is [^.]*?(\d+(?:\.\d+)?)\s*ng/g", re.I)

KEY_COLUMNS = ["NTP Study Number", "Concentration", "Animal ID", "Sex", "Phase", "Day"]


def is_lab_results(sheet_names: list[str]) -> bool:
    return any(s.strip().endswith(_SHEET_SUFFIX) for s in sheet_names)


def _text(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def _header_index(rows: list[list]) -> int:
    for i, r in enumerate(rows):
        if r and _text(r[0]) == _HEADER_FIRST:
            return i
    raise ValueError(f"no '{_HEADER_FIRST}' header row")


def species_sheet(sheets: dict[str, list[list]], species: str) -> str:
    """The one sheet whose Strain/Species column names `species` ("rat", "mouse")."""
    words = _SPECIES_WORDS.get(species.lower())
    if not words:
        raise ValueError(f"unsupported species {species!r}")
    hits = []
    for name, rows in sheets.items():
        if not name.strip().endswith(_SHEET_SUFFIX):
            continue
        h = _header_index(rows)
        sid = [_text(c) for c in rows[h]].index("Subject ID")
        strains = {_text(r[0]).lower() for r in rows[h + 1:] if len(r) > sid and r[sid]}
        if strains and all(any(w in re.findall(r"[a-z]+", s) for w in words) for s in strains):
            hits.append(name)
    if len(hits) != 1:
        raise ValueError(f"{len(hits)} sheets hold {species} results: {hits}")
    return hits[0]


def detection_limits(rows: list[list]) -> tuple[str, str]:
    """(blood LOD, tissue LOD) from the sheet's footnote, as written ("0.0960")."""
    text = " ".join(_text(c) for r in rows for c in r if c) + " "
    b, t = _BLOOD_LOD.search(text), _TISSUE_LOD.search(text)
    if not (b and t):
        raise ValueError("the sheet states no blood and tissue limit of detection")
    return b.group(1), t.group(1)


def _animal_id(subject: str, group, sex: str) -> str:
    m = re.fullmatch(r"(\d+)([FM])(\d+)", subject)
    if not m or m.group(1) != str(group) or m.group(2) != sex[:1].upper():
        raise ValueError(f"Subject ID {subject!r} is not group {group} + {sex[:1]} + animal number")
    return str(int(m.group(3)))


def to_key_data(rows: list[list], study_number: str) -> tuple[list[str], list[list[str]], dict, list[str]]:
    """(header, body, units, notes) — the Tissue Concentration Key/Data rows of one sheet."""
    h = _header_index(rows)
    head = [_text(c) for c in rows[h]]
    col = {name: head.index(name) for name in
           ("Sex", "Subject ID", "Group #", "Exposure Concentration (ppm)")}
    day_idx = next(i for i, c in enumerate(head) if c.startswith("Study Day"))
    matrices = []
    for i, c in enumerate(head):
        m = _MATRIX_HEADER.match(c)
        if m:
            matrices.append((i, m.group("matrix").title(), m.group("analyte"), m.group("unit")))
    if not matrices:
        raise ValueError("no '<Matrix> <analyte> Concentration (<unit>)' columns")
    blood_lod, tissue_lod = detection_limits(rows[h + 1:])

    header = list(KEY_COLUMNS)
    units: dict[str, str] = {}
    for _, matrix, analyte, unit in matrices:
        conc, lod = f"{matrix} {analyte} Concentration", f"{matrix} {analyte} LOD"
        header += [conc, lod]
        units[conc] = units[lod] = unit

    body, not_sampled = [], 0
    for r in rows[h + 1:]:
        if not r or not _text(r[col["Subject ID"]]) or r[col["Group #"]] is None:
            continue
        sex = _text(r[col["Sex"]])
        day = re.fullmatch(r"Day\s*(\d+)", _text(r[day_idx]))
        if not day:
            raise ValueError(f"unreadable study day {r[day_idx]!r}")
        out = [study_number, _text(r[col["Exposure Concentration (ppm)"]]),
               _animal_id(_text(r[col["Subject ID"]]), r[col["Group #"]], sex), sex, "SD", day.group(1)]
        for i, matrix, _, _ in matrices:
            v = _text(r[i]) if i < len(r) else ""
            lod = blood_lod if matrix == "Blood" else tissue_lod
            if _NUMBER.match(v) or v.upper() == "BLOD":
                out += [v if _NUMBER.match(v) else "BLOD", lod]
            else:
                out += ["", ""]
                not_sampled += 1
        body.append(out)

    notes = [f"lab results sheet → Key/Data ({len(body)} animals); "
             f"LOD blood {blood_lod}, tissue {tissue_lod} from the sheet's footnote; "
             f"Subject ID group/sex prefix dropped"]
    if not_sampled:
        notes.append(f"{not_sampled} matrix value(s) not sampled → empty")
    return header, body, units, notes
