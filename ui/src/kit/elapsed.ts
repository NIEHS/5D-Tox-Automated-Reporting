import { useEffect, useState } from 'react'

/** "42 s", "3 min 05 s", "1 h 02 min". */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h} h ${String(m).padStart(2, '0')} min`
  if (m > 0) return `${m} min ${String(s).padStart(2, '0')} s`
  return `${s} s`
}

/** The time of day of an ISO timestamp, in the person's locale; null if unreadable. */
export function formatClock(iso: string | null | undefined): string | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  return new Date(t).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

/** Milliseconds since `startMs`, re-rendered every second; null when the start is unknown. */
export function useElapsed(startMs: number | null): number | null {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (startMs === null) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [startMs])
  return startMs === null ? null : Math.max(0, now - startMs)
}
