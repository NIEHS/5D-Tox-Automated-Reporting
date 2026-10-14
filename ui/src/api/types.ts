/**
 * The shared contracts of MODULES.md §4, as TypeScript types.
 *
 * These are the shapes the backend serves; the front-end reads them and never
 * computes them. A field the backend does not serve yet is absent (optional
 * here), never guessed (§4.1). Fields marked PROPOSED are not in MODULES.md §4
 * and are awaiting the orchestrator's decision.
 */

// ---------------------------------------------------------------------------
// §4.1 The state read model: GET /api/v2/studies/{id}/state
// ---------------------------------------------------------------------------

/** workflow.phases.Phase. A value outside this list is shown as unknown, never hidden. */
export const PHASES = [
  'EMPTY',
  'UPLOADED',
  'VALIDATION_ERRORS',
  'VALIDATED',
  'INTEGRATED',
  'APPROVED',
] as const
export type Phase = (typeof PHASES)[number]

/** workflow.phases.Action. */
export const ACTIONS = ['VALIDATE', 'INTEGRATE', 'APPROVE', 'REPROCESS', 'RESET', 'CLEAR_FILES'] as const
export type Action = (typeof ACTIONS)[number]

/** The module ids of MODULES.md §3; `fix` fields name one of these. */
export const MODULE_IDS = [
  'M1', 'M2', 'M3', 'M4', 'M5', 'M6',
  'P1', 'P2',
  'D1', 'D2', 'D3', 'D4', 'D5', 'D6',
] as const
export type ModuleId = (typeof MODULE_IDS)[number]

export interface Identity {
  name?: string
  casrn?: string
  dtxsid?: string
  short_name?: string
}

export interface MethodPin {
  name: string
  mode: 'fixed' | 'track'
  /** "default" means nobody chose it: the screen must say so (never a silent default). */
  pinned_by: 'person' | 'default'
  deviations: string[]
  mismatches: string[]
}

export interface DefinitionPin {
  name: string
  mode: 'fixed' | 'track'
  drift: string | null
  source: 'study' | 'era' | 'session'
}

export interface Pins {
  method?: MethodPin | null
  definition?: DefinitionPin | null
}

export interface RunLast {
  ok: boolean
  finished_at: string | null
  content_errors: string[]
}

export interface RunState {
  in_flight: boolean
  started_at: string | null
  last: RunLast | null
}

/** workflow.labels.Fact, the maturity ladder. Not in the §4.1 example; PROPOSED. */
export type Maturity = 'first_draft' | 'working_draft' | 'final'

export interface Regenerated {
  reason: string
  at?: string
}

export interface SectionState {
  key: string
  /** who writes it: an LLM, or the program. */
  kind: 'llm' | 'programmatic'
  approvable: boolean
  approved: boolean
  stale: boolean
  regenerated: Regenerated | null
  wording_review: string[]
  source: string
  version: number
  version_status: string | null
  machine_may_write: boolean
  blocked_by: string[]
  /** PROPOSED: the maturity rung, if the backend serves it. */
  maturity?: Maturity | null
}

export type ReadinessLevel = 'block' | 'warn'

export interface ReadinessItem {
  id: string
  level: ReadinessLevel
  say: string
  fix?: ModuleId | null
  section?: string
}

export interface Readiness {
  ready: boolean
  items: ReadinessItem[]
}

/** PROPOSED: the member studies of a report over several studies. */
export interface MemberStudy {
  role: string
  id: string
  phase?: string
  processed?: boolean
}

export interface StudyState {
  id: string
  exists: boolean
  /** typed as string: an unknown phase from a newer backend is shown, not dropped. */
  phase: Phase | (string & {})
  legal_actions: (Action | (string & {}))[]
  identity?: Identity | null
  pins?: Pins
  processed?: boolean
  run?: RunState
  sections?: SectionState[]
  readiness?: {
    data_approval?: Readiness
    publish?: Readiness
  }
  members?: MemberStudy[]
}

// ---------------------------------------------------------------------------
// §4.2 The error envelope
// ---------------------------------------------------------------------------

export interface ErrorBody {
  code: string
  status: number
  /** the backend's verbatim text */
  message: string
  /** plain words for a toxicologist */
  say: string
  fix?: ModuleId | null
  details?: Record<string, unknown>
}

export interface ErrorEnvelope {
  error: ErrorBody
}

/** A "success that did nothing" (§4.2). */
export interface Noop {
  code: string
  say: string
}

export type WithNoop<T> = T & { noop?: Noop }

// ---------------------------------------------------------------------------
// §4.3 Confirm-or-undo: the dry-run shape
// ---------------------------------------------------------------------------

export type ActStrength = 'reversible' | 'costly' | 'irreversible'

export interface DryRunItem {
  what: string
  say?: string
}

export interface DryRun {
  act: string
  strength: ActStrength
  deletes: DryRunItem[]
  keeps: DryRunItem[]
  approvals_lost: string[]
  cost?: { say: string } | null
  reason_required: boolean
}

// ---------------------------------------------------------------------------
// §4.4 The run's event stream (NDJSON)
// ---------------------------------------------------------------------------

export type StepStatus = 'computing' | 'reused' | 'done' | 'failed'

export interface StepEvent {
  event: 'step'
  unit: string
  status: StepStatus
  say: string
  ms?: number
}

export interface ResultEvent {
  event: 'result'
  ok: boolean
  summary: Record<string, unknown>
}

export interface ErrorEvent {
  event: 'error'
  error: ErrorBody
}

export type RunEvent = StepEvent | ResultEvent | ErrorEvent

// ---------------------------------------------------------------------------
// §4.5 Vocabularies: GET /api/v2/vocabularies
// ---------------------------------------------------------------------------

/** A flat controlled list. */
export interface FlatVocabulary {
  label?: string
  values: string[]
}

/** A list that depends on another field's value (strain ← species). */
export interface DependentVocabulary {
  label?: string
  depends_on: string
  by: Record<string, string[]>
}

export type Vocabulary = FlatVocabulary | DependentVocabulary

/** The id kinds an <IdField> checks. */
export type IdKind = 'dtxsid' | 'casrn' | 'doi' | 'date'

/**
 * PROPOSED: the backend's id patterns, served beside the vocabularies so that
 * the front-end checks with the backend's own rule (§4.5).
 * `pattern` is a JavaScript-compatible regular expression source.
 */
export interface IdPattern {
  pattern: string
  example: string
  say: string
}

export interface Vocabularies {
  vocabularies: Record<string, Vocabulary>
  patterns?: Partial<Record<IdKind, IdPattern>>
}

export function isDependentVocabulary(v: Vocabulary): v is DependentVocabulary {
  return 'depends_on' in v
}
