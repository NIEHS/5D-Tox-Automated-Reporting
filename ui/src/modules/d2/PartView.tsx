import { App, Alert, Button, Card, Col, Collapse, Descriptions, Row, Skeleton, Space, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router'
import {
  takeSummaryRun,
  type GivenItem,
  type PaperOffered,
  type PartCitationCheck,
  type PartDetail,
  type SummaryRun,
  type TextBlock,
} from '../../api/demoWriting'
import { noopOf } from '../../api/client'
import type { Noop } from '../../api/types'
import { ItemList } from '../../kit/ItemList'
import { moduleRoute } from '../../kit/modules'
import { Refusal } from '../../kit/Refusal'
import { useStudyMutation } from '../../kit/useStudyState'
import { Outside, RecordTag, RecordedText, WrittenByTags } from './marks'
import { useWritingPart } from './queries'
import { MODEL_NOT_RECORDED, NOT_WRITTEN_YET, NO_MODEL, SHOW_TEXT, TAKE_RUN, TAKE_RUN_ELSEWHERE, plural } from './words'

/**
 * One written part: its text beside how it was written. Everything shown is
 * what the backend recorded or says was not recorded; a text is never built
 * here.
 */

function TextBlocks({ blocks }: { blocks: TextBlock[] }) {
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      {blocks.map((b, i) => (
        <section key={b.key ?? `${b.heading ?? ''}-${i}`} data-testid="text-block" data-block={b.key ?? ''}>
          {(b.heading || b.written_by) && (
            <Space wrap align="baseline" style={{ marginBottom: 4 }}>
              {b.heading && (
                <Typography.Title level={5} style={{ margin: 0 }}>
                  {b.heading}
                </Typography.Title>
              )}
              {b.written_by && <WrittenByTags writtenBy={b.written_by} />}
            </Space>
          )}
          {b.caption && (
            <Typography.Paragraph type="secondary" style={{ marginBottom: 4 }}>
              Table: {b.caption}
            </Typography.Paragraph>
          )}
          {b.paragraphs.length === 0 ? (
            <Typography.Text type="secondary">No text under this heading.</Typography.Text>
          ) : (
            b.paragraphs.map((p, j) => (
              <Typography.Paragraph key={j} style={{ marginBottom: 8 }}>
                {p}
              </Typography.Paragraph>
            ))
          )}
        </section>
      ))}
    </Space>
  )
}

function Given({ item }: { item: GivenItem }) {
  return (
    <div data-testid={`given-${item.id}`} data-record={item.record}>
      <Space wrap align="baseline">
        <Typography.Text strong>{item.title}</Typography.Text>
        <RecordTag record={item.record} />
        {item.text !== null && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {plural(item.chars, 'character', 'characters')}
          </Typography.Text>
        )}
      </Space>
      <Typography.Paragraph type="secondary" style={{ margin: '4px 0 8px' }}>
        {item.say}
      </Typography.Paragraph>
      {item.text !== null && (
        <Collapse
          size="small"
          items={[{ key: 'text', label: SHOW_TEXT, children: <RecordedText text={item.text} label={item.title} /> }]}
        />
      )}
    </div>
  )
}

export function CitationCheckBox({ check, checkSays }: { check: PartCitationCheck; checkSays: string }) {
  return (
    <Card size="small" title="The citation check" data-testid="citation-check">
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Alert type={check.untraced > 0 ? 'warning' : 'success'} showIcon title={check.say} />
        {check.sources_supplied !== null && (
          <Typography.Text>
            {plural(check.sources_supplied, 'source was supplied', 'sources were supplied')}; the text cites {check.sources_cited}.
          </Typography.Text>
        )}
        {check.items.length > 0 && (
          <ItemList
            dense
            aria-label="Citations that could not be traced"
            items={check.items}
            rowKey={(it, i) => `${it.token ?? ''}-${i}`}
            render={(it) => (
              <Space orientation="vertical" size={0}>
                <Space wrap>
                  <Tag color="gold">{it.token}</Tag>
                  <Typography.Text type="secondary">{it.what}</Typography.Text>
                </Space>
                <Typography.Text>{it.sentence}</Typography.Text>
              </Space>
            )}
          />
        )}
        <Typography.Text type="secondary" data-testid="check-says">
          {checkSays}
        </Typography.Text>
      </Space>
    </Card>
  )
}

function Papers({ papers }: { papers: PaperOffered[] }) {
  return (
    <Table<PaperOffered>
      aria-label="The papers offered to the model"
      data-testid="papers-offered"
      size="small"
      rowKey="token"
      pagination={false}
      scroll={{ y: 320 }}
      dataSource={papers}
      columns={[
        { title: 'Token', dataIndex: 'token', width: 64 },
        {
          title: 'Paper',
          key: 'paper',
          render: (_, p) => (
            <Space orientation="vertical" size={0}>
              {p.doi ? <Outside href={`https://doi.org/${p.doi}`}>{p.title}</Outside> : <Typography.Text>{p.title}</Typography.Text>}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {[p.venue, p.year].filter(Boolean).join(', ')}
                {p.genes.length > 0 ? ` · offered for ${p.genes.slice(0, 6).join(', ')}${p.genes.length > 6 ? ', …' : ''}` : ''}
              </Typography.Text>
            </Space>
          ),
        },
        {
          title: 'Cited',
          key: 'cited',
          width: 84,
          render: (_, p) => (p.cited ? <Tag color="blue">Cited</Tag> : <Typography.Text type="secondary">Not cited</Typography.Text>),
        },
      ]}
    />
  )
}

