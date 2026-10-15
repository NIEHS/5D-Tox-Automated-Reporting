import { MenuOutlined } from '@ant-design/icons'
import { Alert, Button, Drawer, Grid, Layout, Menu, Spin } from 'antd'
import { useState } from 'react'
import { Link, Outlet, useParams } from 'react-router'
import { MODULES, moduleRoute, studyRoute } from '../kit/modules'
import { Refusal } from '../kit/Refusal'
import { useStudyState } from '../kit/useStudyState'
import { useVocabularies } from '../kit/useVocabularies'
import { RunInFlight } from '../kit/Wait'
import { NoSuchStudy } from '../modules/m1/NoSuchStudy'
import type { SessionKind } from '../api/types'
import { StudyHeader } from './StudyHeader'

const GROUP_TITLES = { data: 'The data', computation: 'Computing', document: 'The report' } as const

/**
 * Which groups of pages a kind of session has (M1 R1): published content is
 * read-only (no workflow page at all); a report over several studies has no
 * data of its own (its studies are prepared on their own pages).
 */
function groupsFor(kind: SessionKind | (string & {})): readonly ('data' | 'computation' | 'document')[] {
  if (kind === 'companion') return []
  if (kind === 'report') return ['document']
  return ['data', 'computation', 'document']
}

function StudyMenu({ studyId, kind, current, onPick }: { studyId: string; kind: string; current?: string; onPick?: () => void }) {
  const groups = groupsFor(kind).map((g) => ({
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
  // A study this page has seen, then reads as absent, was deleted while open (S5).
  const [seenId, setSeenId] = useState<string | null>(null)
  if (data?.exists && seenId !== id) setSeenId(id)

  if (malformed) return <NoSuchStudy id={id} reason="invalid" />
  if (vocab.isPending || isPending) {
    return (
      <Spin size="large" description="Reading the study">
        <div style={{ minHeight: 200 }} />
      </Spin>
    )
  }
  if (!data) {
    if (error?.code === 'invalid_study_id') return <NoSuchStudy id={id} reason="invalid" say={error.say} />
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
  if (!data.exists) return <NoSuchStudy id={id} reason={seenId === id ? 'deleted' : 'not_found'} />
  // A page a kind of session does not have (R1) is not offered, even by its address.
  const pageModule = module ? MODULES.find((m) => m.slug === module) : undefined
  const pageHidden = pageModule !== undefined && !groupsFor(data.kind).includes(pageModule.group)

  return (
    <Layout style={{ background: 'transparent' }}>
      {wide && (
        <Layout.Sider width={240} theme="light" style={{ marginRight: 16 }}>
          <StudyMenu studyId={id} kind={data.kind} current={module} />
        </Layout.Sider>
      )}
      <Layout.Content style={{ minWidth: 0 }}>
        {!wide && (
          <>
            <Button icon={<MenuOutlined />} style={{ marginBottom: 12 }} onClick={() => setMenuOpen(true)}>
              Pages of this study
            </Button>
            <Drawer open={menuOpen} onClose={() => setMenuOpen(false)} placement="left" title="Pages of this study" size={280}>
              <StudyMenu studyId={id} kind={data.kind} current={module} onPick={() => setMenuOpen(false)} />
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
        {/* the study's own page (M1's S3) has its own header */}
        {module && <StudyHeader state={data} />}
        {pageHidden ? (
          <Alert
            type="info"
            showIcon
            title={`${pageModule.title} is not offered here.`}
            description={
              data.kind === 'companion'
                ? "This is the published book's own content. It can't be changed here."
                : "A report over several studies has no data of its own: each study is prepared on its own page."
            }
            action={<Link to={studyRoute(id)}>Back to the study</Link>}
          />
        ) : (
          <Outlet />
        )}
      </Layout.Content>
      <RunInFlight studyId={id} />
    </Layout>
  )
}
