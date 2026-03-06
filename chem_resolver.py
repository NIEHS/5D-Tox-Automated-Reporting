"""
Chemical identity resolver for the background section generator.

Given any single chemical identifier (name, CASRN, DTXSID, PubChem CID, or
EC number), resolves all other identifiers by querying PubChem PUG REST and
the EPA CompTox Chemicals Dashboard (CTX) API.

Resolution strategy (two-pass):
  1. PubChem PUG REST (free, no API key):
     - Name/CASRN -> CID via compound search
     - CID -> properties (formula, InChIKey, IUPAC name)
     - CID -> synonyms (mine for CASRN, EC number patterns)
  2. EPA CTX API (free key, optional):
     - CASRN/name -> DTXSID, chemical class, functional uses
     - Falls back to PubChem-only mode if no CTX key is available

Usage:
    python chem_resolver.py "95-50-1"
    python chem_resolver.py "1,2-Dichlorobenzene"
    python chem_resolver.py --dtxsid DTXSID6020430
"""

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# PubChem PUG REST base URL — free, no key required
PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

# EPA CompTox (CTX) API base URL — requires free API key in CTX_API_KEY env var
CTX_BASE = "https://api-ccte.epa.gov"

# Rate limit delay between API calls (seconds) to be a polite client
RATE_LIMIT = 0.3

# Regex patterns for extracting identifiers from synonym lists
# CASRN format: digits-digits-digit (e.g., "95-50-1", "1234-56-7")
CASRN_PATTERN = re.compile(r"^\d{2,7}-\d{2}-\d$")
# EC number format: three digits, hyphen, three digits, hyphen, one digit (e.g., "202-425-9")
EC_PATTERN = re.compile(r"^\d{3}-\d{3}-\d$")
# DTXSID format: DTXSID followed by digits (e.g., "DTXSID6020430")
DTXSID_PATTERN = re.compile(r"^DTXSID\d+$")


# ---------------------------------------------------------------------------
# Data structure — holds the fully resolved chemical identity
# ---------------------------------------------------------------------------

@dataclass
class ChemicalIdentity:
    """
    All known identifiers and metadata for a single chemical substance.

    This is the output of the resolution process. Fields that could not be
    resolved are left as empty strings or empty lists.
    """
    # Core identifiers
    name: str = ""                  # preferred/IUPAC name
    casrn: str = ""                 # CAS Registry Number (e.g., "95-50-1")
    dtxsid: str = ""               # EPA CompTox substance ID (e.g., "DTXSID6020430")
    pubchem_cid: int = 0           # PubChem Compound ID (e.g., 7239)
    ec_number: str = ""            # EC/EINECS number (e.g., "202-425-9")
    inchikey: str = ""             # InChIKey for structure matching

    # Chemical properties
    molecular_formula: str = ""    # e.g., "C6H4Cl2"
    molecular_weight: float = 0.0  # g/mol
    iupac_name: str = ""           # full IUPAC systematic name
    smiles: str = ""               # canonical SMILES string

    # Classification and usage
    chemical_class: str = ""       # broad class (e.g., "chlorinated aromatic hydrocarbon")
    functional_uses: list[str] = field(default_factory=list)  # industrial uses from CTX
    synonyms: list[str] = field(default_factory=list)  # alternate names (capped at 20)

    # Resolution metadata
    resolution_notes: list[str] = field(default_factory=list)  # warnings/gaps encountered

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ChemicalIdentity":
        """
        Reconstruct a ChemicalIdentity from a JSON-safe dictionary.

        Handles type coercion for fields that may arrive as strings or None
        from JSON (e.g., pubchem_cid as "12345" or null, molecular_weight
        as "147.0" or null).  Unknown keys in the dict are silently ignored.

        Args:
            d: Dict with ChemicalIdentity field names as keys.

        Returns:
            A new ChemicalIdentity with all fields populated from the dict.
        """
        return cls(
            name=d.get("name", ""),
            casrn=d.get("casrn", ""),
            dtxsid=d.get("dtxsid", ""),
            pubchem_cid=int(d.get("pubchem_cid", 0) or 0),
            ec_number=d.get("ec_number", ""),
            inchikey=d.get("inchikey", ""),
            molecular_formula=d.get("molecular_formula", ""),
            molecular_weight=float(d.get("molecular_weight", 0) or 0),
            iupac_name=d.get("iupac_name", ""),
            smiles=d.get("smiles", ""),
            chemical_class=d.get("chemical_class", ""),
            functional_uses=d.get("functional_uses", []),
            synonyms=d.get("synonyms", []),
        )


