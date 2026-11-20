import type { PartRecorded, RecordKind, WrittenBy } from '../../api/demoWriting'

/**
 * The words of the Written sections page. These translate what the backend
 * serves; they decide nothing. A value this page does not know is shown as
 * unknown, never passed off as one it does.
 */

export const PAGE_TITLE = 'Written sections'
export const TAB_SECTIONS = 'Written sections'
export const TAB_CITATIONS = 'Citations'

export const PAGE_PURPOSE =
  'Which text of the report the program builds from the data, which a language model writes, and for the model: what it was given. ' +
  'What was recorded is shown as recorded; what was not is said to be not recorded.'

export const BUILT_FROM_DATA = 'Built from the data'
export const WRITTEN_BY_MODEL = 'Written by a language model'
export const WRITER_NOT_RECORDED = 'Writer not recorded'

/** The tags of who wrote a part: one, or both for a part written by both. */
export function writtenByTags(writtenBy: WrittenBy | (string & {})): { label: string; color: string }[] {
  switch (writtenBy) {
    case 'data':
      return [{ label: BUILT_FROM_DATA, color: 'green' }]
    case 'model':
      return [{ label: WRITTEN_BY_MODEL, color: 'purple' }]
    case 'mixed':
      return [
        { label: BUILT_FROM_DATA, color: 'green' },
        { label: WRITTEN_BY_MODEL, color: 'purple' },
      ]
    case 'unrecorded':
      return [{ label: WRITER_NOT_RECORDED, color: 'default' }]
    default:
      return [{ label: `Unknown writer ("${writtenBy}")`, color: 'red' }]
  }
}

export const RECORD_WORDS: Record<RecordKind, { label: string; color: string }> = {
  as_sent: { label: 'As sent to the model', color: 'blue' },
  recorded: { label: 'Recorded with the result', color: 'cyan' },
  rebuilt: { label: 'Rebuilt from the recorded facts', color: 'gold' },
  not_recorded: { label: 'Not recorded', color: 'default' },
}

export function recordWords(record: RecordKind | (string & {})): { label: string; color: string } {
  return (
    (RECORD_WORDS as Record<string, { label: string; color: string } | undefined>)[record] ?? {
      label: `Unknown record ("${record}")`,
      color: 'red',
    }
  )
}

/** What is recorded about how a model's text was written, as short tags for the list. */
export function recordedTags(recorded: PartRecorded | null): { label: string; color: string }[] {
  if (!recorded) return []
  const prompt =
    recorded.prompt === 'as_sent'
      ? { label: 'Prompt recorded', color: 'blue' }
      : recorded.prompt === 'rebuilt'
        ? { label: 'Prompt not recorded; rebuilt from the recorded facts', color: 'gold' }
        : { label: 'Prompt not recorded', color: 'default' }
  const inputs =
    recorded.inputs === 'recorded' || recorded.inputs === 'as_sent'
      ? { label: 'Inputs recorded', color: 'cyan' }
      : { label: 'Inputs not recorded', color: 'default' }
  return [prompt, inputs]
}

export const NOT_WRITTEN_YET = 'Not written yet'
export const NO_MODEL = 'None: no language model is involved'
export const MODEL_NOT_RECORDED = 'Not recorded'

export const FINISHED_TITLE = 'This is the finished report of the pair. It is kept as it is.'
export const FINISHED_SAY = 'Writing is done on the live copy.'
export const FINISHED_LINK = 'Open this page on the live copy'
export const LIVE_LINK = 'Open this page on the finished report'

export const WRITE_BACKGROUND = 'Write the Background'
export const WRITE_SUMMARY = 'Write the Summary'
export const WAIT_BACKGROUND_TITLE = 'Writing the Background'
export const WAIT_BACKGROUND_NOTE =
  'Public sources about the chemical are gathered first; then the language model writes. The text is saved as a draft, and the prompt is kept with the run.'
export const WAIT_SUMMARY_TITLE = 'Wording the Summary'
export const WAIT_SUMMARY_NOTE =
  "The facts are picked from the study's results by rule; the language model words them. The run is kept with its prompt. The Summary in the report is not changed by the run."

export const TAKE_RUN = 'Take this text into the report'
export const TAKE_RUN_ELSEWHERE = "A run's text is taken into the report on the study's own page, on the live copy."

export const API_PAGE_LEAD = 'This step on the API page:'
export const SHOW_TEXT = 'Show the text'

export const REFERENCES_STUDY_NOTE = 'The report prints the reference list; a study of a report has none of its own:'
export const NO_REFERENCES = 'The printed report cites no source, so its reference list is empty.'
export const NO_LIST_YET = 'There is no list to show until the citations are checked.'
export const CHECK_CITATIONS = 'Check the citations'
export const CHECK_CITATIONS_AGAIN = 'Check the citations again'
export const WAIT_CITATIONS_TITLE = 'Checking the citations'
export const WAIT_CITATIONS_NOTE =
  'The report is read the way a reader gets it. Every citation must name a recorded source; every cited source must have a complete entry and a registered DOI or an address that answers. The reference list is derived from what the report prints. The result is recorded.'
export const PRINTED_TITLE = "The check of the report's citations"

/** What a finished check says of itself, from the run's summary (the backend's counts). */
export function checkOutcome(summary: Record<string, unknown>): string {
  const n = (key: string) => (typeof summary[key] === 'number' ? (summary[key] as number) : 0)
  const found =
    n('errors') > 0
      ? `${plural(n('errors'), 'error was', 'errors were')} found; each is listed below.`
      : n('warnings') > 0
        ? `No error was found. ${plural(n('warnings'), 'check', 'checks')} could not be made or ${n('warnings') === 1 ? 'needs' : 'need'} a look.`
        : 'No error was found.'
  return `The citations were checked and the result was recorded: ${plural(n('citations'), 'citation', 'citations')} in the printed report, ${plural(n('listed'), 'source', 'sources')} listed. ${found}`
}
export const NOT_JUDGED_TITLE = 'What this check does not judge'
export const NOT_LISTED_TITLE = 'Recorded sources the report does not list'
export const NOT_LISTED_SAY =
  'A source is listed only when text the report prints cites it. These are recorded for the report and not listed, each for the reason given.'
export const WRITERS_TITLE = 'What the models cited, against the sources supplied to them'
export const STATEMENTS_NOT_A_PAPER_BOILERPLATE =
  "This is a source of the report definitions' library (what a report of this kind cites whatever the study), not a paper of the knowledge base: there are no extracted statements."
export const STATEMENTS_NOT_A_PAPER_PERSON = 'This source was added by a person, not taken from the knowledge base: there are no extracted statements.'
export const STATEMENTS_TITLE = 'Statements the knowledge base extracted from this paper'
export const STATEMENTS_NONE = 'The knowledge base holds no statement extracted from this paper.'
export const STATEMENTS_UNREADABLE = 'The knowledge base could not be read, so its statements from this paper are not shown.'
export const STATEMENTS_NOT_A_PAPER =
  'This is a public source gathered for the Background, not a paper of the knowledge base: there are no extracted statements.'
export const NOT_CITED = 'No sentence cites this entry.'

export function capital(s: string): string {
  return s ? s[0]!.toUpperCase() + s.slice(1) : s
}

/** "Rat study" from a report's study key. */
export function studyLabel(key: string | null | undefined): string {
  return key ? `${capital(key)} study` : 'This study'
}

export function plural(n: number, one: string, many: string): string {
  return `${n.toLocaleString('en-US')} ${n === 1 ? one : many}`
}
