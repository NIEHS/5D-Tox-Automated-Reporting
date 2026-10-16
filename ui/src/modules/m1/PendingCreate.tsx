import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Checkbox, Modal, Space, Spin, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { createStudy } from '../../api/m1'
import type { ApiError } from '../../api/errors'
import type { CreationCheck, StudyRow } from '../../api/types'
import { studyRoute } from '../../kit/modules'
import { Refusal } from '../../kit/Refusal'
import { FormatNotice } from './FormatNotice'
import { STUDIES_KEY, useCreationCheck } from './queries'

/**
 * "Create it with the chemical pending" (maintainer, 2026-10-16, revised):
 * the only absolute requirement for a test article's identity is its DTXSID,
 * so a lookup that does not know the DTXSID, cannot be reached, or gives no
 * name is not a dead end. The person may create the study with no identity;
 * the name and CAS number then show as pending, and the chemical is looked up
 * later from the study's page.
 *
 * It is a secondary act, behind its own confirmation. Nothing has checked the
 * DTXSID, so the person must say they checked it on the CompTox dashboard,
 * and must confirm the format the id brings, as for any new study. A person
 * never types a name here (Q-M1-3).
 */

/** Why the chemical is pending; the dialog says it in the person's words. */
export type PendingReason = 'not_found' | 'unreachable' | 'no_name'

function reasonSay(reason: PendingReason, dtxsid: string, service: string): string {
  switch (reason) {
    case 'not_found':
      return `${service} does not know ${dtxsid}. A single mistyped digit gives another chemical, or none: check the DTXSID before you go on.`
    case 'unreachable':
      return `The chemical lookup service could not be reached, so ${dtxsid} has not been checked against it.`
    case 'no_name':
      return `${service} gives no name for ${dtxsid}, so its identity can't be taken from this lookup.`
  }
}

function existingIdOf(err: ApiError): string | null {
  const v = err.details.existing_id
  return typeof v === 'string' ? v : null
}

export function PendingCreate({
  dtxsid,
  reason,
  service = 'PubChem',
  onCreated,
}: {
  dtxsid: string
  reason: PendingReason
  service?: string
  onCreated: (row: StudyRow, format: CreationCheck['format']) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button onClick={() => setOpen(true)}>Create it with the chemical pending…</Button>
      {open && (
        <PendingDialog dtxsid={dtxsid} reason={reason} service={service} onClose={() => setOpen(false)} onCreated={onCreated} />
      )}
    </>
  )
}

function PendingDialog({
  dtxsid,
  reason,
  service,
  onClose,
  onCreated,
}: {
  dtxsid: string
  reason: PendingReason
  service: string
  onClose: () => void
  onCreated: (row: StudyRow, format: CreationCheck['format']) => void
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const check = useCreationCheck(dtxsid)
  const [checked, setChecked] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [formatChanged, setFormatChanged] = useState(false)
  const c = check.data

  const create = useMutation<StudyRow, ApiError, CreationCheck>({
    mutationFn: (seen) =>
      createStudy({
        dtxsid,
        identity: null,
        identity_pending: true,
        confirmed: true,
        dtxsid_checked_by_person: checked,
        format_seen: { definition: seen.format.definition, hash: seen.format.hash ?? null },
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: STUDIES_KEY }),
    onSuccess: (row, seen) => onCreated(row, seen.format),
    onError: (err) => {
      if (err.code === 'format_changed') {
        setConfirmed(false)
        setFormatChanged(true)
        void check.refetch()
      }
    },
  })

  const canCreate = Boolean(c) && !c?.exists && checked && confirmed && !check.isFetching && !create.isPending

  return (
    <Modal
      open
      title={`Create ${dtxsid} with the chemical pending?`}
      width={720}
      mask={{ closable: false }}
      onCancel={() => !create.isPending && onClose()}
      okText="Create with the chemical pending"
      okButtonProps={{ disabled: !canCreate, loading: create.isPending }}
      onOk={() => c && canCreate && create.mutate(c)}
      cancelText="Cancel"
      destroyOnHidden
    >
      <Space orientation="vertical" size="middle" style={{ width: '100%' }} data-testid="pending-create">
        <Alert type="warning" showIcon title={reasonSay(reason, dtxsid, service)} />
        <Typography.Paragraph style={{ margin: 0 }}>
          The study will be created under {dtxsid} without its chemical's name and CAS number. They will show as
          "[name pending]" and "[CASRN pending]" until the chemical is looked up later, from the study's page (
          <strong>Look up the chemical</strong>). The DTXSID itself can't be changed later.
        </Typography.Paragraph>
        {check.error ? (
          <Refusal error={check.error} title="The format could not be read" />
        ) : !c ? (
          <Spin description="Reading the format" />
        ) : c.exists ? (
          <Alert
            type="warning"
            showIcon
            title={`A study of this chemical already exists: ${c.existing?.id ?? dtxsid}.`}
            action={<Button onClick={() => void navigate(studyRoute(c.existing?.id ?? dtxsid))}>Open it</Button>}
          />
        ) : (
          <Space orientation="vertical" size="small" style={{ width: '100%' }}>
            {formatChanged && (
              <Alert type="warning" showIcon title="The format this id brings changed since you looked. It is shown again below; review it." />
            )}
            <FormatNotice format={c.format} />
            <Checkbox
              checked={checked}
              onChange={(e) => {
                setChecked(e.target.checked)
                if (!e.target.checked) setConfirmed(false)
              }}
            >
              I checked the DTXSID {dtxsid} on the CompTox dashboard
            </Checkbox>
            <Checkbox checked={confirmed} disabled={!checked} onChange={(e) => setConfirmed(e.target.checked)}>
              <span data-testid="pending-confirm-label">
                Create the study of {dtxsid} with its chemical pending, written in <em>{c.format.title}</em>.
              </span>
            </Checkbox>
          </Space>
        )}
        {create.error && create.error.code !== 'format_changed' && (
          <Refusal
            error={create.error}
            title="The study was not created"
            action={
              create.error.code === 'study_exists' ? (
                <Button onClick={() => void navigate(studyRoute(existingIdOf(create.error) ?? dtxsid))}>Open it</Button>
              ) : undefined
            }
          />
        )}
      </Space>
    </Modal>
  )
}