# ---------------------------------------------------------------------------
# PubChem resolver — free, no API key needed
# ---------------------------------------------------------------------------

def _pubchem_get(path: str, params: dict | None = None) -> dict | None:
    """
    Make a GET request to PubChem PUG REST and return parsed JSON.

    Returns None on any error (network, 404, rate limit, etc.) so that
    callers can gracefully fall through to the next resolution strategy.
    """
    url = f"{PUBCHEM_BASE}{path}"
    try:
        time.sleep(RATE_LIMIT)
        r = requests.get(url, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        # PubChem returns 404 for "not found", which is expected for novel chemicals
        return None
    except requests.RequestException:
        return None


def _resolve_cid_from_name(query: str) -> int:
    """
    Look up a PubChem CID by chemical name or CASRN.

    PubChem's /compound/name/ endpoint accepts both systematic names and
    CAS numbers as input. Returns 0 if not found.
    """
    data = _pubchem_get(f"/compound/name/{requests.utils.quote(query)}/cids/JSON")
    if data:
        cids = data.get("IdentifierList", {}).get("CID", [])
        if cids:
            return cids[0]
    return 0


def _resolve_cid_from_cid(cid: int) -> int:
    """Verify a CID exists by fetching it directly. Returns 0 if invalid."""
    data = _pubchem_get(f"/compound/cid/{cid}/cids/JSON")
    if data:
        cids = data.get("IdentifierList", {}).get("CID", [])
        if cids:
            return cids[0]
    return 0


def _fetch_pubchem_properties(cid: int) -> dict:
    """
    Fetch chemical properties for a CID from PubChem.

    Returns a dict with keys like MolecularFormula, InChIKey, IUPACName, etc.
    Returns empty dict if the CID doesn't exist.
    """
    props = "MolecularFormula,MolecularWeight,InChIKey,IUPACName,CanonicalSMILES"
    data = _pubchem_get(f"/compound/cid/{cid}/property/{props}/JSON")
    if data:
        props_list = data.get("PropertyTable", {}).get("Properties", [])
        if props_list:
            return props_list[0]
    return {}


def _fetch_pubchem_synonyms(cid: int) -> list[str]:
    """
    Fetch the synonym list for a CID from PubChem.

    PubChem stores CASRN, EC numbers, trade names, and alternate names as
    synonyms. We mine these for identifiers in a later step.
    """
    data = _pubchem_get(f"/compound/cid/{cid}/synonyms/JSON")
    if data:
        info_list = data.get("InformationList", {}).get("Information", [])
        if info_list:
            return info_list[0].get("Synonym", [])
    return []


def _fetch_pubchem_description(cid: int) -> str:
    """
    Fetch chemical description/classification from PubChem.

    Returns the first available description text, which often contains
    chemical class information useful for the background paragraph.
    """
    data = _pubchem_get(f"/compound/cid/{cid}/description/JSON")
    if data:
        info_list = data.get("InformationList", {}).get("Information", [])
        for info in info_list:
            desc = info.get("Description", "")
            if desc and len(desc) > 20:
                return desc
    return ""


def resolve_via_pubchem(identity: ChemicalIdentity, query: str,
                        query_type: str = "auto") -> None:
    """
    Resolve chemical identifiers using PubChem PUG REST (pass 1).

    Mutates the identity object in place, filling in whatever fields
    PubChem can provide. The query_type parameter controls how the
    query string is interpreted:
      - "auto": try to detect type from format (CASRN, CID, name)
      - "name": treat as chemical name
      - "casrn": treat as CAS Registry Number
      - "cid": treat as PubChem CID (integer)

    This function never raises — all errors are logged to resolution_notes.
    """
    cid = 0

    # Step 1: Resolve the query to a PubChem CID
    if query_type == "cid" or (query_type == "auto" and query.isdigit()):
        cid = _resolve_cid_from_cid(int(query))
        if not cid:
            identity.resolution_notes.append(f"PubChem CID {query} not found")
    elif query_type == "casrn" or (query_type == "auto" and CASRN_PATTERN.match(query)):
        identity.casrn = query
        cid = _resolve_cid_from_name(query)
        if not cid:
            identity.resolution_notes.append(f"PubChem lookup failed for CASRN {query}")
    else:
        # Treat as name
        cid = _resolve_cid_from_name(query)
        if not cid:
            identity.resolution_notes.append(f"PubChem lookup failed for name '{query}'")

    if not cid:
        return

    identity.pubchem_cid = cid

    # Step 2: Fetch chemical properties (formula, weight, InChIKey, etc.)
    props = _fetch_pubchem_properties(cid)
    if props:
        identity.molecular_formula = props.get("MolecularFormula", "")
        identity.iupac_name = props.get("IUPACName", "")
        identity.inchikey = props.get("InChIKey", "")
        identity.smiles = props.get("CanonicalSMILES", "")
        try:
            identity.molecular_weight = float(props.get("MolecularWeight", 0))
        except (ValueError, TypeError):
            pass

    # Step 3: Fetch synonyms and mine them for CASRN, EC number, name
    synonyms = _fetch_pubchem_synonyms(cid)
    if synonyms:
        # Use first synonym as the preferred name if we don't have one yet
        if not identity.name:
            identity.name = synonyms[0]

        # Mine synonyms for identifiers we're missing
        for syn in synonyms:
            if not identity.casrn and CASRN_PATTERN.match(syn):
                identity.casrn = syn
            if not identity.ec_number and EC_PATTERN.match(syn):
                identity.ec_number = syn
            if not identity.dtxsid and DTXSID_PATTERN.match(syn):
                identity.dtxsid = syn

        # Store a capped subset of synonyms for reference
        identity.synonyms = synonyms[:20]

    # Step 4: Try to get a description for chemical class
    if not identity.chemical_class:
        desc = _fetch_pubchem_description(cid)
        if desc:
            # The description often starts with the chemical class
            identity.chemical_class = desc[:300]

    # Use IUPAC name as fallback if no preferred name found
    if not identity.name and identity.iupac_name:
        identity.name = identity.iupac_name


# ---------------------------------------------------------------------------
# EPA CTX resolver — requires free API key (optional second pass)
# ---------------------------------------------------------------------------

def _ctx_get(path: str, params: dict | None = None,
             api_key: str = "") -> dict | list | None:
    """
    Make a GET request to the EPA CTX API.

    The CTX API requires a free API key passed as an x-api-key header.
    Returns None on any error so callers can fall through gracefully.
    """
    if not api_key:
        return None
    url = f"{CTX_BASE}{path}"
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    try:
        time.sleep(RATE_LIMIT)
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
        return None
    except requests.RequestException:
        return None


def resolve_via_ctx(identity: ChemicalIdentity, api_key: str = "") -> None:
    """
    Resolve additional identifiers using the EPA CompTox (CTX) API (pass 2).

    Fills in DTXSID, chemical class, and functional uses that PubChem
    doesn't provide. Requires a free API key (set CTX_API_KEY env var).

    If no API key is available, this function is a no-op and logs a note.
    """
    if not api_key:
        identity.resolution_notes.append(
            "CTX API key not available — DTXSID and hazard data may be limited. "
            "Set CTX_API_KEY env var (free key from ccte_api@epa.gov)."
        )
        return

    # Try to find the chemical by CASRN first, then by name
    search_term = identity.casrn or identity.name
    if not search_term:
        identity.resolution_notes.append("No CASRN or name available for CTX lookup")
        return

    # Search for the chemical in CTX
    # The /chemical/search/by-name/ endpoint accepts both names and CASRNs
    data = _ctx_get(
        f"/chemical/search/by-name/{requests.utils.quote(search_term)}",
        api_key=api_key,
    )

    if not data:
        # Try the equal endpoint for exact CASRN match
        if identity.casrn:
            data = _ctx_get(
                f"/chemical/detail/search/by-casrn/{identity.casrn}",
                api_key=api_key,
            )

    if not data:
        identity.resolution_notes.append(f"CTX lookup failed for '{search_term}'")
        return

    # CTX returns either a single object or a list — normalize to dict
    record = data[0] if isinstance(data, list) and data else data
    if not isinstance(record, dict):
        return

    # Extract DTXSID if we don't have it yet
    dtxsid = record.get("dtxsid", "")
    if dtxsid and not identity.dtxsid:
        identity.dtxsid = dtxsid

    # Extract chemical class/type from CTX
    chem_type = record.get("substanceType", "")
    if chem_type and not identity.chemical_class:
        identity.chemical_class = chem_type

    # Fetch functional uses if we have a DTXSID
    if identity.dtxsid:
        uses_data = _ctx_get(
            f"/chemical/functionuse/{identity.dtxsid}",
            api_key=api_key,
        )
        if uses_data and isinstance(uses_data, list):
            uses = set()
            for item in uses_data:
                category = item.get("category", "")
                if category:
                    uses.add(category)
            identity.functional_uses = sorted(uses)


# ---------------------------------------------------------------------------
# Main resolution entry point
# ---------------------------------------------------------------------------

def resolve_chemical(query: str, query_type: str = "auto",
                     ctx_api_key: str = "") -> ChemicalIdentity:
    """
    Resolve a chemical identifier to all available identifiers and metadata.

    This is the main entry point. It runs two passes:
      1. PubChem PUG REST — resolves CID, CASRN, name, formula, InChIKey, etc.
      2. EPA CTX API — resolves DTXSID, functional uses, chemical class

    Args:
        query: The chemical identifier to look up (name, CASRN, CID, or DTXSID)
        query_type: How to interpret the query ("auto", "name", "casrn", "cid", "dtxsid")
        ctx_api_key: EPA CTX API key (defaults to CTX_API_KEY env var)

    Returns:
        ChemicalIdentity with all resolved fields filled in
    """
    identity = ChemicalIdentity()

    # Get CTX API key from parameter or environment
    api_key = ctx_api_key or os.environ.get("CTX_API_KEY", "")

    # Detect query type if set to auto
    if query_type == "auto":
        if DTXSID_PATTERN.match(query):
            query_type = "dtxsid"
        elif CASRN_PATTERN.match(query):
            query_type = "casrn"
        elif query.isdigit():
            query_type = "cid"
        else:
            query_type = "name"

    # Handle DTXSID input — need to go through CTX first to get CASRN/name
    if query_type == "dtxsid":
        identity.dtxsid = query
        if api_key:
            # Look up DTXSID in CTX to get CASRN and name
            data = _ctx_get(
                f"/chemical/detail/search/by-dtxsid/{query}",
                api_key=api_key,
            )
            if data:
                record = data[0] if isinstance(data, list) and data else data
                if isinstance(record, dict):
                    casrn = record.get("casrn", "")
                    name = record.get("preferredName", "")
                    if casrn:
                        identity.casrn = casrn
                    if name:
                        identity.name = name
        # Now resolve via PubChem using whatever we got
        pubchem_query = identity.casrn or identity.name or query
        resolve_via_pubchem(identity, pubchem_query, "auto")
    else:
        # Normal flow: PubChem first
        resolve_via_pubchem(identity, query, query_type)

    # Pass 2: EPA CTX for DTXSID, uses, chemical class
    resolve_via_ctx(identity, api_key)

    return identity


# ---------------------------------------------------------------------------
# CLI — standalone testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python chem_resolver.py <identifier> [--type name|casrn|cid|dtxsid]")
        print()
        print("Examples:")
        print('  python chem_resolver.py "95-50-1"')
        print('  python chem_resolver.py "1,2-Dichlorobenzene"')
        print('  python chem_resolver.py "7239" --type cid')
        print('  python chem_resolver.py "DTXSID6020430" --type dtxsid')
        sys.exit(1)

    query = sys.argv[1]
    qtype = "auto"

    # Parse optional --type argument
    if "--type" in sys.argv:
        idx = sys.argv.index("--type")
        if idx + 1 < len(sys.argv):
            qtype = sys.argv[idx + 1]

    print(f"Resolving: '{query}' (type={qtype})")
    print()

    result = resolve_chemical(query, query_type=qtype)
    print(json.dumps(result.to_dict(), indent=2))
