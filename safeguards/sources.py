"""
safeguards.sources — a Background is written only from its sources.

The Background states the chemical's toxicology from the hazard assessments
(ATSDR, IRIS) and cites what it says. Without them it can neither state that
toxicology nor say what is missing from it, and prose with no references has
nothing behind its citations: both are refused, nothing saved. The core
generator (narrative.background_writer) writes whatever it is given: the
notebook may draft a Background offline.
"""

from __future__ import annotations

from safeguards.refusals import Refused

# The authoritative hazard sources (narrative.data_gatherer names them so in
# ``unreachable_sources``).
REQUIRED_SOURCES = ("ATSDR", "IRIS")


def require_sources(dtxsid: str, bg_data) -> None:
    """Before the model runs: the hazard sources were reached."""
    blocked = [s for s in REQUIRED_SOURCES if s in (bg_data.unreachable_sources or [])]
    if blocked:
        raise Refused(
            "background_sources_unreachable",
            f"Background for {dtxsid} not generated: {', '.join(blocked)} could not be "
            "reached (run where these sources are reachable, e.g. the NIEHS network)",
            status_code=503, details={"sources": ", ".join(blocked)})


def require_references(dtxsid: str, result: dict) -> None:
    """After it ran: it wrote paragraphs, and they cite sources."""
    if not result.get("paragraphs"):
        raise Refused("background_empty",
                      f"Background for {dtxsid} not saved: the model returned no paragraphs",
                      status_code=502)
    if not result.get("references"):
        raise Refused("background_no_references",
                      f"Background for {dtxsid} not saved: it has no references "
                      "(sources unreachable?)", status_code=502)
