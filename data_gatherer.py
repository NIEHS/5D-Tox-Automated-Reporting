"""
Regulatory and toxicological data gatherer for background section generation.

For a resolved ChemicalIdentity, queries multiple public databases to collect
the raw data needed to write a structured toxicology background section:

  - EPA CTX Hazard API: RfD, NOAEL, LOAEL, cancer classification, uncertainty factors
  - PubChem: chemical class, description, uses, properties
  - ATSDR ToxProfiles: ADME (absorption, distribution, metabolism, excretion),
    toxicological effects by duration, mechanism of toxicity
  - EPA IRIS: chronic RfD, cancer weight-of-evidence, critical study details
  - OSHA/NIOSH: PELs (Permissible Exposure Limits), RELs, ceiling values
  - Semantic Scholar: recent peer-reviewed papers on mechanism/toxicity

Design note: ATSDR and IRIS pages contain large blocks of narrative text.
Rather than writing fragile parsers to extract specific facts, we pass the
raw text to the LLM along with structured data. The LLM extracts what it
needs during the writing step (background_writer.py).

Usage:
    python data_gatherer.py "95-50-1"
"""

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests

from chem_resolver import ChemicalIdentity, resolve_chemical


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Rate limit between API calls (seconds)
RATE_LIMIT = 0.4

# EPA CTX API base URL
CTX_BASE = "https://api-ccte.epa.gov"

# PubChem PUG REST base URL
PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

# PubChem PUG View base URL (for detailed compound descriptions)
PUGVIEW_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view"

# Semantic Scholar API base URL
S2_BASE = "https://api.semanticscholar.org/graph/v1"

# ATSDR ToxProfiles base URL — the main public repository of toxicological profiles
ATSDR_BASE = "https://www.atsdr.cdc.gov/ToxProfiles"

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

    # --- References collected from all sources ---
    # Each entry: {"url": ..., "title": ..., "source_type": ...}
    references: list[dict] = field(default_factory=list)

    # --- Raw text for LLM context ---
    # These are large blocks of narrative text from ATSDR and IRIS that the
    # LLM can mine for specific facts during the writing step.
    raw_atsdr_text: str = ""
    raw_iris_text: str = ""

    # --- Semantic Scholar papers on mechanism/toxicity ---
    mechanism_papers: list[dict] = field(default_factory=list)

    # --- Gathering notes (warnings, gaps, errors) ---
    notes: list[str] = field(default_factory=list)

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

    data.references.append({
        "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
        "title": f"PubChem Compound {cid}",
        "source_type": "database",
    })


def _flatten_pugview_sections(view: dict) -> list[dict]:
    """
    Recursively flatten PUG View's nested section tree into a flat list.

    PUG View organizes data in deeply nested Section objects. This helper
    extracts all sections at all levels so we can search by heading name.
    """
    results = []

    def _walk(obj):
        if isinstance(obj, dict):
            if "TOCHeading" in obj:
                results.append(obj)
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(view)
    return results


def _extract_pugview_text(section: dict) -> str:
    """
    Extract plain text from a PUG View section, concatenating all
    string values found in the nested Information/Value structure.
    """
    texts = []

    def _walk(obj):
        if isinstance(obj, dict):
            # StringWithMarkup is PUG View's text container
            if "String" in obj:
                texts.append(obj["String"])
            if "StringWithMarkup" in obj:
                for item in obj["StringWithMarkup"]:
                    if isinstance(item, dict) and "String" in item:
                        texts.append(item["String"])
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(section)
    return "\n".join(texts)


# ---------------------------------------------------------------------------
# EPA CTX Hazard API gathering
# ---------------------------------------------------------------------------

