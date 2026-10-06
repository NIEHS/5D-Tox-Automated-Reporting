"""
Clinical observation incidence tables — categorical finding data.

Clinical observation CSVs contain per-animal-per-day categorical findings
(Normal, Hunched, Discharge, etc.) rather than continuous numeric endpoints.
This data cannot be modeled by BMDExpress (no dose-response curve fitting)
and is instead summarized as incidence tables: rows = composite findings,
columns = dose groups, cells = "n/N" (affected/total).

The module is separate from apical_report.py because:
  - Clinical obs data bypasses Java integration entirely (no BMDProject).
  - The output type (IncidenceRow) is structurally different from TableRow
    (no BMD, no stats, no mean±SE — just counts).
  - The CSV format is long-format categorical, not wide-format numeric.

Data flow:
  1. pool_integrator.py stores CSV paths in _meta.clinical_obs_files
     (instead of sending them to Java).
  2. pool_orchestrator.py calls build_clinical_obs_tables() at process time.
  3. The result is serialized as section cards with table_type="incidence".

CSV format expected (NTP clinical observations):
  NTP Study Number, Concentration, Animal ID, Sex, Selection,
  Observation Day, Observation, Site, Modifier, Severity

Composite finding label format:
  "Observation — Site, Modifier (Severity)"
  Parts that are empty are omitted.  "Normal" observations are excluded
  from the incidence count (they represent absence of findings).
"""

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data class — one row in the incidence table
# ---------------------------------------------------------------------------