function Run({ run, canTake, onTake, taking }: { run: SummaryRun; canTake: boolean; onTake: (runId: string) => void; taking: boolean }) {
  return (
    <Space orientation="vertical" size="small" style={{ width: '100%' }} data-testid={`run-${run.run_id}`}>
      <Descriptions
        size="small"
        column={1}
        items={[
          { key: 'template', label: 'Template version', children: run.template_version ?? 'An edit that was not saved as a version' },
          { key: 'model', label: 'Model', children: run.model ?? MODEL_NOT_RECORDED },
          {
            key: 'numbers',
            label: 'Numbers not among the facts given',
            children:
              run.unmatched_numbers.length === 0 ? (
                'None'
              ) : (
                <Space wrap size={4}>
                  {run.unmatched_numbers.map((n) => (
                    <Tag key={n} color="gold">
                      {n}
                    </Tag>
                  ))}
                </Space>
              ),
          },
        ]}
      />
      {run.paragraphs.map((p, i) => (
        <Typography.Paragraph key={i} style={{ marginBottom: 6 }}>
          {p}
        </Typography.Paragraph>
      ))}
      {run.prompt !== null ? (
        <Collapse
          size="small"
          items={[
            {
              key: 'prompt',
              label: (
                <Space wrap>
                  The prompt <RecordTag record="as_sent" />
                </Space>
              ),
              children: <RecordedText text={run.prompt} label="The prompt of this run" />,
            },
          ]}
        />
      ) : (
        <Space wrap>
          <Typography.Text strong>The prompt</Typography.Text>
          <RecordTag record="not_recorded" />
        </Space>
      )}
      {run.in_use ? (
        <Typography.Text type="secondary">This run's text is the Summary now in the report.</Typography.Text>
      ) : canTake ? (
        <Button onClick={() => onTake(run.run_id)} loading={taking}>
          {TAKE_RUN}
        </Button>
      ) : (
        <Typography.Text type="secondary">{TAKE_RUN_ELSEWHERE}</Typography.Text>
      )}
    </Space>
  )
}

function SummaryRuns({ part, canTake }: { part: PartDetail; canTake: boolean }) {
  const { message } = App.useApp()
  const [noop, setNoop] = useState<Noop | null>(null)
  const take = useStudyMutation(part.study, (runId: string) => takeSummaryRun(part.study, runId), {
    onMutate: () => setNoop(null),
    onSuccess: (res) => {
      const nothing = noopOf(res)
      if (nothing) setNoop(nothing)
      else void message.success("The run's text is now the Summary in the report, as a draft that is not approved.")
    },
  })
  const runs = part.runs ?? []
  return (
    <Card size="small" title={`Runs of the model (${runs.length})`} data-testid="summary-runs">
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        {take.error && <Refusal error={take.error} studyId={part.study} title="The text was not taken into the report" />}
        {noop && <Refusal noop={noop} />}
        {runs.length === 0 ? (
          <Typography.Text>No run is recorded: the model has not been asked to word this Summary.</Typography.Text>
        ) : (
          <Collapse
            size="small"
            defaultActiveKey={runs[0] ? [runs[0].run_id] : []}
            items={runs.map((r) => ({
              key: r.run_id,
              label: (
                <Space wrap>
                  <span>Run of {r.at ? new Date(r.at).toLocaleString('en-US') : 'a time not recorded'}</span>
                  {r.in_use && <Tag color="blue">In the report</Tag>}
                </Space>
              ),
              children: <Run run={r} canTake={canTake} onTake={(id) => take.mutate(id)} taking={take.isPending} />,
            }))}
          />
        )}
      </Space>
    </Card>
  )
}

