"""
report_data_toc.py — Table-of-Contents and section-filter layer for the report.

Extracted from report_data.py: the two functions that operate on a fully
overlaid `data` dict to (a) build the manual Table of Contents / Tables list by
walking the document tree, and (b) strip the dict down to a single section for
per-subsection PDF/HTML previews.

marshal_export_data (report_data.py) calls both via function-local imports.
Neither function calls back into report_data — they only reach document_tree
and render_common — so there is no import cycle and this module needs no
top-level imports beyond what the functions pull in locally.
"""


# ---------------------------------------------------------------------------
# TOC entries builder — walks the document tree to build a manual Table of
# Contents for the tables-list preview mode.  The preview strips all body
# content so Typst's outline() has no headings to collect.  Instead, we
# pre-compute the TOC entries here and pass them as data, so the template
# can render a manual TOC with placeholder styling for incomplete sections.
# ---------------------------------------------------------------------------

def _strip_table_prefix(caption: str) -> str:
    """Drop a leading "Table N. " from a caption — the Tables-list numbering adds
    its own "Table N." label, so the stored title is just the descriptive text."""
    import re
    return re.sub(r"^Table\s+\d+\.\s*", "", caption or "").strip()


def _table_list_title(node, data: dict) -> str:
    """The Tables-list title for a numbered table node: the FULL caption its body
    renders (chemical/species interpolated by the platform builder), with the
    "Table N." prefix stripped.  Falls back to node.title when no plan caption is
    available (scaffold render / node with no data), so the list is never blank.

    Reuses the SAME plan functions the renderers call, so the Tables list can't
    drift from the captions on the tables themselves."""
    from render_common import (
        apical_table_plan, incidence_table_plan, bmd_summary_plan, table_caption,
    )
    caption = None
    try:
        if node.node_type == "table":
            plan = apical_table_plan(node, data)
            caption = plan.caption if plan else None
        elif node.node_type == "incidence-table":
            plan = incidence_table_plan(node, data)
            caption = plan.caption if plan else None
        elif node.node_type == "bmd-summary":
            plan = bmd_summary_plan(node, data)
            caption = getattr(plan, "caption", None)
        elif node.node_type == "sample-counts-table":
            caption = table_caption(node, node.caption or node.title)
    except Exception:
        caption = None
    stripped = _strip_table_prefix(caption) if caption else ""
    return stripped or node.title


