"""rendering/bmd_appendix.py — Appendix D, the apical BMD acceptance criteria.

Table D-1 is built from the study's method profile (apical.bmd.acceptance,
ADR-0027) — the same criteria ``bmdx_pipe.bmd_acceptance`` classifies every
apical BMD with (the .bm2 results and the ToxicR fills alike) — so the appendix
states exactly the thresholds the tables were filtered with.  It replaces the
BMDS 2.7 model-recommendation rules NIEHS Report 10 printed, which describe a
method this pipeline never runs.
"""

from __future__ import annotations

def _num(x: float) -> str:
    return f"{x:g}"


def build_bmd_acceptance_matrix(method=None) -> dict:
    """Table D-1 as the generic ``{caption, headers, rows, footnotes}`` matrix a
    ``data-table`` node renders.  ``method`` is the study's resolved method
    (pipeline.method_profile.MethodSettings); None ⇒ the newest profile."""
    if method is None:
        from pipeline.method_profile import session_method
        method = session_method(None)
    acc = method.acceptance_criteria()
    low = round(1 / acc.nr_fraction, 6)
    rows = [
        ["BMD existence", "The model average yields a BMD.", "NA", "NVM"],
        ["Goodness of fit",
         "The R² of the model-averaged curve against the dose-group means is "
         "at least N.", _num(acc.r2_min), "NVM"],
        ["BMD-to-BMDL ratio", "BMD/BMDL is no greater than N.",
         _num(acc.bmd_bmdl_max), "NVM"],
    ]
    if acc.max_dose:
        rows.append(["High BMD", "The BMD is no higher than the highest dose tested.",
                     "NA", "NVM"])
    rows += [
        ["Low BMD",
         "The BMD is no more than N times lower than the lowest nonzero dose.",
         _num(low),
         f"Reported as <(lowest nonzero dose)/{_num(low)}, without a BMDL"],
    ]
    return {
        "caption": "Benchmark Dose Acceptance Criteria for Apical Endpoints",
        "headers": ["Criterion", "Requirement for a Reported BMD",
                    "Numerical Threshold (N)", "Result When Not Met"],
        "rows": rows,
        # Fractions of the line width (LaTeX p-columns): the requirement and
        # outcome texts wrap instead of running off the page.
        "col_widths": [0.18, 0.40, 0.12, 0.20],
        "footnotes": [{
            "kind": "definition",
            "text": ("BMD = benchmark dose; BMDL = benchmark dose lower confidence "
                     "limit; R² = coefficient of determination, one minus the "
                     "residual sum of squares of the fitted curve at the dose-group "
                     "means over their total sum of squares; NA = not applicable; "
                     "NVM = no viable model."),
        }],
    }
