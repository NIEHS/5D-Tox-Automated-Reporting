import { API_V2, getJson, sendJson } from './client'
import { ApiError, SAY_UNREACHABLE, errorFromResponse } from './errors'
import type { ErrorBody, Readiness, SectionState, WithNoop } from './types'

/**
 * The review page (the demo path, spec §4 S5): the report as the Bookshelf
 * shows it, its sections beside it, and the Word document.
 *
 *   - GET …/review (web_routes/v2_review_routes.py, ui_api.review): the types
 *     are the backend's answers, kept in step by the fixtures in
 *     mocks/fixtures/demo-review/, which are real answers;
 *   - the section acts and the history (web_routes/v2_section_routes.py);
 *   - the Bookshelf's own routes (web_routes/bookshelf_routes.py): the book
 *     as a page, the Word document and the PDF. They are not under /api/v2
 *     and do not answer in the §4.2 envelope: a report that cannot be made
 *     answers with a page, or with `{"error": "<the reason>"}`. Both are
 *     turned here into an ApiError whose `say` is the backend's reason.
 */

const enc = encodeURIComponent

export const reviewPaths = {
  review: (id: string) => `${API_V2}/studies/${enc(id)}/review`,
  accept: (owner: string, key: string) => `${API_V2}/studies/${enc(owner)}/sections/${enc(key)}/accept`,
  release: (owner: string, key: string) => `${API_V2}/studies/${enc(owner)}/sections/${enc(key)}/release`,
  history: (owner: string, key: string) => `${API_V2}/studies/${enc(owner)}/sections/${enc(key)}/history`,
}

/** A section as the review page lists it: the read model's row, and where it is. */
export interface ReviewSection extends Omit<SectionState, 'title'> {
  /** the session that holds the section; the acts go to it */
  owner: string
  title: string
  /** who writes it, in plain words */
  writer_say: string
  /** the id of the element in the Bookshelf page where the section starts; null when it has no place of its own */
  anchor: string | null
}

export interface ReviewGroup {
  owner: string
  /** the study's key in its report ("rat"); null for the report itself or a study on its own */
  key: string | null
  title: string
  exists: boolean
  /** null for a study that does not exist */
  publish: Readiness | null
  sections: ReviewSection[]
  /** why there is nothing to list (a study that does not exist) */
  say?: string
}

export interface ReviewBook {
  shown: boolean
  /** the report's page on the Bookshelf; null when it cannot be shown */
  url: string | null
  /** where the book stands, or why it cannot be shown */
  say: string
}

export interface ReviewDownload {
  format: 'docx' | 'pdf' | (string & {})
  title: string
  url: string
  filename: string
}

export interface ReviewActs {
  allowed: boolean
  say: string | null
  /** on the finished side of a pair: the session of the live copy that corresponds to this one */
  counterpart: string | null
}

export interface ApiPageLink {
  group: string
  title: string
  href: string
}

export interface Review {
  /** the session asked for */
  id: string
  kind: string
  /** the report the page shows (the session itself, unless it is a study of a report) */
  report: { id: string; kind: string }
  /** set when a study of a report was asked for */
  asked: { id: string; key: string | null; say: string } | null
  book: ReviewBook
  downloads: ReviewDownload[]
  acts: ReviewActs
  groups: ReviewGroup[]
  api_page: ApiPageLink[]
  /** set when the report's definition could not be built: no section can be scrolled to */
  anchors_error?: ErrorBody
}

export interface SectionActResult {
  section_key: string
  approved: boolean
  version: number | null
  version_status: string | null
}

export interface SectionVersion {
  version: number
  archived: string | null
  status: string | null
  approved_at: string | null
  current: boolean
  retrievable: boolean
}

/** A line of a section's history, as recorded (workflow.section_writes.event). */
export interface SectionEvent {
  version: number | null
  /** what was done: "materialize", "accept", "release", "restore", … */
  act: string
  cause: string
  status: string | null
  ts: string
  /** "system" or "person" */
  actor: string | null
  reason?: string | null
}

export interface SectionHistory {
  section_key: string
  current_version: number | null
  current_status: string | null
  versions: SectionVersion[]
  events: SectionEvent[]
}

export function getReview(id: string, signal?: AbortSignal): Promise<Review> {
  return getJson<Review>(reviewPaths.review(id), signal)
}

export function acceptSection(owner: string, key: string): Promise<WithNoop<SectionActResult>> {
  return sendJson<SectionActResult>('POST', reviewPaths.accept(owner, key))
}

export function releaseSection(owner: string, key: string, reason: string): Promise<WithNoop<SectionActResult>> {
  return sendJson<SectionActResult>('POST', reviewPaths.release(owner, key), { reason })
}

export function getSectionHistory(owner: string, key: string, signal?: AbortSignal): Promise<SectionHistory> {
  return getJson<SectionHistory>(reviewPaths.history(owner, key), signal)
}

// ---------------------------------------------------------------------------
// The Bookshelf's routes
// ---------------------------------------------------------------------------

function unreachable(err: unknown): ApiError {
  return new ApiError({
    code: 'unreachable',
    status: 0,
    message: err instanceof Error ? err.message : String(err),
    say: SAY_UNREACHABLE,
    fix: null,
    details: {},
  })
}

/** The words of a Bookshelf page that says why a report is not shown: its heading and its sentences, without its links. */
export function reasonOfPage(html: string): string | null {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  doc.querySelectorAll('a, script, style').forEach((el) => el.remove())
  const parts = Array.from(doc.querySelectorAll('h1, p'))
    .map((el) => (el.textContent ?? '').replace(/\s+/g, ' ').trim())
    .filter(Boolean)
  return parts.length > 0 ? parts.join(' ') : null
}

/** A failed answer of a Bookshelf route as an ApiError that says the backend's reason. */
async function bookshelfError(res: Response, code: string): Promise<ApiError> {
  let text = ''
  try {
    text = await res.clone().text()
  } catch {
    // the body could not be read; the status is kept below
  }
  let reason: string | null = null
  try {
    const parsed: unknown = JSON.parse(text)
    const e = typeof parsed === 'object' && parsed !== null ? (parsed as { error?: unknown }).error : undefined
    if (typeof e === 'string' && e.trim()) reason = e.trim()
  } catch {
    if (/<html|<!doctype/i.test(text)) reason = reasonOfPage(text)
  }
  if (!reason) return errorFromResponse(res)
  return new ApiError({ code, status: res.status, message: `${res.status} ${res.statusText}`.trim(), say: reason, fix: null, details: {} })
}

/**
 * Ask for the report's Bookshelf page, so that the wait and a refusal are
 * the application's own: resolves when the page can be shown (the server
 * keeps what it built, so showing it then is immediate); rejects with the
 * backend's reason when it cannot.
 */
export async function requestBook(url: string, signal?: AbortSignal): Promise<void> {
  let res: Response
  try {
    res = await fetch(url, { method: 'GET', headers: { Accept: 'text/html' }, signal })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw unreachable(err)
  }
  if (!res.ok) throw await bookshelfError(res, 'book_not_shown')
  // Only whether it can be shown is wanted here; the frame reads the page itself.
  void res.body?.cancel().catch(() => undefined)
}

/** Fetch a download of the report (the Word document, the PDF) as a file's content. */
export async function fetchDownload(url: string, signal?: AbortSignal): Promise<Blob> {
  let res: Response
  try {
    res = await fetch(url, { method: 'GET', signal })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw unreachable(err)
  }
  if (!res.ok) throw await bookshelfError(res, 'download_not_made')
  return res.blob()
}
