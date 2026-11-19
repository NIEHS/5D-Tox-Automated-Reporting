import { useMutation } from '@tanstack/react-query'
import { Alert, Button, Card, Collapse, Grid, Skeleton, Space, Typography } from 'antd'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { noopOf } from '../../api/client'
import { acceptSection, releaseSection, type Review, type ReviewSection, type SectionActResult } from '../../api/demoReview'
import type { ApiError } from '../../api/errors'
import type { Noop, WithNoop } from '../../api/types'
import { moduleRoute } from '../../kit/modules'
import { PublishReadiness } from '../../kit/PublishReadiness'
import { Refusal } from '../../kit/Refusal'
import { useInvalidateStudy } from '../../kit/useStudyState'
import { Book, type BookHandle } from './Book'
import { Downloads } from './Downloads'
import { HistoryDrawer } from './HistoryDrawer'
import { useReview } from './queries'
import { sectionId } from './ids'
import { Rail } from './Rail'
import { ReopenDialog } from './ReopenDialog'
import {
  ACT_NOOP_TITLE,
  ACT_REFUSED_TITLE,
  ANCHORS_ERROR_TITLE,
  ANCHOR_NOT_IN_BOOK,
  API_PAGE_LEAD,
  BOOK_AGAIN,
  BOOK_NOT_READY,
  BOOK_STALE_NOTE,
  FINISHED_SIDE_TITLE,
  NO_ANCHOR,
  NO_STUDY_READINESS,
  OPEN_ON_LIVE_COPY,
  PAGE_PURPOSE,
  PAGE_TITLE,
  PUBLISH_TITLE,
  RAIL_HELP,
  RAIL_TITLE,
} from './words'

const RAIL_WIDTH = 380
const MIN_HEIGHT = 480
const EDGE = 12

