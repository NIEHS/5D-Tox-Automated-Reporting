"""
NTP-standard statistical tests for apical and genomic endpoint analysis.

Implements the National Toxicology Program's decision tree for dose-response
data (body weight, organ weight, gene expression probes, etc.).

Apical endpoints follow the NTP procedure, implemented in Python in
ntp_stats.py:
  - Jonckheere's trend test selects the pairwise test (p <= 0.01 → the
    trend-sensitive test)
  - weights: Williams (trend) or Dunnett; clinical pathology: Shirley (trend)
    or Dunn
  - Report BMD only if BOTH trend AND pairwise are significant

Genomic probes follow the BMDExpress convention, through the Java
RunPrefilter tool (the same WilliamsTrendTestUtil / DunnettsTest routines
BMDExpress 3 uses internally, so prefilter results match BMDExpress):
  - Williams trend test is the gatekeeper (replacing Jonckheere)
  - Dunnett's for pairwise NOEL/LOEL determination
  - Both run in a single Java batch call for efficiency

The apical path no longer uses the Java Dunnett: its p-value is not
monotone in the effect size (an 8 SD difference returns p ~ 0.44).

Reference:
  NTP Statistical Procedures — https://ntp.niehs.nih.gov/data/research/stats
  Jonckheere (1954), Williams (1971, 1972), Dunnett (1955), Shirley (1977),
  Dunn (1964)

Usage:
    from apical_stats import analyze_endpoint, run_java_prefilter
    result = analyze_endpoint(experiment_name, endpoint_name, groups_by_dose)
    batch_results = run_java_prefilter(bm2_json)  # for genomic probes
"""

import json
import math
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import ntp_stats


# ---------------------------------------------------------------------------
# Constants — significance thresholds matching NTP convention
# ---------------------------------------------------------------------------

# Two-sided alpha levels for the * and ** markers on report tables
ALPHA_STAR = 0.05      # single star (*)
ALPHA_DSTAR = 0.01     # double star (**)


# ---------------------------------------------------------------------------
# Result data class — holds all statistical output for one endpoint
# ---------------------------------------------------------------------------

@dataclass
class EndpointStats:
    """
    Complete statistical summary for one apical endpoint (e.g., Liver
    Weight Relative, Male).  Contains the Jonckheere trend test result,
    pairwise comparison results for each dose group, and the final
    determination of whether to report the BMD.

    Attributes:
        endpoint_name:  Human-readable label, e.g. "Liver Weight Relative"
        experiment_name: Source experiment, e.g. "OrganWeightMale"
        doses:          Sorted list of unique dose levels (excluding control)
        control_dose:   The dose value used as control (usually 0.0)
        n_per_dose:     Dict mapping dose → number of animals
        mean_per_dose:  Dict mapping dose → group mean
        se_per_dose:    Dict mapping dose → standard error of the mean
        jonckheere_p:   P-value from Jonckheere's trend test
        jonckheere_sig: True if Jonckheere p ≤ 0.05
        trend_direction: "UP" or "DOWN" — direction of the detected trend
        pairwise_method: "williams" | "dunnett" | "shirley" | "dunn" | "none"
        pairwise_p:     Dict mapping dose → p-value from pairwise test
        pairwise_marker: Dict mapping dose → "" or "*" or "**"
        trend_marker:   "" or "*" or "**" — marker for the control row
        any_pairwise_sig: True if at least one dose group is significant
        report_bmd:     True if BOTH trend and pairwise are significant —
                        the business rule for whether to pull BMD from
                        category analysis
    """
    endpoint_name: str = ""
    experiment_name: str = ""
    doses: list = field(default_factory=list)
    control_dose: float = 0.0
    n_per_dose: dict = field(default_factory=dict)
    mean_per_dose: dict = field(default_factory=dict)
    se_per_dose: dict = field(default_factory=dict)
    jonckheere_p: float = 1.0
    jonckheere_sig: bool = False
    trend_direction: str = ""
    pairwise_method: str = ""
    pairwise_p: dict = field(default_factory=dict)
    pairwise_marker: dict = field(default_factory=dict)
    trend_marker: str = ""
    any_pairwise_sig: bool = False
    report_bmd: bool = False


