"""
Shared assembler for Gene Set / Gene BMD body narratives.

Both the PDF export path (`report_pdf.marshal_export_data`) and the
in-app HTML path (`/api/process-integrated`) need to display the same
per-organ findings paragraphs above their respective tables.  Before
this module existed, the assembly logic lived inline inside
`marshal_export_data`, so the Typst template got the paragraphs but the
HTML client never did — the frontend silently omitted them.

Keeping a single assembler guarantees the two rendering paths stay in
lockstep: any future divergence (new sentence structure, extra filter
clause, different ordering) happens in one place and is observable in
both outputs at once.

The function is pure over the data it receives.  It does NOT read from
disk and does NOT know about sessions — callers prepare inputs from
whichever source they have (in-memory results during process-integrated;
on-disk caches during PDF export).

Output shape:

    {
        "gene_set_narrative": {
            "intros":     [p1, p2],                # methodology + caveat
            "by_organ":   {organ_lower: paragraph},# one per-organ para
            "paragraphs": [intros..., organ_paras...],  # flat form
        },
        "gene_narrative": { ... same structure ... },
    }

Either key is omitted when there is nothing to build (e.g., genomics
data is empty, or dose groups are missing so the LLE cutoff can't be
computed).

The "paragraphs" field is the flattened legacy shape — kept so any
consumer that doesn't yet understand the per-organ structure (DOCX
export, older session round-trips) still gets a sensible prose block.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from __future__ import annotations

from typing import Any

# The four prose builders live in methods_report.  Intros are organ-level
# boilerplate (methodology + caveat); findings are per-organ data-driven
# paragraphs.  Both are pure functions — no I/O.
from methods_report import (
    build_gene_set_body_intro,
    build_gene_set_body_findings,
    build_gene_body_intro,
    build_gene_body_findings,
)


# ---------------------------------------------------------------------------
# Helper: resolve table numbers from the document tree
# ---------------------------------------------------------------------------
# The intro paragraphs reference "Table 9 and Table 10" etc. — the actual
# numbers come from the tree walk (positional, auto-assigned).  The walk
# is done lazily because importing document_tree at module-load time
# creates a circular dependency during app startup.

def _collect_table_numbers(parent_id: str) -> list[int]:
    """
    Walk the subtree rooted at `parent_id` (e.g., "gene-sets" or
    "gene-bmd") and return the table numbers of every table-bearing
    descendant.  Returns an empty list if the node doesn't exist yet or
    no tables have been assigned numbers — the intro builders fall back
    to a generic "the tables below" phrasing in that case.
    """
    from document_tree import find_node, compute_table_numbers
    compute_table_numbers()
    node = find_node(parent_id)
    if not node:
        return []
    nums: list[int] = []

    def _walk(n):
        if n.table_number is not None:
            nums.append(n.table_number)
        for c in n.children:
            _walk(c)

    _walk(node)
    return nums


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_genomics_body_narratives(
    genomics_sections: dict | None,
    methods_context: dict | None,
    chemical_name: str | None,
) -> dict[str, dict[str, Any]]:
    """
    Build both Gene Set and Gene BMD body narratives from a genomics
    payload + methods context.

    Args:
        genomics_sections: The organ_sex-keyed dict produced by
                           `pool_orchestrator._extract_genomics` (also
                           persisted as `_cache_genomics_*.json`).  When
                           empty/None, returns an empty dict.
        methods_context:   The MethodsContext dict (see methods_report)
                           carrying dose_groups, dose_unit, ge_organs,
                           fold_change_filter.  When None, falls back to
                           deriving ge_organs from the section keys and
                           assumes mg/kg.  dose_groups absence means the
                           findings paragraphs can't be built (no LLE).
        chemical_name:     Used in the gene-set intro's methodology
                           sentence ("…most sensitive to {X} exposure.").

    Returns:
        Dict with up to two top-level keys — `gene_set_narrative` and
        `gene_narrative` — each holding `intros`, `by_organ`, and
        `paragraphs`.  Missing keys indicate that nothing could be built
        for that side (e.g., no dose groups).
    """
    # No genomics → nothing to build.  This is the normal case for
    # purely apical studies (no gene expression platform uploaded).
    if not genomics_sections:
        return {}

    # Pull study parameters from MethodsContext, with sensible fallbacks.
    # ge_organs drives the "…in the liver and kidney of rats…" phrase.
    ctx = methods_context or {}
    ge_organs = ctx.get("ge_organs") or []
    if not ge_organs:
        # Fall back: derive organs from the cache keys themselves, so an
        # older session without MethodsContext still renders sensibly.
        ge_organs = sorted({
            k.split("_", 1)[0].capitalize()
            for k in genomics_sections
            if "_" in k
        })

    dose_groups = ctx.get("dose_groups") or []
    dose_unit = ctx.get("dose_unit") or "mg/kg"
    fold_change_filter = ctx.get("fold_change_filter")
    chem_name = chemical_name or ctx.get("chemical_name") or "the test article"

    out: dict[str, dict[str, Any]] = {}

    # --- Gene Set BMD side (intro + per-organ findings) ---
    gs_table_numbers = _collect_table_numbers("gene-sets")
    gs_intros = build_gene_set_body_intro(
        chemical_name=chem_name,
        ge_organs=ge_organs,
        table_numbers=gs_table_numbers,
    )
    gs_by_organ = build_gene_set_body_findings(
        genomics_sections=genomics_sections,
        dose_groups=dose_groups,
        dose_unit=dose_unit,
    )
    # build_*_body_findings returns {} when dose_groups is empty; we
    # still emit the intro paragraphs so the section isn't entirely
    # silent, but skip by_organ (nothing to key on).
    out["gene_set_narrative"] = {
        "intros": gs_intros,
        "by_organ": gs_by_organ,
        "paragraphs": gs_intros + [
            gs_by_organ[o] for o in sorted(gs_by_organ.keys())
        ],
    }

    # --- Gene BMD side (symmetric structure) ---
    gn_table_numbers = _collect_table_numbers("gene-bmd")
    gn_intros = build_gene_body_intro(
        ge_organs=ge_organs,
        table_numbers=gn_table_numbers,
        fold_change_filter=fold_change_filter,
    )
    gn_by_organ = build_gene_body_findings(
        genomics_sections=genomics_sections,
        dose_groups=dose_groups,
        dose_unit=dose_unit,
    )
    out["gene_narrative"] = {
        "intros": gn_intros,
        "by_organ": gn_by_organ,
        "paragraphs": gn_intros + [
            gn_by_organ[o] for o in sorted(gn_by_organ.keys())
        ],
    }

    return out
