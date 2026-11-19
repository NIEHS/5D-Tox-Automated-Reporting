import { Button, Collapse, Space, Tooltip, Typography } from 'antd'
import type { ReviewGroup, ReviewSection } from '../../api/demoReview'
import { SectionStatus } from '../../kit/SectionStatus'
import { sectionId } from './ids'
import { APPROVE, HISTORY, REOPEN } from './words'

export interface RailActs {
  /** false on the finished side of a pair: the rail then offers no act */
  offered: boolean
  /** the section an act is being sent for, if any */
  busy: string | null
  onApprove: (s: ReviewSection) => void
  onReopen: (s: ReviewSection) => void
  onHistory: (s: ReviewSection) => void
}

const SR_ONLY: React.CSSProperties = {
  position: 'absolute',
  width: 1,
  height: 1,
  overflow: 'hidden',
  clipPath: 'inset(50%)',
  whiteSpace: 'nowrap',
}

function ApproveButton({ section, acts }: { section: ReviewSection; acts: RailActs }) {
  const id = sectionId(section)
  // Whether it can be approved now, and why not, is the backend's verdict.
  const { allowed, say } = section.accept
  const why = say ?? 'The application did not say why this section cannot be approved.'
  const whyId = `why-${id.replace(/[^A-Za-z0-9_-]/g, '_')}`
  const button = (
    <Button
      size="small"
      type={allowed ? 'primary' : 'default'}
      disabled={!allowed || (acts.busy !== null && acts.busy !== id)}
      loading={acts.busy === id}
      aria-label={`${APPROVE} ${section.title}`}
      aria-describedby={allowed ? undefined : whyId}
      onClick={() => acts.onApprove(section)}
    >
      {APPROVE}
    </Button>
  )
  if (allowed) return button
  return (
    <>
      <Tooltip title={why}>{button}</Tooltip>
      <span id={whyId} style={SR_ONLY}>
        {why}
      </span>
    </>
  )
}

function SectionRow({
  section,
  chosen,
  note,
  acts,
  onChoose,
}: {
  section: ReviewSection
  chosen: boolean
  /** why the book was not scrolled to the chosen section, if it was not */
  note: string | null
  acts: RailActs
  onChoose: (s: ReviewSection) => void
}) {
  const id = sectionId(section)
  // Approve: on a section that is not approved, and on an approved one the
  // backend says can be approved again (it changed since). Reopen: on an
  // approved one. Neither on the finished side of a pair.
  const showApprove = acts.offered && (!section.approved || section.accept.allowed)
  const showReopen = acts.offered && section.approved
  return (
    <li
      data-section={id}
      data-chosen={chosen ? 'yes' : 'no'}
      aria-current={chosen ? 'true' : undefined}
      style={{
        padding: '8px 10px',
        borderRadius: 6,
        borderInlineStart: chosen ? '3px solid #1677ff' : '3px solid transparent',
        background: chosen ? 'rgba(22, 119, 255, 0.08)' : undefined,
      }}
    >
      <Space orientation="vertical" size={4} style={{ width: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <Button
            type="link"
            onClick={() => onChoose(section)}
            style={{ padding: 0, height: 'auto', whiteSpace: 'normal', textAlign: 'start', fontWeight: chosen ? 600 : 400 }}
          >
            {section.title}
          </Button>
          <span style={{ flex: 'none' }}>
            <SectionStatus section={section} />
          </span>
        </div>
        {chosen && (
          <Typography.Text type="secondary" style={{ fontSize: 13 }}>
            {section.writer_say}
          </Typography.Text>
        )}
        {chosen && note && (
          <Typography.Text type="warning" data-testid="scroll-note" role="status" style={{ fontSize: 13 }}>
            {note}
          </Typography.Text>
        )}
        {(showApprove || showReopen || section.has_file) && (
          <Space size={6} wrap>
            {showApprove && <ApproveButton section={section} acts={acts} />}
            {showReopen && (
              <Button
                size="small"
                disabled={acts.busy !== null}
                aria-label={`${REOPEN} ${section.title}`}
                onClick={() => acts.onReopen(section)}
              >
                {REOPEN}
              </Button>
            )}
            {section.has_file && (
              <Button size="small" aria-label={`${HISTORY} of ${section.title}`} onClick={() => acts.onHistory(section)}>
                {HISTORY}
              </Button>
            )}
          </Space>
        )}
      </Space>
    </li>
  )
}

/**
 * The sections of the report, by the session that owns them, in the book's
 * order. Everything shown about a section is the backend's row: its mark
 * (the kit's), whether it can be approved and why not, and whether it has a
 * place in the book.
 */
export function Rail({
  groups,
  open,
  onOpen,
  chosen,
  note,
  acts,
  onChoose,
}: {
  groups: ReviewGroup[]
  /** the owners of the groups that are opened */
  open: string[]
  onOpen: (owners: string[]) => void
  chosen: string | null
  note: string | null
  acts: RailActs
  onChoose: (s: ReviewSection) => void
}) {
  return (
    <Collapse
      size="small"
      activeKey={open}
      onChange={(keys) => onOpen(Array.isArray(keys) ? keys : [keys])}
      items={groups.map((g) => ({
        key: g.owner,
        label: (
          <span data-testid="group-title">
            <Typography.Text strong>{g.title}</Typography.Text>{' '}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {g.owner}
            </Typography.Text>
          </span>
        ),
        children: g.exists ? (
          <ul aria-label={`Sections of ${g.title}`} data-group={g.owner} style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {g.sections.map((s) => (
              <SectionRow
                key={s.key}
                section={s}
                chosen={chosen === sectionId(s)}
                note={chosen === sectionId(s) ? note : null}
                acts={acts}
                onChoose={onChoose}
              />
            ))}
          </ul>
        ) : (
          <Typography.Text type="secondary">{g.say ?? 'This study does not exist.'}</Typography.Text>
        ),
        styles: { body: { padding: 4 } },
      }))}
    />
  )
}
