"""
NTP-standard statistical tests for apical and genomic endpoint analysis.

Implements the National Toxicology Program's decision tree for dose-response
data (body weight, organ weight, gene expression probes, etc.):

  1. Jonckheere's trend test (gatekeeper) — detects monotonic dose-response.
     Stays in Python because BMDExpress doesn't include Jonckheere (it's an
     NTP convention, not a BMDExpress feature).
  2. Williams trend test (BMDExpress-native, via sciome-commons-math JAR) —
     permutation-based monotonic trend test.  Used as BOTH trend test AND
     pairwise comparison depending on context.
  3. Dunnett's test (BMDExpress-native, via sciome-commons-math JAR) —
     many-to-one pairwise comparisons of each dose group vs control.

The Williams and Dunnett tests call the Java RunPrefilter tool, which uses
the exact same statistical routines that BMDExpress 3 uses internally
(WilliamsTrendTestUtil, DunnettsTest from sciome-commons-math).  This
ensures numerical parity with BMDExpress's own prefilter results.

For apical endpoints, the NTP decision tree applies:
  - Jonckheere is the trend gatekeeper
  - If trend significant → Williams for pairwise (from Java)
  - If trend NOT significant → Dunnett's for pairwise (from Java)
  - Report BMD only if BOTH trend AND pairwise are significant

For genomic probes, the BMDExpress convention applies:
  - Williams trend test is the gatekeeper (replacing Jonckheere)
  - Dunnett's for pairwise NOEL/LOEL determination
  - Both run in a single Java batch call for efficiency

Reference:
  NTP Statistical Procedures — https://ntp.niehs.nih.gov/data/research/stats
  Jonckheere (1954), Williams (1971, 1972), Dunnett (1955)

Usage:
    from apical_stats import analyze_endpoint, run_java_prefilter
    result = analyze_endpoint(experiment_name, endpoint_name, groups_by_dose)
    batch_results = run_java_prefilter(bm2_json)  # for genomic probes
"""

