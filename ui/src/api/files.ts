import { API_V2, getJson, sendForm, streamRun } from './client'
import type { RunEvent } from './types'

/**
 * The "Study files" page (M2): docs/ui-redesign/modules/m2/. The backend is
 * web_routes/v2_files_routes.py (ui_api.files).
 *
 * Everything the page shows is in this one read, derived on the server: the
 * phase, which acts are allowed, what each file is taken to be, what the file
 * check found and what comes next. The browser works none of it out.
 */

const enc = encodeURIComponent

export const filesPaths = {
  files: (id: string) => `${API_V2}/studies/${enc(id)}/files`,
  check: (id: string) => `${API_V2}/studies/${enc(id)}/check`,
  remove: (id: string, name: string) => `${API_V2}/studies/${enc(id)}/files/${enc(name)}/remove`,
  removalPreview: (id: string, name: string) =>
    `${API_V2}/studies/${enc(id)}/files/${enc(name)}/removal-preview`,
}

/** An act, with the reason when it is not allowed now. */
export interface Verdict {
  allowed: boolean
  code: string | null
  say: string | null
}

/** A file that rides on another: its units, the table written from it, a note. */
export interface Companion {
  name: string
  role: 'units' | 'table' | 'sidecar' | 'original' | (string & {})
  say: string
}

/** What a file is taken to be, and on whose word. */
export interface Classification {
  platform: string | null
  data_type: string | null
  say: string
  detected: {
    platform: string | null
    data_type: string | null
    basis: 'file_name' | 'content' | 'bm2_experiments' | 'none' | (string & {})
    say: string
    say_full: string
  }
  stated: { platform: string | null; data_type: string | null; by: string; at: string } | null
  status:
    | 'not_checked'
    | 'unconfirmed'
    | 'confirmed'
    | 'changed'
    | 'needs_reconfirm'
    | 'not_recognized'
    | (string & {})
  flags: { code: string; level: string; say: string }[]
}

/** What the check recorded of a file's contents. */
export interface FileTable {
  sexes: string[]
  doses: number[]
  dose_unit: string | null
  animals: number
  animals_by_dose: Record<string, number>
  measurements: number
  measurement_sample: string[]
  selection_groups: string[]
}

/**
 * What a BMDExpress project holds, and on whose word. A project of more than
 * one test article carries another study's data, so the reading travels with
 * where it came from — a language model's reading is never shown as though
 * the file had stated it, nor silence as though it were agreement.
 */
export interface Bm2 {
  experiments: string[]
  species: string | null
  genes: number | null
  test_articles: string[]
  test_article_basis:
    | 'experiment_names_llm'
    | 'experiment_names_regex'
    | 'none'
    | 'unavailable'
    | 'project_not_read'
    | null
    | (string & {})
  test_article_say: string
  test_article_from: string
  test_article_is_a_reading: boolean
}

/** One file a person brought in. */
export interface FileRow {
  name: string
  kind: 'workbook' | 'table' | 'bm2' | (string & {})
  kind_say: string
  type: string
  size: number | null
  added_at: string | null
  companions: Companion[]
  units: { state: string; values: Record<string, string>; say: string | null }
  tables: FileTable[]
  bm2: Bm2 | null
  bm2_changes: null
  narrow_choices: null
  study_number: string | null
  checked: boolean
  classification: Classification
  issues: string[]
  pending: { what: string; say: string; fix: string }[]
  acts: { remove: Verdict; classify: Verdict; narrow: null }
}

/** One finding of the file check, in plain words. */
export interface Finding {
  id: string
  type: string
  group: 'fix' | 'look' | 'expected' | 'elsewhere' | (string & {})
  severity: string
  say: string
  what_to_do: string | null
  files: string[]
  feeds: string | null
  settle: string | null
  known: boolean
  message: string
  details: Record<string, unknown>
}

/** What the report would be built from, per assay and kind of data. */
export interface CoverageRow {
  key: string
  assay: string
  data_type: string
  data_type_say: string
  workbook: string | null
  tables: string[]
  bm2: string | null
  level: 'ok' | 'warn' | 'block' | (string & {})
  say: string
}

export interface Removed {
  id: string
  at: string
  size: number
  files: string[]
  say: string
  acts: { restore: Verdict }
}

export interface Step {
  step: 'bring_in' | 'check' | 'confirm' | 'conflicts' | (string & {})
  status: 'done' | 'todo' | 'blocked' | 'waiting' | 'not_needed' | (string & {})
  say: string
}

