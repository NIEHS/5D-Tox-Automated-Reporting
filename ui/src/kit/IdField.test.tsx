import { screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { VOCABULARIES } from '../api/mocks/fixtures'
import type { IdKind } from '../api/types'
import { renderWithApp } from '../test/render'
import { casrnCheckDigitOk, checkId } from './checkId'
import { IdField } from './IdField'

const P = VOCABULARIES.patterns ?? {}

describe('checkId', () => {
  it('accepts a bare DTXSID', () => {
    expect(checkId('dtxsid', 'DTXSID50469320', P.dtxsid)).toEqual({ ok: true })
  })

  it('refuses a suffixed study id and says why', () => {
    const r = checkId('dtxsid', 'DTXSID50469320_rat', P.dtxsid)
    expect(r.ok).toBe(false)
    expect(r.ok === false && r.say).toMatch(/DTXSID alone \(DTXSID50469320\)/)
  })

  it('refuses lower case, spaces, empty, and the wrong shape', () => {
    expect(checkId('dtxsid', 'dtxsid50469320', P.dtxsid)).toMatchObject({ ok: false, say: 'Write DTXSID in capital letters.' })
    expect(checkId('dtxsid', ' DTXSID50469320', P.dtxsid)).toMatchObject({ ok: false, say: 'Remove the spaces before or after it.' })
    expect(checkId('dtxsid', '', P.dtxsid)).toMatchObject({ ok: false })
    expect(checkId('dtxsid', 'DTXSIDabc', P.dtxsid)).toMatchObject({ ok: false, say: expect.stringMatching(/For example: DTXSID50469320/) as unknown })
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

  it('checks a date exists', () => {
    expect(checkId('date', '2026-10-14', P.date)).toEqual({ ok: true })
    expect(checkId('date', '2026-02-30', P.date)).toMatchObject({ ok: false, say: 'There is no such date.' })
    expect(checkId('date', '14/10/2026', P.date)).toMatchObject({ ok: false })
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
    expect(screen.getByText(/made by the application itself/)).toBeInTheDocument()
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(onCheck).toHaveBeenLastCalledWith(false)
    await user.clear(input)
    await user.type(input, 'DTXSID50469320')
    expect(screen.queryByText(/made by the application itself/)).not.toBeInTheDocument()
    expect(input).toHaveAttribute('aria-invalid', 'false')
    expect(screen.getByLabelText('looks right')).toBeInTheDocument()
    await waitFor(() => expect(onCheck).toHaveBeenLastCalledWith(true))
  })

  it('shows the example from the backend as the placeholder', async () => {
    renderWithApp(<IdField kind="casrn" />)
    expect(await screen.findByPlaceholderText('e.g. 41997-13-1')).toBeInTheDocument()
  })
})
