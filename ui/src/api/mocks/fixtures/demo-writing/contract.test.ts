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

  it('the finished report was checked: its list is the one the check derived, numbered without a gap, and only cited sources are in it', () => {
    const refs = DEMO_REFERENCES['DTXSID6020430']!
    expect(refs.printed).toMatchObject({ state: 'passed', act: { allowed: false, counterpart: 'DTXSID6020430_live' } })
    expect(refs.printed!.counts!.errors).toBe(0)
    expect(refs.entries.map((e) => e.n)).toEqual(refs.entries.map((_, i) => i + 1))
    expect(refs.entries.filter((e) => e.kind === 'background_source').map((e) => e.n)).toEqual([1, 2, 3, 4, 5])
    expect(refs.entries.filter((e) => e.kind === 'boilerplate').map((e) => e.n)).toEqual([6, 7, 8, 9, 10, 11, 12])
    for (const e of refs.entries) {
      expect(e.listed, String(e.n)).toBe(true)
      expect(e.cited, String(e.n)).toBeGreaterThan(0)
      expect(e.why_not_listed, String(e.n)).toBeNull()
    }
    // recorded and not listed: each says why, and a paper has the knowledge base's statements (or none)
    expect(refs.not_listed.length).toBeGreaterThan(0)
    for (const e of refs.not_listed) {
      expect(e.n).toBeNull()
      expect(e.listed).toBe(false)
      expect(e.why_not_listed).toBeTruthy()
      expect(e.kind === 'paper' ? e.statements !== null : e.statements === null, e.slug ?? '').toBe(true)
    }
  })

  it('the live copy has not been checked, and the check is offered there; a study of a report has no list of its own', () => {
    const live = DEMO_REFERENCES['DTXSID6020430_live']!
    expect(live.printed).toMatchObject({ state: 'not_checked', act: { allowed: true } })
    expect(live.entries).toEqual([])
    for (const id of ['DTXSID6020430_rat', 'DTXSID6020430_live_rat']) {
      const study = DEMO_REFERENCES[id]!
      expect(study.printed, id).toBeNull()
      expect(study.entries, id).toEqual([])
      expect(study.report?.id, id).toBe(DEMO_STATES[id]!.relations!.parent)
    }
  })
})
