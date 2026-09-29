"""
toxicokinetics.py — deterministic Internal Dose Assessment analysis.

Computes screening-level plasma toxicokinetics from the study's internal-dose
plasma-concentration data (the "Tissue Concentration" platform: PFHxSAm plasma
concentrations at two post-dose timepoints, in the internal-dose dose groups).

METHOD (validated against NIEHS Report 10 / NBK589955, which is the PFHxSAm study
itself — the computed half-lives reproduce the published values to the decimal):

  Half-life is first-order elimination between the two measured timepoints,
  computed on the GROUP-MEAN concentrations (mean of the biosampling animals per
  dose per timepoint):

      ke     = ln(C_early / C_late) / (t_late - t_early)        # 1/h
      t_half = ln(2) / ke                                       # h

  Supporting reads from the same means:
    * dose proportionality — the concentration ratio (high dose / low dose)
      against the dose ratio; sub-proportional scaling flags altered ADME.
    * bioaccumulation screen — t_half > 24 h (the reference's stated intent).

  Below-LOQ values are already handled upstream (½·LOQ substitution in the table
  builder); here we consume the biosampling per-animal values the same way.

This module is PURE COMPUTATION (no LLM, no I/O beyond reading the sidecar) so it
is byte-verifiable against the reference. The narrative that INTERPRETS these
numbers is generated separately (narrative layer), per the deterministic-vs-
authored split.
"""

from __future__ import annotations

import math

from tables.table_builder_common import load_sidecar, mean_se
from tables.tissue_concentration_table import _find_loq_value, _parse_timepoint

# t_half above this (hours) is flagged as a screening-level bioaccumulation signal.
BIOACCUM_HALF_LIFE_H = 24.0


def _timepoint_hours(timepoint: str) -> float | None:
    """The numeric hour of a timepoint label ("2 Hour" → 2.0). None if unparsable."""
    import re
    m = re.match(r"\s*(\d+(?:\.\d+)?)", timepoint or "")
    return float(m.group(1)) if m else None


def _extract_group_conc(sidecar: dict) -> dict[str, dict[float, list[float]]]:
    """Per-timepoint, per-dose biosampling-animal plasma values from one sidecar.

    Returns {timepoint_label: {dose: [value, ...]}}. Mirrors the tissue table
    builder's extraction (biosampling animals only; ½·LOQ substitution when a value
    is missing but its LOQ is present on the same study day) so the analysis and the
    table are computed from the SAME numbers.
    """
    out: dict[str, dict[float, list[float]]] = {}
    for rec in (sidecar.get("animals") or {}).values():
        if "biosampling" not in (rec.get("selection", "") or "").lower():
            continue
        dose = rec.get("dose")
        if dose is None:
            continue
        observations = rec.get("observations", []) or []
        for obs in observations:
            timepoint = _parse_timepoint(obs.get("endpoint", ""))
            if timepoint is None:
                continue
            val_str = obs.get("value")
            if val_str and str(val_str).strip():
                try:
                    out.setdefault(timepoint, {}).setdefault(float(dose), []).append(
                        float(val_str)
                    )
                    continue
                except (ValueError, TypeError):
                    pass
            loq = _find_loq_value(observations, obs.get("endpoint", ""), day=obs.get("day", ""))
            if loq is not None and loq > 0:
                out.setdefault(timepoint, {}).setdefault(float(dose), []).append(loq / 2)
    return out


def _half_life(c_early: float, c_late: float, dt_hours: float) -> tuple[float, float] | None:
    """First-order (ke, t_half) from two concentrations dt hours apart, or None when
    it can't be computed (non-declining, zero, or nonpositive concentrations)."""
    if c_early <= 0 or c_late <= 0 or dt_hours <= 0:
        return None
    if c_late >= c_early:
        return None  # no elimination observed between the timepoints
    ke = math.log(c_early / c_late) / dt_hours
    if ke <= 0:
        return None
    return ke, math.log(2) / ke


