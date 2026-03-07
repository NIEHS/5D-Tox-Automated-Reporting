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
        "adrenal", "blood", "bone", "brain", "colon", "heart", "intestine",
        "kidney", "liver", "lung", "muscle", "ovary", "pancreas", "prostate",
        "skin", "spleen", "stomach", "testes", "thymus", "thyroid", "uterus",
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
        "Clinical Chemistry", "Hematology", "Organ Weight", "Generic",
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
        "Affymetrix", "Agilent", "BioSpyder", "RefSeq", "Ensembl",
        "Clinical Endpoint", "Generic",
    ],
    "subjectType": ["in vivo", "in vitro"],
    "articleRoute": ["oral", "inhaled", "transdermal"],
    "articleVehicle": ["corn oil", "feed", "water", "aerosol", "gas"],
    "administrationMeans": ["gavage", "drinking water", "dietary"],
    "studyDuration": [
        "3h", "6h", "9h", "24h",
        "1d", "3d", "5d", "7d", "14d", "28d",
    ],
    "articleType": ["chemical", "mixture", "electromagnetic radiation"],
}


# ---------------------------------------------------------------------------
# Text signal extraction — build the prompt context for each experiment
# ---------------------------------------------------------------------------

# Maximum number of probe names to include per experiment in the prompt.
# Gene expression experiments can have thousands of probes — we only need
# a sample for the LLM to recognize the data type.
_MAX_PROBE_SAMPLE = 10


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
        probes = exp.get("probeResponses", [])
        probe_names = [p["probe"]["id"] for p in probes[:_MAX_PROBE_SAMPLE]]
        n_probes = len(probes)

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
  - "BW", "body wt" → platform: "Generic" (body weight is a generic endpoint)
  - "clin chem", "clinical chemistry", "serum chemistry" → platform: "Clinical Chemistry"
  - "heme", "CBC" → platform: "Hematology"
  - "organ wt", "organ weight" → platform: "Organ Weight"
  - Gene probe IDs like "AADAC_7934" indicate gene expression data

Rules:
1. ONLY output values from the controlled vocabularies.  If you recognize a synonym,
   map it to the vocabulary term.  If nothing fits, use null.
2. For gene expression experiments (many probes with gene-like names), infer the organ
   from the experiment name if present (e.g. "Kidney_..." → organ: "kidney").
3. The test article identity is provided separately — populate testArticle for ALL experiments.
4. If the study is clearly in vivo (animal data), set subjectType to "in vivo".
5. Strain and species may be inferable from filenames or context.  If not, use null.
6. Return valid JSON only — no markdown fences, no commentary."""


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
            "testArticle": {"name": "str", "casrn": "str", "dsstox": "str"},
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

        # strain vocabulary is nested by species — flatten for validation
        if field == "strain":
            species = desc.get("species")
            if isinstance(vocab, dict):
                # Get strain list for the inferred species, or all strains
                if species and species in vocab:
                    allowed = vocab[species]
                else:
                    allowed = [s for strains in vocab.values() for s in strains]
            else:
                allowed = vocab
        else:
            allowed = vocab

        # Exact match
        if value in allowed:
            cleaned[field] = value
            continue

        # Case-insensitive match
        lower_map = {v.lower(): v for v in allowed}
        if value.lower() in lower_map:
            cleaned[field] = lower_map[value.lower()]
            continue

        # No match — the LLM hallucinated a value outside the vocabulary
        logger.warning(
            "Metadata field '%s' value '%s' not in vocabulary — dropping to null",
            field, value,
        )
        cleaned[field] = None

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
            max_tokens=4096,
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

    # Validate each description against controlled vocabularies
    validated: dict[str, dict] = {}
    for exp_name, desc in raw_descriptions.items():
        if not isinstance(desc, dict):
            logger.warning("Skipping non-dict description for '%s'", exp_name)
            continue
        validated[exp_name] = _validate_description(desc)

    logger.info(
        "Metadata inference complete: %d/%d experiments described",
        len(validated), len(experiments),
    )

    return validated


def attach_metadata(
    experiments: list[dict],
    descriptions: dict[str, dict],
) -> None:
    """
    Attach inferred ExperimentDescription metadata to experiments in-place.

    For each experiment, if a description was inferred, it's stored under
    the 'experimentDescription' key — matching the BMDExpress 3 Java schema.

    Existing experimentDescription fields are NOT overwritten — the LLM
    inference is a fallback for experiments that lack metadata.

    Args:
        experiments:  List of doseResponseExperiment dicts (mutated in place).
        descriptions: Dict from infer_experiment_metadata().
    """
    for exp in experiments:
        name = exp["name"]
        # Don't overwrite existing metadata (e.g. from a metadata-aware .bm2)
        existing = exp.get("experimentDescription")
        if existing and any(v for v in existing.values() if v is not None):
            continue

        desc = descriptions.get(name)
        if desc:
            exp["experimentDescription"] = desc
