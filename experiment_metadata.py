"""
experiment_metadata — LLM-powered experiment metadata inference.

When files are uploaded to the 5dToxReport pipeline, the experiments inside
them carry flat string names like "BodyWeightMale", "Kidney_PFHxSAm_Female_No0",
or "female_clin_chem".  These names encode structured metadata (sex, organ,
platform, species, etc.) but in an ad-hoc, inconsistent format.

This module uses an LLM to extract structured ExperimentDescription metadata
from the available text signals:
  - experiment name  ("BodyWeightMale")
  - source filename  ("C20022-01_Individual_Animal_Body_Weight_Data.xlsx")
  - probe names      (["Body Weight"], ["Alanine aminotransferase", ...])
  - test article     (name, CASRN, DTXSID — already resolved)

The LLM maps free-text values to controlled vocabularies defined by
BMDExpress 3 (vocabulary.yml).  It handles synonyms, abbreviations, and
naming conventions — e.g. "F" → "female", "Sprague Dawley" → "Sprague-Dawley",
"oral gavage" → articleRoute="oral" + administrationMeans="gavage".

The output is a dict keyed by experiment name, each value being an
ExperimentDescription-shaped dict ready to attach to the experiment.

Design note: future raw data files may include multiline headers with
explicit metadata fields.  When that day comes, the header parser feeds
the same ExperimentDescription schema — the LLM inference becomes a
fallback for files that lack headers, not the primary path.

Data flow:
    integrate_pool() builds experiments
        → infer_experiment_metadata() enriches them with descriptions
            → validated against controlled vocabularies
                → attached to each doseResponseExperiment

Usage:
    from experiment_metadata import infer_experiment_metadata

    descriptions = infer_experiment_metadata(
        experiments=integrated["doseResponseExperiments"],
        source_files=integrated["_meta"]["source_files"],
        test_article={"name": "Perfluorohexanesulfonamide", "casrn": "41997-13-1", "dsstox": "DTXSID50469320"},
    )
    # descriptions = {"BodyWeightMale": {"sex": "male", "platform": "Generic", ...}, ...}
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Controlled vocabularies — mirrors BMDExpress 3 vocabulary.yml
# ---------------------------------------------------------------------------
# These are the ONLY values the LLM is allowed to output for each field.
# The LLM should map synonyms/abbreviations to the closest match here,
# or return null if nothing fits.

VOCABULARIES = {
    "sex": ["male", "female", "both", "mixed", "NA"],
    "organ": [
        "adrenal", "bladder", "blood", "bone", "bone marrow", "brain",
        "cecum", "cervix", "colon", "duodenum", "epididymis", "esophagus",
        "eye", "gallbladder", "harderian gland", "heart", "ileum",
        "intestine", "jejunum", "kidney", "larynx", "liver", "lung",
        "lymph node", "mammary gland", "muscle", "nasal cavity", "nerve",
        "ovary", "oviduct", "pancreas", "parathyroid", "pituitary",
        "preputial gland", "prostate", "rectum", "salivary gland",
        "seminal vesicle", "skin", "spinal cord", "spleen", "sternum",
        "stomach", "testes", "thymus", "thyroid", "tongue", "trachea",
        "ureter", "uterus", "vagina", "Whole Body",
    ],
    "species": [
        "rat", "mouse", "human", "rabbit", "dog", "monkey",
        "zebrafish", "guinea pig", "hamster", "pig",
    ],
    "strain": {
        "rat": ["Sprague-Dawley", "Wistar", "Long-Evans", "Fischer 344", "Brown Norway"],
        "mouse": ["C57BL/6", "BALB/c", "CD-1", "FVB/N", "129", "DBA/2", "NOD", "SCID"],
    },
    "platform": [
        # Apical platforms — in vivo tox study endpoint classes
        "Body Weight", "Clinical Chemistry", "Hematology", "Hormones",
        "Organ Weight", "Tissue Concentration", "Clinical Observations",
        "IVIVE", "Generic",
        # Genomics platforms
        "S1500+_rat", "S1500+_human",
        "Affymetrix Drosophila Genome Array", "Drosophila Genome 2.0 Array",
        "Human HG-Focus Target Array", "Human Genome U133A Array",
        "Human Genome U133 Plus 2.0 Array", "Human Genome U133A 2.0 Array",
        "HT HG-U133+ PM Array Plate", "HT MG-430 PM Array Plate",
        "HT RG-230 PM Array Plate", "Murine Genome U74A Array",
        "Murine Genome U74A Version 2 Array", "Mouse Expression 430A Array",
        "Mouse Expression 430B Array", "Mouse Genome 430A 2.0 Array",
        "Mouse Genome 430 2.0 Array", "Rat Expression 230A Array",
        "Rat Expression 230B Array", "Rat Genome 230 2.0 Array",
        "Rat Genome U34 Array", "Zebrafish Genome Array",
        "Agilent-021791 D. melanogaster (FruitFly) Oligo Microarray - V2",
        "Agilent-014850 Whole Human Genome Microarray 4x44K G4112F",
        "Agilent-014868 Whole Mouse Genome Microarray 4x44K G4122F",
        "Agilent-024196 Whole Rat Genome Microarray 4x44K",
        "Agilent-026437 D. rerio (Zebrafish) Oligo Microarray V3",
    ],
    "provider": [
        "Affymetrix", "Agilent", "BioSpyder", "BMDExpress 3", "RefSeq", "Ensembl",
        "Apical", "Generic",
    ],
    "subjectType": ["in vivo", "in vitro", "in silico"],
    "articleRoute": ["gavage", "oral", "inhaled", "transdermal"],
    "articleVehicle": ["corn oil", "feed", "water", "aerosol", "gas"],
    "administrationMeans": ["gavage", "drinking water", "dietary"],
    "studyDuration": [
        "5d", "28d",
        "3h", "6h", "9h", "24h",
        "1d", "3d", "7d", "14d",
    ],
    "articleType": ["chemical", "mixture", "electromagnetic radiation"],
    # Data completeness classification — describes whether the data has gaps
    # (tox_study = raw animal data) or is gap-filled for BMD modeling (inferred).
    "dataType": ["tox_study", "inferred", "gene_expression"],
}


# ---------------------------------------------------------------------------
# Text signal extraction — build the prompt context for each experiment
# ---------------------------------------------------------------------------

# Maximum number of probe names to include per experiment in the prompt.
# Gene expression experiments can have thousands of probes — we only need
# a sample for the LLM to recognize the data type.
_MAX_PROBE_SAMPLE = 10

# Probe names that are NOT organs — used by _extract_organ_names to filter
# out non-organ endpoints from organ weight experiments.
_ORGAN_WEIGHT_SKIP_TERMS = {"terminal body weight", "body weight", "bw", "tbw"}


def _extract_probe_ids(exp: dict) -> list[str]:
    """
    Extract all probe IDs from an experiment's probeResponses.

    Each probeResponse has a nested probe.id, but some older formats use
    a top-level 'name' field instead.  This helper handles both, returning
    a flat list of non-empty IDs.

    Used by:
      - _build_experiment_signals (samples first N for LLM context)
      - infer_experiment_metadata (full list for organ weight extraction)
    """
    probe_ids = []
    for pr in exp.get("probeResponses", []):
        pid = pr.get("probe", {}).get("id", "") or pr.get("name", "")
        if pid:
            probe_ids.append(pid)
    return probe_ids


def _extract_organ_names(probe_ids: list[str]) -> list[str]:
    """
    Extract organ names from organ weight probe IDs.

    Organ weight experiments use probe.id values like "Heart", "Kidney-Left",
    "Liver".  This function normalizes them (strips laterality suffixes like
    "-Left"/"-Right", lowercases) and filters out non-organ probes like
    "Terminal Body Weight".

    Returns a deduplicated list of lowercase organ names, preserving insertion
    order, suitable for joining into a comma-separated organ field value.
    """
    organ_names = []
    for pid in probe_ids:
        # Normalize: "Kidney-Left" → "kidney" (strip laterality)
        base = pid.split("-")[0].strip().lower()
        if base not in _ORGAN_WEIGHT_SKIP_TERMS and base not in organ_names:
            organ_names.append(base)
    return organ_names


def _resolve_vocab_value(value: str, allowed: list[str]) -> str | None:
    """
    Match a value against a vocabulary list, returning the canonical form.

    Tries exact match first, then case-insensitive.  Returns None if the
    value doesn't match any allowed term — meaning the LLM hallucinated
    a value outside the controlled vocabulary.
    """
    # Exact match — fastest path
    if value in allowed:
        return value

    # Case-insensitive fallback — handles "Oral" → "oral", etc.
    lower_map = {v.lower(): v for v in allowed}
    if value.lower() in lower_map:
        return lower_map[value.lower()]

    return None


def _get_allowed_values(field: str, vocab, desc: dict) -> list[str]:
    """
    Resolve the allowed values list for a vocabulary field.

    Most vocabularies are flat lists, but 'strain' is nested by species
    (e.g. {"rat": ["Sprague-Dawley", ...], "mouse": ["C57BL/6", ...]}).
    For strain, narrows to the species-specific list if species is known,
    otherwise flattens all strains into one list.

    Args:
        field:  The vocabulary field name (e.g. "strain", "sex").
        vocab:  The vocabulary entry — either a list or a dict (strain only).
        desc:   The full description dict, used to look up species for strain.
    """
    if field == "strain" and isinstance(vocab, dict):
        species = desc.get("species")
        if species and species in vocab:
            return vocab[species]
        # Species unknown or not in strain dict — allow any strain
        return [s for strains in vocab.values() for s in strains]
    return vocab


def _build_experiment_signals(
    experiments: list[dict],
    source_files: dict,
) -> list[dict]:
    """
    Extract text signals from each experiment for LLM inference.

    For each experiment, gathers:
      - experiment name
      - source filename (from _meta.source_files)
      - sample of probe names
      - probe count (helps distinguish gene expression from apical)

    Returns a list of signal dicts, one per experiment, in the same order.
    """
    # Build a reverse map: experiment name → source filename.
    # source_files is keyed by domain (e.g. "clin_chem"), each with a filename.
    # We match by checking if the experiment name relates to the domain.
    # This is best-effort — the LLM handles ambiguity.
    exp_to_filename: dict[str, str] = {}
    for domain_key, info in source_files.items():
        filename = info.get("filename", "")
        exp_to_filename[domain_key] = filename

    signals = []
    for exp in experiments:
        name = exp["name"]
        all_probe_ids = _extract_probe_ids(exp)
        probe_names = all_probe_ids[:_MAX_PROBE_SAMPLE]
        n_probes = len(all_probe_ids)

        # Try to find the source filename — match domain key against experiment name.
        # This is a heuristic; the LLM will also see the filename as context.
        source_filename = ""
        for domain_key, filename in exp_to_filename.items():
            if domain_key.lower().replace("_", "") in name.lower().replace("_", ""):
                source_filename = filename
                break

        signals.append({
            "experiment_name": name,
            "source_filename": source_filename,
            "probe_names_sample": probe_names,
            "probe_count": n_probes,
        })

    return signals


# ---------------------------------------------------------------------------
# LLM prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a metadata extraction assistant for toxicological dose-response experiments.

Given text signals (experiment names, filenames, probe names) from a toxicology study,
infer structured metadata for each experiment.  Map free-text values to the controlled
vocabularies provided — use synonym recognition to find the best match.

Examples of synonym mapping:
  - "F", "fem", "♀" → "female"
  - "M", "mal", "♂" → "male"
  - "Sprague Dawley", "SD" → "Sprague-Dawley"
  - "oral gavage" → articleRoute: "oral", administrationMeans: "gavage"
  - "BW", "body wt" → platform: "Body Weight"
  - "clin chem", "clinical chemistry", "serum chemistry" → platform: "Clinical Chemistry"
  - "heme", "CBC" → platform: "Hematology"
  - "organ wt", "organ weight" → platform: "Organ Weight"
  - "hormone", "T3", "T4", "TSH", "testosterone" → platform: "Hormone"
  - Gene probe IDs like "AADAC_7934" indicate gene expression data

Rules:
1. ONLY output values from the controlled vocabularies.  If you recognize a synonym,
   map it to the vocabulary term.  If nothing fits, use null.
2. For gene expression experiments (many probes with gene-like names), infer the organ
   from the experiment name if present (e.g. "Kidney_..." → organ: "kidney").
3. The test article identity is provided separately — do NOT include testArticle in your output.
   It will be attached automatically in post-processing (same for all experiments).
4. If the study is clearly in vivo (animal data), set subjectType to "in vivo".
5. Strain and species may be inferable from filenames or context.  If not, use null.
6. For apical/clinical endpoints, use provider "Apical" and match the platform:
   "Body Weight" for body weight, "Organ Weight" for organ weight,
   "Clinical Chemistry" for clinical chemistry, "Hematology" for hematology,
   "Hormones" for hormone/thyroid hormone endpoints, "Tissue Concentration"
   for IVIVE/plasma data, "Clinical Observations" for categorical observations.
7. Organ assignments by domain:
   - Hematology, Clinical Chemistry, Hormone → organ: "blood"
   - Body Weight → organ: "Whole Body"
   - Organ Weight → organ: list of organs found in the probe/endpoint names
     (e.g. probes like "liver", "kidney", "spleen" → organ: "liver, kidney, spleen").
     If organ names aren't clear from the probes, use null.
8. Tissue concentration / IVIVE experiments → platform: "Tissue Concentration", provider: "Apical".
9. Defaults (use these unless evidence suggests otherwise):
   studyDuration: "5d", articleRoute: "gavage", articleVehicle: "corn oil".
10. Data type classification (dataType field):
    - "tox_study" — raw experimental data that may have missing values (dead animals,
      excluded samples).  Used for NTP traditional statistics.
    - "inferred" — gap-filled data (dose-group averages substituted for missing values)
      suitable for BMD modeling.  Most .bm2 data is inferred.
    - "gene_expression" — transcriptomics data (always complete, different pipeline).
    - When ambiguous, default to "inferred" (most common in .bm2 files).
11. Return valid JSON only — no markdown fences, no commentary."""


