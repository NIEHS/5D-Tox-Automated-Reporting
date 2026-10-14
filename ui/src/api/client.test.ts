import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { getDryRun, getStudyState, getVocabularies, noopOf, readEvents, runProcess, sendJson } from './client'
import { ApiError, errorFromResponse, isErrorEnvelope } from './errors'
import { STATE_APPROVED_STALE_SUMMARY, STREAM_PROCESS_OK, DRY_RUN_RESET, REFUSAL_PHASE_NOT_ALLOWED, UNEXPECTED_HTML_500, toNdjson } from './mocks/fixtures'
import { createHandlers } from './mocks/handlers'
import { server } from './mocks/node'
import type { RunEvent } from './types'

async function collect(gen: AsyncIterable<RunEvent>): Promise<RunEvent[]> {
  const out: RunEvent[] = []
  for await (const e of gen) out.push(e)
  return out
}

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch))
      c.close()
    },
  })
}

describe('the typed fetch functions', () => {
  it('read the state read model', async () => {
    const s = await getStudyState('DTXSID50469320')
    expect(s.phase).toBe('APPROVED')
    expect(s.sections?.map((x) => x.key)).toEqual(STATE_APPROVED_STALE_SUMMARY.sections?.map((x) => x.key))
  })

  it('read the vocabularies and the dry run', async () => {
    const v = await getVocabularies()
    expect(Object.keys(v.vocabularies)).toContain('strain')
    expect(await getDryRun('DTXSID50469320', 'reset_pool')).toEqual(DRY_RUN_RESET)
  })

  it('turn an envelope refusal into an ApiError carrying the envelope', async () => {
    server.use(http.get('/api/v2/studies/:id/state', () => HttpResponse.json(REFUSAL_PHASE_NOT_ALLOWED, { status: 409 })))
    const err = await getStudyState('X').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    const e = err as ApiError
    expect(e.body).toEqual(REFUSAL_PHASE_NOT_ALLOWED.error)
    expect(e.code).toBe('phase_not_allowed')
    expect(e.status).toBe(409)
    expect(e.fix).toBe('M2')
    expect(e.say).toMatch(/cannot be combined/)
  })

  it('turn a body that is not an envelope into code "unexpected", keeping the status and the body', async () => {
    server.use(http.get('/api/v2/vocabularies', () => new HttpResponse(UNEXPECTED_HTML_500, { status: 500, statusText: 'Internal Server Error' })))
    const e = (await getVocabularies().catch((x: unknown) => x)) as ApiError
    expect(e).toBeInstanceOf(ApiError)
    expect(e.code).toBe('unexpected')
    expect(e.status).toBe(500)
    expect(e.say).toMatch(/does not understand/)
    expect(String(e.details.body)).toContain('Internal Server Error')
  })

  it('treat a FastAPI-style {"detail": …} body as unexpected, not as an envelope', async () => {
    server.use(http.get('/api/v2/vocabularies', () => HttpResponse.json({ detail: 'Not Found' }, { status: 404 })))
    const e = (await getVocabularies().catch((x: unknown) => x)) as ApiError
    expect(e.code).toBe('unexpected')
    expect(e.details.body).toEqual({ detail: 'Not Found' })
  })

  it('turn a 2xx answer that is not JSON into "unexpected"', async () => {
    server.use(http.get('/api/v2/vocabularies', () => new HttpResponse('<html>', { status: 200 })))
    const e = (await getVocabularies().catch((x: unknown) => x)) as ApiError
    expect(e.code).toBe('unexpected')
  })

  it('turn a network failure into code "unreachable"', async () => {
    server.use(http.get('/api/v2/vocabularies', () => HttpResponse.error()))
    const e = (await getVocabularies().catch((x: unknown) => x)) as ApiError
    expect(e).toBeInstanceOf(ApiError)
    expect(e.code).toBe('unreachable')
    expect(e.say).toMatch(/could not be reached/)
  })

  it('send JSON and surface a noop', async () => {
    server.use(
      http.post('/api/v2/studies/:id/summary', async ({ request }) => {
        const body = (await request.json()) as { mode: string }
        return HttpResponse.json({ ok: true, mode: body.mode, noop: { code: 'summary_unchanged', say: 'Nothing changed.' } })
      }),
    )
    const r = await sendJson<{ ok: boolean; mode: string }>('POST', '/api/v2/studies/X/summary', { mode: 'rules' })
    expect(r.mode).toBe('rules')
    expect(noopOf(r)).toEqual({ code: 'summary_unchanged', say: 'Nothing changed.' })
    expect(noopOf({ ok: true })).toBeNull()
  })
})

