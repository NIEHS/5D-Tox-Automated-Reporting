import { Select, Space, Typography, type SelectProps } from 'antd'
import { useId } from 'react'
import { choicesFor, useVocabularies } from './useVocabularies'

/**
 * A choice bound to one controlled vocabulary (MODULES.md §4.5). Only the
 * vocabulary's values can be chosen: there is no free text. A dependent
 * field (strain ← species) is closed until its parent is chosen, and a value
 * that no longer fits its parent is flagged, never silently cleared or kept.
 * It never starts with a value the person did not choose.
 *
 * Controlled, so it works inside an antd Form.Item (value / onChange).
 */

export interface VocabFieldProps {
  /** the vocabulary's key, e.g. "species", "strain" */
  vocab: string
  value?: string | null
  onChange?: (value: string | undefined) => void
  /** the value of the field this one depends on (the species, for strain) */
  parentValue?: string | null
  /** the field's own label; defaults to the vocabulary's */
  label?: string
  disabled?: boolean
  allowClear?: boolean
  id?: string
  selectProps?: Omit<SelectProps<string>, 'value' | 'onChange' | 'options' | 'mode' | 'disabled'>
}

export function VocabField({
  vocab,
  value,
  onChange,
  parentValue,
  label,
  disabled,
  allowClear = true,
  id,
  selectProps,
}: VocabFieldProps) {
  const { data, error, isPending } = useVocabularies()
  const helpId = useId()
  const choices = choicesFor(data, vocab, parentValue)
  const name = label ?? data?.vocabularies[vocab]?.label ?? vocab

  let help: React.ReactNode = null
  let status: 'error' | 'warning' | undefined
  let closed = Boolean(disabled)

  if (error) {
    help = 'The list of allowed values could not be loaded, so nothing can be chosen here yet.'
    status = 'error'
    closed = true
  } else if (isPending) {
    closed = true
  } else if (choices.kind === 'unknown') {
    help = `There is no list of allowed values called "${vocab}".`
    status = 'error'
    closed = true
  } else if (choices.kind === 'needs-parent') {
    help = `Choose the ${choices.parentLabel.toLowerCase()} first.`
    closed = true
    if (value) status = 'warning'
  } else if (choices.values.length === 0) {
    help = `No ${name.toLowerCase()} is allowed for this ${parentValue ?? 'choice'}.`
    closed = true
    if (value) status = 'error'
  } else if (value && !choices.values.includes(value)) {
    help = `"${value}" is not an allowed ${name.toLowerCase()}${parentValue ? ` for ${parentValue}` : ''}. Choose another.`
    status = 'error'
  }

  const options = choices.kind === 'choices' ? choices.values.map((v) => ({ value: v, label: v })) : []

  return (
    <Space orientation="vertical" size={2} style={{ width: '100%' }}>
      <Select<string>
        {...selectProps}
        id={id}
        aria-label={name}
        aria-describedby={help ? helpId : undefined}
        style={{ minWidth: 200, ...(selectProps?.style ?? {}) }}
        showSearch={{ optionFilterProp: 'label' }}
        placeholder={`Choose the ${name.toLowerCase()}`}
        value={value ?? undefined}
        onChange={(v) => onChange?.(v ?? undefined)}
        options={options}
        disabled={closed}
        loading={isPending}
        allowClear={allowClear}
        status={status}
        notFoundContent="No allowed value matches what you typed."
      />
      {help && (
        <Typography.Text id={helpId} type={status === 'error' ? 'danger' : 'secondary'} style={{ fontSize: 12 }}>
          {help}
        </Typography.Text>
      )}
    </Space>
  )
}
