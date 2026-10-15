import {
  ClockCircleOutlined,
  EditOutlined,
  ExclamationCircleOutlined,
  LockOutlined,
  MinusCircleOutlined,
  StopOutlined,
  SyncOutlined,
} from '@ant-design/icons'
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
  'not-approvable': <MinusCircleOutlined />,
  waiting: <ClockCircleOutlined />,
  'cannot-approve-yet': <StopOutlined />,
  draft: <EditOutlined />,
}

/**
 * `wording_review` lists the data-derived words that changed under approved
 * wording, as the backend records them ("Male|liver.direction_adj": a finding
 * and the word's slot). They are codes, so the mark says how many changed and
 * shows the codes only as details; turning each into a sentence is the
 * backend's job (asked for, not done here).
 */
function wordingNote(codes: string[]): string {
  if (codes.length === 0) return ''
  const n = codes.length === 1 ? 'One word that comes from the data has' : `${codes.length} words that come from the data have`
  return `${n} changed since the wording was approved; check the text still says what the data say.`
}

export function SectionStatus({ section }: { section: SectionStatusInput }) {
  const mark = sectionMark(section)
  const wording = section.wording_review ?? []
  const note = wordingNote(wording)
  const tip = (
    <span>
      {mark.explain}
      {note && (
        <>
          {' '}
          {note} <span style={{ opacity: 0.75 }}>({wording.join(', ')})</span>
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
        aria-label={`${mark.label}. ${mark.explain}${note ? ` ${note}` : ''}`}
      >
        {mark.label}
        {wording.length > 0 ? ' · wording to check' : ''}
      </Tag>
    </Tooltip>
  )
}
