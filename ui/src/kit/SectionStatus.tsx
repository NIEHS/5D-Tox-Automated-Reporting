import { ExclamationCircleOutlined, LockOutlined, SyncOutlined, EditOutlined, StopOutlined } from '@ant-design/icons'
import { Tag, Tooltip } from 'antd'
import { sectionMark, type SectionMark, type SectionStatusInput } from './sectionMark'

/** The mark itself; the rules are in sectionMark.ts. */
const ICONS: Record<SectionMark['id'], React.ReactNode> = {
  stale: <ExclamationCircleOutlined />,
  regenerated: <SyncOutlined />,
  'needs-reapproval': <SyncOutlined />,
  final: <LockOutlined />,
  approved: <LockOutlined />,
  owned: <LockOutlined />,
  blocked: <StopOutlined />,
  draft: <EditOutlined />,
}

export function SectionStatus({ section }: { section: SectionStatusInput }) {
  const mark = sectionMark(section)
  const wording = section.wording_review ?? []
  const tip = (
    <span>
      {mark.explain}
      {wording.length > 0 && (
        <>
          {' '}
          Wording to check: {wording.join(' ')}
        </>
      )}
    </span>
  )
  return (
    <Tooltip title={tip}>
      <Tag
        color={mark.color}
        icon={ICONS[mark.id]}
        tabIndex={0}
        data-mark={mark.id}
        aria-label={`${mark.label}. ${mark.explain}${wording.length ? ` Wording to check: ${wording.join(' ')}` : ''}`}
      >
        {mark.label}
        {wording.length > 0 ? ' · wording to check' : ''}
      </Tag>
    </Tooltip>
  )
}