@dataclass
class IncidenceRow:
    """
    One row in a clinical observation incidence table.

    Unlike TableRow (which holds mean±SE and BMD for continuous endpoints),
    IncidenceRow holds simple counts: how many animals in each dose group
    showed a particular finding at least once during the study.

    Attributes:
        label:             Composite finding label, e.g.
                           "Discharge — Eye, Bilateral, Red".
        incidence_by_dose: Dict mapping dose (float) to "n/N" string where
                           n = animals with the finding, N = total animals.
        total_n_by_dose:   Dict mapping dose (float) to total animal count N.
                           Redundant with the denominator in incidence_by_dose,
                           but kept separately so the frontend can access it
                           without parsing the string.
        onset_day_by_dose: Dict mapping dose (float) to the earliest study day
                           (int, from "SD0" etc.) any animal in that group showed
                           the finding — the "Lower row … day of observation
                           onset" of the NTP I05 summary.  Doses without the
                           finding, or rows without a parseable day, are absent.
    """
    label: str = ""
    incidence_by_dose: dict[float, str] = field(default_factory=dict)
    total_n_by_dose: dict[float, int] = field(default_factory=dict)
    onset_day_by_dose: dict[float, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Label construction
# ---------------------------------------------------------------------------

def _build_finding_label(observation: str, site: str, modifier: str, severity: str) -> str:
    """
    Build a composite finding label from the four CSV columns.

    Format: "Observation — Site, Modifier (Severity)"
    Empty parts are omitted.  The dash separator only appears if there's
    a site, modifier, or severity to show.

    Examples:
        ("Hunched", "", "", "")           → "Hunched"
        ("Discharge", "Eye", "Bilateral, Red", "")  → "Discharge — Eye, Bilateral, Red"
        ("Salivation", "", "", "Post Dosing")        → "Salivation (Post Dosing)"
        ("Breathing, labored", "", "", "")            → "Breathing, labored"

    Args:
        observation: The primary finding text (e.g., "Hunched", "Discharge").
        site:        Anatomical site (e.g., "Eye", "Nose/Snout").
        modifier:    Modifier text (e.g., "Bilateral, Red", "Red").
        severity:    Severity qualifier (e.g., "Post Dosing").

    Returns:
        Formatted composite label string.
    """
    # Start with the observation text (always present for non-Normal rows)
    parts = []
    if site:
        parts.append(site)
    if modifier:
        parts.append(modifier)

    label = observation
    if parts:
        label += " \u2014 " + ", ".join(parts)
    if severity:
        label += f" ({severity})"

    return label


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def parse_clinical_obs_csv(path: str, include_biosampling: bool = False) -> dict:
    """
    Parse a clinical observation CSV into structured per-dose-per-animal data.

    Reads the NTP-format CSV (with optional "# Provider/Platform/Data Type"
    header comments) and extracts all non-Normal observations.  Observations
    are collapsed across days: if animal 201 shows "Hunched" on SD1 and SD3,
    it counts as one occurrence for the incidence table.

    Only the Core cohort is counted unless ``include_biosampling``: the
    internal-dose animals ("Biosampling Animals" / "Biosample Animals" in the
    Selection column) are a separate cohort, and the NTP I05 summary reports
    them separately — pooling them into the core counts changes both the
    denominators and which findings appear.  A CSV with no Selection column
    is all core.

    Args:
        path: Absolute path to the clinical observation CSV file.
        include_biosampling: Also count the biosampling cohort.

    Returns:
        Dict with keys:
            "sex":      Sex string from the CSV (e.g., "Male", "Female").
            "findings": Dict mapping composite finding label to
                        {dose: set(animal_ids)} — the set of animals that
                        showed that finding at any observation day.
            "animals_by_dose": Dict mapping dose (float) to set(animal_ids)
                               — all animals in each dose group (including
                               those with only "Normal" observations).
            "onset": Dict mapping composite finding label to {dose: earliest
                     study day (int) the finding was observed}.
    """
    p = Path(path)
    if not p.exists():
        logger.warning("Clinical obs CSV not found: %s", path)
        return {"sex": "Unknown", "findings": {}, "animals_by_dose": {}, "onset": {}}

    with open(path, "r", newline="", encoding="utf-8") as f:
        # Skip comment lines (metadata headers like "# Provider: Apical")
        lines = []
        for line in f:
            if line.startswith("#"):
                continue
            lines.append(line)

    if not lines:
        return {"sex": "Unknown", "findings": {}, "animals_by_dose": {}, "onset": {}}

    reader = csv.DictReader(lines)

    # Normalise header names — the CSV may have varying capitalisation
    # but the column semantics are fixed by NTP convention.
    fieldname_map = {}
    for fn in (reader.fieldnames or []):
        fieldname_map[fn] = fn.strip()

    sex = "Unknown"
    # findings: {composite_label: {dose: set(animal_ids)}}
    findings: dict[str, dict[float, set[str]]] = {}
    # animals_by_dose: {dose: set(animal_ids)} — all animals regardless of finding
    animals_by_dose: dict[float, set[str]] = {}
    # onset: {composite_label: {dose: earliest study day observed}}
    onset: dict[str, dict[float, int]] = {}

    for row in reader:
        # Extract core columns — strip whitespace from values
        concentration = row.get("Concentration", "").strip()
        animal_id = row.get("Animal ID", "").strip()
        row_sex = row.get("Sex", "").strip()
        observation = row.get("Observation", "").strip()
        site = row.get("Site", "").strip()
        modifier = row.get("Modifier", "").strip()
        severity = row.get("Severity", "").strip()

        if not concentration or not animal_id:
            continue
        if not include_biosampling and "biosamp" in (row.get("Selection") or "").lower():
            continue

        try:
            dose = float(concentration)
        except (ValueError, TypeError):
            continue

        # Track sex from the first non-empty value
        if row_sex and sex == "Unknown":
            sex = row_sex.title()

        # Register this animal in its dose group (even if "Normal")
        animals_by_dose.setdefault(dose, set()).add(animal_id)

        # Skip "Normal" observations — they represent absence of findings
        # and should not appear as rows in the incidence table.
        if not observation or observation.lower() == "normal":
            continue

        # Build the composite finding label
        label = _build_finding_label(observation, site, modifier, severity)

        # Collapse across days: use a set so each animal counts once
        findings.setdefault(label, {}).setdefault(dose, set()).add(animal_id)
        day = _study_day(row.get("Observation Day"))
        if day is not None:
            by_dose = onset.setdefault(label, {})
            by_dose[dose] = min(day, by_dose.get(dose, day))

    return {
        "sex": sex,
        "findings": findings,
        "animals_by_dose": animals_by_dose,
        "onset": onset,
    }


def _study_day(value: str | None) -> int | None:
    """"SD0" / "SD 12" / "3" -> the study day number; None when absent."""
    m = re.search(r"-?\d+", str(value or ""))
    return int(m.group()) if m else None


# ---------------------------------------------------------------------------
# Incidence table construction
# ---------------------------------------------------------------------------

def build_incidence_table(parsed: dict) -> list[IncidenceRow]:
    """
    Convert parsed clinical obs data into a list of IncidenceRow objects.

    Each row represents one composite finding.  The incidence cell for each
    dose group is formatted as "n/N" where n = number of affected animals
    and N = total animals in that dose group.

    Rows are sorted alphabetically by label for consistent display.
    Dose groups with zero affected animals still show "0/N" — the full
    dose design is always visible.

    Args:
        parsed: Output from parse_clinical_obs_csv().

    Returns:
        List of IncidenceRow objects, sorted by label.
    """
    findings = parsed.get("findings", {})
    animals_by_dose = parsed.get("animals_by_dose", {})

    if not findings:
        return []

    # All dose levels in the study (sorted ascending)
    all_doses = sorted(animals_by_dose.keys())

    rows = []
    for label in sorted(findings.keys()):
        dose_animals = findings[label]
        incidence_by_dose = {}
        total_n_by_dose = {}

        for dose in all_doses:
            n_total = len(animals_by_dose.get(dose, set()))
            n_affected = len(dose_animals.get(dose, set()))
            incidence_by_dose[dose] = f"{n_affected}/{n_total}"
            total_n_by_dose[dose] = n_total

        rows.append(IncidenceRow(
            label=label,
            incidence_by_dose=incidence_by_dose,
            total_n_by_dose=total_n_by_dose,
            onset_day_by_dose=dict(parsed.get("onset", {}).get(label, {})),
        ))

    return rows


# ---------------------------------------------------------------------------
# Public API — build incidence tables from multiple CSV files
# ---------------------------------------------------------------------------

def build_clinical_obs_tables(
    csv_paths: list[str], include_biosampling: bool = False,
) -> dict[str, list[IncidenceRow]]:
    """
    Build incidence tables from one or more clinical observation CSV files.

    Each CSV typically covers one sex (male or female).  The function parses
    each file, builds the incidence table, and groups results by sex.

    If multiple CSVs have the same sex, their findings are merged: the union
    of animals is used for the denominator, and the union of affected animals
    for the numerator.

    Args:
        csv_paths: List of absolute paths to clinical observation CSV files.
        include_biosampling: Also count the biosampling (internal-dose)
                             cohort; by default only Core animals count
                             (see parse_clinical_obs_csv).

    Returns:
        Dict mapping sex label ("Male", "Female") to list of IncidenceRow.
        Empty dict if no findings (all Normal) or no valid CSVs.
    """
    # Parse all CSVs first, then merge by sex
    parsed_by_sex: dict[str, dict] = {}

    for path in csv_paths:
        parsed = parse_clinical_obs_csv(path, include_biosampling)
        sex = parsed["sex"]

        if sex not in parsed_by_sex:
            # First CSV for this sex — use as-is
            parsed_by_sex[sex] = parsed
        else:
            # Merge findings and animals into the existing entry.
            # This handles the rare case of multiple CSVs for the same sex
            # (e.g., split by study number or observation period).
            existing = parsed_by_sex[sex]
            for dose, aids in parsed["animals_by_dose"].items():
                existing["animals_by_dose"].setdefault(dose, set()).update(aids)
            for label, dose_animals in parsed["findings"].items():
                for dose, aids in dose_animals.items():
                    existing["findings"].setdefault(label, {}).setdefault(dose, set()).update(aids)
            for label, by_dose in parsed.get("onset", {}).items():
                merged = existing.setdefault("onset", {}).setdefault(label, {})
                for dose, day in by_dose.items():
                    merged[dose] = min(day, merged.get(dose, day))

    # Build incidence tables per sex
    result: dict[str, list[IncidenceRow]] = {}
    for sex, parsed in sorted(parsed_by_sex.items()):
        rows = build_incidence_table(parsed)
        if rows:
            result[sex] = rows

    return result


# ---------------------------------------------------------------------------
# DOCX export — incidence table in Word format
# ---------------------------------------------------------------------------

