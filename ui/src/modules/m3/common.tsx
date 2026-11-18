import { Alert, Space, Table, Typography } from 'antd'
import { Link } from 'react-router'
import type { ExistingStudyState, MemberStudy } from '../../api/types'
import { moduleBySlug } from '../../kit/modules'
import { PhaseTag } from '../../kit/PhaseTag'
import { phaseWords } from '../../kit/words'

/**
 * Pieces the demo path's data pages share (Combined data, Process): the
 * choice of a report's studies, the notice on the finished side of a
 * demonstration pair, and the link to the step on the API page.
 */

function pagePath(studyId: string, slug: string): string {
  return `/studies/${encodeURIComponent(studyId)}/${slug}`
}

/**
 * A report over several studies has no data of its own: the page works on
 * one of its studies, chosen here. The studies and where each stands are the
 * backend's (state.members).
 */
export function StudyChoice({ state, slug }: { state: ExistingStudyState; slug: string }) {
  const page = moduleBySlug(slug)
  const members = state.members ?? []
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }} data-testid="study-choice">
      <Alert
        type="info"
        showIcon
        title={`${page?.title ?? 'This page'} works on one study at a time.`}
        description="This report covers several studies and has no data of its own. Choose the study to open."
      />
      <Table<MemberStudy>
        aria-label="The studies in this report"
        size="small"
        rowKey="id"
        pagination={false}
        dataSource={members}
        columns={[
          { title: 'Study', key: 'key', render: (_, m) => <Typography.Text strong>{m.key}</Typography.Text> },
          { title: 'Id', key: 'id', render: (_, m) => <Typography.Text code>{m.id}</Typography.Text> },
          {
            title: 'Where it stands',
            key: 'stands',
            render: (_, m) =>
              !m.exists ? (
                <Typography.Text type="danger">Missing: this study is not in the store.</Typography.Text>
              ) : (
                <Space size="small" wrap>
                  <PhaseTag phase={m.phase ?? ''} say={phaseWords(m.phase ?? '').label} />
                  <Typography.Text type="secondary">{m.processed ? 'Analysis run' : 'Analysis not run yet'}</Typography.Text>
                </Space>
              ),
          },
          {
            title: '',
            key: 'open',
            render: (_, m) =>
              m.exists ? (
                <Link to={pagePath(m.id, slug)} aria-label={`Open ${page?.title ?? 'the page'} of the ${m.key} study`}>
                  Open {page?.title ?? 'the page'}
                </Link>
              ) : null,
          },
        ]}
      />
    </Space>
  )
}

/**
 * The finished side of a pair offers no act: what `act` names is done on the
 * live copy, on the same page.
 */
export function FinishedNotice({ state, slug, act }: { state: ExistingStudyState; slug: string; act: string }) {
  const pair = state.demo
  if (!pair || pair.role !== 'finished') return null
  return (
    <Alert
      type="info"
      showIcon
      data-testid="finished-notice"
      title="This is the finished report, kept as it is for comparison."
      description={
        <Space orientation="vertical" size={4}>
          <Typography.Text>{act} is done on its live copy; this page only shows what was done here.</Typography.Text>
          {pair.counterpart_exists ? (
            <Link to={pagePath(pair.counterpart, slug)}>Open this page of the live copy ({pair.counterpart})</Link>
          ) : (
            <Typography.Text type="secondary">The live copy ({pair.counterpart}) is not in the store now.</Typography.Text>
          )}
        </Space>
      }
    />
  )
}

/** The link to the step's group on the API page (/docs), outside the app. */
export function ApiPageLink({ group }: { group: string }) {
  return (
    <Typography.Text type="secondary">
      <a href="/docs" target="_blank" rel="noopener noreferrer">
        This step on the API page
      </a>{' '}
      (the group “{group}”): what each action reads and writes, and where its code is.
    </Typography.Text>
  )
}
