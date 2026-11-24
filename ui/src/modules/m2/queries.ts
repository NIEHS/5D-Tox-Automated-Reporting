import { useQuery } from '@tanstack/react-query'
import { getFiles, type FilesView } from '../../api/files'
import type { ApiError } from '../../api/errors'
import { studyKey } from '../../kit/useStudyState'

/**
 * The Study files page's read. Its key is under the study's key, so the kit's
 * invalidateStudy (after every act, and when a wait ends) re-reads it too.
 */

export function filesKey(id: string) {
  return [...studyKey(id), 'files'] as const
}

export function useFiles(id: string | undefined) {
  return useQuery<FilesView, ApiError>({
    queryKey: filesKey(id ?? ''),
    queryFn: ({ signal }) => getFiles(id as string, signal),
    enabled: Boolean(id),
  })
}
