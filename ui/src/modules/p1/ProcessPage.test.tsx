import { screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it, onTestFinished } from 'vitest'
import { setDemoStage } from '../../api/mocks/demoData'
import {
  DEMO_FINISHED_RAT,
  DEMO_LIVE_RAT,
  DEMO_LIVE_REPORT,
  PARAMETERS_LIVE_COMBINED,
  PROCESS_SUMMARY_LIVE,
  PROCESS_SUMMARY_WARM,
  REFUSAL_LIVE_VALIDATED_PROCESS,
  STATE_LIVE_COMBINED,
  STATE_LIVE_VALIDATED,
} from '../../api/mocks/fixtures/demoData'
import { server } from '../../api/mocks/node'
import { renderApp } from '../../test/render'
import { RUN_LABEL } from './words'

/**
 * Process (the demo path, S2), against the backend's own answers for the
 * NIEHS-12 pair: the live rat study, files checked, then combined, then
 * processed; and the finished one, which only reads.
 */

async function open(id: string) {
  const r = renderApp(`/studies/${id}/process`)
  await screen.findByRole('heading', { level: 3, name: 'Process' })
  return r
}

const run = () => screen.getByRole('button', { name: RUN_LABEL })

describe('the pre-flight', () => {
  it("shows each of the study's parameters with where it comes from, and changes none", async () => {
    setDemoStage('combined')
    await open(DEMO_LIVE_RAT)
    const table = within(await screen.findByTestId('parameters'))
    const species = table.getByText('Species').closest('tr') as HTMLElement
    expect(species).toHaveTextContent(String(PARAMETERS_LIVE_COMBINED.values.species))
    expect(PARAMETERS_LIVE_COMBINED.sources.species).toBe('recorded')
    expect(within(species).getByText('From the files')).toBeInTheDocument()
    const schedule = table.getByText('Dosing schedule').closest('tr') as HTMLElement
    expect(schedule).toHaveTextContent(String(PARAMETERS_LIVE_COMBINED.values.dosing_schedule))
    expect(PARAMETERS_LIVE_COMBINED.sources.dosing_schedule).toBe('stated')
    expect(within(schedule).getByText('Stated')).toBeInTheDocument()
    expect(table.getByText('Vehicle').closest('tr')).toHaveTextContent('Does not apply to this study')
    // read-only: no field, no other button than the act
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(screen.queryByTestId('parameters-incomplete')).not.toBeInTheDocument()
  })

  it('shows the analysis method, the report definition and the knowledge base fixed for the study', async () => {
    setDemoStage('combined')
    await open(DEMO_LIVE_RAT)
    const pins = await screen.findByTestId('pins')
    expect(pins).toHaveTextContent(STATE_LIVE_COMBINED.pins.method?.name as string)
    expect(pins).toHaveTextContent('chosen by a person')
    expect(pins).toHaveTextContent(STATE_LIVE_COMBINED.pins.definition?.name as string)
    expect(screen.queryByTestId('method-unchosen')).not.toBeInTheDocument()
    expect(await screen.findByText('baseline-2026-05')).toBeInTheDocument()
    expect(screen.getByText('Usable')).toBeInTheDocument()
  })
})

