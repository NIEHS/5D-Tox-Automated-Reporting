"""
Sample-counts table builder for the Materials & Methods section.

The Methods section has exactly one programmatic table — the
"Final Sample Counts for BMD Analysis of Transcriptomics Data" table.  It
appears only when gene-expression data is in the pool, and its rows
are per-(organ, sex, dose) sample counts derived from the
MethodsContext's genomics_sample_counts dict (which the extractor
populates from the animal report or gene-expression fingerprints).

The table's position (and thus its report-facing number) is assigned by
the document-tree walk, never by this builder — so this module is named
for the content it produces, not a fixed table number.

Single public entry point:

  build_sample_counts_table(ctx) -> dict | None

Returns None when there's no genomics data to tabulate, otherwise a
dict in the shape the report renderers expect:
  {
    "caption":   str,
    "headers":   list[str],
    "rows":      list[list[str]],
    "footnotes": list[str],
  }

methods_report.py re-exports build_sample_counts_table so external callers
(llm_routes uses it for the Preview Data path) keep working unchanged.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from __future__ import annotations

import json
from pathlib import Path

from narrative.methods_models import MethodsContext


# ---------------------------------------------------------------------------
# Sample-counts table builder
# ---------------------------------------------------------------------------

def build_sample_counts_table(ctx: MethodsContext) -> dict | None:
    """
    Build the Final Sample Counts for BMD Analysis of Transcriptomics Data table.

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


def build_sample_counts_from_context(
    methods_context: dict | None,
    session_dir: str | Path | None = None,
) -> dict | None:
    """
    Build the sample-counts matrix from a serialized MethodsContext, for the two
    tree-driven export paths (LaTeX load_session_data, web marshal_export_data).

    The document tree has a `sample-counts-table` node bound to
    data["sample_counts"]; this produces that value in the neutral
    {caption, headers, rows, footnotes} shape build_sample_counts_table returns.

    The context's genomics_sample_counts may be absent (a stale cache written
    before the counts were extracted).  When it is AND a session_dir is given,
    reconstruct the counts from that session's _fingerprints.json — the same
    source methods_extract._build_genomics_sample_counts uses — so an old
    session still gets Table 1.  Returns None when there is no genomics data to
    tabulate (no counts and nothing to reconstruct from).
    """
    if not methods_context:
        return None
    ctx = MethodsContext.from_dict(methods_context)
    if not ctx.genomics_sample_counts and session_dir is not None:
        from narrative.methods_extract import _build_genomics_sample_counts
        fingerprints = _load_session_fingerprints(session_dir)
        if fingerprints:
            ctx.genomics_sample_counts = _build_genomics_sample_counts(
                fingerprints, ctx.dose_groups,
            )
    return build_sample_counts_table(ctx)


def _load_session_fingerprints(session_dir: str | Path) -> dict:
    """Read a session's _fingerprints.json ({file_id: fingerprint-dict}), or {}
    if the file is absent/unreadable.  The stale-cache fallback for
    build_sample_counts_from_context."""
    path = Path(session_dir) / "_fingerprints.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


