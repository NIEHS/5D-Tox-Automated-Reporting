import { Alert, Button, Card, Collapse, Descriptions, Empty, Skeleton, Space, Steps, Table, Tag, Tooltip, Typography } from 'antd'
import { useState } from 'react'
import { useParams } from 'react-router'
import type { Companion, CoverageRow, FileRow, Finding, FilesView } from '../../api/files'
import { runCheck } from '../../api/files'
import { Refusal } from '../../kit/Refusal'
import { ItemList } from '../../kit/ItemList'
import { Pending } from '../../kit/Pending'
import { Wait } from '../../kit/Wait'
import { BringIn } from './BringIn'
import { useFiles } from './queries'
import {
  CHECK_AGAIN,
  CHECK_BUTTON,
  CHECK_NOTE,
  CHECK_RUNNING,
  checkRanWords,
  COVERAGE_EXPLAIN,
  COVERAGE_TITLE,
  EMPTY_FILES,
  EMPTY_FILES_EXPLAIN,
  GROUPS,
  LEDE,
  NOT_CHECKED,
  NOT_RECORDED,
  SETTLED_OUTSIDE,
  TITLE,
  checkSummary,
  contentsWords,
  coverageTone,
  markOf,
  sizeWords,
  stepStatus,
  stepTitle,
} from './words'

/**
 * M2 "Study files": bring in the data files, check them, and say what each one
 * is (docs/ui-redesign/modules/m2/spec.md).
 *
 * Everything shown is the backend's (GET /api/v2/studies/{id}/files). Nothing
 * is worked out here: not the phase, not whether an act is allowed, not what a
 * file is, not which group a finding belongs in.
 *
 * Built so far: the study's files and what each one is taken to be, the file
 * check's findings in plain words, what the report would be built from, and
 * two of the acts — bringing files in and running the check. Saying what a
 * file is is not built yet; the page says so rather than offering a control
 * that would refuse.
 */
export function FilesPage() {
  const { id = '' } = useParams()
  const files = useFiles(id)
  const [checking, setChecking] = useState(false)
  const [lastCheck, setLastCheck] = useState<Record<string, unknown> | null>(null)

  if (files.isPending) return <Skeleton active paragraph={{ rows: 8 }} />
  if (files.error) {
    return (
      <Refusal
        error={files.error}
        studyId={id}
        title="The study’s files could not be read"
      />
    )
  }

  const view = files.data
  if (!view.takes_files.allowed) {
    return (
      <>
        <Typography.Title level={3}>{TITLE}</Typography.Title>
        <Alert
          type="info"
          showIcon
          message={view.takes_files.say}
          data-testid="takes-no-files"
        />
      </>
    )
  }

  return (
    <>
      {/* Beside the page, never among its parts: a part that appears while the
          act runs would move the wait, and a moved wait starts the act again. */}
      {checking && (
        <Wait
          studyId={id}
          title={CHECK_RUNNING}
          note={CHECK_NOTE}
          start={() => runCheck(id)}
          onFinish={(outcome) => {
            if (outcome.ok) setLastCheck(outcome.summary)
          }}
          onClose={() => setChecking(false)}
        />
      )}
      <Space orientation="vertical" size="middle" style={{ display: 'flex' }}>
        <div>
          <Typography.Title level={3}>{TITLE}</Typography.Title>
          <Typography.Paragraph type="secondary">{LEDE}</Typography.Paragraph>
        </div>

        <Progress view={view} />
        {view.integration && (
          <Alert
            type={view.integration.state === 'current' ? 'info' : 'warning'}
            showIcon
            message={view.integration.say}
            data-testid="integration"
          />
        )}

        <BringIn id={id} act={view.acts.add} filesToken={view.files_token} />
        <Files view={view} />
        <Check
          view={view}
          lastCheck={lastCheck}
          onCheck={() => {
            setLastCheck(null)
            setChecking(true)
          }}
        />
        <Coverage rows={view.coverage} />
        <ActsNotBuilt view={view} />
      </Space>
    </>
  )
}

