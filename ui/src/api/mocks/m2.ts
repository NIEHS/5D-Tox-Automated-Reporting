import { HttpResponse, http } from 'msw'
import { API_V2 } from '../client'
import type { FilesView } from '../files'
import type { ErrorEnvelope } from '../types'
import FILES_CHECKED from './fixtures/m2/files.checked.json'
import FILES_EMPTY from './fixtures/m2/files.empty.json'
import FILES_REPORT from './fixtures/m2/files.report.json'

/**
 * The Study files page (M2). The answers are real ones, taken from the backend
 * on a real study: a checked study, a report over several studies (whose data
 * is its studies', so it takes no files), and a study with nothing in it yet.
 */

const SESSION_ID = /^DTXSID[A-Za-z0-9_-]{1,64}$/

export const FILES_BY_ID: Record<string, FilesView> = {
  DTXSID6020430_rat: FILES_CHECKED,
  DTXSID6020430: FILES_REPORT,
  DTXSID9000001: FILES_EMPTY,
}

function envelope(code: string, status: number, say: string, message: string): Response {
  const body: ErrorEnvelope = { error: { code, status, message, say, fix: 'M2', details: {} } }
  return HttpResponse.json(body, { status })
}

export function createM2Handlers() {
  return [
    http.get(`${API_V2}/studies/:id/files`, ({ params }) => {
      const id = String(params.id)
      if (!SESSION_ID.test(id)) {
        return envelope(
          'invalid_study_id',
          400,
          'That is not a valid study id. A study is named by its chemical’s DTXSID.',
          `invalid dtxsid: ${id}`,
        )
      }
      const view = FILES_BY_ID[id]
      if (!view) {
        return envelope(
          'study_not_found',
          404,
          `There is no study ${id}. It may have been deleted.`,
          `no session ${id}`,
        )
      }
      return HttpResponse.json(view)
    }),

    // Bringing a batch in: the plan is the server's, so the mock answers with
    // one row per file sent, all of them brought in.
    http.post(`${API_V2}/studies/:id/files`, async ({ request, params }) => {
      const form = await request.formData()
      const sent = form.getAll('files').filter((one): one is File => typeof one !== 'string')
      const rows = sent.map((file) => ({
        name: file.name,
        size: file.size,
        type: file.name.split('.').pop() ?? '',
        verdict: 'add',
        say: 'Will be added.',
        code: null,
        needs_answer: null,
        from_zip: null,
        pairs_with: null,
        replaces: null,
        copy_of: null,
      }))
      return HttpResponse.json({
        id: String(params.id),
        applied: true,
        dry_run: false,
        rows,
        counts: { add: rows.length, unchanged: 0, refused: 0, left_out: 0, needs_answer: 0 },
        brought_in: rows.map((row) => row.name),
        replaced: [],
        files_token: 'sha256:after-the-batch',
      })
    }),

    // What taking one file out would cost, and doing it.
    http.get(`${API_V2}/studies/:id/files/:name/removal-preview`, ({ params }) => {
      const name = String(params.name)
      return HttpResponse.json({
        id: String(params.id),
        file: name,
        companions: [{ name: `${name}.units.json`, say: 'the units of its measurements' }],
        size: 4096,
        invalidates: false,
        kept: true,
        say: `${name} and 1 file written beside it would be taken out of the study.`,
        kept_say:
          "Nothing is deleted: the files are kept among the study's removed files, where they can be found again.",
        invalidates_say: null,
      })
    }),

    http.post(`${API_V2}/studies/:id/files/:name/remove`, ({ params }) => {
      const name = String(params.name)
      return HttpResponse.json({
        id: String(params.id),
        file: name,
        removed: [name, `${name}.units.json`],
        say: `${name} was taken out of the study, with 1 file written beside it.`,
        kept_say: "The files are kept among the study's removed files.",
        files_token: 'sha256:after-the-removal',
      })
    }),

    http.post(`${API_V2}/studies/:id/check`, () =>
      HttpResponse.text(
        [
          JSON.stringify({ event: 'step', unit: 'check', status: 'computing', say: 'Checking the study’s files' }),
          JSON.stringify({ event: 'step', unit: 'check', status: 'done', say: 'Checking the study’s files', ms: 2100 }),
          JSON.stringify({ event: 'result', ok: true, summary: { files: 9, fix: 0, look: 2, expected: 3 } }),
        ].join('\n') + '\n',
        { headers: { 'Content-Type': 'application/x-ndjson' } },
      ),
    ),
  ]
}
