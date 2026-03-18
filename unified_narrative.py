"""
Unified apical narrative generator — cross-platform NTP-style results prose.

The NIEHS reference report (Bookshelf_NBK589955.pdf) groups its results into
two unified narrative sections, each spanning multiple measurement platforms:

  1. "Animal Condition, Body Weights, and Organ Weights" (p.11)
     — one narrative covering mortality, clinical signs, body weight findings,
       and organ weight findings, followed by Tables 2-3.

  2. "Clinical Pathology" (p.14)
     — one narrative covering clinical chemistry, hematology, and hormones,
       followed by Tables 4-6.

Previously, `generate_results_narrative()` in bmdx-pipe was called per-platform
inside `_build_section_cards()`, producing isolated per-card narratives.  This
module replaces that with two unified cross-platform narrative generators that
match the reference report's structure.

This is presentation logic (report writing), so it lives in rlm-bmdx (the web
app), not in bmdx-pipe (the pipeline library).  See CLAUDE.md TODO:
"Move generate_results_narrative out of bmdx-pipe".

Depends on:
  - bmdx_pipe.apical_report.TableRow  — the per-endpoint data row
  - Body weight sidecar JSON           — per-animal terminal day for mortality
  - bmdx_pipe.clinical_observations.IncidenceRow — clinical obs incidence
"""

import json
import logging
import re
from collections import Counter
from typing import Any

from bmdx_pipe import TableRow

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

# Platform groupings matching the NIEHS reference report structure.
# These canonical platform names come from _BM2_PLATFORM_MAP in file_integrator.
APICAL_PLATFORMS = {"Body Weight", "Organ Weight"}
CLINICAL_PATH_PLATFORMS = {"Clinical Chemistry", "Hematology", "Hormones"}

# Ordering within the clinical pathology narrative — the reference report
# presents sub-platforms in this sequence (p.14-15).
CLINICAL_PATH_ORDER = ["Clinical Chemistry", "Hematology", "Hormones"]


# ═══════════════════════════════════════════════════════════════════════════
# Helper functions — copied from bmdx_pipe/apical_report.py
# ═══════════════════════════════════════════════════════════════════════════
# These are private helpers in bmdx-pipe that aren't part of its public API.
# Rather than modifying bmdx-pipe's exports, we copy them here.  When
# bmdx-pipe's generate_results_narrative() is eventually deprecated, these
# become the only copies.


def _parse_cell_mean(cell_text: str) -> float | None:
    """
    Extract the numeric mean from a formatted table cell value.

    Table cells look like "330.2 ± 5.1**" — this function pulls out
    the leading number (330.2) and ignores the SE and significance markers.

    Args:
        cell_text: Formatted cell string, e.g., "330.2 ± 5.1**".

    Returns:
        The mean as a float, or None if parsing fails.
    """
    if not cell_text or cell_text.strip() == "–":
        return None
    # Match the leading number (possibly negative, with decimal)
    match = re.match(r"(-?\d+\.?\d*)", cell_text.strip())
    if match:
        return float(match.group(1))
    return None


