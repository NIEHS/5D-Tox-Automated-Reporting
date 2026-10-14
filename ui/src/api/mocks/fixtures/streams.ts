import type { RunEvent } from '../../types'

/**
 * Run event streams (§4.4), mocked. The units are Process's cache units
 * (HANDOFF §4.6) for PFHxSAm.
 */

export const STREAM_PROCESS_OK: RunEvent[] = [
  { event: 'step', unit: 'ntp', status: 'computing', say: 'Apical statistics' },
  { event: 'step', unit: 'ntp', status: 'done', say: 'Apical statistics', ms: 4200 },
  { event: 'step', unit: 'bmds', status: 'reused', say: 'Apical BMD modelling', ms: 15 },
  { event: 'step', unit: 'genomics', status: 'computing', say: 'Gene expression BMDs' },
  { event: 'step', unit: 'genomics', status: 'done', say: 'Gene expression BMDs', ms: 21800 },
  { event: 'step', unit: 'charts', status: 'reused', say: 'Charts', ms: 9 },
  { event: 'step', unit: 'methods', status: 'computing', say: 'Methods text' },
  { event: 'step', unit: 'methods', status: 'done', say: 'Methods text', ms: 12400 },
  { event: 'step', unit: 'interpretation_liver_male', status: 'computing', say: 'Interpretation: liver, male' },
  { event: 'step', unit: 'interpretation_liver_male', status: 'done', say: 'Interpretation: liver, male', ms: 9100 },
  { event: 'step', unit: 'sections', status: 'computing', say: 'Result sections' },
  { event: 'step', unit: 'sections', status: 'done', say: 'Result sections', ms: 2100 },
  {
    event: 'result',
    ok: true,
    summary: { recomputed: ['ntp', 'genomics', 'methods', 'interpretation_liver_male', 'sections'], reused: ['bmds', 'charts'], approvals_affected: [] },
  },
]

export const STREAM_PROCESS_FAILED: RunEvent[] = [
  { event: 'step', unit: 'ntp', status: 'computing', say: 'Apical statistics' },
  { event: 'step', unit: 'ntp', status: 'done', say: 'Apical statistics', ms: 4100 },
  { event: 'step', unit: 'methods', status: 'computing', say: 'Methods text' },
  { event: 'step', unit: 'methods', status: 'failed', say: 'Methods text', ms: 30000 },
  {
    event: 'error',
    error: {
      code: 'llm_failed',
      status: 502,
      message: 'litellm.Timeout: request to model gateway timed out after 30s',
      say: 'The language model did not answer while writing the Methods text. Nothing approved was changed. Try processing again later.',
      fix: 'P1',
      details: { unit: 'methods' },
    },
  },
]

/** A stream that stops without a result or an error. */
export const STREAM_TRUNCATED: RunEvent[] = [
  { event: 'step', unit: 'ntp', status: 'computing', say: 'Apical statistics' },
]

export function toNdjson(events: RunEvent[]): string {
  return events.map((e) => JSON.stringify(e)).join('\n') + '\n'
}
