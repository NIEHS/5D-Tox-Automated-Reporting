"""
Apical BMD summary narrative + Abstract→Results apical paragraph.

The body Results section opens with a per-platform narrative
summarizing apical BMD findings (Body Weight, Organ Weight, Clinical
Pathology, etc.); the Abstract has a one-paragraph version of the same
information.  Both are generated deterministically from the
apical_bmd_summary list — every fact is already in the data, so no
LLM call is needed.

Public functions:

  build_apical_bmd_summary_narrative(apical_bmd_summary, compound_name,
                                     dose_unit)
      Per-platform body-Results narrative — one sentence per platform
      describing direction-tagged effects and BMD/BMDL values per sex.

  build_abstract_results_apical(apical_bmd_summary, compound_name,
                                dose_unit)
      Abstract-section paragraph — single condensed prose paragraph
      summarising the same findings.

Private helpers (used only by the two builders above):

  _normalize_endpoint_name   lowercase multi-word endpoint, preserve
                             short ALL-CAPS acronyms (ALT, RBC)
  _format_endpoint_phrase    endpoint + direction-word into a noun
                             phrase ("decreased body weight")
  _format_bmd_pair           "0.520 (0.160)" — apical-specific BMD/BMDL
                             formatter (genomics uses a different one)

Cross-cutting helpers (_is_reliable_bmd, _is_anomalous_bmd, _join_oxford,
_DIRECTION_WORDS) come from narrative_helpers.

methods_report.py re-exports build_apical_bmd_summary_narrative so
external callers (process_integrated.py imports it directly when
assembling the platform sections) keep working unchanged.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from __future__ import annotations

from narrative_helpers import (
    _DIRECTION_WORDS,
    _is_reliable_bmd,
    _is_anomalous_bmd,
    _join_oxford,
)


# ---------------------------------------------------------------------------
# Abstract → Results paragraph builder
# ---------------------------------------------------------------------------
# The Abstract → Results paragraph summarizes the apical-endpoint findings
# (significant changes + BMD/BMDL values) per sex.  Like the Methods
# paragraph, every fact is already in the BMD summary, so we generate it
# deterministically without an LLM.  Genomics and pharmacokinetics sub-
# paragraphs follow the same pattern and can be added in future iterations.





def _normalize_endpoint_name(endpoint: str) -> str:
    """
    Lowercase a multi-word endpoint name for mid-sentence use, while
    preserving short ALL-CAPS acronyms (e.g., "ALT", "RBC") that should
    stay uppercase.

    Examples:
      "Total Thyroxine"           → "total thyroxine"
      "Aspartate Aminotransferase" → "aspartate aminotransferase"
      "Thyroid Stimulating Hormone" → "thyroid stimulating hormone"
      "ALT"                        → "ALT"
      "Hgb"                        → "hgb"
    """
    if not endpoint:
        return ""

    words = endpoint.strip().split()
    out_words: list[str] = []
    for w in words:
        # Acronym heuristic: all-uppercase, 2-5 chars, no digits → keep
        if 2 <= len(w) <= 5 and w.isupper() and w.isalpha():
            out_words.append(w)
        else:
            out_words.append(w.lower())
    return " ".join(out_words)


def _format_endpoint_phrase(endpoint: str, direction: str, platform: str) -> str:
    """
    Build the descriptor phrase used in the abstract sentence:
      "{direction word} {endpoint name lowercased}{contextual suffix}"

    Hormone endpoints conventionally include "concentration" (e.g.,
    "decreased total thyroxine concentration"); organ weight endpoints
    append "weight" (e.g., "increased liver weight"); other platforms
    use the bare endpoint name.
    """
    direction_word = _DIRECTION_WORDS.get(direction or "", "altered")
    endpoint_lower = _normalize_endpoint_name(endpoint) or "(unknown endpoint)"

    suffix = ""
    if platform == "Hormones":
        suffix = " concentration"
    elif platform == "Organ Weight":
        suffix = " weight"

    return f"{direction_word} {endpoint_lower}{suffix}"


def _format_bmd_pair(bmd, bmdl) -> str:
    """
    Format one BMD (BMDL) value pair for the listing sentence.

    Strategy: when the source value parses as a clean decimal, preserve
    the source's precision — the upstream BMDExpress output already
    rounds to a sensible number of significant figures, and matching
    that display avoids spurious trailing zeros (e.g., "8.54" not
    "8.540").  Falls back to "—" for missing/non-numeric values.
    """
    def _fmt(v) -> str:
        if v is None:
            return "—"
        s = str(v).strip()
        if s in ("", "—", "NVM", "ND", "NA"):
            return "—"
        # Verify it's parseable, but return the original string to
        # preserve source-side rounding (e.g., "8.54" not "8.5400")
        try:
            float(s)
        except (TypeError, ValueError):
            return s
        return s

    return f"{_fmt(bmd)} ({_fmt(bmdl)})"



def build_apical_bmd_summary_narrative(
    apical_bmd_summary: list[dict],
    compound_name: str,
    dose_unit: str = "mg/kg",
) -> list[str]:
    """
    Build the descriptive body narrative for the Apical Endpoint BMD Summary section.

    Produces two paragraphs that sit above Table 8 (the sex-grouped BMD table):

      1. Overview: which platforms had dose-related changes and a count of
         endpoints with reliable BMD estimates.
      2. Per-sex findings: most sensitive endpoint, direction summary per
         platform, BMD range for each sex; UREP/LOEL-only endpoints noted.

    This is the programmatic (deterministic) layer.  A separate LLM pass
    generates an analytical biology-based paragraph that is appended after
    these by the caller.

    Args:
        apical_bmd_summary: Flat list of endpoint dicts from
            _build_apical_bmd_summary() — each with keys endpoint, sex,
            platform, bmd, bmdl, direction, loel, noel, anomalous (optional).
        compound_name: Chemical name used in prose (e.g. "PFHxSAm").
        dose_unit: Dose unit string (e.g. "mg/kg").

    Returns:
        List of paragraph strings ready for display or export.
    """
    if not apical_bmd_summary:
        return []

    # Canonical readable platform name for prose
    _PLATFORM_PROSE = {
        "Clinical Chemistry": "clinical chemistry",
        "Hematology":         "hematology",
        "Hormones":           "hormone",
        "Organ Weight":       "organ weight",
        "Body Weight":        "body weight",
    }

    # --- Classify entries ---
    # Reliable: numeric BMD string that is not UREP/NVM/empty.
    # UREP/anomalous: row exists but BMD flagged as unreliable curve-fit.
    # LOEL-only: no BMD (UREP or NVM or missing) but has a LOEL.
    def _is_numeric(val) -> bool:
        try:
            float(str(val))
            return True
        except (TypeError, ValueError):
            return False

    reliable = [e for e in apical_bmd_summary if _is_numeric(e.get("bmd"))]

    # Deduplicate reliable by (endpoint, sex) — same endpoint can appear
    # multiple times in the raw data (e.g., from multiple platform tables).
    _seen_reliable: set[tuple] = set()
    _deduped_reliable = []
    for e in reliable:
        key = (e.get("endpoint", ""), e.get("sex", ""))
        if key not in _seen_reliable:
            _seen_reliable.add(key)
            _deduped_reliable.append(e)
    reliable = _deduped_reliable

    urep = [e for e in apical_bmd_summary if e.get("anomalous") or
            (str(e.get("bmd", "")).strip().upper() in ("UREP", "NVM"))]

    # Deduplicate UREP; also collect the set of endpoint names so LOEL-only
    # can exclude endpoints already captured by the UREP classification.
    _seen_urep: set[tuple] = set()
    _deduped_urep = []
    urep_endpoint_keys: set[tuple] = set()
    for e in urep:
        key = (e.get("endpoint", ""), e.get("sex", ""))
        if key not in _seen_urep:
            _seen_urep.add(key)
            _deduped_urep.append(e)
        urep_endpoint_keys.add(key)
    urep = _deduped_urep

    # LOEL-only: statistically significant but no reliable OR unreliable BMD.
    # Exclude endpoints already in the UREP list to keep the three buckets
    # mutually exclusive for clean prose.
    _loel_raw = [
        e for e in apical_bmd_summary
        if not _is_numeric(e.get("bmd"))
        and not e.get("anomalous")
        and str(e.get("bmd", "")).strip().upper() not in ("UREP", "NVM")
        and e.get("loel") is not None
        and (e.get("endpoint", ""), e.get("sex", "")) not in urep_endpoint_keys
    ]
    _seen_loel: set[tuple] = set()
    loel_only = []
    for e in _loel_raw:
        key = (e.get("endpoint", ""), e.get("sex", ""))
        if key not in _seen_loel:
            _seen_loel.add(key)
            loel_only.append(e)

    paragraphs: list[str] = []

    # ── Paragraph 1: overview ───────────────────────────────────────────────
    # Platforms that had at least one reliable BMD or LOEL-only finding.
    active_platforms: list[str] = []
    seen_plats: set[str] = set()
    for e in reliable + loel_only:
        p = e.get("platform", "")
        prose_p = _PLATFORM_PROSE.get(p, p.lower())
        if prose_p not in seen_plats:
            active_platforms.append(prose_p)
            seen_plats.add(prose_p)

    n_reliable = len(reliable)
    if active_platforms:
        plat_phrase = _join_oxford(active_platforms)
        count_phrase = (
            f"{n_reliable} endpoint{'s' if n_reliable != 1 else ''}"
            if n_reliable > 0
            else "no endpoints"
        )
        overview = (
            f"Exposure to {compound_name} resulted in dose-related changes in "
            f"{plat_phrase} measurements. "
            f"Reliable BMD values were calculated for {count_phrase}."
        )
        paragraphs.append(overview)

    # ── Paragraph 2: per-sex findings ──────────────────────────────────────
    sex_sentences: list[str] = []

    for sex in ("Male", "Female"):
        sex_reliable = [e for e in reliable if e.get("sex") == sex]
        sex_urep     = [e for e in urep     if e.get("sex") == sex]
        sex_loel     = [e for e in loel_only if e.get("sex") == sex]

        if not sex_reliable and not sex_urep and not sex_loel:
            sex_sentences.append(
                f"In {sex.lower()} rats, no apical endpoints showed "
                f"dose-related changes."
            )
            continue

        parts: list[str] = []

        if sex_reliable:
            # Sort by BMD ascending so the most sensitive appears first.
            sex_reliable_sorted = sorted(sex_reliable, key=lambda e: float(e["bmd"]))
            most_sensitive = sex_reliable_sorted[0]
            ms_bmd  = most_sensitive["bmd"]
            ms_bmdl = most_sensitive.get("bmdl", "")
            ms_ep   = most_sensitive["endpoint"]
            ms_dir  = most_sensitive.get("direction", "")
            ms_plat = _PLATFORM_PROSE.get(most_sensitive.get("platform", ""),
                                          most_sensitive.get("platform", ""))

            # Direction inside the parenthetical:
            # "Total Thyroxine (decreased; hormone; BMD = 8.54 mg/kg, ...)"
            dir_word = {"UP": "increased", "DOWN": "decreased"}.get(
                (ms_dir or "").upper(), ""
            )
            dir_prefix = f"{dir_word}; " if dir_word else ""

            bmd_range_lo  = ms_bmd
            bmd_range_hi  = sex_reliable_sorted[-1]["bmd"]
            range_phrase = (
                f"BMDs ranged from {bmd_range_lo} to {bmd_range_hi} {dose_unit}"
                if bmd_range_lo != bmd_range_hi
                else f"BMD = {bmd_range_lo} {dose_unit}"
            )

            parts.append(
                f"the most sensitive endpoint was {ms_ep} "
                f"({dir_prefix}{ms_plat}; BMD = {ms_bmd} {dose_unit}, "
                f"BMDL = {ms_bmdl} {dose_unit})"
            )
            if len(sex_reliable) > 1:
                parts.append(f"with {len(sex_reliable)} reliable BMD estimates "
                             f"overall ({range_phrase})")

        if sex_urep:
            ep_list = _join_oxford([e["endpoint"] for e in sex_urep])
            parts.append(
                f"{ep_list} {'was' if len(sex_urep) == 1 else 'were'} flagged "
                f"as unreliable potency estimates (UREP)"
            )

        if sex_loel:
            ep_list = _join_oxford([e["endpoint"] for e in sex_loel])
            parts.append(
                f"no viable BMD model was available for {ep_list}, "
                f"but statistically significant effects were observed "
                f"(LOEL-only)"
            )

        if parts:
            body = "; ".join(parts) + "."
            sex_sentences.append(
                f"In {sex.lower()} rats, {body}"
            )

    if sex_sentences:
        paragraphs.append(" ".join(sex_sentences))

    return paragraphs


def build_abstract_results_apical(
    apical_bmd_summary: list[dict],
    sexes: list[str] | None = None,
) -> str:
    """
    Build the apical-findings portion of the Abstract → Results paragraph.

    Mirrors NIEHS Report 10's per-sex apical summary:

      Several clinical pathology and organ weight measurements showed
      dose-related changes from which BMD values were calculated. In
      male rats, the effects included {direction} {endpoint}, ... The
      BMDs and benchmark dose lower confidence limits (BMDLs) were
      {bmd1} ({bmdl1}), ..., respectively. In female rats, there were
      no apical endpoints for which a BMD value could be reliably
      estimated.

    Strategy:
      1. Lead sentence reports which platform categories had reliable
         BMDs (e.g., "clinical pathology and organ weight" or just
         "organ weight"), or omits the lead if no reliable BMDs exist
         in either sex.
      2. For each sex (in canonical Male, Female order), filter to
         entries with reliable BMDs and a known direction, sort by
         ascending BMD, and emit a "the effects included ..." sentence
         followed by the BMD/BMDL listing.
      3. If a sex has no reliable BMDs, emit the standard "no apical
         endpoints" fallback sentence.

    Args:
        apical_bmd_summary: list of {endpoint, sex, platform, bmd, bmdl,
                            bmd_status, loel, noel, direction} dicts —
                            same structure as data["bmd_summary"]["endpoints"].
        sexes: optional list of sex labels to include (defaults to
               ["Male", "Female"]).  Order is preserved in output.

    Returns:
        A single paragraph string ready to insert into the Abstract.
    """
    if sexes is None:
        sexes = ["Male", "Female"]

    # --- De-duplicate ---
    # The cache may carry duplicate rows where one has BMD values and
    # the other has "—" placeholders.  Keep only the rows with reliable
    # BMD values, dropping the placeholder duplicates.
    reliable = [e for e in apical_bmd_summary if _is_reliable_bmd(e)]

    # --- Anomalous-BMD filter ---
    # Exclude entries whose curve-fit BMD is implausibly low compared to
    # the statistically-observed NOEL/LOEL.  These are model artifacts,
    # not real potency estimates — the reference report excludes them
    # from the Abstract effects list and instead calls them out as
    # anomalous in the body Results section.
    reliable = [e for e in reliable if not _is_anomalous_bmd(e)]

    # --- Lead sentence: which platform categories had findings? ---
    # Group reliable entries by platform → human-readable category name
    PLATFORM_TO_CATEGORY = {
        "Clinical Chemistry": "clinical pathology",
        "Hematology":         "clinical pathology",
        "Hormones":           "clinical pathology",
        "Organ Weight":       "organ weight",
        "Body Weight":        "body weight",
    }
    categories: list[str] = []
    seen: set[str] = set()
    # Order categories by first appearance among reliable entries sorted
    # by sex then platform — gives stable output across runs.
    for entry in sorted(reliable, key=lambda e: (e.get("sex", ""), e.get("platform", ""))):
        cat = PLATFORM_TO_CATEGORY.get(entry.get("platform", ""))
        if cat and cat not in seen:
            categories.append(cat)
            seen.add(cat)

    sentences: list[str] = []
    if categories:
        cat_phrase = _join_oxford(categories)
        sentences.append(
            f"Several {cat_phrase} measurements showed dose-related changes "
            f"from which BMD values were calculated."
        )

    # --- Per-sex apical findings ---
    for sex in sexes:
        sex_entries = [e for e in reliable if e.get("sex") == sex]
        # Filter to entries with a known direction (non-empty)
        sex_entries = [e for e in sex_entries if e.get("direction")]

        if not sex_entries:
            sentences.append(
                f"In {sex.lower()} rats, there were no apical endpoints "
                f"for which a BMD value could be reliably estimated."
            )
            continue

        # Sort by ascending BMD (most sensitive first — matches NIEHS reference)
        sex_entries.sort(key=lambda e: float(e["bmd"]))

        # Build the descriptor phrases and the parallel BMD (BMDL) list
        descriptors = [
            _format_endpoint_phrase(
                e.get("endpoint", ""),
                e.get("direction", ""),
                e.get("platform", ""),
            )
            for e in sex_entries
        ]
        bmd_pairs = [_format_bmd_pair(e["bmd"], e.get("bmdl")) for e in sex_entries]

        # Differentiate "BMD" vs "BMDs" if singular
        plural = len(sex_entries) > 1
        sentences.append(
            f"In {sex.lower()} rats, the effects included "
            f"significantly {_join_oxford(descriptors)}. "
            f"The BMD{'s' if plural else ''} and benchmark dose lower "
            f"confidence limit{'s' if plural else ''} (BMDL{'s' if plural else ''}) "
            f"{'were' if plural else 'was'} {_join_oxford(bmd_pairs)}, "
            f"{'respectively' if plural else ''}".rstrip(", ") + "."
        )

    return " ".join(sentences)


