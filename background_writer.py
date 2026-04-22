"""
LLM-based background section writer for toxicology studies.

Takes a BackgroundData object (from data_gatherer.py) and generates a
structured 6-paragraph background/introduction section suitable for
"5 Day Genomic Dose Response in Sprague-Dawley Rats" study reports.

Paragraph structure (matches Scott Auerbach's template):
  1. Chemical identity & uses (CASRN, DTXSID, CID, EC#, class, industrial uses)
  2. Regulatory limits (OSHA PEL, NIOSH REL, ACGIH TLV, SDWA MCL/MCLG, IRIS RfD)
  3. Exposure routes & ADME (absorption, distribution, metabolism, excretion)
  4. Toxicological effects by duration (acute, subchronic, chronic, carcinogenicity)
  5. Mechanism of toxicity (reactive intermediates, oxidative stress, etc.)
  6. Study purpose (linking to the specific 5-day genomic dose-response study)

LLM selection:
  - Primary: Claude API (best formal scientific prose) via AnthropicEndpoint
  - Fallback: Ollama local models via OllamaEndpoint
  Both endpoint classes are imported from the existing codebase.

Usage:
    # Usually called from background_server.py, but can be run standalone:
    python background_writer.py "95-50-1"
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field

from chem_resolver import ChemicalIdentity, resolve_chemical
from data_gatherer import BackgroundData, gather_all


# ---------------------------------------------------------------------------
# Import LLM endpoints from existing codebase
# ---------------------------------------------------------------------------

# AnthropicEndpoint wraps the Claude API (reads ANTHROPIC_API_KEY from env)
from interpret import AnthropicEndpoint

# OllamaEndpoint wraps local Ollama instances (Qwen, Llama, etc.)
from extract import OllamaEndpoint, LOCAL_OLLAMA, REMOTE_OLLAMA


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default Claude model for background generation — Claude produces the best
# formal scientific prose for this use case
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"

# Maximum tokens for the background generation response — 6 paragraphs with
# inline references typically runs 2000-3000 tokens
MAX_TOKENS = 8192

# Temperature for generation — lower = more factual/conservative, which is
# what we want for regulatory/toxicological text
GENERATION_TEMPERATURE = 0.3


# ---------------------------------------------------------------------------
# Style reference — Scott Auerbach's 1,2-DCB example
# (Included in the prompt so the LLM matches this exact style)
# ---------------------------------------------------------------------------

STYLE_EXAMPLE = """
STYLE REFERENCE (1,2-Dichlorobenzene background, by Scott Auerbach):

1,2-Dichlorobenzene (CASRN: 95-50-1; DTXSID: DTXSID6020430; PubChem CID: 7239;
EC Number: 202-425-9) is a chlorinated aromatic hydrocarbon. It is used as an
industrial solvent, fumigant, and chemical intermediate in the production of dyes,
herbicides, and pharmaceuticals [1]. It is also found as a component of some
consumer products, including deodorizers and cleaning agents [2].

The Occupational Safety and Health Administration (OSHA) has established a
permissible exposure limit (PEL) for 1,2-dichlorobenzene of 50 ppm (300 mg/m³)
as an 8-hour time-weighted average (TWA). The National Institute for Occupational
Safety and Health (NIOSH) recommends an exposure limit (REL) of 25 ppm (150 mg/m³)
as a 10-hour TWA. The American Conference of Governmental Industrial Hygienists
(ACGIH) has assigned a threshold limit value (TLV) of 25 ppm (150 mg/m³) as an
8-hour TWA [3]. Under the Safe Drinking Water Act, the EPA has established a
maximum contaminant level (MCL) of 0.6 mg/L and a maximum contaminant level goal
(MCLG) of 0.6 mg/L for 1,2-dichlorobenzene [4]. The EPA Integrated Risk
Information System (IRIS) has established an oral reference dose (RfD) of
0.09 mg/kg-day based on a NOAEL of 9 mg/kg-day from a subchronic study in rats,
with an uncertainty factor of 100 [5].

