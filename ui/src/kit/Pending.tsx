import { Button, Popover, Space, Typography } from 'antd'
import { Link } from 'react-router'
import type { ModuleId } from '../api/types'
import { moduleById, moduleRoute } from './modules'

/**
 * The "[… pending]" mark (MODULES.md §4.5): what the report will print where
 * a fact is missing, never silence or a guess. Clicking it says why it is
 * pending and links to the place that fills it.
 */

export interface PendingProps {
  /** what is missing, in plain words ("report number") */
  label: string
  /** why it is missing (the backend's `say`, or the screen's own words) */
  cause: string
  /** the module that fills it */
  fix?: ModuleId | null
  studyId?: string
}

export function Pending({ label, cause, fix, studyId }: PendingProps) {
  const m = moduleById(fix)
  const to = m ? moduleRoute(m.id, studyId) : undefined
  const content = (
    <Space orientation="vertical" size={4} style={{ maxWidth: 320 }}>
      <Typography.Text>{cause}</Typography.Text>
      {m && to && <Link to={to}>Fill it in: {m.title}</Link>}
      {m && !to && <Typography.Text type="secondary">It is filled in under {m.title}.</Typography.Text>}
    </Space>
  )
  return (
    <Popover content={content} title={`${label[0]?.toUpperCase() ?? ''}${label.slice(1)} is missing`} trigger={['click', 'hover']}>
      <Button
        type="text"
        size="small"
        aria-label={`${label} is missing; show why`}
        style={{ padding: '0 4px', height: 'auto', background: '#fff7e6', border: '1px dashed #fa8c16', fontFamily: 'inherit' }}
      >
        [{label} pending]
      </Button>
    </Popover>
  )
}
