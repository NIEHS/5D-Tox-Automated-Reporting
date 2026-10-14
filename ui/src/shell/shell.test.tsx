import { screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import {
  STATE_APPROVED_STALE_SUMMARY,
  STATE_EMPTY,
  STATE_INTEGRATED,
  STATE_RUNNING,
  STATE_TWO_STUDIES,
  STATE_VALIDATION_ERRORS,
} from '../api/mocks/fixtures'
import { server } from '../api/mocks/node'
import type { StudyState } from '../api/types'
import { MODULES } from '../kit/modules'
import { renderApp } from '../test/render'
import { nextStepOf } from './nextStep'

function step(action: string): HTMLElement {
  const el = document.querySelector(`[data-action="${action}"]`)
  if (!el) throw new Error(`no step ${action}`)
  return el as HTMLElement
}

async function openStudy(id: string) {
  const r = renderApp(`/studies/${id}`)
  await screen.findByTestId('phase')
  return r
}

describe('the study frame', () => {
  it("shows the study's id, identity and stage in plain words", async () => {
    await openStudy(STATE_APPROVED_STALE_SUMMARY.id)
    expect(screen.getByRole('heading', { name: 'Perfluorohexanesulfonamide' })).toBeInTheDocument()
    expect(screen.getByText('DTXSID50469320')).toBeInTheDocument()
    expect(screen.getByText('41997-13-1')).toBeInTheDocument()
    expect(screen.getByText('PFHxSAm')).toBeInTheDocument()
    expect(screen.getByTestId('phase')).toHaveTextContent('Data reviewed')
    expect(document.body).not.toHaveTextContent(/APPROVED|REPROCESS|wizard/)
  })

  it('marks a missing identity as pending, never blank', async () => {
    await openStudy(STATE_EMPTY.id)
    expect(screen.getByRole('button', { name: 'chemical name is missing; show why' })).toHaveTextContent('[chemical name pending]')
    expect(screen.getByRole('button', { name: 'CAS number is missing; show why' })).toBeInTheDocument()
  })

  it.each<[string, StudyState, string, string]>([
    ['no files', STATE_EMPTY, "Bring in the study's files", 'Study files'],
    ['files with problems', STATE_VALIDATION_ERRORS, 'Check the files', 'Study files'],
    ['combined data', STATE_INTEGRATED, 'Review the data', 'Data review'],
    ['processed, not publishable', STATE_APPROVED_STALE_SUMMARY, 'Clear what stops publishing', 'Review the report'],
    ['a member study not processed', STATE_TWO_STUDIES, 'Clear what stops publishing', 'Process'],
  ])('puts forward the next step from the legal actions (%s)', async (_name, state, label, module) => {
    await openStudy(state.id)
    const alert = screen.getByText('Next step:').closest('.ant-alert') as HTMLElement
    expect(alert).toHaveTextContent(label)
    expect(within(alert).getByRole('link', { name: new RegExp(`Go to ${module}`) })).toBeInTheDocument()
  })

  it('names the first thing that blocks publishing once processed', async () => {
    await openStudy(STATE_APPROVED_STALE_SUMMARY.id)
    const alert = screen.getByText('Next step:').closest('.ant-alert') as HTMLElement
    expect(alert).toHaveTextContent('The Summary was approved, but the study design it was written from has changed since.')
  })

  it('lists every step, the legal ones as links and the rest visibly unavailable with the reason', async () => {
    await openStudy(STATE_VALIDATION_ERRORS.id)
    for (const a of ['VALIDATE', 'RESET']) {
      expect(step(a)).toHaveAttribute('data-available', 'yes')
      expect(within(step(a)).getByRole('link')).toBeInTheDocument()
    }
    for (const a of ['INTEGRATE', 'APPROVE', 'REPROCESS', 'CLEAR_FILES']) {
      expect(step(a)).toHaveAttribute('data-available', 'no')
      expect(within(step(a)).getByRole('button')).toBeDisabled()
      expect(step(a)).toHaveTextContent('Not available now: the study is at "The files have problems".')
    }
  })

  it('offers nothing when the backend allows nothing', async () => {
    await openStudy(STATE_EMPTY.id)
    for (const a of ['VALIDATE', 'INTEGRATE', 'APPROVE', 'REPROCESS', 'CLEAR_FILES', 'RESET']) {
      expect(step(a)).toHaveAttribute('data-available', 'no')
    }
  })

  it('offers nothing, and says why, at a stage it does not know', async () => {
    server.use(http.get('/api/v2/studies/:id/state', () => HttpResponse.json({ ...STATE_INTEGRATED, phase: 'ARCHIVED' })))
    await openStudy(STATE_INTEGRATED.id)
    expect(screen.getByTestId('phase')).toHaveTextContent('Unknown stage')
    expect(screen.getByText('This page cannot offer any step')).toBeInTheDocument()
    expect(document.querySelectorAll('[data-available="yes"]')).toHaveLength(0)
  })

  it('shows what needs attention, each with a link to where it is fixed', async () => {
    await openStudy(STATE_INTEGRATED.id)
    expect(screen.getByText(/the standard design .* is assumed/)).toBeInTheDocument()
    const card = screen.getByText('The data: what to look at').closest('.ant-card') as HTMLElement
    expect(within(card).getByRole('link', { name: 'Go to Study facts' })).toHaveAttribute('href', `/studies/${STATE_INTEGRATED.id}/facts`)
    expect(within(card).getByRole('link', { name: 'Go to Method and report definition' })).toBeInTheDocument()
  })

  it('lists the member studies of a report over two studies', async () => {
    await openStudy(STATE_TWO_STUDIES.id)
    const members = screen.getByLabelText('Studies in this report')
    expect(members).toHaveTextContent('This report covers 2 studies')
    expect(within(members).getByRole('link', { name: /mouse \(DTXSID1020431_mouse\).*not processed/ })).toHaveAttribute('href', '/studies/DTXSID1020431_mouse')
    const blocks = screen.getByText('What stops the report being published').closest('.ant-card') as HTMLElement
    expect(within(blocks).getByText('The mouse study (DTXSID1020431_mouse) has not been processed.')).toBeInTheDocument()
  })

  it('blocks the page when a run is already in flight', async () => {
    server.use(http.get('/api/v2/studies/:id/state', () => HttpResponse.json(STATE_RUNNING)))
    await openStudy(STATE_RUNNING.id)
    expect(await screen.findByText('This study is being processed')).toBeInTheDocument()
  })

  it('says when there is no such study', async () => {
    renderApp('/studies/DTXSID999')
    expect(await screen.findByText('There is no study with this id')).toBeInTheDocument()
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

  it('opens a study from the studies page only with a valid DTXSID', async () => {
    const { user, router } = renderApp('/studies')
    const input = await screen.findByRole('textbox', { name: 'DTXSID' })
    await waitFor(() => expect(input).toBeEnabled())
    const open = screen.getByRole('button', { name: 'Open' })
    await user.type(input, 'DTXSID50469320_rat')
    expect(open).toBeDisabled()
    await user.clear(input)
    await user.type(input, 'DTXSID50469320')
    await waitFor(() => expect(open).toBeEnabled())
    await user.click(open)
    await waitFor(() => expect(router.state.location.pathname).toBe('/studies/DTXSID50469320'))
  })

  it('sends / to the studies', async () => {
    const { router } = renderApp('/')
    await waitFor(() => expect(router.state.location.pathname).toBe('/studies'))
  })
})

describe('nextStepOf', () => {
  it('never suggests a destructive act', () => {
    expect(nextStepOf({ ...STATE_VALIDATION_ERRORS, legal_actions: ['RESET'] })).toBeNull()
    expect(nextStepOf({ ...STATE_VALIDATION_ERRORS, legal_actions: ['RESET', 'CLEAR_FILES'] })).toBeNull()
  })

  it('suggests processing only before the first run', () => {
    expect(nextStepOf({ ...STATE_APPROVED_STALE_SUMMARY, processed: false, readiness: undefined })).toMatchObject({ label: 'Process the study', module: 'P1' })
  })

  it('says nothing blocks publishing when the backend says so', () => {
    expect(nextStepOf({ ...STATE_APPROVED_STALE_SUMMARY, readiness: { publish: { ready: true, items: [] } } })).toMatchObject({ module: 'D1', label: expect.stringMatching(/nothing blocks/) as unknown })
  })
})
