"""
tables/blood_tissue_concentration_table.py — the study-day layout of the
internal concentration table (NIEHS-12 Tables 18/19, NIEHS-13 Tables 19/20).

    Table 19. Summary of Blood, Lung, and Liver Concentration Data for Female
    Rats Exposed to 1,4-Dichlorobenzene for Five Days

The 2025 (DTT) studies measure the test article in blood and tissues on two
study days, rather than plasma at hours after dosing (the G2 timepoint layout,
tables.tissue_concentration_table).  Rows, per sex:

    Study Day 4
      n                                  animals sampled
      Blood
        Blood concentration (ng/mL)      mean ± SE, with markers
        Normalized blood concentration [(ng/mL)/ppm]
      Liver
        …
    Study Day 5
      …

Data: the sidecar of a Tissue Concentration truth CSV whose endpoints are
"<Matrix> <analyte> Concentration" with a paired "<Matrix> <analyte> LOD"
(tooling.cebs_lab_concentration).  A value "BLOD" — or an empty value with a
limit beside it — is below the limit of detection; an empty value with no
limit means the matrix was not sampled.  Every animal with a sample counts;
the lab records no cohort.

Rules (the published tables' footnotes):

* Outliers: "values identified by the outlier test of Dixon and Massey" are
  left out (the reports' statistical methods; NIEHS staff examined each).
  Dixon's r10 ratio — gap to the nearest value over the range — is tested at
  both ends of a group of 3 to 7, values below the LOD at one-half of the LOD,
  against the α = 0.01 critical value.  This reproduces every exclusion in
  NIEHS-12 Tables 18/19 and NIEHS-13 Tables 19/20 (a lone detected value
  beside two below the LOD, ratio 1; NIEHS-13's 1,250 ng/g mouse lung, 0.9945)
  and keeps every value they keep (largest ratio 0.9868); α = 0.005 (0.994)
  would fit them too.  Larger groups are not tested.
* A group with no more than 20% of its values above the LOD is "BD"; otherwise
  values below the LOD count as one-half of the LOD.
* Mean ± SE at 3 significant figures.
* Jonckheere (trend) and Shirley or Dunn (pairwise) tests — the nonparametric
  family — on the groups with a mean, only when the control has one.  The
  control cell carries the trend marker, a treated cell its pairwise marker.
* Normalized rows divide each animal's concentration by its group's nominal
  exposure, with no statistics; not applicable to the control.  The published
  tables also normalize by the theoretical inhaled dose (mg/kg/day), which the
  data do not record — those rows are not built.
* n is the animals sampled on the day; a matrix with fewer samples, or an
  outlier left out, is footnoted ("n = 2 for lung").
* Matrices in the order blood, then the tissues alphabetically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tables.table_builder_common import (
    apical_caption,
    definition_footnote,
    finalize_footnotes,
    format_mean_se_sig,
    js_dose_key,
    legend_footnote,
    lettered_footnote,
    mean_se,
)
from tables.units import UNIT_NOT_RECORDED, recorded_units

CAPTION_TEMPLATE = "Summary of {matrices} Concentration Data for {subject} {treatment}"

_CONC = re.compile(r"^(?P<matrix>\w+)\s+(?P<analyte>.+?)\s+Concentration$")
_LIMIT_SUFFIXES = ("LOD", "LOQ")
_HOUR_ENDPOINT = re.compile(r"Plasma\s+\d+\s+Hour", re.I)
_NUMBER = re.compile(r"^-?\d*\.?\d+(?:[eE][-+]?\d+)?$")

BD = "BD"
NOT_APPLICABLE = "−"     # − (minus sign), as published
NOT_SAMPLED = "–"        # –
# Dixon's r10 critical values (Dixon and Massey), one-sided α → {group size: value}.
DIXON_R10_CRITICAL = {
    0.10: {3: 0.886, 4: 0.679, 5: 0.557, 6: 0.482, 7: 0.434},
    0.05: {3: 0.941, 4: 0.765, 5: 0.642, 6: 0.560, 7: 0.507},
    0.01: {3: 0.988, 4: 0.889, 5: 0.780, 6: 0.698, 7: 0.637},
    0.005: {3: 0.994, 4: 0.926, 5: 0.821, 6: 0.740, 7: 0.680},
}


@dataclass(frozen=True)
class Rules:
    """The internal-dose rules of the study's method profile (internal_dose.*,
    ADR-0027): the values the module docstring describes for ntp-5day-2025."""
    sig_figs: int
    bd_share: float | None            # BD unless MORE than this share is detected; None: no BD
    dixon: dict | None                # {group size: critical value}; None: no outlier test
    pairwise: str                     # "shirley_or_dunn" | "williams_or_dunnett" | "none"
    stats: object                     # bmdx_pipe.ntp_stats.StatsMethod (thresholds)

    @classmethod
    def from_method(cls, method) -> "Rules":
        outliers = method.get("internal_dose.outliers")
        dixon = None
        if outliers:
            dixon = DIXON_R10_CRITICAL.get(outliers["alpha"])
            if dixon is None:
                from pipeline.method_profile import MethodProfileError
                raise MethodProfileError(
                    f"internal_dose.outliers.alpha {outliers['alpha']}: Dixon r10 critical "
                    f"values are tabulated for {sorted(DIXON_R10_CRITICAL)}")
        return cls(sig_figs=method.get("internal_dose.sig_figs"),
                   bd_share=method.get("internal_dose.bd_if_detected_share_at_most"),
                   dixon=dixon,
                   pairwise=method.get("internal_dose.pairwise"),
                   stats=method.internal_dose_stats_method())


def is_day_layout(sidecars) -> bool:
    """True when the sidecars hold matrix concentrations with a paired limit
    column and no plasma-hour endpoints (the G2 timepoint layout)."""
    endpoints = {o.get("endpoint", "") for sc in sidecars
                 for a in (sc or {}).get("animals", {}).values() for o in a.get("observations", [])}
    if any(_HOUR_ENDPOINT.search(e) for e in endpoints):
        return False
    return any(_CONC.match(e) and _limit_endpoint(e, endpoints) for e in endpoints)


def _limit_endpoint(conc_endpoint: str, endpoints) -> str | None:
    stem = conc_endpoint[: -len("Concentration")]
    return next((stem + s for s in _LIMIT_SUFFIXES if stem + s in endpoints), None)


def _matrix_order(matrix: str) -> tuple[int, str]:
    return (0 if matrix.lower() == "blood" else 1, matrix.lower())


def _day_number(day: str) -> int:
    m = re.search(r"(\d+)", day or "")
    return int(m.group(1)) if m else 10**6


def _samples(sidecar: dict) -> tuple[dict, dict, list[str], dict]:
    """({day: {dose: {matrix: [(value, limit)]}}}, {day: {dose: n}}, matrices in
    data order, {matrix: concentration endpoint}).  value is a float, or None
    below the limit; animals not sampled for a matrix are absent."""
    by_day: dict = {}
    n: dict = {}
    matrices: list[str] = []
    endpoint_of: dict[str, str] = {}
    for rec in sidecar.get("animals", {}).values():
        dose = float(rec["dose"])
        obs = rec.get("observations", [])
        endpoints = {o.get("endpoint", "") for o in obs}
        limits = {(o.get("day"), o.get("endpoint")): o.get("value") for o in obs}
        sampled_days = set()
        for o in obs:
            m = _CONC.match(o.get("endpoint", ""))
            limit_ep = _limit_endpoint(o.get("endpoint", ""), endpoints) if m else None
            if not limit_ep:
                continue
            matrix, day = m.group("matrix").title(), o.get("day", "")
            if matrix not in endpoint_of:
                matrices.append(matrix)
                endpoint_of[matrix] = o["endpoint"]
            value = (o.get("value") or "").strip()
            limit = (limits.get((day, limit_ep)) or "").strip()
            if _NUMBER.match(value):
                sample = (float(value), limit)
            elif limit and (not value or value.upper().startswith(("BLOD", "BLOQ"))):
                sample = (None, limit)
            else:
                continue                                  # not sampled
            by_day.setdefault(day, {}).setdefault(dose, {}).setdefault(matrix, []).append(sample)
            sampled_days.add(day)
        for day in sampled_days:
            n.setdefault(day, {})[dose] = n.get(day, {}).get(dose, 0) + 1
    return by_day, n, matrices, endpoint_of


def _dixon_outlier(values: list[float], critical: dict | None) -> int | None:
    """Index of the value Dixon's r10 test flags at either end, or None."""
    crit = (critical or {}).get(len(values))
    order = sorted(range(len(values)), key=values.__getitem__)
    spread = values[order[-1]] - values[order[0]]
    if crit is None or spread <= 0:
        return None
    high = (values[order[-1]] - values[order[-2]]) / spread
    low = (values[order[1]] - values[order[0]]) / spread
    if max(high, low) <= crit:
        return None
    return order[-1] if high >= low else order[0]


