"""
workflow.engine — the UI-agnostic pool workflow engine (ADR-0014, step 3).

`WorkflowEngine` is the single object a front-end (web, TUI, test) drives. It:

  * DERIVES the settled pool phase from artifacts on disk (never stores it —
    CONTEXT.md invariant 3), and
  * exposes the legal actions for that phase (from `workflow.phases.LEGAL_ACTIONS`),
    so a UI maps abstract actions → its own widgets instead of re-deriving button
    state, and
  * runs the workflow steps (`workflow.steps`) as its mutators.

State access goes through an injected `PoolStore` (ADR-0014 Q2); the engine holds
no state of its own beyond the dtxsid + store.

**The de-conflation fix (ADR-0014 follow-up).** The JS caller (`chemical.js`)
collapsed `hasIntegrated` and `hasAnimalReport` into a single `!!data.animal_report`
because its restore payload only carried the animal report. Server-side both are
independently observable on disk: `integrated.json` exists after integrate,
`animal_report.json` only after approve, and `invalidate_pool_artifacts` deletes
both on pool mutation. Deriving from disk therefore distinguishes
"integrated-not-approved" (INTEGRATED) from "approved" (APPROVED) correctly, which
the pure `derive_phase` always supported but the JS caller could not feed. The
route test pins this.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from workflow.phases import (
    LEGAL_ACTIONS,
    Action,
    Phase,
    compute_section_completeness,
    derive_phase,
)
from workflow.store import DiskPoolStore, PoolStore


@dataclass
class WorkflowState:
    """A medium-agnostic snapshot of the pool workflow. UIs render this; they do
    not compute phase themselves.

    phase           — settled Phase (derived, never stored)
    legal_actions   — Actions permitted in this phase
    artifacts       — the raw presence flags phase was derived from (transparency
                      / debugging; a UI may ignore them)
    completeness    — per-platform readiness from the coverage matrix ({} until
                      validation has produced a coverage matrix)
    """

    phase: Phase
    legal_actions: frozenset[Action]
    artifacts: dict = field(default_factory=dict)
    completeness: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """JSON-serializable form for the wire (enums → their string values)."""
        return {
            "phase": self.phase.value,
            "legal_actions": sorted(a.value for a in self.legal_actions),
            "artifacts": self.artifacts,
            "completeness": self.completeness,
        }


class WorkflowEngine:
    """Drives one session's pool workflow over an injected store."""

    def __init__(self, dtxsid: str, store: PoolStore | None = None):
        self.dtxsid = dtxsid
        self.store = store if store is not None else DiskPoolStore()

    # -- artifact gathering ------------------------------------------------

    def gather_artifacts(self) -> dict:
        """Read the phase-relevant artifact flags from the store.

        Cheap: presence checks + the (small) validation report. Never loads
        integrated.json — `artifact_exists` only stats it.
        """
        validation_report = self.store.read_json(self.dtxsid, "validation_report.json")
        has_validation_errors = bool(
            isinstance(validation_report, dict)
            and any(
                (i or {}).get("severity") == "error"
                for i in validation_report.get("issues", [])
            )
        )
        return {
            "hasFiles": self.store.has_files(self.dtxsid),
            "hasStale": self.store.has_stale_sections(self.dtxsid),
            "validationReport": validation_report,
            "hasValidationErrors": has_validation_errors,
            # De-conflated: integrated.json and animal_report.json are separate
            # files with distinct lifecycles (see module docstring).
            "hasIntegrated": self.store.artifact_exists(self.dtxsid, "integrated.json"),
            "hasAnimalReport": self.store.artifact_exists(self.dtxsid, "animal_report.json"),
        }

    # -- derived state -----------------------------------------------------

    def state(self) -> WorkflowState:
        """Re-derive the full workflow state from disk. Cheap enough to call on
        every request; phase is never cached (invariant 3)."""
        artifacts = self.gather_artifacts()
        phase = Phase(derive_phase(artifacts))

        report = artifacts["validationReport"]
        coverage = report.get("coverage_matrix", {}) if isinstance(report, dict) else {}
        completeness = compute_section_completeness(coverage)

        return WorkflowState(
            phase=phase,
            legal_actions=LEGAL_ACTIONS.get(phase, frozenset()),
            artifacts={k: v for k, v in artifacts.items() if k != "validationReport"},
            completeness=completeness,
        )
