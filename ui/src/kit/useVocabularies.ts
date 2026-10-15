import { useQuery } from '@tanstack/react-query'
import { getVocabularies } from '../api/client'
import type { ApiError } from '../api/errors'
import { isDependentVocabulary, type Vocabularies } from '../api/types'

/** The controlled vocabularies and id patterns; read once per session of the app. */
export function useVocabularies() {
  return useQuery<Vocabularies, ApiError>({
    queryKey: ['vocabularies'],
    queryFn: ({ signal }) => getVocabularies(signal),
    staleTime: Infinity,
  })
}

export type VocabChoices =
  | { kind: 'unknown' }
  | { kind: 'needs-parent'; parent: string; parentLabel: string }
  | { kind: 'choices'; values: string[] }

/**
 * The values a vocabulary allows, given the value of the field it depends on.
 * Pure: the screens and form validators use the same answer.
 */
export function choicesFor(
  vocabs: Vocabularies | undefined,
  key: string,
  parentValue?: string | null,
): VocabChoices {
  const v = vocabs?.vocabularies[key]
  if (!v) return { kind: 'unknown' }
  if (!isDependentVocabulary(v)) return { kind: 'choices', values: v.values }
  const parentLabel = vocabs?.vocabularies[v.depends_on]?.label ?? v.depends_on
  if (!parentValue) return { kind: 'needs-parent', parent: v.depends_on, parentLabel }
  return { kind: 'choices', values: v.by[parentValue] ?? [] }
}