def _build_prompt(
    signals: list[dict],
    test_article: dict,
    vocabularies: dict,
) -> str:
    """
    Build the user-turn prompt for the LLM.

    Includes all experiment signals, the test article identity, and the
    controlled vocabularies as the constraint set.
    """
    prompt_parts = []

    prompt_parts.append("## Test Article\n")
    prompt_parts.append(json.dumps(test_article, indent=2))

    prompt_parts.append("\n\n## Controlled Vocabularies\n")
    prompt_parts.append(json.dumps(vocabularies, indent=2))

    prompt_parts.append("\n\n## Experiments\n")
    prompt_parts.append(
        "For each experiment below, infer an experimentDescription object.\n"
    )
    for i, sig in enumerate(signals):
        prompt_parts.append(f"\n### Experiment {i + 1}: {sig['experiment_name']}")
        prompt_parts.append(f"  Source file: {sig['source_filename'] or '(unknown)'}")
        prompt_parts.append(f"  Probe count: {sig['probe_count']}")
        prompt_parts.append(f"  Probe names (sample): {sig['probe_names_sample']}")

    prompt_parts.append("\n\n## Output Format\n")
    prompt_parts.append(
        "Return a JSON object keyed by experiment name.  Each value has these fields "
        "(all nullable — use null if unknown):\n"
    )
    prompt_parts.append(json.dumps({
        "<experiment_name>": {
            "subjectType": "str",
            "species": "str",
            "strain": "str",
            "sex": "str",
            "organ": "str or null",
            "cellLine": "str or null",
            "studyDuration": "str or null",
            "platform": "str",
            "provider": "str",
            "articleRoute": "str or null",
            "articleVehicle": "str or null",
            "administrationMeans": "str or null",
            "articleType": "str",
            "dataType": "str — tox_study, inferred, or gene_expression",
        }
    }, indent=2))

    return "\n".join(prompt_parts)