export interface Choice {
  data_type: string
  label: string
  platforms: string[]
}

/** Everything the Study files page shows. */
export interface FilesView {
  id: string
  phase: string | null
  takes_files: { allowed: boolean; code: string | null; say: string | null }
  files_token: string | null
  progress: Step[]
  next: { act: string | null; say: string; fix: string }
  acts: Record<'add' | 'check' | 'classify' | 'resolve' | 'remove' | 'reset', Verdict>
  files: FileRow[]
  check: {
    run_at: string
    current: boolean
    why_not_current: string | null
    counts: { fix: number; look: number; expected: number }
    not_shown: { count: number; fix: string; say: string } | null
  } | null
  issues: Finding[]
  conflicts: unknown[]
  coverage: CoverageRow[]
  removed: Removed[]
  removed_size: number
  records: { files: { count: number | null }; datasets: { count: number; current: number | null } }
  integration: { state: string; say: string | null; fix: string } | null
  classification_choices: Record<string, Choice[]>
  limits: { accepted: string[] }
}

export function getFiles(id: string, signal?: AbortSignal): Promise<FilesView> {
  return getJson<FilesView>(filesPaths.files(id), signal)
}

// ---------------------------------------------------------------------------
// Bringing files in
// ---------------------------------------------------------------------------

/** What would happen to one file of a batch. The server decides every field. */
export interface IntakeRow {
  name: string
  size: number
  type: string
  verdict: 'add' | 'units' | 'replace' | 'unchanged' | 'copy' | 'units_missing' | 'refused' | 'left_out' | (string & {})
  say: string
  code: string | null
  /** The question this file waits on, or null when it waits on nothing. */
  needs_answer: 'replace' | 'copy' | 'without_units' | null
  from_zip: string | null
  pairs_with: string | null
  replaces: { name: string; size: number } | null
  copy_of: { name: string; where: 'study' | 'batch' | (string & {}) } | null
}

export interface IntakeCounts {
  add: number
  unchanged: number
  refused: number
  left_out: number
  needs_answer: number
}

export interface IntakePlan {
  id: string
  applied: boolean
  dry_run: boolean
  rows: IntakeRow[]
  counts: IntakeCounts
  brought_in: string[]
  replaced: string[]
  files_token: string
}

/** The names a person answered for, by the question that was asked. */
export interface IntakeAnswers {
  replace?: string[]
  copy_anyway?: string[]
  without_units?: string[]
}

/**
 * Bring a batch of files into the study. The batch is one act: when any file
 * waits on an answer the server brings none of them in and refuses with the
 * plan in its details, which is what the page then shows.
 */
export function bringInFiles(
  id: string,
  files: File[],
  opts: { answers?: IntakeAnswers; filesToken?: string | null; dryRun?: boolean } = {},
): Promise<IntakePlan> {
  const form = new FormData()
  for (const file of files) form.append('files', file, file.name)
  if (opts.answers) form.append('answers', JSON.stringify(opts.answers))
  if (opts.filesToken) form.append('files_token', opts.filesToken)
  if (opts.dryRun) form.append('dry_run', 'true')
  return sendForm<IntakePlan>(filesPaths.files(id), form)
}

export interface CheckSummary {
  files: number
  fix: number
  look: number
  expected: number
}

/** Check the study's files: the §4.4 event stream. */
export function runCheck(id: string): AsyncGenerator<RunEvent> {
  return streamRun(filesPaths.check(id))
}

// ---------------------------------------------------------------------------
// Taking a file out
// ---------------------------------------------------------------------------

/** What removing one file would take with it. The server decides every word. */
export interface RemovalPreview {
  id: string
  file: string
  companions: { name: string; say: string }[]
  size: number
  invalidates: boolean
  kept: boolean
  say: string
  kept_say: string
  invalidates_say: string | null
}

export interface Removal {
  id: string
  file: string
  removed: string[]
  say: string
  kept_say: string
  files_token: string
}

export function getRemovalPreview(
  id: string,
  name: string,
  signal?: AbortSignal,
): Promise<RemovalPreview> {
  return getJson<RemovalPreview>(filesPaths.removalPreview(id, name), signal)
}

/** Take one file out of the study, with everything that rides on it. */
export function removeFile(id: string, name: string, filesToken?: string | null): Promise<Removal> {
  const form = new FormData()
  if (filesToken) form.append('files_token', filesToken)
  return sendForm<Removal>(filesPaths.remove(id, name), form)
}
