"""
Cross-cutting formatters and BMD-quality predicates for methods narrative.

Most "abstract_X.py" and gene_bodies.py modules in the split need the
same small set of helpers: Oxford-comma joiners, dose-value formatters,
gene-symbol case fixers, BMD reliability/anomaly predicates.  Rather
than pick one of those modules to host them all (and force every other
one to import from it), this module collects them in one neutral place.

What lives here:

  Constants
    _DIRECTION_WORDS         UP/DOWN/empty → adjective for endpoint prose
    ANOMALY_RATIO_THRESHOLD  factor below NOEL/LOEL at which a BMD is flagged
                             for review (pipeline.bmd_review)

  BMD-quality predicates
    _is_reliable_bmd         entry has a parseable, "viable" BMD?

  Pure formatters (single value)
    _format_dose_value       drop trailing zeros, comma-group thousands,
                             render NaN/inf as the dash placeholder
    _format_rat_gene_symbol  NIEHS rat-gene convention (Prlr / Gsta2 /
                             Loc100911545/A2m)
    _stat_display_name       "fifth_pct" → "fifth percentile" etc.

  Joiners (lists → prose)
    _join_oxford             Oxford-comma joiner with "and" before last
    _format_dose_list        Oxford-comma dose list with integer/decimal
                             discrimination and thousand separators
    _format_organ_list       lowercased organ names joined with Oxford
                             comma (mid-sentence usage)
    _format_organ_phrase     alias for _format_organ_list, kept so body-
                             narrative call sites can evolve independently
    _normalize_organ_name    organ key → lowercase string for mid-sentence
    _format_paired_bmd_pairs list of {bmd, bmdl} → "0.520 (0.160), 0.750
                             (0.186)" style sequence

  Filters
    _picks_above_lle         sort items by BMD ascending, keep top N
                             above the lower-limit-of-extrapolation, drop
                             unreliable (NaN/inf BMD or BMDL)

All functions and constants here are pure: no module-level state, no
disk I/O, no LLM calls.  methods_report.py re-exports each name so
existing import sites keep working unchanged.
"""

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Direction words used to convert UP/DOWN flags into adjectives that read
# naturally when prefixed to an endpoint name.
_DIRECTION_WORDS = {
    "UP":   "increased",
    "DOWN": "decreased",
    "":     "altered",  # fallback if direction wasn't recorded
}


# The screen for an unreliable estimate of potency (pipeline.bmd_review): a
# BMD more than this many times below its NOEL (else its LOEL) is FLAGGED for
# a reviewer, who decides.  It only proposes: the NIEHS reports' UREPs are a
# subject matter expert's call (rejected at 10-fold below the NOEL in NIEHS-07
# and -08, accepted at 25-fold in NIEHS-08), and 10 is the lowest fold any of
# them rejected.
ANOMALY_RATIO_THRESHOLD = 10.0


# ---------------------------------------------------------------------------
# BMD-quality predicates
# ---------------------------------------------------------------------------

def _is_reliable_bmd(entry: dict) -> bool:
    """
    Decide whether a BMD summary entry has a reliable, parseable BMD.

    NIEHS reference convention: report "no reliable BMD" when the value
    is missing, the dash placeholder ("—"), an explicit failure marker
    ("NVM" = no viable model), or when bmd_status is something other
    than "viable".
    """
    bmd = entry.get("bmd")
    if bmd is None:
        return False
    s = str(bmd).strip()
    if s in ("", "—", "NVM", "ND", "NA"):
        return False
    # Must be parseable as float
    try:
        float(s)
    except (TypeError, ValueError):
        return False
    if entry.get("bmd_status") and entry["bmd_status"] != "viable":
        return False
    return True


# ---------------------------------------------------------------------------
# Single-value formatters
# ---------------------------------------------------------------------------

def _format_dose_value(v) -> str:
    """
    Format a dose/BMD value preserving sensible precision.  Drops trailing
    zeros while keeping at most 3 decimal places (matches NIEHS reference
    e.g., "0.520", "5.725", "1,000").  NaN/inf values render as the dash
    placeholder used elsewhere for missing data.
    """
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if math.isnan(f) or math.isinf(f):
        return "—"
    if f >= 1000 and f == int(f):
        return f"{int(f):,}"
    if f == int(f):
        return str(int(f))
    # Round to 3 decimal places, strip trailing zeros, restore at least one
    s = f"{f:.3f}".rstrip("0").rstrip(".")
    return s if s else "0"


def genomics_bmd_decimals(genomics_sections: dict | None) -> int | None:
    """The report's BMD precision as the genomics extraction stamped it on
    every section (``bmd_decimals``, from report_bmd_decimals), or None for
    a payload extracted before the stamp (legacy formatting)."""
    for sec in (genomics_sections or {}).values():
        if isinstance(sec, dict) and isinstance(sec.get("bmd_decimals"), int):
            return sec["bmd_decimals"]
    return None


def _format_bmd_value(v, decimals: int | None = None) -> str:
    """
    Format a BMD/BMDL for prose at the report's fixed precision
    (genomics.bmdexpress_categories.report_bmd_decimals), so the Abstract,
    Summary and Results print a value exactly as the tables do.  ``None``
    keeps _format_dose_value's legacy form; a non-numeric value ("NVM",
    "<0.333") passes through and a missing one prints "—".
    """
    if decimals is None:
        return _format_dose_value(v)
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if math.isnan(f) or math.isinf(f):
        return "—"
    from bmdx_pipe.apical_report import format_bmd
    return format_bmd(f, decimals)


