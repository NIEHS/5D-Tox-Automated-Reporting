import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getCreationCheck, getStudies, getStudy, lookupChemical } from '../../api/m1'
import type { ApiError } from '../../api/errors'
import type { ChemicalLookup, CreationCheck, StudiesList, StudyDetail } from '../../api/types'
import { studyKey } from '../../kit/useStudyState'

/**
 * M1's reads. Every value about the workflow in them comes from the backend;
 * nothing here derives a phase, a kind or an allowed act. A study's own
 * workflow state is read only through the kit's useStudyState.
 */

export const STUDIES_KEY = ['studies'] as const

/** under the study's key, so the kit's invalidateStudy re-reads it too */
export function studyDetailKey(id: string) {
  return [...studyKey(id), 'detail'] as const
}

/** GET /api/v2/studies; re-read on window focus (the app's default) and after a create or a delete. */
export function useStudies() {
  return useQuery<StudiesList, ApiError>({
    queryKey: STUDIES_KEY,
    queryFn: ({ signal }) => getStudies(signal),
  })
}

export function useStudyDetail(id: string | undefined) {
  return useQuery<StudyDetail, ApiError>({
    queryKey: studyDetailKey(id ?? ''),
    queryFn: ({ signal }) => getStudy(id as string, signal),
    enabled: Boolean(id),
  })
}

/** Whether a study of this DTXSID can be created, and its format. Side-effect-free on the backend. */
export function useCreationCheck(dtxsid: string | null) {
  return useQuery<CreationCheck, ApiError>({
    queryKey: ['m1', 'creation-check', dtxsid ?? ''],
    queryFn: ({ signal }) => getCreationCheck(dtxsid as string, signal),
    enabled: Boolean(dtxsid),
    staleTime: 0,
  })
}

/**
 * The chemical lookup. It takes seconds; the backend caches it for ten
 * minutes. Not retried by itself: the person sees an unreachable service at
 * once, with "Try again".
 */
export function useChemicalLookup(dtxsid: string | null) {
  return useQuery<ChemicalLookup, ApiError>({
    queryKey: ['m1', 'chemical', dtxsid ?? ''],
    queryFn: ({ signal }) => lookupChemical(dtxsid as string, signal),
    enabled: Boolean(dtxsid),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 10 * 60 * 1000,
    gcTime: 0,
  })
}

/** Re-read the list (after a create, a delete, an identity filled in). */
export function useRefreshStudies(): () => Promise<void> {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({ queryKey: STUDIES_KEY })
}
