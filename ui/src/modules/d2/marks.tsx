import { Tag } from 'antd'
import type { RecordKind, WrittenBy } from '../../api/demoWriting'
import { recordWords, writtenByTags } from './words'

/** Who wrote a part: one tag, or both for a part written by both. */
export function WrittenByTags({ writtenBy }: { writtenBy: WrittenBy | (string & {}) }) {
  return (
    <span data-testid="written-by" style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4 }}>
      {writtenByTags(writtenBy).map((t) => (
        <Tag key={t.label} color={t.color} style={{ marginInlineEnd: 0 }}>
          {t.label}
        </Tag>
      ))}
    </span>
  )
}

/** How a text relates to the record: as sent, recorded, rebuilt, or not recorded. */
export function RecordTag({ record }: { record: RecordKind | (string & {}) }) {
  const w = recordWords(record)
  return (
    <Tag color={w.color} data-testid="record" data-record={record} style={{ marginInlineEnd: 0 }}>
      {w.label}
    </Tag>
  )
}

/** A long recorded text: monospace, wrapped, in a box that scrolls. */
export function RecordedText({ text, label }: { text: string; label: string }) {
  return (
    <pre
      aria-label={label}
      tabIndex={0}
      style={{
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
        fontSize: 12,
        lineHeight: 1.5,
        whiteSpace: 'pre-wrap',
        overflowWrap: 'anywhere',
        maxHeight: 420,
        overflow: 'auto',
        margin: 0,
        padding: 12,
        background: 'rgba(0, 0, 0, 0.03)',
        border: '1px solid rgba(5, 5, 5, 0.08)',
        borderRadius: 6,
      }}
    >
      {text}
    </pre>
  )
}

/** A link that leaves the application: a new tab. */
export function Outside({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  )
}
