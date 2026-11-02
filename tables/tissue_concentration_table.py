"""
tissue_concentration_table.py — Build NIEHS Table 7 (Tissue Concentration).

Produces the pharmacokinetic plasma concentration table:

    Table 7. Summary of Plasma Concentration Data for Male and Female Rats
    Administered {compound} for Five Days

This table is fundamentally different from all other NIEHS tables:
  - Only Biosampling Animals (opposite of all other tables which use Core)
  - Only dose groups that have biosampling animals (typically 2 of 10 doses)
  - No BMD/BMDL columns — not a dose-response analysis
  - No NTP stats or significance markers
  - Rows = timepoints (e.g., "2 h postdose", "24 h postdose")
  - Columns = dose groups
  - LOQ handling: when a value is below the limit of quantification,
    substitute LOQ/2 for statistical computation

Structure:
    Columns: Timepoint | dose₁ | dose₂ | ...
    Per sex:
        n           — biosampling animals per dose
        2 h postdose — mean ± SE of plasma concentration
        24 h postdose — mean ± SE of plasma concentration

    Values are in the concentration unit the data record (the sidecar's
    "units", from the study workbook's Key sheet — ng/mL, µg/mL, ...).

The sidecar provides raw per-animal concentration values and LOQ data.
No NTP stats are used — this is purely descriptive statistics.
"""

from __future__ import annotations

from common.animal_selection import is_biosampling

import re

import logging
from dataclasses import dataclass, field

from tables.table_builder_common import (
    apical_caption,
    definition_footnote,
    finalize_footnotes,
    format_dose_label,
    format_mean_se_sig,
    js_dose_key,
    lettered_footnote,
    load_sidecar,
    mean_se,
)
from tables.units import UNIT_NOT_RECORDED, recorded_units

logger = logging.getLogger(__name__)

