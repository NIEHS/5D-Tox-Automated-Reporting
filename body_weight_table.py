"""
body_weight_table.py — Build NIEHS Table 2 (Body Weights) from pipeline data.

Produces the exact structure of NIEHS Report 10 Table 2:

    Table 2. Summary of Body Weights of Male and Female Rats Administered
    {compound} for Five Days

Structure:
    Columns: Study Day^(a,b) | dose₀ | dose₁ | ... | doseₙ | BMD₁Std (unit) | BMDL₁Std (unit)
    Row groups per sex:
        n       — sample sizes per dose group (superscript markers for attrition)
        0       — baseline body weights (study day 0)
        5       — terminal body weights (study day 5)
    Footnotes:
        BMD/BMDL definition line (always present, above the lettered footnotes)
        (a) Data format: "Data are displayed as mean ± standard error of the mean;
            body weight data are presented in grams."
        (b) Statistical method: "Statistical analysis performed by the Jonckheere
            (trend) and Williams or Dunnett (pairwise) tests."
        (c,d,...) Animal attrition notes, dynamically generated from missing-animal
            data per dose group.

Business rules:
    - An endpoint row appears in the table ONLY if it passes the gatekeeper:
      significant Jonckheere trend (p ≤ 0.01) AND at least one significant
      Dunnett pairwise (p ≤ 0.05).  For body weight, BOTH study days appear
      regardless — the gate controls only whether BMD is computed, not row
      inclusion.
    - BMD/BMDL column values:
        "NA"  — not applicable (n row, baseline day 0)
        "ND"  — not determined (endpoint did not pass the gatekeeper, so BMD
                was not computed / is meaningless)
        value — numeric BMD from BMDExpress (endpoint passed gate AND modeling
                succeeded)
    - The n row shows sample sizes from the source-of-truth data (base domain,
      not inferred).  Dose groups where all animals died show "–" with a
      superscript footnote marker.
    - Values are mean ± SE in grams (from source-of-truth data).

Input:
    TableRow objects from build_table_data() / build_table_data_from_bm2(),
    keyed by sex ("Male", "Female").  Each TableRow has:
        label:              "SD0" or "SD5" (BMDExpress probe ID)
        values_by_dose:     {dose: "mean ± SE"} with significance markers
        n_by_dose:          {dose: int}
        bmd_str/bmdl_str:   BMD result string from BMDExpress
        bmd_status:         "viable", "NVM", "NR", "UREP", "failure", or None
        responsive:         True if Jonckheere + Dunnett both significant
        missing_animals_by_dose: {dose: count} from xlsx comparison

Output:
    A dict matching the Typst template's apical_sections entry schema,
    ready to be inserted into the report data dict.
"""

from __future__ import annotations
import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Constants — NIEHS Table 2 fixed text
# ---------------------------------------------------------------------------

# The table caption template.  {compound} is replaced with the full
# chemical name (table_caption name form, never abbreviated).
CAPTION_TEMPLATE = (
    "Summary of Body Weights of Male and Female Rats "
    "Administered {compound} for Five Days"
)

# Fixed footnotes that always appear on body weight tables.
# These correspond to the superscript a,b markers on the "Study Day"
# column header.  Their text is verbatim from NIEHS Report 10 Table 2.
FOOTNOTE_DATA_FORMAT = (
    "Data are displayed as mean \u00b1 standard error of the mean; "
    "body weight data are presented in grams."
)
FOOTNOTE_STAT_METHOD = (
    "Statistical analysis performed by the Jonckheere (trend) "
    "and Williams or Dunnett (pairwise) tests."
)

# The BMD/BMDL definition line that appears ABOVE the lettered footnotes.
# It's not lettered — it's a standalone definition paragraph below the
# table rule, before footnote (a).
BMD_DEFINITION = (
    "BMD\u2081Std = benchmark dose corresponding to a benchmark response "
    "set to one standard deviation from the mean; "
    "BMDL\u2081Std = benchmark dose lower confidence limit corresponding "
    "to a benchmark response set to one standard deviation from the mean; "
    "NA = not applicable; ND = not determined."
)


# ---------------------------------------------------------------------------
# Study day label mapping
# ---------------------------------------------------------------------------

def _study_day_label(probe_label: str) -> str:
    """
    Convert a BMDExpress probe ID to a study day number for display.

    BMDExpress body weight probes are named "SD0", "SD5", etc.
    The NIEHS table shows just the number: "0", "5".

    If the label doesn't match the SD pattern, return it unchanged
    (defensive — shouldn't happen for body weight data).
    """
    if probe_label.upper().startswith("SD"):
        return probe_label[2:]
    return probe_label