# ---------------------------------------------------------------------------
# Vocabulary validation — enforce controlled terms post-LLM
# ---------------------------------------------------------------------------

def _validate_description(desc: dict) -> dict:
    """
    Validate an LLM-inferred experimentDescription against controlled vocabularies.

    For each field, checks whether the value is in the allowed vocabulary.
    If not, attempts case-insensitive matching.  If still no match, sets to None.

    The testArticle sub-object is passed through as-is (free-text identifiers).

    Returns a cleaned copy of the description.
    """
    cleaned = {}

    # testArticle is free-text — pass through
    if "testArticle" in desc and desc["testArticle"]:
        cleaned["testArticle"] = desc["testArticle"]

    # Validate each vocabulary-constrained field
    for field, vocab in VOCABULARIES.items():
        value = desc.get(field)
        if value is None:
            cleaned[field] = None
            continue

        allowed = _get_allowed_values(field, vocab, desc)
        resolved = _resolve_vocab_value(value, allowed)

        if resolved is None:
            logger.warning(
                "Metadata field '%s' value '%s' not in vocabulary — dropping to null",
                field, value,
            )

        cleaned[field] = resolved

    return cleaned


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def infer_experiment_metadata(
    experiments: list[dict],
    source_files: dict,
    test_article: dict,
    *,
    llm_generate_json: Any = None,
) -> dict[str, dict]:
    """
    Infer ExperimentDescription metadata for all experiments using an LLM.

    Args:
        experiments:      List of doseResponseExperiment dicts from the integrated
                          BMDProject.  Each must have 'name' and 'probeResponses'.
        source_files:     The _meta.source_files dict from integration, mapping
                          domain keys to {filename, tier, ...}.
        test_article:     Dict with 'name', 'casrn', 'dsstox' for the test chemical.
        llm_generate_json: Callable(name, prompt, system, **kwargs) → parsed JSON.
                          Injected from the server to avoid coupling to the LLM client.
                          If None, returns empty descriptions (no-op).

    Returns:
        Dict keyed by experiment name → ExperimentDescription dict, validated
        against controlled vocabularies.
    """
    if llm_generate_json is None:
        logger.warning("No LLM callable provided — skipping metadata inference")
        return {}

    if not experiments:
        return {}

    # Build text signals from each experiment
    signals = _build_experiment_signals(experiments, source_files)

    # Build the prompt
    prompt = _build_prompt(signals, test_article, VOCABULARIES)

    # Call the LLM
    logger.info(
        "Inferring metadata for %d experiments via LLM...", len(experiments),
    )
    try:
        raw_descriptions = llm_generate_json(
            "experiment-metadata-inference",
            prompt,
            _SYSTEM_PROMPT,
            model="claude-sonnet-4-6",
            max_tokens=8192,
            temperature=0.0,
        )
    except Exception:
        logger.exception("LLM metadata inference failed — experiments will lack metadata")
        return {}

    if not isinstance(raw_descriptions, dict):
        logger.error(
            "LLM returned %s instead of dict — skipping metadata",
            type(raw_descriptions).__name__,
        )
        return {}

    # Build the testArticle block once — same for all experiments.
    # Includes synonyms from the resolved chemical identity so the .bm2
    # carries all known names (trade names, alternate CAS names, etc.).
    test_article_block = None
    if test_article:
        test_article_block = {
            "name": test_article.get("name"),
            "casrn": test_article.get("casrn"),
            "dsstox": test_article.get("dsstox"),
        }
        # Include synonyms if available (from PubChem resolver)
        synonyms = test_article.get("synonyms", [])
        if synonyms:
            test_article_block["synonyms"] = synonyms

    # Build a lookup of probe IDs per experiment for organ weight extraction.
    # For organ weight experiments, the probe.id values ARE the organ names
    # (e.g. "Heart", "Kidney-Left", "Liver").
    experiment_probes: dict[str, list[str]] = {
        exp["name"]: _extract_probe_ids(exp) for exp in experiments
    }

    # Validate each description against controlled vocabularies, then
    # apply post-processing: testArticle attachment + organ weight extraction.
    validated: dict[str, dict] = {}
    for exp_name, desc in raw_descriptions.items():
        if not isinstance(desc, dict):
            logger.warning("Skipping non-dict description for '%s'", exp_name)
            continue
        validated_desc = _validate_description(desc)

        # Attach testArticle (not LLM-generated — same for all experiments)
        if test_article_block:
            validated_desc["testArticle"] = test_article_block

        # For organ weight experiments, derive organ list from probe IDs
        if validated_desc.get("platform") == "Organ Weight":
            organ_names = _extract_organ_names(
                experiment_probes.get(exp_name, []),
            )
            if organ_names:
                validated_desc["organ"] = ", ".join(organ_names)

        validated[exp_name] = validated_desc

    logger.info(
        "Metadata inference complete: %d/%d experiments described",
        len(validated), len(experiments),
    )

    return validated


