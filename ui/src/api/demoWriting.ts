import { API_V2, getJson, sendJson, streamRun } from './client'
import type { RunEvent, WithNoop } from './types'

/**
 * The Written sections page and its Citations tab (the demo path, spec §4 S3
 * and S4): web_routes/v2_writing_routes.py. The types are the backend's
 * answers (ui_api.writing, ui_api.writing_references), kept in step by the
 * fixtures in mocks/fixtures/demo-writing/, which are real answers.
 */

const enc = encodeURIComponent

export const writingPaths = {
  writing: (id: string) => `${API_V2}/studies/${enc(id)}/writing`,
  part: (id: string, part: string) => `${API_V2}/studies/${enc(id)}/writing/${enc(part)}`,
  references: (id: string) => `${API_V2}/studies/${enc(id)}/references`,
  writeBackground: (id: string) => `${API_V2}/studies/${enc(id)}/writing/background`,
  runSummary: (id: string) => `${API_V2}/studies/${enc(id)}/writing/summary`,
  takeSummaryRun: (id: string, runId: string) =>
    `${API_V2}/studies/${enc(id)}/writing/summary/runs/${enc(runId)}/use`,
}

/** Who wrote a part: the program from the data, a language model, both, or the record does not say. */
export type WrittenBy = 'data' | 'model' | 'mixed' | 'unrecorded'

/**
 * How a served text relates to what the session recorded: sent to the model
 * as it stands; recorded with the result; built again from recorded inputs by
 * today's program; or not recorded (then there is no text).
 */
export type RecordKind = 'as_sent' | 'recorded' | 'rebuilt' | 'not_recorded'

export interface PartRecorded {
  prompt: RecordKind | (string & {})
  inputs: RecordKind | (string & {})
  say: string
}

export interface Subsection {
  key: string
  heading: string
  written_by: WrittenBy | (string & {})
}

export interface PartSummary {
  key: string
  /** the session that holds the part (a report for its Background, a study for the rest) */
  study: string
  title: string
  written_by: WrittenBy | (string & {})
  written_by_say: string
  model: string | null
  /** whether there is a text */
  exists: boolean
  approved: boolean
  /** null when no language model is involved */
  recorded: PartRecorded | null
  subsections?: Subsection[]
  /** the Summary: how many runs are recorded */
  run_count?: number
}

export interface ActVerdict {
  allowed: boolean
  say: string | null
  /** on the finished side of a demo pair: the live copy's session */
  counterpart?: string
}

export interface ApiPageLink {
  group: string
  title: string
  href: string
}

export interface StudyParts {
  key: string
  id: string
  exists: boolean
  parts: PartSummary[]
}

export interface WritingOverview {
  id: string
  kind: string
  /** what the citation check does and does not establish: shown as it stands */
  check_says: string
  api_page: ApiPageLink[]
  acts: { background: ActVerdict; summary: ActVerdict }
  parts: PartSummary[]
  /** a report over several studies: each study's parts */
  studies?: StudyParts[]
  /** a study of a report: where the Background is */
  report?: { id: string | null; part: { key: string; title: string } }
}

export interface TextBlock {
  key?: string
  heading: string | null
  written_by?: WrittenBy | (string & {})
  caption?: string | null
  paragraphs: string[]
}

export interface GivenItem {
  id: string
  title: string
  record: RecordKind | (string & {})
  say: string
  /** null when nothing was recorded */
  text: string | null
  chars: number
}

export interface CheckItem {
  token: string | null
  sentence: string | null
  what: string | null
}

export interface PartCitationCheck {
  sources_supplied: number | null
  sources_cited: number
  untraced: number
  /** whether an untraced citation is removed from the printed text */
  removed: boolean
  say: string
  items: CheckItem[]
}

export interface PaperOffered {
  token: string
  title: string | null
  year: number | null
  venue: string | null
  doi: string | null
  citation_count: number | null
  genes: string[]
  cited: boolean
}

