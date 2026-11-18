import type {
  Dataset,
  IntegrateSummary,
  KnowledgeBaseUse,
  ProcessSummary,
  ResultTables,
  StudyParameters,
  TableSources,
} from '../../../demoData'
import type { ErrorEnvelope, ExistingStudyState, RunEvent } from '../../../types'
import rawDatasetFinished from './dataset.finished.json'
import rawDatasetLiveReport from './dataset.live-report.json'
import rawDatasetCombined from './dataset.live.combined.json'
import rawDatasetProcessed from './dataset.live.processed.json'
import rawDatasetValidated from './dataset.live.validated.json'
import rawKbFinished from './knowledge-base.finished.json'
import rawKbCombined from './knowledge-base.live.combined.json'
import rawKbProcessed from './knowledge-base.live.processed.json'
import rawKbValidated from './knowledge-base.live.validated.json'
import rawRefusedIntegrate from './refusal.finished.integrate.json'
import rawRefusedProcess from './refusal.finished.process.json'
import rawRunInFlight from './refusal.live.run_in_flight.json'
import rawRefusedBeforeCombining from './refusal.live.validated.process.json'
import rawLiveBodyWeight from './sources.live.bm2_body-weight.json'
import rawLiveClinChem from './sources.live.bm2_clinical-chemistry.json'
import rawLiveClinObs from './sources.live.bm2_clinical-observations.json'
import rawLiveOrganWeight from './sources.live.bm2_organ-weight.json'
import rawLiveTissue from './sources.live.bm2_tissue-concentration.json'
import rawSourcesBodyWeight from './sources.finished.bm2_body-weight.json'
import rawSourcesClinChem from './sources.finished.bm2_clinical-chemistry.json'
import rawSourcesClinObs from './sources.finished.bm2_clinical-observations.json'
import rawSourcesOrganWeight from './sources.finished.bm2_organ-weight.json'
import rawSourcesTissue from './sources.finished.bm2_tissue-concentration.json'
import rawSourcesUnknown from './sources.finished.unknown.json'
import rawStateFinishedReport from './state.finished-report.json'
import rawStateFinished from './state.finished.json'
import rawStateLiveReport from './state.live-report.json'
import rawStateCombined from './state.live.combined.json'
import rawStateProcessed from './state.live.processed.json'
import rawStateValidated from './state.live.validated.json'
import rawStreamIntegrate from './stream.integrate.json'
import rawStreamCold from './stream.process.cold.json'
import rawStreamWarm from './stream.process.warm.json'
import rawParamsFinished from './study-parameters.finished.json'
import rawParamsCombined from './study-parameters.live.combined.json'
import rawParamsProcessed from './study-parameters.live.processed.json'
import rawParamsValidated from './study-parameters.live.validated.json'
import rawTablesFinished from './tables.finished.json'
import rawTablesCombined from './tables.live.combined.json'
import rawTablesProcessed from './tables.live.processed.json'
import rawTablesValidated from './tables.live.validated.json'

/**
 * The demo path's "Combined data" and "Process" pages, mocked from the
 * backend's OWN answers (written by scripts/fetch-demo-data-fixtures.mjs from
 * a backend running on a scratch store that holds the NIEHS-12 pair). Nothing
 * here is hand-written.
 *
 * | fixture              | session                 | how the scratch copy stood |
 * |----------------------|-------------------------|----------------------------|
 * | *_LIVE_VALIDATED     | DTXSID6020430_live_rat  | after `demo_copy reset`: files checked, nothing combined |
 * | *_LIVE_COMBINED      | DTXSID6020430_live_rat  | after POST …/integrate |
 * | *_LIVE_PROCESSED     | DTXSID6020430_live_rat  | after POST …/process |
 * | *_FINISHED           | DTXSID6020430_rat       | the finished report's rat study, as it is |
 * | STATE_*_REPORT       | DTXSID6020430(_live)    | the two reports of the pair |
 *
 * The event streams (stream.*.json) are the lines the backend sent for the
 * live rat study's acts, saved as they were received; each file says when.
 */

interface Saved<T> {
  status: number
  body: T
}

const body = <T,>(raw: unknown): T => (raw as Saved<T>).body

export const DEMO_LIVE_RAT = 'DTXSID6020430_live_rat'
export const DEMO_FINISHED_RAT = 'DTXSID6020430_rat'
export const DEMO_LIVE_REPORT = 'DTXSID6020430_live'
export const DEMO_FINISHED_REPORT = 'DTXSID6020430'

