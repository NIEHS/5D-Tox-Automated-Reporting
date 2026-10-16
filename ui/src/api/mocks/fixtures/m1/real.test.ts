import { describe, expect, it } from 'vitest'
import { isMissingMember, type ChemicalLookup, type StudiesList, type StudyDetail, type StudyRow } from '../../../types'

/**
 * M1's mocks against the backend's REAL answers (docs/ui-redesign/contracts/m1/,
 * captured from a server on a scratch store). The mocks are built in the
 * contract's shape; this test says whether the real answers still fit them,
 * key for key, including the shapes the review found the screens must
 * survive: a format the backend could not read (null, with a note) and a
 * report whose member study is missing (a stub).
 */

interface Saved<T> {
  status: number
  body: T
}
const real = import.meta.glob<Saved<unknown>>('../../../../../../docs/ui-redesign/contracts/m1/*.json', { eager: true, import: 'default' })
function sample<T>(name: string): T {
  const hit = Object.entries(real).find(([p]) => p.endsWith(`/${name}.json`))
  if (!hit) throw new Error(`no real sample ${name}`)
  return hit[1].body as T
}

const ROW_KEYS = [
  'actions', 'bookshelf', 'chemical_dtxsid', 'chemical_dtxsid_from', 'format', 'id', 'identity', 'kind', 'last_changed',
  'notes', 'processed', 'published', 'relations', 'stands',
].sort()

const rowsOf = (l: StudiesList): StudyRow[] => [...l.chemicals.flatMap((c) => c.sessions), ...l.unassigned]

describe('M1 real answers fit the front-end types', () => {
  it('every listed row has the typed keys, and its identity source says who gave the CAS number', () => {
    for (const r of rowsOf(sample<StudiesList>('studies'))) {
      expect(Object.keys(r).sort(), r.id).toEqual(ROW_KEYS)
      expect(Object.keys(r.identity.source).sort(), r.id).toEqual(['casrn_from', 'confirmed_at', 'kind', 'service'])
    }
  })

  it('a lookup serves what the person must still supply, and the backend\'s words for it', () => {
    const l = sample<ChemicalLookup>('chemical.DTXSID7020182')
    expect(l.needs).toEqual([])
    expect(l.needs_say).toBeNull()
  })

  it('a format the backend cannot read is null, and a note says why', () => {
    const d = sample<StudyDetail>('study.DTXSID_TEST.format_unreadable')
    expect(d.format).toBeNull()
    expect(d.detail.format).toBeNull()
    expect(d.notes.some((n) => n.code === 'damaged_session_file')).toBe(true)
    const row = rowsOf(sample<StudiesList>('studies.format_unreadable')).find((r) => r.id === 'DTXSID_TEST')
    expect(row?.format).toBeNull()
  })

  it('a missing member study is a stub the type recognises', () => {
    const members = sample<StudyDetail>('study.DTXSID1020431.member_missing').detail.members ?? []
    const missing = members.filter(isMissingMember)
    expect(missing).toEqual([{ id: 'DTXSID1020431_mouse', key: 'mouse', exists: false }])
    for (const m of members.filter((x) => !isMissingMember(x))) expect((m as StudyRow).stands, m.id).toBeDefined()
  })
})
