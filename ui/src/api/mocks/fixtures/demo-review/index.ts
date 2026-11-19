import type { Review, SectionActResult, SectionHistory } from '../../../demoReview'
import type { ErrorEnvelope, WithNoop } from '../../../types'
import rawAcceptAgain from './accept.again.json'
import rawAccept from './accept.json'
import rawBookNoReport from './book.no_report.json'
import rawDocxNoReport from './docx.no_report.json'
import rawHistory from './history.json'
import rawRefusalFinished from './refusal.demo_reference.json'
import rawRefusalNoReason from './refusal.release_without_reason.json'
import rawRelease from './release.json'

/**
 * The review page's mock fixtures (the demo path, spec §4 S5).
 *
 * Every JSON file here is the backend's OWN answer ({status, body}), saved by
 * tools/fetch_fixtures.py from a backend running on a scratch store that holds
 * the finished NIEHS-12 report (1,2-dichlorobenzene) and its live copy, both
 * processed (the live report had no Background yet):
 *
 * | file | what |
 * |---|---|
 * | review.<id>.json | GET …/review of the finished report, the live report and the live rat study, before any act |
 * | accept.json, accept.again.json | approving a results section of the live mouse study; approving it again (a success that did nothing) |
 * | refusal.release_without_reason.json, release.json | reopening it without a reason (refused), then with one |
 * | history.json | that section's history after the three acts |
 * | refusal.demo_reference.json | an approval on the finished side (refused) |
 * | book.no_report.json, docx.no_report.json | what the Bookshelf answers for a report it does not have: a page, and `{"error": …}` |
 *
 * Nothing is shortened. The two refusals at the bottom are HAND-MADE in the
 * Bookshelf's own shapes (a page; `{"error": …}`), around a made-up reason:
 * no report of the scratch store was refused.
 */

interface Saved<T> {
  status: number
  body: T
}

const reviews = import.meta.glob<Saved<Review>>('./review.*.json', { eager: true, import: 'default' })

export const REVIEW_FINISHED = 'DTXSID6020430'
export const REVIEW_LIVE = 'DTXSID6020430_live'
export const REVIEW_LIVE_RAT = 'DTXSID6020430_live_rat'
export const REVIEW_LIVE_MOUSE = 'DTXSID6020430_live_mouse'

/** GET /api/v2/studies/{id}/review, by the id asked for */
export const DEMO_REVIEWS: Record<string, Review> = Object.fromEntries(
  Object.values(reviews).map((s) => [s.body.id, s.body]),
)

export const ACCEPT_OK = (rawAccept as Saved<SectionActResult>).body
export const ACCEPT_AGAIN = (rawAcceptAgain as Saved<WithNoop<SectionActResult>>).body
export const RELEASE_OK = (rawRelease as Saved<SectionActResult>).body
export const SECTION_HISTORY = (rawHistory as Saved<SectionHistory>).body
export const REFUSAL_RELEASE_WITHOUT_REASON = (rawRefusalNoReason as Saved<ErrorEnvelope>).body
export const REFUSAL_REVIEW_DEMO_REFERENCE = (rawRefusalFinished as Saved<ErrorEnvelope>).body

/** The Bookshelf's page for a report it does not have (404). */
export const BOOK_NO_REPORT = rawBookNoReport as Saved<string>
/** The Bookshelf's answer for the Word document of a report it does not have (404). */
export const DOCX_NO_REPORT = rawDocxNoReport as Saved<{ error: string }>

/** HAND-MADE: the reason of the two hand-made refusals below. */
export const REASON_PROCESS_AGAIN =
  'The study was processed before the report stated how its benchmark doses were computed. Run Process again.'

/** HAND-MADE in the shape of web_routes.bookshelf_routes._refused_page: a report the system refuses to show. */
export const BOOK_REFUSED: Saved<string> = {
  status: 409,
  body:
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Not shown yet — Bookshelf</title></head>' +
    '<body><div class="wrap"><h1>This report cannot be shown yet</h1>' +
    '<p class="sub">The report for <code>DTXSID6020430_live</code> is not shown:</p>' +
    `<p>${REASON_PROCESS_AGAIN}</p>` +
    '<p class="sub"><a class="home" href="/Bookshelf">← back to the shelf</a></p></div></body></html>',
}

/** HAND-MADE in the shape of web_routes.bookshelf_routes.bookshelf_docx: a Word document that cannot be made. */
export const DOCX_REFUSED: Saved<{ error: string }> = { status: 409, body: { error: REASON_PROCESS_AGAIN } }

/** HAND-MADE: a stand-in for a report's Bookshelf page (the real one is about 400 kB). */
export const BOOK_STAND_IN =
  '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Contents — Bookshelf preview</title></head>' +
  '<body><article class="bk-page" data-slug="bp-background"><h1 id="bp-background">Background</h1></article></body></html>'
