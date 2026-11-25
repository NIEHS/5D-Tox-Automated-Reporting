import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { API_V2 } from '../../api/client'
import { FILES_BY_ID } from '../../api/mocks/m2'
import { server } from '../../api/mocks/node'
import { renderApp } from '../../test/render'

/**
 * Bringing a study's data files in, and checking them (M2's two acts).
 *
 * The plan is the backend's: these tests assert that what it says reaches the
 * page, that a batch waiting on an answer brings nothing in until the answer
 * is given, and that nothing is sent before a person asks for it.
 */

const EMPTY = 'DTXSID9000001'
const CHECKED = 'DTXSID6020430_rat'
const REPORT = 'DTXSID6020430'

function file(name: string, content = 'Dose\tBody Weight\n0\t188.1\n') {
  return new File([content], name, { type: 'text/plain' })
}

/** The fixture a study answers with; a missing one is the test's own mistake. */
function served(id: string) {
  const view = FILES_BY_ID[id]
  if (!view) throw new Error(`no fixture for ${id}`)
  return view
}

async function open(id: string) {
  renderApp(`/studies/${id}/files`)
  return screen.findByRole('heading', { level: 3, name: 'Study files' })
}

/** The dialog behind antd's dropzone; dropping gives the same input. */
function chooser() {
  const input = document.querySelector<HTMLInputElement>('[data-testid="bring-in"] input[type="file"]')
  if (!input) throw new Error('the page offers no way to choose files')
  return input
}

