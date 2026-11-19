import { screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { M1_STUDIES, STATE_MEMBER_RAT } from '../../api/mocks/fixtures'
import { server } from '../../api/mocks/node'
import type { DryRun, StudiesList, StudyRow } from '../../api/types'
import { renderApp } from '../../test/render'
import { openList } from './testing'

/**
 * The demo path spec §3.5: a finished report and its live copy are set apart
 * in the list as "Demo", and each page of one links to the same page of the
 * other.
 */

const group = M1_STUDIES.chemicals.find((c) => c.dtxsid === 'DTXSID1020431')!
const report = group.sessions.find((s) => s.kind === 'report')!
const members = group.sessions.filter((s) => s.kind === 'member')

function asLive(row: StudyRow): StudyRow {
  const id = row.id.replace('DTXSID1020431', 'DTXSID1020431_live')
  return {
    ...row,
    id,
    relations: { ...row.relations, members: row.relations.members.map((m) => ({ ...m, id: m.id.replace('DTXSID1020431', 'DTXSID1020431_live') })) },
    stands: row.kind === 'member' ? { phase: 'VALIDATED', say: 'Files checked, not yet combined', next: { say: 'Combine the files into one dataset', fix: 'M3' } } : row.stands,
  }
}

const LIST: StudiesList = {
  ...M1_STUDIES,
  chemicals: M1_STUDIES.chemicals.filter((c) => c.dtxsid !== 'DTXSID1020431'),
  partitions: [
    {
      name: 'Demo',
      sessions: [
        { id: report.id, role: 'finished', session: report, members },
        { id: 'DTXSID1020431_live', role: 'live', session: asLive(report), members: members.map(asLive) },
      ],
    },
  ],
}

const DRY: DryRun = {
  act: 'reset_live_copy',
  strength: 'costly',
  deletes: [{ what: 'DTXSID1020431_live_rat', say: 'DTXSID1020431_live_rat: the combined dataset, 5 results sections' }],
  keeps: [{ what: 'DTXSID1020431', say: 'The finished report DTXSID1020431 and its studies: they are only read.' }],
  approvals_lost: [],
  cost: { say: 'To come back to where the live copy is now, each study is combined and processed again.' },
  reason_required: false,
}

function serveList() {
  server.use(http.get('/api/v2/studies', () => HttpResponse.json(LIST)))
}

describe('the Demo block of the studies list', () => {
  it('shows the finished report and its live copy side by side, and not again under their chemical', async () => {
    serveList()
    await openList()
    const demo = screen.getByTestId('partition-Demo')
    const finished = within(demo).getByTestId('partition-side-finished')
    const live = within(demo).getByTestId('partition-side-live')
    expect(finished).toHaveTextContent('Finished')
    expect(finished).toHaveTextContent('DTXSID1020431')
    expect(live).toHaveTextContent('Live')
    expect(live).toHaveTextContent('DTXSID1020431_live')
    expect(within(live).getByRole('list', { name: 'Studies of DTXSID1020431_live' })).toHaveTextContent('Next: Combine the files into one dataset')
    expect(document.querySelector('tr[data-row-key="chem:DTXSID1020431"]')).toBeNull()
  })

  it('offers the reset on the live side only, with the consequences from the backend', async () => {
    serveList()
    let reset = 0
    server.use(
      http.get('/api/v2/demo/DTXSID1020431/reset-preview', () => HttpResponse.json(DRY)),
      http.post('/api/v2/demo/DTXSID1020431/reset', () => {
        reset += 1
        return HttpResponse.json({ report: 'DTXSID1020431', copy: 'DTXSID1020431_live' })
      }),
    )
    const { user } = await openList()
    const demo = screen.getByTestId('partition-Demo')
    expect(within(within(demo).getByTestId('partition-side-finished')).queryByRole('button', { name: /Put the live copy back/ })).toBeNull()
    await user.click(within(within(demo).getByTestId('partition-side-live')).getByRole('button', { name: 'Put the live copy back to its start' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('the combined dataset, 5 results sections')
    expect(dialog).toHaveTextContent('they are only read')
    expect(reset).toBe(0)
    await user.click(within(dialog).getByRole('button', { name: 'Put it back' }))
    await waitFor(() => expect(reset).toBe(1))
  })

  it('"Show only this block" hides the other studies, in this browser, until all are shown again', async () => {
    serveList()
    const { user } = await openList()
    expect(document.querySelector('tr[data-row-key="chem:DTXSID5032498"]')).not.toBeNull()
    await user.click(screen.getByRole('switch', { name: 'Show only this block' }))
    await waitFor(() => expect(screen.queryByRole('table')).toBeNull())
    expect(document.body).not.toHaveTextContent('Triclosan')
    expect(screen.getByTestId('partition-Demo')).toBeInTheDocument()
    expect(window.localStorage.getItem('studies.onlyPartition')).toBe('Demo')
    // The Bookshelf's shelf page reads the same choice from a cookie.
    expect(document.cookie).toContain('bookshelf_only=Demo')
    expect(screen.getByTestId('others-hidden')).toHaveTextContent('The other studies are not shown.')
    await user.click(screen.getByRole('button', { name: 'Show all studies' }))
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(window.localStorage.getItem('studies.onlyPartition')).toBeNull()
    expect(document.cookie).not.toContain('bookshelf_only')
  })

  it('a session of the pair links to the same page of the other side', async () => {
    const liveRat = { ...STATE_MEMBER_RAT, demo: { partition: 'Demo', role: 'live', counterpart: 'DTXSID1020431_rat', counterpart_exists: true, report: 'DTXSID1020431_live' } }
    server.use(http.get('/api/v2/studies/DTXSID1020431_live_rat/state', () => HttpResponse.json({ ...liveRat, id: 'DTXSID1020431_live_rat' })))
    renderApp('/studies/DTXSID1020431_live_rat/process')
    const note = await screen.findByTestId('pair-note')
    expect(note).toHaveTextContent('Demo: live copy')
    expect(within(note).getByRole('link', { name: 'Switch to the finished report' })).toHaveAttribute('href', expect.stringContaining('/studies/DTXSID1020431_rat/process'))
    expect(note.textContent ?? '').not.toMatch(/\byou(r|rs)?\b/i)
  })
})