# Fields that are study-level properties — same across all experiments in a
# study.  Used by attach_metadata to propagate consensus values to experiments
# where the LLM returned null (e.g. tissue concentration experiments whose
# names don't encode species/strain).
_STUDY_LEVEL_FIELDS = [
    "species", "strain", "studyDuration", "articleRoute",
    "articleVehicle", "administrationMeans", "articleType", "subjectType",
]


def _compute_study_consensus(experiments: list[dict]) -> dict[str, str]:
    """
    Compute consensus values for study-level fields across all experiments.

    For each field in _STUDY_LEVEL_FIELDS, counts non-null values and picks
    the most common one — but only if it appears in a majority of experiments
    that have any value for that field (i.e. the mode).  This prevents a
    single outlier from overriding.

    Returns a dict of field → consensus value (only fields with a clear
    winner are included).
    """
    from collections import Counter
    consensus = {}
    for field in _STUDY_LEVEL_FIELDS:
        counts: Counter[str] = Counter()
        for exp in experiments:
            ed = exp.get("experimentDescription") or {}
            val = ed.get(field)
            if val is not None:
                counts[val] += 1
        if counts:
            # Pick the most common value — it represents the study default
            best, _count = counts.most_common(1)[0]
            consensus[field] = best
    return consensus


def attach_metadata(
    experiments: list[dict],
    descriptions: dict[str, dict],
) -> None:
    """
    Attach inferred ExperimentDescription metadata to experiments in-place.

    Three-phase merge:
      1. Field-by-field merge of LLM-inferred descriptions into each
         experiment's existing experimentDescription.  Only sets a field
         if its current value is null/missing — preserves human edits,
         prior LLM runs, and Jackson deserialization defaults.
      2. Post-processing overrides: tissue concentration experiments get
         platform="IVIVE" and provider="BMDExpress 3" if still null.
      3. Study-level consensus propagation: fields like species, strain,
         studyDuration are study-wide properties.  If the LLM inferred
         them for most experiments but missed some (e.g. tissue concentration),
         the consensus value fills the gaps.

    Args:
        experiments:  List of doseResponseExperiment dicts (mutated in place).
        descriptions: Dict from infer_experiment_metadata().
    """
    # --- Phase 1: merge LLM descriptions + tissue concentration override ---
    for exp in experiments:
        name = exp["name"]
        existing = exp.get("experimentDescription") or {}

        # Merge LLM-inferred metadata, only for fields currently null/missing.
        desc = descriptions.get(name)
        if desc:
            for field, value in desc.items():
                if existing.get(field) is None:
                    existing[field] = value

        # Tissue concentration experiments: IVIVE is computational modeling
        # (in vitro → in vivo extrapolation), so platform="IVIVE",
        # provider="BMDExpress 3", subjectType="in silico".
        if "tissue" in name.lower() and "concentration" in name.lower():
            if existing.get("platform") is None:
                existing["platform"] = "IVIVE"
            if existing.get("provider") is None:
                existing["provider"] = "BMDExpress 3"
            existing["subjectType"] = "in silico"

        # Always write back — existing may have been mutated by merge or
        # post-processing, and the `or {}` fallback above may have created
        # a new dict not yet assigned to the experiment.
        exp["experimentDescription"] = existing

    # --- Phase 2: propagate study-level consensus to fill remaining gaps ---
    # Fields like species/strain/studyDuration are study-wide — if the LLM
    # got them for body weight and clin chem but not tissue concentration,
    # the consensus fills those in.
    consensus = _compute_study_consensus(experiments)
    if consensus:
        for exp in experiments:
            ed = exp.get("experimentDescription") or {}
            for field, value in consensus.items():
                if ed.get(field) is None:
                    ed[field] = value
            exp["experimentDescription"] = ed
