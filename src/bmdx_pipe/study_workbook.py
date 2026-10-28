"""
study_workbook — read an NTP Individual Animal workbook, once, by column name.

The study team records each platform of a study as an "Individual Animal"
workbook (``C20022-01_Individual_Animal_Body_Weight_Data.xlsx``) with two sheets:

  * **Key to Column Labels** — a data dictionary.  Column A is each Data column's
    label and column B explains it ("Albumin in g/dL", "Dose in mg/kg").  Column D
    of the first four rows names the study: its title, study type ("TOX",
    "5-Day Toxicity"), study number and date.
  * **Data** — one row per animal and observation: study number, dose
    ("Concentration"), animal, sex, selection (core / biosampling), the study day,
    and the platform's measured columns.

The workbook is the study's own record, so it is the reference the other files
are checked against (ADR-0017, ADR-0032).  Everything that reads a workbook goes
through ``read_study_workbook``, which finds every column by its name, never its
position, and smooths over the layouts CEBS has published:

  * 2020–2021 (NIEHS-07 … 10): NTP Study Number, Concentration, Animal ID, Sex,
    Selection, …
  * the male-only Tgx studies (RR-8, NIEHS-06): no Sex and no Selection column;
    the title says "(Male)".
  * 2025 (NIEHS-12, 13): "Study Number" for "NTP Study Number", and no Sex
    column; the title says "in Female Sprague Dawley Rats".

A missing Sex column is filled from the sex the title names (and the reader
notes that it did); a title naming both sexes or neither leaves it missing.

The CEBS database-export layout (NIEHS-02 … 05: one sheet of DEPOSITOR_STUDY_NUMBER,
DOSE, ANMLNUM, …) is not a study workbook; rlm-bmdx's tooling converts it first.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

KEY_SHEET = "Key to Column Labels"
DATA_SHEET = "Data"

# Data-sheet columns that describe the animal or the observation rather than a
# measured endpoint (lower case).  "observation" … "severity" are the clinical
# observation workbook's finding columns, which are categorical, not endpoints.
META_COLS = {
    "ntp study number", "concentration", "animal id", "sex",
    "selection", "observation day", "removal day", "terminal flag",
    "phase", "day",
    "observation", "site", "modifier", "severity",
}

STUDY_NUMBER_COL = "NTP Study Number"

_SEX_WORDS = re.compile(r"\b(Male|Female)s?\b", re.I)
_DOSE_IN = re.compile(r"\b(?:dose|concentration|exposure)\s+in\s+(\S+)", re.I)
_DATE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


@dataclass
class StudyWorkbook:
    """What one study workbook says.

    ``header`` and ``rows`` are the Data sheet as text, normalised: labels
    stripped, "Study Number" renamed "NTP Study Number", a Sex column inserted
    after Animal ID when it was filled from the title, empty rows dropped, and
    every row padded to the header's length.  Cells are the workbook's text
    (``str`` of the cell value, stripped; "" for an empty cell)."""

    path: str
    sheetnames: list[str] = field(default_factory=list)
    # Key + Data sheets: the NTP study-file structure.
    is_study_file: bool = False

    # Key sheet, column D of the first four rows.
    title: str | None = None
    study_type: str | None = None
    study_number: str | None = None
    date: str | None = None            # ISO 8601

    # Key sheet, columns A and B: {column label: explanation}.
    explanations: dict[str, str] = field(default_factory=dict)

    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)

    # The sex written into a Sex column the Data sheet lacked (from the title).
    sex_filled: str | None = None
    notes: list[str] = field(default_factory=list)

    # ── columns ──────────────────────────────────────────────────────────
    def col(self, name: str) -> int | None:
        """Index of the Data column labelled ``name`` (case-insensitive), or None."""
        name = name.lower()
        for i, h in enumerate(self.header):
            if h.lower() == name:
                return i
        return None

    @property
    def endpoint_cols(self) -> list[int]:
        """Indices of the measured columns: everything that isn't META_COLS."""
        return [i for i, h in enumerate(self.header)
                if h and h.lower() not in META_COLS]

    @property
    def endpoints(self) -> list[str]:
        return [self.header[i] for i in self.endpoint_cols]

    # ── what the Key sheet states ────────────────────────────────────────
    @property
    def units(self) -> dict[str, str]:
        """{endpoint column: unit} as the Key sheet states it (see explanation_unit)."""
        units = {}
        for label, text in self.explanations.items():
            if label.lower() in META_COLS:
                continue
            unit = explanation_unit(text)
            if unit:
                units[label] = unit
        return units

    @property
    def dose_unit(self) -> str | None:
        """The unit the Key sheet gives the doses in ("Dose in mg/kg" → "mg/kg",
        "Exposure in ppm" → "ppm")."""
        for label, text in self.explanations.items():
            if label.lower() == "concentration":
                m = _DOSE_IN.search(text)
                return m.group(1) if m else None
        return None

    @property
    def title_facts(self) -> dict[str, str]:
        """The study-design facts the title states (see title_facts)."""
        return title_facts(self.title or "")

    @property
    def held_study_numbers(self) -> list[str]:
        """The study numbers the Data sheet's rows carry."""
        i = self.col(STUDY_NUMBER_COL)
        if i is None:
            return []
        return sorted({r[i] for r in self.rows} - {""})

    # ── rows ─────────────────────────────────────────────────────────────
    def observations(self):
        """Each Data row as an Observation (see there).  Rows without an animal
        are skipped."""
        aid_i = self.col("Animal ID")
        if aid_i is None:
            return
        dose_i = self.col("Concentration")
        sex_i = self.col("Sex")
        sel_i = self.col("Selection")
        term_i = self.col("Terminal Flag")
        obs_i = self.col("Observation Day")
        rem_i = self.col("Removal Day")
        phase_i, day_i = self.col("Phase"), self.col("Day")
        endpoint_cols = self.endpoint_cols
        for r in self.rows:
            aid = r[aid_i]
            if not aid:
                continue
            dose_text = r[dose_i] if dose_i is not None else ""
            try:
                dose = float(dose_text)
            except ValueError:
                dose = None
            # The study day: Observation Day (body weight, clinical pathology),
            # Removal Day (organ weight, hormones), or Phase + Day (tissue
            # concentration: "SD" + "4").
            if obs_i is not None:
                day = r[obs_i]
            elif rem_i is not None:
                day = r[rem_i]
            elif phase_i is not None and day_i is not None:
                day = f"{r[phase_i]}{r[day_i]}"
            else:
                day = ""
            terminal = r[term_i] if term_i is not None else ""
            yield Observation(
                animal_id=aid,
                dose_text=dose_text,
                dose=dose,
                sex=(r[sex_i].title() if sex_i is not None else ""),
                selection=(r[sel_i] if sel_i is not None else ""),
                day=day,
                terminal_text=terminal,
                values={self.header[i]: r[i] for i in endpoint_cols},
            )


