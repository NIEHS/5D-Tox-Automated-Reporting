import { Alert, Button, Card, Skeleton, Space, Table, Tag, Typography } from 'antd'
import { Link } from 'react-router'
import type { CheckPart, KnowledgeBaseUsed, ReferenceEntry, References } from '../../api/demoWriting'
import { ItemList } from '../../kit/ItemList'
import { studyRoute } from '../../kit/modules'
import { Refusal } from '../../kit/Refusal'
import { Outside } from './marks'
import { useReferences } from './queries'
import {
  NOT_CITED,
  NO_REFERENCES,
  REFERENCES_STUDY_NOTE,
  STATEMENTS_NONE,
  STATEMENTS_NOT_A_PAPER,
  STATEMENTS_TITLE,
  STATEMENTS_UNREADABLE,
  plural,
  studyLabel,
} from './words'

/**
 * How citations work: the reference list as printed, the sentences that cite
 * each entry, where a paper came from and what the knowledge base holds of
 * it, and the check's result with what the check does and does not
 * establish. All of it is the backend's answer; nothing is matched here.
 */

function whereOf(part: CheckPart): string {
  if (part.where === 'background') return 'The Background'
  return part.study ? `Gene-level interpretations, ${part.study} study` : 'Gene-level interpretations'
}

function CheckResult({ refs }: { refs: References }) {
  const check = refs.check
  return (
    <Card size="small" title="The citation check" data-testid="check">
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Alert type={check.untraced > 0 ? 'warning' : 'success'} showIcon title={check.say} data-testid="check-result" />
        <Alert type="info" showIcon title={refs.check_says} data-testid="check-says" />
        <ItemList
          dense
          aria-label="The check, part by part"
          items={check.parts}
          rowKey={(p) => `${p.where}-${p.study_id}`}
          render={(p) => (
            <Space orientation="vertical" size={2} style={{ width: '100%' }}>
              <Space wrap>
                <Typography.Text strong>{whereOf(p)}</Typography.Text>
                <Typography.Text>{p.say}</Typography.Text>
              </Space>
              {p.items.map((it, i) => (
                <Space key={i} orientation="vertical" size={0} style={{ paddingInlineStart: 12 }}>
                  <Space wrap>
                    <Tag color="gold">{it.token}</Tag>
                    <Typography.Text type="secondary">{it.what}</Typography.Text>
                  </Space>
                  <Typography.Text>{it.sentence}</Typography.Text>
                </Space>
              ))}
              {p.edited_text_warnings > 0 && (
                <Typography.Text type="warning">
                  {plural(p.edited_text_warnings, 'citation', 'citations')} in text a person edited could not be matched to the list.
                </Typography.Text>
              )}
            </Space>
          )}
        />
      </Space>
    </Card>
  )
}

function KnowledgeBases({ kbs }: { kbs: KnowledgeBaseUsed[] }) {
  if (kbs.length === 0) return null
  return (
    <Card size="small" title="Where the papers come from" data-testid="knowledge-bases">
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Typography.Text>
          Each gene-level interpretation is offered papers from the study's knowledge base: a fixed collection of papers and the
          statements extracted from them. The model may cite only the papers offered.
        </Typography.Text>
        {kbs.map((kb) => (
          <Space key={kb.study_id} wrap>
            <Typography.Text strong>{studyLabel(kb.study)}:</Typography.Text>
            {kb.usable ? (
              <Typography.Text>knowledge base {kb.name}</Typography.Text>
            ) : (
              <Typography.Text type="warning">no knowledge base could be read</Typography.Text>
            )}
            {kb.usable && !kb.same && (
              <Tag color="gold" style={{ whiteSpace: 'normal' }}>
                Not the one recorded with the results{kb.recorded_name ? ` (${kb.recorded_name})` : ''}: the statements shown are
                from the one read now
              </Tag>
            )}
          </Space>
        ))}
      </Space>
    </Card>
  )
}

function fromOf(e: ReferenceEntry): string {
  if (e.kind === 'background_source') return "The Background's sources"
  return e.study ? `${studyLabel(e.study)}'s knowledge base` : 'The knowledge base'
}

