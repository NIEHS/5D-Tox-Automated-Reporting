import { ApiError, SAY_BROKEN_STREAM, SAY_UNREACHABLE, errorFromBody, errorFromResponse, unexpectedError } from './errors'
import type { DryRun, Noop, RunEvent, StudyState, Vocabularies, WithNoop } from './types'

/**
 * The typed API client (MODULES.md §4.6). Owned by the orchestrator: a module
 * asks for its endpoints in its report rather than editing this file.
 *
 * Every function either resolves with the typed body or rejects with an
 * ApiError (see errors.ts). No other kind of rejection leaves this module.
 */

export const API_V2 = '/api/v2'

const enc = encodeURIComponent

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers: { Accept: 'application/json', ...(init.headers ?? {}) },
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError({
      code: 'unreachable',
      status: 0,
      message: err instanceof Error ? err.message : String(err),
      say: SAY_UNREACHABLE,
      fix: null,
      details: {},
    })
  }
  if (!res.ok) throw await errorFromResponse(res)
  return res
}

async function readJson<T>(res: Response): Promise<T> {
  const text = await res.text()
  try {
    return JSON.parse(text) as T
  } catch {
    throw unexpectedError(res.status, 'The answer was not JSON.', { body: text.slice(0, 4000) })
  }
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return readJson<T>(await send(path, { method: 'GET', signal }))
}

export async function sendJson<T>(
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<WithNoop<T>> {
  const init: RequestInit = { method, signal }
  if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { 'Content-Type': 'application/json' }
  }
  return readJson<WithNoop<T>>(await send(path, init))
}

/** The "success that did nothing" carried by a response, if any (§4.2). */
export function noopOf(body: unknown): Noop | null {
  if (typeof body !== 'object' || body === null) return null
  const n = (body as { noop?: unknown }).noop
  if (typeof n !== 'object' || n === null) return null
  const { code, say } = n as Record<string, unknown>
  return typeof code === 'string' && typeof say === 'string' ? { code, say } : null
}

// ---------------------------------------------------------------------------
// NDJSON event streams (§4.4)
// ---------------------------------------------------------------------------

function parseEvent(line: string): RunEvent {
  let x: unknown
  try {
    x = JSON.parse(line)
  } catch {
    throw unexpectedError(200, 'A line of the run stream was not JSON.', { line: line.slice(0, 2000) })
  }
  const ev = x as Partial<RunEvent> & Record<string, unknown>
  if (ev.event === 'step' && typeof ev.unit === 'string' && typeof ev.status === 'string') return ev as RunEvent
  if (ev.event === 'result' && typeof ev.ok === 'boolean') return { ...ev, summary: ev.summary ?? {} } as RunEvent
  if (ev.event === 'error') return { event: 'error', error: errorFromBody(ev.error).body }
  throw unexpectedError(200, 'A line of the run stream had an unknown shape.', { line: line.slice(0, 2000) })
}

/** Read an NDJSON body, one event per line, whatever the chunking. */
export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<RunEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
      let nl = buffer.indexOf('\n')
      while (nl >= 0) {
        const line = buffer.slice(0, nl).trim()
        buffer = buffer.slice(nl + 1)
        if (line) yield parseEvent(line)
        nl = buffer.indexOf('\n')
      }
      if (done) break
    }
    const rest = buffer.trim()
    if (rest) yield parseEvent(rest)
  } finally {
    reader.releaseLock()
  }
}

/**
 * Start a run and yield its events. A refusal before the run starts (a
 * non-2xx answer) rejects with an ApiError like any other call.
 */
export async function* streamRun(path: string, body?: unknown): AsyncGenerator<RunEvent> {
  const init: RequestInit = { method: 'POST', headers: { Accept: 'application/x-ndjson' } }
  if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { ...init.headers, 'Content-Type': 'application/json' }
  }
  const res = await send(path, init)
  if (!res.body) throw unexpectedError(res.status, 'The run answered with no body.', {})
  yield* readEvents(res.body)
}

export { SAY_BROKEN_STREAM }

// ---------------------------------------------------------------------------
// The shared endpoints (MODULES.md §4)
// ---------------------------------------------------------------------------

export const paths = {
  studyState: (id: string) => `${API_V2}/studies/${enc(id)}/state`,
  vocabularies: () => `${API_V2}/vocabularies`,
  /** PROPOSED: the dry run of an act (§4.3); a side-effect-free read. */
  dryRun: (id: string, act: string) => `${API_V2}/studies/${enc(id)}/dry-run/${enc(act)}`,
  /** PROPOSED: the one guarded Process endpoint, streaming §4.4 events (C5). */
  process: (id: string) => `${API_V2}/studies/${enc(id)}/process`,
}

export function getStudyState(id: string, signal?: AbortSignal): Promise<StudyState> {
  return getJson<StudyState>(paths.studyState(id), signal)
}

export function getVocabularies(signal?: AbortSignal): Promise<Vocabularies> {
  return getJson<Vocabularies>(paths.vocabularies(), signal)
}

export function getDryRun(id: string, act: string, signal?: AbortSignal): Promise<DryRun> {
  return getJson<DryRun>(paths.dryRun(id, act), signal)
}

export function runProcess(id: string): AsyncGenerator<RunEvent> {
  return streamRun(paths.process(id))
}
