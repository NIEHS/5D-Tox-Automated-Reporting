"""
methods_analysis.py — the Materials and Methods subsections that state how a
computation was done, built from the record of the computation.

"Benchmark Dose Analysis of Body Weights, Organ Weights, and Clinical
Pathology" describes the apical BMDs.  A paragraph written from a guideline
described one method for every study (one engine, "constant variance", the
method profile's BMR), while a printed BMD could be the study's own BMDExpress
result, or this tool's fit at the recorded settings, or its fit at the
profile's — and a method the profile names but this tool cannot run was
replaced with only a log line to say so (sweep of 2026-11-17, group 4).

"Empirical False Discovery Rate Determination …" said for every study that
eFDR results "are not included in this report's data package", including the
reports whose appendix prints them.  It now says whether the report has them.

So the BMD paragraph is assembled here from ``MethodsContext.apical_bmd_method``
(tables.apical_bmds.apical_bmd_method): per group of assays, where the BMDs
come from and the settings in force; then the acceptance criteria the method
applies; then each departure from the pinned method
(``MethodsContext.method_substitutions``).  It states nothing else.
"""

from __future__ import annotations

from narrative.methods_models import MethodsContext
from narrative.narrative_helpers import _join_oxford

_TOXICR = "toxicr_model_average"

# The reporting gate of each eligibility the tool applies (every endpoint with
# individual-animal data is modeled; the gate decides which BMDs are reported).
_REPORTED_WHEN = {
    "trend_and_pairwise": "a significant trend and at least one significant pairwise difference",
    "trend_or_pairwise": "a significant trend or at least one significant pairwise difference",
}
# What a pinned profile asked for that is not in force, as the Methods name it.
_ASKED = {
    "bmds_2_7_high_dose_drop": "the Benchmark Dose Software (BMDS) version 2.7.0",
}
_BMDS27_MODELS = (
    "a modification of the Benchmark Dose Software (BMDS) version 2.7.0, run in batch "
    "through the Python BMDS interface (version 0.11), with the Linear, Polynomial "
    "(degree 2 to the number of dose groups minus 1), Power, Hill and Exponential "
    "(M2 to M5) models and BMDS 2.7.0 model defaults; when no model was recommended, "
    "the highest dose group was removed and the data set modeled again, until a model "
    "was recommended or three dose groups remained")
_FRACTION_WORDS = {1 / 3: "one third", 0.5: "one half", 0.25: "one quarter", 0.1: "one tenth"}


def _record(ctx: MethodsContext) -> dict:
    """The context's record, or a refusal: a context cached before the record
    existed described a method no record backs, and is never re-stated."""
    if not isinstance(ctx.apical_bmd_method, dict):
        from workflow.errors import StepError
        raise StepError("the Materials and Methods were built before the apical BMD "
                        "method was recorded; run Process again", 409)
    return ctx.apical_bmd_method


_PLATFORM_WORDS = {"Hormones": "hormone"}


def _endpoints_of(setting: dict, all_sexes: list[str]) -> str:
    """"body weight, organ weight, and hematology endpoints" — a platform the
    setting covers for one sex only names it ("clinical chemistry (female)")."""
    from tables.apical_bmds import in_report_order

    names = []
    for platform, sexes in in_report_order(setting.get("platforms") or {}).items():
        name = _PLATFORM_WORDS.get(platform, platform.lower())
        if sexes and len(all_sexes) > 1 and set(sexes) != set(all_sexes):
            name += f" ({' and '.join(s.lower() for s in sexes)})"
        names.append(name)
    return f"{_join_oxford(names)} endpoints"


def _bmr(setting: dict) -> str:
    from tables.apical_bmds import bmr_phrase

    return bmr_phrase(setting.get("bmr")) or "a benchmark response that is not recorded"


def _variance(constant: bool | None) -> str:
    if constant is None:
        return "a variance setting the project does not record"
    return "constant variance" if constant else "nonconstant variance"