@dataclass
class Observation:
    """One Data row: an animal, its dose and group, the day, and the values.

    ``dose`` is None when the Concentration cell isn't a number.  ``sex`` is
    title-cased ("Male"), "" when the workbook doesn't say.  ``values`` maps each
    endpoint column to its cell text ("NA" and "" included)."""

    animal_id: str
    dose_text: str
    dose: float | None
    sex: str
    selection: str
    day: str
    terminal_text: str
    values: dict[str, str]

    @property
    def terminal(self) -> bool:
        return self.terminal_text.lower() in ("yes", "true", "1")


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def read_study_workbook(path: str) -> StudyWorkbook:
    """Read a study workbook (see the module docstring).  A file that can't be
    opened, or has no Data sheet, comes back with no rows and a note."""
    import openpyxl

    wb_out = StudyWorkbook(path=path)
    try:
        # Not read_only: CEBS workbooks declare a stale sheet dimension (A1),
        # which read-only mode trusts and so yields no rows.
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as e:
        logger.warning("Could not open xlsx %s: %s", path, e)
        wb_out.notes.append(f"could not open the workbook: {e}")
        return wb_out
    try:
        wb_out.sheetnames = list(wb.sheetnames)
        has_key = any("Key to" in s for s in wb.sheetnames)
        wb_out.is_study_file = has_key and DATA_SHEET in wb.sheetnames
        if has_key:
            key_name = KEY_SHEET if KEY_SHEET in wb.sheetnames else next(
                s for s in wb.sheetnames if "Key to" in s)
            _read_key(wb[key_name], wb_out)
        if DATA_SHEET in wb.sheetnames:
            _read_data(wb[DATA_SHEET], wb_out)
        else:
            wb_out.notes.append("no Data sheet")
    finally:
        wb.close()
    return wb_out


def _read_key(ws, out: StudyWorkbook) -> None:
    """Column A/B: the label → explanation dictionary.  Column D of rows 1–4:
    title, study type, study number, date (the date is recognised by its form
    wherever it sits in column D)."""
    col_d: list[str] = []
    for row in ws.iter_rows(values_only=True):
        cells = [_text(c) for c in row]
        if len(cells) >= 4 and cells[3]:
            col_d.append(cells[3])
            if _DATE.match(cells[3]) and out.date is None:
                try:
                    out.date = datetime.strptime(cells[3], "%m/%d/%Y").isoformat()
                except ValueError:
                    pass
        else:
            col_d.append("")
        if len(cells) >= 2 and cells[0] and cells[1] and cells[0] != "Column Label":
            out.explanations[cells[0]] = cells[1]
    first4 = (col_d + ["", "", "", ""])[:4]
    out.title = first4[0] or None
    out.study_type = first4[1] or None
    out.study_number = first4[2] if first4[2] and not _DATE.match(first4[2]) else None