# ---------------------------------------------------------------------------
# BMD/BMDL presentation rules
# ---------------------------------------------------------------------------

def _bmd_display(row, is_baseline: bool) -> tuple[str, str]:
    """
    Apply NIEHS business rules to determine BMD/BMDL cell text.

    The inferred .bm2 data is the source of truth for BMD values.
    Each study day probe (SD0, SD5) is modeled independently by
    BMDExpress, so both baseline and terminal can have BMD results
    if the statistical gate passes.

    Rules:
        - If the endpoint is NOT responsive (Jonckheere trend AND
          Dunnett pairwise not both significant): "ND" — BMD was
          not determined because the statistical gate was not passed.
        - If responsive AND BMDExpress produced a result: show the
          numeric BMD/BMDL value.
        - If responsive BUT BMDExpress failed to model (noisy data,
          convergence failure, etc.): "ND" — not determined because
          modeling couldn't produce a value.

    The NIEHS reference shows ND for body weight because the gate
    didn't pass.  With different data, any study day could show a
    numeric BMD.

    Args:
        row:         A TableRow object with bmd_str, bmdl_str, responsive,
                     and bmd_status attributes.
        is_baseline: True for study day 0 rows (unused — all days use
                     the same logic now).

    Returns:
        (bmd_text, bmdl_text) tuple of display strings.
    """
    if not row.responsive:
        # Gate not passed — BMD not computed
        return ("ND", "ND")

    # Gate passed — show BMDExpress result
    bmd = row.bmd_str if row.bmd_str and row.bmd_str != "\u2014" else "ND"
    bmdl = row.bmdl_str if row.bmdl_str and row.bmdl_str != "\u2014" else "ND"
    return (bmd, bmdl)


# ---------------------------------------------------------------------------
# Attrition footnotes
# ---------------------------------------------------------------------------

@dataclass
class _AttritionNote:
    """One animal attrition event to be rendered as a footnote."""
    dose: float
    count: int
    sex: str
    description: str  # e.g., "found dead on study day 0"


