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

/** The DTXSID kinds: a chemical's id, and a study's id (which is the chemical's DTXSID alone). */
export function isDtxsidKind(kind: IdKind): boolean {
  return kind === 'dtxsid' || kind === 'study_id'
}

/**
 * The mistakes a DTXSID is typed with, named before the pattern only says
 * "wrong" (M1 spec §4, rules 3 to 6). Never corrected here: the person is
 * told and retypes.
 */
function dtxsidProblem(value: string, example: string): string | null {
  if (!value.startsWith('DTXSID')) {
    if (/^dtxsid/i.test(value)) return 'Write DTXSID in capital letters.'
    return `A DTXSID starts with 'DTXSID', for example ${example}.`
  }
  const rest = value.slice('DTXSID'.length)
  const suffix = /[_-]/.exec(rest)
  if (suffix) {
    const base = value.slice(0, 'DTXSID'.length + suffix.index)
    const named = /^DTXSID\d+$/.test(base) ? ` (${base})` : ''
    return `A study's id is the DTXSID alone${named}. Ids with a suffix (…_rat, …_published) are made by the system.`
  }
  const lookAlike = /[OIL]/i.exec(rest)
  if (lookAlike) {
    const position = 'DTXSID'.length + lookAlike.index + 1
    return `Character ${position} is the letter ${lookAlike[0].toUpperCase()}. A DTXSID has only digits after 'DTXSID'.`
  }
  return null
}

/** Every DTXSID in a piece of pasted text (a CompTox address, a sentence), upper case, without repeats. */
export function dtxsidsIn(text: string): string[] {
  return [...new Set(text.toUpperCase().match(/DTXSID\d+/g) ?? [])]
}

/**
 * `storeRule` is the backend's rule for any id it can hold (the served
 * `session_id` pattern). A DTXSID kind is checked against it too: the served
 * DTXSID pattern sets no length, but the store does, and an id it can't hold
 * must not look right here only to be refused after Next.
 */
export function checkId(kind: IdKind, value: string, pattern: IdPattern | undefined, storeRule?: IdPattern): IdCheck {
  if (!pattern) return { ok: null, say: `The rule for a ${ID_LABELS[kind]} could not be loaded, so this cannot be checked yet.` }
  const re = compile(pattern)
  if (!re) return { ok: null, say: `The rule for a ${ID_LABELS[kind]} is broken, so this cannot be checked. Tell whoever looks after the application.` }
  if (value === '') {
    if (kind === 'dtxsid') return { ok: false, say: "Enter the chemical's DTXSID." }
    return { ok: false, say: `Type the ${ID_LABELS[kind]}, for example ${pattern.example}.` }
  }
  if (value !== value.trim()) return { ok: false, say: 'Remove the spaces before or after it.' }

  if (isDtxsidKind(kind)) {
    const problem = dtxsidProblem(value, pattern.example)
    if (problem) return { ok: false, say: problem }
    if (!re.test(value)) return { ok: false, say: `After 'DTXSID' come digits only, for example ${pattern.example}.` }
    const store = storeRule ? compile(storeRule) : null
    if (storeRule && !store) {
      return { ok: null, say: `The rule for a ${ID_LABELS[kind]} is broken, so this cannot be checked. Tell whoever looks after the application.` }
    }
    if (store && !store.test(value)) {
      return { ok: false, say: `This is longer than any DTXSID the application can hold. Check it, for example ${pattern.example}.` }
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
    // M1 spec §4's words
    return { ok: false, say: "This CASRN's check digit doesn't match; a digit is probably mistyped." }
  }
  return { ok: true }
}
