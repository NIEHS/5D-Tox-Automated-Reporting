import { Tag, Tooltip } from 'antd'
import type { PHASES } from '../api/types'

/**
 * Where a study stands, as a tag (M1 R3): the backend's plain words
 * (`stands.say`), coloured by the derived phase. The words are never made
 * here; the colour only follows the phase the backend served. A session with
 * no phase of its own (published content, a report over several studies)
 * gets a neutral tag. A phase this screen does not know is shown, in red,
 * never hidden.
 */

const COLOURS: Record<(typeof PHASES)[number], string> = {
  EMPTY: 'default',
  UPLOADED: 'blue',
  VALIDATION_ERRORS: 'red',
  VALIDATED: 'cyan',
  INTEGRATED: 'geekblue',
  APPROVED: 'green',
}

export interface PhaseTagProps {
  /** the derived phase; null when the session has none of its own */
  phase: string | null | undefined
  /** the backend's words for where it stands */
  say: string
}

export function PhaseTag({ phase, say }: PhaseTagProps) {
  if (!phase) {
    return (
      <Tag data-testid="phase" data-phase="none">
        {say}
      </Tag>
    )
  }
  const colour = (COLOURS as Record<string, string | undefined>)[phase]
  if (!colour) {
    return (
      <Tooltip title={`The application reported a stage this page does not know ("${phase}").`}>
        <Tag data-testid="phase" data-phase={phase} color="red">
          {say}
        </Tag>
      </Tooltip>
    )
  }
  return (
    <Tag data-testid="phase" data-phase={phase} color={colour}>
      {say}
    </Tag>
  )
}
