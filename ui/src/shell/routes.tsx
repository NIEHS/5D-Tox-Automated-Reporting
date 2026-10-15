import type { RouteObject } from 'react-router'
import { Navigate } from 'react-router'
import { AppFrame } from './AppFrame'
import { ModulePlaceholder } from './ModulePlaceholder'
import { NewStudy, StudiesList, StudyPage } from '../modules/m1'
import { NotFound } from './NotFound'
import { StudyFrame } from './StudyFrame'

/**
 * The app's routes, under the /app base (MODULES.md §5):
 *   /studies                 the studies (M1, S1)
 *   /studies/new             a new study (M1, S2)
 *   /studies/:id             a study's page (M1, S3; its workflow panels are the shell's)
 *   /studies/:id/:module     a module's page (placeholders until each is built)
 * A module replaces its placeholder by adding its route here, through the
 * orchestrator.
 */
export const routes: RouteObject[] = [
  {
    element: <AppFrame />,
    children: [
      { index: true, element: <Navigate to="/studies" replace /> },
      { path: 'studies', element: <StudiesList /> },
      { path: 'studies/new', element: <NewStudy /> },
      {
        path: 'studies/:id',
        element: <StudyFrame />,
        children: [
          { index: true, element: <StudyPage /> },
          { path: ':module', element: <ModulePlaceholder /> },
        ],
      },
      { path: '*', element: <NotFound /> },
    ],
  },
]
