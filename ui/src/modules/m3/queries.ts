import { useQuery } from '@tanstack/react-query'
import { getDataset, getTableSources, getTables, type Dataset, type ResultTables, type TableSources } from '../../api/demoData'
import type { ApiError } from '../../api/errors'
import { studyKey } from '../../kit/useStudyState'

/**
 * Combined data's reads. Their keys are under the study's key, so the kit's
 * invalidateStudy (after every act, and when a wait ends) re-reads them too.
 */

export function datasetKey(id: string) {
  return [...studyKey(id), 'dataset'] as const
}

export function tablesKey(id: string) {
  return [...studyKey(id), 'tables'] as const
}

export function useDataset(id: string | undefined) {
  return useQuery<Dataset, ApiError>({
    queryKey: datasetKey(id ?? ''),
    queryFn: ({ signal }) => getDataset(id as string, signal),
    enabled: Boolean(id),
  })
}

export function useTables(id: string | undefined) {
  return useQuery<ResultTables, ApiError>({
    queryKey: tablesKey(id ?? ''),
    queryFn: ({ signal }) => getTables(id as string, signal),
    enabled: Boolean(id),
  })
}

export function useTableSources(id: string, key: string | null) {
  return useQuery<TableSources, ApiError>({
    queryKey: [...tablesKey(id), key ?? '', 'sources'],
    queryFn: ({ signal }) => getTableSources(id, key as string, signal),
    enabled: Boolean(key),
  })
}
