import type { IdKind, IdPattern } from '../api/types'

/**
 * Checking an id as it is typed (MODULES.md §4.5). The pattern is the
 * backend's (served with the vocabularies); the extra checks below catch the
 * mistakes a pattern alone would only call "wrong": a suffixed study id, a
 * DOI pasted as a link, a CAS number with a bad check digit. Nothing is
 * corrected silently: the person is told and retypes.
 *
 * The backend serves a pattern for each IdKind. There is no date kind: no
 * backend rule for a date exists (a report's date is stated as "April 2026"),
 * and the front-end does not invent one.
 */

export type IdCheck = { ok: true } | { ok: false; say: string } | { ok: null; say: string }

export const ID_LABELS: Record<IdKind, string> = {
  study_id: 'study id',
  session_id: 'study id',
  dtxsid: 'DTXSID',
  casrn: 'CAS number',
  doi: 'DOI',
}

/** CAS check digit: the weighted sum of the other digits, right to left, mod 10. */
export function casrnCheckDigitOk(value: string): boolean {
  const digits = value.replace(/-/g, '')
  if (!/^\d+$/.test(digits) || digits.length < 5) return false
  const check = Number(digits[digits.length - 1])
  const body = digits.slice(0, -1)
  let sum = 0
  for (let i = 0; i < body.length; i++) sum += Number(body[body.length - 1 - i]) * (i + 1)
  return sum % 10 === check
}

function compile(p: IdPattern): RegExp | null {
  try {
    return new RegExp(p.pattern)
  } catch {
    return null
  }
}

export function checkId(kind: IdKind, value: string, pattern: IdPattern | undefined): IdCheck {
  if (!pattern) return { ok: null, say: `The rule for a ${ID_LABELS[kind]} could not be loaded, so this cannot be checked yet.` }
  const re = compile(pattern)
  if (!re) return { ok: null, say: `The rule for a ${ID_LABELS[kind]} is broken, so this cannot be checked. Tell whoever looks after the application.` }
  if (value === '') return { ok: false, say: `Type the ${ID_LABELS[kind]}, for example ${pattern.example}.` }
  if (value !== value.trim()) return { ok: false, say: 'Remove the spaces before or after it.' }

  if (kind === 'dtxsid' || kind === 'study_id') {
    if (/^dtxsid/i.test(value) && !value.startsWith('DTXSID')) return { ok: false, say: 'Write DTXSID in capital letters.' }
    const suffixed = /^DTXSID\d+[_-]/.exec(value)
    if (suffixed) {
      return {
        ok: false,
        say: `A study you create is named by the chemical's DTXSID alone (${value.slice(0, suffixed[0].length - 1)}). Names with a suffix, like "_rat" or "_published", are made by the application itself.`,
      }
    }
  }
  if (kind === 'doi' && /^(https?:\/\/)?(dx\.)?doi\.org\//i.test(value)) {
    return { ok: false, say: 'Type the DOI without the link part: start at "10.".' }
  }
  if (kind === 'doi' && /^doi:/i.test(value)) {
    return { ok: false, say: 'Type the DOI without "doi:": start at "10.".' }
  }

  if (!re.test(value)) return { ok: false, say: `${pattern.say} For example: ${pattern.example}.` }

  if (kind === 'casrn' && !casrnCheckDigitOk(value)) {
    return { ok: false, say: 'The last digit (the check digit) does not match the others: the number has a typing mistake.' }
  }
  return { ok: true }
}
