import type { ModuleId, StudyState } from '../api/types'
import { ACTION_WORDS, nextAction, phaseWords } from '../kit/words'

/**
 * The "next step" shown at the top of a study: one of the backend's legal
 * actions, or, once processed, the first item that blocks publishing. It
 * ranks what the backend allows; it never decides what is allowed.
 */
export interface NextStep {
  label: string
  module: ModuleId | null
  why?: string
}

export function nextStepOf(state: StudyState): NextStep | null {
  const words = phaseWords(state.phase)
  if (!words.known) return null
  const next = nextAction(state.legal_actions)
  if (next && !(next === 'REPROCESS' && state.processed)) {
    const w = ACTION_WORDS[next]
    return { label: w.label, module: w.module }
  }
  if (state.processed && state.readiness?.publish) {
    const pub = state.readiness.publish
    const block = pub.items.find((i) => i.level === 'block') ?? pub.items[0]
    if (pub.ready || !block) return { label: 'Review the report: nothing blocks publishing', module: 'D1' }
    // the label and the link must name the same place: the one that clears the block
    return { label: 'Clear what stops publishing', module: block.fix ?? 'D1', why: block.say }
  }
  if (words.start) return { label: words.start.label, module: words.start.module }
  return null
}
