import type { ChemicalLookup, ConfirmedIdentity, IdPattern } from '../../api/types'
import { checkId } from '../../kit/checkId'

/**
 * What a looked-up identity still needs before it can be used.
 *
 * - `ok`: the lookup gave a name and a valid CAS number.
 * - `casrn`: the lookup found the chemical but gave no CAS number. The person
 *   types one, from a source they trust (maintainer, 2026-10-16); it is
 *   recorded as stated by a person. The backend says so with `needs:
 *   ["casrn"]`; a lookup without `needs` and without a CAS number is read the
 *   same way.
 * - `blocked`: nothing the person can do here. No name from the lookup (a
 *   stated identity is ruled out, Q-M1-3), or a CAS number from the lookup
 *   that fails its check digit. The backend would refuse it
 *   (`identity_incomplete`, `invalid_casrn`), so it is never offered.
 *
 * `outcome` finishes the sentence: "a study can't be created", "this
 * identity can't be saved".
 */
export type IdentityNeed = { kind: 'ok' } | { kind: 'casrn'; say: string } | { kind: 'blocked'; say: string }

export function identityNeed(lookup: ChemicalLookup, outcome: string, casrnPattern?: IdPattern): IdentityNeed {
  const { name, casrn } = lookup.identity
  const svc = lookup.service
  if (!name?.trim()) {
    return {
      kind: 'blocked',
      say:
        `${svc} gives no name for this chemical, so ${outcome} from this lookup yet. ` +
        'Check the DTXSID on the CompTox dashboard, or ask the maintainer how to go on.',
    }
  }
  if (!casrn?.trim() || lookup.needs?.includes('casrn')) {
    return {
      kind: 'casrn',
      // the backend's words when it serves them
      say:
        lookup.needs_say ??
        `${svc} gives no CAS number for this chemical. Type it from a source you trust (the CompTox dashboard, the study's own records); it will be recorded as stated by you.`,
    }
  }
  // the pattern is the backend's; when it has not loaded, the backend decides
  const c = casrnPattern ? checkId('casrn', casrn.trim(), casrnPattern) : null
  if (c && c.ok === false) {
    return {
      kind: 'blocked',
      say:
        `The CAS number ${svc} gives for this chemical (${casrn}) is not a valid one, so ${outcome} ` +
        'from this lookup yet. Ask the maintainer how to go on.',
    }
  }
  return { kind: 'ok' }
}

/**
 * The identity sent with a create or an identity fill: everything from the
 * lookup, except the CAS number when the person typed it, which is then
 * marked as theirs (`casrn_from: "person"`, 2026-10-16).
 */
export function identityToSend(lookup: ChemicalLookup, need: IdentityNeed, typedCasrn: string): ConfirmedIdentity {
  const typed = need.kind === 'casrn'
  return {
    name: lookup.identity.name,
    casrn: typed ? typedCasrn.trim() : lookup.identity.casrn,
    pubchem_cid: lookup.identity.pubchem_cid,
    source: {
      kind: 'lookup',
      service: lookup.service,
      looked_up_at: lookup.looked_up_at,
      ...(typed ? { casrn_from: 'person' as const } : {}),
    },
  }
}
