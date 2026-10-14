import type { ReadinessItem, SectionState, StudyState } from '../../types'

/**
 * GET /api/v2/studies/{id}/state, mocked (MODULES.md §4.1).
 *
 * The identities are the real chemicals' (from sessions/<id>/identity.json);
 * the phases are chosen to exercise the screens. The backend will publish real
 * examples at docs/ui-redesign/contracts/state.*.json; reconcile with them here,
 * and only here.
 */

// --- PFHxSAm's real section keys -------------------------------------------

type SectionSeed = Pick<SectionState, 'key' | 'kind'> & Partial<SectionState>

function section(seed: SectionSeed): SectionState {
  return {
    approvable: true,
    approved: false,
    stale: false,
    regenerated: null,
    wording_review: [],
    source: 'generated',
    version: 1,
    version_status: null,
    machine_may_write: true,
    blocked_by: [],
    ...seed,
  }
}

const APICAL = [
  'bm2_body-weight',
  'bm2_clinical-chemistry',
  'bm2_clinical-observations',
  'bm2_hematology',
  'bm2_hormones',
  'bm2_organ-weight',
  'bm2_tissue-concentration',
] as const

const GENOMICS = [
  'genomics_liver_male',
  'genomics_liver_female',
  'genomics_kidney_male',
  'genomics_kidney_female',
] as const

export const PFHXSAM_SECTION_KEYS = [
  'background',
  'summary',
  'methods',
  'bmd_summary',
  ...APICAL,
  ...GENOMICS,
] as const

/** An approved study whose Summary went stale after a factual change. */
const approvedSections: SectionState[] = [
  section({ key: 'background', kind: 'llm', approved: true, version: 2, version_status: 'blessed', machine_may_write: false, maturity: 'working_draft' }),
  section({
    key: 'summary',
    kind: 'llm',
    approved: true,
    stale: true,
    version: 2,
    version_status: 'needs-re-bless',
    machine_may_write: false,
    maturity: 'working_draft',
  }),
  section({ key: 'methods', kind: 'llm', approved: true, version: 1, version_status: 'blessed', machine_may_write: false }),
  section({
    key: 'bmd_summary',
    kind: 'llm',
    regenerated: { reason: 'The apical BMD results changed when the study was processed again.', at: '2026-10-12T11:52:40+00:00' },
    version: 3,
    version_status: 'needs-re-bless',
  }),
  section({ key: 'bm2_body-weight', kind: 'programmatic', approved: true, version: 1, version_status: 'blessed', machine_may_write: false }),
  section({ key: 'bm2_clinical-chemistry', kind: 'programmatic', approved: true, version: 1, version_status: 'blessed', machine_may_write: false }),
  section({ key: 'bm2_clinical-observations', kind: 'programmatic' }),
  section({ key: 'bm2_hematology', kind: 'programmatic', approved: true, version: 1, version_status: 'blessed', machine_may_write: false }),
  section({ key: 'bm2_hormones', kind: 'programmatic' }),
  section({ key: 'bm2_organ-weight', kind: 'programmatic', approved: true, version: 1, version_status: 'blessed', machine_may_write: false }),
  section({ key: 'bm2_tissue-concentration', kind: 'programmatic' }),
  section({ key: 'genomics_liver_male', kind: 'llm', approved: true, version: 1, version_status: 'blessed', machine_may_write: false }),
  section({ key: 'genomics_liver_female', kind: 'llm' }),
  section({ key: 'genomics_kidney_male', kind: 'llm' }),
  section({ key: 'genomics_kidney_female', kind: 'llm', wording_review: ['"significantly" is used without a statistical test behind it.'] }),
]

const unapprovedItems: ReadinessItem[] = approvedSections
  .filter((s) => !s.approved)
  .map((s) => ({
    id: 'section.unapproved',
    level: 'block',
    section: s.key,
    say: `The section "${s.key}" has not been approved.`,
    fix: 'D1',
  }))

