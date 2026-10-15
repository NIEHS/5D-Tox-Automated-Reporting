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

/**
 * The test article as stated (identity.json). A value the file does not hold
 * is null: not stated, not guessed.
 */
export interface Identity {
  name: string | null
  casrn: string | null
  /** may be null (a report over several studies) or name a suffixed session id */
  dtxsid: string | null
  /** the stated abbreviation */
  short_name: string | null
}

/** The §4.2 envelope's body, carried where a pin cannot be resolved. */
export type PinError = ErrorBody

/** The analysis method profile (pipeline.method_profile). */
export interface MethodPin {
  /** false: nothing is pinned; `deviations` then says which profile would be used */
  pinned: boolean
  name: string | null
  hash: string | null
  series: string | null
  mode: 'fixed' | 'track' | (string & {}) | null
  /** "default" means nobody chose it: the screen must say so (never a silent default). */
  pinned_by: 'person' | 'default' | (string & {}) | null
  pinned_at: string | null
  /** absent when the profile does not resolve (then `error` is present) */
  deviations?: string[]
  /** what is checked only when Process runs (e.g. whether this machine can run an engine) */
  unchecked?: string[]
  /** where the dataset's recorded analyses disagree with the profile */
  mismatches?: MethodMismatch[]
  error?: PinError
}

export interface MethodMismatch {
  analysis: string
  setting: string
  recorded: unknown
  profile: unknown
  message: string
}

/** The document definition (document_model.definition_pin). */
export interface DefinitionPin {
  pinned: boolean
  /** which definition renders */
  name: string | null
  hash: string | null
  mode: 'fixed' | 'track' | (string & {}) | null
  pinned_by: 'person' | 'default' | (string & {}) | null
  pinned_at: string | null
  /** where the structure comes from */
  source: 'session' | 'study' | 'era' | 'template' | (string & {})
  /** a FIXED study renders from the composed copy saved with its pin */
  snapshot: boolean
  /** how the files now differ from a FIXED pin; null when they don't */
  drift?: string | null
  error?: PinError
}

export interface Pins {
  method?: MethodPin
  definition?: DefinitionPin
}

/** NOT SERVED YET (C5): the run record. Absent from today's read model. */
export interface RunLast {
  ok: boolean
  finished_at: string | null
  content_errors: string[]
}

/** NOT SERVED YET (C5). */
export interface RunState {
  in_flight: boolean
  started_at: string | null
  last: RunLast | null
}

/**
 * Who writes a section (workflow.section_catalog: the node's binding, ADR-0025):
 * a language model, the program, a supplied text, or a reduction of other
 * sections. An unknown value from a newer backend is shown as unknown.
 */
export const SECTION_KINDS = ['llm', 'programmatic', 'authored', 'derived'] as const
export type SectionKind = (typeof SECTION_KINDS)[number]

/** workflow.labels.Fact values a section can carry. */
export type SectionFact = 'approved' | 'first_draft' | 'working_draft' | 'final' | 'protected' | 'published'

export interface Regenerated {
  /** the recorded reason code (e.g. "data_changed"); never shown */
  reason: string
  /** the reason in plain words: what a screen shows */
  say: string
}

/** Whether a person may approve the section now, and if not, why (served). */
export interface AcceptVerdict {
  allowed: boolean
  code: 'not_approvable' | 'blocked' | 'not_saved_as_section' | 'no_saved_text' | (string & {}) | null
  say: string | null
}

export interface SectionState {
  key: string
  title: string | null
  kind: SectionKind | (string & {})
  /** approvable in the catalog; whether it can be approved NOW is `accept` */
  approvable: boolean
  /** the family of an instance (bm2_* → "bm2", genomics_* → "genomics") */
  instance_of: string | null
  /** "front" (front matter) or "body"; null for instances */
  region: 'front' | 'body' | (string & {}) | null
  /** whether a section file exists: no file, nothing to approve */
  has_file: boolean
  /** unlocked by what it depends on */
  enabled: boolean
  /** the unlock groups it waits on (KIND_UNLOCK) */
  blocked_by: string[]
  approved: boolean
  facts: (SectionFact | (string & {}))[]
  user_edited: boolean
  stale: boolean
  regenerated: Regenerated | null
  /** data-derived words that flipped under approved wording ("finding.slot") */
  wording_review: string[]
  /** "generated", "toxicr", …; null when there is no file */
  source: string | null
  /** the model that wrote it, when recorded */
  model: string | null
  version: number | null
  version_status: 'blessed' | 'needs-re-bless' | 'working' | (string & {}) | null
  machine_may_write: boolean
  accept: AcceptVerdict
}

export type ReadinessLevel = 'block' | 'warn'

export interface ReadinessItem {
  id: string
  level: ReadinessLevel
  say: string
  fix?: ModuleId | null
  section?: string
  /** the backend's reason code (e.g. "data_changed") */
  reason?: string | null
}

/** One thing a readiness verdict looked at. */
export interface ReadinessCheck {
  id: string
  say: string
}

export interface Readiness {
  /** nothing that was checked blocks; NOT "ready" unless `complete` */
  ready: boolean
  /** whether `checks` covers everything; false until C6 */
  complete?: boolean
  /** what was checked */
  checks?: ReadinessCheck[]
  items: ReadinessItem[]
}

/** What kind of session (M1 contract §3). */
export type SessionKind = 'study' | 'report' | 'member' | 'companion' | 'other'

export interface Relations {
  /** for a member: the report it belongs to */
  parent: string | null
  /** for a companion: the generated study it was built beside */
  twin: string | null
}

/** One study of a report over several studies (studies.json). */
export interface MemberStudy {
  /** the study's key in studies.json ("rat", "mouse") */
  key: string
  id: string
  exists: boolean
  /** present when it exists */
  phase?: Phase | (string & {})
  processed?: boolean
  readiness?: { publish?: Readiness }
}

/** A study that exists. */
export interface ExistingStudyState {
  id: string
  exists: true
  kind: SessionKind | (string & {})
  relations: Relations
  /** typed as string: an unknown phase from a newer backend is shown, not dropped. */
  phase: Phase | (string & {})
  legal_actions: (Action | (string & {}))[]
  identity: Identity | null
  pins: Pins
  processed: boolean
  /** NOT SERVED YET (C5) */
  run?: RunState
  sections: SectionState[]
  readiness: {
    /** NOT SERVED YET (C6) */
    data_approval?: Readiness
    publish?: Readiness
  }
  /** only for a report over several studies */
  members?: MemberStudy[]
}

/** No session has this id. */
export interface MissingStudyState {
  id: string
  exists: false
}

export type StudyState = ExistingStudyState | MissingStudyState

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

/** A flat controlled list. `label` is the field's BMDExpress 3 header name. */
export interface FlatVocabulary {
  label: string
  values: string[]
}

/** A list that depends on another field's value (strain ← species, the only one served). */
export interface DependentVocabulary {
  label: string
  depends_on: string
  by: Record<string, string[]>
}

export type Vocabulary = FlatVocabulary | DependentVocabulary

/** The id kinds the backend serves a pattern for. */
export type IdKind = 'study_id' | 'session_id' | 'dtxsid' | 'casrn' | 'doi'

/** The backend's id pattern; `pattern` is a JavaScript-compatible regular expression source. */
export interface IdPattern {
  pattern: string
  example: string
  say: string
}

export interface Vocabularies {
  vocabularies: Record<string, Vocabulary>
  patterns: Partial<Record<IdKind, IdPattern>>
}

export function isDependentVocabulary(v: Vocabulary): v is DependentVocabulary {
  return 'depends_on' in v
}