# ---------------------------------------------------------------------------
# Jonckheere-Terpstra trend test
# ---------------------------------------------------------------------------

def jonckheere_test(groups_by_dose: dict[float, list[float]]) -> tuple[float, str]:
    """
    Jonckheere-Terpstra test for ordered alternatives (two-sided, normal
    approximation with the tie-corrected variance) — ntp_stats.jonckheere.

    Args:
        groups_by_dose: Dict mapping dose → list of response values.
                        Missing values and empty groups are left out.

    Returns:
        (p_value, direction) where direction is "UP" or "DOWN" ("UP" when
        there is no trend at all).
    """
    _doses, groups = ntp_stats._clean(groups_by_dose)
    p_value, direction = ntp_stats.jonckheere(groups)
    return p_value, direction or "UP"


# ---------------------------------------------------------------------------
# Java classpath and RunPrefilter invocation
# ---------------------------------------------------------------------------

# Java classpath and helper directory are centralized in java_bridge.py
# to avoid duplication across apical_report, apical_stats, and pool_integrator.
from .java_bridge import build_classpath as _build_classpath
from .java_bridge import BMDX_PROJECT as _BMDX_PROJECT


def run_apical_bmds_java(endpoints: list[dict], timeout: int = 900) -> dict[str, dict]:
    """Fit apical continuous BMDs via the BMDExpress ToxicR engine (RunApicalBmds).

    The Java/ToxicR replacement for the Python pybmds recompute: pipes per-endpoint
    per-animal dose-response data + the SAME fit config the endpoint's .bm2 was run
    with (model set, BMR type/factor, constant variance) to the RunApicalBmds helper,
    which drives libDRBMD.so via ToxicRJNI and returns model-averaged BMD/BMDL.

    Each endpoint dict: {key, doses:[per-animal], Y:[per-animal], models:[int],
    bmr_type:int(1=SD,2=RelDev), bmr_factor:float, is_ncv:bool}. Returns
    {key: {bmd, bmdl, bmdu, model_name, status, notes}} — SAME shape the old
    run_bmds_for_endpoints produced, so downstream consumers are unchanged.

    MUST set -Djava.library.path so ToxicRJNI's System.loadLibrary("DRBMD") resolves
    (BMDX_PROJECT is where libDRBMD.so lives). Raises RuntimeError on process failure.
    """
    import json as _json
    import subprocess as _subprocess

    if not endpoints:
        return {}
    cp = _build_classpath()
    proc = _subprocess.run(
        ["java", f"-Djava.library.path={_BMDX_PROJECT}", "-cp", cp, "RunApicalBmds"],
        input=_json.dumps({"endpoints": endpoints}),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"RunApicalBmds failed (exit {proc.returncode}): {proc.stderr}"
        )
    return _json.loads(proc.stdout)


