"""
workflow.phases — UI-agnostic port of the pool phase machine (ADR-0014, step 1).

Ported byte-for-byte-in-behavior from web/js/pool_state.js. This module is the
single Python source of truth for:

  * derive_phase(artifacts)               — settled pool phase from artifact flags
  * compute_section_completeness(matrix)  — per-platform readiness from coverage
  * is_node_complete(node_id, ..., tree)  — document-tree node readiness

The JS remains the source of truth until ADR-0014 migration step 3 deletes the
derivation functions from pool_state.js. Until then the characterization gate
(tests/unit/test_workflow_phase_characterization.py) pins these three functions
to the JS oracle. Do NOT change observable behavior here without changing it at
the JS source and regenerating the oracle first (see the contract's
`_EVOLVING_THIS_CONTRACT`).

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
    VALIDATE = "VALIDATE"
    INTEGRATE = "INTEGRATE"
    APPROVE = "APPROVE"
    REPROCESS = "REPROCESS"
    RESET = "RESET"
    CLEAR_FILES = "CLEAR_FILES"


# Button id (POOL_PHASES key) → abstract Action. The remaining POOL_PHASES
# keys (badge-pool, validation-summary, file-metadata-review,
# integrated-preview) are pure display, not actions.
_BUTTON_ACTIONS: dict[str, Action] = {
    "btn-validate": Action.VALIDATE,
    "btn-integrate": Action.INTEGRATE,
    "btn-approve-pool": Action.APPROVE,
    "btn-reprocess-pool": Action.REPROCESS,
    "btn-reset-pool": Action.RESET,
    "btn-clear-files": Action.CLEAR_FILES,
}

# Faithful transcription of the settled phases' button enablement from
# web/js/pool_state.js POOL_PHASES (visible AND enabled == actionable).
# Kept as (visible, enabled) pairs so LEGAL_ACTIONS is DERIVED, not hand-typed
# — the derivation is what test_legal_actions_derivation pins. Transient
# phases are intentionally absent. Update this map when POOL_PHASES changes,
# then the derived table + its test move together.
_PHASE_BUTTON_STATE: dict[Phase, dict[str, tuple[bool, bool]]] = {
    Phase.EMPTY: {
        "btn-validate": (True, False),
        "btn-integrate": (True, False),
        "btn-approve-pool": (True, False),
        "btn-reprocess-pool": (False, False),
        "btn-reset-pool": (True, False),
        "btn-clear-files": (False, False),
    },
    Phase.UPLOADED: {
        "btn-validate": (True, True),
        "btn-integrate": (True, False),
        "btn-approve-pool": (True, False),
        "btn-reprocess-pool": (False, False),
        "btn-reset-pool": (True, False),
        "btn-clear-files": (True, True),
    },
    Phase.VALIDATION_ERRORS: {
        "btn-validate": (True, True),
        "btn-integrate": (True, False),
        "btn-approve-pool": (True, False),
        "btn-reprocess-pool": (False, False),
        "btn-reset-pool": (True, True),
        "btn-clear-files": (False, False),
    },
    Phase.VALIDATED: {
        "btn-validate": (True, False),
        "btn-integrate": (True, True),
        "btn-approve-pool": (True, False),
        "btn-reprocess-pool": (False, False),
        "btn-reset-pool": (True, True),
        "btn-clear-files": (False, False),
    },
    Phase.INTEGRATED: {
        "btn-validate": (True, True),
        "btn-integrate": (True, False),
        "btn-approve-pool": (True, True),
        "btn-reprocess-pool": (True, True),
        "btn-reset-pool": (True, True),
        "btn-clear-files": (False, False),
    },
    Phase.APPROVED: {
        "btn-validate": (True, False),
        "btn-integrate": (True, False),
        "btn-approve-pool": (True, False),
        "btn-reprocess-pool": (True, True),
        "btn-reset-pool": (True, True),
        "btn-clear-files": (False, False),
    },
}


def _derive_legal_actions() -> dict[Phase, frozenset[Action]]:
    """An action is legal in a phase iff its button is visible AND enabled."""
    table: dict[Phase, frozenset[Action]] = {}
    for phase, buttons in _PHASE_BUTTON_STATE.items():
        legal = {
            _BUTTON_ACTIONS[bid]
            for bid, (visible, enabled) in buttons.items()
            if visible and enabled and bid in _BUTTON_ACTIONS
        }
        table[phase] = frozenset(legal)
    return table


LEGAL_ACTIONS: dict[Phase, frozenset[Action]] = _derive_legal_actions()


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
      hasFiles, hasStale, validationReport, hasValidationErrors,
      hasIntegrated, hasAnimalReport.
    """
    # No files → nothing to do
    if not artifacts.get("hasFiles"):
        return "EMPTY"

    # Pool mutated after approval/validation (stale sections) → re-validate
    if artifacts.get("hasStale"):
        return "UPLOADED"

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
