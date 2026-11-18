/**
 * Plain words for what the backend serves about the analysis. These
 * translate; they decide nothing.
 */

const PARAMETERS: Record<string, string> = {
  species: 'Species',
  strain: 'Strain',
  route: 'Route of exposure',
  vehicle: 'Vehicle',
  duration_days: 'Study duration (days)',
  dosing_days: 'Days of dosing',
  dosing_schedule: 'Dosing schedule',
  dose_unit: 'Dose unit',
}

/** The order the parameters are listed in; one this page does not know comes after, under its own name. */
export const PARAMETER_ORDER = Object.keys(PARAMETERS)

export function parameterWords(key: string): string {
  return PARAMETERS[key] ?? key
}

const KB_SOURCES: Record<string, string> = {
  default: "the application's default knowledge base",
  definition: "named by the report's definition",
  none: 'none is assigned',
}

export function knowledgeBaseSourceWords(source: string | null): string {
  if (!source) return 'origin not recorded'
  return KB_SOURCES[source] ?? `origin: ${source}`
}

const PIN_MODES: Record<string, string> = {
  fixed: 'fixed: it stays on this version',
  track: 'follows the newest version of its series',
}

export function pinModeWords(mode: string | null | undefined): string {
  if (!mode) return ''
  return PIN_MODES[mode] ?? mode
}

const PINNED_BY: Record<string, string> = {
  person: 'chosen by a person',
  default: 'set by default: nobody chose it',
  demo_copy: 'carried over from the finished report when the live copy was made',
}

export function pinnedByWords(by: string | null | undefined): string {
  if (!by) return 'not chosen'
  return PINNED_BY[by] ?? `set by ${by}`
}

const REVIEW_WHY: Record<string, string> = {
  numbers_changed: 'its numbers changed',
  wording_changed: 'its wording changed with the numbers',
}

export function reviewWhyWords(why: string): string {
  return REVIEW_WHY[why] ?? why
}

export const RUN_LABEL = 'Run the analysis'
export const RUN_NOTE = 'This takes about three minutes. The statistics, the benchmark doses, the tables, the figures and the drafted text are computed in one run.'
