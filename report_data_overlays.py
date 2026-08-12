"""
report_data_overlays.py — Overlay layer for the LaTeX report data assembly.

Extracted from report_data.py: the functions that take the scaffolded `data`
dict and overlay real session content on top of it (abstract sections, apical
endpoint sections, unified/BMD narratives, genomics sections).

marshal_export_data (report_data.py) calls the private `_overlay_*` adapters,
which pull inputs from the request body.  overlay_abstract is the one public
assembler here — latex_export.load_session_data calls it directly with the
inputs it already has, so the abstract is assembled identically from either
the web body or a session export.

The two normalizers that stay in report_data.py (normalize_apical_section_for_render,
_ensure_paragraphs) are pulled in via function-local imports to avoid an import
cycle — report_data imports this module at call time, and this module imports
those two helpers at call time.
"""

import logging
from pathlib import Path

from tables.table_builder_common import lettered_footnote, finalize_footnotes


# ---------------------------------------------------------------------------
# Session cache lookup
# ---------------------------------------------------------------------------

def _latest_session_cache(session_dir: Path, glob_pattern: str):
    """
    Return the NEWEST session cache file matching `glob_pattern`, or None.

    A session accumulates one cache file per content hash (e.g. several
    `_cache_genomics_<hash>.json` as the gene set is re-analysed), so "the
    current one" is the most recently written — not the lexically-first.
    Selecting by modification time matches the convention the session-export
    path uses (latex_export._latest); this is the web/preview path's copy so
    both surfaces resolve the same file from a multi-hash session.

    Returns a pathlib.Path or None when nothing matches.
    """
    candidates = sorted(session_dir.glob(glob_pattern), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def overlay_abstract(
    data: dict,
    *,
    abstract_background: str = "",
    bmd_endpoints: list | None = None,
    genomics_cache: dict | None = None,
    dose_groups: list | None = None,
    dose_unit: str = "mg/kg",
    bmd_stat=None,
    methods_context: dict | None = None,
) -> None:
    """
    Assemble data["abstract"]["sections"] (Background / Methods / Results /
    Summary) from EXPLICIT inputs — no request body, no disk reads.

    Both the web path (marshal_export_data, via the _overlay_abstract adapter
    below) and the session export (latex_export.load_session_data) call this
    with the inputs they already have, so the abstract is assembled identically
    from either source.  This is the shared assembler that replaced the
    previous body-and-disk-coupled implementation.

    methods_context (the MethodsContext dict) drives the Methods paragraph and
    the study-purpose sentence; it is absent for a session with no methods
    cache, in which case those parts are simply skipped.  endpoints come from
    data["bmd_summary"] if present, else the explicit bmd_endpoints.  Empty
    sections are left untouched, so a partial abstract is fine.
    """
    abstract_updates: dict[str, str] = {}

    # Abstract → Methods (deterministic from the extracted study facts).
    if methods_context:
        try:
            from narrative.methods_report import MethodsContext, build_abstract_methods
            abstract_updates["Methods"] = build_abstract_methods(
                MethodsContext.from_dict(methods_context)
            )
        except Exception:
            pass

    # Deterministic study-purpose sentence appended to the LLM background.
    study_purpose_sentence = ""
    if methods_context:
        try:
            from narrative.methods_report import MethodsContext as _MC
            _ctx = _MC.from_dict(methods_context)
            ta = _ctx.chemical_name or "the test article"
            descriptor = "transcriptomic" if _ctx.has_gene_expression else "toxicological"
            study_purpose_sentence = (
                f"A short-term, in vivo {descriptor} study was used to "
                f"assess the biological potency of {ta}."
            )
        except Exception:
            pass

    abstract_bg_text = (abstract_background or "").strip()
    if abstract_bg_text or study_purpose_sentence:
        abstract_updates["Background"] = " ".join(
            p for p in (abstract_bg_text, study_purpose_sentence) if p
        )

    # Apical Results/Summary: prefer endpoints already on `data`, else the arg.
    endpoints = (data.get("bmd_summary") or {}).get("endpoints") or bmd_endpoints or []
    dose_groups = dose_groups or []

    if endpoints or genomics_cache or methods_context:
        try:
            from narrative.methods_report import build_abstract_results, build_abstract_summary
            results_text = build_abstract_results(
                apical_bmd_summary=endpoints,
                genomics_sections=genomics_cache,
                dose_groups=dose_groups,
                dose_unit=dose_unit,
                bmd_stat=bmd_stat,
                methods_ctx=methods_context,
            )
            if results_text:
                abstract_updates["Results"] = results_text
            summary_text = build_abstract_summary(
                apical_bmd_summary=endpoints,
                genomics_sections=genomics_cache,
                dose_groups=dose_groups,
                dose_unit=dose_unit,
                bmd_stat=bmd_stat,
            )
            if summary_text:
                abstract_updates["Summary"] = summary_text
        except Exception:
            pass

    # Apply updates to data["abstract"]["sections"], preserving order/labels.
    if abstract_updates:
        existing = data.get("abstract", {"sections": []})
        sections = list(existing.get("sections", []))
        for label, text in abstract_updates.items():
            updated = False
            for sec in sections:
                if sec.get("label", "").lower() == label.lower():
                    sec["text"] = text
                    updated = True
                    break
            if not updated:
                sections.append({"label": label, "text": text})
        data["abstract"] = {"sections": sections}


def _overlay_abstract(data: dict, body: dict) -> None:
    """
    Web-path adapter: pull the abstract inputs out of the request body — and
    read the genomics cache from disk via the body's dtxsid — then delegate to
    the shared overlay_abstract().  Preserves the exact inputs the previous
    body-coupled implementation derived, so the web export is unchanged.
    """
    methods_data = body.get("methods_data")
    methods_context = (
        methods_data["context"]
        if (methods_data and methods_data.get("context"))
        else None
    )

    # Dose groups / unit come from the MethodsContext when present, else the
    # body's dose_unit (default mg/kg).
    dose_groups: list = []
    dose_unit = body.get("dose_unit", "mg/kg")
    if methods_context:
        dose_groups = methods_context.get("dose_groups", []) or []
        dose_unit = methods_context.get("dose_unit", dose_unit)

    # The request body carries genomics as an array, but the abstract builders
    # want the cached organ×sex dict — read it from disk by dtxsid.
    genomics_cache = None
    dtxsid = body.get("dtxsid", "")
    if dtxsid:
        try:
            session_dir = Path("sessions") / dtxsid
            cache = _latest_session_cache(session_dir, "_cache_genomics_*.json")
            if cache is not None:
                import orjson
                genomics_cache = orjson.loads(cache.read_bytes())
        except Exception:
            pass

    overlay_abstract(
        data,
        abstract_background=body.get("abstract_background", "") or "",
        bmd_endpoints=body.get("bmd_summary_endpoints"),
        genomics_cache=genomics_cache,
        dose_groups=dose_groups,
        dose_unit=dose_unit,
        methods_context=methods_context,
    )


def _find_table_number(nodes: list, platform: str):
    """
    Walk the document tree depth-first for a table node whose `platform`
    matches and that has a positional table_number assigned; return that
    number, or None.  Hoisted to module scope so the apical-section loop in
    _overlay_apical_sections doesn't redefine it on every iteration.
    """
    for node in nodes:
        if node.platform == platform and node.table_number is not None:
            return node.table_number
        if node.children:
            result = _find_table_number(node.children, platform)
            if result is not None:
                return result
    return None


def _overlay_apical_sections(data: dict, body: dict, tree: "list | None" = None) -> None:
    """Overlay the apical endpoint sections: footnotes, tree-derived table numbers, document-order sort, and per-row canonicalization.

    `tree` defaults to the global DOCUMENT_TREE; a per-session tree is passed so
    table numbers resolve against the session's own structure."""
    from report_data import normalize_apical_section_for_render

    chemical_name = body.get("chemical_name", "Chemical")
    # Apical endpoint sections
    apical_sections = body.get("apical_sections", [])
    if apical_sections:
        data["apical_sections"] = []
        for sec in apical_sections:
            # The builder already emitted typed footnote records (legend /
            # definition / lettered) with letters assigned.  Copy the list
            # so we don't mutate the cached section.
            footnotes = list(sec.get("footnotes", []))
            dose_unit = sec.get("dose_unit", "mg/kg")
            table_data = sec.get("table_data", {})

            # Build per-sex missing-animal footnotes from table row data.
            # Each row may have a missing_animals dict mapping dose → count
            # (animals that died before terminal sacrifice).  These are typed
            # `lettered` records; append them and re-run finalize_footnotes so
            # the whole list is re-lettered consistently (idempotent — it
            # re-derives row markers from marker_refs each call).
            footnotes.extend(
                _build_missing_animal_footnotes(table_data, dose_unit)
            )
            finalize_footnotes(footnotes, table_data)

            # Determine the first column header based on section type.
            # Body weight tables use "Study Day" (the rows are day 0, day 5);
            # all other apical tables use "Endpoint" (each row is a measured
            # parameter like ALT, albumin, etc.).
            section_title = sec.get("section_title", "Apical Endpoints")
            is_body_weight = "body weight" in section_title.lower()
            first_col = sec.get("first_col_header",
                                "Study Day" if is_body_weight else "Endpoint")

            # Accept caption from either key — the body_weight_table builder
            # outputs "caption" directly, while the frontend uses
            # "table_caption_template".
            caption = (sec.get("caption")
                       or sec.get("table_caption_template", ""))

            apical_entry = {
                "title": section_title,
                "caption": caption,
                "compound": sec.get("compound_name", chemical_name),
                "dose_unit": dose_unit,
                "first_col_header": first_col,
                "narrative": _split_narrative(
                    sec.get("narrative_paragraphs") or sec.get("narrative")
                ),
                "table_data": table_data,
                # Typed footnote list — legend / definition / lettered
                # records, with letters assigned and row markers derived.
                # The old separate missing_animal_footnotes and
                # bmd_definition keys are folded into this list.
                "footnotes": footnotes,
                # Platform identifier — used by _apply_section_filter()
                # to filter sections for per-subsection PDF previews.
                "platform": sec.get("platform", section_title),
            }

            # Table number — derived from the document structure tree.
            # The tree assigns numbers by position (Table 2 = Body Weight,
            # Table 3 = Organ Weight, etc.).  Overrides any user-provided
            # table_number from the UI.  (_find_table_number is a module-level
            # helper so it isn't rebuilt on every loop iteration.)
            from document_model.document_tree import DOCUMENT_TREE
            nodes = tree if tree is not None else DOCUMENT_TREE
            platform = apical_entry["platform"]
            tree_table_num = _find_table_number(nodes, platform)
            if tree_table_num is not None:
                apical_entry["table_number"] = tree_table_num

            data["apical_sections"].append(apical_entry)

        # Render in document-tree order (Table 2, 3, 4, ...), not the
        # alphabetical platform order the orchestrator's sections cache
        # happens to produce.  Without this, the full report shows
        # Table 3 (Organ Weight) after Tables 4/5/6 because "Organ
        # Weight" sorts after "Clinical Chemistry" / "Hematology" /
        # "Hormones" alphabetically — even though each per-section PDF
        # preview correctly labels Organ Weight as Table 3.  Sections
        # without a table_number (shouldn't happen for apical, but is
        # possible if the document tree doesn't know the platform) sort
        # to the end; the sort is stable to preserve sibling ordering.
        data["apical_sections"].sort(
            key=lambda s: s.get("table_number") or 10_000,
        )

        # Canonicalize per-row shape so both renderers (LaTeX and HTML)
        # see the same input.  The web UI ships row.values as a dict
        # keyed by dose-as-string; the renderers iterate values as a
        # list — without this step they'd produce the dict's keys (the
        # dose strings) in every row's value columns, identical for
        # every endpoint.  See normalize_apical_section_for_render's
        # docstring for the full reasoning.
        data["apical_sections"] = [
            normalize_apical_section_for_render(s)
            for s in data["apical_sections"]
        ]


def _overlay_unified_and_bmd(data: dict, body: dict) -> None:
    """Overlay unified group narratives, internal dose, and the apical BMD summary table plus its intro/LLE paragraph block."""
    methods_data = body.get("methods_data")
    # Unified narratives — group-level prose spanning multiple platform tables.
    # The NIEHS reference has one narrative for "Animal Condition, Body Weights,
    # and Organ Weights" and one for "Clinical Pathology", rendered before their
    # respective table groups.
    # Unified narratives — map from JS keys (apical, clinical_pathology)
    # to Typst template group keys (animal_condition, clinical_pathology).
    # The JS uses "apical" for the Animal Condition group because that was
    # the original key before the TOC restructure.
    _UNIFIED_KEY_MAP = {
        "apical": "animal_condition",
        "clinical_pathology": "clinical_pathology",
    }
    unified_narr = body.get("unified_narratives", {})
    if unified_narr:
        data["unified_narratives"] = {}
        for key, narr_data in unified_narr.items():
            paras = narr_data.get("paragraphs", []) if isinstance(narr_data, dict) else []
            if isinstance(narr_data, list):
                paras = narr_data
            if paras:
                typst_key = _UNIFIED_KEY_MAP.get(key, key)
                data["unified_narratives"][typst_key] = paras

    # Internal Dose Assessment
    internal_dose = body.get("internal_dose")
    if internal_dose:
        data["internal_dose"] = internal_dose

    # BMD Summary
    # The Apical Endpoint BMD Summary table (Table 8 in NIEHS Report 10)
    # carries a fixed footnote block defining BMD/BMDL/LOEL/NOEL/UREP/NVM
    # — all of these can appear in the table cells, so the legend belongs
    # with every export.
    bmd_summary = body.get("bmd_summary")
    bmd_endpoints = body.get("bmd_summary_endpoints", [])
    _bmd_summary_footnotes = [
        "BMD₁Std = benchmark dose corresponding to a benchmark response set "
        "to one standard deviation from the mean; "
        "BMDL₁Std = benchmark dose lower confidence limit corresponding to a "
        "benchmark response set to one standard deviation from the mean; "
        "LOEL = lowest-observed-effect level; "
        "NOEL = no-observed-effect level; "
        "UREP = unreliable estimate of potency — a label based on review of "
        "BMD modeling results indicating the curve-fit BMD is implausibly far "
        "below the statistically observed effect threshold; "
        "NVM = nonviable model, defined as a modeling result that does not "
        "meet prespecified fit criteria and hence is deemed unreliable.",
    ]
    if bmd_summary:
        data["bmd_summary"] = dict(bmd_summary)
        if not data["bmd_summary"].get("footnotes"):
            data["bmd_summary"]["footnotes"] = _bmd_summary_footnotes
    elif bmd_endpoints:
        data["bmd_summary"] = {
            "endpoints": bmd_endpoints,
            "footnotes": _bmd_summary_footnotes,
        }

    # --- Apical Endpoint BMD Summary paragraphs ---
    # Three-layer paragraph block prepended before Table 8:
    #   1. Boilerplate intro (table reference + LLE explanation) — always present.
    #   2. Descriptive findings (programmatic) — from apical_bmd_narrative if
    #      provided by process-integrated; otherwise omitted.
    #   3. Analytical paragraph (LLM) — from apical_bmd_narrative if present.
    #
    # The intro is generated here from MethodsContext because this path runs
    # during both process-integrated (narrative passed in) and standalone PDF
    # export (narrative may not be present, so we still build the intro).
    if data.get("bmd_summary") and not data["bmd_summary"].get("paragraphs"):
        all_paras: list[str] = []

        # --- Layer 1: boilerplate table-reference intro ---
        _doses_for_lle: list[float] = []
        if methods_data and methods_data.get("context"):
            _doses_for_lle = methods_data["context"].get("dose_groups", []) or []
        _nonzero = [d for d in _doses_for_lle if d and d > 0]
        if _nonzero:
            _lle = min(_nonzero) / 3.0
            _lle_str = f"{_lle:.3f}".rstrip("0").rstrip(".") or "0"
            _dose_unit_str = (
                methods_data["context"].get("dose_unit", "mg/kg")
                if methods_data and methods_data.get("context") else "mg/kg"
            )
            _table_num = None
            try:
                from document_model.document_tree import find_node, compute_table_numbers
                compute_table_numbers()
                _bmd_node = find_node("bmd-summary")
                if _bmd_node and _bmd_node.table_number is not None:
                    _table_num = _bmd_node.table_number
            except Exception:
                pass
            _table_ref = f"Table {_table_num}" if _table_num is not None else "the table below"
            all_paras.append(
                f"A summary of the calculated BMDs for each toxicological "
                f"endpoint is provided in {_table_ref}. The endpoint-"
                f"specific LOEL and NOEL are included and could be informative "
                f"for endpoints that lack a calculated BMD either because no "
                f"viable model was available or because the estimated BMD was "
                f"below the lower limit of extrapolation (<{_lle_str} "
                f"{_dose_unit_str})."
            )

        # --- Layers 2 + 3: descriptive + analytical from process-integrated ---
        # apical_bmd_narrative is provided when the PDF is exported immediately
        # after process-integrated (the in-app flow).  On standalone PDF export
        # (export.js → /api/export-pdf) the frontend should include it in the
        # request body if it received it from process-integrated.
        _apical_narr = body.get("apical_bmd_narrative") or {}
        all_paras.extend(_apical_narr.get("paragraphs") or [])

        if all_paras:
            data["bmd_summary"]["paragraphs"] = all_paras


def _overlay_genomics(data: dict, body: dict) -> None:
    """Overlay genomics gene-set/gene sections and auto-populate the gene-set / gene body narratives."""
    from report_data import _ensure_paragraphs

    methods_data = body.get("methods_data")
    _dtxsid = body.get("dtxsid", "")
    _session_dir_path = Path("sessions") / _dtxsid if _dtxsid else None
    # Genomics
    genomics = body.get("genomics_sections", [])
    if genomics:
        data["genomics_sections"] = genomics
        # Attach genomics chart images (UMAP / cluster-scatter PNGs) to the
        # gene_set entries, exactly as the session-export path does.  The
        # charts live in the session's _cache_charts_*.json (base64 PNG, one
        # entry per organ×sex); the browser does NOT round-trip them through
        # the request body, so we read them server-side here — the behaviour
        # export.js documents ("Chart images are read server-side from
        # _cache_charts_{hash}.json").  Charts hang on entry["charts"], which
        # is what both renderers read; that replaces the old, dead
        # data["genomics_charts"] key (no node type ever consumed it).
        if _session_dir_path and _session_dir_path.exists():
            _charts = _latest_session_cache(_session_dir_path, "_cache_charts_*.json")
            if _charts is not None:
                try:
                    import orjson
                    from genomics.genomics_charts import attach_genomics_charts
                    from document_model.document_tree import ACTIVE_TEMPLATE
                    from document_model.document_template import load_report_charts
                    charts_cache = orjson.loads(_charts.read_bytes())
                    if isinstance(charts_cache, list):
                        attach_genomics_charts(
                            genomics, charts_cache,
                            enabled_types=load_report_charts(ACTIVE_TEMPLATE),
                        )
                except Exception:
                    # A missing/corrupt chart cache must not abort the report;
                    # the genomics sections simply render without figures.
                    logging.exception("Failed to attach genomics charts")

    gene_set_narrative = body.get("gene_set_narrative")
    if gene_set_narrative:
        data["gene_set_narrative"] = _ensure_paragraphs(gene_set_narrative)

    gene_narrative = body.get("gene_narrative")
    if gene_narrative:
        data["gene_narrative"] = _ensure_paragraphs(gene_narrative)

    # --- Auto-populate Gene Set / Gene BMD body narratives ---
    # When the user hasn't supplied their own narrative text with a
    # per-organ `by_organ` map, delegate to the shared assembler so the
    # PDF and the in-app HTML render identical prose.  The cache is
    # read here (not in the shared assembler) because this path is
    # session-specific; `/api/process-integrated` passes the in-memory
    # genomics_sections dict directly instead.
    # _dtxsid / _session_dir_path were resolved once at the top of this
    # function (the charts attach also needs them) — reuse them here.
    _genomics_cache = None
    if _session_dir_path and genomics:
        try:
            _gcache = _latest_session_cache(_session_dir_path, "_cache_genomics_*.json")
            if _gcache is not None:
                import orjson
                _genomics_cache = orjson.loads(_gcache.read_bytes())
        except Exception:
            pass

    if _genomics_cache:
        try:
            from genomics.genomics_narratives import build_genomics_body_narratives

            _ctx_dict = (methods_data or {}).get("context") or {}
            _chem_name = (
                _ctx_dict.get("chemical_name")
                or body.get("chemical_name")
                or "the test article"
            )
            narratives = build_genomics_body_narratives(
                genomics_sections=_genomics_cache,
                methods_context=_ctx_dict,
                chemical_name=_chem_name,
            )

            # Overlay each narrative only when the request didn't already
            # carry a `by_organ` map.  The frontend flattens user edits
            # to `paragraphs` (no per-organ awareness), so any session
            # saved before the format upgrade gets a fresh auto-populate
            # on export.  Once the frontend learns to preserve `by_organ`
            # through user edits, those edits win.
            _gs_existing = gene_set_narrative if isinstance(gene_set_narrative, dict) else {}
            if not _gs_existing.get("by_organ") and "gene_set_narrative" in narratives:
                data["gene_set_narrative"] = narratives["gene_set_narrative"]

            _gn_existing = gene_narrative if isinstance(gene_narrative, dict) else {}
            if not _gn_existing.get("by_organ") and "gene_narrative" in narratives:
                data["gene_narrative"] = narratives["gene_narrative"]
        except Exception as e:
            logging.exception("Failed to build genomics body narratives: %s", e)


def _split_narrative(narrative) -> list[str]:
    """
    Normalize narrative input to a list of paragraph strings.

    The narrative may arrive as:
      - A list of strings (one per paragraph) — return as-is
      - A single string with double-newline separators — split
      - None — return empty list
    """
    if narrative is None:
        return []
    if isinstance(narrative, list):
        return narrative
    if isinstance(narrative, str):
        return [p.strip() for p in narrative.split("\n\n") if p.strip()]
    return []


def _build_missing_animal_footnotes(
    table_data: dict, dose_unit: str
) -> list[dict]:
    """
    Scan table_data rows for missing-animal annotations and produce typed
    footnote records for the apical footnote list.

    Each row in table_data[sex] may carry a `missing_animals` dict mapping
    dose (as string) to integer count — the number of animals in the xlsx
    study file roster that are absent from that domain's bm2 data (animals
    that died before terminal sacrifice and couldn't have that endpoint
    measured).

    We aggregate per sex, taking the max count at each dose across all
    endpoints (since different endpoints may report slightly different N),
    and produce one lettered footnote per sex, e.g.:

        "5 animals at 333 mg/kg; 5 animals at 1,000 mg/kg did not survive
         to terminal sacrifice."

    These are typed `lettered` records with `target="none"` — the dose
    groups are named inline in the text, so no in-table cell marker is
    needed.  The caller merges them into the section's footnote list and
    re-runs finalize_footnotes so they pick up the next letters after the
    builder's own footnotes.

    Args:
        table_data: Dict keyed by sex ("Male", "Female"), each value a
                    list of row dicts with optional "missing_animals".
        dose_unit:  Dose unit string (e.g., "mg/kg") for display.

    Returns:
        List of typed `lettered` footnote records (one per sex with
        missing animals).  Empty list if no missing animals in any sex.
    """
    records: list[dict] = []

    for sex in ("Male", "Female"):
        rows = table_data.get(sex, [])
        if not rows:
            continue

        # Aggregate: for each dose, take the max missing count across rows
        missing_by_dose: dict[float, int] = {}
        for row in rows:
            ma = row.get("missing_animals")
            if not ma:
                continue
            for dose_key, count in ma.items():
                dose = float(dose_key)
                if dose not in missing_by_dose or count > missing_by_dose[dose]:
                    missing_by_dose[dose] = count

        if not missing_by_dose:
            continue

        # Sort by dose for consistent display order
        sorted_doses = sorted(missing_by_dose.keys())
        parts = []
        for d in sorted_doses:
            n = missing_by_dose[d]
            # Format dose: drop decimal for whole numbers (333 not 333.0)
            d_label = f"{int(d):,}" if d == int(d) else str(d)
            parts.append(
                f"{n} animal{'s' if n > 1 else ''} at {d_label} {dose_unit}"
            )

        text = f"{'; '.join(parts)} did not survive to terminal sacrifice."
        records.append(lettered_footnote(
            text, f"missing_animal_{sex}", target="none",
        ))

    return records
