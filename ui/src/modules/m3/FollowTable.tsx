import { Alert, Button, Descriptions, Radio, Skeleton, Space, Table, Tag, Tooltip, Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router'
import type { ResultTable, SourceRow, TableSexSources, TableSources } from '../../api/demoData'
import { moduleRoute } from '../../kit/modules'
import { Refusal } from '../../kit/Refusal'
import { useTableSources, useTables } from './queries'
import { BMD_NOT_RECORDED, bmdSourceWords, bmrWords, fileKindWords, isNumberPrinted, recordedInWords, stopWords } from './words'

/**
 * "Follow a table back": choose one of the report's results tables and see,
 * row by row, the endpoint, the experiment in the dataset, the file the data
 * was taken from, the workbook that file was converted from, and where each
 * benchmark dose comes from. Every link is a record the backend read as
 * written; where a record is missing the page says where the chain stops.
 */

function tableLabel(t: ResultTable): string {
  return t.title ?? t.key
}

function Mono({ children }: { children: React.ReactNode }) {
  return <Typography.Text style={{ fontFamily: 'monospace', fontSize: 13 }}>{children}</Typography.Text>
}

const NOT_RECORDED = <Typography.Text type="secondary">not recorded</Typography.Text>

function BenchmarkDoseNote({ sources, sex }: { sources: TableSources; sex: TableSexSources }) {
  if (!sources.has_benchmark_doses) {
    return <Typography.Text type="secondary">This table prints no benchmark dose.</Typography.Text>
  }
  const b = sex.benchmark_dose
  if (!b) return <Typography.Text type="warning">{BMD_NOT_RECORDED}</Typography.Text>
  const words = bmdSourceWords(b)
  const bmr = bmrWords(b.bmr)
  return (
    <Space orientation="vertical" size={2}>
      <span>
        <Tag color={b.source === 'recorded' ? 'blue' : b.source === 'inferred' ? 'gold' : b.source === 'engine' ? 'purple' : 'red'}>{words.label}</Tag>
        <Typography.Text>{words.explain}</Typography.Text>
      </span>
      <Typography.Text type="secondary">
        {bmr ? `Benchmark response: ${bmr}.` : 'Benchmark response: not recorded.'}
        {b.constant_variance === true ? ' Variance: constant.' : b.constant_variance === false ? ' Variance: not constant.' : ''}
        {b.models && b.models.length > 0 ? ` Models averaged: ${b.models.join(', ')}.` : ''}
        {b.analysis?.software ? ` The study's analysis was made with ${b.analysis.software}.` : ''}
      </Typography.Text>
    </Space>
  )
}

function SexSources({ sources, sex }: { sources: TableSources; sex: TableSexSources }) {
  const experiments = sex.experiments.map((e) => e.name ?? '').join(', ')
  const files = sex.files.map((f) => f.filename).join(', ')
  const workbooks = [...new Set(sex.files.map((f) => f.converted_from?.filename).filter((n): n is string => Boolean(n)))].join(', ')
  const b = sex.benchmark_dose
  const sourceLabel = b ? bmdSourceWords(b).label : null

  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }} data-testid={`sources-${sex.sex}`}>
      <Typography.Title level={5} style={{ margin: 0 }}>
        {sex.sex}
      </Typography.Title>
      {sex.stops && (
        <Alert type="warning" showIcon data-testid="chain-stops" title="The record stops here" description={stopWords(sex.stops, sources.assay, sex.sex)} />
      )}
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="Experiment in the dataset">
          {sex.experiments.length === 0
            ? NOT_RECORDED
            : sex.experiments.map((e) => (
                <div key={e.name ?? ''}>
                  <Mono>{e.name}</Mono>{' '}
                  <Typography.Text type="secondary">
                    ({e.endpoints} endpoints, {e.animals} animals{e.organ ? `; ${e.organ}` : ''})
                  </Typography.Text>
                  {e.endpoint_names && e.endpoint_names.length > 0 && (
                    <div>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        Its endpoints: {e.endpoint_names.join(', ')}
                      </Typography.Text>
                    </div>
                  )}
                </div>
              ))}
        </Descriptions.Item>
        <Descriptions.Item label="File the data was taken from">
          {sex.files.length === 0
            ? NOT_RECORDED
            : sex.files.map((f) => (
                <div key={f.filename}>
                  <Mono>{f.filename}</Mono> <Typography.Text type="secondary">(the {fileKindWords(f.kind)})</Typography.Text>
                </div>
              ))}
        </Descriptions.Item>
        <Descriptions.Item label="Workbook it was converted from">
          {sex.files.length === 0
            ? NOT_RECORDED
            : sex.files.map((f) =>
                f.converted_from ? (
                  <div key={f.filename}>
                    <Mono>{f.converted_from.filename}</Mono> <Typography.Text type="secondary">({recordedInWords(f.converted_from)})</Typography.Text>
                  </div>
                ) : f.kind === 'txt_csv' ? (
                  <div key={f.filename}>{NOT_RECORDED}</div>
                ) : (
                  <div key={f.filename}>
                    <Typography.Text type="secondary">The file is a source file itself; it was not converted.</Typography.Text>
                  </div>
                ),
              )}
        </Descriptions.Item>
        <Descriptions.Item label="Benchmark doses">
          <BenchmarkDoseNote sources={sources} sex={sex} />
        </Descriptions.Item>
      </Descriptions>

      <Table<SourceRow & { index: number }>
        aria-label={`${sources.title ?? sources.key}, ${sex.sex}: each row followed back`}
        size="small"
        rowKey="index"
        pagination={false}
        scroll={{ x: true }}
        dataSource={sex.rows.map((r, index) => ({ ...r, index }))}
        columns={[
          {
            title: 'Row of the table',
            key: 'label',
            render: (_, r) => (r.heading ? <Typography.Text strong>{r.label}</Typography.Text> : r.label),
          },
          {
            title: 'Endpoint in the dataset',
            key: 'endpoint',
            render: (_, r) =>
              r.heading || r.count_row ? null : r.endpoint_in_dataset ? (
                <Mono>{r.label}</Mono>
              ) : (
                <Tooltip title="The dataset has no endpoint of exactly this name. The row is built from the experiment's endpoints; which of them is not recorded on the row.">
                  <Typography.Text type="secondary" tabIndex={0}>
                    not recorded for this row
                  </Typography.Text>
                </Tooltip>
              ),
          },
          { title: 'Experiment', key: 'experiment', render: (_, r) => (r.heading ? null : experiments ? <Mono>{experiments}</Mono> : NOT_RECORDED) },
          { title: 'File', key: 'file', render: (_, r) => (r.heading ? null : files ? <Mono>{files}</Mono> : NOT_RECORDED) },
          { title: 'Workbook', key: 'workbook', render: (_, r) => (r.heading ? null : workbooks ? <Mono>{workbooks}</Mono> : NOT_RECORDED) },
          ...(sources.has_benchmark_doses
            ? [
                { title: 'Benchmark dose', key: 'bmd', align: 'right' as const, render: (_: unknown, r: SourceRow) => r.bmd ?? '' },
                { title: 'Lower limit', key: 'bmdl', align: 'right' as const, render: (_: unknown, r: SourceRow) => r.bmdl ?? '' },
                {
                  title: 'Where the benchmark dose comes from',
                  key: 'source',
                  render: (_: unknown, r: SourceRow) =>
                    r.heading || r.count_row ? null : !isNumberPrinted(r.bmd) ? (
                      <Typography.Text type="secondary">none printed for this row</Typography.Text>
                    ) : sourceLabel ? (
                      sourceLabel
                    ) : (
                      <Typography.Text type="warning">not recorded</Typography.Text>
                    ),
                },
              ]
            : []),
        ]}
      />
    </Space>
  )
}

