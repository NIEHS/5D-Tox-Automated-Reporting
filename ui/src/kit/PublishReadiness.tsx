import { Alert, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router'
import type { Readiness } from '../api/types'
import { ItemList } from './ItemList'
import { moduleById, moduleRoute } from './modules'

/**
 * What stops the report being published, as the backend's readiness lists
 * it, AND what that readiness looked at. While the check is partial
 * (`complete` is not true), an empty list never reads as "ready to publish":
 * it says what was checked and that the rest has not been.
 */
export function PublishReadiness({ readiness, studyId }: { readiness?: Readiness; studyId: string }) {
  if (!readiness) {
    return <Typography.Text type="secondary">The application did not say what stops publishing.</Typography.Text>
  }
  const checked = readiness.checks ?? []
  const partial = readiness.complete !== true
  return (
    <Space orientation="vertical" size="small" style={{ width: '100%' }}>
      {readiness.items.length > 0 ? (
        <ItemList
          dense
          aria-label="What stops publishing"
          items={readiness.items}
          rowKey={(item, i) => `${item.id}-${item.section ?? i}`}
          render={(item) => {
            const m = moduleById(item.fix)
            const to = m ? moduleRoute(m.id, studyId) : undefined
            return (
              <Space orientation="vertical" size={0}>
                <Space>
                  <Tag color={item.level === 'block' ? 'red' : 'gold'}>{item.level === 'block' ? 'Blocks' : 'Check'}</Tag>
                  <Typography.Text>
                    {item.section ? <Typography.Text strong>{item.section}: </Typography.Text> : null}
                    {item.say}
                  </Typography.Text>
                </Space>
                {m && to && <Link to={to}>Go to {m.title}</Link>}
              </Space>
            )
          }}
        />
      ) : (
        <Typography.Text data-testid="publish-nothing-found">
          {partial ? 'Nothing found by the checks below.' : 'Nothing stops the report being published.'}
        </Typography.Text>
      )}
      {partial && (
        <Alert
          type="warning"
          showIcon
          data-testid="publish-partial"
          title="This is not a full check of whether the report can be published."
          description={
            <Space orientation="vertical" size={2}>
              <Typography.Text>What was checked:</Typography.Text>
              {checked.length > 0 ? (
                <ul style={{ margin: 0, paddingInlineStart: 20 }}>
                  {checked.map((c) => (
                    <li key={c.id}>{c.say}</li>
                  ))}
                </ul>
              ) : (
                <Typography.Text type="secondary">The application did not say.</Typography.Text>
              )}
              <Typography.Text>
                Not checked yet: whether every section is approved, missing details ("[… pending]"), the studies a report covers,
                and the method and report definition. Read the report before you hand it on.
              </Typography.Text>
            </Space>
          }
        />
      )}
    </Space>
  )
}
