"""
NTP pairwise and trend statistics for continuous apical endpoints, in Python.

The NTP/NIEHS procedure (stated in every 5-day report's Materials and Methods,
e.g. NIEHS-10 and NIEHS-13):

  * Organ and body weights (approximately normal) use the parametric
    multiple-comparison procedures of Williams (1971, 1972) and Dunnett (1955).
  * Clinical pathology (typically skewed) uses the nonparametric procedures of
    Shirley (1977, with the Williams 1986 modification) and Dunn (1964).
  * The Jonckheere (1954) test assesses the dose-response trend and selects the
    pairwise test: the trend-sensitive test (Williams / Shirley) when Jonckheere
    is significant at p <= 0.01, otherwise Dunnett / Dunn.
  * The control column's marker is the trend test; a dose column's marker is
    its pairwise test.  * = p <= 0.05, ** = p <= 0.01.

This replaces the earlier pairing of a Python Jonckheere with the Java
sciome-commons-math DunnettsTest for every endpoint: that Dunnett p-value is
not monotone in the effect size (an 8 SD difference returns p ~ 0.44), and
the Williams / Shirley / Dunn branches did not exist.

Williams' and Shirley's critical values depend on the group sizes and degrees
of freedom.  Instead of the published tables (which cover equal treatment
replication and interpolate otherwise) they are computed by simulating the
null distribution of the statistic for the exact design, with a seed derived
from the design so results are reproducible run to run.

Pure functions over ``{dose: [values]}``; no I/O, no Java.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from scipy import stats as sp_stats

ALPHA_STAR = 0.05
ALPHA_DSTAR = 0.01

# Jonckheere p at or below which the trend-sensitive pairwise test is used.
TREND_TEST_SELECT_P = 0.01

PARAMETRIC = "parametric"        # Williams / Dunnett
NONPARAMETRIC = "nonparametric"  # Shirley / Dunn

# Test family per apical platform (experimentDescription.platform).  Weights
# are approximately normal; clinical pathology is typically skewed.
PLATFORM_FAMILY = {
    "Body Weight": PARAMETRIC,
    "Organ Weight": PARAMETRIC,
    "Clinical Chemistry": NONPARAMETRIC,
    "Hematology": NONPARAMETRIC,
    "Hormones": NONPARAMETRIC,
    "Urinalysis": NONPARAMETRIC,
}

# A treatment group needs at least this many animals to enter the tests.  A
# lone survivor (e.g. NIEHS-07 male, 1000 mg/kg, N = 1) is shown in the table
# but left out of the trend and pairwise tests: NTP's published markers
# reproduce only without it (788/790 cells vs 760/790 with it).
MIN_GROUP_N = 2

# Null-distribution draws for the Williams / Shirley critical values.
_N_SIM = 200_000

# The step-down tests are one-sided in the Jonckheere direction; NTP reports
# them on the two-sided scale (the one-sided p doubled).
_TREND_TEST_SIDES = 2


@dataclass
class PairwiseResult:
    """The NTP statistics for one endpoint.

    pairwise_p holds, per treatment dose, the p-value of the test actually
    used.  For the step-down trend-sensitive tests a dose not reached by the
    step-down (a higher dose was not significant) gets p = 1.0."""
    jonckheere_p: float = 1.0
    direction: str = ""                    # "UP" / "DOWN" from Jonckheere
    method: str = "none"                   # williams | dunnett | shirley | dunn | none
    pairwise_p: dict = field(default_factory=dict)


def family_for_platform(platform: str | None) -> str | None:
    """The test family for an apical platform, or None when the platform is
    not one the NTP procedure names (the caller decides and says so)."""
    return PLATFORM_FAMILY.get((platform or "").strip())


def sig_marker(p: float | None) -> str:
    if p is None or not math.isfinite(p):
        return ""
    return "**" if p <= ALPHA_DSTAR else "*" if p <= ALPHA_STAR else ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(groups_by_dose: dict) -> tuple[list[float], list[np.ndarray]]:
    """Sorted doses and finite-value arrays, dropping empty groups and
    treatment groups smaller than MIN_GROUP_N (the first, control, group is
    kept with any non-zero size)."""
    doses, arrays = [], []
    for d in sorted(groups_by_dose):
        a = np.asarray([v for v in groups_by_dose[d]
                        if v is not None and isinstance(v, (int, float)) and math.isfinite(v)],
                       dtype=float)
        if a.size >= (1 if not doses else MIN_GROUP_N):
            doses.append(float(d))
            arrays.append(a)
    return doses, arrays


def _midranks(values: np.ndarray) -> tuple[np.ndarray, float]:
    """Midranks of the pooled values and the tie term sum(t^3 - t)."""
    ranks = sp_stats.rankdata(values)
    _, counts = np.unique(values, return_counts=True)
    return ranks, float(np.sum(counts.astype(float) ** 3 - counts))


# ---------------------------------------------------------------------------
# Jonckheere-Terpstra trend test (tie-corrected normal approximation)
# ---------------------------------------------------------------------------

def jonckheere(groups: list[np.ndarray]) -> tuple[float, str]:
    """Two-sided p-value and direction ("UP"/"DOWN") of the Jonckheere-Terpstra
    test over groups ordered by dose, with the Hollander-Wolfe tie correction
    to the variance."""
    k = len(groups)
    if k < 2:
        return 1.0, ""
    j_stat = 0.0
    for i in range(k):
        for j in range(i + 1, k):
            diff = groups[j][None, :] - groups[i][:, None]
            j_stat += float(np.sum(diff > 0) + 0.5 * np.sum(diff == 0))
    ns = np.array([len(g) for g in groups], dtype=float)
    n = ns.sum()
    mean = (n * n - np.sum(ns ** 2)) / 4.0
    _, t = np.unique(np.concatenate(groups), return_counts=True)
    t = t.astype(float)
    var = (n * (n - 1) * (2 * n + 5)
           - np.sum(ns * (ns - 1) * (2 * ns + 5))
           - np.sum(t * (t - 1) * (2 * t + 5))) / 72.0
    if n > 2:
        var += (np.sum(ns * (ns - 1) * (ns - 2)) * np.sum(t * (t - 1) * (t - 2))
                / (36.0 * n * (n - 1) * (n - 2)))
    var += np.sum(ns * (ns - 1)) * np.sum(t * (t - 1)) / (8.0 * n * (n - 1))
    if var <= 0:
        return 1.0, ""
    z = (j_stat - mean) / math.sqrt(var)
    if z == 0:
        return 1.0, ""
    return float(2.0 * sp_stats.norm.sf(abs(z))), ("UP" if z > 0 else "DOWN")


# ---------------------------------------------------------------------------
# Williams-type null distributions (shared by Williams and Shirley)
# ---------------------------------------------------------------------------

def _seed(*key) -> int:
    return int.from_bytes(hashlib.sha256(repr(key).encode()).digest()[:8], "little")


@lru_cache(maxsize=256)
def _williams_null(ns: tuple[int, ...], df: float) -> np.ndarray:
    """Null draws of the step statistic for the TOP group of the design `ns`
    (control first): max_u A(u..i) - X0, scaled by s * sqrt(1/n_i + 1/n_0).

    df = inf gives the known-variance form used by Shirley's test."""
    rng = np.random.default_rng(_seed("williams", ns, df))
    n = np.asarray(ns, dtype=float)
    means = rng.standard_normal((_N_SIM, len(ns))) / np.sqrt(n)
    s = 1.0 if math.isinf(df) else np.sqrt(rng.chisquare(df, _N_SIM) / df)
    return _williams_stat(means, n) / (s * math.sqrt(1 / n[-1] + 1 / n[0]))


