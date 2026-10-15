import { HttpResponse, delay, http } from 'msw'
import { API_V2 } from '../client'
import type { ErrorEnvelope, ExistingStudyState, RunEvent } from '../types'
import {
  DRY_RUNS_BY_ACT,
  REFUSAL_INVALID_STUDY_ID,
  REFUSAL_PROCESS_NOT_ALLOWED,
  REFUSAL_RUN_IN_FLIGHT,
  STATES_BY_ID,
  STREAM_PROCESS_OK,
  VOCABULARIES,
  stateNotFound,
} from './fixtures'
import { createM1Handlers, resetM1Db } from './m1'
import { running } from './runs'

/** The backend's session-id gate (common.dtxsid.DTXSID_RE). */
const SESSION_ID = /^DTXSID[A-Za-z0-9_-]{1,64}$/

/**
 * The MSW handlers for the shared contracts (MODULES.md §4). A module's own
 * endpoints are added here by the orchestrator, from the module's contract.
 *
 * The mock keeps one piece of memory: which studies are being processed, so
 * that a reload during a run shows the "already running" state.
 */

export interface MockOptions {
  /** pause between streamed events; 0 in tests */
  stepDelayMs?: number
  /** how long the chemical lookup takes (it takes seconds against PubChem); 0 in tests */
  lookupDelayMs?: number
}

/** Forget every mock run and every change made to the mock studies; called between tests. */
export function resetMockDb(): void {
  running.clear()
  resetM1Db()
}

export function envelope(body: ErrorEnvelope): Response {
  return HttpResponse.json(body, { status: body.error.status })
}

/** While a mock run is going, the state says so (the PROPOSED `run` of C5). */
function withRun(state: ExistingStudyState): ExistingStudyState {
  const since = running.get(state.id)
  if (!since) return state
  return { ...state, run: { in_flight: true, started_at: since, last: state.run?.last ?? null } }
}

/** An NDJSON response that sends `events` one by one. */
export function ndjsonResponse(events: RunEvent[], stepDelayMs = 0, onEnd?: () => void): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for (const ev of events) {
          if (stepDelayMs > 0) await delay(stepDelayMs)
          controller.enqueue(encoder.encode(JSON.stringify(ev) + '\n'))
        }
      } finally {
        onEnd?.()
        controller.close()
      }
    },
  })
  return new HttpResponse(stream, { headers: { 'Content-Type': 'application/x-ndjson' } })
}

export function createHandlers({ stepDelayMs = 0, lookupDelayMs = 0 }: MockOptions = {}) {
  return [
    // M1 Studies (docs/ui-redesign/modules/m1/contract.md); first, because it also
    // answers the state of the sessions it creates, deletes or adds.
    ...createM1Handlers({ lookupDelayMs }),

    http.get(`${API_V2}/studies/:id/state`, ({ params }) => {
      const id = String(params.id)
      if (!SESSION_ID.test(id)) {
        return envelope({ error: { ...REFUSAL_INVALID_STUDY_ID.error, message: `invalid session id '${id}'` } })
      }
      const state = STATES_BY_ID[id]
      return HttpResponse.json(state ? withRun(state) : stateNotFound(id))
    }),

    http.get(`${API_V2}/vocabularies`, () => HttpResponse.json(VOCABULARIES)),

    // PROPOSED (C8): no such route on the backend yet. Kept for <ConfirmAct>.
    http.get(`${API_V2}/studies/:id/dry-run/:act`, ({ params }) => {
      const dry = DRY_RUNS_BY_ACT[String(params.act)]
      if (dry) return HttpResponse.json(dry)
      return envelope({
        error: {
          code: 'unknown_act',
          status: 404,
          message: `no dry run for act ${String(params.act)}`,
          say: 'The application cannot say in advance what this would do.',
          fix: null,
          details: { act: String(params.act) },
        },
      })
    }),

    // PROPOSED (C5): no such route on the backend yet. Kept for <Wait>.
    http.post(`${API_V2}/studies/:id/process`, ({ params }) => {
      const id = String(params.id)
      const state = STATES_BY_ID[id]
      if (!state) {
        return envelope({
          error: { code: 'no_such_study', status: 404, message: `no session ${id}`, say: 'There is no study with this id.', fix: 'M1', details: {} },
        })
      }
      if (running.has(id)) return envelope(REFUSAL_RUN_IN_FLIGHT)
      if (!state.legal_actions.includes('PROCESS')) {
        // The backend's own refusal for a study that cannot be processed yet (C1).
        if (id === 'DTXSID1021952') return envelope(REFUSAL_PROCESS_NOT_ALLOWED)
        return envelope({
          error: {
            ...REFUSAL_PROCESS_NOT_ALLOWED.error,
            message: `PROCESS refused for ${id}: the study is in phase ${state.phase}`,
            details: { action: 'PROCESS', phase: state.phase, legal_actions: state.legal_actions },
          },
        })
      }
      running.set(id, new Date().toISOString())
      return ndjsonResponse(STREAM_PROCESS_OK, stepDelayMs, () => running.delete(id))
    }),

    // Anything else under /api/v2 is not in the contract (yet).
    http.all(`${API_V2}/*`, ({ request }) =>
      envelope({
        error: {
          code: 'no_such_endpoint',
          status: 404,
          message: `${request.method} ${new URL(request.url).pathname} is not mocked`,
          say: 'This part of the application is not available yet.',
          fix: null,
          details: {},
        },
      }),
    ),
  ]
}
