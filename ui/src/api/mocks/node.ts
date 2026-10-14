import { setupServer } from 'msw/node'
import { createHandlers } from './handlers'

/** The test mock: intercepts fetch in Node; events are not paced. */
export const server = setupServer(...createHandlers({ stepDelayMs: 0 }))
