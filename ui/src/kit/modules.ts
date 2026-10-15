import type { ModuleId } from '../api/types'

/**
 * The interface's modules (MODULES.md §3): where each lives in the app, and
 * its name in plain words. `fix` fields in the state and in refusals name a
 * module id; this is how they become links.
 */

export interface ModuleInfo {
  id: ModuleId
  /** the route segment under /studies/:id/ (absent for M1, which is /studies) */
  slug: string
  title: string
  /** one line: what a person does there */
  purpose: string
  group: 'data' | 'computation' | 'document'
}

export const MODULES: readonly ModuleInfo[] = [
  { id: 'M1', slug: '', title: 'Studies', purpose: 'Create, open or delete a study.', group: 'data' },
  { id: 'M2', slug: 'files', title: 'Study files', purpose: 'Bring in the data files, check them, and say what each one is.', group: 'data' },
  { id: 'M3', slug: 'dataset', title: 'Combined data', purpose: 'Combine the files into one dataset and review what it says.', group: 'data' },
  { id: 'M4', slug: 'facts', title: 'Study facts', purpose: 'State what the data cannot say: the design, the dose unit, the short name.', group: 'data' },
  { id: 'M5', slug: 'pins', title: 'Method and report definition', purpose: 'Choose the analysis method and the report definition.', group: 'data' },
  { id: 'M6', slug: 'data-review', title: 'Data review', purpose: 'Check that every animal is accounted for.', group: 'data' },
  { id: 'P1', slug: 'process', title: 'Process', purpose: 'Compute the statistics, the BMDs and the draft text.', group: 'computation' },
  { id: 'P2', slug: 'impact', title: 'What a change affects', purpose: 'See what a change would redo or undo before making it.', group: 'computation' },
  { id: 'D1', slug: 'review', title: 'Review the report', purpose: 'Read and approve each section; see what stops publishing.', group: 'document' },
  { id: 'D2', slug: 'writing', title: 'Written sections', purpose: 'Draft the Background, the Summary and the other written text.', group: 'document' },
  { id: 'D3', slug: 'preview', title: 'Preview and downloads', purpose: 'See the report as it will be delivered, and download it.', group: 'document' },
  { id: 'D4', slug: 'handoff', title: 'Word and Overleaf', purpose: 'Hand the report out for editing, bring the edits back, see what changed.', group: 'document' },
  { id: 'D5', slug: 'setup', title: 'Report setup', purpose: 'The report structure, its styles, its authors and publication details.', group: 'document' },
  { id: 'D6', slug: 'bookshelf', title: 'Bookshelf', purpose: 'The report as it will look on NCBI Bookshelf.', group: 'document' },
]

const BY_ID = new Map<string, ModuleInfo>(MODULES.map((m) => [m.id, m]))
const BY_SLUG = new Map<string, ModuleInfo>(MODULES.filter((m) => m.slug).map((m) => [m.slug, m]))

export function moduleById(id: string | null | undefined): ModuleInfo | undefined {
  return id ? BY_ID.get(id) : undefined
}

export function moduleBySlug(slug: string | undefined): ModuleInfo | undefined {
  return slug ? BY_SLUG.get(slug) : undefined
}

/** The router path of a module (inside the app's /app base). */
export function moduleRoute(id: ModuleId, studyId?: string): string | undefined {
  const m = BY_ID.get(id)
  if (!m) return undefined
  if (m.id === 'M1') return '/studies'
  if (!studyId) return undefined
  return `/studies/${encodeURIComponent(studyId)}/${m.slug}`
}

export function studyRoute(studyId: string): string {
  return `/studies/${encodeURIComponent(studyId)}`
}
