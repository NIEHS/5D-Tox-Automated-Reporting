import { Button, Drawer, Skeleton, Space, Tag, Typography } from 'antd'
import type { ReviewSection } from '../../api/demoReview'
import { ItemList } from '../../kit/ItemList'
import { Refusal } from '../../kit/Refusal'
import { useSectionHistory } from './queries'
import {
  BOOK_AGAIN,
  CURRENT,
  HISTORY_EMPTY,
  HISTORY_ERROR_TITLE,
  HISTORY_EVENTS,
  HISTORY_TITLE,
  HISTORY_VERSIONS,
  actWords,
  actorWords,
  statusWords,
  whenWords,
} from './words'

/**
 * A section's history: its versions and what happened to each, as recorded
 * (GET …/sections/{key}/history, read from the session that holds it).
 */
export function HistoryDrawer({ section, onClose }: { section: ReviewSection | null; onClose: () => void }) {
  const { data, error, isPending, refetch, isFetching } = useSectionHistory(section?.owner, section?.key)
  return (
    <Drawer open={section !== null} onClose={onClose} size={520} title={section ? HISTORY_TITLE(section.title) : ''}>
      {!section ? null : isPending ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : !data ? (
        <Refusal
          error={error}
          studyId={section.owner}
          title={HISTORY_ERROR_TITLE}
          action={
            <Button onClick={() => void refetch()} loading={isFetching}>
              {BOOK_AGAIN}
            </Button>
          }
        />
      ) : (
        <Space orientation="vertical" size="large" style={{ width: '100%' }} data-testid="section-history">
          <div>
            <Typography.Title level={5} style={{ marginTop: 0 }}>
              {HISTORY_VERSIONS}
            </Typography.Title>
            {data.versions.length === 0 ? (
              <Typography.Text type="secondary">{HISTORY_EMPTY}</Typography.Text>
            ) : (
              <ItemList
                dense
                aria-label={HISTORY_VERSIONS}
                items={data.versions}
                rowKey={(v) => String(v.version)}
                rowProps={(v) => ({ 'data-version': String(v.version) })}
                render={(v) => (
                  <Space wrap size="small">
                    <Typography.Text strong>Version {v.version}</Typography.Text>
                    <Typography.Text>{statusWords(v.status)}</Typography.Text>
                    {v.current && <Tag color="blue">{CURRENT}</Tag>}
                    {!v.retrievable && <Tag>its text was not kept</Tag>}
                  </Space>
                )}
              />
            )}
          </div>
          <div>
            <Typography.Title level={5} style={{ marginTop: 0 }}>
              {HISTORY_EVENTS}
            </Typography.Title>
            {data.events.length === 0 ? (
              <Typography.Text type="secondary">{HISTORY_EMPTY}</Typography.Text>
            ) : (
              <ItemList
                aria-label={HISTORY_EVENTS}
                items={data.events}
                rowKey={(e, i) => `${e.ts}-${i}`}
                rowProps={(e) => ({ 'data-act': e.act })}
                render={(e) => (
                  <Space orientation="vertical" size={0} style={{ width: '100%' }}>
                    <Typography.Text strong>{actWords(e)}</Typography.Text>
                    <Typography.Text type="secondary">
                      {whenWords(e.ts)} · by {actorWords(e.actor)}
                      {e.version !== null && e.version !== undefined ? ` · version ${e.version}` : ''}
                      {e.status ? ` · then: ${statusWords(e.status).toLowerCase()}` : ''}
                    </Typography.Text>
                    {e.reason && <Typography.Text>Reason given: {e.reason}</Typography.Text>}
                  </Space>
                )}
              />
            )}
          </div>
        </Space>
      )}
    </Drawer>
  )
}