def _parse_organ_label(label: str) -> tuple[str, str]:
    """
    Parse an endpoint label into (organ_name, weight_type).

    The .bm2 endpoint labels follow patterns like:
        "Liver Absolute"       → ("Liver", "absolute")
        "Liver Weight Relative" → ("Liver", "relative")
        "R. Kidney Absolute"   → ("R. Kidney", "absolute")
        "Terminal Body Wt."    → ("", "body_weight")
        "SD5"                  → ("", "body_weight")
        "Alanine aminotransferase" → ("Alanine aminotransferase", "endpoint")

    The organ_name is used to group absolute/relative pairs.  "endpoint" is
    for clinical pathology endpoints whose narrative omits the word "weight".

    Args:
        label: The endpoint label string from the TableRow.

    Returns:
        A 2-tuple (organ_name, weight_type) where weight_type is one of:
        "absolute", "relative", "body_weight", or "endpoint".
    """
    lower = label.lower()

    # Body weight endpoints — various naming conventions from BMDExpress
    if "body" in lower and ("wt" in lower or "weight" in lower):
        return ("", "body_weight")

    # "SD5", "SD 5", etc. — Study Day N terminal body weight labels
    if re.match(r"^sd\s*\d+$", lower):
        return ("", "body_weight")

    # Organ weight endpoints — last word is "Absolute" or "Relative"
    if lower.endswith("absolute"):
        organ = label[: -len("Absolute")].strip()
        organ = re.sub(r"\s+(?:Weight|Wt\.?)$", "", organ, flags=re.IGNORECASE)
        return (organ, "absolute")
    elif lower.endswith("relative"):
        organ = label[: -len("Relative")].strip()
        organ = re.sub(r"\s+(?:Weight|Wt\.?)$", "", organ, flags=re.IGNORECASE)
        return (organ, "relative")

    # Fallback: clinical pathology or other non-weight endpoints
    return (label, "endpoint")


def _endpoint_direction(row: TableRow) -> str:
    """
    Determine whether an endpoint increased or decreased relative to control.

    Compares the control group mean to the highest-dose group mean.  This
    is a simplification — real studies might have non-monotonic responses —
    but it matches the NTP report convention of reporting the overall
    direction of the dose-response.

    Args:
        row: A TableRow with values_by_dose.

    Returns:
        "increase" or "decrease".
    """
    sorted_doses = sorted(row.values_by_dose.keys())
    if len(sorted_doses) < 2:
        return "increase"  # fallback

    control_mean = _parse_cell_mean(row.values_by_dose.get(sorted_doses[0], ""))
    highest_mean = _parse_cell_mean(row.values_by_dose.get(sorted_doses[-1], ""))

    if control_mean is None or highest_mean is None:
        return "increase"  # fallback

    return "decrease" if highest_mean < control_mean else "increase"


def _lowest_sig_dose(row: TableRow) -> float | None:
    """
    Find the lowest non-control dose group that has pairwise significance.

    Significance is indicated by * or ** appended to the cell value.
    The control dose (0.0) is excluded because its marker represents the
    trend test, not pairwise comparison.

    Args:
        row: A TableRow with values_by_dose containing formatted strings.

    Returns:
        The lowest dose (float) with a pairwise significance marker,
        or None if no treatment dose is significant.
    """
    sorted_doses = sorted(row.values_by_dose.keys())
    for dose in sorted_doses:
        if dose == 0.0:
            continue
        val = row.values_by_dose.get(dose, "")
        if "*" in val:
            return dose
    return None


def _fmt_dose(dose: float) -> str:
    """
    Format a dose value for prose output.

    Drops trailing ".0" for integer-valued doses to match natural writing
    style:  12.0 → "12", 0.15 → "0.15".

    Args:
        dose: Dose value in dose units.

    Returns:
        Clean string representation.
    """
    if dose == int(dose):
        return str(int(dose))
    return str(dose)


def _oxford_comma(items: list[str], conjunction: str = "or") -> str:
    """
    Join a list of strings with an Oxford comma.

    Follows the NTP report convention:
        []            → ""
        ["a"]         → "a"
        ["a", "b"]    → "a or b"
        ["a", "b", "c"] → "a, b, or c"

    Args:
        items:       List of strings to join.
        conjunction: The conjunction word ("or", "and").

    Returns:
        The joined string with Oxford comma formatting.
    """
    if len(items) == 0:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conjunction} {items[1]}"
    return ", ".join(items[:-1]) + f", {conjunction} {items[-1]}"


# ═══════════════════════════════════════════════════════════════════════════
# Mortality extraction from body weight sidecar JSON
# ═══════════════════════════════════════════════════════════════════════════


