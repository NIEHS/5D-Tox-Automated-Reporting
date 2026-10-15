import { MenuOutlined } from '@ant-design/icons'
import { Alert, Button, Drawer, Grid, Layout, Menu, Result, Space, Spin, Typography } from 'antd'
import { useState } from 'react'
import { Link, Outlet, useParams } from 'react-router'
import { MODULES, moduleRoute, studyRoute } from '../kit/modules'
import { Refusal } from '../kit/Refusal'
import { useStudyState } from '../kit/useStudyState'
import { useVocabularies } from '../kit/useVocabularies'
import { RunInFlight } from '../kit/Wait'
import { StudyHeader } from './StudyHeader'

const GROUP_TITLES = { data: 'The data', computation: 'Computing', document: 'The report' } as const

function StudyMenu({ studyId, current, onPick }: { studyId: string; current?: string; onPick?: () => void }) {
  const groups = (['data', 'computation', 'document'] as const).map((g) => ({
    type: 'group' as const,
    key: g,
    label: GROUP_TITLES[g],
    children: MODULES.filter((m) => m.group === g && m.id !== 'M1').map((m) => ({
      key: m.slug,
      label: <Link to={moduleRoute(m.id, studyId) ?? studyRoute(studyId)}>{m.title}</Link>,
    })),
  }))
  return (
    <Menu
      mode="inline"
      selectedKeys={[current ?? 'overview']}
      items={[{ key: 'overview', label: <Link to={studyRoute(studyId)}>Overview</Link> }, ...groups]}
      style={{ height: '100%', borderInlineEnd: 0 }}
      onClick={onPick}
    />
  )
}

/** The frame around every study page: the menu, the header, the "already running" wait. */
export function StudyFrame() {
  const { id = '', module } = useParams()
  // An id the backend's own session-id rule (served with the vocabularies)
  // refuses is never sent: the person is told at once, in the backend's words.
  // If the rule cannot be loaded, the backend is asked and decides.
  const vocab = useVocabularies()
  const rule = vocab.data?.patterns.session_id
  const malformed = rule ? !new RegExp(rule.pattern).test(id) : false
  const { data, error, isPending, refetch, isFetching } = useStudyState(vocab.isPending || malformed ? undefined : id)
  // a side menu on a wide window; behind a button on a narrow one
  const wide = Grid.useBreakpoint().lg !== false
  const [menuOpen, setMenuOpen] = useState(false)

  if (malformed) {
    return (
      <Result
        status="warning"
        title="This is not a study id"
        subTitle={
          <Space orientation="vertical" size={2}>
            <Typography.Text code>{id}</Typography.Text>
            <Typography.Text>{vocab.data?.patterns.study_id?.say ?? rule?.say}</Typography.Text>
          </Space>
        }
        extra={<Link to="/studies">Go to the studies</Link>}
      />
    )
  }
  if (vocab.isPending || isPending) {
    return (
      <Spin size="large" description="Reading the study">
        <div style={{ minHeight: 200 }} />
      </Spin>
    )
  }
  if (!data) {
    return (
      <Refusal
        error={error}
        studyId={id}
        title={error?.code === 'invalid_study_id' ? 'This is not a study id' : 'The study could not be read'}
        action={
          <Button onClick={() => void refetch()} loading={isFetching}>
            Try again
          </Button>
        }
      />
    )
  }
  if (!data.exists) {
    return (
      <Result
        status="404"
        title="There is no study with this id"
        subTitle={<Typography.Text code>{id}</Typography.Text>}
        extra={<Link to="/studies">Go to the studies</Link>}
      />
    )
  }

  return (
    <Layout style={{ background: 'transparent' }}>
      {wide && (
        <Layout.Sider width={240} theme="light" style={{ marginRight: 16 }}>
          <StudyMenu studyId={id} current={module} />
        </Layout.Sider>
      )}
      <Layout.Content style={{ minWidth: 0 }}>
        {!wide && (
          <>
            <Button icon={<MenuOutlined />} style={{ marginBottom: 12 }} onClick={() => setMenuOpen(true)}>
              Pages of this study
            </Button>
            <Drawer open={menuOpen} onClose={() => setMenuOpen(false)} placement="left" title="Pages of this study" size={280}>
              <StudyMenu studyId={id} current={module} onPick={() => setMenuOpen(false)} />
            </Drawer>
          </>
        )}
        {error && (
          <Alert
            style={{ marginBottom: 16 }}
            type="warning"
            showIcon
            title="The study could not be read again; what is shown may be out of date."
            description={error.say}
            action={
              <Button size="small" onClick={() => void refetch()} loading={isFetching}>
                Try again
              </Button>
            }
          />
        )}
        <StudyHeader state={data} />
        <Outlet />
      </Layout.Content>
      <RunInFlight studyId={id} />
    </Layout>
  )
}