def _build_attrition_footnotes(
    table_data: dict,
    dose_unit: str,
) -> tuple[list[str], dict[str, dict[float, str]]]:
    """
    Build attrition footnotes and per-cell superscript marker assignments.

    Scans the n_by_dose and missing_animals_by_dose fields across all rows
    and sexes.  Each dose group with missing animals gets a footnote letter
    (c, d, e, ...) and the corresponding n-cell gets a superscript marker.

    The NIEHS reference shows specific descriptions:
        "One male rat was found dead on study day 0."
        "All male and female 333 and 1,000 mg/kg rats were found dead
         or moribund and euthanized by study day 1."

    We generate generic descriptions from the count data.  More specific
    descriptions (cause of death, study day) would require additional
    metadata from the xlsx study file.

    Args:
        table_data: {sex: [TableRow, ...]} from build_table_data.
        dose_unit:  Dose unit string for display (e.g., "mg/kg").

    Returns:
        (footnotes, markers) where:
            footnotes: list of footnote text strings (starting from letter c)
            markers:   {sex: {dose: "c"}} mapping for superscript placement
    """
    footnotes: list[str] = []
    markers: dict[str, dict[float, str]] = {}
    # Start footnote letters at 'c' since 'a' and 'b' are the fixed footnotes
    next_letter_ord = ord("c")

    # Collect unique (dose, sex) attrition events.
    # Use the n row to detect doses where N dropped to 0 or below expected.
    # Also check missing_animals_by_dose for explicit attrition counts.
    seen: set[tuple[str, float]] = set()

    for sex in ("Male", "Female"):
        rows = table_data.get(sex, [])
        markers.setdefault(sex, {})

        for row in rows:
            if not row.missing_animals_by_dose:
                continue
            for dose, count in sorted(row.missing_animals_by_dose.items()):
                if count <= 0:
                    continue
                key = (sex, dose)
                if key in seen:
                    continue
                seen.add(key)

                letter = chr(next_letter_ord)
                next_letter_ord += 1

                # Format dose for display: drop .0 for whole numbers
                d_label = str(int(dose)) if dose == int(dose) else str(dose)

                # Generic description — specific cause/timing would need
                # additional study metadata
                animal_word = "animal" if count == 1 else "animals"
                sex_word = sex.lower()
                footnotes.append(
                    f"{count} {sex_word} {animal_word} at "
                    f"{d_label} {dose_unit} did not survive to "
                    f"terminal sacrifice."
                )
                markers[sex][dose] = letter

    return footnotes, markers


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_body_weight_table(
    table_data: dict,
    compound_name: str = "Chemical",
    dose_unit: str = "mg/kg",
) -> dict:
    """
    Build the NIEHS Table 2 (Body Weights) data structure.

    Takes raw TableRow objects from the NTP stats pipeline and produces
    a dict matching the Typst template's apical_sections entry schema,
    with all body-weight-specific business rules applied:
        - Study day labels (SD0→0, SD5→5)
        - BMD/BMDL presentation (NA/ND/value per rules)
        - Structured footnotes (definition line + a,b + attrition)
        - Sex-grouped row structure (Male block, Female block)

    Args:
        table_data:    {sex: [TableRow, ...]} from build_table_data().
                       Expected to contain body weight rows with labels
                       like "SD0", "SD5".
        compound_name: Full chemical name for the caption.
        dose_unit:     Dose unit string (default "mg/kg").

    Returns:
        Dict with keys matching the Typst apical_sections schema:
            title, caption, compound, dose_unit, first_col_header,
            table_data (serialized), footnotes, bmd_definition
    """
    # Build attrition footnotes from missing-animal data
    attrition_fn, attrition_markers = _build_attrition_footnotes(
        table_data, dose_unit
    )

    # Assemble the complete footnote list:
    #   [0] = BMD/BMDL definition (unnumbered, rendered as a paragraph)
    #   [1] = (a) data format
    #   [2] = (b) statistical method
    #   [3..] = (c,d,...) attrition notes
    footnotes = [
        FOOTNOTE_DATA_FORMAT,     # (a)
        FOOTNOTE_STAT_METHOD,     # (b)
    ] + attrition_fn              # (c, d, ...)

    # Serialize rows for each sex, applying business rules
    serialized: dict[str, list[dict]] = {}

    for sex in ("Male", "Female"):
        rows = table_data.get(sex, [])
        if not rows:
            continue

        serialized[sex] = []
        for row in rows:
            label = _study_day_label(row.label)
            is_baseline = label == "0"

            # Apply BMD/BMDL display rules
            bmd_text, bmdl_text = _bmd_display(row, is_baseline)

            # Get the dose list from the row's data
            sorted_doses = sorted(row.values_by_dose.keys())

            # Build the values dict with string dose keys matching
            # JavaScript's String(number) behavior
            values = {}
            n_vals = {}
            for dose in sorted_doses:
                dk = _js_dose_key(dose)
                values[dk] = row.values_by_dose.get(dose, "\u2013")
                n_vals[dk] = row.n_by_dose.get(dose, 0)

            entry = {
                "label": label,
                "doses": sorted_doses,
                "values": values,
                "n": n_vals,
                "bmd": bmd_text,
                "bmdl": bmdl_text,
            }

            # Attach attrition markers for this sex's n-row rendering.
            # The Typst template uses these to place superscript letters
            # on specific n-cells (e.g., "4^c" for a dose group where
            # one animal died).
            sex_markers = attrition_markers.get(sex, {})
            if sex_markers:
                entry["attrition_markers"] = {
                    _js_dose_key(d): letter
                    for d, letter in sex_markers.items()
                }

            serialized[sex].append(entry)

    return {
        "title": "Animal Condition, Body Weights, and Organ Weights",
        "caption": CAPTION_TEMPLATE.replace("{compound}", compound_name),
        "compound": compound_name,
        "dose_unit": dose_unit,
        "first_col_header": "Study Day",
        "table_data": serialized,
        "footnotes": footnotes,
        "bmd_definition": BMD_DEFINITION,
        "missing_animal_footnotes": {},  # handled via attrition_markers instead
    }


def _js_dose_key(dose: float) -> str:
    """
    Format a dose float as a string matching JavaScript's String(number).

    JavaScript's String(0.15) produces "0.15", String(0.0) produces "0",
    String(1000.0) produces "1000".  Python's str(0.0) produces "0.0".
    We need consistent keys between Python serialization and JavaScript
    object property access.
    """
    if dose == int(dose):
        return str(int(dose))
    return str(dose)


# ---------------------------------------------------------------------------
# Sidecar-based builder — computes stats from raw animal values
# ---------------------------------------------------------------------------
#
# The pipeline's generic path (build_table_data → serialize_table_rows)
# computes stats from BMDExpress-integrated data, which has two problems
# for body weight:
#   1. BMDExpress drops dose groups where ALL animals died (333/1000 mg/kg)
#   2. BMDExpress includes Biosampling Animals, inflating N counts
#
# This alternative builder reads the sidecar JSON written by
# tox_study_csv_to_pivot_txt(), which preserves per-animal metadata
# (Selection, Observation Day, Terminal Flag) that the pivot discards.
# It computes mean±SE directly from the raw Core Animals values.