def gather_ctx_hazard(data: BackgroundData, session: requests.Session) -> None:
    """
    Gather hazard data from the EPA CompTox (CTX) Hazard API.

    Provides RfD, NOAEL, LOAEL, cancer classification, and uncertainty
    factors from EPA's integrated risk information. Requires a DTXSID and
    the CTX_API_KEY environment variable.
    """
    dtxsid = data.identity.dtxsid
    api_key = os.environ.get("CTX_API_KEY", "")

    if not dtxsid:
        data.notes.append("No DTXSID — skipping CTX Hazard lookup")
        return
    if not api_key:
        data.notes.append("No CTX_API_KEY — skipping CTX Hazard lookup")
        return

    url = f"{CTX_BASE}/hazard/search/by-dtxsid/{dtxsid}"
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    try:
        time.sleep(RATE_LIMIT)
        r = session.get(url, headers=headers, timeout=30)
        if r.status_code != 200:
            data.notes.append(f"CTX Hazard API returned {r.status_code} for {dtxsid}")
            return
        hazard_records = r.json()
    except (requests.RequestException, ValueError) as e:
        data.notes.append(f"CTX Hazard API error: {e}")
        return

    if not isinstance(hazard_records, list):
        return

    # Parse hazard records — each record has a type (e.g., "oral RfD", "cancer")
    for rec in hazard_records:
        if not isinstance(rec, dict):
            continue

        # The hazard endpoint returns a flat list of records with various fields
        tox_type = (rec.get("toxvalType") or "").lower()
        tox_val = rec.get("toxvalNumeric", "")
        units = rec.get("toxvalUnits", "")
        source = rec.get("source", "")
        study_type = (rec.get("studyType") or "").lower()

        # Reference dose from IRIS or other EPA sources
        if "rfd" in tox_type or "reference dose" in tox_type:
            val_str = f"{tox_val} {units}" if tox_val else ""
            if val_str and not data.iris_rfd:
                data.iris_rfd = f"{val_str} (source: {source})"

        # NOAEL values
        if "noael" in tox_type:
            val_str = f"{tox_val} {units}" if tox_val else ""
            if val_str and not data.iris_noael:
                data.iris_noael = f"{val_str} ({study_type}, source: {source})"

        # Cancer classification
        cancer_class = rec.get("cancerCallDescription") or rec.get("supercategory", "")
        if cancer_class and "cancer" in (rec.get("humanHealthHazard") or "").lower():
            if not data.cancer_class:
                data.cancer_class = cancer_class

    data.references.append({
        "url": f"https://comptox.epa.gov/dashboard/chemical/hazard/{dtxsid}",
        "title": f"EPA CompTox Hazard Data for {dtxsid}",
        "source_type": "database",
    })


# ---------------------------------------------------------------------------
# ATSDR ToxProfiles gathering
# ---------------------------------------------------------------------------

def gather_atsdr(data: BackgroundData, session: requests.Session) -> None:
    """
    Gather toxicological profile text from ATSDR (Agency for Toxic
    Substances and Disease Registry).

    ATSDR ToxProfiles are the gold standard for chemical toxicology summaries.
    Each profile has structured chapters covering ADME, health effects,
    mechanism, etc. Not all chemicals have profiles — if absent, the
    background will have thinner ADME/mechanism sections.

    Strategy: Fetch the main ToxProfile page by CASRN, then extract
    relevant text blocks. Since ATSDR recently restructured their site,
    we try multiple URL patterns.
    """
    casrn = data.identity.casrn
    name = data.identity.name
    if not casrn and not name:
        data.notes.append("No CASRN or name — skipping ATSDR lookup")
        return

    # Try the ATSDR ToxFAQs search by chemical name (structured summary)
    # ATSDR provides substance-specific pages at predictable URLs
    atsdr_text = ""
    atsdr_url = ""

    # Try PubChem's ATSDR integration — PubChem links to ATSDR substance pages
    if data.identity.pubchem_cid:
        pugview_url = (
            f"{PUGVIEW_BASE}/data/compound/{data.identity.pubchem_cid}/JSON"
            f"?heading=ATSDR+Toxic+Substances+Portal"
        )
        try:
            time.sleep(RATE_LIMIT)
            r = session.get(pugview_url, timeout=15)
            if r.status_code == 200:
                view = r.json()
                text = _extract_pugview_text(view)
                if text and len(text) > 200:
                    atsdr_text = text
                    # Try to find the actual ATSDR URL from the response
                    atsdr_url = f"https://www.atsdr.cdc.gov/toxfaqs/tfacts{casrn.replace('-', '')}.cfm"
        except (requests.RequestException, ValueError):
            pass

    # Try direct ATSDR ToxFAQs search
    if not atsdr_text:
        search_term = casrn or name
        search_url = (
            "https://wwwn.cdc.gov/TSP/ToxProfiles/ToxProfiles.aspx"
            f"?id=&tid=&casrn={requests.utils.quote(search_term)}"
        )
        try:
            time.sleep(RATE_LIMIT)
            r = session.get(search_url, timeout=30)
            if r.status_code == 200 and len(r.text) > 500:
                # Extract text from HTML (similar to fulltext.py approach)
                atsdr_text = _extract_html_text(r.text)
                atsdr_url = search_url
        except requests.RequestException:
            pass

    # Try the ATSDR minimal risk levels page for this chemical
    if not atsdr_text:
        mrl_url = f"https://wwwn.cdc.gov/TSP/MRLS/mrlslisting.aspx?cas={casrn}"
        try:
            time.sleep(RATE_LIMIT)
            r = session.get(mrl_url, timeout=15)
            if r.status_code == 200 and len(r.text) > 300:
                mrl_text = _extract_html_text(r.text)
                if "mrl" in mrl_text.lower() or "minimal risk" in mrl_text.lower():
                    atsdr_text = mrl_text
                    atsdr_url = mrl_url
        except requests.RequestException:
            pass

    if atsdr_text:
        # Store raw text for LLM (capped at 15K chars to fit in prompt)
        data.raw_atsdr_text = atsdr_text[:15000]
        if atsdr_url:
            data.references.append({
                "url": atsdr_url,
                "title": f"ATSDR Toxicological Profile for {name or casrn}",
                "source_type": "government_report",
            })
    else:
        data.notes.append(
            f"No ATSDR ToxProfile found for {name or casrn}. "
            "ADME and mechanism sections may be thinner."
        )