export const STATE_LIVE_VALIDATED = body<ExistingStudyState>(rawStateValidated)
export const STATE_LIVE_COMBINED = body<ExistingStudyState>(rawStateCombined)
export const STATE_LIVE_PROCESSED = body<ExistingStudyState>(rawStateProcessed)
export const STATE_FINISHED = body<ExistingStudyState>(rawStateFinished)
export const STATE_LIVE_REPORT = body<ExistingStudyState>(rawStateLiveReport)
export const STATE_FINISHED_REPORT = body<ExistingStudyState>(rawStateFinishedReport)

export const DATASET_LIVE_VALIDATED = body<Dataset>(rawDatasetValidated)
export const DATASET_LIVE_COMBINED = body<Dataset>(rawDatasetCombined)
export const DATASET_LIVE_PROCESSED = body<Dataset>(rawDatasetProcessed)
export const DATASET_FINISHED = body<Dataset>(rawDatasetFinished)
/** A report has no data of its own: the 409 the backend answers. */
export const REFUSAL_REPORT_HAS_NO_DATA = body<ErrorEnvelope>(rawDatasetLiveReport)

export const TABLES_LIVE_VALIDATED = body<ResultTables>(rawTablesValidated)
export const TABLES_LIVE_COMBINED = body<ResultTables>(rawTablesCombined)
export const TABLES_LIVE_PROCESSED = body<ResultTables>(rawTablesProcessed)
export const TABLES_FINISHED = body<ResultTables>(rawTablesFinished)

function byKey(raws: unknown[]): Record<string, TableSources> {
  return Object.fromEntries(
    raws.map((raw) => {
      const s = body<TableSources>(raw)
      return [s.key, s]
    }),
  )
}

export const SOURCES_FINISHED = byKey([rawSourcesBodyWeight, rawSourcesClinChem, rawSourcesClinObs, rawSourcesOrganWeight, rawSourcesTissue])
export const SOURCES_LIVE = byKey([rawLiveBodyWeight, rawLiveClinChem, rawLiveClinObs, rawLiveOrganWeight, rawLiveTissue])
/** A table the report does not have: the 404 the backend answers. */
export const REFUSAL_TABLE_NOT_FOUND = body<ErrorEnvelope>(rawSourcesUnknown)

export const PARAMETERS_LIVE_VALIDATED = body<StudyParameters>(rawParamsValidated)
export const PARAMETERS_LIVE_COMBINED = body<StudyParameters>(rawParamsCombined)
export const PARAMETERS_LIVE_PROCESSED = body<StudyParameters>(rawParamsProcessed)
export const PARAMETERS_FINISHED = body<StudyParameters>(rawParamsFinished)

export const KNOWLEDGE_BASE_LIVE_VALIDATED = body<KnowledgeBaseUse>(rawKbValidated)
export const KNOWLEDGE_BASE_LIVE_COMBINED = body<KnowledgeBaseUse>(rawKbCombined)
export const KNOWLEDGE_BASE_LIVE_PROCESSED = body<KnowledgeBaseUse>(rawKbProcessed)
export const KNOWLEDGE_BASE_FINISHED = body<KnowledgeBaseUse>(rawKbFinished)

/** The finished side of the pair refuses both acts before they start. */
export const REFUSAL_FINISHED_INTEGRATE = body<ErrorEnvelope>(rawRefusedIntegrate)
export const REFUSAL_FINISHED_PROCESS = body<ErrorEnvelope>(rawRefusedProcess)

/** Process before the files are combined: refused before it starts (the phase). */
export const REFUSAL_LIVE_VALIDATED_PROCESS = body<ErrorEnvelope>(rawRefusedBeforeCombining)
/** A second act while Process runs on the study: refused before it starts. */
export const REFUSAL_LIVE_RUN_IN_FLIGHT = body<ErrorEnvelope>(rawRunInFlight)

interface SavedStream {
  captured: string
  events: RunEvent[]
}

function summaryOf<T>(events: RunEvent[]): T {
  const last = events[events.length - 1]
  if (!last || last.event !== 'result') throw new Error('the saved stream does not end with a result')
  return last.summary as T
}

/** Combining the files, then the animal accounting. */
export const STREAM_INTEGRATE_OK = (rawStreamIntegrate as SavedStream).events
export const INTEGRATE_SUMMARY = summaryOf<IntegrateSummary>(STREAM_INTEGRATE_OK)

/** Process right after Combine: everything is computed. */
export const STREAM_PROCESS_LIVE = (rawStreamCold as SavedStream).events
export const PROCESS_SUMMARY_LIVE = summaryOf<ProcessSummary>(STREAM_PROCESS_LIVE)

/** Process again on the processed study: what did not change is reused. */
export const STREAM_PROCESS_WARM = (rawStreamWarm as SavedStream).events
export const PROCESS_SUMMARY_WARM = summaryOf<ProcessSummary>(STREAM_PROCESS_WARM)
