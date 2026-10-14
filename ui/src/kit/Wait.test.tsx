import { act, screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { runProcess } from '../api/client'
import { ApiError } from '../api/errors'
import { STATE_APPROVED_STALE_SUMMARY, STATE_RUNNING, STREAM_PROCESS_FAILED, STREAM_PROCESS_OK, STREAM_TRUNCATED } from '../api/mocks/fixtures'
import { createHandlers } from '../api/mocks/handlers'
import { server } from '../api/mocks/node'
import type { RunEvent } from '../api/types'
import { renderWithApp } from '../test/render'
import { formatElapsed } from './elapsed'
import { useStudyState } from './useStudyState'
import { RunInFlight, Wait, type WaitOutcome } from './Wait'

const ID = STATE_APPROVED_STALE_SUMMARY.id

/** A stream the test feeds by hand. */
function controlledStream() {
  const queue: RunEvent[] = []
  let wake: (() => void) | null = null
  let ended = false
  let fail: Error | null = null
  async function* gen(): AsyncGenerator<RunEvent> {
    for (;;) {
      if (fail) throw fail
      const e = queue.shift()
      if (e) {
        yield e
        continue
      }
      if (ended) return
      await new Promise<void>((r) => (wake = r))
    }
  }
  const poke = () => {
    const w = wake
    wake = null
    w?.()
  }
  return {
    gen,
    push: (e: RunEvent) => {
      queue.push(e)
      poke()
    },
    end: () => {
      ended = true
      poke()
    },
    throw: (err: Error) => {
      fail = err
      poke()
    },
  }
}

async function* fromList(events: RunEvent[]): AsyncGenerator<RunEvent> {
  for (const e of events) {
    await Promise.resolve()
    yield e
  }
}

describe('formatElapsed', () => {
  it('says seconds, minutes and hours plainly', () => {
    expect(formatElapsed(0)).toBe('0 s')
    expect(formatElapsed(42_400)).toBe('42 s')
    expect(formatElapsed(185_000)).toBe('3 min 05 s')
    expect(formatElapsed(3_720_000)).toBe('1 h 02 min')
  })
})

describe('<Wait>', () => {
  it('blocks the page with the elapsed time and no way to cancel or close', async () => {
    const s = controlledStream()
    renderWithApp(<Wait studyId={ID} title="Processing the study" note="This usually takes 1 to 4 minutes." start={s.gen} onClose={vi.fn()} />)
    const d = within(await screen.findByRole('dialog'))
    expect(d.getByText('Processing the study')).toBeInTheDocument()
    expect(d.getByText(/Running for 0 s/)).toBeInTheDocument()
    expect(d.getByText('This usually takes 1 to 4 minutes.')).toBeInTheDocument()
    expect(d.queryByRole('button')).not.toBeInTheDocument()
    expect(d.queryByText(/cancel/i)).not.toBeInTheDocument()
  })

  it('counts the elapsed time', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const s = controlledStream()
      renderWithApp(<Wait studyId={ID} title="Processing the study" start={s.gen} onClose={vi.fn()} />)
      await screen.findByRole('dialog')
      await act(() => vi.advanceTimersByTimeAsync(65_000))
      expect(screen.getByText(/Running for 1 min 0[5-6] s/)).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('lists the steps as the stream reports them, updating each in place', async () => {
    const s = controlledStream()
    renderWithApp(<Wait studyId={ID} title="Processing the study" start={s.gen} onClose={vi.fn()} />)
    const steps = await screen.findByRole('dialog')
    act(() => s.push({ event: 'step', unit: 'ntp', status: 'computing', say: 'Apical statistics' }))
    expect(await within(steps).findByText('Apical statistics')).toBeInTheDocument()
    expect(within(steps).getByText('working')).toBeInTheDocument()
    act(() => s.push({ event: 'step', unit: 'ntp', status: 'done', say: 'Apical statistics', ms: 4200 }))
    act(() => s.push({ event: 'step', unit: 'bmds', status: 'reused', say: 'Apical BMD modelling', ms: 12 }))
    expect(await within(steps).findByText('done (4 s)')).toBeInTheDocument()
    expect(within(steps).getByText('unchanged, reused (0 s)')).toBeInTheDocument()
    expect(within(steps).getAllByText('Apical statistics')).toHaveLength(1)
  })

  it('closes on the result, gives the summary, and re-reads the study', async () => {
    let stateReads = 0
    server.use(
      http.get('/api/v2/studies/:id/state', () => {
        stateReads++
        return HttpResponse.json(STATE_APPROVED_STALE_SUMMARY)
      }),
    )
    const outcomes: WaitOutcome[] = []
    const stream = controlledStream()
    function Probe() {
      // something on the page reads the study, as the study frame does
      const { data } = useStudyState(ID)
      return <div>{data ? 'state read' : ''}</div>
    }
    function Host() {
      const [open, setOpen] = useState(true)
      return open ? (
        <Wait studyId={ID} title="Processing the study" start={stream.gen} onFinish={(o) => outcomes.push(o)} onClose={() => setOpen(false)} />
      ) : (
        <div>closed</div>
      )
    }
    renderWithApp(
      <>
        <Probe />
        <Host />
      </>,
    )
    await screen.findByText('state read')
    const before = stateReads
    act(() => {
      for (const e of STREAM_PROCESS_OK) stream.push(e)
    })
    expect(await screen.findByText('closed')).toBeInTheDocument()
    expect(outcomes).toEqual([{ ok: true, summary: (STREAM_PROCESS_OK.at(-1) as { summary: Record<string, unknown> }).summary }])
    await waitFor(() => expect(stateReads).toBeGreaterThan(before))
  })

  it('ends on an error event with the refusal, and closes only when the person says so', async () => {
    const onClose = vi.fn()
    const outcomes: WaitOutcome[] = []
    const failing = () => fromList(STREAM_PROCESS_FAILED)
    const { user } = renderWithApp(<Wait studyId={ID} title="Processing the study" start={failing} onFinish={(o) => outcomes.push(o)} onClose={onClose} />)
    const d = within(await screen.findByRole('dialog'))
    expect(await d.findByText('The run did not finish')).toBeInTheDocument()
    expect(d.getByText(/did not answer while writing the Methods text/)).toBeInTheDocument()
    expect(d.getByText('failed (30 s)')).toBeInTheDocument()
    expect(outcomes[0]).toMatchObject({ ok: false, error: { code: 'llm_failed' } })
    expect(onClose).not.toHaveBeenCalled()
    await user.click(d.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('treats a refusal before the run starts as the error', async () => {
    renderWithApp(<Wait studyId="DTXSID1021952" title="Processing the study" start={() => runProcess('DTXSID1021952')} onClose={vi.fn()} />)
    expect(await screen.findByText(/data have not been combined/)).toBeInTheDocument()
  })

  it('treats a stream that stops without a result as an error, never as success', async () => {
    const onFinish = vi.fn()
    const truncated = () => fromList(STREAM_TRUNCATED)
    renderWithApp(<Wait studyId={ID} title="Processing the study" start={truncated} onFinish={onFinish} onClose={vi.fn()} />)
    expect(await screen.findByText(/stopped without saying whether it finished/)).toBeInTheDocument()
    expect(onFinish).toHaveBeenCalledWith(expect.objectContaining({ ok: false }))
  })

  it('treats a broken connection as an error', async () => {
    const s = controlledStream()
    renderWithApp(<Wait studyId={ID} title="Processing the study" start={s.gen} onClose={vi.fn()} />)
    await screen.findByRole('dialog')
    act(() => s.throw(new ApiError({ code: 'unreachable', status: 0, message: 'net', say: "The application's server could not be reached." })))
    expect(await screen.findByText(/could not be reached/)).toBeInTheDocument()
  })

  it('starts the run exactly once, even under StrictMode', async () => {
    const start = vi.fn(() => controlledStream().gen())
    renderWithApp(<Wait studyId={ID} title="Processing the study" start={start} onClose={vi.fn()} />)
    await screen.findByRole('dialog')
    expect(start).toHaveBeenCalledTimes(1)
  })
})

describe('<RunInFlight>, the "already running" state', () => {
  it('blocks the page while the state says a run is in flight, with its start time', async () => {
    server.use(http.get('/api/v2/studies/:id/state', () => HttpResponse.json(STATE_RUNNING)))
    renderWithApp(<RunInFlight studyId={ID} />)
    const d = within(await screen.findByRole('dialog'))
    expect(d.getByText('This study is being processed')).toBeInTheDocument()
    expect(d.getByText(/It has been running since/)).toBeInTheDocument()
    expect(d.getByText(/Running for/)).toBeInTheDocument()
    expect(d.queryByRole('button')).not.toBeInTheDocument()
  })

  it('says so when the start time is not known', async () => {
    server.use(http.get('/api/v2/studies/:id/state', () => HttpResponse.json({ ...STATE_RUNNING, run: { in_flight: true, started_at: null, last: null } })))
    renderWithApp(<RunInFlight studyId={ID} />)
    expect(await screen.findByText(/the start time is not known/)).toBeInTheDocument()
  })

  it('shows nothing when no run is in flight', async () => {
    renderWithApp(<RunInFlight studyId={ID} />)
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('ends by itself when the run does', async () => {
    let inFlight = true
    server.use(http.get('/api/v2/studies/:id/state', () => HttpResponse.json(inFlight ? STATE_RUNNING : STATE_APPROVED_STALE_SUMMARY)))
    renderWithApp(<RunInFlight studyId={ID} />)
    await screen.findByRole('dialog')
    inFlight = false
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument(), { timeout: 6000 })
  })

  it("stays out of the way of this tab's own wait", async () => {
    server.use(...createHandlers({ stepDelayMs: 30 }))
    const s = controlledStream()
    renderWithApp(
      <>
        <Wait studyId={ID} title="Processing the study" start={s.gen} onClose={vi.fn()} />
        <RunInFlight studyId={ID} />
      </>,
    )
    await screen.findByText('Processing the study')
    server.use(http.get('/api/v2/studies/:id/state', () => HttpResponse.json(STATE_RUNNING)))
    await new Promise((r) => setTimeout(r, 100))
    expect(screen.queryByText('This study is being processed')).not.toBeInTheDocument()
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
  })
})
