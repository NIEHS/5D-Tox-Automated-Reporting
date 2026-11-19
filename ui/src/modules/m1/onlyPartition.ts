import { useSyncExternalStore } from 'react'

/**
 * "Show only this block": the studies list reduced to one partition (the
 * Demo pair), so that the other studies in the store are not on the screen
 * while it is shown to an audience. A display choice of this browser, kept
 * across pages and reloads; it changes nothing about any study.
 */

const KEY = 'studies.onlyPartition'
const listeners = new Set<() => void>()

function read(): string | null {
  try {
    return window.localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function setOnlyPartition(name: string | null) {
  try {
    if (name === null) window.localStorage.removeItem(KEY)
    else window.localStorage.setItem(KEY, name)
  } catch {
    // a browser that keeps nothing still shows the whole list
  }
  for (const l of listeners) l()
}

function subscribe(l: () => void) {
  listeners.add(l)
  window.addEventListener('storage', l)
  return () => {
    listeners.delete(l)
    window.removeEventListener('storage', l)
  }
}

/** The partition the list is reduced to, or null for the whole list. */
export function useOnlyPartition(): string | null {
  return useSyncExternalStore(subscribe, read, () => null)
}