def _group_values(samples: list[tuple], rules: Rules) -> tuple[list[float] | None, int]:
    """(the values a group's mean is computed from, or None when it is BD;
    the number of outliers left out)."""
    filled = [(v if v is not None else float(lim) / 2, v is not None) for v, lim in samples]
    out = _dixon_outlier([v for v, _ in filled], rules.dixon)
    kept = [x for i, x in enumerate(filled) if i != out]
    if rules.bd_share is not None and sum(det for _, det in kept) <= rules.bd_share * len(kept):
        return None, int(out is not None)
    return [v for v, _ in kept], int(out is not None)


def _fmt(values: list[float], sig_figs: int) -> str:
    m, s = mean_se(values)
    return format_mean_se_sig(m, s, sig_figs)


def _dose_label(dose: float, dose_unit: str) -> str:
    return f"{js_dose_key(dose)} {dose_unit}"


def build_day_layout_table(sidecar_data: dict[str, dict], compound_name: str,
                           dose_unit: str, design: dict | None, method) -> dict:
    """The study-day concentration table (module docstring) from {sex: sidecar},
    under the study's resolved method (pipeline.method_profile.MethodSettings)."""
    from bmdx_pipe.ntp_stats import ntp_pairwise
    from pipeline.method_profile import family_of, marker_legend, statistics_sentence

    rules = Rules.from_method(method)
    family = family_of(rules.pairwise)

    units = recorded_units(sidecar_data.values(), lambda ep: bool(_CONC.match(ep)))
    serialized: dict[str, list[dict]] = {}
    all_matrices: list[str] = []
    limits: dict[str, set[str]] = {}
    n_notes: list[str] = []
    any_marker = any_bd = control_bd = any_stats = any_normalized = any_outlier = False

    for sex in ("Male", "Female"):
        sc = sidecar_data.get(sex)
        if not sc:
            continue
        by_day, n_by_day, matrices, endpoint_of = _samples(sc)
        if not by_day:
            continue
        all_matrices += [m for m in matrices if m not in all_matrices]
        doses = sorted({float(a["dose"]) for a in sc["animals"].values()})
        control = doses[0] if doses and doses[0] == 0 else None
        rows: list[dict] = []

        def row(label, values=None, **flags):
            rows.append({"label": label, "doses": doses, "values": values or {}, **flags})

        for day in sorted(by_day, key=_day_number):
            groups = by_day[day]
            row(f"Study Day {_day_number(day)}", is_heading=True)
            row("n", {js_dose_key(d): str(n_by_day[day].get(d) or NOT_SAMPLED) for d in doses},
                is_n_row=True)
            for matrix in sorted(matrices, key=_matrix_order):
                unit = units.get(endpoint_of[matrix]) or UNIT_NOT_RECORDED.format(what="concentration")
                values_by_dose = {}
                for d in doses:
                    samples = groups.get(d, {}).get(matrix, [])
                    for _, lim in samples:
                        limits.setdefault(matrix, set()).add(lim)
                    values_by_dose[d], outliers = (_group_values(samples, rules) if samples
                                                   else ([], 0))
                    short = len(samples) - outliers
                    any_outlier = any_outlier or bool(outliers)
                    if short < n_by_day[day].get(d, 0):
                        why = (" One animal was identified as an outlier and thus excluded from "
                               "analysis." if outliers else " No sample was received for "
                               f"{'one animal' if short + 1 == n_by_day[day][d] else 'some animals'}.")
                        n_notes.append(f"Study Day {_day_number(day)}, {_dose_label(d, dose_unit)}: "
                                       f"n = {short} for {matrix.lower()}.{why}")

                markers: dict[float, str] = {}
                if family and control is not None and values_by_dose.get(control):
                    tested = {d: v for d, v in values_by_dose.items() if v}
                    result = ntp_pairwise(tested, family, control_dose=control, method=rules.stats)
                    any_stats = True
                    markers[control] = rules.stats.marker(result.jonckheere_p)
                    markers.update({d: rules.stats.marker(p) for d, p in result.pairwise_p.items()})
                elif control is not None and values_by_dose.get(control) is None:
                    control_bd = True

                cells, normalized = {}, {}
                for d in doses:
                    v = values_by_dose[d]
                    dk = js_dose_key(d)
                    if v is None:
                        cells[dk] = BD
                        any_bd = True
                    elif not v:
                        cells[dk] = NOT_SAMPLED
                    else:
                        cells[dk] = _fmt(v, rules.sig_figs) + markers.get(d, "")
                        any_marker = any_marker or bool(markers.get(d))
                    if d == control:
                        normalized[dk] = NOT_APPLICABLE
                    else:
                        normalized[dk] = cells[dk] if not v else _fmt([x / d for x in v],
                                                                      rules.sig_figs)
                row(matrix, is_heading=True)
                row(f"{matrix} concentration ({unit})", cells, sig_figs=rules.sig_figs)
                if any(d != control for d in doses):
                    any_normalized = True
                    row(f"Normalized {matrix.lower()} concentration [({unit})/{dose_unit}]",
                        normalized, sig_figs=rules.sig_figs)
        serialized[sex] = rows

    if not serialized:
        return {}

    footnotes: list[dict] = []
    if any_marker:
        footnotes.append(legend_footnote(
            f"Statistical significance for an exposed group indicates a significant pairwise "
            f"test compared to the 0 {dose_unit} group. Statistical significance for the "
            f"0 {dose_unit} group indicates a significant trend test."))
        footnotes.append(legend_footnote(marker_legend(method)))
    share = f"{rules.bd_share:.0%}" if rules.bd_share is not None else None
    if any_bd:
        footnotes.append(definition_footnote(
            f"BD = below detection; group did not have more than {share} of its values above "
            "the limit of detection (LOD)."))
    footnotes.append(lettered_footnote("Data are presented as mean ± standard error.", "data_format"))
    lod_text = "; ".join(
        f"LOD for {m.lower()} = {' or '.join(sorted(limits[m]))} "
        f"{units.get(_endpoint_unit_key(sidecar_data, m), '') or ''}".rstrip()
        for m in sorted(limits, key=_matrix_order))
    substitution = ("one-half of the LOD was substituted for values below the LOD"
                    if share is None else
                    f"If over {share} of the animals in a group were above the limit of detection "
                    "(LOD), one-half of the LOD was substituted for values below the LOD")
    footnotes.append(lettered_footnote(
        f"{substitution[0].upper()}{substitution[1:]}. {lod_text}.", "lod_rule"))
    if any_outlier:
        footnotes.append(lettered_footnote(
            "Values identified by the outlier test of Dixon and Massey were excluded from "
            "analysis.", "outliers"))
    if any_stats:
        footnotes.append(lettered_footnote(statistics_sentence(method, rules.pairwise),
                                           "stats_method"))
    if control_bd:
        footnotes.append(lettered_footnote(
            f"When the 0 {dose_unit} group did not have over {share} of its values above the "
            "LOD, no mean or standard error was calculated, and no statistical analysis was "
            "performed.", "control_bd"))
    if any_normalized:
        footnotes.append(lettered_footnote(
            "Normalized concentrations were calculated by dividing the measured concentration "
            f"by the nominal exposure ({dose_unit}). No statistical analysis was performed on "
            "normalized endpoints.", "normalized"))
        footnotes.append(lettered_footnote(f"{NOT_APPLICABLE} = not applicable.", "not_applicable"))
    for i, text in enumerate(dict.fromkeys(n_notes)):
        footnotes.append(lettered_footnote(text, f"n_{i}"))
    finalize_footnotes(footnotes, serialized)

    matrices_phrase = _series([m.title() for m in all_matrices])
    caption = apical_caption(CAPTION_TEMPLATE.replace("{matrices}", matrices_phrase),
                             serialized, compound_name, design)
    days = sorted({r["label"] for rows in serialized.values() for r in rows
                   if r.get("is_heading") and r["label"].startswith("Study Day")}, key=_day_number)
    day_numbers = [str(_day_number(d)) for d in days]
    summary = (f"{_series([m.lower() for m in all_matrices]).capitalize()} concentrations of "
               f"{compound_name} were measured on study day{'s' if len(days) > 1 else ''} "
               f"{_series(day_numbers)}.")
    return {
        "title": "Tissue Concentration",
        "caption": caption,
        "compound": compound_name,
        "dose_unit": dose_unit,
        "first_col_header": "Endpoint",
        "table_data": serialized,
        "footnotes": footnotes,
        "table_type": "pharmacokinetic",
        "summary": summary,
    }


def _endpoint_unit_key(sidecar_data: dict, matrix: str) -> str:
    """The concentration endpoint of `matrix` (the units map's key)."""
    for sc in sidecar_data.values():
        for ep in (sc or {}).get("units") or {}:
            m = _CONC.match(ep)
            if m and m.group("matrix").title() == matrix:
                return ep
    return ""


def _series(items: list[str]) -> str:
    """"Blood", "Blood and Lung", "Blood, Lung, and Liver" (serial comma)."""
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]
