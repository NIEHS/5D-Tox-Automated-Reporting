"""
bmd_acceptance.py — which apical BMD results a report may print.

The apical BMDs are model averages (ToxicR Laplace model averaging of the Hill,
Power, Exponential 3 and Exponential 5 models).  NIEHS reports built on that
method (NIEHS Reports 12 and 13, Materials and Methods, "Benchmark Dose Analysis
of Body Weights, Organ Weights, and Clinical Pathology") pass every modeled
response through a BMDExpress defined-category filter and print "NVM" (no viable
model) for any that fail it:

  - R² of the model-averaged curve against the dose-group means ≥ 0.6
    (BMDExpress "Remove BMD with R^2 < Cutoff: 0.6");
  - BMD/BMDL ≤ 10 (BMDExpress "Remove genes with BMD/BMDL >: 10.0");
  - BMD ≤ the highest dose tested (BMDExpress "Remove BMD > Highest Dose").

Applied to the NIEHS-13 non-genomic project this reproduces every published
NVM (rat relative right kidney weight R² 0.56; rat sorbitol dehydrogenase, no
BMD; mouse body weight gain BMD/BMDL 10.3) and keeps every published value.

One reporting rule is carried on top of the filter: a BMD below one third of the
lowest nonzero dose is outside the range the data can support and is printed as
"<(lowest dose)/3" ("NR", not reportable) rather than as a number.

The statuses are "viable", "NR" and "NVM"; callers add "failure" for an endpoint
that was never modeled.  The criteria are module constants so the report's
methods appendix can state them from the same values the classifier applies.
"""

from __future__ import annotations

import math

R2_MIN = 0.6
BMD_BMDL_MAX = 10.0
NR_FRACTION = 1.0 / 3.0


def _finite(x) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def r_squared(group_means: list[float], predicted: list[float]) -> float | None:
    """BMDExpress's R² (BMDStatisticsService.calculateRSquared): one minus the
    residual sum of squares of the fitted curve at each dose group's mean over
    the total sum of squares of the group means.  None when the group means do
    not vary."""
    if not group_means or len(group_means) != len(predicted):
        return None
    avg = sum(group_means) / len(group_means)
    sst = sum((m - avg) ** 2 for m in group_means)
    if sst <= 0:
        return None
    ssr = sum((m - p) ** 2 for m, p in zip(group_means, predicted))
    return 1.0 - ssr / sst


def classify(
    bmd,
    bmdl,
    r2,
    lowest_nonzero_dose: float,
    highest_dose: float,
) -> tuple[str, str]:
    """(status, reason) of one modeled apical response.

    A criterion whose input is missing is not applied — the BMDExpress filter
    keeps a result whose BMDL or R² is undefined — except the BMD itself: a
    model average with no BMD has no viable model."""
    bmd_f = _finite(bmd)
    if bmd_f is None:
        return "NVM", "no BMD"
    r2_f = _finite(r2)
    if r2_f is not None and r2_f < R2_MIN:
        return "NVM", f"R² {r2_f:.3f} < {R2_MIN:g}"
    bmdl_f = _finite(bmdl)
    if bmdl_f is not None and bmdl_f > 0 and bmd_f / bmdl_f > BMD_BMDL_MAX:
        return "NVM", f"BMD/BMDL {bmd_f / bmdl_f:.1f} > {BMD_BMDL_MAX:g}"
    if highest_dose > 0 and bmd_f > highest_dose:
        return "NVM", f"BMD {bmd_f:.3g} > highest dose {highest_dose:g}"
    if lowest_nonzero_dose > 0 and bmd_f < lowest_nonzero_dose * NR_FRACTION:
        return "NR", f"BMD {bmd_f:.3g} < lowest nonzero dose/3"
    return "viable", ""


def classify_from_doses(bmd, bmdl, r2, doses) -> tuple[str, str]:
    """classify() with the dose range taken from the per-animal (or per-group)
    dose list."""
    nonzero = [float(d) for d in doses or [] if float(d) > 0]
    return classify(bmd, bmdl, r2,
                    min(nonzero) if nonzero else 0.0,
                    max(nonzero) if nonzero else 0.0)