function Sources({ studyId, tableKey }: { studyId: string; tableKey: string }) {
  const q = useTableSources(studyId, tableKey)
  if (q.isPending) return <Skeleton active />
  if (!q.data) {
    return (
      <Refusal
        error={q.error}
        studyId={studyId}
        title="The table could not be followed back"
        action={
          <Button onClick={() => void q.refetch()} loading={q.isFetching}>
            Try again
          </Button>
        }
      />
    )
  }
  const s = q.data
  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }} data-testid="table-sources">
      <div>
        <Typography.Title level={4} style={{ margin: 0 }}>
          {s.title ?? s.key}
        </Typography.Title>
        {s.caption && <Typography.Text type="secondary">{s.caption}</Typography.Text>}
      </div>
      {s.has_benchmark_doses && !s.benchmark_dose_recorded && <Alert type="warning" showIcon title={BMD_NOT_RECORDED} />}
      {s.sexes.map((sex) => (
        <SexSources key={sex.sex} sources={s} sex={sex} />
      ))}
    </Space>
  )
}

export function FollowTable({ studyId }: { studyId: string }) {
  const tables = useTables(studyId)
  const [chosen, setChosen] = useState<string | null>(null)

  if (tables.isPending) return <Skeleton active />
  if (!tables.data) {
    return (
      <Refusal
        error={tables.error}
        studyId={studyId}
        title="The report's tables could not be listed"
        action={
          <Button onClick={() => void tables.refetch()} loading={tables.isFetching}>
            Try again
          </Button>
        }
      />
    )
  }
  const list = tables.data.tables
  if (list.length === 0) {
    const process = moduleRoute('P1', studyId)
    return (
      <Alert
        type="info"
        showIcon
        data-testid="no-tables"
        title="The report has no results tables yet."
        description={
          <span>
            The tables are written when the analysis is run. {process && <Link to={process}>Go to Process</Link>}
          </span>
        }
      />
    )
  }
  const current = list.some((t) => t.key === chosen) ? chosen : null
  return (
    <Space orientation="vertical" size="large" style={{ width: '100%' }}>
      <Space orientation="vertical" size="small">
        <Typography.Text>
          The results tables of the report. Choose one to see where each of its rows comes from. Only the tables of the apical results are
          listed; the gene expression tables are not followed back on this page.
        </Typography.Text>
        <Radio.Group
          aria-label="Results table"
          optionType="button"
          buttonStyle="solid"
          value={current}
          onChange={(e) => setChosen(String(e.target.value))}
          options={list.map((t) => ({ value: t.key, label: tableLabel(t) }))}
        />
      </Space>
      {current && <Sources studyId={studyId} tableKey={current} />}
    </Space>
  )
}
