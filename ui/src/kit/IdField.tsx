import { CheckCircleFilled } from '@ant-design/icons'
import { Input, Space, Typography, type InputProps } from 'antd'
import { useEffect, useId, useRef, useState } from 'react'
import type { IdKind } from '../api/types'
import { ID_LABELS, checkId, type IdCheck } from './checkId'
import { useVocabularies } from './useVocabularies'

/**
 * An id typed by a person: a bare DTXSID, a CAS number, a DOI or a date
 * (MODULES.md §4.5). Checked as it is typed, with the backend's pattern; the
 * reason it is wrong is shown under it. Controlled, for antd Form.Item.
 *
 * `onCheck` reports whether the value is good, so the screen can keep its
 * "save" closed until it is. An id that cannot be checked (the rule did not
 * load) is never reported good.
 */

export interface IdFieldProps {
  kind: IdKind
  value?: string
  onChange?: (value: string) => void
  onCheck?: (ok: boolean) => void
  label?: string
  id?: string
  disabled?: boolean
  inputProps?: Omit<InputProps, 'value' | 'onChange' | 'status' | 'disabled'>
}

export function IdField({ kind, value = '', onChange, onCheck, label, id, disabled, inputProps }: IdFieldProps) {
  const { data, isPending } = useVocabularies()
  const helpId = useId()
  const [touched, setTouched] = useState(value !== '')
  const pattern = data?.patterns?.[kind]
  const check: IdCheck | null = isPending ? null : checkId(kind, value, pattern)
  const name = label ?? ID_LABELS[kind]

  const showProblem = check !== null && check.ok !== true && (touched || check.ok === null)
  const good = check?.ok === true
  const onCheckRef = useRef(onCheck)
  useEffect(() => {
    onCheckRef.current = onCheck
  })
  useEffect(() => {
    onCheckRef.current?.(good)
  }, [good])

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
          onChange?.(e.target.value)
        }}
        onBlur={() => setTouched(true)}
      />
      {showProblem && check && !check.ok && (
        <Typography.Text id={helpId} type="danger" style={{ fontSize: 12 }}>
          {check.say}
        </Typography.Text>
      )}
    </Space>
  )
}
