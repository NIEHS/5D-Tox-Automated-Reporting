"""The transcriptomic BMD Methods guideline states the workflow the .bm2
records — BMDExpress 2.x best-model selection vs BMDExpress 3 ToxicR model
averaging — rather than assuming the current era."""

from narrative.methods_extract import _collect_bm2_analysis_metadata
from narrative.methods_models import MethodsContext
from narrative.methods_prompt import _genomic_workflow_phrase


def _ctx(project: dict) -> MethodsContext:
    ctx = MethodsContext()
    for k, v in _collect_bm2_analysis_metadata(project).items():
        if hasattr(ctx, k):
            setattr(ctx, k, v)
    return ctx


def _project(bmd_notes, williams_notes, curve_fit=False, responses=((1.0, 2.0),)):
    return {
        "williamsTrendResults": [{"analysisInfo": {"notes": williams_notes}}],
        "curveFitPrefilterResults": [{"analysisInfo": {"notes": ["Curve Fit Prefilter"]}}] if curve_fit else [],
        "bMDResult": [{"analysisInfo": {"notes": bmd_notes}}],
        "doseResponseExperiments": [{"chip": {"name": "S1500+"},
                                     "probeResponses": [{"responses": list(r)} for r in responses]}],
    }


def test_bmdexpress_2_project_reads_best_model_selection():
    ctx = _ctx(_project(
        ["BMDExpress2 Version: BMDExpress 2.30.0507 BETA", "Models fit: hill, power",
         "Constant Variance: 1", "BMR Type: Standard Deviation", "BMR Factor: 1.0",
         "Best Model Selection: Lowest AIC"],
        ["Unadjusted P-Value Cutoff: 0.05", "Used Fold Filter with cuttoff: 1.5"],
        responses=((0.0, 2.0), (1.0, 3.0))))
    assert ctx.bmdexpress_version == "BMDExpress 2.30.0507 BETA"
    phrase = _genomic_workflow_phrase(ctx)
    assert "Lowest AIC" in phrase and "1.5-fold" in phrase
    assert "ToxicR" not in phrase and "Curve Fit" not in phrase
    assert "zero count" not in phrase          # the data still has zero responses


def test_bmdexpress_3_project_reads_model_averaging():
    ctx = _ctx(_project(
        ["BMDExpress3 Version: BMDExpress 3.20.0119 BETA", "Models fit: hill, power",
         "Model Averaging Method: Laplace Model Averaging", "Constant Variance: 1",
         "BMR Type: Relative Deviation", "BMR Factor: 0.25"],
        ["Unadjusted P-Value Cutoff: 0.05"], curve_fit=True))
    phrase = _genomic_workflow_phrase(ctx)
    assert "Laplace Model Averaging (ToxicR)" in phrase
    assert "Curve Fit Prefilter" in phrase and "25% relative deviation" in phrase
    assert phrase.startswith("probes with a zero count")
