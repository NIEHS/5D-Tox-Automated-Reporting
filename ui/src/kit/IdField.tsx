import { CheckCircleFilled } from '@ant-design/icons'
import { Button, Input, Space, Typography, type InputProps } from 'antd'
import { useEffect, useId, useRef, useState } from 'react'
import type { IdKind } from '../api/types'
import { ID_LABELS, checkId, dtxsidsIn, isDtxsidKind, type IdCheck } from './checkId'
import { useVocabularies } from './useVocabularies'

/**
 * An id typed by a person: a study id (a bare DTXSID), a CAS number or a DOI
 * (MODULES.md §4.5). Checked as it is typed, with the backend's pattern; the
 * reason it is wrong is shown under it. Controlled, for antd Form.Item.
 *
 * `onCheck` reports whether the value is good, so the screen can keep its
 * "save" closed until it is. An id that cannot be checked (the rule did not
 * load) is never reported good.
 *
 * `optional`: an empty field is acceptable (no message, `onCheck` reports
 * true once the rule has loaded); anything typed is checked as usual.
 *
 * A DTXSID (kinds `dtxsid` and `study_id`) is made upper case as it is typed,
 * visibly in the field. Pasted text loses its spaces at either end. When
 * pasted text holds exactly one DTXSID but is not one (a CompTox address),
 * the field offers "Use DTXSID…?"; it is never filled without that click.
 */

export interface IdFieldProps {
  kind: IdKind
  value?: string
  onChange?: (value: string) => void
  onCheck?: (ok: boolean) => void
  label?: string
  id?: string
  disabled?: boolean
  onBlur?: () => void
  /** an empty value is acceptable; a typed one must still be right */
  optional?: boolean
  inputProps?: Omit<InputProps, 'value' | 'onChange' | 'status' | 'disabled' | 'onBlur' | 'onPaste'>
}

export function IdField({ kind, value = '', onChange, onCheck, label, id, disabled, onBlur, optional, inputProps }: IdFieldProps) {
  const { data, isPending } = useVocabularies()
  const helpId = useId()
  const [touched, setTouched] = useState(value !== '')
  const [offer, setOffer] = useState<string | null>(null)
  const dtxsid = isDtxsidKind(kind)
  const shape = (text: string) => (dtxsid ? text.toUpperCase() : text)
  const pattern = data?.patterns?.[kind]
  // a DTXSID must also be an id the store can hold (the served session-id rule bounds its length)
  const storeRule = dtxsid ? data?.patterns?.session_id : undefined
  const emptyOptional = Boolean(optional) && value === ''
  const check: IdCheck | null = isPending || emptyOptional ? null : checkId(kind, value, pattern, storeRule)
  const name = label ?? ID_LABELS[kind]
  // while "Use DTXSID…?" is offered for pasted text, only the offer is shown, not the error beside it
  const offering = offer !== null && offer !== value

  const showProblem = !offering && check !== null && check.ok !== true && (touched || check.ok === null)
  const good = check?.ok === true
  const acceptable = good || (emptyOptional && !isPending)
  const onCheckRef = useRef(onCheck)
  useEffect(() => {
    onCheckRef.current = onCheck
  })
  useEffect(() => {
    onCheckRef.current?.(acceptable)
  }, [acceptable])

  return (
    <Space orientation="vertical" size={2} style={{ width: '100%' }}>
      <Input
        {...inputProps}
        id={id}
        aria-label={name}
        aria-invalid={showProblem}
        aria-describedby={showProblem ? helpId : undefined}
        placeholder={pattern ? `e.g. ${pattern.example}` : undefined}
        value={value}
        disabled={disabled || isPending}
        status={showProblem ? 'error' : undefined}
        spellCheck={false}
        autoComplete="off"
        suffix={good ? <CheckCircleFilled aria-label="looks right" style={{ color: '#52c41a' }} /> : <span />}
        onChange={(e) => {
          setTouched(true)
          setOffer(null)
          onChange?.(shape(e.target.value))
        }}
        onPaste={(e) => {
          const pasted = e.clipboardData.getData('text')
          const trimmed = pasted.trim()
          const input = e.currentTarget
          e.preventDefault()
          const start = input.selectionStart ?? value.length
          const end = input.selectionEnd ?? value.length
          const next = shape(value.slice(0, start) + trimmed + value.slice(end))
          setTouched(true)
          onChange?.(next)
          const found = dtxsid ? dtxsidsIn(trimmed) : []
          setOffer(found.length === 1 && found[0] !== next ? (found[0] ?? null) : null)
        }}
        onBlur={() => {
          setTouched(true)
          onBlur?.()
        }}
      />
      {showProblem && check && !check.ok && (
        <Typography.Text id={helpId} type="danger" style={{ fontSize: 12 }}>
          {check.say}
        </Typography.Text>
      )}
      {offering && (
        <Space size={4} wrap data-testid="id-offer">
          <Typography.Text style={{ fontSize: 13 }}>The pasted text holds a DTXSID.</Typography.Text>
          <Button
            size="small"
            onClick={() => {
              setOffer(null)
              onChange?.(offer)
            }}
          >
            Use {offer}?
          </Button>
        </Space>
      )}
    </Space>
  )
}
