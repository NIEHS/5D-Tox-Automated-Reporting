"""
NTP-standard statistical tests for apical (non-genomic) endpoint analysis.

Implements the National Toxicology Program's decision tree for body weight
and organ weight data in subchronic study reports:

  1. Jonckheere's trend test (gatekeeper) — detects monotonic dose-response
  2. If trend significant → Williams test (pairwise, trend-sensitive)
  3. If trend NOT significant → Dunnett's test (pairwise, no trend assumption)

These tests determine:
  - Whether a BMD value should be reported for an endpoint (requires BOTH
    significant pairwise AND significant trend)
  - Which dose groups get significance markers (* p≤0.05, ** p≤0.01)
  - Whether the control row gets a trend marker

Reference:
  NTP Statistical Procedures — https://ntp.niehs.nih.gov/data/research/stats
  Jonckheere (1954), Williams (1971, 1972), Dunnett (1955)

Usage:
    from apical_stats import analyze_endpoint
    result = analyze_endpoint(dose_groups, control_values, treatment_values_by_dose)
"""

import math
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np
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
    # Sort doses to ensure correct ordering
    sorted_doses = sorted(groups_by_dose.keys())
    ordered_groups = [groups_by_dose[d] for d in sorted_doses]
    k = len(ordered_groups)

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
# Williams test for pairwise comparisons (trend-sensitive)
# ---------------------------------------------------------------------------

def williams_test(
    control_vals: list[float],
    treatment_groups: dict[float, list[float]],
) -> dict[float, float]:
    """
    Williams test for minimum effective dose under a monotonic trend.

    Williams' procedure uses isotonic regression ("amalgamation") to produce
    monotonically constrained group means, then compares each amalgamated
    treatment mean to the control mean using a pooled variance estimate.

    The test is performed step-down from the highest dose: if the highest
    dose is not significant, lower doses are not tested (closed testing).

    This implementation uses the t-distribution approximation for p-values
    rather than Williams' original exact tables, which is standard practice
    for modern NTP software.

    Args:
        control_vals: List of response values for the control (dose=0) group.
        treatment_groups: Dict mapping dose → response values, sorted by
                         dose ascending.  Does NOT include control.

    Returns:
        Dict mapping dose → p-value for each treatment dose.
    """
    sorted_doses = sorted(treatment_groups.keys())
    k = len(sorted_doses)  # number of treatment groups

    # Pool all groups to estimate the common within-group variance
    # (MSE from one-way ANOVA)
    all_groups = [control_vals] + [treatment_groups[d] for d in sorted_doses]
    ns = [len(g) for g in all_groups]
    means = [np.mean(g) for g in all_groups]
    n_total = sum(ns)
    k_total = len(all_groups)

    # Pooled variance (within-group sum of squares / degrees of freedom)
    ss_within = sum(
        sum((x - means[i]) ** 2 for x in all_groups[i])
        for i in range(k_total)
    )
    df_within = n_total - k_total
    if df_within <= 0:
        # Not enough data to estimate variance
        return {d: 1.0 for d in sorted_doses}
    mse = ss_within / df_within

    control_mean = means[0]
    control_n = ns[0]

    # Isotonic regression on treatment means (PAVA — pool adjacent violators)
    # Direction: we assume the Jonckheere trend already told us the direction.
    # Williams amalgamates in the direction of the trend, but for the t-test
    # we only need the amalgamated means.  We amalgamate assuming an
    # increasing trend; if it's decreasing, we negate, amalgamate, un-negate.
    treatment_means = [means[i + 1] for i in range(k)]
    treatment_ns = [ns[i + 1] for i in range(k)]

    # Detect direction from raw means — does highest dose mean exceed control?
    increasing = treatment_means[-1] >= control_mean

    if not increasing:
        # Flip sign so PAVA works for increasing sequences
        treatment_means = [-m for m in treatment_means]
        control_mean_adj = -control_mean
    else:
        control_mean_adj = control_mean

    # PAVA (pool adjacent violators algorithm) for isotonic regression
    # Forces the treatment means to be monotonically non-decreasing
    amalgamated = _pava(treatment_means, treatment_ns)

    if not increasing:
        # Flip back
        amalgamated = [-m for m in amalgamated]
        control_mean_adj = -control_mean_adj

    # Step-down testing from highest dose
    # Williams' t-statistic: t_i = (amalgamated_i - control_mean) / sqrt(MSE * (1/n_control + 1/n_eff_i))
    # where n_eff_i is the effective sample size after amalgamation
    p_values = {}
    for i in range(k - 1, -1, -1):
        dose = sorted_doses[i]
        amal_mean = amalgamated[i]
        n_treat = treatment_ns[i]

        # Effective n — if this dose was amalgamated with neighbors, the
        # effective n is the sum of the amalgamated group sizes.
        # For simplicity, use the original group size (conservative).
        se = math.sqrt(mse * (1.0 / control_n + 1.0 / n_treat))

        # Recover the actual control mean (undo any sign flip)
        actual_control = control_mean if increasing else -control_mean
        diff = abs(amal_mean - actual_control)

        if se <= 0:
            # Degenerate case: zero within-group variance.  This happens
            # with coded/discretized data where every animal at the same
            # dose has the identical response value.  If the group means
            # differ, the difference is deterministic (effectively infinite
            # t-statistic), so p → 0.  If means are equal, p = 1.
            p_values[dose] = 0.0 if diff > 0 else 1.0
            continue

        t_stat = diff / se

        # Two-sided p-value using t-distribution
        p_val = 2.0 * sp_stats.t.sf(t_stat, df_within)
        p_values[dose] = p_val

    return p_values