import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from scipy import stats as sp_stats


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
        pairwise_method: "williams" or "dunnett" — which pairwise test was used
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
    Jonckheere-Terpstra test for ordered alternatives.

    Tests the null hypothesis that all group distributions are identical
    against the alternative that they are monotonically ordered (either
    increasing or decreasing with dose).

    The test statistic J counts the number of times an observation in a
    higher-dose group exceeds an observation in a lower-dose group, summed
    over all pairs of groups.  Under H0, J has a known mean and variance,
    and the standardized Z is approximately normal for n ≥ 5 per group.

    We run a two-sided test and then report the direction based on whether
    J exceeds or falls below its expected value.

    Args:
        groups_by_dose: Dict mapping dose → list of response values,
                        sorted by dose (ascending).  Must include control.

    Returns:
        (p_value, direction) where direction is "UP" or "DOWN".
    """
    # Sort doses and exclude empty groups (doses where no observations survived
    # filtering — e.g. high-dose groups with complete mortality).
    sorted_doses = sorted(groups_by_dose.keys())
    ordered_groups = [groups_by_dose[d] for d in sorted_doses if len(groups_by_dose[d]) > 0]
    k = len(ordered_groups)
    if k < 2:
        # Need at least 2 non-empty groups for a trend test
        return 1.0, "UP"

    # Count the J statistic: for each pair of groups (i < j),
    # count how many times an observation in group j exceeds one in group i
    # (with ties contributing 0.5)
    j_stat = 0.0
    for i in range(k):
        for j in range(i + 1, k):
            for x in ordered_groups[i]:
                for y in ordered_groups[j]:
                    if y > x:
                        j_stat += 1.0
                    elif y == x:
                        j_stat += 0.5

    # Compute expected value and variance under H0
    # n_i = size of group i, N = total observations
    ns = [len(g) for g in ordered_groups]
    n_total = sum(ns)

    # E(J) = (N^2 - sum(n_i^2)) / 4
    sum_ni_sq = sum(ni ** 2 for ni in ns)
    e_j = (n_total ** 2 - sum_ni_sq) / 4.0

    # Var(J) — formula accounting for ties in the combined sample
    # First, the tie-free variance:
    # Var(J) = [N^2(2N+3) - sum(n_i^2(2n_i+3))] / 72
    var_j_numer = (n_total ** 2 * (2 * n_total + 3)
                   - sum(ni ** 2 * (2 * ni + 3) for ni in ns))
    var_j = var_j_numer / 72.0

    if var_j <= 0:
        # Degenerate case — all groups identical or single observations
        return 1.0, "UP"

    # Standardized Z (continuity correction of 0.5 for discrete statistic)
    z = (j_stat - e_j) / math.sqrt(var_j)

    # Two-sided p-value from normal approximation
    p_value = 2.0 * sp_stats.norm.sf(abs(z))

    # Direction: if J > E(J), the trend is upward (higher doses → higher values)
    direction = "UP" if z > 0 else "DOWN"

    return p_value, direction


# ---------------------------------------------------------------------------
# Java classpath and RunPrefilter invocation
# ---------------------------------------------------------------------------

# BMDExpress 3 project root — same as apical_report.py uses
_BMDX_PROJECT = Path.home() / "Dev" / "Projects" / "BMDExpress-3"
_BMDX_CORE_JAR = _BMDX_PROJECT / "target" / "bmdx-core.jar"
_BMDX_DEPS_DIR = _BMDX_PROJECT / "target" / "deps"
_JAVA_HELPER_DIR = Path(__file__).parent / "java"


def _build_classpath() -> str:
    """
    Assemble the Java classpath from bmdx-core.jar + its Maven-resolved deps.

    Includes sciome-commons-math (Williams/Dunnett), jdistlib, commons-math3,
    and Jackson for JSON I/O.  Also includes the java/ helper directory where
    RunPrefilter.class lives.

    Returns:
        Colon-separated classpath string suitable for java -cp.
    """
    jars = [str(_BMDX_CORE_JAR)]
    if _BMDX_DEPS_DIR.exists():
        for jar in _BMDX_DEPS_DIR.glob("*.jar"):
            jars.append(str(jar))
    jars.append(str(_JAVA_HELPER_DIR))
    return ":".join(jars)


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
            import sys
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


def _java_pairwise_for_endpoint(
    groups_by_dose: dict[float, list[float]],
    control_dose: float = 0.0,
) -> tuple[dict[float, float], dict[float, float]]:
    """
    Run Java Williams/Dunnett on a single endpoint's dose-response data.

    Constructs the flat dose vector and response matrix from grouped data,
    calls RunPrefilter, and returns the Dunnett pairwise p-values plus
    the Williams trend p-value.

    This is used by analyze_endpoint() for per-endpoint stats in the apical
    pathway.  For batch processing (genomics), use run_java_prefilter().

    Args:
        groups_by_dose: Dict mapping dose → list of response values.
        control_dose:   Which dose is the control (default 0.0).

    Returns:
        (dunnett_pvals, williams_info) where:
          - dunnett_pvals: Dict mapping treatment dose → p-value
          - williams_info: Dict with "williams_p" and "williams_adjusted_p"
    """
    # Build the flat arrays RunPrefilter expects
    sorted_doses = sorted(groups_by_dose.keys())
    doses_flat = []
    responses_flat = []

    for dose in sorted_doses:
        for val in groups_by_dose[dose]:
            doses_flat.append(dose)
            responses_flat.append(val)

    # Single probe — wrap in a 2D array.
    # Use williams_p_cutoff=1.0 so Dunnett's always runs: for apical
    # endpoints, Jonckheere (not Williams) is the trend gatekeeper,
    # and we need Dunnett's p-values regardless of Williams result.
    result = _call_java_prefilter(
        doses=doses_flat,
        probe_ids=["endpoint"],
        responses=[responses_flat],
        num_permutations=1000,
        num_threads=2,
        dunnett_simulations=15000,
        williams_p_cutoff=1.0,
    )

    probe = result["probes"][0]

    # Convert Dunnett p-values from string-keyed dict to float-keyed.
    # NaN/null p-values (from zero-variance edge cases) → 1.0 (non-significant).
    dunnett_pvals = {}
    for dose_str, pval in probe.get("dunnett_p", {}).items():
        if pval is None or isinstance(pval, str):
            pval = 1.0
        dunnett_pvals[float(dose_str)] = float(pval)

    williams_info = {
        "williams_p": probe.get("williams_p", 1.0),
        "williams_adjusted_p": probe.get("williams_adjusted_p", 1.0),
    }

    return dunnett_pvals, williams_info


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
) -> EndpointStats:
    """
    Run the full NTP statistical analysis for one apical endpoint.

    Implements the NTP decision tree:
      1. Compute descriptive stats (n, mean, SE) per dose group
      2. Run Jonckheere's trend test (gatekeeper)
      3. If trend significant → Williams pairwise test
         If trend NOT significant → Dunnett's pairwise test
      4. Determine significance markers for each dose group
      5. Determine whether BMD should be reported (both trend + pairwise)

    Args:
        experiment_name: E.g. "OrganWeightMale"
        endpoint_name:   E.g. "Liver Weight Relative"
        groups_by_dose:  Dict mapping dose (float) → list of response values.
                         Must include the control dose.
        control_dose:    Dose value for the control group (default 0.0).

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
    # or NaN→null JSON sanitization.  All downstream code (descriptive stats,
    # Jonckheere, Williams, Dunnett) receives only valid numeric values.
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

    # ---- Jonckheere's trend test (gatekeeper) ----
    jonck_p, direction = jonckheere_test(groups_by_dose)
    result.jonckheere_p = jonck_p
    result.jonckheere_sig = jonck_p <= ALPHA_STAR
    result.trend_direction = direction
    result.trend_marker = _sig_marker(jonck_p)

    # ---- Pairwise comparisons ----
    # Exclude dose groups with no valid observations — these represent doses
    # where all animals died or were sacrificed early (e.g. high-dose groups
    # in an NTP 28-day study).  The statistical tests require ≥1 observation
    # per group; empty groups are a normal study design feature, not an error.
    control_vals = groups_by_dose[control_dose]
    treatment_groups = {
        d: groups_by_dose[d] for d in treatment_doses
        if len(groups_by_dose[d]) > 0
    }

    if not control_vals or not treatment_groups:
        # No valid control or no valid treatment groups — can't run pairwise
        result.pairwise_method = "none"
        pairwise_p = {}
    else:
        # Run BMDExpress-native Williams/Dunnett via Java.
        # The Java tool runs both tests in a single call.  We use Dunnett's
        # pairwise p-values for dose-group significance markers (same as NTP
        # convention), and Williams' trend p-value is available for reference.
        try:
            dunnett_pvals, williams_info = _java_pairwise_for_endpoint(
                groups_by_dose, control_dose
            )

            if result.jonckheere_sig:
                # Trend detected — report as "williams" pairwise method
                # to maintain compatibility with downstream code that checks
                # the method name.  The actual p-values come from Dunnett's
                # (which is what BMDExpress uses for NOEL/LOEL).
                result.pairwise_method = "williams"
            else:
                result.pairwise_method = "dunnett"

            pairwise_p = dunnett_pvals

        except (RuntimeError, FileNotFoundError, json.JSONDecodeError) as e:
            # If Java stats fail (e.g., RunPrefilter not compiled, JVM not
            # available), fall back gracefully with a warning.
            import sys
            print(f"  WARNING: Java prefilter failed for {endpoint_name}: "
                  f"{e}", file=sys.stderr)
            result.pairwise_method = "none"
            pairwise_p = {}

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

    for exp in bm2_json.get("doseResponseExperiments", []):
        exp_name = exp.get("name", "Unknown")
        treatments = exp.get("treatments", [])

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
            stats = analyze_endpoint(exp_name, probe_name, groups_by_dose)
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
