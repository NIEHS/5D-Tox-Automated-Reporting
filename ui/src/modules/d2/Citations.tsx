import { Alert, Button, Card, Skeleton, Space, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router'
import {
  checkCitations,
  type CheckPart,
  type CitationFinding,
  type KnowledgeBaseUsed,
  type PrintedCheck,
  type ReferenceEntry,
  type References,
} from '../../api/demoWriting'
import { ItemList } from '../../kit/ItemList'
import { studyRoute } from '../../kit/modules'
import { Refusal } from '../../kit/Refusal'
import { Wait, type WaitOutcome } from '../../kit/Wait'
import { Outside } from './marks'
import { useReferences } from './queries'
import {
  CHECK_CITATIONS,
  CHECK_CITATIONS_AGAIN,
  FINISHED_LINK,
  NOT_CITED,
  NOT_JUDGED_TITLE,
  NOT_LISTED_SAY,
  NOT_LISTED_TITLE,
  NO_LIST_YET,
  NO_REFERENCES,
  PRINTED_TITLE,
  REFERENCES_STUDY_NOTE,
  STATEMENTS_NONE,
  STATEMENTS_NOT_A_PAPER,
  STATEMENTS_NOT_A_PAPER_BOILERPLATE,
  STATEMENTS_NOT_A_PAPER_PERSON,
  STATEMENTS_TITLE,
  STATEMENTS_UNREADABLE,
  WAIT_CITATIONS_NOTE,
  WAIT_CITATIONS_TITLE,
  WRITERS_TITLE,
  checkOutcome,
  plural,
  studyLabel,
} from './words'

/**
 * How citations work. The check of the report as it is presented (an act
 * with a record: where it stands, what it found, what it does not judge);
 * the reference list that check derived from what the report prints, with
 * the sentences that cite each entry and, for a paper, what the knowledge
 * base holds of it; the recorded sources the report does not list, each with
 * the reason; and what the models cited against the sources supplied to
 * them. All of it is the backend's answer; nothing is matched or numbered
 * here.
 */

const STATE_ALERT: Record<string, 'success' | 'info' | 'warning' | 'error'> = {
  passed: 'success',
  not_checked: 'info',
  out_of_date: 'warning',
  failed: 'error',
}

const SEVERITY: Record<string, { label: string; color: string }> = {
  error: { label: 'Error', color: 'red' },
  warning: { label: 'Not checked or to look at', color: 'gold' },
  note: { label: 'Note', color: 'blue' },
}

function Finding({ f }: { f: CitationFinding }) {
  const mark = SEVERITY[f.severity] ?? { label: f.severity, color: 'default' }
  return (
    <Space orientation="vertical" size={2} style={{ width: '100%' }} data-finding={f.code}>
      <Space align="start">
        <Tag color={mark.color}>{mark.label}</Tag>
        <Typography.Text>{f.say}</Typography.Text>
      </Space>
      {f.sentences.length > 0 && (
        <ul style={{ margin: 0, paddingInlineStart: 28 }}>
          {f.sentences.map((s) => (
            <li key={s}>
              <Typography.Text type="secondary">{s}</Typography.Text>
            </li>
          ))}
        </ul>
      )}
    </Space>
  )
}

function Printed({ printed, onCheck }: { printed: PrintedCheck; onCheck: () => void }) {
  const counts = printed.counts
  return (
    <Card
      size="small"
      title={PRINTED_TITLE}
      data-testid="printed-check"
      data-state={printed.state}
      extra={
        printed.act.allowed ? (
          <Button type={printed.state === 'passed' ? 'default' : 'primary'} onClick={onCheck} data-testid="check-citations">
            {printed.state === 'not_checked' ? CHECK_CITATIONS : CHECK_CITATIONS_AGAIN}
          </Button>
        ) : null
      }
    >
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Alert type={STATE_ALERT[printed.state] ?? 'info'} showIcon title={printed.say} data-testid="printed-state" />
        {!printed.act.allowed && printed.act.say && (
          <Typography.Text type="secondary" data-testid="check-not-offered">
            {printed.act.say}{' '}
            {printed.act.counterpart && <Link to={`${studyRoute(printed.act.counterpart)}/writing?tab=citations`}>{FINISHED_LINK}</Link>}
          </Typography.Text>
        )}
        {counts && (
          <Typography.Text data-testid="printed-counts">
            The printed report cites {plural(counts.cited_sources, 'source', 'sources')} in {plural(counts.citations, 'place', 'places')} and
            lists {counts.listed.toLocaleString('en-US')}. {plural(counts.recorded_sources, 'source is', 'sources are')} recorded for it.
          </Typography.Text>
        )}
        {printed.findings.length > 0 && (
          <ItemList
            dense
            aria-label="What the check found"
            items={printed.findings}
            rowKey={(f, i) => `${f.code}-${i}`}
            render={(f) => <Finding f={f} />}
          />
        )}
        <section aria-label={NOT_JUDGED_TITLE} data-testid="not-judged">
          <Typography.Text strong>{NOT_JUDGED_TITLE}</Typography.Text>
          <ul style={{ margin: '2px 0 0', paddingInlineStart: 20 }}>
            {printed.not_judged.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
      </Space>
    </Card>
  )
}

function whereOf(part: CheckPart): string {
  if (part.where === 'background') return 'The Background'
  return part.study ? `Gene-level interpretations, ${part.study} study` : 'Gene-level interpretations'
}

function CheckResult({ refs }: { refs: References }) {
  const check = refs.check
  return (
    <Card size="small" title={WRITERS_TITLE} data-testid="check">
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
  switch (e.kind) {
    case 'background_source':
      return "The Background's sources"
    case 'paper':
      return e.knowledge_base ? `Knowledge base ${e.knowledge_base}` : 'The knowledge base'
    case 'boilerplate':
      return "The report definitions' source library"
    case 'person_source':
      return 'Added by a person'
    default:
      return 'As given with the report'
  }
}

function notAPaper(e: ReferenceEntry): string {
  if (e.kind === 'boilerplate') return STATEMENTS_NOT_A_PAPER_BOILERPLATE
  if (e.kind === 'person_source') return STATEMENTS_NOT_A_PAPER_PERSON
  return STATEMENTS_NOT_A_PAPER
}

function keyOf(e: ReferenceEntry): string {
  return e.n !== null ? String(e.n) : (e.slug ?? e.entry ?? '')
}

function Entry({ e }: { e: ReferenceEntry }) {
  const sentences = e.cited_in.reduce((n, c) => n + c.sentences.length, 0)
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }} data-testid={`entry-${keyOf(e)}`}>
      <section aria-label="The source">
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          {e.listed ? 'The entry as the report prints it' : 'The source as recorded'}
        </Typography.Title>
        <Typography.Paragraph style={{ marginBottom: 4 }}>
          {e.entry ?? e.title ?? e.text}
        </Typography.Paragraph>
        {e.url && <Outside href={e.url}>{e.doi ? `https://doi.org/${e.doi}` : e.url}</Outside>}
        {e.why_not_listed && (
          <Typography.Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
            Not listed: {e.why_not_listed}
          </Typography.Paragraph>
        )}
        {e.genes.length > 0 && (
          <Typography.Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
            Offered to the model for {plural(e.genes.length, 'gene', 'genes')} of the study: {e.genes.join(', ')}
          </Typography.Paragraph>
        )}
      </section>

      <section aria-label="Sentences that cite it">
        <Typography.Title level={5} style={{ marginTop: 0 }}>
          Sentences of the printed report that cite it ({sentences})
        </Typography.Title>
        {e.cited_in.length === 0 ? (
          <Typography.Text type="secondary">{NOT_CITED}</Typography.Text>
        ) : (
          e.cited_in.map((c) => (
            <div key={`${c.study_id}-${c.part_title}`} style={{ marginBottom: 8 }}>
              <Space wrap>
                <Typography.Text strong>{c.part_title}</Typography.Text>
                {c.part && <Link to={`${studyRoute(c.study_id)}/writing?part=${encodeURIComponent(c.part)}`}>Open this part</Link>}
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
          <Typography.Text type="secondary">{notAPaper(e)}</Typography.Text>
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

function ReferenceList({ entries, label, testid }: { entries: ReferenceEntry[]; label: string; testid: string }) {
  const listed = entries.some((e) => e.listed)
  return (
    <Table<ReferenceEntry>
      aria-label={label}
      data-testid={testid}
      size="small"
      rowKey={(e) => `${e.study_id}-${keyOf(e)}`}
      pagination={entries.length > 25 ? { pageSize: 25, showSizeChanger: false } : false}
      dataSource={entries}
      onRow={(e) => ({ 'data-entry': keyOf(e) }) as React.HTMLAttributes<HTMLTableRowElement>}
      expandable={{
        expandRowByClick: true,
        expandedRowRender: (e) => <Entry e={e} />,
      }}
      columns={[
        ...(listed ? [{ title: 'No.', key: 'n', width: 64, render: (_: unknown, e: ReferenceEntry) => (e.n !== null ? `[${e.n}]` : '') }] : []),
        {
          title: 'Source',
          key: 'source',
          render: (_, e) => (
            <Space orientation="vertical" size={0}>
              <Typography.Text>{e.title ?? e.text ?? e.entry}</Typography.Text>
              {(e.venue || e.year) && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {[e.venue, e.year].filter(Boolean).join(', ')}
                </Typography.Text>
              )}
            </Space>
          ),
        },
        { title: 'From', key: 'from', width: '20%', render: (_, e) => fromOf(e) },
        listed
          ? {
              title: 'Cited in',
              key: 'cited',
              width: 110,
              render: (_, e) => plural(e.cited, 'place', 'places'),
            }
          : { title: 'Why it is not listed', key: 'why', width: '28%', render: (_, e) => e.why_not_listed },
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
  const [checking, setChecking] = useState(false)
  const [last, setLast] = useState<WaitOutcome | null>(null)
  if (isPending) return <Skeleton active paragraph={{ rows: 8 }} />
  if (!data) {
    return (
      <Refusal
        error={error}
        studyId={studyId}
        title="The citations could not be read"
        action={
          <Button onClick={() => void refetch()} loading={isFetching}>
            Try again
          </Button>
        }
      />
    )
  }
  const printed = data.printed
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }} data-testid="citations">
      <Typography.Paragraph style={{ margin: 0 }}>
        Every source a report may cite is recorded: a public source gathered for the Background, a paper of the knowledge base offered to
        a gene-level interpretation, a source of the report definitions' library (the statistical procedures, the software), or a source
        a person added. Text cites a source by its record. The numbers and the reference list are derived from what the report prints:
        a source is numbered at its first citation, and only the sources the printed text cites are listed, each once.
      </Typography.Paragraph>
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
      {last?.ok && (
        <Alert
          type={Number(last.summary.errors) > 0 ? 'error' : 'success'}
          showIcon
          closable
          onClose={() => setLast(null)}
          data-testid="check-outcome"
          title={checkOutcome(last.summary)}
        />
      )}
      {printed && (
        <Printed
          printed={printed}
          onCheck={() => {
            setLast(null)
            setChecking(true)
          }}
        />
      )}
      {printed && (
        <Card
          size="small"
          title={`The reference list as the report prints it (${data.entries.length})`}
          extra={data.entries.length > 0 ? <Typography.Text type="secondary">Choose an entry to see what cites it</Typography.Text> : null}
        >
          <Space orientation="vertical" size="small" style={{ width: '100%' }}>
            <Typography.Text type="secondary">{data.numbering_say}</Typography.Text>
            {printed.state === 'not_checked' ? (
              <Typography.Text data-testid="no-list-yet">{NO_LIST_YET}</Typography.Text>
            ) : data.entries.length === 0 ? (
              <Typography.Text>{NO_REFERENCES}</Typography.Text>
            ) : (
              <ReferenceList entries={data.entries} label="The reference list" testid="reference-list" />
            )}
          </Space>
        </Card>
      )}
      {data.not_listed.length > 0 && (
        <Card size="small" title={`${NOT_LISTED_TITLE} (${data.not_listed.length})`} data-testid="not-listed">
          <Space orientation="vertical" size="small" style={{ width: '100%' }}>
            <Typography.Text type="secondary">{NOT_LISTED_SAY}</Typography.Text>
            <ReferenceList entries={data.not_listed} label={NOT_LISTED_TITLE} testid="not-listed-list" />
          </Space>
        </Card>
      )}
      <CheckResult refs={data} />
      <KnowledgeBases kbs={data.knowledge_bases} />
      {checking && (
        <Wait
          studyId={studyId}
          title={WAIT_CITATIONS_TITLE}
          note={WAIT_CITATIONS_NOTE}
          start={() => checkCitations(studyId)}
          onFinish={(outcome) => setLast(outcome)}
          onClose={() => setChecking(false)}
        />
      )}
    </Space>
  )
}
