"""
Regulatory and toxicological data gatherer for background section generation.

For a resolved ChemicalIdentity, collects what a Background is written from,
the way a human author of the published reports does (the routine was read
from the twelve books, 2026-11-23):

  - PubChem's record of the compound: uses, exposure, hazard descriptions;
  - the documents an author consults, each found from the chemical's public
    identifiers and read (narrative.agency_sources): EPA's CompTox dashboard,
    ATSDR's toxicological profile, OECD's SIDS assessment, EPA's IRIS summary,
    the IARC monograph, NTP's technical reports, OSHA's Table Z-1, the NIOSH
    Pocket Guide, ACGIH's Data Hub, EPA's drinking water regulations;
  - papers on the chemical's toxicity, metabolism and kinetics, from PubMed.

Each document is a numbered reference, entered as a reference list cites it,
and its text is passed to the model as that numbered document: the model
writes from what the documents say and cites them by number
(background_writer.py).  A site that could not be read is named in
``unreachable_sources``; that is different from a document that does not
exist for the chemical.

Usage:
    python data_gatherer.py "95-50-1"
"""

import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict

import requests

from narrative.chem_resolver import ChemicalIdentity, resolve_chemical


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Rate limit between API calls (seconds)
RATE_LIMIT = 0.4

# PubChem PUG REST base URL
PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

# PubChem PUG View base URL (for detailed compound descriptions)
PUGVIEW_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"

# User-Agent header for web requests — identifies us as a research tool
USER_AGENT = "BackgroundGenerator/1.0 (toxicology research tool)"


# ---------------------------------------------------------------------------
# Data structure — holds all gathered toxicological/regulatory data
# ---------------------------------------------------------------------------

