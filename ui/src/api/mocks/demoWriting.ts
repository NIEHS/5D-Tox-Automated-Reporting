import { HttpResponse, http } from 'msw'
import { API_V2 } from '../client'
import type { PartDetail } from '../demoWriting'
import type { ErrorEnvelope, ExistingStudyState, RunEvent } from '../types'
import {
  DEMO_FINISHED_RAT,
  DEMO_PARTS,
  DEMO_REFERENCES,
  DEMO_STATES,
  DEMO_WRITING,
  REFUSAL_BACKGROUND_IS_THE_REPORTS,
  REFUSAL_DEMO_REFERENCE,
  REFUSAL_WRITING_PART_NOT_FOUND,
  STREAM_BACKGROUND_OK,
  STREAM_SUMMARY_OK,
} from './fixtures/demo-writing'
import { running } from './runs'

/**
 * The Written sections page, mocked (web_routes/v2_writing_routes.py): the
 * backend's own answers for the finished NIEHS-12 report and its live copy.
 * The rules played here (no act on the finished side; the Background is the
 * report's) are the BACKEND's; no screen repeats them.
 *
 * Mock-only: a part of a study whose answer was not saved is served from the
 * finished rat study's part of the same key, under the asked study's id.
 * Writing changes nothing in the mock: the page reads the same answers again.
 */

function envelope(body: ErrorEnvelope): Response {
  return HttpResponse.json(body, { status: body.error.status })
}

function ndjson(events: RunEvent[], stepDelayMs: number, onEnd: () => void): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      try {
        for (const ev of events) {
          if (stepDelayMs > 0) await new Promise((r) => setTimeout(r, stepDelayMs))
          controller.enqueue(encoder.encode(JSON.stringify(ev) + '\n'))
        }
      } finally {
        onEnd()
        controller.close()
      }
    },
  })
  return new HttpResponse(stream, { headers: { 'Content-Type': 'application/x-ndjson' } })
}

function withRun(state: ExistingStudyState): ExistingStudyState {
  const since = running.get(state.id)
  if (!since) return state
  return { ...state, run: { ...(state.run ?? { last: null }), in_flight: true, started_at: since } }
}

function partOf(id: string, part: string): PartDetail | undefined {
  const own = DEMO_PARTS[`${id}/${part}`]
  if (own) return own
  const like = DEMO_PARTS[`${DEMO_FINISHED_RAT}/${part}`]
  const state = DEMO_STATES[id]
  return like && state && state.kind === 'member' ? { ...like, study: id } : undefined
}

export function createDemoWritingHandlers({ stepDelayMs = 0 }: { stepDelayMs?: number } = {}) {
  /** A long act on a session of the pair: refused where the backend refuses it, else its stream. */
  const act = (id: string, act: 'background' | 'summary', events: RunEvent[]) => {
    const state = DEMO_STATES[id]
    if (!state) return undefined
    if (state.demo?.role === 'finished') {
      return envelope({
        error: { ...REFUSAL_DEMO_REFERENCE.error, details: { id, counterpart: state.demo.counterpart } },
      })
    }
    if (act === 'background' && state.kind === 'member') return envelope(REFUSAL_BACKGROUND_IS_THE_REPORTS)
    running.set(id, new Date().toISOString())
    return ndjson(events, stepDelayMs, () => running.delete(id))
  }

  return [
    // The state of the pair's sessions; any other id is answered by the shared handler.
    http.get(`${API_V2}/studies/:id/state`, ({ params }) => {
      const state = DEMO_STATES[String(params.id)]
      return state ? HttpResponse.json(withRun(state)) : undefined
    }),

    http.get(`${API_V2}/studies/:id/writing`, ({ params }) => {
      const overview = DEMO_WRITING[String(params.id)]
      return overview ? HttpResponse.json(overview) : undefined
    }),

    http.get(`${API_V2}/studies/:id/writing/:part`, ({ params }) => {
      const id = String(params.id)
      if (!DEMO_STATES[id]) return undefined
      const part = partOf(id, String(params.part))
      if (part) return HttpResponse.json(part)
      return envelope({
        error: { ...REFUSAL_WRITING_PART_NOT_FOUND.error, details: { id, part: String(params.part) } },
      })
    }),

    http.get(`${API_V2}/studies/:id/references`, ({ params }) => {
      const refs = DEMO_REFERENCES[String(params.id)]
      return refs ? HttpResponse.json(refs) : undefined
    }),

    http.post(`${API_V2}/studies/:id/writing/background`, ({ params }) =>
      act(String(params.id), 'background', STREAM_BACKGROUND_OK),
    ),

    http.post(`${API_V2}/studies/:id/writing/summary`, ({ params }) =>
      act(String(params.id), 'summary', STREAM_SUMMARY_OK),
    ),

    http.post(`${API_V2}/studies/:id/writing/summary/runs/:run/use`, ({ params }) => {
      const state = DEMO_STATES[String(params.id)]
      if (!state) return undefined
      if (state.demo?.role === 'finished') return envelope(REFUSAL_DEMO_REFERENCE)
      return HttpResponse.json({ ok: true, version: 2, outcome: 'written' })
    }),
  ]
}