def _our_fit(setting: dict) -> str:
    return (f"ToxicR Laplace model averaging of the {_join_oxford(setting['models'])} "
            f"models with {_variance(setting['constant_variance'])}")


def _recorded_sentences(settings: list[dict], sexes: list[str], gate: str) -> list[str]:
    """The settings the study's own analysis records.  Those that differ only
    in the BMR (the February 2026 DTT method: clinical chemistry at a relative
    deviation, the rest at 1 SD) are stated together."""
    out = []
    groups: dict[str, list[dict]] = {}
    for setting in settings:
        key = repr((setting.get("analysis"), setting["constant_variance"], setting["models"]))
        groups.setdefault(key, []).append(setting)
    for members in groups.values():
        analysis = members[0].get("analysis") or {}
        how = analysis.get("selection") or "a model selection the project does not record"
        models = analysis.get("models") or []
        software = f" ({analysis['software']})" if analysis.get("software") else ""
        what = "; ".join(
            f"the {_endpoints_of(m, sexes)}, at a "
            f"{'benchmark response (BMR)' if i == 0 else 'BMR'} of {_bmr(m)}"
            for i, m in enumerate(members))
        analysis_text = (how + (f" of the {_join_oxford(models)} models" if models else "")
                         + f", with {_variance(analysis.get('constant_variance'))}")
        if len(members) == 1:
            out.append(
                f"The benchmark doses (BMDs) of the {_endpoints_of(members[0], sexes)} are "
                f"those of the study's BMDExpress analysis{software}: {analysis_text}, at a "
                f"benchmark response (BMR) of {_bmr(members[0])}.")
        else:
            out.append(
                f"The benchmark doses (BMDs) of these endpoints are those of the study's "
                f"BMDExpress analysis{software}, {analysis_text}: {what}.")
        out.append(
            f"An endpoint that analysis modeled without obtaining a numeric BMD, or did not "
            f"model although it showed {gate}, was modeled for this report from the "
            f"individual-animal data by {_our_fit(members[0])} at the same BMR; a viable "
            f"result is reported in its place.")
    return out


def _inferred_sentences(setting: dict, sexes: list[str], gate: str, only: bool) -> list[str]:
    what = _endpoints_of(setting, sexes)
    lead = (f"The data integrated for this report record no benchmark dose (BMD) analysis "
            f"of the {what}." if only else
            f"The data integrated for this report record no BMD analysis of the {what}.")
    return [
        lead,
        f"They were modeled for this report from the nontransformed individual-animal data "
        f"by {_our_fit(setting)}, at a benchmark response (BMR) of {_bmr(setting)}; a BMD "
        f"is reported for an endpoint that showed {gate}.",
    ]


