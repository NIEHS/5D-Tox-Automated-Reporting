import type { ExistingStudyState, ModuleId } from '../api/types'
import { ACTION_WORDS, phaseWords } from '../kit/words'

/**
 * THE BACKEND SHOULD SERVE THIS. The "next step" at the top of a study is
 * worked out here only until the read model serves it (M1's contract asks for
 * `stands.next`, derived in the backend from the phase, the kind of session
 * and the readiness). Everything the front-end decides about it is in this one
 * function, so it can be replaced by reading the served value.
 *
 * It ranks what the backend allows; it never decides what is allowed: an
 * action is put forward only if it is in `legal_actions`.
 *
 * Until C6 the publish readiness checks only part of what publishing needs
 * (`readiness.publish.complete` is false), so "Publish" is never the next
 * step and nothing here says the report is ready.
 */
export interface NextStep {
  label: string
  module: ModuleId | null
  why?: string
}

/** Which legal action to put forward, when several are: forward first, never a destructive one. */
const NEXT_PREFERENCE = ['INTEGRATE', 'APPROVE', 'REPROCESS', 'VALIDATE'] as const

export function nextStepOf(state: ExistingStudyState): NextStep | null {
  // Published content and reports over several studies have their own next steps.
  if (state.kind === 'companion') return null
  if (state.kind === 'report') {
    const members = state.members ?? []
    const pending = members.filter((m) => !m.exists || !m.processed)
    if (pending.length > 0) {
      return {
        label: 'Finish the studies this report covers',
        module: null,
        why: `Not yet processed: ${pending.map((m) => `${m.key} (${m.id})`).join(', ')}.`,
      }
    }
    return { label: "Review the report's sections", module: 'D1' }
  }

  const words = phaseWords(state.phase)
  if (!words.known) return null
  const next = NEXT_PREFERENCE.find((a) => state.legal_actions.includes(a)) ?? null
  if (next && !(next === 'REPROCESS' && state.processed)) {
    const w = ACTION_WORDS[next]
    return { label: w.label, module: w.module }
  }
  if (state.processed) {
    const block = state.readiness.publish?.items.find((i) => i.level === 'block')
    // the label and the link must name the same place: the one that clears the block
    if (block) return { label: 'Clear what stops publishing', module: block.fix ?? 'D1', why: block.say }
    return { label: "Review the report's sections", module: 'D1' }
  }
  if (words.start) return { label: words.start.label, module: words.start.module }
  return null
}
