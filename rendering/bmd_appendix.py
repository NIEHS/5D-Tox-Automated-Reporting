"""rendering/bmd_appendix.py — Appendix D, Table D-1: how an apical BMD is
accepted, for the engine in force.

ToxicR model averaging (the engine every report has run with so far): the
table is built from the study's method profile (apical.bmd.acceptance,
ADR-0027) — the same criteria ``bmdx_pipe.bmd_acceptance`` classifies every
apical BMD with (the .bm2 results and the ToxicR fills alike) — so the appendix
states exactly the thresholds the tables were filtered with.

BMDS 2.7 (pipeline.bmds27, when it runs): the engine's own recommendation
rules decide, not the profile's criteria, and the table lists those rules.

A study whose pinned profile names an engine that is not the one in force
(RR-8, NIEHS-02 … 10: BMDS 2.7, replaced by ToxicR) prints this table in an
appendix its definition titles for the BMDS rules; a note under the table says
those rules were not applied (sweep of 2026-11-17, group 4).
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
    if method.get("apical.bmd.engine") == "bmds_2_7_high_dose_drop":
        return _bmds27_rules_matrix()
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
    footnotes = []
    note = _engine_not_in_force(method)
    if note:
        footnotes.append({"kind": "definition", "text": note})
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
        }] + footnotes,
    }


def _engine_not_in_force(method) -> str | None:
    """The note for a study whose pinned profile names an engine this report
    was not computed with (MethodSettings.substitutions), else None."""
    for sub in getattr(method, "substitutions", None) or []:
        if sub.get("setting") != "apical.bmd.engine":
            continue
        asked = {"bmds_2_7_high_dose_drop":
                 "the model recommendation rules of the Benchmark Dose Software (BMDS) "
                 "version 2.7.0"}.get(sub.get("asked"), f"the rules of {sub.get('asked')}")
        cannot = ("this tool does not implement" if sub.get("why") == "not implemented"
                  else "could not be run where this report was produced")
        return (f"The analysis method specified for this study ({method.profile}) selects a "
                f"model by {asked}, which {cannot}. Those rules were not applied: this "
                f"table gives the criteria applied to the BMDs in this report.")
    return None


def _bmds27_rules_matrix() -> dict:
    """Table D-1 under the BMDS 2.7 engine: its recommendation rules, as the
    engine runs them (pipeline.bmds27.engine.recommendation_rules)."""
    from pipeline.bmds27.engine import recommendation_rules

    rows = [[r["rule"], "NA" if r["threshold"] is None else _num(r["threshold"]),
             r["bin"].capitalize()] for r in recommendation_rules()]
    return {
        "caption": "Benchmark Dose Model Recommendation/Selection Rules for Apical Endpoints",
        "headers": ["Rule", "Numerical Threshold (N)", "Bin Placement for Rule Failure"],
        "rows": rows,
        "col_widths": [0.45, 0.20, 0.25],
        "footnotes": [{
            "kind": "definition",
            "text": ("The rules of the Benchmark Dose Software (BMDS) version 2.7.0 model "
                     "recommendation logic, as applied to each model of each endpoint. A "
                     "model that no rule places in the warning or failure bin is viable. "
                     "BMD = benchmark dose; BMDL = benchmark dose lower confidence limit; "
                     "NA = not applicable."),
        }],
    }