describe('bringing files in', () => {
  it('offers both a dialog and a drop, and sends nothing until asked', async () => {
    await open(EMPTY)
    const dropzone = await screen.findByTestId('dropzone')

    expect(dropzone).toHaveTextContent('Drop the study’s data files here, or click to choose them')
    expect(chooser().multiple).toBe(true)
    expect(await screen.findByTestId('bring-in-send')).toBeDisabled()

    await userEvent.upload(chooser(), [file('body_weight.txt'), file('organ_weights.txt')])

    expect(await screen.findByText('2 files chosen.')).toBeInTheDocument()
    expect(screen.getByTestId('bring-in-send')).toBeEnabled()
    // Chosen is not sent: nothing of the batch has reached the study.
    expect(screen.queryByTestId('plan')).not.toBeInTheDocument()
  })

  it('sends every file chosen, and shows the server’s row for each', async () => {
    // jsdom's FormData hands the receiving side a nameless blob, so the names
    // cannot be read back here; that the server reads the name it was sent is
    // covered in tests/unit/test_files_acts.py.
    const parts: number[] = []
    server.use(
      http.post(`${API_V2}/studies/:id/files`, async ({ request }) => {
        const form = await request.formData()
        parts.push(form.getAll('files').length)
        return HttpResponse.json({
          id: EMPTY,
          applied: true,
          dry_run: false,
          rows: [
            {
              name: 'body_weight.txt',
              size: 30,
              type: 'txt',
              verdict: 'add',
              say: 'Will be added.',
              code: null,
              needs_answer: null,
              from_zip: null,
              pairs_with: null,
              replaces: null,
              copy_of: null,
            },
          ],
          counts: { add: 1, unchanged: 0, refused: 0, left_out: 0, needs_answer: 0 },
          brought_in: ['body_weight.txt'],
          replaced: [],
          files_token: 'sha256:after',
        })
      }),
    )
    await open(EMPTY)
    await screen.findByTestId('dropzone')
    await userEvent.upload(chooser(), [file('body_weight.txt'), file('organ_weights.txt')])
    await userEvent.click(screen.getByTestId('bring-in-send'))

    expect(await screen.findByTestId('brought-in')).toHaveTextContent(
      '1 file brought into the study.',
    )
    await waitFor(() => expect(parts).toEqual([2]))

    // Each row is the server's own: its words, not the page's.
    const plan = within(await screen.findByTestId('plan'))
    expect(plan.getByText('body_weight.txt')).toBeInTheDocument()
    expect(plan.getByText('Will be added.')).toBeInTheDocument()
  })

  it('brings nothing in while one file waits on an answer, and says why', async () => {
    server.use(
      http.post(`${API_V2}/studies/:id/files`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'answer_required',
              status: 409,
              message: '1 rows need an answer',
              say: '1 of the files sent need an answer before any of them is brought in: the batch is one act. Nothing was brought in.',
              fix: 'M2',
              details: {
                count: 1,
                rows: [
                  {
                    name: 'body_weight.txt',
                    size: 30,
                    type: 'txt',
                    verdict: 'replace',
                    say: 'Replaces body_weight.txt, already in the study. The old one is kept among the removed files.',
                    code: null,
                    needs_answer: 'replace',
                    from_zip: null,
                    pairs_with: null,
                    replaces: { name: 'body_weight.txt', size: 28 },
                    copy_of: null,
                  },
                ],
              },
            },
          },
          { status: 409 },
        ),
      ),
    )
    await open(EMPTY)
    await screen.findByTestId('dropzone')
    await userEvent.upload(chooser(), [file('body_weight.txt')])
    await userEvent.click(screen.getByTestId('bring-in-send'))

    expect(await screen.findByTestId('answer-required')).toHaveTextContent('the batch is one act')
    const answer = await screen.findByTestId('answer-body_weight.txt')
    expect(answer).toHaveTextContent('Replace the file already in the study')
    expect(answer).toHaveTextContent('The old one is kept among the removed files.')
    expect(screen.queryByTestId('brought-in')).not.toBeInTheDocument()
  })

  it('sends the answer with the same batch when it is ticked', async () => {
    const sent: unknown[] = []
    let first = true
    server.use(
      http.post(`${API_V2}/studies/:id/files`, async ({ request }) => {
        const form = await request.formData()
        sent.push(form.get('answers'))
        if (first) {
          first = false
          return HttpResponse.json(
            {
              error: {
                code: 'answer_required',
                status: 409,
                message: '1 rows need an answer',
                say: 'needs an answer',
                fix: 'M2',
                details: {
                  rows: [
                    {
                      name: 'body_weight.txt',
                      size: 30,
                      type: 'txt',
                      verdict: 'replace',
                      say: 'Replaces body_weight.txt.',
                      code: null,
                      needs_answer: 'replace',
                      from_zip: null,
                      pairs_with: null,
                      replaces: { name: 'body_weight.txt', size: 28 },
                      copy_of: null,
                    },
                  ],
                },
              },
            },
            { status: 409 },
          )
        }
        return HttpResponse.json({
          id: EMPTY,
          applied: true,
          dry_run: false,
          rows: [],
          counts: { add: 1, unchanged: 0, refused: 0, left_out: 0, needs_answer: 0 },
          brought_in: ['body_weight.txt'],
          replaced: ['body_weight.txt'],
          files_token: 'sha256:after',
        })
      }),
    )
    await open(EMPTY)
    await screen.findByTestId('dropzone')
    await userEvent.upload(chooser(), [file('body_weight.txt')])
    await userEvent.click(screen.getByTestId('bring-in-send'))

    await userEvent.click(within(await screen.findByTestId('answer-body_weight.txt')).getByRole('checkbox'))
    await userEvent.click(screen.getByTestId('bring-in-send'))

    expect(await screen.findByTestId('brought-in')).toHaveTextContent('1 file replaced.')
    await waitFor(() => expect(sent).toHaveLength(2))
    expect(JSON.parse(String(sent[1]))).toEqual({
      replace: ['body_weight.txt'],
      copy_anyway: [],
      without_units: [],
    })
  })

  it('shows a refusal in the backend’s words, having brought nothing in', async () => {
    server.use(
      http.post(`${API_V2}/studies/:id/files`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'batch_refused',
              status: 400,
              message: 'nothing in the batch could be brought in',
              say: 'None of the 1 files sent can be brought into a study. Nothing was brought in.',
              fix: 'M2',
              details: {},
            },
          },
          { status: 400 },
        ),
      ),
    )
    await open(EMPTY)
    await screen.findByTestId('dropzone')
    await userEvent.upload(chooser(), [file('notes.pdf')])
    await userEvent.click(screen.getByTestId('bring-in-send'))

    expect(
      await screen.findByText('None of the 1 files sent can be brought into a study. Nothing was brought in.'),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('brought-in')).not.toBeInTheDocument()
  })

  it('offers no dropzone where the backend does not allow the act', async () => {
    const view = FILES_BY_ID[CHECKED]!
    server.use(
      http.get(`${API_V2}/studies/:id/files`, () =>
        HttpResponse.json({
          ...view,
          acts: {
            ...view.acts,
            add: { allowed: false, code: 'phase_not_allowed', say: 'Files cannot be brought in now (the data is approved).' },
          },
        }),
      ),
    )
    await open(CHECKED)
    expect(await screen.findByTestId('bring-in-not-allowed')).toHaveTextContent(
      'Files cannot be brought in now (the data is approved).',
    )
    expect(screen.queryByTestId('dropzone')).not.toBeInTheDocument()
  })

  it('offers nothing at all to a study whose data is not its own', async () => {
    await open(REPORT)
    await screen.findByTestId('takes-no-files')
    expect(screen.queryByTestId('bring-in')).not.toBeInTheDocument()
  })
})

