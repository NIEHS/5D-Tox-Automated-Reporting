import type { ChemicalLookup, ConfirmedIdentity, IdPattern } from '../../api/types'
import { checkId } from '../../kit/checkId'

/**
 * What a looked-up identity still needs before it can be used. The only
 * absolute requirement for a test article's identity is its DTXSID (the
 * maintainer, 2026-10-16, revised); every gap is handled simply, never by a
 * dead end.
 *
 * - `ok`: the lookup gave a name and a valid CAS number.
 * - `casrn`: the lookup found the chemical but gave no usable CAS number:
 *   none (the backend says so with `needs: ["casrn"]`; a lookup without
 *   `needs` and without a CAS number is read the same way), or one that fails
 *   its check digit (`lookupCasrn` then holds it; it is never sent). The
 *   person is asked for one but may go on without it: a typed one is
 *   recorded as stated by a person; an empty one shows as "[CASRN pending]".
 * - `no_name`: the lookup found a compound but gives no name. A person never
 *   types a name (Q-M1-3), so the identity can't come from this lookup; the
 *   study can still be created with its chemical pending, like a DTXSID the
 *   lookup does not know.
 */
export type IdentityNeed =
  | { kind: 'ok' }
  | { kind: 'casrn'; say: string; lookupCasrn: string | null }
  | { kind: 'no_name'; say: string }

export function identityNeed(lookup: ChemicalLookup, casrnPattern?: IdPattern): IdentityNeed {
  const { name, casrn } = lookup.identity
  const svc = lookup.service
  if (!name?.trim()) {
    return {
      kind: 'no_name',
      say: `${svc} found a compound for ${lookup.dtxsid} but gives no name for it, so its identity can't be taken from this lookup.`,
    }
  }
  if (!casrn?.trim() || lookup.needs?.includes('casrn')) {
    return {
      kind: 'casrn',
      lookupCasrn: null,
      // the backend's words when it serves them
      say:
        lookup.needs_say ??
        `${svc} gives no CAS number for ${name}. If you have it from a source you trust (the CompTox dashboard, the study's own records), type it; it will be recorded as stated by you. Without it, the study shows "[CASRN pending]".`,
    }
  }
  // the pattern is the backend's; when it has not loaded, the backend decides
  const c = casrnPattern ? checkId('casrn', casrn.trim(), casrnPattern) : null
  if (c && c.ok === false) {
    return {
      kind: 'casrn',
      lookupCasrn: casrn,
      say:
        `The CAS number ${svc} gives for ${name} (${casrn}) fails its check digit, so it is not used. ` +
        `If you have the right one from a source you trust, type it; it will be recorded as stated by you. Without it, the study shows "[CASRN pending]".`,
    }
  }
  return { kind: 'ok' }
}

/**
 * The identity sent with a create or an identity fill: everything from the
 * lookup, except the CAS number when the lookup gave none usable. Then it is
 * the person's, marked as theirs (`casrn_from: "person"`), or null when they
 * left it empty (it shows as pending).
 */
export function identityToSend(lookup: ChemicalLookup, need: IdentityNeed, typedCasrn: string): ConfirmedIdentity {
  const asked = need.kind === 'casrn'
  const typed = asked ? typedCasrn.trim() : ''
  return {
    name: lookup.identity.name,
    casrn: asked ? typed || null : lookup.identity.casrn,
    pubchem_cid: lookup.identity.pubchem_cid,
    source: {
      kind: 'lookup',
      service: lookup.service,
      looked_up_at: lookup.looked_up_at,
      ...(typed ? { casrn_from: 'person' as const } : {}),
    },
  }
}
