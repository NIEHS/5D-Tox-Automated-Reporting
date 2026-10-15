import type { ChemicalLookup, IdPattern } from '../../api/types'
import { checkId } from '../../kit/checkId'

/**
 * Why a looked-up identity can't be used, or null when it can. The backend
 * refuses a study or an identity without a name and a CAS number
 * (`identity_incomplete`), or with a CAS number whose check digit fails
 * (`invalid_casrn`); the screen never offers what it would refuse. No CAS
 * number is typed in instead: a stated identity is ruled out (Q-M1-3).
 * `outcome` finishes the sentence: "a study can't be created", "this
 * identity can't be saved".
 */
export function identityGap(lookup: ChemicalLookup, outcome: string, casrnPattern?: IdPattern): string | null {
  const { name, casrn } = lookup.identity
  const svc = lookup.service
  const missing = [!name?.trim() && 'name', !casrn?.trim() && 'CAS number'].filter(Boolean) as string[]
  if (missing.length > 0) {
    const what = missing.length === 2 ? 'no name and no CAS number' : `no ${missing[0]}`
    return (
      `${svc} gives ${what} for this chemical, so ${outcome} from this lookup yet. ` +
      "A study needs the chemical's name and CAS number. Ask the maintainer how to go on."
    )
  }
  // the pattern is the backend's; when it has not loaded, the backend decides
  const c = casrnPattern ? checkId('casrn', (casrn ?? '').trim(), casrnPattern) : null
  if (c && c.ok === false) {
    return (
      `The CAS number ${svc} gives for this chemical (${casrn}) is not a valid one, so ${outcome} ` +
      'from this lookup yet. Ask the maintainer how to go on.'
    )
  }
  return null
}