describe('checking the files', () => {
  it('runs the check as a told act and sums up what it found', async () => {
    await open(CHECKED)
    await userEvent.click(await screen.findByTestId('check-run'))

    expect(await screen.findByTestId('check-ran')).toHaveTextContent(
      '9 files checked. Nothing blocks.',
    )
  })

  it('does not offer the check where the backend does not allow it', async () => {
    await open(EMPTY)
    expect(await screen.findByTestId('check-run')).toBeDisabled()
  })
})

describe('taking a file out', () => {
  it('shows what would go with it before anything goes', async () => {
    await open(CHECKED)
    const view = served(CHECKED)
    const row = view.files[0]!

    await userEvent.click(await screen.findByTestId(`remove-${row.name}`))

    // The dry run is fetched when the person clicks, so the list arrives after.
    const dialog = within(await screen.findByRole('dialog'))
    expect(await dialog.findByText(new RegExp(`${row.name} .* the data file`))).toBeInTheDocument()
    expect(await dialog.findByText(/the units of its measurements/)).toBeInTheDocument()
    expect(await dialog.findByText(/kept among the study.s removed files/)).toBeInTheDocument()
  })

  it('does not offer the act where the backend does not allow it', async () => {
    const view = served(CHECKED)
    server.use(
      http.get(`${API_V2}/studies/:id/files`, () =>
        HttpResponse.json({
          ...view,
          files: view.files.map((f) => ({
            ...f,
            acts: {
              ...f.acts,
              remove: {
                allowed: false,
                code: 'phase_not_allowed',
                say: 'A file cannot be removed now (the data is approved).',
              },
            },
          })),
        }),
      ),
    )
    await open(CHECKED)
    const row = view.files[0]!
    expect(await screen.findByTestId(`remove-${row.name}`)).toBeDisabled()
  })
})

describe('what a BMDExpress project is of', () => {
  it('says where the reading came from, and never passes silence for agreement', async () => {
    await open(CHECKED)
    const view = served(CHECKED)
    const project = view.files.find((f) => f.bm2)!

    // The row's detail is behind the expander.
    const table = within(await screen.findByTestId('files'))
    const rows = table.getAllByRole('row')
    const found = rows.find((r) => within(r).queryByText(project.name))!
    await userEvent.click(within(found).getByRole('button', { expanded: false }))

    expect(await screen.findByText('Test article not established')).toBeInTheDocument()
    expect(await screen.findByTestId(`of-${project.name}`)).toHaveTextContent(
      'carry no test article, so the application cannot tell what this project is of',
    )
  })
})