def compute_toxicokinetics(sidecar_paths: dict[str, str]) -> dict:
    """Screening-level internal-dose toxicokinetics from the plasma sidecars.

    Args:
        sidecar_paths: {"Male": ".../male.sidecar.json", "Female": ...}.

    Returns a dict:
        {
          "by_sex": {
            sex: {
              "timepoints": [hour, ...],             # ascending
              "doses": [dose, ...],                  # ascending
              "means": {dose: {hour: mean_conc}},    # ng/mL group means
              "n": {dose: n_biosampling},
              "half_life": {dose: t_half_h | None},  # ke-derived, group means
              "ke": {dose: ke_per_h | None},
              "bioaccumulative": {dose: bool},       # t_half > 24 h
            }
          },
          "dose_proportionality": {
            sex: {hour: {"conc_ratio": r, "dose_ratio": d, "sub_proportional": bool}}
          },
          "unit": "ng/mL",
        }
    Returns {"by_sex": {}} when no usable plasma data is present.
    """
    by_sex: dict[str, dict] = {}
    dose_prop: dict[str, dict] = {}

    for sex, path in sidecar_paths.items():
        try:
            sidecar = load_sidecar(path)
        except Exception:
            continue
        conc = _extract_group_conc(sidecar)
        if not conc:
            continue

        # Numeric-hour timepoints, ascending; doses ascending.
        tp_hours: dict[str, float] = {}
        doses: set[float] = set()
        for tp, dose_vals in conc.items():
            h = _timepoint_hours(tp)
            if h is None:
                continue
            tp_hours[tp] = h
            doses.update(dose_vals.keys())
        if len(tp_hours) < 2 or not doses:
            continue

        sorted_tps = sorted(tp_hours.items(), key=lambda kv: kv[1])  # (label, hour)
        hours = [h for _, h in sorted_tps]
        sorted_doses = sorted(doses)

        means: dict[float, dict[float, float]] = {}
        n: dict[float, int] = {}
        for dose in sorted_doses:
            per_hour: dict[float, float] = {}
            n_here = 0
            for tp, h in sorted_tps:
                vals = conc.get(tp, {}).get(dose, [])
                if vals:
                    m, _ = mean_se(vals)
                    per_hour[h] = m
                    n_here = max(n_here, len(vals))
            means[dose] = per_hour
            n[dose] = n_here

        # Half-life from the earliest and latest timepoints that both have a mean.
        half_life: dict[float, float | None] = {}
        ke_map: dict[float, float | None] = {}
        bioaccum: dict[float, bool] = {}
        early_h, late_h = hours[0], hours[-1]
        for dose in sorted_doses:
            ph = means.get(dose, {})
            c_early, c_late = ph.get(early_h), ph.get(late_h)
            res = (
                _half_life(c_early, c_late, late_h - early_h)
                if c_early is not None and c_late is not None
                else None
            )
            if res is None:
                half_life[dose] = ke_map[dose] = None
                bioaccum[dose] = False
            else:
                ke_map[dose], half_life[dose] = res
                bioaccum[dose] = half_life[dose] > BIOACCUM_HALF_LIFE_H

        by_sex[sex] = {
            "timepoints": hours,
            "doses": sorted_doses,
            "means": means,
            "n": n,
            "half_life": half_life,
            "ke": ke_map,
            "bioaccumulative": bioaccum,
        }

        # Dose proportionality: high vs low dose at each timepoint.
        if len(sorted_doses) >= 2:
            low, high = sorted_doses[0], sorted_doses[-1]
            dose_ratio = high / low if low else None
            per_tp: dict[float, dict] = {}
            for h in hours:
                c_low, c_high = means.get(low, {}).get(h), means.get(high, {}).get(h)
                if c_low and c_high and dose_ratio:
                    conc_ratio = c_high / c_low
                    per_tp[h] = {
                        "conc_ratio": conc_ratio,
                        "dose_ratio": dose_ratio,
                        "sub_proportional": conc_ratio < dose_ratio,
                    }
            if per_tp:
                dose_prop[sex] = per_tp

    return {"by_sex": by_sex, "dose_proportionality": dose_prop, "unit": "ng/mL"}


# ---------------------------------------------------------------------------
# Internal-dose narrative — grounded in the computed toxicokinetics.
# ---------------------------------------------------------------------------

def _fmt_dose(d: float) -> str:
    return f"{int(d)}" if float(d).is_integer() else f"{d:g}"


