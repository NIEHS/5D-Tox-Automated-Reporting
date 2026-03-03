"""
Generate NTP-style apical endpoint report sections from BMDExpress 3 .bm2 files.

Originally built for the "Animal Condition, Body Weights, and Organ Weights"
section, but parameterized so it can also produce "Clinical Pathology" or any
other apical endpoint section — just pass --section-title and --table-caption.

This script is the bridge between BMDExpress category analysis results and
the NTP-standard statistical tests (apical_stats.py).  It:

  1. Exports raw dose-response and category analysis data from a .bm2 file
     using the BMDExpress 3 Java CLI
  2. Runs NTP-standard statistical tests (Jonckheere → Williams/Dunnett)
     on the raw dose-response data
  3. Cross-references category analysis results for BMD/BMDL values
  4. Applies the business rule: BMD is only reported if BOTH pairwise
     significance AND trend significance are met
  5. Generates a .docx report section with tables split by sex, matching
     the NTP subchronic study report format (PFHxSAm prototype)

Table format (per sex):
  - First row: "n" — sample sizes per dose group
  - Subsequent rows: one per endpoint (e.g., "Terminal Body Wt.", "Liver
    Absolute", "Liver Relative")
  - Columns: Endpoint label, then mean ± SE for each dose group (with */**
    significance markers), then BMD1Std and BMDL1Std columns
  - Control row gets * / ** for the trend test (Jonckheere)
  - Treatment rows get * / ** for pairwise test (Williams or Dunnett)
  - Endpoints not significant for BOTH trend + pairwise get "ND" for BMD/BMDL
  - Dose groups with no surviving animals get a dash and footnote

Usage:
    python apical_report.py <path_to.bm2> [--output report.docx]

    # Or import and use programmatically:
    from apical_report import generate_report
    generate_report("path/to/file.bm2", "output.docx")
"""

import argparse
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

import bm2_cache
from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn

from apical_stats import analyze_endpoint, EndpointStats


# ---------------------------------------------------------------------------
# Constants — paths and configuration
# ---------------------------------------------------------------------------

# BMDExpress 3 project root — used to locate the JAR and build the classpath
BMDX_PROJECT = Path.home() / "Dev" / "Projects" / "BMDExpress-3"

# Maven repository root — JAR dependencies are cached here
M2_REPO = Path.home() / ".m2" / "repository"

# The compiled BMDExpress 3 JAR (not a fat JAR — needs classpath assembly)
BMDX_JAR = BMDX_PROJECT / "target" / "bmdexpress3-3.0.0-SNAPSHOT.jar"

# Font size for table cells (small to fit many dose columns)
TABLE_FONT_SIZE = 8

# Font size for table header cells
HEADER_FONT_SIZE = 8


# ---------------------------------------------------------------------------
# Classpath assembly — collect all JARs needed to run the BMDExpress CLI
# ---------------------------------------------------------------------------

def _build_classpath() -> str:
    """
    Assemble the Java classpath from the BMDExpress 3 JAR and its Maven
    dependencies.  The compiled JAR is NOT a fat JAR, so we need to find
    each dependency in the local Maven repository (~/.m2/repository/).

    Returns:
        Colon-separated classpath string suitable for java -cp.
    """
    jars = [str(BMDX_JAR)]

    # The lib/ directory has jfreechart-1.0.19-fx.jar
    lib_dir = BMDX_PROJECT / "lib"
    if lib_dir.exists():
        for jar in lib_dir.glob("*.jar"):
            jars.append(str(jar))

    # Known Maven dependencies and their repository paths
    # (groupId/artifactId/version/artifactId-version.jar)
    maven_deps = [
        "commons-cli/commons-cli/1.6.0/commons-cli-1.6.0.jar",
        "com/fasterxml/jackson/core/jackson-core/2.18.1/jackson-core-2.18.1.jar",
        "com/fasterxml/jackson/core/jackson-databind/2.18.1/jackson-databind-2.18.1.jar",
        "com/fasterxml/jackson/core/jackson-annotations/2.18.1/jackson-annotations-2.18.1.jar",
        "commons-io/commons-io/2.17.0/commons-io-2.17.0.jar",
        "org/apache/commons/commons-math3/3.6.1/commons-math3-3.6.1.jar",
        "org/apache/commons/commons-lang3/3.17.0/commons-lang3-3.17.0.jar",
        "gov/nist/math/jama/1.0.3/jama-1.0.3.jar",
    ]

    for dep in maven_deps:
        full_path = M2_REPO / dep
        if full_path.exists():
            jars.append(str(full_path))

    # Dependencies with non-trivial paths — find them by glob
    glob_patterns = [
        ("sciome-commons", "*.jar"),
        ("org/slf4j", "slf4j-api-1.7.36.jar"),
        ("ch/qos/logback", "logback-classic-1.2.11.jar"),
        ("ch/qos/logback", "logback-core-1.2.11.jar"),
        ("com/google/guava", "guava-33.3.1-jre.jar"),
        ("org/jfree", "jfreechart-1.5.0.jar"),
        ("org/jfree", "jcommon-1.0.24.jar"),
        ("org/jfree", "jfreesvg-3.3.jar"),
        ("org/jeasy", "easy-rules-core-4.1.0.jar"),
        ("org/jeasy", "easy-rules-support-4.1.0.jar"),
    ]

    for subdir, pattern in glob_patterns:
        search_dir = M2_REPO / subdir
        if search_dir.exists():
            for jar in search_dir.rglob(pattern):
                jars.append(str(jar))

    return ":".join(jars)


# ---------------------------------------------------------------------------
# .bm2 export — single JVM launch via pre-compiled Java helper
# ---------------------------------------------------------------------------
# The old approach launched 3 JVMs:
#   1. javac to compile an inline Java source file
#   2. java to run the compiled class (JSON export)
#   3. java to run BMDExpressCommandLine (category TSV export)
#
# The new approach uses a pre-compiled ExportBm2.class that does both
# JSON + category TSV in a single JVM launch (~0.4s total vs ~15s before).
# The .class file lives at java/ExportBm2.class (compiled from java/ExportBm2.java).

# Path to the directory containing ExportBm2.class
JAVA_HELPER_DIR = Path(__file__).parent / "java"


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


# ---------------------------------------------------------------------------
# Category analysis BMD lookup — parse the TSV export
# ---------------------------------------------------------------------------

def build_category_lookup(tsv_path: str) -> dict[tuple[str, str], dict]:
    """
    Parse the BMDExpress category analysis TSV export into a lookup dict.

    The category analysis maps defined-category endpoints to their BMD
    results.  Each row represents one endpoint that passed all filters
    (R² threshold, BMDU/BMDL ratio, confidence level).

    The key is (experiment_prefix, endpoint_name), matching how we identify
    endpoints in the dose-response data.

    Args:
        tsv_path: Path to the category analysis TSV export.

    Returns:
        Dict mapping (experiment_prefix, endpoint_name) → {bmd, bmdl, bmdu, ...}
    """
    lookup = {}
    with open(tsv_path) as f:
        lines = [line for line in f.readlines() if line.strip()]

    reader = csv.DictReader(lines, delimiter="\t")
    for row in reader:
        analysis = row.get("Analysis", "")
        endpoint = row.get("GO/Pathway/Gene Set/Gene Name", "")

        # The analysis name looks like:
        #   BodyWeightFemale_BMD_null_DEFINED-Category File-..._true_rsquared0.6_...
        # We need the prefix before "_BMD" to match against experiment names
        prefix = analysis.split("_BMD")[0]

        lookup[(prefix, endpoint)] = {
            "bmd": row.get("BMD Mean", ""),
            "bmdl": row.get("BMDL Mean", ""),
            "bmdu": row.get("BMDU Mean", ""),
            "category_id": row.get("GO/Pathway/Gene Set/Gene ID", ""),
            "direction": row.get("Overall Direction", ""),
            "fold_change": row.get("Max Fold Change", ""),
        }

    return lookup


