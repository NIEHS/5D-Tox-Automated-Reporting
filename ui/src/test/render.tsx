import { QueryClient } from '@tanstack/react-query'
import { render, type RenderResult } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter, type RouteObject } from 'react-router'
import { AppProviders } from '../shell/AppProviders'
import { routes } from '../shell/routes'

/** A QueryClient for one test: no retries, nothing kept between tests. */
export function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  })
}

export interface Rendered extends RenderResult {
  user: ReturnType<typeof userEvent.setup>
  queryClient: QueryClient
  router: ReturnType<typeof createMemoryRouter>
}

/** Render a component inside the app's providers and a router, at `path`. */
export function renderWithApp(
  ui: React.ReactElement,
  { path = '/', routePath = '*', queryClient = testQueryClient(), extraRoutes = [] as RouteObject[] } = {},
): Rendered {
  const router = createMemoryRouter(
    [{ path: routePath, element: ui }, ...extraRoutes, { path: '*', element: <div>elsewhere</div> }],
    { initialEntries: [path] },
  )
  const user = userEvent.setup()
  const result = render(
    <AppProviders queryClient={queryClient} motion={false}>
      <RouterProvider router={router} />
    </AppProviders>,
  )
  return { ...result, user, queryClient, router }
}

/** Render the whole app (the real routes) at `path`. */
export function renderApp(path: string, queryClient = testQueryClient()): Rendered {
  const router = createMemoryRouter(routes, { initialEntries: [path] })
  const user = userEvent.setup()
  const result = render(
    <AppProviders queryClient={queryClient} motion={false}>
      <RouterProvider router={router} />
    </AppProviders>,
  )
  return { ...result, user, queryClient, router }
}
