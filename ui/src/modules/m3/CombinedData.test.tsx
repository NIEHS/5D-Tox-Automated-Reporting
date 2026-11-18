import { screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it, onTestFinished } from 'vitest'
import { setDemoStage } from '../../api/mocks/demoData'
import { REFUSAL_RUN_IN_FLIGHT, STATE_UPLOADED } from '../../api/mocks/fixtures'
import {
  DATASET_FINISHED,
  DATASET_LIVE_VALIDATED,
  DEMO_FINISHED_RAT,
  DEMO_LIVE_RAT,
  DEMO_LIVE_REPORT,
  SOURCES_FINISHED,
  STATE_LIVE_VALIDATED,
} from '../../api/mocks/fixtures/demoData'
import { server } from '../../api/mocks/node'
import { renderApp } from '../../test/render'
import { COMBINE_LABEL } from './CombinedData'

/**
 * Combined data (the demo path, S1), against the backend's own answers for
 * the NIEHS-12 pair: the live rat study, which the act moves on, and the
 * finished one, which only reads.
 */

async function open(id: string) {
  const r = renderApp(`/studies/${id}/dataset`)
  await screen.findByRole('heading', { level: 3, name: 'Combined data' })
  return r
}

const combine = () => screen.getByRole('button', { name: COMBINE_LABEL })

/** The acts the page sends from now on, as "POST /path"; read when the test ends. */
function countActs(): () => string[] {
  const seen: string[] = []
  const listen = ({ request }: { request: Request }) => {
    if (request.method === 'POST') seen.push(`POST ${new URL(request.url).pathname}`)
  }
  server.events.on('request:start', listen)
  onTestFinished(() => server.events.removeListener('request:start', listen))
  return () => seen
}

/** The refusal explainer that carries `title` (a page has other alerts: its notices). */
async function refusal(title: string): Promise<HTMLElement> {
  return (await screen.findByText(title)).closest('[role="alert"]') as HTMLElement
}

/** Choose a results table under "Follow a table back". */
async function follow(user: ReturnType<typeof renderApp>['user'], name: string) {
  const radio = await screen.findByRole('radio', { name })
  await user.click(radio.closest('label') as HTMLElement)
}

describe('the page in the study frame', () => {
  it("keeps the study's header above it", async () => {
    await open(DEMO_LIVE_RAT)
    expect(screen.getByLabelText('Study id')).toHaveTextContent(DEMO_LIVE_RAT)
    expect(screen.getByRole('link', { name: 'This step on the API page' })).toHaveAttribute('href', '/docs')
    expect(screen.getByRole('link', { name: 'This step on the API page' })).toHaveAttribute('target', '_blank')
    expect(screen.getByText(/the group “Combined data”/)).toBeInTheDocument()
  })
})