# ---------------------------------------------------------------------------
# Data assembly — combine stats + category analysis into table-ready data
# ---------------------------------------------------------------------------

@dataclass
class TableRow:
    """
    One row of the final report table — represents a single endpoint
    (e.g., "Liver Weight Relative") for one sex.

    Attributes:
        label:          Display label for the endpoint column
        values_by_dose: Dict mapping dose → formatted string ("mean ± SE**")
        n_by_dose:      Dict mapping dose → sample size (for the n row)
        bmd_str:        Formatted BMD value or "ND"
        bmdl_str:       Formatted BMDL value or "ND"
        trend_marker:   "*" or "**" or "" — for the control column
    """
    label: str = ""
    values_by_dose: dict = field(default_factory=dict)
    n_by_dose: dict = field(default_factory=dict)
    bmd_str: str = "ND"
    bmdl_str: str = "ND"
    trend_marker: str = ""


def build_table_data(
    bm2_json: dict,
    category_lookup: dict,
) -> dict[str, list[TableRow]]:
    """
    Build the table data for all endpoints, organized by sex.

    For each endpoint:
      1. Run NTP statistical tests (Jonckheere → Williams/Dunnett)
      2. Check if endpoint appears in category analysis
      3. Apply business rule: report BMD only if BOTH trend + pairwise sig
      4. Format mean ± SE with significance markers for each dose group

    Args:
        bm2_json:        Parsed JSON from the .bm2 export.
        category_lookup: Dict from build_category_lookup().

    Returns:
        Dict mapping sex label ("Male" / "Female") → list of TableRow.
        Each list is ordered: body weight endpoints first, then organ
        weight endpoints.
    """
    tables: dict[str, list[TableRow]] = {}

    for exp in bm2_json.get("doseResponseExperiments", []):
        exp_name = exp.get("name", "")
        treatments = exp.get("treatments", [])
        treat_doses = {i: t["dose"] for i, t in enumerate(treatments)}

        # Determine sex from experiment name
        if "Female" in exp_name:
            sex = "Female"
        elif "Male" in exp_name:
            sex = "Male"
        else:
            sex = "Unknown"

        if sex not in tables:
            tables[sex] = []

        for pr in exp.get("probeResponses", []):
            probe_name = pr["probe"]["id"]
            responses = pr["responses"]

            # Group responses by dose
            groups_by_dose: dict[float, list[float]] = {}
            for i, val in enumerate(responses):
                dose = treat_doses[i]
                groups_by_dose.setdefault(dose, []).append(val)

            # Run the NTP statistical analysis
            stats = analyze_endpoint(exp_name, probe_name, groups_by_dose)

            # Check category analysis for BMD/BMDL
            cat = category_lookup.get((exp_name, probe_name))

            # Business rule: report BMD only if stats say so AND category
            # analysis has the value
            if stats.report_bmd and cat:
                try:
                    bmd_val = float(cat["bmd"])
                    bmdl_val = float(cat["bmdl"])
                    bmd_str = _format_bmd(bmd_val)
                    bmdl_str = _format_bmd(bmdl_val)
                except (ValueError, KeyError):
                    bmd_str = "ND"
                    bmdl_str = "ND"
            else:
                bmd_str = "ND"
                bmdl_str = "ND"

            # Build the formatted values for each dose group
            sorted_doses = sorted(groups_by_dose.keys())
            values_by_dose = {}
            n_by_dose = {}

            for dose in sorted_doses:
                n = stats.n_per_dose[dose]
                mean = stats.mean_per_dose[dose]
                se = stats.se_per_dose[dose]
                n_by_dose[dose] = n

                # Format: "mean ± SE" with significance marker
                if dose == stats.control_dose:
                    marker = stats.trend_marker
                else:
                    marker = stats.pairwise_marker.get(dose, "")

                if se > 0:
                    values_by_dose[dose] = f"{mean:.1f} ± {se:.1f}{marker}"
                else:
                    values_by_dose[dose] = f"{mean:.1f}{marker}"

            row = TableRow(
                label=probe_name,
                values_by_dose=values_by_dose,
                n_by_dose=n_by_dose,
                bmd_str=bmd_str,
                bmdl_str=bmdl_str,
                trend_marker=stats.trend_marker,
            )
            tables[sex].append(row)

    return tables


def _format_bmd(value: float) -> str:
    """
    Format a BMD or BMDL value for display in the report table.

    Uses fixed-point notation with 3 significant figures, matching the
    precision level in NTP reports.

    Args:
        value: BMD or BMDL value (in dose units, e.g., mg/kg).

    Returns:
        Formatted string, e.g., "8.492" or "0.00679".
    """
    if value == 0:
        return "0"
    # Use 3 significant figures
    return f"{value:.3g}"


# ---------------------------------------------------------------------------
# Narrative generation — auto-generate NTP-style prose from table data
# ---------------------------------------------------------------------------
# These helpers and the main generate_results_narrative() function produce
# the "Results" paragraphs that appear between the section heading and the
# tables in an NTP subchronic study report.  The prototype structure comes
# from the PFHxSAm study report:
#   - Paragraph about body weight findings
#   - Paragraphs about organ weight findings per sex (significant + non-sig)
# Clinical observations (paragraph 1 in real reports) must be user-supplied
# since that data isn't in the .bm2 file.

def _parse_cell_mean(cell_text: str) -> float | None:
    """
    Extract the numeric mean from a formatted table cell value.

    Table cells look like "330.2 ± 5.1**" — this function pulls out
    the leading number (330.2) and ignores the SE and significance markers.

    Args:
        cell_text: Formatted cell string, e.g., "330.2 ± 5.1**".

    Returns:
        The mean as a float, or None if parsing fails.
    """
    if not cell_text or cell_text.strip() == "–":
        return None
    # Match the leading number (possibly negative, with decimal)
    match = re.match(r"(-?\d+\.?\d*)", cell_text.strip())
    if match:
        return float(match.group(1))
    return None


def _lowest_sig_dose(row: TableRow) -> float | None:
    """
    Find the lowest non-control dose group that has pairwise significance.

    Significance is indicated by * or ** appended to the cell value.
    The control dose (0.0) is excluded because its marker represents the
    trend test, not pairwise comparison.

    Args:
        row: A TableRow with values_by_dose containing formatted strings.

    Returns:
        The lowest dose (float) with a pairwise significance marker,
        or None if no treatment dose is significant.
    """
    sorted_doses = sorted(row.values_by_dose.keys())
    for dose in sorted_doses:
        # Skip control — its marker is for the trend test (Jonckheere)
        if dose == 0.0:
            continue
        val = row.values_by_dose.get(dose, "")
        if "*" in val:
            return dose
    return None


