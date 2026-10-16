import { act, screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { M1_CHECK_PFHXSAM, M1_CHEMICALS } from '../../api/mocks/fixtures'
import { removeMockStudy } from '../../api/mocks/m1'
import { server } from '../../api/mocks/node'
import { renderApp } from '../../test/render'

/** S2 New study: M1 spec §12 criteria 12–26. */

async function openNew(query = '') {
  const r = renderApp(`/studies/new${query}`)
  const input = await screen.findByRole('textbox', { name: "The chemical's DTXSID" })
  await waitFor(() => expect(input).toBeEnabled())
  return { ...r, input, next: () => screen.getByRole('button', { name: /Next/ }) }
}

async function toStep2(id: string) {
  const r = await openNew()
  await r.user.type(r.input, id)
  await waitFor(() => expect(r.next()).toBeEnabled())
  await r.user.click(r.next())
  return r
}

/** How many sessions the list holds (to show a step wrote nothing). */
async function listSize(): Promise<number> {
  const body = (await (await fetch('/api/v2/studies')).json()) as { chemicals: { sessions: unknown[] }[]; unassigned: unknown[] }
  return body.chemicals.reduce((n, c) => n + c.sessions.length, 0) + body.unassigned.length
}

describe('S2 step 1: the DTXSID', () => {
  it('AC12: letters are made upper case as typed, visibly', async () => {
    const { user, input } = await openNew()
    await user.type(input, 'dtxsid7020182')
    expect(input).toHaveValue('DTXSID7020182')
  })

  it.each([
    ['AC13', 'DTXSID5046932O', 'Character 14 is the letter O.'],
    ['AC14', 'DTXSID50469320_v2', "A study's id is the DTXSID alone"],
    ['AC15', '7020182', "A DTXSID starts with 'DTXSID'"],
  ])('%s: %s is refused with its own message, and Next stays disabled', async (_ac, typed, message) => {
    const { user, input, next } = await openNew()
    await user.type(input, typed)
    expect(screen.getByText(new RegExp(message.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))).toBeInTheDocument()
    await act(() => new Promise((r) => setTimeout(r, 450)))
    expect(next()).toBeDisabled()
  })

  it('AC16: pasting a CompTox address offers its DTXSID; the field is filled only by the click', async () => {
    const { user, input } = await openNew()
    await user.click(input)
    await user.paste('https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182')
    expect(input).not.toHaveValue('DTXSID7020182')
    // F7: only the offer, not the red "A DTXSID starts with…" beside it
    expect(screen.queryByText(/A DTXSID starts with 'DTXSID'/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Use DTXSID7020182?' }))
    expect(input).toHaveValue('DTXSID7020182')
  })

  it('F7: an id longer than the store can hold (80 digits) is refused on the screen; Next stays disabled; it is never sent', async () => {
    let checks = 0
    server.use(
      http.get('/api/v2/studies/:dtxsid/creation-check', () => {
        checks++
        return HttpResponse.json({}, { status: 500 })
      }),
    )
    const { user, input, next } = await openNew()
    await user.click(input)
    await user.paste(`DTXSID${'7'.repeat(80)}`)
    expect(screen.getByText(/longer than any DTXSID the application can hold/)).toBeInTheDocument()
    await act(() => new Promise((r) => setTimeout(r, 450)))
    expect(next()).toBeDisabled()
    expect(checks).toBe(0)
  })

  it('AC17: an existing study is named, with Open it; Next stays disabled; nothing is written', async () => {
    const before = await listSize()
    const { user, input, next, router } = await openNew()
    await user.type(input, 'DTXSID50469320')
    const exists = await screen.findByTestId('study-exists')
    expect(exists).toHaveTextContent('A study of this chemical already exists: DTXSID50469320')
    await waitFor(() => expect(exists).toHaveTextContent('Perfluorohexanesulfonamide'))
    expect(next()).toBeDisabled()
    expect(screen.getByTestId('related-sessions')).toHaveTextContent('DTXSID50469320_nb')
    await user.click(within(exists).getByRole('button', { name: 'Open it' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/studies/DTXSID50469320'))
    expect(await listSize()).toBe(before)
  })

  it('AC24 (Back): Back from step 2 keeps the id; nothing is written', async () => {
    const before = await listSize()
    const { user, input } = await toStep2('DTXSID7020182')
    await screen.findByTestId('chemical-card')
    await user.click(screen.getByRole('button', { name: 'Back' }))
    expect(await screen.findByRole('textbox', { name: "The chemical's DTXSID" })).toHaveValue('DTXSID7020182')
    void input
    expect(await listSize()).toBe(before)
  })

  it('AC24 (reload): a fresh page during step 2 starts at step 1', async () => {
    await toStep2('DTXSID7020182')
    await screen.findByTestId('chemical-card')
    // a reload is a new page; nothing of step 2 is kept anywhere
    const { input } = await openNew()
    expect(input).toHaveValue('')
    expect(screen.getAllByText("The chemical's DTXSID").length).toBeGreaterThan(0)
  })

  it('starts with the id from the address (?dtxsid=)', async () => {
    const { input } = await openNew('?dtxsid=dtxsid7020182')
    expect(input).toHaveValue('DTXSID7020182')
  })
})

describe('S2 step 2: the chemical and the format', () => {
  it('AC18: shows "Looking up…", then the chemical: name, CASRN, formula, picture, PubChem link, the source line', async () => {
    await toStep2('DTXSID7020182')
    expect(await screen.findByText('Looking up DTXSID7020182 in PubChem…')).toBeInTheDocument()
    const card = await screen.findByTestId('chemical-card')
    expect(card).toHaveTextContent('Bisphenol A')
    expect(card).toHaveTextContent('80-05-7')
    expect(card).toHaveTextContent('C15H16O2')
    expect(within(card).getByRole('img', { name: 'Structure of Bisphenol A' })).toHaveAttribute('src', '/api/v2/chemicals/DTXSID7020182/structure.png')
    const cid = within(card).getByRole('link', { name: /6623/ })
    expect(cid).toHaveAttribute('href', 'https://pubchem.ncbi.nlm.nih.gov/compound/6623')
    expect(cid).toHaveAttribute('target', '_blank')
    expect(screen.getByTestId('lookup-source')).toHaveTextContent('Looked up in PubChem just now.')
  })

  it('AC19: the format notice is informational: the format for new studies, no published report on file', async () => {
    await toStep2('DTXSID7020182')
    const notice = await screen.findByTestId('format-notice')
    expect(notice).toHaveAttribute('data-level', 'info')
    expect(notice).toHaveTextContent('No published report is on file for this chemical, so the study uses the format for new studies')
    expect(notice).toHaveTextContent('2026')
    expect(notice).toHaveTextContent("The DTXSID decides this. It can't be changed here.")
  })

  it('AC20: in a store without PFHxSAm, the format notice warns: NIEHS-10, March 2023, and what the id brings', async () => {
    removeMockStudy('DTXSID50469320')
    removeMockStudy('DTXSID50469320_nb')
    removeMockStudy('DTXSID50469320_published')
    await toStep2('DTXSID50469320')
    const notice = await screen.findByTestId('format-notice')
    expect(notice).toHaveAttribute('data-level', 'warning')
    expect(notice).toHaveTextContent('NIEHS-10 (March 2023)')
    const brings = within(notice).getByRole('list', { name: 'What the id also brings' })
    expect(brings).toHaveTextContent('organs and endpoints')
    expect(brings).toHaveTextContent('deposited files and its data DOI')
    expect(brings).toHaveTextContent('Appendix A')
    expect(screen.getByTestId('confirm-label')).toHaveTextContent(M1_CHECK_PFHXSAM.format.title)
  })

  it('AC21: Create study stays disabled until the confirm box is ticked (and, when PubChem did not match the DTXSID, the check box first)', async () => {
    const { user } = await toStep2('DTXSID7020182')
    await screen.findByTestId('confirm-label')
    const create = screen.getByRole('button', { name: 'Create study' })
    expect(create).toBeDisabled()
    // Bisphenol A's fixture: PubChem does not list the DTXSID (dtxsid_matched false)
    expect(screen.getByText(/does not list DTXSID7020182 for it/)).toBeInTheDocument()
    const confirm = screen.getByRole('checkbox', { name: /This is the chemical I am studying/ })
    expect(confirm).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /I checked the DTXSID DTXSID7020182 on the CompTox dashboard/ }))
    expect(confirm).toBeEnabled()
    expect(create).toBeDisabled()
    await user.click(confirm)
    expect(create).toBeEnabled()
    await user.click(confirm)
    expect(create).toBeDisabled()
  })

  it('2026-10-16: PubChem gives no CAS number: the person is asked for one; Create waits for a valid one and the tick; it is sent as stated by the person', async () => {
    let sent: { casrn: string | null; source: { casrn_from?: string } } | null = null
    server.events.on('request:start', async ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname === '/api/v2/studies') {
        sent = ((await request.clone().json()) as { identity: typeof sent }).identity
      }
    })
    try {
      const { user } = await toStep2('DTXSID3333333333')
      const ask = await screen.findByTestId('casrn-ask')
      expect(ask).toHaveTextContent('PubChem gives no CAS number for Bisphenol A. Type it before going on') // the backend's needs_say
      const field = within(ask).getByRole('textbox', { name: 'CAS number (required)' })
      const confirm = screen.getByRole('checkbox', { name: /This is the chemical I am studying/ })
      const create = screen.getByRole('button', { name: 'Create study' })
      expect(confirm).toBeDisabled()
      expect(create).toBeDisabled()
      expect(screen.getByTestId('casrn-wait')).toHaveTextContent('Type a valid CAS number above first.')

      // a mistyped check digit: the spec's words; still no create
      await user.type(field, '80-05-8')
      expect(within(ask).getByText("This CASRN's check digit doesn't match; a digit is probably mistyped.")).toBeInTheDocument()
      expect(confirm).toBeDisabled()
      expect(create).toBeDisabled()

      await user.clear(field)
      await user.type(field, '80-05-7')
      await waitFor(() => expect(confirm).toBeEnabled())
      expect(create).toBeDisabled()
      await user.click(confirm)
      expect(create).toBeEnabled()

      // changing the number after ticking unticks: what was confirmed changed
      await user.type(field, '1')
      expect(confirm).not.toBeChecked()
      expect(create).toBeDisabled()
      await user.type(field, '{Backspace}')
      await waitFor(() => expect(confirm).toBeEnabled())
      await user.click(confirm)

      await user.click(create)
      expect(await screen.findByText('Study DTXSID3333333333 created: Bisphenol A (80-05-7)')).toBeInTheDocument()
      expect(sent).toMatchObject({ casrn: '80-05-7', source: { kind: 'lookup', casrn_from: 'person' } })
    } finally {
      server.events.removeAllListeners()
    }
  })

  it('2026-10-16: a lookup that gives a CAS number asks for none, and sends no casrn_from', async () => {
    let sent: { source: Record<string, unknown> } | null = null
    server.events.on('request:start', async ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname === '/api/v2/studies') {
        sent = ((await request.clone().json()) as { identity: typeof sent }).identity
      }
    })
    try {
      const { user } = await toStep2('DTXSID7020182')
      await screen.findByTestId('confirm-label')
      expect(screen.queryByTestId('casrn-ask')).not.toBeInTheDocument()
      await user.click(screen.getByRole('checkbox', { name: /I checked the DTXSID/ }))
      await user.click(screen.getByRole('checkbox', { name: /This is the chemical I am studying/ }))
      await user.click(screen.getByRole('button', { name: 'Create study' }))
      await screen.findByText(/Study DTXSID7020182 created/)
      expect(sent!.source).not.toHaveProperty('casrn_from')
    } finally {
      server.events.removeAllListeners()
    }
  })

  it('review 3: a lookup with no name is still a dead end: the tick is closed, the screen says why, no field to type a name', async () => {
    const bpa = structuredClone(M1_CHEMICALS['DTXSID7020182']!)
    bpa.identity.name = ''
    bpa.identity.casrn = null
    bpa.dtxsid_matched = true
    let posts = 0
    server.use(
      http.get('/api/v2/chemicals/DTXSID7020182', () => HttpResponse.json(bpa)),
      http.post('/api/v2/studies', () => {
        posts++
        return HttpResponse.json({}, { status: 500 })
      }),
    )
    const { user } = await toStep2('DTXSID7020182')
    const why = await screen.findByTestId('identity-incomplete')
    expect(why).toHaveTextContent("PubChem gives no name for this chemical, so a study can't be created from this lookup yet.")
    expect(screen.getByRole('checkbox', { name: /This is the chemical I am studying/ })).toBeDisabled()
    const create = screen.getByRole('button', { name: 'Create study' })
    expect(create).toBeDisabled()
    await user.click(create)
    expect(posts).toBe(0)
    expect(screen.queryByTestId('casrn-ask')).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('review 3: a lookup whose CAS number fails its check digit offers no create either', async () => {
    const bpa = structuredClone(M1_CHEMICALS['DTXSID7020182']!)
    bpa.identity.casrn = '80-05-8'
    bpa.dtxsid_matched = true
    server.use(http.get('/api/v2/chemicals/DTXSID7020182', () => HttpResponse.json(bpa)))
    await toStep2('DTXSID7020182')
    expect(await screen.findByTestId('identity-incomplete')).toHaveTextContent('(80-05-8) is not a valid one')
    expect(screen.getByRole('button', { name: 'Create study' })).toBeDisabled()
  })

  it('AC22: a DTXSID PubChem does not know: the error, Back to the id, no name, no way to create', async () => {
    await toStep2('DTXSID0000000001')
    const e = await screen.findByTestId('lookup-not-found')
    expect(e).toHaveTextContent('PubChem has no chemical with the DTXSID DTXSID0000000001')
    expect(within(e).getByRole('button', { name: 'Back to the id' })).toBeInTheDocument()
    expect(document.body).not.toHaveTextContent(/Test Article/i)
    expect(screen.queryByRole('button', { name: 'Create study' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('chemical-card')).not.toBeInTheDocument()
  })

  it('AC23: the lookup service unreachable: says so, that nothing was created, and offers Try again; the list is unchanged', async () => {
    const before = await listSize()
    const { user } = await toStep2('DTXSID0000000002')
    const e = await screen.findByTestId('lookup-unreachable')
    expect(e).toHaveTextContent('could not be reached. Nothing was created.')
    let calls = 0
    server.use(http.get('/api/v2/chemicals/:dtxsid', () => { calls++; return HttpResponse.json({ error: { code: 'identity_lookup_unreachable', status: 503, message: 'x', say: 'Still unreachable.', fix: null, details: {} } }, { status: 503 }) }))
    await user.click(within(e).getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(calls).toBe(1))
    expect(await listSize()).toBe(before)
  })
})

describe('S2 step 3: created', () => {
  it('AC25: the success page names the id, chemical and format, offers the next step; the list and the page show the new study', async () => {
    const { user, router } = await toStep2('DTXSID7020182')
    await user.click(await screen.findByRole('checkbox', { name: /I checked the DTXSID/ }))
    await user.click(screen.getByRole('checkbox', { name: /This is the chemical I am studying/ }))
    await user.click(screen.getByRole('button', { name: 'Create study' }))
    expect(await screen.findByText('Study DTXSID7020182 created: Bisphenol A (80-05-7)')).toBeInTheDocument()
    expect(screen.getByText(/It will be written in NIEHS Report, as published in 2026/)).toBeInTheDocument()
    const next = screen.getByRole('link', { name: /Bring in the study's files/ })
    expect(next).toHaveAttribute('href', '/studies/DTXSID7020182/files')

    await user.click(screen.getByRole('button', { name: 'Back to studies' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/studies'))
    const top = await screen.findByText('Bisphenol A')
    const r = top.closest('tr') as HTMLElement
    expect(r).toHaveTextContent('No files yet')
    expect(r).toHaveTextContent("Next: Bring in the study's files")

    await user.click(within(r).getByRole('button', { name: 'Open' }))
    const src = await screen.findByTestId('identity-source')
    const today = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    expect(src).toHaveTextContent(`Confirmed by a person from a PubChem lookup on ${today}.`)
  })

  it('F9: Back from the success view goes to the studies list; the filled-in form can\'t be reached again, and nothing is sent twice', async () => {
    let posts = 0
    server.events.on('request:start', ({ request }) => {
      if (request.method === 'POST' && new URL(request.url).pathname === '/api/v2/studies') posts++
    })
    try {
      const { user, router } = await toStep2('DTXSID7020182')
      await user.click(await screen.findByRole('checkbox', { name: /I checked the DTXSID/ }))
      await user.click(screen.getByRole('checkbox', { name: /This is the chemical I am studying/ }))
      await user.click(screen.getByRole('button', { name: 'Create study' }))
      expect(await screen.findByText('Study DTXSID7020182 created: Bisphenol A (80-05-7)')).toBeInTheDocument()
      expect(router.state.location.pathname).toBe('/studies/new')
      expect(router.state.location.search).toBe('?created=DTXSID7020182')

      await act(() => router.navigate(-1))
      await waitFor(() => expect(router.state.location.pathname).toBe('/studies'))
      expect(await screen.findByRole('heading', { name: 'Studies' })).toBeInTheDocument()
      // the form's place was taken by the list: one more Back reaches no form
      await act(() => router.navigate(-1))
      expect(router.state.location.pathname).toBe('/studies')
      expect(screen.queryByRole('textbox', { name: "The chemical's DTXSID" })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Create study' })).not.toBeInTheDocument()

      // Forward returns to the success view, read from the backend; still no second create
      await act(() => router.navigate(1))
      expect(await screen.findByText('Study DTXSID7020182 created: Bisphenol A (80-05-7)')).toBeInTheDocument()
      expect(posts).toBe(1)
    } finally {
      server.events.removeAllListeners()
    }
  })

  it('F9: the success view\'s address, opened afresh (a reload), shows the study as the backend serves it, never the form', async () => {
    const check = (await (await fetch('/api/v2/studies/DTXSID7020182/creation-check')).json()) as { format: { definition: string; hash: string } }
    const made = await fetch('/api/v2/studies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dtxsid: 'DTXSID7020182',
        identity: { name: 'Bisphenol A', casrn: '80-05-7', pubchem_cid: 6623, source: { kind: 'lookup', service: 'PubChem', looked_up_at: 'x' } },
        confirmed: true, dtxsid_checked_by_person: true, format_seen: check.format,
      }),
    })
    expect(made.status).toBe(201)
    renderApp('/studies/new?created=DTXSID7020182')
    expect(await screen.findByText('Study DTXSID7020182 created: Bisphenol A (80-05-7)')).toBeInTheDocument()
    expect(screen.getByText(/It will be written in NIEHS Report, as published in 2026/)).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: "The chemical's DTXSID" })).not.toBeInTheDocument()
  })

  it('AC26: two tabs at step 2 for the same id: the second create is refused with Open it; one study exists', async () => {
    // tab 1 creates the study while tab 2 sits at step 2
    const tab2 = await toStep2('DTXSID7020182')
    await tab2.user.click(await screen.findByRole('checkbox', { name: /I checked the DTXSID/ }))
    await tab2.user.click(screen.getByRole('checkbox', { name: /This is the chemical I am studying/ }))
    const check = (await (await fetch('/api/v2/studies/DTXSID7020182/creation-check')).json()) as { format: { definition: string; hash: string } }
    const first = await fetch('/api/v2/studies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dtxsid: 'DTXSID7020182',
        identity: { name: 'Bisphenol A', casrn: '80-05-7', pubchem_cid: 6623, source: { kind: 'lookup', service: 'PubChem', looked_up_at: 'x' } },
        confirmed: true, dtxsid_checked_by_person: true, format_seen: check.format,
      }),
    })
    expect(first.status).toBe(201)
    await tab2.user.click(screen.getByRole('button', { name: 'Create study' }))
    expect(await screen.findByText('A study of this chemical already exists (DTXSID7020182). Open it instead.')).toBeInTheDocument()
    await tab2.user.click(screen.getByRole('button', { name: 'Open it' }))
    await waitFor(() => expect(tab2.router.state.location.pathname).toBe('/studies/DTXSID7020182'))
    const list = (await (await fetch('/api/v2/studies')).json()) as { chemicals: { sessions: { id: string }[] }[] }
    expect(list.chemicals.flatMap((c) => c.sessions).filter((s) => s.id === 'DTXSID7020182')).toHaveLength(1)
  })

  it('a format that changed after it was seen: shows the new format again and unticks the box', async () => {
    const { user } = await toStep2('DTXSID7020182')
    await user.click(await screen.findByRole('checkbox', { name: /I checked the DTXSID/ }))
    const confirm = screen.getByRole('checkbox', { name: /This is the chemical I am studying/ })
    await user.click(confirm)
    server.use(
      http.post('/api/v2/studies', () =>
        HttpResponse.json({ error: { code: 'format_changed', status: 409, message: 'hash differs', say: 'The report format this id brings changed since you looked. Review it again.', fix: null, details: {} } }, { status: 409 }),
      ),
    )
    await user.click(screen.getByRole('button', { name: 'Create study' }))
    expect(await screen.findByText(/The format this id brings changed since you looked/)).toBeInTheDocument()
    expect(confirm).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Create study' })).toBeDisabled()
  })
})