describe('the envelope check', () => {
  it('accepts only the §4.2 shape', () => {
    expect(isErrorEnvelope(REFUSAL_PHASE_NOT_ALLOWED)).toBe(true)
    expect(isErrorEnvelope({ error: 'boom' })).toBe(false)
    expect(isErrorEnvelope({ error: { code: 'x' } })).toBe(false)
    expect(isErrorEnvelope(null)).toBe(false)
  })

  it('takes the HTTP status when the envelope omits one', async () => {
    const res = new Response(JSON.stringify({ error: { code: 'c', message: 'm', say: 's' } }), { status: 422 })
    const e = await errorFromResponse(res)
    expect(e.status).toBe(422)
    expect(e.code).toBe('c')
  })
})

describe('the run event stream (NDJSON)', () => {
  it('yields one event per line whatever the chunking', async () => {
    const text = toNdjson(STREAM_PROCESS_OK)
    const chunks: string[] = []
    for (let i = 0; i < text.length; i += 7) chunks.push(text.slice(i, i + 7))
    expect(await collect(readEvents(streamOf(chunks)))).toEqual(STREAM_PROCESS_OK)
  })

  it('reads a last line with no newline, and skips blank lines', async () => {
    const events = await collect(readEvents(streamOf(['\n{"event":"step","unit":"a","status":"done","say":"A"}\n\n', '{"event":"result","ok":true,"summary":{}}'])))
    expect(events.map((e) => e.event)).toEqual(['step', 'result'])
  })

  it('rejects a line that is not JSON with an "unexpected" ApiError', async () => {
    const e = await collect(readEvents(streamOf(['{"event":"step"\n']))).catch((x: unknown) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect((e as ApiError).code).toBe('unexpected')
  })

  it('normalises an error event that does not carry an envelope', async () => {
    const [ev] = await collect(readEvents(streamOf(['{"event":"error","error":"kaboom"}\n'])))
    expect(ev).toMatchObject({ event: 'error', error: { code: 'unexpected' } })
  })

  it('streams Process from the mock; while it runs the state says so and a second run is refused', async () => {
    server.use(...createHandlers({ stepDelayMs: 20 }))
    const first = runProcess('DTXSID50469320')
    expect((await first.next()).value).toMatchObject({ event: 'step', unit: 'ntp' })
    expect((await getStudyState('DTXSID50469320')).run?.in_flight).toBe(true)
    const second = (await collect(runProcess('DTXSID50469320')).catch((x: unknown) => x)) as ApiError
    expect(second).toBeInstanceOf(ApiError)
    expect(second.code).toBe('run_in_flight')
    const rest: RunEvent[] = []
    for await (const e of { [Symbol.asyncIterator]: () => first }) rest.push(e)
    expect(rest.at(-1)).toMatchObject({ event: 'result', ok: true })
    expect((await getStudyState('DTXSID50469320')).run?.in_flight).toBe(false)
  })

  it('refuses Process before the run starts when the phase does not allow it', async () => {
    const e = (await collect(runProcess('DTXSID1021952')).catch((x: unknown) => x)) as ApiError
    expect(e).toBeInstanceOf(ApiError)
    expect(e.code).toBe('phase_not_allowed')
    expect(e.fix).toBe('M3')
  })
})
