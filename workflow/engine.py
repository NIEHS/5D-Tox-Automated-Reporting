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
    NEXT_STEP,
    Action,
    Phase,
    compute_section_completeness,
    derive_phase,
)
from workflow.integration_basis import integration_status
from workflow.section_catalog import catalog_for_session
from workflow.section_readiness import derive_section_readiness
from workflow.store import DiskPoolStore, PoolStore

def _has_knowledge_base(dtxsid: str) -> bool:
    """Whether the session's report has a knowledge base that can ground its
    genomics interpretation: the one its document definition names, else the
    default (knowledge_base.registry)."""
    from knowledge_base.registry import kb_or_none
    return kb_or_none(dtxsid) is not None


def _is_processed(session_dir) -> bool:
    """Whether the session has been Processed — its section content exists. Gated on
    the NTP cache (the first Process stage), same signal the wizard `/processed`
    route uses. Cheap glob; no content load. Gates M&M generation (its study
    metadata all exists post-Process)."""
    from pathlib import Path
    d = Path(session_dir)
    return d.exists() and bool(list(d.glob("_cache_ntp_*.json")))


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
    next_step       — the act that moves the phase forward (None once
                      integrated: everything is legal there)
    """

    phase: Phase
    legal_actions: frozenset[Action]
    artifacts: dict = field(default_factory=dict)
    completeness: dict = field(default_factory=dict)
    next_step: Action | None = None

    def to_dict(self) -> dict:
        """JSON-serializable form for the wire (enums → their string values)."""
        return {
            "phase": self.phase.value,
            "legal_actions": sorted(a.value for a in self.legal_actions),
            "artifacts": self.artifacts,
            "completeness": self.completeness,
            "next_step": self.next_step.value if self.next_step else None,
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
            # Whether the dataset was built from the validation on disk now
            # (workflow.integration_basis): current / out_of_date / unrecorded,
            # None with no integrated.json. Small reads: the basis file, the
            # report already in hand, precedence.json.
            "integration": integration_status(self.dtxsid, self.store,
                                              report=validation_report),
            # Presence of the query substrate (session.duckdb), built only at the
            # end of Process — the cheap "has this session been processed" signal
            # the data-prep DB-view button gates on. Read-only stat, like above.
            "hasQuerySubstrate": self.store.artifact_exists(self.dtxsid, "session.duckdb"),
            # The report's knowledge base, usable for the genomics interpretation
            # (knowledge_base.registry: its definition's, else the default). Gates
            # the KB-dependent document sections (genomics interpretation → graph-
            # grounded references).
            "hasKnowledgeBase": _has_knowledge_base(self.dtxsid),
        }

    # -- derived state -----------------------------------------------------

    def state(self) -> WorkflowState:
        """Re-derive the full workflow state from disk. Cheap enough to call on
        every request; phase is never cached (invariant 3)."""
        artifacts = self.gather_artifacts()
        # An integration built from another validation is not this one's
        # dataset: the phase reads VALIDATED (integrate again). The raw
        # hasIntegrated flag stays in `artifacts`; derive_phase is unchanged.
        effective = {**artifacts, "hasIntegrated": bool(
            artifacts["hasIntegrated"] and artifacts.get("integration") != "out_of_date")}
        phase = Phase(derive_phase(effective))

        report = artifacts["validationReport"]
        coverage = report.get("coverage_matrix", {}) if isinstance(report, dict) else {}
        completeness = compute_section_completeness(coverage)

        return WorkflowState(
            phase=phase,
            legal_actions=LEGAL_ACTIONS.get(phase, frozenset()),
            artifacts={k: v for k, v in artifacts.items() if k != "validationReport"},
            completeness=completeness,
            next_step=NEXT_STEP.get(phase),
        )

    # -- derived section readiness ----------------------------------------

    def derive_section_readiness(
        self, section_states: "dict[str, bool] | None" = None, catalog=None,
    ) -> dict:
        """Per-report-section readiness, DERIVED from what is approved on disk.

        Reads the approved-state of every section via the store and applies the
        declared dependency table (workflow.section_readiness). Returns
        `{section_key: {enabled, blocked_by, approved}}`. Like phase, this is
        recomputed every call and never stored (CONTEXT.md invariant 3) — it
        replaces the imperative `ready.methods` / `ready.summary` flags the JS
        front-end sets from a dozen call sites.
        """
        # Callers that already read the states / built the session catalog for
        # their own purposes pass them in, so a request does each exactly once.
        if section_states is None:
            section_states = self.store.read_section_states(self.dtxsid)
        if catalog is None:
            catalog = catalog_for_session(self.dtxsid)
        return derive_section_readiness(
            section_states,
            resources={
                "knowledge_base": _has_knowledge_base(self.dtxsid),
                "processed": _is_processed(self.store.session_dir(self.dtxsid)),
            },
            catalog=catalog,
        )

    # -- derived publish readiness (currency BLOCK, report grain) ----------

    def publish_readiness(self) -> dict:
        """Whether the report may be published, DERIVED from section currency.

        Surfaces the Phase 3a report-grain currency BLOCK: a reprocess stales the
        LLM sections (workflow.reprocess) and stamps their `regenerated` reason;
        publishing is refused until a human re-accepts each. Returns
        `{can_publish: bool, blocking: [{section_key, reason}, ...]}`, recomputed
        every call (never stored). `reason` echoes the section's `regenerated`
        marker when present, else "stale". Also surfaces the rewrite ATTRIBUTION
        (the reframed Phase 3a gap): a stale LLM section IS the "regenerated
        because data changed, re-accept it" signal.

        An apical BMD the review screen flagged blocks too, as
        ``bmd_review:<sex>|<platform>|<endpoint>``: ``bmd_review_pending`` until
        a reviewer decides it, ``bmd_review_not_applied`` until Process applies
        the decision (pipeline.bmd_review).  A report over several studies
        (studies.json: NIEHS-12/13's rat and mouse) waits for each member
        study's flags too, as ``bmd_review:<member session>:<key>`` with the
        member's ``session``, where the decision is recorded.
        """
        from workflow.reprocess import blocking_llm_sections

        sections = self.store.read_section_dicts(self.dtxsid)
        blocking = []
        for key in blocking_llm_sections(sections):
            regen = sections.get(key, {}).get("regenerated")
            reason = regen.get("reason") if isinstance(regen, dict) else "stale"
            blocking.append({"section_key": key, "reason": reason})
        # An apical BMD far below its NOEL/LOEL needs a reviewer's decision
        # (pipeline.bmd_review), and the decision a Process to take effect.
        from pipeline.bmd_review import FLAGS_FILE, REVIEWS_FILE, unsettled
        from rendering.report_compose import STUDIES_FILE

        members = self.store.read_json(self.dtxsid, STUDIES_FILE) or {}
        for session in [self.dtxsid, *members.values()]:
            flags = (self.store.read_json(session, FLAGS_FILE) or {}).get("flags") or []
            reviews = self.store.read_json(session, REVIEWS_FILE) or {}
            prefix = "" if session == self.dtxsid else f"{session}:"
            for item in unsettled(flags, reviews):
                entry = {"section_key": f"bmd_review:{prefix}{item['key']}",
                         "reason": item["reason"]}
                if prefix:
                    entry["session"] = session
                blocking.append(entry)
        return {"can_publish": not blocking, "blocking": blocking}
