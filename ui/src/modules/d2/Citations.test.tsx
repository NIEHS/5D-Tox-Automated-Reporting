import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DEMO_FINISHED, DEMO_FINISHED_RAT, DEMO_REFERENCES } from '../../api/mocks/fixtures/demo-writing'
import { entryRow, openWriting } from './testing'

/** Citations (the demo path, spec §4 S4), against the backend's own answers for NIEHS-12. */

const CHECK_SAYS =
  'The check establishes that a citation points at a source. It does not judge whether the source supports the sentence.'

describe('the Citations tab', () => {
  it('opens from the address and from the tab, and states what the check does and does not establish, word for word', async () => {
    const { user } = await openWriting(DEMO_FINISHED)
    await user.click(screen.getByRole('tab', { name: 'Citations' }))
    const tab = await screen.findByTestId('citations')
    expect(within(tab).getByTestId('check-says')).toHaveTextContent(CHECK_SAYS)
    expect(DEMO_REFERENCES[DEMO_FINISHED]!.check_says).toBe(CHECK_SAYS)
    expect(within(tab).getByTestId('check-result')).toHaveTextContent('Every citation points at a source that was supplied.')
    // part by part, in the backend's words
    for (const p of DEMO_REFERENCES[DEMO_FINISHED]!.check.parts) expect(within(tab).getByTestId('check')).toHaveTextContent(p.say)
  })

  it('lists the references as printed: the Background\'s sources, then each study\'s papers', async () => {
    await openWriting(DEMO_FINISHED, '?tab=citations')
    const list = await screen.findByTestId('reference-list')
    const entries = DEMO_REFERENCES[DEMO_FINISHED]!.entries
    const rows = [...list.querySelectorAll('tr[data-entry]')]
    expect(rows.map((r) => Number(r.getAttribute('data-entry')))).toEqual(entries.map((e) => e.n))
    expect(entryRow(1)).toHaveTextContent('[1]')
    expect(entryRow(1)).toHaveTextContent('PubChem Compound 7239 (database).')
    expect(entryRow(1)).toHaveTextContent("The Background's sources")
    const paper = entries.find((e) => e.kind === 'paper')!
    expect(entryRow(paper.n)).toHaveTextContent(paper.title!)
    expect(entryRow(paper.n)).toHaveTextContent("Rat study's knowledge base")
    expect(within(entryRow(paper.n)).getByRole('link', { name: 'DOI' })).toHaveAttribute('target', '_blank')
    expect(screen.getByTestId('knowledge-bases')).toHaveTextContent('knowledge base baseline-2026-05')
  })

  it('choosing a paper shows the sentences that cite it, the paper with its DOI in a new tab, and the knowledge base\'s statements', async () => {
    const { user } = await openWriting(DEMO_FINISHED, '?tab=citations')
    await screen.findByTestId('reference-list')
    const paper = DEMO_REFERENCES[DEMO_FINISHED]!.entries.find((e) => e.kind === 'paper' && (e.statements?.length ?? 0) > 0)!
    await user.click(entryRow(paper.n))
    const detail = await screen.findByTestId(`entry-${paper.n}`)
    expect(detail).toHaveTextContent(paper.cited_in[0]!.sentences[0]!)
    expect(detail).toHaveTextContent(paper.cited_in[0]!.part_title)
    expect(detail).toHaveTextContent(paper.statements![0]!)
    expect(detail).toHaveTextContent(`Offered to the model for`)
    const doi = within(detail).getByRole('link', { name: `https://doi.org/${paper.doi}` })
    expect(doi).toHaveAttribute('href', `https://doi.org/${paper.doi}`)
    expect(doi).toHaveAttribute('target', '_blank')
    expect(within(detail).getAllByRole('link', { name: 'Open this part' })[0]).toHaveAttribute(
      'href',
      `/studies/${paper.cited_in[0]!.study_id}/writing?part=${paper.cited_in[0]!.part}`,
    )
  })

  it('a Background source has no extracted statements, and says why', async () => {
    const { user } = await openWriting(DEMO_FINISHED, '?tab=citations')
    await screen.findByTestId('reference-list')
    await user.click(entryRow(2))
    const detail = await screen.findByTestId('entry-2')
    expect(detail).toHaveTextContent('not a paper of the knowledge base')
    expect(detail).toHaveTextContent(DEMO_REFERENCES[DEMO_FINISHED]!.entries[1]!.cited_in[0]!.sentences[0]!)
  })

  it('a study lists its own papers and points at the report for the whole list', async () => {
    await openWriting(DEMO_FINISHED_RAT, '?tab=citations')
    await screen.findByTestId('reference-list')
    const pointer = screen.getByTestId('references-pointer')
    expect(within(pointer).getByRole('link')).toHaveAttribute('href', `/studies/${DEMO_FINISHED}/writing?tab=citations`)
    expect(screen.getByTestId('citations')).toHaveTextContent(DEMO_REFERENCES[DEMO_FINISHED_RAT]!.numbering_say)
  })
})
