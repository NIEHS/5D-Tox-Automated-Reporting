import { FilePdfOutlined, FileWordOutlined } from '@ant-design/icons'
import { Button, Space, Typography } from 'antd'
import { useState } from 'react'
import { fetchDownload, type ReviewDownload } from '../../api/demoReview'
import type { RunEvent } from '../../api/types'
import { Wait } from '../../kit/Wait'
import { saveFile } from './save'
import {
  EDITED_IN_WORD,
  NO_DOWNLOADS,
  PDF_BUTTON,
  PDF_WAIT_NOTE,
  PDF_WAIT_TITLE,
  SAVED,
  WORD_BUTTON,
  WORD_WAIT_NOTE,
  WORD_WAIT_TITLE,
} from './words'

const WORDS: Record<string, { button: string; title: string; note: string; icon: React.ReactNode; primary: boolean }> = {
  docx: { button: WORD_BUTTON, title: WORD_WAIT_TITLE, note: WORD_WAIT_NOTE, icon: <FileWordOutlined aria-hidden />, primary: true },
  pdf: { button: PDF_BUTTON, title: PDF_WAIT_TITLE, note: PDF_WAIT_NOTE, icon: <FilePdfOutlined aria-hidden />, primary: false },
}

/**
 * "Make the Word document" (and the PDF): the Bookshelf's own downloads,
 * fetched behind the kit's wait, then handed to the browser to save. They
 * change nothing, so they are offered on the finished side of a pair too. A
 * document that cannot be made shows the backend's reason.
 */
export function Downloads({ reportId, downloads }: { reportId: string; downloads: ReviewDownload[] }) {
  const [making, setMaking] = useState<ReviewDownload | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const offered = downloads.filter((d) => WORDS[d.format])

  const make = (d: ReviewDownload) =>
    async function* (): AsyncGenerator<RunEvent> {
      const content = await fetchDownload(d.url)
      saveFile(content, d.filename)
      yield { event: 'result', ok: true, summary: { filename: d.filename } }
    }

  return (
    <Space orientation="vertical" size="small" style={{ width: '100%' }} data-testid="downloads">
      {offered.length === 0 ? (
        <Typography.Text type="secondary">{NO_DOWNLOADS}</Typography.Text>
      ) : (
        <Space wrap size="small">
          {offered.map((d) => {
            const w = WORDS[d.format]!
            return (
              <Button
                key={d.format}
                type={w.primary ? 'primary' : 'default'}
                icon={w.icon}
                onClick={() => {
                  setSaved(null)
                  setMaking(d)
                }}
              >
                {w.button}
              </Button>
            )
          })}
        </Space>
      )}
      <Typography.Text>{EDITED_IN_WORD}</Typography.Text>
      {saved && (
        <Typography.Text type="success" role="status" data-testid="download-saved">
          {SAVED(saved)}
        </Typography.Text>
      )}
      {making && (
        <Wait
          key={making.format}
          studyId={reportId}
          title={WORDS[making.format]!.title}
          note={WORDS[making.format]!.note}
          start={make(making)}
          onFinish={(outcome) => {
            if (outcome.ok) setSaved(making.filename)
          }}
          onClose={() => setMaking(null)}
        />
      )}
    </Space>
  )
}
