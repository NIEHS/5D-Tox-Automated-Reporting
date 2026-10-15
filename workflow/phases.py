"""
workflow.phases — UI-agnostic port of the pool phase machine (ADR-0014, step 1).

Ported byte-for-byte-in-behavior from web/js/pool_state.js. This module is the
single Python source of truth for:

  * derive_phase(artifacts)               — settled pool phase from artifact flags
  * compute_section_completeness(matrix)  — per-platform readiness from coverage
  * is_node_complete(node_id, ..., tree)  — document-tree node readiness

The characterization gate (tests/unit/test_workflow_phase_characterization.py)
pins these three functions to the committed oracle. It was generated from the
JS; since C1 decision D2 (2026-10-15, the maintainer) this module is the source
of truth for `derive_phase`: the rule "a stale section sends the phase to
UPLOADED" was dropped here and its two oracle cases edited by hand (see the
case table's `_EVOLVING_THIS_CONTRACT`). Change observable behaviour only as a
deliberate, signed decision, with the case table and the oracle in the same
commit.

The legal-action table (`LEGAL_ACTIONS`, with `NEXT_STEP`) is NOT a port: since
C1 it is the workflow's own declared table of acts, and every mutating step
enforces it (`workflow.engine.require_legal`).

Fidelity notes vs. the JS:
  * `validationReport` presence uses `is None`, not Python truthiness — JS treats
    any object (even {}) as truthy; only null/undefined is "not yet validated".
  * completeness is a plain dict here (JS used a Map); membership/lookup semantics
    are identical for the string keys in play.
"""

from __future__ import annotations

import enum


# ---------------------------------------------------------------------------
# Phases and actions — the UI-agnostic core of the pool workflow.
#
# SETTLED phases only. The three transient in-flight phases from the JS
# (VALIDATING / INTEGRATING / APPROVING) are deliberately DROPPED: they are
# per-UI "async operation in progress" presentation states, not workflow
# states. A UI shows them locally between dispatching an action and receiving
# the settled result; the core never derives or stores them.
# ---------------------------------------------------------------------------

class Phase(str, enum.Enum):
    EMPTY = "EMPTY"
    UPLOADED = "UPLOADED"
    VALIDATION_ERRORS = "VALIDATION_ERRORS"
    VALIDATED = "VALIDATED"
    INTEGRATED = "INTEGRATED"
    APPROVED = "APPROVED"


class Action(str, enum.Enum):
    """The workflow's acts on a study's data, as the interface names them. Every
    mutating step names the one it performs and refuses outside its phase
    (workflow.engine.require_legal)."""

    ADD_FILES = "ADD_FILES"                    # bring files into the study (step 1)
    REMOVE_FILE = "REMOVE_FILE"                # remove one file
    RESET = "RESET"                            # clear the files and all derived from them
    VALIDATE = "VALIDATE"                      # the file check (step 2)
    RESOLVE = "RESOLVE"                        # choose between conflicting files (step 3)
    CONFIRM_CLASSIFICATION = "CONFIRM_CLASSIFICATION"  # correct a file's platform/type (4)
    INTEGRATE = "INTEGRATE"                    # combine the files into one dataset (step 5)
    STATE_DATASET_FACTS = "STATE_DATASET_FACTS"  # study design / experiment metadata (6)
    APPROVE = "APPROVE"                        # the data approval, the animal accounting (8)
    PROCESS = "PROCESS"                        # Process, content preparation, materialising (9)