// --- the phases ---------------------------------------------------------------

/** A study just created: no files. */
export const STATE_EMPTY: StudyState = {
  id: 'DTXSID5032498',
  exists: true,
  phase: 'EMPTY',
  legal_actions: [],
  identity: { dtxsid: 'DTXSID5032498' },
  pins: { method: null, definition: null },
  processed: false,
  run: { in_flight: false, started_at: null, last: null },
  sections: [],
  readiness: {
    data_approval: {
      ready: false,
      items: [{ id: 'files.none', level: 'block', say: 'No data files have been brought in yet.', fix: 'M2' }],
    },
    publish: {
      ready: false,
      items: [{ id: 'phase.not_processed', level: 'block', say: 'The study has not been processed yet.', fix: 'P1' }],
    },
  },
}

/** Files brought in; checking them found problems. */
export const STATE_VALIDATION_ERRORS: StudyState = {
  id: 'DTXSID1021952',
  exists: true,
  phase: 'VALIDATION_ERRORS',
  legal_actions: ['RESET', 'VALIDATE'],
  identity: { dtxsid: 'DTXSID1021952', name: 'Triphenyl phosphate', casrn: '115-86-6' },
  pins: { method: null, definition: null },
  processed: false,
  run: { in_flight: false, started_at: null, last: null },
  sections: [],
  readiness: {
    data_approval: {
      ready: false,
      items: [
        {
          id: 'validation.conflict',
          level: 'block',
          say: 'Two files both give the Clinical Chemistry data for the same animals. Choose which one is right.',
          fix: 'M2',
        },
        {
          id: 'validation.missing_bm2',
          level: 'block',
          say: 'Hematology has study data but no BMDExpress (.bm2) file.',
          fix: 'M2',
        },
      ],
    },
    publish: {
      ready: false,
      items: [{ id: 'phase.not_processed', level: 'block', say: 'The study has not been processed yet.', fix: 'P1' }],
    },
  },
}

/** Data combined; the method was pinned by default, the design is the fallback. */
export const STATE_INTEGRATED: StudyState = {
  id: 'DTXSID1022477',
  exists: true,
  phase: 'INTEGRATED',
  legal_actions: ['APPROVE', 'REPROCESS', 'RESET', 'VALIDATE'],
  identity: { dtxsid: 'DTXSID1022477', name: '2,3-Benzofluorene', casrn: '243-17-4' },
  pins: {
    method: { name: 'ntp-5day-2025', mode: 'track', pinned_by: 'default', deviations: [], mismatches: [] },
    definition: { name: 'era/2026', mode: 'track', drift: null, source: 'era' },
  },
  processed: false,
  run: { in_flight: false, started_at: null, last: null },
  sections: [],
  readiness: {
    data_approval: {
      ready: false,
      items: [
        {
          id: 'design.fallback',
          level: 'warn',
          say: 'Nobody has stated the study design; the standard design (Sprague Dawley rats, gavage, corn oil, 5 days) is assumed.',
          fix: 'M4',
        },
        {
          id: 'pins.method_default',
          level: 'warn',
          say: 'The analysis method was chosen by default, not by a person.',
          fix: 'M5',
        },
      ],
    },
    publish: {
      ready: false,
      items: [{ id: 'phase.not_processed', level: 'block', say: 'The study has not been processed yet.', fix: 'P1' }],
    },
  },
}

