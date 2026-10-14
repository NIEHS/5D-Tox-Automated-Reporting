import { MenuOutlined } from '@ant-design/icons'
import { Alert, Button, Drawer, Grid, Layout, Menu, Result, Spin } from 'antd'
import { useState } from 'react'
import { Link, Outlet, useParams } from 'react-router'
import { MODULES, moduleRoute, studyRoute } from '../kit/modules'
import { Refusal } from '../kit/Refusal'
import { useStudyState } from '../kit/useStudyState'
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
  const { data, error, isPending, refetch, isFetching } = useStudyState(id)
  // a side menu on a wide window; behind a button on a narrow one
  const wide = Grid.useBreakpoint().lg !== false
  const [menuOpen, setMenuOpen] = useState(false)

  if (isPending) {
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
        title="The study could not be read"
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
        subTitle={id}
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