def _load_sidecar(path: str) -> dict:
    """
    Load a sidecar JSON file written by tox_study_csv_to_pivot_txt().

    Returns the parsed dict: {source, platform, sex, animals: {aid: {...}}}.
    Raises FileNotFoundError if the sidecar doesn't exist.
    """
    with open(path, "r") as f:
        return json.load(f)


def _mean_se(values: list[float]) -> tuple[float, float]:
    """
    Compute mean and standard error of the mean for a list of values.

    SE = SD / sqrt(N), where SD = population-corrected (N-1 denominator).

    Returns (mean, se).  If N < 2, SE is 0.0 (no variability estimable).
    """
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    mean = sum(values) / n
    if n < 2:
        return (mean, 0.0)
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    se = math.sqrt(variance) / math.sqrt(n)
    return (mean, se)


def _format_mean_se(mean: float, se: float, decimals: int = 1) -> str:
    """
    Format mean ± SE as a display string matching NIEHS reference style.

    Example: "296.5\u00a0±\u00a04.4" (1 decimal for body weight in grams).
    Uses non-breaking spaces (U+00A0) around the ± (U+00B1) so the value
    never wraps across lines in the PDF table — "296.5 ± 4.4" stays on
    one line regardless of column width.
    """
    # U+00A0 = non-breaking space, U+00B1 = ±
    return f"{mean:.{decimals}f}\u00a0\u00b1\u00a0{se:.{decimals}f}"


def _detect_terminal_day(observations: list[dict]) -> str | None:
    """
    Determine which observation day is the terminal measurement for an animal.

    Scans the observations list for the entry with terminal=True.
    Returns the day string (e.g., "SD5", "SD1", "SD0") or None if no
    terminal flag is set.
    """
    for obs in observations:
        if obs.get("terminal"):
            return obs.get("day", "")
    return None


