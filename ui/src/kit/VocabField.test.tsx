import { screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { VOCABULARIES } from '../api/mocks/fixtures'
import { server } from '../api/mocks/node'
import { renderWithApp } from '../test/render'
import { choicesFor } from './useVocabularies'
import { VocabField } from './VocabField'

/** The open dropdown's options (antd keeps closed dropdowns in the page). */
function listbox() {
  const open = Array.from(document.querySelectorAll('.ant-select-dropdown')).filter((d) => !d.classList.contains('ant-select-dropdown-hidden'))
  return within(open.at(-1) as HTMLElement)
}

function optionTexts(): string[] {
  return Array.from(document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option')).map((o) => o.textContent ?? '')
}

function SpeciesStrain({ initialSpecies, initialStrain }: { initialSpecies?: string; initialStrain?: string }) {
  const [species, setSpecies] = useState<string | undefined>(initialSpecies)
  const [strain, setStrain] = useState<string | undefined>(initialStrain)
  return (
    <>
      <VocabField vocab="species" value={species} onChange={setSpecies} />
      <VocabField vocab="strain" value={strain} onChange={setStrain} parentValue={species} />
      <output data-testid="values">{JSON.stringify({ species, strain })}</output>
    </>
  )
}

describe('choicesFor', () => {
  it('gives a flat list, or the dependent list for the parent value', () => {
    expect(choicesFor(VOCABULARIES, 'sex')).toEqual({ kind: 'choices', values: ['male', 'female', 'both', 'mixed', 'NA'] })
    expect(choicesFor(VOCABULARIES, 'strain')).toEqual({ kind: 'needs-parent', parent: 'species', parentLabel: 'Species' })
    expect(choicesFor(VOCABULARIES, 'strain', 'mouse')).toMatchObject({ kind: 'choices', values: expect.arrayContaining(['B6C3F1', 'C57BL/6']) as unknown })
    expect(choicesFor(VOCABULARIES, 'strain', 'zebrafish')).toEqual({ kind: 'choices', values: [] })
    expect(choicesFor(VOCABULARIES, 'nonsense')).toEqual({ kind: 'unknown' })
    expect(choicesFor(undefined, 'sex')).toEqual({ kind: 'unknown' })
  })
})

describe('<VocabField>', () => {
  it('offers exactly the vocabulary, and starts with no value chosen', async () => {
    const onChange = vi.fn()
    const { user } = renderWithApp(<VocabField vocab="articleRoute" onChange={onChange} />)
    const box = await screen.findByRole('combobox', { name: 'Route' })
    await waitFor(() => expect(box).toBeEnabled())
    expect(screen.getByText('Choose the route')).toBeInTheDocument()
    await user.click(box)
    await waitFor(() => expect(optionTexts()).toEqual(['gavage', 'oral', 'inhaled', 'transdermal']))
    await user.click(listbox().getByTitle('inhaled'))
    expect(onChange).toHaveBeenCalledWith('inhaled')
  })

  it('never accepts free text', async () => {
    const onChange = vi.fn()
    const { user } = renderWithApp(<VocabField vocab="species" onChange={onChange} />)
    const box = await screen.findByRole('combobox', { name: 'Species' })
    await waitFor(() => expect(box).toBeEnabled())
    await user.click(box)
    await user.keyboard('ferret{Enter}')
    expect(onChange).not.toHaveBeenCalled()
    expect(await screen.findByText('No allowed value matches what you typed.')).toBeInTheDocument()
  })

  it('keeps a dependent field closed until its parent is chosen, then offers only its values', async () => {
    const { user } = renderWithApp(<SpeciesStrain />)
    const strain = await screen.findByRole('combobox', { name: 'Strain' })
    await waitFor(() => expect(screen.getByText('Choose the species first.')).toBeInTheDocument())
    expect(strain).toBeDisabled()

    const species = screen.getByRole('combobox', { name: 'Species' })
    await user.click(species)
    await user.click(listbox().getByTitle('mouse'))
    await waitFor(() => expect(strain).toBeEnabled())
    await user.click(strain)
    await waitFor(() => expect(optionTexts()).toContain('B6C3F1'))
    expect(optionTexts()).not.toContain('Sprague-Dawley')
  })

  it('flags a value that no longer fits its parent, without clearing it', async () => {
    renderWithApp(<SpeciesStrain initialSpecies="mouse" initialStrain="Sprague-Dawley" />)
    expect(await screen.findByText('"Sprague-Dawley" is not an allowed strain for mouse. Choose another.')).toBeInTheDocument()
    expect(screen.getByTestId('values')).toHaveTextContent('"strain":"Sprague-Dawley"')
  })

  it('says so when the parent allows nothing', async () => {
    renderWithApp(<VocabField vocab="strain" parentValue="zebrafish" />)
    expect(await screen.findByText('No strain is allowed for this zebrafish.')).toBeInTheDocument()
  })

  it('is closed, and says why, when the vocabularies cannot be loaded', async () => {
    server.use(http.get('/api/v2/vocabularies', () => HttpResponse.json({ detail: 'x' }, { status: 500 })))
    renderWithApp(<VocabField vocab="species" />)
    expect(await screen.findByText(/could not be loaded, so nothing can be chosen/)).toBeInTheDocument()
    expect(screen.getByRole('combobox')).toBeDisabled()
  })

  it('is closed for a vocabulary that does not exist', async () => {
    renderWithApp(<VocabField vocab="colour" />)
    expect(await screen.findByText('There is no list of allowed values called "colour".')).toBeInTheDocument()
  })
})
