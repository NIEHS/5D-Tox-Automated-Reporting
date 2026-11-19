import { ArrowRightOutlined, BookOutlined, ExperimentOutlined, ReadOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Col, Row, Skeleton, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router'
import type { StudiesList, StudyRow } from '../../api/types'
import { MODULES, studyRoute, type ModuleInfo } from '../../kit/modules'
import { isBuilt } from '../../shell/modulePages'
import { useOnlyPartition } from '../m1/onlyPartition'
import { useStudies } from '../m1/queries'
import { ROLE_WORDS } from '../m1/words'
import { API_PAGE, BOOKSHELF, GROUPS, LEDE, NOTEBOOK, TITLE } from './words'

/**
 * The first page (/): what the application is for, where to go, the studies
 * that are set apart (the Demo pair), where the studies stand, and the steps
 * of a report in order. A first version, for the maintainer to cut or grow.
 */

function everySession(list: StudiesList, only: string | null): StudyRow[] {
  const set: StudyRow[] = []
  for (const p of list.partitions ?? []) {
    if (only !== null && p.name !== only) continue
    for (const e of p.sessions) {
      if (e.session) set.push(e.session)
      set.push(...e.members)
    }
  }
  if (only !== null) return set
  return [...set, ...list.chemicals.flatMap((c) => c.sessions), ...list.unassigned]
}

/** How many studies stand at each stage, in the words the backend serves. */
function byStage(sessions: StudyRow[]): { say: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const s of sessions) {
    // A report over several studies has no stage of its own: its studies have.
    if (s.kind === 'report') continue
    counts.set(s.stands.say, (counts.get(s.stands.say) ?? 0) + 1)
  }
  return [...counts].map(([say, count]) => ({ say, count })).sort((a, b) => b.count - a.count)
}

function WhereToGo() {
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} md={8}>
        <Card title={<Space><ExperimentOutlined />Studies</Space>} style={{ height: '100%' }}>
          <Typography.Paragraph>Open a study and take it through its steps, or start a new one.</Typography.Paragraph>
          <Link to="/studies">
            <Button type="primary" icon={<ArrowRightOutlined />} iconPlacement="end">
              Go to the studies
            </Button>
          </Link>
        </Card>
      </Col>
      <Col xs={24} md={8}>
        <Card title={<Space><BookOutlined />Bookshelf</Space>} style={{ height: '100%' }}>
          <Typography.Paragraph>{BOOKSHELF}</Typography.Paragraph>
          <Button href="/Bookshelf" icon={<ArrowRightOutlined />} iconPlacement="end">
            Open the Bookshelf
          </Button>
        </Card>
      </Col>
      <Col xs={24} md={8}>
        <Card title={<Space><ReadOutlined />What happens at each step</Space>} style={{ height: '100%' }}>
          <Typography.Paragraph>{API_PAGE}</Typography.Paragraph>
          <Button href="/docs" icon={<ArrowRightOutlined />} iconPlacement="end">
            Open the API page
          </Button>
          <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
            {NOTEBOOK}
          </Typography.Paragraph>
        </Card>
      </Col>
    </Row>
  )
}

function SetApart({ list, only }: { list: StudiesList; only: string | null }) {
  const partitions = (list.partitions ?? []).filter((p) => only === null || p.name === only)
  if (partitions.length === 0) return null
  return (
    <>
      {partitions.map((p) => (
        <Card key={p.name} size="small" title={`Set apart: ${p.name}`} data-testid={`home-partition-${p.name}`}>
          <Space orientation="vertical" size="small">
            {p.sessions.map((e) => {
              const role = e.role ? ROLE_WORDS[e.role] : undefined
              return (
                <Space key={e.id} wrap>
                  {role && <Tag color={role.color}>{role.label}</Tag>}
                  {e.session ? (
                    <Link to={studyRoute(e.id)}>{e.session.identity.name ?? e.id}</Link>
                  ) : (
                    <Typography.Text type="secondary">{e.id} (not there)</Typography.Text>
                  )}
                  <Typography.Text type="secondary" code>
                    {e.id}
                  </Typography.Text>
                  {role && <Typography.Text type="secondary">{role.say}</Typography.Text>}
                </Space>
              )
            })}
          </Space>
        </Card>
      ))}
    </>
  )
}

function Standing({ list, only }: { list: StudiesList; only: string | null }) {
  const stages = byStage(everySession(list, only))
  const total = stages.reduce((n, s) => n + s.count, 0)
  return (
    <Card size="small" title="Where the studies stand" data-testid="home-standing">
      {total === 0 ? (
        <Typography.Text type="secondary">There is no study yet.</Typography.Text>
      ) : (
        <Space orientation="vertical" size={4}>
          {stages.map((s) => (
            <Space key={s.say}>
              <Typography.Text strong style={{ display: 'inline-block', minWidth: 28, textAlign: 'right' }}>
                {s.count}
              </Typography.Text>
              <Typography.Text>{s.say}</Typography.Text>
            </Space>
          ))}
          {only !== null && (
            <Typography.Text type="secondary">Only the studies of “{only}” are counted, as on the studies list.</Typography.Text>
          )}
        </Space>
      )}
    </Card>
  )
}

function Step({ m }: { m: ModuleInfo }) {
  return (
    <li style={{ marginBottom: 8 }}>
      <Typography.Text strong>{m.title}</Typography.Text>
      {!isBuilt(m.slug) && (
        <Tag style={{ marginInlineStart: 8 }} data-testid={`home-not-built-${m.slug}`}>
          page not built yet
        </Tag>
      )}
      <div>
        <Typography.Text type="secondary">{m.purpose}</Typography.Text>
      </div>
    </li>
  )
}

function Steps() {
  return (
    <Card title="The steps of a report, in order" data-testid="home-steps">
      <Typography.Paragraph type="secondary">Each step is a page of a study. The software checks a step before it runs, and says why when it refuses.</Typography.Paragraph>
      <Row gutter={[24, 16]}>
        {GROUPS.map((g) => (
          <Col xs={24} md={8} key={g.group}>
            <Typography.Title level={5}>{g.title}</Typography.Title>
            <ol style={{ paddingInlineStart: 20, margin: 0 }}>
              {MODULES.filter((m) => m.group === g.group && m.slug).map((m) => (
                <Step key={m.id} m={m} />
              ))}
            </ol>
          </Col>
        ))}
      </Row>
    </Card>
  )
}

export function Landing() {
  const studies = useStudies()
  const only = useOnlyPartition()
  return (
    <Space orientation="vertical" size="large" style={{ width: '100%', maxWidth: 1200, margin: '0 auto', display: 'flex' }} data-testid="home">
      <div>
        <Typography.Title level={2} style={{ marginBottom: 8 }}>
          {TITLE}
        </Typography.Title>
        <Typography.Paragraph style={{ fontSize: 16, maxWidth: 820, marginBottom: 0 }}>{LEDE}</Typography.Paragraph>
      </div>
      <WhereToGo />
      {studies.isPending ? (
        <Skeleton active paragraph={{ rows: 2 }} />
      ) : studies.data ? (
        <Row gutter={[16, 16]}>
          <Col xs={24} md={14}>
            <SetApart list={studies.data} only={only} />
          </Col>
          <Col xs={24} md={(studies.data.partitions ?? []).length > 0 ? 10 : 24}>
            <Standing list={studies.data} only={only} />
          </Col>
        </Row>
      ) : (
        <Alert type="warning" showIcon title="The studies could not be read" description={studies.error?.say ?? 'The application did not say why.'} />
      )}
      <Steps />
    </Space>
  )
}