def build_body_weight_table_from_sidecar(
    sidecar_paths: dict[str, str],
    bmd_results: dict[str, dict[str, str]] | None = None,
    compound_name: str = "Chemical",
    dose_unit: str = "mg/kg",
) -> dict:
    """
    Build NIEHS Table 2 (Body Weights) directly from sidecar JSON files.

    This is the preferred builder for body weight tables when sidecar data
    is available.  It replaces the generic build_table_data → serialize path
    with a direct computation from raw animal-level data, fixing three
    mismatches vs the NIEHS reference:

        1. All 10 dose groups present (including 333/1000 where animals died)
        2. N = Core Animals only (excludes Biosampling Animals)
        3. Correct mean ± SE from Core Animals values

    Args:
        sidecar_paths: {"Male": "/path/to/male.sidecar.json",
                        "Female": "/path/to/female.sidecar.json"}
                       One or both sexes may be present.
        bmd_results:   Optional BMD/BMDL values from the pipeline, keyed by
                       study day label: {"SD5": {"bmd": "123.4", "bmdl": "56.7"},
                       "SD0": {"bmd": "NA", "bmdl": "NA"}}.
                       If None, all BMD cells show "NA" (baseline) or "ND"
                       (terminal, since BMD wasn't computed from sidecar data).
        compound_name: Full chemical name for the table caption.
        dose_unit:     Dose unit string (default "mg/kg").

    Returns:
        Dict with keys matching the Typst apical_sections schema,
        identical to build_body_weight_table() output.
    """
    if bmd_results is None:
        bmd_results = {}

    # ── Load sidecars and extract per-dose-group stats ───────────────────
    # For each sex, group Core Animals by dose and study day, then compute
    # mean ± SE.  Also track attrition (animals whose terminal day isn't
    # the expected terminal — e.g., SD1 instead of SD5 = died/moribund).

    # Collect ALL doses across all sexes to ensure consistent column set.
    # This is critical: 333/1000 mg/kg must appear even if BMDExpress
    # would normally drop them (no surviving animals at SD5).
    all_doses: set[float] = set()

    # {sex: {day: {dose: [value, ...]}}} — raw values for stats computation
    raw_values: dict[str, dict[str, dict[float, list[float]]]] = {}

    # {sex: {dose: {count_died: int, terminal_day: str}}} — attrition data
    # for footnote generation.  We track how many animals at each dose had
    # their terminal measurement on a day earlier than the study endpoint
    # (SD5 for a 5-day study).
    attrition_by_sex_dose: dict[str, dict[float, list[dict]]] = {}

    # Determine the "expected terminal day" — the latest terminal day
    # across all animals in the study.  This is the day when surviving
    # animals are sacrificed (SD5 for a 5-day study, SD28 for 28-day,
    # etc.).  Animals whose terminal day is earlier than this died before
    # study completion — they're attrition cases.
    #
    # Derived from the data by finding the most common terminal day
    # (the mode), since the majority of animals survive to the planned
    # endpoint.  Falls back to the latest day if no terminal flags exist.
    _all_terminal_days: list[str] = []
    _all_obs_days: set[str] = set()
    for sc_path in sidecar_paths.values():
        sc = _load_sidecar(sc_path)
        for rec in sc.get("animals", {}).values():
            for obs in rec.get("observations", []):
                day = obs.get("day", "")
                if day:
                    _all_obs_days.add(day)
                if obs.get("terminal") and day:
                    _all_terminal_days.append(day)

    if _all_terminal_days:
        # Mode of terminal days = the planned sacrifice day
        from collections import Counter
        expected_terminal_day = Counter(_all_terminal_days).most_common(1)[0][0]
    elif _all_obs_days:
        # Fallback: latest observation day by numeric suffix
        expected_terminal_day = max(
            _all_obs_days,
            key=lambda d: int(d[2:]) if d.upper().startswith("SD") and d[2:].isdigit() else 999,
        )
    else:
        expected_terminal_day = "SD5"  # last resort default

    for sex, sc_path in sidecar_paths.items():
        sc = _load_sidecar(sc_path)
        sex_vals: dict[str, dict[float, list[float]]] = {}
        attrition: dict[float, list[dict]] = {}

        for aid, rec in sc.get("animals", {}).items():
            dose = rec["dose"]
            selection = rec.get("selection", "Unknown")
            all_doses.add(dose)

            # ── Core Animals filter ──────────────────────────────────────
            # Only Core Animals contribute to Table 2 statistics.
            # Biosampling Animals are sampled mid-study for tissue collection
            # and are NOT included in the endpoint body weight stats (their
            # inclusion would inflate N from 5 to 8 at 4/37 mg/kg).
            if "core" not in selection.lower():
                continue

            terminal_day = _detect_terminal_day(rec.get("observations", []))

            # Track attrition: animals whose terminal day is before the
            # expected study endpoint (SD5).  These are dead/moribund animals.
            if terminal_day and terminal_day != expected_terminal_day:
                attrition.setdefault(dose, []).append({
                    "animal_id": aid,
                    "terminal_day": terminal_day,
                })

            # Collect observation values by study day.
            # Exclude post-mortem/carcass weights: when terminal=True on a
            # day EARLIER than the expected terminal day (SD5), the value is
            # not a live body weight measurement.  Example: animal 203 at
            # 1000 mg/kg has terminal=True on SD0 with value 290.7 — that's
            # a carcass weight recorded when found dead.  The NIEHS reference
            # excludes this animal from SD0 stats (N=4, not 5).
            #
            # Non-terminal observations on earlier days still count —
            # animal 201 at 1000 mg/kg has terminal=False on SD0 (281.6)
            # which is a valid live baseline weight.
            for obs in rec.get("observations", []):
                day = obs.get("day", "")
                val_str = obs.get("value")
                is_terminal_obs = obs.get("terminal", False)
                if not day or not val_str:
                    continue

                # Post-mortem filter: if this observation is marked terminal
                # AND the day is NOT the expected study endpoint, it's a
                # carcass weight from a dead/moribund animal — exclude it
                # from body weight statistics.
                if is_terminal_obs and day != expected_terminal_day:
                    continue

                try:
                    fval = float(val_str)
                except (ValueError, TypeError):
                    # Non-numeric ("NA") — don't include in stats but the
                    # animal still counts for attrition tracking above.
                    continue
                sex_vals.setdefault(day, {}).setdefault(dose, []).append(fval)

        raw_values[sex] = sex_vals
        attrition_by_sex_dose[sex] = attrition

    sorted_doses = sorted(all_doses)

    # ── Build attrition footnotes and marker placement ───────────────────
    # The NIEHS reference uses two distinct marker placement strategies:
    #
    #   1. **N-row markers** — when an individual animal died before baseline
    #      measurements could be taken, reducing N below the expected count.
    #      Example: animal 203 at 1000 mg/kg found dead SD0 → N=4^c instead
    #      of 5.  The marker goes on the n-row cell for that dose.
    #
    #   2. **Dash markers** — when all animals at a dose group died before
    #      the terminal study day, so no data exists for that row.  The
    #      marker goes on the "–" dash in the data row, not the n-row.
    #      Example: 333 mg/kg at SD5 → "–^d" because all animals died by
    #      SD1.  The n-row at 333 stays plain "5" (all 5 were alive at
    #      baseline).
    #
    # Footnotes are merged across sexes and doses when the same event
    # applies broadly.  The reference uses:
    #   c = "One male rat was found dead on study day 0."
    #   d = "All male and female 333 and 1,000 mg/kg rats were found dead
    #        or moribund and euthanized by study day 1."
    #
    # We classify attrition events into two categories:
    #   - "individual": ≤1 animal at a dose, died on a non-terminal day
    #     earlier than mass attrition (e.g., SD0 death when others die SD1)
    #   - "mass": all animals at a dose died, typically by the same day
    #
    # Individual events get per-dose footnotes with n-row markers.
    # Mass events are merged into one combined footnote with dash markers.

    footnotes: list[str] = [
        FOOTNOTE_DATA_FORMAT,     # (a)
        FOOTNOTE_STAT_METHOD,     # (b)
    ]
    next_letter_ord = ord("c")

    # Markers placed on the n-row: {sex: {dose: letter}}
    # Used when N is reduced (individual deaths before baseline)
    n_row_markers: dict[str, dict[float, str]] = {}

    # Markers placed on dashes in data rows: {sex: {(dose, day): letter}}
    # Used when all animals at a dose are dead for a given study day
    dash_markers: dict[str, dict[tuple[float, str], str]] = {}

    # ── Pass 1: Classify individual vs mass attrition ────────────────
    # Individual deaths: animal died on a day EARLIER than the rest of
    # its dose group (e.g., animal 203 died SD0, others died SD1).
    # These reduce the N count and get their own footnote.
    #
    # Mass attrition: ALL animals at a dose died by the same day.
    # These get merged into one combined footnote.
    individual_events: list[dict] = []  # [{sex, dose, count, day}, ...]
    mass_doses: dict[str, set] = {}     # {terminal_day: {dose, ...}}
    mass_sexes: set[str] = set()

    for sex in ("Male", "Female"):
        attrition = attrition_by_sex_dose.get(sex, {})
        n_row_markers.setdefault(sex, {})
        dash_markers.setdefault(sex, {})

        for dose in sorted_doses:
            events = attrition.get(dose, [])
            if not events:
                continue

            # Check if ALL core animals at this dose died (no SD5 data)
            sex_sd5 = raw_values.get(sex, {}).get(expected_terminal_day, {})
            surviving = len(sex_sd5.get(dose, []))
            all_died = (surviving == 0)

            # Group events by terminal day
            by_day: dict[str, list] = defaultdict(list)
            for ev in events:
                by_day[ev["terminal_day"]].append(ev)

            if all_died:
                # Find the latest terminal day for this dose group
                # (the day by which all were dead/moribund)
                latest_day = max(by_day.keys(),
                                 key=lambda d: int(d[2:]) if d.upper().startswith("SD") and d[2:].isdigit() else 999)

                # Check for individual early deaths (died before the
                # group's main terminal day).  E.g., animal 203 died SD0
                # while the rest of 1000 mg/kg died SD1.
                for day, day_events in sorted(by_day.items()):
                    if day != latest_day:
                        # Individual early death(s) — separate footnote
                        individual_events.append({
                            "sex": sex,
                            "dose": dose,
                            "count": len(day_events),
                            "day": day,
                        })

                # Record the mass attrition (by the latest day)
                mass_doses.setdefault(latest_day, set()).add(dose)
                mass_sexes.add(sex)
            else:
                # Partial attrition — some animals died but not all.
                # Each gets its own individual footnote.
                for day, day_events in sorted(by_day.items()):
                    individual_events.append({
                        "sex": sex,
                        "dose": dose,
                        "count": len(day_events),
                        "day": day,
                    })

    # ── Pass 2: Generate individual footnotes (n-row markers) ────────
    for ev in individual_events:
        letter = chr(next_letter_ord)
        next_letter_ord += 1

        sex = ev["sex"]
        dose = ev["dose"]
        count = ev["count"]
        day_num = ev["day"][2:] if ev["day"].upper().startswith("SD") else ev["day"]

        # Marker goes on the n-row at this dose for this sex
        # (the N is reduced because this animal's data was excluded)
        n_row_markers[sex][dose] = letter

        sex_word = sex.lower()
        if count == 1:
            footnotes.append(
                f"One {sex_word} rat was found dead on study day {day_num}."
            )
        else:
            footnotes.append(
                f"{count} {sex_word} rats were found dead on study day {day_num}."
            )

    # ── Pass 3: Generate mass attrition footnote (dash markers) ──────
    # Merge all mass-attrition doses and sexes into one combined footnote,
    # matching the NIEHS reference style:
    #   "All male and female 333 and 1,000 mg/kg rats were found dead or
    #    moribund and euthanized by study day 1."
    if mass_doses:
        letter = chr(next_letter_ord)
        next_letter_ord += 1

        # Collect all doses involved in mass attrition
        all_mass_doses: set[float] = set()
        mass_terminal_day = None
        for day, doses_set in mass_doses.items():
            all_mass_doses.update(doses_set)
            # Use the latest terminal day for the footnote text
            if mass_terminal_day is None:
                mass_terminal_day = day
            else:
                day_num = int(day[2:]) if day.upper().startswith("SD") and day[2:].isdigit() else 999
                curr_num = int(mass_terminal_day[2:]) if mass_terminal_day.upper().startswith("SD") and mass_terminal_day[2:].isdigit() else 999
                if day_num > curr_num:
                    mass_terminal_day = day

        # Place dash marker on the FIRST dash cell only (standard footnote
        # convention — the superscript introduces the footnote once, the
        # footnote text describes all affected cells).  The table is read
        # Male-then-Female, lowest-dose-first, so the first dash is at
        # the lowest mass-attrition dose in the Male SD5 row.
        marker_placed = False
        for sex in ("Male", "Female"):
            attrition = attrition_by_sex_dose.get(sex, {})
            for dose in sorted(all_mass_doses):
                if dose in attrition:
                    if not marker_placed:
                        dash_markers[sex][(dose, expected_terminal_day)] = letter
                        marker_placed = True
                    # Remaining dashes get no marker — the footnote text
                    # ("All male and female 333 and 1,000 mg/kg...") tells
                    # the reader which cells are affected.

        # Build the combined footnote text
        sorted_mass_doses = sorted(all_mass_doses)
        dose_labels = []
        for d in sorted_mass_doses:
            d_label = f"{int(d):,}" if d == int(d) else str(d)
            dose_labels.append(d_label)
        dose_str = " and ".join(dose_labels)

        sex_list = sorted(mass_sexes)
        if len(sex_list) == 2:
            sex_str = "male and female"
        else:
            sex_str = sex_list[0].lower()

        day_num = mass_terminal_day[2:] if mass_terminal_day.upper().startswith("SD") else mass_terminal_day
        footnotes.append(
            f"All {sex_str} {dose_str} {dose_unit} rats were found dead "
            f"or moribund and euthanized by study day {day_num}."
        )

    # ── Determine which study days to show as TABLE ROWS ────────────────
    # Only the baseline (SD0) and terminal (SD5) study days appear as data
    # rows in the NIEHS Table 2.  Intermediate days (SD1 for moribund/dead
    # animals) are captured in the attrition footnotes but do NOT get their
    # own row.  The reference Table 2 has exactly: n, 0, 5 — nothing else.
    display_days = ["SD0", expected_terminal_day]

    # ── Build the complete row grid per sex ──────────────────────────────
    # Python builds every row the table will contain — including the `n`
    # row.  The Typst template receives a flat list of rows and renders
    # them verbatim.  No data logic in the template.
    #
    # Row structure (matches reference Table 2):
    #   [0] n     — sample sizes per dose, "NA" in BMD cols
    #   [1] 0     — baseline body weights, empty BMD cols
    #   [2] 5     — terminal body weights, BMD/BMDL from pipeline
    #
    # Each row is a list of cell strings, one per column:
    #   [label, dose0_val, dose1_val, ..., bmd, bmdl]
    #
    # The grid approach means the Typst template is a pure renderer —
    # it iterates rows and cells, applies font/alignment/rules, done.
    # All business rules (which rows exist, what BMD shows, which cells
    # get attrition markers) are decided here in Python.

    serialized: dict[str, list[dict]] = {}

    for sex in ("Male", "Female"):
        sex_vals = raw_values.get(sex, {})
        if not sex_vals:
            continue

        sex_n_markers = n_row_markers.get(sex, {})
        sex_dash_markers = dash_markers.get(sex, {})
        rows: list[dict] = []

        # ── n row (sample sizes) ─────────────────────────────────────────
        # Shows the starting Core Animals count at each dose.  Markers
        # appear ONLY when N is reduced from the expected count (individual
        # deaths that excluded animals from stats).  Mass attrition markers
        # go on the data row dashes instead (see below).
        #
        # N is the max across all display study days for each dose — this
        # gives the starting count (baseline SD0 has all surviving animals).
        n_vals: dict[str, str] = {}
        n_markers: dict[str, str] = {}
        for dose in sorted_doses:
            dk = _js_dose_key(dose)
            max_n = 0
            for day in display_days:
                day_vals = sex_vals.get(day, {})
                n_at_dose = len(day_vals.get(dose, []))
                if n_at_dose > max_n:
                    max_n = n_at_dose

            # Only attach marker if this dose has an individual death
            # that reduced N (marker on n-row, not on dash)
            marker = sex_n_markers.get(dose)
            if marker:
                n_markers[dk] = marker

            if max_n > 0:
                n_vals[dk] = str(max_n)
            else:
                n_vals[dk] = "\u2013"

        rows.append({
            "label": "n",
            "doses": sorted_doses,
            "values": n_vals,
            "markers": n_markers,
            "bmd": "NA",
            "bmdl": "NA",
            "is_n_row": True,
        })

        # ── Data rows (one per display study day) ────────────────────────
        for day in display_days:
            dose_vals = sex_vals.get(day, {})
            label = _study_day_label(day)
            is_baseline = (label == "0")

            # BMD/BMDL business rules:
            #   All data rows (baseline and terminal) show the pipeline's
            #   BMD result.  The pipeline runs NTP stats on each probe
            #   (SD0, SD5) from the inferred .bm2 data independently:
            #
            #   - If the statistical gate passes (significant Jonckheere
            #     trend + Dunnett pairwise) AND BMDExpress modeling
            #     succeeds → numeric BMD/BMDL value
            #   - If the gate doesn't pass OR modeling fails → "ND"
            #     (not determined)
            #
            #   The NIEHS reference shows ND for both day 0 and day 5
            #   body weights because the gate didn't pass in that study.
            #   With different data (e.g., a compound that causes
            #   immediate weight loss), day 0 could show a numeric BMD.
            #   The inferred .bm2 is the source of truth for BMD values.
            day_bmd = bmd_results.get(day, {})
            bmd_text = day_bmd.get("bmd", "ND")
            bmdl_text = day_bmd.get("bmdl", "ND")

            values: dict[str, str] = {}
            row_markers: dict[str, str] = {}
            for dose in sorted_doses:
                dk = _js_dose_key(dose)
                animals_at_dose = dose_vals.get(dose, [])

                if animals_at_dose:
                    mean, se = _mean_se(animals_at_dose)
                    values[dk] = _format_mean_se(mean, se)
                else:
                    # No surviving animals at this dose for this day.
                    # Show dash (–) matching NIEHS convention.
                    values[dk] = "\u2013"
                    # Check for a dash marker (mass attrition footnote)
                    dm = sex_dash_markers.get((dose, day))
                    if dm:
                        row_markers[dk] = dm

            entry = {
                "label": label,
                "doses": sorted_doses,
                "values": values,
                "bmd": bmd_text,
                "bmdl": bmdl_text,
            }
            if row_markers:
                entry["markers"] = row_markers
            rows.append(entry)

        serialized[sex] = rows

    return {
        "title": "Animal Condition, Body Weights, and Organ Weights",
        "caption": CAPTION_TEMPLATE.replace("{compound}", compound_name),
        "compound": compound_name,
        "dose_unit": dose_unit,
        "first_col_header": "Study Day",
        "table_data": serialized,
        "footnotes": footnotes,
        "bmd_definition": BMD_DEFINITION,
    }


def find_sidecar_paths(session_dir: str, platform: str = "Body Weight") -> dict[str, str]:
    """
    Scan a session's files/ directory for body weight sidecar JSON files.

    Sidecar files are named like `body_weight_truth_male.sidecar.json` and
    are written by tox_study_csv_to_pivot_txt() alongside the pivot txt.

    Args:
        session_dir: Absolute path to the session directory (e.g.,
                     sessions/DTXSID50469320/).
        platform:    The platform name to match (default "Body Weight").

    Returns:
        {"Male": "/path/to/male.sidecar.json", "Female": "/path/to/female.sidecar.json"}
        Only present sexes are included.  Empty dict if no sidecars found.
    """
    files_dir = os.path.join(session_dir, "files")
    if not os.path.isdir(files_dir):
        return {}

    result: dict[str, str] = {}
    for fname in os.listdir(files_dir):
        if not fname.endswith(".sidecar.json"):
            continue
        sc_path = os.path.join(files_dir, fname)
        try:
            with open(sc_path, "r") as f:
                sc = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        # Only match sidecars for the requested platform
        if sc.get("platform") != platform:
            continue

        sex = sc.get("sex", "Unknown")
        if sex in ("Male", "Female"):
            result[sex] = sc_path

    return result