describe('before the files are combined', () => {
  it('shows the files as the file check recognized them, and each assay from workbook to converted table', async () => {
    await open(DEMO_LIVE_RAT)
    expect(await screen.findByTestId('not-combined')).toHaveTextContent('The files are not combined yet.')
    const files = within(screen.getByTestId('files'))
    for (const f of DATASET_LIVE_VALIDATED.files) expect(files.getByText(f.filename)).toBeInTheDocument()
    expect(files.getAllByText('Workbook').length).toBeGreaterThan(0)
    expect(files.getAllByText('Converted table').length).toBeGreaterThan(0)
    expect(files.getByText('BMDExpress project')).toBeInTheDocument()

    const chains = screen.getByTestId('assay-chains')
    const bodyWeight = within(chains).getByText('Body Weight').closest('tr') as HTMLElement
    expect(bodyWeight).toHaveTextContent('108020006_Individual_Animal_Body_Weight_Data_Rats.xlsx')
    expect(bodyWeight).toHaveTextContent('body_weight_truth_female.txt')
    expect(bodyWeight).toHaveTextContent("converted from 108020006_Individual_Animal_Body_Weight_Data_Rats.xlsx (recorded in the table's own notes)")
    // nothing is combined: no experiment, no "taken into the dataset" column
    expect(screen.queryByTestId('experiments')).not.toBeInTheDocument()
    expect(within(chains).queryByText('Taken into the dataset from')).not.toBeInTheDocument()
  })

  it('offers the one act when the backend says combining is legal', async () => {
    await open(DEMO_LIVE_RAT)
    await screen.findByTestId('files')
    expect(STATE_LIVE_VALIDATED.legal_actions).toContain('INTEGRATE')
    expect(combine()).toBeEnabled()
    expect(screen.queryByTestId('combine-why-not')).not.toBeInTheDocument()
  })

  it('disables the act when the backend does not allow it, and says why from the state', async () => {
    // The live study as it would stand with files not yet checked: the stage,
    // the legal actions and the next step are the backend's own for that stage.
    server.use(
      http.get('/api/v2/studies/:id/state', () =>
        HttpResponse.json({
          ...STATE_LIVE_VALIDATED,
          phase: STATE_UPLOADED.phase,
          legal_actions: STATE_UPLOADED.legal_actions,
          stands: STATE_UPLOADED.stands,
        }),
      ),
    )
    await open(DEMO_LIVE_RAT)
    await screen.findByTestId('files')
    expect(STATE_UPLOADED.legal_actions).not.toContain('INTEGRATE')
    expect(combine()).toBeDisabled()
    const why = screen.getByTestId('combine-why-not')
    expect(why).toHaveTextContent(`Not available now: ${STATE_UPLOADED.stands.say}.`)
    expect(within(why).getByRole('link', { name: STATE_UPLOADED.stands.next?.say })).toHaveAttribute('href', `/studies/${DEMO_LIVE_RAT}/files`)
  })

  it('combines the files in a foreground wait, once, then shows the dataset and what the run did', async () => {
    const acts = countActs()
    const { user } = await open(DEMO_LIVE_RAT)
    await screen.findByTestId('files')
    await user.click(combine())
    const outcome = await screen.findByTestId('combine-outcome')
    expect(outcome).toHaveTextContent('The files were combined into one dataset.')
    expect(outcome).toHaveTextContent("9 experiments; 5 result sets of the study's own benchmark dose analysis")
    // the next step is the backend's, re-read after the run
    expect(within(outcome).getByRole('link', { name: 'Process the data' })).toHaveAttribute('href', `/studies/${DEMO_LIVE_RAT}/process`)
    expect(await screen.findByTestId('experiments')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument(), { timeout: 6000 })
    // combined: the act is not offered again
    expect(screen.queryByRole('button', { name: COMBINE_LABEL })).not.toBeInTheDocument()
    // The page changes while the act runs (the dataset appears); the wait must
    // not start the act a second time (it did, once: found in a live run).
    expect(acts()).toEqual([`POST /api/v2/studies/${DEMO_LIVE_RAT}/integrate`])
  })

  it('shows a refusal of the act through the refusal explainer, and changes nothing', async () => {
    server.use(http.post('/api/v2/studies/:id/integrate', () => HttpResponse.json(REFUSAL_RUN_IN_FLIGHT, { status: 409 })))
    const { user } = await open(DEMO_LIVE_RAT)
    await screen.findByTestId('files')
    await user.click(combine())
    const alert = await refusal('The run did not finish')
    expect(alert).toHaveTextContent(REFUSAL_RUN_IN_FLIGHT.error.say)
    await user.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument(), { timeout: 6000 })
    expect(screen.getByTestId('not-combined')).toBeInTheDocument()
    expect(combine()).toBeEnabled()
  })

  it('explains a dataset that cannot be read, and offers to try again', async () => {
    server.use(
      http.get('/api/v2/studies/:id/dataset', () =>
        HttpResponse.json(
          { error: { code: 'dataset_invalid', status: 422, message: 'BMDProject schema validation failed', say: "The study's combined dataset doesn't have the form the report needs.", fix: 'M3', details: {} } },
          { status: 422 },
        ),
      ),
    )
    await open(DEMO_LIVE_RAT)
    const alert = await refusal('The combined data could not be read')
    expect(alert).toHaveTextContent("The study's combined dataset doesn't have the form the report needs.")
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: COMBINE_LABEL })).not.toBeInTheDocument()
  })
})