def _williams_stat(means: np.ndarray, n: np.ndarray) -> np.ndarray:
    """max over u in 1..i of the n-weighted mean of groups u..i, minus the
    control mean (column 0).  Vectorised over rows."""
    w = means[:, 1:] * n[1:]
    best = None
    for u in range(w.shape[1]):
        avg = w[:, u:].sum(axis=1) / n[1 + u:].sum()
        best = avg if best is None else np.maximum(best, avg)
    return best - means[:, 0]


def _null_p(observed: float, ns: tuple[int, ...], df: float) -> float:
    null = _williams_null(ns, float(df))
    return float((np.count_nonzero(null >= observed) + 1) / (null.size + 1))


# ---------------------------------------------------------------------------
# Williams (parametric, step-down)
# ---------------------------------------------------------------------------

def williams(groups: list[np.ndarray], direction: str) -> dict[int, float]:
    """Williams' step-down test of each treatment group (index >= 1) against
    the control (index 0), in the trend `direction`.

    At step i the isotonic estimate of the top group is computed from groups
    1..i only (the higher groups having been dropped), and compared with the
    control mean using the pooled within-group variance of all groups.  The
    p-value is one-sided in the trend direction, doubled (two-sided
    convention).  Steps stop at the first non-significant dose; doses below it
    get p = 1."""
    sign = -1.0 if direction == "DOWN" else 1.0
    gs = [sign * g for g in groups]
    n = np.array([len(g) for g in gs], dtype=float)
    df = n.sum() - len(gs)
    if df <= 0:
        return {i: 1.0 for i in range(1, len(gs))}
    s2 = sum(float(np.sum((g - g.mean()) ** 2)) for g in gs) / df
    means = np.array([g.mean() for g in gs])
    out = {i: 1.0 for i in range(1, len(gs))}
    for i in range(len(gs) - 1, 0, -1):
        stat = _williams_stat(means[None, : i + 1], n[: i + 1])[0]
        if s2 <= 0:
            p = 0.0 if stat > 0 else 1.0
        else:
            t = stat / math.sqrt(s2 * (1 / n[i] + 1 / n[0]))
            p = min(1.0, _TREND_TEST_SIDES * _null_p(t, tuple(int(x) for x in n[: i + 1]), df))
        out[i] = p
        if p > ALPHA_STAR:
            break
    return out


