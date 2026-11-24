import { API_V2, getJson } from './client'

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
  bm2: { experiments: string[]; species: string | null; genes: number | null } | null
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