describe('the act', () => {
  it('is offered when the backend says Process is legal and no parameter is missing', async () => {
    setDemoStage('combined')
    await open(DEMO_LIVE_RAT)
    await screen.findByTestId('parameters')
    expect(STATE_LIVE_COMBINED.legal_actions).toContain('PROCESS')
    await waitFor(() => expect(run()).toBeEnabled())
    expect(screen.queryByTestId('run-why-not')).not.toBeInTheDocument()
    expect(screen.getByTestId('run-act')).toHaveTextContent('This takes about three minutes.')
  })

  it('is disabled before the files are combined, with the reason and the next step from the state', async () => {
    await open(DEMO_LIVE_RAT)
    await screen.findByTestId('parameters')
    expect(STATE_LIVE_VALIDATED.legal_actions).not.toContain('PROCESS')
    expect(run()).toBeDisabled()
    const why = screen.getByTestId('run-why-not')
    expect(why).toHaveTextContent(`Not available now: ${STATE_LIVE_VALIDATED.stands.say}.`)
    expect(within(why).getByRole('link', { name: STATE_LIVE_VALIDATED.stands.next?.say })).toHaveAttribute('href', `/studies/${DEMO_LIVE_RAT}/dataset`)
  })

  it('is disabled when a study parameter is missing, which is shown as the refusal it will cause', async () => {
    setDemoStage('combined')
    server.use(
      http.get('/api/workflow/:id/study-parameters', () =>
        HttpResponse.json({
          ...PARAMETERS_LIVE_COMBINED,
          complete: false,
          values: { ...PARAMETERS_LIVE_COMBINED.values, dosing_days: null },
          missing: ['dosing_days'],
          problems: ['the number of days of dosing is not recorded in the data and has not been stated'],
        }),
      ),
    )
    await open(DEMO_LIVE_RAT)
    const alert = await screen.findByTestId('parameters-incomplete')
    expect(alert).toHaveTextContent('The analysis will be refused until every study parameter is recorded in the data or stated.')
    expect(alert).toHaveTextContent('the number of days of dosing is not recorded in the data and has not been stated')
    const row = within(screen.getByTestId('parameters')).getByText('Days of dosing').closest('tr') as HTMLElement
    expect(within(row).getByRole('button', { name: /days of dosing is missing/ })).toHaveTextContent('[days of dosing pending]')
    expect(run()).toBeDisabled()
    expect(screen.getByTestId('run-why-not')).toHaveTextContent('a study parameter is missing or in conflict')
  })

  it('is disabled while no person has chosen the analysis method, and proposes the one the backend suggests', async () => {
    setDemoStage('combined')
    const method = STATE_LIVE_COMBINED.pins.method!
    server.use(
      http.get('/api/v2/studies/:id/state', () =>
        HttpResponse.json({
          ...STATE_LIVE_COMBINED,
          pins: {
            ...STATE_LIVE_COMBINED.pins,
            method: { ...method, pinned: false, pinned_by: null, suggestion: { name: 'ntp-5day-2025', why: 'the newest profile its analyses agree with' } },
          },
        }),
      ),
    )
    await open(DEMO_LIVE_RAT)
    const unchosen = await screen.findByTestId('method-unchosen')
    expect(unchosen).toHaveTextContent('No person has chosen the analysis method.')
    expect(unchosen).toHaveTextContent('Proposed: ntp-5day-2025 (the newest profile its analyses agree with).')
    expect(within(unchosen).getByRole('link', { name: 'Go to Method and report definition' })).toHaveAttribute('href', `/studies/${DEMO_LIVE_RAT}/pins`)
    await screen.findByTestId('parameters')
    expect(run()).toBeDisabled()
    expect(screen.getByTestId('run-why-not')).toHaveTextContent('no person has chosen the analysis method')
  })

  it('runs in a foreground wait, once, then shows what was computed, what was written, and the next step', async () => {
    setDemoStage('combined')
    const acts: string[] = []
    const listen = ({ request }: { request: Request }) => {
      if (request.method === 'POST') acts.push(`POST ${new URL(request.url).pathname}`)
    }
    server.events.on('request:start', listen)
    onTestFinished(() => server.events.removeListener('request:start', listen))
    const { user } = await open(DEMO_LIVE_RAT)
    await screen.findByTestId('parameters')
    await waitFor(() => expect(run()).toBeEnabled())
    await user.click(run())
    const outcome = await screen.findByTestId('process-outcome')
    expect(outcome).toHaveTextContent('The analysis ran to its end.')
    const computed = within(outcome).getByRole('list', { name: 'Computed in this run' })
    for (const u of PROCESS_SUMMARY_LIVE.units?.computed ?? []) expect(within(computed).getByText(u.say)).toBeInTheDocument()
    expect(PROCESS_SUMMARY_LIVE.units?.reused).toEqual([])
    expect(outcome).toHaveTextContent('Unchanged, reused (0)')
    // the results sections, by their titles in the report
    expect(PROCESS_SUMMARY_LIVE.result_sections?.written).toContain('bm2_organ-weight')
    expect(outcome).toHaveTextContent('Organ Weight')
    expect(outcome).toHaveTextContent(`Written (${PROCESS_SUMMARY_LIVE.summary?.paragraphs} paragraphs)`)
    expect(within(outcome).getByTestId('citations-removed')).toHaveTextContent(String(PROCESS_SUMMARY_LIVE.citations_removed))
    expect(within(outcome).getByRole('link', { name: 'See the citations' })).toHaveAttribute('href', `/studies/${DEMO_LIVE_RAT}/writing`)
    // the next step is the backend's, re-read after the run
    expect(within(outcome).getByTestId('next-step')).toHaveTextContent("Review the report's sections")
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument(), { timeout: 6000 })
    // the page changes when the run ends; the wait must not start the analysis a second time
    expect(acts).toEqual([`POST /api/v2/studies/${DEMO_LIVE_RAT}/process`])
  })

  it('reuses what did not change when the analysis is run again, and says which', async () => {
    setDemoStage('processed')
    const { user } = await open(DEMO_LIVE_RAT)
    await screen.findByTestId('parameters')
    await waitFor(() => expect(run()).toBeEnabled())
    await user.click(run())
    const outcome = await screen.findByTestId('process-outcome')
    const reused = within(outcome).getByRole('list', { name: 'Unchanged, reused' })
    for (const u of PROCESS_SUMMARY_WARM.units?.reused ?? []) expect(within(reused).getByText(u.say)).toBeInTheDocument()
    expect(PROCESS_SUMMARY_WARM.units?.reused?.map((u) => u.unit)).toContain('content')
    expect(PROCESS_SUMMARY_WARM.result_sections?.written).toEqual([])
    expect(outcome).toHaveTextContent('Unchanged, left as they were: Body Weight')
    expect(outcome).toHaveTextContent('Not rewritten')
  })

  it('says so when the run did not record what it computed, and claims nothing', async () => {
    setDemoStage('combined')
    server.use(
      http.post('/api/v2/studies/:id/process', () =>
        HttpResponse.text(JSON.stringify({ event: 'result', ok: true, summary: { ...PROCESS_SUMMARY_LIVE, units: { recorded: false }, citations_removed: null } }) + '\n', {
          headers: { 'Content-Type': 'application/x-ndjson' },
        }),
      ),
    )
    const { user } = await open(DEMO_LIVE_RAT)
    await screen.findByTestId('parameters')
    await waitFor(() => expect(run()).toBeEnabled())
    await user.click(run())
    const outcome = await screen.findByTestId('process-outcome')
    expect(within(outcome).getByTestId('units-not-recorded')).toHaveTextContent('What was computed and what was reused was not recorded for this run.')
    expect(outcome).toHaveTextContent('The run wrote no reference list.')
    expect(within(outcome).queryByTestId('citations-removed')).not.toBeInTheDocument()
  })

  it('shows a refusal of the act through the refusal explainer', async () => {
    setDemoStage('combined')
    server.use(http.post('/api/v2/studies/:id/process', () => HttpResponse.json(REFUSAL_LIVE_VALIDATED_PROCESS, { status: 409 })))
    const { user } = await open(DEMO_LIVE_RAT)
    await screen.findByTestId('parameters')
    await waitFor(() => expect(run()).toBeEnabled())
    await user.click(run())
    const alert = (await screen.findByText('The run did not finish')).closest('[role="alert"]') as HTMLElement
    expect(alert).toHaveTextContent(REFUSAL_LIVE_VALIDATED_PROCESS.error.say)
    expect(within(alert).getByRole('link', { name: /Go to Combined data to fix this/ })).toHaveAttribute('href', `/studies/${DEMO_LIVE_RAT}/dataset`)
    await user.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument(), { timeout: 6000 })
    expect(screen.queryByTestId('process-outcome')).not.toBeInTheDocument()
  })

  it('says the analysis has been run when the study is processed, with the next step', async () => {
    setDemoStage('processed')
    await open(DEMO_LIVE_RAT)
    const done = await screen.findByTestId('already-processed')
    expect(done).toHaveTextContent('The analysis has been run on this study.')
    expect(within(done).getByRole('link', { name: "Review the report's sections" })).toHaveAttribute('href', `/studies/${DEMO_LIVE_RAT}/review`)
    await waitFor(() => expect(run()).toBeEnabled())
    expect(screen.getByTestId('run-act')).toHaveTextContent('running it again computes what changed since and reuses the rest')
  })
})

describe('the finished side of the pair, and a report', () => {
  it('offers no act on the finished report, and links to the same page of the live copy', async () => {
    await open(DEMO_FINISHED_RAT)
    await screen.findByTestId('parameters')
    expect(screen.queryByRole('button', { name: RUN_LABEL })).not.toBeInTheDocument()
    expect(screen.queryByTestId('run-act')).not.toBeInTheDocument()
    const notice = screen.getByTestId('finished-notice')
    expect(notice).toHaveTextContent('Running the analysis is done on its live copy')
    expect(within(notice).getByRole('link', { name: /Open this page of the live copy/ })).toHaveAttribute('href', `/studies/${DEMO_LIVE_RAT}/process`)
  })

  it('shows a choice of the studies on a report, which has no data of its own', async () => {
    renderApp(`/studies/${DEMO_LIVE_REPORT}/process`)
    const choice = await screen.findByTestId('study-choice')
    expect(choice).toHaveTextContent('Process works on one study at a time.')
    expect(within(choice).getByRole('link', { name: 'Open Process of the rat study' })).toHaveAttribute('href', '/studies/DTXSID6020430_live_rat/process')
    expect(screen.queryByRole('button', { name: RUN_LABEL })).not.toBeInTheDocument()
  })
})
