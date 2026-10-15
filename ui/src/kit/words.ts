import type { Action, ModuleId, Phase } from '../api/types'

/**
 * Plain words for the values the backend serves. These translate; they do
 * not decide anything: which phase a study is in and which actions are legal
 * always come from the state.
 */

export interface PhaseWords {
  label: string
  explain: string
  /** where the work starts when no action is legal yet (EMPTY: bringing in files is not an action) */
  start?: { module: ModuleId; label: string }
}

export const PHASE_WORDS: Record<Phase, PhaseWords> = {
  EMPTY: {
    label: 'No files yet',
    explain: 'No data files have been brought in for this study.',
    start: { module: 'M2', label: "Bring in the study's files" },
  },
  UPLOADED: { label: 'Files not yet checked', explain: 'Files have been brought in but not checked.' },
  VALIDATION_ERRORS: { label: 'The files have problems', explain: 'Checking the files found problems that must be fixed before the data can be combined.' },
  VALIDATED: { label: 'Files checked', explain: 'The files have been checked; the data are not yet combined.' },
  INTEGRATED: { label: 'Data combined', explain: "The files' data have been combined into one dataset." },
  APPROVED: { label: 'Data reviewed', explain: 'The combined data have been reviewed and every animal accounted for.' },
}

export function phaseWords(phase: string): PhaseWords & { known: boolean } {
  const w = (PHASE_WORDS as Record<string, PhaseWords | undefined>)[phase]
  if (w) return { ...w, known: true }
  return {
    label: 'Unknown stage',
    explain: `The application reported a stage this page does not know ("${phase}"). Nothing can be offered until it is understood.`,
    known: false,
  }
}

export interface ActionWords {
  label: string
  /** the module where a person does it */
  module: ModuleId
  /** it removes or undoes work */
  destructive: boolean
}

export const ACTION_WORDS: Record<Action, ActionWords> = {
  VALIDATE: { label: 'Check the files', module: 'M2', destructive: false },
  INTEGRATE: { label: 'Combine the data', module: 'M3', destructive: false },
  APPROVE: { label: 'Review the data', module: 'M6', destructive: false },
  REPROCESS: { label: 'Process the study', module: 'P1', destructive: false },
  CLEAR_FILES: { label: 'Remove all files', module: 'M2', destructive: true },
  RESET: { label: 'Start over', module: 'M2', destructive: true },
}

/** The workflow's own order, for listing the steps. */
export const ACTION_ORDER: readonly Action[] = ['VALIDATE', 'INTEGRATE', 'APPROVE', 'REPROCESS', 'CLEAR_FILES', 'RESET']
