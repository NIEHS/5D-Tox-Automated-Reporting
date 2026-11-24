import type { Classification, Finding, FileRow, Step } from '../../api/files'

/**
 * Plain words for what the backend serves about a study's data files. These
 * translate; they decide nothing. A value this page does not know is shown as
 * it was served, never passed off as one it knows.
 *
 * Nobody is addressed and the spelling is American (wording.test.ts).
 */

export const TITLE = 'Study files'
export const PURPOSE = 'Bring in the data files, check them, and say what each one is.'

export const LEDE =
  'The study starts here. Every file is checked against the others and against the ' +
  'study workbook, and what each one holds is confirmed before anything is combined.'

// ---------------------------------------------------------------------------
// What a file is
// ---------------------------------------------------------------------------

/** The mark on a row: what the application knows about this file's kind. */
export interface Mark {
  label: string
  tone: 'success' | 'warning' | 'error' | 'processing' | 'default'
  explain: string
}

const MARKS: Record<string, Mark> = {
  not_checked: {
    label: 'Not checked yet',
    tone: 'default',
    explain: 'The file check has not read this file yet.',
  },
  unconfirmed: {
    label: 'Recognized, not confirmed',
    tone: 'warning',
    explain:
      'The check read this from the file name. Nothing is taken as confirmed until a person says so.',
  },
  confirmed: {
    label: 'Confirmed',
    tone: 'success',
    explain: 'A person confirmed this, and the next check keeps it.',
  },
  changed: {
    label: 'Corrected',
    tone: 'processing',
    explain:
      'A person said this file is something other than the check read from its name. The correction stands.',
  },
  needs_reconfirm: {
    label: 'Changed since it was confirmed',
    tone: 'warning',
    explain:
      'The file is not the one that was confirmed. Confirm what it is again, or check the files.',
  },
  read_for_itself: {
    label: 'Read by the application',
    tone: 'default',
    explain:
      'Nobody states what this file is: it either holds this or it does not, and the check reads which.',
  },
  not_recognized: {
    label: 'Not recognized',
    tone: 'error',
    explain:
      'The check cannot tell what this file is from its name. Say what it is, or remove it.',
  },
}

export function markOf(classification: Classification): Mark {
  return (
    MARKS[classification.status] ?? {
      label: `Marked "${classification.status}"`,
      tone: 'error',
      explain:
        'The application gave a state this page does not know. Treat what this file is as unsettled.',
    }
  )
}

/** The contents of a file, as one line. */
function count(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}

export function contentsWords(row: FileRow): string {
  if (row.bm2) {
    const parts = [count(row.bm2.experiments.length, 'experiment')]
    if (row.bm2.species) parts.push(row.bm2.species)
    if (row.bm2.genes) parts.push(count(row.bm2.genes, 'gene'))
    return parts.join(' · ')
  }
  const table = row.tables[0]
  if (!table) return NOT_RECORDED
  const parts: string[] = []
  if (table.sexes.length) parts.push(table.sexes.join(', '))
  if (table.animals) parts.push(count(table.animals, 'animal'))
  if (table.doses.length) {
    parts.push(`${count(table.doses.length, 'dose group')}${table.dose_unit ? ` (${table.dose_unit})` : ''}`)
  }
  if (table.measurements) parts.push(count(table.measurements, 'measurement'))
  return parts.length ? parts.join(' · ') : NOT_RECORDED
}

export const NOT_RECORDED = 'Not recorded'

export function sizeWords(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return NOT_RECORDED
  if (bytes < 1024) return `${bytes} bytes`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} kB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ---------------------------------------------------------------------------
// The check
// ---------------------------------------------------------------------------

export const GROUPS: { key: Finding['group']; title: string; explain: string }[] = [
  {
    key: 'fix',
    title: 'Must be fixed',
    explain: 'The files cannot be combined until each of these is settled.',
  },
  {
    key: 'look',
    title: 'Worth a look',
    explain: 'Nothing here blocks combining the files. Each one is worth reading first.',
  },
  {
    key: 'expected',
    title: 'Expected for this kind of package',
    explain: 'These are normal for a package like this one, and are listed so nothing is hidden.',
  },
]

export function checkSummary(
  counts: { fix: number; look: number; expected: number } | undefined,
): { tone: 'error' | 'success'; say: string } {
  const fix = counts?.fix ?? 0
  const look = counts?.look ?? 0
  const expected = counts?.expected ?? 0
  if (fix) {
    return {
      tone: 'error',
      say: `${fix} ${fix === 1 ? 'problem must' : 'problems must'} be fixed before the files can be combined.`,
    }
  }
  const tail = [
    look ? `${look} ${look === 1 ? 'point is' : 'points are'} worth a look` : '',
    expected ? `${expected} ${expected === 1 ? 'is' : 'are'} expected for this kind of package` : '',
  ].filter(Boolean)
  return {
    tone: 'success',
    say: tail.length ? `Nothing blocks. ${tail.join('; ')}.` : 'Nothing blocks.',
  }
}

export const NOT_CHECKED = 'Not checked yet.'
export const CHECK_RUNNING = 'Checking the study’s files'
export const CHECK_NOTE =
  'A large BMDExpress project takes about half a minute the first time it is read.'

// ---------------------------------------------------------------------------
// Where the study stands
// ---------------------------------------------------------------------------

const STEP_STATUS: Record<string, 'finish' | 'process' | 'error' | 'wait'> = {
  done: 'finish',
  todo: 'process',
  blocked: 'error',
  waiting: 'wait',
  not_needed: 'wait',
}

export function stepStatus(step: Step): 'finish' | 'process' | 'error' | 'wait' {
  return STEP_STATUS[step.status] ?? 'wait'
}

const STEP_TITLES: Record<string, string> = {
  bring_in: 'Bring in files',
  check: 'Check them',
  confirm: 'Say what each one is',
  conflicts: 'Settle conflicts',
}

export function stepTitle(step: Step): string {
  return STEP_TITLES[step.step] ?? step.step
}

export const EMPTY_FILES = 'No files yet.'
export const EMPTY_FILES_EXPLAIN = 'Bring in the study’s data files to start.'

export const COVERAGE_TITLE = 'What the report would be built from'
export const COVERAGE_EXPLAIN =
  'One row per assay the files cover, with the files each would be built from.'

const COVERAGE_TONE: Record<string, 'success' | 'warning' | 'error'> = {
  ok: 'success',
  warn: 'warning',
  block: 'error',
}

export function coverageTone(level: string): 'success' | 'warning' | 'error' | 'default' {
  return COVERAGE_TONE[level] ?? 'default'
}

export const SETTLED_OUTSIDE =
  'The application does not choose between these files. Correct or remove one outside the application, then check the files again.'

export const NOT_BUILT_YET = 'This part of the page is not built yet.'