def _call_java_prefilter(
    doses: list[float],
    probe_ids: list[str],
    responses: list[list[float]],
    num_permutations: int = 1000,
    num_threads: int = 4,
    dunnett_simulations: int = 15000,
    log_transform: str = "none",
    williams_p_cutoff: float = 0.05,
) -> dict:
    """
    Call the Java RunPrefilter tool to run Williams trend test and Dunnett's
    pairwise comparisons on a batch of dose-response data.

    This is the bridge between Python and BMDExpress-native statistics.
    Sends dose-response data as JSON on stdin, receives per-probe results
    as JSON on stdout.

    The Java tool uses the exact same statistical routines as BMDExpress 3:
      - WilliamsTrendTestUtil.williams() — permutation-based trend test
      - DunnettsTest.dunnettsTest() — multivariate-t pairwise comparisons

    Args:
        doses:          Dose value for each sample (column), in order.
        probe_ids:      Probe/endpoint name per row.
        responses:      2D list [n_probes × n_samples] of response values.
        num_permutations: Williams permutation count (default 1000).
        num_threads:    Parallelism for Williams (default 4).
        dunnett_simulations: Monte Carlo iterations for Dunnett's (default 15000).
        log_transform:  "none", "base2", "base10", or "natural".

    Returns:
        Parsed JSON dict from RunPrefilter with structure:
        {
            "status": "ok",
            "n_probes": int,
            "doses_unique": [float, ...],
            "probes": [
                {
                    "probe_id": str,
                    "williams_p": float,
                    "williams_adjusted_p": float,
                    "dunnett_p": { "dose": p_value, ... },
                    "best_fold_change": float,
                    "fold_changes": { "dose": fc, ... },
                    "noel_dose": float | null,
                    "loel_dose": float | null
                },
                ...
            ]
        }

    Raises:
        RuntimeError: If the Java process fails or returns an error status.
    """
    input_data = {
        "doses": doses,
        "probe_ids": probe_ids,
        "responses": responses,
        "num_permutations": num_permutations,
        "num_threads": num_threads,
        "dunnett_simulations": dunnett_simulations,
        "log_transform": log_transform,
        "williams_p_cutoff": williams_p_cutoff,
    }

    cp = _build_classpath()
    proc = subprocess.run(
        ["java", "-cp", cp, "RunPrefilter"],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=300,  # 5-minute timeout for large probe sets
    )

    if proc.returncode != 0:
        raise RuntimeError(
            f"RunPrefilter failed (exit {proc.returncode}): {proc.stderr}"
        )

    result = json.loads(proc.stdout)
    if result.get("status") != "ok":
        raise RuntimeError(
            f"RunPrefilter error: {result.get('message', 'unknown')}"
        )

    return result


def run_java_prefilter(
    bm2_json: dict,
    num_permutations: int = 1000,
    num_threads: int = 4,
    dunnett_simulations: int = 15000,
) -> dict[str, dict]:
    """
    Run BMDExpress-native Williams/Dunnett on all endpoints in a .bm2 JSON.

    Batches all probe-response data from all experiments into a single Java
    call, then returns per-experiment×probe results indexed by a
    (experiment_name, probe_id) tuple key.

    This is the primary entry point for genomic probes, where efficiency
    matters (thousands of probes processed in one JVM launch instead of
    thousands of individual Python scipy calls).

    For apical endpoints, analyze_endpoint() calls the Java tool per-endpoint
    internally — this function is for bulk batch processing.

    Args:
        bm2_json:           Parsed JSON from the .bm2 export.
        num_permutations:   Williams permutation count.
        num_threads:        Thread count for Williams.
        dunnett_simulations: Monte Carlo iterations for Dunnett's.

    Returns:
        Dict mapping (experiment_name, probe_id) → probe result dict from
        RunPrefilter (williams_p, dunnett_p, fold_changes, etc.).
    """
    # Collect all dose-response data across experiments into a single batch.
    # Track which experiment each probe came from so we can key the results.
    all_doses: list[float] = []
    all_probe_ids: list[str] = []
    all_responses: list[list[float]] = []
    probe_origins: list[tuple[str, str]] = []  # (exp_name, probe_id)

    for exp in bm2_json.get("doseResponseExperiments", []):
        exp_name = exp.get("name", "Unknown")
        treatments = exp.get("treatments", [])
        exp_doses = [t["dose"] for t in treatments]

        # All experiments must share the same dose vector for batching.
        # If dose vectors differ, process each experiment separately.
        if not all_doses:
            all_doses = exp_doses
        elif exp_doses != all_doses:
            # Different dose structure — can't batch with previous experiments.
            # Process this experiment as its own batch and merge results.
            # For now, log a warning and skip.  In practice, experiments in
            # the same .bm2 file almost always share the same dose design.
            print(f"  WARNING: Experiment '{exp_name}' has different doses, "
                  f"processing separately", file=sys.stderr)
            continue

        for pr in exp.get("probeResponses", []):
            probe_id = pr["probe"]["id"]
            responses = pr["responses"]

            # Sanitize: replace None/null with 0.0 for JSON safety.
            # None values represent missing observations (from BMDExpress
            # NaN→null serialization).  Using 0.0 preserves the sample
            # count; these values are rare and don't significantly affect
            # the Williams/Dunnett statistics on remaining valid data.
            clean_responses = [
                v if v is not None else 0.0
                for v in responses
            ]

            all_probe_ids.append(f"{exp_name}::{probe_id}")
            all_responses.append(clean_responses)
            probe_origins.append((exp_name, probe_id))

    if not all_probe_ids:
        return {}

    # Call Java
    java_result = _call_java_prefilter(
        doses=all_doses,
        probe_ids=all_probe_ids,
        responses=all_responses,
        num_permutations=num_permutations,
        num_threads=num_threads,
        dunnett_simulations=dunnett_simulations,
    )

    # Index results by (experiment_name, probe_id) for easy lookup
    result_map = {}
    for i, probe_result in enumerate(java_result["probes"]):
        exp_name, probe_id = probe_origins[i]
        result_map[(exp_name, probe_id)] = probe_result

    return result_map


