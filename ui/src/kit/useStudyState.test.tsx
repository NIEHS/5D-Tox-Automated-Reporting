import { QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../api/errors'
import { STATE_APPROVED_STALE_SUMMARY, STATE_INTEGRATED, REFUSAL_PHASE_NOT_ALLOWED } from '../api/mocks/fixtures'
import { server } from '../api/mocks/node'
import { testQueryClient } from '../test/render'
import { invalidateStudy, useStudyMutation, useStudyState } from './useStudyState'

function wrapper(client = testQueryClient()) {
  return {
    client,
    Wrapper: ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  }
}

function countingStateHandler(states: Array<typeof STATE_INTEGRATED>) {
  let calls = 0
  server.use(
    http.get('/api/v2/studies/:id/state', () => {
      const s = states[Math.min(calls, states.length - 1)]
      calls++
      return HttpResponse.json(s)
    }),
  )
  return () => calls
}

describe('useStudyState', () => {
  it('serves the backend state as it is, without computing anything', async () => {
    const { Wrapper } = wrapper()
    const { result } = renderHook(() => useStudyState('DTXSID50469320'), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data).toEqual(STATE_APPROVED_STALE_SUMMARY)
  })

  it('does not read anything without an id', () => {
    const calls = countingStateHandler([STATE_INTEGRATED])
    const { Wrapper } = wrapper()
    const { result } = renderHook(() => useStudyState(undefined), { wrapper: Wrapper })
    expect(result.current.fetchStatus).toBe('idle')
    expect(calls()).toBe(0)
  })

  it('reports a refusal as an ApiError and does not retry it', async () => {
    let calls = 0
    server.use(
      http.get('/api/v2/studies/:id/state', () => {
        calls++
        return HttpResponse.json(REFUSAL_PHASE_NOT_ALLOWED, { status: 409 })
      }),
    )
    const { Wrapper } = wrapper()
    const { result } = renderHook(() => useStudyState('X'), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.error).toBeInstanceOf(ApiError))
    expect(result.current.error?.code).toBe('phase_not_allowed')
    expect(calls).toBe(1)
  })

  it('re-reads after invalidateStudy', async () => {
    const after = { ...STATE_INTEGRATED, phase: 'APPROVED', legal_actions: ['REPROCESS', 'RESET'] }
    const calls = countingStateHandler([STATE_INTEGRATED, after])
    const { Wrapper, client } = wrapper()
    const { result } = renderHook(() => useStudyState(STATE_INTEGRATED.id), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.data?.phase).toBe('INTEGRATED'))
    await act(() => invalidateStudy(client, STATE_INTEGRATED.id))
    await waitFor(() => expect(result.current.data?.phase).toBe('APPROVED'))
    expect(calls()).toBe(2)
  })

  it('re-reads after a mutation, whether it succeeded or was refused', async () => {
    const calls = countingStateHandler([STATE_INTEGRATED])
    const { Wrapper } = wrapper()
    const { result } = renderHook(
      () => ({
        state: useStudyState(STATE_INTEGRATED.id),
        ok: useStudyMutation(STATE_INTEGRATED.id, () => Promise.resolve('done')),
        refused: useStudyMutation(STATE_INTEGRATED.id, () => Promise.reject(new ApiError(REFUSAL_PHASE_NOT_ALLOWED.error))),
      }),
      { wrapper: Wrapper },
    )
    await waitFor(() => expect(result.current.state.data).toBeDefined())
    expect(calls()).toBe(1)
    await act(async () => {
      await result.current.ok.mutateAsync()
    })
    await waitFor(() => expect(calls()).toBe(2))
    await act(async () => {
      await result.current.refused.mutateAsync().catch(() => undefined)
    })
    await waitFor(() => expect(calls()).toBe(3))
    expect(result.current.refused.error?.code).toBe('phase_not_allowed')
  })

  it('polls while a run is in flight, and stops when it ends', async () => {
    const running = { ...STATE_APPROVED_STALE_SUMMARY, run: { in_flight: true, started_at: '2026-10-14T09:00:00Z', last: null } }
    const calls = countingStateHandler([running, STATE_APPROVED_STALE_SUMMARY])
    const { Wrapper } = wrapper()
    const { result } = renderHook(() => useStudyState(running.id), { wrapper: Wrapper })
    await waitFor(() => expect(result.current.data?.run?.in_flight).toBe(true))
    await waitFor(() => expect(result.current.data?.run?.in_flight).toBe(false), { timeout: 6000 })
    const n = calls()
    await new Promise((r) => setTimeout(r, 3500))
    expect(calls()).toBe(n)
  })
})
