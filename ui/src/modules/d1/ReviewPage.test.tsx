import { screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, delay, http } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reviewPaths, type Review } from '../../api/demoReview'
import {
  BOOK_REFUSED,
  DEMO_REVIEWS,
  DOCX_REFUSED,
  REASON_PROCESS_AGAIN,
  REFUSAL_REVIEW_DEMO_REFERENCE,
  REVIEW_FINISHED,
  REVIEW_LIVE,
  REVIEW_LIVE_MOUSE,
  REVIEW_LIVE_RAT,
  SECTION_HISTORY,
} from '../../api/mocks/fixtures/demo-review'
import { server } from '../../api/mocks/node'
import { saveFile } from './save'
import { alertTitled, approveButton, bookFrame, groupOf, loadBook, markOf, openReview, sectionRow } from './testing'
import {
  ANCHOR_NOT_IN_BOOK,
  BOOK_BUILDING,
  BOOK_BUILDING_NOTE,
  BOOK_NOT_READY,
  BOOK_NOT_SHOWN_TITLE,
  EDITED_IN_WORD,
  NO_ANCHOR,
  NO_DOWNLOADS,
  PDF_BUTTON,
  REOPEN_REASON_MISSING,
  WORD_BUTTON,
  WORD_WAIT_NOTE,
} from './words'

vi.mock('./save', () => ({ saveFile: vi.fn() }))

/** Review the report (the demo path, spec §4 S5), against the backend's own answers for NIEHS-12. */

const LIVE_RAT = REVIEW_LIVE_RAT
const FINISHED_RAT = `${REVIEW_FINISHED}_rat`

/** How often the report's page was asked for. */
function countBookRequests(): () => number {
  let n = 0
  server.events.on('request:start', ({ request }) => {
    if (/\/Bookshelf\/[^/]+$/.test(new URL(request.url).pathname)) n += 1
  })
  return () => n
}

beforeEach(() => {
  vi.mocked(saveFile).mockClear()
  server.events.removeAllListeners()
})

