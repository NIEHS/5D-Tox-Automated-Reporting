import type { ErrorBody, ErrorEnvelope, ModuleId } from './types'

/**
 * Every failed call becomes an ApiError carrying the §4.2 envelope's body.
 * A body that is not an envelope becomes code "unexpected"; a server that
 * cannot be reached becomes code "unreachable". Screens render it with
 * <Refusal>, never by reading `message`.
 */
export class ApiError extends Error {
  readonly body: ErrorBody

  constructor(body: ErrorBody) {
    super(body.message || body.say)
    this.name = 'ApiError'
    this.body = body
  }

  get code(): string {
    return this.body.code
  }
  get status(): number {
    return this.body.status
  }
  get say(): string {
    return this.body.say
  }
  get fix(): ModuleId | null {
    return this.body.fix ?? null
  }
  get details(): Record<string, unknown> {
    return this.body.details ?? {}
  }
}

export const SAY_UNEXPECTED =
  'The application answered in a way this screen does not understand. Nothing was changed by this screen. Show the details to whoever looks after the application.'

export const SAY_UNREACHABLE =
  "The application's server could not be reached. Check that it is running, then try again."

export const SAY_BROKEN_STREAM =
  'The run stopped without saying whether it finished. Reload the page to see what the study looks like now.'

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x)
}

/** True when `x` has the §4.2 envelope's shape. */
export function isErrorEnvelope(x: unknown): x is ErrorEnvelope {
  if (!isRecord(x) || !isRecord(x.error)) return false
  const e = x.error
  return typeof e.code === 'string' && typeof e.say === 'string' && typeof e.message === 'string'
}

export function unexpectedError(status: number, message: string, details: Record<string, unknown> = {}): ApiError {
  return new ApiError({ code: 'unexpected', status, message, say: SAY_UNEXPECTED, fix: null, details })
}

/** An envelope body found inside an event stream or elsewhere. */
export function errorFromBody(body: unknown, status = 0): ApiError {
  if (isRecord(body) && isErrorEnvelope({ error: body })) {
    const e = body as unknown as ErrorBody
    return new ApiError({ ...e, status: typeof e.status === 'number' ? e.status : status })
  }
  return unexpectedError(status, 'An error without the expected shape.', { body })
}

/** Turn a non-2xx response into an ApiError. Never throws anything else. */
export async function errorFromResponse(res: Response): Promise<ApiError> {
  let text = ''
  try {
    text = await res.text()
  } catch {
    // the body could not be read; keep the status
  }
  let parsed: unknown = undefined
  try {
    parsed = text ? JSON.parse(text) : undefined
  } catch {
    // not JSON
  }
  if (isErrorEnvelope(parsed)) {
    const e = parsed.error
    return new ApiError({ ...e, status: typeof e.status === 'number' ? e.status : res.status })
  }
  const message = `${res.status} ${res.statusText}`.trim()
  return unexpectedError(res.status, message, { body: parsed ?? text.slice(0, 4000) })
}