def _endpoint_direction(row: TableRow) -> str:
    """
    Determine whether an endpoint increased or decreased relative to control.

    Compares the control group mean to the highest-dose group mean.  This
    is a simplification — real studies might have non-monotonic responses —
    but it matches the NTP report convention of reporting the overall
    direction of the dose-response.

    Args:
        row: A TableRow with values_by_dose.

    Returns:
        "increase" or "decrease".
    """
    sorted_doses = sorted(row.values_by_dose.keys())
    if len(sorted_doses) < 2:
        return "increase"  # fallback

    control_mean = _parse_cell_mean(row.values_by_dose.get(sorted_doses[0], ""))
    highest_mean = _parse_cell_mean(row.values_by_dose.get(sorted_doses[-1], ""))

    if control_mean is None or highest_mean is None:
        return "increase"  # fallback

    return "decrease" if highest_mean < control_mean else "increase"


def _fmt_dose(dose: float) -> str:
    """
    Format a dose value for prose output.

    Drops trailing ".0" for integer-valued doses to match natural writing
    style:  12.0 → "12", 0.15 → "0.15".

    Args:
        dose: Dose value in dose units.

    Returns:
        Clean string representation.
    """
    if dose == int(dose):
        return str(int(dose))
    return str(dose)


def _parse_organ_label(label: str) -> tuple[str, str]:
    """
    Parse an endpoint label into (organ_name, weight_type).

    The .bm2 endpoint labels follow patterns like:
        "Liver Absolute"       → ("Liver", "absolute")
        "Liver Weight Relative" → ("Liver", "relative")
        "R. Kidney Absolute"   → ("R. Kidney", "absolute")
        "Kidney-Left Absolute" → ("Kidney-Left", "absolute")
        "Terminal Body Wt."    → ("", "body_weight")
        "Body Weight"          → ("", "body_weight")
        "Body Weight Gain"     → ("", "body_weight")
        "SD5"                  → ("", "body_weight")   # Study Day 5 terminal wt
        "Alanine aminotransferase" → ("Alanine aminotransferase", "endpoint")

    The organ_name is used to group absolute/relative pairs when
    describing organ weight findings in prose.  The "endpoint" type
    is for clinical pathology or other non-weight endpoints — their
    narrative prose omits the word "weight".

    Args:
        label: The endpoint label string from the TableRow.

    Returns:
        A 2-tuple (organ_name, weight_type) where weight_type is one of:
        "absolute", "relative", "body_weight", or "endpoint".
    """
    lower = label.lower()

    # Body weight endpoints — various naming conventions from BMDExpress
    if "body" in lower and ("wt" in lower or "weight" in lower):
        return ("", "body_weight")

    # "SD5", "SD 5", etc. — Study Day N terminal body weight labels.
    # BMDExpress uses these short codes for the terminal body weight
    # measurement at the end of a 5-day study.
    if re.match(r"^sd\s*\d+$", lower):
        return ("", "body_weight")

    # Organ weight endpoints — last word is "Absolute" or "Relative".
    # Also strip redundant "Weight" from the organ name so we get
    # "Liver" instead of "Liver Weight" (avoids "Liver Weight relative
    # weight" double-weight in prose).
    if lower.endswith("absolute"):
        organ = label[:-len("Absolute")].strip()
        # Strip trailing "Weight" / "Wt" / "Wt." from organ name
        organ = re.sub(r"\s+(?:Weight|Wt\.?)$", "", organ, flags=re.IGNORECASE)
        return (organ, "absolute")
    elif lower.endswith("relative"):
        organ = label[:-len("Relative")].strip()
        organ = re.sub(r"\s+(?:Weight|Wt\.?)$", "", organ, flags=re.IGNORECASE)
        return (organ, "relative")

    # Fallback: clinical pathology or other non-weight endpoints.
    # Marked as "endpoint" so the narrative generator can omit the
    # word "weight" from prose (e.g., "ALT was significantly increased"
    # rather than "ALT absolute weight was significantly increased").
    return (label, "endpoint")


def _oxford_comma(items: list[str], conjunction: str = "or") -> str:
    """
    Join a list of strings with an Oxford comma.

    Follows the NTP report convention:
        []            → ""
        ["a"]         → "a"
        ["a", "b"]    → "a or b"
        ["a", "b", "c"] → "a, b, or c"

    Args:
        items:       List of strings to join.
        conjunction: The conjunction word ("or", "and").

    Returns:
        The joined string with Oxford comma formatting.
    """
    if len(items) == 0:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conjunction} {items[1]}"
    return ", ".join(items[:-1]) + f", {conjunction} {items[-1]}"


