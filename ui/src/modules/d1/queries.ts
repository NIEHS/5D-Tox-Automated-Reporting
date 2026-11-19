import { useQuery } from '@tanstack/react-query'
import { getReview, getSectionHistory, type Review, type SectionHistory } from '../../api/demoReview'
import type { ApiError } from '../../api/errors'
import { studyKey } from '../../kit/useStudyState'

/**
 * The reads of the review page. Every key is under a study's own key, so the
 * kit's invalidateStudy (after an act) re-reads them. Nothing here derives a
 * section's standing: the backend says.
 */

export function reviewKey(id: string) {
  return [...studyKey(id), 'review'] as const
}

export function historyKey(owner: string, key: string) {
  return [...studyKey(owner), 'sections', key, 'history'] as const
}

export function useReview(id: string | undefined) {
  return useQuery<Review, ApiError>({
    queryKey: reviewKey(id ?? ''),
    queryFn: ({ signal }) => getReview(id as string, signal),
    enabled: Boolean(id),
  })
}

/** A section's history, read from the session that holds the section. */
export function useSectionHistory(owner: string | undefined, key: string | undefined) {
  return useQuery<SectionHistory, ApiError>({
    queryKey: historyKey(owner ?? '', key ?? ''),
    queryFn: ({ signal }) => getSectionHistory(owner as string, key as string, signal),
    enabled: Boolean(owner && key),
  })
}
