import { describe, expect, it } from 'vitest'
import { reasonOfPage } from '../../../demoReview'
import {
  ACCEPT_AGAIN,
  ACCEPT_OK,
  BOOK_NO_REPORT,
  BOOK_REFUSED,
  DEMO_REVIEWS,
  DOCX_NO_REPORT,
  REASON_PROCESS_AGAIN,
  REFUSAL_RELEASE_WITHOUT_REASON,
  REFUSAL_REVIEW_DEMO_REFERENCE,
  RELEASE_OK,
  REVIEW_FINISHED,
  REVIEW_LIVE,
  REVIEW_LIVE_RAT,
  SECTION_HISTORY,
} from '.'
import { DEMO_STATES } from '../demo-writing'

/**
 * The fixtures are the backend's own answers. These tests pin what the page's
 * types and words rely on, so a change on either side fails here first.
 */

describe('the review fixtures are real answers in the typed shape', () => {
  it('covers the finished report, the live report and a study of the live report', () => {
    expect(Object.keys(DEMO_REVIEWS).sort()).toEqual([REVIEW_FINISHED, REVIEW_LIVE, REVIEW_LIVE_RAT].sort())
    for (const [id, review] of Object.entries(DEMO_REVIEWS)) {
      expect(review.id).toBe(id)
      expect(review.groups.map((g) => [g.key, g.title])).toEqual([
        [null, 'The report'],
        ['rat', 'Rat study'],
        ['mouse', 'Mouse study'],
      ])
      expect(review.book).toEqual({ shown: true, url: `/Bookshelf/${review.report.id}`, say: expect.any(String) as string })
      expect(review.downloads.map((d) => d.format)).toEqual(['docx', 'pdf'])
      expect(review.api_page.map((l) => l.title)).toEqual(['Review and approval', 'The report: Bookshelf, Word and PDF'])
    }
    // The mocks of the pair's state (demo-writing) answer for the same sessions.
    for (const id of Object.keys(DEMO_REVIEWS)) expect(DEMO_STATES[id], id).toBeDefined()
  })

  it('a study of a report is answered with the report, and says which study was asked for', () => {
    const asked = DEMO_REVIEWS[REVIEW_LIVE_RAT]!
    expect(asked.report.id).toBe(REVIEW_LIVE)
    expect(asked.asked).toMatchObject({ id: REVIEW_LIVE_RAT, key: 'rat' })
    expect(asked.groups).toEqual(DEMO_REVIEWS[REVIEW_LIVE]!.groups)
    expect(DEMO_REVIEWS[REVIEW_LIVE]!.asked).toBeNull()
  })

  it('every section has an owner, a title, a writer, the accept verdict, and an anchor or null', () => {
    for (const review of Object.values(DEMO_REVIEWS)) {
      for (const group of review.groups) {
        expect(group.publish?.complete, group.owner).toBe(false)
        for (const s of group.sections) {
          expect(s.owner, s.key).toBe(group.owner)
          expect(s.title && s.writer_say, s.key).toBeTruthy()
          expect(typeof s.accept.allowed, s.key).toBe('boolean')
          if (!s.accept.allowed) expect(s.accept.say, s.key).toBeTruthy()
          expect(s.anchor === null || /^(fm|bp|sec|T)-/.test(s.anchor), `${s.key} ${s.anchor}`).toBe(true)
        }
      }
    }
    const live = DEMO_REVIEWS[REVIEW_LIVE]!
    const noPlace = live.groups.flatMap((g) => g.sections.filter((s) => s.anchor === null).map((s) => `${g.key ?? 'report'}/${s.key}`))
    expect(noPlace).toEqual(['report/abstract', 'rat/bm2_clinical-observations', 'mouse/bm2_clinical-observations'])
  })

  it('acts are offered on the live side only, and the finished side names its live copy', () => {
    expect(DEMO_REVIEWS[REVIEW_FINISHED]!.acts).toMatchObject({ allowed: false, counterpart: REVIEW_LIVE })
    expect(DEMO_REVIEWS[REVIEW_FINISHED]!.acts.say).toBe(REFUSAL_REVIEW_DEMO_REFERENCE.error.say.replace(`${REVIEW_LIVE}_rat`, REVIEW_LIVE))
    expect(DEMO_REVIEWS[REVIEW_LIVE]!.acts).toEqual({ allowed: true, say: null, counterpart: null })
    expect(REFUSAL_REVIEW_DEMO_REFERENCE.error.code).toBe('demo_reference')
  })

  it('the acts answer as the page reads them', () => {
    expect(ACCEPT_OK).toMatchObject({ approved: true, version_status: 'blessed' })
    expect(ACCEPT_AGAIN.noop).toMatchObject({ code: 'already_accepted' })
    expect(RELEASE_OK).toMatchObject({ approved: false, version_status: 'working' })
    expect(REFUSAL_RELEASE_WITHOUT_REASON.error).toMatchObject({ code: 'reason_required', status: 400 })
    expect(SECTION_HISTORY.events.map((e) => [e.act, e.actor])).toEqual([
      ['materialize', 'system'],
      ['accept', 'person'],
      ['release', 'person'],
    ])
    expect(SECTION_HISTORY.events[2]!.reason).toBeTruthy()
  })

  it('a report the Bookshelf does not show answers with a page or a reason, which the page turns into words', () => {
    expect(BOOK_NO_REPORT.status).toBe(404)
    expect(reasonOfPage(BOOK_NO_REPORT.body)).toBe('No report There is no generated report for DTXSID0000000.')
    expect(DOCX_NO_REPORT).toEqual({ status: 404, body: { error: 'No generated report for DTXSID0000000' } })
    expect(reasonOfPage(BOOK_REFUSED.body)).toContain(REASON_PROCESS_AGAIN)
  })
})
