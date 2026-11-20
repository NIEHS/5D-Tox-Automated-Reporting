import { Alert, Button, Card, Collapse, Descriptions, Skeleton, Space, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { runIntegrate, type AssayChain, type Dataset, type DatasetExperiment, type DatasetFile, type IntegrateSummary, type LeftOutValue } from '../../api/demoData'
import type { ExistingStudyState } from '../../api/types'
import { formatClock } from '../../kit/elapsed'
import { moduleById, moduleRoute } from '../../kit/modules'
import { Refusal } from '../../kit/Refusal'
import { useStudyState } from '../../kit/useStudyState'
import { Wait } from '../../kit/Wait'
import { ApiPageLink, FinishedNotice, StudyChoice } from './common'
import { isFinishedSide } from './demoPair'
import { FollowTable } from './FollowTable'
import { useDataset } from './queries'
import { LEFT_OUT_SAY, LEFT_OUT_TITLE, capital, dataTypeWords, doseWords, fileKindWords, fileTypeWords, recordedInWords } from './words'

/**
 * Combined data (the demo path, S1): a study's files become one dataset, and
 * every table of the report can be followed back to the files it was built
 * from. Before the files are combined: the files, and the one act. After:
 * the dataset's experiments, each assay's chain from workbook to dataset, the
 * animal accounting, and "Follow a table back".
 *
 * Everything shown is the backend's: the files and chains from
 * GET …/dataset, and whether the act may be done from the study's state
 * (legal_actions). Nothing is worked out here.
 */

export const COMBINE_LABEL = 'Combine the files into one dataset'

function FileName({ name }: { name: string | null | undefined }) {
  return name ? <Typography.Text style={{ fontFamily: 'monospace', fontSize: 13 }}>{name}</Typography.Text> : null
}

const NOT_RECORDED = <Typography.Text type="secondary">not recorded</Typography.Text>

function FilesTable({ files }: { files: DatasetFile[] }) {
  return (
    <Table<DatasetFile>
      aria-label="The study's files"
      data-testid="files"
      size="small"
      rowKey="filename"
      pagination={false}
      scroll={{ x: true }}
      dataSource={files}
      columns={[
        { title: 'File', key: 'file', render: (_, f) => <FileName name={f.filename} /> },
        { title: 'Recognized as', key: 'type', render: (_, f) => fileTypeWords(f.file_type, f.data_type) },
        { title: 'Assay', key: 'assay', render: (_, f) => f.assay ?? <Typography.Text type="secondary">none</Typography.Text> },
        { title: 'Kind of data', key: 'data', render: (_, f) => dataTypeWords(f.data_type) },
        { title: 'Sexes', key: 'sexes', render: (_, f) => f.sexes.join(', ') },
        { title: 'Animals', key: 'animals', align: 'right', render: (_, f) => f.animals },
        { title: 'Dose groups', key: 'doses', render: (_, f) => doseWords(f.dose_groups, f.dose_unit) },
      ]}
    />
  )
}

/** The values the package says were left out, as the backend serves them. */
function LeftOut({ values }: { values: LeftOutValue[] }) {
  if (values.length === 0) return null
  return (
    <Card size="small" title={`${LEFT_OUT_TITLE} (${values.length})`}>
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Typography.Text type="secondary">{LEFT_OUT_SAY}</Typography.Text>
        <Table<LeftOutValue>
          aria-label={LEFT_OUT_TITLE}
          data-testid="left-out"
          size="small"
          rowKey={(v) => `${v.stated_in}|${v.animal_id}|${v.endpoint}|${v.day}`}
          pagination={false}
          scroll={{ x: true }}
          dataSource={values}
          columns={[
            { title: 'Animal', key: 'animal', render: (_, v) => v.animal_id },
            { title: 'Assay', key: 'assay', render: (_, v) => v.assay ?? NOT_RECORDED },
            { title: 'Endpoint', key: 'endpoint', render: (_, v) => v.endpoint ?? NOT_RECORDED },
            { title: 'Day', key: 'day', render: (_, v) => v.day ?? NOT_RECORDED },
            { title: 'Value recorded', key: 'value', align: 'right', render: (_, v) => v.value ?? NOT_RECORDED },
            { title: 'Why', key: 'why', render: (_, v) => (v.reason_say ? capital(v.reason_say) : (v.reason ?? NOT_RECORDED)) },
            { title: 'Stated in', key: 'file', render: (_, v) => <FileName name={v.stated_in} /> },
          ]}
          expandable={{
            rowExpandable: (v) => Boolean(v.note),
            expandedRowRender: (v) => <Typography.Text type="secondary">{v.note}</Typography.Text>,
          }}
        />
      </Space>
    </Card>
  )
}

/** Per assay: workbook → converted table → (once combined) the file the dataset took. */
function AssayChains({ assays, combined }: { assays: AssayChain[]; combined: boolean }) {
  return (
    <Table<AssayChain>
      aria-label="From workbook to dataset, by assay"
      data-testid="assay-chains"
      size="small"
      rowKey="key"
      pagination={false}
      scroll={{ x: true }}
      dataSource={assays}
      columns={[
        {
          title: 'Assay',
          key: 'assay',
          render: (_, a) => <Typography.Text strong>{a.assay ?? dataTypeWords(a.data_type)}</Typography.Text>,
        },
        {
          title: 'Workbook',
          key: 'workbook',
          render: (_, a) => (a.workbook ? <FileName name={a.workbook} /> : <Typography.Text type="secondary">none</Typography.Text>),
        },
        {
          title: 'Table converted from it',
          key: 'tables',
          render: (_, a) =>
            a.tables.length === 0 ? (
              <Typography.Text type="secondary">none</Typography.Text>
            ) : (
              <Space orientation="vertical" size={2}>
                {a.tables.map((t) => (
                  <span key={t.filename}>
                    <FileName name={t.filename} />
                    <br />
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {t.converted_from ? (
                        <>
                          converted from {t.converted_from.filename} ({recordedInWords(t.converted_from)})
                        </>
                      ) : (
                        'which workbook it was converted from is not recorded'
                      )}
                    </Typography.Text>
                  </span>
                ))}
              </Space>
            ),
        },
        {
          title: 'BMDExpress project',
          key: 'bm2',
          render: (_, a) => (a.bm2 ? <FileName name={a.bm2} /> : <Typography.Text type="secondary">none</Typography.Text>),
        },
        ...(combined
          ? [
              {
                title: 'Taken into the dataset from',
                key: 'taken',
                render: (_: unknown, a: AssayChain) =>
                  a.taken_from ? (
                    <span>
                      <FileName name={a.taken_from.filename} />
                      <br />
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        the {fileKindWords(a.taken_from.kind)}
                      </Typography.Text>
                    </span>
                  ) : (
                    NOT_RECORDED
                  ),
              },
            ]
          : []),
      ]}
    />
  )
}

function ExperimentsTable({ experiments }: { experiments: DatasetExperiment[] }) {
  return (
    <Table<DatasetExperiment>
      aria-label="The experiments in the dataset"
      data-testid="experiments"
      size="small"
      rowKey={(e) => e.name ?? ''}
      pagination={false}
      scroll={{ x: true }}
      dataSource={experiments}
      columns={[
        { title: 'Experiment', key: 'name', render: (_, e) => <FileName name={e.name} /> },
        { title: 'Assay', key: 'assay', render: (_, e) => e.assay },
        { title: 'Sex', key: 'sex', render: (_, e) => capital(e.sex) },
        { title: 'Organ or tissue', key: 'organ', render: (_, e) => e.organ ?? '' },
        { title: 'Endpoints', key: 'endpoints', align: 'right', render: (_, e) => e.endpoints.toLocaleString('en-US') },
        { title: 'Animals', key: 'animals', align: 'right', render: (_, e) => e.animals },
        {
          title: 'File the data came from',
          key: 'file',
          render: (_, e) => (e.taken_from ? <FileName name={e.taken_from.filename} /> : NOT_RECORDED),
        },
        {
          title: "Study's own benchmark dose analysis",
          key: 'bmd',
          render: (_, e) => (e.own_benchmark_doses ? <Tag color="green">In the dataset</Tag> : <Tag>Not among the files</Tag>),
        },
      ]}
    />
  )
}

function AccountingSummary({ dataset }: { dataset: Dataset }) {
  const a = dataset.accounting
  if (!a) {
    return (
      <Alert
        type="warning"
        showIcon
        title="The animals have not been accounted for yet."
        description="The accounting is made right after the files are combined. It is missing here, so the data cannot be analyzed yet."
      />
    )
  }
  const doses = Object.keys(a.dose_design)
  const sexes = [...new Set(doses.flatMap((d) => Object.keys(a.dose_design[d] ?? {})))]
  const assays = Object.entries(a.assay_coverage)
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }} data-testid="accounting">
      {a.problems.length === 0 ? (
        <Alert type="success" showIcon title="The accounting found no inconsistency between the files." />
      ) : (
        <Alert
          type="error"
          showIcon
          title={`The accounting found ${a.problems.length} ${a.problems.length === 1 ? 'inconsistency' : 'inconsistencies'} between the files.`}
          description={<pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: 0 }}>{JSON.stringify(a.problems, null, 2)}</pre>}
        />
      )}
      <Table
        aria-label="Animals by dose group"
        size="small"
        rowKey="dose"
        pagination={false}
        dataSource={doses.map((dose) => ({ dose, ...(a.dose_design[dose] ?? {}) }))}
        columns={[
          { title: 'Dose group', key: 'dose', render: (_, r) => String(Number(r.dose)) },
          ...sexes.map((sex) => ({ title: `${sex} animals`, key: sex, align: 'right' as const, render: (_: unknown, r: Record<string, string | number>) => r[sex] ?? 0 })),
        ]}
      />
      <Table
        aria-label="Animals found per assay, by kind of file"
        size="small"
        rowKey={(r) => r[0]}
        pagination={false}
        dataSource={assays}
        columns={[
          { title: 'Assay', key: 'assay', render: (_, [assay]) => assay },
          { title: 'In the workbook', key: 'xlsx', align: 'right', render: (_, [, c]) => c.xlsx ?? 0 },
          { title: 'In the converted table', key: 'txt', align: 'right', render: (_, [, c]) => c.txt_csv ?? 0 },
          { title: 'In the BMDExpress project (samples)', key: 'bm2', align: 'right', render: (_, [, c]) => c.bm2 ?? 0 },
        ]}
      />
    </Space>
  )
}

