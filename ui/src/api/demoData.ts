import { API_V2, getJson, streamRun } from './client'
import type { RunEvent } from './types'

/**
 * The demo path's "Combined data" (M3) and "Process" (P1) pages:
 * docs/ui-redesign/modules/demo/spec.md §4 S1 and S2. The backend is
 * web_routes/v2_data_routes.py (ui_api.dataset, ui_api.process_run). The two
 * reads at the end are routes that existed before the new interface; they
 * answer outside /api/v2, so a failure of theirs is not an envelope.
 */

const enc = encodeURIComponent

export const demoDataPaths = {
  dataset: (id: string) => `${API_V2}/studies/${enc(id)}/dataset`,
  integrate: (id: string) => `${API_V2}/studies/${enc(id)}/integrate`,
  tables: (id: string) => `${API_V2}/studies/${enc(id)}/tables`,
  tableSources: (id: string, key: string) => `${API_V2}/studies/${enc(id)}/tables/${enc(key)}/sources`,
  process: (id: string) => `${API_V2}/studies/${enc(id)}/process`,
  studyParameters: (id: string) => `/api/workflow/${enc(id)}/study-parameters`,
  knowledgeBase: (id: string) => `/api/session/${enc(id)}/knowledge-base`,
}

// ---------------------------------------------------------------------------
// GET …/dataset
// ---------------------------------------------------------------------------

/** The workbook a converted table was made from, and which record says so. */
export interface ConvertedFrom {
  filename: string
  recorded_in: 'sidecar' | 'file_check' | (string & {})
}

/** One file of the study, as the file check recorded it. */
export interface DatasetFile {
  filename: string
  file_type: string | null
  assay: string | null
  data_type: string | null
  sexes: string[]
  animals: number
  dose_groups: number[]
  dose_unit: string | null
  converted_from: ConvertedFrom | null
}

/** The file the dataset says an assay's data was taken from. */
export interface TakenFrom {
  filename: string
  kind: 'xlsx' | 'txt_csv' | 'bm2' | (string & {}) | null
}

/** One assay's chain, as the file check recorded it. */
export interface AssayChain {
  key: string
  assay: string | null
  data_type: string | null
  workbook: string | null
  tables: { filename: string; converted_from: ConvertedFrom | null }[]
  bm2: string | null
  /** only once the files are combined; null: the dataset names no file */
  taken_from?: TakenFrom | null
}

export interface DatasetExperiment {
  name: string | null
  assay: string | null
  data_type: string | null
  sex: string | null
  organ: string | null
  endpoints: number
  animals: number
  taken_from: TakenFrom | null
  /** the study's own benchmark dose analysis of this experiment is in the dataset */
  own_benchmark_doses: boolean
}

export interface Accounting {
  study_number: string | null
  total_animals: number | null
  core_count: number | null
  biosampling_count: number | null
  dose_groups: number[]
  /** {dose: {sex: animals}} */
  dose_design: Record<string, Record<string, number>>
  /** {assay: ids seen per kind of file} */
  assay_coverage: Record<string, { xlsx?: number; txt_csv?: number; bm2?: number }>
  problems: unknown[]
}

export interface Dataset {
  id: string
  files_checked: boolean
  files: DatasetFile[]
  assays: AssayChain[]
  integrated: boolean
  integrated_at: string | null
  experiments: DatasetExperiment[] | null
  own_bmd_analysis: { analyses: number; experiments: string[] } | null
  accounting: Accounting | null
}

export function getDataset(id: string, signal?: AbortSignal): Promise<Dataset> {
  return getJson<Dataset>(demoDataPaths.dataset(id), signal)
}

/** What the integrate run's `result` carries. */
export interface IntegrateSummary {
  experiments?: number | null
  own_bmd_analyses?: number | null
  data_approval_withdrawn?: boolean
  accounting_problems?: number
}

/** Combine the files, then account for the animals: the §4.4 event stream. */
export function runIntegrate(id: string): AsyncGenerator<RunEvent> {
  return streamRun(demoDataPaths.integrate(id))
}

// ---------------------------------------------------------------------------
// GET …/tables, …/tables/{key}/sources
// ---------------------------------------------------------------------------

export interface ResultTable {
  key: string
  title: string | null
  assay: string | null
  caption: string | null
  sexes: string[]
  rows: number
  has_benchmark_doses: boolean
}

export interface ResultTables {
  id: string
  tables: ResultTable[]
}

export function getTables(id: string, signal?: AbortSignal): Promise<ResultTables> {
  return getJson<ResultTables>(demoDataPaths.tables(id), signal)
}

/** A benchmark response: standard deviations from the mean, or a relative deviation. */
export interface Bmr {
  type: 'SD' | 'RD' | (string & {})
  factor: number | null
}

