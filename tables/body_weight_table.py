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

from tables.table_builder_common import (
    js_dose_key as _js_dose_key,
    mean_se as _mean_se,
    format_mean_se as _format_mean_se,
    load_sidecar as _load_sidecar,
    find_sidecar_paths,
    BMD_DEFINITION,
    definition_footnote,
    lettered_footnote,
    finalize_footnotes,
    is_reportable_bmd,
)


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


# BMD_DEFINITION is imported from table_builder_common.py.


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


# _js_dose_key, _mean_se, _format_mean_se, _load_sidecar, find_sidecar_paths,
# and BMD_DEFINITION are imported from table_builder_common.py.


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


# _load_sidecar, _mean_se, _format_mean_se are imported from table_builder_common.py.


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

    # ── Footnotes (typed model — see table_builder_common) ────────────────
    # Body weight's footnote set, in render order.  finalize_footnotes —
    # called at the end, once the rows exist — assigns the a/b/c... letters
    # to the `lettered` records and derives each row's `markers` dict from
    # its `marker_refs`.
    #
    #   definition  — BMD/BMDL abbreviation paragraph         [Canonical]
    #   (a)         — data format (header marker a)           [Canonical]
    #   (b)         — statistical method (header marker b)    [Canonical]
    #   (c,d,...)   — attrition, one per individual-death event [Canonical]
    #   (next)      — mass attrition (one combined footnote)  [Canonical]
    #
    # There is no `*`/`**` significance legend: the sidecar builder computes
    # plain mean +/- SE from Core Animals and runs no pairwise test, so
    # body-weight cells carry no significance markers.  Provenance: every
    # body-weight footnote is Canonical — anchored in NIEHS Report 10 Table 2.
    footnotes: list[dict] = [
        definition_footnote(BMD_DEFINITION),
        lettered_footnote(FOOTNOTE_DATA_FORMAT, "data_format", target="header"),
        lettered_footnote(FOOTNOTE_STAT_METHOD, "stat_method", target="header"),
    ]

    # Footnote IDs to superscript on cells, keyed by location.  Two marker
    # placements (per the NIEHS reference):
    #   n_row_marker_refs  {sex: {dose: id}}        — N reduced by an
    #       individual early death; marker on the n-row cell.
    #   dash_marker_refs   {sex: {(dose, day): id}} — all animals at a dose
    #       died before a study day; marker on that data row's "-" dash.
    # finalize_footnotes turns these stable ids into the displayed letters.
    n_row_marker_refs: dict[str, dict[float, str]] = {}
    dash_marker_refs: dict[str, dict[tuple[float, str], str]] = {}

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
        n_row_marker_refs.setdefault(sex, {})
        dash_marker_refs.setdefault(sex, {})

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

    # ── Pass 2: individual-death footnotes (n-row markers) ───────────
    # One lettered/cells footnote per DISTINCT (sex, study-day, count) —
    # NOT per event.  Two dose groups that each lost "one male rat on
    # study day 0" share a single footnote, with its letter superscripted
    # on both n-row cells (the typed model lets many cells point at one
    # footnote id via marker_refs).  Emitting one footnote per event — the
    # old behavior — produced near-duplicate notes whenever the same death
    # pattern recurred across dose groups.  The footnote text names no
    # dose, so it reads correctly per-cell wherever its marker appears.
    indiv_fid_by_key: dict[tuple, str] = {}
    for ev in individual_events:
        sex = ev["sex"]
        dose = ev["dose"]
        count = ev["count"]
        day = ev["day"]
        day_num = day[2:] if day.upper().startswith("SD") else day
        key = (sex, day, count)
        fid = indiv_fid_by_key.get(key)
        if fid is None:
            # First event with this (sex, day, count) — emit the footnote.
            fid = f"indiv_death_{sex}_{day}_{count}"
            sex_word = sex.lower()
            if count == 1:
                text = f"One {sex_word} rat was found dead on study day {day_num}."
            else:
                text = f"{count} {sex_word} rats were found dead on study day {day_num}."
            footnotes.append(lettered_footnote(text, fid, target="cells"))
            indiv_fid_by_key[key] = fid

        # Marker goes on the n-row at this dose for this sex (the N is
        # reduced because this animal's data was excluded from the stats).
        n_row_marker_refs[sex][dose] = fid

    # ── Pass 3: mass-attrition footnote (dash markers) ───────────────
    # Merge all mass-attrition doses and sexes into one combined footnote,
    # matching the NIEHS reference style:
    #   "All male and female 333 and 1,000 mg/kg rats were found dead or
    #    moribund and euthanized by study day 1."
    if mass_doses:
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

        # Place the dash marker on the FIRST dash cell only (standard
        # footnote convention — the superscript introduces the footnote
        # once, the footnote text describes all affected cells).  The table
        # is read Male-then-Female, lowest-dose-first, so the first dash is
        # at the lowest mass-attrition dose in the Male SD5 row.
        marker_placed = False
        for sex in ("Male", "Female"):
            attrition = attrition_by_sex_dose.get(sex, {})
            for dose in sorted(all_mass_doses):
                if dose in attrition:
                    if not marker_placed:
                        dash_marker_refs[sex][(dose, expected_terminal_day)] = "mass_attrition"
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
        footnotes.append(lettered_footnote(
            f"All {sex_str} {dose_str} {dose_unit} rats were found dead "
            f"or moribund and euthanized by study day {day_num}.",
            "mass_attrition", target="cells",
        ))

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

        sex_n_marker_refs = n_row_marker_refs.get(sex, {})
        sex_dash_marker_refs = dash_marker_refs.get(sex, {})
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
        n_marker_refs: dict[str, str] = {}
        for dose in sorted_doses:
            dk = _js_dose_key(dose)
            max_n = 0
            for day in display_days:
                day_vals = sex_vals.get(day, {})
                n_at_dose = len(day_vals.get(dose, []))
                if n_at_dose > max_n:
                    max_n = n_at_dose

            # Only attach a marker ref if this dose has an individual death
            # that reduced N (marker on n-row, not on dash).  finalize_footnotes
            # turns the ref id into the displayed letter.
            ref = sex_n_marker_refs.get(dose)
            if ref:
                n_marker_refs[dk] = ref

            if max_n > 0:
                n_vals[dk] = str(max_n)
            else:
                n_vals[dk] = "\u2013"

        n_row = {
            "label": "n",
            "doses": sorted_doses,
            "values": n_vals,
            "bmd": "NA",
            "bmdl": "NA",
            "is_n_row": True,
        }
        if n_marker_refs:
            n_row["marker_refs"] = n_marker_refs
        rows.append(n_row)

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
            row_marker_refs: dict[str, str] = {}
            for dose in sorted_doses:
                dk = _js_dose_key(dose)
                animals_at_dose = dose_vals.get(dose, [])

                if animals_at_dose:
                    mean, se = _mean_se(animals_at_dose)
                    values[dk] = _format_mean_se(mean, se)
                else:
                    # No surviving animals at this dose for this day.
                    # Show dash (–) matching NIEHS convention.
                    values[dk] = "–"
                    # Check for a dash marker ref (mass attrition footnote);
                    # finalize_footnotes turns the ref id into the letter.
                    ref = sex_dash_marker_refs.get((dose, day))
                    if ref:
                        row_marker_refs[dk] = ref

            # Row emphasis (bold).  Body weight's sidecar builder runs no
            # NTP gate, so there is no `responsive` flag to OR in — a study-
            # day row is emphasized purely when its BMD column holds a real
            # modeled value (is_reportable_bmd).  The n-row is built above
            # with bmd "NA" and gets no `emphasize` key at all, so it never
            # bolds.
            entry = {
                "label": label,
                "doses": sorted_doses,
                "values": values,
                "bmd": bmd_text,
                "bmdl": bmdl_text,
                "emphasize": is_reportable_bmd(bmd_text),
            }
            if row_marker_refs:
                entry["marker_refs"] = row_marker_refs
            rows.append(entry)

        serialized[sex] = rows

    # Assign letters to the lettered footnotes and derive every row's
    # `markers` dict from its `marker_refs` — see the typed footnote
    # model in table_builder_common.
    finalize_footnotes(footnotes, serialized)

    return {
        "title": "Animal Condition, Body Weights, and Organ Weights",
        "caption": CAPTION_TEMPLATE.replace("{compound}", compound_name),
        "compound": compound_name,
        "dose_unit": dose_unit,
        "first_col_header": "Study Day",
        "table_data": serialized,
        # Typed footnote list: definition + lettered records, letters already
        # assigned by finalize_footnotes.  The old separate bmd_definition key
        # is folded in as a `definition` record.
        "footnotes": footnotes,
    }



# find_sidecar_paths is imported from table_builder_common.py.
