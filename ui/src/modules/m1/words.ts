import type { FormatSummary, IdentitySource, PublishedReport, StudyRow } from '../../api/types'

/**
 * Plain words for what the backend serves about a session. These translate;
 * they decide nothing: the kind, where a session stands, its format and what
 * may be done with it all come from the backend.
 */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function capital(s: string): string {
  return s ? s[0]!.toUpperCase() + s.slice(1) : s
}

/** The tag for a session's kind. A member names its part ("Rat study, part of a report") when the report says it. */
export function kindLabel(row: Pick<StudyRow, 'kind' | 'relations'>, memberKey?: string | null): string {
  switch (row.kind) {
    case 'study':
      return 'Study'
    case 'report': {
      const n = row.relations.members.length
      return `Report over ${n} ${n === 1 ? 'study' : 'studies'}`
    }
    case 'member':
      return memberKey ? `${capital(memberKey)} study, part of a report` : 'Study, part of a report'
    case 'companion':
      return 'Published content'
    case 'other':
      return 'Other session'
    default:
      return `Unknown kind ("${row.kind}")`
  }
}

export const KIND_COLOURS: Record<string, string> = {
  study: 'blue',
  report: 'purple',
  member: 'geekblue',
  companion: 'gold',
  other: 'default',
}

/** How many sessions of each kind, for a collapsed row ("+ 1 published content, 1 other session"). */
export function childCount(rows: Pick<StudyRow, 'kind'>[]): string {
  const order: [string, string, string][] = [
    ['study', 'study', 'studies'],
    ['report', 'report', 'reports'],
    ['member', 'study of the report', 'studies of the report'],
    ['companion', 'published content', 'published contents'],
    ['other', 'other session', 'other sessions'],
  ]
  const parts: string[] = []
  for (const [kind, one, many] of order) {
    const n = rows.filter((r) => r.kind === kind).length
    if (n > 0) parts.push(`${n} ${n === 1 ? one : many}`)
  }
  const unknown = rows.filter((r) => !order.some(([k]) => k === r.kind)).length
  if (unknown > 0) parts.push(`${unknown} of an unknown kind`)
  return parts.length ? `+ ${parts.join(', ')}` : ''
}

/** "2023-03" → "2023 Mar"; null when the date is not readable. */
export function publishedWhen(date: string | null | undefined): string | null {
  const m = date ? /^(\d{4})-(\d{2})/.exec(date) : null
  const month = m ? MONTHS[Number(m[2]) - 1] : undefined
  return m && month ? `${m[1]} ${month}` : null
}

export function publishedLabel(p: PublishedReport): { report: string; when: string | null } {
  return { report: p.report, when: publishedWhen(p.date) }
}

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

/** "2 days ago"; null when the time is not readable. */
export function relativeTime(iso: string | null | undefined, now = Date.now()): string | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  const s = Math.round((t - now) / 1000)
  const abs = Math.abs(s)
  if (abs < 45) return 'just now'
  if (abs < 3600) return rtf.format(Math.round(s / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(s / 3600), 'hour')
  if (abs < 86400 * 30) return rtf.format(Math.round(s / 86400), 'day')
  if (abs < 86400 * 365) return rtf.format(Math.round(s / (86400 * 30)), 'month')
  return rtf.format(Math.round(s / (86400 * 365)), 'year')
}

/** The exact local time, for a tooltip. */
export function exactTime(iso: string | null | undefined): string | null {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isNaN(t) ? null : new Date(t).toLocaleString()
}

/** "14 Oct 2026" */
export function dayOf(iso: string | null | undefined): string | null {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isNaN(t) ? null : new Date(t).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

/** Where the identity on file came from, in a person's words. */
export function identitySourceSay(source: IdentitySource | null | undefined): string {
  if (!source || source.kind === 'unknown') return 'On file; how it was set is not recorded.'
  if (source.kind === 'lookup') {
    const day = dayOf(source.confirmed_at)
    const said = `Confirmed by a person from a ${source.service ?? 'chemical'} lookup${day ? ` on ${day}` : ''}.`
    return source.casrn_from === 'person' ? `${said} CAS number stated by a person (the lookup gave none).` : said
  }
  if (source.kind === 'stated') return 'Stated by a person, not confirmed by a lookup.'
  return `Origin not recognised ("${source.kind}"); treat it as unchecked.`
}

/** Where the format's definition comes from. */
export function formatSourceSay(format: Pick<FormatSummary, 'source' | 'definition'>): string {
  switch (format.source) {
    case 'study': {
      const dir = format.definition.replace(/\/document$/, '')
      return `This study's own definition, under templates/${dir}/.`
    }
    case 'default':
      return 'The format for new studies.'
    case 'session':
      return "This session's own structure."
    case 'pinned':
      return "A fixed copy, saved with the study's pin."
    default:
      return `A source this page does not know ("${format.source}").`
  }
}

/** Turn a link the backend serves into a router path (inside /app) or leave it outside. */
export function appPath(href: string): { inApp: boolean; to: string } {
  if (href.startsWith('/app/')) return { inApp: true, to: href.slice('/app'.length) }
  if (href === '/app') return { inApp: true, to: '/' }
  return { inApp: false, to: href }
}

/** Why the format could not be read: the backend's note, or plain words when it sent none. */
export function formatUnreadSay(s: StudyRow): string {
  const note = s.notes.find((n) => n.code === 'damaged_session_file') ?? s.notes.find((n) => n.level === 'error')
  return note?.say ?? "The report format of this session could not be read."
}