// ---------------------------------------------------------------------------
// Where the study stands
// ---------------------------------------------------------------------------

function Progress({ view }: { view: FilesView }) {
  return (
    <Card size="small" data-testid="progress">
      <Steps
        size="small"
        items={view.progress.map((step) => ({
          title: stepTitle(step),
          description: step.say,
          status: stepStatus(step),
        }))}
      />
      <Typography.Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
        <Typography.Text strong>Next: </Typography.Text>
        <Typography.Text data-testid="next">{view.next.say}</Typography.Text>
      </Typography.Paragraph>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// The study's files
// ---------------------------------------------------------------------------

function Files({ view }: { view: FilesView }) {
  if (!view.files.length) {
    return (
      <Card size="small" title="The study’s files" data-testid="files">
        <Empty description={EMPTY_FILES}>
          <Typography.Text type="secondary">{EMPTY_FILES_EXPLAIN}</Typography.Text>
        </Empty>
      </Card>
    )
  }
  return (
    <Card size="small" title={`The study’s files (${view.files.length})`} data-testid="files">
      <Table<FileRow>
        aria-label="The study’s files"
        size="small"
        rowKey="name"
        dataSource={view.files}
        pagination={false}
        scroll={{ x: true }}
        expandable={{ expandedRowRender: (row) => <FileDetail row={row} view={view} /> }}
        columns={[
          {
            title: 'File',
            dataIndex: 'name',
            render: (name: string, row) => (
              <Space orientation="vertical" size={0}>
                <Typography.Text code>{name}</Typography.Text>
                <Typography.Text type="secondary">
                  {row.kind_say} · {sizeWords(row.size)}
                </Typography.Text>
              </Space>
            ),
          },
          {
            title: 'What it is',
            dataIndex: ['classification', 'say'],
            render: (say: string, row) => {
              const mark = markOf(row.classification)
              return (
                <Space orientation="vertical" size={2}>
                  <Typography.Text>{say}</Typography.Text>
                  <Tooltip title={mark.explain}>
                    <Tag color={mark.tone} data-testid={`mark-${row.name}`}>
                      {mark.label}
                    </Tag>
                  </Tooltip>
                </Space>
              )
            },
          },
          {
            title: 'Contents',
            key: 'contents',
            render: (_: unknown, row) => <Typography.Text>{contentsWords(row)}</Typography.Text>,
          },
          {
            title: 'Units',
            key: 'units',
            render: (_: unknown, row) =>
              row.units.state === 'missing' ? (
                <Pending label="units" cause={row.units.say ?? ''} fix="M2" studyId={view.id} />
              ) : (
                <Typography.Text type="secondary">
                  {row.units.state === 'not_needed' ? '—' : (row.units.say ?? NOT_RECORDED)}
                </Typography.Text>
              ),
          },
          {
            title: 'Findings',
            key: 'issues',
            render: (_: unknown, row) =>
              row.issues.length ? (
                <Tag data-testid={`findings-${row.name}`}>{row.issues.length}</Tag>
              ) : (
                <Typography.Text type="secondary">None</Typography.Text>
              ),
          },
        ]}
      />
    </Card>
  )
}

function FileDetail({ row, view }: { row: FileRow; view: FilesView }) {
  const items = [
    {
      key: 'detected',
      label: 'What the check read',
      children: (
        <Space orientation="vertical" size={0}>
          <Typography.Text>{row.classification.detected.say_full}</Typography.Text>
          <Typography.Text type="secondary">{row.classification.detected.say}</Typography.Text>
        </Space>
      ),
    },
  ]
  if (row.classification.stated) {
    items.push({
      key: 'stated',
      label: 'What a person said',
      children: (
        <Typography.Text>
          {row.classification.say} — stated {row.classification.stated.at}
        </Typography.Text>
      ),
    })
  }
  if (row.companions.length) {
    items.push({
      key: 'companions',
      label: 'What rides on it',
      children: (
        <ItemList
          items={row.companions}
          rowKey={(companion: Companion) => companion.name}
          render={(companion: Companion) => (
            <Typography.Text>
              <Typography.Text code>{companion.name}</Typography.Text> — {companion.say}
            </Typography.Text>
          )}
        />
      ),
    })
  }
  if (row.bm2) {
    items.push({
      key: 'experiments',
      label: 'Its experiments',
      children: <Typography.Text>{row.bm2.experiments.join(', ') || NOT_RECORDED}</Typography.Text>,
    })
  }
  const table = row.tables[0]
  if (table) {
    items.push({
      key: 'measurements',
      label: 'Its measurements',
      children: (
        <Typography.Text>
          {table.measurement_sample.join(', ')}
          {table.measurements > table.measurement_sample.length
            ? `, and ${table.measurements - table.measurement_sample.length} more`
            : ''}
        </Typography.Text>
      ),
    })
  }
  const found = view.issues.filter((one) => row.issues.includes(one.id))
  if (found.length) {
    items.push({
      key: 'found',
      label: 'What the check found',
      children: (
        <ItemList
          items={found}
          rowKey={(one: Finding) => one.id}
          render={(one: Finding) => <Typography.Text>{one.say}</Typography.Text>}
          dense
        />
      ),
    })
  }
  return <Descriptions size="small" column={1} bordered items={items} />
}

// ---------------------------------------------------------------------------
// The file check
// ---------------------------------------------------------------------------

function Check({
  view,
  lastCheck,
  onCheck,
}: {
  view: FilesView
  lastCheck: Record<string, unknown> | null
  onCheck: () => void
}) {
  const summary = checkSummary(view.check?.counts)
  const act = view.acts.check
  return (
    <Card
      size="small"
      title="The file check"
      data-testid="check"
      extra={
        act.allowed ? (
          <Button type="primary" onClick={onCheck} data-testid="check-run">
            {view.check === null ? CHECK_BUTTON : CHECK_AGAIN}
          </Button>
        ) : (
          <Tooltip title={act.say}>
            <Button disabled data-testid="check-run">
              {CHECK_BUTTON}
            </Button>
          </Tooltip>
        )
      }
    >
      {lastCheck && (
        <Alert
          type="success"
          showIcon
          style={{ marginBottom: 12 }}
          message={checkRanWords(lastCheck)}
          data-testid="check-ran"
        />
      )}
      {view.check === null ? (
        <Typography.Paragraph type="secondary" data-testid="check-not-run">
          {NOT_CHECKED} {CHECK_NOTE}
        </Typography.Paragraph>
      ) : (
        <Space orientation="vertical" size="small" style={{ display: 'flex' }}>
          <Typography.Text type="secondary">Checked {view.check.run_at}</Typography.Text>
          {!view.check.current && (
            <Alert
              type="warning"
              showIcon
              message={view.check.why_not_current}
              data-testid="check-stale"
            />
          )}
          <Alert type={summary.tone} showIcon message={summary.say} data-testid="check-summary" />
          {view.check.not_shown && (
            <Typography.Text type="secondary">{view.check.not_shown.say}</Typography.Text>
          )}
          <Findings issues={view.issues} />
        </Space>
      )}
    </Card>
  )
}

function Findings({ issues }: { issues: Finding[] }) {
  const groups = GROUPS.map((group) => ({
    ...group,
    found: issues.filter((one) => one.group === group.key),
  })).filter((group) => group.found.length)
  if (!groups.length) return null

  return (
    <Collapse
      size="small"
      defaultActiveKey={groups.filter((g) => g.key !== 'expected').map((g) => g.key)}
      data-testid="findings"
      items={groups.map((group) => ({
        key: group.key,
        label: `${group.title} (${group.found.length})`,
        children: (
          <Space orientation="vertical" size="small" style={{ display: 'flex' }}>
            <Typography.Text type="secondary">{group.explain}</Typography.Text>
            <ItemList
              items={group.found}
              rowKey={(one: Finding) => one.id}
              rowProps={(one: Finding) => ({ 'data-testid': `finding-${one.id}` })}
              render={(one: Finding) => <Found one={one} />}
            />
          </Space>
        ),
      }))}
    />
  )
}

function Found({ one }: { one: Finding }) {
  return (
    <Space orientation="vertical" size={2}>
      <Typography.Text>{one.say}</Typography.Text>
      {one.what_to_do && <Typography.Text strong>{one.what_to_do}</Typography.Text>}
      {one.settle === 'outside' && (
        <Typography.Text type="secondary">{SETTLED_OUTSIDE}</Typography.Text>
      )}
      {one.feeds === 'M6' && (
        <Typography.Text type="secondary">
          The data review accounts for these animals.
        </Typography.Text>
      )}
      {!one.known && (
        <Typography.Text type="secondary">
          This is a kind of finding the page has no words for; the check’s own message is shown.
        </Typography.Text>
      )}
    </Space>
  )
}

// ---------------------------------------------------------------------------
// What the report would be built from
// ---------------------------------------------------------------------------

function Coverage({ rows }: { rows: CoverageRow[] }) {
  if (!rows.length) return null
  return (
    <Card size="small" title={COVERAGE_TITLE} data-testid="coverage">
      <Typography.Paragraph type="secondary">{COVERAGE_EXPLAIN}</Typography.Paragraph>
      <Table<CoverageRow>
        aria-label={COVERAGE_TITLE}
        size="small"
        rowKey="key"
        dataSource={rows}
        pagination={false}
        scroll={{ x: true }}
        columns={[
          { title: 'Assay', dataIndex: 'assay' },
          { title: 'Kind of data', dataIndex: 'data_type_say' },
          {
            title: 'Workbook',
            dataIndex: 'workbook',
            render: (name: string | null) =>
              name ? <Typography.Text code>{name}</Typography.Text> : <Typography.Text type="secondary">None</Typography.Text>,
          },
          {
            title: 'Tables',
            dataIndex: 'tables',
            render: (names: string[]) =>
              names.length ? (
                <Space orientation="vertical" size={0}>
                  {names.map((name) => (
                    <Typography.Text code key={name}>
                      {name}
                    </Typography.Text>
                  ))}
                </Space>
              ) : (
                <Typography.Text type="secondary">None</Typography.Text>
              ),
          },
          {
            title: 'BMDExpress project',
            dataIndex: 'bm2',
            render: (name: string | null) =>
              name ? <Typography.Text code>{name}</Typography.Text> : <Typography.Text type="secondary">None</Typography.Text>,
          },
          {
            title: 'Status',
            key: 'level',
            render: (_: unknown, row) => (
              <Tooltip title={row.say}>
                <Tag color={coverageTone(row.level)}>{row.level === 'ok' ? 'Would be combined' : 'Nothing would be combined'}</Tag>
              </Tooltip>
            ),
          },
        ]}
      />
    </Card>
  )
}

// ---------------------------------------------------------------------------
// The acts, which are not built yet
// ---------------------------------------------------------------------------

function ActsNotBuilt({ view }: { view: FilesView }) {
  return (
    <Alert
      type="info"
      showIcon
      data-testid="acts-not-built"
      message="Saying what a file is, is not built on this page yet"
      description={
        <Space orientation="vertical" size={2}>
          <Typography.Text>
            Correcting what the check read a file as, confirming the files, removing one and
            starting the files over are done from the API page or the notebook for now. Bringing
            files in and checking them are done here.
          </Typography.Text>
          <Typography.Text type="secondary">
            The next step for this study is: {view.next.say}.
          </Typography.Text>
        </Space>
      }
    />
  )
}