def build_internal_dose_narrative(tk: dict, compound_name: str, dose_unit: str = "mg/kg") -> list[str]:
    """Deterministic Internal Dose Assessment prose grounded in the computed TK.

    Follows the reference report's interpretive frame (NIEHS Report 10): what was
    measured, the sex difference in plasma exposure, the sub-proportional
    dose-scaling read (→ altered ADME), and the half-life / clearance-induction
    read. Every quantitative claim comes from the `tk` dict, so the prose can never
    drift from the numbers. Returns [] when there is no usable TK data.

    This is the DETERMINISTIC baseline (byte-stable, grounded). It is generated
    content — a human edits it externally after hand-off (ADR-0018); it is never
    auto-blessed as final.
    """
    by_sex = tk.get("by_sex") or {}
    if not by_sex:
        return []

    paragraphs: list[str] = []
    sexes = [s for s in ("Male", "Female") if s in by_sex]
    any_sex = by_sex[sexes[0]]
    hours = any_sex.get("timepoints") or []
    doses = any_sex.get("doses") or []
    unit = tk.get("unit", "ng/mL")

    # 1. What was measured.
    if hours and doses:
        hrs = " and ".join(f"{int(h) if float(h).is_integer() else h}" for h in hours)
        dgs = " and ".join(f"{_fmt_dose(d)} {dose_unit}" for d in doses)
        paragraphs.append(
            f"Plasma concentrations of {compound_name} were measured in biosampling "
            f"animals at {hrs} hours following the final dose in the {dgs} dose groups. "
            f"Average plasma concentrations (in {unit}) are summarized in the "
            f"accompanying table."
        )

    # 2. Sex difference in exposure (compare the highest-dose early-timepoint mean).
    if "Male" in by_sex and "Female" in by_sex and hours and doses:
        h0, dhi = hours[0], doses[-1]
        m = by_sex["Male"]["means"].get(dhi, {}).get(h0)
        f = by_sex["Female"]["means"].get(dhi, {}).get(h0)
        if m is not None and f is not None and m != f:
            higher, lower = ("female", "male") if f > m else ("male", "female")
            paragraphs.append(
                f"Average plasma concentrations in {higher} rats were higher than "
                f"those in {lower} rats, indicating a sex difference in internal exposure."
            )

    # 3. Dose proportionality → ADME inference.
    dp = tk.get("dose_proportionality") or {}
    sub_prop = any(
        d.get("sub_proportional") for per_tp in dp.values() for d in per_tp.values()
    )
    if sub_prop and len(doses) >= 2:
        # Report the ratios from whichever sex has them (they track together).
        per_tp = next(iter(dp.values()))
        ratios = sorted(per_tp.items())
        ratio_txt = "; ".join(
            f"approximately {d['conc_ratio']:.1f}-fold at {int(h) if float(h).is_integer() else h} hours"
            for h, d in ratios
        )
        dose_ratio = ratios[0][1]["dose_ratio"] if ratios else None
        dr = f"{dose_ratio:.1f}-fold" if dose_ratio else "the dose increase"
        paragraphs.append(
            f"As the administered dose increased {dr} (from {_fmt_dose(doses[0])} to "
            f"{_fmt_dose(doses[-1])} {dose_unit}), average plasma concentrations increased "
            f"less than proportionally ({ratio_txt}). This sub-proportional increase "
            f"suggests changes in the absorption, distribution, metabolism, and excretion "
            f"processes — such as lower absorption and/or induction of metabolism and "
            f"clearance pathways — as the dose increased."
        )

    # 4. Half-lives → bioaccumulation / clearance-induction read.
    hl_bits: list[str] = []
    for sex in sexes:
        s = by_sex[sex]
        parts = []
        for d in s["doses"]:
            th = s["half_life"].get(d)
            if th is not None:
                parts.append(f"{th:.1f} hours at {_fmt_dose(d)} {dose_unit}")
        if parts:
            hl_bits.append(f"{sex.lower()} rats, {' and '.join(parts)}")
    if hl_bits:
        # Was the half-life shorter at the higher dose (clearance induction)?
        induced = any(
            (by_sex[s]["half_life"].get(by_sex[s]["doses"][0]) or 0)
            > (by_sex[s]["half_life"].get(by_sex[s]["doses"][-1]) or 0)
            for s in sexes if len(by_sex[s]["doses"]) >= 2
        )
        bioaccum = any(
            v for s in sexes for v in by_sex[s]["bioaccumulative"].values()
        )
        sent = (
            f"Estimated plasma half-lives (from the measured timepoints) were: "
            f"{'; '.join(hl_bits)}."
        )
        if induced:
            sent += (
                " The shorter half-lives at the higher dose are consistent with "
                "induction of clearance pathways as the dose increases."
            )
        if bioaccum:
            sent += (
                " Half-lives exceeding 24 hours indicate potential for bioaccumulation "
                "at the screening level of this assessment."
            )
        paragraphs.append(sent)

    return paragraphs