export interface SummaryRun {
  run_id: string
  at: string | null
  template_version: number | null
  model: string | null
  prompt: string | null
  paragraphs: string[]
  unmatched_numbers: string[]
  /** whether this run's text is the Summary now in the report */
  in_use: boolean
}

export interface PartDetail extends PartSummary {
  text: TextBlock[]
  /** how to read the text shown */
  text_say?: string
  /** why there is no text, when there is none */
  say?: string | null
  given: GivenItem[]
  /** the Background: its reference list as printed */
  references?: string[]
  citation_check?: PartCitationCheck | null
  /** the Background: the recorded run whose text this is */
  run?: { run_id: string; at: string | null } | null
  /** an interpretation: the knowledge base recorded with it */
  knowledge_base?: { name: string | null; sha256: string | null } | null
  papers_offered?: PaperOffered[]
  /** the Summary */
  template?: { version: number; in_use_version: number | null }
  unmatched_numbers?: string[] | null
  unmatched_say?: string
  runs?: SummaryRun[]
}

export interface CitedIn {
  part: string
  part_title: string
  study: string | null
  study_id: string
  sentences: string[]
}

export interface ReferenceEntry {
  /** the number as printed */
  n: number
  kind: 'background_source' | 'paper' | (string & {})
  /** the study's key in the report ("rat"); null for the Background's sources */
  study: string | null
  study_id: string
  /** a Background source, as printed */
  text: string | null
  url: string | null
  title: string | null
  year: number | null
  venue: string | null
  doi: string | null
  /** the genes a paper was offered for */
  genes: string[]
  cited_in: CitedIn[]
  /** the knowledge base's statements from the paper; null when it has none to read from */
  statements: string[] | null
}

export interface CheckPart {
  where: 'background' | 'interpretations' | (string & {})
  study: string | null
  study_id: string
  untraced: number
  removed: boolean
  say: string
  items: CheckItem[]
  edited_text_warnings: number
}

export interface KnowledgeBaseUsed {
  study: string | null
  study_id: string
  name: string | null
  recorded_name: string | null
  /** whether the knowledge base read now is the one recorded with the results */
  same: boolean
  usable: boolean
}

export interface References {
  id: string
  kind: string
  check_says: string
  numbering_say: string
  report?: { id: string | null }
  entries: ReferenceEntry[]
  check: { untraced: number; removed: number; say: string; parts: CheckPart[] }
  knowledge_bases: KnowledgeBaseUsed[]
}

export interface TakeRunResult {
  ok: boolean
  version: number | null
  outcome: string
}

/** The written parts of a report or a study. No side effect. */
export function getWriting(id: string, signal?: AbortSignal): Promise<WritingOverview> {
  return getJson<WritingOverview>(writingPaths.writing(id), signal)
}

/** One written part in full, from the session that holds it. No side effect. */
export function getWritingPart(studyId: string, part: string, signal?: AbortSignal): Promise<PartDetail> {
  return getJson<PartDetail>(writingPaths.part(studyId, part), signal)
}

/** The reference list as printed, with what cites each entry. No side effect. */
export function getReferences(id: string, signal?: AbortSignal): Promise<References> {
  return getJson<References>(writingPaths.references(id), signal)
}

/** Write the Background and save it as a draft: a run's events (§4.4). */
export function writeBackground(id: string): AsyncGenerator<RunEvent> {
  return streamRun(writingPaths.writeBackground(id))
}

/** Have the model word the Summary, as a run: a run's events (§4.4). The report is not changed. */
export function runSummary(id: string): AsyncGenerator<RunEvent> {
  return streamRun(writingPaths.runSummary(id))
}

/** Make a recorded Summary run's text the report's Summary. */
export function takeSummaryRun(id: string, runId: string): Promise<WithNoop<TakeRunResult>> {
  return sendJson<TakeRunResult>('POST', writingPaths.takeSummaryRun(id, runId))
}
