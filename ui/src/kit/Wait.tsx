import { CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined, RetweetOutlined } from '@ant-design/icons'
import { Button, Modal, Space, Spin, Typography } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { SAY_BROKEN_STREAM } from '../api/client'
import { ApiError } from '../api/errors'
import type { ErrorBody, RunEvent, StepStatus } from '../api/types'
import { formatClock, formatElapsed, useElapsed } from './elapsed'
import { ItemList } from './ItemList'
import { markWaiting, useWaitingHere } from './localRuns'
import { Refusal } from './Refusal'
import { useInvalidateStudy, useStudyState } from './useStudyState'

/**
 * The wait (MODULES.md §4.4): a foreground block over the whole page while a
 * long act runs (Process, integration, a render, Background writing). It
 * shows the elapsed time and the steps the run reports, and has no cancel
 * (Q12). It ends on the run's `result` (the overlay closes and `onFinish`
 * gets the summary) or its `error` (the refusal is shown until the person
 * closes it). The study's state is re-read either way.
 */

export type WaitOutcome = { ok: true; summary: Record<string, unknown> } | { ok: false; error: ErrorBody }

interface StepRow {
  unit: string
  say: string
  status: StepStatus
  ms?: number
}

const STATUS_WORDS: Record<StepStatus, string> = {
  computing: 'working',
  reused: 'unchanged, reused',
  done: 'done',
  failed: 'failed',
}

function StepIcon({ status }: { status: StepStatus }) {
  switch (status) {
    case 'computing':
      return <LoadingOutlined aria-hidden />
    case 'reused':
      return <RetweetOutlined aria-hidden style={{ color: '#8c8c8c' }} />
    case 'done':
      return <CheckCircleOutlined aria-hidden style={{ color: '#52c41a' }} />
    case 'failed':
      return <CloseCircleOutlined aria-hidden style={{ color: '#ff4d4f' }} />
  }
}

function StepList({ steps }: { steps: StepRow[] }) {
  if (steps.length === 0) return null
  return (
    <ItemList
      dense
      aria-label="Steps"
      items={steps}
      rowKey={(s) => s.unit}
      rowProps={(s) => ({ 'data-status': s.status })}
      render={(s) => (
        <Space>
          <StepIcon status={s.status} />
          <Typography.Text>{s.say}</Typography.Text>
          <Typography.Text type="secondary">
            {STATUS_WORDS[s.status] ?? s.status}
            {s.status !== 'computing' && typeof s.ms === 'number' ? ` (${formatElapsed(s.ms)})` : ''}
          </Typography.Text>
        </Space>
      )}
    />
  )
}

/** The overlay itself; <Wait> and <RunInFlight> both use it. */
export function WaitOverlay({
  title,
  note,
  elapsedMs,
  steps = [],
  children,
  footer = null,
}: {
  title: string
  note?: React.ReactNode
  elapsedMs: number | null
  steps?: StepRow[]
  children?: React.ReactNode
  footer?: React.ReactNode
}) {
  return (
    <Modal open title={title} closable={false} mask={{ closable: false }} keyboard={false} footer={footer} centered>
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        {children ?? (
          <>
            <Space>
              <Spin />
              <Typography.Text strong aria-live="off">
                {elapsedMs === null ? 'Running' : `Running for ${formatElapsed(elapsedMs)}`}
              </Typography.Text>
            </Space>
            {note && <Typography.Paragraph style={{ margin: 0 }}>{note}</Typography.Paragraph>}
            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
              Please wait. Closing or reloading the page does not stop it.
            </Typography.Paragraph>
          </>
        )}
        <StepList steps={steps} />
      </Space>
    </Modal>
  )
}

