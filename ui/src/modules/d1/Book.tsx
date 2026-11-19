import { Alert, Button, Space, Spin, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useImperativeHandle, useRef, useState } from 'react'
import { requestBook, type ReviewBook } from '../../api/demoReview'
import type { ApiError } from '../../api/errors'
import { formatElapsed, useElapsed } from '../../kit/elapsed'
import { Refusal } from '../../kit/Refusal'
import {
  BOOK_AGAIN,
  BOOK_BUILDING,
  BOOK_BUILDING_NOTE,
  BOOK_NOT_SHOWN_TITLE,
  BOOK_NO_BOOK_TITLE,
  BOOK_TITLE,
} from './words'

/** What scrolling the book to a section came to. */
export type ScrollOutcome = 'ok' | 'not_found' | 'not_ready'

export interface BookHandle {
  /** Scroll the book to the element with this id; says so when it cannot. */
  scrollTo: (anchor: string) => ScrollOutcome
}

const MARK_MS = 2500

/**
 * The report's page on the Bookshelf, in a frame (the page is kept code and
 * is shown as it is). The page is asked for first, so that the wait and a
 * refusal are the application's own; the server keeps what it built, so the
 * frame then opens it at once.
 *
 * The page shows one part of the book at a time and goes to the part that
 * holds an element when its address names the element (`#<id>`): scrolling
 * uses that, the page's own way.
 */
export function Book({ book, ref }: { book: ReviewBook; ref?: React.Ref<BookHandle> }) {
  const url = book.shown ? book.url : null
  const check = useQuery<true, ApiError>({
    // Not under the study's key: an approval or a reopening does not change
    // the text, so the book is not asked for (and built) again after one.
    queryKey: ['book', url],
    queryFn: async ({ signal }): Promise<true> => {
      await requestBook(url as string, signal)
      return true
    },
    enabled: Boolean(url),
    // Kept only while the page is open: coming back to the page asks again,
    // so a report that changed meanwhile shows the wait, not an empty frame.
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  })
  const [startMs, setStartMs] = useState(() => Date.now())
  const elapsed = useElapsed(url && check.isFetching && !check.data ? startMs : null)
  const frame = useRef<HTMLIFrameElement>(null)
  const [loaded, setLoaded] = useState(false)

  useImperativeHandle(
    ref,
    () => ({
      scrollTo(anchor: string): ScrollOutcome {
        const doc = frame.current?.contentDocument
        const win = frame.current?.contentWindow
        if (!loaded || !doc || !win) return 'not_ready'
        const el = doc.getElementById(anchor)
        if (!el) return 'not_found'
        if (win.location.hash === `#${anchor}`) {
          el.scrollIntoView()
        } else {
          // The frame's own address with the element's id; a bare "#id" would
          // be read against this page's address, not the frame's. Replacing
          // keeps the browser's Back button for the application's pages.
          const to = new URL(win.location.href)
          to.hash = anchor
          win.location.replace(to.href)
        }
        // Show where it is for a moment.
        const before = el.style.outline
        const beforeOffset = el.style.outlineOffset
        el.style.outline = '3px solid #1677ff'
        el.style.outlineOffset = '4px'
        setTimeout(() => {
          el.style.outline = before
          el.style.outlineOffset = beforeOffset
        }, MARK_MS)
        return 'ok'
      },
    }),
    [loaded],
  )

  if (!url) {
    return (
      <div style={{ padding: 16 }}>
        <Alert type="info" showIcon data-testid="book-none" title={BOOK_NO_BOOK_TITLE} description={book.say} />
      </div>
    )
  }
  if (check.error && !check.data) {
    return (
      <div style={{ padding: 16 }} data-testid="book-refused">
        <Refusal
          error={check.error}
          title={BOOK_NOT_SHOWN_TITLE}
          action={
            <Button
              onClick={() => {
                setStartMs(Date.now())
                void check.refetch()
              }}
              loading={check.isFetching}
            >
              {BOOK_AGAIN}
            </Button>
          }
        />
      </div>
    )
  }
  if (!check.data) {
    return (
      <div
        data-testid="book-wait"
        role="status"
        style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}
      >
        <Space orientation="vertical" align="center" size="small" style={{ maxWidth: 520, textAlign: 'center' }}>
          <Spin size="large" />
          <Typography.Text strong>{BOOK_BUILDING}</Typography.Text>
          <Typography.Text aria-live="off">{elapsed === null ? 'Waiting' : `Waiting for ${formatElapsed(elapsed)}`}</Typography.Text>
          <Typography.Text type="secondary">{BOOK_BUILDING_NOTE}</Typography.Text>
        </Space>
      </div>
    )
  }
  return (
    <iframe
      ref={frame}
      title={BOOK_TITLE}
      src={url}
      data-testid="book-frame"
      data-loaded={loaded ? 'yes' : 'no'}
      onLoad={() => setLoaded(true)}
      style={{ display: 'block', width: '100%', height: '100%', border: 0, background: '#fff' }}
    />
  )
}
