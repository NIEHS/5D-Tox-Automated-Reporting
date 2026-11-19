import { useParams } from 'react-router'
import { ReviewPage } from '../modules/d1'
import { WritingPage } from '../modules/d2'
import { CombinedData } from '../modules/m3'
import { ProcessPage } from '../modules/p1'
import { ModulePlaceholder } from './ModulePlaceholder'

/**
 * The modules that are built, by their route segment (kit/modules.ts); any
 * other segment shows the placeholder. The built pages stay under the one
 * `:module` route, so the study's frame still reads which page is open from
 * the route: its header and its menu depend on it.
 */
const MODULE_PAGES: Record<string, React.ComponentType> = {
  dataset: CombinedData, // M3 Combined data (the demo path's S1)
  process: ProcessPage, // P1 Process (the demo path's S2)
  writing: WritingPage, // D2 Written sections and its Citations tab (S3, S4)
  review: ReviewPage, // D1 Review the report: the Bookshelf view, approvals, the Word document (S5)
}

export function ModulePage() {
  const { module } = useParams()
  const Page = module ? MODULE_PAGES[module] : undefined
  return Page ? <Page /> : <ModulePlaceholder />
}