def _read_data(ws, out: StudyWorkbook) -> None:
    rows = [[_text(c) for c in r] for r in ws.iter_rows(values_only=True)]
    if not rows:
        out.notes.append("empty Data sheet")
        return
    header = rows[0]
    # Trailing empty header cells (RR-8: "Removal Day", …, "", "") carry nothing.
    while header and not header[-1]:
        header = header[:-1]
    width = len(header)
    body = [(r + [""] * width)[:width] for r in rows[1:] if any(r)]
    if header and header[0] == "Study Number":
        header[0] = STUDY_NUMBER_COL
        out.notes.append("'Study Number' read as 'NTP Study Number'")
    out.header, out.rows = header, body

    if out.col("Sex") is None and out.col("Animal ID") is not None:
        sexes = title_sexes(out.title or "")
        if len(sexes) == 1:
            sex = sexes[0]
            i = out.col("Animal ID") + 1
            out.header = header[:i] + ["Sex"] + header[i:]
            out.rows = [r[:i] + [sex] + r[i:] for r in body]
            out.sex_filled = sex
            out.notes.append(f"no Sex column: '{sex}' from the Key sheet's title")
        else:
            out.notes.append("no Sex column, and the title does not name exactly one sex")

    if out.study_number is None:
        held = out.held_study_numbers
        if len(held) == 1:
            out.study_number = held[0]


# ── Key-sheet text ───────────────────────────────────────────────────────

def explanation_unit(text: str) -> str | None:
    """The unit a Key-sheet explanation states, or None.

    Two forms, which vary by platform and by study:
      "Albumin in g/dL", "Heart weight in grams"            → trailing " in <unit>"
      "Concentration of X in plasma 2 hours post-dosing (ug/ml)" → trailing "(<unit>)"
    The unit is copied as written (display normalisation is the report's job).
    An explanation in neither form, or a multi-word phrase that cannot be told
    from prose, gives None rather than a guess."""
    m = re.search(r"\(([^()]+)\)\s*$", text)
    if m:
        unit = m.group(1).strip()
        # "(SD = Study day; )" and other parenthetical prose are not units.
        return unit if re.fullmatch(r"[^\s=;,]+", unit) else None
    m = re.search(r"\sin\s+([^\s]+)\s*$", text)
    return m.group(1) if m else None


def title_sexes(title: str) -> list[str]:
    """The sexes a study title names ("in Female Sprague Dawley Rats" → ["Female"])."""
    return sorted({m.group(1).title() for m in _SEX_WORDS.finditer(title)})


# How the title says the article was given → (articleRoute, administrationMeans),
# in the metadata vocabulary (experiment_metadata.VOCABULARIES).
_ADMINISTRATION = [
    (re.compile(r"\bwhole[- ]body\s+inhalation\b", re.I), ("inhaled", "whole-body")),
    (re.compile(r"\bnose[- ]only\s+inhalation\b", re.I), ("inhaled", "nose-only")),
    (re.compile(r"\binhalation\b", re.I), ("inhaled", None)),
    (re.compile(r"\bgavage\b", re.I), ("oral", "gavage")),
    (re.compile(r"\bdrinking\s+water\b", re.I), ("oral", "drinking water")),
    (re.compile(r"\b(?:dosed\s+)?feed\b", re.I), ("oral", "dietary")),
    (re.compile(r"\bdermal\b", re.I), ("transdermal", None)),
]

_SPECIES = [(re.compile(r"\brats?\b", re.I), "rat"),
            (re.compile(r"\b(?:mice|mouse)\b", re.I), "mouse")]

_DURATION = re.compile(r"\b(\d+)[- ]day\b", re.I)


def title_facts(title: str) -> dict[str, str]:
    """The study-design facts a study title states, in the metadata vocabulary.

    "Evaluation of … in Sprague Dawley Rats (Hsd:Sprague Dawley® SD®) Treated via
    Oral Gavage" → {species: rat, strain: Sprague-Dawley, articleRoute: oral,
    administrationMeans: gavage}.  "5-Day Whole Body Inhalation Toxicity Study of
    … in Female B6D2F1/Crl Mice" adds studyDuration 5d and sex female.  Only what
    the title says, in a vocabulary value; nothing else is filled in."""
    from .experiment_metadata import VOCABULARIES

    facts: dict[str, str] = {}
    if not title:
        return facts
    species = {s for pat, s in _SPECIES if pat.search(title)}
    if len(species) == 1:
        facts["species"] = species.pop()
    strains = VOCABULARIES["strain"]
    candidates = (strains.get(facts["species"], []) if "species" in facts
                  else [s for v in strains.values() for s in v])
    flat = re.sub(r"[-\s]+", " ", title).lower()
    found = [s for s in candidates
             if re.search(rf"(?<![\w]){re.escape(re.sub(r'[-\s]+', ' ', s).lower())}(?![\w])", flat)]
    if len(found) == 1:
        facts["strain"] = found[0]
    for pat, (route, means) in _ADMINISTRATION:
        if pat.search(title):
            facts["articleRoute"] = route
            if means:
                facts["administrationMeans"] = means
            break
    m = _DURATION.search(title)
    if m and f"{m.group(1)}d" in VOCABULARIES["studyDuration"]:
        facts["studyDuration"] = f"{m.group(1)}d"
    sexes = title_sexes(title)
    if len(sexes) == 1:
        facts["sex"] = sexes[0].lower()
    return facts
