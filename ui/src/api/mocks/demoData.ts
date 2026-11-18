import { HttpResponse, http } from 'msw'
import { API_V2 } from '../client'
import type { Dataset, KnowledgeBaseUse, ResultTables, StudyParameters, TableSources } from '../demoData'
import type { ErrorEnvelope, ExistingStudyState, RunEvent } from '../types'
import {
  DATASET_FINISHED,
  DATASET_LIVE_COMBINED,
  DATASET_LIVE_PROCESSED,
  DATASET_LIVE_VALIDATED,
  DEMO_FINISHED_RAT,
  DEMO_FINISHED_REPORT,
  DEMO_LIVE_RAT,
  DEMO_LIVE_REPORT,
  KNOWLEDGE_BASE_FINISHED,
  KNOWLEDGE_BASE_LIVE_COMBINED,
  KNOWLEDGE_BASE_LIVE_PROCESSED,
  KNOWLEDGE_BASE_LIVE_VALIDATED,
  PARAMETERS_FINISHED,
  PARAMETERS_LIVE_COMBINED,
  PARAMETERS_LIVE_PROCESSED,
  PARAMETERS_LIVE_VALIDATED,
  REFUSAL_FINISHED_INTEGRATE,
  REFUSAL_FINISHED_PROCESS,
  REFUSAL_LIVE_RUN_IN_FLIGHT,
  REFUSAL_LIVE_VALIDATED_PROCESS,
  REFUSAL_REPORT_HAS_NO_DATA,
  REFUSAL_TABLE_NOT_FOUND,
  SOURCES_FINISHED,
  SOURCES_LIVE,
  STATE_FINISHED,
  STATE_FINISHED_REPORT,
  STATE_LIVE_COMBINED,
  STATE_LIVE_PROCESSED,
  STATE_LIVE_REPORT,
  STATE_LIVE_VALIDATED,
  STREAM_INTEGRATE_OK,
  STREAM_PROCESS_LIVE,
  STREAM_PROCESS_WARM,
  TABLES_FINISHED,
  TABLES_LIVE_COMBINED,
  TABLES_LIVE_PROCESSED,
  TABLES_LIVE_VALIDATED,
} from './fixtures/demoData'
import { running } from './runs'

/**
 * The demo path's "Combined data" and "Process" pages, mocked
 * (web_routes/v2_data_routes.py). The mock world is the NIEHS-12 pair: the
 * finished rat study, which only reads, and its live copy, which the two acts
 * move from "files checked" to "combined" to "processed", as on the backend.
 * Every answer is one the backend gave (fixtures/demoData); the rules played
 * here (which act is refused when) are the BACKEND's, and no screen repeats
 * them. Any other study id is not this mock's: the request falls through.
 */

export type DemoStage = 'validated' | 'combined' | 'processed'

let stage: DemoStage = 'validated'

/** Put the live copy back to "files checked, nothing combined"; called between tests. */
export function resetDemoDataDb(): void {
  stage = 'validated'
}

/** Put the live copy at a stage (tests; the browser demo walks there through the acts). */
export function setDemoStage(next: DemoStage): void {
  stage = next
}

interface StudyAnswers {
  state: ExistingStudyState
  dataset: Dataset
  tables: ResultTables
  sources: Record<string, TableSources>
  parameters: StudyParameters
  knowledgeBase: KnowledgeBaseUse
}

const LIVE: Record<DemoStage, StudyAnswers> = {
  validated: {
    state: STATE_LIVE_VALIDATED,
    dataset: DATASET_LIVE_VALIDATED,
    tables: TABLES_LIVE_VALIDATED,
    sources: {},
    parameters: PARAMETERS_LIVE_VALIDATED,
    knowledgeBase: KNOWLEDGE_BASE_LIVE_VALIDATED,
  },
  combined: {
    state: STATE_LIVE_COMBINED,
    dataset: DATASET_LIVE_COMBINED,
    tables: TABLES_LIVE_COMBINED,
    sources: {},
    parameters: PARAMETERS_LIVE_COMBINED,
    knowledgeBase: KNOWLEDGE_BASE_LIVE_COMBINED,
  },
  processed: {
    state: STATE_LIVE_PROCESSED,
    dataset: DATASET_LIVE_PROCESSED,
    tables: TABLES_LIVE_PROCESSED,
    sources: SOURCES_LIVE,
    parameters: PARAMETERS_LIVE_PROCESSED,
    knowledgeBase: KNOWLEDGE_BASE_LIVE_PROCESSED,
  },
}

const FINISHED: StudyAnswers = {
  state: STATE_FINISHED,
  dataset: DATASET_FINISHED,
  tables: TABLES_FINISHED,
  sources: SOURCES_FINISHED,
  parameters: PARAMETERS_FINISHED,
  knowledgeBase: KNOWLEDGE_BASE_FINISHED,
}

const REPORTS: Record<string, ExistingStudyState> = {
  [DEMO_LIVE_REPORT]: STATE_LIVE_REPORT,
  [DEMO_FINISHED_REPORT]: STATE_FINISHED_REPORT,
}

