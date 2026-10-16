import { describe, expect, it } from 'vitest'
import { M1_CHEMICALS, VOCABULARIES } from '../../api/mocks/fixtures'
import { identityNeed, identityToSend } from './identityGap'

/** The identity rule (maintainer, 2026-10-16, revised): only the DTXSID is required. */

const bpa = () => ({ ...structuredClone(M1_CHEMICALS['DTXSID7020182']!), needs: [], needs_say: null })
const casrnRule = VOCABULARIES.patterns.casrn

describe('identityNeed', () => {
  it('ok when the lookup gives a name and a valid CAS number', () => {
    expect(identityNeed(bpa(), casrnRule)).toEqual({ kind: 'ok' })
  })

  it('asks for the CAS number when the lookup gives none, in the backend\'s words when served', () => {
    const l = { ...bpa(), needs: ['casrn'], needs_say: 'Served words.' }
    l.identity.casrn = null
    expect(identityNeed(l, casrnRule)).toEqual({ kind: 'casrn', say: 'Served words.', lookupCasrn: null })
  })

  it('treats a lookup CAS number that fails its check digit as missing (asked for), never as a dead end', () => {
    const l = bpa()
    l.identity.casrn = '80-05-8'
    const n = identityNeed(l, casrnRule)
    expect(n).toMatchObject({ kind: 'casrn', lookupCasrn: '80-05-8' })
  })

  it('no name: the identity cannot come from this lookup (no stated name, Q-M1-3)', () => {
    const l = bpa()
    l.identity.name = '  '
    expect(identityNeed(l, casrnRule).kind).toBe('no_name')
  })
})

describe('identityToSend', () => {
  it('the lookup\'s CAS number, with no casrn_from, when nothing was asked', () => {
    const l = bpa()
    const sent = identityToSend(l, { kind: 'ok' }, 'ignored')
    expect(sent.casrn).toBe('80-05-7')
    expect(sent.source).not.toHaveProperty('casrn_from')
  })

  it('a typed CAS number is the person\'s', () => {
    const l = bpa()
    l.identity.casrn = null
    const sent = identityToSend(l, { kind: 'casrn', say: '', lookupCasrn: null }, ' 80-05-7 ')
    expect(sent).toMatchObject({ casrn: '80-05-7', source: { kind: 'lookup', casrn_from: 'person' } })
  })

  it('an empty one is null (pending), never the lookup\'s invalid one', () => {
    const l = bpa()
    l.identity.casrn = '80-05-8'
    const sent = identityToSend(l, { kind: 'casrn', say: '', lookupCasrn: '80-05-8' }, '')
    expect(sent.casrn).toBeNull()
    expect(sent.source).not.toHaveProperty('casrn_from')
  })
})
