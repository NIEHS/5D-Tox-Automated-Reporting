import type { ExistingStudyState } from '../../api/types'

/** True on the finished side of a demonstration pair: it is left as it is, and offered no act. */
export function isFinishedSide(state: ExistingStudyState): boolean {
  return state.demo?.role === 'finished'
}