# ---------------------------------------------------------------------------
# EPA IRIS gathering
# ---------------------------------------------------------------------------

def gather_iris(data: BackgroundData, session: requests.Session) -> None:
    """
    Gather data from EPA's Integrated Risk Information System (IRIS).

    IRIS provides chronic reference doses (RfD), cancer weight-of-evidence
    classifications, and critical study details. The data is available via
    the IRIS assessments page.

    We first check the IRIS summary table (JSON endpoint), then try to
    fetch the full assessment page for raw text.
    """
    casrn = data.identity.casrn
    name = data.identity.name
    if not casrn:
        data.notes.append("No CASRN — skipping IRIS lookup")
        return

    # Try the IRIS assessment search
    iris_url = (
        f"https://cfpub.epa.gov/ncea/iris2/chemicalLanding.cfm"
        f"?substance_nmbr={casrn.replace('-', '')}"
    )
    try:
        time.sleep(RATE_LIMIT)
        r = session.get(iris_url, timeout=30, allow_redirects=True)
        if r.status_code == 200 and len(r.text) > 500:
            iris_text = _extract_html_text(r.text)
            if iris_text and ("reference dose" in iris_text.lower()
                             or "iris" in iris_text.lower()
                             or "cancer" in iris_text.lower()):
                data.raw_iris_text = iris_text[:15000]
                data.references.append({
                    "url": iris_url,
                    "title": f"EPA IRIS Assessment for {name or casrn}",
                    "source_type": "government_report",
                })
            else:
                data.notes.append("IRIS page found but no assessment data detected")
        else:
            data.notes.append(f"IRIS lookup returned {r.status_code}")
    except requests.RequestException as e:
        data.notes.append(f"IRIS lookup error: {e}")

    # Also try the IRIS data via PubChem (PubChem cross-references IRIS)
    if data.identity.pubchem_cid and not data.raw_iris_text:
        pugview_url = (
            f"{PUGVIEW_BASE}/data/compound/{data.identity.pubchem_cid}/JSON"
            f"?heading=EPA+Integrated+Risk+Information+System"
        )
        try:
            time.sleep(RATE_LIMIT)
            r = session.get(pugview_url, timeout=15)
            if r.status_code == 200:
                view = r.json()
                text = _extract_pugview_text(view)
                if text and len(text) > 100:
                    data.raw_iris_text = text[:15000]
        except (requests.RequestException, ValueError):
            pass