NOTE: The above is a partial example showing the target style. Your output should
follow this same formal, citation-heavy, regulatory-focused prose style.
""".strip()


# ---------------------------------------------------------------------------
# Prompt assembly — builds the complete LLM prompt from gathered data
# ---------------------------------------------------------------------------

def build_prompt(data: BackgroundData,
                 style_rules: list[str] | None = None) -> str:
    """
    Assemble the complete LLM prompt from gathered toxicological data.

    The prompt includes:
      1. The target 6-paragraph structure with explicit descriptions
      2. All structured regulatory/tox data with source attribution
      3. Raw ATSDR/IRIS text for the LLM to mine for ADME/mechanism facts
      4. Scott's example as a style reference
      5. Instructions for inline [N] references and reference list
      6. (Optional) Learned writing style preferences from prior user edits

    Args:
        data: BackgroundData containing all gathered toxicological info
        style_rules: Optional list of learned style rule strings to inject
            into the prompt.  These come from the global style profile and
            represent writing preferences the user has demonstrated through
            previous edits (e.g., "Use 'test article' instead of 'compound'").

    Returns the complete prompt string ready to send to the LLM.
    """
    identity = data.identity

    # Build the structured data section
    structured_data = _format_structured_data(data)

    # Build the reference inventory section
    ref_inventory = _format_reference_inventory(data)

    # Build the raw text sections (ATSDR + IRIS for LLM context)
    raw_sections = _format_raw_text_sections(data)

    # Build the mechanism papers section
    papers_section = _format_mechanism_papers(data)

    prompt = f"""You are a senior toxicologist writing a background/introduction section for a
"5 Day Genomic Dose Response in Sprague-Dawley Rats" study report. Write formal
scientific prose with inline numbered references in [N] format.

CHEMICAL: {identity.name} (CASRN: {identity.casrn})

{STYLE_EXAMPLE}

=== STRUCTURED DATA (from regulatory databases) ===

{structured_data}

=== REFERENCE SOURCES AVAILABLE ===

{ref_inventory}

{raw_sections}

{papers_section}

=== INSTRUCTIONS ===

Write exactly 7 paragraphs following this structure:

PARAGRAPH 1 — Chemical Identity, Uses, Products & Exposure Settings
- Start with the full chemical name and all identifiers in parentheses:
  (CASRN: {identity.casrn}; DTXSID: {identity.dtxsid}; PubChem CID: {identity.pubchem_cid}; EC Number: {identity.ec_number})
- State the chemical class (e.g., "chlorinated aromatic hydrocarbon",
  "organophosphate ester", "phthalate diester")