describe('after the files are combined', () => {
  it('lists the experiments with the file each came from and whether the study’s own benchmark doses are in the dataset', async () => {
    await open(DEMO_FINISHED_RAT)
    const table = within(await screen.findByTestId('experiments'))
    const experiments = DATASET_FINISHED.experiments ?? []
    expect(experiments).toHaveLength(9)
    for (const e of experiments) {
      const row = table.getByText(e.name as string).closest('tr') as HTMLElement
      expect(row).toHaveTextContent(e.taken_from?.filename as string)
      expect(row).toHaveTextContent(e.own_benchmark_doses ? 'In the dataset' : 'Not among the files')
    }
    const organ = table.getByText('organ_weights_truth_female').closest('tr') as HTMLElement
    expect(organ).toHaveTextContent('Organ Weight')
    expect(organ).toHaveTextContent('Female')
    expect(organ).toHaveTextContent('organ_weights_truth_female.txt')
  })

  it('shows each assay from workbook to converted table to the file the dataset took', async () => {
    await open(DEMO_FINISHED_RAT)
    const chains = await screen.findByTestId('assay-chains')
    expect(within(chains).getAllByText('Taken into the dataset from').length).toBeGreaterThan(0)
    const organ = within(chains).getByText('Organ Weight').closest('tr') as HTMLElement
    expect(organ).toHaveTextContent('108020006_Individual_Animal_Organ_Weight_Data_Rats.xlsx')
    expect(organ).toHaveTextContent('the converted table')
    const genes = within(chains).getByText('Gene expression').closest('tr') as HTMLElement
    expect(genes).toHaveTextContent('the BMDExpress project')
  })

  it("shows the animal accounting's summary", async () => {
    await open(DEMO_FINISHED_RAT)
    const accounting = await screen.findByTestId('accounting')
    expect(accounting).toHaveTextContent('The accounting found no inconsistency between the files.')
    expect(within(accounting).getByRole('table', { name: 'Animals by dose group' })).toHaveTextContent('500')
    expect(within(accounting).getByRole('table', { name: 'Animals found per assay, by kind of file' })).toHaveTextContent('Organ Weight')
  })

  it('says so when the report has no results tables yet, and links to Process', async () => {
    setDemoStage('combined')
    await open(DEMO_LIVE_RAT)
    const none = await screen.findByTestId('no-tables')
    expect(none).toHaveTextContent('The report has no results tables yet.')
    expect(within(none).getByRole('link', { name: 'Go to Process' })).toHaveAttribute('href', `/studies/${DEMO_LIVE_RAT}/process`)
  })
})