# ---------------------------------------------------------------------------
# OSHA / NIOSH gathering
# ---------------------------------------------------------------------------

def gather_osha_niosh(data: BackgroundData, session: requests.Session) -> None:
    """
    Gather occupational exposure limits from OSHA and NIOSH.

    OSHA PEL = legally enforceable workplace limit (8-hour TWA)
    NIOSH REL = recommended limit (not enforceable but often stricter)

    We use PubChem's cross-references to OSHA/NIOSH data, since scraping
    the actual OSHA/NIOSH sites is fragile.
    """
    cid = data.identity.pubchem_cid
    if not cid:
        return

    # PubChem PUG View has NIOSH and OSHA sections under "Safety and Hazards"
    for heading_name, field_name in [
        ("OSHA+Standards", "osha_pel"),
        ("NIOSH+Recommendations", "niosh_rel"),
    ]:
        url = (
            f"{PUGVIEW_BASE}/data/compound/{cid}/JSON"
            f"?heading={heading_name}"
        )
        try:
            time.sleep(RATE_LIMIT)
            r = session.get(url, timeout=15)
            if r.status_code == 200:
                view = r.json()
                text = _extract_pugview_text(view)
                if text:
                    # Extract the actual limit value from the text
                    setattr(data, field_name, text[:500])
        except (requests.RequestException, ValueError):
            pass

    # ACGIH TLV — behind a paywall, so we just note that
    if not data.acgih_tlv:
        data.acgih_tlv = "See ACGIH documentation (subscription required)"

    # Add OSHA/NIOSH references if we found data
    if data.osha_pel:
        data.references.append({
            "url": f"https://www.osha.gov/chemicaldata/",
            "title": "OSHA Chemical Data",
            "source_type": "regulation",
        })
    if data.niosh_rel:
        data.references.append({
            "url": f"https://www.cdc.gov/niosh/npg/",
            "title": "NIOSH Pocket Guide to Chemical Hazards",
            "source_type": "regulation",
        })


# ---------------------------------------------------------------------------
# EPA SDWA (Safe Drinking Water Act) MCL/MCLG
# ---------------------------------------------------------------------------

def gather_sdwa(data: BackgroundData, session: requests.Session) -> None:
    """
    Gather Safe Drinking Water Act Maximum Contaminant Levels.

    MCL = enforceable maximum allowed in drinking water
    MCLG = health-based goal (may be zero for carcinogens)

    Uses PubChem's cross-reference to EPA drinking water data.
    """
    cid = data.identity.pubchem_cid
    if not cid:
        return

    url = (
        f"{PUGVIEW_BASE}/data/compound/{cid}/JSON"
        f"?heading=Drinking+Water+Standards"
    )
    try:
        time.sleep(RATE_LIMIT)
        r = session.get(url, timeout=15)
        if r.status_code == 200:
            view = r.json()
            text = _extract_pugview_text(view)
            if text:
                # Look for MCL and MCLG values in the text
                mcl_match = re.search(
                    r'MCL[^G].*?(\d+\.?\d*\s*(?:mg/L|ppm|ppb|ug/L|μg/L))',
                    text, re.IGNORECASE,
                )
                mclg_match = re.search(
                    r'MCLG.*?(\d+\.?\d*\s*(?:mg/L|ppm|ppb|ug/L|μg/L))',
                    text, re.IGNORECASE,
                )
                if mcl_match:
                    data.epa_mcl = mcl_match.group(0)[:200]
                if mclg_match:
                    data.epa_mclg = mclg_match.group(0)[:200]

                # If we couldn't parse specific values, store the whole text
                if not data.epa_mcl and not data.epa_mclg and text:
                    data.epa_mcl = text[:500]

                data.references.append({
                    "url": "https://www.epa.gov/ground-water-and-drinking-water/national-primary-drinking-water-regulations",
                    "title": "EPA National Primary Drinking Water Regulations",
                    "source_type": "regulation",
                })
    except (requests.RequestException, ValueError):
        pass


# ---------------------------------------------------------------------------
# Semantic Scholar — mechanism/toxicity papers
# ---------------------------------------------------------------------------

