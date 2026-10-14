import { Alert, Button, Input, Modal, Space, Typography, type ButtonProps } from 'antd'
import { useState } from 'react'
import { getDryRun, noopOf } from '../api/client'
import { ApiError } from '../api/errors'
import type { DryRun, Noop } from '../api/types'
import { Refusal } from './Refusal'
import { useStudyMutation } from './useStudyState'

/**
 * Confirm-or-undo for an act that changes or destroys something
 * (MODULES.md §4.3). The strength and the consequences come from the
 * backend's dry run, fetched when the person clicks; nothing is listed from
 * the front-end's own knowledge.
 *
 * - reversible: done at once, then an Undo link (needs `undo`);
 * - costly: a dialog listing what will be deleted, kept and lost;
 * - irreversible: the same dialog, and the person types the study id.
 *
 * A reversible act with no `undo`, or one that needs a reason, gets the
 * dialog too. An unknown strength is treated as irreversible. If the dry run
 * cannot be had, the act is not offered.
 */

export interface ConfirmActProps {
  studyId: string
  /** the act's name, as the dry-run endpoint knows it */
  act: string
  /** what the button says, in plain words ("Start over") */
  label: string
  /** do the act; gets the reason when the backend asked for one */
  perform: (input: { reason?: string }) => Promise<unknown>
  /** undo a reversible act */
  undo?: () => Promise<unknown>
  /** called with the act's answer once it is done */
  onDone?: (result: unknown) => void
  /** fetch the dry run; defaults to GET …/dry-run/{act} */
  loadDryRun?: (signal?: AbortSignal) => Promise<DryRun>
  /** the act is not allowed now; `disabledReason` must say why */
  disabled?: boolean
  disabledReason?: string
  buttonProps?: Omit<ButtonProps, 'onClick' | 'disabled' | 'loading' | 'children'>
}

type Phase =
  | { at: 'idle' }
  | { at: 'loading' }
  | { at: 'dialog'; dry: DryRun }
  | { at: 'done'; dry: DryRun; noop: Noop | null }
  | { at: 'undone' }

const KNOWN_STRENGTHS = new Set(['reversible', 'costly', 'irreversible'])

function needsDialog(dry: DryRun, canUndo: boolean): boolean {
  return dry.strength !== 'reversible' || dry.reason_required || !canUndo
}

function isIrreversible(dry: DryRun): boolean {
  return dry.strength === 'irreversible' || !KNOWN_STRENGTHS.has(dry.strength)
}