/** The study's own BMDExpress analysis, as its notes record it (null: no such note). */
export interface RecordedAnalysis {
  software: string | null
  selection: string | null
  models: string[]
  constant_variance: boolean | null
}

/** Where a table's benchmark doses come from (the record of ADR-0036). */
export interface BenchmarkDoseSource {
  source: 'recorded' | 'inferred' | 'engine' | (string & {})
  bmr: Bmr | null
  constant_variance?: boolean | null
  models?: string[] | null
  analysis?: RecordedAnalysis
}

export interface SourceFile extends TakenFrom {
  file_type: string | null
  converted_from: ConvertedFrom | null
}

export interface SourceRow {
  label: string | null
  heading: boolean
  count_row: boolean
  /**
   * The endpoints of the experiment(s) the row is built from, and how where it
   * is computed ("the organ's weight divided by the terminal body weight");
   * null for a heading, a count row, a row of a counted table, and a row the
   * builders' naming gives no endpoint for.
   */
  built_from: { endpoints: string[]; how: string | null } | null
  /** whether the row is followed to an endpoint; null where the question does not arise */
  endpoint_in_dataset: boolean | null
  /** as printed; null when the table prints no benchmark dose */
  bmd: string | null
  bmdl: string | null
}

/** The first link of the chain that is not recorded; null when the chain is whole. */
export type ChainStop = 'dataset' | 'experiment' | 'file' | 'workbook'

export interface TableSexSources {
  sex: string
  experiments: { name: string | null; organ: string | null; endpoints: number; animals: number; endpoint_names: string[] | null }[]
  files: SourceFile[]
  /**
   * The dataset holds no experiment for this table and records the files it
   * is counted from instead (Clinical Observations): `files` are those.
   */
  counted_from_files: boolean
  stops: ChainStop | (string & {}) | null
  benchmark_dose: BenchmarkDoseSource | null
  rows: SourceRow[]
}

export interface TableSources {
  id: string
  key: string
  title: string | null
  assay: string | null
  caption: string | null
  has_benchmark_doses: boolean
  /** false: the last analysis left no record of the benchmark dose method */
  benchmark_dose_recorded: boolean
  sexes: TableSexSources[]
}

export function getTableSources(id: string, key: string, signal?: AbortSignal): Promise<TableSources> {
  return getJson<TableSources>(demoDataPaths.tableSources(id, key), signal)
}

// ---------------------------------------------------------------------------
// POST …/process
// ---------------------------------------------------------------------------

export interface UnitSaid {
  unit: string
  say: string
}

/** What the Process run's `result` carries. Every field is what the run recorded. */
export interface ProcessSummary {
  test_article?: string
  units?: { recorded: boolean; computed?: UnitSaid[]; reused?: UnitSaid[] }
  analysis?: { apical_sections: number; genomics_sections: number; methods: boolean }
  result_sections?: { written: string[]; unchanged: string[] }
  approvals_affected?: { needs_review: { key: string; why: string }[]; held: string[] }
  summary?: { written: boolean; paragraphs: number; held: { why: string; version?: number | null } | null }
  /** null: the run wrote no reference list */
  citations_removed?: number | null
}

/** Run the analysis, then write its results sections and its Summary: the §4.4 event stream. */
export function runAnalysis(id: string): AsyncGenerator<RunEvent> {
  return streamRun(demoDataPaths.process(id))
}

// ---------------------------------------------------------------------------
// The pre-flight's reads (routes older than the new interface)
// ---------------------------------------------------------------------------

/** GET /api/workflow/{id}/study-parameters (pipeline.study_parameters). */
export interface StudyParameters {
  complete: boolean
  values: Record<string, string | number | null>
  /** where each value comes from: recorded (the data), stated (a person), inferred */
  sources: Record<string, string>
  missing: string[]
  conflicting: Record<string, unknown>
  not_applicable: string[]
  problems: string[]
}

export function getStudyParameters(id: string, signal?: AbortSignal): Promise<StudyParameters> {
  return getJson<StudyParameters>(demoDataPaths.studyParameters(id), signal)
}

/** GET /api/session/{id}/knowledge-base (knowledge_base.registry). */
export interface KnowledgeBaseUse {
  name: string | null
  /** who chose it: the study, its report definition, or the default */
  source: string | null
  usable: boolean
  problem: string | null
  capabilities?: string[]
  processed_with?: { name: string | null; sha256?: string | null } | null
}

export function getKnowledgeBase(id: string, signal?: AbortSignal): Promise<KnowledgeBaseUse> {
  return getJson<KnowledgeBaseUse>(demoDataPaths.knowledgeBase(id), signal)
}
