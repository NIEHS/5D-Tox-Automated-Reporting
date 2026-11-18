import { Alert, Button, Card, Descriptions, Skeleton, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { runAnalysis, type KnowledgeBaseUse, type ProcessSummary, type StudyParameters } from '../../api/demoData'
import type { ExistingStudyState } from '../../api/types'
import { ItemList } from '../../kit/ItemList'
import { moduleById, moduleRoute } from '../../kit/modules'
import { Pending } from '../../kit/Pending'
import { Provenance } from '../../kit/Provenance'
import { Refusal } from '../../kit/Refusal'
import { useStudyState } from '../../kit/useStudyState'
import { Wait } from '../../kit/Wait'
import { ApiPageLink, FinishedNotice, StudyChoice, isFinishedSide } from '../m3'
import { useKnowledgeBase, useStudyParameters } from './queries'
import { PARAMETER_ORDER, RUN_LABEL, RUN_NOTE, knowledgeBaseSourceWords, parameterWords, pinModeWords, pinnedByWords, reviewWhyWords } from './words'

/**
 * Process (the demo path, S2): what the analysis is about to be computed
 * from, the one act that runs it, and what it did.
 *
 * The pre-flight is read-only: the study's parameters each with its source,
 * the analysis method and the report definition fixed for the study, and the
 * knowledge base. Whether the analysis may run is the backend's (the state's
 * legal actions, the parameters' `complete`, the method's `suggestion`, which
 * is served only while no person has chosen one). Nothing is worked out here.
 */

interface ParameterRow {
  key: string
  value: string | number | null
  source: string | undefined
  missing: boolean
  conflicting: unknown
  notApplicable: boolean
}

function parameterRows(p: StudyParameters): ParameterRow[] {
  const keys = [...PARAMETER_ORDER.filter((k) => k in p.values), ...Object.keys(p.values).filter((k) => !PARAMETER_ORDER.includes(k))]
  return keys.map((key) => ({
    key,
    value: p.values[key] ?? null,
    source: p.sources[key],
    missing: p.missing.includes(key),
    conflicting: p.conflicting[key],
    notApplicable: p.not_applicable.includes(key),
  }))
}

function ParametersTable({ parameters, studyId }: { parameters: StudyParameters; studyId: string }) {
  return (
    <Space orientation="vertical" size="small" style={{ width: '100%' }}>
      {!parameters.complete && (
        <Alert
          type="error"
          showIcon
          data-testid="parameters-incomplete"
          title="The analysis will be refused until every study parameter is recorded in the data or stated."
          description={
            parameters.problems.length > 0 ? <ItemList dense items={parameters.problems} rowKey={(p) => p} render={(p) => <Typography.Text>{p}</Typography.Text>} /> : undefined
          }
        />
      )}
      <Table<ParameterRow>
        aria-label="The study's parameters"
        data-testid="parameters"
        size="small"
        rowKey="key"
        pagination={false}
        dataSource={parameterRows(parameters)}
        columns={[
          { title: 'Parameter', key: 'name', render: (_, r) => parameterWords(r.key) },
          {
            title: 'Value',
            key: 'value',
            render: (_, r) =>
              r.notApplicable ? (
                <Typography.Text type="secondary">Does not apply to this study</Typography.Text>
              ) : r.missing ? (
                <Pending
                  label={parameterWords(r.key).toLowerCase()}
                  cause="The data do not record it and nobody has stated it. The analysis is refused until it is stated."
                  fix="M4"
                  studyId={studyId}
                />
              ) : r.conflicting !== undefined ? (
                <Typography.Text type="danger">{Array.isArray(r.conflicting) ? r.conflicting.map(String).join(' / ') : JSON.stringify(r.conflicting)}</Typography.Text>
              ) : (
                <Typography.Text strong>{String(r.value ?? '')}</Typography.Text>
              ),
          },
          {
            title: 'Where it comes from',
            key: 'source',
            render: (_, r) =>
              r.notApplicable || r.missing ? null : r.conflicting !== undefined ? (
                <Provenance kind="conflict" fix="M4" studyId={studyId} />
              ) : (
                <Provenance kind={r.source ?? 'unknown'} fix="M4" studyId={studyId} />
              ),
          },
        ]}
      />
    </Space>
  )
}

function PinsCard({ state }: { state: ExistingStudyState }) {
  const method = state.pins.method
  const definition = state.pins.definition
  const pinsPath = moduleRoute('M5', state.id)
  // Served only while no person has chosen the method: Process refuses until then.
  const unchosen = method?.suggestion !== undefined
  return (
    <Card size="small" title="Analysis method and report definition" data-testid="pins">
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        {unchosen && (
          <Alert
            type="error"
            showIcon
            data-testid="method-unchosen"
            title="No person has chosen the analysis method. The analysis is refused until one is chosen."
            description={
              <Space orientation="vertical" size={2}>
                {method?.suggestion && (
                  <Typography.Text>
                    Proposed: {method.suggestion.name} ({method.suggestion.why}).
                  </Typography.Text>
                )}
                {pinsPath && <Link to={pinsPath}>Go to {moduleById('M5')?.title}</Link>}
              </Space>
            }
          />
        )}
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="Analysis method">
            {method?.name ? (
              <Space wrap size="small">
                <Typography.Text strong>{method.name}</Typography.Text>
                <Typography.Text type="secondary">
                  {[pinModeWords(method.mode), method.pinned ? pinnedByWords(method.pinned_by) : 'not fixed for this study'].filter(Boolean).join('; ')}
                </Typography.Text>
              </Space>
            ) : (
              <Typography.Text type="danger">None</Typography.Text>
            )}
            {(method?.deviations ?? []).map((d) => (
              <div key={d}>
                <Typography.Text type="warning">{d}</Typography.Text>
              </div>
            ))}
            {(method?.mismatches ?? []).map((m) => (
              <div key={m.message}>
                <Typography.Text type="warning">{m.message}</Typography.Text>
              </div>
            ))}
            {method?.error && <Refusal error={method.error} studyId={state.id} title="The analysis method cannot be used" />}
          </Descriptions.Item>
          <Descriptions.Item label="Report definition">
            {definition?.name ? (
              <Space wrap size="small">
                <Typography.Text strong>{definition.name}</Typography.Text>
                <Typography.Text type="secondary">
                  {[pinModeWords(definition.mode), definition.pinned ? pinnedByWords(definition.pinned_by) : 'not fixed for this study'].filter(Boolean).join('; ')}
                </Typography.Text>
              </Space>
            ) : (
              <Typography.Text type="danger">None</Typography.Text>
            )}
            {definition?.drift && (
              <div>
                <Tooltip title={definition.drift}>
                  <Typography.Text type="secondary" tabIndex={0}>
                    The definition&apos;s own files have changed since it was fixed for this study; the study keeps the version it was fixed to.
                  </Typography.Text>
                </Tooltip>
              </div>
            )}
            {definition?.error && <Refusal error={definition.error} studyId={state.id} title="The report definition cannot be used" />}
          </Descriptions.Item>
        </Descriptions>
      </Space>
    </Card>
  )
}

function KnowledgeBaseCard({ kb }: { kb: KnowledgeBaseUse }) {
  return (
    <Descriptions size="small" column={1} bordered>
      <Descriptions.Item label="Knowledge base">
        <Space wrap size="small">
          <Typography.Text strong>{kb.name ?? 'None'}</Typography.Text>
          <Typography.Text type="secondary">{knowledgeBaseSourceWords(kb.source)}</Typography.Text>
          {kb.usable ? <Tag color="green">Usable</Tag> : <Tag color="red">Not usable</Tag>}
        </Space>
        {kb.problem && (
          <div>
            <Typography.Text type="danger">{kb.problem}</Typography.Text>
          </div>
        )}
        <div>
          <Typography.Text type="secondary">
            The gene-level interpretation is written from the papers of this knowledge base.
          </Typography.Text>
        </div>
      </Descriptions.Item>
    </Descriptions>
  )
}

function NextStep({ state }: { state: ExistingStudyState }) {
  const next = state.stands.next
  const m = moduleById(next?.fix)
  const to = m ? moduleRoute(m.id, state.id) : undefined
  if (!next) return null
  return (
    <Typography.Text data-testid="next-step">
      Next step: {to && m?.id !== 'P1' ? <Link to={to}>{next.say}</Link> : next.say}
    </Typography.Text>
  )
}

function UnitList({ title, units }: { title: string; units: { unit: string; say: string }[] }) {
  return (
    <div>
      <Typography.Text strong>
        {title} ({units.length})
      </Typography.Text>
      {units.length === 0 ? (
        <div>
          <Typography.Text type="secondary">Nothing.</Typography.Text>
        </div>
      ) : (
        <ItemList dense aria-label={title} items={units} rowKey={(u) => u.unit} render={(u) => <Typography.Text>{u.say}</Typography.Text>} />
      )}
    </div>
  )
}

function Outcome({ summary, state }: { summary: ProcessSummary; state: ExistingStudyState }) {
  const units = summary.units
  const written = summary.result_sections?.written ?? []
  const unchanged = summary.result_sections?.unchanged ?? []
  const review = summary.approvals_affected?.needs_review ?? []
  const held = summary.approvals_affected?.held ?? []
  const writing = moduleRoute('D2', state.id)
  const titleOf = (key: string) => state.sections.find((s) => s.key === key)?.title ?? key
  return (
    <Card size="small" title="What the analysis did" data-testid="process-outcome">
      <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
        <Alert type="success" showIcon title="The analysis ran to its end." />
        {units?.recorded ? (
          <Space size="large" align="start" wrap>
            <UnitList title="Computed in this run" units={units.computed ?? []} />
            <UnitList title="Unchanged, reused" units={units.reused ?? []} />
          </Space>
        ) : (
          <Typography.Text type="secondary" data-testid="units-not-recorded">
            What was computed and what was reused was not recorded for this run.
          </Typography.Text>
        )}
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="Results sections written">
            {written.length === 0 ? 'None' : written.map(titleOf).join(', ')}
            {unchanged.length > 0 && (
              <div>
                <Typography.Text type="secondary">Unchanged, left as they were: {unchanged.map(titleOf).join(', ')}</Typography.Text>
              </div>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Approvals affected">
            {review.length === 0 && held.length === 0 ? (
              'None'
            ) : (
              <Space orientation="vertical" size={2}>
                {review.map((r) => (
                  <Typography.Text key={r.key} type="warning">
                    {titleOf(r.key)}: its approval was withdrawn because {reviewWhyWords(r.why)}; it has to be approved again.
                  </Typography.Text>
                ))}
                {held.map((key) => (
                  <Typography.Text key={key}>{titleOf(key)}: it belongs to a person, so the new text was not put in its place.</Typography.Text>
                ))}
              </Space>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Summary">
            {summary.summary?.written
              ? `Written (${summary.summary.paragraphs} paragraphs)`
              : summary.summary?.held
                ? 'Left as it was: it was written or approved by a person'
                : 'Not rewritten'}
          </Descriptions.Item>
          <Descriptions.Item label="Citations the check removed">
            {summary.citations_removed === null || summary.citations_removed === undefined ? (
              <Typography.Text type="secondary">The run wrote no reference list.</Typography.Text>
            ) : (
              <Space size="small" wrap>
                <Typography.Text strong data-testid="citations-removed">
                  {summary.citations_removed}
                </Typography.Text>
                <Typography.Text type="secondary">citations in the drafted text could not be traced to a paper that was supplied, and were removed.</Typography.Text>
                {writing && <Link to={writing}>See the citations</Link>}
              </Space>
            )}
          </Descriptions.Item>
        </Descriptions>
        <NextStep state={state} />
      </Space>
    </Card>
  )
}

/** The one act, offered only where the backend allows it, with the reason where it does not. */
function RunAct({
  state,
  parameters,
  parametersFailed,
  onStart,
}: {
  state: ExistingStudyState
  parameters: StudyParameters | undefined
  parametersFailed: boolean
  onStart: () => void
}) {
  const legal = state.legal_actions.includes('PROCESS')
  const unchosen = state.pins.method?.suggestion !== undefined
  const why = !legal
    ? `Not available now: ${state.stands.say}.`
    : parametersFailed
      ? "Not available now: the study's parameters could not be read, so it is not known whether any is missing."
      : !parameters
        ? "Reading the study's parameters."
        : !parameters.complete
          ? 'Not available now: a study parameter is missing or in conflict (above).'
          : unchosen
            ? 'Not available now: no person has chosen the analysis method (above).'
            : null
  const next = state.stands.next
  const m = moduleById(next?.fix)
  const to = m ? moduleRoute(m.id, state.id) : undefined
  return (
    <Space orientation="vertical" size="small" data-testid="run-act">
      <Button type="primary" size="large" disabled={why !== null} onClick={onStart}>
        {RUN_LABEL}
      </Button>
      {why === null ? (
        <Typography.Text type="secondary">
          {RUN_NOTE} The run goes on if this page is closed or reloaded; it cannot be stopped.
          {state.processed ? ' The analysis has been run before: running it again computes what changed since and reuses the rest.' : ''}
        </Typography.Text>
      ) : (
        <Typography.Text data-testid="run-why-not">
          {why}
          {!legal && next ? <> Next step: {to && m?.id !== 'P1' ? <Link to={to}>{next.say}</Link> : next.say}.</> : null}
        </Typography.Text>
      )}
    </Space>
  )
}

/** The page; its transient state (the wait, the last run) belongs to one study. */
export function ProcessPage() {
  const { id = '' } = useParams()
  return <ProcessOf key={id} id={id} />
}

function ProcessOf({ id }: { id: string }) {
  const { data: state } = useStudyState(id)
  const [waiting, setWaiting] = useState(false)
  const [lastRun, setLastRun] = useState<ProcessSummary | null>(null)
  const isStudy = Boolean(state?.exists && state.kind !== 'report')
  const parameters = useStudyParameters(isStudy ? id : undefined)
  const kb = useKnowledgeBase(isStudy ? id : undefined)

  if (!state?.exists) return null
  if (state.kind === 'report') return <StudyChoice state={state} slug="process" />

  const finished = isFinishedSide(state)

  return (
    <>
      {/* Beside the page, never among its parts: a part that appears while the
          act runs would move the wait, and a moved wait starts the act again. */}
      {waiting && (
        <Wait
          studyId={id}
          title="Running the analysis"
          note="This takes about three minutes."
          start={() => runAnalysis(id)}
          onFinish={(outcome) => {
            if (outcome.ok) setLastRun(outcome.summary)
          }}
          onClose={() => setWaiting(false)}
        />
      )}
      <Space orientation="vertical" size="large" style={{ width: '100%' }}>
        <Space orientation="vertical" size={4}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Process
          </Typography.Title>
          <Typography.Text>
            The analysis computes the report&apos;s results from the combined dataset: the statistical tests, the benchmark doses, the table of each
            assay, the gene expression results, the figures and the drafted text.
          </Typography.Text>
          <ApiPageLink group="Process" />
        </Space>

        <FinishedNotice state={state} slug="process" act="Running the analysis" />

        {lastRun ? (
          <Outcome summary={lastRun} state={state} />
        ) : state.processed ? (
          <Alert
            type="success"
            showIcon
            data-testid="already-processed"
            title="The analysis has been run on this study."
            description={<NextStep state={state} />}
          />
        ) : null}

        <Card size="small" title="What the analysis is computed from" extra={<Typography.Text type="secondary">shown here, changed elsewhere</Typography.Text>}>
          <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
            <Typography.Text type="secondary">
              The analysis takes no setting from this page. The study&apos;s own parameters, its analysis method and its knowledge base decide.
            </Typography.Text>
            {parameters.isPending ? (
              <Skeleton active />
            ) : parameters.data ? (
              <ParametersTable parameters={parameters.data} studyId={id} />
            ) : (
              <Refusal
                error={parameters.error}
                studyId={id}
                title="The study's parameters could not be read"
                action={
                  <Button onClick={() => void parameters.refetch()} loading={parameters.isFetching}>
                    Try again
                  </Button>
                }
              />
            )}
          </Space>
        </Card>

        <PinsCard state={state} />

        {kb.isPending ? (
          <Skeleton active paragraph={{ rows: 1 }} />
        ) : kb.data ? (
          <KnowledgeBaseCard kb={kb.data} />
        ) : (
          <Refusal error={kb.error} studyId={id} title="The knowledge base could not be read" />
        )}

        {!finished && (
          <RunAct state={state} parameters={parameters.data} parametersFailed={!parameters.isPending && !parameters.data} onStart={() => setWaiting(true)} />
        )}

      </Space>
    </>
  )
}
