"""
narrative/apical_bmd_llm.py — the LLM-written analytical paragraph(s) for the
Apical BMD Summary section.

What it does: given the programmatic apical BMD summary rows (endpoint, BMD,
BMDL, LOEL/NOEL, direction), asks the model for a short analytical paragraph
that reads across the table — what the most sensitive endpoints are, how the
apical potency compares across organ systems — and caches the result per
summary-hash under the session directory so an unchanged table never re-calls
the model.

Where it fits: called from pipeline/process_integrated (content preparation,
ADR-0021 concern [2]). The paragraph is *analytical* prose layered under the
deterministic *descriptive* prose built by narrative/abstract_apical.

MOVED 2026-09-18 from web_routes/llm_routes.py: it is a narrative generator,
not an HTTP handler, and pipeline/ importing it from the HTTP package inverted
the layering (ADR-0013).

Failure model: fail-soft. On any error the function returns {"error": msg};
the caller records that in ProcessContext.content_errors so the degraded run
is served once but never cached (see prepare_content_if_changed).
"""

import hashlib
import json
import logging

from common.paths import SESSIONS_DIR
from common.dtxsid import validate_dtxsid
from narrative.background_writer import DEFAULT_CLAUDE_MODEL

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Apical BMD Summary — LLM analytical narrative
# ---------------------------------------------------------------------------

_APICAL_BMD_SYSTEM = """\
You are a toxicologist writing narrative text for an NTP (National Toxicology Program) \
research report on a rodent subchronic toxicity study. \
Your role is to interpret the pattern of apical endpoint benchmark dose (BMD) results \
in terms of biological significance.

Write in a clear, formal scientific style consistent with NTP report conventions. \
Use past tense. Refer to animals as "male rats" / "female rats". \
Do not invent data — work only from the findings provided. \
Write one or two concise paragraphs (3–5 sentences each).\
"""

_APICAL_BMD_PROMPT = """\
The following apical endpoint BMD results were obtained in a {duration} study of {compound} \
administered to rats at doses of {doses} {dose_unit}.

{findings_block}

Write an analytical paragraph (or two) interpreting the biological significance of these \
apical endpoint findings. Address:
  1. Which organ systems or physiological processes showed the greatest sensitivity \
     (lowest BMDs), and what that implies about the primary target organ(s).
  2. Whether the pattern of directional changes across endpoints is biologically coherent \
     (e.g., liver enzyme increases with liver weight gain; thyroid hormone decreases with \
     corresponding compensatory changes).
  3. Sex differences in sensitivity or pattern of response, if notable.
  4. What the BMD range implies about the dose-response relationship \
     (steep vs. shallow, concordant across endpoints).

Do not reproduce the table of values — refer to findings by endpoint name and direction \
only, using approximate BMD magnitudes where helpful (e.g., "at approximately 10 mg/kg"). \
End with a summary sentence on the overall potency of the test article for apical endpoints.\
"""


