import type { ReviewSection } from '../../api/demoReview'

/** One section of one session: the two together name it on the page. */
export function sectionId(s: Pick<ReviewSection, 'owner' | 'key'>): string {
  return `${s.owner}/${s.key}`
}