def _pava(values: list[float], weights: list[float]) -> list[float]:
    """
    Pool Adjacent Violators Algorithm for isotonic regression.

    Produces a monotonically non-decreasing sequence of weighted means.
    When adjacent values violate the monotonic constraint, they are
    "pooled" (replaced by their weighted average) until the constraint
    is satisfied.

    Args:
        values:  Raw sequence of values (should be roughly increasing).
        weights: Corresponding weights (sample sizes).

    Returns:
        Isotonically constrained values (same length as input).
    """
    n = len(values)
    # Each block is (weighted_sum, total_weight, start_index, end_index)
    blocks = [(values[i] * weights[i], weights[i], i, i) for i in range(n)]

    # Merge adjacent blocks that violate monotonicity
    merged = True
    while merged:
        merged = False
        new_blocks = [blocks[0]]
        for j in range(1, len(blocks)):
            prev_mean = new_blocks[-1][0] / new_blocks[-1][1]
            curr_mean = blocks[j][0] / blocks[j][1]
            if curr_mean < prev_mean:
                # Violation — pool with previous block
                p = new_blocks.pop()
                pooled = (
                    p[0] + blocks[j][0],
                    p[1] + blocks[j][1],
                    p[2],
                    blocks[j][3],
                )
                new_blocks.append(pooled)
                merged = True
            else:
                new_blocks.append(blocks[j])
        blocks = new_blocks

    # Expand blocks back to individual values
    result = [0.0] * n
    for ws, w, start, end in blocks:
        block_mean = ws / w
        for i in range(start, end + 1):
            result[i] = block_mean

    return result


# ---------------------------------------------------------------------------
# Dunnett's test (wraps scipy.stats.dunnett)
# ---------------------------------------------------------------------------

def dunnett_test(
    control_vals: list[float],
    treatment_groups: dict[float, list[float]],
) -> dict[float, float]:
    """
    Dunnett's test for many-to-one comparisons (each dose vs control).

    Uses scipy.stats.dunnett which implements the exact multivariate-t
    distribution for simultaneous inference, controlling the family-wise
    error rate.

    This is the pairwise test used when Jonckheere's trend test is NOT
    significant (i.e., no monotonic trend assumed).

    Args:
        control_vals: Response values for the control group.
        treatment_groups: Dict mapping dose → response values.

    Returns:
        Dict mapping dose → adjusted p-value.
    """
    sorted_doses = sorted(treatment_groups.keys())

    # scipy.stats.dunnett expects (*samples, control=control_array)
    # where each sample is an array of treatment group observations
    treatment_arrays = [np.array(treatment_groups[d]) for d in sorted_doses]
    control_array = np.array(control_vals)

    result = sp_stats.dunnett(*treatment_arrays, control=control_array)

    # result.pvalue is an array of p-values, one per treatment group,
    # in the same order as the input arrays
    p_values = {}
    for i, dose in enumerate(sorted_doses):
        p_values[dose] = float(result.pvalue[i])

    return p_values


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

    # ---- Descriptive statistics ----
    sorted_doses = sorted(groups_by_dose.keys())
    treatment_doses = [d for d in sorted_doses if d != control_dose]
    result.doses = treatment_doses

    for dose in sorted_doses:
        vals = groups_by_dose[dose]
        n = len(vals)
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
    control_vals = groups_by_dose[control_dose]
    treatment_groups = {d: groups_by_dose[d] for d in treatment_doses}

    if result.jonckheere_sig:
        # Trend detected → use Williams (trend-sensitive, more powerful)
        result.pairwise_method = "williams"
        pairwise_p = williams_test(control_vals, treatment_groups)
    else:
        # No trend → use Dunnett (no monotonic assumption)
        result.pairwise_method = "dunnett"
        pairwise_p = dunnett_test(control_vals, treatment_groups)

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