def _build_toc_entries(data: dict, tree: "list | None" = None) -> tuple[list[dict], list[dict]]:
    """
    Walk the document tree and build two arrays for the Typst template:

      toc_entries:   [{title, level, ready, id}, ...]
                     Every heading (level 1-3) in the document tree.
                     "ready" is True when the section has real content
                     (not just the scaffold placeholder).

      table_entries: [{title, table_number, ready}, ...]
                     Every numbered table in the Results section.
                     "ready" is True when the table's platform has data
                     in apical_sections or elsewhere.

    "Ready" determination:
      - Front matter sections (foreword, about, peer review, etc.) are
        always ready because the scaffold provides boilerplate.
      - Body sections check whether the corresponding data_key in the
        report data dict has been overlaid with real content.  The
        scaffold sets empty stubs ({paragraphs: []} or empty arrays),
        so we check for non-empty content.
      - Apical table nodes check whether any apical_section entry
        matches the node's platform AND has non-empty table_data.
      - Genomics nodes check genomics_sections for matching entries.

    Args:
        data: The full report data dict (after overlay, before filter).

    Returns:
        (toc_entries, table_entries) — both are lists of dicts.
    """
    from document_model.document_tree import DOCUMENT_TREE, compute_table_numbers

    nodes = tree if tree is not None else DOCUMENT_TREE
    # Ensure table numbers are computed before we walk
    compute_table_numbers(nodes)

    toc_entries = []
    table_entries = []

    # --- Readiness checks for each data_key ---
    # Front matter keys are always "ready" (scaffold provides boilerplate).
    _FRONT_KEYS = {
        "foreword", "about_report", "peer_review",
        "publication_details", "acknowledgments", "abstract",
        "table_of_contents",
    }

    def _is_ready(node) -> bool:
        """
        Check whether a node's content is real (not scaffold placeholder).

        Front matter is always ready (boilerplate).  Body sections check
        for non-empty content under their data_key.  Table nodes check
        for platform-matching apical_sections with table_data.  Genomics
        nodes check genomics_sections for matching organ/type entries.
        """
        dk = getattr(node, "data_key", None)

        # Front matter — always ready (boilerplate content)
        if dk in _FRONT_KEYS:
            return True

        # Table nodes — check apical_sections for matching platform data
        if node.node_type == "table" or node.node_type == "incidence-table":
            platform = getattr(node, "platform", None)
            if platform:
                for sec in data.get("apical_sections", []):
                    if sec.get("platform") == platform and sec.get("table_data"):
                        return True
            return False

        # Sample-counts table (Table 1) — ready iff its built matrix has rows.
        if node.node_type == "sample-counts-table":
            built = data.get(dk) if dk else None
            return bool(isinstance(built, dict) and built.get("rows"))

        # BMD summary — check for non-placeholder endpoints
        if node.node_type == "bmd-summary":
            bmd = data.get("bmd_summary", {})
            endpoints = bmd.get("endpoints", [])
            # Scaffold has one placeholder row with endpoint "—"
            if len(endpoints) > 1:
                return True
            if len(endpoints) == 1 and endpoints[0].get("endpoint") != "—":
                return True
            return False

        # Genomics sections — check for gene_set/gene entries with data
        if node.node_type == "genomics-section":
            gs = data.get("genomics_sections", [])
            nk = getattr(node, "narrative_key", None)
            if nk == "gene_set_narrative":
                return any(s.get("type") == "gene_set" and s.get("gene_sets") for s in gs)
            elif nk == "gene_narrative":
                return any(s.get("type") == "gene" and s.get("top_genes") for s in gs)
            return bool(gs)

        # Narrative / heading-only nodes — check data_key for content
        if dk:
            val = data.get(dk)
            if val is None:
                return False
            if isinstance(val, dict):
                # Check for non-empty paragraphs or sections
                paras = val.get("paragraphs", [])
                secs = val.get("sections", [])
                return bool(paras) or bool(secs)
            if isinstance(val, list):
                return bool(val)
            return bool(val)

        # Heading-only nodes with children — ready if any child is ready
        if node.children:
            return any(_is_ready(c) for c in node.children)

        return False

    # Narrative+tables nodes (animal condition, clinical path) — ready if
    # they have a unified narrative OR any child table has data
    def _is_narrative_tables_ready(node) -> bool:
        """
        Check readiness for narrative+tables nodes (e.g., Animal Condition,
        Clinical Pathology).  Ready if unified narrative exists OR any
        child table node has platform data in apical_sections.
        """
        nk = getattr(node, "narrative_key", None)
        if nk:
            un = data.get("unified_narratives", {})
            if un.get(nk):
                return True
        # Check child tables
        return any(_is_ready(c) for c in node.children)

    # This is a PRUNED walk, deliberately NOT the shared document_tree.walk_tree
    # (ADR-0006): it does not descend into cover / title-page / tables-list /
    # appendix nodes — those are TOC leaves (or excluded), and their subtrees
    # must not contribute entries.  walk_tree always recurses, so it can't
    # express that pruning; the manual recursion below keeps the intent explicit
    # rather than relying on those node types happening to be childless today.
    def _walk_toc(nodes: list):
        """
        Recursively walk tree nodes, emitting toc_entries for headings
        (level >= 1) and table_entries for table nodes with numbers.  Does not
        descend into structural / appendix nodes (see the note above).
        """
        for node in nodes:
            # Skip structural pages (cover, title) — they're not TOC entries
            if node.node_type in ("cover", "title-page"):
                continue

            # Tables list node — skip (it IS the TOC, not an entry in it)
            if node.node_type == "tables-list":
                continue

            # Appendix nodes — always show as placeholders in the TOC.  The entry
            # text is composed "Appendix {letter}. {title}" from the positional
            # letter (node.title no longer carries the literal prefix), matching
            # the reference ToC and the rendered appendix headings.
            if node.node_type == "appendix":
                from render_common import appendix_heading_text
                toc_entries.append({
                    "title": appendix_heading_text(node),
                    "level": node.level,
                    "ready": False,
                    "id": node.id,
                })
                continue

            # Heading entries (level >= 1) go into the TOC
            if node.level >= 1:
                if node.node_type == "narrative+tables":
                    ready = _is_narrative_tables_ready(node)
                else:
                    ready = _is_ready(node)
                toc_entries.append({
                    "title": node.title,
                    "level": node.level,
                    "ready": ready,
                    "id": node.id,
                })

            # Table entries (numbered tables) go into the Tables list.  Use the
            # FULL caption the table body renders (chemical/species interpolated
            # via each platform builder's CAPTION_TEMPLATE), not the short
            # node.title — so the Tables list reads "Summary of Body Weights of
            # Male and Female Rats Administered <chemical> for Five Days", matching
            # the example documents.  The "Table N." prefix is stripped (the list's
            # own numbering supplies it); falls back to node.title when no plan
            # caption is available (scaffold / no data).
            if node.table_number is not None:
                ready = _is_ready(node)
                table_entries.append({
                    "title": _table_list_title(node, data),
                    "table_number": node.table_number,
                    "ready": ready,
                })

            # Recurse into children
            if node.children:
                _walk_toc(node.children)

    _walk_toc(nodes)

    # Genomics tables are DATA-DRIVEN (not tree nodes), so the walk above misses
    # them.  They were numbered by assign_genomics_table_numbers before this ran;
    # append them to the Tables list in table_number order so the front-matter
    # list continues Table 8 → 9, 10, ...  Title/readiness come from the same
    # shared caption + row presence the renderers use, so all three agree.
    from render_common import genomics_table_caption
    genomics_tables = [
        {
            "title": genomics_table_caption(entry).split(". ", 1)[-1],
            "table_number": entry["table_number"],
            "ready": bool(
                entry.get("gene_sets") if entry.get("type") == "gene_set"
                else entry.get("top_genes")
            ),
        }
        for entry in (data.get("genomics_sections") or [])
        if entry.get("table_number") is not None
    ]
    genomics_tables.sort(key=lambda e: e["table_number"])
    table_entries.extend(genomics_tables)

    return toc_entries, table_entries


