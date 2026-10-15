import { setupWorker } from 'msw/browser'
import { createHandlers } from './handlers'

/** The development mock: a Service Worker, with paced run events. */
export const worker = setupWorker(...createHandlers({ stepDelayMs: 700 }))

export function startMockWorker() {
  return worker.start({
    serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
    onUnhandledFrame: 'bypass',
    quiet: true,
  })
}
