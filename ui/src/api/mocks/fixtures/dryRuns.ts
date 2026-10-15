import type { DryRun } from '../../types'

/** The confirm/dry-run shape (§4.3), mocked, one per strength. */

/** Irreversible: the person types the study id. */
export const DRY_RUN_RESET: DryRun = {
  act: 'reset_pool',
  strength: 'irreversible',
  deletes: [
    { what: 'integrated.json', say: 'the combined dataset' },
    { what: 'validation_report.json', say: 'the result of checking the files' },
    { what: 'bm2_*.json (7 files)', say: 'the apical result sections, including 4 approved ones' },
    { what: '_cache_*.json (12 files)', say: 'the stored results of processing' },
  ],
  keeps: [{ what: 'files/', say: 'the data files you brought in' }, { what: 'history/', say: 'the past versions of every section' }],
  approvals_lost: ['bm2_body-weight', 'bm2_clinical-chemistry', 'bm2_hematology', 'bm2_organ-weight'],
  cost: { say: 'checking the files again, combining the data, and a full Process: about 5 minutes' },
  reason_required: false,
}

/** Costly: a dialog listing the consequences. */
export const DRY_RUN_CLEAR_FILES: DryRun = {
  act: 'clear_files',
  strength: 'costly',
  deletes: [{ what: 'files/ (16 files)', say: 'every data file brought in for this study' }],
  keeps: [{ what: 'identity.json', say: "the chemical's name and identifiers" }],
  approvals_lost: [],
  cost: { say: 'bringing the files in again' },
  reason_required: false,
}

/** Reversible, with a reason: releasing an approved section. */
export const DRY_RUN_RELEASE_SECTION: DryRun = {
  act: 'release_section',
  strength: 'reversible',
  deletes: [],
  keeps: [{ what: 'summary.json', say: 'the approved text, kept in its history' }],
  approvals_lost: ['summary'],
  cost: null,
  reason_required: true,
}

/** Reversible, no reason: approving a section. */
export const DRY_RUN_ACCEPT_SECTION: DryRun = {
  act: 'accept_section',
  strength: 'reversible',
  deletes: [],
  keeps: [],
  approvals_lost: [],
  cost: null,
  reason_required: false,
}

export const DRY_RUNS_BY_ACT: Record<string, DryRun> = Object.fromEntries(
  [DRY_RUN_RESET, DRY_RUN_CLEAR_FILES, DRY_RUN_RELEASE_SECTION, DRY_RUN_ACCEPT_SECTION].map((d) => [d.act, d]),
)