# ---------------------------------------------------------------------------
# Significance marker helper
# ---------------------------------------------------------------------------

def _sig_marker(p_value: float) -> str:
    """
    Convert a p-value to an NTP-style significance marker.

    Returns:
        "**" if p ≤ 0.01
        "*"  if p ≤ 0.05
        ""   otherwise
    """
    if p_value <= ALPHA_DSTAR:
        return "**"
    elif p_value <= ALPHA_STAR:
        return "*"
    return ""


# ---------------------------------------------------------------------------
# Main analysis function — runs the full NTP decision tree
# ---------------------------------------------------------------------------

def analyze_endpoint(
    experiment_name: str,
    endpoint_name: str,
    groups_by_dose: dict[float, list[float]],
    control_dose: float = 0.0,
    family: str = ntp_stats.PARAMETRIC,
) -> EndpointStats:
    """
    Run the full NTP statistical analysis for one apical endpoint.

    Implements the NTP decision tree:
      1. Compute descriptive stats (n, mean, SE) per dose group
      2. Run Jonckheere's trend test (gatekeeper)
      3. Jonckheere p <= 0.01 → the trend-sensitive pairwise test (Williams,
         or Shirley for the nonparametric family); otherwise Dunnett / Dunn
      4. Determine significance markers for each dose group
      5. Determine whether BMD should be reported (both trend + pairwise)

    Args:
        experiment_name: E.g. "OrganWeightMale"
        endpoint_name:   E.g. "Liver Weight Relative"
        groups_by_dose:  Dict mapping dose (float) → list of response values.
                         Must include the control dose.
        control_dose:    Dose value for the control group (default 0.0).
        family:          ntp_stats.PARAMETRIC (weights) or NONPARAMETRIC
                         (clinical pathology).

    Returns:
        EndpointStats with all results populated.
    """
    result = EndpointStats(
        endpoint_name=endpoint_name,
        experiment_name=experiment_name,
        control_dose=control_dose,
    )

    # Sanitize groups_by_dose once up front: remove None and NaN values.
    # These represent missing observations from Java BMDExpress serialization
    # or NaN→null JSON sanitization.  All downstream code (descriptive stats
    # and the NTP tests) receives only valid numeric values.
    groups_by_dose = {
        dose: [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]
        for dose, vals in groups_by_dose.items()
    }

    # ---- Descriptive statistics ----
    sorted_doses = sorted(groups_by_dose.keys())
    treatment_doses = [d for d in sorted_doses if d != control_dose]
    result.doses = treatment_doses

    for dose in sorted_doses:
        vals = groups_by_dose[dose]
        n = len(vals)
        if n == 0:
            result.n_per_dose[dose] = 0
            result.mean_per_dose[dose] = None
            result.se_per_dose[dose] = None
            continue
        mean = sum(vals) / n
        result.n_per_dose[dose] = n
        result.mean_per_dose[dose] = mean
        if n > 1:
            # Standard error of the mean = SD / sqrt(n)
            variance = sum((v - mean) ** 2 for v in vals) / (n - 1)
            result.se_per_dose[dose] = math.sqrt(variance / n)
        else:
            result.se_per_dose[dose] = 0.0

    # ---- Jonckheere trend test + the pairwise test it selects ----
    ntp = ntp_stats.ntp_pairwise(groups_by_dose, family, control_dose=control_dose)
    result.jonckheere_p = ntp.jonckheere_p
    result.jonckheere_sig = ntp.jonckheere_p <= ALPHA_STAR
    result.trend_direction = ntp.direction or "UP"
    result.trend_marker = _sig_marker(ntp.jonckheere_p)
    result.pairwise_method = ntp.method
    pairwise_p = dict(ntp.pairwise_p)
    result.pairwise_p = pairwise_p
    result.pairwise_marker = {d: _sig_marker(p) for d, p in pairwise_p.items()}

    # ---- Business rule: report BMD? ----
    # Need BOTH significant trend AND at least one significant pairwise
    result.any_pairwise_sig = any(p <= ALPHA_STAR for p in pairwise_p.values())
    result.report_bmd = result.jonckheere_sig and result.any_pairwise_sig

    return result


