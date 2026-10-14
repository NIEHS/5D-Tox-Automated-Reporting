import { useSyncExternalStore } from 'react'

/**
 * Which studies this browser tab is itself waiting on. Transient front-end
 * state only (a <Wait> is open); it lets <RunInFlight> stay out of the way of
 * the tab's own wait. The run itself is known only from the backend's state.
 */

const waiting = new Map<string, number>()
const listeners = new Set<() => void>()

function emit() {
  for (const l of listeners) l()
}

export function markWaiting(studyId: string): () => void {
  waiting.set(studyId, (waiting.get(studyId) ?? 0) + 1)
  emit()
  return () => {
    const n = (waiting.get(studyId) ?? 1) - 1
    if (n <= 0) waiting.delete(studyId)
    else waiting.set(studyId, n)
    emit()
  }
}

function subscribe(l: () => void) {
  listeners.add(l)
  return () => listeners.delete(l)
}

export function useWaitingHere(studyId: string): boolean {
  return useSyncExternalStore(subscribe, () => waiting.has(studyId))
}