def _join_or(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + (
        "," if len(items) > 2 else "") + " or " + items[-1]


def _acceptance(method) -> str:
    acc = method.acceptance_criteria()
    reasons = [f"its R² was below {acc.r2_min:g}",
               f"its BMD/BMDL ratio was above {acc.bmd_bmdl_max:g}"]
    if acc.max_dose:
        reasons.append("its BMD was above the highest dose")
    fraction = next((w for f, w in _FRACTION_WORDS.items() if abs(f - acc.nr_fraction) < 1e-9),
                    f"{acc.nr_fraction:g} times")
    of = "" if fraction.endswith("times") else " of"
    return (
        f"A modeled response was not accepted when {_join_or(reasons)}; an "
        f"endpoint without an accepted model is reported as having no viable model (NVM). "
        f"A BMD below {fraction}{of} the lowest nonzero dose is reported as less than that "
        f"value, without a BMDL.")


def _substitution_sentences(ctx: MethodsContext, gate: str) -> list[str]:
    """One or two sentences per departure from the pinned method."""
    out = []
    for sub in ctx.method_substitutions or []:
        setting, asked, why = sub.get("setting"), sub.get("asked"), sub.get("why")
        profile = f" ({ctx.method_profile})" if ctx.method_profile else ""
        cannot = ("this tool does not implement it" if why == "not implemented"
                  else "it could not be run where this report was produced")
        if setting == "apical.bmd.engine":
            out.append(
                f"The analysis method specified for this study{profile} computes these BMDs "
                f"with {_ASKED.get(asked, asked)}; {cannot}. The BMDs in this report were "
                f"computed as described here and are not the results of that software.")
        elif setting == "apical.bmd.eligibility" and asked == "all_endpoints":
            out.append(
                f"That method reports a BMD for every endpoint modeled; this report gives "
                f"one only for an endpoint that showed {gate}.")
        else:
            out.append(
                f"The specified method{profile} sets {setting} to {asked}; {cannot}, and "
                f"{sub.get('used')} was used.")
    return out


# ---------------------------------------------------------------------------
# The values left out of the apical analysis (ADR-0037)
# ---------------------------------------------------------------------------
# One paragraph, the last of the statistics subsection, built from the marks
# the study's sidecars carry (MethodsContext.excluded_values: {reason: count}).
# Its opening and closing are fixed, which is how a later build recognizes and
# replaces it (methods_design.refresh_data_built, rendering.report_compose).

EXCLUDED_SUBSECTION = "stat_analysis"
EXCLUDED_OPENING = "Prior to analysis, "
EXCLUDED_CLOSING = "noted in the table it belongs to."


def _excluded_clause(reason: str, n: int) -> str:
    from narrative.unified_narrative import _count_word

    values = f"{_count_word(n)} value{'' if n == 1 else 's'}"
    was = "was" if n == 1 else "were"
    if reason == "measurement problem":
        problem = "a measurement problem" if n == 1 else "measurement problems"
        return (f"{values} that the laboratory indicated as inadequate because of "
                f"{problem} {was} excluded")
    if reason == "unrelated illness":
        animals = "an animal" if n == 1 else "animals"
        return (f"{values} from {animals} suspected of illness from causes other than "
                f"experimental exposure {was} excluded")
    return f"{values} {was} excluded as {'an outlier' if n == 1 else 'outliers'}"


def excluded_values_paragraph(groups: list[tuple[str | None, dict | None]]) -> str | None:
    """The paragraph that states the values left out of the apical analysis.

    ``groups``: ``[(whose, {reason: count})]``: one entry with ``whose`` None
    for a study; for a report over several studies one per study, named by
    its animals ("Rats", "Mice").  None when nothing was left out.

    "Prior to analysis, one value was excluded as an outlier. It is noted in
    the table it belongs to."
    """
    from bmdx_pipe.excluded_values import REASONS
    from narrative.narrative_helpers import _join_oxford

    stated, total = [], 0
    for whose, counts in groups:
        clauses = [_excluded_clause(r, counts[r]) for r in REASONS if (counts or {}).get(r)]
        if not clauses:
            continue
        total += sum(counts[r] for r in REASONS if counts.get(r))
        stated.append(_join_oxford(clauses) + (f" for the {whose.lower()}" if whose else ""))
    if not stated:
        return None
    body = "; ".join(stated) if any(", " in s for s in stated) else _join_oxford(stated)
    return (f"{EXCLUDED_OPENING}{body}. {'It is' if total == 1 else 'Each is'} "
            f"{EXCLUDED_CLOSING}")


def is_excluded_values_paragraph(paragraph) -> bool:
    return (isinstance(paragraph, str) and paragraph.startswith(EXCLUDED_OPENING)
            and paragraph.endswith(EXCLUDED_CLOSING))


def with_excluded_values(paragraphs: list[str], stated: str | None) -> list[str]:
    """A statistics subsection's paragraphs with the excluded-values
    paragraph as it is now: any earlier one removed, ``stated`` last."""
    kept = [p for p in paragraphs if not is_excluded_values_paragraph(p)]
    return kept + ([stated] if stated else [])


def build_bmd_apical(ctx: MethodsContext, introduce: bool = True) -> list[str]:
    """The apical BMD paragraph(s), from the record of the computation."""
    from narrative.methods_prompt import _method

    record = _record(ctx)
    method = _method(ctx)
    settings = record.get("settings") or []
    if not settings:
        return []
    sexes = [str(s).title() for s in ctx.sexes or []]
    gate = _REPORTED_WHEN[method.get("apical.bmd.eligibility")]
    has_body_weight = any("Body Weight" in (s.get("platforms") or {}) for s in settings)
    body_weight = ("For body weight, the BMD and benchmark dose lower confidence limit "
                   "(BMDL) are presented as not determined (ND) when there were no "
                   "significant results.")

    if record.get("engine") != _TOXICR:
        setting = settings[0]
        sentences = [
            f"Benchmark dose (BMD) modeling of the {_endpoints_of(setting, sexes)} used "
            f"dose-group summary data (N, mean, standard deviation). Every endpoint was "
            f"modeled; a BMD is reported for an endpoint that showed {gate}.",
            f"Modeling used {_BMDS27_MODELS}, and a benchmark response (BMR) of "
            f"{_bmr(setting)} (relative to control).",
            "Each model was placed in a bin by the recommendation rules of Appendix D, "
            "Table D-1; among the viable models (those no rule placed in the warning or "
            "failure bin), the one with the lowest AIC was recommended when their BMDLs "
            "were within 3-fold of each other, else the one with the lowest BMDL. An "
            "endpoint that met the statistical criteria without a recommended model is "
            "reported as having no viable model (NVM).",
        ]
        if has_body_weight:
            sentences.append(body_weight)
        return [" ".join(sentences + _substitution_sentences(ctx, gate))]

    recorded = [s for s in settings if s["source"] == "recorded"]
    inferred = [s for s in settings if s["source"] == "inferred"]
    sentences: list[str] = []
    sentences += _recorded_sentences(recorded, sexes, gate)
    for setting in inferred:
        sentences += _inferred_sentences(setting, sexes, gate, only=not recorded)
    sentences.append(_acceptance(method))
    if has_body_weight:
        sentences.append(body_weight)
    paragraphs = [" ".join(sentences)]
    departures = _substitution_sentences(ctx, gate)
    if departures:
        paragraphs.append(" ".join(departures))
    return paragraphs


# ---------------------------------------------------------------------------
# The empirical false discovery rate of the genomic modeling
# ---------------------------------------------------------------------------

def efdr_paragraphs(has_results: bool, table: str | None = None) -> list[str]:
    """What the Methods say of the eFDR: that it was determined, and where the
    report gives the procedure and the rates (``table``: the label of the
    report's eFDR table, "D-1") — or that the report has no such analysis.
    ``has_results``: the report has eFDR results (genomics.efdr, efdr.json)."""
    if not has_results:
        return ["No empirical false discovery rate analysis of the genomic dose-response "
                "modeling is among the data integrated for this report."]
    where = (f"are reported with Table {table}" if table
             else "are reported with the results of that analysis")
    return ["The empirical false discovery rate of the genomic dose-response modeling was "
            "determined from synthetic null data that were analyzed in BMDExpress with the "
            f"parameters used for the study data. The procedure and the rates {where}."]


def build_efdr(ctx: MethodsContext, introduce: bool = True) -> list[str]:
    """The eFDR subsection for the study's own session.  A report composed of
    several studies holds the analysis itself; its render states it
    (rendering.genomics_appendix.attach_genomics_appendix)."""
    from genomics.efdr import load_efdr

    efdr = load_efdr(ctx.dtxsid or None)
    return efdr_paragraphs(bool(efdr and efdr.get("tissues")))