function HowItWasWritten({ part, checkSays, canTake }: { part: PartDetail; checkSays: string; canTake: boolean }) {
  const noModel = part.written_by === 'data'
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }} data-testid="how-written">
      <Descriptions
        size="small"
        column={1}
        items={[
          {
            key: 'by',
            label: 'Written by',
            children: (
              <Space orientation="vertical" size={2}>
                <WrittenByTags writtenBy={part.written_by} />
                <Typography.Text type="secondary">{part.written_by_say}</Typography.Text>
              </Space>
            ),
          },
          { key: 'model', label: 'Model', children: part.model ?? (noModel ? NO_MODEL : MODEL_NOT_RECORDED) },
          ...(part.knowledge_base !== undefined
            ? [
                {
                  key: 'kb',
                  label: 'Knowledge base',
                  children: part.knowledge_base?.name ? (
                    <Space orientation="vertical" size={0}>
                      <Typography.Text>{part.knowledge_base.name}</Typography.Text>
                      {part.knowledge_base.sha256 && (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          fingerprint {part.knowledge_base.sha256.slice(0, 12)}
                        </Typography.Text>
                      )}
                    </Space>
                  ) : (
                    MODEL_NOT_RECORDED
                  ),
                },
              ]
            : []),
          ...(part.template
            ? [
                {
                  key: 'template',
                  label: 'Prompt template',
                  children:
                    part.template.in_use_version !== null
                      ? `Version ${part.template.in_use_version} worded the text in the report; version ${part.template.version} is the current one.`
                      : `Version ${part.template.version} is the current one.`,
                },
              ]
            : []),
          { key: 'approved', label: 'Approved', children: part.approved ? 'Yes' : 'No' },
        ]}
      />

      {part.given.length > 0 && (
        <Card size="small" title="What the model was given">
          <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
            {part.given.map((g) => (
              <Given key={g.id} item={g} />
            ))}
          </Space>
        </Card>
      )}

      {part.unmatched_say !== undefined && (
        <Card size="small" title="Numbers in the text that were not among the facts given" data-testid="unmatched">
          <Space orientation="vertical" size="small">
            {part.unmatched_numbers && part.unmatched_numbers.length > 0 && (
              <Space wrap size={4}>
                {part.unmatched_numbers.map((n) => (
                  <Tag key={n} color="gold">
                    {n}
                  </Tag>
                ))}
              </Space>
            )}
            <Typography.Text>{part.unmatched_say}</Typography.Text>
          </Space>
        </Card>
      )}

      {part.runs !== undefined && <SummaryRuns part={part} canTake={canTake} />}

      {part.papers_offered !== undefined && (
        <Card size="small" title={`The papers offered to the model (${part.papers_offered.length})`}>
          {part.papers_offered.length === 0 ? (
            <Typography.Text>No paper was recorded as offered.</Typography.Text>
          ) : (
            <Papers papers={part.papers_offered} />
          )}
        </Card>
      )}

      {part.citation_check && <CitationCheckBox check={part.citation_check} checkSays={checkSays} />}
    </Space>
  )
}

export function PartView({
  studyId,
  part,
  checkSays,
  canTake,
  onBack,
}: {
  /** the session that holds the part */
  studyId: string
  part: string
  checkSays: string
  /** whether a Summary run may be taken into the report from this page */
  canTake: boolean
  onBack: () => void
}) {
  const { data, error, isPending, refetch, isFetching } = useWritingPart(studyId, part)
  const back = (
    <Button type="link" style={{ padding: 0 }} onClick={onBack}>
      ← All written parts
    </Button>
  )
  if (isPending) {
    return (
      <Space orientation="vertical" style={{ width: '100%' }}>
        {back}
        <Skeleton active paragraph={{ rows: 8 }} />
      </Space>
    )
  }
  if (!data) {
    return (
      <Space orientation="vertical" style={{ width: '100%' }}>
        {back}
        <Refusal
          error={error}
          studyId={studyId}
          title="This part could not be read"
          action={
            <Button onClick={() => void refetch()} loading={isFetching}>
              Try again
            </Button>
          }
        />
      </Space>
    )
  }
  const datasetRoute = moduleRoute('M3', data.study)
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }} data-testid="part-view" data-part={data.key}>
      {back}
      <Space wrap align="baseline" size="middle">
        <Typography.Title level={4} style={{ margin: 0 }}>
          {data.title}
        </Typography.Title>
        <Typography.Text code>{data.study}</Typography.Text>
        <WrittenByTags writtenBy={data.written_by} />
      </Space>
      <Row gutter={[24, 24]}>
        <Col xs={24} xl={13}>
          <Card size="small" title="The text" data-testid="part-text">
            <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
              {!data.exists && <Alert type="info" showIcon title={NOT_WRITTEN_YET} description={data.say ?? undefined} />}
              {data.text_say && <Typography.Text type="secondary">{data.text_say}</Typography.Text>}
              <TextBlocks blocks={data.text} />
              {data.key === 'results' && datasetRoute && (
                <Link to={datasetRoute}>Follow a table back to the files it was built from (Combined data)</Link>
              )}
              {data.references && data.references.length > 0 && (
                <section aria-label="References">
                  <Typography.Title level={5} style={{ marginTop: 0 }}>
                    References
                  </Typography.Title>
                  {data.references.map((r) => (
                    <Typography.Paragraph key={r} style={{ marginBottom: 4 }}>
                      {r}
                    </Typography.Paragraph>
                  ))}
                </section>
              )}
            </Space>
          </Card>
        </Col>
        <Col xs={24} xl={11}>
          <Card size="small" title="How it was written">
            <HowItWasWritten part={data} checkSays={checkSays} canTake={canTake} />
          </Card>
        </Col>
      </Row>
    </Space>
  )
}