@dataclass
class BackgroundData:
    """
    All gathered data for a single chemical, organized by source.

    This is the input to background_writer.py, which assembles it into
    a structured 6-paragraph background section.
    """
    # The resolved chemical identity (from chem_resolver.py)
    identity: ChemicalIdentity = field(default_factory=ChemicalIdentity)

    # --- Regulatory limits ---
    # OSHA Permissible Exposure Limit (workplace air concentration, 8-hr TWA)
    osha_pel: str = ""
    # NIOSH Recommended Exposure Limit
    niosh_rel: str = ""
    # ACGIH Threshold Limit Value (paywall — often just a placeholder)
    acgih_tlv: str = ""
    # EPA Safe Drinking Water Act — Maximum Contaminant Level
    epa_mcl: str = ""
    # EPA SDWA — Maximum Contaminant Level Goal (health-based, not enforceable)
    epa_mclg: str = ""
    # EPA IRIS Reference Dose (oral, mg/kg-day)
    iris_rfd: str = ""
    # NOAEL from the IRIS critical study (mg/kg-day)
    iris_noael: str = ""
    # Uncertainty factors applied to derive the RfD
    iris_uf: str = ""
    # What IRIS says of an inhalation reference concentration (RfC): its value,
    # or that none was assessed
    iris_rfc: str = ""
    # EPA/IARC cancer classification (e.g., "Group D — Not classifiable")
    cancer_class: str = ""

    # --- ADME (Absorption, Distribution, Metabolism, Excretion) ---
    absorption_routes: str = ""    # how the chemical enters the body
    distribution: str = ""         # where it goes (organs, tissues, fat)
    metabolism: str = ""           # metabolic enzymes and metabolites
    excretion: str = ""            # how it leaves (urine, feces, exhaled)

    # --- Toxicological effects ---
    acute_effects: str = ""        # effects from single/short exposure
    subchronic_effects: str = ""   # effects from weeks-to-months exposure
    chronic_effects: str = ""      # effects from long-term/lifetime exposure

    # --- Mechanism ---
    mechanism_summary: str = ""    # known or proposed mechanism of toxicity

    # --- Uses (detailed, separated by context) ---
    uses: str = ""                 # general use description from PubChem
    industrial_uses: str = ""      # industrial applications (solvents, intermediates, etc.)
    manufacturing_uses: str = ""   # use as ingredient in manufacturing processes
    consumer_products: str = ""    # presence in consumer products (cleaners, etc.)
    cpdat_uses: list[str] = field(default_factory=list)  # EPA CPDat functional use categories

    # --- Exposure settings ---
    # Occupational, environmental, and consumer scenarios that create
    # potential for human exposure (from ATSDR, PubChem, NIOSH)
    exposure_settings: str = ""    # narrative summary of exposure scenarios
    environmental_fate: str = ""   # environmental fate/transport (air, water, soil)

    # --- Data gap analysis (hazard characterization / risk assessment) ---
    # Populated by build_data_gap_analysis() after all other gathering is done.
    # Each entry: {"domain": ..., "item": ..., "status": "available"|"missing"|"partial",
    #              "detail": ..., "risk_impact": ...}
    data_gaps: list[dict] = field(default_factory=list)

    # --- References: the documents consulted, in the order offered ---
    # Each entry is a reference record (narrative.sources fields: kind,
    # authors, title, container, year, accessed, url) with its source_type.
    references: list[dict] = field(default_factory=list)

    # --- Raw text for LLM context ---
    # These are large blocks of narrative text from ATSDR and IRIS that the
    # LLM can mine for specific facts during the writing step.
    raw_atsdr_text: str = ""
    raw_iris_text: str = ""

    # The number of PubChem's summary among the references (0: none): the
    # uses, exposure and hazard descriptions above are its.
    pubchem_reference: int = 0

    # --- What the documents say, for the model: {"n": the reference's number,
    # "label": the document's title, "text": the part read} ---
    documents: list[dict] = field(default_factory=list)

    # --- Papers on toxicity, metabolism and kinetics (PubMed): reference
    # records (narrative.sources fields) with their "abstract" ---
    mechanism_papers: list[dict] = field(default_factory=list)

    # --- Gathering notes (warnings, gaps, errors) ---
    notes: list[str] = field(default_factory=list)
    # Sources that could not be QUERIED (network/TLS failure, missing API key) —
    # as opposed to queried and found nothing.  The gap analysis reports their
    # items as "unknown", never as missing data.
    unreachable_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dictionary."""
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Helper: HTTP session with polite headers
# ---------------------------------------------------------------------------

def _make_session() -> requests.Session:
    """Create a requests session with a polite User-Agent."""
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


# ---------------------------------------------------------------------------
# PubChem data gathering
# ---------------------------------------------------------------------------

def gather_pubchem(data: BackgroundData, session: requests.Session) -> None:
    """
    Gather chemical description and use data from PubChem PUG View.

    PUG View provides structured sections like "Use and Manufacturing",
    "Safety and Hazards", etc. that complement the PUG REST properties
    already fetched by the resolver.
    """
    cid = data.identity.pubchem_cid
    if not cid:
        data.notes.append("No PubChem CID — skipping PubChem data gathering")
        return

    # Fetch the full PUG View record (structured sections)
    url = f"{PUGVIEW_BASE}/data/compound/{cid}/JSON"
    try:
        time.sleep(RATE_LIMIT)
        r = session.get(url, timeout=30)
        if r.status_code != 200:
            data.notes.append(f"PubChem PUG View returned {r.status_code}")
            return
        view = r.json()
    except (requests.RequestException, ValueError) as e:
        data.notes.append(f"PubChem PUG View error: {e}")
        return

    # Navigate the nested section structure to find uses and hazard summaries
    sections = _flatten_pugview_sections(view)

    # Extract "Use and Manufacturing" section for general uses
    for sec in sections:
        heading = sec.get("TOCHeading", "")
        if "use" in heading.lower() and "manufactur" in heading.lower():
            text = _extract_pugview_text(sec)
            if text:
                data.uses = text[:2000]
                break

    # Extract "Industry Uses" — how the chemical is used in industrial settings
    # (e.g., as a solvent, chemical intermediate, degreasing agent)
    for sec in sections:
        heading = sec.get("TOCHeading", "")
        if heading.lower() == "industry uses" or heading.lower() == "industrial uses":
            text = _extract_pugview_text(sec)
            if text:
                data.industrial_uses = text[:2000]

    # Extract "Consumer Uses" — presence in consumer products
    # (e.g., cleaning agents, deodorizers, paints)
    for sec in sections:
        heading = sec.get("TOCHeading", "")
        if "consumer" in heading.lower() and "use" in heading.lower():
            text = _extract_pugview_text(sec)
            if text:
                data.consumer_products = text[:2000]

    # Extract "Methods of Manufacturing" — how the chemical is made,
    # and its role as an ingredient in manufacturing processes
    for sec in sections:
        heading = sec.get("TOCHeading", "")
        if "manufactur" in heading.lower() and ("method" in heading.lower()
                                                 or "process" in heading.lower()):
            text = _extract_pugview_text(sec)
            if text:
                data.manufacturing_uses = text[:2000]

    # Extract "Formulations/Preparations" — products containing this chemical
    for sec in sections:
        heading = sec.get("TOCHeading", "")
        if "formulation" in heading.lower() or "preparation" in heading.lower():
            text = _extract_pugview_text(sec)
            if text and not data.consumer_products:
                data.consumer_products = text[:2000]

    # Extract "Exposure Summary" / "Exposure Routes" / "Human Exposure" —
    # describes occupational, residential, environmental settings where
    # people may encounter this chemical
    for sec in sections:
        heading = sec.get("TOCHeading", "")
        h_lower = heading.lower()
        if (("exposure" in h_lower and ("summar" in h_lower or "route" in h_lower
                                         or "human" in h_lower or "potential" in h_lower))
            or h_lower == "probable routes of human exposure"):
            text = _extract_pugview_text(sec)
            if text and not data.exposure_settings:
                data.exposure_settings = text[:2000]

    # Extract "Environmental Fate/Exposure" / "Environmental Fate" —
    # how the chemical moves through air, water, soil (informs
    # environmental exposure pathways)
    for sec in sections:
        heading = sec.get("TOCHeading", "")
        h_lower = heading.lower()
        if "environmental" in h_lower and ("fate" in h_lower or "transport" in h_lower):
            text = _extract_pugview_text(sec)
            if text and not data.environmental_fate:
                data.environmental_fate = text[:2000]

    # Extract safety/hazard information
    for sec in sections:
        heading = sec.get("TOCHeading", "")
        if "ghs" in heading.lower() or "hazard" in heading.lower():
            text = _extract_pugview_text(sec)
            if text and not data.acute_effects:
                # GHS hazard statements often describe acute effects
                data.acute_effects = text[:1500]



def _flatten_pugview_sections(view: dict) -> list[dict]:
    """
    Recursively flatten PUG View's nested section tree into a flat list.

    PUG View organizes data in deeply nested Section objects. This helper
    extracts all sections at all levels so we can search by heading name.
    """
    results = []

    def _walk_pugview_sections(obj):
        if isinstance(obj, dict):
            if "TOCHeading" in obj:
                results.append(obj)
            for v in obj.values():
                _walk_pugview_sections(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk_pugview_sections(item)

    _walk_pugview_sections(view)
    return results


def _extract_pugview_text(section: dict) -> str:
    """
    Extract plain text from a PUG View section, concatenating all
    string values found in the nested Information/Value structure.
    """
    texts = []

    def _walk_pugview_text(obj):
        if isinstance(obj, dict):
            # StringWithMarkup is PUG View's text container
            if "String" in obj:
                texts.append(obj["String"])
            if "StringWithMarkup" in obj:
                for item in obj["StringWithMarkup"]:
                    if isinstance(item, dict) and "String" in item:
                        texts.append(item["String"])
            for v in obj.values():
                _walk_pugview_text(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk_pugview_text(item)

    _walk_pugview_text(section)
    return "\n".join(texts)


# ---------------------------------------------------------------------------
# The documents a human author consults (narrative.agency_sources)
# ---------------------------------------------------------------------------

# The order the documents are offered in, and so numbered: the databases that
# identify the chemical, the assessments, then each limit's own document.
# (What each is and how it is found: narrative.agency_sources.)
_ROUTINE = (
    ("pubchem_summary", "PubChem's compound summary"),
    ("comptox", "EPA's CompTox Chemicals Dashboard"),
    ("atsdr_profile", "ATSDR's toxicological profile"),
    ("oecd_sids", "OECD's SIDS initial assessment"),
    ("iris", "EPA's IRIS assessment"),
    ("iarc", "the IARC monograph"),
    ("ntp_reports", "NTP's technical reports"),
    ("osha_table_z", "OSHA's Table Z-1 (29 CFR 1910.1000)"),
    ("niosh", "the NIOSH Pocket Guide"),
    ("acgih", "ACGIH's Data Hub"),
    ("drinking_water", "EPA's drinking water regulations"),
)

# What each document's facts fill of the structured data.
_TEXT_FIELDS = {"atsdr": "raw_atsdr_text", "iris": "raw_iris_text"}


def gather_documents(data: BackgroundData, report=None) -> None:
    """Find and read the documents of the authors' routine for this chemical.
    Each one found becomes a numbered reference (its entry as a reference list
    cites it) and, when it says something, a document the model writes from;
    then the papers PubMed has on its toxicity."""
    from narrative.agency_sources import Finder

    report = report or (lambda message: None)
    finder = Finder(data.identity, report)
    for method, label in _ROUTINE:
        report(f"Looking for {label}...")
        try:
            found = getattr(finder, method)()
        except Exception as exc:  # noqa: BLE001 — one document's failure never stops the rest
            data.notes.append(f"{label}: not read ({type(exc).__name__}: {exc})")
            continue
        for source in (found if isinstance(found, list) else [found]):
            if source is None:
                continue
            data.references.append(source.record)
            number = len(data.references)
            if source.key == "pubchem":
                data.pubchem_reference = number
            if source.text:
                data.documents.append({"n": number, "label": source.record["title"], "text": source.text})
            for key, value in source.facts.items():
                if key == "cpdat_uses":
                    data.cpdat_uses = list(value)
                elif value and key == "cancer_class" and data.cancer_class:
                    data.cancer_class += f"; {value} [{number}]"      # each body's own class
                elif value and not getattr(data, key, ""):
                    setattr(data, key, f"{value} [{number}]")
            if source.key in _TEXT_FIELDS:
                setattr(data, _TEXT_FIELDS[source.key], source.text)

    report("Searching PubMed for papers on its toxicity, metabolism and kinetics...")
    try:
        papers = finder.papers()
    except Exception as exc:  # noqa: BLE001
        data.notes.append(f"PubMed: not searched ({type(exc).__name__}: {exc})")
        papers = []
    for source in papers:
        data.mechanism_papers.append({**source.record, "abstract": source.text})

    data.notes.extend(finder.notes)
    for name in finder.unreachable:
        if name not in data.unreachable_sources:
            data.unreachable_sources.append(name)


# ---------------------------------------------------------------------------
# Data gap analysis — hazard characterization & risk assessment
# ---------------------------------------------------------------------------

def build_data_gap_analysis(data: BackgroundData) -> None:
    """
    Programmatically inventory what hazard characterization and risk assessment
    data is available vs. missing for this chemical.

    Examines every data domain needed for a complete hazard characterization
    (identity, exposure, hazard, dose-response, risk characterization) and
    flags each item as "available", "partial", or "missing" with an
    explanation of the risk assessment impact.

    This gives the LLM a structured checklist to write the data gap
    analysis paragraph.
    """
    gaps = []

    # ---- CHEMICAL IDENTITY ----
    _check_gap(gaps, "Chemical Identity", "CASRN",
               data.identity.casrn,
               "Cannot cross-reference regulatory databases without CASRN")
    _check_gap(gaps, "Chemical Identity", "DTXSID",
               data.identity.dtxsid,
               "Cannot access EPA CompTox hazard or exposure data")
    _check_gap(gaps, "Chemical Identity", "Molecular structure (InChIKey/SMILES)",
               data.identity.inchikey or data.identity.smiles,
               "Cannot perform structure-activity relationship (SAR) analysis "
               "or read-across from structural analogs")

    # ---- EXPOSURE CHARACTERIZATION ----
    _check_gap(gaps, "Exposure", "Industrial/commercial uses",
               data.uses or data.industrial_uses,
               "Cannot identify exposed worker populations or industrial exposure scenarios")
    _check_gap(gaps, "Exposure", "Manufacturing process role",
               data.manufacturing_uses,
               "Unknown whether chemical is used as ingredient in manufacturing — "
               "cannot assess occupational exposure in production facilities")
    _check_gap(gaps, "Exposure", "Consumer product presence",
               data.consumer_products,
               "Cannot characterize general population exposure via consumer products")
    _check_gap(gaps, "Exposure", "Exposure settings and scenarios",
               data.exposure_settings,
               "No characterization of occupational, residential, or environmental "
               "settings that create potential for human exposure — cannot bound "
               "the exposed population or identify high-risk subgroups")
    _check_gap(gaps, "Exposure", "Environmental fate and transport",
               data.environmental_fate,
               "Environmental partitioning unknown — cannot assess exposure via "
               "contaminated air, drinking water, or soil pathways")
    _check_gap(gaps, "Exposure", "OSHA PEL (occupational exposure limit)",
               data.osha_pel,
               "No enforceable workplace air limit established — worker risk "
               "assessment relies on NIOSH REL or ACGIH TLV as surrogates")
    _check_gap(gaps, "Exposure", "NIOSH REL",
               data.niosh_rel,
               "No recommended occupational exposure limit available")
    _check_gap(gaps, "Exposure", "ACGIH TLV",
               data.acgih_tlv and "see ACGIH" not in data.acgih_tlv.lower(),
               "TLV data behind paywall — value not programmatically retrievable")

    # ---- HAZARD IDENTIFICATION ----
    unreachable = set(data.unreachable_sources)

    def _unknown(item_sources: set[str], value) -> bool:
        # Missing only because every source that could supply it was unreachable.
        return not value and bool(item_sources) and item_sources <= unreachable

    _check_gap(gaps, "Hazard Identification", "ATSDR Toxicological Profile",
               data.raw_atsdr_text,
               "No comprehensive federal toxicological profile — ADME, mechanism, "
               "and health effects data may be incomplete or scattered across "
               "primary literature",
               unknown=_unknown({"ATSDR"}, data.raw_atsdr_text))
    _check_gap(gaps, "Hazard Identification", "Acute toxicity data",
               data.acute_effects,
               "Cannot characterize acute hazard for emergency response or "
               "short-term exposure scenarios")
    # A duration the documents read report on is not a gap, whether or not a
    # structured field holds it.
    read = " ".join(d.get("text", "") for d in data.documents).lower()
    subchronic = data.subchronic_effects or re.search(r"subchronic|13-week|90-day|intermediate-duration", read)
    chronic = data.chronic_effects or re.search(r"\bchronic\b|2-year|two-year|carcinogenesis stud", read)
    _check_gap(gaps, "Hazard Identification", "Subchronic toxicity data",
               subchronic,
               "Gap in intermediate-duration exposure assessment — relevant "
               "for occupational and repeated consumer exposure")
    _check_gap(gaps, "Hazard Identification", "Chronic toxicity data",
               chronic,
               "Cannot characterize long-term/lifetime health risks")
    _check_gap(gaps, "Hazard Identification", "Cancer classification",
               data.cancer_class,
               "No authoritative cancer weight-of-evidence determination — "
               "carcinogenic potential is uncharacterized",
               unknown=_unknown({"IRIS", "CTX"}, data.cancer_class))
    _check_gap(gaps, "Hazard Identification", "Mechanism of toxicity",
               data.mechanism_summary or data.raw_atsdr_text or data.mechanism_papers,
               "Molecular mechanism unknown — limits mode-of-action-based "
               "risk assessment and human relevance evaluation")

    # ---- DOSE-RESPONSE ----
    _check_gap(gaps, "Dose-Response", "EPA IRIS assessment",
               data.raw_iris_text,
               "No EPA IRIS assessment — no peer-reviewed federal dose-response "
               "values available",
               unknown=_unknown({"IRIS"}, data.raw_iris_text))
    _check_gap(gaps, "Dose-Response", "Oral reference dose (RfD)",
               data.iris_rfd,
               "No oral RfD — cannot derive health-based oral exposure limits "
               "or drinking water guidelines",
               unknown=_unknown({"IRIS", "CTX"}, data.iris_rfd))
    _check_gap(gaps, "Dose-Response", "NOAEL/LOAEL from critical study",
               data.iris_noael,
               "No identified point of departure — benchmark dose modeling "
               "or read-across may be needed",
               unknown=_unknown({"IRIS", "CTX"}, data.iris_noael))
    # IRIS says whether it derived an RfC; without its word (no assessment
    # read, or one that does not say) whether one exists is unknown, not a gap.
    _check_gap(gaps, "Dose-Response", "Inhalation reference concentration (RfC)",
               data.iris_rfc and "not assessed" not in data.iris_rfc.lower(),
               "No inhalation RfC — cannot derive health-based inhalation limits",
               unknown=not data.iris_rfc)

    # ---- RISK CHARACTERIZATION ----
    _check_gap(gaps, "Risk Characterization", "Drinking water MCL/MCLG",
               data.epa_mcl or data.epa_mclg,
               "No enforceable drinking water standard — environmental "
               "contamination risk is unquantified")
    _check_gap(gaps, "Risk Characterization", "ADME data (absorption, metabolism, excretion)",
               data.absorption_routes or data.metabolism or data.excretion
               or data.raw_atsdr_text,
               "Toxicokinetic data insufficient for PBPK modeling or "
               "human equivalent dose extrapolation")

    data.data_gaps = gaps


def _check_gap(gaps: list[dict], domain: str, item: str,
               value, missing_impact: str, unknown: bool = False) -> None:
    """
    Check whether a data item is available, partial, or missing and append
    the result to the gaps list.

    Args:
        gaps: The list to append to
        domain: Category (e.g., "Dose-Response", "Exposure")
        item: Specific data item being checked
        value: The actual value — truthy means available, falsy means missing
        missing_impact: What it means for risk assessment if this is missing
    """
    if unknown:
        # The only sources for this item could not be queried: say nothing
        # about whether the data exist.
        status = "unknown"
        detail = "Source could not be queried; availability unknown"
        risk_impact = ""
    elif value:
        # Data is available — still record it so the analysis is comprehensive
        status = "available"
        detail = "Data obtained from regulatory database"
        risk_impact = ""
    else:
        status = "missing"
        detail = "Not found in queried databases"
        risk_impact = missing_impact

    gaps.append({
        "domain": domain,
        "item": item,
        "status": status,
        "detail": detail,
        "risk_impact": risk_impact,
    })


# ---------------------------------------------------------------------------
# Main gathering entry point
# ---------------------------------------------------------------------------

def gather_all(identity: ChemicalIdentity,
               progress_callback=None) -> BackgroundData:
    """
    Gather all regulatory and toxicological data for a resolved chemical.

    This is the main entry point. It queries all sources in sequence and
    returns a BackgroundData object with all available data filled in.

    Args:
        identity: A resolved ChemicalIdentity from chem_resolver.py
        progress_callback: Optional callable(str) for status updates (e.g., SSE)

    Returns:
        BackgroundData with all gathered fields
    """
    data = BackgroundData(identity=identity)
    session = _make_session()

    def _report(msg: str):
        """Report progress via callback and print to console."""
        print(f"  [gather] {msg}")
        if progress_callback:
            progress_callback(msg)

    # PubChem's use, exposure and hazard descriptions (the structured data).
    _report("Querying PubChem for chemical data...")
    gather_pubchem(data, session)

    # The documents a human author consults, and the papers.
    gather_documents(data, _report)

    # Final step: Build data gap analysis from hazard characterization
    # and risk assessment standpoint — examines all gathered data and
    # flags what's missing and why it matters
    _report("Building data gap analysis...")
    build_data_gap_analysis(data)

    _report("Data gathering complete.")
    return data


# ---------------------------------------------------------------------------
# CLI — standalone testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python data_gatherer.py <identifier>")
        print()
        print("Examples:")
        print('  python data_gatherer.py "95-50-1"')
        print('  python data_gatherer.py "1,2-Dichlorobenzene"')
        sys.exit(1)

    query = sys.argv[1]
    print(f"Step 1: Resolving chemical identity for '{query}'...")
    identity = resolve_chemical(query)
    print(f"  Name: {identity.name}")
    print(f"  CASRN: {identity.casrn}")
    print(f"  DTXSID: {identity.dtxsid}")
    print(f"  CID: {identity.pubchem_cid}")
    print()

    print("Step 2: Gathering regulatory/toxicological data...")
    bg_data = gather_all(identity)
    print()

    # Print summary
    print("=" * 60)
    print("GATHERED DATA SUMMARY")
    print("=" * 60)
    print(f"  OSHA PEL: {bg_data.osha_pel[:100] or 'not found'}")
    print(f"  NIOSH REL: {bg_data.niosh_rel[:100] or 'not found'}")
    print(f"  IRIS RfD: {bg_data.iris_rfd[:100] or 'not found'}")
    print(f"  IRIS NOAEL: {bg_data.iris_noael[:100] or 'not found'}")
    print(f"  Cancer class: {bg_data.cancer_class[:100] or 'not found'}")
    print(f"  MCL: {bg_data.epa_mcl[:100] or 'not found'}")
    print(f"  ATSDR text: {len(bg_data.raw_atsdr_text)} chars")
    print(f"  IRIS text: {len(bg_data.raw_iris_text)} chars")
    print(f"  Mechanism papers: {len(bg_data.mechanism_papers)}")
    print(f"  References: {len(bg_data.references)}")
    print(f"  Notes: {bg_data.notes}")

    # Save full output as JSON
    out_path = "background_data.json"
    with open(out_path, "w") as f:
        json.dump(bg_data.to_dict(), f, indent=2, default=str)
    print(f"\nFull output saved to {out_path}")