def _format_rat_gene_symbol(symbol: str) -> str:
    """
    Convert an uppercase gene symbol (e.g., "PRLR") into NIEHS rat-gene
    convention (e.g., "Prlr") — first letter capitalized, rest lowercase,
    with embedded slashes and digits preserved.

    Examples:
      "PRLR"                  → "Prlr"
      "GSTA2"                 → "Gsta2"
      "LOC100911545/A2M"      → "Loc100911545/A2m"
      "CYP7A1"                → "Cyp7a1"
    """
    if not symbol:
        return symbol
    # Slash-separated multi-symbols: format each segment independently
    if "/" in symbol:
        return "/".join(_format_rat_gene_symbol(s) for s in symbol.split("/"))
    s = symbol.strip()
    if not s:
        return s
    return s[0].upper() + s[1:].lower()


def _stat_display_name(stat_key: str) -> str:
    """
    Convert a BMD aggregation stat key (e.g., "median", "fifth_pct") into
    the prose word used in the abstract sentence ("median", "fifth percentile").
    """
    return {
        "median":     "median",
        "mean":       "mean",
        "fifth_pct":  "fifth percentile",
        "minimum":    "minimum",
        "maximum":    "maximum",
    }.get(stat_key, stat_key.replace("_", " "))


# ---------------------------------------------------------------------------
# List joiners
# ---------------------------------------------------------------------------

def _join_oxford(items: list[str]) -> str:
    """
    Join a list with Oxford comma and "and" before the last element.
    "" → "", ["a"] → "a", ["a","b"] → "a and b",
    ["a","b","c"] → "a, b, and c".
    """
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _format_dose_list(doses: list[float], dose_unit: str) -> str:
    """
    Format a list of dose values into a NIEHS-style comma-separated string.

    Per NIEHS Report 10 convention:
      - Preserve the exact dose values (including leading zero and decimals)
      - Separate with commas, with "and" before the last value
      - Append "mg/kg body weight [mg/kg]" style unit annotation

    Examples:
      _format_dose_list([0, 0.15, 0.5], "mg/kg")
        → "0, 0.15, and 0.5"
      _format_dose_list([4, 37], "mg/kg")
        → "4 and 37"
    """
    if not doses:
        return "(doses not specified)"

    # Format each dose: strip trailing ".0" for integers (with NIEHS-style
    # thousand-separator comma for >=1000), keep decimals otherwise.
    def _fmt(d: float) -> str:
        if d == int(d):
            return f"{int(d):,}"
        return f"{d:g}"

    formatted = [_fmt(d) for d in doses]

    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} and {formatted[1]}"
    return ", ".join(formatted[:-1]) + ", and " + formatted[-1]


def _format_organ_list(organs: list[str]) -> str:
    """
    Format a list of organ names (e.g., ["Liver", "Kidney"]) into natural
    English: "liver and kidney" (two), "liver, kidney, and spleen" (three+),
    "liver" (one).  Lowercases organ names since they appear mid-sentence.
    """
    lc = [o.lower() for o in organs]
    if not lc:
        return ""
    if len(lc) == 1:
        return lc[0]
    if len(lc) == 2:
        return f"{lc[0]} and {lc[1]}"
    return ", ".join(lc[:-1]) + ", and " + lc[-1]


def _format_organ_phrase(organs: list[str]) -> str:
    """
    "liver and kidney" / "liver, kidney, and spleen" / "liver".

    Lowercases organ names since they appear mid-sentence.  Identical
    behavior to _format_organ_list — kept as a separate helper so the
    body-narrative builders can evolve independently.
    """
    return _format_organ_list(organs)


def _normalize_organ_name(organ: str) -> str:
    """
    Normalize an organ key (e.g., 'liver') into title case for headings
    (e.g., 'Liver'), and into lowercase for mid-sentence prose.  This
    helper just returns the lowercase form; callers that need title
    case should capitalize themselves.
    """
    return (organ or "").lower()


def _format_paired_bmd_pairs(items: list[dict], decimals: int | None = None) -> str:
    """
    Format a list of {bmd, bmdl} entries as a NIEHS-style "BMD (BMDL)"
    sequence joined with the Oxford comma, at the report's BMD precision:
      "0.520 (0.160) and 0.750 (0.186)"
      "5.7 (1.7), 7.4 (5.8), and 8.4 (7.1)"
    """
    pairs = [
        f"{_format_bmd_value(it.get('bmd'), decimals)} ({_format_bmd_value(it.get('bmdl'), decimals)})"
        for it in items
    ]
    return _join_oxford(pairs)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def _picks_above_lle(items: list[dict], lle: float, n: int) -> list[dict]:
    """
    Return up to N items sorted by ascending BMD, filtered to those with
    BMD >= lower-limit-of-extrapolation (LLE).  The reference report
    excludes anything below LLE from the "most sensitive" lists.

    Items with NaN/inf BMD or BMDL are treated as unreliable and dropped
    — these come from failed model fits where curve coefficients didn't
    converge.
    """
    reliable: list[dict] = []
    for item in items:
        bmd = item.get("bmd")
        bmdl = item.get("bmdl")
        if bmd is None:
            continue
        try:
            bmd_f = float(bmd)
        except (TypeError, ValueError):
            continue
        if math.isnan(bmd_f) or math.isinf(bmd_f) or bmd_f < lle:
            continue
        # Also filter NaN BMDLs — a NaN BMDL means the lower confidence
        # limit didn't converge, which the reference treats as unreliable.
        try:
            bmdl_f = float(bmdl) if bmdl is not None else None
            if bmdl_f is not None and (math.isnan(bmdl_f) or math.isinf(bmdl_f)):
                continue
        except (TypeError, ValueError):
            pass
        reliable.append({**item, "_bmd_float": bmd_f})

    reliable.sort(key=lambda x: x["_bmd_float"])
    return reliable[:n]
