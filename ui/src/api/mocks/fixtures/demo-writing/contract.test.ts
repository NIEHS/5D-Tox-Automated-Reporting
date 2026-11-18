import { describe, expect, it } from 'vitest'
import { DEMO_PARTS, DEMO_REFERENCES, DEMO_STATES, DEMO_WRITING } from '.'

/**
 * The fixtures are the backend's own answers. These tests pin what the page's
 * types and words rely on, so a change on either side fails here first.
 */

const WRITERS = ['data', 'model', 'mixed', 'unrecorded']
const RECORDS = ['as_sent', 'recorded', 'rebuilt', 'not_recorded']

describe('the Written sections fixtures are real answers in the typed shape', () => {
  it('covers the finished report, one of its studies, and the live copy of each', () => {
    expect(Object.keys(DEMO_WRITING).sort()).toEqual(Object.keys(DEMO_STATES).sort())
    expect(Object.keys(DEMO_REFERENCES).sort()).toEqual(Object.keys(DEMO_STATES).sort())
    expect(Object.values(DEMO_STATES).map((s) => [s.id, s.kind, s.demo?.role])).toEqual([
      ['DTXSID6020430', 'report', 'finished'],
      ['DTXSID6020430_live', 'report', 'live'],
      ['DTXSID6020430_live_rat', 'member', 'live'],
      ['DTXSID6020430_rat', 'member', 'finished'],
    ])
  })

  it('every part names a known writer, and every text served is labeled with a known record', () => {
    const summaries = Object.values(DEMO_WRITING).flatMap((o) => [...o.parts, ...(o.studies ?? []).flatMap((s) => s.parts)])
    expect(summaries.length).toBeGreaterThan(30)
    for (const p of summaries) {
      expect(WRITERS, p.key).toContain(p.written_by)
      for (const s of p.subsections ?? []) expect(['data', 'model'], s.key).toContain(s.written_by)
      if (p.recorded) {
        expect(RECORDS, p.key).toContain(p.recorded.prompt)
        expect(RECORDS, p.key).toContain(p.recorded.inputs)
      }
    }
    for (const part of Object.values(DEMO_PARTS)) {
      for (const g of part.given) {
        expect(RECORDS, `${part.key} ${g.id}`).toContain(g.record)
        // what was not recorded has no text; what is served has one
        expect(g.text === null, `${part.key} ${g.id}`).toBe(g.record === 'not_recorded')
      }
    }
  })

  it('an act is allowed only on the live side, and the finished side names its live copy', () => {
    for (const [id, o] of Object.entries(DEMO_WRITING)) {
      const role = DEMO_STATES[id]!.demo!.role
      for (const verdict of Object.values(o.acts)) {
        if (role === 'finished') expect(verdict).toMatchObject({ allowed: false, counterpart: DEMO_STATES[id]!.demo!.counterpart })
        if (!verdict.allowed) expect(verdict.say, id).toBeTruthy()
      }
    }
    expect(DEMO_WRITING['DTXSID6020430_live']!.acts.background.allowed).toBe(true)
    expect(DEMO_WRITING['DTXSID6020430_live_rat']!.acts.summary.allowed).toBe(true)
  })

  it('the reference list is numbered as printed, without a gap in what was kept of the Background', () => {
    const refs = DEMO_REFERENCES['DTXSID6020430']!
    expect(refs.entries.filter((e) => e.kind === 'background_source').map((e) => e.n)).toEqual([1, 2, 3, 4, 5])
    expect(refs.entries.find((e) => e.kind === 'paper')!.n).toBe(6)
    for (const e of refs.entries) expect(e.kind === 'paper' ? e.statements !== null : e.statements === null, String(e.n)).toBe(true)
  })
})