def generate_results_narrative(
    table_data: dict[str, list[TableRow]],
    compound_name: str,
    dose_unit: str = "mg/kg",
    start_table_num: int = 1,
) -> list[str]:
    """
    Auto-generate NTP-style results narrative paragraphs from table data.

    Produces the prose that appears between the section heading and the
    statistical tables in an NTP report.  Follows the structure of the
    PFHxSAm prototype:

      1. Body weight paragraph (significant or not, per sex)
      2+ Organ weight paragraphs per sex (significant endpoints with
         BMD/BMDL, then non-significant endpoint list)

    Clinical observations (animal condition, mortality) are NOT generated
    here because that data isn't in the .bm2 file — those are user-supplied.

    Args:
        table_data:      Dict mapping sex label ("Male"/"Female") → list of
                         TableRow, as returned by build_table_data().
        compound_name:   Chemical name for use in prose.
        dose_unit:       Dose unit string (e.g., "mg/kg").
        start_table_num: Starting table number for cross-references.

    Returns:
        A list of paragraph strings, ready for insertion into the .docx
        or display in the UI textarea.
    """
    paragraphs = []

    # ---------------------------------------------------------------
    # Body weight paragraph — look for body weight rows across sexes
    # ---------------------------------------------------------------
    # Collect body weight findings for each sex to build a single paragraph
    bw_findings = []  # list of per-sex description strings
    table_num = start_table_num  # track which table number each sex maps to

    # We need the table number for each sex to reference in prose
    sex_table_num = {}
    tnum = start_table_num
    for sex in ["Male", "Female"]:
        if sex in table_data and table_data[sex]:
            sex_table_num[sex] = tnum
            tnum += 1

    for sex in ["Male", "Female"]:
        rows = table_data.get(sex, [])
        bw_rows = [r for r in rows if _parse_organ_label(r.label)[1] == "body_weight"]

        for bw_row in bw_rows:
            tbl_ref = sex_table_num.get(sex, start_table_num)
            if bw_row.bmd_str == "ND":
                # Not significant — report as such
                bw_findings.append(
                    f"{sex.lower()} rats (Table {tbl_ref})"
                )
            else:
                # Significant — report direction, lowest sig dose, trend, BMD
                direction = _endpoint_direction(bw_row)
                low_dose = _lowest_sig_dose(bw_row)
                # Trend direction label for prose
                trend_dir = "positive" if direction == "increase" else "negative"

                parts = []
                parts.append(
                    f"Terminal body weight was significantly "
                    f"{'increased' if direction == 'increase' else 'decreased'} "
                    f"in {sex.lower()} rats"
                )
                if low_dose is not None:
                    parts.append(
                        f" at ≥{_fmt_dose(low_dose)} {dose_unit}"
                    )
                parts.append(
                    f" with a {trend_dir} trend "
                    f"(Table {tbl_ref}). "
                    f"The BMD and BMDL were {bw_row.bmd_str} and "
                    f"{bw_row.bmdl_str} {dose_unit}, respectively."
                )
                bw_findings.append("".join(parts))

    # Build the body weight paragraph
    if bw_findings:
        # Check if ALL findings are non-significant (just table refs)
        all_nd = all("Table" in f and f.startswith(("male", "female"))
                     for f in bw_findings)
        if all_nd:
            # All non-significant — single sentence
            sex_refs = _oxford_comma(bw_findings, conjunction="or")
            paragraphs.append(
                f"No significant changes in terminal body weight for "
                f"{sex_refs} occurred with exposure to {compound_name}."
            )
        else:
            # At least one significant — join the individual findings
            paragraphs.append(" ".join(bw_findings))

    # ---------------------------------------------------------------
    # Organ weight paragraphs — one block per sex
    # ---------------------------------------------------------------
    for sex in ["Male", "Female"]:
        rows = table_data.get(sex, [])
        if not rows:
            continue

        tbl_ref = sex_table_num.get(sex, start_table_num)

        # Separate non-body-weight rows (organ weights + clinical endpoints)
        organ_rows = [r for r in rows if _parse_organ_label(r.label)[1] != "body_weight"]
        if not organ_rows:
            continue

        # Detect whether this section is organ weights or clinical pathology.
        # If ANY row has "absolute" or "relative" type, it's an organ weight
        # section.  Otherwise it's clinical pathology / generic endpoints.
        all_types = {_parse_organ_label(r.label)[1] for r in organ_rows}
        is_organ_section = bool(all_types & {"absolute", "relative"})

        # Split into significant (BMD reported) and non-significant (BMD = "ND")
        sig_rows = [r for r in organ_rows if r.bmd_str != "ND"]
        nonsig_rows = [r for r in organ_rows if r.bmd_str == "ND"]

        if not sig_rows:
            # No significant findings for this sex
            endpoint_noun = "organ weights" if is_organ_section else "endpoints"
            paragraphs.append(
                f"In {sex.lower()} rats at study termination, there were no "
                f"{endpoint_noun} that exhibited significant trend and pairwise "
                f"comparisons (Table {tbl_ref})."
            )
            continue

        # Group significant rows by organ/endpoint name so we can pair
        # absolute/relative for organ weights, or list individual clinical
        # pathology endpoints
        organ_groups: dict[str, list[TableRow]] = {}
        for r in sig_rows:
            organ_name, wtype = _parse_organ_label(r.label)
            organ_groups.setdefault(organ_name, []).append(r)

        # Build per-organ/endpoint finding descriptions
        sex_findings = []
        for organ_name, group_rows in organ_groups.items():
            # Determine direction from the first row (abs and rel should agree)
            direction = _endpoint_direction(group_rows[0])
            dir_word = "increased" if direction == "increase" else "decreased"
            trend_dir = "positive" if direction == "increase" else "negative"

            # Find lowest pairwise-significant dose across the group
            low_doses = [_lowest_sig_dose(r) for r in group_rows]
            low_doses = [d for d in low_doses if d is not None]
            min_low_dose = min(low_doses) if low_doses else None

            # Determine weight types present in this group
            weight_types = []
            for r in group_rows:
                _, wt = _parse_organ_label(r.label)
                weight_types.append(wt)

            # Collect BMD/BMDL values, qualifying with weight type only
            # for organ weight endpoints (not clinical pathology)
            bmd_parts = []
            for r in group_rows:
                _, wt = _parse_organ_label(r.label)
                if wt in ("absolute", "relative"):
                    bmd_parts.append(
                        f"{r.bmd_str} and {r.bmdl_str} {dose_unit} "
                        f"({wt} weight)"
                    )
                else:
                    bmd_parts.append(
                        f"{r.bmd_str} and {r.bmdl_str} {dose_unit}"
                    )

            # Compose the finding sentence — phrasing differs between
            # organ weight endpoints ("liver relative weight was...") and
            # clinical pathology endpoints ("ALT was...").
            has_weight_types = any(
                wt in ("absolute", "relative") for wt in weight_types
            )
            if has_weight_types:
                # Organ weight: "Liver absolute and relative weight was..."
                wt_type_str = _oxford_comma(
                    sorted(set(wt for wt in weight_types
                               if wt in ("absolute", "relative"))),
                    conjunction="and",
                )
                finding = (
                    f"{organ_name} {wt_type_str} weight was significantly "
                    f"{dir_word}"
                )
            else:
                # Clinical pathology / generic: "ALT was significantly..."
                finding = (
                    f"{organ_name} was significantly {dir_word}"
                )

            if min_low_dose is not None:
                finding += f" at ≥{_fmt_dose(min_low_dose)} {dose_unit}"
            finding += f" with a {trend_dir} trend"

            # Add BMD/BMDL
            if len(bmd_parts) == 1:
                finding += (
                    f". The BMD and BMDL were {bmd_parts[0]}, respectively."
                )
            else:
                finding += (
                    ". The BMD and BMDL were "
                    + "; ".join(bmd_parts)
                    + ", respectively."
                )

            sex_findings.append(finding)

        # Opening line for significant findings
        sex_para = (
            f"In {sex.lower()} rats at study termination (Table {tbl_ref}), "
        )
        sex_para += " ".join(sex_findings)

        # Non-significant endpoints listed at the end
        if nonsig_rows:
            nonsig_labels = [r.label.lower() for r in nonsig_rows]
            nonsig_str = _oxford_comma(nonsig_labels, conjunction="or")
            sex_para += (
                f" Significant trend and pairwise comparisons were not "
                f"observed in {nonsig_str}."
            )

        paragraphs.append(sex_para)

    return paragraphs


# ---------------------------------------------------------------------------
# .docx table generation — build the Word document tables
# ---------------------------------------------------------------------------

def _set_cell_text(cell, text: str, bold: bool = False, size: int = TABLE_FONT_SIZE):
    """
    Set the text of a Word table cell with consistent formatting.

    Clears any existing content, sets font to Calibri at the specified
    size, and optionally makes it bold.  Also sets minimal paragraph
    spacing for compact tables.

    Args:
        cell:  The docx table cell to modify.
        text:  The text to display.
        bold:  Whether to make the text bold.
        size:  Font size in points (default TABLE_FONT_SIZE).
    """
    cell.text = ""
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(1)
    run = p.add_run(str(text))
    run.font.size = Pt(size)
    run.font.name = "Calibri"
    run.bold = bold