function answersFor(id: string): StudyAnswers | undefined {
  if (id === DEMO_LIVE_RAT) return LIVE[stage]
  if (id === DEMO_FINISHED_RAT) return FINISHED
  return undefined
}

function envelope(body: ErrorEnvelope): Response {
  return HttpResponse.json(body, { status: body.error.status })
}

/** The refusal with this study's id in place of the one the fixture was saved for. */
function reportRefusal(id: string): Response {
  const e = REFUSAL_REPORT_HAS_NO_DATA.error
  return envelope({ error: { ...e, details: { ...e.details, id } } })
}

function withRun(state: ExistingStudyState): ExistingStudyState {
  const since = running.get(state.id)
  if (!since) return state
  return { ...state, run: { in_flight: true, started_at: since, what: 'a long act', last: null } }
}

/** An NDJSON response that sends `events` one by one, then calls `onEnd` before the last. */
function stream(events: RunEvent[], stepDelayMs: number, beforeLast: () => void): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for (const [i, ev] of events.entries()) {
          if (stepDelayMs > 0) await new Promise((r) => setTimeout(r, stepDelayMs))
          // as on the backend: the study is released, and stands where the act left it, before the last line
          if (i === events.length - 1) beforeLast()
          controller.enqueue(encoder.encode(JSON.stringify(ev) + '\n'))
        }
      } finally {
        controller.close()
      }
    },
  })
  return new HttpResponse(body, { headers: { 'Content-Type': 'application/x-ndjson' } })
}

export function createDemoDataHandlers({ stepDelayMs = 0 }: { stepDelayMs?: number } = {}) {
  const act = (id: string, legal: string, refusedBefore: ErrorEnvelope, events: () => RunEvent[], next: DemoStage) => {
    if (id === DEMO_FINISHED_RAT) return envelope(legal === 'INTEGRATE' ? REFUSAL_FINISHED_INTEGRATE : REFUSAL_FINISHED_PROCESS)
    if (REPORTS[id]) return reportRefusal(id)
    if (id !== DEMO_LIVE_RAT) return undefined
    if (running.has(id)) return envelope(REFUSAL_LIVE_RUN_IN_FLIGHT)
    if (!LIVE[stage].state.legal_actions.includes(legal)) return envelope(refusedBefore)
    running.set(id, new Date().toISOString())
    return stream(events(), stepDelayMs, () => {
      running.delete(id)
      stage = next
    })
  }

  return [
    http.get(`${API_V2}/studies/:id/state`, ({ params }) => {
      const id = String(params.id)
      const state = answersFor(id)?.state ?? REPORTS[id]
      return state ? HttpResponse.json(withRun(state)) : undefined
    }),

    http.get(`${API_V2}/studies/:id/dataset`, ({ params }) => {
      const id = String(params.id)
      if (REPORTS[id]) return reportRefusal(id)
      const a = answersFor(id)
      return a ? HttpResponse.json(a.dataset) : undefined
    }),

    http.get(`${API_V2}/studies/:id/tables`, ({ params }) => {
      const id = String(params.id)
      if (REPORTS[id]) return reportRefusal(id)
      const a = answersFor(id)
      return a ? HttpResponse.json(a.tables) : undefined
    }),

    http.get(`${API_V2}/studies/:id/tables/:key/sources`, ({ params }) => {
      const id = String(params.id)
      const key = String(params.key)
      if (REPORTS[id]) return reportRefusal(id)
      const a = answersFor(id)
      if (!a) return undefined
      const sources = a.sources[key]
      if (sources) return HttpResponse.json(sources)
      const e = REFUSAL_TABLE_NOT_FOUND.error
      return envelope({
        error: {
          ...e,
          message: `${id} has no results table ${key}`,
          say: typeof e.details?.key === 'string' ? e.say.replace(e.details.key, key) : e.say,
          details: { id, key },
        },
      })
    }),

    // Combining is legal at every stage the live copy stands at here; the phase refusal is never reached.
    http.post(`${API_V2}/studies/:id/integrate`, ({ params }) =>
      act(String(params.id), 'INTEGRATE', REFUSAL_LIVE_RUN_IN_FLIGHT, () => STREAM_INTEGRATE_OK, 'combined'),
    ),

    // Right after Combine everything is computed; on the processed study what did not change is reused.
    http.post(`${API_V2}/studies/:id/process`, ({ params }) =>
      act(String(params.id), 'PROCESS', REFUSAL_LIVE_VALIDATED_PROCESS, () => (stage === 'processed' ? STREAM_PROCESS_WARM : STREAM_PROCESS_LIVE), 'processed'),
    ),

    // Routes older than the new interface (outside /api/v2).
    http.get('/api/workflow/:id/study-parameters', ({ params }) => {
      const a = answersFor(String(params.id))
      return a ? HttpResponse.json(a.parameters) : undefined
    }),

    http.get('/api/session/:id/knowledge-base', ({ params }) => {
      const a = answersFor(String(params.id))
      return a ? HttpResponse.json(a.knowledgeBase) : undefined
    }),
  ]
}