function Consequences({ dry }: { dry: DryRun }) {
  return (
    <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
      {isIrreversible(dry) ? (
        <Alert type="error" showIcon title="This cannot be undone." />
      ) : dry.strength === 'costly' ? (
        <Alert type="warning" showIcon title="This cannot be undone from here, and it takes time to redo." />
      ) : null}
      {dry.deletes.length > 0 && (
        <section aria-label="It will delete">
          <Typography.Text strong>It will delete:</Typography.Text>
          <ul style={{ margin: '4px 0 0' }}>
            {dry.deletes.map((d) => (
              <li key={d.what}>
                {d.say ? (
                  <>
                    {d.say} <Typography.Text type="secondary">({d.what})</Typography.Text>
                  </>
                ) : (
                  d.what
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {dry.approvals_lost.length > 0 && (
        <section aria-label="Approvals that will be lost">
          <Typography.Text strong type="danger">
            {dry.approvals_lost.length === 1 ? 'This approval will be lost:' : `These ${dry.approvals_lost.length} approvals will be lost:`}
          </Typography.Text>
          <ul style={{ margin: '4px 0 0' }}>
            {dry.approvals_lost.map((k) => (
              <li key={k}>
                <Typography.Text code>{k}</Typography.Text>
              </li>
            ))}
          </ul>
        </section>
      )}
      {dry.keeps.length > 0 && (
        <section aria-label="It will keep">
          <Typography.Text strong>It will keep:</Typography.Text>
          <ul style={{ margin: '4px 0 0' }}>
            {dry.keeps.map((k) => (
              <li key={k.what}>
                {k.say ? (
                  <>
                    {k.say} <Typography.Text type="secondary">({k.what})</Typography.Text>
                  </>
                ) : (
                  k.what
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {dry.cost?.say && (
        <Typography.Paragraph style={{ margin: 0 }}>
          <Typography.Text strong>To redo it: </Typography.Text>
          {dry.cost.say}
        </Typography.Paragraph>
      )}
      {dry.deletes.length === 0 && dry.approvals_lost.length === 0 && (
        <Typography.Paragraph style={{ margin: 0 }}>Nothing will be deleted.</Typography.Paragraph>
      )}
    </Space>
  )
}

export function ConfirmAct({
  studyId,
  act,
  label,
  perform,
  undo,
  onDone,
  loadDryRun,
  disabled,
  disabledReason,
  buttonProps,
}: ConfirmActProps) {
  const [phase, setPhase] = useState<Phase>({ at: 'idle' })
  const [reason, setReason] = useState('')
  const [typedId, setTypedId] = useState('')
  const [dryError, setDryError] = useState<ApiError | null>(null)

  const doAct = useStudyMutation(studyId, (input: { reason?: string }) => perform(input))
  const doUndo = useStudyMutation(studyId, () => (undo ? undo() : Promise.resolve(undefined)))

  const finish = (dry: DryRun, result: unknown) => {
    setPhase({ at: 'done', dry, noop: noopOf(result) })
    setReason('')
    setTypedId('')
    onDone?.(result)
  }

  // A refusal from the dialog stays in the dialog; otherwise it shows under the button.
  const run = (dry: DryRun) => {
    doAct.mutate(dry.reason_required ? { reason: reason.trim() } : {}, { onSuccess: (result) => finish(dry, result) })
  }

  const start = async () => {
    setDryError(null)
    doAct.reset()
    setPhase({ at: 'loading' })
    let dry: DryRun
    try {
      dry = await (loadDryRun ? loadDryRun() : getDryRun(studyId, act))
    } catch (err) {
      setDryError(err instanceof ApiError ? err : new ApiError({ code: 'unexpected', status: 0, message: String(err), say: 'The application could not say what this would do, so it was not done.', fix: null }))
      setPhase({ at: 'idle' })
      return
    }
    if (needsDialog(dry, Boolean(undo))) {
      setPhase({ at: 'dialog', dry })
    } else {
      // the button shows the act as pending from here on
      setPhase({ at: 'idle' })
      run(dry)
    }
  }

  const dialog = phase.at === 'dialog' ? phase.dry : null
  const reasonOk = !dialog?.reason_required || reason.trim().length > 0
  const idOk = !dialog || !isIrreversible(dialog) || typedId === studyId
  const canConfirm = reasonOk && idOk && !doAct.isPending

  return (
    <div>
      <Space wrap>
        <Button
          {...buttonProps}
          disabled={disabled}
          loading={phase.at === 'loading' || doAct.isPending}
          onClick={() => void start()}
        >
          {label}
        </Button>
        {disabled && disabledReason && <Typography.Text type="secondary">{disabledReason}</Typography.Text>}
      </Space>

      {dryError && (
        <div style={{ marginTop: 8 }}>
          <Refusal error={dryError} studyId={studyId} title={`"${label}" was not done`} />
        </div>
      )}

      {phase.at !== 'dialog' && doAct.error && (
        <div style={{ marginTop: 8 }}>
          <Refusal error={doAct.error} studyId={studyId} title={`"${label}" was not done`} />
        </div>
      )}

      {phase.at === 'done' && phase.noop && (
        <div style={{ marginTop: 8 }}>
          <Refusal noop={phase.noop} studyId={studyId} />
        </div>
      )}

      {phase.at === 'done' && !phase.noop && phase.dry.strength === 'reversible' && undo && (
        <Alert
          style={{ marginTop: 8 }}
          type="success"
          showIcon
          role="status"
          title={`Done: ${label}.`}
          action={
            <Button size="small" type="link" loading={doUndo.isPending} onClick={() => doUndo.mutate(undefined, { onSuccess: () => setPhase({ at: 'undone' }) })}>
              Undo
            </Button>
          }
        />
      )}
      {doUndo.error && (
        <div style={{ marginTop: 8 }}>
          <Refusal error={doUndo.error} studyId={studyId} title="The undo was not done" />
        </div>
      )}
      {phase.at === 'undone' && <Alert style={{ marginTop: 8 }} type="info" showIcon role="status" title={`Undone: ${label}.`} />}

      <Modal
        open={dialog !== null}
        title={label}
        mask={{ closable: false }}
        onCancel={() => {
          if (doAct.isPending) return
          setPhase({ at: 'idle' })
          setReason('')
          setTypedId('')
          doAct.reset()
        }}
        okText={label}
        okButtonProps={{ danger: dialog ? dialog.strength !== 'reversible' : false, disabled: !canConfirm, loading: doAct.isPending }}
        cancelText="Cancel"
        onOk={() => dialog && run(dialog)}
        destroyOnHidden
      >
        {dialog && (
          <Space orientation="vertical" size="middle" style={{ width: '100%' }}>
            <Consequences dry={dialog} />
            {dialog.reason_required && (
              <label style={{ display: 'block' }}>
                <Typography.Text strong>Why? </Typography.Text>
                <Typography.Text type="secondary">The reason is kept with the history.</Typography.Text>
                <Input.TextArea
                  aria-label="Reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  autoSize={{ minRows: 2 }}
                  status={reason.length > 0 && !reasonOk ? 'error' : undefined}
                />
              </label>
            )}
            {isIrreversible(dialog) && (
              <label style={{ display: 'block' }}>
                <Typography.Text>
                  To confirm, type the study id <Typography.Text code>{studyId}</Typography.Text>
                </Typography.Text>
                <Input
                  aria-label="Type the study id to confirm"
                  value={typedId}
                  onChange={(e) => setTypedId(e.target.value)}
                  autoComplete="off"
                  spellCheck={false}
                  status={typedId.length > 0 && !idOk ? 'error' : undefined}
                />
                {typedId.length > 0 && !idOk && (
                  <Typography.Text type="danger">That is not this study's id.</Typography.Text>
                )}
              </label>
            )}
            {doAct.error && <Refusal error={doAct.error} studyId={studyId} title={`"${label}" was not done`} />}
          </Space>
        )}
      </Modal>
    </div>
  )
}
