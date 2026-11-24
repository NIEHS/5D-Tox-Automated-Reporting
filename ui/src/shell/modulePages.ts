import type { ComponentType } from 'react'
import { ReviewPage } from '../modules/d1'
import { WritingPage } from '../modules/d2'
import { FilesPage } from '../modules/m2'
import { CombinedData } from '../modules/m3'
import { ProcessPage } from '../modules/p1'

/**
 * The modules that are built, by their route segment (kit/modules.ts); any
 * other segment shows the placeholder. The built pages stay under the one
 * `:module` route, so the study's frame still reads which page is open from
 * the route: its header and its menu depend on it.
 */
export const MODULE_PAGES: Record<string, ComponentType> = {
  files: FilesPage, // M2 Study files: bring in, check, say what each one is
  dataset: CombinedData, // M3 Combined data (the demo path's S1)
  process: ProcessPage, // P1 Process (the demo path's S2)
  writing: WritingPage, // D2 Written sections and its Citations tab (S3, S4)
  review: ReviewPage, // D1 Review the report: the Bookshelf view, approvals, the Word document (S5)
}

/** Whether the module of this route segment has a page (not the placeholder). */
export function isBuilt(slug: string): boolean {
  return slug in MODULE_PAGES
}
