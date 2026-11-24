import { describe, expect, it } from 'vitest'

/**
 * The wording rules for text the study team reads (spec §5): nobody is
 * addressed directly and the spelling is American. Checked on the source of
 * the Study files page, so a string no test happens to render is covered too. (The third rule, the word the interface is never
 * called, is the linter's: eslint.config.js.)
 */

const sources = import.meta.glob<string>('./*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
})

const SECOND_PERSON = /\b(you|your|yours|yourself)\b/i
// As tests/unit/test_api_guide.py checks the API page's guide.
const BRITISH =
  /\b(\w*colour\w*|\w*behaviour\w*|\w*favour\w*|\w*(?:organi|summari|recogni|normali|categori|standardi|materiali|optimi|minimi|customi|finali|initiali|visuali|prioriti|harmoni|utili|characteri|speciali|generali|synchroni|authori|digiti|randomi)s(?:e[ds]?|ing|ation\w*)|analyse[ds]?|emphasise[ds]?|modell(?:ed|ing)|labell(?:ed|ing)|cent(?:re|red)|programme|licence|catalogue[ds]?|grey)\b/i

const pages = Object.entries(sources).filter(([path]) => !/\.test\.tsx?$/.test(path))

describe('the wording of Study files', () => {
  it('covers the page’s whole source', () => {
    const names = pages.map(([path]) => path)
    expect(names).toContain('./FilesPage.tsx')
    expect(names).toContain('./words.ts')
    expect(names).toContain('./queries.ts')
  })

  it.each(pages)('%s addresses nobody and is American', (_path, text) => {
    const problems: string[] = []
    text.split('\n').forEach((line, i) => {
      for (const [rule, what] of [
        [SECOND_PERSON, 'addresses the reader'],
        [BRITISH, 'British spelling'],
      ] as const) {
        const m = rule.exec(line)
        if (m) problems.push(`line ${i + 1}: ${what} (${m[0]})`)
      }
    })
    expect(problems).toEqual([])
  })
})
