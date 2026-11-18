import { useQuery } from '@tanstack/react-query'
import { getKnowledgeBase, getStudyParameters, type KnowledgeBaseUse, type StudyParameters } from '../../api/demoData'
import type { ApiError } from '../../api/errors'
import { studyKey } from '../../kit/useStudyState'

/**
 * Process's pre-flight reads. Their keys are under the study's key, so the
 * kit's invalidateStudy (when a wait ends) re-reads them too.
 */

export function useStudyParameters(id: string | undefined) {
  return useQuery<StudyParameters, ApiError>({
    queryKey: [...studyKey(id ?? ''), 'study-parameters'],
    queryFn: ({ signal }) => getStudyParameters(id as string, signal),
    enabled: Boolean(id),
  })
}

export function useKnowledgeBase(id: string | undefined) {
  return useQuery<KnowledgeBaseUse, ApiError>({
    queryKey: [...studyKey(id ?? ''), 'knowledge-base'],
    queryFn: ({ signal }) => getKnowledgeBase(id as string, signal),
    enabled: Boolean(id),
  })
}
