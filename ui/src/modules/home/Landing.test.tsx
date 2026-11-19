import { screen, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it } from 'vitest'
import { M1_STUDIES } from '../../api/mocks/fixtures'
import { server } from '../../api/mocks/node'
import type { StudiesList } from '../../api/types'
import { MODULES } from '../../kit/modules'
import { renderApp } from '../../test/render'
import { setOnlyPartition } from '../m1/onlyPartition'

/** The first page (/): where to go, the studies set apart, where the studies stand, the steps. */

const group = M1_STUDIES.chemicals.find((c) => c.dtxsid === 'DTXSID1020431')!
const report = group.sessions.find((s) => s.kind === 'report')!
const members = group.sessions.filter((s) => s.kind === 'member')

const WITH_DEMO: StudiesList = {
  ...M1_STUDIES,
  chemicals: M1_STUDIES.chemicals.filter((c) => c.dtxsid !== 'DTXSID1020431'),
  partitions: [{ name: 'Demo', sessions: [{ id: report.id, role: 'finished', session: report, members }] }],
}

function serve(list: StudiesList) {
  server.use(http.get('/api/v2/studies', () => HttpResponse.json(list)))
}

const SOURCES = import.meta.glob<string>(['./*.ts', './*.tsx', '!./*.test.tsx'], { eager: true, query: '?raw', import: 'default' })

afterEach(() => setOnlyPartition(null))

describe('the first page', () => {
  it('is what / shows, and leads to the studies, the Bookshelf and the API page', async () => {
    const { user, router } = renderApp('/')
    const home = await screen.findByTestId('home')
    expect(within(home).getByRole('heading', { level: 2, name: 'Potency reports' })).toBeInTheDocument()
    expect(within(home).getByRole('link', { name: /Open the Bookshelf/ })).toHaveAttribute('href', '/Bookshelf')
    expect(within(home).getByRole('link', { name: /Open the API page/ })).toHaveAttribute('href', '/docs')
    await user.click(within(home).getByRole('button', { name: /Go to the studies/ }))
    expect(router.state.location.pathname).toBe('/studies')
  })

  it('counts the studies by the stage the backend serves, a report over studies not among them', async () => {
    renderApp('/')
    const standing = await screen.findByTestId('home-standing')
    const studies = [...M1_STUDIES.chemicals.flatMap((c) => c.sessions), ...M1_STUDIES.unassigned].filter((s) => s.kind !== 'report')
    const says = new Set(studies.map((s) => s.stands.say))
    for (const say of says) expect(await within(standing).findByText(say)).toBeInTheDocument()
    const first = [...says][0]!
    const count = studies.filter((s) => s.stands.say === first).length
    expect(within(standing).getByText(first).closest('.ant-space')).toHaveTextContent(`${count}${first}`)
  })

  it('shows the studies that are set apart, with links to them', async () => {
    serve(WITH_DEMO)
    renderApp('/')
    const demo = await screen.findByTestId('home-partition-Demo')
    expect(demo).toHaveTextContent('Set apart: Demo')
    expect(within(demo).getByText('Finished')).toBeInTheDocument()
    expect(within(demo).getByRole('link', { name: report.identity.name ?? report.id })).toHaveAttribute('href', `/studies/${report.id}`)
  })

  it('counts only the studies of the block when the list is reduced to it', async () => {
    serve(WITH_DEMO)
    setOnlyPartition('Demo')
    renderApp('/')
    const standing = await screen.findByTestId('home-standing')
    expect(within(standing).getByText(/Only the studies of “Demo” are counted/)).toBeInTheDocument()
    const others = new Set(WITH_DEMO.chemicals.flatMap((c) => c.sessions).map((s) => s.stands.say))
    const mine = new Set(members.map((s) => s.stands.say))
    for (const say of others) if (!mine.has(say)) expect(within(standing).queryByText(say)).toBeNull()
  })

  it('lists every step of a report with its purpose, and says which have no page yet', async () => {
    renderApp('/')
    const steps = await screen.findByTestId('home-steps')
    for (const m of MODULES.filter((m) => m.slug)) {
      expect(within(steps).getByText(m.title)).toBeInTheDocument()
      expect(within(steps).getByText(m.purpose)).toBeInTheDocument()
    }
    for (const built of ['dataset', 'process', 'writing', 'review']) expect(screen.queryByTestId(`home-not-built-${built}`)).toBeNull()
    expect(screen.getByTestId('home-not-built-files')).toHaveTextContent('page not built yet')
  })

  it('says so when the studies cannot be read, and still shows the rest', async () => {
    server.use(http.get('/api/v2/studies', () => HttpResponse.json({ error: { code: 'boom', say: 'The store could not be read.', fix: null, details: {} } }, { status: 500 })))
    renderApp('/')
    expect(await screen.findByText('The studies could not be read')).toBeInTheDocument()
    expect(screen.getByTestId('home-steps')).toBeInTheDocument()
  })

  it('addresses nobody and is American', () => {
    const second = /\b(you|your|yours|yourself)\b/i
    const british = /\b(\w*colour\w*|\w*behaviour\w*|analyse[ds]?|\w*(?:organi|summari|recogni)s(?:e[ds]?|ing|ation\w*)|cent(?:re|red)|programme|grey)\b/i
    for (const [file, source] of Object.entries(SOURCES)) {
      const visible = source.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:'"`])\/\/.*$/gm, '$1').replace(/^import .*$/gm, ' ')
      expect(second.test(visible), file).toBe(false)
      expect(british.test(visible), file).toBe(false)
    }
  })
})
