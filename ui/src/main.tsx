import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider, createBrowserRouter } from 'react-router'
import { AppProviders } from './shell/AppProviders'
import { routes } from './shell/routes'

async function enableMocks() {
  // VITE_MOCK=0 talks to a real backend through the dev proxy; otherwise the
  // contract mocks answer. A production build never contains the mocks.
  if (!import.meta.env.DEV || import.meta.env.VITE_MOCK === '0') return
  const { startMockWorker } = await import('./api/mocks/browser')
  await startMockWorker()
}

const router = createBrowserRouter(routes, { basename: import.meta.env.BASE_URL.replace(/\/$/, '') })

void enableMocks().then(() => {
  const root = document.getElementById('root')
  if (!root) throw new Error('no #root element')
  createRoot(root).render(
    <StrictMode>
      <AppProviders>
        <RouterProvider router={router} />
      </AppProviders>
    </StrictMode>,
  )
})