describe('the rail', () => {
  it("lists the sections by owner, in the report's order, each with the kit's mark", async () => {
    await openReview(REVIEW_LIVE)
    expect(screen.getAllByTestId('group-title').map((el) => el.textContent)).toEqual([
      `The report ${REVIEW_LIVE}`,
      `Rat study ${LIVE_RAT}`,
      `Mouse study ${REVIEW_LIVE_MOUSE}`,
    ])
    const fixture = DEMO_REVIEWS[REVIEW_LIVE]!
    for (const group of fixture.groups) {
      const rows = Array.from(groupOf(group.owner).querySelectorAll('li[data-section]'))
      expect(rows.map((r) => r.getAttribute('data-section'))).toEqual(group.sections.map((s) => `${group.owner}/${s.key}`))
      for (const s of group.sections) expect(sectionRow(group.owner, s.key), s.key).toHaveTextContent(s.title)
    }
    // The report owns the front matter and the Background; a study owns its results.
    expect(groupOf(REVIEW_LIVE)).toHaveTextContent('Foreword')
    expect(groupOf(REVIEW_LIVE)).not.toHaveTextContent('Body Weight')
    expect(markOf(sectionRow(LIVE_RAT, 'bm2_body-weight'))).toBe('draft')
    expect(markOf(sectionRow(REVIEW_LIVE, 'foreword'))).toBe('not-approvable')
    expect(markOf(sectionRow(LIVE_RAT, 'summary'))).toBe('waiting')
    expect(markOf(sectionRow(LIVE_RAT, 'methods'))).toBe('cannot-approve-yet')
  })

  it('offers Approve where the backend allows it, and says why not where it does not', async () => {
    await openReview(REVIEW_LIVE)
    const fixture = DEMO_REVIEWS[REVIEW_LIVE]!
    let allowed = 0
    for (const group of fixture.groups) {
      for (const s of group.sections) {
        const button = approveButton(sectionRow(group.owner, s.key))
        if (s.accept.allowed) {
          allowed += 1
          expect(button, s.key).toBeEnabled()
        } else {
          expect(button, s.key).toBeDisabled()
          expect(button, s.key).toHaveAccessibleDescription(s.accept.say!)
        }
      }
    }
    expect(allowed).toBeGreaterThan(0)
    // The live report has no Background yet: the backend's reason, word for word.
    expect(approveButton(sectionRow(REVIEW_LIVE, 'background'))).toHaveAccessibleDescription(
      'There is no text for this section yet, so there is nothing to approve.',
    )
    // Nothing is approved yet, so nothing can be reopened.
    expect(screen.queryByRole('button', { name: /^Reopen / })).toBeNull()
  })

  it('approves a section of a study at the study, reads the state again, and does not ask for the book again', async () => {
    const asked: string[] = []
    const books = countBookRequests()
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST') asked.push(new URL(request.url).pathname)
    })
    const { user } = await openReview(REVIEW_LIVE)
    await bookFrame()
    const row = sectionRow(LIVE_RAT, 'bm2_body-weight')
    await user.click(approveButton(row))
    await waitFor(() => expect(markOf(sectionRow(LIVE_RAT, 'bm2_body-weight'))).toBe('approved'))
    expect(asked).toEqual([reviewPaths.accept(LIVE_RAT, 'bm2_body-weight')])
    // Approved: Reopen is offered, Approve no longer; the other study's section of the same key is its own.
    expect(within(sectionRow(LIVE_RAT, 'bm2_body-weight')).getByRole('button', { name: 'Reopen Body Weight' })).toBeEnabled()
    expect(within(sectionRow(LIVE_RAT, 'bm2_body-weight')).queryByRole('button', { name: /^Approve / })).toBeNull()
    expect(markOf(sectionRow(REVIEW_LIVE_MOUSE, 'bm2_body-weight'))).toBe('draft')
    expect(books()).toBe(1)
    expect(await bookFrame()).toHaveAttribute('src', `/Bookshelf/${REVIEW_LIVE}`)
  })

  it('reopening requires a reason before anything is sent, and says the reason is kept in the history', async () => {
    const sent: unknown[] = []
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && request.url.endsWith('/release')) void request.clone().json().then((b) => sent.push(b))
    })
    const { user } = await openReview(REVIEW_LIVE)
    await user.click(approveButton(sectionRow(LIVE_RAT, 'bm2_organ-weight')))
    const reopen = await within(groupOf(LIVE_RAT)).findByRole('button', { name: 'Reopen Organ Weight' })
    await user.click(reopen)
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Reopen “Organ Weight”')
    expect(dialog).toHaveTextContent('The reason is kept in the section’s history.')

    // No reason, then only spaces: refused here, nothing sent.
    await user.click(within(dialog).getByRole('button', { name: 'Reopen the section' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent(REOPEN_REASON_MISSING)
    await user.type(within(dialog).getByLabelText('Reason for reopening'), '   ')
    await user.click(within(dialog).getByRole('button', { name: 'Reopen the section' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent(REOPEN_REASON_MISSING)
    expect(sent).toEqual([])
    expect(markOf(sectionRow(LIVE_RAT, 'bm2_organ-weight'))).toBe('approved')

    await user.type(within(dialog).getByLabelText('Reason for reopening'), 'A footnote is to be checked.')
    await user.click(within(dialog).getByRole('button', { name: 'Reopen the section' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(sent).toEqual([{ reason: 'A footnote is to be checked.' }])
    await waitFor(() => expect(approveButton(sectionRow(LIVE_RAT, 'bm2_organ-weight'))).toBeEnabled())
    expect(within(sectionRow(LIVE_RAT, 'bm2_organ-weight')).queryByRole('button', { name: /^Reopen / })).toBeNull()
  })

  it("shows the backend's refusal of an act through the refusal explainer", async () => {
    server.use(
      http.post(reviewPaths.accept(LIVE_RAT, 'bm2_body-weight'), () =>
        HttpResponse.json(REFUSAL_REVIEW_DEMO_REFERENCE, { status: REFUSAL_REVIEW_DEMO_REFERENCE.error.status }),
      ),
    )
    const { user } = await openReview(REVIEW_LIVE)
    await user.click(approveButton(sectionRow(LIVE_RAT, 'bm2_body-weight')))
    const alert = await alertTitled('“Body Weight” was not approved')
    expect(alert).toHaveAttribute('role', 'alert')
    expect(alert).toHaveTextContent(REFUSAL_REVIEW_DEMO_REFERENCE.error.say)
    expect(within(alert).getByRole('button', { name: 'Show the technical details' })).toBeInTheDocument()
    expect(markOf(sectionRow(LIVE_RAT, 'bm2_body-weight'))).toBe('draft')
    await user.click(within(alert).getByRole('button', { name: 'Close' }))
    expect(screen.queryByText('“Body Weight” was not approved')).toBeNull()
  })

  it("shows the backend's refusal of a reopening inside the dialog, which stays open", async () => {
    const { user } = await openReview(REVIEW_LIVE)
    await user.click(approveButton(sectionRow(LIVE_RAT, 'bm2_body-weight')))
    await user.click(await within(groupOf(LIVE_RAT)).findByRole('button', { name: 'Reopen Body Weight' }))
    server.use(
      http.post(reviewPaths.release(LIVE_RAT, 'bm2_body-weight'), () =>
        HttpResponse.json(REFUSAL_REVIEW_DEMO_REFERENCE, { status: REFUSAL_REVIEW_DEMO_REFERENCE.error.status }),
      ),
    )
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Reason for reopening'), 'A reason.')
    await user.click(within(dialog).getByRole('button', { name: 'Reopen the section' }))
    expect(await within(dialog).findByText('“Body Weight” was not reopened')).toBeInTheDocument()
    expect(dialog).toHaveTextContent(REFUSAL_REVIEW_DEMO_REFERENCE.error.say)
  })

  it('opens a section’s history: its versions and what happened to each, with the reason given', async () => {
    const { user } = await openReview(REVIEW_LIVE)
    await user.click(within(sectionRow(REVIEW_LIVE_MOUSE, 'bm2_organ-weight')).getByRole('button', { name: 'History of Organ Weight' }))
    const history = await screen.findByTestId('section-history')
    expect(screen.getByText('History of “Organ Weight”')).toBeInTheDocument()
    expect(history.querySelectorAll('li[data-version]')).toHaveLength(SECTION_HISTORY.versions.length)
    expect(Array.from(history.querySelectorAll('li[data-act]')).map((li) => li.getAttribute('data-act'))).toEqual(
      SECTION_HISTORY.events.map((e) => e.act),
    )
    expect(history).toHaveTextContent('Built from the results of Process')
    expect(history).toHaveTextContent('Approved as it stood')
    expect(history).toHaveTextContent('Reopened')
    expect(history).toHaveTextContent('Reason given: The footnote on the liver weights is to be checked.')
    expect(history).toHaveTextContent('by a person')
    // A section with no saved text has no history to open.
    expect(within(sectionRow(REVIEW_LIVE, 'background')).queryByRole('button', { name: /^History / })).toBeNull()
  })
})

describe('choosing a section', () => {
  it('scrolls the book to where the section starts, the way the Bookshelf page itself goes to an element', async () => {
    const { user } = await openReview(REVIEW_LIVE)
    const frame = await bookFrame()
    const anchor = DEMO_REVIEWS[REVIEW_LIVE]!.groups[1]!.sections.find((s) => s.key === 'bm2_tissue-concentration')!.anchor!
    expect(anchor).toBe('T-table-tissue-conc--rat')
    loadBook(frame, [anchor, 'bp-background'])
    const row = sectionRow(LIVE_RAT, 'bm2_tissue-concentration')
    await user.click(within(row).getByRole('button', { name: 'Tissue Concentration' }))
    expect(sectionRow(LIVE_RAT, 'bm2_tissue-concentration')).toHaveAttribute('data-chosen', 'yes')
    expect(frame.contentWindow!.location.hash).toBe(`#${anchor}`)
    expect(screen.queryByTestId('scroll-note')).toBeNull()
    // Only one section is marked as chosen.
    await user.click(within(sectionRow(REVIEW_LIVE, 'foreword')).getByRole('button', { name: 'Foreword' }))
    expect(document.querySelectorAll('li[data-chosen="yes"]')).toHaveLength(1)
  })

  it('says so when a section has no place of its own in the book', async () => {
    const { user } = await openReview(REVIEW_LIVE)
    loadBook(await bookFrame(), ['bp-background'])
    const abstract = DEMO_REVIEWS[REVIEW_LIVE]!.groups[0]!.sections.find((s) => s.key === 'abstract')!
    expect(abstract.anchor).toBeNull()
    await user.click(within(sectionRow(REVIEW_LIVE, 'abstract')).getByRole('button', { name: 'Abstract' }))
    expect(sectionRow(REVIEW_LIVE, 'abstract')).toHaveAttribute('data-chosen', 'yes')
    expect(within(sectionRow(REVIEW_LIVE, 'abstract')).getByTestId('scroll-note')).toHaveTextContent(NO_ANCHOR)
  })

  it('says so when the place is not in the book as shown, or the book is not shown yet', async () => {
    const { user } = await openReview(REVIEW_LIVE)
    const frame = await bookFrame()
    await user.click(within(sectionRow(REVIEW_LIVE, 'foreword')).getByRole('button', { name: 'Foreword' }))
    expect(screen.getByTestId('scroll-note')).toHaveTextContent(BOOK_NOT_READY)
    loadBook(frame, ['bp-background'])
    await user.click(within(sectionRow(REVIEW_LIVE, 'foreword')).getByRole('button', { name: 'Foreword' }))
    expect(screen.getByTestId('scroll-note')).toHaveTextContent(ANCHOR_NOT_IN_BOOK)
  })
})

describe('the finished side of a pair', () => {
  it('offers no act, says where the acts are done, and links to this page of the live copy', async () => {
    await openReview(REVIEW_FINISHED)
    expect(screen.queryByRole('button', { name: /^Approve / })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Reopen / })).toBeNull()
    const note = screen.getByTestId('no-acts')
    expect(note).toHaveTextContent(DEMO_REVIEWS[REVIEW_FINISHED]!.acts.say!)
    expect(within(note).getByRole('link', { name: 'Open this page on the live copy' })).toHaveAttribute(
      'href',
      `/studies/${REVIEW_LIVE}/review`,
    )
    // The standing of each section is still shown, and so is its history.
    expect(markOf(sectionRow(FINISHED_RAT, 'bm2_body-weight'))).toBe('draft')
    expect(markOf(sectionRow(REVIEW_FINISHED, 'background'))).toBe('draft')
    expect(within(sectionRow(REVIEW_FINISHED, 'background')).getByRole('button', { name: 'History of Background' })).toBeEnabled()
    // The Word document and the PDF change nothing: they stay.
    expect(screen.getByRole('button', { name: WORD_BUTTON })).toBeEnabled()
    expect(screen.getByRole('button', { name: PDF_BUTTON })).toBeEnabled()
  })
})

describe('opened on a study of a report', () => {
  it("shows the report's page, says so in one line, and opens that study's sections first", async () => {
    await openReview(LIVE_RAT)
    const line = screen.getByTestId('asked-study')
    expect(line).toHaveTextContent(DEMO_REVIEWS[LIVE_RAT]!.asked!.say)
    expect(line).toHaveTextContent(LIVE_RAT)
    expect(await bookFrame()).toHaveAttribute('src', `/Bookshelf/${REVIEW_LIVE}`)
    // All three groups are listed; only the study's own is opened.
    expect(screen.getAllByTestId('group-title')).toHaveLength(3)
    expect(groupOf(LIVE_RAT)).toHaveTextContent('Body Weight')
    expect(document.querySelector(`ul[data-group="${REVIEW_LIVE}"]`)).toBeNull()
    expect(document.querySelector(`ul[data-group="${REVIEW_LIVE_MOUSE}"]`)).toBeNull()
  })
})

describe('the book', () => {
  it('says the report is being built, and how long that can take, until the page is answered', async () => {
    server.use(
      http.get('/Bookshelf/:id', async () => {
        await delay(150)
        return new HttpResponse('<html><body><article class="bk-page"></article></body></html>', {
          headers: { 'Content-Type': 'text/html' },
        })
      }),
    )
    await openReview(REVIEW_LIVE)
    const wait = screen.getByTestId('book-wait')
    expect(wait).toHaveTextContent(BOOK_BUILDING)
    expect(wait).toHaveTextContent(BOOK_BUILDING_NOTE)
    expect(wait).toHaveTextContent(/Waiting for \d+ s/)
    expect(screen.queryByTestId('book-frame')).toBeNull()
    expect(await bookFrame()).toHaveAttribute('title', 'The report as the Bookshelf shows it')
    expect(screen.queryByTestId('book-wait')).toBeNull()
  })

  it("shows the backend's reason when the report cannot be built, not a blank frame", async () => {
    server.use(
      http.get(
        '/Bookshelf/:id',
        () => new HttpResponse(BOOK_REFUSED.body, { status: BOOK_REFUSED.status, headers: { 'Content-Type': 'text/html' } }),
      ),
    )
    await openReview(REVIEW_LIVE)
    const alert = await alertTitled(BOOK_NOT_SHOWN_TITLE)
    expect(alert).toHaveTextContent(REASON_PROCESS_AGAIN)
    expect(alert).not.toHaveTextContent('back to the shelf')
    expect(screen.queryByTestId('book-frame')).toBeNull()
    // The sections are still listed.
    expect(groupOf(LIVE_RAT)).toHaveTextContent('Body Weight')
  })

  it("says why there is no book yet, in the backend's words, and offers no document", async () => {
    const none: Review = {
      ...DEMO_REVIEWS[REVIEW_LIVE]!,
      book: { shown: false, url: null, say: 'Not yet: its studies have not all been processed' },
      downloads: [],
    }
    const books = countBookRequests()
    server.use(http.get(reviewPaths.review(REVIEW_LIVE), () => HttpResponse.json(none)))
    await openReview(REVIEW_LIVE)
    expect(screen.getByTestId('book-none')).toHaveTextContent('Not yet: its studies have not all been processed')
    expect(screen.queryByTestId('book-frame')).toBeNull()
    expect(screen.queryByRole('button', { name: WORD_BUTTON })).toBeNull()
    expect(screen.getByTestId('downloads')).toHaveTextContent(NO_DOWNLOADS)
    expect(books()).toBe(0)
  })
})

describe('Make the Word document', () => {
  it('waits with the elapsed time, then hands the document to the browser to save', async () => {
    server.use(
      http.get('/Bookshelf/:id/report.docx', async () => {
        await delay(150)
        return new HttpResponse('PK the Word document', {
          headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' },
        })
      }),
    )
    const { user } = await openReview(REVIEW_LIVE)
    expect(screen.getByTestId('downloads')).toHaveTextContent(EDITED_IN_WORD)
    await user.click(screen.getByRole('button', { name: WORD_BUTTON }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Making the Word document')
    expect(dialog).toHaveTextContent(WORD_WAIT_NOTE)
    expect(dialog).toHaveTextContent(/Running for \d+ s/)
    expect(saveFile).not.toHaveBeenCalled()
    await waitFor(() => expect(saveFile).toHaveBeenCalledTimes(1))
    const [content, filename] = vi.mocked(saveFile).mock.calls[0]!
    expect(filename).toBe(`${REVIEW_LIVE}-report.docx`)
    expect(await content.text()).toBe('PK the Word document')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getByTestId('download-saved')).toHaveTextContent(`${REVIEW_LIVE}-report.docx`)
  })

  it("shows the backend's reason when the document cannot be made, and saves nothing", async () => {
    server.use(http.get('/Bookshelf/:id/report.docx', () => HttpResponse.json(DOCX_REFUSED.body, { status: DOCX_REFUSED.status })))
    const { user } = await openReview(REVIEW_LIVE)
    await user.click(screen.getByRole('button', { name: WORD_BUTTON }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('The run did not finish')).toBeInTheDocument()
    expect(dialog).toHaveTextContent(REASON_PROCESS_AGAIN)
    expect(saveFile).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.queryByTestId('download-saved')).toBeNull()
  })

  it('makes the PDF the same way', async () => {
    const { user } = await openReview(REVIEW_FINISHED)
    await user.click(screen.getByRole('button', { name: PDF_BUTTON }))
    await waitFor(() => expect(saveFile).toHaveBeenCalledTimes(1))
    expect(vi.mocked(saveFile).mock.calls[0]![1]).toBe(`${REVIEW_FINISHED}-report.pdf`)
  })
})

describe('what stands between the report and publishing', () => {
  it('is shown for the report and for each study, and never reads as ready to publish', async () => {
    const { user } = await openReview(REVIEW_LIVE)
    const card = screen.getByTestId('publishing')
    expect(card).toHaveTextContent('What stands between the report and publishing')
    for (const title of ['Rat study', 'Mouse study']) await user.click(within(card).getByText(title))
    expect(within(card).getAllByTestId('publish-partial')).toHaveLength(3)
    expect(card).toHaveTextContent('This is not a full check of whether the report can be published.')
    expect(document.body.textContent ?? '').not.toMatch(/ready to publish/i)
    expect(document.body.textContent ?? '').not.toMatch(/Nothing stops the report being published/i)
  })
})

describe('this step on the API page', () => {
  it('is linked by the names of its two groups, in a new tab', async () => {
    await openReview(REVIEW_LIVE)
    const links = within(screen.getByTestId('api-page')).getAllByRole('link')
    expect(links.map((a) => a.textContent)).toEqual(['Review and approval', 'The report: Bookshelf, Word and PDF'])
    for (const a of links) {
      expect(a.getAttribute('href')).toMatch(/^\/docs#\//)
      expect(a).toHaveAttribute('target', '_blank')
    }
  })
})
