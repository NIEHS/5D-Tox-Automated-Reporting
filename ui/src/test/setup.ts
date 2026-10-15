import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { resetMockDb } from '../api/mocks/handlers'
import { server } from '../api/mocks/node'

// antd needs these, which jsdom lacks.
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList
}
if (!('ResizeObserver' in window)) {
  class RO {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  ;(window as unknown as { ResizeObserver: typeof RO }).ResizeObserver = RO
}
// antd measures the scrollbar with getComputedStyle on pseudo-elements, which jsdom does not support.
const gcs = window.getComputedStyle.bind(window)
window.getComputedStyle = (elt: Element) => gcs(elt)

// A request no handler answers fails the test: every call must be in the contract.
beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  resetMockDb()
})
afterAll(() => server.close())
