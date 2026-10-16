import { focusManager } from '@tanstack/react-query'
import { act, screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { M1_CHEMICALS, M1_DETAILS, STATE_APPROVED, STATE_RUNNING } from '../../api/mocks/fixtures'
import type { StudyDetail } from '../../api/types'
import { emptyM1Db, removeMockStudy, touchMockStudy } from '../../api/mocks/m1'
import { server } from '../../api/mocks/node'
import { running } from '../../api/mocks/runs'
import { renderApp } from '../../test/render'
import { DAMAGED_NOTE, openStudyPage } from './testing'

/** The study's pages: in a drawer on a narrow window (jsdom's). */
async function studyMenu(user: ReturnType<typeof renderApp>['user']) {
  await user.click(screen.getByRole('button', { name: /Pages of this study/ }))
  return within(await screen.findByRole('dialog', { name: /Pages of this study/ }))
}

/** S3 Study page, S4 Delete, S5 No such study: M1 spec §12 criteria 27–41. */

describe('S3 the study page', () => {
  it('AC27: PFHxSAm: identity, where it stands with the next step, its format and pin, the Bookshelf, related sessions', async () => {
    await openStudyPage('DTXSID50469320')
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Perfluorohexanesulfonamide')
    const chem = screen.getByTestId('chemical')
    expect(chem).toHaveTextContent('41997-13-1')
    expect(chem).toHaveTextContent('DTXSID50469320')
    const stands = screen.getByTestId('where-it-stands')
    expect(stands).toHaveTextContent('Data reviewed')
    expect(within(stands).getByRole('link', { name: /Review the report's sections/ })).toHaveAttribute('href', '/studies/DTXSID50469320/review')
    const fmt = screen.getByTestId('format-card')
    expect(fmt).toHaveTextContent('NIEHS Report, as published in March 2023')
    expect(fmt).toHaveTextContent("This study's own definition, under templates/studies/DTXSID50469320/")
    expect(within(screen.getByTestId('format-pin')).getByRole('link', { name: 'Method and report definition' })).toHaveAttribute('href', '/studies/DTXSID50469320/pins')
    expect(screen.getByTestId('format-pin')).toHaveTextContent('Not pinned yet')
    expect(within(screen.getByTestId('bookshelf')).getByRole('link', { name: /On the Bookshelf \(draft\)/ })).toHaveAttribute('target', '_blank')
    const rel = screen.getByTestId('related')
    expect(rel).toHaveTextContent('DTXSID50469320_published')
    expect(rel).toHaveTextContent('DTXSID50469320_nb')
    // the shell's workflow panels follow
    expect(screen.getByText('Steps')).toBeInTheDocument()
  })

  it('AC6: the notebook\'s session warns that it uses the 2026 format and not NIEHS-10\'s', async () => {
    await openStudyPage('DTXSID50469320_nb')
    const b = screen.getByTestId('kind-banner')
    expect(b).toHaveTextContent("is not a chemical's DTXSID")
    expect(b).toHaveTextContent("Its report uses the 2026 format; a study under DTXSID50469320 would use NIEHS-10's format.")
    expect(screen.getByTestId('chemical')).toHaveTextContent('taken from the session id')
    expect(screen.getByTestId('format-pin')).toHaveTextContent('Tracks the current definition.')
  })

  it('AC28: published content: the read-only banner with its links, no workflow page, no delete', async () => {
    const { user } = await openStudyPage('DTXSID50469320_published')
    const b = screen.getByTestId('kind-banner')
    expect(b).toHaveTextContent("It can't be changed or deleted here.")
    expect(within(b).getByRole('link', { name: 'Read it on the Bookshelf' })).toHaveAttribute('href', '/Bookshelf/DTXSID50469320_published')
    expect(within(b).getByRole('link', { name: /The generated study: DTXSID50469320/ })).toHaveAttribute('href', '/studies/DTXSID50469320')
    expect(screen.queryByText('Steps')).not.toBeInTheDocument()
    const menu = await studyMenu(user)
    expect(menu.getByRole('link', { name: 'Overview' })).toBeInTheDocument()
    expect(menu.queryByRole('link', { name: 'Study files' })).not.toBeInTheDocument()
    expect(menu.queryByRole('link', { name: 'Review the report' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete this study…' })).toBeDisabled()
    expect(screen.getByTestId('delete-card')).toHaveTextContent("This is the published book's own content")
  })

  it('AC28: a data page of published content opened by its address is not offered', async () => {
    renderApp('/studies/DTXSID50469320_published/files')
    expect(await screen.findByText('Study files is not offered here.')).toBeInTheDocument()
  })

  it('AC29: a rat study names its report and its mouse sibling, with links; delete disabled with the reason beside it', async () => {
    await openStudyPage('DTXSID1020431_rat')
    const b = screen.getByTestId('kind-banner')
    expect(b).toHaveTextContent('This is the rat study of the report DTXSID1020431')
    expect(within(b).getByRole('link', { name: /The report DTXSID1020431/ })).toHaveAttribute('href', '/studies/DTXSID1020431')
    expect(within(b).getByRole('link', { name: /DTXSID1020431_mouse/ })).toHaveAttribute('href', '/studies/DTXSID1020431_mouse')
    expect(screen.getByRole('button', { name: 'Delete this study…' })).toBeDisabled()
    expect(screen.getByTestId('delete-card')).toHaveTextContent('This is the rat study of the report DTXSID1020431. Deleting it would break that report.')
  })

  it('AC30: the report lists its two member studies, each with where it stands and Open', async () => {
    const { user } = await openStudyPage('DTXSID1020431')
    const members = screen.getByTestId('members')
    for (const id of ['DTXSID1020431_rat', 'DTXSID1020431_mouse']) {
      const r = within(members).getByText(id).closest('tr') as HTMLElement
      expect(r).toHaveTextContent('Data reviewed')
      expect(within(r).getByRole('link', { name: `Open ${id}` })).toHaveAttribute('href', `/studies/${id}`)
    }
    expect(screen.queryByText('No files yet')).not.toBeInTheDocument()
    // a report has no data pages of its own
    const menu = await studyMenu(user)
    expect(menu.queryByRole('link', { name: 'Study files' })).not.toBeInTheDocument()
    expect(menu.queryByRole('link', { name: 'Process' })).not.toBeInTheDocument()
    expect(menu.getByRole('link', { name: 'Review the report' })).toBeInTheDocument()
  })

  it('review 1 (spec S1/S3): a study whose format could not be read still opens: the note, and "[format pending]" in the format card', async () => {
    const d = structuredClone<StudyDetail>(M1_DETAILS['DTXSID5032498']!)
    d.format = null
    d.detail.format = null
    d.notes = [DAMAGED_NOTE('DTXSID5032498')]
    server.use(http.get('/api/v2/studies/DTXSID5032498', () => HttpResponse.json(d)))
    await openStudyPage('DTXSID5032498')
    const card = screen.getByTestId('format-card')
    expect(within(card).getByRole('button', { name: 'format is missing; show why' })).toHaveTextContent('[format pending]')
    expect(within(card).getByTestId('format-unread')).toHaveTextContent('The report format could not be read')
    // the page's note says why, and the rest of the page is there
    expect(screen.getAllByRole('alert').some((a) => a.textContent?.includes(DAMAGED_NOTE('DTXSID5032498').say))).toBe(true)
    expect(screen.getByTestId('chemical')).toBeInTheDocument()
    expect(screen.getByTestId('delete-card')).toBeInTheDocument()
  })

  it('review 2: a report whose member folder is missing still opens; the member says it is missing, with no Open', async () => {
    const d = structuredClone<StudyDetail>(M1_DETAILS['DTXSID1020431']!)
    d.detail.members = d.detail.members!.map((m) => (m.id === 'DTXSID1020431_mouse' ? { id: m.id, key: 'mouse', exists: false as const } : m))
    server.use(http.get('/api/v2/studies/DTXSID1020431', () => HttpResponse.json(d)))
    await openStudyPage('DTXSID1020431')
    const members = screen.getByTestId('members')
    const mouse = within(members).getByText('DTXSID1020431_mouse').closest('tr') as HTMLElement
    expect(mouse).toHaveTextContent("Missing: this study's folder is not in the store.")
    expect(within(mouse).queryByRole('link')).not.toBeInTheDocument()
    expect(within(mouse).queryByRole('button', { name: 'Open' })).not.toBeInTheDocument()
    const rat = within(members).getByText('DTXSID1020431_rat').closest('tr') as HTMLElement
    expect(within(rat).getByRole('link', { name: 'Open DTXSID1020431_rat' })).toBeInTheDocument()
  })

  it('AC31: a missing short name is pending, linking to Study facts', async () => {
    const { user } = await openStudyPage('DTXSID50469320')
    const p = within(screen.getByTestId('chemical')).getByRole('button', { name: 'short name is missing; show why' })
    expect(p).toHaveTextContent('[short name pending]')
    await user.click(p)
    expect(await screen.findByRole('link', { name: 'Fill it in: Study facts' })).toHaveAttribute('href', '/studies/DTXSID50469320/facts')
  })

  it('AC33: a session with no identity shows "[name pending]" and Look up the chemical; confirming fills it', async () => {
    const { user } = await openStudyPage('DTXSID8031865_scratch')
    expect(within(screen.getByTestId('chemical')).getByRole('button', { name: 'name is missing; show why' })).toHaveTextContent('[name pending]')
    await user.click(screen.getByRole('button', { name: 'Look up the chemical' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Perfluorooctanoic acid')).toBeInTheDocument()
    const save = within(dialog).getByRole('button', { name: 'Save this identity' })
    expect(save).toBeDisabled()
    await user.click(within(dialog).getByRole('checkbox', { name: /This is the chemical studied under/ }))
    await user.click(save)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(screen.getByTestId('chemical')).toHaveTextContent('335-67-1'))
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Perfluorooctanoic acid')
    expect(screen.getByTestId('identity-source')).toHaveTextContent('Confirmed by a person from a PubChem lookup')
    expect(screen.queryByRole('button', { name: 'Look up the chemical' })).not.toBeInTheDocument()
  })

  it('2026-10-16 (revised): Look up the chemical, when PubChem gives no CAS number: asked for, optional; a typed one must be valid; the page then says it was stated by a person', async () => {
    const pfoa = structuredClone(M1_CHEMICALS['DTXSID8031865']!)
    pfoa.identity.casrn = null
    pfoa.needs = ['casrn']
    server.use(http.get('/api/v2/chemicals/DTXSID8031865', () => HttpResponse.json(pfoa)))
    const { user } = await openStudyPage('DTXSID8031865_scratch')
    await user.click(screen.getByRole('button', { name: 'Look up the chemical' }))
    const dialog = await screen.findByRole('dialog')
    const ask = await within(dialog).findByTestId('casrn-ask')
    // no needs_say served here: the screen's own words
    expect(ask).toHaveTextContent('PubChem gives no CAS number for Perfluorooctanoic acid. If you have it from a source you trust')
    expect(ask).toHaveTextContent('Without it, the study shows "[CASRN pending]".')
    const confirm = within(dialog).getByRole('checkbox', { name: /This is the chemical studied under/ })
    const save = within(dialog).getByRole('button', { name: 'Save this identity' })
    // empty is allowed: the tick opens
    await waitFor(() => expect(confirm).toBeEnabled())
    expect(save).toBeDisabled()
    const field = within(ask).getByRole('textbox', { name: 'CAS number (optional)' })
    await user.type(field, '335-67-2')
    expect(within(ask).getByText("This CASRN's check digit doesn't match; a digit is probably mistyped.")).toBeInTheDocument()
    expect(confirm).toBeDisabled()
    expect(save).toBeDisabled()
    await user.clear(field)
    await user.type(field, '335-67-1')
    await waitFor(() => expect(confirm).toBeEnabled())
    expect(save).toBeDisabled()
    await user.click(confirm)
    expect(save).toBeEnabled()
    await user.click(save)
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(screen.getByTestId('chemical')).toHaveTextContent('335-67-1'))
    expect(screen.getByTestId('identity-source')).toHaveTextContent('CAS number stated by a person (the lookup gave none).')
  })

  it('2026-10-16 (revised): Look up the chemical with no CAS number and none typed: Save needs only the tick; the name fills, the CAS number stays pending', async () => {
    const pfoa = structuredClone(M1_CHEMICALS['DTXSID8031865']!)
    pfoa.identity.casrn = null
    pfoa.needs = ['casrn']
    let sent: { casrn: string | null; source: Record<string, unknown> } | null = null
    server.use(http.get('/api/v2/chemicals/DTXSID8031865', () => HttpResponse.json(pfoa)))
    server.events.on('request:start', async ({ request }) => {
      if (request.method === 'PUT') sent = ((await request.clone().json()) as { identity: typeof sent }).identity
    })
    try {
      const { user } = await openStudyPage('DTXSID8031865_scratch')
      await user.click(screen.getByRole('button', { name: 'Look up the chemical' }))
      const dialog = await screen.findByRole('dialog')
      await within(dialog).findByTestId('casrn-ask')
      const confirm = within(dialog).getByRole('checkbox', { name: /This is the chemical studied under/ })
      await waitFor(() => expect(confirm).toBeEnabled())
      await user.click(confirm)
      await user.click(within(dialog).getByRole('button', { name: 'Save this identity' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
      await waitFor(() => expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Perfluorooctanoic acid'))
      expect(sent!.casrn).toBeNull()
      expect(sent!.source).not.toHaveProperty('casrn_from')
      const chem = screen.getByTestId('chemical')
      expect(within(chem).getByRole('button', { name: 'CASRN is missing; show why' })).toHaveTextContent('[CASRN pending]')
      expect(screen.queryByRole('button', { name: 'Look up the chemical' })).not.toBeInTheDocument()
    } finally {
      server.events.removeAllListeners()
    }
  })

  it('2026-10-16 (revised): Look up the chemical, when PubChem gives no name: no name field, Save closed, and the dialog says the study stays pending', async () => {
    const pfoa = structuredClone(M1_CHEMICALS['DTXSID8031865']!)
    pfoa.identity.name = ''
    let puts = 0
    server.use(
      http.get('/api/v2/chemicals/DTXSID8031865', () => HttpResponse.json(pfoa)),
      http.put('/api/v2/studies/DTXSID8031865_scratch/identity', () => {
        puts++
        return HttpResponse.json({}, { status: 500 })
      }),
    )
    const { user } = await openStudyPage('DTXSID8031865_scratch')
    await user.click(screen.getByRole('button', { name: 'Look up the chemical' }))
    const dialog = await screen.findByRole('dialog')
    const why = await within(dialog).findByTestId('identity-no-name')
    expect(why).toHaveTextContent('PubChem found a compound for DTXSID8031865 but gives no name for it')
    expect(why).toHaveTextContent('Nothing is changed: the study keeps its name and CAS number pending')
    expect(within(dialog).queryByTestId('casrn-ask')).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('textbox')).not.toBeInTheDocument()
    const save = within(dialog).getByRole('button', { name: 'Save this identity' })
    expect(save).toBeDisabled()
    await user.click(save)
    expect(puts).toBe(0)
    await user.click(within(dialog).getByRole('button', { name: 'Close; keep it pending' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Look up the chemical' })).toBeInTheDocument()
  })

  it('2026-10-16 (revised): Look up the chemical, when PubChem does not know the DTXSID or cannot be reached: says the study stays pending; nothing is sent', async () => {
    let puts = 0
    let reachable = false
    server.use(
      http.get('/api/v2/chemicals/DTXSID8031865', () =>
        reachable
          ? HttpResponse.json({ error: { code: 'identity_not_found', status: 404, message: 'x', say: 'PubChem has no chemical with the DTXSID DTXSID8031865.', fix: null, details: {} } }, { status: 404 })
          : HttpResponse.json({ error: { code: 'identity_lookup_unreachable', status: 503, message: 'x', say: 'The chemical lookup service (PubChem) could not be reached. Nothing was created.', fix: null, details: {} } }, { status: 503 }),
      ),
      http.put('/api/v2/studies/DTXSID8031865_scratch/identity', () => {
        puts++
        return HttpResponse.json({}, { status: 500 })
      }),
    )
    const { user } = await openStudyPage('DTXSID8031865_scratch')
    await user.click(screen.getByRole('button', { name: 'Look up the chemical' }))
    const dialog = await screen.findByRole('dialog')
    const down = await within(dialog).findByTestId('lookup-unreachable')
    expect(down).toHaveTextContent('Nothing is changed: the study keeps its name and CAS number pending')
    reachable = true
    await user.click(within(down).getByRole('button', { name: 'Try again' }))
    const nf = await within(dialog).findByTestId('lookup-not-found')
    expect(nf).toHaveTextContent('PubChem has no chemical with the DTXSID DTXSID8031865.')
    expect(nf).toHaveTextContent('can be looked up again later from this page')
    expect(within(dialog).getByRole('button', { name: 'Save this identity' })).toBeDisabled()
    await user.click(within(dialog).getByRole('button', { name: 'Close; keep it pending' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(puts).toBe(0)
  })

  it('2026-10-16 (revised): a study created with its chemical pending: "[name pending]", "[CASRN pending]", the pending provenance, and Look up the chemical fills it', async () => {
    const check = (await (await fetch('/api/v2/studies/DTXSID7020182/creation-check')).json()) as { format: { definition: string; hash: string } }
    const made = await fetch('/api/v2/studies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dtxsid: 'DTXSID7020182', identity: null, identity_pending: true, confirmed: true, dtxsid_checked_by_person: true, format_seen: check.format }),
    })
    expect(made.status).toBe(201)
    expect(((await made.json()) as StudyDetail).identity.source.kind).toBe('pending')
    const { user } = await openStudyPage('DTXSID7020182')
    const chem = screen.getByTestId('chemical')
    expect(within(chem).getByRole('button', { name: 'name is missing; show why' })).toHaveTextContent('[name pending]')
    expect(within(chem).getByRole('button', { name: 'CASRN is missing; show why' })).toHaveTextContent('[CASRN pending]')
    expect(screen.getByTestId('identity-source')).toHaveTextContent('Pending: the study was created before its chemical was looked up. Look it up below.')

    await user.click(within(chem).getByRole('button', { name: 'Look up the chemical' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText('Bisphenol A')).toBeInTheDocument()
    // Bisphenol A's fixture: PubChem does not list the DTXSID; the check tick comes first
    await user.click(within(dialog).getByRole('checkbox', { name: /I checked the DTXSID DTXSID7020182/ }))
    await user.click(within(dialog).getByRole('checkbox', { name: /This is the chemical studied under DTXSID7020182/ }))
    await user.click(within(dialog).getByRole('button', { name: 'Save this identity' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() => expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Bisphenol A'))
    expect(screen.getByTestId('chemical')).toHaveTextContent('80-05-7')
    expect(screen.getByTestId('identity-source')).toHaveTextContent('Confirmed by a person from a PubChem lookup')
    expect(screen.queryByRole('button', { name: 'Look up the chemical' })).not.toBeInTheDocument()
  })

  it('a CAS number a person stated is said so on the page; one from the lookup is not', async () => {
    const d = structuredClone<StudyDetail>(M1_DETAILS['DTXSID50469320']!)
    d.identity.source = { kind: 'lookup', service: 'PubChem', confirmed_at: '2026-10-16T09:00:00Z', casrn_from: 'person' }
    server.use(http.get('/api/v2/studies/DTXSID50469320', () => HttpResponse.json(d)))
    await openStudyPage('DTXSID50469320')
    expect(screen.getByTestId('identity-source')).toHaveTextContent(
      'Confirmed by a person from a PubChem lookup on 16 Oct 2026. CAS number stated by a person (the lookup gave none).',
    )
  })

  it('AC33: the lookup is not offered on a session that has an identity, nor on one whose id names no chemical', async () => {
    await openStudyPage('DTXSID50469320')
    expect(screen.queryByRole('button', { name: 'Look up the chemical' })).not.toBeInTheDocument()
  })

  it('AC33 (DTXSID_TEST): no identity and no chemical in the id: "[name pending]", and says why it cannot be looked up', async () => {
    await openStudyPage('DTXSID_TEST')
    expect(within(screen.getByTestId('chemical')).getByRole('button', { name: 'name is missing; show why' })).toBeInTheDocument()
    expect(screen.getByTestId('chemical')).toHaveTextContent("this session's id names no chemical")
  })

  it('AC38: while Process runs, the next step is replaced by "Process is running…", and delete is disabled with the reason', async () => {
    running.set('DTXSID50469320', '2026-10-14T09:00:00+00:00')
    server.use(http.get('/api/v2/studies/DTXSID50469320/state', () => HttpResponse.json(STATE_RUNNING)))
    renderApp('/studies/DTXSID50469320')
    expect(await screen.findByTestId('run-in-flight')).toHaveTextContent(/Process is running on this study since/)
    expect(screen.getByRole('button', { name: 'Delete this study…' })).toBeDisabled()
    expect(screen.getByTestId('delete-card')).toHaveTextContent(/Process is running on this study \(since .*\)\. Wait for it to finish\./)
  })

  it('reads where it stands from the state when the state serves it (R2), and the shell shows the same words', async () => {
    server.use(
      http.get('/api/v2/studies/DTXSID50469320/state', () =>
        HttpResponse.json({ ...STATE_APPROVED, stands: { phase: 'APPROVED', say: 'Served words', next: { say: 'Do the served thing', fix: 'D2' } } }),
      ),
    )
    renderApp('/studies/DTXSID50469320')
    const card = await screen.findByTestId('where-it-stands')
    await waitFor(() => expect(card).toHaveTextContent('Served words'))
    expect(within(card).getByRole('link', { name: /Do the served thing/ })).toHaveAttribute('href', '/studies/DTXSID50469320/writing')
  })
})

describe('S5 no such study', () => {
  it('AC32: an absent DTXSID: "There is no study…", Create a study of this chemical; the list is unchanged', async () => {
    const before = await (await fetch('/api/v2/studies')).text()
    const { user, router } = renderApp('/studies/DTXSID7020182')
    expect(await screen.findByText('There is no study DTXSID7020182. It may have been deleted.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Create a study of this chemical' }))
    await waitFor(() => expect(router.state.location.search).toBe('?dtxsid=DTXSID7020182'))
    const after = await (await fetch('/api/v2/studies')).text()
    const chems = (t: string) => (JSON.parse(t) as { chemicals: unknown }).chemicals
    expect(chems(after)).toEqual(chems(before))
  })

  it('AC32: "foo" is not a study id; Back to studies; no create offered', async () => {
    renderApp('/studies/foo')
    expect(await screen.findByText("'foo' is not a study id.")).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to studies' })).toBeInTheDocument()
    expect(screen.queryByText('Create a study of this chemical')).not.toBeInTheDocument()
  })

  it('a suffixed id that does not exist offers no create (it is not a chemical\'s DTXSID)', async () => {
    renderApp('/studies/DTXSID7020182_rat')
    expect(await screen.findByText(/There is no study DTXSID7020182_rat/)).toBeInTheDocument()
    expect(screen.queryByText('Create a study of this chemical')).not.toBeInTheDocument()
  })

  it('F8: deleted in another tab, the page says "This study was deleted." when the window comes back into focus', async () => {
    await openStudyPage('DTXSID5032498')
    removeMockStudy('DTXSID5032498')
    try {
      // the app's query client re-reads on window focus (kit/queryClient.ts); so does the tests'
      act(() => {
        focusManager.setFocused(false)
        focusManager.setFocused(true)
      })
      expect(await screen.findByText('This study was deleted.')).toBeInTheDocument()
      expect(screen.queryByText(/It may have been deleted/)).not.toBeInTheDocument()
    } finally {
      act(() => focusManager.setFocused(undefined))
    }
  })

  it('F8: the study\'s own read answering 404 first (the state not yet re-read) still says "This study was deleted."', async () => {
    const { queryClient } = await openStudyPage('DTXSID5032498')
    removeMockStudy('DTXSID5032498')
    await queryClient.invalidateQueries({ queryKey: ['study', 'DTXSID5032498', 'detail'] })
    expect(await screen.findByText('This study was deleted.')).toBeInTheDocument()
  })

  it('F8: an id never seen keeps the plain not-found words', async () => {
    renderApp('/studies/DTXSID7020182')
    expect(await screen.findByText('There is no study DTXSID7020182. It may have been deleted.')).toBeInTheDocument()
    expect(screen.queryByText('This study was deleted.')).not.toBeInTheDocument()
  })

  it('AC40: a page open on a study deleted elsewhere says "This study was deleted" on its next read', async () => {
    const { queryClient } = await openStudyPage('DTXSID5032498')
    removeMockStudy('DTXSID5032498')
    await queryClient.invalidateQueries()
    expect(await screen.findByText('This study was deleted.')).toBeInTheDocument()
  })
})

describe('S4 delete', () => {
  async function openDialog(id: string) {
    const r = await openStudyPage(id)
    await r.user.click(screen.getByRole('button', { name: 'Delete this study…' }))
    const dialog = await screen.findByRole('dialog')
    return { ...r, dialog, typed: () => within(dialog).getByLabelText('Type the study id to confirm'), ok: () => within(dialog).getByRole('button', { name: 'Delete for good' }) }
  }

  it('AC34: the dialog lists what is deleted, what stays, and the approvals lost by name', async () => {
    const { dialog } = await openDialog('DTXSID2029905')
    expect(dialog).toHaveTextContent('Delete DTXSID2029905 for good?')
    expect(dialog).toHaveTextContent('This cannot be undone.')
    const del = within(dialog).getByRole('region', { name: 'It will delete' })
    for (const w of ["The study's data files", 'The integrated dataset', 'report sections', 'What people stated', 'history']) expect(del).toHaveTextContent(w)
    const keeps = within(dialog).getByRole('region', { name: 'It will keep' })
    expect(keeps).toHaveTextContent('output/DTXSID2029905/')
    expect(keeps).toHaveTextContent('templates/studies/DTXSID2029905/')
    const lost = within(dialog).getByRole('region', { name: 'Approvals that will be lost' })
    for (const t of ['Background', 'Body Weight', 'Organ Weight']) expect(lost).toHaveTextContent(t)
  })

  it('AC34 (the contract\'s preview): PFHxSAm keeps its published content and other session, and says what it costs', async () => {
    const { dialog } = await openDialog('DTXSID50469320')
    expect(dialog).toHaveTextContent("The published book's content, DTXSID50469320_published")
    expect(dialog).toHaveTextContent('The other session of this chemical, DTXSID50469320_nb')
    expect(dialog).toHaveTextContent('It can be rebuilt only from the command line')
  })

  it('AC35: Delete for good is enabled only for the exact id (spaces around it allowed, case matters)', async () => {
    const { user, typed, ok } = await openDialog('DTXSID5032498')
    expect(ok()).toBeDisabled()
    for (const wrong of ['dtxsid5032498', 'DTXSID503249', 'DTXSID50324980']) {
      await user.clear(typed())
      await user.type(typed(), wrong)
      expect(ok()).toBeDisabled()
    }
    await user.clear(typed())
    await user.type(typed(), 'DTXSID5032498')
    expect(ok()).toBeEnabled()
    await user.clear(typed())
    await user.type(typed(), '  DTXSID5032498 ')
    expect(ok()).toBeEnabled()
  })

  it('AC36: Cancel closes the dialog and the study is unchanged', async () => {
    const { user, dialog } = await openDialog('DTXSID5032498')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect((await fetch('/api/v2/studies/DTXSID5032498')).status).toBe(200)
  })

  it('AC37: confirming returns to the list with "… was deleted"; the study is gone from it', async () => {
    const { user, typed, ok, router } = await openDialog('DTXSID5032498')
    await user.type(typed(), 'DTXSID5032498')
    await user.click(ok())
    await waitFor(() => expect(router.state.location.pathname).toBe('/studies'))
    expect(await screen.findByText('DTXSID5032498 was deleted.')).toBeInTheDocument()
    await screen.findByRole('table')
    expect(document.querySelector('tr[data-row-key="chem:DTXSID5032498"]')).toBeNull()
    expect((await fetch('/api/v2/studies/DTXSID5032498')).status).toBe(404)
  })

  it('AC39: a change elsewhere while the dialog is open: "changed after you reviewed", the list reloads, nothing is deleted', async () => {
    const { user, typed, ok, dialog } = await openDialog('DTXSID5032498')
    touchMockStudy('DTXSID5032498')
    await user.type(typed(), 'DTXSID5032498')
    await user.click(ok())
    expect(await within(dialog).findByText('The study changed while this was open. Review what this will do again.')).toBeInTheDocument()
    expect(dialog).toHaveTextContent('The study changed after you reviewed what would be deleted. Nothing was deleted; review the list again.')
    expect(typed()).toHaveValue('')
    expect(ok()).toBeDisabled()
    expect((await fetch('/api/v2/studies/DTXSID5032498')).status).toBe(200)
    // the reviewed list was read again: confirming now deletes
    await user.type(typed(), 'DTXSID5032498')
    await user.click(ok())
    expect(await screen.findByText('DTXSID5032498 was deleted.')).toBeInTheDocument()
  })

  it('S4.4: a refusal of the preview itself is explained, and no dialog opens', async () => {
    server.use(
      http.get('/api/v2/studies/:id/delete-preview', () =>
        HttpResponse.json({ error: { code: 'run_in_flight', status: 409, message: 'lock held', say: 'Process is running on this study (since 10:42). Wait for it to finish.', fix: 'P1', details: {} } }, { status: 409 }),
      ),
    )
    const { user } = await openStudyPage('DTXSID5032498')
    await user.click(screen.getByRole('button', { name: 'Delete this study…' }))
    expect(await screen.findByText('Process is running on this study (since 10:42). Wait for it to finish.')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('another refusal of the delete stays in the dialog, in plain words, with the details behind a toggle (AC41)', async () => {
    server.use(
      http.post('/api/v2/studies/:id/delete', () =>
        HttpResponse.json({ error: { code: 'confirm_mismatch', status: 400, message: 'confirm_id x != y', say: "The id you typed doesn't match this study's id. Nothing was deleted.", fix: null, details: {} } }, { status: 400 }),
      ),
    )
    const { user, typed, ok, dialog } = await openDialog('DTXSID5032498')
    await user.type(typed(), 'DTXSID5032498')
    await user.click(ok())
    expect(await within(dialog).findByText("The id you typed doesn't match this study's id. Nothing was deleted.")).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Show the technical details' }))
    expect(within(dialog).getByTestId('refusal-details')).toHaveTextContent('confirm_id x != y')
  })
})

describe('everywhere', () => {
  // the forbidden word is spelled out of pieces so the lint rule that bans it in UI text stays strict
  const FORBIDDEN = new RegExp(['wiz', 'ard'].join(''), 'i')
  it('AC41: no M1 screen uses the forbidden name for the interface', async () => {
    for (const path of ['/studies', '/studies/new', '/studies/DTXSID50469320', '/studies/DTXSID_TEST', '/studies/foo']) {
      const r = renderApp(path)
      await waitFor(() => expect(document.querySelector('.ant-skeleton, .ant-spin-spinning')).toBeNull(), { timeout: 3000 })
      expect(document.body).not.toHaveTextContent(FORBIDDEN)
      r.unmount()
    }
    emptyM1Db()
  })
})
