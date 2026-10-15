import { Alert, Space, Typography } from 'antd'
import type { FormatDetail } from '../../api/types'

/**
 * "The report format" (M1 spec §3 S2 step 2): which format a study under
 * this id is written in, and why. Informational when the id brings the format
 * for new studies; a warning when it brings a published book's format.
 */
export function FormatNotice({ format }: { format: FormatDetail }) {
  const fromBook = format.source !== 'default'
  return (
    <Alert
      data-testid="format-notice"
      data-level={fromBook ? 'warning' : 'info'}
      type={fromBook ? 'warning' : 'info'}
      showIcon
      title={`The report format: ${format.title}`}
      description={
        <Space orientation="vertical" size="small">
          <Typography.Text>{format.say}</Typography.Text>
          {format.brings.length > 0 && (
            <div>
              <Typography.Text>It also brings:</Typography.Text>
              <ul style={{ margin: '4px 0 0', paddingInlineStart: 20 }} aria-label="What the id also brings">
                {format.brings.map((b) => (
                  <li key={b.what + b.path}>{b.say}</li>
                ))}
              </ul>
            </div>
          )}
          <Typography.Text type="secondary">The DTXSID decides this. It can't be changed here.</Typography.Text>
        </Space>
      }
    />
  )
}