/** The one act of the page, offered only where the backend allows it, with the reason where it does not. */
function CombineAct({ state, onStart }: { state: ExistingStudyState; onStart: () => void }) {
  const legal = state.legal_actions.includes('INTEGRATE')
  const next = state.stands.next
  const nextModule = moduleById(next?.fix)
  const nextPath = nextModule ? moduleRoute(nextModule.id, state.id) : undefined
  return (
    <Space orientation="vertical" size="small" data-testid="combine-act">
      <Button type="primary" size="large" disabled={!legal} onClick={onStart}>
        {COMBINE_LABEL}
      </Button>
      {legal ? (
        <Typography.Text type="secondary">
          It takes about half a minute. Every animal is then accounted for across the files, as part of the same step.
        </Typography.Text>
      ) : (
        <Typography.Text data-testid="combine-why-not">
          Not available now: {state.stands.say}.
          {next ? (
            <>
              {' '}
              Next step: {nextPath && nextModule?.id !== 'M3' ? <Link to={nextPath}>{next.say}</Link> : next.say}.
            </>
          ) : null}
        </Typography.Text>
      )}
    </Space>
  )
}

function RunOutcome({ summary, state }: { summary: IntegrateSummary; state: ExistingStudyState }) {
  const next = state.stands.next
  const nextModule = moduleById(next?.fix)
  const nextPath = nextModule ? moduleRoute(nextModule.id, state.id) : undefined
  return (
    <Alert
      type="success"
      showIcon
      closable
      data-testid="combine-outcome"
      title="The files were combined into one dataset."
      description={
        <Space orientation="vertical" size={2}>
          <Typography.Text>
            {summary.experiments ?? 0} experiments; {summary.own_bmd_analyses ?? 0} result sets of the study&apos;s own benchmark dose analysis; the
            animals accounted for, with {summary.accounting_problems ?? 0} {summary.accounting_problems === 1 ? 'inconsistency' : 'inconsistencies'} found.
          </Typography.Text>
          {summary.data_approval_withdrawn && (
            <Typography.Text>The earlier review of the data no longer holds: it was made on the dataset this one replaces.</Typography.Text>
          )}
          {next && nextPath && nextModule?.id !== 'M3' && (
            <Typography.Text>
              Next step: <Link to={nextPath}>{next.say}</Link>
            </Typography.Text>
          )}
        </Space>
      }
    />
  )
}