def extract_mortality(sidecar_paths: dict[str, str]) -> dict:
    """
    Extract mortality data from body weight sidecar JSON files.

    Animals whose terminal observation falls before the expected terminal day
    (the most common terminal day across the study, usually the last study day
    like SD5) are counted as early deaths.  For example, an animal with
    terminal=true on SD0 when the expected day is SD5 means it was "found dead
    on study day 0".

    Args:
        sidecar_paths: Dict mapping sex label ("Male"/"Female") to the
                       absolute path of the sidecar JSON file.  Produced by
                       body_weight_table.find_sidecar_paths().

    Returns:
        Dict with structure:
        {
            "expected_terminal_day": "SD5",
            "by_dose": {
                dose_float: {
                    sex_str: {
                        "total": int,           # animals assigned to this group
                        "early_deaths": int,     # terminated before expected day
                        "death_days": {"SD0": 1, "SD1": 3},  # when they died
                    }
                }
            },
            "all_survived_doses": [0.0, 0.15, ...],  # doses where nobody died early
        }
        Empty dict if no sidecar files are available.
    """
    if not sidecar_paths:
        return {}

    # First pass: collect ALL terminal days across both sexes to find the
    # expected (modal) terminal day.  This is study-wide, not per-sex.
    all_terminal_days: list[str] = []
    # Collect per-animal records grouped by (dose, sex)
    animal_records: dict[tuple[float, str], list[dict]] = {}

    for sex, sc_path in sidecar_paths.items():
        try:
            with open(sc_path, "r") as f:
                sc = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read sidecar %s: %s", sc_path, exc)
            continue

        for _animal_id, animal in sc.get("animals", {}).items():
            dose = float(animal.get("dose", 0.0))
            key = (dose, sex)
            animal_records.setdefault(key, [])

            # Find terminal observation for this animal
            terminal_day = None
            for obs in animal.get("observations", []):
                if obs.get("terminal"):
                    terminal_day = obs.get("day", "")
                    all_terminal_days.append(terminal_day)
                    break

            animal_records[key].append({
                "terminal_day": terminal_day,
            })

    if not all_terminal_days:
        return {}

    # The expected terminal day is the mode — the day most animals terminate
    # on, which is the scheduled sacrifice day (e.g., SD5 for a 5-day study).
    day_counts = Counter(all_terminal_days)
    expected_day = day_counts.most_common(1)[0][0]

    # Parse the numeric portion of a study day label for comparison.
    # "SD5" → 5, "SD0" → 0.  Handles "SD 5" and "SD05" too.
    def _day_num(day_str: str) -> int:
        match = re.search(r"\d+", day_str or "")
        return int(match.group()) if match else -1

    expected_day_num = _day_num(expected_day)

    # Second pass: compute mortality per (dose, sex) group
    by_dose: dict[float, dict[str, dict]] = {}
    all_doses: set[float] = set()

    for (dose, sex), records in animal_records.items():
        all_doses.add(dose)
        total = len(records)
        early_deaths = 0
        death_days: dict[str, int] = {}

        for rec in records:
            td = rec["terminal_day"]
            if td and _day_num(td) < expected_day_num:
                early_deaths += 1
                death_days[td] = death_days.get(td, 0) + 1

        by_dose.setdefault(dose, {})[sex] = {
            "total": total,
            "early_deaths": early_deaths,
            "death_days": death_days,
        }

    # Identify doses where all animals (both sexes) survived to the expected day
    all_survived_doses = []
    for dose in sorted(all_doses):
        dose_data = by_dose.get(dose, {})
        any_deaths = any(
            sex_data.get("early_deaths", 0) > 0
            for sex_data in dose_data.values()
        )
        if not any_deaths:
            all_survived_doses.append(dose)

    return {
        "expected_terminal_day": expected_day,
        "by_dose": by_dose,
        "all_survived_doses": all_survived_doses,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Paragraph builders — internal building blocks
# ═══════════════════════════════════════════════════════════════════════════


def _build_animal_condition_paragraphs(
    compound_name: str,
    dose_unit: str,
    mortality: dict,
    clinical_obs_incidence: dict[str, list] | None,
) -> list[str]:
    """
    Build the "Animal Condition" paragraph(s) for the apical narrative.

    Reference (p.11): "Male and female rats administered 333 and 1000 mg/kg
    of PFHxSAm began exhibiting signs of overt toxicity on study day 0,
    which included ..."

    This is the opening paragraph of the "Animal Condition, Body Weights,
    and Organ Weights" section.  It describes mortality (from sidecar data)
    and clinical signs (from clinical obs incidence data).

    Args:
        compound_name:          Chemical name for prose.
        dose_unit:              Dose unit string (e.g., "mg/kg").
        mortality:              Output from extract_mortality().
        clinical_obs_incidence: Optional {sex: [IncidenceRow]} from
                                build_clinical_obs_tables().  Used to list
                                clinical signs.

    Returns:
        List of paragraph strings (usually 1-2 paragraphs).
    """
    paragraphs: list[str] = []

    if not mortality or not mortality.get("by_dose"):
        # No mortality data available — skip the animal condition paragraph.
        # The per-card narrative from bmdx-pipe never included this, so this
        # is a graceful no-op for sessions without sidecar files.
        return paragraphs

    by_dose = mortality["by_dose"]
    expected_day = mortality.get("expected_terminal_day", "")
    all_survived = mortality.get("all_survived_doses", [])

    # Identify doses with any early deaths (either sex)
    death_doses: list[float] = []
    for dose in sorted(by_dose.keys()):
        dose_data = by_dose[dose]
        total_deaths = sum(
            sd.get("early_deaths", 0) for sd in dose_data.values()
        )
        if total_deaths > 0:
            death_doses.append(dose)

    if not death_doses:
        # No mortality — brief statement that all survived
        paragraphs.append(
            f"All male and female rats survived to study termination "
            f"({expected_day}) without signs of overt toxicity."
        )
        return paragraphs

    # ── Build the mortality/toxicity paragraph ──

    # List the affected dose groups
    death_dose_strs = [_fmt_dose(d) for d in death_doses]
    dose_list_str = _oxford_comma(death_dose_strs, conjunction="and")

    # Earliest study day any death occurred (across all affected doses)
    earliest_death_day: str | None = None
    earliest_day_num = 999
    for dose in death_doses:
        for sex_data in by_dose[dose].values():
            for day_str in sex_data.get("death_days", {}):
                match = re.search(r"\d+", day_str)
                if match:
                    dnum = int(match.group())
                    if dnum < earliest_day_num:
                        earliest_day_num = dnum
                        earliest_death_day = day_str

    # Clinical signs from incidence data (if available)
    clinical_signs: list[str] = []
    if clinical_obs_incidence:
        # Collect unique finding labels across both sexes, up to 5 for brevity
        seen: set[str] = set()
        for _sex, rows in clinical_obs_incidence.items():
            for row in rows:
                # IncidenceRow.label looks like "Discharge — Eye, Bilateral, Red"
                # We want the primary finding (before the comma detail)
                label = row.label if hasattr(row, "label") else str(row)
                if label not in seen:
                    seen.add(label)
                    clinical_signs.append(label.lower())

    # Build the opening sentence
    parts: list[str] = []
    parts.append(
        f"Male and female rats administered {dose_list_str} {dose_unit} "
        f"of {compound_name}"
    )
    if earliest_death_day:
        parts.append(
            f" began exhibiting signs of overt toxicity on study day "
            f"{earliest_day_num}"
        )
    if clinical_signs:
        # Limit to first 5 signs to keep prose manageable
        sign_list = _oxford_comma(clinical_signs[:5], conjunction="and")
        parts.append(f", which included {sign_list}")
    parts.append(".")

    sentence1 = "".join(parts)

    # Per-dose mortality details: "In the 1000 mg/kg group, 5 male rats
    # and 5 female rats were found dead or moribund..."
    death_details: list[str] = []
    for dose in death_doses:
        dose_data = by_dose[dose]
        sex_counts: list[str] = []
        # Latest death day for this dose (for the "by study day X" clause)
        latest_day_num = 0
        for sex in ["Male", "Female"]:
            sd = dose_data.get(sex, {})
            n_dead = sd.get("early_deaths", 0)
            if n_dead > 0:
                sex_counts.append(f"{n_dead} {sex.lower()} {'rat' if n_dead == 1 else 'rats'}")
                for day_str in sd.get("death_days", {}):
                    match = re.search(r"\d+", day_str)
                    if match:
                        dnum = int(match.group())
                        if dnum > latest_day_num:
                            latest_day_num = dnum
        if sex_counts:
            count_str = _oxford_comma(sex_counts, conjunction="and")
            detail = (
                f"In the {_fmt_dose(dose)} {dose_unit} group, {count_str} "
                f"were found dead or moribund"
            )
            if latest_day_num > 0:
                detail += f" by study day {latest_day_num}"
            detail += "."
            death_details.append(detail)

    # Surviving doses sentence
    surviving_sentence = ""
    if all_survived:
        surviving_dose_strs = [_fmt_dose(d) for d in all_survived if d > 0]
        if surviving_dose_strs:
            surv_list = _oxford_comma(surviving_dose_strs, conjunction="and")
            surviving_sentence = (
                f"Rats in the {surv_list} {dose_unit} groups did not exhibit "
                f"signs of overt toxicity, and all survived to study termination."
            )

    # Combine into the paragraph
    para_parts = [sentence1]
    para_parts.extend(death_details)
    if surviving_sentence:
        para_parts.append(surviving_sentence)

    paragraphs.append(" ".join(para_parts))
    return paragraphs


def _build_body_weight_paragraphs(
    platform_tables: dict[str, dict[str, list]],
    compound_name: str,
    dose_unit: str,
) -> list[str]:
    """
    Build body weight finding paragraphs from the Body Weight platform data.

    Follows the reference report convention (p.11):
      - If not significant: "No significant changes in terminal body weight
        for male rats (Table 2) or female rats (Table 2) occurred..."
      - If significant: "Terminal body weight was significantly {dir} in
        {sex} rats at ≥{loel} {dose_unit} with a {trend} trend (Table 2).
        The BMD and BMDL were {bmd} and {bmdl} {dose_unit}, respectively."

    Args:
        platform_tables: The full {platform -> {sex -> [TableRow]}} dict.
        compound_name:   Chemical name for prose.
        dose_unit:       Dose unit string.

    Returns:
        List of paragraph strings (usually 1 paragraph).
    """
    bw_data = platform_tables.get("Body Weight", {})
    if not bw_data:
        return []

    bw_findings: list[str] = []

    for sex in ["Male", "Female"]:
        rows = bw_data.get(sex, [])
        bw_rows = [r for r in rows if _parse_organ_label(r.label)[1] == "body_weight"]

        for bw_row in bw_rows:
            if not bw_row.responsive or bw_row.bmd_str == "ND":
                # Not significant — just note the sex for the combined sentence
                bw_findings.append(f"{sex.lower()} rats (Table 2)")
            else:
                # Significant — full sentence with direction, LOEL, BMD
                direction = _endpoint_direction(bw_row)
                low_dose = _lowest_sig_dose(bw_row)
                trend_dir = "positive" if direction == "increase" else "negative"

                parts = [
                    f"Terminal body weight was significantly "
                    f"{'increased' if direction == 'increase' else 'decreased'} "
                    f"in {sex.lower()} rats"
                ]
                if low_dose is not None:
                    parts.append(f" at ≥{_fmt_dose(low_dose)} {dose_unit}")
                parts.append(
                    f" with a {trend_dir} trend (Table 2). "
                    f"The BMD and BMDL were {bw_row.bmd_str} and "
                    f"{bw_row.bmdl_str} {dose_unit}, respectively."
                )
                bw_findings.append("".join(parts))

    if not bw_findings:
        return []

    # Check if ALL findings are non-significant (just table refs like "male rats (Table 2)")
    all_nd = all(f.startswith(("male", "female")) for f in bw_findings)
    if all_nd:
        sex_refs = _oxford_comma(bw_findings, conjunction="or")
        return [
            f"No significant changes in terminal body weight for "
            f"{sex_refs} occurred with exposure to {compound_name}."
        ]
    else:
        return [" ".join(bw_findings)]


def _build_organ_weight_paragraphs(
    platform_tables: dict[str, dict[str, list]],
    compound_name: str,
    dose_unit: str,
) -> list[str]:
    """
    Build organ weight finding paragraphs from the Organ Weight platform data.

    Reference structure (p.11-12):
      - Per sex, in order: Male then Female
      - Significant findings: "In {sex} rats at study termination, a significant
        {increase/decrease} in {organ} {abs/rel} weight occurred at ≥{loel};
        these endpoints had {pos/neg} trends (Table 3).  The BMDs (BMDLs) for
        {organ} weights were {bmd} ({bmdl}) and {bmd} ({bmdl}) {dose_unit}."
      - Non-significant: "Significant trend and pairwise comparisons were not
        observed in {endpoint_list}."

    Args:
        platform_tables: The full {platform -> {sex -> [TableRow]}} dict.
        compound_name:   Chemical name for prose.
        dose_unit:       Dose unit string.

    Returns:
        List of paragraph strings (one per sex that has data).
    """
    ow_data = platform_tables.get("Organ Weight", {})
    if not ow_data:
        return []

    paragraphs: list[str] = []

    for sex in ["Male", "Female"]:
        rows = ow_data.get(sex, [])
        if not rows:
            continue

        # Separate organ-weight rows from any body-weight rows that might be mixed in
        organ_rows = [r for r in rows if _parse_organ_label(r.label)[1] != "body_weight"]
        if not organ_rows:
            continue

        # Split into significant (responsive with BMD) and non-significant
        sig_rows = [r for r in organ_rows if r.responsive and r.bmd_str != "ND"]
        nonsig_rows = [r for r in organ_rows if not r.responsive or r.bmd_str == "ND"]

        if not sig_rows:
            # No significant findings for this sex
            paragraphs.append(
                f"In {sex.lower()} rats at study termination, there were no "
                f"organ weights that exhibited significant trend and pairwise "
                f"comparisons."
            )
            continue

        # Group significant rows by organ name to pair absolute/relative
        organ_groups: dict[str, list[TableRow]] = {}
        for r in sig_rows:
            organ_name, _wtype = _parse_organ_label(r.label)
            organ_groups.setdefault(organ_name, []).append(r)

        # Build per-organ finding descriptions
        sex_findings: list[str] = []
        for organ_name, group_rows in organ_groups.items():
            direction = _endpoint_direction(group_rows[0])
            dir_word = "increased" if direction == "increase" else "decreased"
            trend_dir = "positive" if direction == "increase" else "negative"

            # Find lowest pairwise-significant dose across the group
            low_doses = [_lowest_sig_dose(r) for r in group_rows]
            low_doses = [d for d in low_doses if d is not None]
            min_low_dose = min(low_doses) if low_doses else None

            # Determine weight types present
            weight_types = [_parse_organ_label(r.label)[1] for r in group_rows]

            # Collect BMD/BMDL values with weight type qualifiers
            bmd_parts: list[str] = []
            for r in group_rows:
                _, wt = _parse_organ_label(r.label)
                if wt in ("absolute", "relative"):
                    bmd_parts.append(
                        f"{r.bmd_str} ({r.bmdl_str}) {dose_unit} ({wt} weight)"
                    )
                else:
                    bmd_parts.append(f"{r.bmd_str} ({r.bmdl_str}) {dose_unit}")

            # Compose the finding sentence
            has_weight_types = any(
                wt in ("absolute", "relative") for wt in weight_types
            )
            if has_weight_types:
                wt_type_str = _oxford_comma(
                    sorted(set(wt for wt in weight_types if wt in ("absolute", "relative"))),
                    conjunction="and",
                )
                finding = (
                    f"a significant {direction} in {organ_name} {wt_type_str} "
                    f"weight occurred"
                )
            else:
                finding = f"{organ_name} was significantly {dir_word}"

            if min_low_dose is not None:
                finding += f" in dose groups ≥{_fmt_dose(min_low_dose)} {dose_unit}"
            finding += f"; these endpoints had {trend_dir} trends (Table 3)"

            # Add BMD/BMDL — use "BMDs (BMDLs)" format from the reference
            if len(bmd_parts) == 1:
                finding += (
                    f". The BMD (BMDL) was {bmd_parts[0]}."
                )
            else:
                finding += (
                    ". The BMDs (BMDLs) were "
                    + _oxford_comma(bmd_parts, conjunction="and")
                    + ", respectively."
                )

            sex_findings.append(finding)

        # Opening line + findings
        sex_para = f"In {sex.lower()} rats at study termination, "
        sex_para += " ".join(sex_findings)

        # Non-significant endpoints listed at the end
        if nonsig_rows:
            nonsig_labels = []
            for r in nonsig_rows:
                organ_name, wtype = _parse_organ_label(r.label)
                if wtype in ("absolute", "relative"):
                    nonsig_labels.append(f"{wtype} {organ_name.lower()}")
                else:
                    nonsig_labels.append(r.label.lower())
            nonsig_str = _oxford_comma(nonsig_labels, conjunction="or")
            sex_para += (
                f" Significant trend and pairwise comparisons were not "
                f"observed in {nonsig_str} weights."
            )

        paragraphs.append(sex_para)

    return paragraphs


# ═══════════════════════════════════════════════════════════════════════════
# Clinical pathology paragraph builders
# ═══════════════════════════════════════════════════════════════════════════


def _build_sub_platform_paragraphs(
    sub_platform: str,
    sex_rows: dict[str, list],
    compound_name: str,
    dose_unit: str,
) -> list[str]:
    """
    Build narrative paragraphs for one clinical pathology sub-platform.

    Reference structure (p.14-15): each sub-platform (Clinical Chemistry,
    Hematology, Hormones) gets its own block, organized by sex (Male then
    Female).  Endpoints with significant trend AND pairwise comparisons are
    described with direction, LOEL, and BMD/BMDL.

    Args:
        sub_platform: Display name, e.g., "Clinical Chemistry".
        sex_rows:     {sex -> [TableRow]} for this sub-platform.
        compound_name: Chemical name for prose.
        dose_unit:     Dose unit string.

    Returns:
        List of paragraph strings (one per sex with data, possibly zero).
    """
    paragraphs: list[str] = []

    for sex in ["Male", "Female"]:
        rows = sex_rows.get(sex, [])
        if not rows:
            continue

        # Split into significant and non-significant
        sig_rows = [r for r in rows if r.responsive and r.bmd_str != "ND"]
        nonsig_rows = [r for r in rows if not r.responsive or r.bmd_str == "ND"]

        if not sig_rows:
            # Nothing significant for this sex in this sub-platform
            paragraphs.append(
                f"In {sex.lower()} rats, no {sub_platform.lower()} endpoints "
                f"exhibited significant trend and pairwise comparisons."
            )
            continue

        # Build per-endpoint findings
        findings: list[str] = []
        for r in sig_rows:
            direction = _endpoint_direction(r)
            dir_word = "increased" if direction == "increase" else "decreased"
            trend_dir = "positive" if direction == "increase" else "negative"
            low_dose = _lowest_sig_dose(r)

            finding = f"{r.label} was significantly {dir_word}"
            if low_dose is not None:
                finding += f" at ≥{_fmt_dose(low_dose)} {dose_unit}"
            finding += f" with a {trend_dir} trend"
            finding += (
                f". The BMD and BMDL were {r.bmd_str} and "
                f"{r.bmdl_str} {dose_unit}, respectively."
            )
            findings.append(finding)

        sex_para = f"In {sex.lower()} rats, "
        sex_para += " ".join(findings)

        # Non-significant endpoints
        if nonsig_rows:
            nonsig_labels = [r.label.lower() for r in nonsig_rows]
            nonsig_str = _oxford_comma(nonsig_labels, conjunction="or")
            sex_para += (
                f" Significant trend and pairwise comparisons were not "
                f"observed in {nonsig_str}."
            )

        paragraphs.append(sex_para)

    return paragraphs


# ═══════════════════════════════════════════════════════════════════════════
# Public API — the two unified narrative generators
# ═══════════════════════════════════════════════════════════════════════════


def generate_apical_narrative(
    platform_tables: dict[str, dict[str, list]],
    compound_name: str,
    dose_unit: str,
    sidecar_mortality: dict | None = None,
    clinical_obs_incidence: dict[str, list] | None = None,
) -> list[str]:
    """
    Unified "Animal Condition, Body Weights, and Organ Weights" narrative.

    Produces paragraphs in the same order as the NIEHS reference report (p.11):
      1. Animal condition (mortality + clinical signs)
      2. Body weight findings per sex
      3. Organ weight findings per sex (significant, then non-significant list)

    This replaces the per-platform generate_results_narrative() calls for
    Body Weight and Organ Weight platforms.

    Args:
        platform_tables:        The full {platform -> {sex -> [TableRow]}} dict
                                from the NTP stats pipeline.  Only the
                                "Body Weight" and "Organ Weight" entries are used.
        compound_name:          Chemical name for prose (e.g., "PFHxSAm").
        dose_unit:              Dose unit string (e.g., "mg/kg").
        sidecar_mortality:      Output from extract_mortality().  If None, the
                                animal condition paragraph is omitted.
        clinical_obs_incidence: Optional {sex: [IncidenceRow]} from
                                build_clinical_obs_tables().  If None, clinical
                                signs are omitted from the condition paragraph.

    Returns:
        List of paragraph strings, ready for display or export.
    """
    paragraphs: list[str] = []

    # 1. Animal condition (mortality + clinical signs)
    if sidecar_mortality:
        paragraphs.extend(
            _build_animal_condition_paragraphs(
                compound_name, dose_unit, sidecar_mortality,
                clinical_obs_incidence,
            )
        )

    # 2. Body weight findings
    paragraphs.extend(
        _build_body_weight_paragraphs(platform_tables, compound_name, dose_unit)
    )

    # 3. Organ weight findings
    paragraphs.extend(
        _build_organ_weight_paragraphs(platform_tables, compound_name, dose_unit)
    )

    return paragraphs


def generate_clinical_pathology_narrative(
    platform_tables: dict[str, dict[str, list]],
    compound_name: str,
    dose_unit: str,
) -> list[str]:
    """
    Unified "Clinical Pathology" narrative.

    Produces paragraphs organized by sub-platform then by sex, in the same
    order as the NIEHS reference report (p.14-15):
      - Clinical Chemistry (male, female)
      - Hematology (male, female)
      - Hormones (male, female)

    This replaces the per-platform generate_results_narrative() calls for
    Clinical Chemistry, Hematology, and Hormones platforms.

    Args:
        platform_tables: The full {platform -> {sex -> [TableRow]}} dict.
                         Only Clinical Chemistry, Hematology, and Hormones
                         entries are used.
        compound_name:   Chemical name for prose (e.g., "PFHxSAm").
        dose_unit:       Dose unit string (e.g., "mg/kg").

    Returns:
        List of paragraph strings, ready for display or export.
    """
    paragraphs: list[str] = []

    for sub_platform in CLINICAL_PATH_ORDER:
        sex_rows = platform_tables.get(sub_platform, {})
        if not sex_rows:
            continue

        # Sub-platform heading is implicit in the prose — the reference report
        # doesn't use explicit sub-headers within the Clinical Pathology section,
        # it just transitions between topics.  We add a brief label for clarity.
        sub_paras = _build_sub_platform_paragraphs(
            sub_platform, sex_rows, compound_name, dose_unit,
        )
        paragraphs.extend(sub_paras)

    return paragraphs
