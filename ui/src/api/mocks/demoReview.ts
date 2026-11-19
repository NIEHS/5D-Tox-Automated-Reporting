import { HttpResponse, http } from 'msw'
import { API_V2 } from '../client'
import type { Review, ReviewSection } from '../demoReview'
import type { ErrorEnvelope } from '../types'
import {
  ACCEPT_AGAIN,
  ACCEPT_OK,
  BOOK_NO_REPORT,
  BOOK_STAND_IN,
  DEMO_REVIEWS,
  DOCX_NO_REPORT,
  REFUSAL_RELEASE_WITHOUT_REASON,
  REFUSAL_REVIEW_DEMO_REFERENCE,
  RELEASE_OK,
  SECTION_HISTORY,
} from './fixtures/demo-review'

/**
 * The review page, mocked (web_routes/v2_review_routes.py, the section acts
 * of web_routes/v2_section_routes.py, and the Bookshelf's page and downloads):
 * the backend's own answers for the finished NIEHS-12 report and its live
 * copy. The rules played here (no act on the finished side; a reason to
 * reopen) are the BACKEND's; no screen repeats them.
 *
 * Mock-only:
 *   - an approval or a reopening is played on the saved rows with the fields
 *     the backend's next read showed on the scratch store (approved: blessed,
 *     final, kept from the machine, "already accepted"; reopened: working,
 *     still kept from the machine, can be approved), so the page's re-read
 *     sees the act;
 *   - every section's history is the one saved history, under the asked key;
 *   - the report's page is a small stand-in, and a download is a few bytes.
 */

let db: Record<string, Review> = structuredClone(DEMO_REVIEWS)

/** Forget every act played on the mock reviews; called between tests. */
export function resetDemoReviewDb(): void {
  db = structuredClone(DEMO_REVIEWS)
}

function envelope(body: ErrorEnvelope): Response {
  return HttpResponse.json(body, { status: body.error.status })
}

/** The saved rows of a session's section, in every review that lists it. */
function rowsOf(owner: string, key: string): ReviewSection[] {
  return Object.values(db).flatMap((review) =>
    review.groups.filter((g) => g.owner === owner).flatMap((g) => g.sections.filter((s) => s.key === key)),
  )
}

/** Whether the session is on a side the backend refuses acts on (the finished report and its studies). */
function onFinishedSide(owner: string): boolean {
  return Object.values(db).some((review) => !review.acts.allowed && review.groups.some((g) => g.owner === owner))
}

/** The reports whose page and downloads the mock has. */
function isKnownReport(id: string): boolean {
  return Object.values(db).some((review) => review.report.id === id)
}

export function createDemoReviewHandlers() {
  return [
    http.get(`${API_V2}/studies/:id/review`, ({ params }) => {
      const review = db[String(params.id)]
      return review ? HttpResponse.json(review) : undefined
    }),

    http.post(`${API_V2}/studies/:id/sections/:key/accept`, ({ params }) => {
      const owner = String(params.id)
      const key = String(params.key)
      const rows = rowsOf(owner, key)
      if (rows.length === 0) return undefined
      if (onFinishedSide(owner)) return envelope(REFUSAL_REVIEW_DEMO_REFERENCE)
      const first = rows[0]
      if (first?.approved) return HttpResponse.json({ ...ACCEPT_AGAIN, section_key: key, version: first.version })
      if (!first?.accept.allowed) return undefined
      for (const row of rows) {
        row.approved = true
        row.version_status = ACCEPT_OK.version_status
        row.facts = ['approved', 'final', 'protected']
        row.maturity = 'final'
        row.machine_may_write = false
        row.accept = { allowed: false, code: ACCEPT_AGAIN.noop?.code ?? 'already_accepted', say: ACCEPT_AGAIN.noop?.say ?? null }
      }
      return HttpResponse.json({ ...ACCEPT_OK, section_key: key, version: first.version })
    }),

    http.post(`${API_V2}/studies/:id/sections/:key/release`, async ({ params, request }) => {
      const owner = String(params.id)
      const key = String(params.key)
      const rows = rowsOf(owner, key)
      if (rows.length === 0) return undefined
      if (onFinishedSide(owner)) return envelope(REFUSAL_REVIEW_DEMO_REFERENCE)
      const body = (await request.json().catch(() => null)) as { reason?: unknown } | null
      const reason = typeof body?.reason === 'string' ? body.reason.trim() : ''
      if (!reason) {
        return envelope({
          error: { ...REFUSAL_RELEASE_WITHOUT_REASON.error, details: { key, act: 'reopen' } },
        })
      }
      for (const row of rows) {
        row.approved = false
        row.version_status = RELEASE_OK.version_status
        row.facts = ['protected']
        row.maturity = null
        row.machine_may_write = false
        row.accept = { allowed: true, code: null, say: null }
      }
      return HttpResponse.json({ ...RELEASE_OK, section_key: key, version: rows[0]?.version ?? null })
    }),

    http.get(`${API_V2}/studies/:id/sections/:key/history`, ({ params }) => {
      const key = String(params.key)
      if (rowsOf(String(params.id), key).length === 0) return undefined
      return HttpResponse.json({ ...SECTION_HISTORY, section_key: key })
    }),

    // The Bookshelf's own routes: the report as a page, and its downloads.
    http.get('/Bookshelf/:id', ({ params }) =>
      isKnownReport(String(params.id))
        ? new HttpResponse(BOOK_STAND_IN, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })
        : new HttpResponse(BOOK_NO_REPORT.body, {
            status: BOOK_NO_REPORT.status,
            headers: { 'Content-Type': 'text/html; charset=utf-8' },
          }),
    ),

    http.get('/Bookshelf/:id/:file', ({ params }) => {
      const id = String(params.id)
      const file = String(params.file)
      if (file !== 'report.docx' && file !== 'report.pdf') return undefined
      if (!isKnownReport(id)) return HttpResponse.json(DOCX_NO_REPORT.body, { status: DOCX_NO_REPORT.status })
      const word = file === 'report.docx'
      return new HttpResponse(word ? 'PK mock Word document' : '%PDF-1.7 mock', {
        headers: {
          'Content-Type': word
            ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            : 'application/pdf',
          'Content-Disposition': `attachment; filename="${id}-${file}"`,
        },
      })
    }),
  ]
}
