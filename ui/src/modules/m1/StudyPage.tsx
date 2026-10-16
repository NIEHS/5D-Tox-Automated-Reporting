import { ArrowRightOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { Alert, App, Button, Card, Descriptions, Skeleton, Space, Table, Tag, Typography } from 'antd'
import { Link, useNavigate, useParams } from 'react-router'
import { deleteStudy, getDeleteDryRun } from '../../api/m1'
import { isMissingMember, type ExistingStudyState, type MissingMember, type StudyDetail, type StudyRow } from '../../api/types'
import { ConfirmAct } from '../../kit/ConfirmAct'
import { formatClock } from '../../kit/elapsed'
import { moduleById, moduleRoute, studyRoute } from '../../kit/modules'
import { Pending } from '../../kit/Pending'
import { PhaseTag } from '../../kit/PhaseTag'
import { Refusal } from '../../kit/Refusal'
import { studyKey, useStudyState } from '../../kit/useStudyState'
import { StudyWorkflowPanels } from '../../shell/StudyOverview'
import { IdentityLookup } from './IdentityLookup'
import { NoSuchStudy } from './NoSuchStudy'
import { STUDIES_KEY, useStudyDetail } from './queries'
import { BookshelfLink, NextLink } from './StudiesList'
import { KIND_COLOURS, appPath, dayOf, formatSourceSay, formatUnreadSay, identitySourceSay, kindLabel } from './words'

/**
 * S3 Study page (M1 spec §3): the study's landing page. What it is, where it
 * stands and the next step, its chemical, its format, the Bookshelf, the
 * sessions it belongs with, and its delete. Then the workflow panels the
 * shell's overview had (steps, what to look at, what stops publishing, the
 * method). The row comes from GET /api/v2/studies/{id}; the workflow state
 * from the kit's useStudyState. Nothing here is derived in the browser.
 */

function BackendLink({ href, children }: { href: string; children: React.ReactNode }) {
  const p = appPath(href)
  return p.inApp ? (
    <Link to={p.to}>{children}</Link>
  ) : (
    <a href={p.to} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  )
}

function Header({ d, stands }: { d: StudyDetail; stands: StudyRow['stands'] }) {
  return (
    <Space orientation="vertical" size={4} style={{ width: '100%' }}>
      <Link to="/studies">← Studies</Link>
      <Space wrap align="baseline" size="middle">
        <Typography.Title level={2} style={{ margin: 0 }}>
          {d.identity.name ?? <Pending label="name" cause="The chemical's name is not on file." />}
        </Typography.Title>
        <Typography.Text code copyable aria-label="Study id">
          {d.id}
        </Typography.Text>
        <Tag color={KIND_COLOURS[d.kind] ?? 'red'} data-testid="kind">
          {kindLabel(d)}
        </Tag>
        <PhaseTag phase={stands.phase} say={stands.say} />
      </Space>
    </Space>
  )
}

function Banner({ d }: { d: StudyDetail }) {
  const b = d.detail.banner
  if (!b) return null
  return (
    <Alert
      data-testid="kind-banner"
      type={b.level === 'warning' ? 'warning' : 'info'}
      showIcon
      title={b.say}
      description={
        b.links.length > 0 ? (
          <Space wrap size="middle">
            {b.links.map((l) => (
              <BackendLink key={l.href} href={l.href}>
                {l.say}
              </BackendLink>
            ))}
          </Space>
        ) : undefined
      }
    />
  )
}

/** A member study whose folder is not in the store: said plainly, never opened. */
export const MISSING_MEMBER_SAY = "Missing: this study's folder is not in the store."

function MembersTable({ members }: { members: (StudyRow | MissingMember)[] }) {
  return (
    <Table<StudyRow | MissingMember>
      aria-label="The studies in this report"
      data-testid="members"
      size="small"
      rowKey="id"
      pagination={false}
      dataSource={members}
      columns={[
        { title: 'Study', key: 'id', render: (_, m) => <Typography.Text style={{ fontFamily: 'monospace' }}>{m.id}</Typography.Text> },
        {
          title: 'Where it stands',
          key: 'stands',
          render: (_, m) =>
            isMissingMember(m) ? (
              <Typography.Text type="danger" data-testid="member-missing">
                {MISSING_MEMBER_SAY}
              </Typography.Text>
            ) : (
              <Space orientation="vertical" size={2}>
                <PhaseTag phase={m.stands.phase} say={m.stands.say} />
                <NextLink s={m} />
              </Space>
            ),
        },
        {
          title: '',
          key: 'open',
          render: (_, m) =>
            isMissingMember(m) ? null : (
              <Link to={studyRoute(m.id)} aria-label={`Open ${m.id}`}>
                <Button size="small">Open</Button>
              </Link>
            ),
        },
      ]}
    />
  )
}

function WhereItStands({ d, stands, state }: { d: StudyDetail; stands: StudyRow['stands']; state: ExistingStudyState | null }) {
  const next = stands.next
  const m = moduleById(next?.fix)
  // a report's next step (its members) is on this page
  const to = m && m.id !== 'M1' ? moduleRoute(m.id, d.id) : undefined
  const run = state?.run
  return (
    <Card title="Where it stands" size="small" data-testid="where-it-stands">
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Typography.Text>{stands.say}</Typography.Text>
        {run?.in_flight ? (
          <Typography.Text strong data-testid="run-in-flight">
            Process is running on this study{formatClock(run.started_at) ? ` since ${formatClock(run.started_at)}` : ''}.
          </Typography.Text>
        ) : next ? (
          to ? (
            <Link to={to}>
              <Button type="primary" icon={<ArrowRightOutlined />} iconPlacement="end">
                {next.say}
              </Button>
            </Link>
          ) : (
            <Typography.Text>
              <Typography.Text strong>Next: </Typography.Text>
              {next.say}
            </Typography.Text>
          )
        ) : null}
        {d.kind === 'report' && d.detail.members && <MembersTable members={d.detail.members} />}
      </Space>
    </Card>
  )
}

function ChemicalCard({ d, state }: { d: StudyDetail; state: ExistingStudyState | null }) {
  const id = d.identity
  // The short name is a stated fact; the state's identity is the one the report uses.
  const shortName = state?.identity?.short_name ?? id.short_name
  const canLookUp = !id.name && (d.kind === 'study' || d.kind === 'other')
  return (
    <Card title="The chemical" size="small" data-testid="chemical">
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Descriptions size="small" column={1}>
          <Descriptions.Item label="Name">
            {id.name ?? <Pending label="name" cause="The chemical's name is not on file. Look the chemical up below." />}
          </Descriptions.Item>
          <Descriptions.Item label="CASRN">
            {id.casrn ?? (
              <Pending
                label="CASRN"
                cause={
                  canLookUp
                    ? "The chemical's CAS number is not on file. Look the chemical up below."
                    : 'The CAS number is not on file: the lookup gave none, and none was typed when the identity was confirmed. Adding it to an identity on file is not offered on this page.'
                }
              />
            )}
          </Descriptions.Item>
          <Descriptions.Item label="DTXSID">
            {d.chemical_dtxsid ? (
              <Space size={6} wrap>
                <Typography.Text style={{ fontFamily: 'monospace' }}>{d.chemical_dtxsid}</Typography.Text>
                {d.chemical_dtxsid_from === 'id_prefix' && <Typography.Text type="secondary">taken from the session id</Typography.Text>}
              </Space>
            ) : (
              <Typography.Text type="secondary">This session's id names no chemical.</Typography.Text>
            )}
          </Descriptions.Item>
          <Descriptions.Item label="Short name">
            {shortName ?? (
              <Pending
                label="short name"
                cause="The short name (abbreviation) used in the report is not stated yet."
                fix={d.kind === 'companion' || d.kind === 'report' ? null : 'M4'}
                studyId={d.id}
              />
            )}
          </Descriptions.Item>
        </Descriptions>
        <Typography.Text type="secondary" data-testid="identity-source">
          {identitySourceSay(id.source)}
        </Typography.Text>
        {canLookUp &&
          (d.chemical_dtxsid ? (
            <IdentityLookup studyId={d.id} dtxsid={d.chemical_dtxsid} />
          ) : (
            <Typography.Text type="secondary">
              The chemical can't be looked up from here: this session's id names no chemical.
            </Typography.Text>
          ))}
      </Space>
    </Card>
  )
}

function FormatCard({ d, state }: { d: StudyDetail; state: ExistingStudyState | null }) {
  const f = d.detail.format
  if (!f) {
    // the backend could not read the format (a damaged file): say so, never guess one
    return (
      <Card title="Report format" size="small" data-testid="format-card">
        <Space orientation="vertical" size="small" style={{ width: '100%' }}>
          <Pending label="format" cause={formatUnreadSay(d)} />
          <Typography.Text type="secondary" data-testid="format-unread">
            The report format could not be read, so none is shown. The warning at the top of the page says why.
          </Typography.Text>
        </Space>
      </Card>
    )
  }
  const pin = state?.pins.definition
  const m5 = moduleById('M5')
  const m5To = moduleRoute('M5', d.id)
  let pinSay: string
  if (pin?.error) pinSay = pin.error.say
  else if (pin?.pinned && pin.mode === 'fixed') pinSay = `Fixed${dayOf(pin.pinned_at) ? ` on ${dayOf(pin.pinned_at)}` : ''}.`
  else if (pin?.pinned) pinSay = 'Tracks the current definition.'
  else if (f.pin?.mode === 'fixed') pinSay = `Fixed${dayOf(f.pin.pinned_at) ? ` on ${dayOf(f.pin.pinned_at)}` : ''}.`
  else if (f.pin?.mode === 'track') pinSay = 'Tracks the current definition.'
  else pinSay = 'Not pinned yet: it follows the definition files.'
  return (
    <Card title="Report format" size="small" data-testid="format-card">
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Typography.Text strong>{f.title}</Typography.Text>
        <Typography.Text>{f.say}</Typography.Text>
        <Typography.Text type="secondary">{formatSourceSay(f)}</Typography.Text>
        <Space size={6} wrap data-testid="format-pin">
          <Typography.Text>{pinSay}</Typography.Text>
          {d.kind !== 'companion' && m5 && m5To && <Link to={m5To}>{m5.title}</Link>}
        </Space>
        {f.brings.length > 0 && (
          <div>
            <Typography.Text>The id also brings:</Typography.Text>
            <ul style={{ margin: '4px 0 0', paddingInlineStart: 20 }}>
              {f.brings.map((b) => (
                <li key={b.what + b.path}>{b.say}</li>
              ))}
            </ul>
          </div>
        )}
      </Space>
    </Card>
  )
}

const RELATION_WORDS = {
  parent: 'The report it is part of',
  members: 'A study of this report',
  companion: "The published book's content",
  twin: 'The generated study',
  others: 'Another session of this chemical',
} as const

function RelatedCard({ d }: { d: StudyDetail }) {
  const r = d.relations
  const items: { id: string; role: keyof typeof RELATION_WORDS; extra?: string }[] = [
    ...(r.parent ? [{ id: r.parent, role: 'parent' as const }] : []),
    ...r.members.map((m) => ({ id: m.id, role: 'members' as const, extra: m.key })),
    ...(r.companion ? [{ id: r.companion, role: 'companion' as const }] : []),
    ...(r.twin ? [{ id: r.twin, role: 'twin' as const }] : []),
    ...r.others.map((o) => ({ id: o, role: 'others' as const })),
  ]
  return (
    <Card title="Related sessions" size="small" data-testid="related">
      {items.length === 0 ? (
        <Typography.Text type="secondary">None.</Typography.Text>
      ) : (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {items.map((it) => (
            <li key={`${it.role}:${it.id}`} style={{ padding: '4px 0' }}>
              <Space wrap>
                <Tag>
                  {RELATION_WORDS[it.role]}
                  {it.extra ? ` (${it.extra})` : ''}
                </Tag>
                <Typography.Text style={{ fontFamily: 'monospace' }}>{it.id}</Typography.Text>
                <Link to={studyRoute(it.id)} aria-label={`Open ${it.id}`}>
                  <Button size="small">Open</Button>
                </Link>
              </Space>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function DeleteCard({ d }: { d: StudyDetail }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { message } = App.useApp()
  const del = d.actions.delete
  return (
    <Card title="Delete this study" size="small" style={{ borderColor: '#ff4d4f' }} data-testid="delete-card">
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Typography.Text type="secondary">
          Deleting removes the study and everything in it for good. It can't be undone.
        </Typography.Text>
        <ConfirmAct
          studyId={d.id}
          act="delete_study"
          label="Delete this study…"
          dialogTitle={`Delete ${d.id} for good?`}
          confirmLabel="Delete for good"
          buttonProps={{ danger: true }}
          disabled={!del.allowed}
          disabledReason={del.say ?? 'The application does not allow deleting this session now.'}
          loadDryRun={(signal) => getDeleteDryRun(d.id, signal)}
          perform={async ({ typedId, previewToken }) => {
            const r = await deleteStudy(d.id, typedId ?? '', previewToken ?? '')
            void navigate('/studies')
            void message.success(r.say)
            qc.removeQueries({ queryKey: studyKey(d.id) })
            await qc.invalidateQueries({ queryKey: STUDIES_KEY })
            return r
          }}
        />
      </Space>
    </Card>
  )
}

export function StudyPage() {
  const { id = '' } = useParams()
  const detail = useStudyDetail(id)
  const { data: stateData } = useStudyState(id)
  const state = stateData?.exists ? stateData : null

  if (detail.isPending) return <Skeleton active paragraph={{ rows: 10 }} />
  if (detail.error) {
    // a study this page had shown (its earlier read is kept) and now reads as absent was deleted while open (S5)
    if (detail.error.code === 'study_not_found') return <NoSuchStudy id={id} reason={detail.data?.id === id ? 'deleted' : 'not_found'} />
    if (detail.error.code === 'invalid_study_id') return <NoSuchStudy id={id} reason="invalid" say={detail.error.say} />
    return (
      <Refusal
        error={detail.error}
        studyId={id}
        title="The study could not be read"
        action={
          <Button onClick={() => void detail.refetch()} loading={detail.isFetching}>
            Try again
          </Button>
        }
      />
    )
  }
  const d = detail.data
  // R2: the state will serve `stands`; until then the row's, from the same backend function.
  const stands = state?.stands ?? d.stands

  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      <Header d={d} stands={stands} />
      <Banner d={d} />
      {d.notes.length > 0 && (
        <Alert
          type={d.notes.some((n) => n.level === 'error') ? 'error' : 'warning'}
          showIcon
          title={d.notes.map((n) => n.say).join(' ')}
        />
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16 }}>
        <WhereItStands d={d} stands={stands} state={state} />
        <ChemicalCard d={d} state={state} />
        <FormatCard d={d} state={state} />
        <Card title="Bookshelf" size="small" data-testid="bookshelf">
          <BookshelfLink s={d} />
        </Card>
        <RelatedCard d={d} />
      </div>
      {state && <StudyWorkflowPanels state={state} />}
      <DeleteCard d={d} />
    </Space>
  )
}