async def generate_apical_bmd_narrative_async(
    *,
    dtxsid: str,
    compound_name: str,
    dose_unit: str,
    apical_bmd_summary: list[dict],
    study_duration: str = "subchronic (90-day)",
    dose_groups: list[float] | None = None,
) -> dict:
    """
    LLM-generate a biology-grounded analytical paragraph for the Apical
    Endpoint BMD Summary section.

    This is the analytical companion to the programmatic descriptive
    paragraphs produced by build_apical_bmd_summary_narrative().  The LLM
    receives the full findings table as structured text and is asked to
    interpret biological significance, organ-system sensitivity, sex
    differences, and dose-response potency.

    Args:
        dtxsid:             Session DTXSID for cache path.
        compound_name:      Chemical name (e.g., "PFHxSAm").
        dose_unit:          Dose unit string (e.g., "mg/kg").
        apical_bmd_summary: Flat list of endpoint dicts from
                            _build_apical_bmd_summary().
        study_duration:     Plain-English study duration for the prompt
                            (default "subchronic (90-day)").
        dose_groups:        Non-zero dose levels (mg/kg) — used in the
                            prompt to anchor the LLM on actual study doses.

    Returns:
        {"paragraphs": [str, ...], "model_used": str}
        or {"error": str} on failure.
    """
    # --- Cache: keyed on a hash of the BMD summary data ---
    # The apical BMD summary is deterministic — if the data hasn't changed
    # (same integration + NTP stats run), reuse the cached paragraph.
    import orjson
    cache_key = hashlib.md5(
        orjson.dumps(apical_bmd_summary, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()[:16]
    cache_path = SESSIONS_DIR / validate_dtxsid(dtxsid) / f"_cache_apical_narrative_{cache_key}.json"

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            logger.info("Apical BMD narrative cache hit for %s", dtxsid)
            return cached
        except Exception:
            logger.warning("Corrupted apical narrative cache for %s, recomputing", dtxsid)

    # --- Build structured findings block for the prompt ---
    # Group by sex → platform → entries.  Each line: endpoint, direction,
    # BMD/BMDL or UREP/LOEL-only marker.
    lines: list[str] = []
    for sex in ("Male", "Female"):
        sex_entries = [e for e in apical_bmd_summary if e.get("sex") == sex]
        if not sex_entries:
            continue
        lines.append(f"{sex} rats:")
        # Group by platform for readability
        by_plat: dict[str, list[dict]] = {}
        for e in sex_entries:
            plat = e.get("platform", "Other")
            by_plat.setdefault(plat, []).append(e)
        for plat, entries in sorted(by_plat.items()):
            lines.append(f"  {plat}:")
            for e in entries:
                bmd_str = e.get("bmd", "")
                bmdl_str = e.get("bmdl", "")
                direction = e.get("direction", "")
                loel = e.get("loel")
                if bmd_str and str(bmd_str).upper() not in ("UREP", "NVM", ""):
                    try:
                        float(bmd_str)
                        dir_part = f" ({direction})" if direction else ""
                        lines.append(
                            f"    {e['endpoint']}{dir_part}: "
                            f"BMD={bmd_str} {dose_unit}, BMDL={bmdl_str} {dose_unit}"
                        )
                    except (TypeError, ValueError):
                        pass
                elif str(bmd_str).upper() in ("UREP", "NVM"):
                    loel_part = f", LOEL={loel} {dose_unit}" if loel else ""
                    lines.append(
                        f"    {e['endpoint']}: {bmd_str} (unreliable curve fit){loel_part}"
                    )
                elif loel:
                    lines.append(
                        f"    {e['endpoint']}: no reliable BMD, LOEL={loel} {dose_unit}"
                    )

    findings_block = "\n".join(lines) if lines else "(No apical endpoint data available.)"

    # Format non-zero doses
    dose_str = (
        ", ".join(str(d) for d in sorted(dose_groups) if d and d > 0)
        if dose_groups else "not specified"
    )

    prompt = _APICAL_BMD_PROMPT.format(
        compound=compound_name,
        duration=study_duration,
        doses=dose_str,
        dose_unit=dose_unit,
        findings_block=findings_block,
    )

    try:
        from styling_export.llm_endpoints import (
            build_async_anthropic_client,
            resolve_model_name,
        )
        # Build the client through the shared chokepoint rather than a bare
        # AsyncAnthropic(): that is the only place that installs the NIH CA
        # bundle (the SDK ignores REQUESTS_CA_BUNDLE) and resolves the key. A
        # bare client worked locally but failed TLS behind the NIEHS proxy, and
        # the except below turned that into a silently missing paragraph —
        # the same failure shape as the earlier model-name remap bug (see
        # resolve_model_name: hyphen → dot version so the proxy accepts it).
        client = build_async_anthropic_client()
        proxy_model = resolve_model_name(DEFAULT_CLAUDE_MODEL)
        response = await client.messages.create(
            model=proxy_model,
            max_tokens=600,
            system=_APICAL_BMD_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Split on blank lines to produce a list of paragraphs.
        paras = [p.strip() for p in raw.split("\n\n") if p.strip()]
        result = {"paragraphs": paras, "model_used": DEFAULT_CLAUDE_MODEL}

        # Cache the result.
        cache_path.write_text(json.dumps(result))
        return result

    except Exception as e:
        logger.warning("Apical BMD narrative LLM call failed: %s", e)
        return {"error": str(e)}
