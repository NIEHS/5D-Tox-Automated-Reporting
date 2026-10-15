import type { SectionState } from '../api/types'

/**
 * One mark for a section's standing (MODULES.md §4.5), built from what the
 * backend serves: stale, regenerated, version_status, approved, facts,
 * machine_may_write and the `accept` verdict. It replaces the two meanings of
 * "protected". The worst news wins the mark; the rest is in its explanation.
 *
 * Whether a section can be approved is never worked out here: it is the
 * backend's `accept` verdict. In particular, a section the catalog calls
 * approvable but that has no saved text (Methods and the apical BMD summary,
 * until C9) is "Can't be approved yet", with the backend's reason, never
 * "Draft".
 */

export type SectionStatusInput = Pick<
  SectionState,
  'approved' | 'stale' | 'regenerated' | 'machine_may_write' | 'accept' | 'kind' | 'has_file'
> &
  Partial<Pick<SectionState, 'facts' | 'version_status' | 'wording_review'>>

export interface SectionMark {
  id:
    | 'stale'
    | 'regenerated'
    | 'needs-reapproval'
    | 'final'
    | 'approved'
    | 'owned'
    | 'not-approvable'
    | 'waiting'
    | 'cannot-approve-yet'
    | 'draft'
  label: string
  color: string
  explain: string
}

const REREAD = 'Read it again before it can be approved or published.'

export function sectionMark(s: SectionStatusInput): SectionMark {
  if (s.stale) {
    return {
      id: 'stale',
      label: s.approved ? 'Approved, out of date' : 'Out of date',
      color: 'red',
      explain: s.regenerated?.say ?? `What it was written from has changed since. ${REREAD}`,
    }
  }
  if (s.regenerated) {
    return {
      id: 'regenerated',
      label: 'Rewritten',
      color: 'orange',
      explain: `The machine rewrote it. ${s.regenerated.say}`,
    }
  }
  if (s.version_status === 'needs-re-bless') {
    return { id: 'needs-reapproval', label: 'Needs approving again', color: 'orange', explain: `It changed since it was approved. ${REREAD}` }
  }
  if (s.approved) {
    const final = (s.facts ?? []).includes('final')
    return {
      id: final ? 'final' : 'approved',
      label: final ? 'Final' : 'Approved',
      color: 'green',
      explain: s.machine_may_write ? 'A person approved it.' : 'A person approved it; the machine will not change it.',
    }
  }
  if (!s.machine_may_write) {
    return {
      id: 'owned',
      label: 'Kept as written',
      color: 'blue',
      explain:
        'A person owns this text (it was edited outside the application, or marked to keep); the machine will not change it. It is not approved yet.',
    }
  }
  if (!s.accept.allowed) {
    const why = s.accept.say ?? 'The application did not say why it cannot be approved.'
    if (s.accept.code === 'not_approvable') {
      return { id: 'not-approvable', label: 'Not approved on its own', color: 'default', explain: why }
    }
    if (s.accept.code === 'blocked') {
      return { id: 'waiting', label: 'Waiting', color: 'default', explain: why }
    }
    return { id: 'cannot-approve-yet', label: "Can't be approved yet", color: 'default', explain: why }
  }
  return {
    id: 'draft',
    label: 'Draft',
    color: 'default',
    explain:
      s.kind === 'programmatic'
        ? 'Built from the data and not approved. Its numbers are brought up to date when the study is processed again.'
        : 'Written by the machine and not approved. It may be rewritten when the study is processed again.',
  }
}
