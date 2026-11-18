import { Alert, Button, Card, Space, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router'
import { runSummary, writeBackground, type ActVerdict, type PartSummary, type WritingOverview } from '../../api/demoWriting'
import type { ExistingStudyState } from '../../api/types'
import { studyRoute } from '../../kit/modules'
import { Wait, type WaitOutcome } from '../../kit/Wait'
import { WrittenByTags } from './marks'
import {
  FINISHED_LINK,
  FINISHED_SAY,
  FINISHED_TITLE,
  LIVE_LINK,
  MODEL_NOT_RECORDED,
  NOT_WRITTEN_YET,
  WAIT_BACKGROUND_NOTE,
  WAIT_BACKGROUND_TITLE,
  WAIT_SUMMARY_NOTE,
  WAIT_SUMMARY_TITLE,
  WRITE_BACKGROUND,
  WRITE_SUMMARY,
  plural,
  recordedTags,
  studyLabel,
} from './words'

/**
 * The written parts of a report or a study, each marked built from the data
 * or written by a language model, and the two acts of the page. Which act is
 * offered, and why not, is the backend's verdict (`overview.acts`); on the
 * finished side of a demo pair no act is offered at all.
 */

type Act = 'background' | 'summary'

function PartsTable({ parts, label, onOpen }: { parts: PartSummary[]; label: string; onOpen: (p: PartSummary) => void }) {
  return (
    <Table<PartSummary>
      aria-label={label}
      size="small"
      rowKey="key"
      pagination={false}
      dataSource={parts}
      onRow={(p) => ({ 'data-part': p.key }) as React.HTMLAttributes<HTMLTableRowElement>}
      columns={[
        {
          title: 'Part',
          key: 'part',
          render: (_, p) => (
            <Space orientation="vertical" size={2}>
              <Typography.Text strong>{p.title}</Typography.Text>
              {!p.exists && <Tag>{NOT_WRITTEN_YET}</Tag>}
              {p.subsections && p.subsections.length > 0 && (
                <ul aria-label={`Parts of ${p.title}`} style={{ margin: 0, paddingInlineStart: 18 }}>
                  {p.subsections.map((s) => (
                    <li key={s.key} data-subsection={s.key} style={{ padding: '1px 0' }}>
                      <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 6 }}>
                        <span style={{ flex: 'none' }}>
                          <WrittenByTags writtenBy={s.written_by} />
                        </span>
                        <Typography.Text>{s.heading}</Typography.Text>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Space>
          ),
        },
        {
          title: 'Who wrote it',
          key: 'by',
          width: '30%',
          render: (_, p) => (
            <Space orientation="vertical" size={2} data-testid="who-wrote">
              <WrittenByTags writtenBy={p.written_by} />
              {p.written_by !== 'data' && p.exists && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  Model: {p.model ?? MODEL_NOT_RECORDED}
                </Typography.Text>
              )}
            </Space>
          ),
        },
        {
          title: 'What is recorded of how',
          key: 'recorded',
          width: '26%',
          render: (_, p) =>
            p.recorded ? (
              <Space orientation="vertical" size={2} data-testid="recorded">
                {recordedTags(p.recorded).map((t) => (
                  <Tag key={t.label} color={t.color} style={{ whiteSpace: 'normal' }}>
                    {t.label}
                  </Tag>
                ))}
              </Space>
            ) : (
              <Typography.Text type="secondary">{p.exists ? 'No language model wrote this text.' : ''}</Typography.Text>
            ),
        },
        {
          title: '',
          key: 'open',
          width: 90,
          render: (_, p) => (
            <Button size="small" onClick={() => onOpen(p)} aria-label={`Open ${p.title}`}>
              Open
            </Button>
          ),
        },
      ]}
    />
  )
}

function ActRow({ label, verdict, onStart }: { label: string; verdict: ActVerdict; onStart: () => void }) {
  return (
    <Space orientation="vertical" size={2}>
      <Button type="primary" disabled={!verdict.allowed} onClick={onStart}>
        {label}
      </Button>
      {!verdict.allowed && verdict.say && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {verdict.say}
        </Typography.Text>
      )}
    </Space>
  )
}

function Outcome({ act, outcome, onOpen }: { act: Act; outcome: WaitOutcome; onOpen: () => void }) {
  if (!outcome.ok) return null
  const s = outcome.summary
  const num = (k: string) => (typeof s[k] === 'number' ? s[k] : 0)
  if (act === 'background') {
    return (
      <Alert
        type="success"
        showIcon
        data-testid="act-outcome"
        title="The Background was written and saved as a draft. It is not approved."
        description={
          <Space orientation="vertical" size={2}>
            <Typography.Text>
              {plural(num('paragraphs'), 'paragraph', 'paragraphs')}, {plural(num('references'), 'reference', 'references')};{' '}
              {plural(num('untraced_citations'), 'citation', 'citations')} could not be traced to a supplied source. The prompt is kept
              with the run.
            </Typography.Text>
            <Button type="link" style={{ padding: 0 }} onClick={onOpen}>
              Open the Background and its prompt
            </Button>
          </Space>
        }
      />
    )
  }
  const unmatched = Array.isArray(s.unmatched_numbers) ? (s.unmatched_numbers as unknown[]).map(String) : []
  return (
    <Alert
      type="success"
      showIcon
      data-testid="act-outcome"
      title="The run is kept with its prompt. The Summary in the report was not changed."
      description={
        <Space orientation="vertical" size={2}>
          <Typography.Text>
            {unmatched.length === 0
              ? 'Every number in the run is among the facts the model was given.'
              : `Numbers in the run that are not among the facts the model was given: ${unmatched.join(', ')}.`}
          </Typography.Text>
          <Button type="link" style={{ padding: 0 }} onClick={onOpen}>
            Open the Summary to read the run
          </Button>
        </Space>
      }
    />
  )
}

export function WrittenSections({
  studyId,
  state,
  overview,
  onOpen,
}: {
  studyId: string
  state: ExistingStudyState | undefined
  overview: WritingOverview
  onOpen: (studyId: string, part: string) => void
}) {
  const [running, setRunning] = useState<Act | null>(null)
  const [last, setLast] = useState<{ act: Act; outcome: WaitOutcome } | null>(null)
  const finished = state?.demo?.role === 'finished'
  const open = (p: PartSummary) => onOpen(p.study, p.key)

  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      {finished ? (
        <Alert
          type="info"
          showIcon
          data-testid="finished-note"
          title={FINISHED_TITLE}
          description={
            <Space wrap>
              <Typography.Text>{FINISHED_SAY}</Typography.Text>
              {state?.demo?.counterpart_exists && <Link to={`${studyRoute(state.demo.counterpart)}/writing`}>{FINISHED_LINK}</Link>}
            </Space>
          }
        />
      ) : (
        <Card
          size="small"
          title="Writing"
          data-testid="acts"
          extra={
            state?.demo?.role === 'live' && state.demo.counterpart_exists ? (
              <Link to={`${studyRoute(state.demo.counterpart)}/writing`}>{LIVE_LINK}</Link>
            ) : undefined
          }
        >
          <Space wrap size="large" align="start">
            <ActRow
              label={WRITE_BACKGROUND}
              verdict={overview.acts.background}
              onStart={() => {
                setLast(null)
                setRunning('background')
              }}
            />
            <ActRow
              label={WRITE_SUMMARY}
              verdict={overview.acts.summary}
              onStart={() => {
                setLast(null)
                setRunning('summary')
              }}
            />
          </Space>
        </Card>
      )}

      {last && <Outcome act={last.act} outcome={last.outcome} onOpen={() => onOpen(studyId, last.act)} />}

      {overview.report?.id && (
        <Alert
          type="info"
          showIcon
          data-testid="background-pointer"
          title={
            <span>
              The {overview.report.part.title} is the report's, not this study's.{' '}
              <Link to={`${studyRoute(overview.report.id)}/writing?part=${encodeURIComponent(overview.report.part.key)}`}>
                Open it on the report ({overview.report.id})
              </Link>
            </span>
          }
        />
      )}

      {overview.parts.length > 0 && (
        <Card size="small" title={overview.kind === 'report' ? 'The report' : 'This study'} data-testid="parts-own">
          <PartsTable parts={overview.parts} label="Written parts" onOpen={open} />
        </Card>
      )}

      {(overview.studies ?? []).map((s) => (
        <Card
          key={s.id}
          size="small"
          data-testid={`parts-${s.key}`}
          title={
            <Space wrap>
              {studyLabel(s.key)}
              <Typography.Text code>{s.id}</Typography.Text>
            </Space>
          }
        >
          {s.exists ? (
            <PartsTable parts={s.parts} label={`Written parts of the ${s.key} study`} onOpen={open} />
          ) : (
            <Typography.Text type="danger">Missing: this study's folder is not in the store.</Typography.Text>
          )}
        </Card>
      ))}

      {running === 'background' && (
        <Wait
          studyId={studyId}
          title={WAIT_BACKGROUND_TITLE}
          note={WAIT_BACKGROUND_NOTE}
          start={() => writeBackground(studyId)}
          onFinish={(outcome) => setLast({ act: 'background', outcome })}
          onClose={() => setRunning(null)}
        />
      )}
      {running === 'summary' && (
        <Wait
          studyId={studyId}
          title={WAIT_SUMMARY_TITLE}
          note={WAIT_SUMMARY_NOTE}
          start={() => runSummary(studyId)}
          onFinish={(outcome) => setLast({ act: 'summary', outcome })}
          onClose={() => setRunning(null)}
        />
      )}
    </Space>
  )
}
