import { Grid, Layout, Typography } from 'antd'
import { Link, Outlet } from 'react-router'

/** The app's frame: a header and the page. The app's real name is still to be chosen (HANDOFF §2). */
export function AppFrame() {
  const pad = Grid.useBreakpoint().md === false ? 12 : 24
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header style={{ paddingInline: pad, display: 'flex', alignItems: 'center', gap: 24, background: '#fff', borderBottom: '1px solid #f0f0f0' }}>
        <Link to="/studies">
          <Typography.Title level={4} style={{ margin: 0 }}>
            Potency reports
          </Typography.Title>
        </Link>
        <Link to="/studies">Studies</Link>
      </Layout.Header>
      <Layout.Content style={{ padding: pad }}>
        <Outlet />
      </Layout.Content>
    </Layout>
  )
}
