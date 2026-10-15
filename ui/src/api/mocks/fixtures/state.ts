import type { ErrorEnvelope, ExistingStudyState, StudyState, Vocabularies } from '../../types'
import rawEmpty from './real/state.DTXSID9000001.json'
import rawUploaded from './real/state.DTXSID1022477.json'
import rawValidationErrors from './real/state.DTXSID1021952.json'
import rawValidated from './real/state.DTXSID5032498.json'
import rawIntegrated from './real/state.DTXSID4028880.json'
import rawPfhxsam from './real/state.DTXSID50469320.json'
import rawApprovedSections from './real/state.DTXSID2029905.json'
import rawStale from './real/state.DTXSID6024701.json'
import rawReport from './real/state.DTXSID1020431.json'
import rawRat from './real/state.DTXSID1020431_rat.json'
import rawMouse from './real/state.DTXSID1020431_mouse.json'
import rawCompanion from './real/state.DTXSID50469320_published.json'
import rawMissing from './real/state.DTXSID9999999.json'
import rawInvalid from './real/state.not-a-study.json'
import rawVocabularies from './real/vocabularies.json'

/**
 * GET /api/v2/studies/{id}/state, mocked (MODULES.md §4.1), from the
 * backend's OWN answers (`real/*.json`, written by scripts/fetch-fixtures.mjs
 * from a backend running on a scratch copy of the sessions). Nothing here is
 * hand-written except STATE_RUNNING, whose `run` the backend does not serve
 * yet (C5).
 *
 * Every phase is a real answer. Where no real session is in that phase, a
 * scratch copy of a real one was put there with the workflow's own steps or
 * by removing the files the phase is derived from:
 *
 * | fixture                        | id                  | how the scratch copy was made |
 * |--------------------------------|---------------------|-------------------------------|
 * | STATE_EMPTY                    | DTXSID9000001       | a new folder with only an identity.json naming the DTXSID |
 * | STATE_UPLOADED                 | DTXSID1022477       | copy without validation_report.json and the Process results |
 * | STATE_VALIDATION_ERRORS        | DTXSID1021952       | copy without integrated.json; one "dose_mismatch" error (bmdx_pipe's own issue shape) added to its validation report |
 * | STATE_VALIDATED                | DTXSID5032498       | copy without integrated.json and animal_report.json |
 * | STATE_INTEGRATED               | DTXSID4028880       | copy without animal_report.json |
 * | STATE_APPROVED                 | DTXSID50469320      | NIEHS-10 (PFHxSAm), as it is |
 * | STATE_APPROVED_SECTIONS        | DTXSID2029905       | three sections approved with accept_section_step |
 * | STATE_STALE_AFTER_FILE_CHANGE  | DTXSID6024701       | six sections approved with accept_section_step, then invalidate_pool_artifacts (a file change): the Summary is stale and rewritten, publishing is blocked |
 * | STATE_REPORT                   | DTXSID1020431       | NIEHS-13, a report over a rat and a mouse study |
 * | STATE_MEMBER_RAT/_MOUSE        | DTXSID1020431_rat/… | its member studies |
 * | STATE_COMPANION                | DTXSID50469320_published | the published book's content |
 * | STATE_MISSING                  | DTXSID9999999       | no such session |
 * | REFUSAL_INVALID_STUDY_ID       | not-a-study         | the 400 envelope |
 */

interface Saved<T> {
  status: number
  body: T
}

function existing(raw: unknown): ExistingStudyState {
  const saved = raw as Saved<StudyState>
  if (!saved.body.exists) throw new Error(`fixture ${saved.body.id} does not exist`)
  return saved.body
}

export const STATE_EMPTY = existing(rawEmpty)
export const STATE_UPLOADED = existing(rawUploaded)
export const STATE_VALIDATION_ERRORS = existing(rawValidationErrors)
export const STATE_VALIDATED = existing(rawValidated)
export const STATE_INTEGRATED = existing(rawIntegrated)
export const STATE_APPROVED = existing(rawPfhxsam)
export const STATE_APPROVED_SECTIONS = existing(rawApprovedSections)
export const STATE_STALE_AFTER_FILE_CHANGE = existing(rawStale)
export const STATE_REPORT = existing(rawReport)
export const STATE_MEMBER_RAT = existing(rawRat)
export const STATE_MEMBER_MOUSE = existing(rawMouse)
export const STATE_COMPANION = existing(rawCompanion)
export const STATE_MISSING = (rawMissing as Saved<StudyState>).body
export const REFUSAL_INVALID_STUDY_ID = (rawInvalid as Saved<ErrorEnvelope>).body

/** GET /api/v2/vocabularies, as the backend answers. */
export const VOCABULARIES = (rawVocabularies as Saved<Vocabularies>).body

/**
 * HAND-MADE, PROPOSED (C5): PFHxSAm while Process runs (another tab, or before
 * a reload). The backend serves no `run` yet; this is the shape MODULES.md §4.1
 * fixes for it, over the real PFHxSAm answer.
 */
export const STATE_RUNNING: ExistingStudyState = {
  ...STATE_APPROVED,
  run: {
    in_flight: true,
    started_at: '2026-10-14T09:00:00+00:00',
    last: { ok: true, finished_at: '2026-10-12T11:52:41+00:00', content_errors: [] },
  },
}

/** A study id with no session behind it, as the backend answers. */
export function stateNotFound(id: string): StudyState {
  return { id, exists: false }
}

/** Every real answer, by study id: what the mock server serves. */
export const STATES_BY_ID: Record<string, ExistingStudyState> = Object.fromEntries(
  [
    STATE_EMPTY,
    STATE_UPLOADED,
    STATE_VALIDATION_ERRORS,
    STATE_VALIDATED,
    STATE_INTEGRATED,
    STATE_APPROVED,
    STATE_APPROVED_SECTIONS,
    STATE_STALE_AFTER_FILE_CHANGE,
    STATE_REPORT,
    STATE_MEMBER_RAT,
    STATE_MEMBER_MOUSE,
    STATE_COMPANION,
  ].map((s) => [s.id, s]),
)
