import type { ExistingStudyState, ModuleId } from '../api/types'

/**
 * The "next step" at the top of a study: the backend's own (`stands.next`,
 * M1 R2), derived from the phase, the kind of session and the readiness by
 * the same function that fills the studies list. Nothing is decided here; a
 * report's pending studies are named from its served `members`.
 *
 * "Publish" is the next step only when the backend serves the publish
 * readiness complete and ready (C6), never before.
 */
export interface NextStep {
  label: string
  module: ModuleId | null
  why?: string
}

export function nextStepOf(state: ExistingStudyState): NextStep | null {
  const next = state.stands.next
  if (!next) return null
  const step: NextStep = { label: next.say, module: (next.fix as ModuleId | null) ?? null }
  if (state.kind === 'report') {
    const pending = (state.members ?? []).filter((m) => !m.exists || !m.processed)
    if (pending.length > 0) step.why = `Not yet processed: ${pending.map((m) => `${m.key} (${m.id})`).join(', ')}.`
  }
  return step
}