BD = "BD"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAPTION_TEMPLATE = (
    "Summary of Plasma Concentration Data for {subject} {treatment}"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_timepoint(endpoint_name: str, after: str = "postdose") -> str | None:
    """
    Extract the timepoint label from a tissue concentration endpoint name.

    NTP endpoint names follow the pattern:
        "Plasma {N} Hour {Chemical} Concentration"
    We extract "{N} h postdose" as the display label ("{N} h postexposure"
    for an inhalation study — `after`, pipeline.study_design.after_administration).

    Also filters out the detection-limit columns (names ending in "LOQ" or
    "LOD" — NIEHS-07 and -09 record both).

    Args:
        endpoint_name: Full endpoint name from the CSV/sidecar.

    Returns:
        Timepoint label like "2 h postdose" or None if this is an LOQ/LOD
        column or doesn't match the expected pattern.
    """
    # Skip LOQ/LOD columns — they contain detection limit values, not measurements
    if endpoint_name.strip().upper().endswith(("LOQ", "LOD")):
        return None

    # Match "Plasma {N} Hour" pattern (case-insensitive)
    m = re.search(r"Plasma\s+(\d+)\s+Hour", endpoint_name, re.IGNORECASE)
    if m:
        hours = m.group(1)
        return f"{hours} h {after}"

    # Fallback: use the endpoint name as-is if it contains "Concentration"
    if "Concentration" in endpoint_name:
        return endpoint_name

    return None


# A value that says the sample never reached the lab: no measurement, so not
# below the limit either — the group is reported on fewer samples, with a
# footnote (NIEHS-07: "Only two samples were received for the 4 mg/kg female
# rats at 2 hours postdose").
_NOT_SAMPLED = ("no sample received", "sample not received", "not received", "no sample")
_NUMBER = re.compile(r"^-?\d*\.?\d+(?:[eE][-+]?\d+)?$")
_COUNT_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def _hours(endpoint_name: str) -> int | None:
    """The hours after the last administration a "Plasma {N} Hour {Chemical}
    Concentration" endpoint was sampled at; None for a limit column or any
    other endpoint."""
    if endpoint_name.strip().upper().endswith(("LOQ", "LOD")):
        return None
    m = re.search(r"Plasma\s+(\d+)\s+Hour", endpoint_name, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _limit(observations: list[dict], endpoint_name: str, day) -> str:
    """The limit a below-limit value is reported against, recorded the same
    study day beside the concentration: the LOD, else the LOQ (NIEHS-08 and
    10 record only an LOQ).  "" when neither is recorded that day — the
    measurement was not made then."""
    stem = endpoint_name.replace("Concentration", "").strip()
    found: dict[str, str] = {}
    for o in observations:
        ep = (o.get("endpoint") or "").strip()
        kind = ep.split()[-1].upper() if ep else ""
        value = str(o.get("value") or "").strip()
        if (o.get("day") == day and kind in ("LOD", "LOQ") and ep.startswith(stem)
                and _NUMBER.match(value)):
            found[kind] = value
    return found.get("LOD") or found.get("LOQ") or ""


@dataclass
class PlasmaGroup:
    """One sex × dose × timepoint group: its samples ``[(value, limit)]``
    (value None below the limit) and the biosampling animals of its dose."""
    samples: list = field(default_factory=list)
    animals: int = 0


def plasma_groups(sidecar: dict) -> dict[int, dict[float, PlasmaGroup]]:
    """``{hours: {dose: PlasmaGroup}}`` of the biosampling animals' plasma
    concentrations in one sidecar — the groups the table, the toxicokinetics
    and the Abstract all compute from.  A number is a measurement; any other
    value with a limit recorded that day is below the limit (half the limit,
    or BD — ``group_values``); "No Sample Received" is not a sample; a value
    with no limit that day was not measured then."""
    animals: dict[float, int] = {}
    out: dict[int, dict[float, PlasmaGroup]] = {}
    for rec in (sidecar.get("animals") or {}).values():
        if not is_biosampling(rec.get("selection")):
            continue
        dose = float(rec["dose"])
        animals[dose] = animals.get(dose, 0) + 1
        observations = rec.get("observations") or []
        for o in observations:
            hours = _hours(o.get("endpoint") or "")
            if hours is None:
                continue
            value = str(o.get("value") or "").strip()
            limit = _limit(observations, o["endpoint"], o.get("day"))
            if _NUMBER.match(value):
                sample = (float(value), limit)
            elif value.lower() in _NOT_SAMPLED:
                sample = None
            elif limit:
                sample = (None, limit)
            else:
                if value:
                    logger.warning("Plasma concentration %r of %s (%s) has no limit recorded "
                                   "that day: left out", value, o["endpoint"], o.get("day"))
                continue
            group = out.setdefault(hours, {}).setdefault(dose, PlasmaGroup())
            if sample:
                group.samples.append(sample)
    for by_dose in out.values():
        for dose, group in by_dose.items():
            group.animals = animals[dose]
    return out


def group_values(group: PlasmaGroup, method) -> tuple[list[float] | None, int]:
    """(the values the group's mean is computed from — values below the limit
    at half the limit — or None when the group is BD; outliers left out), by
    the method's internal_dose rules (blood_tissue_concentration_table.Rules)."""
    from pipeline.method_profile import session_method
    from tables.blood_tissue_concentration_table import Rules, _group_values
    if method is None:
        method = session_method(None)
    if not group.samples:
        return [], 0
    return _group_values(group.samples, Rules.from_method(method))


def timepoint_label(hours: int, after: str, unit: str | None) -> str:
    """The row label the reports print: "2 Hours Postdose (ng/mL)"."""
    unit_text = unit or UNIT_NOT_RECORDED.format(what="concentration")
    return f"{hours} {'Hour' if hours == 1 else 'Hours'} {after.title()} ({unit_text})"


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_tissue_concentration_table_from_sidecar(
    sidecar_paths: dict[str, str],
    compound_name: str = "Chemical",
    dose_unit: str = "mg/kg",
    design: dict | None = None,
    method=None,
) -> dict:
    """
    Build NIEHS Table 7 (Tissue Concentration) from sidecar data.

    Reads raw per-animal plasma concentration values from the sidecar JSON
    and computes mean ± SE per dose group per timepoint.  Only Biosampling
    Animals are included (this is the opposite of all other tables).

    LOQ handling: if a concentration value is missing but the LOQ is present,
    the value is substituted with LOQ/2 (standard analytical chemistry
    convention for below-detection-limit samples).

    Args:
        sidecar_paths:  {"Male": "/path/to/male.sidecar.json", ...}.
        compound_name:  Full chemical name for the caption.
        dose_unit:      Dose unit string (default "mg/kg").
        design:         Study design facts (pipeline.study_design) for the caption's
                        species, verb and duration, and the timepoint word (postdose/
                        postexposure); None ⇒ the standard design.
        method:         The study's resolved method (pipeline.method_profile):
                        internal_dose.* — significant figures, and for the
                        study-day layout the BD, outlier and statistics rules.
                        None ⇒ the newest profile.

    Returns:
        Dict with keys matching the Typst apical_sections schema, plus
        table_type="pharmacokinetic" flag for specialized Typst rendering.
        Returns empty dict if no tissue concentration data found.
    """
    from pipeline.method_profile import session_method
    from pipeline.study_design import (
        after_administration, design_or_standard, species_plural, species_singular,
    )

    method = method if method is not None else session_method(None)
    sig_figs = method.get("internal_dose.sig_figs")

    _after = after_administration(design_or_standard(design))
    # ── Load sidecars ─────────────────────────────────────────────────────
    sidecar_data: dict[str, dict] = {}
    for sex, sc_path in sidecar_paths.items():
        sidecar_data[sex] = load_sidecar(sc_path)

    if not sidecar_data:
        return {}

    # The 2025 studies' blood/tissue concentrations by study day are a
    # different table (tables.blood_tissue_concentration_table).
    from tables.blood_tissue_concentration_table import build_day_layout_table, is_day_layout

    if is_day_layout(sidecar_data.values()):
        return build_day_layout_table(sidecar_data, compound_name, dose_unit, design, method)

    # ── The groups: biosampling animals by timepoint and dose ────────────
    from tables.blood_tissue_concentration_table import Rules

    rules = Rules.from_method(method)
    groups_by_sex = {sex: plasma_groups(sc) for sex, sc in sidecar_data.items()}
    groups_by_sex = {sex: g for sex, g in groups_by_sex.items() if g}
    if not groups_by_sex:
        return {}
    sorted_doses = sorted({d for g in groups_by_sex.values() for by in g.values() for d in by})
    all_hours = sorted({h for g in groups_by_sex.values() for h in g})

    # ── Concentration unit per timepoint, as the data record it ───────────
    ep_units = recorded_units(sidecar_data.values(), lambda ep: _hours(ep) is not None)
    hour_units: dict[int, set[str]] = {}
    for ep, unit in ep_units.items():
        hour_units.setdefault(_hours(ep), set()).add(unit)

    def _unit(h: int) -> str | None:
        units = hour_units.get(h, set())
        return next(iter(units)) if len(units) == 1 else None

    animal = species_singular(design_or_standard(design))
    animals = species_plural(design_or_standard(design))

    # ── Build the table rows ──────────────────────────────────────────────
    serialized: dict[str, list[dict]] = {}
    any_bd = any_outlier = False
    any_limit = any(lim for g in groups_by_sex.values() for by in g.values()
                    for grp in by.values() for _, lim in grp.samples)
    short_notes: dict[str, str] = {}

    for sex in ("Male", "Female"):
        groups = groups_by_sex.get(sex)
        if not groups:
            continue
        animals_by_dose = {d: grp.animals for by in groups.values() for d, grp in by.items()}

        rows: list[dict] = [{
            "label": "n",
            "doses": sorted_doses,
            "values": {js_dose_key(d): str(animals_by_dose[d]) if animals_by_dose.get(d)
                       else "\u2013" for d in sorted_doses},
            "is_n_row": True,
        }]

        for h in all_hours:
            values: dict[str, str] = {}
            marker_refs: dict[str, str] = {}
            for dose in sorted_doses:
                dk = js_dose_key(dose)
                group = groups.get(h, {}).get(dose)
                if group is None:
                    values[dk] = "\u2013"
                    continue
                vals, outliers = group_values(group, method)
                any_outlier = any_outlier or bool(outliers)
                if vals is None:
                    values[dk] = BD
                    any_bd = True
                elif vals:
                    m, s = mean_se(vals)
                    values[dk] = format_mean_se_sig(m, s, sig_figs)
                else:
                    values[dk] = "\u2013"
                if len(group.samples) < group.animals:
                    # The reports' note for a group short of samples.
                    n = len(group.samples)
                    count = _COUNT_WORDS[n] if n < len(_COUNT_WORDS) else str(n)
                    received = (f"Only {count} sample{'' if n == 1 else 's'} "
                                f"{'was' if n == 1 else 'were'}" if n else "No samples were")
                    text = (f"{received} received for the {format_dose_label(dose, dose_unit)} {dose_unit} "
                            f"{sex.lower()} {animal if group.animals == 1 else animals} at {h} "
                            f"{'hour' if h == 1 else 'hours'} {_after}.")
                    fid = short_notes.setdefault(text, f"samples_{len(short_notes)}")
                    marker_refs[dk] = fid
            row = {
                "label": timepoint_label(h, _after, _unit(h)),
                "doses": sorted_doses,
                "values": values,
                # The renderer re-rounds every mean ± SE cell; this keeps it at
                # the published 3 significant figures (display_precision).
                "sig_figs": sig_figs,
            }
            if marker_refs:
                row["marker_refs"] = marker_refs
            rows.append(row)

        serialized[sex] = rows

    if not serialized:
        return {}

    # ── Footnotes (NIEHS-07 … 10 Table 7, from the lab's PA48 summary) ────
    # The rule always (NIEHS-10 prints it with no value below the limit), the
    # BD definition when a cell is BD, then the lettered notes.  The lab and
    # the books call the limit "the limit of detection" whichever one the data
    # record (NIEHS-08 and 10 record only an LOQ).
    share = f"{rules.bd_share:.0%}" if rules.bd_share is not None else None
    footnotes: list[dict] = []
    if any_limit or any_bd:
        footnotes.append(definition_footnote(
            f"If over {share} of the animals in a group are above the limit of detection, then "
            "half the limit of detection value is substituted for values that are below it."
            if share else
            "Half the limit of detection value is substituted for values that are below it."))
    if any_bd:
        footnotes.append(definition_footnote(
            f"BD = below detection; group did not have over {share} of its values above the "
            "limit of detection so mean and standard error were not calculated."))
    footnotes.append(lettered_footnote(
        "Data are displayed as mean \u00b1 standard error of the mean.", "data_format",
        target="header"))
    for text, fid in short_notes.items():
        footnotes.append(lettered_footnote(text, fid, target="cells"))
    if any_outlier:
        footnotes.append(lettered_footnote(
            "Values identified by the outlier test of Dixon and Massey were excluded from "
            "analysis.", "outliers"))
    finalize_footnotes(footnotes, serialized)

    return {
        "title": "Tissue Concentration",
        "caption": apical_caption(CAPTION_TEMPLATE, serialized, compound_name, design),
        "compound": compound_name,
        "dose_unit": dose_unit,
        "first_col_header": "Timepoint",
        "table_data": serialized,
        "footnotes": footnotes,
        # Flag for Typst template to use pharmacokinetic layout:
        # no BMD columns, narrow format, different column headers.
        "table_type": "pharmacokinetic",
    }
