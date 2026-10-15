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

# The shared knowledge base (bmdx.duckdb) is a repo-level static artifact, resolved
# cwd-relative — the same default ToxKBQuerier(db_path="bmdx.duckdb") uses, and the
# server runs from the repo root. Not per-session.
_KNOWLEDGE_BASE_FILE = "bmdx.duckdb"


def _has_knowledge_base() -> bool:
    """Whether the shared knowledge base (bmdx.duckdb) is present."""
    from pathlib import Path
    return Path(_KNOWLEDGE_BASE_FILE).exists()


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
            # Presence of the shared knowledge base (bmdx.duckdb, repo-level). Gates
            # the KB-dependent document sections (genomics interpretation → graph-
            # grounded references). Not per-session; resolved cwd-relative to match
            # ToxKBQuerier's default. Always present today — infrastructure for when
            # the KB becomes buildable/absent (the deferred K-graph GUI).
            "hasKnowledgeBase": _has_knowledge_base(),
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
        )

    # -- the guard (ADR-0014: every mutating step checks legality first) ---

    def require(self, action) -> WorkflowState:
        """Derive the state and refuse `action` when the phase does not allow it
        (PhaseRefusal, 409 ``phase_not_allowed``). Returns the state, so the
        caller does not derive it twice. Every mutating step calls this before
        it reads or writes anything else; C5's run lock will refuse here too."""
        from workflow.errors import PhaseRefusal

        action = Action(action)
        st = self.state()
        if action not in st.legal_actions:
            nxt = NEXT_STEP.get(st.phase)
            raise PhaseRefusal(
                self.dtxsid, action.value, st.phase.value,
                [a.value for a in st.legal_actions],
                integration=st.artifacts.get("integration"),
                next_action=nxt.value if nxt else None)
        return st

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
                "knowledge_base": _has_knowledge_base(),
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
        """
        from workflow.reprocess import blocking_llm_sections

        sections = self.store.read_section_dicts(self.dtxsid)
        blocking = []
        for key in blocking_llm_sections(sections):
            regen = sections.get(key, {}).get("regenerated")
            reason = regen.get("reason") if isinstance(regen, dict) else "stale"
            blocking.append({"section_key": key, "reason": reason})
        return {"can_publish": not blocking, "blocking": blocking}


def require_legal(dtxsid: str, action, store: PoolStore | None = None) -> WorkflowState:
    """``WorkflowEngine(dtxsid, store).require(action)``: the one guard every
    mutating entry point calls (route, command line, notebook, script)."""
    return WorkflowEngine(dtxsid, store).require(action)