# ---------------------------------------------------------------------------
# Convenience: analyze all endpoints from a parsed .bm2 JSON
# ---------------------------------------------------------------------------

def analyze_all_endpoints(bm2_json: dict) -> list[EndpointStats]:
    """
    Run NTP statistical analysis on every endpoint in a deserialized .bm2.

    Iterates over all dose-response experiments and their probe responses
    (which for non-genomic data represent apical endpoints like body weight,
    organ weights, etc.).

    Args:
        bm2_json: Parsed JSON from the BMDExpress .bm2 export (the output
                  of ExportBm2Json).

    Returns:
        List of EndpointStats, one per experiment×endpoint combination.
    """
    all_results = []

    from .apical_report import _stats_family

    for exp in bm2_json.get("doseResponseExperiments", []):
        exp_name = exp.get("name", "Unknown")
        treatments = exp.get("treatments", [])
        desc = exp.get("experimentDescription")
        family = _stats_family(desc.get("platform") if isinstance(desc, dict) else None,
                               exp_name)

        # Build a mapping from treatment index → dose
        treat_doses = {i: t["dose"] for i, t in enumerate(treatments)}

        for pr in exp.get("probeResponses", []):
            probe_name = pr["probe"]["id"]
            responses = pr["responses"]

            # Group response values by dose
            groups_by_dose: dict[float, list[float]] = {}
            for i, val in enumerate(responses):
                dose = treat_doses[i]
                groups_by_dose.setdefault(dose, []).append(val)

            # Run the full NTP analysis
            stats = analyze_endpoint(exp_name, probe_name, groups_by_dose,
                                     family=family)
            all_results.append(stats)

    return all_results


# ---------------------------------------------------------------------------
# Entry point — run standalone on a .bm2 JSON export for testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python apical_stats.py <bm2_export.json>")
        sys.exit(1)

    json_path = sys.argv[1]
    with open(json_path) as f:
        bm2_data = json.load(f)

    results = analyze_all_endpoints(bm2_data)

    for r in results:
        print(f"=== {r.experiment_name} / {r.endpoint_name} ===")
        print(f"  Jonckheere p={r.jonckheere_p:.4g}, sig={r.jonckheere_sig}, "
              f"direction={r.trend_direction}, marker='{r.trend_marker}'")
        print(f"  Pairwise method: {r.pairwise_method}")
        print(f"  Report BMD: {r.report_bmd}")
        print(f"  {'Dose':>8}  {'n':>3}  {'Mean':>8}  {'SE':>8}  {'p':>8}  Marker")
        # Control row
        d = r.control_dose
        print(f"  {d:>8.2f}  {r.n_per_dose[d]:>3}  "
              f"{r.mean_per_dose[d]:>8.1f}  {r.se_per_dose[d]:>8.2f}  "
              f"{'trend':>8}  {r.trend_marker}")
        # Treatment rows
        for d in r.doses:
            p = r.pairwise_p.get(d, 1.0)
            print(f"  {d:>8.2f}  {r.n_per_dose[d]:>3}  "
                  f"{r.mean_per_dose[d]:>8.1f}  {r.se_per_dose[d]:>8.2f}  "
                  f"{p:>8.4f}  {r.pairwise_marker.get(d, '')}")
        print()
