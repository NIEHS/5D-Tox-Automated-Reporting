import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { STATE_APPROVED_STALE_SUMMARY } from '../api/mocks/fixtures'
import type { SectionState } from '../api/types'
import { renderWithApp } from '../test/render'
import { Pending } from './Pending'
import { Provenance } from './Provenance'
import { sectionMark } from './sectionMark'
import { SectionStatus } from './SectionStatus'

const sections = Object.fromEntries((STATE_APPROVED_STALE_SUMMARY.sections ?? []).map((s) => [s.key, s])) as Record<string, SectionState>
const base: SectionState = {
  key: 'x',
  kind: 'llm',
  approvable: true,
  approved: false,
  stale: false,
  regenerated: null,
  wording_review: [],
  source: 'generated',
  version: 1,
  version_status: null,
  machine_may_write: true,
  blocked_by: [],
}

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
  it('reads the PFHxSAm fixture', () => {
    expect(sectionMark(sections.summary as SectionState).id).toBe('stale')
    expect(sectionMark(sections.summary as SectionState).label).toBe('Approved, out of date')
    expect(sectionMark(sections.bmd_summary as SectionState).id).toBe('regenerated')
    expect(sectionMark(sections.background as SectionState).id).toBe('approved')
    expect(sectionMark(sections['bm2_hormones'] as SectionState).id).toBe('draft')
  })

  it('puts the worst news first', () => {
    expect(sectionMark({ ...base, approved: true, stale: true, regenerated: { reason: 'r' } }).id).toBe('stale')
    expect(sectionMark({ ...base, approved: true, regenerated: { reason: 'r' } }).id).toBe('regenerated')
    expect(sectionMark({ ...base, approved: true, version_status: 'needs-re-bless' }).id).toBe('needs-reapproval')
  })

  it('tells approved, final, kept-as-written, not-ready and draft apart', () => {
    expect(sectionMark({ ...base, approved: true, machine_may_write: false }).id).toBe('approved')
    expect(sectionMark({ ...base, approved: true, maturity: 'final' }).id).toBe('final')
    expect(sectionMark({ ...base, machine_may_write: false }).id).toBe('owned')
    expect(sectionMark({ ...base, approvable: false, blocked_by: ['background'] })).toMatchObject({ id: 'blocked', explain: expect.stringContaining('background') as unknown })
    expect(sectionMark(base).id).toBe('draft')
  })
})

describe('<SectionStatus>', () => {
  it('renders the mark with its explanation, and the wording to check', () => {
    renderWithApp(<SectionStatus section={sections['genomics_kidney_female'] as SectionState} />)
    const tag = screen.getByLabelText(/^Draft\./)
    expect(tag).toHaveTextContent('Draft · wording to check')
    expect(tag.getAttribute('aria-label')).toContain('"significantly"')
  })

  it('says why a regenerated section was rewritten', () => {
    renderWithApp(<SectionStatus section={sections.bmd_summary as SectionState} />)
    expect(screen.getByLabelText(/^Rewritten\. The machine rewrote it\. Why: The apical BMD results changed/)).toBeInTheDocument()
  })
})