/** PFHxSAm: processed and approved; the Summary went stale. */
export const STATE_APPROVED_STALE_SUMMARY: StudyState = {
  id: 'DTXSID50469320',
  exists: true,
  phase: 'APPROVED',
  legal_actions: ['REPROCESS', 'RESET'],
  identity: {
    dtxsid: 'DTXSID50469320',
    name: 'Perfluorohexanesulfonamide',
    casrn: '41997-13-1',
    short_name: 'PFHxSAm',
  },
  pins: {
    method: { name: 'ntp-5day-2021', mode: 'fixed', pinned_by: 'person', deviations: [], mismatches: [] },
    definition: { name: 'studies/DTXSID50469320/document', mode: 'track', drift: null, source: 'study' },
  },
  processed: true,
  run: {
    in_flight: false,
    started_at: null,
    last: { ok: true, finished_at: '2026-10-12T11:52:41+00:00', content_errors: [] },
  },
  sections: approvedSections,
  readiness: {
    data_approval: { ready: true, items: [] },
    publish: {
      ready: false,
      items: [
        {
          id: 'section.stale',
          level: 'block',
          section: 'summary',
          say: 'The Summary was approved, but the study design it was written from has changed since.',
          fix: 'D1',
        },
        ...unapprovedItems,
        {
          id: 'pending.report_number',
          level: 'block',
          say: 'The report number is still "[report number pending]".',
          fix: 'D5',
        },
      ],
    },
  },
}

/** PFHxSAm while Process runs (another tab, or before a reload). */
export const STATE_RUNNING: StudyState = {
  ...STATE_APPROVED_STALE_SUMMARY,
  run: {
    in_flight: true,
    started_at: '2026-10-14T09:00:00+00:00',
    last: STATE_APPROVED_STALE_SUMMARY.run?.last ?? null,
  },
}

/** 1,4-Dichlorobenzene: one report over a rat and a mouse study (NIEHS-13). */
export const STATE_TWO_STUDIES: StudyState = {
  id: 'DTXSID1020431',
  exists: true,
  phase: 'APPROVED',
  legal_actions: ['REPROCESS', 'RESET'],
  identity: { dtxsid: 'DTXSID1020431', name: '1,4-Dichlorobenzene', casrn: '106-46-7', short_name: '1,4-DCB' },
  pins: {
    method: { name: 'ntp-5day-2025', mode: 'fixed', pinned_by: 'person', deviations: [], mismatches: [] },
    definition: { name: 'studies/DTXSID1020431/document', mode: 'fixed', drift: null, source: 'study' },
  },
  processed: true,
  run: { in_flight: false, started_at: null, last: { ok: true, finished_at: '2026-10-11T16:20:03+00:00', content_errors: [] } },
  members: [
    { role: 'rat', id: 'DTXSID1020431_rat', phase: 'APPROVED', processed: true },
    { role: 'mouse', id: 'DTXSID1020431_mouse', phase: 'INTEGRATED', processed: false },
  ],
  sections: [
    section({ key: 'background', kind: 'llm', approved: true, version: 1, version_status: 'blessed', machine_may_write: false }),
    section({ key: 'summary', kind: 'llm' }),
    section({ key: 'methods', kind: 'llm' }),
  ],
  readiness: {
    data_approval: { ready: true, items: [] },
    publish: {
      ready: false,
      items: [
        {
          id: 'member.not_processed',
          level: 'block',
          say: 'The mouse study (DTXSID1020431_mouse) has not been processed.',
          fix: 'P1',
        },
        { id: 'section.unapproved', level: 'block', section: 'summary', say: 'The section "summary" has not been approved.', fix: 'D1' },
        { id: 'section.unapproved', level: 'block', section: 'methods', say: 'The section "methods" has not been approved.', fix: 'D1' },
      ],
    },
  },
}

/** A study id with no session behind it. */
export function stateNotFound(id: string): StudyState {
  return { id, exists: false, phase: 'EMPTY', legal_actions: [] }
}

/** Every fixture above, by study id: what the mock server serves. */
export const STATES_BY_ID: Record<string, StudyState> = Object.fromEntries(
  [STATE_EMPTY, STATE_VALIDATION_ERRORS, STATE_INTEGRATED, STATE_APPROVED_STALE_SUMMARY, STATE_TWO_STUDIES].map((s) => [s.id, s]),
)
