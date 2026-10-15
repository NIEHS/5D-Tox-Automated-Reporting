import { describe, expect, it } from 'vitest'
import type { StudyRow } from '../../../types'
import { STATES_BY_ID } from '../state'
import {
  M1_CHECK_BPA,
  M1_CHECK_PFHXSAM,
  M1_CHEMICALS,
  M1_DELETE_PREVIEW_PFHXSAM,
  M1_DETAILS,
  M1_STUDIES,
  M1_STUDIES_CONTRACT,
} from '.'

/**
 * M1's fixtures in the contract's shape (contract.md §2), and the built mock
 * world consistent with the kit's real state fixtures. When the backend's
 * real answers land in docs/ui-redesign/contracts/m1/, they replace these
 * files and this test says whether the shapes still agree.
 */

const ROW_KEYS = [
  'actions', 'bookshelf', 'chemical_dtxsid', 'chemical_dtxsid_from', 'format', 'id', 'identity', 'kind', 'last_changed',
  'notes', 'processed', 'published', 'relations', 'stands',
].sort()

const rows = (l: typeof M1_STUDIES): StudyRow[] => [...l.chemicals.flatMap((c) => c.sessions), ...l.unassigned]

describe('M1 fixtures', () => {
  it('every row has the contract\'s keys, in both the contract\'s list and the built one', () => {
    for (const r of [...rows(M1_STUDIES_CONTRACT), ...rows(M1_STUDIES)]) {
      expect(Object.keys(r).sort(), r.id).toEqual(ROW_KEYS)
      expect(Object.keys(r.relations).sort(), r.id).toEqual(['companion', 'members', 'others', 'parent', 'twin'])
      expect(Object.keys(r.identity.source).sort(), r.id).toEqual(['confirmed_at', 'kind', 'service'])
      if (!r.actions.delete.allowed) expect(r.actions.delete.say, r.id).toBeTruthy()
    }
  })

  it('the built list agrees with the state fixtures: same kind, and the phase where the session has one', () => {
    for (const r of rows(M1_STUDIES)) {
      const st = STATES_BY_ID[r.id]
      if (!st) continue
      expect(r.kind, r.id).toBe(st.kind)
      if (r.kind === 'study' || r.kind === 'member') expect(r.stands.phase, r.id).toBe(st.phase)
      else expect(r.stands.phase, r.id).toBeNull()
    }
  })

  it('every row has a detail, and the detail is the row plus `detail`', () => {
    for (const r of rows(M1_STUDIES)) {
      const d = M1_DETAILS[r.id]
      expect(d, r.id).toBeDefined()
      const { detail, ...row } = d!
      expect(row, r.id).toEqual(r)
      expect(Object.keys(detail.format), r.id).toEqual(expect.arrayContaining(['brings', 'pin', 'title', 'say', 'source']))
      expect('members' in detail, r.id).toBe(r.kind === 'report')
    }
  })

  it('the lookups, creation checks and the delete preview carry the contract\'s keys', () => {
    for (const l of Object.values(M1_CHEMICALS)) {
      expect(Object.keys(l).sort()).toEqual(['dtxsid', 'dtxsid_matched', 'identity', 'looked_up_at', 'say_source', 'service', 'structure_url'])
    }
    for (const c of [M1_CHECK_BPA, M1_CHECK_PFHXSAM]) {
      expect(Object.keys(c).sort()).toEqual(['dtxsid', 'existing', 'exists', 'format', 'published', 'related_sessions'])
    }
    expect(Object.keys(M1_DELETE_PREVIEW_PFHXSAM).sort()).toEqual(['confirm', 'preview_token', 'type_to_confirm'])
    expect(M1_DELETE_PREVIEW_PFHXSAM.confirm.strength).toBe('irreversible')
  })

  it('no session folder starting with "_" is listed', () => {
    expect(rows(M1_STUDIES).some((r) => r.id.startsWith('_'))).toBe(false)
  })
})
