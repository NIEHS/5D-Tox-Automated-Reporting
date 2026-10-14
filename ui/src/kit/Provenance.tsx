import { Tag, Tooltip } from 'antd'
import { Link } from 'react-router'
import type { ModuleId } from '../api/types'
import { moduleById, moduleRoute } from './modules'

/**
 * Where a fact comes from (MODULES.md §4.5), on every fact a screen shows.
 * An origin this screen does not know is shown as unknown, in red: never
 * passed off as one of the others.
 */

export type ProvenanceKind = 'stated' | 'recorded' | 'inferred' | 'standard_design' | 'conflict'

const WORDS: Record<ProvenanceKind, { label: string; color: string; explain: string }> = {
  stated: { label: 'Stated', color: 'green', explain: 'A person stated this.' },
  recorded: { label: 'From the files', color: 'blue', explain: "Read from the study's data files." },
  inferred: {
    label: 'Inferred',
    color: 'gold',
    explain: 'Worked out from clues such as file names, not stated anywhere. Check it, and state it if it is wrong.',
  },
  standard_design: {
    label: 'Standard design, assumed',
    color: 'orange',
    explain: 'Nobody stated this and the data do not say it, so the standard design was assumed. State it if this study differs.',
  },
  conflict: { label: 'In conflict', color: 'red', explain: 'The sources disagree. Choose which one is right.' },
}

export interface ProvenanceProps {
  kind: ProvenanceKind | (string & {})
  /** more about the source, e.g. the file it was read from */
  detail?: string
  /** where to state or settle it */
  fix?: ModuleId | null
  studyId?: string
}

export function Provenance({ kind, detail, fix, studyId }: ProvenanceProps) {
  const w = (WORDS as Record<string, (typeof WORDS)[ProvenanceKind] | undefined>)[kind] ?? {
    label: 'Origin unknown',
    color: 'red',
    explain: `The application gave an origin this screen does not know ("${kind}"). Treat this value as unchecked.`,
  }
  const m = moduleById(fix)
  const to = m ? moduleRoute(m.id, studyId) : undefined
  const tip = (
    <span>
      {w.explain}
      {detail ? <> {detail}</> : null}
    </span>
  )
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <Tooltip title={tip}>
        <Tag color={w.color} tabIndex={0} aria-label={`${w.label}: ${w.explain}${detail ? ` ${detail}` : ''}`} style={{ marginInlineEnd: 0 }}>
          {w.label}
        </Tag>
      </Tooltip>
      {m && to && (kind === 'inferred' || kind === 'standard_design' || kind === 'conflict' || !(kind in WORDS)) && (
        <Link to={to} style={{ fontSize: 12 }}>
          {kind === 'conflict' ? 'Settle it' : 'State it'}
        </Link>
      )}
    </span>
  )
}
