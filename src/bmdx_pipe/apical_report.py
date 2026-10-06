"""
Generate NTP-style apical endpoint report sections from BMDExpress 3 .bm2 files.

Originally built for the "Animal Condition, Body Weights, and Organ Weights"
section, but parameterized so it can also produce "Clinical Pathology" or any
other apical endpoint section — just pass --section-title and --table-caption.

This script is the bridge between BMDExpress category analysis results and
the NTP-standard statistical tests (ntp_stats.py).  It:

  1. Exports raw dose-response and category analysis data from a .bm2 file
     using the BMDExpress 3 Java CLI
  2. Runs NTP-standard statistical tests (Jonckheere → Williams/Dunnett for
     weights, Shirley/Dunn for clinical pathology) on the raw dose-response
     data, including relative organ weights derived per animal
  3. Cross-references category analysis results for BMD/BMDL values
  4. Applies the business rule: BMD is only reported if BOTH pairwise
     significance AND trend significance are met

Produces the report table DATA (build_table_data / build_table_data_from_bm2 →
{sex: [TableRow]}) plus the .bm2 export/stat helpers. Presentation (docx emission
and the old standalone CLI) was removed in the seam re-cut (C1, 2026-09-08) — the
data-model library no longer renders; rlm-bmdx's rendering/ surfaces do. See
docs/plans/bmdx-pipe-seam-recut.md.

Per-sex TableRow structure:
  - First row: "n" — sample sizes per dose group
  - Subsequent rows: one per endpoint (e.g., "Terminal Body Wt.", "Liver
    Absolute", "Liver Relative")
  - mean ± SE per dose group (with */** significance markers), plus BMD1Std /
    BMDL1Std; control row carries the trend (Jonckheere) marker, treatment rows
    the pairwise (Williams/Dunnett or Shirley/Dunn) marker; not-significant-both → "ND"; dose
    groups with no surviving animals → dash + attrition footnote.
"""

import csv
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import bm2_cache
from .apical_stats import analyze_endpoint, EndpointStats, run_java_prefilter


# ---------------------------------------------------------------------------
# Constants — paths and configuration
# ---------------------------------------------------------------------------

# Java classpath, project paths, and helper directory are centralized in
# java_bridge.py to avoid duplication across apical_report, apical_stats,
# and pool_integrator.
from .java_bridge import build_classpath as _build_classpath
from .java_bridge import JAVA_HELPER_DIR

# Font size for table cells (small to fit many dose columns)
TABLE_FONT_SIZE = 8

# Font size for table header cells
HEADER_FONT_SIZE = 8


def export_bm2(bm2_path: str, output_json: str, output_tsv: str) -> None:
    """
    Export a .bm2 file to JSON + category TSV in a single JVM launch.

    Uses the pre-compiled ExportBm2.class which deserializes the .bm2 file
    (Java ObjectInputStream → BMDProject), then:
      1. Writes the full BMDProject as JSON via Jackson
      2. Writes category analysis results as TSV via BMDExpress's own
         DataCombinerService + ProjectNavigationService

    This is ~30x faster than the old 3-JVM approach because JVM startup
    is the bottleneck, not the actual work.

    Args:
        bm2_path:    Path to the input .bm2 file.
        output_json: Path where the JSON export will be written.
        output_tsv:  Path for category TSV, or "NONE" to skip.
    """
    cp = _build_classpath()
    helper_dir = str(JAVA_HELPER_DIR)

    subprocess.run(
        [
            "java", "-cp", f"{cp}:{helper_dir}",
            "ExportBm2", bm2_path, output_json, output_tsv,
        ],
        check=True, capture_output=True,
    )


