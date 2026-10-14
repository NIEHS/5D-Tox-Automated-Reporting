import { Alert, Button, Space, Typography } from 'antd'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { ApiError } from '../api/errors'
import type { ErrorBody, Noop } from '../api/types'
import { moduleById, moduleRoute } from './modules'

/**
 * The refusal explainer (MODULES.md §4.2). Renders the backend's plain words
 * (`say`), a link to the place that fixes it (`fix`), and the backend's
 * verbatim message and details behind a toggle. Also renders a "success that
 * did nothing" (`noop`). Never shows a bare technical message first.
 */

export type RefusalProps =
  | { error: ApiError | ErrorBody; noop?: undefined; studyId?: string; title?: string; action?: React.ReactNode }
  | { noop: Noop; error?: undefined; studyId?: string; title?: string; action?: React.ReactNode }

function bodyOf(error: ApiError | ErrorBody): ErrorBody {
  return error instanceof ApiError ? error.body : error
}

export function Refusal(props: RefusalProps) {
  const [open, setOpen] = useState(false)
  const detailsId = useId()

  if (props.noop) {
    return (
      <Alert
        type="info"
        showIcon
        role="status"
        title={props.title ?? 'Nothing was changed'}
        description={<Typography.Paragraph style={{ margin: 0 }}>{props.noop.say}</Typography.Paragraph>}
        action={props.action}
      />
    )
  }

  const body = bodyOf(props.error)
  const fixModule = moduleById(body.fix)
  const fixPath = fixModule ? moduleRoute(fixModule.id, props.studyId) : undefined
  const details = body.details && Object.keys(body.details).length > 0 ? body.details : null

  return (
    <Alert
      type="error"
      showIcon
      role="alert"
      title={props.title ?? 'This could not be done'}
      action={props.action}
      description={
        <Space orientation="vertical" size="small" style={{ width: '100%' }}>
          <Typography.Paragraph style={{ margin: 0 }}>{body.say}</Typography.Paragraph>
          {fixModule && fixPath && (
            <Link to={fixPath}>Go to {fixModule.title} to fix this</Link>
          )}
          {fixModule && !fixPath && (
            <Typography.Text>It is fixed in {fixModule.title}.</Typography.Text>
          )}
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            aria-expanded={open}
            aria-controls={detailsId}
            onClick={() => setOpen((o) => !o)}
          >
            {open ? 'Hide the technical details' : 'Show the technical details'}
          </Button>
          {open && (
            <div id={detailsId} data-testid="refusal-details">
              <Typography.Text type="secondary">
                Code: <Typography.Text code>{body.code}</Typography.Text>
                {body.status ? <> · status {body.status}</> : null}
              </Typography.Text>
              <Typography.Paragraph copyable style={{ marginTop: 4, marginBottom: 4 }}>
                <Typography.Text code>{body.message || '(no message)'}</Typography.Text>
              </Typography.Paragraph>
              {details && (
                <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: 0 }}>{JSON.stringify(details, null, 2)}</pre>
              )}
            </div>
          )}
        </Space>
      }
    />
  )
}
