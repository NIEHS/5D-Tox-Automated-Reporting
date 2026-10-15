import type { ErrorEnvelope, Noop } from '../../types'

/** Refusals in the §4.2 envelope, mocked. */

export const REFUSAL_PHASE_NOT_ALLOWED: ErrorEnvelope = {
  error: {
    code: 'phase_not_allowed',
    status: 409,
    message: "StepError: action INTEGRATE is not legal in phase VALIDATION_ERRORS (legal: ['RESET', 'VALIDATE'])",
    say: 'The data cannot be combined while the files still have problems. Fix the problems with the files first.',
    fix: 'M2',
    details: { phase: 'VALIDATION_ERRORS', action: 'INTEGRATE', legal_actions: ['RESET', 'VALIDATE'] },
  },
}

export const REFUSAL_RUN_IN_FLIGHT: ErrorEnvelope = {
  error: {
    code: 'run_in_flight',
    status: 409,
    message: 'process lock held for DTXSID50469320 since 2026-10-14T09:00:00+00:00',
    say: 'This study is already being processed. Wait for that run to finish.',
    fix: 'P1',
    details: { started_at: '2026-10-14T09:00:00+00:00' },
  },
}

export const REFUSAL_SECTION_OWNED: ErrorEnvelope = {
  error: {
    code: 'section_owned',
    status: 409,
    message: 'may_machine_write(summary) is False: approved',
    say: 'The Summary has been approved, so the machine will not rewrite it. Release it first if you want a new draft.',
    fix: 'D1',
    details: { section: 'summary' },
  },
}

/** A success that did nothing (§4.2). */
export const NOOP_SUMMARY_NOT_REWRITTEN: Noop = {
  code: 'summary_unchanged',
  say: 'The Summary was not rewritten: nothing it is written from has changed.',
}

/** What a crashed server sends: not an envelope. */
export const UNEXPECTED_HTML_500 =
  '<html><head><title>500 Internal Server Error</title></head><body><h1>Internal Server Error</h1></body></html>'