/** The window's height, less a margin: the page's two panes fill the window once they are at its top. */
function useWindowHeight(): number {
  const [height, setHeight] = useState(() => Math.max(MIN_HEIGHT, window.innerHeight - 2 * EDGE))
  useLayoutEffect(() => {
    const measure = () => setHeight(Math.max(MIN_HEIGHT, window.innerHeight - 2 * EDGE))
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [])
  return height
}

interface Outcome {
  section: ReviewSection
  act: 'approved' | 'reopened'
  error?: ApiError
  noop?: Noop
}

/**
 * Review the report (the demo path, spec §4 S5): the report as the Bookshelf
 * shows it in the main pane; beside it the sections in the book's order, each
 * with its standing, Approve, Reopen and its history; what stands between
 * the report and publishing; and "Make the Word document".
 *
 * Text is not edited here: it is edited in Word. Everything about a section
 * (its standing, whether it can be approved and why not, where it is in the
 * book) and about publishing is the backend's; after an act the page reads it
 * again. The book is not shown again after an act, which changes no text.
 */
export function ReviewPage() {
  const { id = '' } = useParams()
  const { data: review, error, isPending, refetch, isFetching } = useReview(id)

  if (isPending) return <Skeleton active paragraph={{ rows: 8 }} />
  if (!review) {
    return (
      <Refusal
        error={error}
        studyId={id}
        title="The report's review could not be read"
        action={
          <Button onClick={() => void refetch()} loading={isFetching}>
            {BOOK_AGAIN}
          </Button>
        }
      />
    )
  }
  // A new report or another study asked for starts the page afresh.
  return <ReviewBody key={`${review.report.id}/${review.asked?.id ?? ''}`} pageId={id} review={review} />
}

/** The page's name, what it is for, and where its step is on the API page. */
function Heading({ review }: { review: Review }) {
  return (
    <Space orientation="vertical" size={4} style={{ width: '100%' }}>
      <Typography.Title level={4} style={{ margin: 0 }}>
        {PAGE_TITLE}
      </Typography.Title>
      <Typography.Text style={{ fontSize: 13 }}>{PAGE_PURPOSE}</Typography.Text>
      {review.asked && (
        <Typography.Text data-testid="asked-study" style={{ fontSize: 13 }}>
          <Typography.Text strong>{review.asked.id}: </Typography.Text>
          {review.asked.say}
        </Typography.Text>
      )}
      {review.api_page.length > 0 && (
        <Space wrap size="small" data-testid="api-page" style={{ fontSize: 13 }}>
          <Typography.Text type="secondary">{API_PAGE_LEAD}</Typography.Text>
          {review.api_page.map((l) => (
            <a key={l.group} href={l.href} target="_blank" rel="noopener noreferrer">
              {l.title}
            </a>
          ))}
        </Space>
      )}
    </Space>
  )
}

function ReviewBody({ pageId, review }: { pageId: string; review: Review }) {
  const wide = Grid.useBreakpoint().lg !== false
  const box = useRef<HTMLDivElement>(null)
  const height = useWindowHeight()
  // The book and the rail are brought to the top of the window when the page
  // opens, so that they fill it; the study's header stays above, a scroll away.
  useEffect(() => {
    if (wide && typeof box.current?.scrollIntoView === 'function') box.current.scrollIntoView({ block: 'start' })
    // once, when the page opens
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const book = useRef<BookHandle>(null)
  const invalidate = useInvalidateStudy()

  // Opened on a study of a report: that study's sections first. Otherwise every group.
  const askedOwner = review.asked?.id ?? null
  const [open, setOpen] = useState<string[]>(() =>
    askedOwner && review.groups.some((g) => g.owner === askedOwner) ? [askedOwner] : review.groups.map((g) => g.owner),
  )
  const [chosen, setChosen] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [reopening, setReopening] = useState<ReviewSection | null>(null)
  const [history, setHistory] = useState<ReviewSection | null>(null)

  /** After an act: read again what the page shows of the report, of the section's session and of the session opened. */
  const reread = async (owner: string) => {
    await Promise.all([...new Set([pageId, review.report.id, owner])].map((sid) => invalidate(sid)))
  }

  const approve = useMutation<WithNoop<SectionActResult>, ApiError, ReviewSection>({
    mutationFn: (s) => acceptSection(s.owner, s.key),
    onMutate: () => setOutcome(null),
    onSuccess: (data, s) => {
      const noop = noopOf(data)
      if (noop) setOutcome({ section: s, act: 'approved', noop })
    },
    onError: (err, s) => setOutcome({ section: s, act: 'approved', error: err }),
    onSettled: (_d, _e, s) => reread(s.owner),
  })

  const reopen = useMutation<WithNoop<SectionActResult>, ApiError, { section: ReviewSection; reason: string }>({
    mutationFn: ({ section, reason }) => releaseSection(section.owner, section.key, reason),
    onMutate: () => setOutcome(null),
    onSuccess: (data, { section }) => {
      const noop = noopOf(data)
      if (noop) setOutcome({ section, act: 'reopened', noop })
      setReopening(null)
    },
    onSettled: (_d, _e, { section }) => reread(section.owner),
  })

  const choose = (s: ReviewSection) => {
    setChosen(sectionId(s))
    if (!s.anchor) {
      setNote(NO_ANCHOR)
      return
    }
    const went = book.current?.scrollTo(s.anchor) ?? 'not_ready'
    setNote(went === 'ok' ? null : went === 'not_found' ? ANCHOR_NOT_IN_BOOK : BOOK_NOT_READY)
  }

  // The chosen section's row is brought into view in the rail (it may have been chosen before its group was opened).
  useEffect(() => {
    if (!chosen) return
    const row = document.querySelector(`[data-section="${CSS.escape(chosen)}"]`)
    if (row && typeof row.scrollIntoView === 'function') row.scrollIntoView({ block: 'nearest' })
  }, [chosen])

  const busy = approve.isPending && approve.variables ? sectionId(approve.variables) : reopen.isPending ? 'reopening' : null
  const counterpart = review.acts.counterpart
  const sameOnLive = counterpart ? moduleRoute('D1', counterpart) : undefined

  return (
    <div
      ref={box}
      data-testid="review"
      style={{
        display: 'flex',
        flexDirection: wide ? 'row' : 'column',
        gap: 16,
        alignItems: 'stretch',
        height: wide ? height : undefined,
        scrollMarginTop: EDGE,
      }}
    >
      <div
        data-testid="book-pane"
        style={{
          flex: wide ? '1 1 0' : 'none',
          minWidth: 0,
          height: wide ? '100%' : '75vh',
          border: '1px solid rgba(5, 5, 5, 0.12)',
          borderRadius: 8,
          overflow: 'hidden',
          background: '#fff',
        }}
      >
        <Book ref={book} book={review.book} />
      </div>

      <aside
        aria-label="The sections of the report"
        style={{ flex: wide ? `0 0 ${RAIL_WIDTH}px` : 'none', minWidth: 0, height: wide ? '100%' : undefined, overflowY: wide ? 'auto' : undefined }}
      >
        <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
          <Heading review={review} />

          <Card size="small">
            <Downloads reportId={review.report.id} downloads={review.downloads} />
          </Card>

          {!review.acts.allowed && (
            <Alert
              type="info"
              showIcon
              data-testid="no-acts"
              title={FINISHED_SIDE_TITLE}
              description={
                <Space orientation="vertical" size={4}>
                  <span>{review.acts.say}</span>
                  {sameOnLive && <Link to={sameOnLive}>{OPEN_ON_LIVE_COPY}</Link>}
                </Space>
              }
            />
          )}

          {review.anchors_error && (
            <Alert type="warning" showIcon title={ANCHORS_ERROR_TITLE} description={review.anchors_error.say} />
          )}

          {outcome?.error && (
            <Refusal
              error={outcome.error}
              studyId={outcome.section.owner}
              title={ACT_REFUSED_TITLE(outcome.act, outcome.section.title)}
              action={
                <Button size="small" onClick={() => setOutcome(null)}>
                  Close
                </Button>
              }
            />
          )}
          {outcome?.noop && (
            <Refusal
              noop={outcome.noop}
              title={`${ACT_NOOP_TITLE}: “${outcome.section.title}”`}
              action={
                <Button size="small" onClick={() => setOutcome(null)}>
                  Close
                </Button>
              }
            />
          )}

          <div>
            <Typography.Title level={5} style={{ margin: '0 0 2px' }}>
              {RAIL_TITLE}
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ margin: '0 0 8px', fontSize: 13 }}>
              {RAIL_HELP} {review.acts.allowed ? BOOK_STALE_NOTE : ''}
            </Typography.Paragraph>
            <Rail
              groups={review.groups}
              open={open}
              onOpen={setOpen}
              chosen={chosen}
              note={note}
              onChoose={choose}
              acts={{
                offered: review.acts.allowed,
                busy,
                onApprove: (s) => approve.mutate(s),
                onReopen: (s) => {
                  reopen.reset()
                  setReopening(s)
                },
                onHistory: setHistory,
              }}
            />
          </div>

          <Card size="small" title={PUBLISH_TITLE} data-testid="publishing">
            <Collapse
              size="small"
              ghost
              defaultActiveKey={review.groups.slice(0, 1).map((g) => g.owner)}
              items={review.groups.map((g) => ({
                key: g.owner,
                label: <Typography.Text strong>{g.title}</Typography.Text>,
                children: g.publish ? (
                  <PublishReadiness readiness={g.publish} studyId={g.owner} />
                ) : (
                  <Typography.Text type="secondary">{g.say ?? NO_STUDY_READINESS}</Typography.Text>
                ),
              }))}
            />
          </Card>
        </Space>
      </aside>

      {reopening && (
        <ReopenDialog
          key={sectionId(reopening)}
          section={reopening}
          sending={reopen.isPending}
          error={reopen.error}
          onCancel={() => setReopening(null)}
          onReopen={(reason) => reopen.mutate({ section: reopening, reason })}
        />
      )}
      <HistoryDrawer section={history} onClose={() => setHistory(null)} />
    </div>
  )
}
