import { ExportOutlined, PlusOutlined, WarningFilled } from '@ant-design/icons'
import { Button, Empty, Input, Popover, Skeleton, Space, Table, Tag, Tooltip, Typography, type TableColumnsType } from 'antd'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import type { StudyRow } from '../../api/types'
import { moduleById, moduleRoute, studyRoute } from '../../kit/modules'
import { Pending } from '../../kit/Pending'
import { PhaseTag } from '../../kit/PhaseTag'
import { Refusal } from '../../kit/Refusal'
import { useStudies } from './queries'
import { UNASSIGNED_KEY, buildRows, searchRows, type ListRow } from './rows'
import { KIND_COLOURS, childCount, exactTime, kindLabel, publishedLabel, relativeTime } from './words'

/**
 * S1 Studies list (M1 spec §3). One top-level row per chemical, in the
 * backend's order and grouping; the chemical's other sessions as child rows.
 * Every value about a session (its kind, where it stands, the next step, its
 * format, the Bookshelf) is the backend's. There is no delete here.
 */

function ChemicalCell({ r }: { r: ListRow }) {
  if (r.key === UNASSIGNED_KEY) return <Typography.Text strong>Sessions not tied to a chemical</Typography.Text>
  const isTop = r.key.startsWith('chem:')
  // a child row of a chemical repeats nothing; one with no chemical shows its own identity
  if (!isTop && r.group) return null
  const name = isTop ? r.group?.name : r.row?.identity.name
  const casrn = isTop ? r.group?.casrn : r.row?.identity.casrn
  const dtxsid = isTop ? r.group?.dtxsid : null
  const openId = r.row?.id ?? r.group?.primary ?? null
  const fill = openId ? studyRoute(openId) : undefined
  return (
    <Space orientation="vertical" size={0}>
      {name ? (
        <Typography.Text strong>{name}</Typography.Text>
      ) : (
        <Pending label="name" cause="The chemical's name is not on file." to={fill} toLabel="Open the study to look the chemical up" />
      )}
      <Typography.Text type="secondary" style={{ fontFamily: 'monospace', fontSize: 12 }}>
        {dtxsid ? <>{dtxsid} · </> : null}
        {casrn ?? (
          <Pending label="CASRN" cause="The chemical's CAS number is not on file." to={fill} toLabel="Open the study to look the chemical up" />
        )}
      </Typography.Text>
    </Space>
  )
}

function SessionCell({ r, expanded }: { r: ListRow; expanded: boolean }) {
  const count = !expanded && r.children ? childCount(r.children.map((c) => c.row!).filter(Boolean)) : ''
  if (!r.row) {
    if (r.key === UNASSIGNED_KEY) return <Typography.Text type="secondary">{count}</Typography.Text>
    return (
      <Space orientation="vertical" size={2}>
        <Typography.Text>No study of this chemical yet</Typography.Text>
        {r.group?.can_create && (
          <Link to={`/studies/new?dtxsid=${encodeURIComponent(r.group.dtxsid)}`}>
            <Button size="small" icon={<PlusOutlined />}>
              Create a study
            </Button>
          </Link>
        )}
        {count && <Typography.Text type="secondary">{count}</Typography.Text>}
      </Space>
    )
  }
  const s = r.row
  return (
    <Space orientation="vertical" size={2}>
      <Space size={4} wrap>
        <Tag color={KIND_COLOURS[s.kind] ?? 'red'} data-testid="kind">
          {kindLabel(s, r.memberKey)}
        </Tag>
        {s.notes.length > 0 && (
          <Tooltip title={s.notes.map((n) => n.say).join(' ')}>
            <WarningFilled
              aria-label={`Note: ${s.notes.map((n) => n.say).join(' ')}`}
              style={{ color: s.notes.some((n) => n.level === 'error') ? '#ff4d4f' : '#faad14' }}
            />
          </Tooltip>
        )}
      </Space>
      <Typography.Text style={{ fontFamily: 'monospace', fontSize: 12 }}>{s.id}</Typography.Text>
      {count && <Typography.Text type="secondary">{count}</Typography.Text>}
    </Space>
  )
}

function FormatCell({ s }: { s: StudyRow }) {
  const pub = s.published ? publishedLabel(s.published) : null
  return (
    <Popover content={<Typography.Paragraph style={{ maxWidth: 360, margin: 0 }}>{s.format.say}</Typography.Paragraph>} title={s.format.title}>
      <Space size={4} wrap style={{ cursor: 'help' }} data-testid="format">
        <Tag>{s.format.title_short}</Tag>
        {pub && (
          <Tag color="gold">
            {pub.report} · {pub.when ?? '[publication date pending]'}
          </Tag>
        )}
      </Space>
    </Popover>
  )
}