# ---------------------------------------------------------------------------
# Shirley (nonparametric, step-down, Williams 1986 modification)
# ---------------------------------------------------------------------------

def shirley(groups: list[np.ndarray], direction: str) -> dict[int, float]:
    """Shirley's nonparametric step-down test with Williams' (1986)
    modification: at step i the observations of groups 0..i are re-ranked,
    the top group's mean rank is the isotonic estimate over groups 1..i, and
    the statistic is referred to Williams' distribution with infinite df."""
    sign = -1.0 if direction == "DOWN" else 1.0
    gs = [sign * g for g in groups]
    out = {i: 1.0 for i in range(1, len(gs))}
    for i in range(len(gs) - 1, 0, -1):
        sub = gs[: i + 1]
        n = np.array([len(g) for g in sub], dtype=float)
        total = n.sum()
        ranks, ties = _midranks(np.concatenate(sub))
        bounds = np.cumsum(np.concatenate([[0], n])).astype(int)
        mean_ranks = np.array([ranks[bounds[j]:bounds[j + 1]].mean() for j in range(len(sub))])
        var = total * (total + 1) / 12.0 - ties / (12.0 * (total - 1)) if total > 1 else 0.0
        stat = _williams_stat(mean_ranks[None, :], n)[0]
        if var <= 0:
            p = 1.0
        else:
            t = stat / math.sqrt(var * (1 / n[i] + 1 / n[0]))
            p = min(1.0, _TREND_TEST_SIDES * _null_p(t, tuple(int(x) for x in n), math.inf))
        out[i] = p
        if p > ALPHA_STAR:
            break
    return out


# ---------------------------------------------------------------------------
# Dunnett (parametric) and Dunn (nonparametric)
# ---------------------------------------------------------------------------

def dunnett(groups: list[np.ndarray]) -> dict[int, float]:
    """Two-sided Dunnett test of each treatment group against the control."""
    if len(groups) < 2 or any(len(g) < 1 for g in groups):
        return {i: 1.0 for i in range(1, len(groups))}
    if np.ptp(np.concatenate(groups)) == 0:
        return {i: 1.0 for i in range(1, len(groups))}
    res = sp_stats.dunnett(*groups[1:], control=groups[0], alternative="two-sided",
                           random_state=np.random.default_rng(_seed("dunnett")))
    return {i + 1: float(p) for i, p in enumerate(res.pvalue)}


def dunn(groups: list[np.ndarray]) -> dict[int, float]:
    """Dunn's (1964) rank test of each treatment group against the control:
    joint midranks, tie-corrected variance, two-sided, Bonferroni-adjusted for
    the number of comparisons."""
    k = len(groups) - 1
    if k < 1:
        return {}
    n = np.array([len(g) for g in groups], dtype=float)
    total = n.sum()
    ranks, ties = _midranks(np.concatenate(groups))
    bounds = np.cumsum(np.concatenate([[0], n])).astype(int)
    mean_ranks = [ranks[bounds[j]:bounds[j + 1]].mean() for j in range(len(groups))]
    var = total * (total + 1) / 12.0 - ties / (12.0 * (total - 1))
    out = {}
    for i in range(1, len(groups)):
        if var <= 0:
            out[i] = 1.0
            continue
        z = (mean_ranks[i] - mean_ranks[0]) / math.sqrt(var * (1 / n[i] + 1 / n[0]))
        out[i] = min(1.0, k * 2.0 * float(sp_stats.norm.sf(abs(z))))
    return out


# ---------------------------------------------------------------------------
# The NTP decision procedure
# ---------------------------------------------------------------------------

def ntp_pairwise(groups_by_dose: dict, family: str = PARAMETRIC,
                 control_dose: float = 0.0) -> PairwiseResult:
    """Jonckheere trend + the NTP-selected pairwise test for one endpoint.

    `family` is PARAMETRIC (Williams/Dunnett — body and organ weights) or
    NONPARAMETRIC (Shirley/Dunn — clinical pathology).  Groups with no finite
    values (e.g. every animal died), and treatment groups of fewer than
    MIN_GROUP_N animals, are left out of every test."""
    doses, groups = _clean(groups_by_dose)
    result = PairwiseResult()
    if not doses or doses[0] != float(control_dose) or len(groups) < 2:
        return result
    result.jonckheere_p, result.direction = jonckheere(groups)

    trend = result.jonckheere_p <= TREND_TEST_SELECT_P and result.direction in ("UP", "DOWN")
    if family == NONPARAMETRIC:
        result.method = "shirley" if trend else "dunn"
        p = shirley(groups, result.direction) if trend else dunn(groups)
    else:
        result.method = "williams" if trend else "dunnett"
        p = williams(groups, result.direction) if trend else dunnett(groups)
    result.pairwise_p = {doses[i]: v for i, v in p.items()}
    return result
