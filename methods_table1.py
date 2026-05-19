"""
Table 1 builder for the Materials & Methods section.

The Methods section has exactly one programmatic table — Table 1,
"Final Sample Counts for BMD Analysis of Transcriptomics Data."  It
appears only when gene-expression data is in the pool, and its rows
are per-(organ, sex, dose) sample counts derived from the
MethodsContext's genomics_sample_counts dict (which the extractor
populates from the animal report or gene-expression fingerprints).

Single public entry point:

  build_table1_data(ctx) -> dict | None

Returns None when there's no genomics data to tabulate, otherwise a
dict in the shape that the DOCX builder + the Typst template expect:
  {
    "caption":   str,
    "headers":   list[str],
    "rows":      list[list[str]],
    "footnotes": list[str],
  }

methods_report.py re-exports build_table1_data so external callers
(llm_routes uses it for the Preview Data path) keep working unchanged.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from __future__ import annotations

from methods_models import MethodsContext


# ---------------------------------------------------------------------------
# Table 1 builder
# ---------------------------------------------------------------------------

def build_table1_data(ctx: MethodsContext) -> dict | None:
    """
    Build Table 1: Final Sample Counts for BMD Analysis of Transcriptomics Data.

    This table shows the number of samples per organ × sex × dose group
    that passed QC and were included in the BMD analysis.

    Args:
        ctx: MethodsContext with genomics_sample_counts populated.

    Returns:
        Dict with keys: caption, headers, rows, footnotes.
        Or None if no genomics data.
    """
    if not ctx.genomics_sample_counts:
        return None

    # Headers: empty corner cell + dose group columns
    dose_headers = []
    for d in ctx.dose_groups:
        # Format: "0 mg/kg", "0.15 mg/kg", etc.
        if d == int(d):
            dose_headers.append(f"{int(d)} {ctx.dose_unit}")
        else:
            dose_headers.append(f"{d} {ctx.dose_unit}")

    headers = [""] + dose_headers

    # Rows: grouped by sex, then by organ
    rows = []
    all_sexes = sorted({
        sex
        for organ_data in ctx.genomics_sample_counts.values()
        for sex in organ_data
    })
    all_organs = sorted(ctx.genomics_sample_counts.keys())

    for sex in all_sexes:
        # Sex header row (bold — indicated by leading **)
        rows.append([f"**{sex}**"] + [""] * len(ctx.dose_groups))

        for organ in all_organs:
            sex_data = ctx.genomics_sample_counts.get(organ, {}).get(sex, {})
            row = [f"  {organ}"]
            for dose in ctx.dose_groups:
                count = sex_data.get(dose, 0)
                if count > 0:
                    row.append(str(count))
                else:
                    # Dash indicates no samples (mortality, exclusion, etc.)
                    row.append("–")
            rows.append(row)

    return {
        "caption": "Final Sample Counts for BMD Analysis of Transcriptomics Data",
        "headers": headers,
        "rows": rows,
        "footnotes": [],
    }