/** "Next:" links to the module the backend names; a report's members are on its own page. */
export function NextLink({ s }: { s: StudyRow }) {
  const next = s.stands.next
  if (!next) return null
  const m = moduleById(next.fix)
  const to = !m ? undefined : m.id === 'M1' ? studyRoute(s.id) : moduleRoute(m.id, s.id)
  return (
    <Typography.Text style={{ fontSize: 13 }}>
      Next: {to ? <Link to={to}>{next.say}</Link> : next.say}
    </Typography.Text>
  )
}

function StandsCell({ s }: { s: StudyRow }) {
  return (
    <Space orientation="vertical" size={2} data-testid="stands">
      <PhaseTag phase={s.stands.phase} say={s.stands.say} />
      <NextLink s={s} />
    </Space>
  )
}

export function BookshelfLink({ s }: { s: StudyRow }) {
  const b = s.bookshelf
  if (b.on_shelf && b.url) {
    return (
      <a href={b.url} target="_blank" rel="noopener noreferrer">
        {b.say} <ExportOutlined aria-label="opens in a new tab" />
      </a>
    )
  }
  if (b.url) {
    return (
      <Typography.Text type="secondary">
        <a href={b.url} target="_blank" rel="noopener noreferrer">
          {b.say}
        </a>
      </Typography.Text>
    )
  }
  return <Typography.Text type="secondary">{b.say}</Typography.Text>
}

export function StudiesList() {
  const { data, error, isPending } = useStudies()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState<readonly React.Key[]>([])

  const all = useMemo(() => (data ? buildRows(data) : []), [data])
  const { rows, expand } = useMemo(() => searchRows(all, query), [all, query])
  const expandedKeys = useMemo(() => [...new Set([...expanded, ...expand])], [expanded, expand])

  const columns: TableColumnsType<ListRow> = [
    {
      title: 'Chemical',
      key: 'chemical',
      sorter: (a, b) => (a.group?.name ?? '￿').localeCompare(b.group?.name ?? '￿'),
      render: (_, r) => <ChemicalCell r={r} />,
    },
    { title: 'Session', key: 'session', render: (_, r) => <SessionCell r={r} expanded={expandedKeys.includes(r.key)} /> },
    { title: 'Report format', key: 'format', width: 220, render: (_, r) => (r.row ? <FormatCell s={r.row} /> : null) },
    { title: 'Where it stands', key: 'stands', width: 250, render: (_, r) => (r.row ? <StandsCell s={r.row} /> : null) },
    {
      title: 'Last changed',
      key: 'changed',
      render: (_, r) => {
        if (!r.row) return null
        const rel = relativeTime(r.row.last_changed)
        return rel ? (
          <Tooltip title={exactTime(r.row.last_changed)}>
            <span>{rel}</span>
          </Tooltip>
        ) : (
          <Typography.Text type="secondary">not known</Typography.Text>
        )
      },
    },
    { title: 'Bookshelf', key: 'bookshelf', width: 170, render: (_, r) => (r.row ? <BookshelfLink s={r.row} /> : null) },
    {
      title: <span style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>Open</span>,
      key: 'open',
      render: (_, r) => {
        if (!r.row) return null
        const open = r.row.actions.open
        return open.allowed ? (
          <Link to={studyRoute(r.row.id)} aria-label={`Open ${r.row.id}`}>
            <Button size="small">Open</Button>
          </Link>
        ) : (
          <Tooltip title={open.say}>
            <Button size="small" disabled aria-label={`Open ${r.row.id}`}>
              Open
            </Button>
          </Tooltip>
        )
      },
    },
  ]

  const empty = data && data.chemicals.length === 0 && data.unassigned.length === 0

  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
        <Typography.Title level={2} style={{ margin: 0 }}>
          Studies
        </Typography.Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => void navigate('/studies/new')}>
          New study
        </Button>
      </Space>

      {error ? (
        <Refusal error={error} title="The list of studies could not be read" />
      ) : isPending ? (
        <Skeleton active paragraph={{ rows: 8 }} data-testid="studies-loading" />
      ) : empty ? (
        <Empty description="No studies yet">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => void navigate('/studies/new')}>
            New study
          </Button>
        </Empty>
      ) : (
        <>
          <Input.Search
            allowClear
            aria-label="Find a study"
            placeholder="Find by name, CASRN or DTXSID"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ maxWidth: 420 }}
          />
          <Table<ListRow>
            rowKey="key"
            size="middle"
            columns={columns}
            dataSource={rows}
            pagination={false}
            scroll={{ x: 1180 }}
            expandable={{ expandedRowKeys: expandedKeys, onExpandedRowsChange: (keys) => setExpanded(keys) }}
            rowClassName={(r) => (r.key.startsWith('chem:') || r.key === UNASSIGNED_KEY ? 'm1-chemical-row' : 'm1-session-row')}
            locale={{ emptyText: <Empty description={`Nothing matches "${query.trim()}".`} /> }}
          />
        </>
      )}
    </Space>
  )
}