def _apply_section_filter(data: dict, section_filter: str, tree: "list | None" = None) -> None:
    """
    Strip all report sections except the requested one for PDF preview.

    Uses the document structure tree (document_tree.py) to determine which
    data keys and platforms belong to the requested TOC node.  This replaces
    all hardcoded filter maps with a single tree-driven lookup.

    Modifies `data` in place: sets section_only=True (tells the Typst
    template to skip structural pages), removes front matter for body
    previews, removes body sections not referenced by the requested node,
    and sub-filters apical_sections by platform.

    Args:
        data: The full report data dict (modified in place).
        section_filter: Any TOC node ID (e.g., "animal-condition",
                        "table-body-weight", "background", "foreword").
    """
    from document_model.document_tree import (
        find_node, collect_data_keys, collect_platforms, collect_methods_keys,
    )

    # All data keys that can be independently removed
    ALL_BODY = {
        "background", "methods", "sample_counts", "apical_sections",
        "unified_narratives", "internal_dose", "bmd_summary",
        "genomics_sections", "gene_set_narrative", "gene_narrative",
        "summary", "references",
    }
    ALL_FRONT = {
        "foreword", "about_report", "peer_review", "publication_details",
        "acknowledgments", "abstract", "table_of_contents",
    }

    # --- Resolve dynamic per-organ subnode IDs ---
    # The frontend sidebar generates per-organ subnodes for the genomics
    # parents — IDs like "gene-set-liver" or "gene-bmd-kidney" — that
    # don't exist in the static DOCUMENT_TREE.  Map them to the parent
    # node ("gene-sets" / "gene-bmd") and remember the organ qualifier
    # so we can sub-filter genomics_sections to just that organ below.
    organ_qualifier: str | None = None
    if section_filter and section_filter not in (None, ""):
        for prefix, parent_id in (
            ("gene-set-", "gene-sets"),
            ("gene-bmd-", "gene-bmd"),
        ):
            if section_filter.startswith(prefix):
                candidate_organ = section_filter[len(prefix):]
                # Only treat as a per-organ subnode when the suffix
                # isn't itself an existing static node ID.
                if find_node(section_filter, tree) is None and candidate_organ:
                    organ_qualifier = candidate_organ.lower()
                    section_filter = parent_id
                break

    # --- Look up the node in the document tree ---
    node = find_node(section_filter, tree)

    if node is None:
        # Unknown node ID — strip everything as a safe fallback
        data["section_only"] = True
        return

    # --- Signal the Typst template which preview mode to use ---
    # Front-matter nodes strip all body content and set preview_mode so
    # the Typst template renders only the appropriate structural pages.
    #
    # Three sub-modes:
    #   "cover"        — render only the cover page (full-bleed green)
    #   "title-page"   — render only the inner title page (centered text)
    #   "front-matter" — render inner title + one front matter section
    #
    # For individual front-matter sections (foreword, peer-review, etc.),
    # we strip all OTHER front matter keys so only the selected section
    # renders — otherwise every front matter page shows up.
    if node.node_type in ("front-matter", "tables-list", "cover", "title-page"):
        for key in ALL_BODY:
            data.pop(key, None)

        if node.node_type == "cover":
            data["preview_mode"] = "cover"
        elif node.node_type == "title-page":
            data["preview_mode"] = "title-page"
        elif node.node_type == "tables-list":
            # TOC/tables-list preview: strip all front matter content
            # sections but keep body data so the TOC outline has entries.
            data["preview_mode"] = "tables-list"
            for key in ALL_FRONT:
                data.pop(key, None)
            # Restore body keys so outline() can enumerate headings
            # (they were already stripped above — re-marshal from scaffold)
        else:
            data["preview_mode"] = "front-matter"
            # Keep only the selected front-matter section's data key.
            keep_key = getattr(node, "data_key", None)
            if keep_key:
                for key in ALL_FRONT:
                    if key != keep_key:
                        data.pop(key, None)
        return

    # Body content: skip front matter and structural pages
    data["section_only"] = True

    # Body content: remove front matter, keep only data keys referenced
    # by this node's subtree
    for key in ALL_FRONT:
        data.pop(key, None)

    keep = collect_data_keys(node)
    # For nodes under Results that reference apical_sections, also keep
    # the sections array itself
    platforms = collect_platforms(node)
    if platforms:
        keep.add("apical_sections")

    # Charts are rendered inline within the gene-set per-organ blocks, and
    # their PNG payload now travels INSIDE each genomics_sections entry (as
    # entry["charts"], attached by genomics_charts.attach_genomics_charts).
    # So keeping "genomics_sections" automatically keeps the charts — there is
    # no separate top-level chart key to preserve any more.
    for key in ALL_BODY - keep:
        data.pop(key, None)

    # Sub-filter apical_sections by platform
    if platforms and "apical_sections" in data:
        data["apical_sections"] = [
            s for s in data["apical_sections"]
            if s.get("platform") in platforms
        ]

    # Sub-filter methods.sections by selected M&M subsection.
    # Each M&M subnode (mm-study-design, mm-clin-exam, etc.) has a methods_key
    # that maps to a key in data.methods.sections.  For heading-only parents
    # (mm-clin-exam, mm-transcriptomics, mm-data-analysis), we collect the
    # parent's key plus all children's keys so the preview shows the whole
    # subtree under that parent heading.  The root "methods" node has no
    # methods_key of its own but its subtree covers every section.
    methods_keys = collect_methods_keys(node)
    if methods_keys and "methods" in data:
        methods_data = data["methods"]
        sections = methods_data.get("sections", [])
        filtered = [s for s in sections if s.get("key") in methods_keys]
        if filtered:
            data["methods"] = {**methods_data, "sections": filtered}

    # Sub-filter genomics_sections by type for the gene-sets / gene-bmd
    # node previews.  Both nodes share data_key="genomics_sections" but each
    # represents a different slice — gene-sets renders type="gene_set"
    # entries, gene-bmd renders type="gene" entries.  Without this filter,
    # the gene-sets preview would also show gene tables and vice versa.
    # The narrative_key on the node uniquely identifies which slice to keep.
    nk = getattr(node, "narrative_key", None)
    if nk in ("gene_set_narrative", "gene_narrative") and "genomics_sections" in data:
        wanted_type = "gene_set" if nk == "gene_set_narrative" else "gene"
        data["genomics_sections"] = [
            s for s in data["genomics_sections"]
            if s.get("type") == wanted_type
        ]

    # Per-organ subnode filter — when the requested TOC id was e.g.
    # "gene-set-liver", drop sections for other organs so the preview
    # renders only the Liver table (and its narrative, via the Typst
    # `by_organ` lookup).  The narrative dict stays intact because its
    # per-organ placement is keyed by organ name in the template.
    if organ_qualifier and "genomics_sections" in data:
        data["genomics_sections"] = [
            s for s in data["genomics_sections"]
            if str(s.get("organ", "")).lower() == organ_qualifier
        ]
