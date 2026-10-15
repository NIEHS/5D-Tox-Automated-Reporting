import { describe, expect, it } from 'vitest'
import { ACTIONS, PHASES, SECTION_KINDS, type ExistingStudyState, type SectionState } from '../../types'
import {
  STATES_BY_ID,
  STATE_APPROVED,
  STATE_COMPANION,
  STATE_EMPTY,
  STATE_MEMBER_RAT,
  STATE_MISSING,
  STATE_REPORT,
  VOCABULARIES,
} from '.'

/**
 * The fixtures are the backend's own answers. These tests pin the keys the
 * front-end types declare against them, so a change on either side fails
 * here first rather than on a screen.
 */

const STATE_KEYS = [
  'chemical_dtxsid', 'chemical_dtxsid_from', 'exists', 'id', 'identity', 'kind', 'legal_actions', 'phase', 'pins',
  'processed', 'readiness', 'relations', 'sections', 'stands',
]

const SECTION_KEYS: (keyof SectionState)[] = [
  'accept', 'approvable', 'approved', 'blocked_by', 'enabled', 'facts', 'has_file', 'instance_of', 'key', 'kind',
  'machine_may_write', 'maturity', 'model', 'region', 'regenerated', 'review', 'source', 'stale', 'title', 'user_edited', 'version',
  'version_status', 'wording_review',
]

const all: ExistingStudyState[] = Object.values(STATES_BY_ID)

describe('the state fixtures are real answers in the typed shape', () => {
  it('every study has exactly the served keys (members only on a report)', () => {
    for (const s of all) {
      const keys = Object.keys(s).filter((k) => k !== 'members').sort()
      expect(keys, s.id).toEqual(STATE_KEYS)
      expect('members' in s, s.id).toBe(s.kind === 'report')
    }
  })

  it('every phase is a known one, and the six phases are all covered', () => {
    const phases = new Set(all.map((s) => s.phase))
    for (const p of phases) expect(PHASES).toContain(p)
    for (const p of PHASES) expect(phases, p).toContain(p)
  })

  it('every section has exactly the typed keys and a known kind', () => {
    for (const s of all) {
      for (const sec of s.sections) {
        expect(Object.keys(sec).sort(), `${s.id} ${sec.key}`).toEqual([...SECTION_KEYS].sort())
        expect(SECTION_KINDS, sec.key).toContain(sec.kind)
        expect(Object.keys(sec.accept).sort()).toEqual(['allowed', 'code', 'say'])
        if (!sec.accept.allowed) expect(sec.accept.say, sec.key).toBeTruthy()
      }
    }
  })

  it('serves an approvable section with no file as not approvable now, with a reason', () => {
    const methods = STATE_APPROVED.sections.find((x) => x.key === 'methods')
    expect(methods).toMatchObject({ approvable: true, has_file: false, accept: { allowed: false } })
  })

  it('the pins carry the served keys', () => {
    for (const s of all) {
      expect(Object.keys(s.pins).sort()).toEqual(['definition', 'method'])
      const m = s.pins.method ?? {}
      for (const k of ['pinned', 'name', 'hash', 'series', 'mode', 'pinned_by', 'pinned_at']) expect(m, `${s.id} method.${k}`).toHaveProperty(k)
      const d = s.pins.definition ?? {}
      for (const k of ['pinned', 'name', 'hash', 'mode', 'pinned_by', 'pinned_at', 'source', 'snapshot']) expect(d, `${s.id} definition.${k}`).toHaveProperty(k)
    }
  })

  it('legal actions are C1\'s: only ADD_FILES when empty, none on a companion or a report (R6)', () => {
    for (const s of all) for (const a of s.legal_actions) expect(ACTIONS, s.id).toContain(a)
    expect(STATE_EMPTY.legal_actions).toEqual(['ADD_FILES'])
    expect(STATE_COMPANION.legal_actions).toEqual([])
    expect(STATE_REPORT.legal_actions).toEqual([])
  })

  it('an unpinned method carries the suggestion a person confirms (C1 D1 = B); a pinned one does not', () => {
    expect(STATE_EMPTY.pins.method?.pinned).toBe(false)
    const suggestion = STATE_EMPTY.pins.method?.suggestion
    expect(suggestion?.name).toBeTruthy()
    expect(suggestion?.why).toBeTruthy()
    expect(STATE_APPROVED.pins.method?.pinned).toBe(true)
    expect(STATE_APPROVED.pins.method).not.toHaveProperty('suggestion')
  })

  it('the publish readiness says what it checked and that it is not complete', () => {
    for (const s of all) {
      const p = s.readiness.publish
      expect(p?.complete, s.id).toBe(false)
      expect(p?.checks?.map((c) => c.id)).toEqual(['stale_llm_sections'])
      expect('data_approval' in s.readiness).toBe(false) // not served yet (C6)
      expect('run' in s).toBe(false) // not served yet (C5)
    }
  })

  it('members, the companion and a missing study have the served shape', () => {
    for (const m of STATE_REPORT.members ?? []) {
      expect(Object.keys(m).sort()).toEqual(['exists', 'id', 'key', 'phase', 'processed', 'readiness'])
    }
    for (const s of all) {
      expect(Object.keys(s.relations).sort(), s.id).toEqual(['companion', 'members', 'others', 'parent', 'twin'])
      expect(Object.keys(s.stands).sort(), s.id).toEqual(['next', 'phase', 'say'])
    }
    expect(STATE_REPORT.relations.members.map((m) => m.key)).toEqual(['rat', 'mouse'])
    expect(STATE_MEMBER_RAT.relations.parent).toBe(STATE_REPORT.id)
    expect(STATE_COMPANION.relations.twin).toBe('DTXSID50469320')
    expect(STATE_MISSING).toEqual({ id: 'DTXSID9999999', exists: false })
  })
})

describe('the vocabularies are the real answer, one self-describing entry per field', () => {
  it('flat lists and the one dependency, each with a label', () => {
    for (const [key, v] of Object.entries(VOCABULARIES.vocabularies)) {
      expect(v.label, key).toBeTruthy()
      if ('depends_on' in v) expect(key).toBe('strain')
    }
    expect(VOCABULARIES.vocabularies.strain).toMatchObject({ depends_on: 'species' })
    expect(Object.keys(VOCABULARIES).sort()).toEqual(['patterns', 'vocabularies'])
  })
})