def export_genomics(bm2_path: str, output_json: str) -> dict:
    """
    Extract genomics results (gene-level BMD + GO BP categories) from a .bm2 file.

    Uses the pre-compiled ExportGenomics.class which deserializes the .bm2 via
    BMDExpress 3's native Java API, then extracts:
      1. Per-probe BMD/BMDL/BMDU, direction, rSquared, fold change
      2. GO Biological Process category analysis with aggregated BMD stats

    Results are grouped by organ × sex experiment.  This is the authoritative
    source — BMDExpress's own prefilter → curve fit → BMD pipeline ran on the
    data, and we're reading its results directly.

    Args:
        bm2_path:    Path to the gene expression .bm2 file.
        output_json: Path where the genomics JSON will be written.

    Returns:
        The parsed JSON dict with structure:
        {
            "experiments": [
                {
                    "name": str, "organ": str, "sex": str,
                    "total_probes": int,
                    "genes": [{ "probe_id", "gene_symbol", "bmd", "bmdl",
                                "bmdu", "direction", "r_squared", ... }],
                    "go_bp": [{ "go_id", "go_term", "bmd_median", "bmdl_median",
                                "n_genes", "n_passed", "direction", ... }]
                }
            ]
        }
    """
    cp = _build_classpath()
    helper_dir = str(JAVA_HELPER_DIR)

    subprocess.run(
        [
            "java", "-cp", f"{cp}:{helper_dir}",
            "ExportGenomics", bm2_path, output_json,
        ],
        check=True, capture_output=True,
    )

    with open(output_json, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Category analysis BMD extraction — via native Java API
# ---------------------------------------------------------------------------

def export_categories(bm2_path: str, output_json: str) -> dict:
    """
    Extract all category analysis BMD values from a .bm2 file.

    Uses the pre-compiled ExportCategories.class which reads
    CategoryAnalysisResults directly from the BMDProject via BMDExpress's
    native Java API.  This replaces the broken DataCombinerService TSV
    export path (which crashes with IndexOutOfBoundsException).

    Exports ALL BMD statistics per endpoint: mean, median, minimum,
    weighted mean, 5th/10th percentile, 95% CI bounds — so the user
    can choose which statistic to display in report tables.

    Args:
        bm2_path:    Path to the .bm2 file.
        output_json: Path where the categories JSON will be written.

    Returns:
        The parsed JSON dict with structure:
        {
            "analysis_count": int,
            "total_endpoints": int,
            "analyses": [
                {
                    "name": str,
                    "experiment_prefix": str,
                    "category_type": str,
                    "results": [
                        {
                            "category_id": str,
                            "category_title": str,
                            "bmd": { "mean", "median", "minimum", ... },
                            "bmdl": { ... },
                            "bmdu": { ... },
                            "genes_passed": int,
                            ...
                        }
                    ]
                }
            ]
        }
    """
    cp = _build_classpath()
    helper_dir = str(JAVA_HELPER_DIR)

    subprocess.run(
        [
            "java", "-cp", f"{cp}:{helper_dir}",
            "ExportCategories", bm2_path, output_json,
        ],
        check=True, capture_output=True,
    )

    with open(output_json, "rb") as f:
        import orjson
        return orjson.loads(f.read())


def build_category_lookup(
    categories_json: dict,
    bmd_stat: str = "mean",
    experiment_names: list[str] | None = None,
) -> dict[tuple[str, str], dict]:
    """
    Build the category lookup dict from ExportCategories output.

    Transforms the structured JSON from export_categories() into the
    (experiment_name, endpoint_name) → {bmd, bmdl, bmdu, ...} lookup
    that build_table_data() uses to populate BMD/BMDL columns.

    BMDExpress appends pipeline suffixes to experiment names in category
    analysis results (e.g., "female_clin_chem" becomes
    "female_clin_chem_williams_0.05_NOMTC_nofoldfilter").  When
    experiment_names is provided, this function resolves each suffixed
    prefix back to its raw experiment name so build_table_data() can
    look up BMD values using the original experiment name.

    The bmd_stat parameter controls which BMD aggregate statistic is used.
    For single-gene apical endpoints (1 gene per category), all statistics
    are identical.  For GO categories in genomics data, the choice matters
    (e.g., median vs 5th percentile can differ substantially).

    Args:
        categories_json:  Output from export_categories().
        bmd_stat:         Which BMD statistic to use. One of:
                          "mean", "median", "minimum", "weighted_mean",
                          "fifth_pct", "tenth_pct", "lower95", "upper95".
                          Defaults to "mean" for backward compatibility.
        experiment_names: Optional list of raw experiment names from the
                          BMDProject's doseResponseExperiments.  When
                          provided, category prefixes are resolved to the
                          longest matching experiment name, fixing the
                          key mismatch caused by BMDExpress pipeline
                          suffixes.

    Returns:
        Dict mapping (experiment_name, endpoint_name) → {bmd, bmdl, bmdu, ...}
    """
    # Pre-sort experiment names by length (longest first) so we match the
    # most specific name when a prefix starts with multiple candidates.
    # E.g., "female_clin_chem" should match before "female_clin".
    sorted_exp_names = (
        sorted(experiment_names, key=len, reverse=True)
        if experiment_names
        else []
    )

    lookup = {}

    for analysis in categories_json.get("analyses", []):
        prefix = analysis.get("experiment_prefix", "")

        # Resolve the suffixed prefix to a raw experiment name.
        # BMDExpress category analysis names look like:
        #   female_clin_chem_williams_0.05_NOMTC_nofoldfilter_BMD_null_DEFINED-...
        # ExportCategories splits on "_BMD" → prefix is the part before it:
        #   female_clin_chem_williams_0.05_NOMTC_nofoldfilter
        # We need to map this back to the raw experiment name:
        #   female_clin_chem
        resolved_prefix = prefix
        for exp_name in sorted_exp_names:
            # The prefix must start with the experiment name, and the
            # character after (if any) must be '_' to avoid partial matches
            # (e.g., "female_clin" should not match "female_clin_chem").
            if prefix == exp_name:
                resolved_prefix = exp_name
                break
            if prefix.startswith(exp_name) and prefix[len(exp_name):len(exp_name) + 1] == "_":
                resolved_prefix = exp_name
                break

        for result in analysis.get("results", []):
            endpoint = result.get("category_title", "")

            # Pull the selected statistic from the nested bmd/bmdl/bmdu blocks
            bmd_block = result.get("bmd", {})
            bmdl_block = result.get("bmdl", {})
            bmdu_block = result.get("bmdu", {})

            entry = {
                "bmd": bmd_block.get(bmd_stat, bmd_block.get("mean", "")),
                "bmdl": bmdl_block.get(bmd_stat, bmdl_block.get("mean", "")),
                "bmdu": bmdu_block.get(bmd_stat, bmdu_block.get("mean", "")),
                "category_id": result.get("category_id", ""),
                "direction": result.get("direction", ""),
                "fold_change": result.get("max_fold_change", ""),
                # Preserve the full stat blocks for downstream use
                "bmd_stats": bmd_block,
                "bmdl_stats": bmdl_block,
                "bmdu_stats": bmdu_block,
            }

            # Store under the resolved prefix (raw experiment name).
            # Also store under the full suffixed prefix for callers that
            # already use the suffixed key (backward compatibility).
            lookup[(resolved_prefix, endpoint)] = entry
            if resolved_prefix != prefix:
                lookup[(prefix, endpoint)] = entry

    return lookup


# ---------------------------------------------------------------------------
# Data assembly — combine stats + category analysis into table-ready data
# ---------------------------------------------------------------------------

@dataclass
class TableRow:
    """
    One row of the final report table — represents a single endpoint
    (e.g., "Liver Weight Relative") for one sex.

    The reference NIEHS report splits apical data into two table types:
      - Domain tables (Tables 2-7): mean ± SE per dose group, significance
        markers, sample sizes.  NO BMD columns.
      - BMD summary (Table 8): Endpoint, BMD, BMDL, LOEL, NOEL, Direction.
        Only includes endpoints with significant findings.

    This dataclass carries all fields needed for both table types.

    Attributes:
        label:          Display label for the endpoint column
        values_by_dose: Dict mapping dose → formatted string ("mean ± SE**")
        n_by_dose:      Dict mapping dose → sample size (for the n row)
        bmd_str:        Formatted BMD value, "NVM", "<x" (NR), "—"
        bmdl_str:       Formatted BMDL value, "NVM", "—"
        trend_marker:   "*" or "**" or "" — for the control column
        bmd_status:     NIEHS classification: "viable", "NVM", "NR",
                        "failure", or None (not modeled).
        loel:           Lowest observed effect level (mg/kg), or None
        noel:           No observed effect level (mg/kg), or None
        direction:      "UP" or "DOWN" — direction of change vs control
        mean_se_by_dose: Dict mapping dose → [mean, se] unrounded (se None for
                        n = 1) — the numbers values_by_dose was formatted from.
        responsive:     True if both Jonckheere trend AND Dunnett pairwise tests
                        are significant (p ≤ 0.05).  Used to filter main body
                        tables (Tables 2-7) per NIEHS business rule: only
                        responsive endpoints appear in domain tables.  BMD
                        summary (Table 8) uses its own inclusion gate.
    """
    label: str = ""
    values_by_dose: dict = field(default_factory=dict)
    n_by_dose: dict = field(default_factory=dict)
    bmd_str: str = "—"
    bmdl_str: str = "—"
    trend_marker: str = ""
    bmd_status: str | None = None
    loel: float | None = None
    noel: float | None = None
    direction: str = ""
    responsive: bool = False
    # Which NTP pairwise test produced the dose-column markers
    # (williams | dunnett | shirley | dunn | none) and the Jonckheere p-value
    # behind the control-column marker — so text describing the statistics
    # can name the test that actually ran.
    pairwise_method: str = ""
    trend_p: float | None = None
    # Missing-animal footnote data.  Populated when an xlsx study file
    # provides the authoritative animal roster and some animals are absent
    # from the bm2 data (died before terminal sacrifice).
    # Maps dose → number of animals in the xlsx roster that have no data
    # for this endpoint.  Empty dict means no missing animals.
    missing_animals_by_dose: dict[float, int] = field(default_factory=dict)
    # The unrounded statistics behind values_by_dose: dose -> [mean, se] (se
    # None for a single animal; absent when the group has no data).  Lets a
    # report print each row at the endpoint's own precision instead of the
    # magnitude-based one baked into values_by_dose.
    mean_se_by_dose: dict[float, list] = field(default_factory=dict)


def _safe_float(val) -> float | None:
    """
    Safely convert a value to float, handling None, string "NaN", and
    Jackson serialization quirks.  Returns None if the value is not a
    valid finite number.
    """
    if val is None:
        return None
    if isinstance(val, str):
        if val.lower() == "nan" or val.lower() == "infinity":
            return None
        try:
            f = float(val)
            return f if f == f else None  # NaN check
        except ValueError:
            return None
    if isinstance(val, (int, float)):
        return val if val == val else None  # NaN check
    return None


def _adaptive_decimals(*values: float | None, min_dp: int = 1, max_dp: int = 4) -> int:
    """
    Choose the number of decimal places for a group of related values
    (typically mean and SE for the same dose group).

    Uses the smallest non-zero absolute value to decide:
      - |v| >= 1    → 1 decimal  (e.g., "234.5 ± 12.3")
      - |v| >= 0.1  → 2 decimals (e.g., "0.34 ± 0.12")
      - |v| >= 0.01 → 3 decimals (e.g., "0.034 ± 0.012")
      - |v| < 0.01  → 4 decimals (e.g., "0.0034 ± 0.0012")

    This keeps large body weights at 1 dp (matching reference format) while
    giving small clinical chemistry values enough precision.
    """
    # Find the smallest non-zero magnitude among all provided values
    smallest = None
    for v in values:
        if v is not None and v != 0:
            mag = abs(v)
            if smallest is None or mag < smallest:
                smallest = mag

    if smallest is None or smallest >= 1.0:
        return min_dp
    elif smallest >= 0.1:
        return max(min_dp, 2)
    elif smallest >= 0.01:
        return max(min_dp, 3)
    else:
        return max_dp


def _classify_bmd_result(
    bmd: float | None,
    bmdl: float | None,
    lowest_nonzero_dose: float,
    highest_dose: float,
    best_stat_result: dict | None,
) -> str:
    """
    Classify a BMDExpress bMDResult into the report's BMD statuses.

      - "failure":  no model result at all (the endpoint was never modeled).
      - "NVM":      no viable model — the fit failed, or the model average
                    fails the NIEHS defined-category filter (R² < 0.6,
                    BMD/BMDL > 10, BMD > highest dose; see bmd_acceptance).
      - "NR":       not reportable — BMD below 1/3 of the lowest nonzero dose;
                    printed as "<LNZD/3" with no BMDL.
      - "viable":   reported.

    Args:
        bmd, bmdl: Best BMD / BMDL (None when NaN or absent).
        lowest_nonzero_dose, highest_dose: The experiment's dose range.
        best_stat_result: The bestStatResult dict from BMDExpress 3 (carries
                          `success` and `rSquared`).
    """
    from .bmd_acceptance import classify

    if best_stat_result is None:
        return "failure" if bmd is None else classify(
            bmd, bmdl, None, lowest_nonzero_dose, highest_dose)[0]
    # BMDExpress 3 serializes success as string "true" or null
    success = best_stat_result.get("success")
    if success is None or success in ("false", False):
        return "NVM"
    return classify(bmd, bmdl, best_stat_result.get("rSquared"),
                    lowest_nonzero_dose, highest_dose)[0]


def _build_bmd_result_lookup(bm2_json: dict) -> dict[tuple[str, str], dict]:
    """
    Build a lookup of BMD/BMDL values and NIEHS classification from
    BMDExpress 3 native bMDResult data.

    BMDExpress 3 stores dose-response modeling results in the bMDResult
    array.  Each entry has probeStatResults with bestBMD/bestBMDL and
    model fit metrics (rSquared, success, confidence bounds).

    This function resolves Jackson @ref pointers, extracts BMD values,
    and classifies each result into NIEHS bins: viable, NVM, NR, or
    failure (see _classify_bmd_result and bmd_acceptance).  The parent
    experiment's dose range drives the NR (BMD < LNZD/3) and
    BMD > highest dose rules.

    Returns:
        Dict mapping (experiment_name, probe_id) → {
            "bmd": float|None, "bmdl": float|None, "bmdu": float|None,
            "status": str  # "viable", "NVM", "NR", "failure"
        }.
    """
    import math

    # Resolve Jackson object identity.  Each object is serialized inline the
    # first time it appears, carrying its id as "@ref", and as that bare
    # integer afterwards.  An experiment usually appears first in
    # doseResponseExperiments, but a project can also carry BMD results for
    # experiments it does not list (the NIEHS-13 non-genomic project holds
    # NIEHS-12's analyses), which are then inline inside the bMDResult.
    exps: dict[int, dict] = {}
    probes: dict[int, dict] = {}       # probeResponse objects
    probe_objs: dict[int, dict] = {}   # their Probe objects (shared across experiments)

    def _register_exp(exp: dict) -> None:
        if exp.get("@ref") is not None:
            exps[exp["@ref"]] = exp
        for pr in exp.get("probeResponses", []) or []:
            if isinstance(pr, dict) and pr.get("@ref") is not None:
                probes[pr["@ref"]] = pr
                _resolve(pr.get("probe"), probe_objs)

    def _resolve(obj, table: dict[int, dict], register=None) -> dict | None:
        if isinstance(obj, dict):
            if register:
                register(obj)
            elif obj.get("@ref") is not None:
                table[obj["@ref"]] = obj
            return obj
        return table.get(obj) if isinstance(obj, int) else None

    for exp in bm2_json.get("doseResponseExperiments", []):
        _register_exp(exp)

    # Cache the dose range per experiment: the lowest nonzero dose (NR when
    # BMD < LNZD/3) and the highest dose (NVM when BMD exceeds it).
    dose_range_cache: dict[str, tuple[float, float]] = {}

    lookup: dict[tuple[str, str], dict] = {}
    for result in bm2_json.get("bMDResult", []):
        exp = _resolve(result.get("doseResponseExperiment"), exps, _register_exp)
        exp_name = (exp or {}).get("name", "")
        if not exp_name:
            continue

        # Dose range for this experiment (cached per name)
        if exp_name not in dose_range_cache:
            doses = [t["dose"] for t in exp.get("treatments", []) if isinstance(t, dict)]
            nonzero = [d for d in doses if d > 0]
            dose_range_cache[exp_name] = ((min(nonzero), max(nonzero))
                                          if nonzero else (0.0, 0.0))
        lnzd, high = dose_range_cache[exp_name]

        for psr in result.get("probeStatResults", []):
            pr = _resolve(psr.get("probeResponse"), probes)
            probe = _resolve((pr or {}).get("probe"), probe_objs)
            probe_id = (probe or {}).get("id", "")
            if not probe_id:
                continue

            bmd = _safe_float(psr.get("bestBMD"))
            bmdl = _safe_float(psr.get("bestBMDL"))
            bmdu = _safe_float(psr.get("bestBMDU"))

            # Get bestStatResult for model fit classification.
            # It can be a dict (inline) or an int (@ref pointer).
            bsr = psr.get("bestStatResult")
            if isinstance(bsr, int):
                bsr = None  # unresolved @ref — treat as no info

            status = _classify_bmd_result(bmd, bmdl, lnzd, high, bsr)

            lookup[(exp_name, probe_id)] = {
                "bmd": bmd,
                "bmdl": bmdl,
                "bmdu": bmdu,
                "status": status,
            }

    return lookup


# Experiment-name hints for the statistics family when an experiment carries
# no recognised platform (older sessions): weights are parametric, clinical
# pathology nonparametric.
_PARAMETRIC_NAME_HINTS = ("organ", "weight", "body")
_NONPARAMETRIC_NAME_HINTS = ("clin", "chem", "hemat", "hormon", "urin", "thyroid")


def _stats_family(platform: str | None, exp_name: str) -> str:
    """The NTP test family (ntp_stats.PARAMETRIC / NONPARAMETRIC) for an
    experiment: from its platform, else from its name.  An experiment neither
    names is analysed parametrically, with a warning."""
    from . import ntp_stats
    family = ntp_stats.family_for_platform(platform)
    if family:
        return family
    lower = (exp_name or "").lower()
    if any(h in lower for h in _NONPARAMETRIC_NAME_HINTS):
        return ntp_stats.NONPARAMETRIC
    if any(h in lower for h in _PARAMETRIC_NAME_HINTS):
        return ntp_stats.PARAMETRIC
    import sys
    print(f"  WARNING: no statistics family for experiment {exp_name!r} "
          f"(platform {platform!r}); using the parametric tests "
          f"(Williams/Dunnett)", file=sys.stderr)
    return ntp_stats.PARAMETRIC


def _is_organ_weight(platform: str | None, exp_name: str) -> bool:
    if platform:
        return platform == "Organ Weight"
    return "organ" in (exp_name or "").lower()


def _is_body_weight_label(label: str) -> bool:
    lower = label.lower()
    return "body" in lower and ("weight" in lower or "wt" in lower)


def _relative_organ_weights(
    probe_vectors: list[tuple[str, list]],
) -> list[tuple[str, list]]:
    """Relative organ weights for one organ-weight experiment:
    "<organ> Relative" = organ weight / terminal body weight x 1000 (mg/g),
    per animal (the response vectors share the experiment's animal order).

    Needs a terminal body weight endpoint; an organ that already has a
    relative endpoint in the data, or is itself one, is left alone."""
    tbw = next((v for name, v in probe_vectors if _is_body_weight_label(name)), None)
    if tbw is None:
        return []
    names = {name for name, _ in probe_vectors}
    out = []
    for name, values in probe_vectors:
        if _is_body_weight_label(name) or name.lower().endswith("relative"):
            continue
        organ = name[: -len("Absolute")].strip() if name.lower().endswith("absolute") else name
        rel_name = f"{organ} Relative"
        if rel_name in names:
            continue
        rel = []
        for o, t in zip(values, tbw):
            ok = all(isinstance(x, (int, float)) and math.isfinite(x) for x in (o, t))
            rel.append(o / t * 1000.0 if ok and t > 0 else None)
        out.append((rel_name, rel))
    return out


def build_table_data(
    bm2_json: dict,
    category_lookup: dict,
    platforms: list[str] | None = None,
    bmd_decimals: int | None = None,
) -> dict[str, list[TableRow]]:
    """
    Build the table data for all endpoints, organized by sex.

    Statistics follow the NTP procedure (bmdx_pipe.ntp_stats): Jonckheere's
    trend test selects the pairwise test — Williams or Dunnett for body and
    organ weights, Shirley or Dunn for clinical pathology — and the family
    comes from the experiment's platform.  Organ-weight experiments also get
    relative organ weights (mg organ / g terminal body weight, per animal) as
    endpoints of their own, with the same statistics and BMD inputs.
    BMD lookup uses BMDExpress 3 native bMDResult data (bestBMD/bestBMDL) as
    the primary source, with category_lookup as fallback for genomics
    endpoints.

    Args:
        bm2_json:        Parsed JSON from the .bm2 export.
        category_lookup: Dict from build_category_lookup().
        platforms:       Optional list of platform strings to include.  When
                         provided, only experiments whose experimentDescription
                         .platform is in this list are processed.  When None,
                         all experiments are included (backward compat).
        bmd_decimals:    The report's fixed BMD precision (format_bmd); None
                         keeps 3 significant figures.

    Returns:
        Dict mapping sex label ("Male" / "Female") → list of TableRow.
        Each list is ordered: body weight endpoints first, then organ
        weight endpoints.
    """
    from . import ntp_stats
    from .apical_stats import _sig_marker, ALPHA_STAR
    import math

    # Build lookup of BMDExpress 3-native BMD values from bMDResult.
    # This is the primary BMD source for apical endpoints (body weight,
    # organ weight, clinical chemistry, hematology, hormones).  Category
    # analysis (category_lookup) is the fallback for genomics endpoints.
    bmd_result_lookup = _build_bmd_result_lookup(bm2_json)

    # ---- Collect endpoints ----
    endpoint_meta: list[dict] = []

    for exp in bm2_json.get("doseResponseExperiments", []):
        exp_name = exp.get("name", "")
        desc = exp.get("experimentDescription")
        exp_platform = desc.get("platform") if isinstance(desc, dict) else None

        # --- Platform filter: skip experiments not in the requested platforms ---
        if platforms is not None and exp_platform not in platforms:
            continue

        family = _stats_family(exp_platform, exp_name)
        treatments = exp.get("treatments", [])
        treat_doses = {i: t["dose"] for i, t in enumerate(treatments)}

        # Determine sex from experiment name
        exp_name_lower = exp_name.lower()
        if "female" in exp_name_lower:
            sex = "Female"
        elif "male" in exp_name_lower:
            sex = "Male"
        else:
            sex = "Unknown"

        probe_vectors = [(pr["probe"]["id"], pr["responses"])
                         for pr in exp.get("probeResponses", [])]
        if _is_organ_weight(exp_platform, exp_name):
            probe_vectors += _relative_organ_weights(probe_vectors)

        for probe_name, responses in probe_vectors:
            # Group by dose, dropping missing observations (None/NaN).  A dose
            # whose every value is missing keeps an empty group so the table
            # still shows the column.
            groups_by_dose: dict[float, list[float]] = {}
            for i, val in enumerate(responses):
                dose = treat_doses[i]
                group = groups_by_dose.setdefault(dose, [])
                if val is not None and not (isinstance(val, float) and math.isnan(val)):
                    group.append(val)

            # Skip endpoints without control
            if 0.0 not in groups_by_dose:
                continue

            endpoint_meta.append({
                "exp_name": exp_name,
                "probe_name": probe_name,
                "sex": sex,
                "family": family,
                "groups_by_dose": groups_by_dose,
                "sorted_doses": sorted(groups_by_dose.keys()),
            })

    # ---- Per endpoint: NTP statistics, BMD lookup, table row ----
    tables: dict[str, list[TableRow]] = {}

    for meta in endpoint_meta:
        exp_name = meta["exp_name"]
        probe_name = meta["probe_name"]
        sex = meta["sex"]
        groups_by_dose = meta["groups_by_dose"]
        sorted_doses = meta["sorted_doses"]

        if sex not in tables:
            tables[sex] = []

        # Descriptive statistics
        control_dose = 0.0
        treatment_doses = [d for d in sorted_doses if d != control_dose]
        n_per_dose = {}
        mean_per_dose = {}
        se_per_dose = {}

        for dose in sorted_doses:
            vals = groups_by_dose[dose]
            n = len(vals)
            if n == 0:
                n_per_dose[dose] = 0
                mean_per_dose[dose] = None
                se_per_dose[dose] = None
                continue
            mean_val = sum(vals) / n
            n_per_dose[dose] = n
            mean_per_dose[dose] = mean_val
            if n > 1:
                variance = sum((v - mean_val) ** 2 for v in vals) / (n - 1)
                se_per_dose[dose] = math.sqrt(variance / n)
            else:
                se_per_dose[dose] = 0.0

        # Jonckheere trend test + the pairwise test it selects (NTP procedure).
        # The control column's marker is the trend test; a dose column's
        # marker is its pairwise test.
        stats_result = ntp_stats.ntp_pairwise(
            groups_by_dose, meta["family"], control_dose=control_dose)
        jonck_p, direction = stats_result.jonckheere_p, stats_result.direction
        jonckheere_sig = jonck_p <= ALPHA_STAR
        trend_marker = _sig_marker(jonck_p)
        pairwise_p: dict[float, float] = dict(stats_result.pairwise_p)
        pairwise_method = stats_result.method

        pairwise_marker = {d: _sig_marker(p) for d, p in pairwise_p.items()}
        any_pairwise_sig = any(p <= ALPHA_STAR for p in pairwise_p.values())
        report_bmd = jonckheere_sig and any_pairwise_sig

        # Look up BMD/BMDL and NIEHS classification status.
        # BMD modeling and statistical significance are INDEPENDENT concerns:
        #   - BMDExpress 3 runs its own prefilter → produces bMDResult
        #   - Our NTP stats (Jonckheere + Williams/Dunnett/Shirley/Dunn)
        #     → determine LOEL/NOEL
        # The reference report Table 8 shows both side by side.  We always
        # show the BMDExpress 3 classification if a bMDResult exists,
        # regardless of our stat gate.
        #
        # NIEHS classification bins (_classify_bmd_result / bmd_acceptance):
        #   "viable" → report BMD and BMDL values
        #   "NR"     → not reportable (BMD < 1/3 LNZD); show "<LNZD/3"
        #   "NVM"    → no viable model; show "NVM"
        #   "failure" → model did not complete; show "NVM"
        #   None     → endpoint not modeled by BMDExpress 3
        bmd_str = "—"
        bmdl_str = "—"
        bmd_status = None

        # Primary source: BMDExpress 3 native bMDResult
        bmd_entry = bmd_result_lookup.get((exp_name, probe_name))
        if bmd_entry:
            status = bmd_entry["status"]
            bmd_status = status

            if status == "viable":
                bmd_val = bmd_entry["bmd"]
                bmdl_val = bmd_entry["bmdl"]
                if bmd_val is not None and bmdl_val is not None:
                    bmd_str = format_bmd(bmd_val, bmd_decimals)
                    bmdl_str = format_bmd(bmdl_val, bmd_decimals)
                else:
                    bmd_str = "NVM"
                    bmdl_str = "NVM"
                    bmd_status = "NVM"
            elif status == "NR":
                # BMD below extrapolation limit — report as <1/3 LNZD.
                # BMDL is not reported per NIEHS convention.
                lnzd = sorted_doses[1] if len(sorted_doses) > 1 else 0
                bmd_str = f"<{_format_bmd(lnzd / 3)}"
                bmdl_str = "—"
            elif status == "NVM":
                bmd_str = "NVM"
                bmdl_str = "NVM"
            else:
                # "failure" or unknown
                bmd_str = "NVM"
                bmdl_str = "NVM"
                bmd_status = "NVM"
        else:
            # Fallback: category analysis (genomics endpoints via GO terms)
            cat = category_lookup.get((exp_name, probe_name))
            if cat:
                try:
                    bmd_val = float(cat["bmd"])
                    bmdl_val = float(cat["bmdl"])
                    bmd_str = format_bmd(bmd_val, bmd_decimals)
                    bmdl_str = format_bmd(bmdl_val, bmd_decimals)
                    bmd_status = "viable"
                except (ValueError, KeyError, TypeError):
                    pass

        # Build the formatted values for each dose group
        values_by_dose = {}
        n_by_dose = {}
        mean_se_by_dose = {}

        for dose in sorted_doses:
            n = n_per_dose[dose]
            mean = mean_per_dose[dose]
            se = se_per_dose[dose]
            n_by_dose[dose] = n
            if mean is not None:
                mean_se_by_dose[dose] = [float(mean), float(se) if se is not None else None]

            # Format: "mean ± SE" with significance marker
            if dose == control_dose:
                marker = trend_marker
            else:
                marker = pairwise_marker.get(dose, "")

            if se is not None and se > 0:
                # Adaptive decimal places: use more for small values so
                # precision isn't lost (e.g., 0.0034 ± 0.0012 instead of
                # 0.0 ± 0.0).  Large values (≥1) keep 1 decimal place to
                # match the NTP reference format.
                dp = _adaptive_decimals(mean, se)
                values_by_dose[dose] = f"{mean:.{dp}f} ± {se:.{dp}f}{marker}"
            elif mean is not None:
                dp = _adaptive_decimals(mean)
                values_by_dose[dose] = f"{mean:.{dp}f}{marker}"
            else:
                values_by_dose[dose] = "—"

        # Derive LOEL, NOEL, and direction of change for Table 8.
        # LOEL: lowest treatment dose with a significant (p ≤ 0.05) pairwise
        #   difference from control.  Per NIEHS: "the lowest dose demonstrating
        #   a significant (p ≤ 0.05) pairwise difference relative to the
        #   vehicle control group."
        # NOEL: highest dose NOT showing a significant pairwise difference.
        #   Per NIEHS: "the highest dose not showing a significant (p ≤ 0.05)
        #   pairwise difference relative to the vehicle control group."
        # Direction: UP or DOWN based on Jonckheere trend direction.
        loel = None
        noel = None
        for d in treatment_doses:
            if pairwise_p.get(d, 1.0) <= ALPHA_STAR:
                if loel is None or d < loel:
                    loel = d
        if loel is not None:
            # NOEL = highest dose below LOEL that is not significant
            candidates = [d for d in treatment_doses if d < loel]
            noel = max(candidates) if candidates else control_dose
        else:
            # No significant pairwise → NOEL is the highest dose tested
            noel = max(treatment_doses) if treatment_doses else None

        # Direction from Jonckheere: "UP" or "DOWN" string.
        # Only show direction when the Jonckheere trend test is significant,
        # matching the NIEHS reference convention (Table 8 shows direction
        # only for endpoints with a significant monotonic trend).
        dir_str = ""
        if jonckheere_sig and direction in ("UP", "DOWN"):
            dir_str = direction

        row = TableRow(
            label=probe_name,
            values_by_dose=values_by_dose,
            n_by_dose=n_by_dose,
            bmd_str=bmd_str,
            bmdl_str=bmdl_str,
            trend_marker=trend_marker,
            bmd_status=bmd_status,
            loel=loel,
            noel=noel,
            direction=dir_str,
            responsive=report_bmd,
            pairwise_method=pairwise_method,
            trend_p=jonck_p,
            mean_se_by_dose=mean_se_by_dose,
        )
        tables[sex].append(row)

        # Collect dose-response summary stats for optional BMDS modeling.
        # These are the same means/SDs/Ns we computed above, packaged in a
        # format that apical_bmds.run_bmds_for_endpoints() expects.
        # Stored on the TableRow so the orchestrator can extract them without
        # re-parsing the integrated JSON.
        _sorted_doses = sorted(groups_by_dose.keys())
        row._bmds_input = {
            "key": f"{sex}::{probe_name}",
            "doses": _sorted_doses,
            "ns": [n_per_dose.get(d, 0) for d in _sorted_doses],
            "means": [
                mean_per_dose.get(d, 0.0) if mean_per_dose.get(d) is not None else 0.0
                for d in _sorted_doses
            ],
            "stdevs": [
                # Convert SE back to SD: SD = SE * sqrt(n)
                (se_per_dose.get(d, 0.0) or 0.0) * math.sqrt(n_per_dose.get(d, 1))
                for d in _sorted_doses
            ],
            # Per-animal vectors for the ToxicR Java fitter (suff_stat=false path):
            # BMDExpress fits from individual values, not group summaries, so match it
            # for digit-identical validation. groups_by_dose already holds per-animal
            # values (cleaned) — flatten to parallel doses[]/Y[] arrays.
            "doses_per_animal": [
                d for d in _sorted_doses for _ in groups_by_dose.get(d, [])
            ],
            "Y": [
                v for d in _sorted_doses for v in groups_by_dose.get(d, [])
            ],
            "sex": sex,
            "endpoint": probe_name,
        }

    return tables


def annotate_missing_animals(
    domain_tables: dict[str, dict[str, list]],
    xlsx_rosters: dict[str, dict],
    reference_platform: str = "Body Weight",
) -> None:
    """
    Annotate TableRows with missing-animal counts by comparing bm2 N counts
    against the xlsx study file roster.

    Dead animals are detected by comparing the bm2 N per dose (survivors
    with measurements) against the xlsx Core Animals roster (full assignment).
    The difference is recorded as missing_animals_by_dose on each TableRow.

    For platforms whose xlsx roster has fewer dose groups than the reference
    platform (e.g., clinical chemistry missing 333/1000 mg/kg), the entire
    dose group is flagged as missing.

    Mutates TableRows in place — no return value.

    Args:
        domain_tables:      {platform → {sex → [TableRow, ...]}}, as from _partition_by_domain.
        xlsx_rosters:       From integrated["_meta"]["xlsx_rosters"].
        reference_platform: Platform with the most complete roster (usually Body Weight).
    """
    if not xlsx_rosters:
        return

    # Use the reference platform (body weight) to establish the full Core
    # Animals roster — all dose groups and all animals expected to survive
    # to terminal sacrifice.  If no body weight xlsx exists, use the platform
    # with the most dose groups.
    ref_roster = xlsx_rosters.get(reference_platform)
    if not ref_roster:
        # Fallback: domain with most dose groups
        ref_roster = max(
            xlsx_rosters.values(),
            key=lambda r: len(r.get("dose_groups", [])),
            default=None,
        )
    if not ref_roster:
        return

    # Reference: dose (float) → sex → expected Core Animal count.
    # Dose keys may be strings from JSON — normalize to float.
    ref_core_raw = ref_roster.get("core_animals_by_dose_sex", {})
    ref_core = {float(k): v for k, v in ref_core_raw.items()}

    for domain, sex_rows in domain_tables.items():
        # Get this domain's xlsx roster for comparison.
        # Normalize dose keys to float (may be strings from JSON).
        dom_roster = xlsx_rosters.get(domain, {})
        dom_core_raw = dom_roster.get("core_animals_by_dose_sex", {})
        dom_core = {float(k): v for k, v in dom_core_raw.items()}

        for sex, rows in sex_rows.items():
            for row in rows:
                missing = {}
                for dose, actual_n in row.n_by_dose.items():
                    # Expected N: from this domain's xlsx, or from reference
                    # domain if this domain's xlsx doesn't have the dose group
                    dom_sex_aids = dom_core.get(dose, {}).get(sex)
                    ref_sex_aids = ref_core.get(dose, {}).get(sex)

                    if dom_sex_aids is not None:
                        expected_n = len(dom_sex_aids)
                    elif ref_sex_aids is not None:
                        # This domain doesn't have this dose group in its
                        # xlsx — all animals at this dose died before this
                        # endpoint could be measured
                        expected_n = len(ref_sex_aids)
                    else:
                        continue

                    diff = expected_n - actual_n
                    if diff > 0:
                        missing[dose] = diff

                # Also flag dose groups that are in the reference but
                # completely absent from this endpoint's data
                for dose in ref_core:
                    if dose not in row.n_by_dose:
                        sex_aids = ref_core[dose].get(sex)
                        if sex_aids:
                            missing[dose] = len(sex_aids)

                row.missing_animals_by_dose = missing


def backfill_missing_doses(
    domain_tables: dict[str, dict[str, list]],
    xlsx_rosters: dict[str, dict],
    reference_platform: str = "Body Weight",
) -> None:
    """
    Ensure every TableRow uses the full study dose list as columns, filling
    in "–" (em-dash) for dose groups where no animals survived to be measured.

    The NIEHS reference report shows ALL dose columns in every domain table,
    even when an entire dose group is absent (all animals died).  Those
    columns display "–" for the value and 0 for N, making it visually clear
    that the study included that dose but no data was collected.

    This function runs AFTER annotate_missing_animals() so that the
    missing_animals_by_dose dict is already populated.  It:
      1. Determines the full dose list from the reference xlsx roster
      2. For each TableRow, adds any missing doses with "–" values and N=0

    Mutates TableRows in place — no return value.

    Args:
        domain_tables:      {platform → {sex → [TableRow, ...]}}, as from _partition_by_domain.
        xlsx_rosters:       From integrated["_meta"]["xlsx_rosters"].
        reference_platform: Platform with the most complete roster (usually Body Weight).
    """
    if not xlsx_rosters:
        return

    # Determine the full study dose list from the reference platform's roster.
    # The body_weight xlsx always has every dose group because body weight
    # is measured on all animals regardless of survival.
    ref_roster = xlsx_rosters.get(reference_platform)
    if not ref_roster:
        # Fallback: domain with the most dose groups
        ref_roster = max(
            xlsx_rosters.values(),
            key=lambda r: len(r.get("dose_groups", [])),
            default=None,
        )
    if not ref_roster:
        return

    # Full dose list from the reference roster, sorted ascending.
    # Dose keys may be strings from JSON — normalize to float.
    ref_doses_raw = ref_roster.get("dose_groups", [])
    full_doses = sorted(float(d) for d in ref_doses_raw)
    if not full_doses:
        return

    for domain, sex_rows in domain_tables.items():
        for sex, rows in sex_rows.items():
            for row in rows:
                # Add any doses from the full list that are absent from
                # this row's data.  These are dose groups where no animals
                # survived to have this endpoint measured.
                for dose in full_doses:
                    if dose not in row.values_by_dose:
                        row.values_by_dose[dose] = "–"
                        row.n_by_dose[dose] = 0


def format_bmd(value: float, decimals: int | None = None) -> str:
    """
    Format a BMD or BMDL value for display.

    ``decimals`` is the report's fixed precision: the 2025 NIEHS reports
    (NIEHS-12/13) print every BMD to 1 decimal ("437.0", "0.9"), NIEHS-10 to
    3.  A positive value that would round to zero keeps two significant
    figures instead ("0.034", not "0.0").  ``None`` keeps the legacy
    3-significant-figure form ("8.49", "63").

    Args:
        value:    BMD or BMDL value (in dose units, e.g., mg/kg).
        decimals: Fixed decimal places, or None for 3 significant figures.

    Returns:
        Formatted string, e.g., "8.5" (decimals=1) or "8.49" (None).
    """
    if value == 0:
        return "0"
    if decimals is None:
        return f"{value:.3g}"
    s = f"{value:.{decimals}f}"
    if value > 0 and float(s) == 0:
        return f"{value:.2g}"
    return s


# The table builder's historical name.
_format_bmd = format_bmd


# ---------------------------------------------------------------------------
# Narrative generation moved app-side (Increment A1a of the bmdx-pipe seam
# re-cut).  generate_results_narrative() and its prose helpers were PRESENTATION
# logic duplicated by narrative/unified_narrative.py in the app; all callers now
# route through narrative.unified_narrative.generate_platform_narrative().  Only
# data-model + computation remains below the seam.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Main entry point — build the report table DATA
# ---------------------------------------------------------------------------
# NOTE (seam re-cut C1, 2026-09-08): the .docx EMITTERS + standalone CLI that
# lived here were REMOVED — presentation left the data-model library. rlm-bmdx
# renders docx via its own rendering/docx_generator.py; this module now yields
# only DATA (build_table_data*, TableRow). See docs/plans/bmdx-pipe-seam-recut.md.

def build_table_data_from_bm2(
    bm2_path: str,
    bmd_stat: str = "mean",
) -> tuple[dict[str, list[TableRow]], dict, dict]:
    """
    Convenience wrapper: export .bm2 → JSON + categories, run stats, return
    (table_data, category_lookup, bm2_json).

    Handles the full export-and-analyze pipeline so callers don't need
    to manage temp files or know about the BMDExpress Java classes.

    Caching: both the full BMDProject JSON and category analysis are cached
    in LMDB (bm2_cache module).  On first call: run Java exports → store
    in LMDB.  On subsequent calls: LMDB lookup + orjson.loads (no JVM).

    The category export now uses ExportCategories.java which reads
    CategoryAnalysisResults directly from the BMDProject via BMDExpress's
    native Java API — replacing the broken DataCombinerService TSV path.

    Args:
        bm2_path: Path to the BMDExpress 3 .bm2 file.
        bmd_stat: Which BMD aggregate statistic to use for the lookup.
                  One of: "mean", "median", "minimum", "weighted_mean",
                  "fifth_pct", "tenth_pct".  Defaults to "mean".

    Returns:
        A 3-tuple:
          - table_data: Dict mapping sex label ("Male"/"Female") → list of
            TableRow, consumed by the app's renderers (rlm-bmdx).
          - category_lookup: Dict from build_category_lookup(), mapping
            (experiment_prefix, endpoint_name) → BMD info dict.
          - bm2_json: The full deserialized BMDProject as a dict.
    """
    print(f"Processing: {bm2_path}")

    # Step 1: Load or export the full BMDProject JSON.
    # LMDB B-tree cache stores deserialized dicts keyed by file path.
    bm2_json = bm2_cache.get_json(bm2_path)
    category_lookup = bm2_cache.get_categories(bm2_path)

    if bm2_json is not None and category_lookup is not None:
        print("  Loaded BMDProject + categories from LMDB cache")
    else:
        # Export BMDProject JSON if not cached
        if bm2_json is None:
            print("  Exporting .bm2 → JSON (ExportBm2)...")
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp_json = tmp.name
            # Skip the TSV export — we use ExportCategories instead
            export_bm2(bm2_path, tmp_json, "NONE")
            with open(tmp_json, "rb") as f:
                import orjson
                bm2_json = orjson.loads(f.read())
            bm2_cache.put_json(bm2_path, bm2_json)
            os.unlink(tmp_json)

        # Export category analysis if not cached
        if category_lookup is None:
            print("  Exporting categories (ExportCategories)...")
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp_cat = tmp.name
            categories_json = export_categories(bm2_path, tmp_cat)
            # Pass experiment names so the lookup resolves BMDExpress
            # pipeline suffixes (e.g., "_williams_0.05_NOMTC_nofoldfilter")
            # back to raw experiment names used by build_table_data().
            exp_names = [
                exp.get("name", "")
                for exp in bm2_json.get("doseResponseExperiments", [])
            ]
            category_lookup = build_category_lookup(
                categories_json, bmd_stat, experiment_names=exp_names,
            )
            bm2_cache.put_categories(bm2_path, category_lookup)
            os.unlink(tmp_cat)

    print(f"  Category analysis: {len(category_lookup)} endpoints with BMD values")

    # Steps 3-5: Build table data (runs stats + cross-references + business rules).
    # NTP procedure: Jonckheere selects Williams/Dunnett (weights) or
    # Shirley/Dunn (clinical pathology) — see ntp_stats.
    print("  Running NTP statistical tests (Jonckheere + Williams/Dunnett/Shirley/Dunn)...")
    table_data = build_table_data(bm2_json, category_lookup)

    return table_data, category_lookup, bm2_json

