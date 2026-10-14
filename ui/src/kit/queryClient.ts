import { QueryClient } from '@tanstack/react-query'
import { ApiError } from '../api/errors'

/**
 * The app's one QueryClient. A refusal (4xx) is an answer, not a glitch, so
 * it is never retried; a server error or an unreachable server is retried
 * once.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
          return failureCount < 1
        },
        refetchOnWindowFocus: true,
        staleTime: 0,
      },
      mutations: { retry: false },
    },
  })
}
