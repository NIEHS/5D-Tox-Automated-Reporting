import { screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { VOCABULARIES } from '../api/mocks/fixtures'
import type { IdKind } from '../api/types'
import { renderWithApp } from '../test/render'
import { casrnCheckDigitOk, checkId, dtxsidsIn } from './checkId'
import { IdField } from './IdField'

const P = VOCABULARIES.patterns

describe('checkId', () => {
  it('accepts a bare DTXSID', () => {
    expect(checkId('dtxsid', 'DTXSID50469320', P.dtxsid)).toEqual({ ok: true })
  })

  it('refuses a suffixed study id and says why', () => {
    const r = checkId('dtxsid', 'DTXSID50469320_rat', P.dtxsid)
    expect(r.ok).toBe(false)
    expect(r.ok === false && r.say).toMatch(/DTXSID alone \(DTXSID50469320\)\. Ids with a suffix/)
  })

  it('refuses lower case, spaces, empty, and the wrong shape', () => {
    expect(checkId('dtxsid', 'dtxsid50469320', P.dtxsid)).toMatchObject({ ok: false, say: 'Write DTXSID in capital letters.' })
    expect(checkId('dtxsid', ' DTXSID50469320', P.dtxsid)).toMatchObject({ ok: false, say: 'Remove the spaces before or after it.' })
    expect(checkId('dtxsid', '', P.dtxsid)).toMatchObject({ ok: false })
    expect(checkId('dtxsid', '', P.dtxsid)).toMatchObject({ ok: false, say: "Enter the chemical's DTXSID." })
    expect(checkId('dtxsid', 'DTXSIDabc', P.dtxsid)).toMatchObject({ ok: false, say: expect.stringMatching(/^After 'DTXSID' come digits only/) as unknown })
  })

  it('checks a CAS number, including its check digit', () => {
    expect(casrnCheckDigitOk('41997-13-1')).toBe(true)
    expect(casrnCheckDigitOk('106-46-7')).toBe(true)
    expect(casrnCheckDigitOk('7732-18-5')).toBe(true)
    expect(checkId('casrn', '41997-13-1', P.casrn)).toEqual({ ok: true })
    expect(checkId('casrn', '41997-13-2', P.casrn)).toMatchObject({ ok: false, say: expect.stringMatching(/check digit/) as unknown })
    expect(checkId('casrn', '4199713-1', P.casrn)).toMatchObject({ ok: false })
  })

  it('checks a DOI, and refuses one pasted as a link', () => {
    expect(checkId('doi', '10.22427/NIEHS-10', P.doi)).toEqual({ ok: true })
    expect(checkId('doi', 'https://doi.org/10.22427/NIEHS-10', P.doi)).toMatchObject({ ok: false, say: expect.stringMatching(/without the link/) as unknown })
    expect(checkId('doi', 'doi:10.22427/NIEHS-10', P.doi)).toMatchObject({ ok: false })
    expect(checkId('doi', '22427/NIEHS-10', P.doi)).toMatchObject({ ok: false })
  })

  it('checks a study id with the backend\'s own study-id rule (a bare DTXSID)', () => {
    expect(checkId('study_id', 'DTXSID50469320', P.study_id)).toEqual({ ok: true })
    expect(checkId('study_id', 'DTXSID1020431_rat', P.study_id)).toMatchObject({ ok: false, say: expect.stringMatching(/made by the system/) as unknown })
  })

  it('names the DTXSID mistakes before the pattern (M1 spec §4 rules 3 to 6)', () => {
    expect(checkId('dtxsid', '7020182', P.dtxsid)).toMatchObject({ ok: false, say: "A DTXSID starts with 'DTXSID', for example DTXSID50469320." })
    expect(checkId('dtxsid', 'DTXSID50469320_v2', P.dtxsid)).toMatchObject({ ok: false, say: expect.stringMatching(/^A study's id is the DTXSID alone/) as unknown })
    expect(checkId('dtxsid', 'DTXSID5046932O', P.dtxsid)).toMatchObject({ ok: false, say: "Character 14 is the letter O. A DTXSID has only digits after 'DTXSID'." })
    expect(checkId('dtxsid', 'DTXSIDl0', P.dtxsid)).toMatchObject({ ok: false, say: expect.stringMatching(/Character 7 is the letter L/) as unknown })
    expect(checkId('dtxsid', 'DTXSID', P.dtxsid)).toMatchObject({ ok: false, say: expect.stringMatching(/digits only/) as unknown })
  })

  it('finds the DTXSIDs in pasted text', () => {
    expect(dtxsidsIn('https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182')).toEqual(['DTXSID7020182'])
    expect(dtxsidsIn('DTXSID1 and dtxsid2')).toEqual(['DTXSID1', 'DTXSID2'])
    expect(dtxsidsIn('nothing here')).toEqual([])
  })

  it('serves no date rule, so none is checked (none is invented)', () => {
    expect(Object.keys(P).sort()).toEqual(['casrn', 'doi', 'dtxsid', 'session_id', 'study_id'])
  })

  it('checks a DTXSID against the store\'s rule too: the served DTXSID pattern sets no length, the store does', () => {
    const long = `DTXSID${'1'.repeat(80)}`
    expect(checkId('dtxsid', long, P.dtxsid).ok).toBe(true)
    expect(checkId('dtxsid', long, P.dtxsid, P.session_id)).toMatchObject({ ok: false, say: expect.stringMatching(/longer than any DTXSID/) as unknown })
    expect(checkId('dtxsid', `DTXSID${'1'.repeat(64)}`, P.dtxsid, P.session_id)).toEqual({ ok: true })
    expect(checkId('study_id', long, P.study_id, P.session_id).ok).toBe(false)
    expect(checkId('dtxsid', 'DTXSID50469320', P.dtxsid, { pattern: '(', example: '', say: '' }).ok).toBeNull()
  })

  it('never calls an id good when its rule is missing or broken', () => {
    expect(checkId('doi', '10.1/x', undefined).ok).toBeNull()
    expect(checkId('doi', '10.1/x', { pattern: '(', example: '', say: '' }).ok).toBeNull()
  })
})

function Host({ kind, onCheck }: { kind: IdKind; onCheck: (ok: boolean) => void }) {
  const [v, setV] = useState('')
  return <IdField kind={kind} value={v} onChange={setV} onCheck={onCheck} />
}

describe('<IdField>', () => {
  it('checks as it is typed, says what is wrong, and reports when it is right', async () => {
    const onCheck = vi.fn()
    const { user } = renderWithApp(<Host kind="dtxsid" onCheck={onCheck} />)
    const input = await screen.findByRole('textbox', { name: 'DTXSID' })
    await waitFor(() => expect(input).toBeEnabled())
    expect(screen.queryByText(/For example/)).not.toBeInTheDocument()
    await user.type(input, 'DTXSID5046932_')
    expect(screen.getByText(/made by the system/)).toBeInTheDocument()
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(onCheck).toHaveBeenLastCalledWith(false)
    await user.clear(input)
    await user.type(input, 'DTXSID50469320')
    expect(screen.queryByText(/made by the system/)).not.toBeInTheDocument()
    expect(input).toHaveAttribute('aria-invalid', 'false')
    expect(screen.getByLabelText('looks right')).toBeInTheDocument()
    await waitFor(() => expect(onCheck).toHaveBeenLastCalledWith(true))
  })

  it('makes a DTXSID upper case as it is typed, visibly', async () => {
    const { user } = renderWithApp(<Host kind="dtxsid" onCheck={vi.fn()} />)
    const input = await screen.findByRole('textbox', { name: 'DTXSID' })
    await waitFor(() => expect(input).toBeEnabled())
    await user.type(input, 'dtxsid7020182')
    expect(input).toHaveValue('DTXSID7020182')
  })

  it('trims a paste, and offers the DTXSID found in pasted text without filling it in', async () => {
    const { user } = renderWithApp(<Host kind="dtxsid" onCheck={vi.fn()} />)
    const input = await screen.findByRole('textbox', { name: 'DTXSID' })
    await waitFor(() => expect(input).toBeEnabled())
    await user.click(input)
    await user.paste('  DTXSID50469320 ')
    expect(input).toHaveValue('DTXSID50469320')
    expect(screen.queryByTestId('id-offer')).not.toBeInTheDocument()
    await user.clear(input)
    await user.paste('https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182')
    expect(input).toHaveValue('HTTPS://COMPTOX.EPA.GOV/DASHBOARD/CHEMICAL/DETAILS/DTXSID7020182')
    // while the offer is shown, only the offer: no red error beside it
    expect(screen.queryByText(/starts with 'DTXSID'/)).not.toBeInTheDocument()
    expect(input).toHaveAttribute('aria-invalid', 'false')
    await user.click(screen.getByRole('button', { name: 'Use DTXSID7020182?' }))
    expect(input).toHaveValue('DTXSID7020182')
    expect(screen.queryByTestId('id-offer')).not.toBeInTheDocument()
  })

  it('says what is wrong again once the offer is set aside by typing', async () => {
    const { user } = renderWithApp(<Host kind="dtxsid" onCheck={vi.fn()} />)
    const input = await screen.findByRole('textbox', { name: 'DTXSID' })
    await waitFor(() => expect(input).toBeEnabled())
    await user.click(input)
    await user.paste('https://comptox.epa.gov/dashboard/chemical/details/DTXSID7020182')
    expect(screen.getByTestId('id-offer')).toBeInTheDocument()
    await user.type(input, 'x')
    expect(screen.queryByTestId('id-offer')).not.toBeInTheDocument()
    expect(screen.getByText(/starts with 'DTXSID'/)).toBeInTheDocument()
  })

  it('never calls a DTXSID right that the store could not hold (80 digits)', async () => {
    const onCheck = vi.fn()
    const { user } = renderWithApp(<Host kind="dtxsid" onCheck={onCheck} />)
    const input = await screen.findByRole('textbox', { name: 'DTXSID' })
    await waitFor(() => expect(input).toBeEnabled())
    await user.click(input)
    await user.paste(`DTXSID${'1'.repeat(80)}`)
    expect(screen.getByText(/longer than any DTXSID the application can hold/)).toBeInTheDocument()
    expect(screen.queryByLabelText('looks right')).not.toBeInTheDocument()
    expect(onCheck).toHaveBeenLastCalledWith(false)
  })

  it('leaves a CAS number as it is typed', async () => {
    const { user } = renderWithApp(<Host kind="casrn" onCheck={vi.fn()} />)
    const input = await screen.findByRole('textbox', { name: 'CAS number' })
    await waitFor(() => expect(input).toBeEnabled())
    await user.type(input, '80-05-8')
    expect(screen.getByText(/check digit doesn't match/)).toBeInTheDocument()
  })

  it('shows the example from the backend as the placeholder', async () => {
    renderWithApp(<IdField kind="casrn" />)
    expect(await screen.findByPlaceholderText('e.g. 41997-13-1')).toBeInTheDocument()
  })
})
