import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationOptions,
} from '@tanstack/react-query'
import { getStudyState } from '../api/client'
import type { ApiError } from '../api/errors'
import type { StudyState } from '../api/types'

/**
 * The only reader of a study's workflow state (MODULES.md §4.1). A screen
 * learns the phase, the legal actions, the sections, the readiness and the
 * run from here, and never computes, guesses or stores any of them.
 *
 * While a run is in flight the state is re-read every few seconds, so the
 * "already running" wait ends by itself when the run does.
 */

export const IN_FLIGHT_POLL_MS = 3000

export function studyKey(id: string) {
  return ['study', id] as const
}

export function studyStateKey(id: string) {
  return ['study', id, 'state'] as const
}

export function useStudyState(id: string | undefined) {
  return useQuery<StudyState, ApiError>({
    queryKey: studyStateKey(id ?? ''),
    queryFn: ({ signal }) => getStudyState(id as string, signal),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const d = query.state.data
      return d?.exists && d.run?.in_flight ? IN_FLIGHT_POLL_MS : false
    },
  })
}

/** Re-read everything the app holds about a study. Call after every mutating call. */
export function invalidateStudy(queryClient: QueryClient, id: string): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: studyKey(id) })
}

export function useInvalidateStudy(): (id: string) => Promise<void> {
  const queryClient = useQueryClient()
  return (id: string) => invalidateStudy(queryClient, id)
}

/**
 * A mutation on a study that re-reads the study's state afterwards, whether
 * it succeeded or was refused (a refusal can follow a change made elsewhere).
 */
export function useStudyMutation<TData = unknown, TVars = void>(
  id: string,
  mutationFn: (vars: TVars) => Promise<TData>,
  options: Omit<UseMutationOptions<TData, ApiError, TVars>, 'mutationFn'> = {},
) {
  const queryClient = useQueryClient()
  return useMutation<TData, ApiError, TVars>({
    ...options,
    mutationFn,
    onSettled: async (...args) => {
      await invalidateStudy(queryClient, id)
      await options.onSettled?.(...args)
    },
  })
}
