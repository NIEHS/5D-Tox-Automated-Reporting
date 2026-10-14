import type { RouteObject } from 'react-router'
import { Navigate } from 'react-router'
import { AppFrame } from './AppFrame'
import { ModulePlaceholder } from './ModulePlaceholder'
import { NotFound } from './NotFound'
import { StudiesPage } from './StudiesPage'
import { StudyFrame } from './StudyFrame'
import { StudyOverview } from './StudyOverview'

/**
 * The app's routes, under the /app base (MODULES.md §5):
 *   /studies                 the studies (M1)
 *   /studies/:id             a study's overview
 *   /studies/:id/:module     a module's page (placeholders until each is built)
 * A module replaces its placeholder by adding its route here, through the
 * orchestrator.
 */
export const routes: RouteObject[] = [
  {
    element: <AppFrame />,
    children: [
      { index: true, element: <Navigate to="/studies" replace /> },
      { path: 'studies', element: <StudiesPage /> },
      {
        path: 'studies/:id',
        element: <StudyFrame />,
        children: [
          { index: true, element: <StudyOverview /> },
          { path: ':module', element: <ModulePlaceholder /> },
        ],
      },
      { path: '*', element: <NotFound /> },
    ],
  },
]
