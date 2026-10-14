import type { SectionState } from '../api/types'

/**
 * One mark for a section's standing (MODULES.md §4.5), built from what the
 * backend serves: stale, regenerated, approved, machine_may_write, maturity,
 * approvable. It replaces the two meanings of "protected". The worst news
 * wins the mark; the rest is in its explanation.
 */

export type SectionStatusInput = Pick<
  SectionState,
  'approved' | 'stale' | 'regenerated' | 'machine_may_write' | 'approvable'
> &
  Partial<Pick<SectionState, 'maturity' | 'version_status' | 'wording_review' | 'blocked_by'>>

export interface SectionMark {
  id: 'stale' | 'regenerated' | 'needs-reapproval' | 'final' | 'approved' | 'owned' | 'blocked' | 'draft'
  label: string
  color: string
  explain: string
}

export function sectionMark(s: SectionStatusInput): SectionMark {
  if (s.stale) {
    return {
      id: 'stale',
      label: s.approved ? 'Approved, out of date' : 'Out of date',
      color: 'red',
      explain: 'What it was written from has changed since. Read it again before it can be approved or published.',
    }
  }
  if (s.regenerated) {
    return {
      id: 'regenerated',
      label: 'Rewritten',
      color: 'orange',
      explain: `The machine rewrote it. Why: ${s.regenerated.reason} Read it again and approve it if it is right.`,
    }
  }
  if (s.version_status === 'needs-re-bless') {
    return { id: 'needs-reapproval', label: 'Needs approving again', color: 'orange', explain: 'It changed since it was approved. Read it again.' }
  }
  if (s.approved) {
    const final = s.maturity === 'final'
    return {
      id: final ? 'final' : 'approved',
      label: final ? 'Final' : 'Approved',
      color: 'green',
      explain: s.machine_may_write
        ? 'A person approved it.'
        : 'A person approved it; the machine will not change it.',
    }
  }
  if (!s.machine_may_write) {
    return {
      id: 'owned',
      label: 'Kept as written',
      color: 'blue',
      explain: 'A person owns this text (it was edited outside the application, or marked to keep); the machine will not change it. It is not approved yet.',
    }
  }
  if (!s.approvable) {
    const by = s.blocked_by && s.blocked_by.length > 0 ? ` It waits on: ${s.blocked_by.join(', ')}.` : ''
    return { id: 'blocked', label: 'Not ready', color: 'default', explain: `It cannot be approved yet.${by}` }
  }
  return {
    id: 'draft',
    label: 'Draft',
    color: 'default',
    explain: 'Written by the machine and not approved. It may be rewritten when the study is processed again.',
  }
}