# The declared table of legal actions per settled phase (C1 spec §1). Typed
# directly: it is the workflow's rule, no longer a transcription of a screen's
# buttons. Why each entry is there:
#   * ADD_FILES is always legal (C5's run lock will refuse it during a run);
#   * VALIDATE stays legal after validation: the fix for an out-of-date
#     integration is "validate again", and the command line re-validates on
#     every run;
#   * RESOLVE / CONFIRM_CLASSIFICATION follow the validation: a choice must be
#     changeable after integration, before the re-integration it calls for;
#   * INTEGRATE at INTEGRATED/APPROVED is re-integration (it withdraws the data
#     approval); STATE_DATASET_FACTS writes onto the dataset, so needs one;
#   * PROCESS is not gated on the data approval: INTEGRATED and APPROVED differ
#     only in what the data review shows.
_FILE_ACTS = frozenset({Action.ADD_FILES, Action.REMOVE_FILE, Action.RESET, Action.VALIDATE})
_CHOICES = frozenset({Action.RESOLVE, Action.CONFIRM_CLASSIFICATION})
_ALL = frozenset(Action)

LEGAL_ACTIONS: dict[Phase, frozenset[Action]] = {
    Phase.EMPTY: frozenset({Action.ADD_FILES}),
    Phase.UPLOADED: _FILE_ACTS,
    Phase.VALIDATION_ERRORS: _FILE_ACTS | _CHOICES,
    Phase.VALIDATED: _FILE_ACTS | _CHOICES | {Action.INTEGRATE},
    Phase.INTEGRATED: _ALL,
    Phase.APPROVED: _ALL,
}

# The act that moves each phase forward, as data, so a refusal and the
# interface's "next step" read one table. INTEGRATED and APPROVED have none:
# everything is legal there.
NEXT_STEP: dict[Phase, Action] = {
    Phase.EMPTY: Action.ADD_FILES,
    Phase.UPLOADED: Action.VALIDATE,
    Phase.VALIDATION_ERRORS: Action.VALIDATE,   # after fixing what the check lists
    Phase.VALIDATED: Action.INTEGRATE,
}


def is_legal(phase, action) -> bool:
    """Whether `action` is permitted in `phase`. Accepts enums or their str values."""
    phase = Phase(phase)
    action = Action(action)
    return action in LEGAL_ACTIONS.get(phase, frozenset())


# ---------------------------------------------------------------------------
# Phase derivation — the settled pool phase is a function of artifact state.
# Evaluated top-to-bottom, first match wins. Mirrors derivePoolPhase().
# ---------------------------------------------------------------------------

def derive_phase(artifacts: dict) -> str:
    """Derive the settled pool phase from artifact presence flags.

    artifacts keys (all optional; absent == falsy):
      hasFiles, validationReport, hasValidationErrors, hasIntegrated,
      hasAnimalReport. (hasStale is accepted and ignored since C1 D2.)
    """
    # No files → nothing to do
    if not artifacts.get("hasFiles"):
        return "EMPTY"

    # (A stale section no longer moves the phase, C1 D2: staleness is a
    # section matter — currency and the publish gate. A file change already
    # deletes the validation report, which gives UPLOADED below.)

    # Files exist but haven't been validated yet (JS: any object is truthy)
    if artifacts.get("validationReport") is None:
        return "UPLOADED"

    # Validation ran but found errors
    if artifacts.get("hasValidationErrors"):
        return "VALIDATION_ERRORS"

    # Validated but not yet integrated
    if not artifacts.get("hasIntegrated"):
        return "VALIDATED"

    # Integrated but not yet approved
    if not artifacts.get("hasAnimalReport"):
        return "INTEGRATED"

    # All present — fully approved
    return "APPROVED"


# ---------------------------------------------------------------------------
# Section completeness — derived from the coverage matrix. Mirrors
# computeSectionCompleteness() + its APICAL_PLATFORMS / PLATFORM_ALIASES.
# ---------------------------------------------------------------------------

APICAL_PLATFORMS = frozenset({
    "Body Weight", "Organ Weight", "Clinical Chemistry",
    "Hematology", "Hormones",
})

PLATFORM_ALIASES = {
    "Clinical": "Clinical Observations",
}


