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

    Rules (from NIEHS Report 10 Table 2):
        - Baseline (study day 0): always "NA" — no treatment effect
          measurable at baseline, BMD is not applicable.
        - Terminal (study day 5):
            - If the endpoint is NOT responsive (Jonckheere trend AND
              Dunnett pairwise not both significant): "ND" — BMD was
              not determined because the statistical gate was not passed.
            - If responsive AND BMDExpress produced a result: show the
              numeric BMD/BMDL value.
            - If responsive BUT BMDExpress failed to model (noisy data,
              convergence failure, etc.): "NA" — not applicable because
              modeling couldn't produce a value despite significance.

    Args:
        row:         A TableRow object with bmd_str, bmdl_str, responsive,
                     and bmd_status attributes.
        is_baseline: True for study day 0 rows.

    Returns:
        (bmd_text, bmdl_text) tuple of display strings.
    """
    if is_baseline:
        return ("NA", "NA")

    if not row.responsive:
        # Gate not passed — BMD not computed
        return ("ND", "ND")

    # Gate passed — show BMDExpress result
    bmd = row.bmd_str if row.bmd_str and row.bmd_str != "\u2014" else "NA"
    bmdl = row.bmdl_str if row.bmdl_str and row.bmdl_str != "\u2014" else "NA"
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
