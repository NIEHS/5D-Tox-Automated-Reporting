"""
apical_bmds.py — BMDS-based benchmark dose modeling for apical endpoints.

Runs pybmds (EPA BMDS) continuous models on apical endpoint dose-response data
to produce BMD, BMDL, BMDU, model name, and NIEHS classification bins.  This
matches the reference NIEHS report methodology (BMDS 2.7.0 via pybmds) and
provides a second BMD summary alongside the BMDExpress 3-native results.

Why two BMD summaries?
  BMDExpress 3 runs its own internal BMD pipeline (Hill, Power, Linear, Poly 2,
  Exp M2-M5) with its own model selection logic.  The NIEHS reference reports
  used BMDS 2.7.0 via pybmds which has a richer model set (Linear, Poly 2-8,
  Power, Hill, Exp M2-M5) and the EPA-recommended model selection algorithm.
  Running both lets users compare and understand differences.

Inputs:
  - Dose-response summary statistics: doses, sample sizes, means, and standard
    deviations per dose group for each endpoint.  These come from the same data
    that build_table_data() processes.

Outputs:
  - Per-endpoint dict with BMD, BMDL, BMDU, model name, NIEHS classification
    bin (viable / NVM / NR / UREP / failure), and recommender notes.

Integration:
  Called from pool_orchestrator.py's api_process_integrated() endpoint.
  Results returned as "apical_bmd_summary_bmds" in the JSON response.

Performance:
  Each endpoint takes ~1.2s to model (fitting ~12 continuous models with
  numerical optimization).  With 106 apical endpoints, serial execution takes
  ~128s.  Using ProcessPoolExecutor with 8 workers brings this down to ~16s.
  ThreadPoolExecutor won't help because pybmds is CPU-bound (numpy/scipy
  optimization) and Python's GIL blocks true thread parallelism.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
import logging
import math
import os
from concurrent.futures import ProcessPoolExecutor

import pybmds
from pybmds.recommender.recommender import RecommenderResults

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# LogicBin enum values from pybmds recommender:
#   0 = NO_CHANGE  → viable (no warnings, no failures)
#   1 = WARNING    → model passed but with warnings (maps to UREP in NIEHS bins)
#   2 = FAILURE    → model did not meet acceptability criteria (maps to NVM)
_BIN_VIABLE = 0
_BIN_WARNING = 1
_BIN_FAILURE = 2

# NIEHS NR (not reportable) threshold: BMD < 1/3 of the lowest nonzero dose.
# This avoids extrapolation artifacts where the BMD curve dips below the
# tested dose range, producing unreliable estimates.
_NR_FRACTION = 1.0 / 3.0


# ---------------------------------------------------------------------------
# Core modeling function
# ---------------------------------------------------------------------------

def run_bmds_session(
    doses: list[float],
    ns: list[int],
    means: list[float],
    stdevs: list[float],
) -> dict:
    """
    Run a full pybmds continuous modeling session on one endpoint.

    Fits all default continuous models (Linear, Polynomial 2-N, Power, Hill,
    Exponential M3, M5) with a 1 SD BMR relative to control — matching the
    NIEHS reference report methodology.  Uses the EPA-recommended model
    selection algorithm (lowest AIC among viable models, with BMDL fallback
    when BMDL range > 3-fold).

    Args:
        doses:  List of dose levels (must include 0 as control).
        ns:     Sample size per dose group.
        means:  Group means per dose group.
        stdevs: Group standard deviations per dose group.

    Returns:
        Dict with keys:
          bmd:        float or None — benchmark dose estimate
          bmdl:       float or None — lower confidence limit
          bmdu:       float or None — upper confidence limit
          model_name: str or None — name of the selected model (e.g., "Hill")
          status:     str — NIEHS classification: "viable", "NVM", "NR",
                      "UREP", or "failure"
          bin:        int — raw pybmds bin (0=viable, 1=warning, 2=failure)
          notes:      str — recommender notes (human-readable warnings)
    """
    # Validate inputs — pybmds will crash on bad data.
    # Need at least 3 dose groups (control + 2 treatment) and matching lengths.
    if len(doses) < 3 or len(doses) != len(ns) != len(means) != len(stdevs):
        return _failure_result("Insufficient dose groups or mismatched lengths")

    # Skip endpoints with zero variance everywhere — no dose-response to model
    if all(s == 0 for s in stdevs):
        return _failure_result("Zero variance across all dose groups")

    # Replace zero stdevs with a small fraction of the mean range to avoid
    # numerical singularities in the optimizer.  This can happen when a dose
    # group has n=1 or all animals have the exact same value.
    mean_range = max(means) - min(means) if means else 1.0
    epsilon = max(mean_range * 0.001, 1e-10)
    safe_stdevs = [s if s > 0 else epsilon for s in stdevs]

    try:
        # Create the continuous dataset (summary-level data: means ± SD)
        ds = pybmds.ContinuousDataset(
            doses=doses,
            ns=ns,
            means=means,
            stdevs=safe_stdevs,
        )

        # Create session and add all default continuous models.
        # pybmds adds: Linear, Poly 2-N (up to n_doses-1), Power, Hill,
        # Exponential M3, Exponential M5.  BMR defaults to 1 SD relative
        # to control, which matches the NIEHS reference.
        sess = pybmds.Session(dataset=ds)
        sess.add_default_models()

        # Execute all models and run the EPA recommender
        sess.execute()
        sess.recommend()

        # Extract recommender results
        rec_res: RecommenderResults = sess.recommender.results
        rec_idx = rec_res.recommended_model_index
        bins = rec_res.bmds_model_bin

        if rec_idx is not None:
            # A model was recommended — extract its results
            model = sess.models[rec_idx]
            r = model.results
            model_bin = bins[rec_idx].value  # LogicBin enum → int

            # Classify using NIEHS bins
            bmd_val = r.bmd
            bmdl_val = r.bmdl
            bmdu_val = r.bmdu

            # Check for NaN/Inf from the optimizer
            if (bmd_val is None or math.isnan(bmd_val) or math.isinf(bmd_val)):
                return _failure_result("BMD is NaN or Inf")

            # Determine the lowest nonzero dose for NR classification
            nonzero_doses = [d for d in doses if d > 0]
            lnzd = min(nonzero_doses) if nonzero_doses else 0

            # NIEHS classification logic:
            #   1. bin=2 (FAILURE) → NVM
            #   2. bin=1 (WARNING) → UREP (model passed but has warnings)
            #   3. BMD < LNZD/3   → NR (below extrapolation limit)
            #   4. BMDU/BMDL > 40 → UREP (unreliable confidence interval)
            #   5. Otherwise       → viable
            if model_bin == _BIN_FAILURE:
                status = "NVM"
            elif model_bin == _BIN_WARNING:
                status = "UREP"
            elif lnzd > 0 and bmd_val < lnzd * _NR_FRACTION:
                status = "NR"
            elif (bmdl_val and bmdu_val and bmdl_val > 0
                  and bmdu_val / bmdl_val > 40):
                status = "UREP"
            else:
                status = "viable"

            # Build notes string from the recommender
            notes_dict = rec_res.bmds_model_notes[rec_idx]
            warning_notes = notes_dict.get(
                # LogicBin.WARNING = 1
                list(notes_dict.keys())[1] if len(notes_dict) > 1 else None,
                [],
            )
            notes_str = "; ".join(warning_notes) if warning_notes else ""

            return {
                "bmd": round(bmd_val, 3),
                "bmdl": round(bmdl_val, 3) if bmdl_val else None,
                "bmdu": round(bmdu_val, 3) if bmdu_val else None,
                "model_name": model.name(),
                "status": status,
                "bin": model_bin,
                "notes": notes_str,
            }
        else:
            # No model recommended — check if ANY model had a viable bin.
            # If all models are in bin 2 (failure), it's NVM.
            # If some are in bin 1 (warning), the best is UREP.
            bin_values = [b.value for b in bins]
            if any(b == _BIN_WARNING for b in bin_values):
                # Find the warning-bin model with the lowest AIC
                warning_models = [
                    (i, sess.models[i])
                    for i in range(len(sess.models))
                    if bin_values[i] == _BIN_WARNING
                ]
                best_i, best_m = min(
                    warning_models,
                    key=lambda x: x[1].results.bmdl
                    if x[1].results.bmdl else float("inf"),
                )
                r = best_m.results
                return {
                    "bmd": round(r.bmd, 3) if r.bmd else None,
                    "bmdl": round(r.bmdl, 3) if r.bmdl else None,
                    "bmdu": round(r.bmdu, 3) if r.bmdu else None,
                    "model_name": best_m.name(),
                    "status": "UREP",
                    "bin": _BIN_WARNING,
                    "notes": "No viable model; best warning-bin model selected",
                }
            else:
                return _failure_result("No viable or warning-bin model found")

    except Exception as e:
        logger.warning("pybmds session failed: %s", e)
        return _failure_result(f"pybmds error: {e}")


def _failure_result(reason: str) -> dict:
    """
    Return a standardized failure/NVM result dict.

    Used when no model could be fit, inputs are invalid, or pybmds
    raises an exception.
    """
    return {
        "bmd": None,
        "bmdl": None,
        "bmdu": None,
        "model_name": None,
        "status": "NVM",
        "bin": _BIN_FAILURE,
        "notes": reason,
    }


# ---------------------------------------------------------------------------
# Batch endpoint modeling
# ---------------------------------------------------------------------------

def _run_single_endpoint(ep: dict) -> tuple[str, dict]:
    """
    Run BMDS modeling on a single endpoint.  Top-level function so it can be
    pickled by ProcessPoolExecutor (lambdas and closures can't be pickled).

    Args:
        ep: Dict with key, doses, ns, means, stdevs.

    Returns:
        Tuple of (key, result_dict) for collection into the results map.
    """
    key = ep["key"]
    result = run_bmds_session(
        doses=ep["doses"],
        ns=ep["ns"],
        means=ep["means"],
        stdevs=ep["stdevs"],
    )
    return key, result


# Default number of parallel workers for BMDS modeling.  Each worker fits
# ~12 models per endpoint using scipy optimization — fully CPU-bound.
# os.cpu_count() returns logical cores; cap at 8 to leave headroom for
# the web server and other concurrent tasks.
_BMDS_MAX_WORKERS = min(os.cpu_count() or 4, 8)


def run_bmds_for_endpoints(endpoint_data: list[dict]) -> dict[str, dict]:
    """
    Run BMDS modeling on a batch of apical endpoints in parallel.

    Takes the dose-response summary statistics that build_table_data()
    computes (means, SEs, Ns per dose group) and runs a pybmds session
    for each endpoint.  Uses ProcessPoolExecutor to parallelize across
    CPU cores — each endpoint is independent (no shared state).

    Args:
        endpoint_data: List of dicts, each containing:
          - key:    str — unique identifier (e.g., "Male::Total Thyroxine")
          - doses:  list[float] — sorted dose levels
          - ns:     list[int] — sample sizes per dose
          - means:  list[float] — group means per dose
          - stdevs: list[float] — group standard deviations per dose

    Returns:
        Dict mapping key → run_bmds_session() result dict.
    """
    if not endpoint_data:
        return {}

    n_workers = min(_BMDS_MAX_WORKERS, len(endpoint_data))
    logger.info(
        "BMDS modeling %d endpoints with %d workers", len(endpoint_data), n_workers,
    )

    results = {}
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        for key, result in pool.map(_run_single_endpoint, endpoint_data):
            results[key] = result
            if result["status"] == "viable":
                logger.info(
                    "BMDS %s: %s BMD=%.3f BMDL=%.3f (%s)",
                    key, result["status"], result["bmd"],
                    result["bmdl"], result["model_name"],
                )
            else:
                logger.info(
                    "BMDS %s: %s — %s", key, result["status"], result["notes"],
                )

    return results