def compute_section_completeness(coverage_matrix: dict) -> dict:
    """Per-platform completeness from the coverage matrix.

    Returns {platform: {hasToxStudy, hasBm2, complete, missing}}. Compound keys
    ("Body Weight|tox_study") collapse to per-platform presence, merging tiers.
    """
    if not coverage_matrix:
        return {}

    # Collapse compound keys into per-platform presence.
    collapsed: dict[str, dict] = {}
    for key in coverage_matrix.keys():
        raw = key.split("|")[0] if "|" in key else key
        platform = PLATFORM_ALIASES.get(raw, raw)
        if platform not in collapsed:
            collapsed[platform] = {"xlsx": False, "txtCsvCount": 0, "bm2": False}
        tiers = coverage_matrix[key]
        if tiers.get("xlsx"):
            collapsed[platform]["xlsx"] = True
        txt_arr = tiers.get("txt_csv") or []
        if isinstance(txt_arr, list):
            collapsed[platform]["txtCsvCount"] += len(txt_arr)
        else:
            collapsed[platform]["txtCsvCount"] += 1 if txt_arr else 0
        if tiers.get("bm2"):
            collapsed[platform]["bm2"] = True

    result: dict[str, dict] = {}
    for platform, tiers in collapsed.items():
        has_tox_study = bool(tiers["xlsx"] or tiers["txtCsvCount"] > 0)
        has_bm2 = bool(tiers["bm2"])
        missing: list[str] = []

        if platform in APICAL_PLATFORMS:
            if not has_tox_study:
                missing.append("Requires study data (.txt/.csv) for NTP statistics")
            if not has_bm2:
                missing.append("Requires .bm2 for BMD/BMDL values")
        elif platform == "Tissue Concentration":
            if not tiers["xlsx"]:
                missing.append("Requires .xlsx with Biosampling Animal data")
        elif platform == "Clinical Observations":
            if not has_tox_study:
                missing.append("Requires clinical observation CSV data")
        elif platform in ("gene_expression", "Gene Expression"):
            if not has_bm2:
                missing.append("Requires .bm2 with gene expression data")

        result[platform] = {
            "hasToxStudy": has_tox_study,
            "hasBm2": has_bm2,
            "complete": len(missing) == 0,
            "missing": missing,
        }

    return result


# ---------------------------------------------------------------------------
# Node completeness — document-tree node readiness. Mirrors isNodeComplete()
# and its recursive _findNodeInTree() helper.
# ---------------------------------------------------------------------------

def _find_node_in_tree(node_id: str, tree) -> dict | None:
    """Recursive search for a node by id in the serialized document tree."""
    if not tree:
        return None
    nodes = tree if isinstance(tree, list) else [tree]
    for node in nodes:
        if node.get("id") == node_id:
            return node
        children = node.get("children")
        if children:
            found = _find_node_in_tree(node_id, children)
            if found:
                return found
    return None


def is_node_complete(node_id: str, completeness: dict, document_tree) -> dict:
    """Whether a document-tree node is complete for preview.

    Leaf table node → inherits its platform's completeness. Group node →
    complete only if ALL child table nodes are complete. Non-data node → complete.
    """
    if not completeness:
        return {"complete": False,
                "missing": ["No completeness data — validate the pool first"]}

    node = _find_node_in_tree(node_id, document_tree)
    if not node:
        return {"complete": True, "missing": []}  # non-data node

    # Leaf table node — check its platform
    platform = node.get("platform")
    if platform:
        status = completeness.get(platform)
        if not status:
            return {"complete": False, "missing": [f"No data for platform: {platform}"]}
        return {"complete": status["complete"], "missing": status["missing"]}

    # Group node — complete only if ALL child table nodes are complete
    children = node.get("children")
    if children:
        all_missing: list[str] = []
        for child in children:
            child_platform = child.get("platform")
            if child_platform:
                status = completeness.get(child_platform)
                if not status or not status["complete"]:
                    label = child.get("title") or child_platform
                    reasons = status["missing"] if status else [f"No data for {child_platform}"]
                    all_missing.append(f"{label}: {'; '.join(reasons)}")
        return {"complete": len(all_missing) == 0, "missing": all_missing}

    # Non-table node (narrative, front matter, etc.) — always complete
    return {"complete": True, "missing": []}
