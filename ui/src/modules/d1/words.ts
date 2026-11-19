import type { SectionEvent } from '../../api/demoReview'

/**
 * The words of the review page. They translate what the backend serves and
 * decide nothing: whether a section can be approved, why not, where it is in
 * the book and what stops publishing are all the backend's.
 */

export const PAGE_TITLE = 'Review the report'
export const PAGE_PURPOSE =
  'The report as the NCBI Bookshelf would show it, with its sections beside it. A section is approved as it stands, or reopened with a reason; ' +
  'approving never changes its text.'

export const API_PAGE_LEAD = 'This step on the API page:'

export const BOOK_TITLE = 'The report as the Bookshelf shows it'
export const BOOK_BUILDING = 'The report is being built for showing.'
export const BOOK_BUILDING_NOTE =
  'This takes up to a minute when the report changed since it was last shown; otherwise it opens at once.'
export const BOOK_NOT_SHOWN_TITLE = 'The report cannot be shown'
export const BOOK_NO_BOOK_TITLE = 'There is no report to show yet'
export const BOOK_AGAIN = 'Try again'
export const BOOK_STALE_NOTE =
  'The book is not shown again after an approval or a reopening: neither changes the text.'

export const RAIL_TITLE = 'Sections'
export const RAIL_HELP = 'Choosing a section scrolls the book to where it starts.'
export const ANCHORS_ERROR_TITLE = 'The sections cannot be scrolled to'

export const APPROVE = 'Approve'
export const REOPEN = 'Reopen'
export const HISTORY = 'History'

export const NO_ANCHOR = 'This section has no place of its own in the book, so the book cannot be scrolled to it.'
export const ANCHOR_NOT_IN_BOOK = 'This section was not found in the book as it is shown now.'
export const BOOK_NOT_READY = 'The book is not shown yet, so it cannot be scrolled.'

export const FINISHED_SIDE_TITLE = 'Nothing is approved or reopened here'
export const OPEN_ON_LIVE_COPY = 'Open this page on the live copy'

export const ACT_REFUSED_TITLE = (act: string, title: string) => `“${title}” was not ${act}`
export const ACT_NOOP_TITLE = 'Nothing was changed'

export const REOPEN_TITLE = (title: string) => `Reopen “${title}”`
export const REOPEN_EXPLAIN =
  'The section stops counting as approved. Its text is not changed, and it stays kept from the machine. The reason is kept in the section’s history.'
export const REOPEN_REASON_LABEL = 'Reason for reopening'
export const REOPEN_REASON_MISSING = 'A reason is required: it is kept in the section’s history.'
export const REOPEN_OK = 'Reopen the section'
export const CANCEL = 'Cancel'

export const HISTORY_TITLE = (title: string) => `History of “${title}”`
export const HISTORY_VERSIONS = 'Versions'
export const HISTORY_EVENTS = 'What happened, oldest first'
export const HISTORY_ERROR_TITLE = 'The history could not be read'
export const HISTORY_EMPTY = 'Nothing is recorded for this section.'
export const CURRENT = 'current'

export const PUBLISH_TITLE = 'What stands between the report and publishing'
export const NO_STUDY_READINESS = 'The application did not say what stops publishing for this part.'

export const WORD_BUTTON = 'Make the Word document'
export const PDF_BUTTON = 'Make the PDF'
export const WORD_WAIT_TITLE = 'Making the Word document'
export const PDF_WAIT_TITLE = 'Making the PDF'
export const WORD_WAIT_NOTE =
  'The Word document is being made; this takes about a minute when the report changed since it was last made. It is saved by the browser when it is ready.'
export const PDF_WAIT_NOTE =
  'The PDF is being made from the Word document; this takes about a minute when the report changed since it was last made. It is saved by the browser when it is ready.'
export const EDITED_IN_WORD = 'Text is edited in Word; the application does not edit text.'
export const SAVED = (filename: string) => `${filename} was handed to the browser to save.`
export const NO_DOWNLOADS = 'The Word document and the PDF are made once the report can be shown.'

/** A version's standing, as recorded (the version status of workflow.section_writes). */
const STATUS_WORDS: Record<string, string> = {
  draft: 'Draft',
  blessed: 'Approved',
  working: 'Reopened, not approved',
  'needs-re-bless': 'Changed since it was approved',
  discarded: 'Discarded',
}

export function statusWords(status: string | null | undefined): string {
  if (!status) return 'Standing not recorded'
  return STATUS_WORDS[status] ?? `Recorded as “${status}”`
}

/** What was done, as recorded (the act of a history line). An act this page does not know is shown as recorded. */
const ACT_WORDS: Record<string, string> = {
  materialize: 'Built from the results of Process',
  summary: 'The Summary was built by rule from the results of Process',
  background: 'The Background was written by the language model',
  use_run: 'A run of the language model was taken as the text',
  save: 'Saved',
  accept: 'Approved as it stood',
  release: 'Reopened',
  restore: 'An earlier version was brought back',
  discard: 'Discarded',
  pool_reset: 'Discarded when the study’s files were cleared',
}

export function actWords(event: Pick<SectionEvent, 'act' | 'cause'>): string {
  if (event.cause === 'hold') return 'Kept as it was: the machine did not replace it'
  if (event.cause === 'reprocess') return 'The study was processed again; the section is to be read again'
  return ACT_WORDS[event.act] ?? `Recorded as “${event.act}”`
}

const ACTOR_WORDS: Record<string, string> = { person: 'a person', system: 'the application' }

export function actorWords(actor: string | null | undefined): string {
  if (!actor) return 'not recorded'
  return ACTOR_WORDS[actor] ?? actor
}

/** A recorded time in the reader's own date and time format; the text as recorded when it is not a time. */
export function whenWords(ts: string | null | undefined): string {
  if (!ts) return 'time not recorded'
  const t = Date.parse(ts)
  return Number.isNaN(t) ? ts : new Date(t).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}