- INDUSTRIAL USES — be specific about which industries and what role:
  name the specific industrial processes (e.g., "used as a solvent in metal
  degreasing operations", "serves as a chemical intermediate in the synthesis
  of agrochemicals", "employed as a heat transfer fluid in closed-loop systems")
- MANUFACTURING INGREDIENT — describe what products it is used to make:
  (e.g., "used as an intermediate in the production of 1,4-dichlorobenzene,
  dyes, herbicides, and pharmaceuticals", "serves as a feedstock for polymer
  production", "incorporated as a plasticizer in PVC formulations")
- INDUSTRIAL PRODUCTS containing this chemical — name them:
  (e.g., "component of industrial solvents and degreasing formulations",
  "present in dielectric fluids", "used in metal cleaning solutions")
- CONSUMER PRODUCTS containing this chemical — name specific product types:
  (e.g., "found in household deodorizers, moth control products, and
  drain cleaning formulations", "present in consumer-grade adhesives,
  paints, and lacquers", "used in automotive care products")
- EXPOSURE SETTINGS — describe specific occupational, residential, and
  environmental settings that create potential for human exposure:
  * Occupational: workers in which industries? (e.g., "chemical manufacturing
    plant operators", "metal degreasing workers", "pesticide applicators")
  * Residential/consumer: how does the general public encounter it?
    (e.g., "use of consumer products containing the chemical in enclosed
    spaces", "residential proximity to manufacturing facilities")
  * Environmental: contamination pathways? (e.g., "volatilization from
    industrial wastewater into ambient air", "leaching into groundwater
    from contaminated soil at disposal sites")
- If EPA CPDat functional use categories are available, incorporate them
- Cite sources for each use and exposure claim

PARAGRAPH 2 — Regulatory Limits
- OSHA PEL (with units, TWA period)
- NIOSH REL (with units, TWA period)
- ACGIH TLV (with units, or note if unavailable)
- EPA SDWA MCL and MCLG (with units)
- EPA IRIS oral RfD with NOAEL, critical study, and uncertainty factor
- Each regulatory value must cite its source

PARAGRAPH 3 — Exposure Routes & ADME
- Routes of exposure (inhalation, oral, dermal)
- Absorption characteristics
- Distribution to organs/tissues
- Metabolism (enzymes involved, key metabolites)
- Excretion routes and half-lives
- Cite ATSDR ToxProfile or primary literature

PARAGRAPH 4 — Toxicological Effects by Duration
- Acute effects (single/short-term exposure)
- Subacute/subchronic effects (weeks to months)
- Chronic effects (long-term/lifetime)
- Carcinogenicity classification (EPA, IARC if available)
- Cite specific studies where possible

PARAGRAPH 5 — Mechanism of Toxicity
- Known or proposed mechanism(s) of action
- Reactive intermediates, oxidative stress, receptor interactions
- Key molecular targets and pathways
- Cite primary literature or ATSDR/IRIS assessments

PARAGRAPH 6 — Data Gap Analysis (Hazard Characterization & Risk Assessment)
- Systematically identify what toxicological and regulatory data is MISSING
  or INSUFFICIENT for a complete hazard characterization and risk assessment
- Organize by domain: exposure characterization, hazard identification,
  dose-response assessment, risk characterization
- For each gap, explain WHY it matters (e.g., "No inhalation RfC has been
  established, precluding derivation of health-based inhalation exposure limits")
- Note which data domains ARE well-characterized (e.g., "Oral dose-response
  data are adequate based on the IRIS RfD...")
- Mention if key assessments (ATSDR ToxProfile, IRIS assessment) are absent
- Be specific: name the missing data type, the regulatory implication,
  and whether surrogate or read-across data might be available
- Use the DATA GAP INVENTORY provided below to write this paragraph

PARAGRAPH 7 — Study Purpose
- One to two sentences connecting all the above to the specific study
- Template: "Given the [uses/exposure potential] of [chemical], its
  [key tox effects], and the [identified data gaps], this 5 day genomic
  dose response study in Sprague-Dawley rats was conducted to
  [characterize gene expression changes / identify molecular targets /
  fill specific knowledge gaps / etc.]."

{_format_style_rules(style_rules)}=== FORMAT REQUIREMENTS ===

- Use inline numbered references: [1], [2], [3], etc.
- After the 7 paragraphs, include a "References" section listing all citations
- Each reference should include: [N] Author/Organization. "Title." Source/URL. Year.
- Write in third person, past tense for completed studies, present tense for
  established facts
- If data is unavailable for a section, note the gap briefly (e.g.,
  "No ATSDR ToxProfile is available for this chemical.")
- Do NOT invent data — only use what is provided above
- Match the formal, regulatory-focused tone of the style reference

Output ONLY the 7 paragraphs followed by the References section. No preamble,
no commentary, no markdown headers (just paragraph text and a "References" label).
"""

    return prompt


def _format_structured_data(data: BackgroundData) -> str:
    """Format all structured regulatory/tox data into a readable block."""
    identity = data.identity
    lines = []

    # Chemical identity
    lines.append("Chemical Identity:")
    lines.append(f"  Name: {identity.name}")
    lines.append(f"  CASRN: {identity.casrn}")
    lines.append(f"  DTXSID: {identity.dtxsid}")
    lines.append(f"  PubChem CID: {identity.pubchem_cid}")
    lines.append(f"  EC Number: {identity.ec_number}")
    lines.append(f"  Molecular Formula: {identity.molecular_formula}")
    lines.append(f"  Molecular Weight: {identity.molecular_weight} g/mol")
    lines.append(f"  IUPAC Name: {identity.iupac_name}")
    lines.append(f"  Chemical Class: {identity.chemical_class}")
    if identity.functional_uses:
        lines.append(f"  Functional Uses (CTX): {', '.join(identity.functional_uses)}")
    lines.append("")

    # Regulatory limits
    lines.append("Regulatory Limits:")
    lines.append(f"  OSHA PEL: {data.osha_pel or 'Not found'}")
    lines.append(f"  NIOSH REL: {data.niosh_rel or 'Not found'}")
    lines.append(f"  ACGIH TLV: {data.acgih_tlv or 'Not found'}")
    lines.append(f"  EPA MCL: {data.epa_mcl or 'Not found'}")
    lines.append(f"  EPA MCLG: {data.epa_mclg or 'Not found'}")
    lines.append(f"  EPA IRIS RfD: {data.iris_rfd or 'Not found'}")
    lines.append(f"  EPA IRIS NOAEL: {data.iris_noael or 'Not found'}")
    lines.append(f"  EPA IRIS UF: {data.iris_uf or 'Not found'}")
    lines.append(f"  Cancer Classification: {data.cancer_class or 'Not found'}")
    lines.append("")

    # Uses (detailed by context)
    lines.append("Uses & Products:")
    if data.uses:
        lines.append(f"  General: {data.uses[:1500]}")
    if data.industrial_uses:
        lines.append(f"  Industrial uses: {data.industrial_uses[:1500]}")
    if data.manufacturing_uses:
        lines.append(f"  Manufacturing ingredient/feedstock: {data.manufacturing_uses[:1500]}")
    if data.consumer_products:
        lines.append(f"  Consumer products containing this chemical: {data.consumer_products[:1500]}")
    if data.cpdat_uses:
        lines.append(f"  EPA CPDat functional use categories: {', '.join(data.cpdat_uses)}")
    if not any([data.uses, data.industrial_uses, data.manufacturing_uses,
                data.consumer_products, data.cpdat_uses]):
        lines.append("  No use/product data found")
    lines.append("")

    # Exposure settings and environmental fate
    lines.append("Exposure Settings & Environmental Fate:")
    if data.exposure_settings:
        lines.append(f"  Exposure scenarios: {data.exposure_settings[:1500]}")
    else:
        lines.append("  Exposure scenarios: Not found — LLM should infer likely "
                     "occupational and consumer exposure settings from the use data above")
    if data.environmental_fate:
        lines.append(f"  Environmental fate/transport: {data.environmental_fate[:1500]}")
    else:
        lines.append("  Environmental fate: Not found")
    lines.append("")

    # ADME (if gathered directly)
    if any([data.absorption_routes, data.distribution,
            data.metabolism, data.excretion]):
        lines.append("ADME:")
        if data.absorption_routes:
            lines.append(f"  Absorption: {data.absorption_routes}")
        if data.distribution:
            lines.append(f"  Distribution: {data.distribution}")
        if data.metabolism:
            lines.append(f"  Metabolism: {data.metabolism}")
        if data.excretion:
            lines.append(f"  Excretion: {data.excretion}")
        lines.append("")

    # Tox effects
    if any([data.acute_effects, data.subchronic_effects, data.chronic_effects]):
        lines.append("Toxicological Effects:")
        if data.acute_effects:
            lines.append(f"  Acute: {data.acute_effects[:500]}")
        if data.subchronic_effects:
            lines.append(f"  Subchronic: {data.subchronic_effects[:500]}")
        if data.chronic_effects:
            lines.append(f"  Chronic: {data.chronic_effects[:500]}")
        lines.append("")

    # Mechanism
    if data.mechanism_summary:
        lines.append("Mechanism of Toxicity:")
        lines.append(f"  {data.mechanism_summary[:500]}")
        lines.append("")

    # Gathering notes (warnings from data collection)
    if data.notes:
        lines.append("Gathering Notes:")
        for note in data.notes:
            lines.append(f"  - {note}")
        lines.append("")

    # Data gap inventory — structured checklist for the data gap analysis paragraph
    if data.data_gaps:
        lines.append("=== DATA GAP INVENTORY (for Paragraph 6) ===")
        lines.append("Use this inventory to write the data gap analysis paragraph.")
        lines.append("Focus on MISSING items and their risk assessment impact.")
        lines.append("")

        # Group by domain
        current_domain = ""
        missing_count = 0
        available_count = 0
        for gap in data.data_gaps:
            domain = gap["domain"]
            if domain != current_domain:
                lines.append(f"  [{domain}]")
                current_domain = domain

            status = gap["status"]
            item = gap["item"]
            if status == "available":
                lines.append(f"    [OK] {item}")
                available_count += 1
            else:
                lines.append(f"    [MISSING] {item}")
                lines.append(f"            Impact: {gap['risk_impact']}")
                missing_count += 1

        lines.append("")
        lines.append(f"  Summary: {available_count} data items available, "
                     f"{missing_count} missing or insufficient")

    return "\n".join(lines)


def _format_reference_inventory(data: BackgroundData) -> str:
    """Format all collected references into a numbered inventory."""
    if not data.references:
        return "No references collected."

    lines = ["Available references (use these for inline citations):"]
    for i, ref in enumerate(data.references, 1):
        title = ref.get("title", "")
        url = ref.get("url", "")
        source_type = ref.get("source_type", "")
        lines.append(f"  [{i}] {title} ({source_type}) — {url}")

    return "\n".join(lines)


def _format_raw_text_sections(data: BackgroundData) -> str:
    """Format raw ATSDR and IRIS text blocks for LLM context."""
    parts = []

    if data.raw_atsdr_text:
        parts.append("=== RAW ATSDR TOXPROFILE TEXT ===")
        parts.append("(Extract ADME, mechanism, and health effects from this text)")
        parts.append(data.raw_atsdr_text[:12000])
        parts.append("")

    if data.raw_iris_text:
        parts.append("=== RAW EPA IRIS TEXT ===")
        parts.append("(Extract RfD, cancer classification, and critical study from this text)")
        parts.append(data.raw_iris_text[:12000])
        parts.append("")

    return "\n".join(parts) if parts else ""


def _format_mechanism_papers(data: BackgroundData) -> str:
    """Format Semantic Scholar papers into a citable list."""
    if not data.mechanism_papers:
        return ""

    lines = ["=== PEER-REVIEWED PAPERS ON MECHANISM/TOXICITY ==="]
    lines.append("(Cite relevant papers using author-year format in the References)")
    for p in data.mechanism_papers:
        authors = ", ".join(p.get("authors", []))
        year = p.get("year", "")
        title = p.get("title", "")
        venue = p.get("venue", "")
        lines.append(f"  - {authors} ({year}). {title}. {venue}.")

    return "\n".join(lines)


def _format_style_rules(style_rules: list[str] | None) -> str:
    """
    Format learned writing style rules into a prompt section.

    If style_rules is None or empty, returns an empty string (so no extra
    section appears in the prompt).  Otherwise, builds a clearly-delimited
    block that the LLM should apply throughout its writing — placed before
    FORMAT REQUIREMENTS so the LLM sees it in time to influence generation.

    Args:
        style_rules: List of human-readable style rule strings extracted from
            prior user edits (e.g., "Use 'test article' instead of 'compound'")

    Returns:
        Formatted prompt section string, or empty string if no rules.
    """
    if not style_rules:
        return ""

    lines = [
        "=== WRITING STYLE PREFERENCES ===",
        "(Learned from previous editing sessions. Apply these preferences",
        "throughout your writing when they don't conflict with the core",
        "requirements above.)",
        "",
    ]
    for rule in style_rules:
        lines.append(f"- {rule}")
    lines.append("")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM generation — Claude primary, Ollama fallback
# ---------------------------------------------------------------------------

def generate_background(data: BackgroundData,
                        use_ollama: bool = False,
                        model: str = "",
                        style_rules: list[str] | None = None) -> dict:
    """
    Generate the 6-paragraph background section using an LLM.

    Args:
        data: BackgroundData from data_gatherer.py
        use_ollama: If True, use local Ollama instead of Claude
        model: Override the default model name
        style_rules: Optional list of learned style rule strings to inject
            into the prompt.  When present, a WRITING STYLE PREFERENCES
            section is appended to the prompt before FORMAT REQUIREMENTS.

    Returns:
        Dict with keys:
          - "text": The full generated background text
          - "paragraphs": List of 7 paragraph strings (body)
          - "references": Extracted reference list
          - "abstract_background": 2-sentence distillation for the
            Abstract section (the deterministic study-purpose sentence
            is appended later by the export pipeline; this is just the
            chemical-class + knowledge-state sentences).  Empty string
            when the LLM omits the block.
          - "model_used": Which LLM model was used
          - "prompt_tokens_approx": Approximate input token count
    """
    prompt = build_prompt(data, style_rules=style_rules)
    system = (
        "You are a senior toxicologist and technical writer. "
        "Write precise, citation-heavy regulatory prose. "
        "Never fabricate data. If information is not provided, note the gap."
    )

    # Approximate token count (rough: 1 token ≈ 4 chars)
    prompt_tokens_approx = len(prompt) // 4

    if use_ollama:
        # Try local Ollama endpoints
        endpoint = _get_ollama_endpoint(model)
        if not endpoint:
            raise RuntimeError("No Ollama endpoint available")
        response = endpoint.generate(prompt, system=system,
                                     temperature=GENERATION_TEMPERATURE)
        model_used = f"ollama/{endpoint.model}"
    else:
        # Use Claude API (primary — best prose quality)
        claude_model = model or DEFAULT_CLAUDE_MODEL
        endpoint = AnthropicEndpoint(
            name="background-writer",
            model=claude_model,
            max_tokens=MAX_TOKENS,
            temperature=GENERATION_TEMPERATURE,
        )
        response = endpoint.generate(prompt, system=system)
        model_used = f"claude/{claude_model}"

    if not response:
        raise RuntimeError(f"LLM ({model_used}) returned empty response")

    # Parse the response into paragraphs and references.
    paragraphs, references = _parse_response(response)

    # Second pass: distill the body into a 2-sentence Abstract Background.
    # This is a separate focused LLM call rather than a tail block in the
    # main response, because the body-generation prompt is too dense for
    # the model to reliably emit a delimited abstract section.  Failure
    # here is non-fatal — the export pipeline falls back to the
    # deterministic study-purpose sentence alone.
    chemical_display_name = data.identity.name or "the test article"
    abstract_background = distill_abstract_background(
        body_text=response,
        chemical_name=chemical_display_name,
        use_ollama=use_ollama,
        model=model,
    )

    return {
        "text": response,
        "paragraphs": paragraphs,
        "references": references,
        "abstract_background": abstract_background,
        "model_used": model_used,
        "prompt_tokens_approx": prompt_tokens_approx,
    }


def _get_ollama_endpoint(model: str = "") -> OllamaEndpoint | None:
    """
    Find an available Ollama endpoint, preferring the local one.

    If a custom model is specified, override the default model on the
    endpoint before returning it.
    """
    for ep in [LOCAL_OLLAMA, REMOTE_OLLAMA]:
        if ep.is_available():
            if model:
                # Create a copy with the custom model
                return OllamaEndpoint(
                    name=ep.name,
                    url=ep.url,
                    model=model,
                    timeout=300,  # longer timeout for background generation
                    weight=ep.weight,
                )
            ep.timeout = 300
            return ep
    return None


def _parse_response(text: str) -> tuple[list[str], list[str]]:
    """
    Parse the LLM response into paragraphs and references.

    Expected format: 7 body paragraphs separated by double newlines,
    followed by a "References" header and [N] citation entries.
    """
    # Find the references section
    ref_split = re.split(r'\n\s*References?\s*\n', text, flags=re.IGNORECASE)

    prose_text = ref_split[0].strip()
    ref_text = ref_split[1].strip() if len(ref_split) > 1 else ""

    # Split prose into paragraphs (on double newline)
    raw_paragraphs = re.split(r'\n\s*\n', prose_text)
    paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]

    # Parse references
    references = []
    if ref_text:
        ref_lines = ref_text.strip().split("\n")
        for line in ref_lines:
            line = line.strip()
            if line and (line[0] == '[' or line[0].isdigit()):
                references.append(line)

    return paragraphs, references


def distill_abstract_background(
    body_text: str,
    chemical_name: str,
    use_ollama: bool = False,
    model: str = "",
) -> str:
    """
    Second-pass LLM call: distill the body Background into a 2-sentence
    Abstract → Background block.

    Why a second pass? The body generation prompt is too dense for the LLM
    to reliably emit a delimited side-block — it focuses on the 7 paragraphs
    and tends to ignore tail-end format requirements.  A focused second
    call with a tight JSON schema is much more reliable.

    The deterministic study-purpose sentence ("A short-term, in vivo
    transcriptomic study was used to assess...") is appended LATER by the
    export pipeline using MethodsContext, so this function returns ONLY
    the chemistry/exposure + knowledge-state sentences.

    Args:
        body_text:     The full LLM response from generate_background (the
                       7 paragraphs + References section as one string).
        chemical_name: Test article name for use in the distillation.
        use_ollama:    If True, route to local Ollama instead of Claude.
        model:         Optional model override.

    Returns:
        Two-sentence string, or "" if the distillation fails (non-fatal —
        the export pipeline still emits the deterministic boilerplate).
    """
    if not body_text or not body_text.strip():
        return ""

    system = (
        "You distill long technical regulatory prose into precise, "
        "fact-grounded abstract sentences.  Return ONLY valid JSON."
    )

    prompt = f"""Below is the body Background section of a NIEHS toxicology report.
Distill it into a 2-sentence Abstract → Background block.

=== BODY BACKGROUND ===
{body_text}
=== END BODY BACKGROUND ===

Return ONLY a JSON object of this exact shape:

{{"abstract_background": "<sentence 1> <sentence 2>"}}

Sentence 1 template (chemistry / exposure):
  "{chemical_name} ([abbreviation if mentioned in body]) is a member of
   the [chemical class verbatim from body Paragraph 1] of compounds to
   which [1-clause exposure context — humans, environment, occupational]."

Sentence 2 template (knowledge state):
  "Toxicological information on [this class | this compound] is
   [sparse | limited | well-characterized]."

Rules:
- Use ONLY facts that appear in the body Background.  Do not introduce
  new claims, doses, mechanisms, or regulatory citations.
- The chemical class wording must match what Paragraph 1 of the body says.
- The knowledge-state word must be consistent with the data-gap paragraph
  (Paragraph 6).  Use "sparse" when significant regulatory/mechanistic
  gaps exist, "limited" for moderate gaps, "well-characterized" only when
  comprehensive ATSDR/IRIS-style assessments exist.
- Do NOT include any inline reference markers like [1], [2].
- Do NOT add a study-purpose sentence — the system appends one separately.
- Both sentences in one string, separated by a single space.
"""

    try:
        # Reuse the centralized JSON-mode helper.  Default model matches
        # the body Background generator (claude-sonnet-4-6) — distillation
        # doesn't need the strongest model.
        from llm_helpers import llm_generate_json
        kwargs = {"max_tokens": 1024, "temperature": 0.1}
        if model:
            kwargs["model"] = model
        result = llm_generate_json(
            "abstract-background-distiller", prompt, system, **kwargs,
        )
    except Exception as e:
        logger.warning("Abstract Background distillation failed: %s", e)
        return ""

    if isinstance(result, dict):
        text = result.get("abstract_background", "")
        if isinstance(text, str):
            return text.strip()
    return ""


# ---------------------------------------------------------------------------
# CLI — standalone testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python background_writer.py <identifier> [--ollama] [--model MODEL]")
        print()
        print("Examples:")
        print('  python background_writer.py "95-50-1"')
        print('  python background_writer.py "1,2-Dichlorobenzene" --ollama')
        print('  python background_writer.py "95-50-1" --model claude-opus-4-6')
        sys.exit(1)

    query = sys.argv[1]
    use_ollama = "--ollama" in sys.argv
    model = ""
    if "--model" in sys.argv:
        idx = sys.argv.index("--model")
        if idx + 1 < len(sys.argv):
            model = sys.argv[idx + 1]

    # Step 1: Resolve
    print(f"Resolving '{query}'...")
    identity = resolve_chemical(query)
    print(f"  -> {identity.name} (CID={identity.pubchem_cid}, CASRN={identity.casrn})")

    # Step 2: Gather
    print("\nGathering data...")
    bg_data = gather_all(identity)

    # Step 3: Generate
    print(f"\nGenerating background ({'Ollama' if use_ollama else 'Claude'})...")
    result = generate_background(bg_data, use_ollama=use_ollama, model=model)

    # Print output
    print("\n" + "=" * 70)
    print("GENERATED BACKGROUND")
    print("=" * 70)
    print(result["text"])
    print("\n" + "=" * 70)
    print(f"Model: {result['model_used']}")
    print(f"Paragraphs: {len(result['paragraphs'])}")
    print(f"References: {len(result['references'])}")
    print(f"Approx prompt tokens: {result['prompt_tokens_approx']}")