def gather_mechanism_papers(data: BackgroundData,
                            session: requests.Session) -> None:
    """
    Search Semantic Scholar for recent peer-reviewed papers on the chemical's
    mechanism of toxicity.

    These papers provide primary literature citations for the mechanism
    paragraph in the background section.
    """
    name = data.identity.name
    if not name:
        return

    # Search for mechanism-of-toxicity papers
    queries = [
        f"{name} mechanism toxicity",
        f"{name} ADME pharmacokinetics",
    ]

    for query in queries:
        url = f"{S2_BASE}/paper/search"
        params = {
            "query": query,
            "limit": 5,
            "fields": "title,year,url,authors,venue,citationCount",
        }
        try:
            time.sleep(RATE_LIMIT)
            r = session.get(url, params=params, timeout=15)
            if r.status_code == 200:
                results = r.json()
                for paper in results.get("data", []):
                    data.mechanism_papers.append({
                        "title": paper.get("title", ""),
                        "year": paper.get("year"),
                        "url": paper.get("url", ""),
                        "venue": paper.get("venue", ""),
                        "citation_count": paper.get("citationCount", 0),
                        "authors": [
                            a.get("name", "") for a in paper.get("authors", [])[:3]
                        ],
                    })
            elif r.status_code == 429:
                # Rate limited — wait and skip
                data.notes.append("Semantic Scholar rate limited — fewer papers retrieved")
                time.sleep(3)
        except requests.RequestException:
            pass

    # Deduplicate by title
    seen_titles = set()
    unique_papers = []
    for p in data.mechanism_papers:
        title_lower = p["title"].lower()
        if title_lower not in seen_titles:
            seen_titles.add(title_lower)
            unique_papers.append(p)
    data.mechanism_papers = unique_papers


# ---------------------------------------------------------------------------
# HTML text extraction helper
# ---------------------------------------------------------------------------

