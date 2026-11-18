import { screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { writingPaths, type PartDetail } from '../../api/demoWriting'
import {
  DEMO_FINISHED,
  DEMO_FINISHED_RAT,
  DEMO_LIVE,
  DEMO_LIVE_RAT,
  DEMO_PARTS,
  DEMO_WRITING,
  REFUSAL_DEMO_REFERENCE,
  STREAM_BACKGROUND_SOURCES_UNREACHABLE,
} from '../../api/mocks/fixtures/demo-writing'
import { REFUSAL_SECTION_OWNED, toNdjson } from '../../api/mocks/fixtures'
import { server } from '../../api/mocks/node'
import { alertTitled, openPart, openWriting, partRow } from './testing'
import { BUILT_FROM_DATA, WRITE_BACKGROUND, WRITE_SUMMARY, WRITTEN_BY_MODEL } from './words'

/** Written sections (the demo path, spec §4 S3), against the backend's own answers for NIEHS-12. */

describe('the list of written parts', () => {
  it('marks each part built from the data or written by a language model; Methods shows both, per subsection', async () => {
    await openWriting(DEMO_FINISHED)
    const report = screen.getByTestId('parts-own')
    expect(within(partRow('background', report)).getByTestId('who-wrote')).toHaveTextContent(WRITTEN_BY_MODEL)
    expect(partRow('background', report)).not.toHaveTextContent(BUILT_FROM_DATA)

    const rat = screen.getByTestId('parts-rat')
    const methods = partRow('methods', rat)
    const whoWrote = within(methods).getByTestId('who-wrote')
    expect(whoWrote).toHaveTextContent(BUILT_FROM_DATA)
    expect(whoWrote).toHaveTextContent(WRITTEN_BY_MODEL)
    // per subsection, as the backend says (narrative.methods_design.DATA_BUILT_KEYS)
    for (const s of DEMO_WRITING[DEMO_FINISHED]!.studies![0]!.parts[0]!.subsections!) {
      const li = methods.querySelector(`li[data-subsection="${s.key}"]`) as HTMLElement
      expect(li, s.key).toHaveTextContent(s.written_by === 'data' ? BUILT_FROM_DATA : WRITTEN_BY_MODEL)
      expect(li, s.key).not.toHaveTextContent(s.written_by === 'data' ? WRITTEN_BY_MODEL : BUILT_FROM_DATA)
    }
    expect(within(methods.querySelector('li[data-subsection="study_design"]') as HTMLElement).getByTestId('written-by')).toHaveTextContent(
      BUILT_FROM_DATA,
    )

    expect(within(partRow('results', rat)).getByTestId('who-wrote')).toHaveTextContent(BUILT_FROM_DATA)
    expect(within(partRow('results', rat)).getByTestId('who-wrote')).not.toHaveTextContent(WRITTEN_BY_MODEL)
    expect(within(partRow('genomics_liver_female', rat)).getByTestId('who-wrote')).toHaveTextContent(WRITTEN_BY_MODEL)
    // The Summary now in the report was built by rule: it is not called the model's.
    expect(within(partRow('summary', rat)).getByTestId('who-wrote')).toHaveTextContent(BUILT_FROM_DATA)
    expect(partRow('summary', rat)).toHaveTextContent('No language model wrote this text.')
    // Both studies of the report are listed.
    expect(screen.getByTestId('parts-mouse')).toHaveTextContent('DTXSID6020430_mouse')
  })

  it('says what is recorded of how each model text was written', async () => {
    await openWriting(DEMO_FINISHED)
    expect(within(partRow('background')).getByTestId('recorded')).toHaveTextContent('Prompt not recorded')
    const rat = screen.getByTestId('parts-rat')
    expect(within(partRow('methods', rat)).getByTestId('recorded')).toHaveTextContent('Prompt not recorded; rebuilt from the recorded facts')
    expect(within(partRow('methods', rat)).getByTestId('recorded')).toHaveTextContent('Inputs recorded')
    expect(within(partRow('bmd_summary', rat)).getByTestId('recorded')).toHaveTextContent('Inputs not recorded')
    expect(within(partRow('genomics_liver_female', rat)).getByTestId('recorded')).toHaveTextContent('Inputs recorded')
  })

  it('links to this step on the API page, by the names of its two groups, in a new tab', async () => {
    await openWriting(DEMO_FINISHED)
    const links = within(screen.getByTestId('api-page')).getAllByRole('link')
    expect(links.map((a) => a.textContent)).toEqual(['Written sections and their prompts', 'Citations and the literature behind them'])
    for (const a of links) {
      expect(a.getAttribute('href')).toMatch(/^\/docs#\//)
      expect(a).toHaveAttribute('target', '_blank')
    }
  })

  it('a study of a report points at the report for the Background', async () => {
    await openWriting(DEMO_FINISHED_RAT)
    const pointer = screen.getByTestId('background-pointer')
    expect(pointer).toHaveTextContent("The Background is the report's, not this study's.")
    expect(within(pointer).getByRole('link')).toHaveAttribute('href', `/studies/${DEMO_FINISHED}/writing?part=background`)
    expect(document.querySelector('tr[data-part="background"]')).toBeNull()
  })
})

describe('one part: the text beside how it was written', () => {
  it('a Background whose prompt was not kept says "Not recorded" and shows no text for it', async () => {
    const { user } = await openWriting(DEMO_FINISHED)
    const view = await openPart('background', user)
    expect(within(view).getByTestId('part-text')).toHaveTextContent('1,2-Dichlorobenzene (CASRN: 95-50-1')
    const prompt = within(view).getByTestId('given-prompt')
    expect(within(prompt).getByTestId('record')).toHaveTextContent('Not recorded')
    expect(prompt).toHaveTextContent('was not recorded')
    expect(within(prompt).queryByText('Show the text')).toBeNull()
    expect(within(view).getByTestId('citation-check')).toHaveTextContent(
      'Every citation in this text points at a source that was supplied.',
    )
    expect(within(view).getByTestId('check-says')).toHaveTextContent(DEMO_WRITING[DEMO_FINISHED]!.check_says)
  })

  it('the model paragraphs of the benchmark dose summary have nothing recorded but the text and the model', async () => {
    const { user } = await openWriting(DEMO_FINISHED)
    const view = await openPart('bmd_summary', user, screen.getByTestId('parts-rat'))
    expect(within(view).getByTestId('how-written')).toHaveTextContent('claude-sonnet-4-6')
    const given = within(view).getAllByTestId('record')
    expect(given.map((g) => g.textContent)).toEqual(['Not recorded'])
  })

  it('Methods: per subsection who wrote it, the facts as recorded, the prompt labeled as rebuilt', async () => {
    const { user } = await openWriting(DEMO_FINISHED)
    const view = await openPart('methods', user, screen.getByTestId('parts-rat'))
    const design = view.querySelector('[data-block="study_design"]') as HTMLElement
    expect(within(design).getByTestId('written-by')).toHaveTextContent(BUILT_FROM_DATA)
    const obs = view.querySelector('[data-block="clinical_obs"]') as HTMLElement
    expect(within(obs).getByTestId('written-by')).toHaveTextContent(WRITTEN_BY_MODEL)
    expect(within(within(view).getByTestId('given-facts')).getByTestId('record')).toHaveTextContent('Recorded with the result')
    const prompt = within(view).getByTestId('given-prompt')
    expect(within(prompt).getByTestId('record')).toHaveTextContent('Rebuilt from the recorded facts')
    expect(prompt).toHaveTextContent('The prompt itself was not recorded.')
    await user.click(within(prompt).getByText('Show the text'))
    expect(await within(prompt).findByLabelText('The prompt')).toHaveTextContent('Generate the Materials and Methods section')
  })

  it('an interpretation: the text given to the model as sent, the whole prompt not recorded, the knowledge base and the papers offered', async () => {
    const { user } = await openWriting(DEMO_FINISHED_RAT)
    const view = await openPart('genomics_liver_female', user)
    const context = within(view).getByTestId('given-context')
    expect(within(context).getByTestId('record')).toHaveTextContent('As sent to the model')
    expect(context).toHaveTextContent('57,229 characters')
    await user.click(within(context).getByText('Show the text'))
    expect(await within(context).findByLabelText("The study's results and the literature evidence")).toHaveTextContent(
      '=== DOSE-RESPONSE SUMMARY ===',
    )
    expect(within(within(view).getByTestId('given-prompt')).getByTestId('record')).toHaveTextContent('Not recorded')
    expect(within(view).getByTestId('how-written')).toHaveTextContent('baseline-2026-05')
    const papers = within(view).getByTestId('papers-offered')
    expect(papers).toHaveTextContent('P1')
    const doi = within(papers).getAllByRole('link')[0]!
    expect(doi.getAttribute('href')).toMatch(/^https:\/\/doi\.org\//)
    expect(doi).toHaveAttribute('target', '_blank')
  })

  it('the results are built from the data, and link to where a table is followed back', async () => {
    const { user } = await openWriting(DEMO_FINISHED_RAT)
    const view = await openPart('results', user)
    expect(within(view).getByTestId('how-written')).toHaveTextContent('None: no language model is involved')
    expect(within(view).queryByText('What the model was given')).toBeNull()
    expect(within(view).getByRole('link', { name: /Follow a table back/ })).toHaveAttribute(
      'href',
      `/studies/${DEMO_FINISHED_RAT}/dataset`,
    )
  })

  it('the Summary: built by rule, the template version, no run recorded, and what a run would send labeled as rebuilt', async () => {
    const { user } = await openWriting(DEMO_FINISHED_RAT)
    const view = await openPart('summary', user)
    expect(within(view).getByTestId('how-written')).toHaveTextContent('Version 1 is the current one.')
    expect(within(within(view).getByTestId('given-prompt')).getByTestId('record')).toHaveTextContent('Not recorded')
    expect(within(within(view).getByTestId('given-prompt_now')).getByTestId('record')).toHaveTextContent('Rebuilt from the recorded facts')
    expect(within(within(view).getByTestId('given-template')).getByTestId('record')).toHaveTextContent('Recorded with the result')
    expect(within(view).getByTestId('unmatched')).toHaveTextContent('was not worded by a model')
    expect(within(view).getByTestId('summary-runs')).toHaveTextContent('No run is recorded')
    await user.click(within(view).getByRole('button', { name: /All written parts/ }))
    expect(await screen.findByTestId('parts-own')).toBeInTheDocument()
  })

  it('a part that cannot be read shows the refusal in plain words', async () => {
    await openWriting(DEMO_FINISHED, '?part=methods')
    const alert = await alertTitled('This part could not be read')
    expect(alert).toHaveTextContent('This study has no written part called “methods”.')
  })
})

describe('the acts', () => {
  it('the finished side offers no act, says where writing is done, and links to the same page of the live copy', async () => {
    const { user } = await openWriting(DEMO_FINISHED)
    expect(screen.queryByRole('button', { name: WRITE_BACKGROUND })).toBeNull()
    expect(screen.queryByRole('button', { name: WRITE_SUMMARY })).toBeNull()
    expect(screen.queryByTestId('acts')).toBeNull()
    const note = screen.getByTestId('finished-note')
    expect(note).toHaveTextContent('Writing is done on the live copy.')
    expect(within(note).getByRole('link')).toHaveAttribute('href', `/studies/${DEMO_LIVE}/writing`)
    // Nor in a part: the Summary's runs offer nothing to take.
    await openPart('summary', user, screen.getByTestId('parts-rat'))
    expect(screen.queryByRole('button', { name: /Take this text/ })).toBeNull()
  })

  it('the live report offers the Background, and says why the Summary is not written there', async () => {
    const { user } = await openWriting(DEMO_LIVE)
    expect(partRow('background')).toHaveTextContent('Not written yet')
    const acts = screen.getByTestId('acts')
    expect(within(acts).getByRole('button', { name: WRITE_SUMMARY })).toBeDisabled()
    expect(acts).toHaveTextContent(DEMO_WRITING[DEMO_LIVE]!.acts.summary.say!)
    await user.click(within(acts).getByRole('button', { name: WRITE_BACKGROUND }))
    const outcome = await screen.findByTestId('act-outcome')
    expect(outcome).toHaveTextContent('The Background was written and saved as a draft. It is not approved.')
    expect(outcome).toHaveTextContent('7 paragraphs, 5 references; 0 citations could not be traced')
    await waitFor(() => expect(screen.queryByText('Writing the Background')).toBeNull())
  })

  it('a run that ends in a refusal shows it through the refusal explainer, and nothing is claimed', async () => {
    server.use(
      http.post(writingPaths.writeBackground(DEMO_LIVE), () =>
        new HttpResponse(toNdjson(STREAM_BACKGROUND_SOURCES_UNREACHABLE), { headers: { 'Content-Type': 'application/x-ndjson' } }),
      ),
    )
    const { user } = await openWriting(DEMO_LIVE)
    await user.click(screen.getByRole('button', { name: WRITE_BACKGROUND }))
    const alert = await alertTitled('The run did not finish')
    expect(alert).toHaveTextContent("The Background can't be written now: ATSDR could not be reached")
    expect(screen.queryByTestId('act-outcome')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByText('The run did not finish')).toBeNull())
  })

  it('a refusal before the run starts is shown the same way', async () => {
    server.use(http.post(writingPaths.writeBackground(DEMO_LIVE), () => HttpResponse.json(REFUSAL_DEMO_REFERENCE, { status: 409 })))
    const { user } = await openWriting(DEMO_LIVE)
    await user.click(screen.getByRole('button', { name: WRITE_BACKGROUND }))
    expect(await alertTitled('The run did not finish')).toHaveTextContent(REFUSAL_DEMO_REFERENCE.error.say)
  })

  it('the live study runs the Summary; the report is said to be unchanged, with the numbers that were not given', async () => {
    const { user } = await openWriting(DEMO_LIVE_RAT)
    const acts = screen.getByTestId('acts')
    expect(within(acts).getByRole('button', { name: WRITE_BACKGROUND })).toBeDisabled()
    expect(acts).toHaveTextContent(DEMO_WRITING[DEMO_LIVE_RAT]!.acts.background.say!)
    await user.click(within(acts).getByRole('button', { name: WRITE_SUMMARY }))
    const outcome = await screen.findByTestId('act-outcome')
    expect(outcome).toHaveTextContent('The Summary in the report was not changed.')
    expect(outcome).toHaveTextContent('not among the facts the model was given: 95.')
  })

  const WITH_RUN: PartDetail = {
    ...DEMO_PARTS[`${DEMO_LIVE_RAT}/summary`]!,
    runs: [
      {
        run_id: 'r20261118T181500-3d4e5f',
        at: '2026-11-18T18:15:00Z',
        template_version: 1,
        model: 'claude-sonnet-4-6',
        prompt: 'SYSTEM INSTRUCTIONS\n\nReword the draft.\n\nPROMPT\n\nThe draft …',
        paragraphs: ['Worded by the model, at 95 ppm.'],
        unmatched_numbers: ['95'],
        in_use: false,
      },
    ],
  }

  it('a run shows its prompt as sent and its unmatched numbers, and can be taken into the report on the live study', async () => {
    server.use(http.get(writingPaths.part(DEMO_LIVE_RAT, 'summary'), () => HttpResponse.json(WITH_RUN)))
    const { user } = await openWriting(DEMO_LIVE_RAT, '?part=summary')
    const run = await screen.findByTestId('run-r20261118T181500-3d4e5f')
    expect(run).toHaveTextContent('Worded by the model, at 95 ppm.')
    expect(within(run).getByTestId('record')).toHaveTextContent('As sent to the model')
    expect(run).toHaveTextContent('95')
    await user.click(within(run).getByRole('button', { name: 'Take this text into the report' }))
    expect(await screen.findByText(/is now the Summary in the report, as a draft/)).toBeInTheDocument()
  })

  it('taking a run over an approved Summary is refused, and the refusal is shown', async () => {
    server.use(
      http.get(writingPaths.part(DEMO_LIVE_RAT, 'summary'), () => HttpResponse.json(WITH_RUN)),
      http.post(writingPaths.takeSummaryRun(DEMO_LIVE_RAT, 'r20261118T181500-3d4e5f'), () =>
        HttpResponse.json(REFUSAL_SECTION_OWNED, { status: 409 }),
      ),
    )
    const { user } = await openWriting(DEMO_LIVE_RAT, '?part=summary')
    const run = await screen.findByTestId('run-r20261118T181500-3d4e5f')
    await user.click(within(run).getByRole('button', { name: 'Take this text into the report' }))
    const alert = await alertTitled('The text was not taken into the report')
    expect(alert).toHaveTextContent(REFUSAL_SECTION_OWNED.error.say)
  })
})
