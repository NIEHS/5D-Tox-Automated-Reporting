import { cleanup, screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import {
  STATE_APPROVED,
  STATE_COMPANION,
  STATE_EMPTY,
  STATE_INTEGRATED,
  STATE_MEMBER_RAT,
  STATE_REPORT,
  STATE_RUNNING,
  STATE_STALE_AFTER_FILE_CHANGE,
  STATE_UPLOADED,
  STATE_VALIDATED,
  STATE_VALIDATION_ERRORS,
} from '../api/mocks/fixtures'
import { server } from '../api/mocks/node'
import type { ExistingStudyState } from '../api/types'
import { MODULES } from '../kit/modules'
import { renderApp } from '../test/render'
import { nextStepOf } from './nextStep'

function step(action: string): HTMLElement {
  const el = document.querySelector(`[data-action="${action}"]`)
  if (!el) throw new Error(`no step ${action}`)
  return el as HTMLElement
}

/** A study's landing page (M1's S3, with the shell's workflow panels). */
async function openStudy(id: string) {
  const r = renderApp(`/studies/${id}`)
  await screen.findByTestId('where-it-stands')
  return r
}

/** A module's page in the study frame: the frame's header (stage, next step, kind) is on top. */
async function openHeader(id: string, slug = 'facts') {
  const r = renderApp(`/studies/${id}/${slug}`)
  await screen.findByText('Next step:', {}, { timeout: 3000 }).catch(() => undefined)
  await waitFor(() => expect(document.querySelector('.ant-card')).not.toBeNull())
  return r
}

describe('the study frame', () => {
  it("shows the study's id, identity and stage in plain words", async () => {
    await openHeader(STATE_APPROVED.id)
    expect(screen.getByRole('heading', { name: 'Perfluorohexanesulfonamide' })).toBeInTheDocument()
    expect(screen.getByText('DTXSID50469320')).toBeInTheDocument()
    expect(screen.getByText('41997-13-1')).toBeInTheDocument()
    expect(screen.getByTestId('phase')).toHaveTextContent('Data reviewed')
    expect(document.body).not.toHaveTextContent(/APPROVED|REPROCESS|wizard|stale_llm_sections|data_changed/)
  })

  it('marks a missing identity as pending, never blank (a real null short name; an empty study)', async () => {
    await openHeader(STATE_APPROVED.id)
    expect(screen.getByRole('button', { name: 'short name is missing; show why' })).toHaveTextContent('[short name pending]')
    cleanup()
    await openHeader(STATE_EMPTY.id)
    expect(screen.getByRole('button', { name: 'chemical name is missing; show why' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'CAS number is missing; show why' })).toBeInTheDocument()
  })

  it.each<[string, ExistingStudyState, string, string]>([
    ['no files', STATE_EMPTY, "Bring in the study's files", 'Study files'],
    ['files not checked', STATE_UPLOADED, 'Validate the files', 'Study files'],
    ['files with problems', STATE_VALIDATION_ERRORS, 'Fix the problems the validation found', 'Study files'],
    ['files checked', STATE_VALIDATED, 'Integrate the data', 'Combined data'],
    ['combined data, processed before', STATE_INTEGRATED, "Review the report's sections", 'Review the report'],
    ['processed, nothing found to block', STATE_APPROVED, "Review the report's sections", 'Review the report'],
  ])('puts forward the next step the backend serves (%s)', async (_name, state, label, module) => {
    await openHeader(state.id)
    const alert = screen.getByText('Next step:').closest('.ant-alert') as HTMLElement
    expect(alert).toHaveTextContent(label)
    expect(within(alert).getByRole('link', { name: new RegExp(`Go to ${module}`) })).toBeInTheDocument()
  })

  it('never says a report is ready to publish while the check is partial, and says what was checked', async () => {
    await openStudy(STATE_APPROVED.id)
    expect(STATE_APPROVED.readiness.publish?.ready).toBe(true)
    expect(STATE_APPROVED.readiness.publish?.complete).toBe(false)
    expect(document.body).not.toHaveTextContent(/ready to publish|Nothing stops the report being published|nothing blocks/i)
    expect(screen.getByTestId('publish-nothing-found')).toHaveTextContent('Nothing found by the checks below.')
    const partial = screen.getByTestId('publish-partial')
    expect(partial).toHaveTextContent('This is not a full check')
    expect(partial).toHaveTextContent(/out of date with the study's data/)
    expect(partial).toHaveTextContent(/Not checked yet: whether every section is approved/)
  })

  it('names what blocks publishing, from the backend, after a file change staled the Summary', async () => {
    renderApp(`/studies/${STATE_STALE_AFTER_FILE_CHANGE.id}`)
    await screen.findByTestId('phase')
    const card = screen.getByText('What stops the report being published').closest('.ant-card') as HTMLElement
    expect(within(card).getByText(/summary:/)).toBeInTheDocument()
    expect(card).toHaveTextContent("The study's data changed after this section was written.")
    expect(within(card).getByRole('link', { name: 'Go to Review the report' })).toBeInTheDocument()
  })

  it('lists every step, the legal ones as links and the rest visibly unavailable with the reason', async () => {
    await openStudy(STATE_VALIDATION_ERRORS.id)
    for (const a of STATE_VALIDATION_ERRORS.legal_actions) {
      expect(step(a)).toHaveAttribute('data-available', 'yes')
      expect(within(step(a)).getByRole('link')).toBeInTheDocument()
    }
    for (const a of ['INTEGRATE', 'STATE_DATASET_FACTS', 'APPROVE', 'PROCESS']) {
      expect(step(a)).toHaveAttribute('data-available', 'no')
      expect(within(step(a)).getByRole('button')).toBeDisabled()
      expect(step(a)).toHaveTextContent('Not available now: the study is at "The files have problems".')
    }
  })

  it('offers only what the backend allows: bringing in files on an empty study', async () => {
    await openStudy(STATE_EMPTY.id)
    expect(step('ADD_FILES')).toHaveAttribute('data-available', 'yes')
    for (const a of ['VALIDATE', 'RESOLVE', 'REMOVE_FILE', 'RESET', 'INTEGRATE', 'APPROVE', 'PROCESS']) {
      expect(step(a)).toHaveAttribute('data-available', 'no')
    }
  })

  it('offers nothing, and says why, at a stage it does not know', async () => {
    // as the backend would serve it: workflow.studies.stands words an unknown phase "At the stage …"
    const archived = { ...STATE_INTEGRATED, phase: 'ARCHIVED', stands: { phase: 'ARCHIVED', say: 'At the stage ARCHIVED', next: null } }
    server.use(http.get('/api/v2/studies/:id/state', () => HttpResponse.json(archived)))
    await openHeader(STATE_INTEGRATED.id)
    expect(screen.getByTestId('phase')).toHaveAttribute('data-phase', 'ARCHIVED')
    expect(screen.getByTestId('phase')).toHaveTextContent('At the stage ARCHIVED')
    expect(screen.getByText('This page cannot offer any step')).toBeInTheDocument()
    cleanup()
    await openStudy(STATE_INTEGRATED.id)
    await screen.findByText('Steps')
    expect(document.querySelectorAll('[data-available="yes"]')).toHaveLength(0)
  })

  it('shows the method and the report definition as the backend reports them, an unchosen method plainly', async () => {
    await openStudy(STATE_APPROVED.id)
    const method = screen.getByTestId('pin-method')
    expect(method).toHaveTextContent('ntp-5day-2021')
    expect(method).toHaveTextContent(/does not implement/)
    expect(screen.getByTestId('pin-definition')).toHaveTextContent("studies/DTXSID50469320/document")
    cleanup()
    await openStudy(STATE_EMPTY.id)
    expect(screen.getByTestId('pin-method')).toHaveTextContent('not chosen')
    expect(screen.getByTestId('pin-method')).toHaveTextContent(/no profile pinned; the newest/)
  })

  it('shows a report over two studies: its members and their stage, no steps of its own, never "bring in files"', async () => {
    renderApp(`/studies/${STATE_REPORT.id}/review`)
    const members = await screen.findByLabelText('Studies in this report')
    expect(members).toHaveTextContent('This report covers 2 studies')
    expect(within(members).getByRole('link', { name: /rat \(DTXSID1020431_rat\): Data reviewed/ })).toHaveAttribute('href', '/studies/DTXSID1020431_rat')
    expect(within(members).getByRole('link', { name: /mouse \(DTXSID1020431_mouse\)/ })).toBeInTheDocument()
    expect(screen.queryByTestId('phase')).not.toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(/Bring in the study's files|No files yet/)
    expect(screen.getByText('Next step:').closest('.ant-alert')).toHaveTextContent("Review the report's sections")
    expect(document.querySelector('[data-action]')).toBeNull()
  })

  it('says when a member study of a report is not processed', async () => {
    const report: ExistingStudyState = {
      ...STATE_REPORT,
      members: (STATE_REPORT.members ?? []).map((m) => (m.key === 'mouse' ? { ...m, processed: false, phase: 'INTEGRATED' } : m)),
      // as workflow.studies.stands serves it while a study is not processed
      stands: { phase: null, say: 'A report over 2 studies; its studies are being prepared', next: { say: 'Finish the member studies', fix: 'M1' } },
    }
    server.use(http.get('/api/v2/studies/:id/state', () => HttpResponse.json(report)))
    renderApp(`/studies/${STATE_REPORT.id}/review`)
    const alert = (await screen.findByText('Next step:')).closest('.ant-alert') as HTMLElement
    expect(alert).toHaveTextContent('Finish the member studies')
    expect(alert).toHaveTextContent('mouse (DTXSID1020431_mouse)')
  })

  it('links a member study to its report', async () => {
    await openHeader(STATE_MEMBER_RAT.id)
    const note = await screen.findByTestId('kind-note')
    expect(within(note).getByRole('link', { name: 'DTXSID1020431' })).toHaveAttribute('href', '/studies/DTXSID1020431')
  })

  it("shows the published book's companion as read-only content, with no steps and no next step", async () => {
    renderApp(`/studies/${STATE_COMPANION.id}/review`)
    const note = await screen.findByTestId('kind-note')
    expect(note).toHaveTextContent("published book's content")
    expect(within(note).getByRole('link', { name: 'DTXSID50469320' })).toBeInTheDocument()
    expect(screen.queryByText('Next step:')).not.toBeInTheDocument()
    expect(screen.queryByText('No step is available now.')).not.toBeInTheDocument()
    // no workflow page is offered for published content, even by its address
    expect(screen.getByText('Review the report is not offered here.')).toBeInTheDocument()
    cleanup()
    await openStudy(STATE_COMPANION.id)
    expect(document.querySelector('[data-action]')).toBeNull()
    expect(screen.queryByText('What stops the report being published')).not.toBeInTheDocument()
    expect(screen.queryByTestId('pin-method')).not.toBeInTheDocument()
  })

  it('blocks the page when a run is already in flight', async () => {
    server.use(http.get('/api/v2/studies/:id/state', () => HttpResponse.json(STATE_RUNNING)))
    await openStudy(STATE_RUNNING.id)
    expect(await screen.findByText('This study is being processed')).toBeInTheDocument()
  })

  it('says when there is no such study', async () => {
    renderApp('/studies/DTXSID9999999')
    expect(await screen.findByText('There is no study DTXSID9999999. It may have been deleted.')).toBeInTheDocument()
  })

  it("refuses an id that is not a study id before asking for it, in the backend's words", async () => {
    let asked = 0
    server.use(
      http.get('/api/v2/studies/:id/state', () => {
        asked++
        return HttpResponse.json({})
      }),
    )
    renderApp('/studies/not-a-study')
    expect(await screen.findByText("'not-a-study' is not a study id.")).toBeInTheDocument()
    expect(screen.getByText(/A study is named by its chemical's DTXSID/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to studies' })).toBeInTheDocument()
    expect(asked).toBe(0)
  })

  it("still explains the backend's refusal of an id when the id rule could not be loaded", async () => {
    server.use(http.get('/api/v2/vocabularies', () => HttpResponse.error()))
    renderApp('/studies/not-a-study')
    expect(await screen.findByText("'not-a-study' is not a study id.", {}, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText(/A study is named by its chemical's DTXSID/)).toBeInTheDocument()
  })

  it('explains a study that cannot be read, and offers to try again', async () => {
    server.use(http.get('/api/v2/studies/:id/state', () => HttpResponse.error()))
    renderApp('/studies/DTXSID50469320')
    expect(await screen.findByText('The study could not be read')).toBeInTheDocument()
    expect(screen.getByText(/could not be reached/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('the routes', () => {
  it.each(MODULES.filter((m) => m.slug).map((m) => [m.id, m.slug, m.title] as const))(
    '%s has a placeholder page at /studies/:id/%s',
    async (_id, slug, title) => {
      renderApp(`/studies/DTXSID50469320/${slug}`)
      expect(await screen.findByText(`${MODULES.find((m) => m.slug === slug)?.purpose ?? ''} This page is not built yet.`)).toBeInTheDocument()
      expect(screen.getAllByText(title).length).toBeGreaterThan(0)
    },
  )

  it('says so for a page that does not exist', async () => {
    renderApp('/studies/DTXSID50469320/nonsense')
    expect(await screen.findByText(/no page called "nonsense"/)).toBeInTheDocument()
  })

  it('sends / to the studies', async () => {
    const { router } = renderApp('/')
    await waitFor(() => expect(router.state.location.pathname).toBe('/studies'))
  })
})

describe('nextStepOf', () => {
  it('reads the next step the backend serves, and decides nothing itself', () => {
    expect(nextStepOf({ ...STATE_APPROVED, stands: { phase: 'APPROVED', say: 'x', next: { say: 'Process the data', fix: 'P1' } } }))
      .toEqual({ label: 'Process the data', module: 'P1' })
    expect(nextStepOf({ ...STATE_APPROVED, stands: { phase: 'APPROVED', say: 'x', next: null } })).toBeNull()
  })

  it('never puts "publish" forward, even when nothing was found to block it', () => {
    const step = nextStepOf({ ...STATE_APPROVED, readiness: { publish: { ready: true, complete: true, checks: [], items: [] } } })
    expect(step).toMatchObject({ module: 'D1', label: "Review the report's sections" })
  })

  it('has no next step for published content', () => {
    expect(nextStepOf(STATE_COMPANION)).toBeNull()
  })
})
