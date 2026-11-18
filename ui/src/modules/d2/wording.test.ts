import { describe, expect, it } from 'vitest'
import {
  REFUSAL_BACKGROUND_SOURCES_UNREACHABLE,
  STREAM_BACKGROUND_OK,
  STREAM_SUMMARY_OK,
} from '../../api/mocks/fixtures/demo-writing'

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

describe('the wording of the Written sections page', () => {
  it('scans every source of the module', () => {
    expect(Object.keys(sources).sort()).toEqual(
      ['./Citations.tsx', './PartView.tsx', './WritingPage.tsx', './WrittenSections.tsx', './index.ts', './marks.tsx', './queries.ts', './words.ts'].sort(),
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

  it('the hand-made mock texts follow the same rules', () => {
    const texts = [
      REFUSAL_BACKGROUND_SOURCES_UNREACHABLE.error.say,
      ...[...STREAM_BACKGROUND_OK, ...STREAM_SUMMARY_OK].flatMap((e) => (e.event === 'step' ? [e.say] : [])),
    ]
    expect(texts.filter((t) => SECOND_PERSON.test(t) || BRITISH.test(t) || NAMED.test(t))).toEqual([])
  })
})