describe('follow a table back', () => {
  it('follows each row of a table to its experiment, its file and its workbook, and says where the benchmark doses come from', async () => {
    const { user } = await open(DEMO_FINISHED_RAT)
    await follow(user, 'Organ Weight')
    const sources = await screen.findByTestId('table-sources')
    const expected = SOURCES_FINISHED['bm2_organ-weight']!.sexes[0]!
    expect(sources).toHaveTextContent('Summary of Select Organ Weights of Female Rats')
    const female = within(screen.getByTestId('sources-Female'))
    // the chain, as recorded
    expect(expected.stops).toBeNull()
    expect(screen.queryByTestId('chain-stops')).not.toBeInTheDocument()
    expect(female.getAllByText('organ_weights_truth_female').length).toBeGreaterThan(0)
    expect(female.getByText(/Its endpoints: Heart, Kidney-Left/)).toBeInTheDocument()
    expect(female.getByText("(recorded in the table's own notes)")).toBeInTheDocument()
    // the benchmark doses: fit here, at one standard deviation
    expect(expected.benchmark_dose?.source).toBe('inferred')
    expect(female.getAllByText('Fit by this application').length).toBeGreaterThan(0)
    expect(female.getByText(/Benchmark response: 1 standard deviation from the mean\./)).toBeInTheDocument()
    // row by row
    const liver = female.getByText('Liver Absolute (g)').closest('tr') as HTMLElement
    const row = expected.rows.find((r) => r.label === 'Liver Absolute (g)')!
    expect(liver).toHaveTextContent('organ_weights_truth_female.txt')
    expect(liver).toHaveTextContent('108020006_Individual_Animal_Organ_Weight_Data_Rats.xlsx')
    expect(liver).toHaveTextContent(row.bmd as string)
    expect(liver).toHaveTextContent(row.bmdl as string)
    expect(liver).toHaveTextContent('Fit by this application')
    // a row with no benchmark dose printed claims no origin for one
    const heart = female.getByText('Heart Absolute (g)').closest('tr') as HTMLElement
    expect(heart).toHaveTextContent('none printed for this row')
    expect(heart).not.toHaveTextContent('Fit by this application')
  })

  it('names the endpoint where the dataset has one of exactly the row’s name, and says so where it has not', async () => {
    const { user } = await open(DEMO_FINISHED_RAT)
    await follow(user, 'Clinical Chemistry')
    const female = within(await screen.findByTestId('sources-Female'))
    const albumin = female.getAllByText('Albumin')[0]!.closest('tr') as HTMLElement
    expect(albumin).not.toHaveTextContent('not recorded for this row')
    const ratio = female.getByText('A/G Ratio').closest('tr') as HTMLElement
    expect(ratio).toHaveTextContent('not recorded for this row')
  })

  it('says where the chain stops when a link is not recorded, and guesses nothing', async () => {
    const { user } = await open(DEMO_FINISHED_RAT)
    await follow(user, 'Clinical Observations')
    const stops = await screen.findByTestId('chain-stops')
    expect(SOURCES_FINISHED['bm2_clinical-observations']!.sexes[0]!.stops).toBe('experiment')
    expect(stops).toHaveTextContent('The record stops here')
    expect(stops).toHaveTextContent('The dataset has no experiment under the assay name "Clinical Observations"')
    const female = within(screen.getByTestId('sources-Female'))
    expect(female.getByText('This table prints no benchmark dose.')).toBeInTheDocument()
    const row = female.getByText('Lethargic').closest('tr') as HTMLElement
    expect(within(row).getAllByText('not recorded').length).toBeGreaterThanOrEqual(3)
  })

  it('explains a table that cannot be followed', async () => {
    server.use(
      http.get('/api/v2/studies/:id/tables/:key/sources', () =>
        HttpResponse.json(
          { error: { code: 'table_not_found', status: 404, message: 'no results table', say: "This study's report has no results table bm2_organ-weight.", fix: 'P1', details: {} } },
          { status: 404 },
        ),
      ),
    )
    const { user } = await open(DEMO_FINISHED_RAT)
    await follow(user, 'Organ Weight')
    const alert = await refusal('The table could not be followed back')
    expect(within(alert).getByRole('link', { name: /Go to Process/ })).toHaveAttribute('href', `/studies/${DEMO_FINISHED_RAT}/process`)
  })
})

describe('the finished side of the pair, and a report', () => {
  it('offers no act on the finished report, and links to the same page of the live copy', async () => {
    await open(DEMO_FINISHED_RAT)
    await screen.findByTestId('experiments')
    expect(screen.queryByRole('button', { name: COMBINE_LABEL })).not.toBeInTheDocument()
    const notice = screen.getByTestId('finished-notice')
    expect(notice).toHaveTextContent('This is the finished report, kept as it is for comparison.')
    expect(notice).toHaveTextContent('Combining the files is done on its live copy')
    expect(within(notice).getByRole('link', { name: /Open this page of the live copy/ })).toHaveAttribute('href', `/studies/${DEMO_LIVE_RAT}/dataset`)
  })

  it('offers no act on the finished side even before its files are combined', async () => {
    server.use(http.get('/api/v2/studies/:id/dataset', () => HttpResponse.json({ ...DATASET_LIVE_VALIDATED, id: DEMO_FINISHED_RAT })))
    await open(DEMO_FINISHED_RAT)
    await screen.findByTestId('not-combined')
    expect(screen.queryByRole('button', { name: COMBINE_LABEL })).not.toBeInTheDocument()
  })

  it('shows a choice of the studies on a report, which has no data of its own', async () => {
    renderApp(`/studies/${DEMO_LIVE_REPORT}/dataset`)
    const choice = await screen.findByTestId('study-choice')
    expect(choice).toHaveTextContent('Combined data works on one study at a time.')
    expect(within(choice).getByRole('link', { name: 'Open Combined data of the rat study' })).toHaveAttribute('href', '/studies/DTXSID6020430_live_rat/dataset')
    expect(within(choice).getByRole('link', { name: 'Open Combined data of the mouse study' })).toHaveAttribute('href', '/studies/DTXSID6020430_live_mouse/dataset')
    expect(screen.queryByRole('button', { name: COMBINE_LABEL })).not.toBeInTheDocument()
  })
})
