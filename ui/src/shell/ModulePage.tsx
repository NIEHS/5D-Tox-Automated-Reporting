import { useParams } from 'react-router'
import { ModulePlaceholder } from './ModulePlaceholder'
import { MODULE_PAGES } from './modulePages'

/** The page of the module the route names (modulePages.ts), or the placeholder. */
export function ModulePage() {
  const { module } = useParams()
  const Page = module ? MODULE_PAGES[module] : undefined
  return Page ? <Page /> : <ModulePlaceholder />
}