function Entry({ e }: { e: ReferenceEntry }) {
  const sentences = e.cited_in.reduce((n, c) => n + c.sentences.length, 0)
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }} data-testid={`entry-${e.n}`}>
      <section aria-label="The source">
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          {e.kind === 'paper' ? 'The paper' : 'The source'}
        </Typography.Title>
        <Typography.Paragraph style={{ marginBottom: 4 }}>
          {e.title ? `${e.title.replace(/\.$/, '')}.` : e.text}
          {e.venue || e.year ? ` ${[e.venue, e.year].filter(Boolean).join(', ')}.` : ''}
        </Typography.Paragraph>
        {e.url && <Outside href={e.url}>{e.doi ? `https://doi.org/${e.doi}` : e.url}</Outside>}
        {e.genes.length > 0 && (
          <Typography.Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
            Offered to the model for {plural(e.genes.length, 'gene', 'genes')} of the study: {e.genes.join(', ')}
          </Typography.Paragraph>
        )}
      </section>

      <section aria-label="Sentences that cite it">
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          Sentences that cite it ({sentences})
        </Typography.Title>
        {e.cited_in.length === 0 ? (
          <Typography.Text type="secondary">{NOT_CITED}</Typography.Text>
        ) : (
          e.cited_in.map((c) => (
            <div key={`${c.study_id}-${c.part_title}`} style={{ marginBottom: 8 }}>
              <Space wrap>
                <Typography.Text strong>{c.part_title}</Typography.Text>
                <Link to={`${studyRoute(c.study_id)}/writing?part=${encodeURIComponent(c.part)}`}>Open this part</Link>
              </Space>
              <ul style={{ margin: '4px 0 0', paddingInlineStart: 18 }}>
                {c.sentences.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
          ))
        )}
      </section>

      <section aria-label={STATEMENTS_TITLE}>
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          {STATEMENTS_TITLE}
        </Typography.Title>
        {e.kind !== 'paper' ? (
          <Typography.Text type="secondary">{STATEMENTS_NOT_A_PAPER}</Typography.Text>
        ) : e.statements === null ? (
          <Typography.Text type="warning">{STATEMENTS_UNREADABLE}</Typography.Text>
        ) : e.statements.length === 0 ? (
          <Typography.Text type="secondary">{STATEMENTS_NONE}</Typography.Text>
        ) : (
          <ul style={{ margin: 0, paddingInlineStart: 18 }}>
            {e.statements.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        )}
      </section>
    </Space>
  )
}

function ReferenceList({ entries }: { entries: ReferenceEntry[] }) {
  return (
    <Table<ReferenceEntry>
      aria-label="The reference list"
      data-testid="reference-list"
      size="small"
      rowKey={(e) => `${e.study_id}-${e.n}`}
      pagination={false}
      dataSource={entries}
      onRow={(e) => ({ 'data-entry': String(e.n) }) as React.HTMLAttributes<HTMLTableRowElement>}
      expandable={{
        expandRowByClick: true,
        expandedRowRender: (e) => <Entry e={e} />,
      }}
      columns={[
        { title: 'No.', dataIndex: 'n', width: 64, render: (n: number) => `[${n}]` },
        {
          title: 'Source',
          key: 'source',
          render: (_, e) => (
            <Space orientation="vertical" size={0}>
              <Typography.Text>{e.title ?? e.text}</Typography.Text>
              {(e.venue || e.year) && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {[e.venue, e.year].filter(Boolean).join(', ')}
                </Typography.Text>
              )}
            </Space>
          ),
        },
        { title: 'From', key: 'from', width: '20%', render: (_, e) => fromOf(e) },
        {
          title: 'Cited in',
          key: 'cited',
          width: 110,
          render: (_, e) => plural(e.cited_in.reduce((n, c) => n + c.sentences.length, 0), 'sentence', 'sentences'),
        },
        {
          title: 'Link',
          key: 'link',
          width: 90,
          render: (_, e) =>
            e.url ? (
              <span onClick={(ev) => ev.stopPropagation()}>
                <Outside href={e.url}>{e.doi ? 'DOI' : 'Source'}</Outside>
              </span>
            ) : null,
        },
      ]}
    />
  )
}

export function Citations({ studyId }: { studyId: string }) {
  const { data, error, isPending, refetch, isFetching } = useReferences(studyId)
  if (isPending) return <Skeleton active paragraph={{ rows: 8 }} />
  if (!data) {
    return (
      <Refusal
        error={error}
        studyId={studyId}
        title="The reference list could not be read"
        action={
          <Button onClick={() => void refetch()} loading={isFetching}>
            Try again
          </Button>
        }
      />
    )
  }
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }} data-testid="citations">
      <Typography.Paragraph style={{ margin: 0 }}>
        Every citation in the report points at a source that was supplied to the model: a public source gathered for the Background,
        or a paper of the knowledge base offered to a gene-level interpretation. A citation that points at nothing supplied is
        reported, and in the interpretations it is removed from the printed text.
      </Typography.Paragraph>
      <CheckResult refs={data} />
      <KnowledgeBases kbs={data.knowledge_bases} />
      {data.report?.id && (
        <Alert
          type="info"
          showIcon
          data-testid="references-pointer"
          title={
            <span>
              {REFERENCES_STUDY_NOTE} <Link to={`${studyRoute(data.report.id)}/writing?tab=citations`}>open the report's list ({data.report.id})</Link>
            </span>
          }
        />
      )}
      <Card
        size="small"
        title={`The reference list (${data.entries.length})`}
        extra={<Typography.Text type="secondary">Choose an entry to see what cites it</Typography.Text>}
      >
        <Space orientation="vertical" size="small" style={{ width: '100%' }}>
          <Typography.Text type="secondary">{data.numbering_say}</Typography.Text>
          {data.entries.length === 0 ? <Typography.Text>{NO_REFERENCES}</Typography.Text> : <ReferenceList entries={data.entries} />}
        </Space>
      </Card>
    </Space>
  )
}
