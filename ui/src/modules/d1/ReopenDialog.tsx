import { Input, Modal, Space, Typography } from 'antd'
import { useId, useState } from 'react'
import type { ReviewSection } from '../../api/demoReview'
import type { ApiError } from '../../api/errors'
import { Refusal } from '../../kit/Refusal'
import { ACT_REFUSED_TITLE, CANCEL, REOPEN_EXPLAIN, REOPEN_OK, REOPEN_REASON_LABEL, REOPEN_REASON_MISSING, REOPEN_TITLE } from './words'

/**
 * Reopening an approved section: a reason is required before anything is
 * sent (the backend requires it too, and keeps it in the section's history).
 */
export function ReopenDialog({
  section,
  sending,
  error,
  onCancel,
  onReopen,
}: {
  section: ReviewSection
  sending: boolean
  /** the backend's refusal of the last attempt, if any */
  error: ApiError | null
  onCancel: () => void
  onReopen: (reason: string) => void
}) {
  const [reason, setReason] = useState('')
  const [missing, setMissing] = useState(false)
  const fieldId = useId()
  const errorId = useId()

  const submit = () => {
    const given = reason.trim()
    if (!given) {
      setMissing(true)
      return
    }
    onReopen(given)
  }

  return (
    <Modal
      open
      title={REOPEN_TITLE(section.title)}
      okText={REOPEN_OK}
      cancelText={CANCEL}
      onOk={submit}
      onCancel={onCancel}
      confirmLoading={sending}
      mask={{ closable: false }}
    >
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        <Typography.Paragraph style={{ margin: 0 }}>{REOPEN_EXPLAIN}</Typography.Paragraph>
        <label htmlFor={fieldId}>
          <Typography.Text strong>{REOPEN_REASON_LABEL}</Typography.Text>
        </label>
        <Input.TextArea
          id={fieldId}
          autoFocus
          rows={3}
          maxLength={2000}
          value={reason}
          status={missing ? 'error' : undefined}
          aria-invalid={missing}
          aria-describedby={missing ? errorId : undefined}
          onChange={(e) => {
            setReason(e.target.value)
            if (e.target.value.trim()) setMissing(false)
          }}
        />
        {missing && (
          <Typography.Text type="danger" id={errorId} role="alert">
            {REOPEN_REASON_MISSING}
          </Typography.Text>
        )}
        {error && <Refusal error={error} studyId={section.owner} title={ACT_REFUSED_TITLE('reopened', section.title)} />}
      </Space>
    </Modal>
  )
}
