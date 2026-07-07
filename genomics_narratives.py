"""
Shared assembler for Gene Set / Gene BMD body narratives.

Both the PDF export path (`report_data.marshal_export_data`) and the
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
consumer that doesn't yet understand the per-organ structure (older
session round-trips) still gets a sensible prose block.
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

    def _walk_table_numbers(n):
        if n.table_number is not None:
            nums.append(n.table_number)
        for c in n.children:
            _walk_table_numbers(c)

    _walk_table_numbers(node)
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


# ---------------------------------------------------------------------------
# Helper: aggregate per-(organ, sex) LLM narratives into per-organ paragraphs
# ---------------------------------------------------------------------------
# The LLM tier (`generate_genomics_narrative_async`) produces a separate
# Gene Set + Gene BMD narrative for EACH organ×sex.  Three call sites need to
# fold those per-sex results into ONE ordered paragraph list per organ —
# male block first, then female — with a "Male:" / "Female:" label prefixed
# on the first paragraph of each sex so the reader can tell the blocks apart:
#
#   * process_integrated.py  (Layer 3.5a, fresh generation during a run)
#   * session_routes.py      (session reload, rebuilt from interpretation caches)
#   * llm_routes.py          (the per-organ Regenerate endpoint)
#
# That fold-and-prefix loop, plus the "user override wins" merge, was copied
# verbatim into all three.  This shared helper is the single source of truth
# so any future change to the labelling, sex ordering, or override precedence
# happens in one place and stays observable in every path at once (the same
# discipline that motivated `build_genomics_body_narratives` above).

# Sexes are emitted in this fixed order so the prose reads male-then-female
# regardless of the dict insertion order of the per-organ bundle.
_SEX_ORDER: tuple[str, ...] = ("male", "female")


def interpretation_cache_prefix(organ: str, sex: str) -> str:
    """
    The filename prefix for an organ×sex genomics-narrative cache:
    `_cache_interpretation_{organ}_{sex}_`.  Append `{gene_hash}.json` for a
    specific file, or glob `{prefix}*.json` for every hash of that organ×sex.

    organ/sex are sanitized the same way the cache writer does — lower-cased
    with spaces turned to underscores — so the prefix produced here matches the
    files on disk regardless of how the caller capitalized or spaced the names.
    This is the single source of that naming convention: the writer, the
    exact-and-stale lookup, the cleanup glob (llm_routes) and the session-reload
    glob (session_routes) all build their path from this one helper, so they
    cannot drift on the prefix string.
    """
    organ_key = organ.lower().replace(" ", "_")
    sex_key = sex.lower().replace(" ", "_")
    return f"_cache_interpretation_{organ_key}_{sex_key}_"


def aggregate_organ_llm_narratives(
    per_organ_bundles: dict[str, dict[str, dict[str, list[str]]]],
    overrides: dict[str, dict[str, list[str]]] | None = None,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """
    Fold per-(organ, sex) LLM narratives into per-organ paragraph lists.

    Inputs
    ------
    per_organ_bundles:
        {organ_lower: {sex_lower: {"gs": [paras...], "gn": [paras...]}}}.
        "gs" is the Gene Set narrative, "gn" the Gene BMD narrative, each an
        ordered list of paragraph strings for that one organ×sex.
    overrides:
        Optional user-edited paragraphs that WIN over the LLM output, shaped
        {"gene_set": {organ_lower: [paras...]}, "gene_bmd": {organ_lower:
        [paras...]}}.  A non-empty list for an organ replaces the aggregated
        LLM result for that organ entirely; an empty/absent entry leaves the
        LLM result in place.  Pass None to skip the override merge (e.g. the
        Regenerate path, which deliberately discards prior edits upstream).

    Returns
    -------
    (gs_by_organ, gn_by_organ):
        Two dicts {organ_lower: [paragraph strings]} — the Gene Set and Gene
        BMD narratives respectively, ready to drop into a narrative dict's
        `by_organ_llm` field.  Organs with no paragraphs are omitted.
    """
    gs_by_organ: dict[str, list[str]] = {}
    gn_by_organ: dict[str, list[str]] = {}

    for organ, by_sex in per_organ_bundles.items():
        gs_paras: list[str] = []
        gn_paras: list[str] = []
        for sex in _SEX_ORDER:
            block = by_sex.get(sex)
            if not block:
                continue
            # Prefix the first paragraph of each sex block with a "Male:" /
            # "Female:" label so a reader scanning the combined organ prose
            # can tell which sentences describe which sex.  We keep it inline
            # (no structural HTML) so the same string renders correctly in
            # both the HTML view and the LaTeX/PDF export.
            sex_label = sex.capitalize()
            if block.get("gs"):
                gs_paras.append(f"{sex_label}: " + block["gs"][0])
                gs_paras.extend(block["gs"][1:])
            if block.get("gn"):
                gn_paras.append(f"{sex_label}: " + block["gn"][0])
                gn_paras.extend(block["gn"][1:])
        if gs_paras:
            gs_by_organ[organ] = gs_paras
        if gn_paras:
            gn_by_organ[organ] = gn_paras

    # User overrides win: a stored paragraph list for an organ replaces the
    # aggregated LLM output entirely.  Organ keys are lower-cased to match the
    # aggregation keys regardless of how the override file cased them.
    if overrides:
        for organ, paras in (overrides.get("gene_set") or {}).items():
            if paras:
                gs_by_organ[organ.lower()] = paras
        for organ, paras in (overrides.get("gene_bmd") or {}).items():
            if paras:
                gn_by_organ[organ.lower()] = paras

    return gs_by_organ, gn_by_organ
