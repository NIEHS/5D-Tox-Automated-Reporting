import { describe, expect, it } from 'vitest'
import { BOOK_REFUSED, DEMO_REVIEWS, REASON_PROCESS_AGAIN } from '../../api/mocks/fixtures/demo-review'

/**
 * The wording rules for team-facing text (spec §5): nobody is addressed as
 * "you"; American spelling; the interface is never called by the word the lint rule names. The
 * module's own sources are scanned, comments and imports left out, so every
 * string a person can see is covered, whichever component shows it.
 */

const sources = import.meta.glob<string>(['./*.ts', './*.tsx', '!./*.test.ts', '!./*.test.tsx', '!./testing.ts'], {
  eager: true,
  query: '?raw',
  import: 'default',
})

const SECOND_PERSON = /\b(you|your|yours|yourself)\b/i
// The word is put together here so that this file does not itself contain it.
const THE_WORD = ['wiz', 'ard'].join('')
const NAMED = new RegExp(THE_WORD, 'i')
const BRITISH =
  /\b(\w*colour\w*|\w*behaviour\w*|\w*favour\w*|\w*(?:organi|summari|recogni|normali|categori|standardi|optimi|minimi|customi|finali|initiali|visuali|prioriti|utili|characteri|speciali|generali|authori)s(?:e[ds]?|ing|ation\w*)|analyse[ds]?|emphasise[ds]?|modell(?:ed|ing)|labell(?:ed|ing)|cent(?:re|red)|programme|licence|catalogue[ds]?|grey)\b/i

/** The code without its comments and its import lines. */
function visible(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|[^:'"`])\/\/.*$/gm, '$1')
    .replace(/^import .*$/gm, ' ')
}

function breaks(text: string): boolean {
  return SECOND_PERSON.test(text) || BRITISH.test(text) || NAMED.test(text)
}

describe('the wording of the review page', () => {
  it('scans every source of the module', () => {
    expect(Object.keys(sources).sort()).toEqual(
      [
        './Book.tsx',
        './Downloads.tsx',
        './HistoryDrawer.tsx',
        './Rail.tsx',
        './ReopenDialog.tsx',
        './ReviewPage.tsx',
        './ids.ts',
        './index.ts',
        './queries.ts',
        './save.ts',
        './words.ts',
      ].sort(),
    )
  })

  it('addresses nobody, is American, and never uses the word the interface is not called by', () => {
    const problems: string[] = []
    for (const [file, source] of Object.entries(sources)) {
      visible(source)
        .split('\n')
        .forEach((line, i) => {
          for (const [what, rule] of [
            ['addresses the reader', SECOND_PERSON],
            ['British spelling', BRITISH],
            [`says "${THE_WORD}"`, NAMED],
          ] as const) {
            const m = rule.exec(line)
            if (m) problems.push(`${file}:${i + 1}: ${what} (${m[0]})`)
          }
        })
    }
    expect(problems).toEqual([])
  })

  it("the backend's own words on the page, and the hand-made mock texts, follow the same rules", () => {
    const served = Object.values(DEMO_REVIEWS).flatMap((r) => [
      r.book.say,
      r.asked?.say ?? '',
      r.acts.say ?? '',
      ...r.downloads.map((d) => d.title),
      ...r.groups.flatMap((g) => [g.title, ...g.sections.flatMap((s) => [s.title, s.writer_say, s.accept.say ?? ''])]),
    ])
    expect(served.length).toBeGreaterThan(100)
    expect([...new Set(served)].filter(breaks)).toEqual([])
    expect([REASON_PROCESS_AGAIN, BOOK_REFUSED.body.replace(/<[^>]+>/g, ' ')].filter(breaks)).toEqual([])
  })
})
