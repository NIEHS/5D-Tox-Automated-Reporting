import { screen, within } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../../api/mocks/node'
import { renderApp } from '../../test/render'
import { API_V2 } from '../../api/client'
import { FILES_BY_ID } from '../../api/mocks/m2'

/**
 * The Study files page (M2). Everything it shows is the backend's answer: the
 * tests assert against the fixture, which is a real answer from a real study,
 * rather than against prose written twice.
 */

const CHECKED = 'DTXSID6020430_rat'
const REPORT = 'DTXSID6020430'
const EMPTY = 'DTXSID9000001'

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

describe('the study’s files', () => {
  it('shows one row per file a person brought in', async () => {
    await open(CHECKED)
    const view = served(CHECKED)
    const table = within(await screen.findByTestId('files'))

    expect(await screen.findByText(`The study’s files (${view.files.length})`)).toBeInTheDocument()
    for (const row of view.files) {
      expect(table.getByText(row.name)).toBeInTheDocument()
    }
  })

  it('says what each file is taken to be, and on whose word', async () => {
    await open(CHECKED)
    const view = served(CHECKED)
    const row = view.files[0]!
    await screen.findByTestId('files')

    expect(screen.getAllByText(row.classification.say).length).toBeGreaterThan(0)
    // Nothing passes as confirmed by default.
    expect(await screen.findByTestId(`mark-${row.name}`)).toHaveTextContent(
      'Recognized, not confirmed',
    )
  })

  it('tells an empty study to bring its files in', async () => {
    await open(EMPTY)
    expect(await screen.findByText('No files yet.')).toBeInTheDocument()
    expect(await screen.findByTestId('next')).toHaveTextContent("Bring in the study's files")
  })
})

describe('the file check', () => {
  it('sums up what it found, and groups the findings', async () => {
    await open(CHECKED)
    const view = served(CHECKED)
    const counts = view.check!.counts

    expect(await screen.findByTestId('check-summary')).toHaveTextContent('Nothing blocks')
    const findings = within(await screen.findByTestId('findings'))
    expect(findings.getByText(`Worth a look (${counts.look})`)).toBeInTheDocument()
    expect(
      findings.getByText(`Expected for this kind of package (${counts.expected})`),
    ).toBeInTheDocument()
  })

  it('says each finding in plain words, naming no file id', async () => {
    await open(CHECKED)
    const view = served(CHECKED)
    const worth = view.issues.find((one) => one.group === 'look')!

    const found = await screen.findByTestId(`finding-${worth.id}`)
    expect(found).toHaveTextContent(worth.say)
    expect(found.textContent ?? '').not.toContain('scan-')
  })

  it('says when a problem must be fixed before anything is combined', async () => {
    const view = served(CHECKED)
    server.use(
      http.get(`${API_V2}/studies/:id/files`, () =>
        HttpResponse.json({
          ...view,
          check: { ...view.check, counts: { fix: 2, look: 0, expected: 0 } },
        }),
      ),
    )
    await open(CHECKED)
    expect(await screen.findByTestId('check-summary')).toHaveTextContent(
      '2 problems must be fixed before the files can be combined.',
    )
  })

  it('warns when the files changed after the check ran', async () => {
    const view = served(CHECKED)
    server.use(
      http.get(`${API_V2}/studies/:id/files`, () =>
        HttpResponse.json({
          ...view,
          check: {
            ...view.check,
            current: false,
            why_not_current: 'organ_weights.xlsx came into the study after the check ran.',
          },
        }),
      ),
    )
    await open(CHECKED)
    expect(await screen.findByTestId('check-stale')).toHaveTextContent(
      'organ_weights.xlsx came into the study after the check ran.',
    )
  })

  it('says a check has not run yet rather than showing an empty result', async () => {
    const view = served(CHECKED)
    server.use(
      http.get(`${API_V2}/studies/:id/files`, () =>
        HttpResponse.json({ ...view, check: null, issues: [] }),
      ),
    )
    await open(CHECKED)
    expect(await screen.findByTestId('check-not-run')).toHaveTextContent('Not checked yet.')
  })
})

describe('what the report would be built from', () => {
  it('lists each assay with the files behind it', async () => {
    await open(CHECKED)
    const view = served(CHECKED)
    const coverage = within(await screen.findByTestId('coverage'))

    for (const row of view.coverage) {
      expect(coverage.getAllByText(row.assay).length).toBeGreaterThan(0)
    }
  })
})

describe('a study whose data is not its own', () => {
  it('says so, and offers nothing', async () => {
    await open(REPORT)
    const view = served(REPORT)

    expect(await screen.findByTestId('takes-no-files')).toHaveTextContent(
      view.takes_files.say as string,
    )
    expect(screen.queryByTestId('files')).not.toBeInTheDocument()
    expect(screen.queryByTestId('check')).not.toBeInTheDocument()
  })
})

describe('files that cannot be read', () => {
  it('shows the backend’s refusal in its own words, not a blank page', async () => {
    server.use(
      http.get(`${API_V2}/studies/:id/files`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'damaged_session_file',
              status: 422,
              message: 'validation_report.json is not valid JSON',
              say: 'A file this study keeps is damaged and cannot be read.',
              fix: 'M2',
              details: {},
            },
          },
          { status: 422 },
        ),
      ),
    )
    renderApp(`/studies/${CHECKED}/files`)
    const refusal = await screen.findByText(
      'A file this study keeps is damaged and cannot be read.',
    )
    expect(refusal).toBeInTheDocument()
    expect(screen.queryByTestId('files')).not.toBeInTheDocument()
  })
})

describe('what the page does not do yet', () => {
  it('names the acts that are not built, rather than offering one that would refuse', async () => {
    await open(CHECKED)
    const said = await screen.findByTestId('acts-not-built')
    expect(said).toHaveTextContent('Saying what a file is, is not built on this page yet')
    expect(said).toHaveTextContent('Bringing files in and checking them are done here.')
  })
})
