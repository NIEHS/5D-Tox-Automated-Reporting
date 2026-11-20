import type { BenchmarkDoseSource, Bmr, ChainStop, ConvertedFrom } from '../../api/demoData'

/**
 * Plain words for what the backend serves about a study's files and its
 * dataset. These translate; they decide nothing. A value this page does not
 * know is shown as it was served, never passed off as one it knows.
 */

const FILE_TYPES: Record<string, string> = {
  xlsx: 'Workbook',
  txt: 'Converted table',
  csv: 'Converted table',
  bm2: 'BMDExpress project',
}

/** A list the package states (not a table converted from a workbook). */
const LISTS: Record<string, string> = {
  excluded_values: 'List',
}

export function fileTypeWords(fileType: string | null, dataType?: string | null): string {
  if (dataType && LISTS[dataType]) return LISTS[dataType]
  if (!fileType) return 'Not recognized'
  return FILE_TYPES[fileType] ?? fileType
}

const DATA_TYPES: Record<string, string> = {
  tox_study: 'Animal data',
  gene_expression: 'Gene expression',
  removal_reasons: 'Removal reasons',
  excluded_values: 'Values left out of the analysis',
}

export const LEFT_OUT_TITLE = 'Values left out of the analysis'
export const LEFT_OUT_SAY =
  'The study\u2019s package names these values and why. They are not in the statistics or the benchmark dose inputs, and the tables note each.'

export function dataTypeWords(dataType: string | null): string {
  if (!dataType) return 'Not recognized'
  return DATA_TYPES[dataType] ?? dataType
}

const FILE_KINDS: Record<string, string> = {
  xlsx: 'workbook',
  txt_csv: 'converted table',
  bm2: 'BMDExpress project',
}

export function fileKindWords(kind: string | null | undefined): string {
  if (!kind) return 'file'
  return FILE_KINDS[kind] ?? kind
}

export function capital(s: string | null | undefined): string {
  return s ? s[0]!.toUpperCase() + s.slice(1) : ''
}

export function doseWords(groups: number[], unit: string | null): string {
  if (groups.length === 0) return ''
  return `${groups.join(', ')}${unit ? ` ${unit}` : ''}`
}

/** Which record names the workbook a table was converted from. */
export function recordedInWords(c: ConvertedFrom): string {
  if (c.recorded_in === 'sidecar') return "recorded in the table's own notes"
  if (c.recorded_in === 'file_check') return 'recorded by the file check'
  return `recorded in "${c.recorded_in}"`
}

export function bmrWords(bmr: Bmr | null | undefined): string | null {
  if (!bmr || bmr.factor === null || bmr.factor === undefined) return null
  if (bmr.type === 'SD') return `${bmr.factor} standard deviation${bmr.factor === 1 ? '' : 's'} from the mean`
  if (bmr.type === 'RD') return `a ${Math.round(bmr.factor * 1000) / 10}% relative deviation from the control mean`
  return `${bmr.factor} (${bmr.type})`
}

/** Where a table's benchmark doses come from, from the record the analysis kept. */
export function bmdSourceWords(b: BenchmarkDoseSource): { label: string; explain: string } {
  switch (b.source) {
    case 'recorded':
      return {
        label: "The study's own analysis",
        explain:
          "The benchmark doses printed are those of the study's own BMDExpress analysis, which is among its files. " +
          'Where that analysis left an endpoint without one, a fit made by this application fills it, under the same settings.',
      }
    case 'inferred':
      return {
        label: 'Fit by this application',
        explain:
          "No benchmark dose analysis of this assay is among the study's files, so the doses were fit by this application " +
          "at the benchmark response of the study's analysis method.",
      }
    case 'engine':
      return {
        label: "Computed by the method's own engine",
        explain: "Every benchmark dose of this assay was computed by the engine the study's analysis method names, with that engine's own settings.",
      }
    default:
      return {
        label: `Origin unknown ("${b.source}")`,
        explain: 'The application gave an origin this page does not know. Treat these benchmark doses as unchecked.',
      }
  }
}

export const BMD_NOT_RECORDED =
  'Not recorded: the last analysis kept no record of how the benchmark doses of this assay and sex were computed.'

/** A table the dataset holds no experiment for, and records the files of. */
export const COUNTED_FROM_FILES =
  'None: this table is counted from the file below, which the dataset names. The dataset holds no experiment for it.'

/** A row the builders' naming gives no endpoint for. */
export const NO_ENDPOINT_FOR_ROW =
  "The row is built from the experiment's endpoints, and the rule that names which of them does not cover this row."

/** Where the chain from a table to its files stops, when a record is missing. */
export function stopWords(stop: ChainStop | (string & {}), assay: string | null, sex: string): string {
  switch (stop) {
    case 'dataset':
      return "The study's files are not combined into a dataset now, so the table cannot be followed further back."
    case 'experiment':
      return `The dataset has no experiment under the assay name "${assay ?? ''}" for the sex "${sex}". Which data this table was built from is not recorded where this page can follow it.`
    case 'file':
      return 'The dataset does not name the file the data of this assay was taken from.'
    case 'workbook':
      return 'Nothing records which workbook the file was converted from.'
    default:
      return `The chain stops at a link this page does not know ("${stop}").`
  }
}

/** True when a printed benchmark dose is a number (not a dash, "NA" or "ND"). */
export function isNumberPrinted(text: string | null): boolean {
  return text !== null && text.trim() !== '' && !Number.isNaN(Number(text.replace(/,/g, '')))
}
