import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DEMO_FINISHED, DEMO_FINISHED_RAT, DEMO_LIVE, DEMO_REFERENCES } from '../../api/mocks/fixtures/demo-writing'
import { entryRow, openWriting } from './testing'

/** Citations (the demo path, spec §4 S4), against the backend's own answers for NIEHS-12. */

const CHECK_SAYS =
  'The check establishes that a citation points at a source. It does not judge whether the source supports the sentence.'

describe('the Citations tab', () => {
  it('opens from the tab, says where the check of the report stands and what it does not judge, in the backend\'s words', async () => {
    const { user } = await openWriting(DEMO_FINISHED)
    await user.click(screen.getByRole('tab', { name: 'Citations' }))
    const tab = await screen.findByTestId('citations')
    const printed = DEMO_REFERENCES[DEMO_FINISHED]!.printed!
    const card = within(tab).getByTestId('printed-check')
    expect(card).toHaveAttribute('data-state', 'passed')
    expect(within(card).getByTestId('printed-state')).toHaveTextContent(printed.say)
    for (const f of printed.findings) expect(card).toHaveTextContent(f.say)
    for (const line of printed.not_judged) expect(within(card).getByTestId('not-judged')).toHaveTextContent(line)
    expect(within(card).getByTestId('printed-counts')).toHaveTextContent('cites 12 sources in 43 places and lists 12')
    // the finished side: the check is not offered, and the page says where it is
    expect(within(card).queryByTestId('check-citations')).toBeNull()
    expect(within(card).getByTestId('check-not-offered')).toHaveTextContent(printed.act.say!)
    expect(within(card).getByRole('link', { name: 'Open this page on the live copy' })).toHaveAttribute(
      'href',
      `/studies/${DEMO_LIVE}/writing?tab=citations`,
    )
  })

  it('states what the models\' citations were checked against, part by part, word for word', async () => {
    await openWriting(DEMO_FINISHED, '?tab=citations')
    const tab = await screen.findByTestId('citations')
    expect(within(tab).getByTestId('check-says')).toHaveTextContent(CHECK_SAYS)
    expect(DEMO_REFERENCES[DEMO_FINISHED]!.check_says).toBe(CHECK_SAYS)
    expect(within(tab).getByTestId('check-result')).toHaveTextContent(DEMO_REFERENCES[DEMO_FINISHED]!.check.say)
    for (const p of DEMO_REFERENCES[DEMO_FINISHED]!.check.parts) expect(within(tab).getByTestId('check')).toHaveTextContent(p.say)
    expect(screen.getByTestId('knowledge-bases')).toHaveTextContent('knowledge base baseline-2026-05')
  })

  it('lists the references as the report prints them: only what its text cites, in the order of first citation', async () => {
    await openWriting(DEMO_FINISHED, '?tab=citations')
    const list = await screen.findByTestId('reference-list')
    const entries = DEMO_REFERENCES[DEMO_FINISHED]!.entries
    const rows = [...list.querySelectorAll('tr[data-entry]')]
    expect(rows.map((r) => Number(r.getAttribute('data-entry')))).toEqual(entries.map((e) => e.n))
    expect(entryRow(1)).toHaveTextContent('[1]')
    expect(entryRow(1)).toHaveTextContent('PubChem Compound 7239 (database).')
    expect(entryRow(1)).toHaveTextContent("The Background's sources")
    const boilerplate = entries.find((e) => e.kind === 'boilerplate')!
    expect(entryRow(boilerplate.n!)).toHaveTextContent(boilerplate.title!)
    expect(entryRow(boilerplate.n!)).toHaveTextContent("The report definitions' source library")
    expect(within(entryRow(boilerplate.n!)).getByRole('link', { name: 'DOI' })).toHaveAttribute('target', '_blank')
    expect(screen.getByTestId('citations')).toHaveTextContent(DEMO_REFERENCES[DEMO_FINISHED]!.numbering_say)
  })

  it('choosing an entry shows it as printed, the sentences of the report that cite it, and why it has no extracted statements', async () => {
    const { user } = await openWriting(DEMO_FINISHED, '?tab=citations')
    await screen.findByTestId('reference-list')
    const entry = DEMO_REFERENCES[DEMO_FINISHED]!.entries.find((e) => e.kind === 'boilerplate')!
    await user.click(entryRow(entry.n!))
    const detail = await screen.findByTestId(`entry-${entry.n}`)
    expect(detail).toHaveTextContent(entry.entry!)
    expect(detail).toHaveTextContent(entry.cited_in[0]!.sentences[0]!)
    expect(detail).toHaveTextContent("not a paper of the knowledge base")
    const doi = within(detail).getByRole('link', { name: `https://doi.org/${entry.doi}` })
    expect(doi).toHaveAttribute('href', `https://doi.org/${entry.doi}`)
    expect(doi).toHaveAttribute('target', '_blank')

    await user.click(entryRow(2))
    const source = await screen.findByTestId('entry-2')
    expect(source).toHaveTextContent('not a paper of the knowledge base')
    expect(source).toHaveTextContent(DEMO_REFERENCES[DEMO_FINISHED]!.entries[1]!.cited_in[0]!.sentences[0]!)
  })

  it('lists the recorded sources the report does not list, each with the reason and what the knowledge base holds of a paper', async () => {
    const { user } = await openWriting(DEMO_FINISHED, '?tab=citations')
    const card = await screen.findByTestId('not-listed')
    const idle = DEMO_REFERENCES[DEMO_FINISHED]!.not_listed
    expect(card).toHaveTextContent(`Recorded sources the report does not list (${idle.length})`)
    const paper = idle.find((e) => e.kind === 'paper' && (e.statements?.length ?? 0) > 0)!
    const row = card.querySelector(`tr[data-entry="${paper.slug}"]`) as HTMLElement
    expect(row).toHaveTextContent(paper.title!)
    expect(row).toHaveTextContent(paper.why_not_listed!)
    expect(row).toHaveTextContent(`Knowledge base ${paper.knowledge_base}`)
    await user.click(row)
    const detail = await screen.findByTestId(`entry-${paper.slug}`)
    expect(detail).toHaveTextContent(paper.statements![0]!)
    expect(detail).toHaveTextContent('Offered to the model for')
    expect(detail).toHaveTextContent('No sentence cites this entry.')
  })

  it('on the live copy the citations have not been checked: no list is shown, and the check is offered and runs', async () => {
    const { user } = await openWriting(DEMO_LIVE, '?tab=citations')
    const card = await screen.findByTestId('printed-check')
    expect(card).toHaveAttribute('data-state', 'not_checked')
    expect(within(card).getByTestId('printed-state')).toHaveTextContent(DEMO_REFERENCES[DEMO_LIVE]!.printed!.say)
    expect(screen.getByTestId('no-list-yet')).toHaveTextContent('There is no list to show until the citations are checked.')
    expect(screen.queryByTestId('reference-list')).toBeNull()
    await user.click(within(card).getByRole('button', { name: 'Check the citations' }))
    const outcome = await screen.findByTestId('check-outcome')
    expect(outcome).toHaveTextContent(
      'The citations were checked and the result was recorded: 43 citations in the printed report, 12 sources listed. No error was found. 1 check could not be made or needs a look.',
    )
    await waitFor(() => expect(screen.queryByText('Checking the citations')).toBeNull())
  })

  it('a study of a report has no list of its own and points at the report\'s', async () => {
    await openWriting(DEMO_FINISHED_RAT, '?tab=citations')
    const pointer = await screen.findByTestId('references-pointer')
    expect(within(pointer).getByRole('link')).toHaveAttribute('href', `/studies/${DEMO_FINISHED}/writing?tab=citations`)
    expect(screen.queryByTestId('printed-check')).toBeNull()
    expect(screen.queryByTestId('reference-list')).toBeNull()
    expect(screen.getByTestId('check')).toHaveTextContent(DEMO_REFERENCES[DEMO_FINISHED_RAT]!.check.say)
  })
})
