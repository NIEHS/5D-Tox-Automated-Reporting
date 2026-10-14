import { screen, waitFor, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/errors'
import { DRY_RUN_ACCEPT_SECTION, DRY_RUN_CLEAR_FILES, DRY_RUN_RELEASE_SECTION, DRY_RUN_RESET, REFUSAL_PHASE_NOT_ALLOWED } from '../api/mocks/fixtures'
import { server } from '../api/mocks/node'
import type { DryRun } from '../api/types'
import { renderWithApp } from '../test/render'
import { ConfirmAct } from './ConfirmAct'

const ID = 'DTXSID50469320'

function setup(props: Partial<React.ComponentProps<typeof ConfirmAct>> & { dry?: DryRun }) {
  const perform = props.perform ?? vi.fn(() => Promise.resolve({ ok: true }))
  const { dry, ...rest } = props
  const r = renderWithApp(
    <ConfirmAct
      studyId={ID}
      act={dry?.act ?? 'reset_pool'}
      label={rest.label ?? 'Start over'}
      perform={perform}
      loadDryRun={dry ? () => Promise.resolve(dry) : undefined}
      {...rest}
    />,
  )
  return { ...r, perform }
}

async function dialog() {
  return within(await screen.findByRole('dialog'))
}

describe('<ConfirmAct>, irreversible', () => {
  it('lists what the backend says it deletes, keeps and loses, and asks for the study id', async () => {
    const { user, perform } = setup({ dry: DRY_RUN_RESET })
    await user.click(screen.getByRole('button', { name: 'Start over' }))
    const d = await dialog()
    expect(d.getByText('This cannot be undone.')).toBeInTheDocument()
    for (const x of DRY_RUN_RESET.deletes) expect(d.getByText(x.say as string, { exact: false })).toBeInTheDocument()
    for (const x of DRY_RUN_RESET.keeps) expect(d.getByText(x.say as string, { exact: false })).toBeInTheDocument()
    expect(d.getByText(/These 4 approvals will be lost/)).toBeInTheDocument()
    for (const k of DRY_RUN_RESET.approvals_lost) expect(d.getByText(k)).toBeInTheDocument()
    expect(d.getByText(/about 5 minutes/)).toBeInTheDocument()

    const ok = d.getByRole('button', { name: 'Start over' })
    expect(ok).toBeDisabled()
    await user.type(d.getByLabelText('Type the study id to confirm'), 'DTXSID5046932')
    expect(ok).toBeDisabled()
    expect(d.getByText("That is not this study's id.")).toBeInTheDocument()
    await user.type(d.getByLabelText('Type the study id to confirm'), '0')
    expect(ok).toBeEnabled()
    await user.click(ok)
    await waitFor(() => expect(perform).toHaveBeenCalledWith({}))
  })

  it('does nothing when cancelled', async () => {
    const { user, perform } = setup({ dry: DRY_RUN_RESET })
    await user.click(screen.getByRole('button', { name: 'Start over' }))
    await user.click((await dialog()).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(perform).not.toHaveBeenCalled()
  })

  it('treats a strength it does not know as irreversible', async () => {
    const { user } = setup({ dry: { ...DRY_RUN_CLEAR_FILES, strength: 'catastrophic' as DryRun['strength'] } })
    await user.click(screen.getByRole('button', { name: 'Start over' }))
    const d = await dialog()
    expect(d.getByLabelText('Type the study id to confirm')).toBeInTheDocument()
  })

  it('keeps a refusal inside the dialog, in plain words', async () => {
    const perform = vi.fn(() => Promise.reject(new ApiError(REFUSAL_PHASE_NOT_ALLOWED.error)))
    const { user } = setup({ dry: DRY_RUN_RESET, perform })
    await user.click(screen.getByRole('button', { name: 'Start over' }))
    const d = await dialog()
    await user.type(d.getByLabelText('Type the study id to confirm'), ID)
    await user.click(d.getByRole('button', { name: 'Start over' }))
    expect(await d.findByText(REFUSAL_PHASE_NOT_ALLOWED.error.say)).toBeInTheDocument()
  })
})

describe('<ConfirmAct>, costly', () => {
  it('asks in a dialog without the study id', async () => {
    const { user, perform } = setup({ dry: DRY_RUN_CLEAR_FILES, label: 'Remove all files' })
    await user.click(screen.getByRole('button', { name: 'Remove all files' }))
    const d = await dialog()
    expect(d.queryByLabelText('Type the study id to confirm')).not.toBeInTheDocument()
    expect(d.getByText(/every data file brought in/)).toBeInTheDocument()
    await user.click(d.getByRole('button', { name: 'Remove all files' }))
    await waitFor(() => expect(perform).toHaveBeenCalledTimes(1))
  })
})

describe('<ConfirmAct>, reversible', () => {
  it('acts at once and offers Undo', async () => {
    const undo = vi.fn(() => Promise.resolve({ ok: true }))
    const { user, perform } = setup({ dry: DRY_RUN_ACCEPT_SECTION, label: 'Approve', undo })
    await user.click(screen.getByRole('button', { name: 'Approve' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(perform).toHaveBeenCalledTimes(1))
    const done = await screen.findByText('Done: Approve.')
    expect(done).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(undo).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('Undone: Approve.')).toBeInTheDocument()
  })

  it('asks for a reason when the backend requires one, and sends it', async () => {
    const undo = vi.fn(() => Promise.resolve({}))
    const { user, perform } = setup({ dry: DRY_RUN_RELEASE_SECTION, label: 'Release the Summary', undo })
    await user.click(screen.getByRole('button', { name: 'Release the Summary' }))
    const d = await dialog()
    const ok = d.getByRole('button', { name: 'Release the Summary' })
    expect(ok).toBeDisabled()
    await user.type(d.getByLabelText('Reason'), '   ')
    expect(ok).toBeDisabled()
    await user.type(d.getByLabelText('Reason'), 'The design changed.')
    expect(ok).toBeEnabled()
    expect(d.getByText(/This approval will be lost/)).toBeInTheDocument()
    await user.click(ok)
    await waitFor(() => expect(perform).toHaveBeenCalledWith({ reason: 'The design changed.' }))
  })

  it('asks in a dialog when there is no way to undo', async () => {
    const { user } = setup({ dry: DRY_RUN_ACCEPT_SECTION, label: 'Approve' })
    await user.click(screen.getByRole('button', { name: 'Approve' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('shows a success that did nothing, and no Undo', async () => {
    const perform = vi.fn(() => Promise.resolve({ ok: true, noop: { code: 'already', say: 'It was already approved.' } }))
    const { user } = setup({ dry: DRY_RUN_ACCEPT_SECTION, label: 'Approve', undo: vi.fn(), perform })
    await user.click(screen.getByRole('button', { name: 'Approve' }))
    expect(await screen.findByText('It was already approved.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
  })

  it('shows a refusal under the button when the act is refused', async () => {
    const perform = vi.fn(() => Promise.reject(new ApiError(REFUSAL_PHASE_NOT_ALLOWED.error)))
    const { user } = setup({ dry: DRY_RUN_ACCEPT_SECTION, label: 'Approve', undo: vi.fn(), perform })
    await user.click(screen.getByRole('button', { name: 'Approve' }))
    expect(await screen.findByText(REFUSAL_PHASE_NOT_ALLOWED.error.say)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled()
  })
})

describe('<ConfirmAct>, the dry run', () => {
  it('reads it from the backend by default', async () => {
    const { user } = setup({ act: 'clear_files', label: 'Remove all files' })
    await user.click(screen.getByRole('button', { name: 'Remove all files' }))
    expect(await (await dialog()).findByText(/every data file brought in/)).toBeInTheDocument()
  })

  it('does not offer the act when the dry run cannot be had', async () => {
    server.use(http.get('/api/v2/studies/:id/dry-run/:act', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })))
    const { user, perform } = setup({ act: 'clear_files', label: 'Remove all files' })
    await user.click(screen.getByRole('button', { name: 'Remove all files' }))
    expect(await screen.findByText('"Remove all files" was not done')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(perform).not.toHaveBeenCalled()
  })

  it('is closed, with the reason, when the act is not allowed', () => {
    setup({ dry: DRY_RUN_RESET, disabled: true, disabledReason: 'Start over is not possible while the study is being processed.' })
    expect(screen.getByRole('button', { name: 'Start over' })).toBeDisabled()
    expect(screen.getByText(/not possible while the study is being processed/)).toBeInTheDocument()
  })
})