def generate_table(
    doc: Document,
    sex: str,
    rows: list[TableRow],
    table_number: int,
    compound_name: str,
    dose_unit: str = "mg/kg",
    table_caption_template: str = (
        "Summary of Body Weights and Organ Weights "
        "of {sex} Rats Administered {compound} for Five Days"
    ),
) -> None:
    """
    Generate one NTP-style summary table in the Word document.

    Creates a table matching the PFHxSAm prototype format:
      - Title row with table number, compound name, and sex
      - Header row with "Endpoint" + dose columns + BMD/BMDL columns
      - "n" row showing sample sizes per dose group
      - One row per endpoint with mean ± SE and significance markers
      - Footnotes explaining significance markers and statistical methods

    Args:
        doc:                    The Document to add the table to.
        sex:                    "Male" or "Female".
        rows:                   List of TableRow objects for this sex.
        table_number:           Table number for the caption (e.g., 3).
        compound_name:          Chemical name for the caption.
        dose_unit:              Dose unit string (default "mg/kg").
        table_caption_template: Format string for the table caption.
                                Must contain {sex} and {compound} placeholders.
                                Default matches the NTP body/organ weight format.
    """
    if not rows:
        return

    # Get the dose groups from the first row (all rows share the same doses)
    sorted_doses = sorted(rows[0].values_by_dose.keys())

    # Column layout: Endpoint | dose_0 | dose_1 | ... | dose_n | BMD1Std | BMDL1Std
    n_cols = 1 + len(sorted_doses) + 2
    # Rows: header + n row + data rows
    n_rows = 1 + 1 + len(rows)

    # -- Table caption --
    caption = doc.add_paragraph()
    caption.paragraph_format.space_before = Pt(12)
    caption.paragraph_format.space_after = Pt(4)
    # Format the caption from the template, filling in sex and compound name
    caption_text = table_caption_template.format(
        sex=sex, compound=compound_name,
    )
    run = caption.add_run(f"Table {table_number}. {caption_text}")
    run.font.size = Pt(10)
    run.font.name = "Calibri"
    run.bold = True

    # -- Create the table --
    table = doc.add_table(rows=n_rows, cols=n_cols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # -- Header row --
    header_row = table.rows[0]
    _set_cell_text(header_row.cells[0], "Endpoint", bold=True, size=HEADER_FONT_SIZE)

    for i, dose in enumerate(sorted_doses):
        # Format dose column header: "0 mg/kg", "0.15 mg/kg", etc.
        if dose == 0:
            label = f"0 {dose_unit}"
        elif dose == int(dose):
            label = f"{int(dose)} {dose_unit}"
        else:
            label = f"{dose} {dose_unit}"
        _set_cell_text(header_row.cells[1 + i], label, bold=True, size=HEADER_FONT_SIZE)

    _set_cell_text(header_row.cells[-2], f"BMD1Std\n({dose_unit})", bold=True, size=HEADER_FONT_SIZE)
    _set_cell_text(header_row.cells[-1], f"BMDL1Std\n({dose_unit})", bold=True, size=HEADER_FONT_SIZE)

    # -- "n" row (sample sizes per dose group) --
    n_row = table.rows[1]
    _set_cell_text(n_row.cells[0], "n", bold=True, size=TABLE_FONT_SIZE)
    # Use the first data row's n values (they may vary slightly across
    # endpoints if some animals died, so we show the max across endpoints)
    for i, dose in enumerate(sorted_doses):
        # Find max n across all endpoints for this dose
        max_n = max(row.n_by_dose.get(dose, 0) for row in rows)
        _set_cell_text(n_row.cells[1 + i], str(max_n), size=TABLE_FONT_SIZE)
    _set_cell_text(n_row.cells[-2], "NA", size=TABLE_FONT_SIZE)
    _set_cell_text(n_row.cells[-1], "NA", size=TABLE_FONT_SIZE)

    # -- Data rows --
    for ri, row in enumerate(rows):
        tbl_row = table.rows[2 + ri]
        _set_cell_text(tbl_row.cells[0], row.label, bold=True, size=TABLE_FONT_SIZE)

        for i, dose in enumerate(sorted_doses):
            val = row.values_by_dose.get(dose, "–")
            _set_cell_text(tbl_row.cells[1 + i], val, size=TABLE_FONT_SIZE)

        _set_cell_text(tbl_row.cells[-2], row.bmd_str, size=TABLE_FONT_SIZE)
        _set_cell_text(tbl_row.cells[-1], row.bmdl_str, size=TABLE_FONT_SIZE)

    # -- Footnotes --
    footnotes = doc.add_paragraph()
    footnotes.paragraph_format.space_before = Pt(2)
    footnotes.paragraph_format.space_after = Pt(2)

    notes = [
        "* Statistically significant at p ≤ 0.05; ** p ≤ 0.01.",
        "Statistical analysis performed by Jonckheere (trend) and "
        "Williams or Dunnett (pairwise) tests.",
        "BMD1Std and BMDL1Std from BMDExpress 3 model averaging (defined "
        "category analysis).  ND = not determined (trend and/or pairwise "
        "significance criteria not met).",
    ]
    for note in notes:
        run = footnotes.add_run(note + "\n")
        run.font.size = Pt(8)
        run.font.name = "Calibri"
        run.italic = True

    doc.add_paragraph()  # spacing after table


# ---------------------------------------------------------------------------
# Main entry point — generate the full report
# ---------------------------------------------------------------------------

def build_table_data_from_bm2(
    bm2_path: str,
) -> tuple[dict[str, list[TableRow]], dict, dict]:
    """
    Convenience wrapper: export .bm2 → JSON + TSV, run stats, return
    (table_data, category_lookup, bm2_json).

    Handles the full export-and-analyze pipeline so callers don't need
    to manage temp files or know about the BMDExpress CLI.  This is
    steps 1–5 of the generate_report() pipeline extracted into a
    reusable function for the web server.

    Sidecar caching: the two expensive Java exports (full JSON + category
    TSV) are cached as files next to the .bm2 source:
      - {bm2_path}.json          — full BMDProject JSON
      - {bm2_path}.categories.tsv — category analysis TSV
    On subsequent calls for the same .bm2 file, the cached exports are
    read directly — zero JVM launches.  This means processing only
    happens once per .bm2 file per report project.

    Args:
        bm2_path: Path to the BMDExpress 3 .bm2 file.

    Returns:
        A 3-tuple:
          - table_data: Dict mapping sex label ("Male"/"Female") → list of
            TableRow, ready for generate_table() or add_apical_tables_to_doc().
          - category_lookup: Dict from build_category_lookup(), mapping
            (experiment_prefix, endpoint_name) → BMD info dict.
          - bm2_json: The full deserialized BMDProject as a dict — contains
            all 7 top-level lists (doseResponseExperiments, bMDResult,
            categoryAnalysisResults, oneWayANOVAResults, williamsTrendResults,
            curveFitPrefilterResults, oriogenResults) plus the project name.
            Preserved for file preview so users can inspect the complete
            .bm2 structure, not just the processed dose-response tables.
    """
    print(f"Processing: {bm2_path}")

    # Step 1: Load or export the full BMDProject structure.
    # The LMDB B-tree cache (bm2_cache module) stores deserialized dicts
    # keyed by file path.  After first access the OS page cache keeps the
    # LMDB pages hot, and orjson deserialization is ~10ms for a 5 MB dict.
    # On first call: run Java export → parse JSON → store in LMDB.
    # On subsequent calls: B-tree lookup + orjson.loads (no JVM, no file I/O).
    # Step 1 + 2: Try LMDB cache for both BMDProject JSON and category lookup.
    # If either is missing, we need to export — and with the unified Java
    # helper (ExportBm2.class), both come from a single JVM launch (~0.4s).
    bm2_json = bm2_cache.get_json(bm2_path)
    category_lookup = bm2_cache.get_categories(bm2_path)

    if bm2_json is not None and category_lookup is not None:
        print("  Loaded BMDProject + categories from LMDB cache")
    else:
        # Check for legacy pickle sidecars from before the LMDB migration.
        # If found, import them into LMDB and delete the pickle files.
        pkl_path = bm2_path + ".pkl"
        cat_pkl_path = bm2_path + ".categories.pkl"

        if bm2_json is None and os.path.exists(pkl_path):
            print("  Migrating BMDProject from pickle → LMDB...")
            import pickle
            with open(pkl_path, "rb") as f:
                bm2_json = pickle.load(f)
            bm2_cache.put_json(bm2_path, bm2_json)
            os.unlink(pkl_path)

        if category_lookup is None and os.path.exists(cat_pkl_path):
            print("  Migrating category analysis from pickle → LMDB...")
            import pickle
            with open(cat_pkl_path, "rb") as f:
                category_lookup = pickle.load(f)
            bm2_cache.put_categories(bm2_path, category_lookup)
            os.unlink(cat_pkl_path)

        # If either is still missing after migration, run the unified
        # Java export — one JVM launch produces both JSON + category TSV.
        if bm2_json is None or category_lookup is None:
            print("  Exporting .bm2 (single JVM launch — JSON + categories)...")
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp_json = tmp.name
            with tempfile.NamedTemporaryFile(suffix=".tsv", delete=False) as tmp:
                tmp_tsv = tmp.name

            export_bm2(bm2_path, tmp_json, tmp_tsv)

            if bm2_json is None:
                with open(tmp_json) as f:
                    bm2_json = json.load(f)
                bm2_cache.put_json(bm2_path, bm2_json)
            os.unlink(tmp_json)

            if category_lookup is None:
                category_lookup = build_category_lookup(tmp_tsv)
                bm2_cache.put_categories(bm2_path, category_lookup)
            os.unlink(tmp_tsv)

    print(f"  Category analysis: {len(category_lookup)} endpoints with BMD values")

    # Steps 3-5: Build table data (runs stats + cross-references + business rules).
    # This is pure Python (no JVM) and fast, so we always re-run it.
    print("  Running NTP statistical tests (Jonckheere → Williams/Dunnett)...")
    table_data = build_table_data(bm2_json, category_lookup)

    return table_data, category_lookup, bm2_json


def add_apical_tables_to_doc(
    doc: Document,
    table_data: dict[str, list[TableRow]],
    section_title: str,
    compound_name: str,
    dose_unit: str = "mg/kg",
    table_caption_template: str = (
        "Summary of Body Weights and Organ Weights "
        "of {sex} Rats Administered {compound} for Five Days"
    ),
    start_table_num: int = 1,
    narrative_paragraphs: list[str] | None = None,
) -> int:
    """
    Add apical endpoint tables to an existing Document object.

    This is the docx-building half of generate_report(), extracted so
    the web server can add NTP tables to a report document that already
    contains the background section paragraphs.

    Adds a section heading, optional narrative paragraphs (NTP-style prose
    describing body weight and organ weight findings), then one table per
    sex (Male, Female), each with its own caption, header row, n row, data
    rows, and footnotes.

    Args:
        doc:                    The Document to add tables to.
        table_data:             Dict mapping sex label → list of TableRow,
                                as returned by build_table_data_from_bm2().
        section_title:          Heading text for the section (e.g.,
                                "Animal Condition, Body Weights, and Organ Weights").
        compound_name:          Chemical name for table captions.
        dose_unit:              Dose unit for column headers (default "mg/kg").
        table_caption_template: Format string for per-table captions.  Must
                                contain {sex} and {compound} placeholders.
        start_table_num:        Starting table number (default 1).  Use this
                                when adding multiple .bm2 sections so table
                                numbers continue sequentially.
        narrative_paragraphs:   Optional list of prose paragraphs to insert
                                between the section heading and the first table.
                                These are the auto-generated (and possibly
                                user-edited) NTP-style results narrative.

    Returns:
        The next available table number (so multiple .bm2 files can be
        added sequentially with correct numbering).
    """
    # Section heading — parameterized so we can reuse for clinical pathology, etc.
    doc.add_heading(section_title, level=2)

    # Insert narrative paragraphs (if provided) between heading and tables.
    # These describe body weight and organ weight findings in NTP prose style.
    if narrative_paragraphs:
        for para_text in narrative_paragraphs:
            p = doc.add_paragraph()
            run = p.add_run(para_text)
            run.font.size = Pt(11)
            run.font.name = "Calibri"
            p.paragraph_format.space_after = Pt(6)

    # Generate one table per sex, in a consistent order
    table_num = start_table_num
    for sex in ["Male", "Female"]:
        rows = table_data.get(sex, [])
        if rows:
            generate_table(
                doc, sex, rows, table_num,
                compound_name=compound_name,
                dose_unit=dose_unit,
                table_caption_template=table_caption_template,
            )
            table_num += 1

            # Print summary to console for debugging / CLI usage
            for row in rows:
                sig_doses = sum(
                    1 for d, v in row.values_by_dose.items()
                    if "*" in v and d != 0.0
                )
                print(f"    {sex} / {row.label}: "
                      f"BMD={row.bmd_str}, BMDL={row.bmdl_str}, "
                      f"{sig_doses} sig dose groups")

    return table_num


# ---------------------------------------------------------------------------
# NIEHS report table helpers — BMD Summary, Gene Set BMD, Gene BMD
# ---------------------------------------------------------------------------
# These three functions add new table types to a .docx document, matching
# the structure of NIEHS Report 10 (PFHxSAm, NBK589955).  They are
# composable: the server calls them to assemble the full NIEHS-style
# report alongside the existing apical endpoint tables.

def _format_table_cell(cell, text: str, bold: bool = False, size: int = 8) -> None:
    """
    Set the text and formatting of a single table cell.

    This is a small helper to avoid repeating font-size / font-name /
    bold assignment on every cell.  Matches the formatting style used
    by generate_table() for visual consistency across all report tables.

    Args:
        cell:  A python-docx table cell object.
        text:  The string to display in the cell.
        bold:  Whether the text should be bold (for headers / sex rows).
        size:  Font size in points (default 8, matching TABLE_FONT_SIZE).
    """
    cell.text = str(text)
    for p in cell.paragraphs:
        for run in p.runs:
            run.font.size = Pt(size)
            run.font.name = "Calibri"
            run.bold = bold


def add_bmd_summary_table_to_doc(
    doc: Document,
    endpoints: list[dict],
    table_num: int,
    dose_unit: str = "mg/kg",
) -> int:
    """
    Add an Apical Endpoint BMD Summary table to the document.

    This table aggregates BMD, BMDL, LOEL, and NOEL across all apical
    endpoints (organ weights + clinical pathology), sorted by BMD from
    low to high.  It provides a single-glance overview of which endpoints
    were most sensitive.

    The table is split by sex: a "Male" header row followed by male
    endpoints, then a "Female" header row followed by female endpoints.
    Within each sex block, endpoints are sorted by BMD ascending.

    Matching NIEHS format:
      Caption: "BMD, BMDL, LOEL, and NOEL Summary for Apical Endpoints,
                Sorted by BMD or LOEL from Low to High."
      Columns: Endpoint | BMD1Std (unit) | BMDL1Std (unit) | LOEL (unit) |
               NOEL (unit) | Direction of Change

    Args:
        doc:        The Document to add the table to.
        endpoints:  List of endpoint dicts, each with keys:
                      endpoint (str), bmd (str/float), bmdl (str/float),
                      loel (str/float), noel (str/float), direction (str),
                      sex (str — "Male" or "Female").
        table_num:  The sequential table number for the caption.
        dose_unit:  Unit string for column headers (default "mg/kg").

    Returns:
        The next available table number (table_num + 1).
    """
    # Section heading
    doc.add_heading("Apical Endpoint BMD Summary", level=3)

    # Table caption — styled as italic paragraph before the table
    caption = (
        f"Table {table_num}. BMD, BMDL, LOEL, and NOEL Summary for "
        f"Apical Endpoints, Sorted by BMD or LOEL from Low to High."
    )
    cap_para = doc.add_paragraph()
    run = cap_para.add_run(caption)
    run.font.size = Pt(9)
    run.font.name = "Calibri"
    run.italic = True
    cap_para.paragraph_format.space_after = Pt(4)

    # Column headers
    headers = [
        "Endpoint",
        f"BMD₁Std ({dose_unit})",
        f"BMDL₁Std ({dose_unit})",
        f"LOEL ({dose_unit})",
        f"NOEL ({dose_unit})",
        "Direction of Change",
    ]

    # Split endpoints by sex for the grouped display
    male_eps = sorted(
        [e for e in endpoints if e.get("sex", "").lower() == "male"],
        key=lambda e: float(e.get("bmd", 9999)) if str(e.get("bmd", "ND")) != "ND" else 9999,
    )
    female_eps = sorted(
        [e for e in endpoints if e.get("sex", "").lower() == "female"],
        key=lambda e: float(e.get("bmd", 9999)) if str(e.get("bmd", "ND")) != "ND" else 9999,
    )

    # Calculate total rows: header + male sex row + male data + female sex row + female data
    n_rows = 1  # column header row
    if male_eps:
        n_rows += 1 + len(male_eps)    # "Male" row + data rows
    if female_eps:
        n_rows += 1 + len(female_eps)  # "Female" row + data rows

    if n_rows <= 1:
        # No endpoints to show — add a note and return
        p = doc.add_paragraph()
        run = p.add_run("No apical endpoints with BMD values available.")
        run.font.size = Pt(10)
        run.font.name = "Calibri"
        run.italic = True
        return table_num + 1

    table = doc.add_table(rows=n_rows, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Header row
    for i, header in enumerate(headers):
        _format_table_cell(table.rows[0].cells[i], header, bold=True, size=HEADER_FONT_SIZE)

    # Fill data rows, grouped by sex
    row_idx = 1

    for sex_label, sex_eps in [("Male", male_eps), ("Female", female_eps)]:
        if not sex_eps:
            continue

        # Sex header row — merged across all columns, bold
        for i in range(len(headers)):
            _format_table_cell(table.rows[row_idx].cells[i], sex_label if i == 0 else "", bold=True)
        row_idx += 1

        # Individual endpoint rows
        for ep in sex_eps:
            bmd_val = ep.get("bmd", "ND")
            bmdl_val = ep.get("bmdl", "ND")
            loel_val = ep.get("loel", "—")
            noel_val = ep.get("noel", "—")
            direction = ep.get("direction", "")

            # Format numeric values to reasonable precision
            def _fmt_val(v):
                if v is None or str(v) in ("ND", "—", ""):
                    return str(v) if v else "—"
                try:
                    return f"{float(v):.2f}"
                except (ValueError, TypeError):
                    return str(v)

            row_data = [
                ep.get("endpoint", ""),
                _fmt_val(bmd_val),
                _fmt_val(bmdl_val),
                _fmt_val(loel_val),
                _fmt_val(noel_val),
                direction,
            ]
            for i, val in enumerate(row_data):
                _format_table_cell(table.rows[row_idx].cells[i], val)
            row_idx += 1

    doc.add_paragraph()  # spacing after table
    return table_num + 1


def add_gene_set_bmd_tables_to_doc(
    doc: Document,
    gene_sets_data: list[dict],
    organ: str,
    sex: str,
    table_num: int,
    dose_unit: str = "mg/kg",
) -> int:
    """
    Add a Gene Set (GO Biological Process) BMD table to the document.

    Produces one table for a specific organ × sex combination (e.g.,
    "Liver Male").  The table shows the top 10 GO terms ranked by the
    median BMD of their member genes — lower median BMD means the gene
    set was perturbed at a lower dose (more potent).

    Matching NIEHS format:
      Caption: "Top 10 {Organ} Gene Ontology Biological Process Gene Sets
                Ranked by Potency of Perturbation, Sorted by Benchmark
                Dose Median ({Sex})"
      Columns: GO Term | GO ID | BMD Median (unit) | BMDL Median (unit) |
               # Genes | Direction

    Args:
        doc:             The Document to add the table to.
        gene_sets_data:  List of gene set dicts from rank_go_sets_by_bmd():
                           [{rank, go_id, go_term, bmd_median, bmdl_median,
                             n_genes, genes, direction}, ...]
        organ:           Organ name for the caption (e.g., "Liver").
        sex:             Sex label for the caption (e.g., "Male").
        table_num:       Sequential table number.
        dose_unit:       Unit string for column headers.

    Returns:
        The next available table number (table_num + 1).
    """
    # Section heading
    organ_title = organ.title()
    sex_title = sex.title()
    doc.add_heading(f"Gene Set Benchmark Dose Analysis — {organ_title} ({sex_title})", level=3)

    # Caption
    caption = (
        f"Table {table_num}. Top 10 {organ_title} Gene Ontology Biological "
        f"Process Gene Sets Ranked by Potency of Perturbation, Sorted by "
        f"Benchmark Dose Median ({sex_title})."
    )
    cap_para = doc.add_paragraph()
    run = cap_para.add_run(caption)
    run.font.size = Pt(9)
    run.font.name = "Calibri"
    run.italic = True
    cap_para.paragraph_format.space_after = Pt(4)

    if not gene_sets_data:
        p = doc.add_paragraph()
        run = p.add_run(f"No qualifying gene sets for {organ_title} ({sex_title}).")
        run.font.size = Pt(10)
        run.font.name = "Calibri"
        run.italic = True
        return table_num + 1

    headers = [
        "GO Term",
        "GO ID",
        f"BMD Median ({dose_unit})",
        f"BMDL Median ({dose_unit})",
        "# Genes",
        "Direction",
    ]

    table = doc.add_table(rows=1 + len(gene_sets_data), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Header row
    for i, header in enumerate(headers):
        _format_table_cell(table.rows[0].cells[i], header, bold=True, size=HEADER_FONT_SIZE)

    # Data rows
    for row_idx, gs in enumerate(gene_sets_data, 1):
        row_data = [
            gs.get("go_term", ""),
            gs.get("go_id", ""),
            f"{gs['bmd_median']:.3f}" if gs.get("bmd_median") is not None else "—",
            f"{gs['bmdl_median']:.3f}" if gs.get("bmdl_median") is not None else "—",
            str(gs.get("n_genes", 0)),
            gs.get("direction", ""),
        ]
        for i, val in enumerate(row_data):
            _format_table_cell(table.rows[row_idx].cells[i], val)

    doc.add_paragraph()  # spacing
    return table_num + 1


def add_gene_bmd_tables_to_doc(
    doc: Document,
    genes_data: list[dict],
    organ: str,
    sex: str,
    table_num: int,
    dose_unit: str = "mg/kg",
) -> int:
    """
    Add a Gene-level BMD table to the document.

    Produces one table for a specific organ × sex combination showing
    the top 10 individual genes ranked by BMD (most sensitive first).

    Matching NIEHS format:
      Caption: "Top 10 {Organ} Genes Ranked by Potency of Perturbation,
                Sorted by Benchmark Dose Median ({Sex})"
      Columns: Gene Symbol | Gene Name | BMD (unit) | BMDL (unit) |
               Fold Change | Direction

    Args:
        doc:          The Document to add the table to.
        genes_data:   List of gene dicts from rank_genes_by_bmd():
                        [{rank, gene_symbol, full_name, bmd, bmdl, bmdu,
                          direction, fold_change}, ...]
        organ:        Organ name for the caption.
        sex:          Sex label for the caption.
        table_num:    Sequential table number.
        dose_unit:    Unit string for column headers.

    Returns:
        The next available table number (table_num + 1).
    """
    organ_title = organ.title()
    sex_title = sex.title()
    doc.add_heading(f"Gene Benchmark Dose Analysis — {organ_title} ({sex_title})", level=3)

    # Caption
    caption = (
        f"Table {table_num}. Top 10 {organ_title} Genes Ranked by Potency "
        f"of Perturbation, Sorted by Benchmark Dose Median ({sex_title})."
    )
    cap_para = doc.add_paragraph()
    run = cap_para.add_run(caption)
    run.font.size = Pt(9)
    run.font.name = "Calibri"
    run.italic = True
    cap_para.paragraph_format.space_after = Pt(4)

    if not genes_data:
        p = doc.add_paragraph()
        run = p.add_run(f"No qualifying genes for {organ_title} ({sex_title}).")
        run.font.size = Pt(10)
        run.font.name = "Calibri"
        run.italic = True
        return table_num + 1

    headers = [
        "Gene Symbol",
        "Gene Name",
        f"BMD ({dose_unit})",
        f"BMDL ({dose_unit})",
        "Fold Change",
        "Direction",
    ]

    table = doc.add_table(rows=1 + len(genes_data), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Header row
    for i, header in enumerate(headers):
        _format_table_cell(table.rows[0].cells[i], header, bold=True, size=HEADER_FONT_SIZE)

    # Data rows
    for row_idx, gene in enumerate(genes_data, 1):
        fc = gene.get("fold_change")
        row_data = [
            gene.get("gene_symbol", ""),
            gene.get("full_name", ""),
            f"{gene['bmd']:.3f}" if gene.get("bmd") is not None else "—",
            f"{gene['bmdl']:.3f}" if gene.get("bmdl") is not None else "—",
            f"{fc:.2f}" if fc is not None else "—",
            gene.get("direction", ""),
        ]
        for i, val in enumerate(row_data):
            _format_table_cell(table.rows[row_idx].cells[i], val)

    doc.add_paragraph()  # spacing
    return table_num + 1


def generate_report(
    bm2_path: str,
    output_docx: str = "apical_report.docx",
    compound_name: str = "Test Compound",
    dose_unit: str = "mg/kg",
    section_title: str = "Animal Condition, Body Weights, and Organ Weights",
    table_caption_template: str = (
        "Summary of Body Weights and Organ Weights "
        "of {sex} Rats Administered {compound} for Five Days"
    ),
) -> str:
    """
    Generate the complete report section from a .bm2 file.

    Pipeline:
      1. Export .bm2 → JSON (full structure with dose-response data)
      2. Export .bm2 → TSV (category analysis results with BMD values)
      3. Run NTP statistical tests on each endpoint
      4. Cross-reference with category analysis for BMD/BMDL
      5. Apply business rules (both trend + pairwise required)
      6. Generate .docx with tables split by sex

    Internally delegates to build_table_data_from_bm2() for steps 1-5
    and add_apical_tables_to_doc() for step 6.  The CLI entry point
    calls this function, while the web server calls the helpers directly
    to compose tables into a larger report document.

    Args:
        bm2_path:               Path to the BMDExpress 3 .bm2 file.
        output_docx:            Path for the output Word document.
        compound_name:          Chemical name for table captions.
        dose_unit:              Dose unit for column headers and BMD columns.
        section_title:          Heading text for the report section.
                                Default: "Animal Condition, Body Weights, and
                                Organ Weights".
        table_caption_template: Format string for per-table captions.  Must
                                contain {sex} and {compound} placeholders.
                                Default matches the NTP body/organ weight format.

    Returns:
        Path to the generated .docx file.
    """
    # Steps 1-5: export .bm2 and build table data
    table_data, _category_lookup, _bm2_json = build_table_data_from_bm2(bm2_path)

    # Step 6: Generate .docx using the composable helper
    print("  Generating .docx...")
    doc = Document()

    add_apical_tables_to_doc(
        doc,
        table_data,
        section_title=section_title,
        compound_name=compound_name,
        dose_unit=dose_unit,
        table_caption_template=table_caption_template,
    )

    doc.save(output_docx)
    print(f"\nSaved: {output_docx}")
    return output_docx


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Generate NTP-style apical endpoint report from a .bm2 file. "
            "Works for body/organ weights, clinical pathology, or any other "
            "apical endpoint type — use --section-title and --table-caption "
            "to customize headings."
        ),
    )
    parser.add_argument(
        "bm2_path",
        help="Path to the BMDExpress 3 .bm2 file",
    )
    parser.add_argument(
        "--output", "-o",
        default="apical_report.docx",
        help="Output .docx path (default: apical_report.docx)",
    )
    parser.add_argument(
        "--compound", "-c",
        default="Test Compound",
        help="Compound name for table captions",
    )
    parser.add_argument(
        "--dose-unit", "-u",
        default="mg/kg",
        help="Dose unit for column headers (default: mg/kg)",
    )
    parser.add_argument(
        "--section-title",
        default="Animal Condition, Body Weights, and Organ Weights",
        help=(
            "Section heading in the report "
            "(default: 'Animal Condition, Body Weights, and Organ Weights')"
        ),
    )
    parser.add_argument(
        "--table-caption",
        default=(
            "Summary of Body Weights and Organ Weights "
            "of {sex} Rats Administered {compound} for Five Days"
        ),
        help=(
            "Table caption template with {sex} and {compound} placeholders "
            "(default: 'Summary of Body Weights and Organ Weights of {sex} "
            "Rats Administered {compound} for Five Days')"
        ),
    )

    args = parser.parse_args()
    generate_report(
        args.bm2_path,
        output_docx=args.output,
        compound_name=args.compound,
        dose_unit=args.dose_unit,
        section_title=args.section_title,
        table_caption_template=args.table_caption,
    )
