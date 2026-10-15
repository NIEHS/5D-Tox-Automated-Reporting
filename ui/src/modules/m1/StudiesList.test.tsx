import { screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { M1_STUDIES } from '../../api/mocks/fixtures'
import type { StudiesList } from '../../api/types'
import { emptyM1Db } from '../../api/mocks/m1'
import { server } from '../../api/mocks/node'
import { renderApp } from '../../test/render'
import { DAMAGED_NOTE, expand, openList, queryRow, row } from './testing'

/** S1 Studies list: M1 spec §12 criteria 1, 3–11 (2 needs the real backend). */

describe('S1 the studies list', () => {
  it('AC1: one row per chemical, in the backend\'s order, and a last group for sessions tied to no chemical', async () => {
    await openList()
    const tops = [...document.querySelectorAll('tr.m1-chemical-row')].map((r) => r.getAttribute('data-row-key'))
    expect(tops).toEqual([...M1_STUDIES.chemicals.map((c) => `chem:${c.dtxsid}`), 'unassigned'])
    expect(row('unassigned')).toHaveTextContent('Sessions not tied to a chemical')
    expect(row('unassigned')).toHaveTextContent('+ 1 other session')
    expect(document.body).not.toHaveTextContent('_prompts')
  })

  it('AC3: the words on a row are the backend\'s, the same the study page shows', async () => {
    const { user } = await openList()
    const triclosan = M1_STUDIES.chemicals.find((c) => c.dtxsid === 'DTXSID5032498')!.sessions[0]!
    expect(within(row('chem:DTXSID5032498')).getByTestId('stands')).toHaveTextContent(triclosan.stands.say)
    await user.click(within(row('chem:DTXSID5032498')).getByRole('button', { name: 'Open' }))
    const card = await screen.findByTestId('where-it-stands')
    expect(card).toHaveTextContent(triclosan.stands.say)
    expect(screen.getAllByTestId('phase')[0]).toHaveTextContent(triclosan.stands.say)
  })

  it('AC4, AC5: a report over two studies shows no phase and no "No files yet"; its rat, mouse and published content as children', async () => {
    const { user } = await openList()
    const top = row('chem:DTXSID1020431')
    expect(top).toHaveTextContent('Report over 2 studies')
    expect(top).toHaveTextContent('NIEHS-13 · 2026 Apr')
    expect(top).not.toHaveTextContent('No files yet')
    expect(within(top).getByTestId('phase')).toHaveAttribute('data-phase', 'none')
    expect(top).toHaveTextContent('+ 2 studies of the report, 1 published content')
    expect(queryRow('DTXSID1020431_rat')).toBeNull()
    await expand('chem:DTXSID1020431', user)
    expect(row('DTXSID1020431_rat')).toHaveTextContent('Rat study, part of a report')
    expect(row('DTXSID1020431_rat')).toHaveTextContent('Data reviewed')
    expect(row('DTXSID1020431_rat')).toHaveTextContent("Next: Review the report's sections")
    expect(row('DTXSID1020431_mouse')).toHaveTextContent('Mouse study, part of a report')
    const comp = row('DTXSID1020431_published')
    expect(comp).toHaveTextContent('Published content')
    expect(within(comp).getByTestId('phase')).toHaveAttribute('data-phase', 'none')
    expect(comp).not.toHaveTextContent(/No files yet|Next:/)
  })

  it('AC5: every published-content and report row shows no phase', async () => {
    const { user } = await openList()
    await expand('chem:DTXSID50469320', user)
    await expand('chem:DTXSID1020431', user)
    for (const id of ['DTXSID50469320_published', 'DTXSID1020431_published']) {
      expect(within(row(id)).getByTestId('phase')).toHaveAttribute('data-phase', 'none')
      expect(row(id)).not.toHaveTextContent('No files yet')
    }
  })

  it('AC6: PFHxSAm\'s notebook build is an "Other session" under the chemical, with a warning', async () => {
    const { user } = await openList()
    await expand('chem:DTXSID50469320', user)
    const nb = row('DTXSID50469320_nb')
    expect(nb).toHaveTextContent('Other session')
    expect(within(nb).getByLabelText(/Note: Made by a tool/)).toBeInTheDocument()
  })

  it('AC7: the Bookshelf cell is a draft link opening in a new tab; a member study says it is part of the parent\'s book', async () => {
    const { user } = await openList()
    const link = within(row('chem:DTXSID50469320')).getByRole('link', { name: /On the Bookshelf \(draft\)/ })
    expect(link).toHaveAttribute('href', '/Bookshelf/DTXSID50469320')
    expect(link).toHaveAttribute('target', '_blank')
    await expand('chem:DTXSID1020431', user)
    expect(row('DTXSID1020431_rat')).toHaveTextContent("Part of DTXSID1020431's book")
  })

  it('AC8: searching by CASRN keeps one group; by a member\'s id keeps its group, expanded; clearing brings every row back', async () => {
    const { user } = await openList()
    const search = screen.getByRole('searchbox', { name: 'Find a study' })
    await user.type(search, '41997-13-1')
    expect([...document.querySelectorAll('tr.m1-chemical-row')].map((r) => r.getAttribute('data-row-key'))).toEqual(['chem:DTXSID50469320'])
    await user.clear(search)
    await user.type(search, 'DTXSID1020431_rat')
    expect([...document.querySelectorAll('tr.m1-chemical-row')].map((r) => r.getAttribute('data-row-key'))).toEqual(['chem:DTXSID1020431'])
    expect(row('DTXSID1020431_rat')).toBeVisible()
    await user.clear(search)
    expect(document.querySelectorAll('tr.m1-chemical-row')).toHaveLength(M1_STUDIES.chemicals.length + 1)
  })

  it('AC9: no row has a delete control', async () => {
    const { user } = await openList()
    for (const c of M1_STUDIES.chemicals) if (c.sessions.length > 1) await expand(`chem:${c.dtxsid}`, user)
    expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(/delete/i)
  })

  it('AC10: with an empty store, says "No studies yet" and offers New study', async () => {
    emptyM1Db()
    const { user, router } = renderApp('/studies')
    expect(await screen.findByText('No studies yet')).toBeInTheDocument()
    const buttons = screen.getAllByRole('button', { name: /New study/ })
    await user.click(buttons[buttons.length - 1]!)
    await waitFor(() => expect(router.state.location.pathname).toBe('/studies/new'))
  })

  it('AC11: each "Next:" link opens the module it names, for that study', async () => {
    await openList()
    const cases: [string, string][] = [
      ['chem:DTXSID5032498', '/studies/DTXSID5032498/dataset'],
      ['chem:DTXSID1021952', '/studies/DTXSID1021952/files'],
      ['chem:DTXSID4028880', '/studies/DTXSID4028880/review'],
      ['chem:DTXSID9000001', '/studies/DTXSID9000001/files'],
    ]
    for (const [key, href] of cases) {
      const s = within(row(key)).getByTestId('stands')
      expect(within(s).getByRole('link')).toHaveAttribute('href', href)
    }
  })

  it('a chemical with no study says so and offers to create one with the DTXSID filled in', async () => {
    const { user, router } = await openList()
    const top = row('chem:DTXSID8031865')
    expect(top).toHaveTextContent('No study of this chemical yet')
    await user.click(within(top).getByRole('button', { name: /Create a study/ }))
    await waitFor(() => expect(router.state.location.search).toBe('?dtxsid=DTXSID8031865'))
    expect(await screen.findByRole('textbox', { name: "The chemical's DTXSID" })).toHaveValue('DTXSID8031865')
  })

  it('a missing name or CASRN is a pending mark, never blank', async () => {
    await openList()
    const r = row('chem:DTXSID9000001')
    expect(within(r).getByRole('button', { name: 'name is missing; show why' })).toHaveTextContent('[name pending]')
    expect(within(r).getByRole('button', { name: 'CASRN is missing; show why' })).toBeInTheDocument()
  })

  it('shows the format\'s reason on hover, and the published book\'s tag', async () => {
    const { user } = await openList()
    const f = within(row('chem:DTXSID50469320')).getByTestId('format')
    expect(f).toHaveTextContent('NIEHS Report, March 2023')
    expect(f).toHaveTextContent('NIEHS-10 · 2023 Mar')
    await user.hover(f)
    expect(await screen.findByText(/This chemical has a published report, NIEHS-10/)).toBeInTheDocument()
  })

  it('review 1 (spec S1): a session whose format the backend could not read still lists: "[format pending]" with the note, and the warning icon', async () => {
    const list = structuredClone(M1_STUDIES) as StudiesList
    const triclosan = list.chemicals.find((c) => c.dtxsid === 'DTXSID5032498')!.sessions[0]!
    triclosan.format = null
    triclosan.notes = [DAMAGED_NOTE('DTXSID5032498')]
    server.use(http.get('/api/v2/studies', () => HttpResponse.json(list)))
    const { user } = await openList()
    const r = row('chem:DTXSID5032498')
    const pending = within(within(r).getByTestId('format')).getByRole('button', { name: 'format is missing; show why' })
    expect(pending).toHaveTextContent('[format pending]')
    expect(within(r).getByLabelText(/^Note: One of this study's saved files is damaged/)).toBeInTheDocument()
    await user.click(pending)
    expect(await screen.findByText(DAMAGED_NOTE('DTXSID5032498').say)).toBeInTheDocument()
    // the other rows are unaffected
    expect(within(row('chem:DTXSID50469320')).getByTestId('format')).toHaveTextContent('NIEHS Report, March 2023')
  })

  it('explains a list that cannot be read, in plain words', async () => {
    server.use(http.get('/api/v2/studies', () => HttpResponse.error()))
    renderApp('/studies')
    expect(await screen.findByText('The list of studies could not be read')).toBeInTheDocument()
    expect(screen.getByText(/could not be reached/)).toBeInTheDocument()
  })
})