/** The page; its transient state (the wait, the last run) belongs to one study. */
export function CombinedData() {
  const { id = '' } = useParams()
  return <CombinedDataOf key={id} id={id} />
}

function CombinedDataOf({ id }: { id: string }) {
  const { data: state } = useStudyState(id)
  const [waiting, setWaiting] = useState(false)
  const [lastRun, setLastRun] = useState<IntegrateSummary | null>(null)
  const isStudy = Boolean(state?.exists && state.kind !== 'report')
  const dataset = useDataset(isStudy ? id : undefined)

  if (!state?.exists) return null
  if (state.kind === 'report') return <StudyChoice state={state} slug="dataset" />

  const finished = isFinishedSide(state)
  const d = dataset.data

  return (
    <>
      {/* Beside the page, never among its parts: a part that appears while the
          act runs would move the wait, and a moved wait starts the act again. */}
      {waiting && (
        <Wait
          studyId={id}
          title="Combining the files into one dataset"
          note="This takes about half a minute."
          start={() => runIntegrate(id)}
          onFinish={(outcome) => {
            if (outcome.ok) setLastRun(outcome.summary)
          }}
          onClose={() => setWaiting(false)}
        />
      )}
      <Space orientation="vertical" size="large" style={{ width: '100%' }}>
        <Space orientation="vertical" size={4}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            Combined data
          </Typography.Title>
          <Typography.Text>
            The study&apos;s files are combined into one dataset. Every table, figure and sentence of the report is built from that dataset and
            nothing else, so each table can be followed back to the files it came from.
          </Typography.Text>
          <ApiPageLink group="Combined data" />
        </Space>

        <FinishedNotice state={state} slug="dataset" act="Combining the files" />

        {dataset.isPending ? (
          <Skeleton active />
        ) : !d ? (
          <Refusal
            error={dataset.error}
            studyId={id}
            title="The combined data could not be read"
            action={
              <Button onClick={() => void dataset.refetch()} loading={dataset.isFetching}>
                Try again
              </Button>
            }
          />
        ) : !d.integrated ? (
          <>
            <Alert
              type="info"
              showIcon
              data-testid="not-combined"
              title="The files are not combined yet."
              description={
                d.files_checked
                  ? 'The file check recognized the files below. Combining them makes the one dataset the report is built from.'
                  : 'The files below have not passed the file check, which comes first.'
              }
            />
            {!finished && <CombineAct state={state} onStart={() => setWaiting(true)} />}
            <Card size="small" title={`The study's files (${d.files.length})`}>
              <FilesTable files={d.files} />
            </Card>
            <LeftOut values={d.left_out} />
            <Card size="small" title="From workbook to dataset, by assay" extra={<Typography.Text type="secondary">as the file check recorded it</Typography.Text>}>
              <AssayChains assays={d.assays} combined={false} />
            </Card>
          </>
        ) : (
          <>
            {lastRun && <RunOutcome summary={lastRun} state={state} />}
            {/* An integration made from an earlier file check: the backend says the next step is here. */}
            {!finished && state.stands.next?.fix === 'M3' && (
              <>
                <Alert type="warning" showIcon title="The dataset below was combined before the files were last checked." description={`${state.stands.say}.`} />
                <CombineAct state={state} onStart={() => setWaiting(true)} />
              </>
            )}
            <Card
              size="small"
              title="The dataset"
              extra={d.integrated_at ? <Typography.Text type="secondary">combined {d.integrated_at.slice(0, 10)} at {formatClock(d.integrated_at)}</Typography.Text> : null}
            >
              <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
                <Descriptions size="small" column={{ xs: 1, md: 3 }}>
                  <Descriptions.Item label="Experiments">{d.experiments?.length ?? 0}</Descriptions.Item>
                  <Descriptions.Item label="Experiments with the study's own benchmark dose analysis">{d.own_bmd_analysis?.experiments.length ?? 0}</Descriptions.Item>
                  <Descriptions.Item label="Files">{d.files.length}</Descriptions.Item>
                </Descriptions>
                <ExperimentsTable experiments={d.experiments ?? []} />
                <Typography.Text type="secondary">
                  Where the study&apos;s own benchmark dose analysis of an experiment is not among the files, its benchmark doses are fit by this
                  application when the analysis is run; each results table says which, under “Follow a table back”.
                </Typography.Text>
              </Space>
            </Card>
            <Card size="small" title="From workbook to dataset, by assay" extra={<Typography.Text type="secondary">as the file check and the dataset recorded it</Typography.Text>}>
              <AssayChains assays={d.assays} combined />
            </Card>
            <LeftOut values={d.left_out} />
            <Card size="small" title="Follow a table back">
              <FollowTable studyId={id} />
            </Card>
            <Card size="small" title="Animal accounting">
              <AccountingSummary dataset={d} />
            </Card>
            <Collapse
              items={[{ key: 'files', label: `The study's files (${d.files.length})`, children: <FilesTable files={d.files} /> }]}
            />
          </>
        )}

      </Space>
    </>
  )
}
