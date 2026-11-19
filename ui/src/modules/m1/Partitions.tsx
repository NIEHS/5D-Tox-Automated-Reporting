import { Button, Card, Col, Row, Space, Switch, Tag, Tooltip, Typography } from 'antd'
import { Link } from 'react-router'
import { getResetPreview, resetLiveCopy } from '../../api/m1'
import type { Partition, PartitionEntry, StudyRow } from '../../api/types'
import { ConfirmAct } from '../../kit/ConfirmAct'
import { studyRoute } from '../../kit/modules'
import { PhaseTag } from '../../kit/PhaseTag'
import { setOnlyPartition } from './onlyPartition'
import { useRefreshStudies } from './queries'
import { BookshelfLink, NextLink } from './StudiesList'
import { ROLE_WORDS } from './words'

/**
 * The sessions a person set apart from the list (ui_api.demo): a finished
 * report and its live copy, side by side. Which side a session is, where it
 * stands and what comes next are the backend's; nothing is worked out here.
 */

function memberKey(report: StudyRow, member: StudyRow): string {
  return report.relations.members.find((m) => m.id === member.id)?.key ?? member.id
}

function OpenButton({ s }: { s: StudyRow }) {
  const open = s.actions.open
  return open.allowed ? (
    <Link to={studyRoute(s.id)} aria-label={`Open ${s.id}`}>
      <Button size="small">Open</Button>
    </Link>
  ) : (
    <Tooltip title={open.say}>
      <Button size="small" disabled aria-label={`Open ${s.id}`}>
        Open
      </Button>
    </Tooltip>
  )
}

function Side({ entry, finished }: { entry: PartitionEntry; finished: PartitionEntry | undefined }) {
  const refresh = useRefreshStudies()
  const words = ROLE_WORDS[entry.role ?? ''] ?? { label: 'Set apart', color: 'default', say: '' }
  const s = entry.session
  return (
    <Card size="small" data-testid={`partition-side-${entry.role ?? 'other'}`} style={{ height: '100%' }}>
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Space wrap size="small">
          <Tag color={words.color}>{words.label}</Tag>
          <Typography.Text style={{ fontFamily: 'monospace', fontSize: 12 }}>{entry.id}</Typography.Text>
        </Space>
        {words.say && <Typography.Text type="secondary">{words.say}</Typography.Text>}
        {!s ? (
          <Typography.Text type="danger">This session is named here and does not exist.</Typography.Text>
        ) : (
          <>
            <Space wrap size="small" align="center">
              <Typography.Text strong>{s.identity.name ?? s.id}</Typography.Text>
              <PhaseTag phase={s.stands.phase} say={s.stands.say} />
              <OpenButton s={s} />
            </Space>
            <NextLink s={s} />
            <BookshelfLink s={s} />
            {entry.members.length > 0 && (
              <ul aria-label={`Studies of ${entry.id}`} style={{ margin: 0, paddingLeft: 18 }}>
                {entry.members.map((m) => (
                  <li key={m.id}>
                    <Space wrap size="small" align="center">
                      <Link to={studyRoute(m.id)}>{memberKey(s, m)}</Link>
                      <PhaseTag phase={m.stands.phase} say={m.stands.say} />
                      <NextLink s={m} />
                    </Space>
                  </li>
                ))}
              </ul>
            )}
            {entry.role === 'live' && finished && (
              <ConfirmAct
                studyId={entry.id}
                act="reset_live_copy"
                label="Put the live copy back to its start"
                dialogTitle="Put the live copy back to its start?"
                confirmLabel="Put it back"
                loadDryRun={(signal) => getResetPreview(finished.id, signal)}
                perform={() => resetLiveCopy(finished.id)}
                onDone={() => void refresh()}
                buttonProps={{ size: 'small' }}
              />
            )}
          </>
        )}
      </Space>
    </Card>
  )
}

function OnlyThis({ name, on }: { name: string; on: boolean }) {
  return (
    <Space size="small">
      <Typography.Text type="secondary" id={`only-${name}`}>
        Show only this block
      </Typography.Text>
      <Switch size="small" aria-labelledby={`only-${name}`} checked={on} onChange={(v) => setOnlyPartition(v ? name : null)} />
    </Space>
  )
}

export function Partitions({ partitions, only }: { partitions: Partition[]; only: string | null }) {
  if (partitions.length === 0) return null
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      {partitions.map((p) => {
        const finished = p.sessions.find((e) => e.role === 'finished')
        return (
          <Card key={p.name} title={p.name} size="small" data-testid={`partition-${p.name}`} extra={<OnlyThis name={p.name} on={only === p.name} />}>
            <Row gutter={[12, 12]}>
              {p.sessions.map((e) => (
                <Col key={e.id} xs={24} md={Math.max(8, Math.floor(24 / p.sessions.length))}>
                  <Side entry={e} finished={finished} />
                </Col>
              ))}
            </Row>
          </Card>
        )
      })}
    </Space>
  )
}