def _extract_html_text(html: str) -> str:
    """
    Extract readable text from HTML, stripping tags and normalizing whitespace.

    Uses BeautifulSoup if available, otherwise falls back to regex-based
    extraction (same approach as fulltext.py).
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        # Remove script and style elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
    except ImportError:
        # Fallback: regex-based extraction (from fulltext.py pattern)
        text = re.sub(r'<script[^>]*>.*?</script>', '', html,
                       flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', html,
                       flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<(?:p|div|br|h[1-6]|li|tr)[^>]*>', '\n', html,
                       flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = text.replace('&amp;', '&').replace('&lt;', '<')
        text = text.replace('&gt;', '>').replace('&nbsp;', ' ')

    # Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ---------------------------------------------------------------------------
# EPA CPDat — Chemicals and Products Database (functional uses, products)
# ---------------------------------------------------------------------------

def gather_cpdat(data: BackgroundData, session: requests.Session) -> None:
    """
    Gather functional use and consumer product data from EPA's CPDat
    (Chemicals and Products Database) via the CTX API.

    CPDat tracks what chemicals are used for (functional uses like "solvent",
    "flame retardant", "plasticizer") and what product categories contain them
    (e.g., "cleaning products", "paints and coatings"). This complements
    PubChem's use data with EPA's product-specific categorization.
    """
    dtxsid = data.identity.dtxsid
    api_key = os.environ.get("CTX_API_KEY", "")

    if not dtxsid or not api_key:
        # Without CTX key or DTXSID, can't query CPDat
        return

    # Fetch functional use data from CTX
    # This endpoint returns categories like "Solvent", "Intermediate",
    # "Cleaning agent", etc.
    url = f"{CTX_BASE}/chemical/functionuse/{dtxsid}"
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    try:
        time.sleep(RATE_LIMIT)
        r = session.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            uses_data = r.json()
            if isinstance(uses_data, list):
                categories = set()
                for item in uses_data:
                    cat = item.get("category", "")
                    if cat:
                        categories.add(cat)
                data.cpdat_uses = sorted(categories)
    except (requests.RequestException, ValueError):
        pass

    # Fetch product/use categories — what kinds of products contain this chemical
    url = f"{CTX_BASE}/chemical/productdata/{dtxsid}"
    try:
        time.sleep(RATE_LIMIT)
        r = session.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            prod_data = r.json()
            if isinstance(prod_data, list) and prod_data:
                product_cats = set()
                for item in prod_data:
                    puc = item.get("pucName", "") or item.get("productCategory", "")
                    if puc:
                        product_cats.add(puc)
                if product_cats and not data.consumer_products:
                    data.consumer_products = "; ".join(sorted(product_cats))

                data.references.append({
                    "url": f"https://comptox.epa.gov/dashboard/chemical/product-data/{dtxsid}",
                    "title": f"EPA CPDat Product Data for {dtxsid}",
                    "source_type": "database",
                })
    except (requests.RequestException, ValueError):
        pass


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
    _check_gap(gaps, "Hazard Identification", "ATSDR Toxicological Profile",
               data.raw_atsdr_text,
               "No comprehensive federal toxicological profile — ADME, mechanism, "
               "and health effects data may be incomplete or scattered across "
               "primary literature")
    _check_gap(gaps, "Hazard Identification", "Acute toxicity data",
               data.acute_effects,
               "Cannot characterize acute hazard for emergency response or "
               "short-term exposure scenarios")
    _check_gap(gaps, "Hazard Identification", "Subchronic toxicity data",
               data.subchronic_effects,
               "Gap in intermediate-duration exposure assessment — relevant "
               "for occupational and repeated consumer exposure")
    _check_gap(gaps, "Hazard Identification", "Chronic toxicity data",
               data.chronic_effects,
               "Cannot characterize long-term/lifetime health risks")
    _check_gap(gaps, "Hazard Identification", "Cancer classification",
               data.cancer_class,
               "No authoritative cancer weight-of-evidence determination — "
               "carcinogenic potential is uncharacterized")
    _check_gap(gaps, "Hazard Identification", "Mechanism of toxicity",
               data.mechanism_summary or data.raw_atsdr_text or data.mechanism_papers,
               "Molecular mechanism unknown — limits mode-of-action-based "
               "risk assessment and human relevance evaluation")

    # ---- DOSE-RESPONSE ----
    _check_gap(gaps, "Dose-Response", "EPA IRIS assessment",
               data.raw_iris_text,
               "No EPA IRIS assessment — no peer-reviewed federal dose-response "
               "values available")
    _check_gap(gaps, "Dose-Response", "Oral reference dose (RfD)",
               data.iris_rfd,
               "No oral RfD — cannot derive health-based oral exposure limits "
               "or drinking water guidelines")
    _check_gap(gaps, "Dose-Response", "NOAEL/LOAEL from critical study",
               data.iris_noael,
               "No identified point of departure — benchmark dose modeling "
               "or read-across may be needed")
    _check_gap(gaps, "Dose-Response", "Inhalation reference concentration (RfC)",
               "",  # We don't currently gather RfC — always a gap to flag
               "No inhalation RfC — cannot derive health-based inhalation limits")

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
               value, missing_impact: str) -> None:
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
    if value:
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

    # Source 1: PubChem (uses, GHS hazards, descriptions)
    _report("Querying PubChem for chemical data...")
    gather_pubchem(data, session)

    # Source 2: EPA CTX Hazard (RfD, NOAEL, cancer class)
    _report("Querying EPA CTX Hazard API...")
    gather_ctx_hazard(data, session)

    # Source 3: ATSDR ToxProfiles (ADME, mechanism, effects)
    _report("Querying ATSDR ToxProfiles...")
    gather_atsdr(data, session)

    # Source 4: EPA IRIS (chronic RfD, cancer WOE)
    _report("Querying EPA IRIS...")
    gather_iris(data, session)

    # Source 5: OSHA/NIOSH (workplace exposure limits)
    _report("Querying OSHA/NIOSH exposure limits...")
    gather_osha_niosh(data, session)

    # Source 6: EPA SDWA (drinking water limits)
    _report("Querying EPA Safe Drinking Water Act...")
    gather_sdwa(data, session)

    # Source 7: Semantic Scholar (mechanism/tox papers)
    _report("Searching Semantic Scholar for mechanism papers...")
    gather_mechanism_papers(data, session)

    # Source 8: EPA CPDat (functional uses, consumer product categories)
    _report("Querying EPA CPDat for product/use data...")
    gather_cpdat(data, session)

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
