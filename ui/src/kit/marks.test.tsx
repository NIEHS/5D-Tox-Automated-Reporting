import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { STATE_APPROVED, STATE_EMPTY, STATE_STALE_AFTER_FILE_CHANGE } from '../api/mocks/fixtures'
import type { ExistingStudyState, SectionState } from '../api/types'
import { renderWithApp } from '../test/render'
import { Pending } from './Pending'
import { Provenance } from './Provenance'
import { sectionMark } from './sectionMark'
import { SectionStatus } from './SectionStatus'

/** A study's real section rows (the backend's answers), by key. */
function rows(state: ExistingStudyState): Record<string, SectionState> {
  return Object.fromEntries(state.sections.map((s) => [s.key, s]))
}
const pfhxsam = rows(STATE_APPROVED)
const stale = rows(STATE_STALE_AFTER_FILE_CHANGE)
const empty = rows(STATE_EMPTY)

/** A real draft row (PFHxSAm's Background, unapproved), to vary one field at a time. */
const base = pfhxsam.background as SectionState

describe('<Pending>', () => {
  it('prints the placeholder, and on click says why and where to fill it', async () => {
    const { user } = renderWithApp(<Pending label="report number" cause="Nobody has given the report number yet." fix="D5" studyId="DTXSID50469320" />)
    const mark = screen.getByRole('button', { name: 'report number is missing; show why' })
    expect(mark).toHaveTextContent('[report number pending]')
    await user.click(mark)
    expect(await screen.findByText('Nobody has given the report number yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Fill it in: Report setup' })).toHaveAttribute('href', '/studies/DTXSID50469320/setup')
  })
})

describe('<Provenance>', () => {
  it.each([
    ['stated', 'Stated'],
    ['recorded', 'From the files'],
    ['inferred', 'Inferred'],
    ['standard_design', 'Standard design, assumed'],
    ['conflict', 'In conflict'],
  ])('marks %s as "%s"', (kind, label) => {
    renderWithApp(<Provenance kind={kind} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('links an assumption to where it is stated, but not a stated fact', () => {
    const { unmount } = renderWithApp(<Provenance kind="standard_design" fix="M4" studyId="DTXSID1022477" />)
    expect(screen.getByRole('link', { name: 'State it' })).toHaveAttribute('href', '/studies/DTXSID1022477/facts')
    unmount()
    renderWithApp(<Provenance kind="stated" fix="M4" studyId="DTXSID1022477" />)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('never passes off an unknown origin as a known one', () => {
    renderWithApp(<Provenance kind="llm_guess" />)
    expect(screen.getByText('Origin unknown')).toBeInTheDocument()
    expect(screen.getByLabelText(/"llm_guess"/)).toBeInTheDocument()
  })
})

describe('sectionMark: one mark from the backend fields', () => {
  it('reads real rows: a stale, rewritten Summary after a file change; approved results; drafts', () => {
    expect(sectionMark(stale.summary as SectionState)).toMatchObject({ id: 'stale', label: 'Approved, out of date' })
    expect(sectionMark(stale.summary as SectionState).explain).toMatch(/data changed after this section was written/)
    expect(sectionMark(stale['bm2_body-weight'] as SectionState).id).toBe('final')
    expect(sectionMark(pfhxsam.background as SectionState).id).toBe('draft')
    expect(sectionMark(pfhxsam['bm2_hormones'] as SectionState).explain).toMatch(/numbers are brought up to date/)
  })

  it('never offers an approvable section with no saved text as a draft (methods, bmd_summary)', () => {
    for (const key of ['methods', 'bmd_summary']) {
      const row = pfhxsam[key] as SectionState
      expect(row.approvable && !row.has_file).toBe(true)
      const mark = sectionMark(row)
      expect(mark).toMatchObject({ id: 'cannot-approve-yet', label: "Can't be approved yet" })
      expect(mark.explain).toBe(row.accept.say)
    }
  })

  it('says what a section waits on, and why supplied text is not approved here, in the backend\'s words', () => {
    expect(sectionMark(pfhxsam.summary as SectionState)).toMatchObject({ id: 'waiting', explain: expect.stringMatching(/Background is approved/) as unknown })
    expect(sectionMark(empty.methods as SectionState)).toMatchObject({ id: 'waiting', explain: expect.stringMatching(/processed/) as unknown })
    expect(sectionMark(pfhxsam.foreword as SectionState)).toMatchObject({ id: 'not-approvable', explain: expect.stringMatching(/supplied/) as unknown })
    expect(sectionMark(pfhxsam.genomics_liver_male as SectionState).id).toBe('not-approvable')
  })

  it('puts the worst news first', () => {
    const regen = { reason: 'data_changed', say: 'It changed.' }
    expect(sectionMark({ ...base, approved: true, stale: true, regenerated: regen }).id).toBe('stale')
    expect(sectionMark({ ...base, approved: true, regenerated: regen }).id).toBe('regenerated')
    expect(sectionMark({ ...base, approved: true, version_status: 'needs-re-bless' }).id).toBe('needs-reapproval')
  })

  it('tells approved, final and kept-as-written apart from the facts', () => {
    expect(sectionMark({ ...base, approved: true, machine_may_write: false, facts: ['approved', 'protected'] }).id).toBe('approved')
    expect(sectionMark({ ...base, approved: true, facts: ['approved', 'final', 'protected'] }).id).toBe('final')
    expect(sectionMark({ ...base, machine_may_write: false }).id).toBe('owned')
  })
})

describe('<SectionStatus>', () => {
  it('says how many data-derived words changed, in words, and keeps the codes as details', () => {
    renderWithApp(<SectionStatus section={{ ...base, approved: true, facts: ['approved', 'final'], wording_review: ['Male|liver.direction_adj', 'Male|liver.trend'] }} />)
    const tag = screen.getByLabelText(/^Final\./)
    expect(tag).toHaveTextContent('Final · wording to check')
    expect(tag.getAttribute('aria-label')).toContain('2 words that come from the data have changed')
    expect(tag.getAttribute('aria-label')).not.toContain('direction_adj')
  })

  it('says why a section was rewritten, in words and never the reason code', () => {
    renderWithApp(<SectionStatus section={stale.summary as SectionState} />)
    const tag = screen.getByLabelText(/^Approved, out of date\. The study's data changed/)
    expect(tag.getAttribute('aria-label')).not.toContain('data_changed')
  })
})