export interface WaitProps {
  studyId: string
  /** what is running, in plain words ("Processing the study") */
  title: string
  /** how long it usually takes, or anything else the person should know */
  note?: React.ReactNode
  /** starts the run and yields its events; called once */
  start: () => AsyncIterable<RunEvent>
  /** called when the run has ended, before the overlay closes on success */
  onFinish?: (outcome: WaitOutcome) => void
  /** called when the overlay is gone: at once on success, after "Close" on an error */
  onClose: () => void
}

export function Wait({ studyId, title, note, start, onFinish, onClose }: WaitProps) {
  const [steps, setSteps] = useState<StepRow[]>([])
  const [error, setError] = useState<ErrorBody | null>(null)
  const [startMs] = useState(() => Date.now())
  const started = useRef(false)
  const invalidate = useInvalidateStudy()
  const elapsed = useElapsed(error ? null : startMs)

  // Hold the latest callbacks without restarting the run.
  const callbacks = useRef({ start, onFinish, onClose, invalidate })
  useEffect(() => {
    callbacks.current = { start, onFinish, onClose, invalidate }
  })

  useEffect(() => markWaiting(studyId), [studyId])

  useEffect(() => {
    // Exactly once, even under StrictMode's double effects: a second start
    // would be a second run.
    if (started.current) return
    started.current = true
    const { start: begin } = callbacks.current

    const end = async (outcome: WaitOutcome) => {
      await callbacks.current.invalidate(studyId)
      callbacks.current.onFinish?.(outcome)
      if (outcome.ok) callbacks.current.onClose()
      else setError(outcome.error)
    }

    void (async () => {
      try {
        for await (const ev of begin()) {
          if (ev.event === 'step') {
            setSteps((prev) => {
              const row: StepRow = { unit: ev.unit, say: ev.say, status: ev.status, ms: ev.ms }
              const i = prev.findIndex((p) => p.unit === ev.unit)
              if (i < 0) return [...prev, row]
              const next = prev.slice()
              next[i] = row
              return next
            })
          } else if (ev.event === 'result') {
            await end({ ok: true, summary: ev.summary })
            return
          } else {
            await end({ ok: false, error: ev.error })
            return
          }
        }
        await end({
          ok: false,
          error: { code: 'unexpected', status: 0, message: 'The event stream ended without a result or an error.', say: SAY_BROKEN_STREAM, fix: null },
        })
      } catch (err) {
        const body: ErrorBody =
          err instanceof ApiError
            ? err.body
            : { code: 'unexpected', status: 0, message: String(err), say: SAY_BROKEN_STREAM, fix: null }
        await end({ ok: false, error: body })
      }
    })()
  }, [studyId])

  if (error) {
    return (
      <WaitOverlay
        title={title}
        elapsedMs={null}
        steps={steps}
        footer={
          <Button type="primary" onClick={() => callbacks.current.onClose()}>
            Close
          </Button>
        }
      >
        <Refusal error={error} studyId={studyId} title="The run did not finish" />
      </WaitOverlay>
    )
  }
  return <WaitOverlay title={title} note={note} elapsedMs={elapsed} steps={steps} />
}

/**
 * The "already running" wait: blocks the page whenever the study's state says
 * a run is in flight that this tab did not start (a reload, a second tab). It
 * ends by itself when the state stops saying so.
 */
export function RunInFlight({ studyId }: { studyId: string }) {
  const { data } = useStudyState(studyId)
  const here = useWaitingHere(studyId)
  const run = data?.run
  const startedAt = run?.in_flight ? run.started_at : null
  const startMs = startedAt && !Number.isNaN(Date.parse(startedAt)) ? Date.parse(startedAt) : null
  const elapsed = useElapsed(run?.in_flight ? startMs : null)

  if (!run?.in_flight || here) return null
  const clock = formatClock(startedAt)
  return (
    <WaitOverlay
      title="This study is being processed"
      elapsedMs={elapsed}
      note={
        <>
          {clock ? `It has been running since ${clock}` : 'It was started earlier; the start time is not known'}
          , from another page or before this one was reloaded. This page will continue when it ends.
        </>
      }
    />
  )
}
