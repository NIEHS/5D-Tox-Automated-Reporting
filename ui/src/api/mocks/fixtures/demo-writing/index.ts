import type { PartDetail, References, WritingOverview } from '../../../demoWriting'
import type { ErrorEnvelope, ExistingStudyState, RunEvent } from '../../../types'
import rawRefusalMember from './refusal.background_is_the_reports.json'
import rawRefusalFinished from './refusal.demo_reference.json'
import rawRefusalNoPart from './refusal.writing_part_not_found.json'

/**
 * The Written sections page's mock fixtures (the demo path, spec §4 S3, S4).
 *
 * Every JSON file here is the backend's OWN answer ({status, body}), saved by
 * tools/fetch_fixtures.py from a backend running on a scratch store that holds
 * the finished NIEHS-12 report (1,2-dichlorobenzene) and its live copy:
 *
 * | file | what |
 * |---|---|
 * | state.<id>.json | the read model of the finished report, its rat study, the live report and its rat study (with `demo` and `run`) |
 * | writing.<id>.json | GET …/writing of the same four |
 * | part.<id>.<part>.json | GET …/writing/{part}: the finished Background (no prompt recorded), the live report's (not written), the finished rat study's five kinds of part, the live rat study's Summary |
 * | references.<id>.json | GET …/references of the four |
 * | refusal.*.json | three refusals, each as answered before any work |
 *
 * Three answers are SHORTENED by the tool (nothing else is changed): the
 * liver interpretation's recorded text is cut to its first 3,000 characters
 * (its `chars` still says 57,229) and its papers to the first eight; each
 * reference list keeps the Background's sources and five papers per study.
 *
 * The event streams at the bottom are HAND-MADE in the §4.4 shape, with the
 * backend's own step names (as two real runs printed them); the
 * unreachable-source refusal is the backend's own answer in this sandbox.
 */

interface Saved<T> {
  status: number
  body: T
}

const states = import.meta.glob<Saved<ExistingStudyState>>('./state.*.json', { eager: true, import: 'default' })
const overviews = import.meta.glob<Saved<WritingOverview>>('./writing.*.json', { eager: true, import: 'default' })
const parts = import.meta.glob<Saved<PartDetail>>('./part.*.json', { eager: true, import: 'default' })
const references = import.meta.glob<Saved<References>>('./references.*.json', { eager: true, import: 'default' })

export const DEMO_FINISHED = 'DTXSID6020430'
export const DEMO_FINISHED_RAT = 'DTXSID6020430_rat'
export const DEMO_LIVE = 'DTXSID6020430_live'
export const DEMO_LIVE_RAT = 'DTXSID6020430_live_rat'

/** GET /api/v2/studies/{id}/state of the pair's sessions, by id */
export const DEMO_STATES: Record<string, ExistingStudyState> = Object.fromEntries(
  Object.values(states).map((s) => [s.body.id, s.body]),
)

/** GET /api/v2/studies/{id}/writing, by id */
export const DEMO_WRITING: Record<string, WritingOverview> = Object.fromEntries(
  Object.values(overviews).map((s) => [s.body.id, s.body]),
)

/** GET /api/v2/studies/{id}/writing/{part}, by "<id>/<part>" */
export const DEMO_PARTS: Record<string, PartDetail> = Object.fromEntries(
  Object.values(parts).map((s) => [`${s.body.study}/${s.body.key}`, s.body]),
)

/** GET /api/v2/studies/{id}/references, by id */
export const DEMO_REFERENCES: Record<string, References> = Object.fromEntries(
  Object.values(references).map((s) => [s.body.id, s.body]),
)

export const REFUSAL_DEMO_REFERENCE = (rawRefusalFinished as Saved<ErrorEnvelope>).body
export const REFUSAL_BACKGROUND_IS_THE_REPORTS = (rawRefusalMember as Saved<ErrorEnvelope>).body
export const REFUSAL_WRITING_PART_NOT_FOUND = (rawRefusalNoPart as Saved<ErrorEnvelope>).body

/**
 * The backend's answer when a hazard assessment cannot be reached
 * (safeguards.sources), as it ended a real run in this sandbox on 2026-11-18
 * (ATSDR is behind the firewall here).
 */
export const REFUSAL_BACKGROUND_SOURCES_UNREACHABLE: ErrorEnvelope = {
  error: {
    code: 'background_sources_unreachable',
    status: 503,
    message:
      'Background for DTXSID6020430_live not generated: ATSDR could not be reached (run where these sources are reachable, e.g. the NIEHS network)',
    say: "The Background can't be written now: ATSDR could not be reached, and without them it can neither state the chemical's toxicology nor say what is missing from it. Nothing was changed. Try again later, or where these sources are reachable (the NIEHS network).",
    fix: 'D1',
    details: { sources: 'ATSDR' },
  },
}

const GATHERING: [string, string][] = [
  ['chemical', 'Looking up the chemical'],
  ['source_1', 'Querying PubChem for chemical data'],
  ['source_2', 'Querying EPA CTX Hazard API'],
  ['source_3', 'Querying ATSDR ToxProfiles'],
  ['source_4', 'Querying EPA IRIS'],
  ['source_5', 'Querying OSHA/NIOSH exposure limits'],
  ['source_6', 'Querying EPA Safe Drinking Water Act'],
  ['source_7', 'Searching Semantic Scholar for mechanism papers'],
  ['source_8', 'Querying EPA CPDat for product/use data'],
  ['source_9', 'Building data gap analysis'],
]

function steps(rows: [string, string][], ms = 900): RunEvent[] {
  return rows.flatMap(([unit, say]): RunEvent[] => [
    { event: 'step', unit, status: 'computing', say },
    { event: 'step', unit, status: 'done', say, ms },
  ])
}

/** HAND-MADE: writing the Background, to its end. */
export const STREAM_BACKGROUND_OK: RunEvent[] = [
  ...steps(GATHERING),
  ...steps([['sources', 'Checking that the hazard assessments were reached']], 1),
  ...steps([['model', 'The language model writes the Background']], 48000),
  ...steps([['references', 'Checking that the text cites its sources']], 1),
  ...steps([['save', 'Saving the Background as a draft']], 20),
  ...steps([['record', 'Keeping the prompt with the run']], 5),
  {
    event: 'result',
    ok: true,
    summary: {
      paragraphs: 7,
      references: 5,
      untraced_citations: 0,
      outcome: 'written',
      version: 1,
      run_id: 'r20261118T180000-0a1b2c',
      model: 'claude-sonnet-4-6',
    },
  },
]

/** HAND-MADE around the backend's own refusal: the hazard assessments were not reached. */
export const STREAM_BACKGROUND_SOURCES_UNREACHABLE: RunEvent[] = [
  ...steps(GATHERING),
  { event: 'step', unit: 'sources', status: 'computing', say: 'Checking that the hazard assessments were reached' },
  { event: 'step', unit: 'sources', status: 'failed', say: 'Checking that the hazard assessments were reached', ms: 1 },
  { event: 'error', error: REFUSAL_BACKGROUND_SOURCES_UNREACHABLE.error },
]

/** HAND-MADE: a Summary run, to its end. */
export const STREAM_SUMMARY_OK: RunEvent[] = [
  ...steps([['facts', "Picking the facts from the study's results"]], 2100),
  ...steps([['model', 'The language model words the Summary; the run is kept with its prompt']], 21000),
  {
    event: 'result',
    ok: true,
    summary: {
      run_id: 'r20261118T181500-3d4e5f',
      template_version: 1,
      model: 'claude-sonnet-4-6',
      paragraphs: 4,
      unmatched_numbers: ['95'],
    },
  },
]
