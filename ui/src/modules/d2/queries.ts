import { useQuery } from '@tanstack/react-query'
import { getReferences, getWriting, getWritingPart, type PartDetail, type References, type WritingOverview } from '../../api/demoWriting'
import type { ApiError } from '../../api/errors'
import { studyKey } from '../../kit/useStudyState'

/**
 * The reads of the Written sections page. Every key is under the study's own
 * key, so the kit's invalidateStudy (after a wait or a mutation) re-reads
 * them. Nothing here derives who wrote a part or what is recorded: the
 * backend says.
 */

export function writingKey(id: string) {
  return [...studyKey(id), 'writing'] as const
}

export function partKey(studyId: string, part: string) {
  return [...studyKey(studyId), 'writing', part] as const
}

export function referencesKey(id: string) {
  return [...studyKey(id), 'references'] as const
}

export function useWriting(id: string | undefined) {
  return useQuery<WritingOverview, ApiError>({
    queryKey: writingKey(id ?? ''),
    queryFn: ({ signal }) => getWriting(id as string, signal),
    enabled: Boolean(id),
  })
}

/** One part, read from the session that holds it (`studyId`: a report for its Background, a study for the rest). */
export function useWritingPart(studyId: string | undefined, part: string | undefined) {
  return useQuery<PartDetail, ApiError>({
    queryKey: partKey(studyId ?? '', part ?? ''),
    queryFn: ({ signal }) => getWritingPart(studyId as string, part as string, signal),
    enabled: Boolean(studyId && part),
  })
}

export function useReferences(id: string | undefined, enabled = true) {
  return useQuery<References, ApiError>({
    queryKey: referencesKey(id ?? ''),
    queryFn: ({ signal }) => getReferences(id as string, signal),
    enabled: Boolean(id) && enabled,
  })
}
